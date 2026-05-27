"""Phase resolution for stuck flights.

Separates the decision logic (what should happen to a stuck flight) from
the side effects (mutating state, releasing gates/runways, recording events).
This makes stuck-flight resolution testable without a full SimulationEngine.
"""

import random
from dataclasses import dataclass, field
from typing import Optional

from src.ingestion._state import FlightPhase, FlightState
from src.simulation.capacity import CapacityManager


@dataclass
class PhaseResolution:
    """Describes what should happen to a stuck flight.

    The engine reads this and applies the mutations + side effects.
    Pure data — no side effects in this object.
    """

    new_phase: Optional[FlightPhase] = None
    state_mutations: dict = field(default_factory=dict)
    gate_release: Optional[str] = None
    gate_assign: Optional[str] = None
    runway_release: Optional[str] = None
    runway_occupy: Optional[str] = None
    divert_to: Optional[str] = None
    reset_phase_time: Optional[str] = None
    phase_time_value: float = 0.0
    event_type: Optional[str] = None
    event_description: str = ""
    event_data: dict = field(default_factory=dict)
    snap_to_gate: bool = False
    snap_to_hold_line: bool = False
    force_approach: bool = False
    mark_exit: bool = False


class PhaseResolver:
    """Resolves stuck flights by determining what phase transition to make.

    Subclass and override individual resolve_* methods to customize behavior.
    """

    def __init__(
        self,
        capacity: CapacityManager,
        airport_code: str,
        alternate_airports: Optional[dict] = None,
    ) -> None:
        self.capacity = capacity
        self.airport_code = airport_code
        self.alternate_airports = alternate_airports or {}

    def resolve(
        self,
        icao24: str,
        state: FlightState,
        phase_time: float,
    ) -> PhaseResolution:
        """Determine what to do with a stuck flight. Pure decision logic."""
        phase = state.phase

        if phase == FlightPhase.TAXI_TO_GATE:
            return self.resolve_taxi_to_gate(icao24, state)
        elif phase == FlightPhase.TAXI_TO_RUNWAY:
            return self.resolve_taxi_to_runway(icao24, state)
        elif phase == FlightPhase.PUSHBACK:
            return self.resolve_pushback(icao24, state)
        elif phase == FlightPhase.APPROACHING:
            return self.resolve_approaching(icao24, state)
        elif phase == FlightPhase.LANDING:
            return self.resolve_landing(icao24, state)
        elif phase == FlightPhase.ENROUTE:
            return self.resolve_enroute(icao24, state)

        return PhaseResolution()

    def resolve_taxi_to_gate(self, icao24: str, state: FlightState) -> PhaseResolution:
        """Snap aircraft to gate position, transition to PARKED."""
        return PhaseResolution(
            new_phase=FlightPhase.PARKED,
            state_mutations={
                "velocity": 0,
                "time_at_gate": 0,
            },
            snap_to_gate=True,
            reset_phase_time="parked",
        )

    def resolve_taxi_to_runway(self, icao24: str, state: FlightState) -> PhaseResolution:
        """Either snap to hold line (first timeout) or force takeoff (second timeout)."""
        from src.ingestion.fallback import TAXI_WAYPOINTS_DEPARTURE
        taxi_wps = state.taxi_route or TAXI_WAYPOINTS_DEPARTURE
        already_at_hold = state.waypoint_index >= len(taxi_wps)

        if already_at_hold:
            return PhaseResolution(
                new_phase=FlightPhase.TAKEOFF,
                state_mutations={
                    "takeoff_subphase": "lineup",
                    "velocity": 0,
                    "phase_progress": 0.0,
                    "takeoff_roll_dist_ft": 0.0,
                },
                reset_phase_time="takeoff",
            )
        else:
            return PhaseResolution(
                new_phase=None,  # stays in same phase
                state_mutations={
                    "departure_queue_hold_s": 0,
                    "departure_queue_set": True,
                    "velocity": 0,
                },
                snap_to_hold_line=True,
                reset_phase_time="taxi_to_runway",
            )

    def resolve_pushback(self, icao24: str, state: FlightState) -> PhaseResolution:
        """Finish pushback, move to taxi."""
        return PhaseResolution(
            new_phase=FlightPhase.TAXI_TO_RUNWAY,
            state_mutations={"waypoint_index": 0},
            gate_release=state.assigned_gate,
            reset_phase_time="taxi_to_runway",
        )

    def resolve_approaching(self, icao24: str, state: FlightState) -> PhaseResolution:
        """Handle stuck approach: force-land to clear the sequence."""
        from src.ingestion.fallback import (
            _is_runway_clear, _get_arrival_runway_name,
        )
        from src.ingestion._runway_ops import _is_runway_scenario_open

        arr_rwy = _get_arrival_runway_name()

        if not _is_runway_scenario_open(arr_rwy):
            return self._diversion_resolution(icao24, state)

        if not _is_runway_clear(arr_rwy) and state.go_around_count < 2:
            return PhaseResolution(reset_phase_time="approaching", phase_time_value=600.0)

        return PhaseResolution(
            new_phase=FlightPhase.LANDING,
            state_mutations={"waypoint_index": 0, "altitude": 200.0},
            runway_occupy=arr_rwy,
            reset_phase_time="landing",
        )

    def resolve_landing(self, icao24: str, state: FlightState) -> PhaseResolution:
        """Force transition from landing to taxi_to_gate."""
        return PhaseResolution(
            new_phase=FlightPhase.TAXI_TO_GATE,
            state_mutations={
                "altitude": 0,
                "on_ground": True,
            },
            runway_release=icao24,
            reset_phase_time="taxi_to_gate",
        )

    def resolve_enroute(self, icao24: str, state: FlightState) -> PhaseResolution:
        """Handle stuck holding: divert or force approach."""
        from src.ingestion._runway_ops import _is_runway_scenario_open
        from src.ingestion.fallback import _get_arrival_runway_name

        is_arriving = (
            (state.origin_airport and not state.destination_airport)
            or (state.destination_airport == self.airport_code)
        )

        if not is_arriving:
            return PhaseResolution(mark_exit=True)

        arr_rwy = _get_arrival_runway_name()
        if state.go_around_count >= 3:
            return self._diversion_resolution(icao24, state)
        if state.go_around_count >= 2 and not _is_runway_scenario_open(arr_rwy):
            return self._diversion_resolution(icao24, state)

        if state.altitude > 5000:
            return PhaseResolution(
                state_mutations={"altitude": max(state.altitude - 2000, 5000)},
                reset_phase_time="enroute",
            )

        # Force transition to approach
        return PhaseResolution(
            new_phase=FlightPhase.APPROACHING,
            state_mutations={"go_around_count": state.go_around_count + 1},
            force_approach=True,
            reset_phase_time="approaching",
        )

    def _go_around_resolution(
        self, icao24: str, state: FlightState, reason: str,
    ) -> PhaseResolution:
        """Build a go-around resolution."""
        from src.ingestion.fallback import VREF_SPEEDS

        new_go_around_count = state.go_around_count + 1
        vref_ga = VREF_SPEEDS.get(state.aircraft_type, 137)

        mutations = {
            "waypoint_index": 0,
            "go_around_target_alt": max(1500.0, state.altitude + 300),
            "vertical_rate": 1500,
            "go_around_count": new_go_around_count,
            "holding_phase_time": 0.0,
            "holding_inbound": True,
        }
        if reason == "weather":
            mutations["velocity"] = min(state.velocity + 10, vref_ga + 20)

        resolution = PhaseResolution(
            new_phase=FlightPhase.ENROUTE,
            state_mutations=mutations,
            reset_phase_time="enroute",
            event_type="go_around",
            event_description=f"{state.callsign} go-around #{new_go_around_count} ({reason})",
            event_data={
                "callsign": state.callsign, "icao24": icao24,
                "attempt": new_go_around_count, "reason": reason,
                "altitude_ft": round(state.altitude),
                "speed_kts": round(state.velocity),
                "aircraft_type": state.aircraft_type,
                "weather_category": self.capacity.current_category,
            },
        )

        if new_go_around_count >= 3:
            resolution.divert_to = self._pick_alternate()

        return resolution

    def _diversion_resolution(self, icao24: str, state: FlightState) -> PhaseResolution:
        """Build a diversion resolution."""
        alt_name = self._pick_alternate()
        return PhaseResolution(
            new_phase=FlightPhase.ENROUTE,
            state_mutations={
                "altitude": max(state.altitude, 3000),
                "velocity": 250,
                "vertical_rate": 1500,
                "go_around_count": 0,
                "destination_airport": alt_name,
            },
            gate_release=state.assigned_gate,
            divert_to=alt_name,
            reset_phase_time="enroute",
            event_type="diversion",
            event_description=f"{state.callsign} diverted to {alt_name}",
            event_data={
                "callsign": state.callsign, "icao24": icao24, "alternate": alt_name,
                "altitude_ft": round(state.altitude),
                "aircraft_type": state.aircraft_type,
                "prior_go_arounds": state.go_around_count,
                "weather_category": self.capacity.current_category,
            },
        )

    def _pick_alternate(self) -> str:
        alternates = self.alternate_airports.get(self.airport_code, [])
        return random.choice(alternates) if alternates else "alternate"

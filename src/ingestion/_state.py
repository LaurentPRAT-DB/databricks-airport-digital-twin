"""Shared mutable state for the synthetic flight system.

This module owns all global state containers that multiple sub-modules
read and write. Extracted from fallback.py to make dependencies explicit.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set


class FlightPhase(Enum):
    """Flight operational phases."""
    APPROACHING = "approaching"    # Descending toward airport
    LANDING = "landing"           # Final approach and touchdown
    TAXI_TO_GATE = "taxi_to_gate" # Taxiing from runway to gate
    PARKED = "parked"             # At gate
    PUSHBACK = "pushback"         # Pushing back from gate
    TAXI_TO_RUNWAY = "taxi_to_runway"  # Taxiing to departure runway
    TAKEOFF = "takeoff"           # Takeoff roll and initial climb
    DEPARTING = "departing"       # Climbing out
    ENROUTE = "enroute"           # Cruising at altitude


@dataclass
class FlightState:
    """Persistent state for a synthetic flight."""
    icao24: str
    callsign: str
    latitude: float
    longitude: float
    altitude: float  # feet
    velocity: float  # knots
    heading: float   # degrees
    vertical_rate: float  # ft/min
    on_ground: bool
    phase: FlightPhase
    aircraft_type: str = "A320"  # ICAO aircraft type code
    assigned_gate: Optional[str] = None
    waypoint_index: int = 0
    phase_progress: float = 0.0  # 0-1 progress through current phase
    time_at_gate: float = 0.0    # seconds parked
    origin_airport: Optional[str] = None      # IATA code of origin
    destination_airport: Optional[str] = None  # IATA code of destination
    taxi_route: Optional[List] = None          # Cached taxi waypoints [(lon, lat), ...]
    takeoff_subphase: str = "lineup"           # lineup/roll/rotate/liftoff/initial_climb
    takeoff_roll_dist_ft: float = 0.0          # Accumulated ground roll distance in feet
    holding_phase_time: float = 0.0            # Elapsed time in current holding leg (seconds)
    holding_inbound: bool = True               # True = inbound leg, False = outbound leg
    go_around_count: int = 0                   # Number of go-arounds for this approach
    go_around_target_alt: float = 0.0           # Target altitude for current go-around climb
    gate_retry_at: float = 0.0                 # time.time() when to next retry gate assignment
    landed_at: float = 0.0                     # time.time() when aircraft touched down (LANDING → TAXI_TO_GATE)
    parked_since: float = 0.0                  # time.time() when aircraft entered PARKED phase
    turnaround_phase: str = ""                 # Current turnaround sub-phase (e.g. "deboarding")
    turnaround_schedule: Optional[Dict] = None # {phase: {"start_offset_s", "duration_s", "done", "started"}}
    departure_queue_hold_s: float = 0.0        # Remaining departure queue hold (seconds, calibrated)
    departure_queue_set: bool = False           # True once the hold has been computed
    arrival_hold_s: float = 0.0                 # Remaining arrival taxi hold (seconds, calibrated)
    arrival_hold_set: bool = False              # True once the arrival hold has been computed
    go_around_hold_until: float = 0.0           # time.time() before which aircraft cannot re-enter approach
    cruise_altitude: float = 0.0               # Target cruise FL (hemispheric rule)
    star_name: str = ""                          # Assigned STAR procedure name
    sid_name: str = ""                           # Assigned SID procedure name


# Maximum simultaneous aircraft on approach (approach + landing)
MAX_APPROACH_AIRCRAFT = 8

# Phase index — maintained automatically by _FlightStateDict and _set_phase
_flights_by_phase: Dict[FlightPhase, Set[str]] = {phase: set() for phase in FlightPhase}


class _FlightStateDict(dict):
    """Dict subclass that auto-syncs _flights_by_phase and _callsigns on insert/delete/clear."""

    _callsigns: Set[str] = set()

    def __setitem__(self, key: str, value: FlightState):
        old = self.get(key)
        if old is not None and old is not value:
            _flights_by_phase[old.phase].discard(key)
            self._callsigns.discard(old.callsign)
        super().__setitem__(key, value)
        _flights_by_phase[value.phase].add(key)
        self._callsigns.add(value.callsign)

    def __delitem__(self, key: str):
        old = self.get(key)
        if old is not None:
            _flights_by_phase[old.phase].discard(key)
            self._callsigns.discard(old.callsign)
        super().__delitem__(key)

    def clear(self):
        super().clear()
        for s in _flights_by_phase.values():
            s.clear()
        self._callsigns.clear()


# Global state storage
_flight_states: Dict[str, FlightState] = _FlightStateDict()
_last_update: float = 0.0


def _set_phase(state: FlightState, new_phase: FlightPhase):
    """Update a flight's phase and keep the _flights_by_phase index in sync."""
    old = state.phase
    if old != new_phase:
        _flights_by_phase[old].discard(state.icao24)
        _flights_by_phase[new_phase].add(state.icao24)
        state.phase = new_phase


# ── Runway & Gate State ──────────────────────────────────────────────────────

@dataclass
class RunwayState:
    """Tracks runway occupancy for separation."""
    occupied_by: Optional[str] = None  # icao24 of aircraft on runway
    last_departure_time: float = 0.0   # Timestamp of last departure
    last_arrival_time: float = 0.0     # Timestamp of last arrival
    approach_queue: List[str] = field(default_factory=list)  # Ordered approach sequence
    departure_queue: List[str] = field(default_factory=list)  # Ordered departure sequence
    last_departure_type: str = "LARGE"  # Wake category of last departure (FAA 7110.65)


# Minimum gate buffer (seconds) between consecutive occupancies.
GATE_BUFFER_SECONDS = 15 * 60  # 15 minutes

# Track gate conflicts for validation reporting
_gate_conflict_count: int = 0

# Count of currently occupied gates (synced by _recount_occupied_gates)
_occupied_gate_count: int = 0


@dataclass
class GateState:
    """Tracks gate occupancy."""
    occupied_by: Optional[str] = None  # icao24 of aircraft at gate
    available_at: float = 0.0          # When gate becomes available (epoch seconds)
    last_released: float = 0.0         # When gate was last vacated


# Global separation state — dynamic runway dict keyed by name
_runway_states: Dict[str, RunwayState] = {}
# Backward-compatible aliases for tests
_runway_28L: RunwayState = RunwayState()
_runway_28R: RunwayState = RunwayState()
_runway_states["28L"] = _runway_28L
_runway_states["28R"] = _runway_28R
_gate_states: Dict[str, GateState] = {}

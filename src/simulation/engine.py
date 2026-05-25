"""Core simulation engine — runs the flight state machine at accelerated speed."""

import logging
import random
import time as wall_time
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.ingestion._clock import set_clock, reset_clock
from src.ingestion._runway_ops import set_runway_closed, set_runway_open, clear_runway_closures

from src.simulation.config import SimulationConfig
from src.simulation.recorder import SimulationRecorder
from src.simulation.capacity import CapacityManager
from src.simulation.diagnostics import DiagnosticLogger, set_diagnostics, diag_log
from src.simulation.scenario import (
    SimulationScenario,
    ResolvedEvent,
    load_scenario,
    resolve_times,
)

# Import the flight state machine and helpers from fallback.py
import src.ingestion.fallback as _fb

from src.ingestion.fallback import (
    FlightPhase,
    FlightState,
    _create_new_flight,
    _update_flight_state,
    _init_gate_states,
    _release_gate,
    _gate_states,
    _flight_states,
    _runway_states,
    _runway_28L,
    _runway_28R,
    RunwayState,
    get_gates,
    set_airport_center,
    get_airport_center,
    CALLSIGN_PREFIXES,
    AIRLINE_FLEET,
    _count_aircraft_in_phase,
    emit_phase_transition,
    emit_gate_event,
    drain_phase_transitions,
    drain_gate_events,
    set_suppress_phase_transitions,
    _DEFAULT_GATES,
    APPROACH_WAYPOINTS,
    DEPARTURE_WAYPOINTS,
    apply_airport_offset,
    reset_airport_offset,
    set_calibration_gate_minutes,
    set_calibration_taxi_out,
    set_calibration_taxi_in,
    _get_taxi_waypoints_arrival,
    _distance_between,
    _KTS_TO_DEG_PER_SEC,
    TAXI_SPEED_STRAIGHT_KTS,
    TAXI_SPEED_RAMP_KTS,
)
from src.ingestion.schedule_generator import (
    AIRPORT_COORDINATES,
    AIRLINES,
    DOMESTIC_AIRPORTS,
    INTERNATIONAL_AIRPORTS,
    _select_airline,
    _generate_flight_number,
    _select_destination,
    _select_aircraft,
    _generate_delay,
    _get_flights_per_hour,
    set_traffic_airport,
)
from src.ml.gse_model import get_turnaround_timing, get_aircraft_category, PHASE_DEPENDENCIES
from src.ingestion.weather_generator import generate_metar
from src.ingestion.baggage_generator import generate_bags_for_flight, simulate_bhs_throughput
from src.simulation.passenger_flow import PassengerFlowModel
from src.calibration.profile import AirportProfile, AirportProfileLoader

logger = logging.getLogger(__name__)

ALTERNATE_AIRPORTS: dict[str, list[str]] = {
    "SFO": ["OAK", "SJC"],
    "JFK": ["EWR", "LGA"],
    "LHR": ["LGW", "STN"],
    "NRT": ["HND"],
    "DXB": ["AUH"],
    "GRU": ["VCP"],
    "SYD": ["MEL", "BNE"],
    "SIN": ["KUL"],
    "FRA": ["MUC", "DUS"],
    "JNB": ["CPT"],
}


def _critical_path_turnaround(aircraft_type: str) -> float:
    """Compute turnaround duration via critical-path through the phase DAG.

    Each phase gets independent ±20% jitter, then the longest path through
    the dependency graph determines total turnaround time.
    """
    timing = get_turnaround_timing(aircraft_type)
    phases = timing["phases"]

    # Apply per-phase jitter
    jittered: dict[str, float] = {}
    for phase, nominal in phases.items():
        jittered[phase] = nominal * random.uniform(0.80, 1.20)

    # Critical-path: earliest finish time per phase
    finish: dict[str, float] = {}
    for phase in phases:
        deps = PHASE_DEPENDENCIES.get(phase, [])
        earliest_start = max((finish[d] for d in deps if d in finish), default=0.0)
        finish[phase] = earliest_start + jittered[phase]

    return max(finish.values()) if finish else timing["total_minutes"]


def _calibrated_turnaround(
    aircraft_type: str,
    airline_code: str,
    profile: AirportProfile,
) -> float:
    """Compute turnaround using calibration data when available.

    Uses BTS OTP turnaround stats from the airport profile as the baseline,
    with aircraft-category and airline adjustments. Falls back to the
    critical-path DAG model when no calibration data exists.
    """
    median = profile.turnaround_median_min
    if median <= 0:
        return _critical_path_turnaround(aircraft_type)

    # Aircraft category scaling: wide-body ~1.4x narrow-body base
    category = get_aircraft_category(aircraft_type)
    if category == "wide_body":
        base = median * 1.4
    else:
        base = median

    # Airline turnaround factor (fast LCCs vs premium carriers)
    from src.ingestion.fallback import AIRLINE_TURNAROUND_FACTOR
    airline_factor = AIRLINE_TURNAROUND_FACTOR.get(airline_code, 1.0)
    base *= airline_factor

    # Add ±15% jitter to match real P25-P75 spread
    return base * random.uniform(0.85, 1.15)


class SimulationEngine:
    """Runs a deterministic, accelerated airport simulation."""

    def __init__(self, config: SimulationConfig) -> None:
        self.config = config
        self.recorder = SimulationRecorder(skip_positions=config.skip_positions)

        # Diagnostic logger
        if config.diagnostics:
            self._diag = DiagnosticLogger(enabled=True)
            set_diagnostics(self._diag)
        else:
            self._diag = None
            set_diagnostics(None)

        # Virtual clock
        self.sim_time = config.effective_start_time()
        self.end_time = self.sim_time + timedelta(hours=config.effective_duration_hours())

        # Set random seed for reproducibility
        if config.seed is not None:
            random.seed(config.seed)

        # Configure airport
        self._setup_airport()

        # Scenario + capacity
        self.scenario: SimulationScenario | None = None
        self.scenario_timeline: list[ResolvedEvent] = []
        self._scenario_event_idx = 0
        self._active_weather_event = None  # currently active weather override
        self._weather_event_expires: datetime | None = None
        self._ground_stop_expires: datetime | None = None
        # Derive runway list from scenario if it references specific runways
        runways = self._derive_runways_from_scenario(config)
        self.capacity = CapacityManager(airport=config.airport, runways=runways)
        self.capacity.configure_runway_reversal()
        self._holding_flights: set[str] = set()  # flights delayed by capacity
        self._spawn_times: dict[int, datetime] = {}  # schedule_idx -> actual spawn time

        if config.scenario_file:
            self.scenario = load_scenario(config.scenario_file)
            self.scenario_timeline = resolve_times(self.scenario, self.sim_time)
            self.recorder.scenario_name = self.scenario.name
            logger.info(
                "Loaded scenario '%s' with %d events",
                self.scenario.name,
                len(self.scenario_timeline),
            )

        # Apply curfews from scenario (static, not time-triggered)
        if self.scenario:
            for curfew in self.scenario.curfew_events:
                self.capacity.add_curfew(
                    curfew.start, curfew.end, curfew.max_arrivals_per_hour
                )
                self.recorder.record_scenario_event(
                    self.sim_time, "curfew",
                    f"Curfew active {curfew.start}-{curfew.end} (max {curfew.max_arrivals_per_hour} arr/hr)",
                    {"start": curfew.start, "end": curfew.end},
                )

        # Load calibration profile for this airport
        self._profile_loader = AirportProfileLoader()
        self.airport_profile = self._profile_loader.get_profile(config.airport)

        # Set traffic profile based on airport characteristics (derived, not hardcoded)
        has_curfew = bool(self.scenario and self.scenario.curfew_events)
        set_traffic_airport(
            config.airport,
            runway_count=len(self.capacity.all_runways),
            has_curfew=has_curfew,
        )

        # Flight state — we reuse the global state from fallback.py
        # but reset it first to get a clean simulation
        self._reset_global_state()

        # Pre-generate flight schedule
        from src.simulation.schedule_builder import ScheduleBuilder
        builder = ScheduleBuilder(config, self.airport_profile, scenario=self.scenario)
        self.flight_schedule = builder.build()
        self.recorder.schedule = self.flight_schedule

        # Phase resolver for stuck-flight recovery
        from src.simulation.phase_resolver import PhaseResolver
        self._phase_resolver = PhaseResolver(
            capacity=self.capacity,
            airport_code=config.airport,
            alternate_airports=ALTERNATE_AIRPORTS,
        )

        # Track which scheduled flights have been spawned
        self._spawned_indices: set[int] = set()
        self._spawn_scan_start: int = 0  # low-water mark for schedule scan

        # Track completed flights for baggage generation
        self._completed_flights: list[dict] = []

        # Track previous altitudes for vertical_rate computation (D04 fix)
        self._prev_altitudes: dict[str, float] = {}

        # Passenger flow model
        gate_count = len(get_gates()) if get_gates() else 40
        self._passenger_flow = PassengerFlowModel(
            gate_count=gate_count,
            seed=config.seed,
        )

        # Position snapshot interval (sim-seconds)
        self._snapshot_interval = 30.0
        self._last_snapshot_time = self.sim_time

        # Weather snapshot interval (sim-seconds)
        self._last_weather_hour = -1

        # Progress tracking
        self._last_progress_hour = -1

        # Phase elapsed time tracker: icao24 -> (phase, elapsed_seconds)
        # Used to detect and resolve stuck flights
        self._phase_time: dict[str, tuple[str, float]] = {}

        # Phase counters for O(1) phase-based queries (avoids per-tick full scans)
        self._phase_counts: dict[str, int] = {}

        # Max time in seconds before forcing phase transitions
        # Use profile-calibrated P95 taxi times when available, else defaults
        profile = self.airport_profile
        taxi_in_cap = max(600.0, profile.taxi_in_p95_min * 60) if profile.taxi_in_p95_min > 0 else 600.0
        taxi_out_cap = max(600.0, profile.taxi_out_p95_min * 60) if profile.taxi_out_p95_min > 0 else 600.0
        self._max_phase_seconds = {
            "taxi_to_gate": taxi_in_cap,
            "taxi_to_runway": taxi_out_cap,
            "pushback": 300.0,        # 5 min max pushback
            "approaching": 900.0,     # 15 min max approach
            "landing": 120.0,         # 2 min max landing
            "enroute": 600.0,         # 10 min max holding — divert or force approach
        }

    def _phase_count_inc(self, phase_value: str) -> None:
        self._phase_counts[phase_value] = self._phase_counts.get(phase_value, 0) + 1

    def _phase_count_dec(self, phase_value: str) -> None:
        self._phase_counts[phase_value] = max(0, self._phase_counts.get(phase_value, 0) - 1)

    def _phase_count_transition(self, old_phase_value: str, new_phase_value: str) -> None:
        self._phase_count_dec(old_phase_value)
        self._phase_count_inc(new_phase_value)

    @staticmethod
    def _derive_runways_from_scenario(config: SimulationConfig) -> list[str] | None:
        """Extract runway names from scenario runway_events.

        If the scenario references specific runways (closures, config changes),
        use those as the airport's runway set. Otherwise return None to let
        CapacityManager use its default.
        """
        if not config.scenario_file:
            return None
        try:
            scenario = load_scenario(config.scenario_file)
        except Exception:
            return None
        rwy_names: set[str] = set()
        for re_evt in scenario.runway_events:
            if re_evt.runway:
                rwy_names.add(re_evt.runway)
        return sorted(rwy_names) if rwy_names else None

    def _setup_airport(self) -> None:
        """Configure airport center coordinates."""
        iata = self.config.airport
        if iata in AIRPORT_COORDINATES:
            lat, lon = AIRPORT_COORDINATES[iata]
        else:
            # Default to SFO
            lat, lon = 37.6213, -122.379
        set_airport_center(lat, lon, iata)

    def _reset_global_state(self) -> None:
        """Reset fallback.py global state for a clean simulation."""
        # Set calibrated gate turnaround time from profile (0 = use GSE model)
        set_calibration_gate_minutes(self.airport_profile.turnaround_median_min)

        # Set calibrated taxi-out hold from BTS OTP data
        profile = self.airport_profile
        if profile.taxi_out_mean_min > 0:
            set_calibration_taxi_out(
                profile.taxi_out_mean_min,
                p95_minutes=getattr(profile, 'taxi_out_p95_min', 0.0),
            )
        else:
            set_calibration_taxi_out(0.0)

        # Set calibrated taxi-in hold from BTS OTP data.
        # Estimate actual waypoint travel time (including congestion) so the
        # hold doesn't overshoot. Taxi separation adds ~50-150% to bare path
        # time depending on traffic density.
        if profile.taxi_in_mean_min > 0:
            waypoint_s = self._estimate_taxi_in_travel_s()
            flights_per_hour = (self.config.arrivals + self.config.departures) / max(self.config.duration_hours, 1)
            congestion_factor = 1.0 + min(flights_per_hour / 10.0, 2.0)
            effective_travel_s = waypoint_s * congestion_factor
            set_calibration_taxi_in(profile.taxi_in_mean_min, waypoint_travel_s=effective_travel_s)
        else:
            set_calibration_taxi_in(0.0)

        _flight_states.clear()
        _gate_states.clear()
        _fb._occupied_gate_count = 0
        from src.ingestion._state import reset_max_approach_cache, set_max_approach_aircraft
        from src.ingestion._approach_departure import reset_arrival_runway_state, set_arrival_runways
        reset_max_approach_cache()
        set_max_approach_aircraft(len(self.capacity.all_runways))
        reset_arrival_runway_state()
        set_arrival_runways(sorted(self.capacity.active_runways))

        # Clear scenario runway closures from previous runs
        clear_runway_closures()

        # Reset ALL runway states — clear the entire dict and re-init defaults.
        # Previous sims may have created dynamic entries (e.g. reciprocal "10L"
        # for "28R") that would otherwise persist and block arrivals.
        _runway_states.clear()
        _runway_28L.__init__()
        _runway_28R.__init__()
        _runway_states["28L"] = _runway_28L
        _runway_states["28R"] = _runway_28R

        # Reset gate cache so simulation uses default gates
        _fb._loaded_gates = None

        # Offset SFO coordinates to target airport (standalone CLI mode)
        iata = self.config.airport
        if iata in AIRPORT_COORDINATES:
            lat, lon = AIRPORT_COORDINATES[iata]
        else:
            lat, lon = get_airport_center()
        if iata != "SFO":
            apply_airport_offset(lat, lon)
        else:
            reset_airport_offset()

        # Patch approach/departure waypoint functions to use hardcoded
        # (possibly offset) fallbacks when no OSM runway data is available.
        _orig_approach = _fb._get_approach_waypoints
        _orig_departure = _fb._get_departure_waypoints

        def _sim_approach_waypoints(origin_iata=None):
            result = _orig_approach(origin_iata)
            if not result:
                return list(_fb.APPROACH_WAYPOINTS)
            return result

        def _sim_departure_waypoints(destination_iata=None):
            result = _orig_departure(destination_iata)
            if not result:
                return list(_fb.DEPARTURE_WAYPOINTS)
            return result

        _fb._get_approach_waypoints = _sim_approach_waypoints
        _fb._get_departure_waypoints = _sim_departure_waypoints
        self._orig_approach = _orig_approach
        self._orig_departure = _orig_departure

        # Initialize gates
        _init_gate_states()

        # Drain any leftover events from previous runs
        drain_phase_transitions()
        drain_gate_events()

    def _estimate_taxi_in_travel_s(self, sample_size: int = 10) -> float:
        """Estimate average taxi-in waypoint travel time by sampling gates.

        Computes the geometric path length for a few random gates at the
        arrival taxi speed (straight + ramp segments) and returns the mean
        travel time in seconds. Falls back to 120s if no gates are available.
        """
        gates = get_gates()
        if not gates:
            return 120.0
        gate_names = list(gates.keys())
        rng = random.Random(0)
        rng.shuffle(gate_names)
        travel_times: list[float] = []
        inbound_speed = TAXI_SPEED_STRAIGHT_KTS + 5  # matches fallback.py taxi_to_gate
        for gname in gate_names[:sample_size]:
            try:
                wps = _get_taxi_waypoints_arrival(gname)
                if not wps or len(wps) < 2:
                    continue
                path_deg = 0.0
                for i in range(len(wps) - 1):
                    p1 = (wps[i][1], wps[i][0])
                    p2 = (wps[i + 1][1], wps[i + 1][0])
                    path_deg += _distance_between(p1, p2)
                # Add gate approach at ramp speed
                gate_pos = gates[gname]
                last_wp = (wps[-1][1], wps[-1][0])
                gate_dist = _distance_between(last_wp, gate_pos)
                straight_s = path_deg / max(inbound_speed * _KTS_TO_DEG_PER_SEC, 1e-12)
                ramp_s = gate_dist / max(TAXI_SPEED_RAMP_KTS * _KTS_TO_DEG_PER_SEC, 1e-12)
                travel_times.append(straight_s + ramp_s)
            except Exception:
                continue
        if not travel_times:
            return 120.0
        avg = sum(travel_times) / len(travel_times)
        if avg > 1800.0:
            logger.warning(f"Estimated taxi-in travel {avg:.0f}s unreasonable, using 120s fallback")
            return 120.0
        logger.debug(f"Estimated taxi-in travel: {avg:.0f}s ({avg/60:.1f} min) from {len(travel_times)} gates")
        return avg

    def _process_scenario_events(self) -> None:
        """Process scenario events that should trigger at current sim_time."""
        while self._scenario_event_idx < len(self.scenario_timeline):
            event = self.scenario_timeline[self._scenario_event_idx]
            if event.time > self.sim_time:
                break

            self._scenario_event_idx += 1

            if event.event_type == "weather":
                we = event.event
                self.capacity.apply_weather(
                    we.visibility_nm, we.ceiling_ft, we.wind_gusts_kt,
                    weather_type=we.type,
                )
                if we.wind_direction is not None:
                    self.capacity.check_wind_reversal(we.wind_direction)
                self._active_weather_event = we
                self._weather_event_expires = event.time + timedelta(hours=we.duration_hours)
                self.recorder.record_scenario_event(
                    self.sim_time, "weather", event.description,
                    {"severity": we.severity, "type": we.type,
                     "visibility_nm": we.visibility_nm, "ceiling_ft": we.ceiling_ft},
                )

            elif event.event_type == "runway":
                re = event.event
                if re.type == "closure" and re.runway:
                    until = event.time + timedelta(minutes=re.duration_minutes or 60)
                    self.capacity.close_runway(re.runway, until)
                    set_runway_closed(re.runway)
                    self.recorder.record_scenario_event(
                        self.sim_time, "runway", event.description,
                        {"runway": re.runway, "reason": re.reason},
                    )
                elif re.type == "reopen" and re.runway:
                    self.capacity.reopen_runway(re.runway)
                    set_runway_open(re.runway)
                    self.recorder.record_scenario_event(
                        self.sim_time, "runway", event.description,
                        {"runway": re.runway},
                    )
                elif re.type == "config_change":
                    # Config change: close all except specified config
                    self.recorder.record_scenario_event(
                        self.sim_time, "runway", event.description,
                        {"runway_config": re.runway_config, "reason": re.reason},
                    )

            elif event.event_type == "ground":
                ge = event.event
                until = event.time + timedelta(hours=ge.duration_hours)
                if ge.type == "gate_failure" and ge.target:
                    self.capacity.fail_gate(ge.target, until)
                if ge.impact and ge.impact.get("turnaround_multiplier"):
                    self.capacity.set_turnaround_multiplier(
                        ge.impact["turnaround_multiplier"]
                    )
                self.recorder.record_scenario_event(
                    self.sim_time, "ground", event.description,
                    {"type": ge.type, "target": ge.target},
                )

            elif event.event_type == "traffic":
                tm = event.event
                if tm.type == "ground_stop":
                    self.capacity.set_ground_stop(True)
                    if tm.duration_hours:
                        self._ground_stop_expires = event.time + timedelta(hours=tm.duration_hours)
                    self.recorder.record_scenario_event(
                        self.sim_time, "traffic", event.description,
                    )

            logger.info("[%s] Scenario: %s", self.sim_time.strftime("%H:%M"), event.description)

        # Check if ground stop has expired
        if self._ground_stop_expires and self.sim_time >= self._ground_stop_expires:
            self.capacity.set_ground_stop(False)
            self._ground_stop_expires = None
            self.recorder.record_scenario_event(
                self.sim_time, "traffic", "Ground stop lifted",
            )

        # Check if active weather has expired
        if self._active_weather_event and self._weather_event_expires:
            if self.sim_time >= self._weather_event_expires:
                self._active_weather_event = None
                self._weather_event_expires = None
                # Revert to VMC
                self.capacity.apply_weather(10.0, 10000, None)

        # Update capacity manager (expire closures, clean tracking)
        prev_closed = set(self.capacity.closed_runways.keys())
        self.capacity.update(self.sim_time)
        for rwy in prev_closed - set(self.capacity.closed_runways.keys()):
            set_runway_open(rwy)

    def _spawn_scheduled_flights(self) -> None:
        """Spawn flights whose scheduled time has arrived, subject to capacity limits."""
        for idx in range(self._spawn_scan_start, len(self.flight_schedule)):
            flight = self.flight_schedule[idx]
            if idx in self._spawned_indices:
                continue

            scheduled = datetime.fromisoformat(flight["scheduled_time"])

            # Schedule is sorted by scheduled_time — if scheduled > sim_time,
            # no later flights can be due either (regardless of delay).
            if scheduled > self.sim_time:
                break

            effective_time = scheduled + timedelta(minutes=flight.get("delay_minutes", 0))
            if effective_time > self.sim_time:
                continue  # delayed flight not yet due, but later flights may be

            icao24 = f"sim{idx:05d}"
            callsign = flight["flight_number"]

            if icao24 in _flight_states:
                continue

            # Capacity check: defer spawn if over rate limit
            if flight["flight_type"] == "arrival":
                if not self.capacity.can_accept_arrival(self.sim_time):
                    if icao24 not in self._holding_flights:
                        self._holding_flights.add(icao24)
                        self.recorder.record_scenario_event(
                            self.sim_time, "capacity",
                            f"Arrival {callsign} holding — arrival rate at capacity",
                            {"callsign": callsign, "action": "hold"},
                        )
                        diag_log(
                            "DEPARTURE_HOLD", self.sim_time,
                            icao24=icao24, reason="arrival_rate_capacity",
                        )
                    continue  # will retry next tick
                self._holding_flights.discard(icao24)
            else:
                if not self.capacity.can_release_departure(self.sim_time):
                    if icao24 not in self._holding_flights:
                        self._holding_flights.add(icao24)
                        self.recorder.record_scenario_event(
                            self.sim_time, "capacity",
                            f"Departure {callsign} held — departure rate at capacity",
                            {"callsign": callsign, "action": "hold"},
                        )
                        diag_log(
                            "DEPARTURE_HOLD", self.sim_time,
                            icao24=icao24, reason="departure_rate_capacity",
                        )
                    continue
                self._holding_flights.discard(icao24)

            if flight["flight_type"] == "arrival":
                phase = FlightPhase.APPROACHING
                origin = flight["origin"]
                dest = flight["destination"]
            else:
                phase = FlightPhase.PARKED
                origin = flight["origin"]
                dest = flight["destination"]

            try:
                state = _create_new_flight(
                    icao24, callsign, phase,
                    origin=origin, destination=dest,
                )
                # Override aircraft type to match schedule
                state.aircraft_type = flight["aircraft_type"]
                _flight_states[icao24] = state
                self._phase_count_inc(state.phase.value)

                self._spawned_indices.add(idx)
                self._spawn_times[idx] = self.sim_time

                # Record capacity tracking
                if flight["flight_type"] == "arrival":
                    self.capacity.record_arrival(self.sim_time)
                else:
                    self.capacity.record_departure(self.sim_time)

                self.recorder.record_phase_transition(
                    self.sim_time, icao24, callsign,
                    "scheduled", phase.value,
                    state.latitude, state.longitude, state.altitude,
                    state.aircraft_type, state.assigned_gate,
                )

                # Process departure passengers through checkpoint
                if flight["flight_type"] == "departure":
                    dep_time = datetime.fromisoformat(flight["scheduled_time"])
                    self._passenger_flow.process_departure(
                        flight_number=callsign,
                        aircraft_type=flight["aircraft_type"],
                        scheduled_departure=dep_time,
                    )
                    # Generate baggage for departures spawned at gate
                    # (arrivals generate baggage when they transition to PARKED)
                    self._completed_flights.append({
                        "icao24": icao24,
                        "callsign": callsign,
                        "schedule": flight,
                        "parked_time": self.sim_time,
                    })

                if self.config.debug:
                    logger.debug(
                        "[%s] Spawned %s (%s) as %s",
                        self.sim_time.strftime("%H:%M:%S"),
                        callsign, flight["flight_type"], phase.value,
                    )
            except Exception as e:
                logger.warning("Failed to spawn flight %s: %s", callsign, e)
                self._spawned_indices.add(idx)

        # Advance low-water mark past contiguous spawned flights
        while (self._spawn_scan_start < len(self.flight_schedule)
               and self._spawn_scan_start in self._spawned_indices):
            self._spawn_scan_start += 1

    def _update_all_flights(self, dt: float) -> None:
        """Update all active flight states and capture events."""
        for icao24 in list(_flight_states.keys()):
            state = _flight_states[icao24]
            old_phase = state.phase

            _flight_states[icao24] = _update_flight_state(state, dt)

            new_state = _flight_states[icao24]
            new_phase = new_state.phase

            # Clamp negative altitudes
            if new_state.altitude < 0:
                new_state.altitude = 0.0

            # Track phase elapsed time for stuck detection
            phase_key = new_phase.value
            prev = self._phase_time.get(icao24)
            if prev and prev[0] == phase_key:
                elapsed = prev[1] + dt
                self._phase_time[icao24] = (phase_key, elapsed)
            else:
                self._phase_time[icao24] = (phase_key, 0.0)
                elapsed = 0.0

            # Resolve stuck flights by forcing phase transitions
            max_time = self._max_phase_seconds.get(phase_key)
            if max_time and elapsed > max_time:
                self._force_advance(icao24, new_state)

            # Detect phase transitions
            if new_phase != old_phase:
                self._phase_count_transition(old_phase.value, new_phase.value)
                self.recorder.record_phase_transition(
                    self.sim_time, icao24, state.callsign,
                    old_phase.value, new_phase.value,
                    state.latitude, state.longitude, state.altitude,
                    state.aircraft_type, state.assigned_gate,
                )
                # Flag that a landing-related transition happened so
                # _capture_positions records all flights this tick.
                if FlightPhase.LANDING in (old_phase, new_phase):
                    self._landing_transition_this_tick = True

                # Track flights that reach PARKED (for baggage + passenger flow)
                if new_phase == FlightPhase.PARKED:
                    sched = self._find_schedule_entry(icao24)
                    if sched:
                        self._completed_flights.append({
                            "icao24": icao24,
                            "callsign": state.callsign,
                            "schedule": sched,
                            "parked_time": self.sim_time,
                        })
                        # Process arrival passengers
                        if sched.get("flight_type") == "arrival":
                            self._passenger_flow.process_arrival(
                                flight_number=state.callsign,
                                aircraft_type=sched.get("aircraft_type", "A320"),
                                parked_time=self.sim_time,
                            )

                # Go-around check: APPROACHING → LANDING transition
                if (old_phase == FlightPhase.APPROACHING
                        and new_phase == FlightPhase.LANDING
                        and random.random() < self.capacity.go_around_probability()):
                    from src.ingestion.fallback import _release_runway, VREF_SPEEDS
                    from src.ingestion.fallback import _get_arrival_runway_name
                    _release_runway(icao24, _get_arrival_runway_name())
                    # Transition to ENROUTE (not APPROACHING wp 0) so the
                    # aircraft flies FORWARD on current heading, climbs, then
                    # re-sequences via the holding pattern logic.
                    # Keep current heading — already correct from approach.
                    self._phase_count_transition("landing", "enroute")
                    new_state.phase = FlightPhase.ENROUTE
                    new_state.waypoint_index = 0
                    new_state.go_around_target_alt = max(1500.0, new_state.altitude + 300)
                    vref_ga = VREF_SPEEDS.get(new_state.aircraft_type, 137)
                    new_state.velocity = min(new_state.velocity + 10, vref_ga + 20)
                    new_state.vertical_rate = 1500
                    new_state.go_around_count += 1
                    new_state.holding_phase_time = 0.0
                    new_state.holding_inbound = True
                    self.recorder.record_phase_transition(
                        self.sim_time, icao24, state.callsign,
                        "approaching", "enroute",
                        new_state.latitude, new_state.longitude,
                        new_state.altitude, new_state.aircraft_type,
                        new_state.assigned_gate,
                    )
                    self.recorder.record_scenario_event(
                        self.sim_time, "go_around",
                        f"{state.callsign} go-around #{new_state.go_around_count} ({self.capacity.current_category})",
                        {"callsign": state.callsign, "icao24": icao24,
                         "attempt": new_state.go_around_count, "weather": self.capacity.current_category},
                    )
                    if new_state.go_around_count >= 3:
                        self._divert_flight(icao24, new_state)

        # Divert airborne flights if all runways closed
        if not self.capacity.active_runways:
            for icao24 in list(_flight_states.keys()):
                state = _flight_states[icao24]
                if state.phase == FlightPhase.APPROACHING:
                    self._divert_flight(icao24, state)
                elif (state.phase == FlightPhase.ENROUTE
                      and state.origin_airport and not state.destination_airport):
                    self._divert_flight(icao24, state)

        # Proactive diversion: holding > 10 min while approach is saturated
        from src.ingestion._state import get_max_approach_aircraft
        _max_app = get_max_approach_aircraft()
        _app_count = self._phase_counts.get("approaching", 0) + self._phase_counts.get("landing", 0)
        if _app_count >= _max_app:
            for icao24 in list(_flight_states.keys()):
                state = _flight_states[icao24]
                if state.phase != FlightPhase.ENROUTE:
                    continue
                _is_arriving = (state.origin_airport and not state.destination_airport)
                if not _is_arriving:
                    continue
                prev = self._phase_time.get(icao24)
                if prev and prev[0] == "enroute" and prev[1] > 360.0:
                    self._divert_flight(icao24, state)

        # Remove completed departures (enroute with exit signal)
        for icao24 in list(_flight_states.keys()):
            state = _flight_states[icao24]
            if state.phase == FlightPhase.ENROUTE and state.phase_progress == -1.0:
                if state.assigned_gate:
                    _release_gate(icao24, state.assigned_gate)
                self._phase_count_dec(state.phase.value)
                del _flight_states[icao24]
                self._phase_time.pop(icao24, None)

    def _force_advance(self, icao24: str, state: FlightState) -> None:
        """Force a stuck flight to advance to the next phase."""
        old_phase = state.phase
        resolution = self._phase_resolver.resolve(icao24, state, 0.0)
        self._apply_resolution(icao24, state, resolution)

        new_phase = state.phase
        if new_phase != old_phase:
            self._phase_count_transition(old_phase.value, new_phase.value)
            self.recorder.record_phase_transition(
                self.sim_time, icao24, state.callsign,
                old_phase.value, new_phase.value,
                state.latitude, state.longitude, state.altitude,
                state.aircraft_type, state.assigned_gate,
            )

    def _apply_resolution(self, icao24: str, state: FlightState, resolution) -> None:
        """Apply a PhaseResolution's mutations and side effects."""
        from src.ingestion.fallback import (
            _occupy_gate, _find_available_gate, _release_runway, _occupy_runway,
            _get_parked_heading, _compute_gate_standoff, _offset_position_by_heading,
            _get_arrival_runway_name, _get_taxi_waypoints_arrival, TAXI_WAYPOINTS_ARRIVAL,
            TAXI_WAYPOINTS_DEPARTURE, _snap_to_nearest_waypoint, _get_star_name,
        )
        from src.ingestion._approach_departure import _get_takeoff_runway_geometry
        from src.ingestion._clock import get_time

        # Gate release
        if resolution.gate_release:
            _release_gate(icao24, resolution.gate_release)

        # Gate assignment (for landing → taxi)
        if resolution.gate_assign:
            _occupy_gate(icao24, resolution.gate_assign)

        # Runway operations
        if resolution.runway_occupy:
            from src.ingestion.fallback import _get_runway_state
            _occupy_runway(icao24, resolution.runway_occupy)
            _get_runway_state(resolution.runway_occupy).last_arrival_time = get_time()

        if resolution.runway_release:
            arr_rwy = _get_arrival_runway_name()
            _release_runway(icao24, arr_rwy)

        # Snap to gate position
        if resolution.snap_to_gate and state.assigned_gate:
            gate_pos = get_gates().get(state.assigned_gate)
            if gate_pos:
                state.latitude, state.longitude = gate_pos
                parked_heading = _get_parked_heading(state.latitude, state.longitude)
                state.heading = parked_heading
                standoff = _compute_gate_standoff(
                    state.latitude, state.longitude, parked_heading, state.aircraft_type
                )
                state.latitude, state.longitude = _offset_position_by_heading(
                    state.latitude, state.longitude, parked_heading, standoff
                )

        # Snap to hold line
        if resolution.snap_to_hold_line:
            taxi_wps = state.taxi_route or TAXI_WAYPOINTS_DEPARTURE
            if taxi_wps:
                last_wp = taxi_wps[-1]
                state.latitude, state.longitude = last_wp[1], last_wp[0]
            state.waypoint_index = len(taxi_wps)
            _, _, dep_hdg, _ = _get_takeoff_runway_geometry()
            state.heading = dep_hdg

        # Force approach: snap to nearest waypoint on approach path
        if resolution.force_approach:
            state.waypoint_index = _snap_to_nearest_waypoint(state)
            state.star_name = _get_star_name(state.origin_airport)

        # Landing → taxi: assign gate and build taxi route
        if resolution.new_phase == FlightPhase.TAXI_TO_GATE and state.phase != FlightPhase.TAXI_TO_GATE:
            if not state.assigned_gate:
                gate = _find_available_gate()
                if gate:
                    state.assigned_gate = gate
                    _occupy_gate(icao24, gate)
            current_pos = (state.longitude, state.latitude)
            taxi_wps = (_get_taxi_waypoints_arrival(state.assigned_gate, start_pos=current_pos)
                        if state.assigned_gate else None) or TAXI_WAYPOINTS_ARRIVAL
            state.taxi_route = [current_pos] + list(taxi_wps)
            state.waypoint_index = 1

        # Apply state mutations
        for field, value in resolution.state_mutations.items():
            setattr(state, field, value)

        # Phase transition
        if resolution.new_phase:
            state.phase = resolution.new_phase

        # Mark exit (for departing enroute stuck flights)
        if resolution.mark_exit:
            state.phase_progress = -1.0

        # Reset phase time tracker
        if resolution.reset_phase_time:
            self._phase_time[icao24] = (resolution.reset_phase_time, resolution.phase_time_value)

        # Record event
        if resolution.event_type:
            self.recorder.record_scenario_event(
                self.sim_time, resolution.event_type,
                resolution.event_description,
                resolution.event_data,
            )

        # Handle diversion (heading toward alternate)
        if resolution.divert_to:
            if state.assigned_gate and resolution.gate_release is None:
                _release_gate(icao24, state.assigned_gate)
            state.assigned_gate = None
            if resolution.divert_to in AIRPORT_COORDINATES:
                from src.ingestion.fallback import _bearing_to_airport
                state.heading = _bearing_to_airport(resolution.divert_to)
            # Record diversion event (separate from any go-around event)
            if resolution.event_type != "diversion":
                self.recorder.record_scenario_event(
                    self.sim_time, "diversion",
                    f"{state.callsign} diverted to {resolution.divert_to}",
                    {"callsign": state.callsign, "icao24": icao24,
                     "alternate": resolution.divert_to,
                     "aircraft_type": state.aircraft_type,
                     "weather_category": self.capacity.current_category},
                )

        # Track completed flights for PARKED transitions (baggage generation)
        if resolution.new_phase == FlightPhase.PARKED:
            sched = self._find_schedule_entry(icao24)
            if sched:
                self._completed_flights.append({
                    "icao24": icao24,
                    "callsign": state.callsign,
                    "schedule": sched,
                    "parked_time": self.sim_time,
                })
                if sched.get("flight_type") == "arrival":
                    self._passenger_flow.process_arrival(
                        flight_number=state.callsign,
                        aircraft_type=sched.get("aircraft_type", "A320"),
                        parked_time=self.sim_time,
                    )

    def _divert_flight(self, icao24: str, state: FlightState) -> None:
        """Divert flight to an alternate airport."""
        from src.simulation.phase_resolver import PhaseResolution
        old_phase_value = state.phase.value
        resolution = self._phase_resolver._diversion_resolution(icao24, state)
        self._apply_resolution(icao24, state, resolution)
        if state.phase.value != old_phase_value:
            self._phase_count_transition(old_phase_value, state.phase.value)

    def _proactive_cancel(self) -> None:
        """Pre-cancel departures when severe weather is forecast within 2 hours.

        Airlines proactively cancel 10-20% of departures before severe weather
        to avoid stranding aircraft/passengers. Real-world: airlines start cancelling
        6-12h before major storms, but in sim timescale we look 2h ahead.
        """
        if not self.scenario_timeline:
            return
        # Look ahead 2 sim-hours for severe weather
        lookahead = self.sim_time + timedelta(hours=2)
        severe_incoming = False
        for evt in self.scenario_timeline[self._scenario_event_idx:]:
            if evt.time > lookahead:
                break
            if evt.event_type == "weather" and evt.event.severity == "severe":
                severe_incoming = True
                break

        if not severe_incoming:
            return

        # Cancel ~15% of unspawned departures in the next 2 hours
        cancelled = 0
        for idx, flight in enumerate(self.flight_schedule):
            if idx in self._spawned_indices:
                continue
            if flight["flight_type"] != "departure":
                continue
            sched_time = datetime.fromisoformat(flight["scheduled_time"])
            if self.sim_time <= sched_time <= lookahead:
                if random.random() < 0.15:
                    self._spawned_indices.add(idx)  # mark as handled
                    flight["cancelled"] = True
                    cancelled += 1
                    self.recorder.record_scenario_event(
                        self.sim_time, "cancellation",
                        f"{flight['flight_number']} proactively cancelled (severe weather forecast)",
                        {"callsign": flight["flight_number"], "reason": "proactive_severe_weather"},
                    )
        if cancelled:
            logger.info("Proactive cancellations: %d departures cancelled for severe weather", cancelled)

    def _update_departure_queue(self) -> None:
        """Count flights in PUSHBACK or TAXI_TO_RUNWAY and update capacity queue metrics."""
        queue_size = (self._phase_counts.get("pushback", 0)
                      + self._phase_counts.get("taxi_to_runway", 0))
        self.capacity.update_departure_queue(queue_size)

    def _apply_temperature(self) -> None:
        """Extract temperature from current weather and apply de-rating."""
        if not self._active_weather_event:
            return
        we = self._active_weather_event
        # Estimate temperature from weather type + time of day
        hour = self.sim_time.hour
        if we.type in ("sandstorm", "dust", "haze"):
            # Desert airports: DXB can hit 45-50°C in summer
            base_temp = 38.0 + (5.0 if 10 <= hour <= 16 else 0.0)
        elif we.type in ("snow", "freezing_rain", "ice_pellets"):
            base_temp = -5.0
        elif we.type == "fog":
            base_temp = 12.0
        elif we.type == "thunderstorm":
            base_temp = 28.0
        else:
            base_temp = 22.0
        self.capacity.set_temperature(base_temp)

    def _find_schedule_entry(self, icao24: str) -> Optional[dict]:
        """Find the schedule entry for a given icao24."""
        idx_str = icao24.replace("sim", "")
        try:
            idx = int(idx_str)
            if 0 <= idx < len(self.flight_schedule):
                return self.flight_schedule[idx]
        except ValueError:
            pass
        return None

    def _capture_positions(self) -> None:
        """Record position snapshots at the configured interval.

        When any flight is in LANDING phase, ALL flights are captured
        every tick so the short flyover/rollout is visible in replays
        without creating frame-count jumps.
        """
        elapsed = (self.sim_time - self._last_snapshot_time).total_seconds()
        bulk_due = elapsed >= self._snapshot_interval

        # High-freq capture when any flight is landing or just transitioned
        has_landing = (
            getattr(self, '_landing_transition_this_tick', False) or
            self._phase_counts.get("landing", 0) > 0
        )
        self._landing_transition_this_tick = False

        if not bulk_due and not has_landing:
            return

        for icao24, state in _flight_states.items():
            # Thin holding pattern recordings: after 30s in ENROUTE, only record
            # every 30s (skip high-freq landing ticks) to prevent dense clusters.
            # Exception: go-around flights (low altitude, actively maneuvering)
            # must remain visible throughout the missed approach procedure.
            if state.phase == FlightPhase.ENROUTE:
                prev = self._phase_time.get(icao24)
                is_go_around = state.go_around_count > 0 and state.altitude < 5000
                if prev and prev[0] == "enroute" and prev[1] > 30.0 and not is_go_around:
                    if not bulk_due:
                        self._prev_altitudes[icao24] = state.altitude
                        continue

            # D04 fix: compute vertical_rate from altitude delta if state value is 0
            vr = state.vertical_rate
            if vr == 0 and icao24 in self._prev_altitudes:
                prev_alt = self._prev_altitudes[icao24]
                alt_diff = state.altitude - prev_alt
                if abs(alt_diff) > 1.0 and elapsed > 0:
                    vr = alt_diff / (elapsed / 60.0)  # ft/min
            self._prev_altitudes[icao24] = state.altitude
            self.recorder.record_position(
                self.sim_time, icao24, state.callsign,
                state.latitude, state.longitude, state.altitude,
                state.velocity, state.heading, state.phase.value,
                state.on_ground, state.aircraft_type, state.assigned_gate,
                vr,
                origin_airport=state.origin_airport,
                destination_airport=state.destination_airport,
            )

        if bulk_due:
            self._last_snapshot_time = self.sim_time

    def _capture_gate_events(self) -> None:
        """Drain gate events from the global buffer and record them."""
        events = drain_gate_events()
        for event in events:
            self.recorder.record_gate_event(
                self.sim_time,
                event["icao24"],
                event["callsign"],
                event["gate"],
                event["event_type"],
                event["aircraft_type"],
            )

    def _capture_phase_transitions(self) -> None:
        """Drain phase transitions from the global buffer.

        Note: phase transitions are already recorded in _update_all_flights()
        when it detects phase changes. We only drain the global buffer here
        to prevent it from growing unbounded. Do NOT re-record them.
        """
        drain_phase_transitions()

    def _capture_weather(self) -> None:
        """Generate weather snapshot at hour boundaries, using scenario overrides if active."""
        current_hour = self.sim_time.hour
        if current_hour != self._last_weather_hour:
            self._last_weather_hour = current_hour
            station = f"K{self.config.airport}" if len(self.config.airport) == 3 else self.config.airport

            if self._active_weather_event:
                # Use scenario weather parameters
                we = self._active_weather_event
                metar = generate_metar(station=station, obs_time=self.sim_time)
                # Override with scenario values
                if we.visibility_nm is not None:
                    metar["visibility_sm"] = we.visibility_nm
                if we.wind_speed_kt is not None:
                    metar["wind_speed_kts"] = we.wind_speed_kt
                if we.wind_gusts_kt is not None:
                    metar["wind_gust_kts"] = we.wind_gusts_kt
                if we.wind_direction is not None:
                    metar["wind_direction"] = we.wind_direction
                if we.ceiling_ft is not None:
                    # Override flight category based on scenario
                    vis = we.visibility_nm or 10.0
                    ceil = we.ceiling_ft
                    if vis < 1.0 or ceil < 500:
                        metar["flight_category"] = "LIFR"
                    elif vis < 3.0 or ceil < 1000:
                        metar["flight_category"] = "IFR"
                    elif vis < 5.0 or ceil < 3000:
                        metar["flight_category"] = "MVFR"
                    else:
                        metar["flight_category"] = "VFR"
                metar["scenario_weather"] = we.type
            else:
                metar = generate_metar(station=station, obs_time=self.sim_time)

            self.recorder.record_weather(self.sim_time, metar)

            # Update weather state in fallback module for turnaround factor calculations
            from src.ingestion.fallback import set_current_weather
            set_current_weather(
                float(metar.get("wind_speed_kts", 0) or 0),
                float(metar.get("visibility_sm", 10.0) or 10.0),
            )

    def _generate_baggage(self) -> None:
        """Generate baggage data for flights that reached PARKED."""
        for completed in self._completed_flights:
            sched = completed["schedule"]
            bags = generate_bags_for_flight(
                flight_number=completed["callsign"],
                aircraft_type=sched.get("aircraft_type", "A320"),
                origin=sched.get("origin", "SFO"),
                destination=sched.get("destination", "LAX"),
                scheduled_time=completed["parked_time"],
                is_arrival=sched.get("flight_type") == "arrival",
            )
            self.recorder.record_baggage(
                completed["parked_time"],
                completed["callsign"],
                bags,
            )
        self._completed_flights.clear()

    def _print_progress(self) -> None:
        """Print progress every sim-hour."""
        current_hour = int((self.sim_time - self.config.effective_start_time()).total_seconds() / 3600)
        if current_hour != self._last_progress_hour:
            self._last_progress_hour = current_hour
            total_hours = self.config.effective_duration_hours()
            pct = min(100, current_hour / total_hours * 100)
            active = len(_flight_states)
            spawned = len(self._spawned_indices)
            total = len(self.flight_schedule)
            bar_len = 30
            filled = int(bar_len * pct / 100)
            bar = "=" * filled + "-" * (bar_len - filled)
            print(
                f"\r  [{bar}] {pct:5.1f}% | "
                f"Sim: {self.sim_time.strftime('%H:%M')} | "
                f"Active: {active:3d} | "
                f"Spawned: {spawned}/{total}",
                end="",
                flush=True,
            )

    def run(self) -> SimulationRecorder:
        """Run the simulation from start to end, returning the recorder."""
        # Inject sim clock so _runway_ops and _flight_lifecycle use sim time
        set_clock(lambda: self.sim_time.timestamp())
        # Suppress fallback emit_phase_transition — engine records directly (D05 fix)
        set_suppress_phase_transitions(True)
        dt = self.config.time_step_seconds
        total_ticks = int(
            (self.end_time - self.sim_time).total_seconds() / dt
        )

        print(f"Starting simulation: {self.config.airport}")
        print(
            f"  Duration: {self.config.effective_duration_hours():.1f}h | "
            f"Flights: {len(self.flight_schedule)} | "
            f"Time step: {dt}s | "
            f"Ticks: {total_ticks:,}"
        )
        if self.scenario:
            print(f"  Scenario: {self.scenario.name} ({len(self.scenario_timeline)} events)")

        start_wall = wall_time.time()

        tick = 0
        while self.sim_time < self.end_time:
            tick_start = wall_time.time()

            # 0. Process scenario events at current sim_time
            if self.scenario:
                self._process_scenario_events()
                self._apply_temperature()
                self._proactive_cancel()

            # 1. Update departure queue metrics and spawn scheduled flights
            self._update_departure_queue()
            self._spawn_scheduled_flights()

            # 2. Update all active flights
            self._update_all_flights(dt)

            # 3. Capture events
            self._capture_positions()
            self._capture_gate_events()
            self._capture_phase_transitions()
            self._capture_weather()

            # 4. Generate baggage for newly parked flights
            self._generate_baggage()

            # 5. Emit tick diagnostics
            if self._diag:
                tick_ms = (wall_time.time() - tick_start) * 1000
                diag_log(
                    "TICK_STATS", self.sim_time,
                    tick=tick,
                    active_flights=len(_flight_states),
                    elapsed_ms=round(tick_ms, 2),
                )

            # 6. Advance time
            self.sim_time += timedelta(seconds=dt)
            tick += 1

            # 7. Progress
            self._print_progress()

        # Enrich schedule with actual spawn times for metrics
        for idx, flight in enumerate(self.flight_schedule):
            flight["actual_spawn_time"] = self._spawn_times[idx].isoformat() if idx in self._spawn_times else None
            flight["spawned"] = idx in self._spawned_indices

        # Store passenger flow results
        pax_results = self._passenger_flow.get_results()
        self.recorder.passenger_events = pax_results.events

        # Run BHS throughput model on all scheduled flights
        gate_count = len(get_gates()) if get_gates() else 40
        bhs_result = simulate_bhs_throughput(
            self.flight_schedule, gate_count=gate_count, seed=self.config.seed,
        )
        self.recorder.bhs_metrics = {
            "peak_throughput_bpm": bhs_result.peak_throughput_bpm,
            "total_injection_capacity_bpm": bhs_result.total_injection_capacity_bpm,
            "jam_count": bhs_result.jam_count,
            "max_queue_depth": bhs_result.max_queue_depth,
            "p95_processing_time_min": bhs_result.p95_processing_time_min,
        }

        # Write diagnostics JSON if enabled
        if self._diag and self.config.output_file and self.config.output_file != "/dev/null":
            import os
            base, ext = os.path.splitext(self.config.output_file)
            diag_path = f"{base}_diagnostics.json"
            try:
                self._diag.write(diag_path)
                print(f"  Diagnostics: {diag_path} ({len(self._diag.events):,} events)")
            except (PermissionError, OSError):
                pass

        # Re-enable fallback phase transition buffering for non-engine callers
        set_suppress_phase_transitions(False)
        # Restore real wall clock
        reset_clock()

        elapsed_wall = wall_time.time() - start_wall
        print(f"\n  Completed in {elapsed_wall:.1f}s wall time")
        print(f"  Speed: {self.config.effective_duration_hours() * 3600 / max(elapsed_wall, 0.001):.0f}x real-time")

        return self.recorder


def run_what_if(
    base_config_dict: dict,
    modifications: dict,
) -> dict:
    """Run a modified simulation and return KPI comparison vs baseline.

    Args:
        base_config_dict: Original simulation config (from sim output JSON).
        modifications: Dict of parameter overrides (arrivals, departures,
            duration_hours, scenario_file, etc.).

    Returns:
        Dict with baseline_kpis (from base_config_dict["summary"] if present),
        modified_kpis, and delta for each numeric KPI.
    """
    import copy

    baseline_kpis = base_config_dict.get("summary", {})

    mod_config_dict = copy.deepcopy(base_config_dict)
    for key in ("summary", "schedule", "position_snapshots", "phase_transitions",
                "gate_events", "scenario_events", "weather_snapshots",
                "baggage_events", "passenger_events", "bhs_metrics"):
        mod_config_dict.pop(key, None)

    mod_config_dict.update(modifications)
    mod_config_dict["skip_positions"] = True
    mod_config_dict["diagnostics"] = False
    mod_config_dict["generate_report"] = False
    mod_config_dict["output_file"] = "/dev/null"

    if "seed" not in modifications:
        mod_config_dict["seed"] = base_config_dict.get("seed", 42)

    config = SimulationConfig(**{
        k: v for k, v in mod_config_dict.items()
        if k in SimulationConfig.model_fields
    })

    engine = SimulationEngine(config)
    recorder = engine.run()
    modified_kpis = recorder.compute_summary(mod_config_dict)

    COMPARE_KEYS = [
        "on_time_pct", "schedule_delay_min", "avg_capacity_hold_min",
        "max_capacity_hold_min", "cancellation_rate_pct", "peak_simultaneous_flights",
        "avg_turnaround_min", "total_go_arounds", "total_diversions",
        "total_holdings", "total_cancellations",
    ]
    delta: dict = {}
    for key in COMPARE_KEYS:
        base_val = baseline_kpis.get(key)
        mod_val = modified_kpis.get(key)
        if isinstance(base_val, (int, float)) and isinstance(mod_val, (int, float)):
            delta[key] = round(mod_val - base_val, 2)

    return {
        "baseline_kpis": {k: baseline_kpis.get(k) for k in COMPARE_KEYS},
        "modified_kpis": {k: modified_kpis.get(k) for k in COMPARE_KEYS},
        "delta": delta,
        "modifications_applied": modifications,
    }

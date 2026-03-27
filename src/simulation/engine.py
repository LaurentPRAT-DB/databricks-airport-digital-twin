"""Core simulation engine — runs the flight state machine at accelerated speed."""

import logging
import random
import time as wall_time
from datetime import datetime, timedelta, timezone
from typing import Optional

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
        self.recorder = SimulationRecorder()

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
        self.flight_schedule: list[dict] = []
        self._generate_schedule()

        # Easter egg: inject fighter jet sorties for Ukrainian airports
        self._inject_fighter_sorties()

        # Inject traffic modifiers from scenario
        if self.scenario:
            self._inject_traffic_modifiers()

        # Track which scheduled flights have been spawned
        self._spawned_indices: set[int] = set()

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
        }

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
            set_calibration_taxi_out(profile.taxi_out_mean_min)
        else:
            set_calibration_taxi_out(0.0)

        _flight_states.clear()
        _gate_states.clear()

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

    def _generate_schedule(self) -> None:
        """Pre-generate the full flight schedule distributed across the duration.

        Uses a three-phase approach for realistic aircraft rotations:
        1. Generate arrivals distributed across hours (same as before)
        2. Link departures to arrivals via turnaround time (same aircraft/airline)
        3. Fill surplus departures as overnight-parked aircraft in the first 2 hours
        """
        start = self.config.effective_start_time()
        end_time = start + timedelta(hours=self.config.effective_duration_hours())
        duration_h = self.config.effective_duration_hours()
        profile = self.airport_profile

        # Build hourly weights for the FULL duration (multi-day aware)
        n_hours = int(duration_h) + (1 if duration_h % 1 > 0 else 0)
        hour_weights: list[float] = []
        for h_offset in range(n_hours):
            clock_hour = (start.hour + h_offset) % 24
            day_offset = (start.hour + h_offset) // 24
            dow = (start.weekday() + day_offset) % 7
            w = _get_flights_per_hour(clock_hour, airport_profile=profile, day_of_week=dow)
            hour_weights.append(max(w, 1.0))

        if not hour_weights:
            hour_weights = [1.0]

        total_weight = sum(hour_weights)

        schedule: list[dict] = []
        local_iata = self.config.airport

        # --- Phase 1: Generate arrivals distributed across hours ---
        for h_idx, weight in enumerate(hour_weights):
            flights_this_hour = max(1, round(self.config.arrivals * weight / total_weight))
            if h_idx == len(hour_weights) - 1:
                already = sum(1 for f in schedule if f["flight_type"] == "arrival")
                flights_this_hour = max(0, self.config.arrivals - already)

            for _ in range(flights_this_hour):
                if sum(1 for f in schedule if f["flight_type"] == "arrival") >= self.config.arrivals:
                    break

                airline_code, airline_name = _select_airline(profile=profile)
                flight_number = _generate_flight_number(airline_code)
                origin = _select_destination("arrival", airline_code, profile=profile)
                aircraft = _select_aircraft(origin, airline_code=airline_code, profile=profile)
                minute = random.randint(0, 59)
                scheduled_time = start + timedelta(hours=h_idx, minutes=minute)
                delay_minutes, delay_code, delay_reason = _generate_delay(profile=profile)

                schedule.append({
                    "flight_number": flight_number,
                    "airline": airline_name,
                    "airline_code": airline_code,
                    "origin": origin,
                    "destination": local_iata,
                    "aircraft_type": aircraft,
                    "flight_type": "arrival",
                    "scheduled_time": scheduled_time.isoformat(),
                    "delay_minutes": delay_minutes,
                    "delay_code": delay_code,
                    "delay_reason": delay_reason,
                })

        arrivals = [f for f in schedule if f["flight_type"] == "arrival"]

        # --- Phase 2: Link departures to arrivals via turnaround ---
        linked_count = 0
        linkable = min(len(arrivals), self.config.departures)
        for arr in arrivals[:linkable]:
            turnaround = _calibrated_turnaround(arr["aircraft_type"], arr["airline_code"], profile)
            arr_time = datetime.fromisoformat(arr["scheduled_time"])
            dep_time = arr_time + timedelta(minutes=turnaround)

            if dep_time >= end_time:
                continue  # aircraft stays parked past sim window

            destination = _select_destination("departure", arr["airline_code"], profile=profile)
            delay_minutes, delay_code, delay_reason = _generate_delay(profile=profile)

            schedule.append({
                "flight_number": _generate_flight_number(arr["airline_code"]),
                "airline": arr["airline"],
                "airline_code": arr["airline_code"],
                "origin": local_iata,
                "destination": destination,
                "aircraft_type": arr["aircraft_type"],
                "flight_type": "departure",
                "scheduled_time": dep_time.isoformat(),
                "delay_minutes": delay_minutes,
                "delay_code": delay_code,
                "delay_reason": delay_reason,
                "linked_arrival": arr["flight_number"],
            })
            linked_count += 1

        # --- Phase 3: Surplus independent departures (overnight-parked) ---
        surplus = self.config.departures - linked_count
        if surplus > 0:
            # Schedule in the first 2 hours of the sim (early morning departures)
            early_window_h = min(2.0, duration_h)
            for _ in range(surplus):
                airline_code, airline_name = _select_airline(profile=profile)
                destination = _select_destination("departure", airline_code, profile=profile)
                aircraft = _select_aircraft(destination, airline_code=airline_code, profile=profile)
                minute = random.randint(0, int(early_window_h * 60) - 1)
                scheduled_time = start + timedelta(minutes=minute)
                delay_minutes, delay_code, delay_reason = _generate_delay(profile=profile)

                schedule.append({
                    "flight_number": _generate_flight_number(airline_code),
                    "airline": airline_name,
                    "airline_code": airline_code,
                    "origin": local_iata,
                    "destination": destination,
                    "aircraft_type": aircraft,
                    "flight_type": "departure",
                    "scheduled_time": scheduled_time.isoformat(),
                    "delay_minutes": delay_minutes,
                    "delay_code": delay_code,
                    "delay_reason": delay_reason,
                })

        # Sort by scheduled time
        schedule.sort(key=lambda f: f["scheduled_time"])
        self.flight_schedule = schedule
        self.recorder.schedule = schedule

        logger.info(
            "Generated schedule: %d arrivals, %d departures (%d linked, %d overnight) over %.1fh",
            sum(1 for f in schedule if f["flight_type"] == "arrival"),
            sum(1 for f in schedule if f["flight_type"] == "departure"),
            linked_count,
            surplus,
            duration_h,
        )

    def _inject_fighter_sorties(self) -> None:
        """Easter egg: inject Ukrainian Air Force fighter jet sorties for UA airports."""
        from src.ingestion.schedule_generator import FIGHTER_JETS

        # Only inject for Ukrainian airports (country code UA in airport table)
        from src.ingestion.airport_table import AIRPORTS as _apt
        entry = _apt.get(self.config.airport)
        if not entry or entry[3] != "UA":
            return

        start = self.config.effective_start_time()
        duration_h = self.config.effective_duration_hours()
        local_iata = self.config.airport

        # Get nearby Ukrainian airports for sortie destinations
        ua_airports = [code for code, e in _apt.items() if e[3] == "UA" and code != local_iata]
        if not ua_airports:
            ua_airports = [local_iata]

        # Inject ~15-20% fighter sorties (proportional to total flights)
        total = len(self.flight_schedule)
        n_sorties = max(4, int(total * 0.18))

        for _ in range(n_sorties):
            aircraft = random.choice(FIGHTER_JETS)
            flight_num = f"UAF{random.randint(100, 999)}"
            hour = random.uniform(0, duration_h)
            sched_time = start + timedelta(hours=hour)

            # Fighter sortie: depart, fly patrol, return
            dest = random.choice(ua_airports)
            self.flight_schedule.append({
                "flight_number": flight_num,
                "airline": "Ukrainian Air Force",
                "airline_code": "UAF",
                "origin": local_iata,
                "destination": dest,
                "aircraft_type": aircraft,
                "flight_type": "departure",
                "scheduled_time": sched_time.isoformat(),
                "delay_minutes": 0,
                "delay_code": None,
                "delay_reason": None,
                "scenario_injected": True,
            })

            # Return sortie 30-90 min later
            return_time = sched_time + timedelta(minutes=random.randint(30, 90))
            if return_time < start + timedelta(hours=duration_h):
                self.flight_schedule.append({
                    "flight_number": f"UAF{random.randint(100, 999)}",
                    "airline": "Ukrainian Air Force",
                    "airline_code": "UAF",
                    "origin": dest,
                    "destination": local_iata,
                    "aircraft_type": aircraft,
                    "flight_type": "arrival",
                    "scheduled_time": return_time.isoformat(),
                    "delay_minutes": 0,
                    "delay_code": None,
                    "delay_reason": None,
                    "scenario_injected": True,
                })

        self.flight_schedule.sort(key=lambda f: f["scheduled_time"])
        self.recorder.schedule = self.flight_schedule
        n_fighters = sum(1 for f in self.flight_schedule if f.get("airline_code") == "UAF")
        logger.info("Easter egg: injected %d Ukrainian Air Force fighter sorties", n_fighters)

    def _inject_traffic_modifiers(self) -> None:
        """Inject extra flights from scenario traffic modifiers into the schedule."""
        if not self.scenario:
            return
        start = self.config.effective_start_time()
        profile = self.airport_profile
        for mod in self.scenario.traffic_modifiers:
            if mod.type == "ground_stop":
                continue  # handled in _process_scenario_events
            base_time = start
            if mod.time:
                h, m = map(int, mod.time.split(":"))
                base_time = start.replace(hour=h, minute=m, second=0, microsecond=0)

            local_iata = self.config.airport
            for i in range(mod.extra_arrivals):
                offset_min = random.randint(0, 20)
                sched_time = base_time + timedelta(minutes=offset_min + i * 3)
                airline_code, airline_name = _select_airline(profile=profile)
                origin = mod.diversion_origin or _select_destination("arrival", airline_code, profile=profile)
                aircraft = _select_aircraft(origin, airline_code=airline_code, profile=profile)
                self.flight_schedule.append({
                    "flight_number": _generate_flight_number(airline_code),
                    "airline": airline_name,
                    "airline_code": airline_code,
                    "origin": origin,
                    "destination": local_iata,
                    "aircraft_type": aircraft,
                    "flight_type": "arrival",
                    "scheduled_time": sched_time.isoformat(),
                    "delay_minutes": 0,
                    "delay_code": None,
                    "delay_reason": f"Diversion from {mod.diversion_origin}" if mod.diversion_origin else "Traffic surge",
                    "scenario_injected": True,
                })

            for i in range(mod.extra_departures):
                offset_min = random.randint(0, 20)
                sched_time = base_time + timedelta(minutes=offset_min + i * 3)
                airline_code, airline_name = _select_airline(profile=profile)
                dest = _select_destination("departure", airline_code, profile=profile)
                aircraft = _select_aircraft(dest, airline_code=airline_code, profile=profile)
                self.flight_schedule.append({
                    "flight_number": _generate_flight_number(airline_code),
                    "airline": airline_name,
                    "airline_code": airline_code,
                    "origin": local_iata,
                    "destination": dest,
                    "aircraft_type": aircraft,
                    "flight_type": "departure",
                    "scheduled_time": sched_time.isoformat(),
                    "delay_minutes": 0,
                    "delay_code": None,
                    "delay_reason": "Traffic surge",
                    "scenario_injected": True,
                })

        # Re-sort schedule after injections
        self.flight_schedule.sort(key=lambda f: f["scheduled_time"])
        self.recorder.schedule = self.flight_schedule
        injected = sum(1 for f in self.flight_schedule if f.get("scenario_injected"))
        if injected:
            logger.info("Injected %d flights from scenario traffic modifiers", injected)

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
                    self.recorder.record_scenario_event(
                        self.sim_time, "runway", event.description,
                        {"runway": re.runway, "reason": re.reason},
                    )
                elif re.type == "reopen" and re.runway:
                    self.capacity.reopen_runway(re.runway)
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
        self.capacity.update(self.sim_time)

    def _spawn_scheduled_flights(self) -> None:
        """Spawn flights whose scheduled time has arrived, subject to capacity limits."""
        for idx, flight in enumerate(self.flight_schedule):
            if idx in self._spawned_indices:
                continue

            scheduled = datetime.fromisoformat(flight["scheduled_time"])
            effective_time = scheduled + timedelta(minutes=flight.get("delay_minutes", 0))

            if effective_time <= self.sim_time:
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

    def _update_all_flights(self, dt: float) -> None:
        """Update all active flight states and capture events."""
        # Monkey-patch time.time() for functions that use it internally
        # (like _find_available_gate, _release_gate which use time.time() for cooldowns)
        sim_timestamp = self.sim_time.timestamp()
        original_time = wall_time.time
        wall_time.time = lambda: sim_timestamp

        try:
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
                    self.recorder.record_phase_transition(
                        self.sim_time, icao24, state.callsign,
                        old_phase.value, new_phase.value,
                        state.latitude, state.longitude, state.altitude,
                        state.aircraft_type, state.assigned_gate,
                    )

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

            # Remove completed departures (enroute with exit signal)
            for icao24 in list(_flight_states.keys()):
                state = _flight_states[icao24]
                if state.phase == FlightPhase.ENROUTE and state.phase_progress == -1.0:
                    if state.assigned_gate:
                        _release_gate(icao24, state.assigned_gate)
                    del _flight_states[icao24]
                    self._phase_time.pop(icao24, None)
        finally:
            wall_time.time = original_time

    def _force_advance(self, icao24: str, state: FlightState) -> None:
        """Force a stuck flight to advance to the next phase."""
        from src.ingestion.fallback import (
            _occupy_gate, _find_available_gate, _release_runway,
            _get_parked_heading, _compute_gate_standoff, _offset_position_by_heading,
        )

        old_phase = state.phase

        if state.phase == FlightPhase.TAXI_TO_GATE:
            # Snap to gate
            if state.assigned_gate:
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
                state.phase = FlightPhase.PARKED
                state.velocity = 0
                state.time_at_gate = 0
                self._phase_time[icao24] = ("parked", 0.0)
                # Track for baggage generation (D03 fix)
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

        elif state.phase == FlightPhase.TAXI_TO_RUNWAY:
            # Jump to takeoff — reset velocity for proper roll start
            state.phase = FlightPhase.TAKEOFF
            state.takeoff_subphase = "lineup"
            state.velocity = 0
            state.phase_progress = 0.0
            state.takeoff_roll_dist_ft = 0.0
            self._phase_time[icao24] = ("takeoff", 0.0)

        elif state.phase == FlightPhase.PUSHBACK:
            # Finish pushback, move to taxi
            if state.assigned_gate:
                _release_gate(icao24, state.assigned_gate)
            state.phase = FlightPhase.TAXI_TO_RUNWAY
            state.waypoint_index = 0
            self._phase_time[icao24] = ("taxi_to_runway", 0.0)

        elif state.phase == FlightPhase.APPROACHING:
            from src.ingestion.fallback import _is_runway_clear, _occupy_runway, _release_runway, VREF_SPEEDS, _get_arrival_runway_name
            _arr_rwy = _get_arrival_runway_name()
            if _is_runway_clear(_arr_rwy):
                # Apply go-around check (same as normal transition)
                if random.random() < self.capacity.go_around_probability():
                    # Transition to ENROUTE; keep current heading (correct from approach)
                    state.phase = FlightPhase.ENROUTE
                    state.waypoint_index = 0
                    state.go_around_target_alt = max(1500.0, state.altitude + 300)
                    vref_ga = VREF_SPEEDS.get(state.aircraft_type, 137)
                    state.velocity = min(state.velocity + 10, vref_ga + 20)
                    state.vertical_rate = 1500
                    state.go_around_count += 1
                    state.holding_phase_time = 0.0
                    state.holding_inbound = True
                    self.recorder.record_scenario_event(
                        self.sim_time, "go_around",
                        f"{state.callsign} go-around #{state.go_around_count} ({self.capacity.current_category})",
                        {"callsign": state.callsign, "icao24": icao24,
                         "attempt": state.go_around_count, "weather": self.capacity.current_category},
                    )
                    if state.go_around_count >= 3:
                        self._divert_flight(icao24, state)
                    self._phase_time[icao24] = ("enroute", 0.0)
                else:
                    # Only transition to landing if altitude is reasonable (<800ft)
                    # Otherwise execute go-around to avoid high-altitude landing (A09 fix)
                    if state.altitude > 800:
                        state.phase = FlightPhase.ENROUTE
                        state.waypoint_index = 0
                        state.go_around_target_alt = max(1500.0, state.altitude + 300)
                        state.vertical_rate = 1500
                        state.go_around_count += 1
                        state.holding_phase_time = 0.0
                        state.holding_inbound = True
                        self._phase_time[icao24] = ("enroute", 0.0)
                        if state.go_around_count >= 3:
                            self._divert_flight(icao24, state)
                    else:
                        state.phase = FlightPhase.LANDING
                        state.waypoint_index = 0
                        _occupy_runway(icao24, _arr_rwy)
                        self._phase_time[icao24] = ("landing", 0.0)
            else:
                # Runway still blocked — reset timer to check again in 5 min
                self._phase_time[icao24] = ("approaching", 600.0)

        elif state.phase == FlightPhase.LANDING:
            # Force taxi
            from src.ingestion.fallback import _release_runway, _get_arrival_runway_name
            state.altitude = 0
            state.on_ground = True
            state.phase = FlightPhase.TAXI_TO_GATE
            state.waypoint_index = 0
            _release_runway(icao24, _get_arrival_runway_name())
            if not state.assigned_gate:
                gate = _find_available_gate()
                if gate:
                    state.assigned_gate = gate
                    _occupy_gate(icao24, gate)
            self._phase_time[icao24] = ("taxi_to_gate", 0.0)

        # Record the phase transition for all force-advances (D06 fix)
        new_phase = state.phase
        if new_phase != old_phase:
            self.recorder.record_phase_transition(
                self.sim_time, icao24, state.callsign,
                old_phase.value, new_phase.value,
                state.latitude, state.longitude, state.altitude,
                state.aircraft_type, state.assigned_gate,
            )

    def _divert_flight(self, icao24: str, state: FlightState) -> None:
        """Divert flight to an alternate airport."""
        alternates = ALTERNATE_AIRPORTS.get(self.config.airport, [])
        alt_name = random.choice(alternates) if alternates else "alternate"
        if state.assigned_gate:
            _release_gate(icao24, state.assigned_gate)
            state.assigned_gate = None
        state.phase = FlightPhase.ENROUTE
        state.destination_airport = alt_name
        state.origin_airport = None
        state.altitude = max(state.altitude, 3000)
        state.velocity = 250
        state.vertical_rate = 1500
        state.go_around_count = 0
        if alt_name in AIRPORT_COORDINATES:
            from src.ingestion.fallback import _bearing_to_airport
            state.heading = _bearing_to_airport(alt_name)
        self.recorder.record_scenario_event(
            self.sim_time, "diversion",
            f"{state.callsign} diverted to {alt_name}",
            {"callsign": state.callsign, "icao24": icao24, "alternate": alt_name,
             "reason": "runway_closure" if not self.capacity.active_runways else "go_around_limit"},
        )

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
        queue_size = 0
        for state in _flight_states.values():
            if state.phase in (FlightPhase.PUSHBACK, FlightPhase.TAXI_TO_RUNWAY):
                queue_size += 1
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
        """Record position snapshots at the configured interval."""
        elapsed = (self.sim_time - self._last_snapshot_time).total_seconds()
        if elapsed >= self._snapshot_interval:
            self._last_snapshot_time = self.sim_time
            for icao24, state in _flight_states.items():
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
                )

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

        elapsed_wall = wall_time.time() - start_wall
        print(f"\n  Completed in {elapsed_wall:.1f}s wall time")
        print(f"  Speed: {self.config.effective_duration_hours() * 3600 / max(elapsed_wall, 0.001):.0f}x real-time")

        return self.recorder

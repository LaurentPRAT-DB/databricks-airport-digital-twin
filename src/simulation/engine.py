"""Core simulation engine — runs the flight state machine at accelerated speed."""

import logging
import random
import time as wall_time
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.simulation.config import SimulationConfig
from src.simulation.recorder import SimulationRecorder
from src.simulation.capacity import CapacityManager
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
    _DEFAULT_GATES,
    APPROACH_WAYPOINTS,
    DEPARTURE_WAYPOINTS,
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
)
from src.ingestion.weather_generator import generate_metar
from src.ingestion.baggage_generator import generate_bags_for_flight

logger = logging.getLogger(__name__)

ALTERNATE_AIRPORTS: dict[str, list[str]] = {
    "SFO": ["OAK", "SJC"],
    "JFK": ["EWR", "LGA"],
    "LHR": ["LGW", "STN"],
    "NRT": ["HND"],
    "DXB": ["AUH"],
    "GRU": ["VCP"],
    "SYD": ["MEL", "BNE"],
}


class SimulationEngine:
    """Runs a deterministic, accelerated airport simulation."""

    def __init__(self, config: SimulationConfig) -> None:
        self.config = config
        self.recorder = SimulationRecorder()

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
        self.capacity = CapacityManager(airport=config.airport, runways=["28L", "28R"])
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

        # Flight state — we reuse the global state from fallback.py
        # but reset it first to get a clean simulation
        self._reset_global_state()

        # Pre-generate flight schedule
        self.flight_schedule: list[dict] = []
        self._generate_schedule()

        # Inject traffic modifiers from scenario
        if self.scenario:
            self._inject_traffic_modifiers()

        # Track which scheduled flights have been spawned
        self._spawned_indices: set[int] = set()

        # Track completed flights for baggage generation
        self._completed_flights: list[dict] = []

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
        self._max_phase_seconds = {
            "taxi_to_gate": 600.0,    # 10 min max taxi
            "taxi_to_runway": 600.0,  # 10 min max taxi
            "pushback": 300.0,        # 5 min max pushback
            "approaching": 900.0,     # 15 min max approach
            "landing": 120.0,         # 2 min max landing
        }

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
        _flight_states.clear()
        _gate_states.clear()

        # Reset runway states
        _runway_28L.occupied_by = None
        _runway_28L.last_departure_time = 0.0
        _runway_28L.last_arrival_time = 0.0
        _runway_28L.approach_queue.clear()
        _runway_28L.departure_queue.clear()
        _runway_28L.last_departure_type = "LARGE"

        _runway_28R.occupied_by = None
        _runway_28R.last_departure_time = 0.0
        _runway_28R.last_arrival_time = 0.0
        _runway_28R.approach_queue.clear()
        _runway_28R.departure_queue.clear()
        _runway_28R.last_departure_type = "LARGE"

        # Reset gate cache so simulation uses default gates
        _fb._loaded_gates = None

        # Patch approach/departure waypoint functions to use hardcoded SFO
        # fallbacks when no OSM runway data is available (standalone sim).
        _orig_approach = _fb._get_approach_waypoints
        _orig_departure = _fb._get_departure_waypoints

        def _sim_approach_waypoints(origin_iata=None):
            result = _orig_approach(origin_iata)
            if not result:
                return list(APPROACH_WAYPOINTS)
            return result

        def _sim_departure_waypoints(destination_iata=None):
            result = _orig_departure(destination_iata)
            if not result:
                return list(DEPARTURE_WAYPOINTS)
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
        """Pre-generate the full flight schedule distributed across the duration."""
        start = self.config.effective_start_time()
        duration_h = self.config.effective_duration_hours()

        # Get hourly distribution weights
        hour_weights: list[float] = []
        for h in range(24):
            if h < int(duration_h) or (h == int(duration_h) and duration_h % 1 > 0):
                hour_weights.append(max(_get_flights_per_hour(h), 1))
            else:
                break

        if not hour_weights:
            hour_weights = [1.0]

        total_weight = sum(hour_weights)

        # Distribute arrivals and departures proportionally across hours
        schedule = []
        local_iata = self.config.airport

        for flight_type, count in [("arrival", self.config.arrivals), ("departure", self.config.departures)]:
            for h_idx, weight in enumerate(hour_weights):
                # How many flights this hour
                flights_this_hour = max(1, round(count * weight / total_weight))
                if h_idx == len(hour_weights) - 1:
                    # Last hour gets remaining flights
                    already_scheduled = sum(
                        1 for f in schedule if f["flight_type"] == flight_type
                    )
                    flights_this_hour = max(0, count - already_scheduled)

                for _ in range(flights_this_hour):
                    if sum(1 for f in schedule if f["flight_type"] == flight_type) >= count:
                        break

                    airline_code, airline_name = _select_airline()
                    flight_number = _generate_flight_number(airline_code)

                    if flight_type == "arrival":
                        origin = _select_destination("arrival", airline_code)
                        destination = local_iata
                    else:
                        origin = local_iata
                        destination = _select_destination("departure", airline_code)

                    # Select aircraft based on REMOTE airport (not local)
                    # Arrivals: remote = origin, Departures: remote = destination
                    remote_airport = origin if flight_type == "arrival" else destination
                    aircraft = _select_aircraft(remote_airport)

                    # Schedule within this hour
                    hour = start.hour + h_idx
                    if hour >= 24:
                        hour = hour % 24
                    minute = random.randint(0, 59)
                    scheduled_time = start + timedelta(hours=h_idx, minutes=minute)

                    delay_minutes, delay_code, delay_reason = _generate_delay()

                    schedule.append({
                        "flight_number": flight_number,
                        "airline": airline_name,
                        "airline_code": airline_code,
                        "origin": origin,
                        "destination": destination,
                        "aircraft_type": aircraft,
                        "flight_type": flight_type,
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
            "Generated schedule: %d arrivals, %d departures over %.1fh",
            sum(1 for f in schedule if f["flight_type"] == "arrival"),
            sum(1 for f in schedule if f["flight_type"] == "departure"),
            duration_h,
        )

    def _inject_traffic_modifiers(self) -> None:
        """Inject extra flights from scenario traffic modifiers into the schedule."""
        if not self.scenario:
            return
        start = self.config.effective_start_time()
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
                airline_code, airline_name = _select_airline()
                origin = mod.diversion_origin or _select_destination("arrival", airline_code)
                aircraft = _select_aircraft(origin)
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
                airline_code, airline_name = _select_airline()
                dest = _select_destination("departure", airline_code)
                aircraft = _select_aircraft(dest)
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

                    # Track flights that reach PARKED (for baggage generation)
                    if new_phase == FlightPhase.PARKED:
                        sched = self._find_schedule_entry(icao24)
                        if sched:
                            self._completed_flights.append({
                                "icao24": icao24,
                                "callsign": state.callsign,
                                "schedule": sched,
                                "parked_time": self.sim_time,
                            })

                    # Go-around check: APPROACHING → LANDING transition
                    if (old_phase == FlightPhase.APPROACHING
                            and new_phase == FlightPhase.LANDING
                            and random.random() < self.capacity.go_around_probability()):
                        from src.ingestion.fallback import _release_runway
                        _release_runway(icao24, "28R")
                        new_state.phase = FlightPhase.APPROACHING
                        new_state.waypoint_index = 0
                        new_state.altitude = 2000
                        new_state.velocity = 200
                        new_state.vertical_rate = 1500
                        new_state.go_around_count += 1
                        new_state.holding_phase_time = 0.0
                        new_state.holding_inbound = True
                        self.recorder.record_scenario_event(
                            self.sim_time, "go_around",
                            f"{state.callsign} go-around #{new_state.go_around_count} ({self.capacity.current_category})",
                            {"callsign": state.callsign, "icao24": icao24,
                             "attempt": new_state.go_around_count, "weather": self.capacity.current_category},
                        )
                        if new_state.go_around_count >= 2:
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

        elif state.phase == FlightPhase.TAXI_TO_RUNWAY:
            # Jump to takeoff
            state.phase = FlightPhase.TAKEOFF
            state.takeoff_subphase = "lineup"
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
            from src.ingestion.fallback import _is_runway_clear, _occupy_runway
            if _is_runway_clear("28R"):
                state.phase = FlightPhase.LANDING
                state.waypoint_index = 0
                _occupy_runway(icao24, "28R")
                self._phase_time[icao24] = ("landing", 0.0)
            else:
                # Runway still blocked — reset timer to check again in 5 min
                self._phase_time[icao24] = ("approaching", 600.0)

        elif state.phase == FlightPhase.LANDING:
            # Force taxi
            state.altitude = 0
            state.on_ground = True
            state.phase = FlightPhase.TAXI_TO_GATE
            state.waypoint_index = 0
            _release_runway(icao24, "28R")
            if not state.assigned_gate:
                gate = _find_available_gate()
                if gate:
                    state.assigned_gate = gate
                    _occupy_gate(icao24, gate)
            self._phase_time[icao24] = ("taxi_to_gate", 0.0)

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
                self.recorder.record_position(
                    self.sim_time, icao24, state.callsign,
                    state.latitude, state.longitude, state.altitude,
                    state.velocity, state.heading, state.phase.value,
                    state.on_ground, state.aircraft_type, state.assigned_gate,
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
            # 0. Process scenario events at current sim_time
            if self.scenario:
                self._process_scenario_events()

            # 1. Spawn scheduled flights
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

            # 5. Advance time
            self.sim_time += timedelta(seconds=dt)
            tick += 1

            # 6. Progress
            self._print_progress()

        # Enrich schedule with actual spawn times for metrics
        for idx, flight in enumerate(self.flight_schedule):
            flight["actual_spawn_time"] = self._spawn_times[idx].isoformat() if idx in self._spawn_times else None
            flight["spawned"] = idx in self._spawned_indices

        elapsed_wall = wall_time.time() - start_wall
        print(f"\n  Completed in {elapsed_wall:.1f}s wall time")
        print(f"  Speed: {self.config.effective_duration_hours() * 3600 / max(elapsed_wall, 0.001):.0f}x real-time")

        return self.recorder

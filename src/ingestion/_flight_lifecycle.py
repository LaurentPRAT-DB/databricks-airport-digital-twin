"""Flight lifecycle: creation, state machine updates, calibration, and helpers."""

import logging
import math
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

from src.simulation.diagnostics import diag_log
from src.simulation.openap_profiles import (
    get_descent_profile,
    get_climb_profile,
    interpolate_profile,
)
from src.ml.gse_model import get_turnaround_timing, get_aircraft_category, PHASE_DEPENDENCIES

import src.ingestion._state as _st
from src.ingestion._state import (
    FlightPhase,
    FlightState,
    _flights_by_phase,
    _flight_states,
    _set_phase,
    MAX_APPROACH_AIRCRAFT,
    get_max_approach_aircraft,
    _gate_states,
)
from src.ingestion._constants import (
    AIRLINE_TURNAROUND_FACTOR,
    _DEFAULT_AIRLINE_FACTOR,
    _AIRPORT_COUNTRY,
    VREF_SPEEDS,
    _DEFAULT_VREF,
    NM_TO_DEG,
    _KTS_TO_DEG_PER_SEC,
    TAXI_SPEED_STRAIGHT_KTS,
    TAXI_SPEED_RAMP_KTS,
    TAXI_SPEED_PUSHBACK_KTS,
    MAX_SPEED_BELOW_FL100_KTS,
    MAX_VELOCITY_KTS,
    DECISION_HEIGHT_FT,
    TAKEOFF_PERFORMANCE,
    _DEFAULT_TAKEOFF_PERF,
    DEPARTURE_SEPARATION_S,
    DEFAULT_DEPARTURE_SEPARATION_S,
    MIN_TAXI_SEPARATION_DEG,
    AIRLINE_FLEET,
    CALLSIGN_PREFIXES,
)
from src.ingestion._geo import (
    _calculate_heading,
    _smooth_heading,
    _distance_between,
    _distance_nm,
    _move_toward,
    _interpolate_altitude,
    _point_on_circle,
    _offset_position_by_heading,
)
from src.ingestion._event_buffers import (
    emit_phase_transition,
    emit_gate_event,
    emit_turnaround_event,
)
from src.ingestion._runway_ops import (
    _get_runway_state,
    _get_departure_runway_name,
    _init_gate_states,
    _get_wake_category,
    _get_required_separation,
    _find_aircraft_ahead_on_approach,
    _find_last_aircraft_on_approach,
    _check_approach_separation,
    _is_runway_clear,
    _is_arrival_separation_met,
    _occupy_runway,
    _release_runway,
    _find_available_gate,
    _find_overflow_gate,
    _occupy_gate,
    _release_gate,
    _check_taxi_separation,
    _taxi_speed_factor,
    _count_aircraft_in_phase,
    _get_approach_queue_position,
)
from src.ingestion._approach_departure import (
    _get_approach_waypoints,
    _get_departure_waypoints,
    _get_runway_threshold,
    _get_runway_heading,
    _get_osm_primary_runway,
    _osm_runway_endpoints,
    _get_fallback_runway,
    _get_arrival_runway_name,
    _get_departure_runway,
    _get_takeoff_runway_geometry,
    _get_star_name,
    _get_sid_name,
    _snap_to_nearest_waypoint,
    _bearing_from_airport,
    _bearing_to_airport,
)
from src.ingestion._taxi_routing import (
    _get_taxi_waypoints_arrival,
    _get_taxi_waypoints_departure,
    _get_pushback_heading,
    _compute_gate_standoff,
    _get_parked_heading,
)


# Calibration override: when set (> 0), the physics turnaround uses this
# median gate time (in minutes) from BTS OTP data instead of the GSE model's
# nominal timing.  The simulation engine populates this from the airport profile.
_calibration_gate_minutes: float = 0.0


def set_calibration_gate_minutes(minutes: float) -> None:
    """Set calibrated median gate turnaround time (minutes). 0 disables."""
    global _calibration_gate_minutes
    _calibration_gate_minutes = minutes


# Calibration: BTS taxi-out mean time in seconds.  When set (> 0), the
# taxi_to_runway phase adds a departure-queue hold so total taxi-out duration
# (waypoint travel + hold) matches the real-world BTS mean.
_calibration_taxi_out_target_s: float = 0.0
# Estimated seconds the waypoint path alone takes (set once per airport).
_calibration_taxi_out_waypoint_s: float = 0.0


def set_calibration_taxi_out(mean_minutes: float, waypoint_travel_s: float = 180.0) -> None:
    """Set calibrated taxi-out target from BTS OTP data.

    Args:
        mean_minutes: BTS mean taxi-out time in minutes (e.g. 20.1 for SFO).
        waypoint_travel_s: estimated seconds the sim's waypoint path takes
            without any hold (default 180s ~ 3 min at 25 kts over 5 waypoints).
    """
    global _calibration_taxi_out_target_s, _calibration_taxi_out_waypoint_s
    _calibration_taxi_out_target_s = mean_minutes * 60.0
    _calibration_taxi_out_waypoint_s = waypoint_travel_s


# Calibration: BTS taxi-in mean time in seconds.  When set (> 0), the
# taxi_to_gate phase adds an arrival hold so total taxi-in duration
# (waypoint travel + hold) matches the real-world BTS mean.
_calibration_taxi_in_target_s: float = 0.0
_calibration_taxi_in_waypoint_s: float = 0.0


def set_calibration_taxi_in(mean_minutes: float, waypoint_travel_s: float = 120.0) -> None:
    """Set calibrated taxi-in target from BTS OTP data.

    Args:
        mean_minutes: BTS mean taxi-in time in minutes (e.g. 7.6 for SFO).
        waypoint_travel_s: estimated seconds the sim's waypoint path takes
            without any hold (default 120s ~ 2 min at 30 kts inbound).
    """
    global _calibration_taxi_in_target_s, _calibration_taxi_in_waypoint_s
    _calibration_taxi_in_target_s = mean_minutes * 60.0
    _calibration_taxi_in_waypoint_s = waypoint_travel_s


# ============================================================================
# WEATHER STATE — updated by simulation engine each weather tick
# ============================================================================

_current_weather: Dict[str, float] = {"wind_speed_kts": 0.0, "visibility_sm": 10.0}


def set_current_weather(wind_speed_kts: float, visibility_sm: float) -> None:
    """Called by simulation engine after each weather update."""
    _current_weather["wind_speed_kts"] = wind_speed_kts
    _current_weather["visibility_sm"] = visibility_sm


def _get_turnaround_weather_factor() -> float:
    """Weather impact on ground handling operations.

    High winds slow fueling/cargo; low visibility slows ramp movement.
    """
    factor = 1.0
    wind = _current_weather.get("wind_speed_kts", 0.0)
    vis = _current_weather.get("visibility_sm", 10.0)

    if wind > 50:
        factor += 0.25
    elif wind > 35:
        factor += 0.15
    elif wind > 25:
        factor += 0.05

    if vis < 0.5:
        factor += 0.15
    elif vis < 1.0:
        factor += 0.10
    elif vis < 3.0:
        factor += 0.05

    return factor




def _get_turnaround_congestion_factor() -> float:
    """More concurrent gate ops = longer turnaround due to crew contention."""
    return 1.0 + 0.01 * max(0, _st._occupied_gate_count - 10)


def _get_turnaround_day_of_week_factor() -> float:
    """Weekend turnarounds are ~5% slower (fewer ground crew on roster)."""
    dow = datetime.now(timezone.utc).weekday()
    if dow >= 5:  # Saturday or Sunday
        return 1.05
    return 1.0


def _get_turnaround_international_factor(state: "FlightState") -> float:
    """International flights have longer turnarounds (+25%)."""
    from src.ingestion.fallback import get_current_airport_iata
    origin = state.origin_airport or ""
    dest = state.destination_airport or ""
    local = get_current_airport_iata()
    other = dest if origin == local else origin
    if _is_international_airport(other):
        return 1.25
    return 1.0

# ============================================================================
# GATE-KEYED INBOUND DELAY TRACKING (for reactionary delay prediction)
# ============================================================================

_gate_last_delay: Dict[str, float] = {}


def get_gate_last_delay(gate_id: str) -> float:
    """Return the delay of the last inbound flight at this gate (minutes)."""
    return _gate_last_delay.get(gate_id, 0.0)


def get_airport_load_ratio() -> float:
    """Return current airport load ratio: active flights / nominal capacity.

    Derives capacity from gate count (same logic as generate_synthetic_flights).
    """
    from src.ingestion.fallback import get_gates
    active = len(_flight_states)
    gate_count = len(get_gates())
    capacity = max(15, int(gate_count * 1.5)) if gate_count > 0 else 50
    return active / capacity


def _get_aircraft_type_for_airline(callsign: str, is_international: bool = False) -> str:
    """Get a random aircraft type based on airline callsign and route type.

    Uses calibrated fleet mix from the airport profile when available.
    """
    airline_code = callsign[:3].upper() if callsign and len(callsign) >= 3 else None

    # Easter egg: Ukrainian Air Force gets fighter jets
    if airline_code == "UAF":
        return random.choice(["F16", "F15", "F22", "F35"])

    # Try calibrated fleet mix first
    if airline_code:
        profile = _get_current_airport_profile()
        if profile and airline_code in profile.fleet_mix:
            fleet = profile.fleet_mix[airline_code]
            if fleet:
                types = list(fleet.keys())
                weights = list(fleet.values())
                return random.choices(types, weights=weights, k=1)[0]

    # Fall back to hardcoded AIRLINE_FLEET
    if airline_code and airline_code in AIRLINE_FLEET:
        fleet = AIRLINE_FLEET[airline_code]
        if is_international:
            wide_body = [a for a in fleet if a in ("B777", "B787", "A330", "A350", "A380", "A345")]
            if wide_body:
                return random.choice(wide_body)
        return random.choice(fleet)
    if is_international:
        return random.choice(["B777", "B787", "A350", "A330"])
    return random.choice(["A320", "B738", "A321", "B737"])



def _is_international_airport(iata: str) -> bool:
    """Check if an airport code is in the international list."""
    from src.ingestion.schedule_generator import INTERNATIONAL_AIRPORTS
    return iata in INTERNATIONAL_AIRPORTS


# Country lookup for origin_country field


def _get_origin_country(origin_iata: Optional[str]) -> str:
    """Get the country for an airport IATA code."""
    if origin_iata:
        from src.ingestion.airport_table import get_country_name
        name = get_country_name(origin_iata)
        if name != "Unknown":
            return name
        # Fallback to legacy dict for any codes not in the global table
        if origin_iata in _AIRPORT_COUNTRY:
            return _AIRPORT_COUNTRY[origin_iata]
    return "United States"


def _get_current_airport_profile():
    """Get the calibrated profile for the current airport (cached, lazy-loaded)."""
    from src.ingestion.fallback import get_current_airport_iata
    from src.ingestion.schedule_generator import _get_profile_loader
    return _get_profile_loader().get_profile(get_current_airport_iata())


def _pick_random_airport(exclude: Optional[str] = None) -> str:
    """Pick a random airport, excluding the specified one (typically the local airport).

    Uses calibrated route shares from the airport profile when available.
    """
    profile = _get_current_airport_profile()

    if profile and (profile.domestic_route_shares or profile.international_route_shares):
        is_domestic = random.random() < profile.domestic_ratio
        if is_domestic and profile.domestic_route_shares:
            routes = {k: v for k, v in profile.domestic_route_shares.items() if k != exclude}
            if routes:
                return random.choices(list(routes.keys()), weights=list(routes.values()), k=1)[0]
        if profile.international_route_shares:
            routes = {k: v for k, v in profile.international_route_shares.items() if k != exclude}
            if routes:
                return random.choices(list(routes.keys()), weights=list(routes.values()), k=1)[0]

    from src.ingestion.fallback import get_current_airport_iata
    from src.ingestion.schedule_generator import get_nearby_airports, INTERNATIONAL_AIRPORTS
    local_iata = get_current_airport_iata()
    nearby, far = get_nearby_airports(local_iata)
    if random.random() < 0.7:
        pool = [a for a in nearby if a != exclude]
    else:
        pool = [a for a in far if a != exclude]
    if not pool:
        pool = [a for a in INTERNATIONAL_AIRPORTS if a != exclude] or INTERNATIONAL_AIRPORTS
    return random.choice(pool)


def _pick_random_origin() -> str:
    """Pick a random origin airport for arriving flights (never the local airport)."""
    from src.ingestion.fallback import get_current_airport_iata
    return _pick_random_airport(exclude=get_current_airport_iata())


def _pick_random_destination() -> str:
    """Pick a random destination airport for departing flights (never the local airport)."""
    from src.ingestion.fallback import get_current_airport_iata
    return _pick_random_airport(exclude=get_current_airport_iata())


# Gate-relevant turnaround phases in DAG order (excludes taxi/pushback sim phases)
_GATE_PHASES = [
    "chocks_on", "deboarding", "unloading", "cleaning",
    "catering", "refueling", "loading", "boarding", "chocks_off",
]


def _build_turnaround_schedule(
    aircraft_type: str,
    airline_code: str,
    combined_factor: float,
) -> Dict[str, Dict]:
    """Build a critical-path turnaround schedule for gate sub-phases.

    Returns dict: {phase_name: {"start_offset_s", "duration_s", "done", "started"}}
    All times are in seconds relative to PARKED entry (time_at_gate=0).
    """
    timing = get_turnaround_timing(aircraft_type)
    phases = timing["phases"]

    # Compute jittered durations (minutes) for gate phases only
    jittered: Dict[str, float] = {}
    for phase in _GATE_PHASES:
        nominal = phases.get(phase, 5)
        jittered[phase] = nominal * combined_factor * random.uniform(0.9, 1.1)

    # Critical-path scheduling: earliest start = max finish of dependencies
    finish: Dict[str, float] = {}
    start: Dict[str, float] = {}
    for phase in _GATE_PHASES:
        deps = PHASE_DEPENDENCIES.get(phase, [])
        # Only consider deps that are also gate phases
        earliest_start = max(
            (finish[d] for d in deps if d in finish),
            default=0.0,
        )
        start[phase] = earliest_start
        finish[phase] = earliest_start + jittered[phase]

    # Convert to seconds and build schedule dict
    schedule: Dict[str, Dict] = {}
    for phase in _GATE_PHASES:
        schedule[phase] = {
            "start_offset_s": start[phase] * 60,
            "duration_s": jittered[phase] * 60,
            "done": False,
            "started": False,
        }

    return schedule


def _create_new_flight(
    icao24: str, callsign: str, phase: FlightPhase,
    origin: Optional[str] = None, destination: Optional[str] = None,
) -> FlightState:
    """Create a new flight in the specified phase with proper separation."""
    from src.ingestion.fallback import get_airport_center, get_current_airport_iata, get_gates
    is_intl = _is_international_airport(origin or "") or _is_international_airport(destination or "")
    aircraft_type = _get_aircraft_type_for_airline(callsign, is_international=is_intl)

    if phase == FlightPhase.APPROACHING:
        # Start on approach from the origin direction WITH PROPER WAKE TURBULENCE SEPARATION
        approach_wps_full = _get_approach_waypoints(origin)
        # Skip transition waypoints (high-altitude lead-in) for the spawn point;
        # first aircraft starts at the STAR corridor entry, not 24 NM out.
        n_trans = max(0, len(approach_wps_full) - 7)  # everything before the 7 final-approach waypoints
        base_wp = approach_wps_full[max(0, n_trans)]
        center = get_airport_center()

        # Find how many aircraft are already approaching
        approaching_count = _count_aircraft_in_phase(FlightPhase.APPROACHING)
        landing_count = _count_aircraft_in_phase(FlightPhase.LANDING)

        # Limit simultaneous approaches (scaled to airport runway count)
        if approaching_count + landing_count >= get_max_approach_aircraft():
            # Too many on approach - start as enroute instead
            return _create_new_flight(icao24, callsign, FlightPhase.ENROUTE, origin=origin, destination=destination)

        # Calculate position based on actual aircraft positions (not just count)
        last_aircraft = _find_last_aircraft_on_approach()

        if last_aircraft is None:
            # No aircraft on approach - start at base waypoint
            lat = base_wp[1] + random.uniform(-0.005, 0.005)
            lon = base_wp[0]
            alt = base_wp[2]
        else:
            # Calculate required separation based on wake turbulence categories
            required_sep_deg = _get_required_separation(
                last_aircraft.aircraft_type,
                aircraft_type
            )
            required_sep_deg *= 1.2

            # Position new aircraft behind the last one (further from airport center)
            dir_from_center = _calculate_heading(
                center, (last_aircraft.latitude, last_aircraft.longitude)
            )
            new_pos = _point_on_circle(
                last_aircraft.latitude, last_aircraft.longitude,
                dir_from_center, required_sep_deg
            )
            lat = new_pos[0] + random.uniform(-0.005, 0.005)
            lon = new_pos[1]
            alt = max(last_aircraft.altitude + 500, 600)

        # Pre-assign a gate so it shows as INBOUND on the gate status panel
        _init_gate_states()
        pre_gate = _find_available_gate()
        if pre_gate:
            _occupy_gate(icao24, pre_gate)

        # Snap waypoint_index to the closest approach waypoint to spawn position
        # so the aircraft doesn't chase a waypoint that's behind it
        approach_wps = _get_approach_waypoints(origin)
        best_wp_idx = 0
        if approach_wps:
            best_dist = float('inf')
            for wi, wp in enumerate(approach_wps):
                d = _distance_between((lat, lon), (wp[1], wp[0]))
                if d < best_dist:
                    best_dist = d
                    best_wp_idx = wi

        # Initialize speed from OpenAP descent profile at the spawn waypoint
        # to avoid the visible speed jump on the first tick when the profile
        # overrides the initial velocity.
        _total_wps = len(approach_wps) if approach_wps else 1
        _n_transition = max(0, _total_wps - 7)
        if _n_transition > 0 and best_wp_idx < _n_transition:
            _t = best_wp_idx / max(1, _n_transition)
            _prof_progress = 0.30 + 0.20 * _t
        else:
            _base_idx = best_wp_idx - max(0, _n_transition)
            _base_total = _total_wps - max(0, _n_transition)
            _prof_progress = 0.50 + 0.50 * (_base_idx / max(1, _base_total - 1))
        _dp = get_descent_profile(aircraft_type)
        _prof_alt, _prof_spd, _prof_vr = interpolate_profile(_dp, _prof_progress)
        vref = VREF_SPEEDS.get(aircraft_type, _DEFAULT_VREF)
        init_speed = max(vref, min(_prof_spd, MAX_SPEED_BELOW_FL100_KTS))

        return FlightState(
            icao24=icao24,
            callsign=callsign,
            latitude=lat,
            longitude=lon,
            altitude=alt + random.uniform(-30, 30),  # realistic ILS approach deviation (±30ft)
            velocity=init_speed + random.uniform(-5, 5),
            heading=_calculate_heading((lat, lon), center),
            vertical_rate=_prof_vr if _prof_vr else -800,
            on_ground=False,
            phase=phase,
            aircraft_type=aircraft_type,
            assigned_gate=pre_gate,
            waypoint_index=best_wp_idx,
            origin_airport=origin,
            destination_airport=destination,
        )

    elif phase == FlightPhase.PARKED:
        # Start at a gate, nose facing toward the nearest terminal center
        _init_gate_states()

        # Find an available gate
        gate = _find_available_gate()
        if gate is None:
            # All gates occupied - switch to approaching or enroute
            return _create_new_flight(icao24, callsign, FlightPhase.APPROACHING, origin=origin, destination=destination)

        lat, lon = get_gates()[gate]
        _occupy_gate(icao24, gate)
        emit_gate_event(icao24, callsign, gate, "occupy", aircraft_type)

        # Compute heading toward nearest terminal (or airport center as fallback)
        parked_heading = _get_parked_heading(lat, lon)

        # Offset aircraft away from terminal based on OSM geometry + aircraft dimensions
        standoff = _compute_gate_standoff(lat, lon, parked_heading, aircraft_type)
        lat, lon = _offset_position_by_heading(lat, lon, parked_heading, standoff)

        initial_time_at_gate = random.uniform(0, 300)  # 0-5 min pre-parked time

        # Build turnaround schedule and pre-advance to match elapsed time
        airline_code = callsign[:3] if callsign and len(callsign) >= 3 else ""
        combined_factor = AIRLINE_TURNAROUND_FACTOR.get(airline_code, _DEFAULT_AIRLINE_FACTOR)
        schedule = _build_turnaround_schedule(aircraft_type, airline_code, combined_factor)
        # Pre-advance phases that would already be started/done given initial_time_at_gate
        current_phase = ""
        for p_name in _GATE_PHASES:
            info = schedule[p_name]
            if initial_time_at_gate >= info["start_offset_s"] + info["duration_s"]:
                info["done"] = True
                info["started"] = True
            elif initial_time_at_gate >= info["start_offset_s"]:
                info["started"] = True
                current_phase = p_name
        if not current_phase:
            # Find first not-yet-started phase
            for p_name in _GATE_PHASES:
                if not schedule[p_name]["done"]:
                    current_phase = p_name
                    break

        return FlightState(
            icao24=icao24,
            callsign=callsign,
            latitude=lat,
            longitude=lon,
            altitude=0,
            velocity=0,
            heading=parked_heading,
            vertical_rate=0,
            on_ground=True,
            phase=phase,
            aircraft_type=aircraft_type,
            assigned_gate=gate,
            time_at_gate=initial_time_at_gate,
            origin_airport=origin,
            destination_airport=destination,
            landed_at=time.time() - initial_time_at_gate - 5 * 60,  # ~5 min taxi before parking
            parked_since=time.time() - initial_time_at_gate,
            turnaround_phase=current_phase,
            turnaround_schedule=schedule,
        )

    elif phase == FlightPhase.ENROUTE:
        # Spawn on edge of visibility circle at bearing from origin airport
        VISIBILITY_RADIUS_DEG = 0.4  # ~25 NM

        if origin:
            # Arriving flight: spawn at correct inbound bearing
            bearing_to_sfo = _bearing_from_airport(origin)
            # The aircraft appears FROM that bearing, so spawn on the circle at the reciprocal
            spawn_bearing = (bearing_to_sfo + 180) % 360
            center = get_airport_center()
            spawn_point = _point_on_circle(
                center[0], center[1],
                spawn_bearing,
                VISIBILITY_RADIUS_DEG + random.uniform(-0.05, 0.05),
            )
            lat, lon = spawn_point
            heading = _calculate_heading((lat, lon), center)
            # International = higher altitude
            alt = random.uniform(33000, 43000) if is_intl else random.uniform(28000, 39000)
        elif destination:
            # Departing flight that's already enroute: heading toward destination
            bearing = _bearing_to_airport(destination)
            # Spawn somewhere between airport and edge of circle
            dist = random.uniform(0.1, 0.3)
            center = get_airport_center()
            spawn_point = _point_on_circle(
                center[0], center[1], bearing, dist,
            )
            lat, lon = spawn_point
            heading = bearing + random.uniform(-5, 5)
            # Departing enroute: spawn at mid-climb altitude (visible as climbing)
            alt = random.uniform(10000, 25000)
        else:
            # No origin/destination — random position on the circle edge
            center = get_airport_center()
            bearing = random.uniform(0, 360)
            spawn_point = _point_on_circle(
                center[0], center[1],
                bearing,
                VISIBILITY_RADIUS_DEG + random.uniform(-0.1, 0.0),
            )
            lat, lon = spawn_point
            heading = _calculate_heading((lat, lon), center)
            # Hemispheric rule (ICAO): eastbound (0-179°) → odd FL, westbound (180-359°) → even FL
            if heading < 180:
                alt = random.choice([29000, 31000, 33000, 35000, 37000, 39000])  # odd FLs
            else:
                alt = random.choice([28000, 30000, 32000, 34000, 36000, 38000])  # even FLs

        # Departing enroute flights climb; arriving ones descend
        _is_departing_enroute = destination is not None and origin is None
        if _is_departing_enroute:
            vrate = random.uniform(800, 2000)  # Climbing
            vel = random.uniform(280, 400)
        else:
            vrate = random.uniform(-500, -100)  # Descending toward airport
            vel = random.uniform(400, 500)

        return FlightState(
            icao24=icao24,
            callsign=callsign,
            latitude=lat,
            longitude=lon,
            altitude=alt,
            velocity=vel,
            heading=heading,
            vertical_rate=vrate,
            on_ground=False,
            phase=phase,
            aircraft_type=aircraft_type,
            origin_airport=origin,
            destination_airport=destination,
        )

    elif phase == FlightPhase.TAXI_TO_GATE:
        # Just landed, taxiing from runway
        _init_gate_states()

        # Check if runway is occupied - if so, can't spawn here
        arrival_rwy = _get_arrival_runway_name()
        if not _is_runway_clear(arrival_rwy):
            return _create_new_flight(icao24, callsign, FlightPhase.APPROACHING, origin=origin, destination=destination)

        gate = _find_available_gate()
        if gate is None:
            # No gates available
            return _create_new_flight(icao24, callsign, FlightPhase.ENROUTE, origin=origin, destination=destination)

        # Compute taxi route from runway to gate (uses OSM graph when available)
        taxi_route = _get_taxi_waypoints_arrival(gate)
        wp = taxi_route[0]
        spawn_pos = (wp[1], wp[0])  # lat, lon

        # Check if taxiway start position is clear (no other taxiing aircraft)
        _taxi_ids = _flights_by_phase[FlightPhase.TAXI_TO_GATE] | _flights_by_phase[FlightPhase.TAXI_TO_RUNWAY]
        for other_icao24 in _taxi_ids:
            other = _flight_states.get(other_icao24)
            if other is not None:
                dist = _distance_between(spawn_pos, (other.latitude, other.longitude))
                if dist < MIN_TAXI_SEPARATION_DEG * 2:  # Buffer for spawn position
                    # Taxiway congested - spawn as approaching instead
                    return _create_new_flight(icao24, callsign, FlightPhase.APPROACHING, origin=origin, destination=destination)

        _occupy_gate(icao24, gate)

        # Heading toward second waypoint (or gate if only one wp)
        if len(taxi_route) >= 2:
            heading = _calculate_heading(spawn_pos, (taxi_route[1][1], taxi_route[1][0]))
        else:
            heading = _calculate_heading(spawn_pos, get_gates()[gate])

        return FlightState(
            icao24=icao24,
            callsign=callsign,
            latitude=wp[1],
            longitude=wp[0],
            altitude=0,
            velocity=15,
            heading=heading,
            vertical_rate=0,
            on_ground=True,
            phase=phase,
            aircraft_type=aircraft_type,
            assigned_gate=gate,
            waypoint_index=0,
            origin_airport=origin,
            destination_airport=destination,
            taxi_route=taxi_route,
        )

    elif phase == FlightPhase.TAXI_TO_RUNWAY:
        # Departing, starting from a gate position
        _init_gate_states()

        # Find an available gate for the departing aircraft
        gate = _find_available_gate()
        if gate is None:
            # All gates occupied - can't spawn departing aircraft
            return _create_new_flight(icao24, callsign, FlightPhase.ENROUTE, origin=origin, destination=destination)

        lat, lon = get_gates()[gate]
        _occupy_gate(icao24, gate)

        # Compute departure taxi route from gate to runway (uses OSM graph when available)
        taxi_route = _get_taxi_waypoints_departure(gate)

        # Heading toward first departure waypoint
        if taxi_route:
            heading = _calculate_heading((lat, lon), (taxi_route[0][1], taxi_route[0][0]))
        else:
            heading = 180  # Fallback: south

        return FlightState(
            icao24=icao24,
            callsign=callsign,
            latitude=lat,
            longitude=lon,
            altitude=0,
            velocity=10,
            heading=heading,
            vertical_rate=0,
            on_ground=True,
            phase=phase,
            aircraft_type=aircraft_type,
            assigned_gate=gate,
            waypoint_index=0,
            origin_airport=origin,
            destination_airport=destination,
            taxi_route=taxi_route,
        )

    # Default: random enroute
    return _create_new_flight(icao24, callsign, FlightPhase.ENROUTE, origin=origin, destination=destination)


def _update_flight_state(state: FlightState, dt: float) -> FlightState:
    """Update a flight's state based on its current phase.

    Implements FAA/ICAO separation standards:
    - Approach: 3-6 NM based on wake turbulence category
    - Runway: Single occupancy (one aircraft at a time)
    - Taxi: Visual separation (~150-300 ft)
    """
    from src.ingestion.fallback import get_airport_center, get_current_airport_iata, get_gates, TAXI_WAYPOINTS_ARRIVAL, TAXI_WAYPOINTS_DEPARTURE

    if state.phase == FlightPhase.APPROACHING:
        # Descend toward airport following approach waypoints WITH SEPARATION
        # Primary transition trigger: altitude <= DECISION_HEIGHT_FT (Cat I ILS DA)
        # Safety fallback: waypoint exhaustion
        approach_wps = _get_approach_waypoints(state.origin_airport)

        # Helper: execute go-around (missed approach procedure)
        # Transitions to ENROUTE so the aircraft flies FORWARD (on runway heading),
        # climbs to missed approach altitude, then re-sequences via the holding
        # pattern / approach capacity logic — instead of flying backward to wp 0.
        def _execute_go_around(reason: str = "runway_busy") -> None:
            state.go_around_count += 1
            state.holding_phase_time = 0.0
            state.holding_inbound = True

            # After 3+ go-arounds, transition to enroute for engine diversion.
            # Don't force-land — the aircraft may not be aligned with the runway.
            if state.go_around_count >= 3:
                emit_phase_transition(
                    state.icao24, state.callsign,
                    FlightPhase.APPROACHING.value, FlightPhase.ENROUTE.value,
                    state.latitude, state.longitude, state.altitude,
                    state.aircraft_type, state.assigned_gate,
                )
                _set_phase(state, FlightPhase.ENROUTE)
                state.waypoint_index = 0
                state.go_around_target_alt = max(3000.0, state.altitude + 500)
                state.vertical_rate = 1500
                logger.info(
                    "GO-AROUND #%d %s (%s) — engine will divert",
                    state.go_around_count, state.callsign, state.aircraft_type,
                )
                return

            # Missed approach: climb to 3000ft AGL minimum
            state.go_around_target_alt = max(3000.0, state.altitude + 500)
            state.vertical_rate = 1500

            # Missed approach speed: gradual acceleration to Vref + 20 kts
            vref_ga = VREF_SPEEDS.get(state.aircraft_type, _DEFAULT_VREF)
            target_ga_speed = vref_ga + 20
            if target_ga_speed > state.velocity:
                state.velocity = min(target_ga_speed, state.velocity + 10)

            # Keep current heading — the aircraft is already pointing in the
            # correct approach direction from _smooth_heading during APPROACHING.
            # Don't override with _get_runway_heading() which depends on OSM
            # geoPoint ordering and could be 180° off.

            # Transition to ENROUTE which has holding pattern + re-approach logic
            emit_phase_transition(
                state.icao24, state.callsign,
                FlightPhase.APPROACHING.value, FlightPhase.ENROUTE.value,
                state.latitude, state.longitude, state.altitude,
                state.aircraft_type, state.assigned_gate,
            )
            _set_phase(state, FlightPhase.ENROUTE)
            state.waypoint_index = 0

            logger.info(
                "GO-AROUND #%d %s (%s): %s at %.0fft → ENROUTE for re-sequence",
                state.go_around_count, state.callsign, state.aircraft_type,
                reason, state.altitude,
            )
            diag_log(
                "GO_AROUND", datetime.now(timezone.utc),
                icao24=state.icao24, callsign=state.callsign,
                reason=reason, alt=state.altitude,
                count=state.go_around_count,
            )

        if state.waypoint_index < len(approach_wps):
            wp = approach_wps[state.waypoint_index]
            target = (wp[1], wp[0])  # lat, lon
            target_alt = wp[2]

            # Skip waypoints whose altitude is above current altitude,
            # but NOT when climbing back after a go-around (the climb-to-profile
            # logic handles the altitude gap gradually — skipping would jump to
            # final approach waypoints and cause a wrong-direction approach).
            if state.go_around_target_alt <= 0:
                while target_alt > state.altitude + 200 and state.waypoint_index < len(approach_wps) - 1:
                    state.waypoint_index += 1
                    wp = approach_wps[state.waypoint_index]
                    target = (wp[1], wp[0])
                    target_alt = wp[2]

            # CHECK SEPARATION before moving
            has_separation = _check_approach_separation(state)
            queue_pos = _get_approach_queue_position(state.icao24)

            if has_separation:
                # --- OpenAP-based descent profile ---
                total_wps = len(approach_wps)
                progress = state.waypoint_index / max(1, total_wps - 1)
                # Map approach progress to descent profile progress.
                # Transition waypoints (first ~3) cover the high-altitude
                # descent segment [0.30, 0.50]; base+final waypoints cover
                # the standard approach segment [0.50, 1.0].
                n_transition = max(0, len(approach_wps) - 7)
                if n_transition > 0 and state.waypoint_index < n_transition:
                    t = state.waypoint_index / max(1, n_transition)
                    profile_progress = 0.30 + 0.20 * t
                else:
                    base_idx = state.waypoint_index - max(0, n_transition)
                    base_total = total_wps - max(0, n_transition)
                    profile_progress = 0.50 + 0.50 * (base_idx / max(1, base_total - 1))
                desc_prof = get_descent_profile(state.aircraft_type)
                prof_alt, prof_spd, prof_vr = interpolate_profile(desc_prof, profile_progress)

                # Speed from profile (respect separation slow-down)
                speed_slow = 1.0
                ahead = _find_aircraft_ahead_on_approach(state)
                if ahead:
                    dist = _distance_nm((state.latitude, state.longitude),
                                       (ahead.latitude, ahead.longitude))
                    req_sep = _get_required_separation(ahead.aircraft_type, state.aircraft_type) / NM_TO_DEG
                    if dist < req_sep * 1.5:
                        speed_slow = 0.5

                # Clamp speed: altitude-aware Vref floor + 250kt below FL100
                # Smooth acceleration/deceleration (max 5 kts/s) to prevent
                # visible speed jumps in 30s snapshot intervals (A05 fix).
                vref = VREF_SPEEDS.get(state.aircraft_type, _DEFAULT_VREF)
                speed_ceiling = MAX_SPEED_BELOW_FL100_KTS if state.altitude < 10000 else MAX_VELOCITY_KTS
                raw_speed = min(prof_spd * speed_slow, speed_ceiling)
                if state.altitude < 1000:
                    # Below 1000ft: hard ceiling at Vref + 30 (stabilized approach)
                    target_speed = min(vref + 30, max(vref, raw_speed))
                    # Hard-clamp: aircraft must be stabilized below 1000ft
                    state.velocity = min(state.velocity, vref + 30)
                elif state.altitude < 3000:
                    # 1000-3000ft: cap at Vref + 50 (configuring for landing)
                    target_speed = min(vref + 50, max(vref, raw_speed))
                else:
                    target_speed = max(vref * 0.9, raw_speed)
                # Below 3000ft: faster deceleration to enforce stabilized approach
                decel_rate = 10.0 if state.altitude < 3000 else 5.0
                max_speed_change = decel_rate * dt
                if target_speed > state.velocity:
                    state.velocity = min(target_speed, state.velocity + 5.0 * dt)
                elif target_speed < state.velocity:
                    state.velocity = max(target_speed, state.velocity - max_speed_change)

                # Move based on actual velocity
                speed_deg = state.velocity * _KTS_TO_DEG_PER_SEC * dt
                dist_to_wp = _distance_between((state.latitude, state.longitude), target)
                if dist_to_wp > 1e-8:
                    dlat = target[0] - state.latitude
                    dlon = target[1] - state.longitude
                    ratio = min(speed_deg / dist_to_wp, 1.0)
                    state.latitude += dlat * ratio
                    state.longitude += dlon * ratio

                # Go-around climb: if target alt is set, climb gradually (O05 fix)
                if state.go_around_target_alt > 0 and state.altitude < state.go_around_target_alt:
                    climb_fps = 25.0  # ~1500 ft/min
                    state.altitude = min(state.go_around_target_alt, state.altitude + climb_fps * dt)
                    state.vertical_rate = 1500
                    if state.altitude >= state.go_around_target_alt:
                        state.go_around_target_alt = 0.0  # Done climbing, resume descent
                else:
                    # Altitude from profile — use OpenAP vertical rate (ft/min→ft/s).
                    # Bounded to 12-20 ft/s (720-1200 fpm) to match realistic
                    # ILS glideslope rates and keep 30s snapshot jumps ≤ 600ft.
                    state.go_around_target_alt = 0.0
                    descent_fps = max(12.0, min(20.0, abs(prof_vr) / 60.0)) if prof_vr else 12.0
                    effective_target = min(prof_alt, target_alt)
                    prev_alt = state.altitude
                    state.altitude = max(float(DECISION_HEIGHT_FT), _interpolate_altitude(state.altitude, effective_target, descent_fps * dt))
                    # Set vertical_rate to match actual altitude direction (O05 fix):
                    # after go-around, waypoint target may be higher than current alt,
                    # causing a climb. Report positive vrate so snapshots are consistent.
                    if state.altitude > prev_alt:
                        state.vertical_rate = abs(prof_vr) if prof_vr else 1500
                    else:
                        state.vertical_rate = prof_vr

                # P1: Decision height-based approach→landing transition
                # Transition when altitude at or below Cat I ILS decision height
                # AND runway is clear. If busy, aircraft continues to waypoint
                # exhaustion where the holding pattern handles the wait.
                if state.altitude <= DECISION_HEIGHT_FT:
                    arrival_rwy = _get_arrival_runway_name()
                    # Priority landing: after 2+ go-arounds, bypass runway-clear check
                    # but still enforce arrival separation to prevent bunched landings
                    runway_ok = (
                        (_is_runway_clear(arrival_rwy) or state.go_around_count >= 2)
                        and _is_arrival_separation_met(arrival_rwy)
                    )
                    if runway_ok:
                        emit_phase_transition(
                            state.icao24, state.callsign,
                            FlightPhase.APPROACHING.value, FlightPhase.LANDING.value,
                            state.latitude, state.longitude, state.altitude,
                            state.aircraft_type, state.assigned_gate,
                        )
                        _set_phase(state, FlightPhase.LANDING)
                        state.waypoint_index = 0
                        _occupy_runway(state.icao24, arrival_rwy)
                        _get_runway_state(arrival_rwy).last_arrival_time = time.time()
                    else:
                        # P2: Runway busy at decision height → go-around
                        _execute_go_around("runway_busy")
                        return state
            else:
                # Too close to aircraft ahead - slow down but keep creeping forward
                # so the map marker doesn't freeze in place (A03 stuck marker fix)
                vref = VREF_SPEEDS.get(state.aircraft_type, _DEFAULT_VREF)
                # Smooth deceleration: max 5 kts/s (matches accel rate in A05 fix)
                state.velocity = max(vref * 0.7, state.velocity - 5.0 * dt)
                state.vertical_rate = -200
                # Creep forward at reduced speed to avoid stuck markers
                creep_deg = state.velocity * 0.3 * _KTS_TO_DEG_PER_SEC * dt
                dist_to_wp = _distance_between((state.latitude, state.longitude), target)
                if dist_to_wp > 1e-8:
                    dlat = target[0] - state.latitude
                    dlon = target[1] - state.longitude
                    ratio = min(creep_deg / dist_to_wp, 0.3)
                    state.latitude += dlat * ratio
                    state.longitude += dlon * ratio

            # Smooth heading toward waypoint (max 3°/s standard rate turn)
            target_hdg = _calculate_heading((state.latitude, state.longitude), target)
            state.heading = _smooth_heading(state.heading, target_hdg, 3.0, dt)

            # Check if reached waypoint
            if _distance_between((state.latitude, state.longitude), target) < 0.003:
                state.waypoint_index += 1
                # Immediately aim toward the NEXT waypoint to prevent zigzag.
                # Without this, heading was computed toward the just-reached
                # waypoint (distance ≈ 0) which returns a degenerate 0° bearing,
                # swinging the heading ~90° off course every other tick.
                if state.waypoint_index < len(approach_wps):
                    next_wp = approach_wps[state.waypoint_index]
                    next_target = (next_wp[1], next_wp[0])
                    next_hdg = _calculate_heading(
                        (state.latitude, state.longitude), next_target
                    )
                    state.heading = _smooth_heading(state.heading, next_hdg, 3.0, dt)
        else:
            # Safety fallback: waypoint exhaustion
            if state.altitude > 1000 and state.go_around_count < 2:
                # Still too high — go around rather than starting landing from altitude
                _execute_go_around("high_altitude_at_threshold")
            else:
                arrival_rwy = _get_arrival_runway_name()
                runway_ok = (
                    (_is_runway_clear(arrival_rwy) or state.go_around_count >= 2)
                    and _is_arrival_separation_met(arrival_rwy)
                )
                if runway_ok:
                    emit_phase_transition(
                        state.icao24, state.callsign,
                        FlightPhase.APPROACHING.value, FlightPhase.LANDING.value,
                        state.latitude, state.longitude, state.altitude,
                        state.aircraft_type, state.assigned_gate,
                    )
                    _set_phase(state, FlightPhase.LANDING)
                    state.waypoint_index = 0
                    _occupy_runway(state.icao24, arrival_rwy)
                    _get_runway_state(arrival_rwy).last_arrival_time = time.time()
                else:
                    _execute_go_around("runway_busy_at_threshold")

    elif state.phase == FlightPhase.LANDING:
        # Final touchdown sequence - land on active arrival runway
        # Runway should already be marked as occupied
        thr = _get_runway_threshold()
        if thr:
            runway_touchdown = (thr[1], thr[0])  # lat, lon
        else:
            fb = _get_fallback_runway()
            runway_touchdown = (fb[0][1], fb[0][0])  # lat, lon

        # Get runway far end for rollout direction (aircraft rolls past threshold)
        rwy_data = _get_osm_primary_runway()
        if rwy_data:
            _, far_end_lonlat, rwy_hdg = _osm_runway_endpoints(rwy_data)
            runway_far_end = (far_end_lonlat[1], far_end_lonlat[0])  # lat, lon
        else:
            fb = _get_fallback_runway()
            runway_far_end = (fb[1][1], fb[1][0])  # far end (lat, lon)
            rwy_hdg = fb[2]

        # Cap speed at Vref + 10 (stabilized approach).
        # After go-arounds, aircraft may re-enter approach too fast.
        vref = VREF_SPEEDS.get(state.aircraft_type, _DEFAULT_VREF)
        max_landing_speed = vref + 10
        if state.velocity > max_landing_speed:
            state.velocity = max_landing_speed

        # Aircraft movement during landing phase
        speed_deg = state.velocity * _KTS_TO_DEG_PER_SEC * dt
        state.heading = rwy_hdg

        if state.altitude > 0:
            # Airborne flare: converge toward runway threshold
            dist_to_thr = _distance_between((state.latitude, state.longitude), runway_touchdown)
            if dist_to_thr > 1e-6:
                dlat = runway_touchdown[0] - state.latitude
                dlon = runway_touchdown[1] - state.longitude
                ratio = min(speed_deg / dist_to_thr, 1.0)
                state.latitude += dlat * ratio
                state.longitude += dlon * ratio
            else:
                rwy_hdg_rad = math.radians(rwy_hdg)
                state.latitude += speed_deg * math.cos(rwy_hdg_rad)
                state.longitude += speed_deg * math.sin(rwy_hdg_rad) / math.cos(math.radians(state.latitude))
        else:
            # On-ground: roll along runway heading
            rwy_hdg_rad = math.radians(rwy_hdg)
            state.latitude += speed_deg * math.cos(rwy_hdg_rad)
            state.longitude += speed_deg * math.sin(rwy_hdg_rad) / math.cos(math.radians(state.latitude))

        if state.altitude > 0:
            # Airborne: descend to touchdown + decelerate during flare
            descent_fpm = 750
            state.altitude = max(0, state.altitude - (descent_fpm / 60.0) * dt)
            state.velocity = max(vref - 5, state.velocity - 2.0 * dt)
            if state.altitude <= 0:
                state.altitude = 0
                state.on_ground = True
                state.vertical_rate = 0
        else:
            # On-ground rollout: decelerate with reverse thrust + brakes (~5 kts/s)
            state.altitude = 0
            state.on_ground = True
            state.vertical_rate = 0
            state.velocity = max(25, state.velocity - 5.0 * dt)

        # Early runway release: vacate when on ground and past initial rollout
        # Real airports: aircraft clears active runway within ~20-30s via high-speed exit
        if state.on_ground and state.velocity <= 80 and not getattr(state, '_runway_released', False):
            arrival_rwy = _get_arrival_runway_name()
            _release_runway(state.icao24, arrival_rwy)
            state._runway_released = True

        if state.on_ground and state.velocity <= 30:
            # Rollout complete — exit runway to taxiway
            emit_phase_transition(
                state.icao24, state.callsign,
                FlightPhase.LANDING.value, FlightPhase.TAXI_TO_GATE.value,
                state.latitude, state.longitude, state.altitude,
                state.aircraft_type, state.assigned_gate,
            )
            _set_phase(state, FlightPhase.TAXI_TO_GATE)
            state.landed_at = time.time()
            # Release runway when exiting to taxiway (may already be released by early release above)
            if not getattr(state, '_runway_released', False):
                arrival_rwy = _get_arrival_runway_name()
                _release_runway(state.icao24, arrival_rwy)
            # Reuse pre-assigned gate from approach if still held, else find new one
            _init_gate_states()
            pre_gate = state.assigned_gate
            rollout_pos = (state.longitude, state.latitude)  # (lon, lat) at rollout end
            if pre_gate and pre_gate in _gate_states and _gate_states[pre_gate].occupied_by == state.icao24:
                # Keep pre-assigned gate
                emit_gate_event(state.icao24, state.callsign, pre_gate, "assign", state.aircraft_type)
                state.taxi_route = _get_taxi_waypoints_arrival(pre_gate, start_pos=rollout_pos)
            else:
                available_gate = _find_available_gate()
                if available_gate:
                    # Release old pre-assigned gate if it was held
                    if pre_gate and pre_gate in _gate_states and _gate_states[pre_gate].occupied_by == state.icao24:
                        _release_gate(state.icao24, pre_gate)
                    state.assigned_gate = available_gate
                    _occupy_gate(state.icao24, available_gate)
                    emit_gate_event(state.icao24, state.callsign, available_gate, "assign", state.aircraft_type)
                    state.taxi_route = _get_taxi_waypoints_arrival(available_gate, start_pos=rollout_pos)
                else:
                    # All gates occupied — defer assignment to taxi phase.
                    # The TAXI_TO_GATE handler retries gate assignment every
                    # few seconds, so a gate freed by a pushback will be
                    # picked up before the aircraft reaches the ramp.
                    if pre_gate and pre_gate in _gate_states and _gate_states[pre_gate].occupied_by == state.icao24:
                        _release_gate(state.icao24, pre_gate)
                    state.assigned_gate = None
                    state.taxi_route = None  # Use default arrival waypoints

            # Prepend current position to taxi route so the aircraft taxis
            # smoothly from the runway rollout end to the first taxiway
            # waypoint, instead of teleporting to it.
            taxi_wps = state.taxi_route or TAXI_WAYPOINTS_ARRIVAL
            current_pos = (state.longitude, state.latitude)  # (lon, lat) format
            if taxi_wps:
                state.taxi_route = [current_pos] + list(taxi_wps)
            else:
                state.taxi_route = [current_pos]
            state.waypoint_index = 1  # Already at wp 0 (current pos)

    elif state.phase == FlightPhase.TAXI_TO_GATE:
        # Taxi along waypoints to assigned gate WITH SEPARATION

        # Calibrated arrival hold — pads taxi-in to match BTS mean.
        # Computed once on first tick, then decremented.
        if not state.arrival_hold_set and _calibration_taxi_in_target_s > 0:
            hold_base = max(0.0, _calibration_taxi_in_target_s - _calibration_taxi_in_waypoint_s)
            state.arrival_hold_s = hold_base * random.uniform(0.80, 1.20)
            state.arrival_hold_set = True
        if state.arrival_hold_s > 0:
            state.arrival_hold_s -= dt
            state.velocity = 0
            return state

        # First, ensure we have an assigned gate before proceeding
        if state.assigned_gate is None:
            now = time.time()
            if now < state.gate_retry_at:
                # Still waiting for retry — hold position
                state.velocity = 0
                return state
            available_gate = _find_available_gate()
            if not available_gate:
                available_gate = _find_overflow_gate()
            if available_gate:
                state.assigned_gate = available_gate
                _occupy_gate(state.icao24, available_gate)
                state.taxi_route = _get_taxi_waypoints_arrival(
                    available_gate, start_pos=(state.longitude, state.latitude))
                state.gate_retry_at = 0.0
            else:
                # No gates available — retry in 5 seconds (sim time)
                state.gate_retry_at = now + 5.0
                state.velocity = 0
                return state

        # Use cached taxi route (dynamic from OSM graph or fallback)
        taxi_wps = state.taxi_route or TAXI_WAYPOINTS_ARRIVAL
        if state.waypoint_index < len(taxi_wps):
            wp = taxi_wps[state.waypoint_index]
            target = (wp[1], wp[0])

            # Graduated taxi separation — slow down near traffic, stop if too close
            speed_factor = _taxi_speed_factor(state)
            if speed_factor > 0:
                # Arriving aircraft taxi faster on the initial straight
                # (ATC clears runway exits quickly to maintain arrival rate)
                base_speed = TAXI_SPEED_STRAIGHT_KTS + 5  # 30 kts for inbound
                taxi_speed = base_speed * speed_factor
                speed_deg = taxi_speed * _KTS_TO_DEG_PER_SEC * dt
                new_pos = _move_toward((state.latitude, state.longitude), target, speed_deg)
                state.latitude, state.longitude = new_pos
                state.velocity = taxi_speed
            elif speed_factor < 0:
                # Head-on hold: yielding to oncoming traffic — stay put
                state.velocity = 0
                speed_deg = 0
            else:
                # Factor 0 = traffic ahead within separation threshold — hold position
                state.velocity = 0
                speed_deg = 0

            # Smooth heading toward waypoint (max 5°/s for taxi turns)
            target_hdg = _calculate_heading((state.latitude, state.longitude), target)
            state.heading = _smooth_heading(state.heading, target_hdg, 5.0, dt)

            if _distance_between((state.latitude, state.longitude), target) < max(speed_deg, 0.0005):
                state.waypoint_index += 1
        else:
            # Head to gate
            target = get_gates()[state.assigned_gate]

            # Check if our gate is still available
            _init_gate_states()
            gate_state = _gate_states.get(state.assigned_gate)
            if gate_state and gate_state.occupied_by and gate_state.occupied_by != state.icao24:
                # Gate was taken, find another
                new_gate = _find_available_gate()
                if new_gate:
                    state.assigned_gate = new_gate
                    _occupy_gate(state.icao24, new_gate)
                    target = get_gates()[new_gate]
                else:
                    # No gates — try overflow gate
                    new_gate = _find_overflow_gate()
                    if new_gate:
                        state.assigned_gate = new_gate
                        _occupy_gate(state.icao24, new_gate)
                        target = get_gates()[new_gate]
                    else:
                        state.velocity = 0
                        return state

            speed_factor = _taxi_speed_factor(state)
            if speed_factor > 0:
                ramp_speed = TAXI_SPEED_RAMP_KTS * speed_factor
                speed_deg = ramp_speed * _KTS_TO_DEG_PER_SEC * dt
                new_pos = _move_toward((state.latitude, state.longitude), target, speed_deg)
                state.latitude, state.longitude = new_pos
                state.velocity = ramp_speed
            else:
                state.velocity = 0
                speed_deg = 0

            target_hdg = _calculate_heading((state.latitude, state.longitude), target)
            state.heading = _smooth_heading(state.heading, target_hdg, 5.0, dt)

            if _distance_between((state.latitude, state.longitude), target) < max(speed_deg, 0.0003):
                emit_phase_transition(
                    state.icao24, state.callsign,
                    FlightPhase.TAXI_TO_GATE.value, FlightPhase.PARKED.value,
                    state.latitude, state.longitude, state.altitude,
                    state.aircraft_type, state.assigned_gate,
                )
                emit_gate_event(state.icao24, state.callsign, state.assigned_gate, "occupy", state.aircraft_type)
                _set_phase(state, FlightPhase.PARKED)
                state.velocity = 0
                state.time_at_gate = 0
                state.parked_since = time.time()
                _occupy_gate(state.icao24, state.assigned_gate)
                # Record inbound delay for reactionary delay prediction
                # (TAXI_TO_GATE → PARKED is always an arrival)
                if state.assigned_gate:
                    _h = (hash(state.icao24) ^ hash(state.callsign[:3] if state.callsign else "")) & 0xFFFF
                    inbound_delay = (5 + ((_h >> 8) % 41)) if ((_h >> 4) % 5 == 0) else 0
                    _gate_last_delay[state.assigned_gate] = float(inbound_delay)
                # Snap to gate position, then offset away from terminal
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
                # Build turnaround schedule
                airline_code = state.callsign[:3] if state.callsign and len(state.callsign) >= 3 else ""
                airline_factor = AIRLINE_TURNAROUND_FACTOR.get(airline_code, _DEFAULT_AIRLINE_FACTOR)
                weather_factor = _get_turnaround_weather_factor()
                congestion_factor = _get_turnaround_congestion_factor()
                intl_factor = _get_turnaround_international_factor(state)
                dow_factor = _get_turnaround_day_of_week_factor()
                combined = airline_factor * weather_factor * congestion_factor * intl_factor * dow_factor
                state.turnaround_schedule = _build_turnaround_schedule(
                    state.aircraft_type, airline_code, combined,
                )
                state.turnaround_phase = "chocks_on"

    elif state.phase == FlightPhase.PARKED:
        # Stay at gate for some time, then pushback
        state.velocity = 0
        state.time_at_gate += dt

        # Progress turnaround sub-phases based on schedule
        if state.turnaround_schedule:
            active_phase = ""
            for p_name in _GATE_PHASES:
                info = state.turnaround_schedule.get(p_name)
                if info is None:
                    continue
                phase_end = info["start_offset_s"] + info["duration_s"]
                if not info["started"] and state.time_at_gate >= info["start_offset_s"]:
                    info["started"] = True
                    emit_turnaround_event(
                        state.icao24, state.callsign,
                        state.assigned_gate or "", p_name, "phase_start",
                        state.aircraft_type,
                    )
                if info["started"] and not info["done"] and state.time_at_gate >= phase_end:
                    info["done"] = True
                    emit_turnaround_event(
                        state.icao24, state.callsign,
                        state.assigned_gate or "", p_name, "phase_complete",
                        state.aircraft_type,
                    )
                if info["started"] and not info["done"]:
                    active_phase = p_name
            state.turnaround_phase = active_phase

        # Realistic turnaround: use calibrated BTS data if available,
        # otherwise fall back to GSE model timing
        if _calibration_gate_minutes > 0:
            # Calibrated: use BTS OTP median turnaround (already gate-only time)
            category = get_aircraft_category(state.aircraft_type)
            if category == "wide_body":
                gate_minutes = _calibration_gate_minutes * 1.4
            else:
                gate_minutes = _calibration_gate_minutes
        else:
            # Fallback: GSE model total minus taxi/pushback phases
            timing = get_turnaround_timing(state.aircraft_type)
            total_min = timing["total_minutes"]  # 45 min narrow-body, 90 min wide-body
            non_gate_min = (timing["phases"].get("arrival_taxi", 0)
                            + timing["phases"].get("pushback", 0)
                            + timing["phases"].get("departure_taxi", 0))
            gate_minutes = total_min - non_gate_min
        gate_seconds = gate_minutes * 60
        # Feature-dependent turnaround: airline + weather + congestion + international
        airline_code = state.callsign[:3] if state.callsign and len(state.callsign) >= 3 else ""
        airline_factor = AIRLINE_TURNAROUND_FACTOR.get(airline_code, _DEFAULT_AIRLINE_FACTOR)
        weather_factor = _get_turnaround_weather_factor()
        congestion_factor = _get_turnaround_congestion_factor()
        intl_factor = _get_turnaround_international_factor(state)
        dow_factor = _get_turnaround_day_of_week_factor()
        combined_factor = airline_factor * weather_factor * congestion_factor * intl_factor * dow_factor
        # +/-10% jitter (reduced from 20% since factors explain more variance)
        target = gate_seconds * combined_factor * random.uniform(0.9, 1.1)
        if state.time_at_gate > target:
            # Ensure correct origin/dest for departure: origin=local, dest=new airport
            local_iata = get_current_airport_iata()
            if state.origin_airport != local_iata:
                # Aircraft arrived here — swap to departing: origin=local, dest=new
                state.origin_airport = local_iata
                state.destination_airport = _pick_random_destination()
            elif not state.destination_airport or state.destination_airport == local_iata:
                # No valid destination set — pick one
                state.destination_airport = _pick_random_destination()
            emit_phase_transition(
                state.icao24, state.callsign,
                FlightPhase.PARKED.value, FlightPhase.PUSHBACK.value,
                state.latitude, state.longitude, state.altitude,
                state.aircraft_type, state.assigned_gate,
            )
            _set_phase(state, FlightPhase.PUSHBACK)
            state.phase_progress = 0

    elif state.phase == FlightPhase.PUSHBACK:
        # Pushback phases: tug connect (0-30s), actual push (30-90s), engine start (90-150s).
        # Only move during the push portion: ~60s at 3kts ≈ 90m (real pushback is 50-80m).
        pb_heading = _get_pushback_heading(state.assigned_gate) if state.assigned_gate else 180.0
        state.phase_progress += dt / 150.0  # ~150s total: tug connect + push + engine start
        # Only move during the active push window (progress 0.2–0.6 ≈ 30s–90s)
        is_pushing = 0.2 <= state.phase_progress < 0.6
        if is_pushing and _check_taxi_separation(state):
            state.velocity = TAXI_SPEED_PUSHBACK_KTS
            pb_rad = math.radians(pb_heading)
            pb_speed_deg = TAXI_SPEED_PUSHBACK_KTS * _KTS_TO_DEG_PER_SEC * dt
            state.latitude += pb_speed_deg * math.cos(pb_rad)
            state.longitude += pb_speed_deg * math.sin(pb_rad)
        else:
            state.velocity = 0  # Stationary during tug connect / engine start / blocked

        # Smooth heading rotation: nose swings from parked heading toward
        # the pushback nose direction (opposite of movement) over the pushback duration.
        nose_target = (pb_heading + 180) % 360
        state.heading = _smooth_heading(state.heading, nose_target, 3.0, dt)

        if state.phase_progress >= 1.0:
            # Release gate when clear of it
            if state.assigned_gate:
                _release_gate(state.icao24, state.assigned_gate)
                emit_gate_event(state.icao24, state.callsign, state.assigned_gate, "release", state.aircraft_type)
            emit_phase_transition(
                state.icao24, state.callsign,
                FlightPhase.PUSHBACK.value, FlightPhase.TAXI_TO_RUNWAY.value,
                state.latitude, state.longitude, state.altitude,
                state.aircraft_type, state.assigned_gate,
            )
            _set_phase(state, FlightPhase.TAXI_TO_RUNWAY)
            state.waypoint_index = 0
            state.taxi_route = _get_taxi_waypoints_departure(state.assigned_gate) if state.assigned_gate else None

    elif state.phase == FlightPhase.TAXI_TO_RUNWAY:
        # Taxi to runway with graduated separation
        taxi_wps = state.taxi_route or TAXI_WAYPOINTS_DEPARTURE
        if state.waypoint_index < len(taxi_wps):
            wp = taxi_wps[state.waypoint_index]
            target = (wp[1], wp[0])

            speed_factor = _taxi_speed_factor(state)
            if speed_factor > 0:
                taxi_speed = TAXI_SPEED_STRAIGHT_KTS * speed_factor
                speed_deg = taxi_speed * _KTS_TO_DEG_PER_SEC * dt
                new_pos = _move_toward((state.latitude, state.longitude), target, speed_deg)
                state.latitude, state.longitude = new_pos
                state.velocity = taxi_speed
            elif speed_factor < 0:
                # Head-on hold: yielding to oncoming traffic — stay put
                state.velocity = 0
                speed_deg = 0
            else:
                # Factor 0 = traffic ahead within separation threshold — hold position
                state.velocity = 0
                speed_deg = 0

            # Smooth heading toward waypoint (max 5°/s for taxi turns)
            target_hdg = _calculate_heading((state.latitude, state.longitude), target)
            state.heading = _smooth_heading(state.heading, target_hdg, 5.0, dt)

            if _distance_between((state.latitude, state.longitude), target) < max(speed_deg, 0.0005):
                state.waypoint_index += 1
        elif state.departure_queue_hold_s > 0:
            # Calibrated departure queue hold — simulates real-world queue time
            # at the runway hold line that the short waypoint path doesn't capture.
            state.departure_queue_hold_s -= dt
            # Hold position at queue — aircraft stays stationary while waiting
            _, _, dep_hdg, _ = _get_takeoff_runway_geometry()
            state.velocity = 0
            state.heading = _smooth_heading(state.heading, dep_hdg, 5.0, dt)
        else:
            # Smoothly face the runway at the hold line
            _, _, dep_hdg, _ = _get_takeoff_runway_geometry()
            state.heading = _smooth_heading(state.heading, dep_hdg, 5.0, dt)
            # Compute departure queue hold once when aircraft first reaches hold line.
            # The capacity system (holding points, taxiway congestion) already adds
            # realistic delays, so the queue hold only fills a residual gap between
            # the capacity-driven taxi time and the BTS target.
            if not state.departure_queue_set and _calibration_taxi_out_target_s > 0:
                queue_base = max(0.0, _calibration_taxi_out_target_s - _calibration_taxi_out_waypoint_s)
                state.departure_queue_hold_s = queue_base * random.uniform(0.80, 1.20)
                state.departure_queue_set = True
                if state.departure_queue_hold_s > 0:
                    state.velocity = 0
                    return state

            # At runway hold line - check runway clear AND departure wake separation
            dep_rwy = _get_departure_runway_name()
            runway_clear = _is_runway_clear(dep_rwy)
            if runway_clear:
                # Check departure wake turbulence separation (FAA 7110.65 5-8-1)
                runway_st = _get_runway_state(dep_rwy)
                elapsed = time.time() - runway_st.last_departure_time
                lead_cat = runway_st.last_departure_type
                follow_cat = _get_wake_category(state.aircraft_type)
                required = DEPARTURE_SEPARATION_S.get(
                    (lead_cat, follow_cat), DEFAULT_DEPARTURE_SEPARATION_S
                )
                if elapsed >= required:
                    emit_phase_transition(
                        state.icao24, state.callsign,
                        FlightPhase.TAXI_TO_RUNWAY.value, FlightPhase.TAKEOFF.value,
                        state.latitude, state.longitude, state.altitude,
                        state.aircraft_type, state.assigned_gate,
                    )
                    _set_phase(state, FlightPhase.TAKEOFF)
                    _, _, dep_hdg, _ = _get_takeoff_runway_geometry()
                    state.heading = dep_hdg
                    state.takeoff_subphase = "lineup"
                    state.phase_progress = 0.0
                    state.takeoff_roll_dist_ft = 0.0
                    state.sid_name = _get_sid_name(state.destination_airport)
                    _occupy_runway(state.icao24, dep_rwy)
                else:
                    # Hold short: wake separation not yet met — stay put
                    state.velocity = 0
                    _, _, dep_hdg, _ = _get_takeoff_runway_geometry()
                    state.heading = _smooth_heading(state.heading, dep_hdg, 5.0, dt)
            else:
                # Hold short of runway — stay put
                state.velocity = 0
                _, _, dep_hdg, _ = _get_takeoff_runway_geometry()
                state.heading = _smooth_heading(state.heading, dep_hdg, 5.0, dt)

    elif state.phase == FlightPhase.TAKEOFF:
        # Realistic takeoff with sub-phases (14 CFR 25.107/111)
        perf = TAKEOFF_PERFORMANCE.get(state.aircraft_type, _DEFAULT_TAKEOFF_PERF)
        v1, vr, v2, accel_rate, climb_fpm = perf

        # Dynamic runway geometry (OSM-aware with SFO fallback)
        rwy_start, rwy_end, rwy_heading, rwy_len_ft = _get_takeoff_runway_geometry()
        rwy_dlat = rwy_end[0] - rwy_start[0]
        rwy_dlon = rwy_end[1] - rwy_start[1]
        rwy_len_deg = math.sqrt(rwy_dlat**2 + rwy_dlon**2)

        state.heading = rwy_heading

        if state.takeoff_subphase == "lineup":
            # Taxi onto runway centerline at ~10 kt, then brief hold
            state.on_ground = True
            dist_to_rwy = _distance_between((state.latitude, state.longitude), (rwy_start[0], rwy_start[1]))
            if dist_to_rwy > 0.0002:  # ~20m — still moving onto runway
                lineup_speed = 10.0  # knots
                state.velocity = lineup_speed
                speed_deg = lineup_speed * _KTS_TO_DEG_PER_SEC * dt
                new_pos = _move_toward((state.latitude, state.longitude), (rwy_start[0], rwy_start[1]), speed_deg)
                state.latitude, state.longitude = new_pos
                state.heading = _smooth_heading(state.heading, rwy_heading, 8.0, dt)
            else:
                # On the runway start — hold briefly before roll
                state.velocity = 0
                state.latitude = rwy_start[0]
                state.longitude = rwy_start[1]
                state.heading = rwy_heading
                state.phase_progress += dt
                if state.phase_progress >= 3.0:
                    state.takeoff_subphase = "roll"
                    state.phase_progress = 0.0
                    state.takeoff_roll_dist_ft = 0.0

        elif state.takeoff_subphase == "roll":
            # Ground roll: accelerate at aircraft-specific rate until VR
            state.velocity = min(state.velocity + accel_rate * dt, vr)
            state.on_ground = True
            # Accumulate ground roll distance
            velocity_ft_s = state.velocity * 1.6878  # knots to ft/s
            state.takeoff_roll_dist_ft += velocity_ft_s * dt
            # Interpolate position along runway centerline
            roll_frac = min(state.takeoff_roll_dist_ft / rwy_len_ft, 0.95)
            state.latitude = rwy_start[0] + rwy_dlat * roll_frac
            state.longitude = rwy_start[1] + rwy_dlon * roll_frac
            if state.velocity >= vr:
                state.takeoff_subphase = "rotate"
                state.phase_progress = 0.0

        elif state.takeoff_subphase == "rotate":
            # Rotation: nose pitches up, reduced acceleration (~3s)
            state.velocity = min(state.velocity + accel_rate * 0.8 * dt, v2 + 5)
            state.on_ground = True
            # Still rolling on ground during rotation
            velocity_ft_s = state.velocity * 1.6878
            state.takeoff_roll_dist_ft += velocity_ft_s * dt
            roll_frac = min(state.takeoff_roll_dist_ft / rwy_len_ft, 0.98)
            state.latitude = rwy_start[0] + rwy_dlat * roll_frac
            state.longitude = rwy_start[1] + rwy_dlon * roll_frac
            # Ramp vertical rate from 0 toward 500 fpm, start climbing
            state.phase_progress += dt
            state.vertical_rate = min(500 * (state.phase_progress / 3.0), 500)
            state.altitude += state.vertical_rate / 60.0 * dt
            if state.phase_progress >= 3.0 or state.velocity >= v2:
                state.takeoff_subphase = "liftoff"
                state.phase_progress = 0.0
                state.on_ground = False  # Wheels leave the ground

        elif state.takeoff_subphase == "liftoff":
            # Wheels off ground, climb to 35 ft screen height
            state.on_ground = False
            state.velocity = min(state.velocity + accel_rate * 0.5 * dt, v2 + 10)
            # Ramp vertical rate from 500 toward initial climb rate
            state.phase_progress += dt
            ramp = min(state.phase_progress / 5.0, 1.0)
            state.vertical_rate = 500 + (climb_fpm - 500) * ramp
            state.altitude += state.vertical_rate / 60.0 * dt
            # Continue along runway heading
            speed_deg = state.velocity * _KTS_TO_DEG_PER_SEC * dt
            state.latitude += (rwy_dlat / rwy_len_deg) * speed_deg
            state.longitude += (rwy_dlon / rwy_len_deg) * speed_deg
            if state.altitude >= 35:
                state.takeoff_subphase = "initial_climb"
                state.phase_progress = 0.0

        elif state.takeoff_subphase == "initial_climb":
            # Climb from 35 ft to 500 ft, then transition to DEPARTING
            # 14 CFR 25.111: min 2.4% net climb gradient, all-engine
            state.on_ground = False
            state.velocity = min(state.velocity + accel_rate * 0.3 * dt, v2 + 10)
            state.vertical_rate = climb_fpm
            state.altitude += climb_fpm / 60.0 * dt
            # Continue along runway heading (noise abatement: no turns below 400 ft)
            speed_deg = state.velocity * _KTS_TO_DEG_PER_SEC * dt
            state.latitude += (rwy_dlat / rwy_len_deg) * speed_deg
            state.longitude += (rwy_dlon / rwy_len_deg) * speed_deg

            if state.altitude >= 500:
                # Release runway and transition to DEPARTING
                _release_runway(state.icao24, _get_departure_runway_name(), state.aircraft_type)
                emit_phase_transition(
                    state.icao24, state.callsign,
                    FlightPhase.TAKEOFF.value, FlightPhase.DEPARTING.value,
                    state.latitude, state.longitude, state.altitude,
                    state.aircraft_type, state.assigned_gate,
                )
                _set_phase(state, FlightPhase.DEPARTING)
                state.waypoint_index = 0
                state.takeoff_subphase = "lineup"  # Reset for next use
                state.takeoff_roll_dist_ft = 0.0

    elif state.phase == FlightPhase.DEPARTING:
        # Climb out following departure path (destination-aware turn)
        departure_wps = _get_departure_waypoints(state.destination_airport)
        if state.waypoint_index < len(departure_wps):
            wp = departure_wps[state.waypoint_index]
            target = (wp[1], wp[0])
            target_alt = wp[2]

            # --- OpenAP-based climb profile ---
            total_wps = len(departure_wps)
            progress = state.waypoint_index / max(1, total_wps - 1)
            # Departure waypoints cover initial climb only (~first 40% of full climb)
            profile_progress = 0.4 * progress
            climb_prof = get_climb_profile(state.aircraft_type)
            prof_alt, prof_spd, prof_vr = interpolate_profile(climb_prof, profile_progress)

            # Speed from profile, respect 250kt below FL100
            target_spd = min(prof_spd, MAX_SPEED_BELOW_FL100_KTS) if state.altitude < 10000 else prof_spd
            # Limit acceleration to ~2 kts/s (realistic for commercial jets)
            max_accel = 2.0 * dt  # kts per tick
            if target_spd > state.velocity:
                state.velocity = min(target_spd, state.velocity + max_accel)
            else:
                state.velocity = max(target_spd, state.velocity - max_accel)

            # Move based on actual velocity
            speed_deg = state.velocity * _KTS_TO_DEG_PER_SEC * dt
            dist_to_wp = _distance_between((state.latitude, state.longitude), target)
            if dist_to_wp > 1e-8:
                dlat = target[0] - state.latitude
                dlon = target[1] - state.longitude
                ratio = min(speed_deg / dist_to_wp, 1.0)
                state.latitude += dlat * ratio
                state.longitude += dlon * ratio

            # Climb rate capped at realistic values (prof_vr is ft/min from OpenAP)
            max_climb_fpm = abs(prof_vr) if prof_vr and prof_vr > 0 else 2500
            max_climb_fpm = min(max_climb_fpm, 2500)  # hard cap — keeps 30s snapshot jumps ≤ 1250ft
            alt_step = max_climb_fpm / 60.0 * dt
            # During departure, altitude must never decrease (monotonic climb).
            # Waypoints may have lower altitudes from SID constraints, but the
            # aircraft should continue climbing past them, not descend.
            new_alt = max(0.0, _interpolate_altitude(state.altitude, target_alt, alt_step))
            state.altitude = max(state.altitude, new_alt)
            # Use profile altitude ceiling (not waypoint) so VR stays positive
            # during climb even when current alt exceeds the low initial waypoint.
            state.vertical_rate = prof_vr if (state.altitude < target_alt or state.altitude < prof_alt) else 0

            # Smooth heading toward waypoint (max 3°/s standard rate turn)
            target_hdg = _calculate_heading((state.latitude, state.longitude), target)
            state.heading = _smooth_heading(state.heading, target_hdg, 3.0, dt)

            if _distance_between((state.latitude, state.longitude), target) < 0.005:
                state.waypoint_index += 1
        else:
            # Waypoints exhausted — continue climbing to FL180 before ENROUTE transition
            if state.altitude < 18000:
                # Use OpenAP climb profile for post-waypoint climb
                climb_prof = get_climb_profile(state.aircraft_type)
                # We're past waypoints, roughly 40-60% of climb
                frac = min(1.0, 0.4 + 0.2 * (state.altitude / 18000.0))
                _, prof_spd, prof_vr = interpolate_profile(climb_prof, frac)
                target_spd = min(prof_spd, MAX_SPEED_BELOW_FL100_KTS) if state.altitude < 10000 else prof_spd
                max_accel = 2.0 * dt
                if target_spd > state.velocity:
                    state.velocity = min(target_spd, state.velocity + max_accel)
                else:
                    state.velocity = max(target_spd, state.velocity - max_accel)
                climb_fpm = prof_vr if prof_vr > 0 else 1500
                climb_fpm = min(climb_fpm, 2500)  # hard cap — keeps 30s snapshot jumps ≤ 1250ft
                state.vertical_rate = climb_fpm
                state.altitude += climb_fpm / 60.0 * dt
                # Continue on departure heading
                speed_deg = state.velocity * _KTS_TO_DEG_PER_SEC * dt
                state.latitude += math.cos(math.radians(state.heading)) * speed_deg
                state.longitude += math.sin(math.radians(state.heading)) * speed_deg / max(0.01, math.cos(math.radians(state.latitude)))
            else:
                # Now switch to enroute — heading toward destination
                emit_phase_transition(
                    state.icao24, state.callsign,
                    FlightPhase.DEPARTING.value, FlightPhase.ENROUTE.value,
                    state.latitude, state.longitude, state.altitude,
                    state.aircraft_type, state.assigned_gate,
                )
                _set_phase(state, FlightPhase.ENROUTE)
                if state.destination_airport:
                    state.heading = _bearing_to_airport(state.destination_airport)

    elif state.phase == FlightPhase.ENROUTE:
        EXIT_RADIUS_DEG = 0.5  # ~30 NM — remove when exiting this circle
        APPROACH_RADIUS_DEG = 0.25  # ~15 NM — transition to approach

        center = get_airport_center()
        dist_from_airport = _distance_between(
            (state.latitude, state.longitude),
            center,
        )

        _local = get_current_airport_iata()
        _is_arriving_enroute = (
            (state.origin_airport and not state.destination_airport)
            or (state.destination_airport == _local)
        )
        if _is_arriving_enroute:
            # ARRIVING enroute: heading toward airport, transition to approach when close

            # Go-around missed approach: climb → straight ahead → turn to
            # re-intercept the approach from the correct side.
            if state.go_around_target_alt > 0 and state.altitude < state.go_around_target_alt:
                climb_fps = 25.0  # ~1500 ft/min
                state.altitude = min(state.go_around_target_alt, state.altitude + climb_fps * dt)
                state.vertical_rate = 1500
                speed_deg = state.velocity * _KTS_TO_DEG_PER_SEC * dt
                state.latitude += math.cos(math.radians(state.heading)) * speed_deg
                state.longitude += math.sin(math.radians(state.heading)) * speed_deg / max(0.01, math.cos(math.radians(state.latitude)))
                if state.altitude >= state.go_around_target_alt:
                    state.go_around_target_alt = 0.0
                    # Fly straight ahead 180s (~12 NM) to clear the airport
                    state.holding_phase_time = -180.0
                state.heading = state.heading % 360
                return state

            # Post-climb straight-ahead leg (negative holding_phase_time counts up to 0)
            if state.holding_phase_time < 0:
                state.holding_phase_time += dt
                speed_deg = state.velocity * _KTS_TO_DEG_PER_SEC * dt
                state.latitude += math.cos(math.radians(state.heading)) * speed_deg
                state.longitude += math.sin(math.radians(state.heading)) * speed_deg / max(0.01, math.cos(math.radians(state.latitude)))
                state.vertical_rate = 0
                return state

            # After missed approach straight-ahead: turn toward the first
            # approach waypoint (far from runway) to re-intercept the approach
            # from the correct side, instead of making a tight U-turn.
            if state.go_around_count > 0:
                approach_wps = _get_approach_waypoints(state.origin_airport)
                if approach_wps:
                    first_wp = approach_wps[0]
                    target_heading = _calculate_heading(
                        (state.latitude, state.longitude),
                        (first_wp[1], first_wp[0]),
                    )
                else:
                    target_heading = _calculate_heading(
                        (state.latitude, state.longitude), center
                    )
            else:
                target_heading = _calculate_heading(
                    (state.latitude, state.longitude), center
                )
            heading_diff = (target_heading - state.heading + 540) % 360 - 180
            if state.go_around_count > 0:
                turn_rate = 2.0  # gentler turn for missed approach pattern
            else:
                # Fresh arrival vectoring: gentle proportional turn
                turn_rate = max(0.5, min(1.5, dist_from_airport / 0.08))
            state.heading += max(-turn_rate, min(turn_rate, heading_diff)) * dt
            state.heading = state.heading % 360

            # Progressive descent & speed envelope for arriving flights
            # dist_from_airport is in degrees; ~0.5° ≈ 30 NM, ~0.25° ≈ 15 NM
            # Start descent around 0.5° out (~30 NM), reach ~3000 ft at 0.17° (~10 NM)
            if dist_from_airport < EXIT_RADIUS_DEG and state.altitude > 3000:
                frac = max(0.0, (dist_from_airport - 0.17) / (EXIT_RADIUS_DEG - 0.17))
                target_alt = max(3000.0, 3000.0 + frac * (35000.0 - 3000.0))
                if state.altitude > target_alt:
                    descent_rate = min(2000.0, (state.altitude - target_alt) * 2.0)
                    state.altitude -= descent_rate * dt / 60.0
                    state.altitude = max(target_alt, state.altitude)
                    state.vertical_rate = -descent_rate

            # Speed envelope based on altitude (realistic deceleration)
            if state.altitude < 3000:
                state.velocity = min(state.velocity, 180)
            elif state.altitude < 5000:
                state.velocity = min(state.velocity, 210)
            elif state.altitude < 10000:
                state.velocity = min(state.velocity, MAX_SPEED_BELOW_FL100_KTS)

            # Enforce approach capacity at runtime (scaled to runway count)
            approach_count = (_count_aircraft_in_phase(FlightPhase.APPROACHING)
                              + _count_aircraft_in_phase(FlightPhase.LANDING))
            # Go-around flights get priority re-entry — they've already been sequenced
            can_start_approach = (approach_count < get_max_approach_aircraft()
                                  or state.go_around_count > 0)

            # Go-around re-entry: require proper alignment with approach
            # course before allowing transition back to APPROACHING.
            reentry_radius = APPROACH_RADIUS_DEG
            ga_aligned = True
            if state.go_around_count > 0:
                approach_wps = _get_approach_waypoints(state.origin_airport)
                if approach_wps and len(approach_wps) >= 2:
                    last_wp = approach_wps[-1]
                    approach_bearing = _calculate_heading(
                        (state.latitude, state.longitude),
                        (last_wp[1], last_wp[0]),
                    )
                    hdg_err = abs((state.heading - approach_bearing + 540) % 360 - 180)
                    ga_aligned = hdg_err < 60

            if can_start_approach and dist_from_airport < reentry_radius and ga_aligned:
                # Close enough — transition to approach
                emit_phase_transition(
                    state.icao24, state.callsign,
                    FlightPhase.ENROUTE.value, FlightPhase.APPROACHING.value,
                    state.latitude, state.longitude, state.altitude,
                    state.aircraft_type, state.assigned_gate,
                )
                _set_phase(state, FlightPhase.APPROACHING)
                state.waypoint_index = _snap_to_nearest_waypoint(state)
                state.star_name = _get_star_name(state.origin_airport)
                # After go-around: set go_around_target_alt to the snapped waypoint
                # altitude so the approach descent uses a gradual climb-to-profile
                # instead of skipping waypoints (which causes wrong-direction approach).
                if state.go_around_count > 0:
                    approach_wps = _get_approach_waypoints(state.origin_airport)
                    if approach_wps and state.waypoint_index < len(approach_wps):
                        wp_alt = approach_wps[state.waypoint_index][2] if len(approach_wps[state.waypoint_index]) > 2 else 3000
                        if wp_alt > state.altitude:
                            state.go_around_target_alt = float(wp_alt)
                # Smooth speed transition: set speed from OpenAP descent profile
                # to prevent a visible speed jump on the first approach tick
                _dp = get_descent_profile(state.aircraft_type)
                _, _ps, _pv = interpolate_profile(_dp, 0.5)
                _vref = VREF_SPEEDS.get(state.aircraft_type, _DEFAULT_VREF)
                state.velocity = max(_vref, min(_ps, MAX_SPEED_BELOW_FL100_KTS))
                state.vertical_rate = _pv if _pv else -800
            elif can_start_approach and random.random() < 0.01 * dt and dist_from_airport < 0.35:
                emit_phase_transition(
                    state.icao24, state.callsign,
                    FlightPhase.ENROUTE.value, FlightPhase.APPROACHING.value,
                    state.latitude, state.longitude, state.altitude,
                    state.aircraft_type, state.assigned_gate,
                )
                _set_phase(state, FlightPhase.APPROACHING)
                state.waypoint_index = _snap_to_nearest_waypoint(state)
                state.star_name = _get_star_name(state.origin_airport)
                _dp = get_descent_profile(state.aircraft_type)
                _, _ps, _pv = interpolate_profile(_dp, 0.5)
                _vref = VREF_SPEEDS.get(state.aircraft_type, _DEFAULT_VREF)
                state.velocity = max(_vref, min(_ps, MAX_SPEED_BELOW_FL100_KTS))
                state.vertical_rate = _pv if _pv else -800
            elif not can_start_approach and dist_from_airport < APPROACH_RADIUS_DEG:
                # Approach full — FAA standard racetrack holding pattern
                # 90-second inbound/outbound legs (~4.5 NM at 180 kts), standard rate turns (3°/s)
                HOLDING_LEG_SECONDS = 90.0   # 1.5-minute legs for wider racetrack
                HOLDING_TURN_SECONDS = 60.0  # 180° at 3°/s standard rate
                STANDARD_RATE_DEG_S = 3.0    # Standard rate turn

                # Altitude stacking: 1000ft separation per go-around count
                holding_alt = 3000.0 + state.go_around_count * 1000.0
                if abs(state.altitude - holding_alt) > 100:
                    if state.altitude < holding_alt:
                        state.altitude = min(holding_alt, state.altitude + 15.0 * dt)
                        state.vertical_rate = 900
                    else:
                        state.altitude = max(holding_alt, state.altitude - 15.0 * dt)
                        state.vertical_rate = -900
                else:
                    state.altitude = holding_alt
                    state.vertical_rate = 0

                state.holding_phase_time += dt
                if state.holding_inbound:
                    # Inbound leg: smooth turn toward the fix (airport center)
                    target_heading = _calculate_heading(
                        (state.latitude, state.longitude), center
                    )
                    state.heading = _smooth_heading(state.heading, target_heading, STANDARD_RATE_DEG_S, dt)
                    if state.holding_phase_time >= HOLDING_LEG_SECONDS:
                        state.holding_phase_time = 0.0
                        state.holding_inbound = False  # Start turn + outbound
                else:
                    # Outbound phase: 180° turn then straight outbound leg
                    if state.holding_phase_time < HOLDING_TURN_SECONDS:
                        state.heading = (state.heading + STANDARD_RATE_DEG_S * dt) % 360
                    elif state.holding_phase_time < HOLDING_TURN_SECONDS + HOLDING_LEG_SECONDS:
                        # Straight outbound leg — maintain heading
                        pass
                    else:
                        state.holding_phase_time = 0.0
                        state.holding_inbound = True

        elif state.destination_airport and state.destination_airport != _local:
            # DEPARTING enroute: heading away from airport toward destination
            target_heading = _bearing_to_airport(state.destination_airport)
            heading_diff = (target_heading - state.heading + 540) % 360 - 180
            state.heading += max(-3, min(3, heading_diff)) * dt
            state.heading = state.heading % 360

            # Climb toward cruise altitude (hemispheric rule: east=odd FL, west=even FL)
            if state.cruise_altitude == 0.0:
                if state.heading < 180:
                    state.cruise_altitude = random.choice([35000, 37000, 39000])
                else:
                    state.cruise_altitude = random.choice([34000, 36000, 38000])
            if state.altitude < state.cruise_altitude:
                # Climb rate capped at realistic values (ft/min → ft/tick)
                # A320-family: ~2500 fpm below FL200, ~1500 fpm above
                max_climb_fpm = 2500 if state.altitude < 20000 else 1500
                alt_step = min(max_climb_fpm / 60.0 * dt, state.cruise_altitude - state.altitude)
                state.altitude += alt_step
                state.vertical_rate = max_climb_fpm

            # Speed management: 250 kts below FL100, accelerate above
            if state.altitude < 10000:
                target_spd = min(state.velocity, MAX_SPEED_BELOW_FL100_KTS)
            else:
                # Cruise speed ~450 kts for jets, limit acceleration to 2 kts/s
                target_spd = 450 if state.altitude > 20000 else 300
            max_accel = 2.0 * dt
            if target_spd > state.velocity:
                state.velocity = min(target_spd, state.velocity + max_accel)
            elif target_spd < state.velocity:
                state.velocity = max(target_spd, state.velocity - max_accel)

            # Remove when exiting visibility circle
            if dist_from_airport > EXIT_RADIUS_DEG:
                # Mark for removal by returning None-like signal
                # We set a special flag — the main loop will handle cleanup
                state.phase_progress = -1.0  # Signal: remove this flight
                return state

        else:
            # No origin/destination — legacy random behavior, head toward airport
            if dist_from_airport > EXIT_RADIUS_DEG:
                state.heading = _calculate_heading(
                    (state.latitude, state.longitude), center
                )
            else:
                pass  # Maintain current heading — no jitter

            if random.random() < 0.005 * dt:
                _set_phase(state, FlightPhase.APPROACHING)
                state.waypoint_index = _snap_to_nearest_waypoint(state)
                state.star_name = _get_star_name(state.origin_airport)

        # 14 CFR 91.117: 250 kts IAS below 10,000 ft MSL
        if state.altitude < 10000:
            state.velocity = min(state.velocity, MAX_SPEED_BELOW_FL100_KTS)

        # Move in current heading direction (velocity-based, latitude-corrected)
        speed_deg = state.velocity * _KTS_TO_DEG_PER_SEC * dt
        state.latitude += math.cos(math.radians(state.heading)) * speed_deg
        state.longitude += math.sin(math.radians(state.heading)) * speed_deg / max(0.01, math.cos(math.radians(state.latitude)))

    # Safety: clamp altitude floor and normalize heading
    state.altitude = max(0.0, state.altitude)
    state.heading = state.heading % 360

    # Safety: clamp velocity for ground phases
    if state.phase in (FlightPhase.TAXI_TO_GATE, FlightPhase.TAXI_TO_RUNWAY):
        state.velocity = min(state.velocity, TAXI_SPEED_STRAIGHT_KTS)
    elif state.phase == FlightPhase.PARKED:
        state.velocity = 0.0
        state.vertical_rate = 0.0

    # Safety: ground-phase coordinate bounds check.
    # Taxi/parked/pushback flights must stay within ~3 NM of airport center.
    # If coordinates drift beyond this (bad waypoint, graph error), reset to gate or center.
    if state.phase in (FlightPhase.TAXI_TO_GATE, FlightPhase.TAXI_TO_RUNWAY,
                       FlightPhase.PARKED, FlightPhase.PUSHBACK):
        center = get_airport_center()
        ground_dist_sq = (state.latitude - center[0]) ** 2 + (state.longitude - center[1]) ** 2
        MAX_GROUND_DIST_SQ = 0.05 ** 2  # ~3 NM — no taxi route exceeds this
        if ground_dist_sq > MAX_GROUND_DIST_SQ:
            logger.warning(
                "Ground flight %s at (%.5f, %.5f) is %.2f° from airport center — resetting position",
                state.icao24, state.latitude, state.longitude, math.sqrt(ground_dist_sq),
            )
            gate_pos = get_gates().get(state.assigned_gate) if state.assigned_gate else None
            if gate_pos:
                state.latitude, state.longitude = gate_pos
            else:
                state.latitude, state.longitude = center
            state.velocity = 0.0

    # Hard safety cap — no commercial aircraft exceeds 600 kts
    state.velocity = min(state.velocity, MAX_VELOCITY_KTS)

    return state


def _get_flight_phase_name(phase: FlightPhase) -> str:
    """Convert flight phase to API-compatible phase name (fine-grained 9-phase)."""
    phase_map = {
        FlightPhase.APPROACHING: "approaching",
        FlightPhase.LANDING: "landing",
        FlightPhase.TAXI_TO_GATE: "taxi_in",
        FlightPhase.PARKED: "parked",
        FlightPhase.PUSHBACK: "pushback",
        FlightPhase.TAXI_TO_RUNWAY: "taxi_out",
        FlightPhase.TAKEOFF: "takeoff",
        FlightPhase.DEPARTING: "departing",
        FlightPhase.ENROUTE: "enroute",
    }
    return phase_map.get(phase, "parked")

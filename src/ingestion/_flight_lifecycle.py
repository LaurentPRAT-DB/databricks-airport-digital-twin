"""Flight lifecycle: creation, state machine updates, calibration, and helpers."""

import logging
import math
import random
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional

from src.ingestion._clock import get_time

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
    _is_runway_scenario_open,
    _is_arrival_separation_met,
    _occupy_runway,
    _release_runway,
    _find_available_gate,
    _find_overflow_gate,
    _resolve_preferred_gate,
    _occupy_gate,
    _release_gate,
    _check_taxi_separation,
    _taxi_speed_factor,
    _count_aircraft_in_phase,
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
    _assign_arrival_runway,
    _clear_arrival_runway_assignment,
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


# ============================================================================
# CALIBRATION STATE — single dataclass holds all per-run calibration params
# ============================================================================

from src.ingestion._calibration_state import SimCalibration

_calibration = SimCalibration()


def reset_calibration() -> None:
    """Reset all calibration state to defaults. Called between simulation runs."""
    global _calibration
    _calibration = SimCalibration()


def set_calibration_gate_minutes(minutes: float) -> None:
    """Set calibrated median gate turnaround time (minutes). 0 disables."""
    _calibration.gate_minutes = minutes


def set_calibration_taxi_out(mean_minutes: float, waypoint_travel_s: float = 180.0, p95_minutes: float = 0.0) -> None:
    """Set calibrated taxi-out target from BTS OTP data."""
    _calibration.taxi_out_target_s = mean_minutes * 60.0
    _calibration.taxi_out_waypoint_s = waypoint_travel_s
    _calibration.taxi_out_p95_s = p95_minutes * 60.0 if p95_minutes > 0 else mean_minutes * 60.0 * 1.8


def set_calibration_taxi_in(mean_minutes: float, waypoint_travel_s: float = 120.0, p95_minutes: float = 0.0) -> None:
    """Set calibrated taxi-in target from BTS OTP data."""
    _calibration.taxi_in_target_s = mean_minutes * 60.0
    _calibration.taxi_in_waypoint_s = waypoint_travel_s
    _calibration.taxi_in_p95_s = p95_minutes * 60.0 if p95_minutes > 0 else mean_minutes * 60.0 * 2.0


def set_current_weather(wind_speed_kts: float, visibility_sm: float) -> None:
    """Called by simulation engine after each weather update."""
    _calibration.weather_wind_kts = wind_speed_kts
    _calibration.weather_visibility_sm = visibility_sm


def get_current_weather() -> Dict[str, float]:
    """Return current weather state as dict (backward compat)."""
    return {"wind_speed_kts": _calibration.weather_wind_kts, "visibility_sm": _calibration.weather_visibility_sm}


def _get_turnaround_weather_factor() -> float:
    """Weather impact on ground handling operations."""
    factor = 1.0
    wind = _calibration.weather_wind_kts
    vis = _calibration.weather_visibility_sm

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


def get_gate_last_delay(gate_id: str) -> float:
    """Return the delay of the last inbound flight at this gate (minutes)."""
    return _calibration.gate_last_delay.get(gate_id, 0.0)


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
    preferred_gate: Optional[str] = None,
    aircraft_type_override: Optional[str] = None,
    registration: Optional[str] = None,
    terminal: Optional[str] = None,
    belt: Optional[str] = None,
    scheduled_time_iso: Optional[str] = None,
    estimated_time_iso: Optional[str] = None,
    actual_time_iso: Optional[str] = None,
    flifo_delay_minutes: int = 0,
    delay_reason: Optional[str] = None,
    codeshares: Optional[list] = None,
    data_source: str = "synthetic",
) -> FlightState:
    """Create a new flight in the specified phase with proper separation."""
    from src.ingestion.fallback import get_airport_center, get_current_airport_iata, get_gates
    is_intl = _is_international_airport(origin or "") or _is_international_airport(destination or "")
    aircraft_type = aircraft_type_override or _get_aircraft_type_for_airline(callsign, is_international=is_intl)

    # FLIFO kwargs to propagate through recursive overflow calls
    _flifo_kw = dict(
        aircraft_type_override=aircraft_type_override,
        registration=registration, terminal=terminal, belt=belt,
        scheduled_time_iso=scheduled_time_iso, estimated_time_iso=estimated_time_iso,
        actual_time_iso=actual_time_iso, flifo_delay_minutes=flifo_delay_minutes,
        delay_reason=delay_reason, codeshares=codeshares, data_source=data_source,
    )

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
            return _create_new_flight(icao24, callsign, FlightPhase.ENROUTE, origin=origin, destination=destination, preferred_gate=preferred_gate, **_flifo_kw)

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
            min_approach_alt = base_wp[2] * 0.5 if base_wp[2] > 0 else 3000
            alt = max(last_aircraft.altitude + 500, min_approach_alt)

        # Pre-assign a gate so it shows as INBOUND on the gate status panel
        _init_gate_states()
        pre_gate = _resolve_preferred_gate(preferred_gate) or _find_available_gate()
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
        if alt < 1000:
            init_speed = min(init_speed, vref + 30)
        elif alt < 2000:
            init_speed = min(init_speed, vref + 40)

        return FlightState(
            icao24=icao24,
            callsign=callsign,
            latitude=lat,
            longitude=lon,
            altitude=alt + random.uniform(-30, 30),
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
            registration=registration,
            terminal=terminal,
            belt=belt,
            scheduled_time_iso=scheduled_time_iso,
            estimated_time_iso=estimated_time_iso,
            actual_time_iso=actual_time_iso,
            flifo_delay_minutes=flifo_delay_minutes,
            delay_reason=delay_reason,
            codeshares=codeshares,
            data_source=data_source,
        )

    elif phase == FlightPhase.PARKED:
        # Start at a gate, nose facing toward the nearest terminal center
        _init_gate_states()

        # Use FLIFO-assigned gate if valid, else find any available
        gate = _resolve_preferred_gate(preferred_gate) or _find_available_gate()
        if gate is None:
            # All gates occupied - switch to approaching or enroute
            return _create_new_flight(icao24, callsign, FlightPhase.APPROACHING, origin=origin, destination=destination, preferred_gate=preferred_gate, **_flifo_kw)

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

        state = FlightState(
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
            landed_at=get_time() - initial_time_at_gate - 5 * 60,  # ~5 min taxi before parking
            parked_since=get_time() - initial_time_at_gate,
            turnaround_phase=current_phase,
            turnaround_schedule=schedule,
            registration=registration,
            terminal=terminal,
            belt=belt,
            scheduled_time_iso=scheduled_time_iso,
            estimated_time_iso=estimated_time_iso,
            actual_time_iso=actual_time_iso,
            flifo_delay_minutes=flifo_delay_minutes,
            delay_reason=delay_reason,
            codeshares=codeshares,
            data_source=data_source,
        )
        state.turnaround_target_s = _compute_turnaround_target(state)
        return state

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
            registration=registration,
            terminal=terminal,
            belt=belt,
            scheduled_time_iso=scheduled_time_iso,
            estimated_time_iso=estimated_time_iso,
            actual_time_iso=actual_time_iso,
            flifo_delay_minutes=flifo_delay_minutes,
            delay_reason=delay_reason,
            codeshares=codeshares,
            data_source=data_source,
        )

    elif phase == FlightPhase.TAXI_TO_GATE:
        # Just landed, taxiing from runway
        _init_gate_states()

        # Check if runway is occupied - if so, can't spawn here
        arrival_rwy = _get_arrival_runway_name()
        if not _is_runway_clear(arrival_rwy):
            return _create_new_flight(icao24, callsign, FlightPhase.APPROACHING, origin=origin, destination=destination, preferred_gate=preferred_gate, **_flifo_kw)

        gate = _resolve_preferred_gate(preferred_gate) or _find_available_gate()
        if gate is None:
            # No gates available
            return _create_new_flight(icao24, callsign, FlightPhase.ENROUTE, origin=origin, destination=destination, preferred_gate=preferred_gate, **_flifo_kw)

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
                    return _create_new_flight(icao24, callsign, FlightPhase.APPROACHING, origin=origin, destination=destination, preferred_gate=preferred_gate, **_flifo_kw)

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
            registration=registration,
            terminal=terminal,
            belt=belt,
            scheduled_time_iso=scheduled_time_iso,
            estimated_time_iso=estimated_time_iso,
            actual_time_iso=actual_time_iso,
            flifo_delay_minutes=flifo_delay_minutes,
            delay_reason=delay_reason,
            codeshares=codeshares,
            data_source=data_source,
        )

    elif phase == FlightPhase.TAXI_TO_RUNWAY:
        # Departing, starting from a gate position
        _init_gate_states()

        # Use FLIFO-assigned gate if valid, else find any available
        gate = _resolve_preferred_gate(preferred_gate) or _find_available_gate()
        if gate is None:
            # All gates occupied - can't spawn departing aircraft
            return _create_new_flight(icao24, callsign, FlightPhase.ENROUTE, origin=origin, destination=destination, preferred_gate=preferred_gate, **_flifo_kw)

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
            registration=registration,
            terminal=terminal,
            belt=belt,
            scheduled_time_iso=scheduled_time_iso,
            estimated_time_iso=estimated_time_iso,
            actual_time_iso=actual_time_iso,
            flifo_delay_minutes=flifo_delay_minutes,
            delay_reason=delay_reason,
            codeshares=codeshares,
            data_source=data_source,
        )

    # Default: random enroute
    return _create_new_flight(icao24, callsign, FlightPhase.ENROUTE, origin=origin, destination=destination, preferred_gate=preferred_gate, **_flifo_kw)


def _update_taxi_to_gate(state: FlightState, dt: float) -> None:
    """TAXI_TO_GATE phase: waypoint following with separation to assigned gate."""
    from src.ingestion.fallback import get_gates, TAXI_WAYPOINTS_ARRIVAL

    # Taxi along waypoints to assigned gate WITH SEPARATION

    # Calibrated arrival hold — pads taxi-in to match BTS mean when
    # natural taxi time is shorter than calibration target.
    if not state.arrival_hold_set:
        state.arrival_hold_s = 0.0
        state.arrival_hold_set = True
    if state.arrival_hold_s > 0:
        state.arrival_hold_s -= dt
        state.velocity = 0
        return state

    # First, ensure we have an assigned gate before proceeding
    if state.assigned_gate is None:
        now = get_time()
        if now < state.gate_retry_at:
            state.phase_progress += dt
            state.velocity = 0
            return state
        available_gate = _find_available_gate()
        if not available_gate:
            available_gate = _find_overflow_gate()
        if not available_gate and state.phase_progress > 60.0:
            # Waited too long — force-assign to least-recently-used gate
            _init_gate_states()
            if _gate_states:
                sorted_gates = sorted(
                    _gate_states.keys(),
                    key=lambda g: _gate_states[g].available_at,
                )
                available_gate = sorted_gates[0]
        if available_gate:
            state.assigned_gate = available_gate
            _occupy_gate(state.icao24, available_gate)
            state.taxi_route = _get_taxi_waypoints_arrival(
                available_gate, start_pos=(state.longitude, state.latitude))
            state.gate_retry_at = 0.0
            state.phase_progress = 0.0
        else:
            # No gates available — retry in 5 seconds (sim time)
            state.gate_retry_at = now + 5.0
            state.phase_progress += dt
            state.velocity = 0
            return state

    # Use cached taxi route (dynamic from OSM graph or fallback)
    taxi_wps = state.taxi_route or TAXI_WAYPOINTS_ARRIVAL
    if state.waypoint_index < len(taxi_wps):
        wp = taxi_wps[state.waypoint_index]
        target = (wp[1], wp[0])

        # Graduated taxi separation — slow down near traffic, stop if too close
        speed_factor = _taxi_speed_factor(state)
        if speed_factor <= 0 and state.phase_progress > 20.0:
            speed_factor = 0.5
        if speed_factor > 0:
            base_speed = TAXI_SPEED_STRAIGHT_KTS + 5
            taxi_speed = base_speed * speed_factor
            speed_deg = taxi_speed * _KTS_TO_DEG_PER_SEC * dt
            new_pos = _move_toward((state.latitude, state.longitude), target, speed_deg)
            state.latitude, state.longitude = new_pos
            state.velocity = taxi_speed
            state.phase_progress = 0.0
        elif speed_factor < 0:
            # Head-on hold: yielding to oncoming traffic — stay put
            state.velocity = 0
            speed_deg = 0
            state.phase_progress += dt
        else:
            # Factor 0 = traffic ahead within separation threshold — hold position
            state.velocity = 0
            speed_deg = 0
            state.phase_progress += dt

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
        if speed_factor <= 0 and state.phase_progress > 20.0:
            speed_factor = 0.5
        if speed_factor > 0:
            ramp_speed = TAXI_SPEED_RAMP_KTS * speed_factor
            speed_deg = ramp_speed * _KTS_TO_DEG_PER_SEC * dt
            new_pos = _move_toward((state.latitude, state.longitude), target, speed_deg)
            state.latitude, state.longitude = new_pos
            state.velocity = ramp_speed
            state.phase_progress = 0.0
        else:
            state.velocity = 0
            speed_deg = 0
            state.phase_progress += dt

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
            state.turnaround_target_s = _compute_turnaround_target(state)
            state.parked_since = get_time()
            _occupy_gate(state.icao24, state.assigned_gate)
            # Record inbound delay for reactionary delay prediction
            # (TAXI_TO_GATE → PARKED is always an arrival)
            if state.assigned_gate:
                _h = (hash(state.icao24) ^ hash(state.callsign[:3] if state.callsign else "")) & 0xFFFF
                inbound_delay = (5 + ((_h >> 8) % 41)) if ((_h >> 4) % 5 == 0) else 0
                _calibration.gate_last_delay[state.assigned_gate] = float(inbound_delay)
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



def _compute_turnaround_target(state: FlightState) -> float:
    """Compute the gate turnaround duration (seconds) for a parked flight.

    Called once when entering PARKED phase. Incorporates calibration data,
    aircraft category, airline factors, weather, congestion, and jitter.
    """
    if _calibration.gate_minutes > 0:
        category = get_aircraft_category(state.aircraft_type)
        if category == "wide_body":
            gate_minutes = _calibration.gate_minutes * 1.4
        else:
            gate_minutes = _calibration.gate_minutes
    else:
        timing = get_turnaround_timing(state.aircraft_type)
        total_min = timing["total_minutes"]
        non_gate_min = (timing["phases"].get("arrival_taxi", 0)
                        + timing["phases"].get("pushback", 0)
                        + timing["phases"].get("departure_taxi", 0))
        gate_minutes = total_min - non_gate_min
    gate_seconds = gate_minutes * 60
    airline_code = state.callsign[:3] if state.callsign and len(state.callsign) >= 3 else ""
    airline_factor = AIRLINE_TURNAROUND_FACTOR.get(airline_code, _DEFAULT_AIRLINE_FACTOR)
    weather_factor = _get_turnaround_weather_factor()
    congestion_factor = _get_turnaround_congestion_factor()
    intl_factor = _get_turnaround_international_factor(state)
    dow_factor = _get_turnaround_day_of_week_factor()
    combined_factor = airline_factor * weather_factor * congestion_factor * intl_factor * dow_factor
    return gate_seconds * combined_factor * random.uniform(0.95, 1.05)


def _update_parked(state: FlightState, dt: float) -> None:
    """PARKED phase: turnaround timer then transition to PUSHBACK."""
    from src.ingestion.fallback import get_current_airport_iata

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

    if state.turnaround_target_s == 0.0:
        state.turnaround_target_s = _compute_turnaround_target(state)
    if state.time_at_gate > state.turnaround_target_s:
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



def _update_landing(state: FlightState, dt: float) -> None:
    """LANDING phase: flare, touchdown, rollout, runway exit."""
    from src.ingestion.fallback import TAXI_WAYPOINTS_ARRIVAL

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
        # Airborne flare: converge toward threshold unless already past it
        dist_to_thr = _distance_between((state.latitude, state.longitude), runway_touchdown)
        dist_to_far = _distance_between((state.latitude, state.longitude), runway_far_end)
        dist_thr_to_far = _distance_between(runway_touchdown, runway_far_end)
        past_threshold = dist_to_far < dist_thr_to_far

        if not past_threshold and dist_to_thr > 1e-6:
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
        # On-ground rollout: reverse thrust + wheel brakes
        # Real-world decel ~3-4 kts/s (reverse thrust dominant phase),
        # increasing to ~5 kts/s below 60kt when brakes take over.
        state.altitude = 0
        state.on_ground = True
        state.vertical_rate = 0
        if state.velocity > 60:
            # High-speed phase: reverse thrust only (~3.5 kts/s)
            decel_rate = 3.5
        else:
            # Low-speed phase: wheel brakes dominant (~5 kts/s)
            decel_rate = 5.0
        state.velocity = max(15, state.velocity - decel_rate * dt)

    # Early runway release: vacate when on ground and past initial rollout
    # Real airports: aircraft clears active runway within ~20-30s via high-speed exit
    if state.on_ground and state.velocity <= 80 and not getattr(state, '_runway_released', False):
        arrival_rwy = _assign_arrival_runway(state.icao24)
        _release_runway(state.icao24, arrival_rwy)
        state._runway_released = True

    if state.on_ground and state.velocity <= 55:
        # High-speed turnoff: aircraft vacates runway at ~50-60kt via angled exit
        emit_phase_transition(
            state.icao24, state.callsign,
            FlightPhase.LANDING.value, FlightPhase.TAXI_TO_GATE.value,
            state.latitude, state.longitude, state.altitude,
            state.aircraft_type, state.assigned_gate,
        )
        _set_phase(state, FlightPhase.TAXI_TO_GATE)
        state.landed_at = get_time()
        state.phase_progress = 0.0
        # Release runway when exiting to taxiway (may already be released by early release above)
        if not getattr(state, '_runway_released', False):
            arrival_rwy = _assign_arrival_runway(state.icao24)
            _release_runway(state.icao24, arrival_rwy)
        _clear_arrival_runway_assignment(state.icao24)
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
                # Route toward airport center (will be re-routed once a gate frees up)
                state.taxi_route = _get_taxi_waypoints_arrival("A1", start_pos=rollout_pos)

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



def _execute_go_around(state: FlightState, reason: str = "runway_busy") -> None:
    """Execute missed approach procedure — climb and transition to ENROUTE."""
    state.go_around_count += 1
    state.holding_phase_time = 0.0
    state.holding_inbound = True
    _clear_arrival_runway_assignment(state.icao24)

    if state.go_around_count >= 2:
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

    state.go_around_target_alt = max(3000.0, state.altitude + 500)
    state.vertical_rate = 1500

    vref_ga = VREF_SPEEDS.get(state.aircraft_type, _DEFAULT_VREF)
    target_ga_speed = vref_ga + 20
    if target_ga_speed > state.velocity:
        state.velocity = min(target_ga_speed, state.velocity + 10)

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


def _update_approaching(state: FlightState, dt: float) -> FlightState | None:
    """APPROACHING phase: descent on approach waypoints with separation."""
    # Go-around flights stuck in re-approach for >15 min: force divert
    if state.go_around_count > 0:
        state.go_around_hold_until += dt
        if state.go_around_hold_until > 900:
            _execute_go_around(state, reason="approach_timeout")
            return state

    approach_wps = _get_approach_waypoints(state.origin_airport)

    if state.waypoint_index < len(approach_wps):
        wp = approach_wps[state.waypoint_index]
        target = (wp[1], wp[0])
        target_alt = wp[2]

        if state.go_around_target_alt <= 0:
            while target_alt > state.altitude + 200 and state.waypoint_index < len(approach_wps) - 1:
                state.waypoint_index += 1
                wp = approach_wps[state.waypoint_index]
                target = (wp[1], wp[0])
                target_alt = wp[2]

        has_separation = _check_approach_separation(state)

        total_wps = len(approach_wps)
        if state.go_around_count > 0 and state.waypoint_index >= total_wps - 7:
            state.go_around_hold_until = 0.0
        progress = state.waypoint_index / max(1, total_wps - 1)
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

        speed_slow = 1.0
        ahead = _find_aircraft_ahead_on_approach(state)
        if ahead:
            dist = _distance_nm((state.latitude, state.longitude),
                               (ahead.latitude, ahead.longitude))
            req_sep = _get_required_separation(ahead.aircraft_type, state.aircraft_type) / NM_TO_DEG
            if dist < req_sep * 1.5:
                speed_slow = max(0.5, dist / (req_sep * 1.5))
        if not has_separation:
            if state.go_around_count > 0:
                speed_slow = min(speed_slow, 0.85)
            else:
                speed_slow = min(speed_slow, 0.6)

        vref = VREF_SPEEDS.get(state.aircraft_type, _DEFAULT_VREF)
        speed_ceiling = MAX_SPEED_BELOW_FL100_KTS if state.altitude < 10000 else MAX_VELOCITY_KTS
        raw_speed = min(prof_spd * speed_slow, speed_ceiling)
        if state.altitude < 1000:
            target_speed = min(vref + 20, max(vref, raw_speed))
        elif state.altitude < 2000:
            target_speed = min(vref + 30, max(vref, raw_speed))
        elif state.altitude < 3000:
            target_speed = min(vref + 50, max(vref, raw_speed))
        else:
            target_speed = max(vref * 0.9, raw_speed)
        decel_rate = 8.0
        max_speed_change = decel_rate * dt
        if target_speed > state.velocity:
            state.velocity = min(target_speed, state.velocity + 5.0 * dt)
        elif target_speed < state.velocity:
            state.velocity = max(target_speed, state.velocity - max_speed_change)

        speed_deg = state.velocity * _KTS_TO_DEG_PER_SEC * dt
        dist_to_wp = _distance_between((state.latitude, state.longitude), target)
        if dist_to_wp > 1e-8:
            dlat = target[0] - state.latitude
            dlon = target[1] - state.longitude
            ratio = min(speed_deg / dist_to_wp, 1.0)
            state.latitude += dlat * ratio
            state.longitude += dlon * ratio

        if state.go_around_target_alt > 0 and state.altitude < state.go_around_target_alt:
            climb_fps = 25.0
            state.altitude = min(state.go_around_target_alt, state.altitude + climb_fps * dt)
            state.vertical_rate = 1500
            if state.altitude >= state.go_around_target_alt:
                state.go_around_target_alt = 0.0
        else:
            state.go_around_target_alt = 0.0
            descent_fps = max(12.0, min(20.0, abs(prof_vr) / 60.0)) if prof_vr else 12.0
            effective_target = min(prof_alt, target_alt)
            prev_alt = state.altitude
            state.altitude = max(float(DECISION_HEIGHT_FT), _interpolate_altitude(state.altitude, effective_target, descent_fps * dt))
            above_path = prev_alt > target_alt + 500
            max_fpm = 1500.0 if (prev_alt > 3000 or above_path) else 800.0
            max_descent_per_tick = max_fpm / 60.0 * dt
            if prev_alt - state.altitude > max_descent_per_tick:
                state.altitude = prev_alt - max_descent_per_tick
            if state.altitude > prev_alt:
                state.vertical_rate = abs(prof_vr) if prof_vr else 1500
            else:
                state.vertical_rate = prof_vr

        if state.altitude <= DECISION_HEIGHT_FT:
            # Must be near runway threshold to transition to LANDING
            max_dist = 0.05 if state.go_around_count > 0 else 0.03
            rwy_threshold = _get_runway_threshold()
            if rwy_threshold:
                dist_to_rwy = _distance_between(
                    (state.latitude, state.longitude), (rwy_threshold[1], rwy_threshold[0])
                )
                if dist_to_rwy > max_dist:
                    state.altitude = float(DECISION_HEIGHT_FT)
                    state.vertical_rate = 0
                    return state

            arrival_rwy = _assign_arrival_runway(state.icao24)
            runway_ok = (_is_runway_scenario_open(arrival_rwy)
                         and (_is_runway_clear(arrival_rwy) or state.go_around_count >= 2))
            if not runway_ok:
                from src.ingestion._approach_departure import (
                    _get_all_arrival_runway_names, _clear_arrival_runway_assignment,
                )
                all_rwys = _get_all_arrival_runway_names()
                for alt_rwy in all_rwys:
                    if alt_rwy == arrival_rwy:
                        continue
                    if _is_runway_clear(alt_rwy) and _is_runway_scenario_open(alt_rwy):
                        _clear_arrival_runway_assignment(state.icao24)
                        arrival_rwy = alt_rwy
                        runway_ok = True
                        break
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
                _get_runway_state(arrival_rwy).last_arrival_time = get_time()
            else:
                _execute_go_around(state, "runway_busy")
                return state

        target_hdg = _calculate_heading((state.latitude, state.longitude), target)
        state.heading = _smooth_heading(state.heading, target_hdg, 3.0, dt)

        if _distance_between((state.latitude, state.longitude), target) < 0.003:
            state.waypoint_index += 1
            if state.waypoint_index < len(approach_wps):
                next_wp = approach_wps[state.waypoint_index]
                next_target = (next_wp[1], next_wp[0])
                next_hdg = _calculate_heading(
                    (state.latitude, state.longitude), next_target
                )
                state.heading = _smooth_heading(state.heading, next_hdg, 3.0, dt)
    else:
        if state.altitude > 2500 and state.go_around_count == 0:
            _execute_go_around(state, "high_altitude_at_threshold")
        elif state.altitude > DECISION_HEIGHT_FT + 200:
            state.altitude = max(float(DECISION_HEIGHT_FT), state.altitude - 1500.0 / 60.0 * dt)
            state.vertical_rate = -1500
            return state
        else:
            max_dist = 0.05 if state.go_around_count > 0 else 0.03
            rwy_threshold = _get_runway_threshold()
            if rwy_threshold:
                dist_to_rwy = _distance_between(
                    (state.latitude, state.longitude), (rwy_threshold[1], rwy_threshold[0])
                )
                if dist_to_rwy > max_dist:
                    state.altitude = float(DECISION_HEIGHT_FT)
                    state.vertical_rate = 0
                    return state

            arrival_rwy = _assign_arrival_runway(state.icao24)
            runway_ok = (_is_runway_scenario_open(arrival_rwy)
                         and (_is_runway_clear(arrival_rwy) or state.go_around_count >= 2))
            if not runway_ok:
                from src.ingestion._approach_departure import (
                    _get_all_arrival_runway_names, _clear_arrival_runway_assignment,
                )
                all_rwys = _get_all_arrival_runway_names()
                for alt_rwy in all_rwys:
                    if alt_rwy == arrival_rwy:
                        continue
                    if _is_runway_clear(alt_rwy) and _is_runway_scenario_open(alt_rwy):
                        _clear_arrival_runway_assignment(state.icao24)
                        arrival_rwy = alt_rwy
                        runway_ok = True
                        break
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
                _get_runway_state(arrival_rwy).last_arrival_time = get_time()
            else:
                _execute_go_around(state, "runway_busy_at_threshold")
    return None


def _update_enroute(state: FlightState, dt: float) -> FlightState | None:
    """ENROUTE phase: arriving approach intercept, departing climb-out, holding."""
    from src.ingestion.fallback import get_airport_center, get_current_airport_iata

    EXIT_RADIUS_DEG = 0.5
    APPROACH_RADIUS_DEG = 0.25

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
        if state.go_around_target_alt > 0 and state.altitude < state.go_around_target_alt:
            climb_fps = 25.0
            state.altitude = min(state.go_around_target_alt, state.altitude + climb_fps * dt)
            state.vertical_rate = 1500
            speed_deg = state.velocity * _KTS_TO_DEG_PER_SEC * dt
            state.latitude += math.cos(math.radians(state.heading)) * speed_deg
            state.longitude += math.sin(math.radians(state.heading)) * speed_deg / max(0.01, math.cos(math.radians(state.latitude)))
            if state.altitude >= state.go_around_target_alt:
                state.go_around_target_alt = 0.0
                state.holding_phase_time = -180.0
            state.heading = state.heading % 360
            return state

        if state.holding_phase_time < 0:
            state.holding_phase_time += dt
            speed_deg = state.velocity * _KTS_TO_DEG_PER_SEC * dt
            state.latitude += math.cos(math.radians(state.heading)) * speed_deg
            state.longitude += math.sin(math.radians(state.heading)) * speed_deg / max(0.01, math.cos(math.radians(state.latitude)))
            state.vertical_rate = 0
            return state

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
            turn_rate = 2.0
            clockwise_diff = (target_heading - state.heading + 360) % 360
            if clockwise_diff <= 180:
                state.heading = (state.heading + min(clockwise_diff, turn_rate * dt)) % 360
            else:
                state.heading = (state.heading + turn_rate * dt) % 360
        else:
            turn_rate = max(0.5, min(1.5, dist_from_airport / 0.08))
            state.heading += max(-turn_rate, min(turn_rate, heading_diff)) * dt
            state.heading = state.heading % 360

        if dist_from_airport < EXIT_RADIUS_DEG and state.altitude > 3000:
            frac = max(0.0, (dist_from_airport - 0.17) / (EXIT_RADIUS_DEG - 0.17))
            target_alt = max(3000.0, 3000.0 + frac * (35000.0 - 3000.0))
            if state.altitude > target_alt:
                max_fpm = 3500.0 if state.altitude > 10000 else 2000.0
                descent_rate = min(max_fpm, (state.altitude - target_alt) * 2.0)
                state.altitude -= descent_rate * dt / 60.0
                state.altitude = max(target_alt, state.altitude)
                state.vertical_rate = -descent_rate

        if state.altitude < 3000:
            state.velocity = min(state.velocity, 180)
        elif state.altitude < 5000:
            state.velocity = min(state.velocity, 210)
        elif state.altitude < 10000:
            state.velocity = min(state.velocity, MAX_SPEED_BELOW_FL100_KTS)

        approach_count = (_count_aircraft_in_phase(FlightPhase.APPROACHING)
                          + _count_aircraft_in_phase(FlightPhase.LANDING))
        can_start_approach = (approach_count < get_max_approach_aircraft()
                              or state.go_around_count > 0)

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

        if can_start_approach and dist_from_airport < reentry_radius and ga_aligned and state.altitude <= 10000:
            emit_phase_transition(
                state.icao24, state.callsign,
                FlightPhase.ENROUTE.value, FlightPhase.APPROACHING.value,
                state.latitude, state.longitude, state.altitude,
                state.aircraft_type, state.assigned_gate,
            )
            _set_phase(state, FlightPhase.APPROACHING)
            state.velocity = min(state.velocity, MAX_SPEED_BELOW_FL100_KTS)
            state.waypoint_index = _snap_to_nearest_waypoint(state)
            state.star_name = _get_star_name(state.origin_airport)
            if state.go_around_count > 0:
                approach_wps = _get_approach_waypoints(state.origin_airport)
                if approach_wps and state.waypoint_index < len(approach_wps):
                    wp_alt = approach_wps[state.waypoint_index][2] if len(approach_wps[state.waypoint_index]) > 2 else 3000
                    if wp_alt > state.altitude:
                        state.go_around_target_alt = float(wp_alt)
            _dp = get_descent_profile(state.aircraft_type)
            _, _ps, _pv = interpolate_profile(_dp, 0.5)
            state.vertical_rate = _pv if _pv else -800
        elif can_start_approach and state.altitude <= 10000 and random.random() < 0.01 * dt and dist_from_airport < 0.35:
            emit_phase_transition(
                state.icao24, state.callsign,
                FlightPhase.ENROUTE.value, FlightPhase.APPROACHING.value,
                state.latitude, state.longitude, state.altitude,
                state.aircraft_type, state.assigned_gate,
            )
            _set_phase(state, FlightPhase.APPROACHING)
            state.velocity = min(state.velocity, MAX_SPEED_BELOW_FL100_KTS)
            state.waypoint_index = _snap_to_nearest_waypoint(state)
            state.star_name = _get_star_name(state.origin_airport)
            _dp = get_descent_profile(state.aircraft_type)
            _, _ps, _pv = interpolate_profile(_dp, 0.5)
            state.vertical_rate = _pv if _pv else -800
        elif not can_start_approach and dist_from_airport < APPROACH_RADIUS_DEG:
            HOLDING_LEG_SECONDS = 90.0
            HOLDING_TURN_SECONDS = 60.0
            STANDARD_RATE_DEG_S = 3.0

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
                target_heading = _calculate_heading(
                    (state.latitude, state.longitude), center
                )
                hdg_diff = (target_heading - state.heading + 360) % 360
                if hdg_diff > 0 and hdg_diff <= 180:
                    state.heading = (state.heading + min(hdg_diff, STANDARD_RATE_DEG_S * dt)) % 360
                elif hdg_diff > 180:
                    state.heading = (state.heading + STANDARD_RATE_DEG_S * dt) % 360
                if state.holding_phase_time >= HOLDING_LEG_SECONDS:
                    state.holding_phase_time = 0.0
                    state.holding_inbound = False
            else:
                if state.holding_phase_time < HOLDING_TURN_SECONDS:
                    state.heading = (state.heading + STANDARD_RATE_DEG_S * dt) % 360
                elif state.holding_phase_time < HOLDING_TURN_SECONDS + HOLDING_LEG_SECONDS:
                    pass
                else:
                    state.holding_phase_time = 0.0
                    state.holding_inbound = True

    elif state.destination_airport and state.destination_airport != _local:
        target_heading = _bearing_to_airport(state.destination_airport)
        heading_diff = (target_heading - state.heading + 540) % 360 - 180
        state.heading += max(-3, min(3, heading_diff)) * dt
        state.heading = state.heading % 360

        if state.cruise_altitude == 0.0:
            if state.heading < 180:
                state.cruise_altitude = random.choice([35000, 37000, 39000])
            else:
                state.cruise_altitude = random.choice([34000, 36000, 38000])
        if state.altitude < state.cruise_altitude:
            max_climb_fpm = 2500 if state.altitude < 20000 else 1500
            alt_step = min(max_climb_fpm / 60.0 * dt, state.cruise_altitude - state.altitude)
            state.altitude += alt_step
            state.vertical_rate = max_climb_fpm

        if state.altitude < 10000:
            target_spd = min(state.velocity, MAX_SPEED_BELOW_FL100_KTS)
        else:
            target_spd = 450 if state.altitude > 20000 else 300
        max_accel = 2.0 * dt
        if target_spd > state.velocity:
            state.velocity = min(target_spd, state.velocity + max_accel)
        elif target_spd < state.velocity:
            state.velocity = max(target_spd, state.velocity - max_accel)

        if dist_from_airport > EXIT_RADIUS_DEG:
            state.phase_progress = -1.0
            return state

    else:
        if dist_from_airport > EXIT_RADIUS_DEG:
            state.heading = _calculate_heading(
                (state.latitude, state.longitude), center
            )
        else:
            pass

        if random.random() < 0.005 * dt:
            _set_phase(state, FlightPhase.APPROACHING)
            state.waypoint_index = _snap_to_nearest_waypoint(state)
            state.star_name = _get_star_name(state.origin_airport)

    if state.altitude < 10000:
        state.velocity = min(state.velocity, MAX_SPEED_BELOW_FL100_KTS)

    speed_deg = state.velocity * _KTS_TO_DEG_PER_SEC * dt
    state.latitude += math.cos(math.radians(state.heading)) * speed_deg
    state.longitude += math.sin(math.radians(state.heading)) * speed_deg / max(0.01, math.cos(math.radians(state.latitude)))
    return None


def _update_departing(state: FlightState, dt: float) -> None:
    """DEPARTING phase: climb out following SID waypoints, then continue to FL180."""
    departure_wps = _get_departure_waypoints(state.destination_airport)
    if state.waypoint_index < len(departure_wps):
        wp = departure_wps[state.waypoint_index]
        target = (wp[1], wp[0])
        target_alt = wp[2]

        total_wps = len(departure_wps)
        progress = state.waypoint_index / max(1, total_wps - 1)
        profile_progress = 0.4 * progress
        climb_prof = get_climb_profile(state.aircraft_type)
        prof_alt, prof_spd, prof_vr = interpolate_profile(climb_prof, profile_progress)

        target_spd = min(prof_spd, MAX_SPEED_BELOW_FL100_KTS) if state.altitude < 10000 else prof_spd
        max_accel = 2.0 * dt
        if target_spd > state.velocity:
            state.velocity = min(target_spd, state.velocity + max_accel)
        else:
            state.velocity = max(target_spd, state.velocity - max_accel)

        speed_deg = state.velocity * _KTS_TO_DEG_PER_SEC * dt
        dist_to_wp = _distance_between((state.latitude, state.longitude), target)
        if dist_to_wp > 1e-8:
            dlat = target[0] - state.latitude
            dlon = target[1] - state.longitude
            ratio = min(speed_deg / dist_to_wp, 1.0)
            state.latitude += dlat * ratio
            state.longitude += dlon * ratio

        max_climb_fpm = abs(prof_vr) if prof_vr and prof_vr > 0 else 2500
        max_climb_fpm = min(max_climb_fpm, 2500)
        alt_step = max_climb_fpm / 60.0 * dt
        new_alt = max(0.0, _interpolate_altitude(state.altitude, target_alt, alt_step))
        state.altitude = max(state.altitude, new_alt)
        state.vertical_rate = prof_vr if (state.altitude < target_alt or state.altitude < prof_alt) else 0

        target_hdg = _calculate_heading((state.latitude, state.longitude), target)
        state.heading = _smooth_heading(state.heading, target_hdg, 3.0, dt)

        if _distance_between((state.latitude, state.longitude), target) < 0.005:
            state.waypoint_index += 1
    else:
        if state.altitude < 18000:
            climb_prof = get_climb_profile(state.aircraft_type)
            frac = min(1.0, 0.4 + 0.2 * (state.altitude / 18000.0))
            _, prof_spd, prof_vr = interpolate_profile(climb_prof, frac)
            target_spd = min(prof_spd, MAX_SPEED_BELOW_FL100_KTS) if state.altitude < 10000 else prof_spd
            max_accel = 2.0 * dt
            if target_spd > state.velocity:
                state.velocity = min(target_spd, state.velocity + max_accel)
            else:
                state.velocity = max(target_spd, state.velocity - max_accel)
            climb_fpm = prof_vr if prof_vr > 0 else 1500
            climb_fpm = min(climb_fpm, 2500)
            state.vertical_rate = climb_fpm
            state.altitude += climb_fpm / 60.0 * dt
            speed_deg = state.velocity * _KTS_TO_DEG_PER_SEC * dt
            state.latitude += math.cos(math.radians(state.heading)) * speed_deg
            state.longitude += math.sin(math.radians(state.heading)) * speed_deg / max(0.01, math.cos(math.radians(state.latitude)))
        else:
            emit_phase_transition(
                state.icao24, state.callsign,
                FlightPhase.DEPARTING.value, FlightPhase.ENROUTE.value,
                state.latitude, state.longitude, state.altitude,
                state.aircraft_type, state.assigned_gate,
            )
            _set_phase(state, FlightPhase.ENROUTE)
            if state.destination_airport:
                state.heading = _bearing_to_airport(state.destination_airport)


def _update_taxi_to_runway(state: FlightState, dt: float) -> FlightState | None:
    """TAXI_TO_RUNWAY phase: waypoint following → queue hold → runway entry."""
    from src.ingestion.fallback import TAXI_WAYPOINTS_DEPARTURE

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
            state.velocity = 0
            speed_deg = 0
        else:
            state.velocity = 0
            speed_deg = 0

        target_hdg = _calculate_heading((state.latitude, state.longitude), target)
        state.heading = _smooth_heading(state.heading, target_hdg, 5.0, dt)

        if _distance_between((state.latitude, state.longitude), target) < max(speed_deg, 0.0005):
            state.waypoint_index += 1
    elif state.departure_queue_hold_s > 0:
        state.departure_queue_hold_s -= dt
        _, _, dep_hdg, _ = _get_takeoff_runway_geometry()
        state.velocity = 0
        state.heading = _smooth_heading(state.heading, dep_hdg, 5.0, dt)
    else:
        _, _, dep_hdg, _ = _get_takeoff_runway_geometry()
        state.heading = _smooth_heading(state.heading, dep_hdg, 5.0, dt)
        if not state.departure_queue_set and _calibration.taxi_out_target_s > 0:
            queue_base = max(0.0, _calibration.taxi_out_target_s - _calibration.taxi_out_waypoint_s)
            p95_budget = max(0.0, _calibration.taxi_out_p95_s - _calibration.taxi_out_waypoint_s) * 0.7
            state.departure_queue_hold_s = min(queue_base * random.uniform(0.70, 1.10), p95_budget)
            state.departure_queue_set = True
            if state.departure_queue_hold_s > 0:
                state.velocity = 0
                return state

        dep_rwy = _get_departure_runway_name()
        runway_clear = _is_runway_clear(dep_rwy)
        state.phase_progress += dt
        p95_exceeded = (_calibration.taxi_out_p95_s > 0
                        and state.phase_progress > 180.0)
        if runway_clear or p95_exceeded:
            runway_st = _get_runway_state(dep_rwy)
            elapsed = get_time() - runway_st.last_departure_time
            lead_cat = runway_st.last_departure_type
            follow_cat = _get_wake_category(state.aircraft_type)
            required = DEPARTURE_SEPARATION_S.get(
                (lead_cat, follow_cat), DEFAULT_DEPARTURE_SEPARATION_S
            )
            if p95_exceeded:
                required = min(required, 30.0)
            if elapsed >= required:
                emit_phase_transition(
                    state.icao24, state.callsign,
                    FlightPhase.TAXI_TO_RUNWAY.value, FlightPhase.TAKEOFF.value,
                    state.latitude, state.longitude, state.altitude,
                    state.aircraft_type, state.assigned_gate,
                )
                _set_phase(state, FlightPhase.TAKEOFF)
                state.velocity = 0
                _, _, dep_hdg, _ = _get_takeoff_runway_geometry()
                state.heading = dep_hdg
                state.takeoff_subphase = "lineup"
                state.phase_progress = 0.0
                state.takeoff_roll_dist_ft = 0.0
                state.sid_name = _get_sid_name(state.destination_airport)
                _occupy_runway(state.icao24, dep_rwy)
            else:
                state.velocity = 0
                _, _, dep_hdg, _ = _get_takeoff_runway_geometry()
                state.heading = _smooth_heading(state.heading, dep_hdg, 5.0, dt)
        else:
            state.velocity = 0
            _, _, dep_hdg, _ = _get_takeoff_runway_geometry()
            state.heading = _smooth_heading(state.heading, dep_hdg, 5.0, dt)
    return None


def _update_takeoff(state: FlightState, dt: float) -> None:
    """TAKEOFF phase: lineup → roll → rotate → liftoff → initial_climb (14 CFR 25.107/111)."""
    perf = TAKEOFF_PERFORMANCE.get(state.aircraft_type, _DEFAULT_TAKEOFF_PERF)
    v1, vr, v2, accel_rate, climb_fpm = perf

    rwy_start, rwy_end, rwy_heading, rwy_len_ft = _get_takeoff_runway_geometry()
    rwy_dlat = rwy_end[0] - rwy_start[0]
    rwy_dlon = rwy_end[1] - rwy_start[1]
    rwy_len_deg = math.sqrt(rwy_dlat**2 + rwy_dlon**2)

    state.heading = rwy_heading

    if state.takeoff_subphase == "lineup":
        state.on_ground = True
        dist_to_rwy = _distance_between((state.latitude, state.longitude), (rwy_start[0], rwy_start[1]))
        if dist_to_rwy > 0.0002:
            lineup_speed = 10.0
            state.velocity = lineup_speed
            speed_deg = lineup_speed * _KTS_TO_DEG_PER_SEC * dt
            new_pos = _move_toward((state.latitude, state.longitude), (rwy_start[0], rwy_start[1]), speed_deg)
            state.latitude, state.longitude = new_pos
            state.heading = _smooth_heading(state.heading, rwy_heading, 8.0, dt)
        else:
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
        state.velocity = min(state.velocity + accel_rate * dt, vr)
        state.on_ground = True
        velocity_ft_s = state.velocity * 1.6878
        state.takeoff_roll_dist_ft += velocity_ft_s * dt
        roll_frac = min(state.takeoff_roll_dist_ft / rwy_len_ft, 0.95)
        state.latitude = rwy_start[0] + rwy_dlat * roll_frac
        state.longitude = rwy_start[1] + rwy_dlon * roll_frac
        if state.velocity >= vr:
            state.takeoff_subphase = "rotate"
            state.phase_progress = 0.0

    elif state.takeoff_subphase == "rotate":
        state.velocity = min(state.velocity + accel_rate * 0.8 * dt, v2 + 5)
        state.on_ground = True
        velocity_ft_s = state.velocity * 1.6878
        state.takeoff_roll_dist_ft += velocity_ft_s * dt
        roll_frac = min(state.takeoff_roll_dist_ft / rwy_len_ft, 0.98)
        state.latitude = rwy_start[0] + rwy_dlat * roll_frac
        state.longitude = rwy_start[1] + rwy_dlon * roll_frac
        state.phase_progress += dt
        state.vertical_rate = min(500 * (state.phase_progress / 3.0), 500)
        state.altitude += state.vertical_rate / 60.0 * dt
        if state.phase_progress >= 3.0 or state.velocity >= v2:
            state.takeoff_subphase = "liftoff"
            state.phase_progress = 0.0
            state.on_ground = False

    elif state.takeoff_subphase == "liftoff":
        state.on_ground = False
        state.velocity = min(state.velocity + accel_rate * 0.5 * dt, v2 + 10)
        state.phase_progress += dt
        ramp = min(state.phase_progress / 5.0, 1.0)
        state.vertical_rate = 500 + (climb_fpm - 500) * ramp
        state.altitude += state.vertical_rate / 60.0 * dt
        speed_deg = state.velocity * _KTS_TO_DEG_PER_SEC * dt
        state.latitude += (rwy_dlat / rwy_len_deg) * speed_deg
        state.longitude += (rwy_dlon / rwy_len_deg) * speed_deg
        if state.altitude >= 35:
            state.takeoff_subphase = "initial_climb"
            state.phase_progress = 0.0

    elif state.takeoff_subphase == "initial_climb":
        state.on_ground = False
        state.velocity = min(state.velocity + accel_rate * 0.3 * dt, v2 + 10)
        state.vertical_rate = climb_fpm
        state.altitude += climb_fpm / 60.0 * dt
        speed_deg = state.velocity * _KTS_TO_DEG_PER_SEC * dt
        state.latitude += (rwy_dlat / rwy_len_deg) * speed_deg
        state.longitude += (rwy_dlon / rwy_len_deg) * speed_deg

        if state.altitude >= 500:
            _release_runway(state.icao24, _get_departure_runway_name(), state.aircraft_type)
            emit_phase_transition(
                state.icao24, state.callsign,
                FlightPhase.TAKEOFF.value, FlightPhase.DEPARTING.value,
                state.latitude, state.longitude, state.altitude,
                state.aircraft_type, state.assigned_gate,
            )
            _set_phase(state, FlightPhase.DEPARTING)
            state.waypoint_index = 0
            state.takeoff_subphase = "lineup"
            state.takeoff_roll_dist_ft = 0.0


def _update_pushback(state: FlightState, dt: float) -> None:
    """PUSHBACK phase: tug connect → push → engine start → taxi."""
    pb_heading = _get_pushback_heading(state.assigned_gate) if state.assigned_gate else 180.0
    state.phase_progress += dt / 150.0
    is_pushing = 0.2 <= state.phase_progress < 0.6
    if is_pushing and _check_taxi_separation(state):
        state.velocity = TAXI_SPEED_PUSHBACK_KTS
        pb_rad = math.radians(pb_heading)
        pb_speed_deg = TAXI_SPEED_PUSHBACK_KTS * _KTS_TO_DEG_PER_SEC * dt
        state.latitude += pb_speed_deg * math.cos(pb_rad)
        state.longitude += pb_speed_deg * math.sin(pb_rad)
    else:
        state.velocity = 0

    nose_target = (pb_heading + 180) % 360
    state.heading = _smooth_heading(state.heading, nose_target, 3.0, dt)

    if state.phase_progress >= 1.0:
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


def _update_flight_state(state: FlightState, dt: float) -> FlightState:
    """Update a flight's state based on its current phase.

    Implements FAA/ICAO separation standards:
    - Approach: 3-6 NM based on wake turbulence category
    - Runway: Single occupancy (one aircraft at a time)
    - Taxi: Visual separation (~150-300 ft)
    """
    from src.ingestion.fallback import get_airport_center, get_current_airport_iata, get_gates, TAXI_WAYPOINTS_ARRIVAL, TAXI_WAYPOINTS_DEPARTURE

    if state.phase == FlightPhase.APPROACHING:
        early = _update_approaching(state, dt)
        if early is not None:
            return early

    elif state.phase == FlightPhase.LANDING:
        _update_landing(state, dt)

    elif state.phase == FlightPhase.TAXI_TO_GATE:
        _update_taxi_to_gate(state, dt)

    elif state.phase == FlightPhase.PARKED:
        _update_parked(state, dt)

    elif state.phase == FlightPhase.PUSHBACK:
        _update_pushback(state, dt)

    elif state.phase == FlightPhase.TAXI_TO_RUNWAY:
        early = _update_taxi_to_runway(state, dt)
        if early is not None:
            return early

    elif state.phase == FlightPhase.TAKEOFF:
        _update_takeoff(state, dt)

    elif state.phase == FlightPhase.DEPARTING:
        _update_departing(state, dt)

    elif state.phase == FlightPhase.ENROUTE:
        early = _update_enroute(state, dt)
        if early is not None:
            return early

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

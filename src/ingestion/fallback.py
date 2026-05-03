"""Synthetic flight data generator with realistic stateful movements.

Generates persistent flight states with realistic behaviors:
- Landing approach and touchdown with proper separation
- Taxi from runway to gate
- Parked at gate
- Pushback and taxi to runway
- Takeoff and departure climb

Aircraft Separation Standards (FAA/ICAO):
- Approach: 3-6 NM minimum depending on wake turbulence category
- Runway: Only one aircraft at a time
- Taxi: ~150-300 ft minimum visual separation
- Gate: Aircraft dimensions + safety buffer
"""

import logging
import math
import random
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

from src.simulation.diagnostics import diag_log

from src.simulation.openap_profiles import (
    get_descent_profile,
    get_climb_profile,
    interpolate_profile,
)
from faker import Faker

from src.ml.gse_model import get_turnaround_timing, get_aircraft_category, PHASE_DEPENDENCIES

from src.ingestion._state import (  # noqa: F401 — re-exported for backward compatibility
    FlightPhase,
    FlightState,
    _FlightStateDict,
    _flights_by_phase,
    _flight_states,
    _last_update,
    _set_phase,
    MAX_APPROACH_AIRCRAFT,
    RunwayState,
    GateState,
    GATE_BUFFER_SECONDS,
    _gate_conflict_count,
    _occupied_gate_count,
    _runway_states,
    _runway_28L,
    _runway_28R,
    _gate_states,
)

from src.ingestion._event_buffers import (  # noqa: F401 — re-exported for backward compatibility
    emit_phase_transition,
    emit_gate_event,
    emit_prediction,
    emit_turnaround_event,
    drain_phase_transitions,
    drain_gate_events,
    drain_predictions,
    drain_turnaround_events,
    set_suppress_phase_transitions,
)

from src.ingestion._geo import (  # noqa: F401 — re-exported for backward compatibility
    _sanitize_float,
    _shortest_angle_diff,
    _calculate_heading,
    _smooth_heading,
    _distance_between,
    _distance_nm,
    _distance_meters,
    _move_toward,
    _interpolate_altitude,
    _point_on_circle,
    _offset_position_by_heading,
    _entry_direction_quadrant,
    _point_to_segment_distance_m,
    _point_in_polygon,
)

from src.ingestion._constants import (  # noqa: F401 — re-exported for backward compatibility
    AIRLINE_TURNAROUND_FACTOR,
    _DEFAULT_AIRLINE_FACTOR,
    _AIRLINE_NAMES,
    WAKE_CATEGORY,
    WAKE_SEPARATION_NM,
    DEFAULT_SEPARATION_NM,
    _KTS_TO_DEG_PER_SEC,
    TAXI_SPEED_STRAIGHT_KTS,
    TAXI_SPEED_TURN_KTS,
    TAXI_SPEED_RAMP_KTS,
    TAXI_SPEED_PUSHBACK_KTS,
    MAX_SPEED_BELOW_FL100_KTS,
    MAX_VELOCITY_KTS,
    DECISION_HEIGHT_FT,
    STABILIZED_APPROACH_GATE_FT,
    STABILIZED_MAX_SPEED_OVER_VREF,
    STABILIZED_MAX_SINK_RATE,
    VREF_SPEEDS,
    _DEFAULT_VREF,
    NM_TO_DEG,
    MIN_APPROACH_SEPARATION_DEG,
    MIN_TAXI_SEPARATION_DEG,
    MIN_TAXI_SEPARATION_ARRIVAL_DEG,
    CROSSING_ZONE_DEG,
    MIN_GATE_SEPARATION_DEG,
    AIRCRAFT_HALF_LENGTH_M,
    _DEFAULT_HALF_LENGTH_M,
    TAKEOFF_PERFORMANCE,
    _DEFAULT_TAKEOFF_PERF,
    DEPARTURE_SEPARATION_S,
    DEFAULT_DEPARTURE_SEPARATION_S,
    MIN_ARRIVAL_SEPARATION_S,
    AIRLINE_FLEET,
    CALLSIGN_PREFIXES,
    _STAR_CORRIDORS,
    _SID_CORRIDORS,
    _AIRPORT_COUNTRY,
    _MAX_BUFFER_SIZE,
    _SFO_CENTER,
    MIN_GATES_FOR_OPERATIONS,
    MAX_OVERFLOW_STANDS,
)

from src.ingestion._runway_ops import (  # noqa: F401 — re-exported for backward compatibility
    _get_runway_state,
    _get_reciprocal_designator,
    _get_departure_runway_name,
    _recount_occupied_gates,
    _init_gate_states,
    _reset_gate_states,
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
    get_gate_conflict_count,
    reset_gate_conflict_count,
    _check_taxi_separation,
    _taxi_speed_factor,
    _count_aircraft_in_phase,
    _get_approach_queue_position,
)

from src.ingestion._approach_departure import (  # noqa: F401 — re-exported for backward compatibility
    _get_airport_coordinates,
    _bearing_cache,
    _bearing_from_airport,
    _bearing_to_airport,
    _get_osm_primary_runway,
    _osm_runway_endpoints,
    _get_fallback_runway,
    _get_runway_threshold,
    _get_runway_heading,
    _get_arrival_runway_name,
    _get_departure_runway,
    _get_takeoff_runway_geometry,
    _get_arrival_runway_endpoints,
    _get_departure_runway_endpoints,
    _get_star_name,
    _get_approach_waypoints,
    _get_sid_name,
    _get_departure_waypoints,
    _snap_to_nearest_waypoint,
)

from src.ingestion._taxi_routing import (  # noqa: F401 — re-exported for backward compatibility
    _compute_taxiway_line,
    _project_onto_line,
    _t_on_line,
    _generate_taxi_spine,
    _smooth_sharp_turns,
    get_terminal_center,
    _build_arrival_taxi_route,
    _build_departure_taxi_route,
    _get_taxi_waypoints_arrival,
    _get_taxi_waypoints_departure,
    _get_pushback_heading,
    _is_gate_inside_terminal,
    _gate_to_terminal_edge_distance_m,
    _compute_gate_standoff,
    _get_parked_heading,
)


fake = Faker()


# (_sanitize_float now imported from _geo)


# (AIRLINE_TURNAROUND_FACTOR, _DEFAULT_AIRLINE_FACTOR now imported from _constants)

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


# (_occupied_gate_count now imported from _state)
# (_recount_occupied_gates now imported from _runway_ops)


def _get_turnaround_congestion_factor() -> float:
    """More concurrent gate ops = longer turnaround due to crew contention."""
    return 1.0 + 0.01 * max(0, _occupied_gate_count - 10)


def _get_turnaround_day_of_week_factor() -> float:
    """Weekend turnarounds are ~5% slower (fewer ground crew on roster)."""
    dow = datetime.now(timezone.utc).weekday()
    if dow >= 5:  # Saturday or Sunday
        return 1.05
    return 1.0


def _get_turnaround_international_factor(state: "FlightState") -> float:
    """International flights have longer turnarounds (+25%)."""
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
    active = len(_flight_states)
    gate_count = len(get_gates())
    capacity = max(15, int(gate_count * 1.5)) if gate_count > 0 else 50
    return active / capacity


# (Event buffers — emit/drain functions now imported from _event_buffers)


def get_flight_turnaround_info(icao24: str) -> Optional[Dict[str, Any]]:
    """Get turnaround info for a flight from simulation state.

    Returns None if the flight is not found or not in PARKED phase.
    Turnaround data is only meaningful when an aircraft is docked at a gate.
    """
    state = _flight_states.get(icao24)
    if state is None:
        return None
    # Only return turnaround data for aircraft actually parked at a gate
    if state.phase != FlightPhase.PARKED:
        return {
            "parked_since": None,
            "time_at_gate_seconds": 0,
            "assigned_gate": state.assigned_gate,
            "aircraft_type": state.aircraft_type,
            "callsign": state.callsign,
            "phase": state.phase.value,
            "turnaround_phase": "",
            "turnaround_schedule": None,
        }
    return {
        "parked_since": datetime.fromtimestamp(state.parked_since, tz=timezone.utc) if state.parked_since > 0 else None,
        "time_at_gate_seconds": state.time_at_gate,
        "assigned_gate": state.assigned_gate,
        "aircraft_type": state.aircraft_type,
        "callsign": state.callsign,
        "phase": state.phase.value,
        "turnaround_phase": state.turnaround_phase,
        "turnaround_schedule": state.turnaround_schedule,
    }


def get_current_flight_states() -> List[Dict[str, Any]]:
    """Snapshot current flight states for persistence."""
    snapshots = []
    for icao24, state in _flight_states.items():
        snapshots.append({
            "icao24": icao24,
            "callsign": state.callsign,
            "latitude": state.latitude,
            "longitude": state.longitude,
            "altitude": state.altitude,
            "velocity": 0 if state.phase == FlightPhase.PARKED else state.velocity,
            "heading": state.heading,
            "vertical_rate": state.vertical_rate,
            "on_ground": state.on_ground,
            "flight_phase": state.phase.value,
            "aircraft_type": state.aircraft_type,
            "assigned_gate": state.assigned_gate,
            "origin_airport": state.origin_airport,
            "destination_airport": state.destination_airport,
            "snapshot_time": datetime.now(timezone.utc).isoformat(),
        })
    return snapshots


# (_AIRLINE_NAMES now imported from _constants)


def get_flights_as_schedule(
    sim_time: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Convert current synthetic flight states into FIDS schedule entries.

    This ensures the FIDS display shows the same flights that are visible
    on the map, rather than independently generated schedule data.

    Args:
        sim_time: Simulation clock time. If provided, all time calculations
                  use this instead of wall clock. This keeps FIDS aligned
                  with the simulation replay.

    Returns:
        List of schedule-format dicts compatible with ScheduleService.
    """
    now = sim_time or datetime.now(timezone.utc)
    schedule = []

    for icao24, state in _flight_states.items():
        callsign = state.callsign.strip() if state.callsign else ""
        airline_code = callsign[:3].upper() if len(callsign) >= 3 else "UAL"
        # Try ICAO 3-letter, then IATA 2-letter prefix
        airline_name = _AIRLINE_NAMES.get(airline_code) or _AIRLINE_NAMES.get(callsign[:2].upper(), airline_code)

        local_iata = get_current_airport_iata()
        origin = state.origin_airport or "???"
        destination = state.destination_airport or local_iata

        # Determine flight type using phase as a strong signal for in-flight
        # aircraft, falling back to origin/destination convention for ambiguous phases.
        phase = state.phase
        arriving_phases = (FlightPhase.APPROACHING, FlightPhase.LANDING, FlightPhase.TAXI_TO_GATE)
        departing_phases = (FlightPhase.PUSHBACK, FlightPhase.TAXI_TO_RUNWAY, FlightPhase.TAKEOFF, FlightPhase.DEPARTING)

        if phase in arriving_phases:
            is_arrival = True
            destination = local_iata
        elif phase in departing_phases:
            is_arrival = False
            if origin != local_iata:
                origin = local_iata
        elif phase == FlightPhase.ENROUTE:
            is_arrival = bool(state.origin_airport and not state.destination_airport) or (destination == local_iata)
        else:
            is_arrival = (destination == local_iata)

        # Guard against self-referencing: arrival origin must not be local airport
        if is_arrival and origin == local_iata:
            origin = _pick_random_origin()
        flight_type = "arrival" if is_arrival else "departure"

        # Map flight phase to FIDS status
        if phase in (FlightPhase.PARKED,):
            if is_arrival:
                status = "arrived"
            elif state.turnaround_phase in ("boarding", "loading", "chocks_off"):
                status = "boarding"
            else:
                status = "scheduled"
        elif phase == FlightPhase.APPROACHING:
            status = "on_time"  # approaching = inbound, on its way
        elif phase == FlightPhase.LANDING:
            status = "final_call"  # actively landing
        elif phase == FlightPhase.TAXI_TO_GATE:
            status = "arrived"  # on the ground, taxiing in
        elif phase in (FlightPhase.PUSHBACK, FlightPhase.TAXI_TO_RUNWAY):
            status = "gate_closed" if not is_arrival else "on_time"
        elif phase == FlightPhase.TAKEOFF:
            status = "departed"
        elif phase == FlightPhase.DEPARTING:
            status = "departed"
        elif phase == FlightPhase.ENROUTE:
            status = "scheduled" if is_arrival else "departed"
        else:
            status = "on_time"

        # Deterministic per-flight hash for stable FIDS ordering across refreshes.
        # Use a large prime multiplier to spread hash values evenly.
        _h = ((hash(icao24) * 2654435761) ^ hash(airline_code)) & 0xFFFFFFFF

        # Compute delay from simulation state for arrivals, hash-based for departures
        delay_minutes = 0
        if is_arrival:
            if state.holding_phase_time > 0:
                delay_minutes = max(1, int(state.holding_phase_time / 60))
            elif state.go_around_target_alt > 0:
                delay_minutes = 5
            elif (_h >> 4) % 10 == 0:
                delay_minutes = 5 + ((_h >> 8) % 20)
        else:
            if (_h >> 4) % 5 == 0:
                delay_minutes = 5 + ((_h >> 8) % 41)

        # Mark as delayed if delay detected and status is not terminal
        if delay_minutes > 0 and status in ("scheduled", "on_time"):
            status = "delayed"

        # Compute scheduled times based on actual flight phase and state.
        # Wide modulo ranges prevent clustering on the FIDS display.
        if is_arrival:
            if phase in (FlightPhase.PARKED,):
                # Use actual parked_since timestamp so the FIDS entry
                # reflects when the aircraft really arrived (not a random
                # hash offset that could push it outside the time window).
                if state.parked_since > 0:
                    scheduled_time = datetime.fromtimestamp(
                        state.parked_since, tz=timezone.utc
                    ).isoformat()
                else:
                    scheduled_time = (now - timedelta(minutes=5 + _h % 55)).isoformat()
            elif phase == FlightPhase.TAXI_TO_GATE:
                # Use actual landing timestamp if available
                if state.landed_at > 0:
                    scheduled_time = datetime.fromtimestamp(
                        state.landed_at, tz=timezone.utc
                    ).isoformat()
                else:
                    scheduled_time = (now - timedelta(minutes=2 + _h % 6)).isoformat()
            elif phase == FlightPhase.LANDING:
                # Actively landing: ETA is now
                scheduled_time = (now + timedelta(minutes=1 + _h % 3)).isoformat()
            elif phase == FlightPhase.APPROACHING:
                # Use altitude to compute realistic ETA
                descent_rate = 800.0  # ft/min typical descent
                descent_min = state.altitude / descent_rate if state.altitude > 0 else 5.0
                eta_min = max(3, int(descent_min))
                scheduled_time = (now + timedelta(minutes=eta_min)).isoformat()
            elif phase == FlightPhase.ENROUTE:
                # Far out: spread 15-135 min into the future
                scheduled_time = (now + timedelta(minutes=15 + _h % 120)).isoformat()
            else:
                scheduled_time = (now + timedelta(minutes=_h % 90)).isoformat()
        else:
            if phase == FlightPhase.PARKED:
                # Departures waiting: spread 10-120 min into the future
                scheduled_time = (now + timedelta(minutes=10 + _h % 110)).isoformat()
            elif phase in (FlightPhase.PUSHBACK, FlightPhase.TAXI_TO_RUNWAY):
                # About to depart: scheduled 0-5 min ago
                scheduled_time = (now - timedelta(minutes=_h % 5)).isoformat()
            elif phase in (FlightPhase.TAKEOFF, FlightPhase.DEPARTING):
                # Departed: scheduled 5-25 min ago
                scheduled_time = (now - timedelta(minutes=5 + _h % 20)).isoformat()
            else:
                scheduled_time = (now + timedelta(minutes=_h % 90)).isoformat()

        # Compute estimated_time for delayed flights or approaching aircraft
        estimated_time = None
        if delay_minutes > 0:
            sched_dt = datetime.fromisoformat(scheduled_time)
            estimated_time = (sched_dt + timedelta(minutes=delay_minutes)).isoformat()

        schedule.append({
            "flight_number": callsign,
            "airline": airline_name,
            "airline_code": airline_code,
            "origin": origin,
            "destination": destination,
            "scheduled_time": scheduled_time,
            "estimated_time": estimated_time,
            "actual_time": now.isoformat() if status in ("arrived", "departed") else None,
            "gate": state.assigned_gate,
            "status": status,
            "delay_minutes": delay_minutes,
            "delay_reason": "Late arrival" if delay_minutes > 0 and is_arrival else ("Gate hold" if delay_minutes > 0 else None),
            "aircraft_type": state.aircraft_type,
            "flight_type": flight_type,
        })

    return schedule


# (Separation constants, VREF_SPEEDS, TAKEOFF_PERFORMANCE, AIRLINE_FLEET,
#  CALLSIGN_PREFIXES now imported from _constants)

# ============================================================================
# AIRPORT GEOMETRY - SFO Coordinates (aligned with frontend maps)
# ============================================================================
# These coordinates MUST match the frontend definitions in:
# - app/frontend/src/constants/airportLayout.ts (2D map)
# - app/frontend/src/constants/airport3D.ts (3D scene)
#
# Coordinate system reference:
# - 2D Map: Direct lat/lon (GeoJSON/Leaflet)
# - 3D Map: Converted via latLonTo3D() with center (37.6213, -122.379), scale 10000
# ============================================================================

# Airport center — dynamic, updated when airport switches
# Default is SFO (matches frontend DEFAULT_CENTER_LAT/LON)
_airport_center = (37.6213, -122.379)
_current_airport_iata = "SFO"

# Keep the constant for backward compatibility in tests
AIRPORT_CENTER = (37.6213, -122.379)


def get_airport_center() -> tuple:
    """Get the current airport center coordinates (lat, lon)."""
    return _airport_center


def get_current_airport_iata() -> str:
    """Get the IATA code of the current airport."""
    return _current_airport_iata


def set_airport_center(lat: float, lon: float, iata: str = "SFO") -> None:
    """Set the current airport center for synthetic flight generation.

    Called when the user switches airports. Updates the center used for
    spawning flights, generating trajectories, and computing bearings.
    """
    global _airport_center, _current_airport_iata
    _airport_center = (lat, lon)
    _current_airport_iata = iata

# Real SFO runway endpoints from FAA Airport/Facility Directory
# These match the frontend airportLayout.ts polygon coordinates
# 4 runways: 28L/10R, 28R/10L (parallel E-W), 01L/19R, 01R/19L (crosswind N-S)

# Runway 28L/10R - 11,381 ft (south parallel, extends into bay)
# Primary landing runway for arrivals from the east
RUNWAY_28L_THRESHOLD = (-122.358349, 37.611712)   # 28L threshold (west end, touchdown)
RUNWAY_10R_THRESHOLD = (-122.393105, 37.626291)   # 10R threshold (east end)

# Runway 28R/10L - 11,870 ft (north parallel, extends into bay)
# Primary departure runway
RUNWAY_28R_THRESHOLD = (-122.357141, 37.613534)   # 28R threshold (west end)
RUNWAY_10L_THRESHOLD = (-122.393392, 37.628739)   # 10L threshold (east end)

# Runway 01L/19R - 7,650 ft (west crosswind)
RUNWAY_01L_THRESHOLD = (-122.381929, 37.607898)   # 01L threshold (south end)
RUNWAY_19R_THRESHOLD = (-122.369609, 37.626481)   # 19R threshold (north end)

# Runway 01R/19L - 8,650 ft (east crosswind)
RUNWAY_01R_THRESHOLD = (-122.380041, 37.606330)   # 01R threshold (south end)
RUNWAY_19L_THRESHOLD = (-122.366111, 37.627342)   # 19L threshold (north end)

# Legacy aliases for backward compatibility
RUNWAY_28L_WEST = RUNWAY_28L_THRESHOLD
RUNWAY_28L_EAST = RUNWAY_10R_THRESHOLD
RUNWAY_28R_WEST = RUNWAY_28R_THRESHOLD
RUNWAY_28R_EAST = RUNWAY_10L_THRESHOLD

# Terminal area - International Terminal (southwest area of airport)
# Matches frontend airportLayout.ts terminal polygon
TERMINAL_CENTER = (37.615, -122.391)

# Gate positions - MUST match frontend airportLayout.ts GATE_POSITIONS
# These are the actual gate locations used in both 2D and 3D visualization
# NOTE: This is the fallback when no OSM data is imported
_DEFAULT_GATES = {
    # International Terminal - Boarding Area G
    "G1": (37.6145, -122.3955),  # Wide-body capable
    "G2": (37.6140, -122.3945),
    "G3": (37.6135, -122.3935),
    "G4": (37.6130, -122.3925),
    # International Terminal - Boarding Area A
    "A1": (37.6155, -122.3900),  # Wide-body capable
    "A2": (37.6150, -122.3890),
    "A3": (37.6145, -122.3880),
    # Domestic Terminal 1 - Boarding Area B
    "B1": (37.6165, -122.3850),
    "B2": (37.6160, -122.3840),
    "B3": (37.6155, -122.3830),
    "B4": (37.6150, -122.3820),
    # Domestic Terminal 2 - Boarding Area C
    "C1": (37.6175, -122.3800),
    "C2": (37.6170, -122.3790),
    "C3": (37.6165, -122.3780),
    # Domestic Terminal 3 - Boarding Area E
    "E1": (37.6180, -122.3760),
    "E2": (37.6175, -122.3750),
    "E3": (37.6170, -122.3740),
    # Domestic Terminal 3 - Boarding Area F
    "F1": (37.6185, -122.3720),
    "F2": (37.6180, -122.3710),
    "F3": (37.6175, -122.3700),
}

# Cache for dynamically loaded gates
_loaded_gates: Optional[Dict[str, tuple]] = None

# Minimum gates to avoid constant saturation with moderate flight counts
# (MIN_GATES_FOR_OPERATIONS, MAX_OVERFLOW_STANDS now imported from _constants)


def _generate_default_gates_around_center(center: tuple, count: int = 20) -> Dict[str, tuple]:
    """Generate default gate positions around the airport center.

    Creates a realistic terminal-like layout with gates arranged in two
    concourses north of the airport center, each with gates on both sides.
    """
    lat, lon = center[0], center[1]
    gates: Dict[str, tuple] = {}
    cos_lat = max(math.cos(math.radians(lat)), 0.01)

    # Two concourses: A (northwest of center) and B (northeast of center)
    concourse_offset_lat = 0.002  # ~220m north of center
    concourse_spacing_lon = 0.002 / cos_lat  # ~220m between concourses

    prefixes = ["A", "B"]
    for ci, prefix in enumerate(prefixes):
        base_lat = lat + concourse_offset_lat
        base_lon = lon + (ci - 0.5) * concourse_spacing_lon
        gates_per_concourse = count // len(prefixes)

        for gi in range(gates_per_concourse):
            ref = f"{prefix}{gi + 1}"
            side = 1 if gi % 2 == 0 else -1
            gate_lat = base_lat + (gi // 2) * 0.0004
            gate_lon = base_lon + side * 0.0003 / cos_lat
            gates[ref] = (gate_lat, gate_lon)

    return gates


def _generate_overflow_stands(existing_gates: Dict[str, tuple], count: int) -> Dict[str, tuple]:
    """Generate overflow remote parking positions near the airport apron.

    Places stands in a line south of the terminal area, spaced ~100m apart.
    These serve as remote parking when all terminal gates are occupied.
    """
    center = get_airport_center()
    stands = {}
    # Place overflow stands south of terminal area
    base_lat = center[0] - 0.005  # ~500m south of center
    base_lon = center[1]
    spacing = 0.001  # ~100m between stands

    for i in range(min(count, MAX_OVERFLOW_STANDS)):
        ref = f"R{i+1}"  # R for "Remote"
        if ref not in existing_gates:
            stands[ref] = (base_lat, base_lon + (i - count / 2) * spacing)

    return stands


def get_gates() -> Dict[str, tuple]:
    """
    Get gate positions, preferring imported OSM data over defaults.

    Only caches the result once the airport config service reports ready,
    preventing early calls from permanently locking in a partial gate set.
    Generates overflow remote stands if total gates are below the minimum.

    Returns:
        Dictionary mapping gate refs to (latitude, longitude) tuples
    """
    global _loaded_gates

    if _loaded_gates is not None:
        return _loaded_gates

    gates = None

    # Try to load from airport config service
    try:
        from app.backend.services.airport_config_service import get_airport_config_service
        service = get_airport_config_service()
        config = service.get_config()

        osm_gates = config.get("gates", [])
        if osm_gates:
            gates = {}
            for gate in osm_gates:
                ref = gate.get("ref") or gate.get("id")
                geo = gate.get("geo", {})
                lat = geo.get("latitude")
                lon = geo.get("longitude")
                if ref and lat and lon:
                    # Validate gate ID: reject malformed refs
                    ref_str = str(ref)
                    numeric_part = "".join(c for c in ref_str if c.isdigit())
                    if numeric_part and int(numeric_part) > 200:
                        logger.debug(f"Rejected malformed gate ref: {ref_str}")
                        continue
                    gates[ref_str] = (float(lat), float(lon))

            if not gates:
                gates = None
            elif service.config_ready:
                # Only cache when config is fully loaded
                pass  # Will cache below after overflow check
    except ImportError:
        pass
    except Exception:
        pass

    if gates is None:
        iata = get_current_airport_iata()
        if iata == "SFO":
            gates = dict(_DEFAULT_GATES)
        else:
            gates = _generate_default_gates_around_center(get_airport_center())

    # Add overflow stands if total gates are below the minimum
    if len(gates) < MIN_GATES_FOR_OPERATIONS:
        overflow = _generate_overflow_stands(gates, MIN_GATES_FOR_OPERATIONS - len(gates))
        gates.update(overflow)

    # Cache only when service is ready
    try:
        from app.backend.services.airport_config_service import get_airport_config_service
        service = get_airport_config_service()
        if service.config_ready:
            _loaded_gates = gates
    except Exception:
        pass

    return gates


def reload_gates() -> Dict[str, tuple]:
    """
    Force reload of gates from airport config service.

    Call this after importing new OSM data to refresh the gate positions.
    Also invalidates the FIDS schedule cache so schedules regenerate with
    the new airport's gate names.

    Returns:
        Updated dictionary mapping gate refs to (latitude, longitude) tuples
    """
    global _loaded_gates, _flight_states
    _loaded_gates = None
    gates = get_gates()
    # Reset gate states and flight states to use new gates
    _reset_gate_states()
    _flight_states.clear()  # Clear flights so they regenerate with new gates
    # Invalidate FIDS schedule cache so it regenerates with the correct gates
    from src.ingestion.schedule_generator import invalidate_schedule_cache
    invalidate_schedule_cache()
    return gates


# Backward compatibility: GATES is now a function call result
# Code using GATES directly will get the default gates
GATES = _DEFAULT_GATES

# ============================================================================
# TAXIWAY WAYPOINTS
# ============================================================================
# Routes from runways to gates, aligned with frontend taxiway definitions
# Coordinates follow actual SFO ground movement paths

# Default arrival/departure taxi waypoints — generated at module load from
# runway thresholds and terminal center.  These are the fallback when OSM
# taxiway graph is not available AND no gate ref is provided.
# Overwritten by apply_airport_offset() for non-SFO airports.
TAXI_WAYPOINTS_ARRIVAL = [
    (-122.370, 37.615),    # High-speed exit from 28L (midpoint rollout)
    (-122.378, 37.616),    # Taxiway intersection
    (-122.385, 37.617),    # Turn toward terminal complex
    (-122.390, 37.616),    # Terminal apron entry
]

TAXI_WAYPOINTS_DEPARTURE = [
    (-122.390, 37.616),    # Leave terminal apron
    (-122.385, 37.618),    # Taxiway junction
    (-122.378, 37.620),    # Join main taxiway
    (-122.370, 37.622),    # Hold short departure runway
    (-122.360, 37.614),    # Runway entry point
]



# (Geometry-derived taxi routing: _compute_taxiway_line, _project_onto_line,
#  _t_on_line, _generate_taxi_spine, _smooth_sharp_turns now imported from _taxi_routing)


# (_get_arrival_runway_endpoints, _get_departure_runway_endpoints
#  now imported from _approach_departure)



# (get_terminal_center, _build_arrival_taxi_route, _build_departure_taxi_route
#  now imported from _taxi_routing)


# ============================================================================
# ILS APPROACH PATH - Runway 28L
# ============================================================================
# Standard ILS approach from the east over San Francisco Bay
# Runway 28L heading: 284° magnetic (298° true)
# 28L threshold: 37.611712, -122.358349
#
# Approach path angles align aircraft with the extended runway centerline
# The approach course passes over the bay, descending from 6000ft to touchdown

# Calculate approach path aligned with runway centerline
# Runway centerline vector: from 28L threshold toward 10R threshold
_RWY_28L_LAT = 37.611712
_RWY_28L_LON = -122.358349
_RWY_10R_LAT = 37.626291
_RWY_10R_LON = -122.393105

# Approach path extends east from 28L threshold, following the extended centerline
# Each waypoint: (longitude, latitude, altitude_feet)
APPROACH_WAYPOINTS = [
    # Initial approach fix - 15 NM east of threshold (~4770 ft on 3° GS)
    (-122.10, 37.58, 4800),
    (-122.15, 37.588, 3800),
    # Intermediate fix - 10 NM from threshold (~3180 ft on 3° GS)
    (-122.20, 37.595, 3200),
    (-122.24, 37.600, 2500),
    # Final approach fix - 5 NM from threshold (~1590 ft on 3° GS)
    (-122.28, 37.605, 1600),
    (-122.30, 37.607, 1300),
    # Glideslope intercept - 3 NM from threshold (~950 ft on 3° GS)
    (-122.32, 37.608, 950),
    (-122.333, 37.609, 630),
    # Short final - 1 NM from threshold (~318 ft on 3° GS)
    (-122.345, 37.610, 320),
    (-122.352, 37.6109, 160),
    # Runway 28L threshold (50 ft TCH per 14 CFR 97.3)
    (_RWY_28L_LON, _RWY_28L_LAT, 50),
]

# ============================================================================
# DEPARTURE PATH - Runway 28R
# ============================================================================
# Standard departure from runway 28R (north parallel)
# Initial climb on runway heading, then turn per SID

_RWY_28R_LAT = 37.613534
_RWY_28R_LON = -122.357141

DEPARTURE_WAYPOINTS = [
    # Initial climb - runway 28R just after liftoff (~0.5 NM)
    (_RWY_28R_LON + 0.02, _RWY_28R_LAT, 200),
    # Climbing runway heading (~2 NM, 284° true)
    (-122.32, 37.608, 1000),
    # Continue climb over bay (~4 NM)
    (-122.28, 37.60, 2000),
    # Departure fix - climbing to cruise (~10 NM)
    (-122.20, 37.58, 5000),
    # Enroute - over the bay (~15 NM)
    (-122.10, 37.55, 8000),
]

# ============================================================================
# AIRPORT OFFSET — shift SFO coordinates to target airport
# ============================================================================
# In standalone CLI mode (no OSM data), all coordinates are SFO-based.
# apply_airport_offset() shifts them to center on any target airport.

# (_SFO_CENTER now imported from _constants)

# Save originals for reset
_ORIG_DEFAULT_GATES = dict(_DEFAULT_GATES)
_ORIG_RUNWAY_28L_THRESHOLD = RUNWAY_28L_THRESHOLD
_ORIG_RUNWAY_10R_THRESHOLD = RUNWAY_10R_THRESHOLD
_ORIG_RUNWAY_28R_THRESHOLD = RUNWAY_28R_THRESHOLD
_ORIG_RUNWAY_10L_THRESHOLD = RUNWAY_10L_THRESHOLD
_ORIG_RUNWAY_01L_THRESHOLD = RUNWAY_01L_THRESHOLD
_ORIG_RUNWAY_19R_THRESHOLD = RUNWAY_19R_THRESHOLD
_ORIG_RUNWAY_01R_THRESHOLD = RUNWAY_01R_THRESHOLD
_ORIG_RUNWAY_19L_THRESHOLD = RUNWAY_19L_THRESHOLD
_ORIG_TERMINAL_CENTER = TERMINAL_CENTER
_ORIG_TAXI_WAYPOINTS_ARRIVAL = list(TAXI_WAYPOINTS_ARRIVAL)
_ORIG_TAXI_WAYPOINTS_DEPARTURE = list(TAXI_WAYPOINTS_DEPARTURE)
_ORIG_APPROACH_WAYPOINTS = list(APPROACH_WAYPOINTS)
_ORIG_DEPARTURE_WAYPOINTS = list(DEPARTURE_WAYPOINTS)
_ORIG_RWY_28L_LAT = _RWY_28L_LAT
_ORIG_RWY_28L_LON = _RWY_28L_LON
_ORIG_RWY_28R_LAT = _RWY_28R_LAT
_ORIG_RWY_28R_LON = _RWY_28R_LON
_ORIG_RWY_10R_LAT = _RWY_10R_LAT
_ORIG_RWY_10R_LON = _RWY_10R_LON


def apply_airport_offset(target_lat: float, target_lon: float) -> None:
    """Offset all hardcoded SFO coordinates to center on the target airport.

    Called by the simulation engine for non-SFO airports in standalone mode
    (no OSM data available). Preserves the realistic relative layout (gate
    spacing, runway angles, taxi routing) while centering at the target airport.
    """
    global _DEFAULT_GATES, GATES
    global RUNWAY_28L_THRESHOLD, RUNWAY_10R_THRESHOLD
    global RUNWAY_28R_THRESHOLD, RUNWAY_10L_THRESHOLD
    global RUNWAY_01L_THRESHOLD, RUNWAY_19R_THRESHOLD
    global RUNWAY_01R_THRESHOLD, RUNWAY_19L_THRESHOLD
    global RUNWAY_28L_WEST, RUNWAY_28L_EAST, RUNWAY_28R_WEST, RUNWAY_28R_EAST
    global TERMINAL_CENTER
    global TAXI_WAYPOINTS_ARRIVAL, TAXI_WAYPOINTS_DEPARTURE
    global APPROACH_WAYPOINTS, DEPARTURE_WAYPOINTS
    global _RWY_28L_LAT, _RWY_28L_LON, _RWY_28R_LAT, _RWY_28R_LON
    global _RWY_10R_LAT, _RWY_10R_LON

    lat_off = target_lat - _SFO_CENTER[0]
    lon_off = target_lon - _SFO_CENTER[1]

    # Gates: {ref: (lat, lon)}
    _DEFAULT_GATES = {k: (v[0] + lat_off, v[1] + lon_off) for k, v in _ORIG_DEFAULT_GATES.items()}
    GATES = _DEFAULT_GATES

    # Runways: (lon, lat)
    RUNWAY_28L_THRESHOLD = (_ORIG_RUNWAY_28L_THRESHOLD[0] + lon_off, _ORIG_RUNWAY_28L_THRESHOLD[1] + lat_off)
    RUNWAY_10R_THRESHOLD = (_ORIG_RUNWAY_10R_THRESHOLD[0] + lon_off, _ORIG_RUNWAY_10R_THRESHOLD[1] + lat_off)
    RUNWAY_28R_THRESHOLD = (_ORIG_RUNWAY_28R_THRESHOLD[0] + lon_off, _ORIG_RUNWAY_28R_THRESHOLD[1] + lat_off)
    RUNWAY_10L_THRESHOLD = (_ORIG_RUNWAY_10L_THRESHOLD[0] + lon_off, _ORIG_RUNWAY_10L_THRESHOLD[1] + lat_off)
    RUNWAY_01L_THRESHOLD = (_ORIG_RUNWAY_01L_THRESHOLD[0] + lon_off, _ORIG_RUNWAY_01L_THRESHOLD[1] + lat_off)
    RUNWAY_19R_THRESHOLD = (_ORIG_RUNWAY_19R_THRESHOLD[0] + lon_off, _ORIG_RUNWAY_19R_THRESHOLD[1] + lat_off)
    RUNWAY_01R_THRESHOLD = (_ORIG_RUNWAY_01R_THRESHOLD[0] + lon_off, _ORIG_RUNWAY_01R_THRESHOLD[1] + lat_off)
    RUNWAY_19L_THRESHOLD = (_ORIG_RUNWAY_19L_THRESHOLD[0] + lon_off, _ORIG_RUNWAY_19L_THRESHOLD[1] + lat_off)

    # Legacy aliases
    RUNWAY_28L_WEST = RUNWAY_28L_THRESHOLD
    RUNWAY_28L_EAST = RUNWAY_10R_THRESHOLD
    RUNWAY_28R_WEST = RUNWAY_28R_THRESHOLD
    RUNWAY_28R_EAST = RUNWAY_10L_THRESHOLD

    # Terminal center: (lat, lon)
    TERMINAL_CENTER = (_ORIG_TERMINAL_CENTER[0] + lat_off, _ORIG_TERMINAL_CENTER[1] + lon_off)

    # Taxi waypoints: [(lon, lat), ...]
    TAXI_WAYPOINTS_ARRIVAL = [(wp[0] + lon_off, wp[1] + lat_off) for wp in _ORIG_TAXI_WAYPOINTS_ARRIVAL]
    TAXI_WAYPOINTS_DEPARTURE = [(wp[0] + lon_off, wp[1] + lat_off) for wp in _ORIG_TAXI_WAYPOINTS_DEPARTURE]

    # Approach/departure: [(lon, lat, alt), ...]
    APPROACH_WAYPOINTS = [(wp[0] + lon_off, wp[1] + lat_off, wp[2]) for wp in _ORIG_APPROACH_WAYPOINTS]
    DEPARTURE_WAYPOINTS = [(wp[0] + lon_off, wp[1] + lat_off, wp[2]) for wp in _ORIG_DEPARTURE_WAYPOINTS]

    # Individual runway coordinate floats
    _RWY_28L_LAT = _ORIG_RWY_28L_LAT + lat_off
    _RWY_28L_LON = _ORIG_RWY_28L_LON + lon_off
    _RWY_28R_LAT = _ORIG_RWY_28R_LAT + lat_off
    _RWY_28R_LON = _ORIG_RWY_28R_LON + lon_off
    _RWY_10R_LAT = _ORIG_RWY_10R_LAT + lat_off
    _RWY_10R_LON = _ORIG_RWY_10R_LON + lon_off


def reset_airport_offset() -> None:
    """Restore all coordinates to their original SFO values.

    Called for test isolation and when switching back to SFO.
    """
    global _DEFAULT_GATES, GATES
    global RUNWAY_28L_THRESHOLD, RUNWAY_10R_THRESHOLD
    global RUNWAY_28R_THRESHOLD, RUNWAY_10L_THRESHOLD
    global RUNWAY_01L_THRESHOLD, RUNWAY_19R_THRESHOLD
    global RUNWAY_01R_THRESHOLD, RUNWAY_19L_THRESHOLD
    global RUNWAY_28L_WEST, RUNWAY_28L_EAST, RUNWAY_28R_WEST, RUNWAY_28R_EAST
    global TERMINAL_CENTER
    global TAXI_WAYPOINTS_ARRIVAL, TAXI_WAYPOINTS_DEPARTURE
    global APPROACH_WAYPOINTS, DEPARTURE_WAYPOINTS
    global _RWY_28L_LAT, _RWY_28L_LON, _RWY_28R_LAT, _RWY_28R_LON
    global _RWY_10R_LAT, _RWY_10R_LON

    _DEFAULT_GATES = dict(_ORIG_DEFAULT_GATES)
    GATES = _DEFAULT_GATES
    RUNWAY_28L_THRESHOLD = _ORIG_RUNWAY_28L_THRESHOLD
    RUNWAY_10R_THRESHOLD = _ORIG_RUNWAY_10R_THRESHOLD
    RUNWAY_28R_THRESHOLD = _ORIG_RUNWAY_28R_THRESHOLD
    RUNWAY_10L_THRESHOLD = _ORIG_RUNWAY_10L_THRESHOLD
    RUNWAY_01L_THRESHOLD = _ORIG_RUNWAY_01L_THRESHOLD
    RUNWAY_19R_THRESHOLD = _ORIG_RUNWAY_19R_THRESHOLD
    RUNWAY_01R_THRESHOLD = _ORIG_RUNWAY_01R_THRESHOLD
    RUNWAY_19L_THRESHOLD = _ORIG_RUNWAY_19L_THRESHOLD
    RUNWAY_28L_WEST = RUNWAY_28L_THRESHOLD
    RUNWAY_28L_EAST = RUNWAY_10R_THRESHOLD
    RUNWAY_28R_WEST = RUNWAY_28R_THRESHOLD
    RUNWAY_28R_EAST = RUNWAY_10L_THRESHOLD
    TERMINAL_CENTER = _ORIG_TERMINAL_CENTER
    TAXI_WAYPOINTS_ARRIVAL = list(_ORIG_TAXI_WAYPOINTS_ARRIVAL)
    TAXI_WAYPOINTS_DEPARTURE = list(_ORIG_TAXI_WAYPOINTS_DEPARTURE)
    APPROACH_WAYPOINTS = list(_ORIG_APPROACH_WAYPOINTS)
    DEPARTURE_WAYPOINTS = list(_ORIG_DEPARTURE_WAYPOINTS)
    _RWY_28L_LAT = _ORIG_RWY_28L_LAT
    _RWY_28L_LON = _ORIG_RWY_28L_LON
    _RWY_28R_LAT = _ORIG_RWY_28R_LAT
    _RWY_28R_LON = _ORIG_RWY_28R_LON
    _RWY_10R_LAT = _ORIG_RWY_10R_LAT
    _RWY_10R_LON = _ORIG_RWY_10R_LON


# (_entry_direction_quadrant now imported from _geo)



# (STAR/SID corridors, approach/departure waypoints, OSM runway geometry,
#  _get_arrival_runway_name, _get_fallback_runway, _get_runway_threshold,
#  _get_takeoff_runway_geometry now imported from _approach_departure)




# (_get_taxi_waypoints_arrival, _get_taxi_waypoints_departure,
#  _get_pushback_heading now imported from _taxi_routing)



# ============================================================================
# SEPARATION MANAGEMENT
# ============================================================================
# (All separation management functions now imported from _runway_ops)


# (_shortest_angle_diff, _calculate_heading, _smooth_heading,
#  _distance_between now imported from _geo)



# (_snap_to_nearest_waypoint now imported from _approach_departure)

# (_move_toward, _interpolate_altitude now imported from _geo)


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



# (_get_airport_coordinates, _bearing_cache, _bearing_from_airport, _bearing_to_airport
#  now imported from _approach_departure)




# (_is_gate_inside_terminal, _gate_to_terminal_edge_distance_m,
#  _compute_gate_standoff, _get_parked_heading now imported from _taxi_routing)



def _is_international_airport(iata: str) -> bool:
    """Check if an airport code is in the international list."""
    from src.ingestion.schedule_generator import INTERNATIONAL_AIRPORTS
    return iata in INTERNATIONAL_AIRPORTS


# Country lookup for origin_country field
# (_AIRPORT_COUNTRY now imported from _constants)


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
    return _pick_random_airport(exclude=get_current_airport_iata())


def _pick_random_destination() -> str:
    """Pick a random destination airport for departing flights (never the local airport)."""
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

        # Limit simultaneous approaches (realistic: max 4-5 in sequence)
        if approaching_count + landing_count >= MAX_APPROACH_AIRCRAFT:
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

            # Missed approach: climb to 1500ft AGL minimum
            state.go_around_target_alt = max(1500.0, state.altitude + 300)
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

            # Skip waypoints whose altitude is above current altitude
            # (happens after go-around re-entry at low altitude)
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
                    # This also handles post-go-around re-entry at low altitude
                    target_speed = min(vref + 30, max(vref, raw_speed))
                elif state.altitude < 2000 or progress > 0.85:
                    target_speed = max(vref, raw_speed)
                else:
                    target_speed = max(vref * 0.9, raw_speed)
                max_speed_change = 5.0 * dt  # 5 kts/s
                if target_speed > state.velocity:
                    state.velocity = min(target_speed, state.velocity + max_speed_change)
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

        # Aircraft moves along the runway heading during landing.
        speed_deg = state.velocity * _KTS_TO_DEG_PER_SEC * dt
        rwy_hdg_rad = math.radians(rwy_hdg)
        state.latitude += speed_deg * math.cos(rwy_hdg_rad)
        state.longitude += speed_deg * math.sin(rwy_hdg_rad) / math.cos(math.radians(state.latitude))
        state.heading = rwy_hdg

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

            # Go-around missed approach: climb → straight ahead → downwind turn → re-approach.
            # Realistic pattern: 3+ NM straight ahead, then gradual turn to downwind.
            if state.go_around_target_alt > 0 and state.altitude < state.go_around_target_alt:
                climb_fps = 25.0  # ~1500 ft/min
                state.altitude = min(state.go_around_target_alt, state.altitude + climb_fps * dt)
                state.vertical_rate = 1500
                speed_deg = state.velocity * _KTS_TO_DEG_PER_SEC * dt
                state.latitude += math.cos(math.radians(state.heading)) * speed_deg
                state.longitude += math.sin(math.radians(state.heading)) * speed_deg / max(0.01, math.cos(math.radians(state.latitude)))
                if state.altitude >= state.go_around_target_alt:
                    state.go_around_target_alt = 0.0
                    # Fly straight ahead 60s (~3 NM) before starting the turn
                    state.holding_phase_time = -60.0
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

            target_heading = _calculate_heading(
                (state.latitude, state.longitude), center
            )
            heading_diff = (target_heading - state.heading + 540) % 360 - 180
            if state.go_around_count > 0:
                # Go-around: standard rate turn (3°/s) for a tight missed approach pattern
                turn_rate = 3.0
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

            # Enforce approach capacity at runtime (max 4 on approach)
            approach_count = (_count_aircraft_in_phase(FlightPhase.APPROACHING)
                              + _count_aircraft_in_phase(FlightPhase.LANDING))
            # Go-around flights get priority re-entry — they've already been sequenced
            can_start_approach = (approach_count < MAX_APPROACH_AIRCRAFT
                                  or state.go_around_count > 0)

            # Go-around re-entry: wider radius since aircraft is already close
            reentry_radius = 0.35 if state.go_around_count > 0 else APPROACH_RADIUS_DEG

            if can_start_approach and dist_from_airport < reentry_radius:
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
                # 1-minute inbound/outbound legs, standard rate turns (3°/s)
                HOLDING_LEG_SECONDS = 60.0  # 1-minute legs per FAA 7110.65
                HOLDING_TURN_SECONDS = 60.0  # 180° at 3°/s standard rate
                STANDARD_RATE_DEG_S = 3.0   # Standard rate turn
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


def generate_synthetic_flights(
    count: int = 50,
    bbox: Dict[str, float] | None = None,
) -> Dict[str, Any]:
    """
    Generate synthetic flight data with persistent realistic movements.

    Maintains flight state across calls for smooth, realistic movements.
    Aircraft follow proper taxi paths, landing/takeoff sequences, and
    cruise patterns. Implements FAA/ICAO separation standards.

    Args:
        count: Number of flights to generate (default 50).
        bbox: Bounding box (unused, kept for API compatibility).

    Returns:
        Dict with 'time' (int) and 'states' (list of lists) matching
        the OpenSky /states/all response format.
    """
    global _flight_states, _last_update

    # Don't create flights until the airport config (runways/gates) is loaded.
    # Generating flights with fallback 270° heading locks in wrong trajectories.
    osm_rwy = _get_osm_primary_runway()
    if osm_rwy is None:
        logger.info("[DIAG] generate_synthetic_flights: BLOCKED — no OSM runway yet")
        return {"time": int(datetime.now(timezone.utc).timestamp()), "states": []}
    if not _flight_states:
        logger.info("[DIAG] generate_synthetic_flights: FIRST RUN with runway ref=%s, %d geoPoints",
                     osm_rwy.get("ref"), len(osm_rwy.get("geoPoints", [])))

    current_time = datetime.now(timezone.utc).timestamp()
    dt = min(current_time - _last_update, 5.0) if _last_update > 0 else 1.0
    _last_update = current_time

    # Initialize gate states on first run
    _init_gate_states()

    # Remove flights that have exited the visibility circle (departures)
    for icao24 in list(_flight_states.keys()):
        state = _flight_states[icao24]
        if state.phase == FlightPhase.ENROUTE and state.phase_progress == -1.0:
            # Release any gate still held
            if state.assigned_gate:
                _release_gate(icao24, state.assigned_gate)
            del _flight_states[icao24]

    # Compute airport-appropriate target flight count:
    # 1) Scale to gate count (small airports get fewer flights)
    # 2) Modulate by hourly traffic profile (quiet hours = fewer flights)
    gate_count = len(get_gates())
    if gate_count > 0:
        target = max(15, min(count, int(gate_count * 1.5)))
    else:
        target = count  # No gates loaded yet — use default

    profile = _get_current_airport_profile()
    if profile and profile.hourly_profile and len(profile.hourly_profile) == 24:
        hour_utc = datetime.now(timezone.utc).hour
        hour_weight = profile.hourly_profile[hour_utc]
        peak_weight = max(profile.hourly_profile)
        if peak_weight > 0:
            hourly_factor = max(0.15, hour_weight / peak_weight)  # floor at 15%
            target = max(5, int(target * hourly_factor))

    # Soft-cull excess flights (max 2 per tick to avoid visual pop)
    if len(_flight_states) > target + 5:
        _cull_candidates = [
            k for k, s in _flight_states.items()
            if s.phase == FlightPhase.ENROUTE and s.phase_progress == -1.0
        ]
        if not _cull_candidates:
            # Fall back to any enroute flight (departing outbound)
            _cull_candidates = [
                k for k, s in _flight_states.items()
                if s.phase == FlightPhase.ENROUTE
            ]
        for _cull_id in _cull_candidates[:2]:
            _cs = _flight_states.get(_cull_id)
            if _cs and _cs.assigned_gate:
                _release_gate(_cull_id, _cs.assigned_gate)
            _flight_states.pop(_cull_id, None)

    # Initialize flights if needed (fill up to target count)
    if len(_flight_states) < target:
        local_iata = get_current_airport_iata()

        # Generate random flights
        while len(_flight_states) < target:
            icao24 = fake.hexify(text="^^^^^^", upper=False)
            if icao24 in _flight_states:
                continue

            # Select airline from calibrated profile if available
            _profile = _get_current_airport_profile()
            _from_profile = False
            if _profile and _profile.airline_shares:
                _codes = list(_profile.airline_shares.keys())
                _weights = list(_profile.airline_shares.values())
                prefix = random.choices(_codes, weights=_weights, k=1)[0]
                _from_profile = True
            else:
                prefix = random.choice(CALLSIGN_PREFIXES)

            # Replace "OTH" catch-all with a real regional carrier
            _OTH_REPLACEMENTS = ["SKW", "RPA", "ENY", "PDT", "EDV"]
            if prefix == "OTH":
                prefix = random.choice(_OTH_REPLACEMENTS)

            # Easter egg: ~15% chance of Ukrainian Air Force at UA airports
            try:
                from src.ingestion.airport_table import AIRPORTS as _apt_table
                _apt_entry = _apt_table.get(local_iata)
                _icao_to_iata_map = {v[2]: k for k, v in _apt_table.items()}
                _resolved_iata = _icao_to_iata_map.get(local_iata, local_iata)
                _apt_entry2 = _apt_table.get(_resolved_iata)
                _check = _apt_entry or _apt_entry2
                if _check and _check[3] == "UA":
                    if random.random() < 0.15:
                        prefix = "UAF"
                        logger.info("Easter egg: UAF fighter jet spawning at %s (resolved: %s)", local_iata, _resolved_iata)
            except Exception:
                pass

            # Validate airline scope — only for non-profile airlines.
            # If the profile explicitly includes a carrier for this airport, trust it.
            if not _from_profile:
                _US_DOMESTIC_CARRIERS = {"SWA", "JBU", "ASA", "HAL"}
                _US_REGIONAL_CARRIERS = {"SKW", "RPA", "ENY", "PDT", "EDV"}
                _US_IATA_CODES = {
                    "SFO", "LAX", "ORD", "DFW", "JFK", "ATL", "DEN", "SEA", "BOS",
                    "PHX", "LAS", "MCO", "MIA", "CLT", "MSP", "DTW", "EWR", "PHL",
                    "IAH", "SAN", "PDX", "HNL", "AUS", "TPA", "SLC", "BNA", "DCA",
                    "IAD", "FLL", "STL", "BWI", "RDU", "SJC", "DAL", "MDW", "OAK",
                    "SMF", "IND", "CLE", "MCI", "CMH", "PIT", "SAT", "MKE", "CVG",
                }
                _is_us_airport = local_iata in _US_IATA_CODES

                # Filter domestic-only US carriers at non-US airports
                if prefix in _US_DOMESTIC_CARRIERS and not _is_us_airport:
                    prefix = random.choice(["UAL", "DAL", "AAL", "UAE", "AFR", "CPA"])

                # Filter US regional carriers at non-US airports
                if prefix in _US_REGIONAL_CARRIERS and not _is_us_airport:
                    prefix = random.choice(["UAL", "DAL", "AAL", "UAE", "AFR", "CPA"])

                try:
                    from src.ingestion.schedule_generator import AIRLINES as _SG_AIRLINES
                    _airline_info = _SG_AIRLINES.get(prefix)
                    if _airline_info:
                        _scope = _airline_info.get("scope", "full")
                        if _scope == "regional_eu" and not _is_international_airport(local_iata):
                            prefix = random.choice(["UAL", "DAL", "AAL", "UAE", "AFR", "CPA"])
                        elif _scope == "regional_me":
                            if not any(local_iata.startswith(p) for p in ("DXB", "DOH", "AUH", "BAH", "KWI", "MCT")):
                                prefix = random.choice(["UAL", "DAL", "AAL", "UAE", "AFR", "CPA"])
                except ImportError:
                    pass

            flight_num = random.randint(100, 9999)
            callsign = f"{prefix}{flight_num}"

            # Ensure callsign uniqueness — skip duplicates (loop will retry)
            if callsign in _flight_states._callsigns:
                continue

            # Count current phases to balance distribution
            parked_count = _count_aircraft_in_phase(FlightPhase.PARKED)
            approach_count = _count_aircraft_in_phase(FlightPhase.APPROACHING)
            taxi_count = (_count_aircraft_in_phase(FlightPhase.TAXI_TO_GATE) +
                         _count_aircraft_in_phase(FlightPhase.TAXI_TO_RUNWAY))

            max_parked = int(len(get_gates()) * 0.8)  # 80% cap — buffer for arrivals

            # Adjust phase bias based on hourly traffic intensity:
            # Quiet hours → more parked, fewer active movements
            # Busy hours  → more approach/departing activity
            _activity_boost = 1.0
            if profile and profile.hourly_profile and len(profile.hourly_profile) == 24:
                _avg_weight = sum(profile.hourly_profile) / 24
                _cur_weight = profile.hourly_profile[datetime.now(timezone.utc).hour]
                if _avg_weight > 0:
                    _activity_boost = max(0.3, min(1.5, _cur_weight / _avg_weight))

            approach_weight = (0.10 * _activity_boost) if approach_count < MAX_APPROACH_AIRCRAFT else 0.0
            parked_weight = (0.12 / max(0.5, _activity_boost)) if parked_count < max_parked else 0.0
            taxi_in_weight = (0.05 * _activity_boost) if taxi_count < 6 else 0.0
            taxi_out_weight = (0.08 * _activity_boost) if taxi_count < 6 else 0.0
            departing_weight = 0.15 * _activity_boost

            total_assigned = approach_weight + parked_weight + taxi_in_weight + taxi_out_weight + departing_weight
            enroute_weight = max(0.0, 1.0 - total_assigned)

            # Split ENROUTE 50/50 into arriving and departing.
            # "ENROUTE_DEPARTING" is a pseudo-phase: spawns as ENROUTE but positioned outbound.
            phase_weights = [
                (FlightPhase.ENROUTE, enroute_weight * 0.5),           # arriving enroute
                ("ENROUTE_DEPARTING", enroute_weight * 0.5),           # departing enroute (pseudo)
                (FlightPhase.APPROACHING, approach_weight),
                (FlightPhase.PARKED, parked_weight),
                (FlightPhase.TAXI_TO_GATE, taxi_in_weight),
                (FlightPhase.TAXI_TO_RUNWAY, taxi_out_weight),
                (FlightPhase.DEPARTING, departing_weight),
            ]

            r = random.random()
            cumulative = 0
            selected_phase = FlightPhase.ENROUTE
            _is_enroute_departing = False
            for phase, weight in phase_weights:
                cumulative += weight
                if r <= cumulative:
                    if phase == "ENROUTE_DEPARTING":
                        selected_phase = FlightPhase.ENROUTE
                        _is_enroute_departing = True
                    else:
                        selected_phase = phase
                    break

            # Assign origin/destination based on phase
            origin = None
            dest = None
            is_arriving = (
                selected_phase in (
                    FlightPhase.ENROUTE, FlightPhase.APPROACHING,
                    FlightPhase.LANDING, FlightPhase.TAXI_TO_GATE,
                )
                and not _is_enroute_departing
            )
            is_departing = (
                selected_phase in (
                    FlightPhase.PUSHBACK, FlightPhase.TAXI_TO_RUNWAY,
                    FlightPhase.TAKEOFF, FlightPhase.DEPARTING,
                )
                or _is_enroute_departing
            )

            local_iata = get_current_airport_iata()
            if is_arriving:
                # Arriving flights: origin=remote airport, destination=local airport
                origin = _pick_random_origin()
                dest = local_iata
            elif is_departing:
                # Departing flights: origin=local airport, destination=remote
                origin = local_iata
                dest = _pick_random_destination()
            elif selected_phase == FlightPhase.PARKED:
                # Parked: set both — parked flights don't use the enroute direction logic
                if random.random() < 0.5:
                    origin = _pick_random_origin()
                    dest = local_iata
                else:
                    origin = local_iata
                    dest = _pick_random_destination()

            _flight_states[icao24] = _create_new_flight(icao24, callsign, selected_phase, origin=origin, destination=dest)

    # Update all flight states
    for icao24, state in list(_flight_states.items()):
        _flight_states[icao24] = _update_flight_state(state, dt)

    # Build response in OpenSky format
    states: List[List[Any]] = []

    for icao24, state in list(_flight_states.items())[:target]:
        # Sanitize numeric fields to prevent NaN/Inf propagation to frontend
        _alt = _sanitize_float(state.altitude, 0.0)
        _vel = min(_sanitize_float(state.velocity, 0.0), MAX_VELOCITY_KTS)
        _hdg = _sanitize_float(state.heading, 0.0) % 360
        _vr = _sanitize_float(state.vertical_rate, 0.0)
        _lat = _sanitize_float(state.latitude, 0.0)
        _lon = _sanitize_float(state.longitude, 0.0)

        state_vector = [
            state.icao24,                              # 0: icao24
            state.callsign.ljust(8),                   # 1: callsign
            _get_origin_country(state.origin_airport), # 2: origin_country
            int(current_time) - random.randint(0, 2), # 3: time_position
            int(current_time),                         # 4: last_contact
            _lon,                                      # 5: longitude
            _lat,                                      # 6: latitude
            _alt * 0.3048,                             # 7: baro_altitude (convert ft to m)
            state.on_ground,                           # 8: on_ground
            _vel * 0.514444,                           # 9: velocity (convert kts to m/s)
            _hdg,                                      # 10: true_track
            _vr * 0.00508,                             # 11: vertical_rate (ft/min to m/s)
            None,                                      # 12: sensors
            _alt * 0.3048,                             # 13: geo_altitude
            f"{random.randint(1000, 7777):04d}",       # 14: squawk
            False,                                     # 15: spi
            0,                                         # 16: position_source
            random.randint(2, 6),                      # 17: category
            _get_flight_phase_name(state.phase),       # 18: flight_phase (custom)
            state.aircraft_type,                       # 19: aircraft_type (custom)
            state.origin_airport,                      # 20: origin_airport (custom)
            state.destination_airport,                 # 21: destination_airport (custom)
            state.assigned_gate if state.phase in (FlightPhase.PARKED, FlightPhase.TAXI_TO_GATE) else None,  # 22: assigned_gate (only at/approaching gate)
        ]
        states.append(state_vector)

    return {
        "time": int(current_time),
        "states": states,
    }




def generate_synthetic_trajectory(icao24: str, minutes: int = 60, limit: int = 1000) -> List[Dict[str, Any]]:
    """Generate synthetic trajectory data for a flight.

    Creates a realistic approach-to-landing trajectory pattern for demo purposes.
    The trajectory follows the ILS approach path to runway 28L at SFO:
    - Approach from the east over San Francisco Bay
    - Descend on the 3° glideslope
    - Land heading approximately 284° (true heading)
    - Taxi to gate via the terminal apron

    The generated trajectory aligns with both the 2D map (Leaflet) and
    3D visualization (Three.js) using the same coordinate reference.

    Args:
        icao24: The ICAO24 address of the aircraft.
        minutes: Minutes of history to simulate.
        limit: Maximum number of points to return.

    Returns:
        List of trajectory points as dictionaries.
    """
    from datetime import datetime, timedelta, timezone

    # Find the flight in the flight states manager
    flight_info = None
    if icao24 in _flight_states:
        state = _flight_states[icao24]
        flight_info = {"icao24": icao24, "callsign": state.callsign}

    if flight_info is None:
        return []

    callsign = flight_info.get("callsign", "UNKNOWN")

    # Get the current flight state if available
    current_state = _flight_states.get(icao24)

    # Determine aircraft's current situation
    if current_state:
        end_lat = current_state.latitude
        end_lon = current_state.longitude
        end_alt = current_state.altitude
        current_heading = current_state.heading
        current_phase = current_state.phase.value if current_state.phase else "descending"
    else:
        # Fallback to approach position
        _app_wps = _get_approach_waypoints()
        end_lat = _app_wps[-1][1]
        end_lon = _app_wps[-1][0]
        end_alt = _app_wps[-1][2]
        current_heading = _get_runway_heading() or _get_fallback_runway()[2]
        current_phase = "descending"

    # Parked aircraft don't need a synthetic trajectory trail — they're
    # stationary at a gate.  Showing a fabricated arrival path is misleading.
    if current_phase == "parked":
        return []

    # Determine if aircraft is on ground
    ground_phases = ["ground", "taxi_to_gate", "taxi_to_runway", "pushback"]
    is_on_ground = current_phase in ground_phases or end_alt < 100

    # Detect go-around: aircraft has executed a missed approach and is either
    # still in enroute/holding or has re-entered approaching for a second attempt.
    _local_iata = get_current_airport_iata()
    is_go_around = (
        current_state
        and current_state.go_around_count > 0
        and current_phase in ("enroute", "approaching")
        and (current_state.origin_airport and (
            not current_state.destination_airport
            or current_state.destination_airport == _local_iata
        ))
    )

    # =========================================================================
    # Generate trajectory following the ILS approach path
    # =========================================================================
    # The ILS approach to runway 28L comes from the east (higher longitude)
    # Aircraft descend on a 3° glideslope (approximately 300 ft/NM)
    # Touchdown zone is at the runway 28L threshold

    points = []
    num_points = min(limit, 80)
    now = datetime.now(timezone.utc)
    interval_seconds = (minutes * 60) / num_points

    # Runway parameters from OSM data — no runway = no trajectory
    _rwy_threshold = _get_runway_threshold()
    _dep_threshold = _get_departure_runway()
    if _rwy_threshold is None or _dep_threshold is None:
        return []  # No runway data, disable trajectory
    rwy_threshold_lon, rwy_threshold_lat = _rwy_threshold[0], _rwy_threshold[1]
    dep_rwy_lon, dep_rwy_lat = _dep_threshold[0], _dep_threshold[1]

    if is_go_around:
        # =================================================================
        # GO-AROUND TRAJECTORY: approach → climb-out → return → re-approach
        # =================================================================
        # Shows the initial approach, the climb-out on runway heading after
        # the missed approach, the curve back, and (when the aircraft has
        # re-entered approaching) the second approach to current position.
        origin_airport = current_state.origin_airport if current_state else None
        _traj_app_wps_ga = _get_approach_waypoints(origin_airport)
        _rwy_heading_ga = _get_runway_heading()
        if _rwy_heading_ga is None or len(_traj_app_wps_ga) < 2:
            return []

        _ga_is_reapproach = current_phase == "approaching"

        if _ga_is_reapproach:
            # 4-phase: initial approach + climb-out + return + re-approach
            _GA_APP_PTS = 30
            _GA_CLIMB_PTS = 12
            _GA_RETURN_PTS = 10
            _GA_REAPP_PTS = 28
            _ga_app_frac = 0.35
            _ga_climb_frac = 0.15
            _ga_return_frac = 0.15
            _ga_reapp_frac = 0.35
        else:
            # 3-phase: initial approach + climb-out + return to holding
            _GA_APP_PTS = 48
            _GA_CLIMB_PTS = 20
            _GA_RETURN_PTS = 12
            _GA_REAPP_PTS = 0
            _ga_app_frac = 0.60
            _ga_climb_frac = 0.25
            _ga_return_frac = 0.15
            _ga_reapp_frac = 0.0

        _ga_total = _GA_APP_PTS + _GA_CLIMB_PTS + _GA_RETURN_PTS + _GA_REAPP_PTS
        _ga_total_secs = minutes * 60
        _ga_app_dur = _ga_app_frac * _ga_total_secs
        _ga_climb_dur = _ga_climb_frac * _ga_total_secs
        _ga_return_dur = _ga_return_frac * _ga_total_secs
        _ga_reapp_dur = _ga_reapp_frac * _ga_total_secs

        # Climb-out endpoint: project forward on runway heading from threshold
        _rwy_rad_ga = math.radians(_rwy_heading_ga)
        _climb_dist_deg = 0.03  # ~3.3 km climb-out segment
        _climb_end_lat = rwy_threshold_lat + _climb_dist_deg * math.cos(_rwy_rad_ga)
        _climb_end_lon = rwy_threshold_lon + _climb_dist_deg * math.sin(_rwy_rad_ga) / math.cos(math.radians(rwy_threshold_lat))
        _climb_end_alt = 1500.0  # missed approach altitude

        # Re-approach entry point: first approach waypoint (far end of approach)
        # The return phase curves from climb-out end to this entry, then the
        # re-approach follows the approach waypoints toward the aircraft position.
        _reapp_entry_lon, _reapp_entry_lat = _traj_app_wps_ga[0]

        # How far along the approach waypoints the aircraft currently is
        _ga_wp_idx = current_state.waypoint_index if current_state else 0
        _ga_wp_count = len(_traj_app_wps_ga)
        # Clamp to valid range
        _ga_wp_idx = min(_ga_wp_idx, _ga_wp_count - 1)

        # Aircraft type for descent/climb profiles
        _ga_actype = current_state.aircraft_type if current_state else "A320"
        _ga_desc_prof = get_descent_profile(_ga_actype)

        _running_hdg = current_heading
        for i in range(_ga_total):
            if i < _GA_APP_PTS:
                # PHASE 1 — Initial approach: interpolate along waypoints to threshold
                app_progress = i / max(_GA_APP_PTS - 1, 1)
                wp_count = len(_traj_app_wps_ga)
                wp_progress = app_progress * (wp_count - 1)
                wp_idx = int(wp_progress)
                wp_frac = wp_progress - wp_idx
                if wp_idx >= wp_count - 1:
                    wp_idx = wp_count - 2
                    wp_frac = 1.0

                wp1 = _traj_app_wps_ga[wp_idx]
                wp2 = _traj_app_wps_ga[min(wp_idx + 1, wp_count - 1)]
                lon = wp1[0] + (wp2[0] - wp1[0]) * wp_frac
                lat = wp1[1] + (wp2[1] - wp1[1]) * wp_frac

                _ga_prof_prog = 0.5 + 0.5 * app_progress
                prof_alt, prof_spd, prof_vr = interpolate_profile(_ga_desc_prof, _ga_prof_prog)
                alt = prof_alt

                target_hdg = _calculate_heading((lat, lon), (wp2[1], wp2[0]))
                _ga_interval = _ga_app_dur / max(_GA_APP_PTS, 1)
                _running_hdg = _smooth_heading(_running_hdg, target_hdg, 3.0, _ga_interval)
                heading = _running_hdg
                velocity = prof_spd
                vertical_rate = prof_vr
                phase = "approaching"
                t_offset = i * _ga_interval

            elif i < _GA_APP_PTS + _GA_CLIMB_PTS:
                # PHASE 2 — Climb-out: fly runway heading, climb to missed approach alt
                ci = i - _GA_APP_PTS
                climb_progress = ci / max(_GA_CLIMB_PTS - 1, 1)

                lat = rwy_threshold_lat + climb_progress * (_climb_end_lat - rwy_threshold_lat)
                lon = rwy_threshold_lon + climb_progress * (_climb_end_lon - rwy_threshold_lon)
                alt = float(DECISION_HEIGHT_FT) + climb_progress * (_climb_end_alt - DECISION_HEIGHT_FT)

                heading = _rwy_heading_ga
                _running_hdg = heading
                vref_ga = VREF_SPEEDS.get(_ga_actype, _DEFAULT_VREF)
                velocity = vref_ga + 20  # missed approach speed
                vertical_rate = 1500
                phase = "enroute"
                _ga_climb_interval = _ga_climb_dur / max(_GA_CLIMB_PTS, 1)
                t_offset = _ga_app_dur + ci * _ga_climb_interval

            elif i < _GA_APP_PTS + _GA_CLIMB_PTS + _GA_RETURN_PTS:
                # PHASE 3 — Return: curve from climb-out end toward holding/re-approach entry
                ri = i - _GA_APP_PTS - _GA_CLIMB_PTS
                return_progress = ri / max(_GA_RETURN_PTS - 1, 1)

                if _ga_is_reapproach:
                    # Curve toward the first approach waypoint (re-approach entry)
                    _ret_target_lat = _reapp_entry_lat
                    _ret_target_lon = _reapp_entry_lon
                    _ret_target_alt = 3500.0  # re-approach entry altitude
                else:
                    # Curve toward aircraft's current position (holding)
                    _ret_target_lat = end_lat
                    _ret_target_lon = end_lon
                    _ret_target_alt = end_alt

                lat = _climb_end_lat + return_progress * (_ret_target_lat - _climb_end_lat)
                lon = _climb_end_lon + return_progress * (_ret_target_lon - _climb_end_lon)
                alt = _climb_end_alt + return_progress * (_ret_target_alt - _climb_end_alt)

                target_hdg = _calculate_heading((lat, lon), (_ret_target_lat, _ret_target_lon))
                _ga_return_interval = _ga_return_dur / max(_GA_RETURN_PTS, 1)
                _running_hdg = _smooth_heading(_running_hdg, target_hdg, 3.0, _ga_return_interval)
                heading = _running_hdg
                vref_ga = VREF_SPEEDS.get(_ga_actype, _DEFAULT_VREF)
                velocity = vref_ga + 10
                vertical_rate = 500 if _ret_target_alt > _climb_end_alt else -500
                phase = "enroute"
                t_offset = _ga_app_dur + _ga_climb_dur + ri * _ga_return_interval

            else:
                # PHASE 4 — Re-approach: follow approach waypoints from entry to current position
                rai = i - _GA_APP_PTS - _GA_CLIMB_PTS - _GA_RETURN_PTS
                reapp_progress = rai / max(_GA_REAPP_PTS - 1, 1)

                # Interpolate along approach waypoints from wp[0] to wp[_ga_wp_idx],
                # then from there to the aircraft's actual current position.
                # Use 80% of points for waypoint traversal, 20% for final segment.
                if _ga_wp_idx > 0 and reapp_progress < 0.80:
                    # Traversing approach waypoints
                    wp_progress = (reapp_progress / 0.80) * _ga_wp_idx
                    wp_idx = int(wp_progress)
                    wp_frac = wp_progress - wp_idx
                    if wp_idx >= _ga_wp_count - 1:
                        wp_idx = _ga_wp_count - 2
                        wp_frac = 1.0
                    wp1 = _traj_app_wps_ga[wp_idx]
                    wp2 = _traj_app_wps_ga[min(wp_idx + 1, _ga_wp_count - 1)]
                    lon = wp1[0] + (wp2[0] - wp1[0]) * wp_frac
                    lat = wp1[1] + (wp2[1] - wp1[1]) * wp_frac
                else:
                    # Final segment: from last waypoint to aircraft position
                    if _ga_wp_idx > 0:
                        final_frac = (reapp_progress - 0.80) / 0.20
                    else:
                        final_frac = reapp_progress
                    _last_wp = _traj_app_wps_ga[min(_ga_wp_idx, _ga_wp_count - 1)]
                    lon = _last_wp[0] + final_frac * (end_lon - _last_wp[0])
                    lat = _last_wp[1] + final_frac * (end_lat - _last_wp[1])

                # Descent profile for re-approach
                _reapp_prof_prog = 0.5 + 0.5 * reapp_progress
                prof_alt, prof_spd, prof_vr = interpolate_profile(_ga_desc_prof, _reapp_prof_prog)
                alt = prof_alt

                if reapp_progress < 0.95:
                    target_hdg = _calculate_heading((lat, lon), (end_lat, end_lon))
                else:
                    target_hdg = current_heading
                _ga_reapp_interval = _ga_reapp_dur / max(_GA_REAPP_PTS, 1)
                _running_hdg = _smooth_heading(_running_hdg, target_hdg, 3.0, _ga_reapp_interval)
                heading = _running_hdg
                velocity = prof_spd
                vertical_rate = prof_vr
                phase = "approaching"
                t_offset = _ga_app_dur + _ga_climb_dur + _ga_return_dur + rai * _ga_reapp_interval

            _total_ga_dur = _ga_app_dur + _ga_climb_dur + _ga_return_dur + _ga_reapp_dur
            timestamp = now - timedelta(seconds=_total_ga_dur - t_offset)

            points.append({
                "timestamp": timestamp.isoformat(),
                "icao24": icao24,
                "callsign": callsign,
                "latitude": lat,
                "longitude": lon,
                "altitude": max(0, alt),
                "velocity": min(max(50, velocity), MAX_VELOCITY_KTS),
                "heading": heading % 360,
                "vertical_rate": vertical_rate,
                "on_ground": False,
                "flight_phase": phase,
                "data_source": "synthetic",
            })

        return points

    elif is_on_ground:
        # Aircraft is on ground - show approach + landing + taxi trajectory
        # Divide trajectory: 45% approach, 20% landing roll, 35% taxi
        # Realistic rollout: 1500-2500m from touchdown to taxi turnoff.

        # Landing roll direction along actual runway heading
        _rwy_heading = _get_runway_heading()
        if _rwy_heading is None:
            return []
        _rwy_heading_rad = math.radians(_rwy_heading)
        _roll_distance = 0.012  # ~1.3 km roll in degrees (touchdown to high-speed exit)
        roll_dlat = _roll_distance * math.cos(_rwy_heading_rad)
        roll_dlon = _roll_distance * math.sin(_rwy_heading_rad) / math.cos(math.radians(rwy_threshold_lat))

        # Adaptive point spacing: dense on ground, sparse in approach.
        # Real ADS-B has ~4-10s ground updates vs ~30-60s airborne.
        _APP_PTS = 28   # 35% of budget → approach (~58s intervals)
        _ROLL_PTS = 12  # 15% of budget → landing roll (~36s intervals)
        _TAXI_PTS = 40  # 50% of budget → taxi (~19s intervals → ~150m apart)

        _progress_schedule = []
        _time_offsets = []        # cumulative seconds from trajectory start
        _total_secs = minutes * 60

        # Phase durations (must sum to _total_secs)
        _app_dur = 0.45 * _total_secs   # 1620s
        _roll_dur = 0.20 * _total_secs  # 720s
        _taxi_dur = 0.35 * _total_secs  # 1260s

        _app_interval = _app_dur / max(_APP_PTS, 1)
        for k in range(_APP_PTS):
            _progress_schedule.append(0.45 * k / max(_APP_PTS - 1, 1))
            _time_offsets.append(k * _app_interval)

        _roll_interval = _roll_dur / max(_ROLL_PTS, 1)
        for k in range(_ROLL_PTS):
            _progress_schedule.append(0.45 + 0.20 * k / max(_ROLL_PTS - 1, 1))
            _time_offsets.append(_app_dur + k * _roll_interval)

        _taxi_interval = _taxi_dur / max(_TAXI_PTS, 1)
        for k in range(_TAXI_PTS):
            _progress_schedule.append(0.65 + 0.35 * k / max(_TAXI_PTS - 1, 1))
            _time_offsets.append(_app_dur + _roll_dur + k * _taxi_interval)

        num_points = len(_progress_schedule)

        _running_hdg = current_heading  # smooth heading across points
        for i, progress in enumerate(_progress_schedule):
            # Per-point time delta for heading smoothing
            _pt_interval = (_time_offsets[i] - _time_offsets[i - 1]) if i > 0 else _app_interval

            if progress < 0.45:
                # APPROACH PHASE: Following ILS glideslope
                approach_progress = progress / 0.45  # 0 to 1

                # Interpolate along the approach waypoints
                # Start from initial approach fix, end at threshold
                _origin_airport = current_state.origin_airport if current_state else None
                _traj_app_wps = _get_approach_waypoints(_origin_airport)
                wp_count = len(_traj_app_wps)
                wp_progress = approach_progress * (wp_count - 1)
                wp_idx = int(wp_progress)
                wp_frac = wp_progress - wp_idx

                if wp_idx >= wp_count - 1:
                    wp_idx = wp_count - 2
                    wp_frac = 1.0

                # Interpolate between waypoints
                wp1 = _traj_app_wps[wp_idx]
                wp2 = _traj_app_wps[min(wp_idx + 1, wp_count - 1)]

                lon = wp1[0] + (wp2[0] - wp1[0]) * wp_frac
                lat = wp1[1] + (wp2[1] - wp1[1]) * wp_frac

                # Altitude from descent profile — progress 0.5-1.0
                _gnd_actype = current_state.aircraft_type if current_state else "A320"
                _gnd_desc_prof = get_descent_profile(_gnd_actype)
                _gnd_prof_prog = 0.5 + 0.5 * approach_progress
                prof_alt, prof_spd, prof_vr = interpolate_profile(_gnd_desc_prof, _gnd_prof_prog)
                alt = prof_alt

                # Smooth heading toward next waypoint
                target_hdg = _calculate_heading((lat, lon), (wp2[1], wp2[0]))
                _running_hdg = _smooth_heading(_running_hdg, target_hdg, 3.0, _pt_interval)
                heading = _running_hdg

                phase = "approaching" if alt > 500 else "landing"
                velocity = prof_spd
                vertical_rate = prof_vr

            elif progress < 0.65:
                # LANDING ROLL: Decelerating on runway (20% of trajectory)
                roll_progress = (progress - 0.45) / 0.20

                # Move along runway heading
                lat = rwy_threshold_lat + roll_progress * roll_dlat
                lon = rwy_threshold_lon + roll_progress * roll_dlon
                alt = 0

                heading = _rwy_heading
                phase = "ground"
                velocity = 130 - roll_progress * 100  # Decelerate to 30 kts
                vertical_rate = 0

            else:
                # TAXI PHASE: Follow taxiway route from runway to current position
                taxi_progress = (progress - 0.65) / 0.35

                # Landing roll endpoint (must match the roll phase above)
                roll_end_lat = rwy_threshold_lat + roll_dlat
                roll_end_lon = rwy_threshold_lon + roll_dlon

                # Build taxi path: use the flight's taxi route if available,
                # otherwise fall back to the gate-based route or straight line.
                taxi_path = []
                if current_state and current_state.taxi_route:
                    # Use the actual route the aircraft is following
                    taxi_path = [(lon_wp, lat_wp) for lon_wp, lat_wp in current_state.taxi_route]
                elif current_state and current_state.assigned_gate:
                    taxi_path = _get_taxi_waypoints_arrival(current_state.assigned_gate)

                if len(taxi_path) >= 2:
                    taxi_path_latlons = [(lat_wp, lon_wp) for lon_wp, lat_wp in taxi_path]

                    # Connect roll endpoint to the taxi route smoothly:
                    # Find the closest point on the taxi route to roll_end,
                    # then splice from that point onward to avoid backtracking.
                    best_idx = 0
                    best_dist = _distance_between(
                        (roll_end_lat, roll_end_lon), taxi_path_latlons[0]
                    )
                    for _ti in range(1, len(taxi_path_latlons)):
                        d = _distance_between(
                            (roll_end_lat, roll_end_lon), taxi_path_latlons[_ti]
                        )
                        if d < best_dist:
                            best_dist = d
                            best_idx = _ti

                    # Trim the taxi path: start from the closest point onward
                    taxi_path_latlons = taxi_path_latlons[best_idx:]

                    # Prepend roll endpoint for smooth phase transition
                    taxi_path_latlons.insert(0, (roll_end_lat, roll_end_lon))
                    # Append current position only if close to last taxi waypoint
                    # to avoid a visible "jump" across the airport
                    last_taxi = taxi_path_latlons[-1]
                    gap = _distance_between(last_taxi, (end_lat, end_lon))
                    if gap < 0.005:  # ~500m — reasonable gate proximity
                        taxi_path_latlons.append((end_lat, end_lon))

                    # Compute cumulative distances along the path
                    cum_dist = [0.0]
                    for j in range(1, len(taxi_path_latlons)):
                        d = _distance_between(taxi_path_latlons[j - 1], taxi_path_latlons[j])
                        cum_dist.append(cum_dist[-1] + d)
                    total_dist = cum_dist[-1] if cum_dist[-1] > 0 else 1e-9

                    # Find the interpolated position along the path
                    target_dist = taxi_progress * total_dist
                    seg_idx = 0
                    for j in range(1, len(cum_dist)):
                        if cum_dist[j] >= target_dist:
                            seg_idx = j - 1
                            break
                    else:
                        seg_idx = len(cum_dist) - 2

                    seg_len = cum_dist[seg_idx + 1] - cum_dist[seg_idx]
                    seg_frac = (target_dist - cum_dist[seg_idx]) / seg_len if seg_len > 0 else 0.0
                    seg_frac = max(0.0, min(1.0, seg_frac))

                    p1 = taxi_path_latlons[seg_idx]
                    p2 = taxi_path_latlons[seg_idx + 1]
                    lat = p1[0] + seg_frac * (p2[0] - p1[0])
                    lon = p1[1] + seg_frac * (p2[1] - p1[1])
                    heading = _calculate_heading((lat, lon), p2)
                else:
                    # Fallback: straight line from runway exit to current position
                    lat = roll_end_lat + taxi_progress * (end_lat - roll_end_lat)
                    lon = roll_end_lon + taxi_progress * (end_lon - roll_end_lon)
                    heading = _calculate_heading((lat, lon), (end_lat, end_lon))

                alt = 0
                phase = "ground"
                velocity = TAXI_SPEED_STRAIGHT_KTS
                vertical_rate = 0

            # Append point — timestamp from adaptive time offsets
            _total_duration = _time_offsets[-1]
            timestamp = now - timedelta(seconds=_total_duration - _time_offsets[i])

            points.append({
                "timestamp": timestamp.isoformat(),
                "icao24": icao24,
                "callsign": callsign,
                "latitude": lat,
                "longitude": lon,
                "altitude": max(0, alt),
                "velocity": min(max(10, velocity), MAX_VELOCITY_KTS),
                "heading": heading,
                "vertical_rate": vertical_rate,
                "on_ground": alt < 50,
                "flight_phase": phase,
                "data_source": "synthetic",
            })

    elif current_phase in ["climbing", "cruising", "departing", "takeoff", "enroute"]:
        # DEPARTURE trajectory - show takeoff, climb, then turn toward destination
        dest_airport = current_state.destination_airport if current_state else None
        _dep_rwy_heading = _get_runway_heading()
        if _dep_rwy_heading is None:
            return []  # No runway data, disable trajectory
        dest_bearing = _bearing_to_airport(dest_airport) if dest_airport else _dep_rwy_heading

        _traj_dep_wps = _get_departure_waypoints(dest_airport)
        if not _traj_dep_wps:
            return []  # No runway data, disable trajectory

        # OpenAP climb profile for realistic speeds/altitudes
        _dep_actype = current_state.aircraft_type if current_state else "A320"
        _dep_climb_prof = get_climb_profile(_dep_actype)

        _running_hdg = _dep_rwy_heading  # smooth heading across points
        for i in range(num_points):
            progress = i / (num_points - 1) if num_points > 1 else 0

            if progress < 0.15:
                # Takeoff roll and initial climb — profile progress 0.0-0.05
                takeoff_progress = progress / 0.15
                profile_prog = takeoff_progress * 0.05
                prof_alt, prof_spd, prof_vr = interpolate_profile(_dep_climb_prof, profile_prog)

                wp = _traj_dep_wps[0]
                lat = dep_rwy_lat + takeoff_progress * (wp[1] - dep_rwy_lat)
                lon = dep_rwy_lon + takeoff_progress * (wp[0] - dep_rwy_lon)
                alt = takeoff_progress * wp[2]
                heading = _dep_rwy_heading
                _running_hdg = heading
                velocity = prof_spd
                vertical_rate = prof_vr if takeoff_progress > 0.3 else 0
                phase = "takeoff" if takeoff_progress < 0.5 else "climbing"
            elif progress < 0.50:
                # Climb out following departure waypoints — profile progress 0.05-0.40
                climb_progress = (progress - 0.15) / 0.35
                profile_prog = 0.05 + climb_progress * 0.35
                prof_alt, prof_spd, prof_vr = interpolate_profile(_dep_climb_prof, profile_prog)

                wp_count = len(_traj_dep_wps)
                wp_progress = climb_progress * (wp_count - 1)
                wp_idx = int(wp_progress)
                wp_frac = wp_progress - wp_idx

                if wp_idx >= wp_count - 1:
                    wp_idx = wp_count - 2
                    wp_frac = 1.0

                wp1 = _traj_dep_wps[wp_idx]
                wp2 = _traj_dep_wps[min(wp_idx + 1, wp_count - 1)]

                lon = wp1[0] + (wp2[0] - wp1[0]) * wp_frac
                lat = wp1[1] + (wp2[1] - wp1[1]) * wp_frac
                alt = wp1[2] + (wp2[2] - wp1[2]) * wp_frac

                target_hdg = _calculate_heading((lat, lon), (wp2[1], wp2[0]))
                _running_hdg = _smooth_heading(_running_hdg, target_hdg, 3.0, interval_seconds)
                heading = _running_hdg
                # Enforce 250kt below FL100
                velocity = min(prof_spd, MAX_SPEED_BELOW_FL100_KTS) if alt < 10000 else prof_spd
                vertical_rate = prof_vr
                phase = "departing"
            else:
                # En-route extension — profile progress 0.40-0.80
                enroute_progress = (progress - 0.50) / 0.50
                profile_prog = 0.40 + enroute_progress * 0.40
                prof_alt, prof_spd, prof_vr = interpolate_profile(_dep_climb_prof, profile_prog)

                last_wp = _traj_dep_wps[-1]
                start_lat_dep = last_wp[1]
                start_lon_dep = last_wp[0]
                start_alt_dep = last_wp[2]

                # Project toward destination bearing
                dist = enroute_progress * 0.15  # ~10 NM extension
                lat = start_lat_dep + dist * math.cos(math.radians(dest_bearing))
                lon = start_lon_dep + dist * math.sin(math.radians(dest_bearing)) / math.cos(math.radians(start_lat_dep))
                alt = start_alt_dep + enroute_progress * (prof_alt - start_alt_dep)

                _running_hdg = _smooth_heading(_running_hdg, dest_bearing, 3.0, interval_seconds)
                heading = _running_hdg
                velocity = min(prof_spd, MAX_SPEED_BELOW_FL100_KTS) if alt < 10000 else prof_spd
                vertical_rate = prof_vr if enroute_progress < 0.7 else max(200, prof_vr * 0.3)
                phase = "departing"

            timestamp = now - timedelta(seconds=interval_seconds * (num_points - 1 - i))

            points.append({
                "timestamp": timestamp.isoformat(),
                "icao24": icao24,
                "callsign": callsign,
                "latitude": lat,
                "longitude": lon,
                "altitude": max(0, alt),
                "velocity": min(max(50, velocity), MAX_VELOCITY_KTS),
                "heading": heading,
                "vertical_rate": vertical_rate,
                "on_ground": alt < 50,
                "flight_phase": phase,
                "data_source": "synthetic",
            })

    else:
        # APPROACH trajectory (aircraft still descending)
        # Use origin-aware approach waypoints so the trajectory starts from
        # the correct direction, then interpolate toward the aircraft's
        # current position.  Only show waypoints up to the aircraft's
        # current position along the approach (not past it).
        origin_airport = current_state.origin_airport if current_state else None
        center = get_airport_center()
        _traj_app_wps2 = _get_approach_waypoints(origin_airport)

        # Clamp end position to reasonable airport vicinity
        clamped_lat = max(center[0] - 0.5, min(center[0] + 0.5, end_lat))
        clamped_lon = max(center[1] - 0.5, min(center[1] + 0.5, end_lon))
        final_alt = end_alt if abs(end_lat - center[0]) < 0.5 else 3000

        # ── Guard: prevent trajectories that cross over the airfield ──
        # The approach waypoints go from far out (index 0) toward the
        # runway threshold (last index).  If the aircraft's current
        # position is on the *opposite* side of the threshold from the
        # approach direction, drawing the full waypoint path would cross
        # the airport center — producing unrealistic overflight.
        #
        # Detection: the last waypoint (threshold) should be *between*
        # the first waypoint (entry) and the aircraft.  If the aircraft
        # is closer to the first waypoint than the threshold is, the
        # aircraft is beyond the threshold on the approach side — fine.
        # If the aircraft is farther from the first waypoint than the
        # threshold AND on the opposite side of the threshold from the
        # approach entry, the path would cross the field.
        threshold_wp = _traj_app_wps2[-1]  # (lon, lat, alt)
        entry_wp = _traj_app_wps2[0]       # (lon, lat, alt)
        dist_entry_to_threshold = _distance_between(
            (entry_wp[1], entry_wp[0]), (threshold_wp[1], threshold_wp[0])
        )
        dist_entry_to_aircraft = _distance_between(
            (entry_wp[1], entry_wp[0]), (clamped_lat, clamped_lon)
        )
        dist_threshold_to_aircraft = _distance_between(
            (threshold_wp[1], threshold_wp[0]), (clamped_lat, clamped_lon)
        )

        # Aircraft is "past the threshold" if it's farther from entry
        # than the threshold AND farther from the threshold than the
        # approach corridor width (~0.02 deg ≈ 2 km).
        aircraft_past_threshold = (
            dist_entry_to_aircraft > dist_entry_to_threshold
            and dist_threshold_to_aircraft > 0.02
        )

        if aircraft_past_threshold:
            # Back-project a short trailing segment so the renderer
            # has >= 2 points (splitAtGaps drops single-point segments).
            back_dist = 0.02  # ~2.2 km behind aircraft
            back_bearing = (current_heading + 180) % 360
            back_lat = clamped_lat + back_dist * math.cos(math.radians(back_bearing))
            back_lon = clamped_lon + back_dist * math.sin(math.radians(back_bearing)) / math.cos(math.radians(clamped_lat))
            path_wps = [
                (back_lon, back_lat, final_alt + 300),
                (clamped_lon, clamped_lat, final_alt),
            ]
            path_count = 2
        else:
            # Normal case: find nearest waypoint and build path
            wp_count = len(_traj_app_wps2)
            best_wp_idx = 0
            best_wp_dist = float('inf')
            for _wi in range(wp_count):
                _wd = _distance_between(
                    (clamped_lat, clamped_lon),
                    (_traj_app_wps2[_wi][1], _traj_app_wps2[_wi][0])
                )
                if _wd < best_wp_dist:
                    best_wp_dist = _wd
                    best_wp_idx = _wi

            # Build path: approach waypoints from first up to nearest-to-aircraft,
            # then final segment to the aircraft's exact position.
            path_wps = _traj_app_wps2[:best_wp_idx + 1]
            # Append current position as the final target
            path_wps.append((clamped_lon, clamped_lat, final_alt))
            path_count = len(path_wps)

        if path_count < 2:
            # Single point — just emit the aircraft's current position
            timestamp = now
            points.append({
                "timestamp": timestamp.isoformat(),
                "icao24": icao24,
                "callsign": callsign,
                "latitude": clamped_lat,
                "longitude": clamped_lon,
                "altitude": max(0, final_alt),
                "velocity": 200,
                "heading": current_heading,
                "vertical_rate": -600,
                "on_ground": False,
                "flight_phase": "approaching",
                "data_source": "synthetic",
            })
        else:
            _running_hdg = current_heading  # smooth heading across points
            for i in range(num_points):
                progress = i / (num_points - 1) if num_points > 1 else 0

                wp_progress = progress * (path_count - 1)
                wp_idx = int(wp_progress)
                wp_frac = wp_progress - wp_idx
                if wp_idx >= path_count - 1:
                    wp_idx = path_count - 2
                    wp_frac = 1.0

                wp1 = path_wps[wp_idx]
                wp2 = path_wps[min(wp_idx + 1, path_count - 1)]

                lon = wp1[0] + (wp2[0] - wp1[0]) * wp_frac
                lat = wp1[1] + (wp2[1] - wp1[1]) * wp_frac

                # Altitude from descent profile — progress 0.3-1.0
                _air_actype = current_state.aircraft_type if current_state else "A320"
                _air_desc_prof = get_descent_profile(_air_actype)
                _air_prof_prog = 0.3 + 0.7 * progress
                prof_alt, prof_spd, prof_vr = interpolate_profile(_air_desc_prof, _air_prof_prog)
                alt = prof_alt

                target_hdg = _calculate_heading((lat, lon), (wp2[1], wp2[0]))
                _running_hdg = _smooth_heading(_running_hdg, target_hdg, 3.0, interval_seconds)
                heading = _running_hdg
                velocity = prof_spd
                vertical_rate = prof_vr
                phase = "approaching" if alt > 500 else "landing"

                timestamp = now - timedelta(seconds=interval_seconds * (num_points - 1 - i))

                points.append({
                    "timestamp": timestamp.isoformat(),
                    "icao24": icao24,
                    "callsign": callsign,
                    "latitude": lat,
                    "longitude": lon,
                    "altitude": max(0, alt),
                    "velocity": min(max(100, velocity), MAX_VELOCITY_KTS),
                    "heading": heading,
                    "vertical_rate": vertical_rate,
                    "on_ground": alt < 50,
                    "flight_phase": phase,
                    "data_source": "synthetic",
                })

    return points


def reset_synthetic_state() -> dict:
    """Reset all synthetic flight state to start fresh.

    Clears all flight states, runway occupancy, and gate assignments
    to regenerate flights with proper separation from scratch.

    Returns:
        dict with count of cleared items.
    """
    global _flight_states, _last_update, _runway_states, _runway_28L, _runway_28R, _gate_states, _loaded_gates

    cleared_flights = len(_flight_states)
    cleared_gates = len(_gate_states)

    # Clear flight state only — airport center is managed by the activate endpoint
    _flight_states.clear()
    _bearing_cache.clear()
    _last_update = 0.0
    _runway_states.clear()
    # Re-populate with current airport's runway names (dynamic, not hardcoded SFO)
    arr_rwy = _get_arrival_runway_name()
    _runway_28L = RunwayState()
    _runway_28R = RunwayState()
    _runway_states[arr_rwy] = _runway_28L
    recip = _get_reciprocal_designator(arr_rwy)
    if recip:
        _runway_states[recip] = _runway_28R
    _gate_states.clear()
    _loaded_gates = None  # Force gate reload with current airport center
    import src.ingestion._state as _st
    _st._occupied_gate_count = 0

    # Clear event buffers (drain functions clear under lock)
    drain_phase_transitions()
    drain_gate_events()
    drain_predictions()
    drain_turnaround_events()

    return {
        "cleared_flights": cleared_flights,
        "cleared_gates": cleared_gates,
        "status": "reset_complete",
    }

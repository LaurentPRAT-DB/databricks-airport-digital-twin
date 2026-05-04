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


from src.ingestion._flight_lifecycle import (  # noqa: F401
    set_calibration_gate_minutes,
    set_calibration_taxi_out,
    set_calibration_taxi_in,
    set_current_weather,
    _get_turnaround_weather_factor,
    _get_turnaround_congestion_factor,
    _get_turnaround_day_of_week_factor,
    _get_turnaround_international_factor,
    get_gate_last_delay,
    get_airport_load_ratio,
    _gate_last_delay,
    _get_aircraft_type_for_airline,
    _is_international_airport,
    _get_origin_country,
    _get_current_airport_profile,
    _pick_random_airport,
    _pick_random_origin,
    _pick_random_destination,
    _GATE_PHASES,
    _build_turnaround_schedule,
    _create_new_flight,
    _update_flight_state,
    _get_flight_phase_name,
)

from src.ingestion._generation import (  # noqa: F401
    get_flight_turnaround_info,
    get_current_flight_states,
    get_flights_as_schedule,
    generate_synthetic_flights,
    generate_synthetic_trajectory,
    reset_synthetic_state,
)


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


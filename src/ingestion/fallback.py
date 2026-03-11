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

import math
import random
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass, field
from enum import Enum

from faker import Faker


fake = Faker()

# ============================================================================
# EVENT BUFFERS for ML training data persistence
# ============================================================================
# Thread-safe buffers that collect events during state machine updates.
# Drained periodically by DataGeneratorService for Lakebase persistence.

_MAX_BUFFER_SIZE = 10000  # Cap to prevent unbounded memory growth

_phase_transition_buffer: List[Dict[str, Any]] = []
_phase_transition_lock = threading.Lock()

_gate_event_buffer: List[Dict[str, Any]] = []
_gate_event_lock = threading.Lock()

_prediction_buffer: List[Dict[str, Any]] = []
_prediction_lock = threading.Lock()


def emit_phase_transition(
    icao24: str,
    callsign: str,
    from_phase: str,
    to_phase: str,
    latitude: float,
    longitude: float,
    altitude: float,
    aircraft_type: str = "A320",
    assigned_gate: Optional[str] = None,
) -> None:
    """Record a flight phase transition event."""
    event = {
        "icao24": icao24,
        "callsign": callsign,
        "from_phase": from_phase,
        "to_phase": to_phase,
        "latitude": latitude,
        "longitude": longitude,
        "altitude": altitude,
        "aircraft_type": aircraft_type,
        "assigned_gate": assigned_gate,
        "event_time": datetime.now(timezone.utc).isoformat(),
    }
    with _phase_transition_lock:
        _phase_transition_buffer.append(event)
        if len(_phase_transition_buffer) > _MAX_BUFFER_SIZE:
            del _phase_transition_buffer[: _MAX_BUFFER_SIZE // 2]


def emit_gate_event(
    icao24: str,
    callsign: str,
    gate: str,
    event_type: str,  # "assign", "occupy", "release"
    aircraft_type: str = "A320",
) -> None:
    """Record a gate assignment/release event."""
    event = {
        "icao24": icao24,
        "callsign": callsign,
        "gate": gate,
        "event_type": event_type,
        "aircraft_type": aircraft_type,
        "event_time": datetime.now(timezone.utc).isoformat(),
    }
    with _gate_event_lock:
        _gate_event_buffer.append(event)
        if len(_gate_event_buffer) > _MAX_BUFFER_SIZE:
            del _gate_event_buffer[: _MAX_BUFFER_SIZE // 2]


def emit_prediction(
    prediction_type: str,  # "delay", "congestion", "gate_recommendation"
    icao24: Optional[str],
    result: Dict[str, Any],
) -> None:
    """Record an ML prediction result for feedback/evaluation."""
    event = {
        "prediction_type": prediction_type,
        "icao24": icao24,
        "result_json": result,
        "event_time": datetime.now(timezone.utc).isoformat(),
    }
    with _prediction_lock:
        _prediction_buffer.append(event)
        if len(_prediction_buffer) > _MAX_BUFFER_SIZE:
            del _prediction_buffer[: _MAX_BUFFER_SIZE // 2]


def drain_phase_transitions() -> List[Dict[str, Any]]:
    """Drain and return all buffered phase transition events."""
    with _phase_transition_lock:
        events = list(_phase_transition_buffer)
        _phase_transition_buffer.clear()
    return events


def drain_gate_events() -> List[Dict[str, Any]]:
    """Drain and return all buffered gate events."""
    with _gate_event_lock:
        events = list(_gate_event_buffer)
        _gate_event_buffer.clear()
    return events


def drain_predictions() -> List[Dict[str, Any]]:
    """Drain and return all buffered prediction events."""
    with _prediction_lock:
        events = list(_prediction_buffer)
        _prediction_buffer.clear()
    return events


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
            "velocity": state.velocity,
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

# ============================================================================
# SEPARATION CONSTANTS (FAA/ICAO Standards)
# ============================================================================

# Wake turbulence categories
WAKE_CATEGORY = {
    "A380": "SUPER",
    "B747": "HEAVY", "B777": "HEAVY", "B787": "HEAVY", "A330": "HEAVY",
    "A340": "HEAVY", "A350": "HEAVY", "A345": "HEAVY",
    "A320": "LARGE", "A321": "LARGE", "A319": "LARGE", "A318": "LARGE",
    "B737": "LARGE", "B738": "LARGE", "B739": "LARGE",
    "CRJ9": "SMALL", "E175": "SMALL", "E190": "SMALL",
}

# Minimum separation in nautical miles (lead aircraft → following aircraft)
WAKE_SEPARATION_NM = {
    ("SUPER", "SUPER"): 4.0,
    ("SUPER", "HEAVY"): 6.0,
    ("SUPER", "LARGE"): 7.0,
    ("SUPER", "SMALL"): 8.0,
    ("HEAVY", "HEAVY"): 4.0,
    ("HEAVY", "LARGE"): 5.0,
    ("HEAVY", "SMALL"): 6.0,
    ("LARGE", "LARGE"): 3.0,
    ("LARGE", "SMALL"): 4.0,
    ("SMALL", "SMALL"): 3.0,
}
DEFAULT_SEPARATION_NM = 3.0

# Taxi speed standards (ICAO Doc 9157 / Annex 14 design speeds)
# 1 knot ≈ 0.5144 m/s; 1° latitude ≈ 111,000 m
_KTS_TO_DEG_PER_SEC = 0.5144 / 111_000  # ~4.63e-6 °/s per knot

TAXI_SPEED_STRAIGHT_KTS = 25    # ICAO standard taxiway design speed
TAXI_SPEED_TURN_KTS = 15        # Reduced speed through turns
TAXI_SPEED_RAMP_KTS = 8         # Near-gate / ramp area
TAXI_SPEED_PUSHBACK_KTS = 3     # Tug-assisted pushback

# Convert NM to degrees (approximate at this latitude)
# 1 NM ≈ 1/60 degree ≈ 0.0167 degrees
NM_TO_DEG = 1.0 / 60.0

# Minimum separation distances
MIN_APPROACH_SEPARATION_DEG = 3.0 * NM_TO_DEG  # 3 NM minimum on approach
MIN_TAXI_SEPARATION_DEG = 0.003  # ~300m for taxi operations (larger for 3D visibility)
MIN_GATE_SEPARATION_DEG = 0.010  # ~800m in 3D scale for gate area (prevents overlap)

# Common US airline callsign prefixes with typical aircraft types
AIRLINE_FLEET = {
    "UAL": ["B738", "B739", "A320", "A319", "B777", "B787"],  # United Airlines
    "DAL": ["B738", "B739", "A320", "A321", "A330", "B777"],  # Delta Air Lines
    "AAL": ["B738", "A321", "A320", "B777", "B787"],          # American Airlines
    "SWA": ["B737", "B738"],                                  # Southwest Airlines
    "JBU": ["A320", "A321", "A319"],                          # JetBlue Airways
    "ASA": ["B738", "B739", "A320"],                          # Alaska Airlines
    "UAE": ["A380", "B777", "A345"],                          # Emirates
    "AFR": ["A320", "A318", "A319", "A330"],                  # Air France
    "CPA": ["A330", "B777", "A350"],                          # Cathay Pacific
}

CALLSIGN_PREFIXES = list(AIRLINE_FLEET.keys())

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
    # International Terminal - Boarding Area A
    "A1": (37.6155, -122.3900),  # Wide-body capable
    "A2": (37.6150, -122.3890),
    # Domestic Terminal 1
    "B1": (37.6165, -122.3850),
    "B2": (37.6160, -122.3840),
    # Domestic Terminal 2/3
    "C1": (37.6175, -122.3800),
    "C2": (37.6170, -122.3790),
}

# Cache for dynamically loaded gates
_loaded_gates: Optional[Dict[str, tuple]] = None


def get_gates() -> Dict[str, tuple]:
    """
    Get gate positions, preferring imported OSM data over defaults.

    Only caches the result once the airport config service reports ready,
    preventing early calls from permanently locking in the 9-gate fallback.

    Returns:
        Dictionary mapping gate refs to (latitude, longitude) tuples
    """
    global _loaded_gates

    if _loaded_gates is not None:
        return _loaded_gates

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
                    gates[ref] = (float(lat), float(lon))

            if gates:
                # Only cache when config is fully loaded to avoid
                # permanently locking in a partial/default gate set
                if service.config_ready:
                    _loaded_gates = gates
                return gates
    except ImportError:
        # App backend not available (e.g., running standalone)
        pass
    except Exception:
        # Service not initialized or no gates loaded
        pass

    return _DEFAULT_GATES


def reload_gates() -> Dict[str, tuple]:
    """
    Force reload of gates from airport config service.

    Call this after importing new OSM data to refresh the gate positions.

    Returns:
        Updated dictionary mapping gate refs to (latitude, longitude) tuples
    """
    global _loaded_gates, _flight_states
    _loaded_gates = None
    gates = get_gates()
    # Reset gate states and flight states to use new gates
    _reset_gate_states()
    _flight_states.clear()  # Clear flights so they regenerate with new gates
    return gates


# Backward compatibility: GATES is now a function call result
# Code using GATES directly will get the default gates
GATES = _DEFAULT_GATES

# ============================================================================
# TAXIWAY WAYPOINTS
# ============================================================================
# Routes from runways to gates, aligned with frontend taxiway definitions
# Coordinates follow actual SFO ground movement paths

# Arrival route: Runway 28L → Terminal gates
# Aircraft land heading west (280°), exit via high-speed taxiway, turn north to terminal
TAXI_WAYPOINTS_ARRIVAL = [
    (-122.370, 37.615),    # High-speed exit from 28L (midpoint rollout)
    (-122.378, 37.616),    # Taxiway Alpha intersection
    (-122.385, 37.617),    # Turn toward terminal complex
    (-122.390, 37.616),    # Terminal apron entry
]

# Departure route: Terminal gates → Runway 28R
# Aircraft push back, taxi south then east to runway 28R for departure
TAXI_WAYPOINTS_DEPARTURE = [
    (-122.390, 37.616),    # Leave terminal apron
    (-122.385, 37.618),    # Taxiway Bravo
    (-122.378, 37.620),    # Join main taxiway
    (-122.370, 37.622),    # Hold short runway 28R
    (-122.360, 37.614),    # Runway 28R entry point
]

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
    # Initial approach fix - 15 NM east of threshold, over San Pablo Bay
    (-122.10, 37.58, 6000),
    (-122.15, 37.588, 5000),
    # Intermediate fix - 10 NM from threshold
    (-122.20, 37.595, 4000),
    (-122.24, 37.600, 3200),
    # Final approach fix - 5 NM from threshold
    (-122.28, 37.605, 2500),
    (-122.30, 37.607, 1800),
    # Glideslope intercept - 3 NM from threshold
    (-122.32, 37.608, 1000),
    (-122.333, 37.609, 650),
    # Short final - 1 NM from threshold
    (-122.345, 37.610, 300),
    (-122.352, 37.6109, 150),
    # Runway 28L threshold (touchdown zone)
    (_RWY_28L_LON, _RWY_28L_LAT, 15),
]

# ============================================================================
# DEPARTURE PATH - Runway 28R
# ============================================================================
# Standard departure from runway 28R (north parallel)
# Initial climb on runway heading, then turn per SID

_RWY_28R_LAT = 37.613534
_RWY_28R_LON = -122.357141

DEPARTURE_WAYPOINTS = [
    # Initial climb - runway 28R at rotation
    (_RWY_28R_LON + 0.02, _RWY_28R_LAT, 500),
    # Climbing runway heading (284° true)
    (-122.32, 37.608, 2000),
    # Continue climb over bay
    (-122.28, 37.60, 4000),
    # Departure fix - climbing to cruise
    (-122.20, 37.58, 8000),
    # Enroute - over the bay
    (-122.10, 37.55, 12000),
]


def _get_approach_waypoints(origin_iata: Optional[str] = None) -> list:
    """Get approach waypoints aligned with the actual runway.

    When *origin_iata* is provided the approach starts from the bearing of that
    airport, so a flight from SEA appears from the north, one from LAX from the
    south, etc.  When origin is ``None`` a default entry from the east is used.

    Returns an empty list when no OSM runway data is available, which disables
    the approach trajectory line rather than producing a nonsensical route.
    """
    # Require real runway data — no runway, no trajectory
    rwy_threshold = _get_runway_threshold()  # (lon, lat) or None
    rwy_heading = _get_runway_heading()       # float or None
    if rwy_threshold is None or rwy_heading is None:
        return []

    rwy_lat, rwy_lon = rwy_threshold[1], rwy_threshold[0]
    approach_course = (rwy_heading + 180) % 360

    if origin_iata is None:
        entry_dir = (approach_course + 180) % 360  # Default: from behind the approach course
    else:
        bearing_to_apt = _bearing_from_airport(origin_iata)
        entry_dir = (bearing_to_apt + 180) % 360

    # Phase 2: Final approach — centered on RUNWAY THRESHOLD
    final_distances = [0.10, 0.075, 0.05, 0.035, 0.02, 0.01, 0.0]
    final_altitudes = [2500, 1800, 1000, 650, 300, 150, 15]
    final_wps = []
    for dist, alt in zip(final_distances, final_altitudes):
        if dist == 0.0:
            final_wps.append((rwy_lon, rwy_lat, alt))
        else:
            pt = _point_on_circle(rwy_lat, rwy_lon, approach_course, dist)
            final_wps.append((pt[1], pt[0], alt))

    # Phase 1: Base leg — blend from entry_dir to approach_course
    # Radiate from the outermost final approach point so they connect smoothly
    anchor_lat, anchor_lon = final_wps[0][1], final_wps[0][0]
    base_distances = [0.15, 0.12, 0.09, 0.05]
    base_altitudes = [6000, 5000, 4000, 3200]
    base_wps = []
    for i, (dist, alt) in enumerate(zip(base_distances, base_altitudes)):
        blend = i / len(base_distances)  # 0→0.75
        bearing = entry_dir + _shortest_angle_diff(entry_dir, approach_course) * blend
        pt = _point_on_circle(anchor_lat, anchor_lon, bearing, dist)
        base_wps.append((pt[1], pt[0], alt))

    return base_wps + final_wps


def _get_runway_heading() -> Optional[float]:
    """Compute the runway heading from OSM runway geometry.

    Returns the heading in degrees or None when no OSM runway data is available.
    """
    rwy = _get_osm_primary_runway()
    if rwy:
        _, _, heading = _osm_runway_endpoints(rwy)
        return heading
    return None


def _get_departure_waypoints(destination_iata: Optional[str] = None) -> list:
    """Get departure waypoints aligned with the actual runway.

    When *destination_iata* is provided the departure curves toward that
    airport's bearing so the trajectory visually heads in the right direction.

    Returns an empty list when no OSM runway data is available, which disables
    the departure trajectory line rather than producing a nonsensical route.
    """
    # Require real runway data — no runway, no trajectory
    dep_rwy = _get_departure_runway()  # (lon, lat) or None
    rwy_heading = _get_runway_heading()  # float or None
    if dep_rwy is None or rwy_heading is None:
        return []

    dep_lat, dep_lon = dep_rwy[1], dep_rwy[0]

    if destination_iata is None:
        exit_dir = rwy_heading  # Default: continue along runway heading
    else:
        exit_dir = _bearing_to_airport(destination_iata)

    # Distances and altitudes for 9 departure waypoints
    distances = [0.02, 0.035, 0.05, 0.075, 0.10, 0.135, 0.17, 0.21, 0.25]
    altitudes = [500, 1200, 2000, 3000, 4000, 6000, 8000, 10000, 12000]

    waypoints = []
    for i, (dist, alt) in enumerate(zip(distances, altitudes)):
        # Blend from runway heading to destination bearing over the first 4 waypoints
        if i < 2:
            bearing = rwy_heading
        elif i < 5:
            blend = (i - 2) / 3.0  # 0.0 → 1.0 over waypoints 2-4
            bearing = rwy_heading + _shortest_angle_diff(rwy_heading, exit_dir) * blend
        else:
            bearing = exit_dir
        pt = _point_on_circle(dep_lat, dep_lon, bearing, dist)
        waypoints.append((pt[1], pt[0], alt))  # (lon, lat, alt)
    return waypoints


def _get_osm_primary_runway() -> Optional[dict]:
    """Get the primary (longest) runway from OSM config data.

    Returns the runway dict with 'geoPoints' [{latitude, longitude}, ...] or None
    if no OSM runway data is available.
    """
    try:
        from app.backend.services.airport_config_service import get_airport_config_service
        service = get_airport_config_service()
        config = service.get_config()
        runways = config.get("osmRunways", [])
        if not runways:
            return None
        # Pick the longest runway by number of geoPoints (proxy for length)
        best = max(runways, key=lambda r: len(r.get("geoPoints", [])))
        if len(best.get("geoPoints", [])) < 2:
            return None
        return best
    except Exception:
        return None


def _osm_runway_endpoints(runway: dict) -> tuple:
    """Extract threshold and opposite-end positions from an OSM runway.

    Returns ((threshold_lon, threshold_lat), (far_lon, far_lat), heading_deg).
    The 'threshold' is the first geoPoint and 'far end' is the last one.
    Heading is computed from threshold → far end.
    """
    pts = runway["geoPoints"]
    t_lat, t_lon = pts[0]["latitude"], pts[0]["longitude"]
    f_lat, f_lon = pts[-1]["latitude"], pts[-1]["longitude"]
    heading = _calculate_heading((t_lat, t_lon), (f_lat, f_lon))
    return (t_lon, t_lat), (f_lon, f_lat), heading


def _get_runway_threshold() -> Optional[tuple]:
    """Get the approach runway threshold (lon, lat) from OSM data.

    Returns (lon, lat) tuple or None when no OSM runway data is available.
    """
    rwy = _get_osm_primary_runway()
    if rwy:
        threshold, _, _ = _osm_runway_endpoints(rwy)
        return threshold
    return None


def _get_departure_runway() -> Optional[tuple]:
    """Get the departure runway start (lon, lat) from OSM data.

    Uses the far end of the primary runway (opposite from approach threshold).
    Returns (lon, lat) tuple or None when no OSM runway data is available.
    """
    rwy = _get_osm_primary_runway()
    if rwy:
        _, far_end, _ = _osm_runway_endpoints(rwy)
        return far_end
    return None


def _get_taxi_waypoints_arrival(gate_ref: str) -> List[tuple]:
    """Get taxi route from landing runway exit to assigned gate.

    Uses OSM taxiway graph when available, falls back to hardcoded SFO
    waypoints or generic straight-line path.

    Returns list of (lon, lat) tuples matching existing waypoint format.
    """
    try:
        from app.backend.services.airport_config_service import get_airport_config_service
        service = get_airport_config_service()
        graph = service.taxiway_graph
        if graph:
            runway_exit = _get_runway_threshold()  # (lon, lat) or None
            gate_pos = get_gates().get(gate_ref)
            if runway_exit and gate_pos:
                route = graph.find_route(
                    (runway_exit[1], runway_exit[0]),  # (lat, lon) for graph
                    gate_pos,  # (lat, lon)
                )
                if route and len(route) >= 2:
                    return [(lon, lat) for lat, lon in route]
    except ImportError:
        pass
    except Exception:
        pass

    # Fallback: existing behavior
    center = get_airport_center()
    if abs(center[0] - AIRPORT_CENTER[0]) < 0.01:
        return TAXI_WAYPOINTS_ARRIVAL
    # Generic: straight line from center to gate
    gate_pos = get_gates().get(gate_ref, center)
    return [(center[1], center[0]), (gate_pos[1], gate_pos[0])]


def _get_taxi_waypoints_departure(gate_ref: str) -> List[tuple]:
    """Get taxi route from gate to departure runway.

    Uses OSM taxiway graph when available, falls back to hardcoded SFO
    waypoints or generic straight-line path.

    Returns list of (lon, lat) tuples matching existing waypoint format.
    """
    try:
        from app.backend.services.airport_config_service import get_airport_config_service
        service = get_airport_config_service()
        graph = service.taxiway_graph
        if graph:
            runway_threshold = _get_departure_runway()  # (lon, lat) or None
            gate_pos = get_gates().get(gate_ref)
            if runway_threshold and gate_pos:
                route = graph.find_route(
                    gate_pos,  # (lat, lon)
                    (runway_threshold[1], runway_threshold[0]),  # (lat, lon) for graph
                )
                if route and len(route) >= 2:
                    return [(lon, lat) for lat, lon in route]
    except ImportError:
        pass
    except Exception:
        pass

    # Fallback: existing behavior
    center = get_airport_center()
    if abs(center[0] - AIRPORT_CENTER[0]) < 0.01:
        return TAXI_WAYPOINTS_DEPARTURE
    gate_pos = get_gates().get(gate_ref, center)
    return [(gate_pos[1], gate_pos[0]), (center[1], center[0])]


def _get_pushback_heading(gate_ref: str) -> float:
    """Determine pushback heading from departure route.

    Uses first segment of departure route to compute direction away from gate.
    Falls back to 180° (south) if no route available.
    """
    try:
        from app.backend.services.airport_config_service import get_airport_config_service
        service = get_airport_config_service()
        graph = service.taxiway_graph
        if graph:
            gate_pos = get_gates().get(gate_ref)
            if gate_pos:
                nearest_id = graph.snap_to_nearest_node(gate_pos[0], gate_pos[1])
                if nearest_id is not None:
                    nearest_pos = graph.nodes[nearest_id]
                    # Heading from gate toward nearest taxiway node
                    return _calculate_heading(gate_pos, nearest_pos)
    except (ImportError, Exception):
        pass
    return 180.0  # Default: south


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


# Global state storage
_flight_states: Dict[str, FlightState] = {}
_last_update: float = 0.0

# ============================================================================
# SEPARATION MANAGEMENT
# ============================================================================

@dataclass
class RunwayState:
    """Tracks runway occupancy for separation."""
    occupied_by: Optional[str] = None  # icao24 of aircraft on runway
    last_departure_time: float = 0.0   # Timestamp of last departure
    last_arrival_time: float = 0.0     # Timestamp of last arrival
    approach_queue: List[str] = field(default_factory=list)  # Ordered approach sequence
    departure_queue: List[str] = field(default_factory=list)  # Ordered departure sequence

@dataclass
class GateState:
    """Tracks gate occupancy."""
    occupied_by: Optional[str] = None  # icao24 of aircraft at gate
    available_at: float = 0.0          # When gate becomes available

# Global separation state
_runway_28L: RunwayState = RunwayState()
_runway_28R: RunwayState = RunwayState()
_gate_states: Dict[str, GateState] = {}

def _init_gate_states():
    """Initialize gate states if not done."""
    global _gate_states
    if not _gate_states:
        for gate in get_gates():
            _gate_states[gate] = GateState()

def _reset_gate_states():
    """Reset gate states when gates are reloaded."""
    global _gate_states
    _gate_states = {}
    _init_gate_states()

def _get_wake_category(aircraft_type: str) -> str:
    """Get wake turbulence category for aircraft type."""
    return WAKE_CATEGORY.get(aircraft_type, "LARGE")

def _get_required_separation(lead_type: str, follow_type: str) -> float:
    """Get required separation in degrees between two aircraft types."""
    lead_cat = _get_wake_category(lead_type)
    follow_cat = _get_wake_category(follow_type)
    separation_nm = WAKE_SEPARATION_NM.get(
        (lead_cat, follow_cat),
        DEFAULT_SEPARATION_NM
    )
    return separation_nm * NM_TO_DEG

def _distance_nm(pos1: tuple, pos2: tuple) -> float:
    """Calculate distance in nautical miles between two positions."""
    deg_dist = _distance_between(pos1, pos2)
    return deg_dist / NM_TO_DEG

def _find_aircraft_ahead_on_approach(state: FlightState) -> Optional[FlightState]:
    """Find the aircraft directly ahead on the approach path.

    "Ahead" means closer to the airport center (further along the approach).
    Uses distance-from-center so it works regardless of approach bearing.
    """
    if state.phase not in [FlightPhase.APPROACHING, FlightPhase.LANDING]:
        return None

    center = get_airport_center()
    state_dist_to_center = _distance_between(
        (state.latitude, state.longitude), center
    )

    closest_ahead = None
    closest_gap = float('inf')

    for icao24, other in _flight_states.items():
        if icao24 == state.icao24:
            continue
        if other.phase not in [FlightPhase.APPROACHING, FlightPhase.LANDING]:
            continue

        other_dist_to_center = _distance_between(
            (other.latitude, other.longitude), center
        )
        # Other is ahead if it is closer to the airport
        if other_dist_to_center < state_dist_to_center:
            gap = _distance_between(
                (state.latitude, state.longitude),
                (other.latitude, other.longitude)
            )
            if gap < closest_gap:
                closest_gap = gap
                closest_ahead = other

    return closest_ahead


def _find_last_aircraft_on_approach() -> Optional[FlightState]:
    """Find the aircraft furthest back in the approach queue.

    "Furthest back" means the greatest distance from the airport center.
    Uses distance-from-center so it works regardless of approach bearing.
    """
    center = get_airport_center()
    last_aircraft = None
    max_dist = -1.0

    for icao24, state in _flight_states.items():
        if state.phase not in [FlightPhase.APPROACHING, FlightPhase.LANDING]:
            continue

        dist = _distance_between((state.latitude, state.longitude), center)
        if dist > max_dist:
            max_dist = dist
            last_aircraft = state

    return last_aircraft

def _check_approach_separation(state: FlightState) -> bool:
    """Check if aircraft has sufficient separation from aircraft ahead."""
    ahead = _find_aircraft_ahead_on_approach(state)
    if ahead is None:
        return True  # No one ahead, clear to proceed

    current_dist = _distance_between(
        (state.latitude, state.longitude),
        (ahead.latitude, ahead.longitude)
    )
    required_dist = _get_required_separation(ahead.aircraft_type, state.aircraft_type)

    return current_dist >= required_dist

def _is_runway_clear(runway: str = "28R") -> bool:
    """Check if runway is clear for landing or takeoff."""
    runway_state = _runway_28R if runway == "28R" else _runway_28L
    return runway_state.occupied_by is None

def _occupy_runway(icao24: str, runway: str = "28R"):
    """Mark runway as occupied by aircraft."""
    runway_state = _runway_28R if runway == "28R" else _runway_28L
    runway_state.occupied_by = icao24

def _release_runway(icao24: str, runway: str = "28R"):
    """Release runway when aircraft clears."""
    runway_state = _runway_28R if runway == "28R" else _runway_28L
    if runway_state.occupied_by == icao24:
        runway_state.occupied_by = None
        runway_state.last_arrival_time = time.time()

def _find_available_gate() -> Optional[str]:
    """Find a random available gate (spread across terminals)."""
    _init_gate_states()
    current_time = time.time()

    available = [
        gate for gate, state in _gate_states.items()
        if state.occupied_by is None and current_time >= state.available_at
    ]
    if available:
        return random.choice(available)
    return None

def _occupy_gate(icao24: str, gate: str):
    """Mark gate as occupied."""
    _init_gate_states()
    if gate in _gate_states:
        _gate_states[gate].occupied_by = icao24

def _release_gate(icao24: str, gate: str):
    """Release gate when aircraft departs."""
    _init_gate_states()
    if gate in _gate_states and _gate_states[gate].occupied_by == icao24:
        _gate_states[gate].occupied_by = None
        _gate_states[gate].available_at = time.time() + 60  # 1 min cooldown

def _check_taxi_separation(state: FlightState) -> bool:
    """Check if aircraft has sufficient separation from others on ground."""
    if not state.on_ground:
        return True

    for icao24, other in _flight_states.items():
        if icao24 == state.icao24:
            continue
        if not other.on_ground:
            continue
        if other.phase == FlightPhase.PARKED:
            continue  # Parked aircraft don't block taxi routes

        dist = _distance_between(
            (state.latitude, state.longitude),
            (other.latitude, other.longitude)
        )
        if dist < MIN_TAXI_SEPARATION_DEG:
            return False

    return True

def _count_aircraft_in_phase(phase: FlightPhase) -> int:
    """Count how many aircraft are currently in a specific phase."""
    return sum(1 for s in _flight_states.values() if s.phase == phase)

def _get_approach_queue_position(icao24: str) -> int:
    """Get position in approach queue (0 = first/next to land)."""
    queue = [s for s in _flight_states.values()
             if s.phase in [FlightPhase.APPROACHING, FlightPhase.LANDING]]
    # Sort by distance to airport center (closest first)
    center = get_airport_center()
    queue.sort(key=lambda s: _distance_between((s.latitude, s.longitude), center))

    for i, s in enumerate(queue):
        if s.icao24 == icao24:
            return i
    return len(queue)


def _shortest_angle_diff(from_deg: float, to_deg: float) -> float:
    """Signed shortest rotation from *from_deg* to *to_deg* (both 0-360)."""
    diff = (to_deg - from_deg + 180) % 360 - 180
    return diff


def _calculate_heading(from_pos: tuple, to_pos: tuple) -> float:
    """Calculate heading from one position to another."""
    lat1, lon1 = from_pos
    lat2, lon2 = to_pos

    dlon = lon2 - lon1
    dlat = lat2 - lat1

    # Calculate bearing
    angle = math.atan2(dlon, dlat)
    heading = math.degrees(angle)

    # Normalize to 0-360
    return (heading + 360) % 360


def _distance_between(pos1: tuple, pos2: tuple) -> float:
    """Calculate approximate distance in degrees (simplified)."""
    lat1, lon1 = pos1[:2]
    lat2, lon2 = pos2[:2]
    return math.sqrt((lat2 - lat1) ** 2 + (lon2 - lon1) ** 2)


def _move_toward(current: tuple, target: tuple, speed_factor: float) -> tuple:
    """Move current position toward target by speed factor."""
    lat, lon = current[:2]
    target_lat, target_lon = target[:2]

    dlat = target_lat - lat
    dlon = target_lon - lon
    distance = math.sqrt(dlat ** 2 + dlon ** 2)

    if distance < 0.0001:  # Close enough
        return target[:2]

    # Move by speed factor (degrees per update)
    move_dist = min(speed_factor, distance)
    ratio = move_dist / distance

    new_lat = lat + dlat * ratio
    new_lon = lon + dlon * ratio

    return (new_lat, new_lon)


def _interpolate_altitude(current_alt: float, target_alt: float, rate: float) -> float:
    """Smoothly change altitude toward target."""
    if abs(current_alt - target_alt) < 50:
        return target_alt

    if current_alt < target_alt:
        return current_alt + rate
    else:
        return current_alt - rate


def _get_aircraft_type_for_airline(callsign: str, is_international: bool = False) -> str:
    """Get a random aircraft type based on airline callsign and route type."""
    if callsign and len(callsign) >= 3:
        airline_code = callsign[:3].upper()
        if airline_code in AIRLINE_FLEET:
            fleet = AIRLINE_FLEET[airline_code]
            if is_international:
                # Prefer wide-body for international routes
                wide_body = [a for a in fleet if a in ("B777", "B787", "A330", "A350", "A380", "A345")]
                if wide_body:
                    return random.choice(wide_body)
            return random.choice(fleet)
    if is_international:
        return random.choice(["B777", "B787", "A350", "A330"])
    return random.choice(["A320", "B738", "A321", "B737"])


def _get_airport_coordinates() -> dict:
    """Get the airport coordinates lookup table."""
    from src.ingestion.schedule_generator import AIRPORT_COORDINATES
    return AIRPORT_COORDINATES


def _bearing_from_airport(origin_iata: str) -> float:
    """Compute initial bearing FROM origin airport TO current airport center (degrees, 0=N, 90=E).

    This gives the direction from which an arriving flight should appear.
    """
    coords = _get_airport_coordinates()
    if origin_iata not in coords:
        return random.uniform(0, 360)

    center = get_airport_center()
    lat1, lon1 = math.radians(coords[origin_iata][0]), math.radians(coords[origin_iata][1])
    lat2, lon2 = math.radians(center[0]), math.radians(center[1])

    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360) % 360


def _bearing_to_airport(dest_iata: str) -> float:
    """Compute initial bearing FROM current airport center TO destination airport (degrees, 0=N, 90=E).

    This gives the direction a departing flight should head toward.
    """
    coords = _get_airport_coordinates()
    if dest_iata not in coords:
        return random.uniform(0, 360)

    center = get_airport_center()
    lat1, lon1 = math.radians(center[0]), math.radians(center[1])
    lat2, lon2 = math.radians(coords[dest_iata][0]), math.radians(coords[dest_iata][1])

    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360) % 360


def _point_on_circle(center_lat: float, center_lon: float, bearing_deg: float, radius_deg: float) -> tuple:
    """Calculate a point at a given bearing and distance from center.

    Args:
        center_lat, center_lon: Center point in degrees
        bearing_deg: Bearing in degrees (0=N, 90=E)
        radius_deg: Distance in degrees

    Returns:
        (latitude, longitude) tuple
    """
    bearing_rad = math.radians(bearing_deg)
    lat = center_lat + radius_deg * math.cos(bearing_rad)
    # Adjust longitude for latitude (1 degree longitude is shorter at higher latitudes)
    lon = center_lon + radius_deg * math.sin(bearing_rad) / math.cos(math.radians(center_lat))
    return (lat, lon)


def _is_international_airport(iata: str) -> bool:
    """Check if an airport code is in the international list."""
    from src.ingestion.schedule_generator import INTERNATIONAL_AIRPORTS
    return iata in INTERNATIONAL_AIRPORTS


# Country lookup for origin_country field
_AIRPORT_COUNTRY = {
    "SFO": "United States", "LAX": "United States", "ORD": "United States",
    "DFW": "United States", "JFK": "United States", "ATL": "United States",
    "DEN": "United States", "SEA": "United States", "BOS": "United States",
    "PHX": "United States", "LAS": "United States", "MCO": "United States",
    "MIA": "United States", "CLT": "United States", "MSP": "United States",
    "DTW": "United States", "EWR": "United States", "PHL": "United States",
    "IAH": "United States", "SAN": "United States", "PDX": "United States",
    "LHR": "United Kingdom", "CDG": "France", "FRA": "Germany",
    "AMS": "Netherlands", "HKG": "Hong Kong", "NRT": "Japan",
    "SIN": "Singapore", "SYD": "Australia", "DXB": "UAE", "ICN": "South Korea",
    "HND": "Japan",
}


def _get_origin_country(origin_iata: Optional[str]) -> str:
    """Get the country for an airport IATA code."""
    if origin_iata and origin_iata in _AIRPORT_COUNTRY:
        return _AIRPORT_COUNTRY[origin_iata]
    return "United States"


def _pick_random_airport(exclude: Optional[str] = None) -> str:
    """Pick a random airport, excluding the specified one (typically the local airport)."""
    from src.ingestion.schedule_generator import DOMESTIC_AIRPORTS, INTERNATIONAL_AIRPORTS
    if random.random() < 0.7:
        pool = [a for a in DOMESTIC_AIRPORTS if a != exclude] or DOMESTIC_AIRPORTS
    else:
        pool = [a for a in INTERNATIONAL_AIRPORTS if a != exclude] or INTERNATIONAL_AIRPORTS
    return random.choice(pool)


def _pick_random_origin() -> str:
    """Pick a random origin airport for arriving flights (never the local airport)."""
    return _pick_random_airport(exclude=get_current_airport_iata())


def _pick_random_destination() -> str:
    """Pick a random destination airport for departing flights (never the local airport)."""
    return _pick_random_airport(exclude=get_current_airport_iata())


def _create_new_flight(
    icao24: str, callsign: str, phase: FlightPhase,
    origin: Optional[str] = None, destination: Optional[str] = None,
) -> FlightState:
    """Create a new flight in the specified phase with proper separation."""
    is_intl = _is_international_airport(origin or "") or _is_international_airport(destination or "")
    aircraft_type = _get_aircraft_type_for_airline(callsign, is_international=is_intl)

    if phase == FlightPhase.APPROACHING:
        # Start on approach from the origin direction WITH PROPER WAKE TURBULENCE SEPARATION
        base_wp = _get_approach_waypoints(origin)[0]
        center = get_airport_center()

        # Find how many aircraft are already approaching
        approaching_count = _count_aircraft_in_phase(FlightPhase.APPROACHING)
        landing_count = _count_aircraft_in_phase(FlightPhase.LANDING)

        # Limit simultaneous approaches (realistic: max 4-5 in sequence)
        if approaching_count + landing_count >= 4:
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
            alt = last_aircraft.altitude + 500

        # Pre-assign a gate so it shows as INBOUND on the gate status panel
        _init_gate_states()
        pre_gate = _find_available_gate()
        if pre_gate:
            _occupy_gate(icao24, pre_gate)

        return FlightState(
            icao24=icao24,
            callsign=callsign,
            latitude=lat,
            longitude=lon,
            altitude=alt + random.uniform(-200, 200),
            velocity=180 + random.uniform(-10, 10),
            heading=_calculate_heading((lat, lon), center),
            vertical_rate=-800,
            on_ground=False,
            phase=phase,
            aircraft_type=aircraft_type,
            assigned_gate=pre_gate,
            waypoint_index=0,
            origin_airport=origin,
            destination_airport=destination,
        )

    elif phase == FlightPhase.PARKED:
        # Start at a gate (facing the terminal, heading ~180)
        _init_gate_states()

        # Find an available gate
        gate = _find_available_gate()
        if gate is None:
            # All gates occupied - switch to approaching or enroute
            return _create_new_flight(icao24, callsign, FlightPhase.APPROACHING, origin=origin, destination=destination)

        lat, lon = get_gates()[gate]
        _occupy_gate(icao24, gate)

        return FlightState(
            icao24=icao24,
            callsign=callsign,
            latitude=lat,
            longitude=lon,
            altitude=0,
            velocity=0,
            heading=180,  # Facing terminal (south)
            vertical_rate=0,
            on_ground=True,
            phase=phase,
            aircraft_type=aircraft_type,
            assigned_gate=gate,
            time_at_gate=random.uniform(0, 300),  # Random time already parked
            origin_airport=origin,
            destination_airport=destination,
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
            alt = random.uniform(15000, 25000) if is_intl else random.uniform(8000, 15000)
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
            alt = random.uniform(8000, 15000)
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
            alt = random.uniform(8000, 15000)

        return FlightState(
            icao24=icao24,
            callsign=callsign,
            latitude=lat,
            longitude=lon,
            altitude=alt,
            velocity=random.uniform(400, 500),
            heading=heading,
            vertical_rate=random.uniform(-200, 200),
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
        if not _is_runway_clear("28R"):
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
        for other_icao24, other in _flight_states.items():
            if other.on_ground and other.phase in [FlightPhase.TAXI_TO_GATE, FlightPhase.TAXI_TO_RUNWAY]:
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
        approach_wps = _get_approach_waypoints(state.origin_airport)
        if state.waypoint_index < len(approach_wps):
            wp = approach_wps[state.waypoint_index]
            target = (wp[1], wp[0])  # lat, lon
            target_alt = wp[2]

            # CHECK SEPARATION before moving
            has_separation = _check_approach_separation(state)
            queue_pos = _get_approach_queue_position(state.icao24)

            if has_separation:
                # Clear to proceed - move toward waypoint
                speed_factor = 0.002
                # Slow down if close to aircraft ahead
                ahead = _find_aircraft_ahead_on_approach(state)
                if ahead:
                    dist = _distance_nm((state.latitude, state.longitude),
                                       (ahead.latitude, ahead.longitude))
                    req_sep = _get_required_separation(ahead.aircraft_type, state.aircraft_type) / NM_TO_DEG
                    if dist < req_sep * 1.5:  # Within 1.5x required separation
                        speed_factor *= 0.5  # Slow down

                new_pos = _move_toward((state.latitude, state.longitude), target, speed_factor)
                state.latitude, state.longitude = new_pos

                # Descend
                state.altitude = _interpolate_altitude(state.altitude, target_alt, 300 * dt)
                state.velocity = 180 - (state.waypoint_index * 20)  # Slow down on approach
                state.vertical_rate = -800 if state.altitude > target_alt else 0
            else:
                # Too close to aircraft ahead - slow down / hold speed
                state.velocity = max(140, state.velocity - 10 * dt)  # Reduce speed
                state.vertical_rate = -200  # Reduce descent rate

            # Update heading regardless
            state.heading = _calculate_heading((state.latitude, state.longitude), target)

            # Check if reached waypoint
            if _distance_between((state.latitude, state.longitude), target) < 0.003:
                state.waypoint_index += 1
        else:
            # Transition to landing only if runway is clear
            if _is_runway_clear("28R"):
                emit_phase_transition(
                    state.icao24, state.callsign,
                    FlightPhase.APPROACHING.value, FlightPhase.LANDING.value,
                    state.latitude, state.longitude, state.altitude,
                    state.aircraft_type, state.assigned_gate,
                )
                state.phase = FlightPhase.LANDING
                state.waypoint_index = 0
                _occupy_runway(state.icao24, "28R")
            else:
                # Hold - orbit or slow down significantly
                state.velocity = max(130, state.velocity - 5 * dt)
                # Slight orbit pattern
                state.heading = (state.heading + 5 * dt) % 360

    elif state.phase == FlightPhase.LANDING:
        # Final touchdown sequence - land on runway 28R
        # Runway should already be marked as occupied
        runway_touchdown = (RUNWAY_28L_EAST[1], RUNWAY_28L_EAST[0])  # lat, lon
        new_pos = _move_toward((state.latitude, state.longitude), runway_touchdown, 0.002)
        state.latitude, state.longitude = new_pos
        state.altitude = max(0, state.altitude - 500 * dt)
        state.velocity = max(30, state.velocity - 20 * dt)
        state.heading = _calculate_heading(new_pos, runway_touchdown)

        if state.altitude <= 0:
            state.altitude = 0
            state.on_ground = True
            state.vertical_rate = 0
            emit_phase_transition(
                state.icao24, state.callsign,
                FlightPhase.LANDING.value, FlightPhase.TAXI_TO_GATE.value,
                state.latitude, state.longitude, state.altitude,
                state.aircraft_type, state.assigned_gate,
            )
            state.phase = FlightPhase.TAXI_TO_GATE
            state.waypoint_index = 0
            state.taxi_route = None  # Will be computed below
            # Release runway when exiting to taxiway
            _release_runway(state.icao24, "28R")
            # Reuse pre-assigned gate from approach if still held, else find new one
            _init_gate_states()
            pre_gate = state.assigned_gate
            if pre_gate and pre_gate in _gate_states and _gate_states[pre_gate].occupied_by == state.icao24:
                # Keep pre-assigned gate
                emit_gate_event(state.icao24, state.callsign, pre_gate, "assign", state.aircraft_type)
                state.taxi_route = _get_taxi_waypoints_arrival(pre_gate)
            else:
                available_gate = _find_available_gate()
                if available_gate:
                    # Release old pre-assigned gate if it was held
                    if pre_gate and pre_gate in _gate_states and _gate_states[pre_gate].occupied_by == state.icao24:
                        _release_gate(state.icao24, pre_gate)
                    state.assigned_gate = available_gate
                    _occupy_gate(state.icao24, available_gate)
                    emit_gate_event(state.icao24, state.callsign, available_gate, "assign", state.aircraft_type)
                    state.taxi_route = _get_taxi_waypoints_arrival(available_gate)
                else:
                    # All gates occupied - hold position until gate available
                    state.assigned_gate = None
                    state.velocity = 0  # Hold on runway exit
                    return state

    elif state.phase == FlightPhase.TAXI_TO_GATE:
        # Taxi along waypoints to assigned gate WITH SEPARATION

        # First, ensure we have an assigned gate before proceeding
        if state.assigned_gate is None:
            available_gate = _find_available_gate()
            if available_gate:
                state.assigned_gate = available_gate
                _occupy_gate(state.icao24, available_gate)
                state.taxi_route = _get_taxi_waypoints_arrival(available_gate)
            else:
                # No gates available - hold position on taxiway
                state.velocity = 0
                return state

        # Use cached taxi route (dynamic from OSM graph or fallback)
        taxi_wps = state.taxi_route or TAXI_WAYPOINTS_ARRIVAL
        if state.waypoint_index < len(taxi_wps):
            wp = taxi_wps[state.waypoint_index]
            target = (wp[1], wp[0])

            # Check taxi separation before moving
            if _check_taxi_separation(state):
                speed_deg = TAXI_SPEED_STRAIGHT_KTS * _KTS_TO_DEG_PER_SEC * dt
                new_pos = _move_toward((state.latitude, state.longitude), target, speed_deg)
                state.latitude, state.longitude = new_pos
                state.velocity = TAXI_SPEED_STRAIGHT_KTS
            else:
                # Hold position - too close to another aircraft
                state.velocity = 0
                speed_deg = 0

            state.heading = _calculate_heading((state.latitude, state.longitude), target)

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
                    # No gates available - hold position
                    state.velocity = 0
                    return state

            if _check_taxi_separation(state):
                speed_deg = TAXI_SPEED_RAMP_KTS * _KTS_TO_DEG_PER_SEC * dt
                new_pos = _move_toward((state.latitude, state.longitude), target, speed_deg)
                state.latitude, state.longitude = new_pos
                state.velocity = TAXI_SPEED_RAMP_KTS
            else:
                state.velocity = 0
                speed_deg = 0

            state.heading = _calculate_heading((state.latitude, state.longitude), target)

            if _distance_between((state.latitude, state.longitude), target) < max(speed_deg, 0.0003):
                emit_phase_transition(
                    state.icao24, state.callsign,
                    FlightPhase.TAXI_TO_GATE.value, FlightPhase.PARKED.value,
                    state.latitude, state.longitude, state.altitude,
                    state.aircraft_type, state.assigned_gate,
                )
                emit_gate_event(state.icao24, state.callsign, state.assigned_gate, "occupy", state.aircraft_type)
                state.phase = FlightPhase.PARKED
                state.velocity = 0
                state.time_at_gate = 0
                _occupy_gate(state.icao24, state.assigned_gate)

    elif state.phase == FlightPhase.PARKED:
        # Stay at gate for some time, then pushback
        state.velocity = 0
        state.time_at_gate += dt

        # After 5-10 minutes, start pushback
        if state.time_at_gate > random.uniform(300, 600):
            emit_phase_transition(
                state.icao24, state.callsign,
                FlightPhase.PARKED.value, FlightPhase.PUSHBACK.value,
                state.latitude, state.longitude, state.altitude,
                state.aircraft_type, state.assigned_gate,
            )
            state.phase = FlightPhase.PUSHBACK
            state.phase_progress = 0

    elif state.phase == FlightPhase.PUSHBACK:
        # Slow pushback from gate WITH separation check
        # Determine pushback heading from taxiway graph or fallback to south
        pb_heading = _get_pushback_heading(state.assigned_gate) if state.assigned_gate else 180.0
        if _check_taxi_separation(state):
            state.velocity = TAXI_SPEED_PUSHBACK_KTS
            state.phase_progress += dt * 0.1
            # Move in pushback direction (away from terminal toward taxiway)
            pb_rad = math.radians(pb_heading)
            pb_speed_deg = TAXI_SPEED_PUSHBACK_KTS * _KTS_TO_DEG_PER_SEC * dt
            state.latitude += pb_speed_deg * math.cos(pb_rad)
            state.longitude += pb_speed_deg * math.sin(pb_rad)
        else:
            state.velocity = 0  # Hold if blocked

        state.heading = (pb_heading + 180) % 360  # Nose faces opposite of movement

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
            state.phase = FlightPhase.TAXI_TO_RUNWAY
            state.waypoint_index = 0
            state.taxi_route = _get_taxi_waypoints_departure(state.assigned_gate) if state.assigned_gate else None

    elif state.phase == FlightPhase.TAXI_TO_RUNWAY:
        # Taxi to runway WITH separation
        taxi_wps = state.taxi_route or TAXI_WAYPOINTS_DEPARTURE
        if state.waypoint_index < len(taxi_wps):
            wp = taxi_wps[state.waypoint_index]
            target = (wp[1], wp[0])

            if _check_taxi_separation(state):
                speed_deg = TAXI_SPEED_STRAIGHT_KTS * _KTS_TO_DEG_PER_SEC * dt
                new_pos = _move_toward((state.latitude, state.longitude), target, speed_deg)
                state.latitude, state.longitude = new_pos
                state.velocity = TAXI_SPEED_STRAIGHT_KTS
            else:
                state.velocity = 0  # Hold
                speed_deg = 0

            state.heading = _calculate_heading((state.latitude, state.longitude), target)

            if _distance_between((state.latitude, state.longitude), target) < max(speed_deg, 0.0005):
                state.waypoint_index += 1
        else:
            # At runway hold line - check if runway is clear before takeoff
            if _is_runway_clear("28R"):
                emit_phase_transition(
                    state.icao24, state.callsign,
                    FlightPhase.TAXI_TO_RUNWAY.value, FlightPhase.TAKEOFF.value,
                    state.latitude, state.longitude, state.altitude,
                    state.aircraft_type, state.assigned_gate,
                )
                state.phase = FlightPhase.TAKEOFF
                state.heading = 280  # Runway heading
                _occupy_runway(state.icao24, "28R")
            else:
                # Hold short of runway
                state.velocity = 0

    elif state.phase == FlightPhase.TAKEOFF:
        # Accelerate down runway and lift off (runway heading ~280 = west)
        state.velocity = min(state.velocity + 30 * dt, 160)
        state.longitude -= 0.002 * dt  # Move west down runway
        state.heading = 280  # Runway heading

        if state.velocity >= 140:  # Rotation speed
            state.on_ground = False
            state.altitude += 1500 * dt
            state.vertical_rate = 2000

            if state.altitude > 500:
                # Release runway when airborne and clear
                _release_runway(state.icao24, "28R")
                emit_phase_transition(
                    state.icao24, state.callsign,
                    FlightPhase.TAKEOFF.value, FlightPhase.DEPARTING.value,
                    state.latitude, state.longitude, state.altitude,
                    state.aircraft_type, state.assigned_gate,
                )
                state.phase = FlightPhase.DEPARTING
                state.waypoint_index = 0

    elif state.phase == FlightPhase.DEPARTING:
        # Climb out following departure path
        departure_wps = _get_departure_waypoints()
        if state.waypoint_index < len(departure_wps):
            wp = departure_wps[state.waypoint_index]
            target = (wp[1], wp[0])
            target_alt = wp[2]

            new_pos = _move_toward((state.latitude, state.longitude), target, 0.002)
            state.latitude, state.longitude = new_pos
            state.altitude = _interpolate_altitude(state.altitude, target_alt, 500 * dt)
            state.velocity = 200 + state.waypoint_index * 50
            state.vertical_rate = 1500 if state.altitude < target_alt else 0
            state.heading = _calculate_heading(new_pos, target)

            if _distance_between(new_pos, target) < 0.005:
                state.waypoint_index += 1
        else:
            # Switch to enroute — heading toward destination
            emit_phase_transition(
                state.icao24, state.callsign,
                FlightPhase.DEPARTING.value, FlightPhase.ENROUTE.value,
                state.latitude, state.longitude, state.altitude,
                state.aircraft_type, state.assigned_gate,
            )
            state.phase = FlightPhase.ENROUTE
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

        if state.origin_airport and not state.destination_airport:
            # ARRIVING enroute: heading toward airport, transition to approach when close
            target_heading = _calculate_heading(
                (state.latitude, state.longitude), center
            )
            # Gently steer toward target (smooth turns)
            heading_diff = (target_heading - state.heading + 540) % 360 - 180
            state.heading += max(-3, min(3, heading_diff)) * dt
            state.heading = state.heading % 360

            if dist_from_airport < APPROACH_RADIUS_DEG:
                # Close enough — transition to approach
                emit_phase_transition(
                    state.icao24, state.callsign,
                    FlightPhase.ENROUTE.value, FlightPhase.APPROACHING.value,
                    state.latitude, state.longitude, state.altitude,
                    state.aircraft_type, state.assigned_gate,
                )
                state.phase = FlightPhase.APPROACHING
                state.waypoint_index = 0
            elif random.random() < 0.01 * dt and dist_from_airport < 0.35:
                emit_phase_transition(
                    state.icao24, state.callsign,
                    FlightPhase.ENROUTE.value, FlightPhase.APPROACHING.value,
                    state.latitude, state.longitude, state.altitude,
                    state.aircraft_type, state.assigned_gate,
                )
                state.phase = FlightPhase.APPROACHING
                state.waypoint_index = 0

        elif state.destination_airport:
            # DEPARTING enroute: heading away from SFO toward destination
            target_heading = _bearing_to_airport(state.destination_airport)
            heading_diff = (target_heading - state.heading + 540) % 360 - 180
            state.heading += max(-3, min(3, heading_diff)) * dt
            state.heading = state.heading % 360

            # Climb toward cruise altitude
            if state.altitude < 20000:
                state.altitude += 500 * dt
                state.vertical_rate = 1500

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
                state.heading += random.uniform(-1, 1) * dt
                state.heading = state.heading % 360

            if random.random() < 0.005 * dt:
                state.phase = FlightPhase.APPROACHING
                state.waypoint_index = 0

        # Move in current heading direction
        state.latitude += math.cos(math.radians(state.heading)) * 0.001 * dt
        state.longitude += math.sin(math.radians(state.heading)) * 0.001 * dt

    return state


def _get_flight_phase_name(phase: FlightPhase) -> str:
    """Convert flight phase to API-compatible phase name."""
    phase_map = {
        FlightPhase.APPROACHING: "descending",
        FlightPhase.LANDING: "descending",
        FlightPhase.TAXI_TO_GATE: "ground",
        FlightPhase.PARKED: "ground",
        FlightPhase.PUSHBACK: "ground",
        FlightPhase.TAXI_TO_RUNWAY: "ground",
        FlightPhase.TAKEOFF: "climbing",
        FlightPhase.DEPARTING: "climbing",
        FlightPhase.ENROUTE: "cruising",
    }
    return phase_map.get(phase, "ground")


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

    # Initialize flights if needed (fill up to target count)
    if len(_flight_states) < count:
        # Predefined test flights - diversified phases to avoid conflicts
        local_iata = get_current_airport_iata()
        test_flights = [
            ("a12345", "UAL123", FlightPhase.APPROACHING, "ORD", local_iata),
            ("b67890", "DAL456", FlightPhase.ENROUTE, "NRT", local_iata),
            ("c11111", "SWA789", FlightPhase.ENROUTE, "LAX", local_iata),
            ("d22222", "AAL100", FlightPhase.PARKED, "JFK", "DEN"),
            ("e33333", "JBU555", FlightPhase.DEPARTING, local_iata, "BOS"),
        ]

        for icao24, callsign, phase, origin, dest in test_flights:
            if icao24 not in _flight_states:
                _flight_states[icao24] = _create_new_flight(icao24, callsign, phase, origin=origin, destination=dest)

        # Generate additional random flights
        while len(_flight_states) < count:
            icao24 = fake.hexify(text="^^^^^^", upper=False)
            if icao24 in _flight_states:
                continue

            prefix = random.choice(CALLSIGN_PREFIXES)
            flight_num = random.randint(100, 9999)
            callsign = f"{prefix}{flight_num}"

            # Count current phases to balance distribution
            parked_count = _count_aircraft_in_phase(FlightPhase.PARKED)
            approach_count = _count_aircraft_in_phase(FlightPhase.APPROACHING)
            taxi_count = (_count_aircraft_in_phase(FlightPhase.TAXI_TO_GATE) +
                         _count_aircraft_in_phase(FlightPhase.TAXI_TO_RUNWAY))

            max_parked = len(get_gates())
            approach_weight = 0.15 if approach_count < 4 else 0.0
            parked_weight = 0.20 if parked_count < max_parked else 0.0
            taxi_in_weight = 0.05 if taxi_count < 3 else 0.0
            taxi_out_weight = 0.05 if taxi_count < 3 else 0.0

            total_ground = approach_weight + parked_weight + taxi_in_weight + taxi_out_weight
            enroute_weight = 1.0 - total_ground - 0.05

            phase_weights = [
                (FlightPhase.ENROUTE, enroute_weight),
                (FlightPhase.APPROACHING, approach_weight),
                (FlightPhase.PARKED, parked_weight),
                (FlightPhase.TAXI_TO_GATE, taxi_in_weight),
                (FlightPhase.TAXI_TO_RUNWAY, taxi_out_weight),
                (FlightPhase.DEPARTING, 0.05),
            ]

            r = random.random()
            cumulative = 0
            selected_phase = FlightPhase.ENROUTE
            for phase, weight in phase_weights:
                cumulative += weight
                if r <= cumulative:
                    selected_phase = phase
                    break

            # Assign origin/destination based on phase
            origin = None
            dest = None
            is_arriving = selected_phase in (
                FlightPhase.ENROUTE, FlightPhase.APPROACHING,
                FlightPhase.LANDING, FlightPhase.TAXI_TO_GATE,
            )
            is_departing = selected_phase in (
                FlightPhase.PUSHBACK, FlightPhase.TAXI_TO_RUNWAY,
                FlightPhase.TAKEOFF, FlightPhase.DEPARTING,
            )

            local_iata = get_current_airport_iata()
            if is_arriving:
                origin = _pick_random_origin()
                dest = local_iata
            elif is_departing:
                origin = local_iata
                dest = _pick_random_destination()
            elif selected_phase == FlightPhase.PARKED:
                # Parked at local airport: randomly arrived here or about to depart
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

    for icao24, state in list(_flight_states.items())[:count]:
        state_vector = [
            state.icao24,                              # 0: icao24
            state.callsign.ljust(8),                   # 1: callsign
            _get_origin_country(state.origin_airport), # 2: origin_country
            int(current_time) - random.randint(0, 2), # 3: time_position
            int(current_time),                         # 4: last_contact
            state.longitude,                           # 5: longitude
            state.latitude,                            # 6: latitude
            state.altitude * 0.3048,                   # 7: baro_altitude (convert ft to m)
            state.on_ground,                           # 8: on_ground
            state.velocity * 0.514444,                 # 9: velocity (convert kts to m/s)
            state.heading,                             # 10: true_track
            state.vertical_rate * 0.00508,             # 11: vertical_rate (ft/min to m/s)
            None,                                      # 12: sensors
            state.altitude * 0.3048,                   # 13: geo_altitude
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


# Keep the test flights list for backward compatibility
TEST_FLIGHTS_WITH_TRAJECTORY = [
    {"icao24": "a12345", "callsign": "UAL123"},
    {"icao24": "b67890", "callsign": "DAL456"},
    {"icao24": "c11111", "callsign": "SWA789"},
    {"icao24": "d22222", "callsign": "AAL100"},
    {"icao24": "e33333", "callsign": "JBU555"},
]


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

    # Find the flight in our test flights list
    flight_info = None
    for f in TEST_FLIGHTS_WITH_TRAJECTORY:
        if f["icao24"] == icao24:
            flight_info = f
            break

    # If not found, check in the flight states manager
    if flight_info is None and icao24 in _flight_states:
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
        current_heading = 284  # Runway 28L heading
        current_phase = "descending"

    # Determine if aircraft is on ground
    ground_phases = ["ground", "parked", "taxi_to_gate", "taxi_to_runway", "pushback"]
    is_on_ground = current_phase in ground_phases or end_alt < 100

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
    runway_28l_lon, runway_28l_lat = _rwy_threshold[0], _rwy_threshold[1]
    dep_rwy_lon, dep_rwy_lat = _dep_threshold[0], _dep_threshold[1]

    if is_on_ground:
        # Aircraft is on ground - show approach + landing + taxi trajectory
        # Divide trajectory: 55% approach, 10% landing roll, 35% taxi

        # Landing roll direction along actual runway heading
        _rwy_heading = _get_runway_heading()
        if _rwy_heading is None:
            return []
        _rwy_heading_rad = math.radians(_rwy_heading)
        _roll_distance = 0.012  # ~1.3 km roll in degrees
        roll_dlat = _roll_distance * math.cos(_rwy_heading_rad)
        roll_dlon = _roll_distance * math.sin(_rwy_heading_rad) / math.cos(math.radians(runway_28l_lat))

        for i in range(num_points):
            progress = i / (num_points - 1) if num_points > 1 else 0

            if progress < 0.55:
                # APPROACH PHASE: Following ILS glideslope
                approach_progress = progress / 0.55  # 0 to 1

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
                alt = wp1[2] + (wp2[2] - wp1[2]) * wp_frac

                # Calculate heading toward next waypoint
                heading = _calculate_heading((lat, lon), (wp2[1], wp2[0]))

                phase = "approaching" if alt > 500 else "landing"
                velocity = 180 - approach_progress * 50  # Slow from 180 to 130 kts
                vertical_rate = -700 if alt > 100 else -300

            elif progress < 0.65:
                # LANDING ROLL: Decelerating on runway
                roll_progress = (progress - 0.55) / 0.10

                # Move along runway heading
                lat = runway_28l_lat + roll_progress * roll_dlat
                lon = runway_28l_lon + roll_progress * roll_dlon
                alt = 0

                heading = _rwy_heading
                phase = "ground"
                velocity = 130 - roll_progress * 100  # Decelerate to 30 kts
                vertical_rate = 0

            else:
                # TAXI PHASE: Follow taxiway route from runway to current position
                taxi_progress = (progress - 0.65) / 0.35

                # Landing roll endpoint (must match the roll phase above)
                roll_end_lat = runway_28l_lat + roll_dlat
                roll_end_lon = runway_28l_lon + roll_dlon

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

            # Append point for this iteration (inside the for loop)
            timestamp = now - timedelta(seconds=interval_seconds * (num_points - 1 - i))

            # Scale noise by phase and altitude:
            # - Ground taxi: minimal noise to stay on taxiways
            # - Low altitude approach (<1000ft): reduced noise for clean final
            # - High altitude approach: normal noise for realistic radar scatter
            if phase == "ground":
                pos_noise = 0.00005
            elif alt < 500:
                pos_noise = 0.0001
            elif alt < 2000:
                pos_noise = 0.0002
            else:
                pos_noise = 0.0003
            points.append({
                "timestamp": timestamp.isoformat(),
                "icao24": icao24,
                "callsign": callsign,
                "latitude": lat + random.uniform(-pos_noise, pos_noise),
                "longitude": lon + random.uniform(-pos_noise, pos_noise),
                "altitude": max(0, alt + random.uniform(-20, 20)),
                "velocity": max(10, velocity + random.uniform(-3, 3)),
                "heading": heading + random.uniform(-1, 1),
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

        for i in range(num_points):
            progress = i / (num_points - 1) if num_points > 1 else 0

            if progress < 0.15:
                # Takeoff roll and initial climb
                takeoff_progress = progress / 0.15
                wp = _traj_dep_wps[0]
                lat = dep_rwy_lat + takeoff_progress * (wp[1] - dep_rwy_lat)
                lon = dep_rwy_lon + takeoff_progress * (wp[0] - dep_rwy_lon)
                alt = takeoff_progress * wp[2]
                heading = _dep_rwy_heading
                velocity = 100 + takeoff_progress * 100
                vertical_rate = 2000 if takeoff_progress > 0.3 else 0
                phase = "takeoff" if takeoff_progress < 0.5 else "climbing"
            elif progress < 0.50:
                # Climb out following departure waypoints
                climb_progress = (progress - 0.15) / 0.35

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

                heading = _calculate_heading((lat, lon), (wp2[1], wp2[0]))
                velocity = 200 + climb_progress * 100
                vertical_rate = 1500
                phase = "departing"
            else:
                # Turn toward destination and continue climbing
                enroute_progress = (progress - 0.50) / 0.50
                last_wp = _traj_dep_wps[-1]
                start_lat_dep = last_wp[1]
                start_lon_dep = last_wp[0]
                start_alt_dep = last_wp[2]

                # Project toward destination bearing
                dist = enroute_progress * 0.15  # ~10 NM extension
                lat = start_lat_dep + dist * math.cos(math.radians(dest_bearing))
                lon = start_lon_dep + dist * math.sin(math.radians(dest_bearing)) / math.cos(math.radians(start_lat_dep))
                alt = start_alt_dep + enroute_progress * 7000  # Climb to ~15000

                heading = dest_bearing + random.uniform(-2, 2)
                velocity = 300 + enroute_progress * 100
                vertical_rate = 1000 if enroute_progress < 0.7 else 200
                phase = "departing"

            timestamp = now - timedelta(seconds=interval_seconds * (num_points - 1 - i))

            points.append({
                "timestamp": timestamp.isoformat(),
                "icao24": icao24,
                "callsign": callsign,
                "latitude": lat + random.uniform(-0.001, 0.001),
                "longitude": lon + random.uniform(-0.001, 0.001),
                "altitude": max(0, alt + random.uniform(-50, 50)),
                "velocity": max(50, velocity + random.uniform(-5, 5)),
                "heading": heading + random.uniform(-2, 2),
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

        # Determine how far along the approach the aircraft currently is
        # by finding the closest waypoint to the current position.
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
        # Trim waypoints to only those before (or at) the aircraft.
        path_wps = _traj_app_wps2[:best_wp_idx + 1]
        # Append current position as the final target
        path_wps.append((clamped_lon, clamped_lat, final_alt))
        path_count = len(path_wps)

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
            alt = wp1[2] + (wp2[2] - wp1[2]) * wp_frac

            heading = _calculate_heading((lat, lon), (wp2[1], wp2[0]))
            velocity = 350 - progress * 210
            vertical_rate = -1000 if alt > 2000 else (-600 if alt > 500 else -400)
            phase = "approaching" if alt > 500 else "landing"

            timestamp = now - timedelta(seconds=interval_seconds * (num_points - 1 - i))

            points.append({
                "timestamp": timestamp.isoformat(),
                "icao24": icao24,
                "callsign": callsign,
                "latitude": lat + random.uniform(-0.001, 0.001),
                "longitude": lon + random.uniform(-0.001, 0.001),
                "altitude": max(0, alt + random.uniform(-50, 50)),
                "velocity": max(100, velocity + random.uniform(-5, 5)),
                "heading": heading + random.uniform(-2, 2),
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
    global _flight_states, _last_update, _runway_28L, _runway_28R, _gate_states

    cleared_flights = len(_flight_states)
    cleared_gates = len(_gate_states)

    # Clear flight state only — airport center is managed by the activate endpoint
    _flight_states.clear()
    _last_update = 0.0
    _runway_28L = RunwayState()
    _runway_28R = RunwayState()
    _gate_states.clear()

    # Clear event buffers
    with _phase_transition_lock:
        _phase_transition_buffer.clear()
    with _gate_event_lock:
        _gate_event_buffer.clear()
    with _prediction_lock:
        _prediction_buffer.clear()

    return {
        "cleared_flights": cleared_flights,
        "cleared_gates": cleared_gates,
        "status": "reset_complete",
    }

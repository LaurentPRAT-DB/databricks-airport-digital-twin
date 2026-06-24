"""ILS approach, SID departure, and runway geometry procedures.

STAR/SID corridor selection, approach/departure waypoint generation,
OSM runway parsing, and bearing calculations. Extracted from fallback.py.
"""

import logging
import math
import re as _re
from typing import Dict, List, Optional

from src.ingestion._constants import _SID_CORRIDORS, _STAR_CORRIDORS
from src.ingestion._geo import (
    _calculate_heading,
    _distance_between,
    _entry_direction_quadrant,
    _point_on_circle,
    _shortest_angle_diff,
)

logger = logging.getLogger(__name__)


# ── Airport coordinate helpers ──────────────────────────────────────────────

# Cache random bearings for unknown airports so the same origin/destination
# always gets the same approach/departure direction within a session.
_bearing_cache: Dict[str, float] = {}


def _get_airport_coordinates() -> dict:
    """Get the airport coordinates lookup table."""
    from src.ingestion.schedule_generator import AIRPORT_COORDINATES
    return AIRPORT_COORDINATES


def _bearing_from_airport(origin_iata: str) -> float:
    """Compute initial bearing FROM origin airport TO current airport center (degrees, 0=N, 90=E).

    This gives the direction from which an arriving flight should appear.
    """
    from src.ingestion.fallback import get_airport_center

    coords = _get_airport_coordinates()
    if origin_iata not in coords:
        key = f"from_{origin_iata}"
        if key not in _bearing_cache:
            _bearing_cache[key] = (hash(origin_iata) % 360)
        return _bearing_cache[key]

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
    from src.ingestion.fallback import get_airport_center

    coords = _get_airport_coordinates()
    if dest_iata not in coords:
        key = f"to_{dest_iata}"
        if key not in _bearing_cache:
            _bearing_cache[key] = (hash(dest_iata) % 360)
        return _bearing_cache[key]

    center = get_airport_center()
    lat1, lon1 = math.radians(center[0]), math.radians(center[1])
    lat2, lon2 = math.radians(coords[dest_iata][0]), math.radians(coords[dest_iata][1])

    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360) % 360


# ── Caches (cleared on airport switch via reset_approach_caches) ─────────────

_cached_osm_primary_runway: Optional[dict] = None
_osm_primary_runway_resolved: bool = False
_approach_waypoints_cache: Dict[Optional[str], list] = {}


_osm_runway_config_id: Optional[int] = None


def _get_osm_primary_runway() -> Optional[dict]:
    """Get the primary (longest) runway from OSM config data.

    Returns the runway dict with 'geoPoints' [{latitude, longitude}, ...] or None
    if no OSM runway data is available. Result is cached per airport session.

    Includes a staleness guard: if the underlying config dict object changed
    (airport switch happened without proper cache clear), force re-resolve.
    """
    global _cached_osm_primary_runway, _osm_primary_runway_resolved, _osm_runway_config_id
    try:
        from app.backend.services.airport_config_service import get_airport_config_service
        service = get_airport_config_service()
        config = service.get_config()
        current_id = id(config)

        if _osm_primary_runway_resolved and current_id == _osm_runway_config_id:
            return _cached_osm_primary_runway

        if _osm_primary_runway_resolved and current_id != _osm_runway_config_id:
            logger.warning(
                "[DIAG] _get_osm_primary_runway: stale cache — config object changed (prev=%s, now=%s), re-resolving",
                _osm_runway_config_id, current_id,
            )
            _approach_waypoints_cache.clear()

        runways = config.get("osmRunways", [])
        if not runways:
            logger.info("[DIAG] _get_osm_primary_runway: osmRunways empty/missing, config keys=%s", list(config.keys())[:15])
            _cached_osm_primary_runway = None
            _osm_primary_runway_resolved = True
            _osm_runway_config_id = current_id
            return None
        best = max(runways, key=lambda r: len(r.get("geoPoints", [])))
        if len(best.get("geoPoints", [])) < 2:
            logger.warning("[DIAG] _get_osm_primary_runway: best runway has <2 geoPoints: ref=%s, pts=%d", best.get("ref"), len(best.get("geoPoints", [])))
            _cached_osm_primary_runway = None
            _osm_primary_runway_resolved = True
            _osm_runway_config_id = current_id
            return None
        if _cached_osm_primary_runway is None and _approach_waypoints_cache:
            logger.info("[DIAG] _get_osm_primary_runway: first OSM resolve — purging stale fallback waypoints")
            _approach_waypoints_cache.clear()
        logger.info("[DIAG] _get_osm_primary_runway: resolved ref=%s, pts=%d", best.get("ref"), len(best.get("geoPoints", [])))
        _cached_osm_primary_runway = best
        _osm_primary_runway_resolved = True
        _osm_runway_config_id = current_id
        return best
    except Exception as e:
        logger.warning("_get_osm_primary_runway failed: %s", e)
        return None


def _osm_runway_endpoints(runway: dict) -> tuple:
    """Extract threshold and opposite-end positions from an OSM runway.

    Returns ((threshold_lon, threshold_lat), (far_lon, far_lat), heading_deg).

    The 'threshold' is the APPROACH end — aircraft land here, flying in the
    direction of *heading_deg*.  The 'far end' is opposite.

    OSM geoPoints don't guarantee which end comes first, so we use the runway
    ref tag (e.g. "10R/28L") to orient correctly.  The ref encodes two
    designators: the first matches the heading from geoPoint[0]→geoPoint[-1].
    We pick the designator with the HIGHER number as the active arrival
    direction (standard for prevailing-wind operations at most airports).
    If the higher designator corresponds to the reverse direction, we swap
    the endpoints.
    """
    pts = runway["geoPoints"]
    p0_lat, p0_lon = pts[0]["latitude"], pts[0]["longitude"]
    pN_lat, pN_lon = pts[-1]["latitude"], pts[-1]["longitude"]
    raw_heading = _calculate_heading((p0_lat, p0_lon), (pN_lat, pN_lon))

    ref = runway.get("ref") or runway.get("name", "")
    designators = [int(m) for m in _re.findall(r'\d+', ref)]

    need_swap = False
    if len(designators) >= 2:
        active_des = max(designators[0], designators[1])
        active_heading_nominal = active_des * 10
        diff = abs((raw_heading - active_heading_nominal + 180) % 360 - 180)
        if diff >= 90:
            need_swap = True
    else:
        airport_lat = (p0_lat + pN_lat) / 2
        abs_lat = abs(airport_lat)
        if abs_lat < 15:
            expected_heading = 90.0
        elif abs_lat < 30:
            expected_heading = 60.0
        else:
            expected_heading = 270.0
        diff = abs((raw_heading - expected_heading + 180) % 360 - 180)
        if diff >= 90:
            need_swap = True

    if need_swap:
        heading = (raw_heading + 180) % 360
        logger.info("[DIAG] _osm_runway_endpoints: ref=%s raw=%.1f active_des=%s swap=True → heading=%.1f",
                     ref, raw_heading, designators, heading)
        return (pN_lon, pN_lat), (p0_lon, p0_lat), heading
    else:
        logger.info("[DIAG] _osm_runway_endpoints: ref=%s raw=%.1f active_des=%s swap=False → heading=%.1f",
                     ref, raw_heading, designators, raw_heading)
        return (p0_lon, p0_lat), (pN_lon, pN_lat), raw_heading


# ── Runway geometry ─────────────────────────────────────────────────────────


def _get_fallback_runway() -> tuple:
    """Synthesize a fallback runway from the airport center when no OSM data.

    Returns ((threshold_lon, threshold_lat), (far_lon, far_lat), heading, length_ft).
    Places a ~3000m runway centered on the active airport with a heading
    derived from prevailing wind patterns based on latitude.
    """
    from src.ingestion.fallback import get_airport_center

    center = get_airport_center()
    lat, lon = center[0], center[1]
    abs_lat = abs(lat)
    if abs_lat < 15:
        heading = 90.0
    elif abs_lat < 30:
        heading = 60.0
    else:
        heading = 270.0
    half_len_deg = 0.015
    rad = math.radians(heading)
    cos_lat = max(math.cos(math.radians(lat)), 0.01)
    thr_lat = lat - half_len_deg * math.cos(rad)
    thr_lon = lon - half_len_deg * math.sin(rad) / cos_lat
    far_lat = lat + half_len_deg * math.cos(rad)
    far_lon = lon + half_len_deg * math.sin(rad) / cos_lat
    return (thr_lon, thr_lat), (far_lon, far_lat), heading, 9843.0


def _get_runway_threshold() -> Optional[tuple]:
    """Get the approach runway threshold (lon, lat) from OSM data.

    Returns (lon, lat) tuple or None when no OSM runway data is available.
    """
    rwy = _get_osm_primary_runway()
    if rwy:
        threshold, _, _ = _osm_runway_endpoints(rwy)
        return threshold
    return None


def _get_runway_heading() -> Optional[float]:
    """Get the active runway heading from OSM geoPoints.

    Uses OSM-derived heading so the approach trajectory aligns with the
    runway drawn on the map (both come from the same geoPoint data).
    """
    rwy = _get_osm_primary_runway()
    if rwy:
        _, _, heading = _osm_runway_endpoints(rwy)
        logger.info("[DIAG] _get_runway_heading: ref=%s heading=%.1f geoPoints=%d", rwy.get("ref"), heading, len(rwy.get("geoPoints", [])))
        return heading
    logger.debug("[DIAG] _get_runway_heading: no OSM runway, returning None")
    return None


def _get_arrival_runway_name() -> str:
    """Get the arrival runway name from OSM ref tag or fall back to '28R'.

    Derives the runway name dynamically from OSM data instead of hardcoding.
    Uses the same orientation logic as _osm_runway_endpoints: the active
    arrival is the HIGHER-numbered designator (prevailing wind direction).
    """
    rwy = _get_osm_primary_runway()
    if rwy:
        ref = rwy.get("ref") or rwy.get("name", "")
        if ref:
            parts = [p.strip() for p in ref.split("/")]
            designators = [int(m) for m in _re.findall(r'\d+', ref)]
            if len(parts) >= 2 and len(designators) >= 2:
                if designators[1] > designators[0]:
                    return parts[1]
                return parts[0]
            return parts[0]
    return "28R"


# ── Multi-runway arrival distribution ─────────────────────────────────────────

_arrival_runway_assignments: Dict[str, str] = {}
_arrival_runway_counter: int = 0
_override_arrival_runways: List[str] = []


def set_arrival_runways(runways: List[str]) -> None:
    """Set available arrival runways (called by engine from capacity manager)."""
    global _override_arrival_runways
    _override_arrival_runways = list(runways)


def _get_all_arrival_runway_names() -> List[str]:
    """Get all active arrival runway designators from OSM data.

    For airports with parallel runways (e.g. SFO 28L/28R), returns all runways
    whose active designator heading is within 30 degrees of the primary.
    Falls back to single-runway if only one exists.
    """
    if _override_arrival_runways:
        return _override_arrival_runways
    try:
        from app.backend.services.airport_config_service import get_airport_config_service
        service = get_airport_config_service()
        config = service.get_config()
        runways = config.get("osmRunways", [])
        if not runways:
            return [_get_arrival_runway_name()]

        names = []
        primary_heading = None
        for rwy in sorted(runways, key=lambda r: len(r.get("geoPoints", [])), reverse=True):
            if len(rwy.get("geoPoints", [])) < 2:
                continue
            _, _, hdg = _osm_runway_endpoints(rwy)
            ref = rwy.get("ref") or rwy.get("name", "")
            parts = [p.strip() for p in ref.split("/")]
            designators = [int(m) for m in _re.findall(r'\d+', ref)]
            if len(parts) >= 2 and len(designators) >= 2:
                name = parts[1] if designators[1] > designators[0] else parts[0]
            elif parts:
                name = parts[0]
            else:
                continue

            if primary_heading is None:
                primary_heading = hdg
                names.append(name)
            else:
                diff = abs((hdg - primary_heading + 180) % 360 - 180)
                if diff < 30:
                    names.append(name)

        return names if names else [_get_arrival_runway_name()]
    except Exception:
        return [_get_arrival_runway_name()]


def _assign_arrival_runway(icao24: str) -> str:
    """Assign an arrival runway to an aircraft using round-robin distribution."""
    global _arrival_runway_counter
    if icao24 in _arrival_runway_assignments:
        return _arrival_runway_assignments[icao24]

    runways = _get_all_arrival_runway_names()
    assigned = runways[_arrival_runway_counter % len(runways)]
    _arrival_runway_counter += 1
    _arrival_runway_assignments[icao24] = assigned
    return assigned


def _clear_arrival_runway_assignment(icao24: str) -> None:
    """Remove runway assignment when aircraft leaves approach (landed or departed)."""
    _arrival_runway_assignments.pop(icao24, None)


def reset_arrival_runway_state() -> None:
    """Reset multi-runway state (call between simulations)."""
    global _arrival_runway_counter, _override_arrival_runways
    _arrival_runway_assignments.clear()
    _arrival_runway_counter = 0
    _override_arrival_runways = []


def reset_approach_caches() -> None:
    """Clear all approach/departure caches (call on airport switch)."""
    global _cached_osm_primary_runway, _osm_primary_runway_resolved, _osm_runway_config_id
    global _approach_waypoints_cache
    _cached_osm_primary_runway = None
    _osm_primary_runway_resolved = False
    _osm_runway_config_id = None
    _approach_waypoints_cache.clear()


def _get_departure_runway() -> Optional[tuple]:
    """Get the departure runway start (lon, lat) from OSM data.

    Departures use the SAME active runway direction as arrivals (real-world
    standard: both ops into the wind).  The departure start is the threshold
    end of the runway.

    Returns (lon, lat) tuple or None when no OSM runway data is available.
    """
    rwy = _get_osm_primary_runway()
    if rwy:
        threshold, _, _ = _osm_runway_endpoints(rwy)
        return threshold
    return None


def _get_takeoff_runway_geometry() -> tuple:
    """Get departure runway geometry for takeoff: start position, end position, heading, length.

    Uses OSM data when available, falls back to SFO Runway 28R constants.
    Returns ((start_lat, start_lon), (end_lat, end_lon), heading_deg, length_ft).
    """
    rwy = _get_osm_primary_runway()
    if rwy:
        threshold, far_end, hdg = _osm_runway_endpoints(rwy)
        start = (threshold[1], threshold[0])
        end = (far_end[1], far_end[0])
        dep_heading = hdg
        dlat = end[0] - start[0]
        dlon = end[1] - start[1]
        dist_m = math.sqrt((dlat * 111000)**2 + (dlon * 111000 * math.cos(math.radians(start[0])))**2)
        length_ft = dist_m / 0.3048
        return start, end, dep_heading, max(length_ft, 3000)

    fb_thr, fb_far, fb_hdg, fb_len = _get_fallback_runway()
    start = (fb_thr[1], fb_thr[0])
    end = (fb_far[1], fb_far[0])
    return start, end, fb_hdg, fb_len


def _get_arrival_runway_endpoints() -> tuple:
    """Get arrival runway (threshold, far_end) as (lon, lat) tuples.

    Uses OSM data when available, falls back to airport-center-based runway.
    """
    rwy = _get_osm_primary_runway()
    if rwy:
        threshold, far_end, _ = _osm_runway_endpoints(rwy)
        return threshold, far_end
    fb = _get_fallback_runway()
    return fb[0], fb[1]


def _get_departure_runway_endpoints() -> tuple:
    """Get departure runway (threshold, far_end) as (lon, lat) tuples.

    Uses OSM data when available, falls back to airport-center-based runway.
    """
    rwy = _get_osm_primary_runway()
    if rwy:
        threshold, far_end, _ = _osm_runway_endpoints(rwy)
        return threshold, far_end
    fb = _get_fallback_runway()
    return fb[0], fb[1]


# ── STAR approach waypoints ─────────────────────────────────────────────────


def _get_star_name(origin_iata: Optional[str] = None) -> str:
    """Return the STAR procedure name for the given origin airport."""
    if origin_iata is None:
        return _STAR_CORRIDORS["WEST"]["name"]
    coords = _get_airport_coordinates()
    if origin_iata not in coords:
        return _STAR_CORRIDORS["EAST"]["name"]
    rwy_heading = _get_runway_heading() or _get_fallback_runway()[2]
    approach_course = (rwy_heading + 180) % 360
    bearing_to_apt = _bearing_from_airport(origin_iata)
    entry_dir = (bearing_to_apt + 180) % 360
    quadrant = _entry_direction_quadrant(entry_dir)
    return _STAR_CORRIDORS[quadrant]["name"]


def _get_approach_waypoints(origin_iata: Optional[str] = None) -> list:
    """Get approach waypoints aligned with the actual runway.

    When *origin_iata* is provided the approach starts from the bearing of that
    airport, so a flight from SEA appears from the north, one from LAX from the
    south, etc.

    Uses directional STAR corridors: 4 distinct approach paths (North, East,
    South, West) based on origin bearing quadrant, all converging to the same
    final approach fix on the ILS.
    """
    if origin_iata in _approach_waypoints_cache:
        return _approach_waypoints_cache[origin_iata]

    rwy_threshold = _get_runway_threshold()
    rwy_heading = _get_runway_heading()
    _used_osm = rwy_threshold is not None and rwy_heading is not None
    if not _used_osm:
        fb_thr, _, fb_hdg, _ = _get_fallback_runway()
        rwy_threshold = fb_thr
        rwy_heading = fb_hdg

    rwy_lat, rwy_lon = rwy_threshold[1], rwy_threshold[0]
    approach_course = (rwy_heading + 180) % 360

    if origin_iata is None:
        entry_dir = approach_course
    else:
        bearing_to_apt = _bearing_from_airport(origin_iata)
        entry_dir = (bearing_to_apt + 180) % 360

    logger.info(
        "[DIAG] _get_approach_waypoints: origin=%s rwy_heading=%.1f approach_course=%.1f "
        "entry_dir=%.1f used_osm=%s rwy_threshold=(%.4f,%.4f)",
        origin_iata, rwy_heading, approach_course, entry_dir, _used_osm,
        rwy_lon, rwy_lat,
    )

    # Phase 2: Final approach — centered on RUNWAY THRESHOLD
    final_distances = [0.10, 0.075, 0.05, 0.035, 0.02, 0.01, 0.0]
    final_altitudes = [1600, 1300, 950, 630, 320, 160, 50]
    final_wps = []
    for dist, alt in zip(final_distances, final_altitudes):
        if dist == 0.0:
            final_wps.append((rwy_lon, rwy_lat, alt))
        else:
            pt = _point_on_circle(rwy_lat, rwy_lon, approach_course, dist)
            final_wps.append((pt[1], pt[0], alt))

    # STAR corridor with transition — distinct per quadrant
    quadrant = _entry_direction_quadrant(entry_dir)
    corridor = _STAR_CORRIDORS[quadrant]
    anchor_lat, anchor_lon = final_wps[0][1], final_wps[0][0]

    angle_diff = _shortest_angle_diff(entry_dir, approach_course)

    if abs(angle_diff) > 90:
        turn_sign = 1.0 if angle_diff > 0 else -1.0
        lateral_offset = 0.12
        perp_bearing = (approach_course + turn_sign * 90) % 360
        downwind_bearing = (approach_course + 180) % 360

        downwind_wps = []
        downwind_dists = [0.35, 0.25, 0.15]
        downwind_alts = [8000, 5500, 4000]
        for dist, alt in zip(downwind_dists, downwind_alts):
            pt = _point_on_circle(anchor_lat, anchor_lon, downwind_bearing, dist)
            pt_offset = _point_on_circle(pt[0], pt[1], perp_bearing, lateral_offset)
            downwind_wps.append((pt_offset[1], pt_offset[0], alt))

        turn_angle = _shortest_angle_diff(perp_bearing, approach_course)
        n_turn = 4
        turn_dists = [0.10, 0.08, 0.065, 0.055]
        turn_alts = [3200, 2800, 2400, 2100]
        turn_wps = []
        for k in range(n_turn):
            frac = (k + 1) / (n_turn + 1)
            brg = (perp_bearing + turn_angle * frac) % 360
            lat_frac = 1.0 - frac
            pt = _point_on_circle(anchor_lat, anchor_lon, brg, turn_dists[k])
            turn_wps.append((pt[1], pt[0], turn_alts[k]))

        return downwind_wps + turn_wps + final_wps

    # Small angle (≤90°): gentle curve using interpolation
    transition_dists = corridor.get("transition_distances", [])
    transition_alts = corridor.get("transition_altitudes", [])
    transition_wps = []
    for i, (dist, alt) in enumerate(zip(transition_dists, transition_alts)):
        blend = 0.25 * (i / max(1, len(transition_dists) - 1))
        bearing = entry_dir + angle_diff * blend
        pt = _point_on_circle(anchor_lat, anchor_lon, bearing, dist)
        transition_wps.append((pt[1], pt[0], alt))

    base_distances = corridor["base_distances"]
    base_altitudes = corridor["base_altitudes"]
    base_wps = []
    for i, (dist, alt) in enumerate(zip(base_distances, base_altitudes)):
        blend = 0.25 + 0.75 * (i / max(1, len(base_distances) - 1))
        bearing = entry_dir + angle_diff * blend
        pt = _point_on_circle(anchor_lat, anchor_lon, bearing, dist)
        base_wps.append((pt[1], pt[0], alt))

    result = transition_wps + base_wps + final_wps
    if _used_osm:
        _approach_waypoints_cache[origin_iata] = result
    return result


# ── SID departure waypoints ─────────────────────────────────────────────────


def _get_sid_name(destination_iata: Optional[str] = None) -> str:
    """Return the SID procedure name for the given destination airport."""
    if destination_iata is None:
        return _SID_CORRIDORS["WEST"]["name"]
    coords = _get_airport_coordinates()
    if destination_iata not in coords:
        return _SID_CORRIDORS["EAST"]["name"]
    rwy_heading = _get_runway_heading() or _get_fallback_runway()[2]
    exit_dir = _bearing_to_airport(destination_iata)
    quadrant = _entry_direction_quadrant(exit_dir)
    return _SID_CORRIDORS[quadrant]["name"]


def _get_departure_waypoints(destination_iata: Optional[str] = None) -> list:
    """Get departure waypoints aligned with the actual runway.

    Uses directional SID corridors: 4 distinct departure paths (North, East,
    South, West) based on destination bearing quadrant.
    """
    rwy_threshold = _get_runway_threshold()
    rwy_heading = _get_runway_heading()
    if rwy_threshold is None or rwy_heading is None:
        fb_thr, _, fb_hdg, _ = _get_fallback_runway()
        rwy_threshold = fb_thr
        rwy_heading = fb_hdg

    dep_lat, dep_lon = rwy_threshold[1], rwy_threshold[0]

    if destination_iata is None:
        exit_dir = rwy_heading
    else:
        exit_dir = _bearing_to_airport(destination_iata)

    quadrant = _entry_direction_quadrant(exit_dir)
    corridor = _SID_CORRIDORS[quadrant]
    turn_start = corridor["turn_start_wp"]
    turn_end = corridor["turn_end_wp"]
    initial_offset = corridor["initial_turn_offset"]

    distances = [0.02, 0.035, 0.05, 0.075, 0.10, 0.135, 0.17, 0.21, 0.25]
    altitudes = [200, 600, 1000, 1800, 2500, 3500, 5000, 6500, 8000]

    initial_heading = (rwy_heading + initial_offset) % 360

    waypoints = []
    for i, (dist, alt) in enumerate(zip(distances, altitudes)):
        if i < turn_start:
            bearing = initial_heading
        elif i < turn_end:
            blend = (i - turn_start) / max(1, turn_end - turn_start)
            bearing = initial_heading + _shortest_angle_diff(initial_heading, exit_dir) * blend
        else:
            bearing = exit_dir
        pt = _point_on_circle(dep_lat, dep_lon, bearing, dist)
        waypoints.append((pt[1], pt[0], alt))
    return waypoints


# ── Waypoint snapping ───────────────────────────────────────────────────────


def _snap_to_nearest_waypoint(state) -> int:
    """Find the best approach waypoint to resume descent from.

    After a go-around, the aircraft re-enters approach from a holding area.
    The selected waypoint must satisfy:
    1. Ahead of the aircraft (within ±90° of heading) — prevents flying backward
    2. Altitude at or above current altitude — prevents arriving over the
       runway at high altitude (the aircraft must descend along the path,
       not skip to a low-altitude waypoint it's already above)
    3. After a go-around, prefer early waypoints (first half of the approach)
       to ensure a full, stable approach instead of cutting to final.

    Falls back to first waypoint with sufficient altitude if no forward match.
    """
    approach_wps = _get_approach_waypoints(state.origin_airport)
    if not approach_wps:
        return 0

    is_go_around = getattr(state, 'go_around_count', 0) > 0
    half_idx = len(approach_wps) // 2

    best_idx = 0
    best_dist = float('inf')
    best_fwd_idx = -1
    best_fwd_dist = float('inf')
    first_above_idx = -1

    for wi, wp in enumerate(approach_wps):
        wp_lat, wp_lon = wp[1], wp[0]
        wp_alt = wp[2] if len(wp) > 2 else 0
        d = _distance_between((state.latitude, state.longitude), (wp_lat, wp_lon))

        if d < best_dist:
            best_dist = d
            best_idx = wi

        if first_above_idx < 0 and wp_alt >= state.altitude:
            first_above_idx = wi

        bearing = _calculate_heading(
            (state.latitude, state.longitude), (wp_lat, wp_lon)
        )
        angle_diff = abs((bearing - state.heading + 540) % 360 - 180)
        if angle_diff <= 90 and wp_alt >= state.altitude - 500 and d < best_fwd_dist:
            if is_go_around and wi > half_idx:
                continue
            best_fwd_dist = d
            best_fwd_idx = wi

    if best_fwd_idx >= 0:
        return best_fwd_idx
    if first_above_idx >= 0:
        return first_above_idx
    return best_idx

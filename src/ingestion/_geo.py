"""Pure geometry and math functions for the synthetic flight system.

All functions in this module are stateless — they depend only on their
arguments and imported constants. Extracted from fallback.py.
"""

import math

from src.ingestion._constants import NM_TO_DEG


def _sanitize_float(val: float, default: float = 0.0) -> float:
    """Replace NaN/Inf with a safe default."""
    if val is None or math.isnan(val) or math.isinf(val):
        return default
    return val


def _shortest_angle_diff(from_deg: float, to_deg: float) -> float:
    """Signed shortest rotation from *from_deg* to *to_deg* (both 0-360)."""
    diff = (to_deg - from_deg + 180) % 360 - 180
    return diff


def _calculate_heading(from_pos: tuple, to_pos: tuple) -> float:
    """Calculate heading (bearing) from one position to another.

    Uses latitude-corrected longitude to account for Mercator distortion.
    """
    lat1, lon1 = from_pos
    lat2, lon2 = to_pos

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    avg_lat = math.radians((lat1 + lat2) / 2)
    dlon_corrected = dlon * math.cos(avg_lat)

    angle = math.atan2(dlon_corrected, dlat)
    heading = math.degrees(angle)

    return (heading + 360) % 360


def _smooth_heading(current: float, target: float, max_rate_per_sec: float, dt: float) -> float:
    """Limit heading change to a realistic turn rate.

    Standard rate turn = 3 deg/s.  Returns new heading in [0, 360).
    """
    diff = (target - current + 540) % 360 - 180  # shortest signed angle
    max_change = max_rate_per_sec * dt
    clamped = max(-max_change, min(max_change, diff))
    return (current + clamped) % 360


def _distance_between(pos1: tuple, pos2: tuple) -> float:
    """Calculate approximate distance in degrees (simplified)."""
    lat1, lon1 = pos1[:2]
    lat2, lon2 = pos2[:2]
    return math.sqrt((lat2 - lat1) ** 2 + (lon2 - lon1) ** 2)


def _distance_nm(pos1: tuple, pos2: tuple) -> float:
    """Calculate distance in nautical miles between two positions."""
    deg_dist = _distance_between(pos1, pos2)
    return deg_dist / NM_TO_DEG


def _distance_meters(pos1: tuple, pos2: tuple) -> float:
    """Approximate distance in meters between two (lat, lon) points."""
    lat1, lon1 = pos1[:2]
    lat2, lon2 = pos2[:2]
    dlat = (lat2 - lat1) * 111_000
    dlon = (lon2 - lon1) * 111_000 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.sqrt(dlat ** 2 + dlon ** 2)


def _move_toward(current: tuple, target: tuple, speed_factor: float) -> tuple:
    """Move current position toward target by speed factor."""
    lat, lon = current[:2]
    target_lat, target_lon = target[:2]

    dlat = target_lat - lat
    dlon = target_lon - lon
    distance = math.sqrt(dlat ** 2 + dlon ** 2)

    if distance < 0.0001:  # Close enough
        return target[:2]

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


def _point_on_circle(center_lat: float, center_lon: float, bearing_deg: float, radius_deg: float) -> tuple:
    """Calculate a point at a given bearing and distance from center.

    Returns:
        (latitude, longitude) tuple
    """
    bearing_rad = math.radians(bearing_deg)
    lat = center_lat + radius_deg * math.cos(bearing_rad)
    lon = center_lon + radius_deg * math.sin(bearing_rad) / math.cos(math.radians(center_lat))
    return (lat, lon)


def _offset_position_by_heading(lat: float, lon: float, heading_deg: float, distance_meters: float) -> tuple:
    """Move a point away from a heading direction (pull aircraft back from gate).

    The aircraft nose points at heading_deg (toward the terminal). This function
    moves the position in the *opposite* direction so the nose reaches the gate
    point while the fuselage sits on the apron.
    """
    reverse_bearing_rad = math.radians((heading_deg + 180) % 360)
    distance_deg = distance_meters / 111_000
    new_lat = lat + distance_deg * math.cos(reverse_bearing_rad)
    new_lon = lon + distance_deg * math.sin(reverse_bearing_rad) / math.cos(math.radians(lat))
    return (new_lat, new_lon)


def _entry_direction_quadrant(entry_dir: float) -> str:
    """Classify an entry bearing into a directional quadrant for STAR/SID naming."""
    normalized = entry_dir % 360
    if normalized >= 315 or normalized < 45:
        return "NORTH"
    elif normalized < 135:
        return "EAST"
    elif normalized < 225:
        return "SOUTH"
    else:
        return "WEST"


def _point_to_segment_distance_m(px: float, py: float,
                                  ax: float, ay: float,
                                  bx: float, by: float) -> float:
    """Minimum distance in meters from point (px, py) to segment (ax,ay)-(bx,by).

    All coordinates in (lat, lon) degrees.
    """
    cos_lat = math.cos(math.radians(px))
    pxm = (px - ax) * 111_000
    pym = (py - ay) * 111_000 * cos_lat
    bxm = (bx - ax) * 111_000
    bym = (by - ay) * 111_000 * cos_lat

    seg_len_sq = bxm * bxm + bym * bym
    if seg_len_sq < 1e-10:
        return math.sqrt(pxm * pxm + pym * pym)

    t = max(0.0, min(1.0, (pxm * bxm + pym * bym) / seg_len_sq))
    proj_x = t * bxm
    proj_y = t * bym
    return math.sqrt((pxm - proj_x) ** 2 + (pym - proj_y) ** 2)


def _point_in_polygon(lat: float, lon: float, polygon: list[dict]) -> bool:
    """Ray-casting point-in-polygon test.

    Polygon vertices are dicts with 'latitude' and 'longitude' keys.
    """
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        yi = float(polygon[i].get("latitude", 0))
        xi = float(polygon[i].get("longitude", 0))
        yj = float(polygon[j].get("latitude", 0))
        xj = float(polygon[j].get("longitude", 0))
        if ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / (yj - yi) + xi
        ):
            inside = not inside
        j = i
    return inside

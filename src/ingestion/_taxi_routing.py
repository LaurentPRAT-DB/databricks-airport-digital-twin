"""Taxi routing and gate geometry functions. Extracted from fallback.py."""

import math
import logging
from datetime import datetime, timezone
from typing import List

from src.ingestion._constants import AIRCRAFT_HALF_LENGTH_M, _DEFAULT_HALF_LENGTH_M
from src.ingestion._geo import _point_to_segment_distance_m, _point_in_polygon, _distance_between, _calculate_heading
from src.simulation.diagnostics import diag_log

logger = logging.getLogger(__name__)


def _compute_taxiway_line(
    runway_threshold: tuple,  # (lon, lat) — arrival runway touchdown end
    runway_far_end: tuple,    # (lon, lat) — opposite end of same runway
    terminal_center: tuple,   # (lat, lon)
    offset_fraction: float = 0.25,
) -> tuple:
    """Compute a taxiway reference line parallel to the runway, offset toward terminals.

    Returns (taxiway_start, taxiway_end) as (lon, lat) tuples — the two endpoints
    of a synthetic taxiway centerline between the runway and terminal area.
    """
    rwy_lon1, rwy_lat1 = runway_threshold
    rwy_lon2, rwy_lat2 = runway_far_end
    term_lat, term_lon = terminal_center

    # Offset the runway line toward the terminal by offset_fraction of the
    # perpendicular distance from runway midpoint to terminal center
    rwy_mid_lon = (rwy_lon1 + rwy_lon2) / 2
    rwy_mid_lat = (rwy_lat1 + rwy_lat2) / 2

    # Vector from runway midpoint to terminal center
    dlat = term_lat - rwy_mid_lat
    dlon = term_lon - rwy_mid_lon

    # Taxiway line = runway shifted toward terminal by offset_fraction
    tw_lat1 = rwy_lat1 + dlat * offset_fraction
    tw_lon1 = rwy_lon1 + dlon * offset_fraction
    tw_lat2 = rwy_lat2 + dlat * offset_fraction
    tw_lon2 = rwy_lon2 + dlon * offset_fraction

    return (tw_lon1, tw_lat1), (tw_lon2, tw_lat2)


def _project_onto_line(
    point_lon: float, point_lat: float,
    line_start: tuple, line_end: tuple,
) -> tuple:
    """Project a point onto a line segment, returning the closest point (lon, lat).

    Uses parametric projection clamped to [0, 1].
    """
    x1, y1 = line_start  # (lon, lat)
    x2, y2 = line_end
    dx, dy = x2 - x1, y2 - y1
    len_sq = dx * dx + dy * dy
    if len_sq < 1e-15:
        return line_start
    t = max(0.0, min(1.0, ((point_lon - x1) * dx + (point_lat - y1) * dy) / len_sq))
    return (x1 + t * dx, y1 + t * dy)


def _t_on_line(point_lon: float, point_lat: float,
               line_start: tuple, line_end: tuple) -> float:
    """Compute parametric position t of a point's projection onto a line.

    Returns t in [0, 1] where 0 = line_start, 1 = line_end.
    """
    x1, y1 = line_start
    x2, y2 = line_end
    dx, dy = x2 - x1, y2 - y1
    len_sq = dx * dx + dy * dy
    if len_sq < 1e-15:
        return 0.0
    return max(0.0, min(1.0, ((point_lon - x1) * dx + (point_lat - y1) * dy) / len_sq))


def _generate_taxi_spine(
    line_start: tuple, line_end: tuple, num_points: int = 6,
) -> List[tuple]:
    """Generate evenly-spaced waypoints along a taxiway line.

    Returns list of (lon, lat, t) from line_start to line_end,
    where t is the parametric position [0, 1].
    """
    pts = []
    for i in range(num_points):
        t = i / max(1, num_points - 1)
        lon = line_start[0] + t * (line_end[0] - line_start[0])
        lat = line_start[1] + t * (line_end[1] - line_start[1])
        pts.append((lon, lat, t))
    return pts


def _smooth_sharp_turns(
    route: List[tuple],
    max_turn_angle: float = 60.0,
    arc_radius_deg: float = 0.0004,
    arc_points: int = 3,
) -> List[tuple]:
    """Insert rounding waypoints at sharp turns in a taxi route.

    For each consecutive triplet (A, B, C) where the turn angle at B exceeds
    max_turn_angle, replaces B with arc points that smoothly round the corner.
    """
    if len(route) < 3:
        return list(route)

    result = [route[0]]
    for i in range(1, len(route) - 1):
        a_lon, a_lat = route[i - 1][:2]
        b_lon, b_lat = route[i][:2]
        c_lon, c_lat = route[i + 1][:2]

        ba_lon, ba_lat = a_lon - b_lon, a_lat - b_lat
        bc_lon, bc_lat = c_lon - b_lon, c_lat - b_lat
        len_ba = math.sqrt(ba_lon ** 2 + ba_lat ** 2)
        len_bc = math.sqrt(bc_lon ** 2 + bc_lat ** 2)

        if len_ba < 1e-10 or len_bc < 1e-10:
            result.append(route[i])
            continue

        ba_lon /= len_ba
        ba_lat /= len_ba
        bc_lon /= len_bc
        bc_lat /= len_bc

        dot = ba_lon * bc_lon + ba_lat * bc_lat
        dot = max(-1.0, min(1.0, dot))
        interior_angle = math.degrees(math.acos(dot))
        turn_angle = 180.0 - interior_angle

        if turn_angle <= max_turn_angle:
            result.append(route[i])
            continue

        radius = min(arc_radius_deg, len_ba * 0.4, len_bc * 0.4)
        entry = (b_lon + ba_lon * radius, b_lat + ba_lat * radius)
        exit_pt = (b_lon + bc_lon * radius, b_lat + bc_lat * radius)

        for j in range(arc_points):
            t = (j + 1) / (arc_points + 1)
            lon = entry[0] * (1 - t) + exit_pt[0] * t
            lat = entry[1] * (1 - t) + exit_pt[1] * t
            result.append((lon, lat))

    result.append(route[-1])
    return result


def get_terminal_center() -> tuple:
    """Get the terminal center (lat, lon).

    Returns the module-level TERMINAL_CENTER which is updated by
    apply_airport_offset for non-SFO airports.
    """
    from src.ingestion.fallback import TERMINAL_CENTER
    return TERMINAL_CENTER


def _build_arrival_taxi_route(
    gate_pos: tuple,          # (lat, lon)
    start_pos: tuple = None,  # (lon, lat) aircraft rollout position
) -> List[tuple]:
    """Build a geometry-derived arrival taxi route: rollout → taxiway → gate.

    Computes a parallel taxiway line between the arrival runway and
    terminal area, then routes along it to the gate's perpendicular
    projection point before turning into the ramp.

    Returns list of (lon, lat) waypoints.
    """
    from src.ingestion._approach_departure import _get_arrival_runway_endpoints
    arr_rwy, arr_far = _get_arrival_runway_endpoints()

    term = get_terminal_center()  # (lat, lon)
    tw_start, tw_end = _compute_taxiway_line(arr_rwy, arr_far, term, offset_fraction=0.25)

    gate_lat, gate_lon = gate_pos

    # Parametric positions along the taxiway line (0 = tw_start, 1 = tw_end)
    t_exit = _t_on_line(
        start_pos[0] if start_pos else arr_rwy[0],
        start_pos[1] if start_pos else arr_rwy[1],
        tw_start, tw_end,
    )
    t_turnoff = _t_on_line(gate_lon, gate_lat, tw_start, tw_end)
    t_lo, t_hi = min(t_exit, t_turnoff), max(t_exit, t_turnoff)
    walk_reversed = t_exit > t_turnoff

    # Project points onto the taxiway line
    exit_point = _project_onto_line(
        start_pos[0] if start_pos else arr_rwy[0],
        start_pos[1] if start_pos else arr_rwy[1],
        tw_start, tw_end,
    )
    turnoff = _project_onto_line(gate_lon, gate_lat, tw_start, tw_end)

    # Build route: rollout exit → along taxiway → turn-off → ramp → gate
    route: List[tuple] = []
    if start_pos:
        route.append(start_pos)
    route.append(exit_point)

    # Add spine points between exit and turnoff (in correct direction)
    spine = _generate_taxi_spine(tw_start, tw_end, num_points=8)
    spine_between = [(lon, lat) for lon, lat, t in spine if t_lo < t < t_hi]
    if walk_reversed:
        spine_between.reverse()
    route.extend(spine_between)

    # Turnoff → apron perimeter → gate (routes around the terminal building)
    route.append(turnoff)
    term_lat, term_lon = term
    gate_dlat = gate_lat - term_lat
    gate_dlon = gate_lon - term_lon
    gate_dist = math.sqrt(gate_dlat ** 2 + gate_dlon ** 2)
    if gate_dist > 1e-8:
        # Apron radius = distance from terminal center to taxiway line midpoint.
        # This keeps the apron waypoint outside the building footprint.
        tw_mid_lon = (tw_start[0] + tw_end[0]) / 2
        tw_mid_lat = (tw_start[1] + tw_end[1]) / 2
        apron_radius = math.sqrt((term_lat - tw_mid_lat) ** 2 + (term_lon - tw_mid_lon) ** 2)
        apron_lat = term_lat + (gate_dlat / gate_dist) * apron_radius
        apron_lon = term_lon + (gate_dlon / gate_dist) * apron_radius
        route.append((apron_lon, apron_lat))
    route.append((gate_lon, gate_lat))

    return _smooth_sharp_turns(route)


def _build_departure_taxi_route(
    gate_pos: tuple,  # (lat, lon)
) -> List[tuple]:
    """Build a geometry-derived departure taxi route: gate → taxiway → runway.

    Computes a parallel taxiway line between the departure runway and
    terminal area, then routes from the gate to the runway hold line.

    Returns list of (lon, lat) waypoints.
    """
    from src.ingestion._approach_departure import _get_departure_runway_endpoints
    dep_rwy, dep_far = _get_departure_runway_endpoints()

    term = get_terminal_center()  # (lat, lon)
    tw_start, tw_end = _compute_taxiway_line(dep_rwy, dep_far, term, offset_fraction=0.25)

    gate_lat, gate_lon = gate_pos

    # Parametric positions along the taxiway line
    t_merge = _t_on_line(gate_lon, gate_lat, tw_start, tw_end)
    t_hold = _t_on_line(dep_rwy[0], dep_rwy[1], tw_start, tw_end)
    t_lo, t_hi = min(t_merge, t_hold), max(t_merge, t_hold)
    walk_reversed = t_merge > t_hold

    merge = _project_onto_line(gate_lon, gate_lat, tw_start, tw_end)
    hold_line = _project_onto_line(dep_rwy[0], dep_rwy[1], tw_start, tw_end)

    route: List[tuple] = []

    # Gate → apron perimeter → merge onto taxiway (routes around terminal)
    route.append((gate_lon, gate_lat))
    term_lat, term_lon = term
    gate_dlat = gate_lat - term_lat
    gate_dlon = gate_lon - term_lon
    gate_dist = math.sqrt(gate_dlat ** 2 + gate_dlon ** 2)
    if gate_dist > 1e-8:
        tw_mid_lon = (tw_start[0] + tw_end[0]) / 2
        tw_mid_lat = (tw_start[1] + tw_end[1]) / 2
        apron_radius = math.sqrt((term_lat - tw_mid_lat) ** 2 + (term_lon - tw_mid_lon) ** 2)
        apron_lat = term_lat + (gate_dlat / gate_dist) * apron_radius
        apron_lon = term_lon + (gate_dlon / gate_dist) * apron_radius
        route.append((apron_lon, apron_lat))
    route.append(merge)

    # Spine points between merge and hold line (in correct direction)
    spine = _generate_taxi_spine(tw_start, tw_end, num_points=8)
    spine_between = [(lon, lat) for lon, lat, t in spine if t_lo < t < t_hi]
    if walk_reversed:
        spine_between.reverse()
    route.extend(spine_between)

    # Hold line → runway threshold
    route.append(hold_line)
    route.append(dep_rwy)

    return _smooth_sharp_turns(route)


def _get_taxi_waypoints_arrival(gate_ref: str, start_pos: tuple = None) -> List[tuple]:
    """Get taxi route from landing rollout position to assigned gate.

    Uses OSM taxiway graph when available, falls back to hardcoded SFO
    waypoints or apron-aware routing for non-SFO airports.

    Args:
        gate_ref: Gate identifier string.
        start_pos: Aircraft's current (lon, lat) position at rollout end.
            When provided, routes from this position (snapped to nearest
            taxiway node) instead of the runway threshold — avoids
            backtracking along the runway.

    Returns list of (lon, lat) tuples matching existing waypoint format.
    """
    try:
        from app.backend.services.airport_config_service import get_airport_config_service
        from src.ingestion._approach_departure import _get_runway_threshold
        service = get_airport_config_service()
        graph = service.taxiway_graph
        if graph:
            if start_pos:
                route_start = (start_pos[1], start_pos[0])  # (lat, lon) for graph
            else:
                runway_exit = _get_runway_threshold()  # (lon, lat) or None
                route_start = (runway_exit[1], runway_exit[0]) if runway_exit else None
            from src.ingestion.fallback import get_gates
            gate_pos = get_gates().get(gate_ref)
            if route_start and gate_pos:
                route = graph.find_route(
                    route_start,
                    gate_pos,  # (lat, lon)
                )
                if route and len(route) >= 2:
                    diag_log("TAXI_ROUTE_GRAPH", datetime.now(timezone.utc),
                             gate=gate_ref, points=len(route), direction="arrival")
                    return [(lon, lat) for lat, lon in route]
                else:
                    logger.warning("TAXI graph find_route returned %s for gate %s (start=%s, gate_pos=%s, nodes=%d)",
                                   route, gate_ref, route_start, gate_pos, len(graph.nodes))
            else:
                logger.warning("TAXI graph skip: route_start=%s gate_pos=%s gate_ref=%s",
                               route_start, gate_pos, gate_ref)
        else:
            logger.debug("TAXI graph not available yet")
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Taxiway graph arrival route failed for gate %s: %s", gate_ref, e)

    # Geometry-derived routing: works for any airport using runway/gate/terminal positions
    from src.ingestion.fallback import get_gates
    gate_pos = get_gates().get(gate_ref)
    if gate_ref and gate_pos:
        route = _build_arrival_taxi_route(gate_pos, start_pos=start_pos)
        if route and len(route) >= 2:
            diag_log("TAXI_ROUTE_GEOMETRY", datetime.now(timezone.utc),
                     gate=gate_ref, points=len(route), direction="arrival")
            return route

    # Last resort: generic waypoints (offset for non-SFO airports)
    diag_log("TAXI_ROUTE_STATIC", datetime.now(timezone.utc),
             gate=gate_ref, direction="arrival")
    from src.ingestion.fallback import TAXI_WAYPOINTS_ARRIVAL
    return list(TAXI_WAYPOINTS_ARRIVAL)


def _get_taxi_waypoints_departure(gate_ref: str) -> List[tuple]:
    """Get taxi route from gate to departure runway.

    Uses OSM taxiway graph when available, falls back to hardcoded SFO
    waypoints or apron-aware routing for non-SFO airports.

    Returns list of (lon, lat) tuples matching existing waypoint format.
    """
    try:
        from app.backend.services.airport_config_service import get_airport_config_service
        from src.ingestion._approach_departure import _get_departure_runway
        service = get_airport_config_service()
        graph = service.taxiway_graph
        if graph:
            runway_threshold = _get_departure_runway()  # (lon, lat) or None
            from src.ingestion.fallback import get_gates
            gate_pos = get_gates().get(gate_ref)
            if runway_threshold and gate_pos:
                route = graph.find_route(
                    gate_pos,  # (lat, lon)
                    (runway_threshold[1], runway_threshold[0]),  # (lat, lon) for graph
                )
                if route and len(route) >= 2:
                    diag_log("TAXI_ROUTE_GRAPH", datetime.now(timezone.utc),
                             gate=gate_ref, points=len(route), direction="departure")
                    return [(lon, lat) for lat, lon in route]
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Taxiway graph departure route failed for gate %s: %s", gate_ref, e)

    # Geometry-derived routing: works for any airport using runway/gate/terminal positions
    from src.ingestion.fallback import get_gates
    gate_pos = get_gates().get(gate_ref)
    if gate_ref and gate_pos:
        route = _build_departure_taxi_route(gate_pos)
        if route and len(route) >= 2:
            diag_log("TAXI_ROUTE_GEOMETRY", datetime.now(timezone.utc),
                     gate=gate_ref, points=len(route), direction="departure")
            return route

    # Last resort: generic waypoints (offset for non-SFO airports)
    diag_log("TAXI_ROUTE_STATIC", datetime.now(timezone.utc),
             gate=gate_ref, direction="departure")
    from src.ingestion.fallback import TAXI_WAYPOINTS_DEPARTURE
    return list(TAXI_WAYPOINTS_DEPARTURE)


def _get_pushback_heading(gate_ref: str) -> float:
    """Determine pushback direction: move straight away from the terminal.

    The parked heading points the nose toward the terminal wall.
    Pushback simply reverses that direction so the aircraft backs away
    from the building.  This is more reliable than using the departure
    taxi route's first segment, which can point along or even into
    adjacent building walls for gates on concourse fingers.

    Falls back to 180° (south) if no gate or terminal data.
    """
    from src.ingestion.fallback import get_gates
    gate_pos = get_gates().get(gate_ref)
    if gate_pos:
        parked_hdg = _get_parked_heading(gate_pos[0], gate_pos[1])
        # Pushback direction = opposite of nose heading (back away from terminal)
        return (parked_hdg + 180) % 360
    return 180.0  # Default: south


def _is_gate_inside_terminal(gate_lat: float, gate_lon: float) -> bool:
    """Check if a gate position is inside any terminal polygon.

    Uses OSM terminal geoPolygon data. Returns False if no terminal data.
    """
    try:
        from app.backend.services.airport_config_service import get_airport_config_service
        service = get_airport_config_service()
        config = service.get_config()
        terminals = config.get("terminals", [])
        for terminal in terminals:
            geo_polygon = terminal.get("geoPolygon", [])
            if len(geo_polygon) < 3:
                continue
            if _point_in_polygon(gate_lat, gate_lon, geo_polygon):
                return True
        return False
    except Exception:
        return False


def _gate_to_terminal_edge_distance_m(gate_lat: float, gate_lon: float) -> float | None:
    """Compute distance in meters from a gate to the nearest terminal polygon edge.

    Uses OSM terminal geoPolygon data. Returns None if no terminal data is available.
    """
    try:
        from app.backend.services.airport_config_service import get_airport_config_service
        service = get_airport_config_service()
        config = service.get_config()
        terminals = config.get("terminals", [])
        if not terminals:
            return None

        best_dist = float('inf')
        for terminal in terminals:
            geo_polygon = terminal.get("geoPolygon", [])
            if len(geo_polygon) < 3:
                continue
            # Check distance to each edge of the terminal polygon
            for i in range(len(geo_polygon)):
                j = (i + 1) % len(geo_polygon)
                a_lat = float(geo_polygon[i].get("latitude", 0))
                a_lon = float(geo_polygon[i].get("longitude", 0))
                b_lat = float(geo_polygon[j].get("latitude", 0))
                b_lon = float(geo_polygon[j].get("longitude", 0))
                d = _point_to_segment_distance_m(gate_lat, gate_lon,
                                                  a_lat, a_lon, b_lat, b_lon)
                if d < best_dist:
                    best_dist = d
        return best_dist if best_dist < float('inf') else None
    except Exception:
        return None


def _compute_gate_standoff(gate_lat: float, gate_lon: float,
                           heading_deg: float, aircraft_type: str) -> float:
    """Compute how far to offset a parked aircraft from the gate node.

    Uses the airport's OSM terminal polygon to determine the gate-to-terminal
    edge distance, combined with the aircraft's full length, so different
    airports and aircraft types produce different standoff distances.

    The Leaflet marker is anchored at the aircraft CENTER. To place the NOSE
    at the gate/jetbridge point while keeping the fuselage on the apron, we
    must offset the center back by at least half the fuselage length.

    When the gate node is on or inside the terminal wall (edge_dist ≈ 0,
    typical for OSM jetbridge nodes), we also add a jetbridge gap so the
    nose clears the building entirely.

    Args:
        gate_lat, gate_lon: Gate/jetbridge position from OSM
        heading_deg: Aircraft nose heading (toward terminal)
        aircraft_type: ICAO type designator (e.g. "A320", "B777")

    Returns:
        Standoff distance in meters (applied in the reverse heading direction)
    """
    half_length = AIRCRAFT_HALF_LENGTH_M.get(aircraft_type, _DEFAULT_HALF_LENGTH_M)
    # Jetbridge gap: distance from terminal wall to aircraft nose tip
    jetbridge_gap_m = 5.0

    edge_dist = _gate_to_terminal_edge_distance_m(gate_lat, gate_lon)
    if edge_dist is None:
        # No OSM terminal data — offset by half-length + jetbridge gap
        return half_length + jetbridge_gap_m

    required = half_length + jetbridge_gap_m
    inside = _is_gate_inside_terminal(gate_lat, gate_lon)

    if inside:
        # Gate is inside terminal building (common for jetbridge nodes) —
        # must push out past the wall first, then clear jetbridge + half-length.
        return required + edge_dist
    else:
        # Gate is outside the building — already has some clearance from wall.
        if edge_dist >= required:
            # Remote stand far from building — no offset needed.
            return 0.0
        return required - edge_dist


def _get_parked_heading(gate_lat: float, gate_lon: float) -> float:
    """Compute heading for a parked aircraft: nose perpendicular to nearest terminal edge.

    This ensures the aircraft wings are parallel to the terminal building face,
    matching real-world gate orientation. Falls back to airport center if no
    terminal data is available, or 180 deg as a last resort.

    Normal disambiguation uses a point-in-polygon probe instead of centroid
    direction, which is robust for irregular/L-shaped terminals and concourse
    fingers where the centroid can be far from the local gate area.

    If the gate is inside a terminal polygon, only edges from that terminal are
    considered (prevents picking an edge from an adjacent terminal building).
    """
    try:
        from app.backend.services.airport_config_service import get_airport_config_service
        service = get_airport_config_service()
        config = service.get_config()
        terminals = config.get("terminals", [])
        if not terminals:
            raise ValueError("no terminals")

        # Collect terminal polygons (parsed once)
        parsed_terminals: list[tuple[list[dict], list[tuple]]] = []
        containing_idx = -1
        for idx, terminal in enumerate(terminals):
            geo_polygon = terminal.get("geoPolygon", [])
            if not geo_polygon or len(geo_polygon) < 3:
                continue
            verts = [
                (float(p.get("latitude", 0)), float(p.get("longitude", 0)))
                for p in geo_polygon
            ]
            parsed_terminals.append((geo_polygon, verts))
            if _point_in_polygon(gate_lat, gate_lon, geo_polygon):
                containing_idx = len(parsed_terminals) - 1

        # If gate is inside a terminal, restrict search to that terminal's edges
        if containing_idx >= 0:
            search_set = [parsed_terminals[containing_idx]]
        else:
            search_set = parsed_terminals

        best_dist = float('inf')
        best_edge = None   # (a_lat, a_lon, b_lat, b_lon)
        best_poly = None   # geo_polygon list for the owning terminal

        for geo_polygon, verts in search_set:
            n = len(verts)
            for i in range(n):
                j = (i + 1) % n
                a_lat, a_lon = verts[i]
                b_lat, b_lon = verts[j]
                d = _point_to_segment_distance_m(
                    gate_lat, gate_lon, a_lat, a_lon, b_lat, b_lon
                )
                if d < best_dist:
                    best_dist = d
                    best_edge = (a_lat, a_lon, b_lat, b_lon)
                    best_poly = geo_polygon

        if best_edge and best_poly:
            a_lat, a_lon, b_lat, b_lon = best_edge
            cos_lat = math.cos(math.radians(gate_lat))
            dx = (b_lon - a_lon) * 111_000 * cos_lat
            dy = (b_lat - a_lat) * 111_000
            edge_len = math.sqrt(dx * dx + dy * dy)
            if edge_len > 0.01:
                # Two candidate normals perpendicular to the edge
                n1x, n1y = -dy / edge_len, dx / edge_len
                # Probe: move 1m from edge midpoint in n1 direction — if
                # that lands inside the polygon, n1 is the inward normal
                mid_lat = (a_lat + b_lat) / 2
                mid_lon = (a_lon + b_lon) / 2
                probe_m = 1.0  # 1 meter
                probe_deg = probe_m / 111_000
                probe_lat = mid_lat + n1y * probe_deg
                probe_lon = mid_lon + n1x * probe_deg / max(cos_lat, 0.01)
                if _point_in_polygon(probe_lat, probe_lon, best_poly):
                    # n1 points inward — use it (nose toward building)
                    nx, ny = n1x, n1y
                else:
                    # n1 points outward — flip to inward
                    nx, ny = -n1x, -n1y
                heading = round(math.degrees(math.atan2(nx, ny)) % 360, 1)
                return heading
    except Exception:
        pass
    # Fallback: face toward airport center
    from src.ingestion.fallback import get_airport_center
    center = get_airport_center()
    if _distance_between((gate_lat, gate_lon), center) > 0.0001:
        return _calculate_heading((gate_lat, gate_lon), center)
    return 180.0

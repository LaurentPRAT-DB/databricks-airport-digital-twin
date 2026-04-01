"""Taxiway routing graph for realistic aircraft ground movement.

Builds a navigable graph from OSM taxiway/runway segments and gate positions,
then uses Dijkstra's algorithm to find shortest paths between any two points
(e.g., runway exit → gate, gate → runway threshold).
"""

import heapq
import math
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Earth radius in meters
_EARTH_RADIUS_M = 6_371_000

# Penalty multiplier for edges whose midpoint falls inside a terminal building.
# Makes Dijkstra strongly prefer routes that go around buildings.
_BUILDING_PENALTY = 1000.0


def _point_in_polygon(lat: float, lon: float, polygon: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test. polygon is list of (lat, lon)."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        yi, xi = polygon[i]
        yj, xj = polygon[j]
        if ((yi > lon) != (yj > lon)) and (lat < (xj - xi) * (lon - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in meters between two (lat, lon) points."""
    rlat1, rlon1 = math.radians(lat1), math.radians(lon1)
    rlat2, rlon2 = math.radians(lat2), math.radians(lon2)
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


class TaxiwayGraph:
    """Builds a navigable graph from OSM taxiway segments.

    Nodes are (lat, lon) positions; edges are weighted by haversine distance
    in meters. Nearby endpoints from different taxiway segments are merged
    (snapped) to create intersections.
    """

    def __init__(self, snap_tolerance: float = 0.0002):
        """
        Args:
            snap_tolerance: degrees (~22m) for merging nearby endpoints.
        """
        self.nodes: dict[int, tuple[float, float]] = {}  # node_id → (lat, lon)
        self.edges: dict[int, list[tuple[int, float]]] = {}  # node_id → [(neighbor, dist)]
        self._snap_tolerance = snap_tolerance
        self._next_id = 0
        # Spatial grid index for O(1) nearest-neighbor lookups.
        # Grid cell size equals snap tolerance so only 3x3 neighborhood
        # needs checking for snap queries.
        self._grid: dict[tuple[int, int], list[int]] = {}
        self._grid_inv = snap_tolerance  # 1/cell_size precomputed below
        if snap_tolerance > 0:
            self._grid_inv = 1.0 / snap_tolerance

    def _grid_key(self, lat: float, lon: float) -> tuple[int, int]:
        """Map a (lat, lon) to a grid cell."""
        return (int(lat * self._grid_inv), int(lon * self._grid_inv))

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def build_from_config(self, config: dict) -> None:
        """Build graph from airport config dict (osmTaxiways, osmRunways, gates).

        Steps:
        1. Add all taxiway segments as edges (consecutive geoPoints pairs).
        2. Add runway endpoints connected to nearest taxiway node.
        3. Connect each gate to nearest taxiway node.

        Snapping merges endpoints within ``snap_tolerance`` degrees into a
        single node, creating junctions where taxiways intersect.
        """
        self.nodes.clear()
        self.edges.clear()
        self._grid.clear()
        self._next_id = 0

        # 1. Taxiway segments
        for taxiway in config.get("osmTaxiways", []):
            geo_points = taxiway.get("geoPoints", [])
            if len(geo_points) < 2:
                continue
            prev_id = self._get_or_create_node(
                geo_points[0]["latitude"], geo_points[0]["longitude"]
            )
            for pt in geo_points[1:]:
                cur_id = self._get_or_create_node(pt["latitude"], pt["longitude"])
                if cur_id != prev_id:
                    self._add_edge(prev_id, cur_id)
                prev_id = cur_id

        # 2. Runway endpoints → nearest taxiway node
        for runway in config.get("osmRunways", []):
            geo_points = runway.get("geoPoints", [])
            if len(geo_points) < 2:
                continue
            for pt in (geo_points[0], geo_points[-1]):
                rwy_id = self._get_or_create_node(pt["latitude"], pt["longitude"])
                nearest = self._find_nearest_node(
                    pt["latitude"], pt["longitude"], exclude={rwy_id}
                )
                if nearest is not None:
                    self._add_edge(rwy_id, nearest)

        # 3. Apron perimeter nodes → connect to nearest taxiway node
        # Aprons are the paved areas around terminals; adding their perimeter
        # points gives Dijkstra more paths around buildings.
        for apron in config.get("osmAprons", []):
            geo_polygon = apron.get("geoPolygon", [])
            if len(geo_polygon) < 3:
                continue
            prev_apron_id = None
            for pt in geo_polygon:
                lat = pt.get("latitude")
                lon = pt.get("longitude")
                if lat is None or lon is None:
                    continue
                apron_node_id = self._get_or_create_node(float(lat), float(lon))
                # Chain consecutive apron perimeter points
                if prev_apron_id is not None and prev_apron_id != apron_node_id:
                    self._add_edge(prev_apron_id, apron_node_id)
                prev_apron_id = apron_node_id
                # Connect apron node to nearest existing taxiway node
                nearest = self._find_nearest_node(
                    float(lat), float(lon), exclude={apron_node_id}
                )
                if nearest is not None:
                    dist = _haversine_m(
                        float(lat), float(lon),
                        self.nodes[nearest][0], self.nodes[nearest][1],
                    )
                    # Only connect if within 300m — avoid long phantom edges
                    if dist < 300:
                        self._add_edge(apron_node_id, nearest)

        # 4. Gate nodes → multiple nearby taxiway nodes
        # Connect to several neighbors so Dijkstra can route around buildings.
        for gate in config.get("gates", []):
            geo = gate.get("geo", {})
            lat = geo.get("latitude")
            lon = geo.get("longitude")
            if lat is None or lon is None:
                continue
            gate_id = self._get_or_create_node(float(lat), float(lon))
            for nid in self._find_nearest_nodes(
                float(lat), float(lon), k=5, max_dist_m=500, exclude={gate_id}
            ):
                self._add_edge(gate_id, nid)

        # 5. Penalize edges that pass through terminal buildings
        building_polygons = self._extract_building_polygons(config)
        if building_polygons:
            penalized = self._penalize_building_edges(building_polygons)
            if penalized:
                logger.info("Penalized %d edges crossing terminal buildings", penalized)

        logger.info(
            "TaxiwayGraph built: %d nodes, %d edges",
            len(self.nodes),
            sum(len(v) for v in self.edges.values()) // 2,
        )

    # ------------------------------------------------------------------
    # Building avoidance
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_building_polygons(config: dict) -> list[list[tuple[float, float]]]:
        """Extract terminal building polygons from config as [(lat, lon), ...]."""
        polygons = []
        for terminal in config.get("terminals", []):
            geo_poly = terminal.get("geoPolygon", [])
            if len(geo_poly) < 3:
                continue
            pts = []
            for pt in geo_poly:
                lat = pt.get("latitude")
                lon = pt.get("longitude")
                if lat is not None and lon is not None:
                    pts.append((float(lat), float(lon)))
            if len(pts) >= 3:
                polygons.append(pts)
        return polygons

    def _penalize_building_edges(self, polygons: list[list[tuple[float, float]]]) -> int:
        """Multiply weight of edges that pass through a terminal building.

        Samples 5 points along each edge (not just midpoint) to catch edges
        that clip building corners.  Returns count of penalized edges.
        """
        penalized = 0
        samples = [0.2, 0.35, 0.5, 0.65, 0.8]
        # Pre-compute bounding boxes for fast rejection
        poly_bounds = []
        for poly in polygons:
            lats = [p[0] for p in poly]
            lons = [p[1] for p in poly]
            poly_bounds.append((min(lats), max(lats), min(lons), max(lons)))
        for node_id, neighbors in self.edges.items():
            lat_a, lon_a = self.nodes[node_id]
            new_neighbors = []
            for neighbor_id, weight in neighbors:
                lat_b, lon_b = self.nodes[neighbor_id]
                hits_building = False
                for t in samples:
                    s_lat = lat_a + t * (lat_b - lat_a)
                    s_lon = lon_a + t * (lon_b - lon_a)
                    for idx, poly in enumerate(polygons):
                        min_lat, max_lat, min_lon, max_lon = poly_bounds[idx]
                        if s_lat < min_lat or s_lat > max_lat or s_lon < min_lon or s_lon > max_lon:
                            continue  # fast bbox reject
                        if _point_in_polygon(s_lat, s_lon, poly):
                            hits_building = True
                            break
                    if hits_building:
                        break
                if hits_building:
                    weight *= _BUILDING_PENALTY
                    penalized += 1
                new_neighbors.append((neighbor_id, weight))
            self.edges[node_id] = new_neighbors
        # Each edge counted twice (bidirectional)
        return penalized // 2

    # ------------------------------------------------------------------
    # Pathfinding
    # ------------------------------------------------------------------

    def find_route(
        self, start: tuple[float, float], end: tuple[float, float]
    ) -> list[tuple[float, float]]:
        """Dijkstra shortest path between two (lat, lon) positions.

        Snaps *start* and *end* to the nearest graph node first.
        Returns list of (lat, lon) waypoints including start and end,
        or an empty list if no path exists.
        """
        if not self.nodes:
            return []

        src = self.snap_to_nearest_node(start[0], start[1])
        dst = self.snap_to_nearest_node(end[0], end[1])
        if src is None or dst is None:
            return []
        if src == dst:
            return [self.nodes[src]]

        # Dijkstra
        dist: dict[int, float] = {src: 0.0}
        prev: dict[int, Optional[int]] = {src: None}
        heap: list[tuple[float, int]] = [(0.0, src)]

        while heap:
            d, u = heapq.heappop(heap)
            if u == dst:
                break
            if d > dist.get(u, float("inf")):
                continue
            for v, w in self.edges.get(u, []):
                nd = d + w
                if nd < dist.get(v, float("inf")):
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(heap, (nd, v))

        if dst not in prev:
            return []

        # Reconstruct
        path: list[int] = []
        cur: Optional[int] = dst
        while cur is not None:
            path.append(cur)
            cur = prev[cur]
        path.reverse()
        return [self.nodes[n] for n in path]

    def route_length_meters(self, route: list[tuple[float, float]]) -> float:
        """Total haversine distance of a route in meters."""
        total = 0.0
        for i in range(len(route) - 1):
            total += _haversine_m(route[i][0], route[i][1], route[i + 1][0], route[i + 1][1])
        return total

    # ------------------------------------------------------------------
    # Node helpers
    # ------------------------------------------------------------------

    def snap_to_nearest_node(self, lat: float, lon: float) -> Optional[int]:
        """Find closest graph node to a geo position. Returns node id or None.

        Searches in expanding grid rings until a candidate is found,
        then checks one more ring to confirm no closer node exists.
        Falls back to full scan for very sparse graphs.
        """
        if not self.nodes:
            return None
        key = self._grid_key(lat, lon)
        best_id = None
        best_dist = float("inf")
        found_radius = -1
        # Search expanding rings: 0, 1, 2, ...
        for radius in range(50):
            for di in range(-radius, radius + 1):
                for dj in range(-radius, radius + 1):
                    if radius > 0 and abs(di) != radius and abs(dj) != radius:
                        continue  # skip interior (already checked)
                    for nid in self._grid.get((key[0] + di, key[1] + dj), ()):
                        nlat, nlon = self.nodes[nid]
                        d = (nlat - lat) ** 2 + (nlon - lon) ** 2
                        if d < best_dist:
                            best_dist = d
                            best_id = nid
                            found_radius = radius
            # Once we've checked one full ring beyond the best find, stop
            if best_id is not None and radius > found_radius:
                return best_id
        return best_id

    def _get_or_create_node(self, lat: float, lon: float) -> int:
        """Return existing node within snap_tolerance, or create a new one.

        Uses a grid-based spatial index so lookup is O(1) amortized
        instead of O(n) linear scan over all nodes.
        """
        tol = self._snap_tolerance
        key = self._grid_key(lat, lon)
        # Check 3x3 grid neighborhood
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for nid in self._grid.get((key[0] + di, key[1] + dj), ()):
                    nlat, nlon = self.nodes[nid]
                    if abs(nlat - lat) < tol and abs(nlon - lon) < tol:
                        return nid
        nid = self._next_id
        self._next_id += 1
        self.nodes[nid] = (lat, lon)
        self.edges.setdefault(nid, [])
        self._grid.setdefault(key, []).append(nid)
        return nid

    def _add_edge(self, a: int, b: int) -> None:
        """Add a bidirectional edge weighted by haversine distance."""
        lat_a, lon_a = self.nodes[a]
        lat_b, lon_b = self.nodes[b]
        d = _haversine_m(lat_a, lon_a, lat_b, lon_b)
        self.edges.setdefault(a, []).append((b, d))
        self.edges.setdefault(b, []).append((a, d))

    def _find_nearest_node(
        self, lat: float, lon: float, exclude: set[int] | None = None
    ) -> Optional[int]:
        """Find closest graph node, optionally excluding a set of ids.

        Uses expanding grid search for efficiency.
        """
        exclude = exclude or set()
        key = self._grid_key(lat, lon)
        best_id = None
        best_dist = float("inf")
        found_radius = -1
        for radius in range(50):
            for di in range(-radius, radius + 1):
                for dj in range(-radius, radius + 1):
                    if radius > 0 and abs(di) != radius and abs(dj) != radius:
                        continue
                    for nid in self._grid.get((key[0] + di, key[1] + dj), ()):
                        if nid in exclude:
                            continue
                        nlat, nlon = self.nodes[nid]
                        d = (nlat - lat) ** 2 + (nlon - lon) ** 2
                        if d < best_dist:
                            best_dist = d
                            best_id = nid
                            found_radius = radius
            if best_id is not None and radius > found_radius:
                return best_id
        return best_id

    def _find_nearest_nodes(
        self, lat: float, lon: float, k: int = 5,
        max_dist_m: float = 500, exclude: set[int] | None = None,
    ) -> list[int]:
        """Return up to *k* nearest nodes within *max_dist_m* meters.

        Pre-filters using degree-distance approximation before computing
        expensive haversine only on nearby candidates.
        """
        exclude = exclude or set()
        # Approximate degree-distance filter (1 degree ≈ 111km)
        deg_radius = max_dist_m / 111_000.0
        key = self._grid_key(lat, lon)
        grid_radius = int(deg_radius * self._grid_inv) + 2
        candidates: list[tuple[float, int]] = []
        for di in range(-grid_radius, grid_radius + 1):
            for dj in range(-grid_radius, grid_radius + 1):
                for nid in self._grid.get((key[0] + di, key[1] + dj), ()):
                    if nid in exclude:
                        continue
                    nlat, nlon = self.nodes[nid]
                    # Fast degree-distance pre-filter
                    if abs(nlat - lat) > deg_radius or abs(nlon - lon) > deg_radius:
                        continue
                    d = _haversine_m(lat, lon, nlat, nlon)
                    if d <= max_dist_m:
                        candidates.append((d, nid))
        candidates.sort()
        return [nid for _, nid in candidates[:k]]

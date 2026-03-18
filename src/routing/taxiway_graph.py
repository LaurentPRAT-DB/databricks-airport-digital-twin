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

        # 4. Gate nodes → nearest taxiway node
        for gate in config.get("gates", []):
            geo = gate.get("geo", {})
            lat = geo.get("latitude")
            lon = geo.get("longitude")
            if lat is None or lon is None:
                continue
            gate_id = self._get_or_create_node(float(lat), float(lon))
            nearest = self._find_nearest_node(
                float(lat), float(lon), exclude={gate_id}
            )
            if nearest is not None:
                self._add_edge(gate_id, nearest)

        logger.info(
            "TaxiwayGraph built: %d nodes, %d edges",
            len(self.nodes),
            sum(len(v) for v in self.edges.values()) // 2,
        )

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
        """Find closest graph node to a geo position. Returns node id or None."""
        if not self.nodes:
            return None
        best_id = None
        best_dist = float("inf")
        for nid, (nlat, nlon) in self.nodes.items():
            d = (nlat - lat) ** 2 + (nlon - lon) ** 2
            if d < best_dist:
                best_dist = d
                best_id = nid
        return best_id

    def _get_or_create_node(self, lat: float, lon: float) -> int:
        """Return existing node within snap_tolerance, or create a new one."""
        tol = self._snap_tolerance
        for nid, (nlat, nlon) in self.nodes.items():
            if abs(nlat - lat) < tol and abs(nlon - lon) < tol:
                return nid
        nid = self._next_id
        self._next_id += 1
        self.nodes[nid] = (lat, lon)
        self.edges.setdefault(nid, [])
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
        """Find nearest node, optionally excluding a set of node ids."""
        exclude = exclude or set()
        best_id = None
        best_dist = float("inf")
        for nid, (nlat, nlon) in self.nodes.items():
            if nid in exclude:
                continue
            d = (nlat - lat) ** 2 + (nlon - lon) ** 2
            if d < best_dist:
                best_dist = d
                best_id = nid
        return best_id

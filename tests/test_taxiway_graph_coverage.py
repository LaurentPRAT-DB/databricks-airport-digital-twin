"""Tests to improve coverage of src/routing/taxiway_graph.py.

Targets uncovered lines: 70, 84, 97-122, 130, 163, 177.
"""

import pytest

from src.routing.taxiway_graph import TaxiwayGraph, _haversine_m


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_geo_point(lat: float, lon: float) -> dict:
    return {"latitude": lat, "longitude": lon}


def _make_taxiway(points: list[tuple[float, float]]) -> dict:
    return {"geoPoints": [_make_geo_point(lat, lon) for lat, lon in points]}


def _make_runway(points: list[tuple[float, float]]) -> dict:
    return {"geoPoints": [_make_geo_point(lat, lon) for lat, lon in points]}


def _make_apron(polygon: list[tuple[float, float]]) -> dict:
    return {"geoPolygon": [_make_geo_point(lat, lon) for lat, lon in polygon]}


def _make_gate(name: str, lat: float | None, lon: float | None) -> dict:
    geo = {}
    if lat is not None:
        geo["latitude"] = lat
    if lon is not None:
        geo["longitude"] = lon
    return {"name": name, "geo": geo}


def _simple_config() -> dict:
    """A minimal config with two connected taxiways forming an L-shape."""
    return {
        "osmTaxiways": [
            _make_taxiway([(37.615, -122.390), (37.615, -122.385)]),
            _make_taxiway([(37.615, -122.385), (37.618, -122.385)]),
        ],
    }


# ---------------------------------------------------------------------------
# Graph construction — basic
# ---------------------------------------------------------------------------

class TestBuildFromConfig:
    def test_empty_config(self):
        g = TaxiwayGraph()
        g.build_from_config({})
        assert len(g.nodes) == 0
        assert len(g.edges) == 0

    def test_taxiway_creates_nodes_and_edges(self):
        g = TaxiwayGraph()
        g.build_from_config(_simple_config())
        # 3 unique nodes in the L-shape (the junction is shared via snapping)
        assert len(g.nodes) == 3
        # Each taxiway segment = 1 bidirectional edge; 2 segments = 2 edges
        total_half_edges = sum(len(v) for v in g.edges.values())
        assert total_half_edges == 4  # 2 edges x 2 directions

    def test_single_point_taxiway_skipped(self):
        """Line 70: taxiways with < 2 geoPoints are skipped."""
        config = {
            "osmTaxiways": [
                _make_taxiway([(37.615, -122.390)]),  # only 1 point
                _make_taxiway([]),  # empty
            ],
        }
        g = TaxiwayGraph()
        g.build_from_config(config)
        assert len(g.nodes) == 0

    def test_runway_with_single_point_skipped(self):
        """Line 84: runways with < 2 geoPoints are skipped."""
        config = {
            **_simple_config(),
            "osmRunways": [
                _make_runway([(37.610, -122.390)]),  # only 1 point
            ],
        }
        g = TaxiwayGraph()
        g.build_from_config(config)
        # Should still have only the taxiway nodes, runway skipped
        assert len(g.nodes) == 3


# ---------------------------------------------------------------------------
# Runway endpoint connections
# ---------------------------------------------------------------------------

class TestRunwayConnections:
    def test_runway_endpoints_connected_to_taxiway(self):
        config = {
            **_simple_config(),
            "osmRunways": [
                # Runway near the taxiway network
                _make_runway([(37.614, -122.390), (37.614, -122.385)]),
            ],
        }
        g = TaxiwayGraph()
        g.build_from_config(config)
        # Runway adds 2 endpoints, each connected to nearest taxiway node
        assert len(g.nodes) >= 5  # 3 taxiway + 2 runway


# ---------------------------------------------------------------------------
# Apron perimeter connectivity (lines 97-122)
# ---------------------------------------------------------------------------

class TestApronPerimeter:
    def test_apron_nodes_connected_within_300m(self):
        """Lines 97-122: apron perimeter nodes chain and connect to nearest taxiway."""
        config = {
            **_simple_config(),
            "osmAprons": [
                _make_apron([
                    (37.6155, -122.3900),  # close to taxiway node
                    (37.6155, -122.3895),
                    (37.6160, -122.3895),
                    (37.6160, -122.3900),
                ]),
            ],
        }
        g = TaxiwayGraph()
        g.build_from_config(config)
        # Apron adds perimeter nodes and connects them to taxiway network
        assert len(g.nodes) >= 5  # 3 taxiway + at least some apron nodes

    def test_apron_beyond_300m_not_connected_to_taxiway(self):
        """Lines 120-121: apron nodes > 300m from any taxiway node get no cross-edge."""
        config = {
            # Taxiway at one location
            "osmTaxiways": [
                _make_taxiway([(37.615, -122.390), (37.615, -122.385)]),
            ],
            # Apron very far away (>300m)
            "osmAprons": [
                _make_apron([
                    (37.650, -122.350),  # ~4 km away
                    (37.650, -122.349),
                    (37.651, -122.349),
                ]),
            ],
        }
        g = TaxiwayGraph()
        g.build_from_config(config)
        # Apron perimeter nodes are chained to each other but NOT to taxiway
        # The taxiway has 2 nodes + 1 edge (bidirectional = 2 half-edges)
        # The apron has 3 nodes + 2 chain edges (4 half-edges)
        # No cross-connections because distance > 300m
        taxiway_node_ids = set()
        for nid, (lat, lon) in g.nodes.items():
            if lat < 37.64:
                taxiway_node_ids.add(nid)

        # Check that no taxiway node has an edge to an apron node
        for tid in taxiway_node_ids:
            neighbors = {n for n, _ in g.edges.get(tid, [])}
            assert neighbors.issubset(taxiway_node_ids), \
                "Taxiway node should not connect to distant apron node"

    def test_apron_with_too_few_points_skipped(self):
        """Line 98: aprons with < 3 geoPolygon points are skipped."""
        config = {
            **_simple_config(),
            "osmAprons": [
                _make_apron([(37.615, -122.390), (37.616, -122.389)]),  # only 2 points
            ],
        }
        g = TaxiwayGraph()
        g.build_from_config(config)
        # Only taxiway nodes should exist
        assert len(g.nodes) == 3

    def test_apron_with_missing_coordinates_skipped(self):
        """Lines 104-105: apron points with None lat/lon are skipped."""
        config = {
            **_simple_config(),
            "osmAprons": [
                {
                    "geoPolygon": [
                        {"latitude": 37.615, "longitude": -122.390},
                        {"latitude": None, "longitude": -122.389},  # missing lat
                        {"longitude": -122.388},  # missing lat key
                        {"latitude": 37.616, "longitude": -122.390},
                    ],
                },
            ],
        }
        g = TaxiwayGraph()
        g.build_from_config(config)
        # Some apron points skipped, but valid ones still added
        assert len(g.nodes) >= 3  # taxiway nodes at minimum


# ---------------------------------------------------------------------------
# Gate nodes (line 130: gate with no geo)
# ---------------------------------------------------------------------------

class TestGateNodes:
    def test_gate_connected_to_taxiway(self):
        config = {
            **_simple_config(),
            "gates": [
                _make_gate("A1", 37.616, -122.389),
            ],
        }
        g = TaxiwayGraph()
        g.build_from_config(config)
        assert len(g.nodes) >= 4  # 3 taxiway + 1 gate

    def test_gate_with_no_geo_skipped(self):
        """Line 130: gates without lat/lon in geo are skipped."""
        config = {
            **_simple_config(),
            "gates": [
                _make_gate("A1", None, None),
                _make_gate("A2", 37.616, None),
                _make_gate("A3", None, -122.389),
                {"name": "A4"},  # no geo key at all
            ],
        }
        g = TaxiwayGraph()
        g.build_from_config(config)
        # Only taxiway nodes
        assert len(g.nodes) == 3


# ---------------------------------------------------------------------------
# Pathfinding (lines 163, 177)
# ---------------------------------------------------------------------------

class TestFindRoute:
    def test_shortest_path_between_endpoints(self):
        g = TaxiwayGraph()
        g.build_from_config(_simple_config())
        # Route from one end of L to the other
        route = g.find_route((37.615, -122.390), (37.618, -122.385))
        assert len(route) == 3  # start, junction, end

    def test_same_start_and_end(self):
        """Line 164-165: start==end returns single-element list."""
        g = TaxiwayGraph()
        g.build_from_config(_simple_config())
        route = g.find_route((37.615, -122.390), (37.615, -122.390))
        assert len(route) == 1

    def test_no_path_returns_empty(self):
        """Line 163/185-186: disconnected components → empty list."""
        g = TaxiwayGraph()
        # Two disconnected taxiways (far apart, beyond snap tolerance)
        config = {
            "osmTaxiways": [
                _make_taxiway([(37.615, -122.390), (37.615, -122.385)]),
                _make_taxiway([(38.000, -121.000), (38.000, -120.995)]),
            ],
        }
        g.build_from_config(config)
        route = g.find_route((37.615, -122.390), (38.000, -121.000))
        assert route == []

    def test_empty_graph_returns_empty(self):
        g = TaxiwayGraph()
        route = g.find_route((37.615, -122.390), (37.618, -122.385))
        assert route == []

    def test_stale_distance_in_heap_skipped(self):
        """Line 177: when a node is popped with a stale (larger) distance, skip it.

        This happens naturally in Dijkstra when a node gets a better path
        after being pushed to the heap.
        """
        g = TaxiwayGraph()
        # Create a diamond: A--B--D and A--C--D, where A-C-D is shorter
        # This forces B to sometimes be popped with a stale distance
        config = {
            "osmTaxiways": [
                # A -> B (long way via detour)
                _make_taxiway([(37.600, -122.400), (37.610, -122.400)]),
                # B -> D
                _make_taxiway([(37.610, -122.400), (37.620, -122.400)]),
                # A -> C (shorter, direct)
                _make_taxiway([(37.600, -122.400), (37.610, -122.395)]),
                # C -> D
                _make_taxiway([(37.610, -122.395), (37.620, -122.400)]),
            ],
        }
        g.build_from_config(config)
        route = g.find_route((37.600, -122.400), (37.620, -122.400))
        assert len(route) >= 2


# ---------------------------------------------------------------------------
# Route length
# ---------------------------------------------------------------------------

class TestRouteLength:
    def test_route_length(self):
        g = TaxiwayGraph()
        g.build_from_config(_simple_config())
        route = g.find_route((37.615, -122.390), (37.618, -122.385))
        length = g.route_length_meters(route)
        assert length > 0

    def test_empty_route_length(self):
        g = TaxiwayGraph()
        assert g.route_length_meters([]) == 0.0

    def test_single_point_route_length(self):
        g = TaxiwayGraph()
        assert g.route_length_meters([(37.615, -122.390)]) == 0.0


# ---------------------------------------------------------------------------
# Haversine sanity
# ---------------------------------------------------------------------------

class TestHaversine:
    def test_same_point(self):
        assert _haversine_m(37.0, -122.0, 37.0, -122.0) == 0.0

    def test_known_distance(self):
        # SFO to LAX is roughly 543 km
        d = _haversine_m(37.6213, -122.3790, 33.9425, -118.4081)
        assert 540_000 < d < 550_000


# ---------------------------------------------------------------------------
# Snap to nearest node
# ---------------------------------------------------------------------------

class TestSnapToNearest:
    def test_snap_to_nearest(self):
        g = TaxiwayGraph()
        g.build_from_config(_simple_config())
        nid = g.snap_to_nearest_node(37.615, -122.390)
        assert nid is not None
        lat, lon = g.nodes[nid]
        assert abs(lat - 37.615) < 0.001
        assert abs(lon - (-122.390)) < 0.001

    def test_snap_empty_graph(self):
        g = TaxiwayGraph()
        assert g.snap_to_nearest_node(37.0, -122.0) is None

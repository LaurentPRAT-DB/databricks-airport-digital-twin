"""Tests for TaxiwayGraph — graph construction, snapping, and routing."""

import pytest
from src.routing.taxiway_graph import TaxiwayGraph, _haversine_m


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_taxiway(geo_points, name="TWY_A"):
    return {
        "id": name,
        "name": name,
        "geoPoints": [{"latitude": lat, "longitude": lon} for lat, lon in geo_points],
        "width": 20.0,
    }


def _make_runway(geo_points, name="RWY_28L"):
    return {
        "id": name,
        "name": name,
        "geoPoints": [{"latitude": lat, "longitude": lon} for lat, lon in geo_points],
        "width": 45.0,
    }


def _make_gate(ref, lat, lon):
    return {"ref": ref, "geo": {"latitude": lat, "longitude": lon}}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBuildGraph:
    def test_build_empty(self):
        g = TaxiwayGraph()
        g.build_from_config({})
        assert len(g.nodes) == 0
        assert len(g.edges) == 0

    def test_build_single_taxiway(self):
        config = {
            "osmTaxiways": [
                _make_taxiway([(37.61, -122.38), (37.61, -122.37), (37.61, -122.36)])
            ]
        }
        g = TaxiwayGraph()
        g.build_from_config(config)
        assert len(g.nodes) == 3
        # 2 edges (bidirectional counted per direction = 4 entries total)
        total_adj = sum(len(v) for v in g.edges.values())
        assert total_adj == 4  # 2 edges × 2 directions

    def test_snap_nearby_nodes(self):
        """Two taxiways with endpoints close together should merge."""
        config = {
            "osmTaxiways": [
                _make_taxiway([(37.610, -122.380), (37.612, -122.378)]),
                # Second taxiway starts ~15m from first's endpoint (within 0.0002° snap)
                _make_taxiway([(37.61201, -122.37801), (37.614, -122.376)]),
            ]
        }
        g = TaxiwayGraph(snap_tolerance=0.0002)
        g.build_from_config(config)
        # Node (37.612, -122.378) should merge with (37.61201, -122.37801)
        assert len(g.nodes) == 3  # Not 4

    def test_snap_does_not_merge_far_nodes(self):
        """Nodes far apart should not snap together."""
        config = {
            "osmTaxiways": [
                _make_taxiway([(37.610, -122.380), (37.612, -122.378)]),
                _make_taxiway([(37.615, -122.375), (37.617, -122.373)]),
            ]
        }
        g = TaxiwayGraph(snap_tolerance=0.0002)
        g.build_from_config(config)
        assert len(g.nodes) == 4  # No merging

    def test_runway_connects_to_taxiway(self):
        config = {
            "osmTaxiways": [
                _make_taxiway([(37.615, -122.380), (37.615, -122.370)])
            ],
            "osmRunways": [
                _make_runway([(37.612, -122.380), (37.612, -122.360)])
            ],
        }
        g = TaxiwayGraph()
        g.build_from_config(config)
        # 2 taxiway nodes + 2 runway endpoints = 4 nodes
        assert len(g.nodes) == 4
        # Runway endpoints should connect to nearest taxiway nodes
        # Verify at least one runway node has edges to a taxiway node
        has_cross_edge = False
        for nid in g.nodes:
            for neighbor, _ in g.edges.get(nid, []):
                n1 = g.nodes[nid]
                n2 = g.nodes[neighbor]
                if abs(n1[0] - n2[0]) > 0.001:  # Different latitudes = cross-connection
                    has_cross_edge = True
        assert has_cross_edge

    def test_gate_connects_to_taxiway(self):
        config = {
            "osmTaxiways": [
                _make_taxiway([(37.615, -122.385), (37.615, -122.375)])
            ],
            "gates": [_make_gate("G1", 37.616, -122.380)],
        }
        g = TaxiwayGraph()
        g.build_from_config(config)
        # 2 taxiway nodes + 1 gate node = 3
        assert len(g.nodes) == 3


class TestFindRoute:
    def _linear_graph(self):
        """A → B → C → D in a line."""
        config = {
            "osmTaxiways": [
                _make_taxiway([
                    (37.610, -122.390),
                    (37.612, -122.385),
                    (37.614, -122.380),
                    (37.616, -122.375),
                ])
            ]
        }
        g = TaxiwayGraph()
        g.build_from_config(config)
        return g

    def test_find_route_simple(self):
        g = self._linear_graph()
        route = g.find_route((37.610, -122.390), (37.616, -122.375))
        assert len(route) == 4
        assert route[0] == (37.610, -122.390)
        assert route[-1] == (37.616, -122.375)

    def test_find_route_reverse(self):
        g = self._linear_graph()
        route = g.find_route((37.616, -122.375), (37.610, -122.390))
        assert len(route) == 4
        assert route[0] == (37.616, -122.375)
        assert route[-1] == (37.610, -122.390)

    def test_find_route_no_path(self):
        """Two disconnected taxiways should return empty route."""
        config = {
            "osmTaxiways": [
                _make_taxiway([(37.610, -122.390), (37.612, -122.385)]),
                _make_taxiway([(37.700, -122.300), (37.702, -122.295)]),
            ]
        }
        g = TaxiwayGraph(snap_tolerance=0.0002)
        g.build_from_config(config)
        route = g.find_route((37.610, -122.390), (37.700, -122.300))
        assert route == []

    def test_find_route_same_point(self):
        g = self._linear_graph()
        route = g.find_route((37.610, -122.390), (37.610, -122.390))
        assert len(route) == 1

    def test_find_route_empty_graph(self):
        g = TaxiwayGraph()
        g.build_from_config({})
        assert g.find_route((37.61, -122.38), (37.62, -122.37)) == []

    def test_find_route_branching(self):
        """Graph with a branch — should find optimal path."""
        config = {
            "osmTaxiways": [
                # Main path: A → B → C
                _make_taxiway([(37.610, -122.390), (37.612, -122.385), (37.614, -122.380)]),
                # Branch: B → D (different direction from C)
                _make_taxiway([(37.612, -122.385), (37.610, -122.380)]),
            ]
        }
        g = TaxiwayGraph()
        g.build_from_config(config)
        # Route from A to D should go A → B → D (not through C)
        route = g.find_route((37.610, -122.390), (37.610, -122.380))
        assert len(route) == 3


class TestSnapToNearestNode:
    def test_snap_to_nearest(self):
        g = TaxiwayGraph()
        g.build_from_config({
            "osmTaxiways": [
                _make_taxiway([(37.610, -122.390), (37.620, -122.380)])
            ]
        })
        nid = g.snap_to_nearest_node(37.611, -122.389)
        assert nid is not None
        assert g.nodes[nid] == (37.610, -122.390)

    def test_snap_empty_graph(self):
        g = TaxiwayGraph()
        g.build_from_config({})
        assert g.snap_to_nearest_node(37.61, -122.38) is None


class TestRouteLength:
    def test_route_length(self):
        g = TaxiwayGraph()
        route = [(37.610, -122.390), (37.620, -122.390)]
        length = g.route_length_meters(route)
        # ~1.1 km for 0.01° latitude
        assert 1000 < length < 1200

    def test_route_length_single_point(self):
        g = TaxiwayGraph()
        assert g.route_length_meters([(37.61, -122.38)]) == 0.0

    def test_route_length_empty(self):
        g = TaxiwayGraph()
        assert g.route_length_meters([]) == 0.0


class TestHaversine:
    def test_same_point(self):
        assert _haversine_m(37.61, -122.38, 37.61, -122.38) == 0.0

    def test_known_distance(self):
        # ~111 km per degree of latitude
        d = _haversine_m(37.0, -122.0, 38.0, -122.0)
        assert 110_000 < d < 112_000


class TestGateToRunwayRoute:
    def test_gate_to_runway_via_taxiway(self):
        """Full scenario: gate connected to taxiway, taxiway to runway."""
        config = {
            "osmTaxiways": [
                _make_taxiway([
                    (37.615, -122.390),
                    (37.615, -122.385),
                    (37.615, -122.380),
                    (37.615, -122.375),
                    (37.615, -122.370),
                ])
            ],
            "osmRunways": [
                _make_runway([(37.612, -122.370), (37.612, -122.360)])
            ],
            "gates": [_make_gate("G1", 37.616, -122.389)],
        }
        g = TaxiwayGraph()
        g.build_from_config(config)

        gate_pos = (37.616, -122.389)
        runway_exit = (37.612, -122.370)
        route = g.find_route(runway_exit, gate_pos)
        assert len(route) >= 3
        length = g.route_length_meters(route)
        assert length > 100  # Some non-trivial distance

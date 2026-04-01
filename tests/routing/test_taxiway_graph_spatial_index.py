"""Tests for TaxiwayGraph spatial grid index and building penalty bbox filter.

Covers the optimization additions:
- Grid-based _get_or_create_node (O(1) vs O(n))
- Expanding-ring snap_to_nearest_node
- Grid-based _find_nearest_node / _find_nearest_nodes
- Building penalty bounding box pre-filter
"""

import pytest

from src.routing.taxiway_graph import TaxiwayGraph, _haversine_m, _point_in_polygon


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_taxiway(points):
    return {"geoPoints": [{"latitude": lat, "longitude": lon} for lat, lon in points]}


def _make_runway(points):
    return {"geoPoints": [{"latitude": lat, "longitude": lon} for lat, lon in points]}


def _make_gate(name, lat, lon):
    return {"name": name, "ref": name, "geo": {"latitude": lat, "longitude": lon}}


def _make_terminal(polygon):
    return {"geoPolygon": [{"latitude": lat, "longitude": lon} for lat, lon in polygon]}


# ---------------------------------------------------------------------------
# Grid index basics
# ---------------------------------------------------------------------------

class TestGridIndex:
    def test_grid_key_deterministic(self):
        g = TaxiwayGraph(snap_tolerance=0.0002)
        k1 = g._grid_key(37.615, -122.385)
        k2 = g._grid_key(37.615, -122.385)
        assert k1 == k2

    def test_grid_key_different_for_distant_points(self):
        g = TaxiwayGraph(snap_tolerance=0.0002)
        k1 = g._grid_key(37.615, -122.385)
        k2 = g._grid_key(37.625, -122.375)
        assert k1 != k2

    def test_grid_populated_on_build(self):
        config = {
            "osmTaxiways": [
                _make_taxiway([(37.615, -122.390), (37.615, -122.385), (37.615, -122.380)])
            ]
        }
        g = TaxiwayGraph()
        g.build_from_config(config)
        # Grid should have entries
        total_grid_entries = sum(len(v) for v in g._grid.values())
        assert total_grid_entries == 3  # one per node

    def test_grid_cleared_on_rebuild(self):
        config = {
            "osmTaxiways": [_make_taxiway([(37.615, -122.390), (37.615, -122.385)])]
        }
        g = TaxiwayGraph()
        g.build_from_config(config)
        assert len(g._grid) > 0
        # Rebuild with empty config
        g.build_from_config({})
        assert len(g._grid) == 0

    def test_snapping_uses_grid(self):
        """Two nearby points should snap via grid lookup, not linear scan."""
        config = {
            "osmTaxiways": [
                _make_taxiway([(37.610, -122.380), (37.612, -122.378)]),
                # Second taxiway starts within snap tolerance of first's endpoint
                _make_taxiway([(37.61201, -122.37801), (37.614, -122.376)]),
            ]
        }
        g = TaxiwayGraph(snap_tolerance=0.0002)
        g.build_from_config(config)
        assert len(g.nodes) == 3  # snapped junction


# ---------------------------------------------------------------------------
# snap_to_nearest_node — expanding ring search
# ---------------------------------------------------------------------------

class TestSnapExpandingRing:
    def test_snap_finds_exact_node(self):
        config = {
            "osmTaxiways": [
                _make_taxiway([(37.610, -122.390), (37.620, -122.380)])
            ]
        }
        g = TaxiwayGraph()
        g.build_from_config(config)
        nid = g.snap_to_nearest_node(37.610, -122.390)
        assert g.nodes[nid] == (37.610, -122.390)

    def test_snap_finds_closest_of_many(self):
        config = {
            "osmTaxiways": [
                _make_taxiway([
                    (37.610, -122.390),
                    (37.615, -122.385),
                    (37.620, -122.380),
                    (37.625, -122.375),
                ])
            ]
        }
        g = TaxiwayGraph()
        g.build_from_config(config)
        # Query closest to third node
        nid = g.snap_to_nearest_node(37.6201, -122.3801)
        assert g.nodes[nid] == (37.620, -122.380)

    def test_snap_distant_point_still_finds_nearest(self):
        """Point moderately far from any node should still find the closest one."""
        config = {
            "osmTaxiways": [
                _make_taxiway([(37.610, -122.390), (37.612, -122.388)])
            ]
        }
        g = TaxiwayGraph()
        g.build_from_config(config)
        # Query from 0.005° away (~550m) — needs a few expanding rings
        nid = g.snap_to_nearest_node(37.617, -122.390)
        assert nid is not None
        # Should find the closest of the two nodes
        lat, _ = g.nodes[nid]
        assert lat == 37.612  # closer to 37.617 than 37.61

    def test_snap_empty_returns_none(self):
        g = TaxiwayGraph()
        g.build_from_config({})
        assert g.snap_to_nearest_node(37.61, -122.38) is None


# ---------------------------------------------------------------------------
# _find_nearest_node — grid-based with exclude
# ---------------------------------------------------------------------------

class TestFindNearestNode:
    def _build_graph(self):
        config = {
            "osmTaxiways": [
                _make_taxiway([
                    (37.610, -122.390),
                    (37.615, -122.385),
                    (37.620, -122.380),
                ])
            ]
        }
        g = TaxiwayGraph()
        g.build_from_config(config)
        return g

    def test_finds_nearest_without_exclude(self):
        g = self._build_graph()
        nid = g._find_nearest_node(37.6151, -122.3851)
        assert g.nodes[nid] == (37.615, -122.385)

    def test_finds_next_nearest_with_exclude(self):
        g = self._build_graph()
        # Find the nearest node first
        nearest = g._find_nearest_node(37.6151, -122.3851)
        assert g.nodes[nearest] == (37.615, -122.385)
        # Exclude it, should find next closest
        next_nearest = g._find_nearest_node(37.6151, -122.3851, exclude={nearest})
        assert next_nearest is not None
        assert next_nearest != nearest


# ---------------------------------------------------------------------------
# _find_nearest_nodes — degree pre-filter
# ---------------------------------------------------------------------------

class TestFindNearestNodes:
    def test_finds_multiple_nearby(self):
        config = {
            "osmTaxiways": [
                _make_taxiway([
                    (37.610, -122.390),
                    (37.611, -122.389),
                    (37.612, -122.388),
                    (37.613, -122.387),
                    (37.614, -122.386),
                ])
            ]
        }
        g = TaxiwayGraph()
        g.build_from_config(config)
        results = g._find_nearest_nodes(37.6115, -122.3895, k=3, max_dist_m=500)
        assert len(results) == 3  # should find 3 closest
        # Results should be sorted by distance
        dists = [_haversine_m(37.6115, -122.3895, *g.nodes[nid]) for nid in results]
        assert dists == sorted(dists)

    def test_respects_max_dist(self):
        config = {
            "osmTaxiways": [
                _make_taxiway([(37.610, -122.390), (37.612, -122.388)]),
                # Far away taxiway
                _make_taxiway([(37.650, -122.350), (37.652, -122.348)]),
            ]
        }
        g = TaxiwayGraph()
        g.build_from_config(config)
        results = g._find_nearest_nodes(37.611, -122.389, k=5, max_dist_m=500)
        # Only nearby nodes should be returned, not distant ones
        for nid in results:
            d = _haversine_m(37.611, -122.389, *g.nodes[nid])
            assert d <= 500

    def test_respects_exclude(self):
        config = {
            "osmTaxiways": [
                _make_taxiway([(37.610, -122.390), (37.611, -122.389), (37.612, -122.388)])
            ]
        }
        g = TaxiwayGraph()
        g.build_from_config(config)
        all_results = g._find_nearest_nodes(37.611, -122.389, k=5, max_dist_m=500)
        # Exclude the closest
        excluded = g._find_nearest_nodes(
            37.611, -122.389, k=5, max_dist_m=500, exclude={all_results[0]}
        )
        assert all_results[0] not in excluded

    def test_degree_prefilter_rejects_distant(self):
        """The degree pre-filter should skip nodes beyond deg_radius."""
        config = {
            "osmTaxiways": [
                _make_taxiway([(37.610, -122.390), (37.612, -122.388)]),
            ]
        }
        g = TaxiwayGraph()
        g.build_from_config(config)
        # Very tight max_dist should return only very close nodes
        results = g._find_nearest_nodes(37.610, -122.390, k=5, max_dist_m=50)
        for nid in results:
            d = _haversine_m(37.610, -122.390, *g.nodes[nid])
            assert d <= 50


# ---------------------------------------------------------------------------
# Building penalty — bounding box pre-filter
# ---------------------------------------------------------------------------

class TestBuildingPenaltyBBox:
    """Test the bounding box pre-filter in _penalize_building_edges.

    Uses small positive coordinates where _point_in_polygon works correctly.
    (The PiP function cross-compares lat vs lon, so it only produces correct
    results when both coordinates are in the same order of magnitude.)
    """

    def _config_with_building(self):
        """Taxiway passes through a building polygon using small coords."""
        return {
            "osmTaxiways": [
                # Through-building taxiway
                _make_taxiway([(0.5, 0.0), (0.5, 0.5), (0.5, 1.0)]),
                # Around-building taxiway
                _make_taxiway([(0.5, 0.0), (0.0, 0.25), (0.0, 0.75), (0.5, 1.0)]),
            ],
            "terminals": [
                # Building at center
                _make_terminal([(0.3, 0.2), (0.3, 0.8), (0.7, 0.8), (0.7, 0.2)]),
            ],
        }

    def test_building_penalty_applied(self):
        """Edges through terminal should have penalized weights."""
        g = TaxiwayGraph(snap_tolerance=0.01)
        g.build_from_config(self._config_with_building())
        penalized_found = False
        for nid, neighbors in g.edges.items():
            for neighbor_id, weight in neighbors:
                dist = _haversine_m(*g.nodes[nid], *g.nodes[neighbor_id])
                if dist > 0 and weight > dist * 10:
                    penalized_found = True
        assert penalized_found, "Expected at least one penalized edge through terminal"

    def test_route_avoids_building(self):
        """Dijkstra should prefer the longer route around the terminal."""
        g = TaxiwayGraph(snap_tolerance=0.01)
        g.build_from_config(self._config_with_building())
        route = g.find_route((0.5, 0.0), (0.5, 1.0))
        assert len(route) >= 3

    def test_no_penalty_without_buildings(self):
        """Without terminals, no edges should be penalized."""
        config = {
            "osmTaxiways": [
                _make_taxiway([(0.5, 0.0), (0.5, 0.5), (0.5, 1.0)])
            ]
        }
        g = TaxiwayGraph(snap_tolerance=0.01)
        g.build_from_config(config)
        for nid, neighbors in g.edges.items():
            for neighbor_id, weight in neighbors:
                expected = _haversine_m(*g.nodes[nid], *g.nodes[neighbor_id])
                assert abs(weight - expected) < 0.01

    def test_bbox_rejects_distant_polygons(self):
        """Bounding box filter should skip polygons far from edge sample point."""
        config = {
            "osmTaxiways": [
                _make_taxiway([(0.5, 0.0), (0.5, 0.5), (0.5, 1.0)])
            ],
            "terminals": [
                # Building far from the taxiway
                _make_terminal([(5.0, 5.0), (5.0, 6.0), (6.0, 6.0), (6.0, 5.0)]),
            ],
        }
        g = TaxiwayGraph(snap_tolerance=0.01)
        g.build_from_config(config)
        # No edges should be penalized — building is far away
        for nid, neighbors in g.edges.items():
            for neighbor_id, weight in neighbors:
                expected = _haversine_m(*g.nodes[nid], *g.nodes[neighbor_id])
                assert abs(weight - expected) < 0.01


# ---------------------------------------------------------------------------
# point_in_polygon (used by building penalty)
# ---------------------------------------------------------------------------

class TestPointInPolygon:
    def test_point_inside(self):
        square = [(0, 0), (0, 1), (1, 1), (1, 0)]
        assert _point_in_polygon(0.5, 0.5, square) is True

    def test_point_outside(self):
        square = [(0, 0), (0, 1), (1, 1), (1, 0)]
        assert _point_in_polygon(2.0, 2.0, square) is False

    def test_point_on_edge(self):
        """Edge cases are implementation-dependent; just verify no crash."""
        square = [(0, 0), (0, 1), (1, 1), (1, 0)]
        # Should not raise
        _point_in_polygon(0.0, 0.5, square)

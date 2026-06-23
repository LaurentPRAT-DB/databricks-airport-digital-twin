"""Tests that approach direction uses OSM runway data, NOT latitude fallback.

Ensures _get_osm_primary_runway resolves correctly for well-known airports
and that _get_approach_waypoints produces trajectories from the correct
bearing — never from the generic fallback (270° for lat>30°).
"""

import math
from unittest.mock import MagicMock, patch

import pytest

from src.ingestion._approach_departure import (
    _get_approach_waypoints,
    _get_fallback_runway,
    _get_osm_primary_runway,
    _get_runway_heading,
    _get_runway_threshold,
    _osm_runway_endpoints,
    reset_approach_caches,
)
from src.ingestion.fallback import get_airport_center, get_current_airport_iata, set_airport_center


# ── Fixtures: realistic runway data from OSM ──────────────────────────────────

KSFO_RUNWAY = {
    "ref": "10L/28R",
    "geoPoints": [
        {"latitude": 37.613926, "longitude": -122.358089},
        {"latitude": 37.628738, "longitude": -122.393396},
    ],
}

LGAV_RUNWAY = {
    "ref": "03R/21L",
    "geoPoints": [
        {"latitude": 37.9259184, "longitude": 23.9455142},
        {"latitude": 37.9503738, "longitude": 23.9687864},
    ],
}

EGLL_RUNWAY = {
    "ref": "09L/27R",
    "geoPoints": [
        {"latitude": 51.4775, "longitude": -0.4857},
        {"latitude": 51.4775, "longitude": -0.4333},
    ],
}

KJFK_RUNWAY = {
    "ref": "13L/31R",
    "geoPoints": [
        {"latitude": 40.6413, "longitude": -73.7781},
        {"latitude": 40.6243, "longitude": -73.7564},
    ],
}


def _make_config(runway):
    return {"osmRunways": [runway]}


def _mock_service(config):
    svc = MagicMock()
    svc.get_config.return_value = config
    return svc


# ── Test: _osm_runway_endpoints orientation ──────────────────────────────────


class TestRunwayEndpointsOrientation:
    """Verify that _osm_runway_endpoints picks the correct active end."""

    def test_ksfo_28r_heading_approx_280_300(self):
        """KSFO 28R: aircraft land heading ~280-300° (west-northwest)."""
        _, _, heading = _osm_runway_endpoints(KSFO_RUNWAY)
        assert 275 <= heading <= 305, f"KSFO heading {heading} not in [275, 305]"

    def test_lgav_21l_heading_approx_210_220(self):
        """LGAV 21L (ATH): aircraft land heading ~210-220° (south-southwest)."""
        _, _, heading = _osm_runway_endpoints(LGAV_RUNWAY)
        assert 210 <= heading <= 225, f"LGAV heading {heading} not in [210, 225]"

    def test_egll_27r_heading_approx_260_280(self):
        """EGLL 27R (Heathrow): aircraft land heading ~270°."""
        _, _, heading = _osm_runway_endpoints(EGLL_RUNWAY)
        assert 255 <= heading <= 285, f"EGLL heading {heading} not in [255, 285]"

    def test_kjfk_31r_heading_approx_300_320(self):
        """KJFK 31R: aircraft land heading ~310°."""
        _, _, heading = _osm_runway_endpoints(KJFK_RUNWAY)
        assert 295 <= heading <= 325, f"KJFK heading {heading} not in [295, 325]"


# ── Test: _get_osm_primary_runway resolves from config ───────────────────────


class TestOsmPrimaryRunwayResolution:
    """Verify _get_osm_primary_runway reads from airport_config_service."""

    def setup_method(self):
        reset_approach_caches()

    def test_resolves_ksfo(self):
        config = _make_config(KSFO_RUNWAY)
        with patch(
            "app.backend.services.airport_config_service.get_airport_config_service",
            return_value=_mock_service(config),
        ):
            rwy = _get_osm_primary_runway()
            assert rwy is not None
            assert rwy["ref"] == "10L/28R"

    def test_resolves_lgav(self):
        config = _make_config(LGAV_RUNWAY)
        with patch(
            "app.backend.services.airport_config_service.get_airport_config_service",
            return_value=_mock_service(config),
        ):
            rwy = _get_osm_primary_runway()
            assert rwy is not None
            assert rwy["ref"] == "03R/21L"

    def test_returns_none_when_no_runways(self):
        config = {"osmRunways": []}
        with patch(
            "app.backend.services.airport_config_service.get_airport_config_service",
            return_value=_mock_service(config),
        ):
            rwy = _get_osm_primary_runway()
            assert rwy is None

    def test_staleness_guard_detects_config_change(self):
        """When config object changes (airport switch), re-resolve."""
        ksfo_config = _make_config(KSFO_RUNWAY)
        lgav_config = _make_config(LGAV_RUNWAY)

        svc = MagicMock()
        svc.get_config.return_value = ksfo_config

        with patch(
            "app.backend.services.airport_config_service.get_airport_config_service",
            return_value=svc,
        ):
            rwy1 = _get_osm_primary_runway()
            assert rwy1["ref"] == "10L/28R"

            # Config object changes (simulates airport switch)
            svc.get_config.return_value = lgav_config
            rwy2 = _get_osm_primary_runway()
            assert rwy2["ref"] == "03R/21L"


# ── Test: approach waypoints use OSM, not fallback ───────────────────────────


class TestApproachWaypointsUseOsm:
    """Critical: approach waypoints must use OSM heading, never latitude fallback."""

    @pytest.fixture(autouse=True)
    def _provide_osm_runway_data(self):
        """Override conftest's autouse fixture — let real _get_osm_primary_runway run."""
        yield

    @pytest.fixture(autouse=True)
    def _restore_airport_center(self):
        """Restore global airport center after each test to avoid polluting other tests."""
        prev_center = get_airport_center()
        prev_iata = get_current_airport_iata()
        yield
        set_airport_center(prev_center[0], prev_center[1], prev_iata)

    def setup_method(self):
        reset_approach_caches()

    def _get_approach_bearing(self, waypoints):
        """Compute bearing from first waypoint to last (approach direction)."""
        wp_first = waypoints[0]  # furthest from airport
        wp_last = waypoints[-1]  # at threshold
        lat1, lon1 = math.radians(wp_first[1]), math.radians(wp_first[0])
        lat2, lon2 = math.radians(wp_last[1]), math.radians(wp_last[0])
        dlon = lon2 - lon1
        x = math.sin(dlon) * math.cos(lat2)
        y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
        bearing = math.degrees(math.atan2(x, y))
        return (bearing + 360) % 360

    def test_ksfo_approach_not_due_east(self):
        """KSFO: approach must NOT come from due east (90°, the fallback).

        With OSM data, KSFO 28R approach comes from ~118° (ESE).
        Fallback would give exactly 90° (due east). Reject if within 10° of 90°.
        """
        config = _make_config(KSFO_RUNWAY)
        set_airport_center(37.6213, -122.3790, "SFO")

        with patch(
            "app.backend.services.airport_config_service.get_airport_config_service",
            return_value=_mock_service(config),
        ):
            wps = _get_approach_waypoints(None)
            bearing = self._get_approach_bearing(wps)
            # Should NOT be near 90° (fallback from east)
            diff_from_fallback = abs((bearing - 90 + 180) % 360 - 180)
            assert diff_from_fallback > 10, (
                f"Approach bearing {bearing:.1f}° is too close to fallback 90° "
                f"(diff={diff_from_fallback:.1f}°) — OSM data not being used!"
            )

    def test_lgav_approach_not_due_east(self):
        """LGAV (ATH): approach must come from NE (~37°), NOT from east (90°).

        With OSM data, LGAV 21L has heading ~217°, approach from ~37° (NE).
        Fallback would give 90° (due east for lat>30°). Reject if near 90°.
        """
        config = _make_config(LGAV_RUNWAY)
        set_airport_center(37.9364, 23.9445, "ATH")

        with patch(
            "app.backend.services.airport_config_service.get_airport_config_service",
            return_value=_mock_service(config),
        ):
            wps = _get_approach_waypoints(None)
            bearing = self._get_approach_bearing(wps)
            # For ATH 21L, approach is from NE (~37°)
            # Fallback would be 90° — must not be near 90°
            diff_from_fallback = abs((bearing - 90 + 180) % 360 - 180)
            assert diff_from_fallback > 20, (
                f"LGAV approach bearing {bearing:.1f}° is too close to fallback 90° "
                f"(diff={diff_from_fallback:.1f}°) — OSM data not being used!"
            )

    def test_ksfo_lax_origin_approaches_from_south(self):
        """Flight from LAX to KSFO must approach from SE, not due east."""
        config = _make_config(KSFO_RUNWAY)
        set_airport_center(37.6213, -122.3790, "SFO")

        with patch(
            "app.backend.services.airport_config_service.get_airport_config_service",
            return_value=_mock_service(config),
        ):
            wps = _get_approach_waypoints("LAX")
            # First waypoint is where aircraft STARTS (far from airport)
            # Last waypoint is threshold. Aircraft flies first→last.
            # Bearing first→last is the aircraft HEADING (not approach-from direction).
            bearing = self._get_approach_bearing(wps)
            # Aircraft heading ~315° means approaching FROM ~135° (SE) — correct for LAX→SFO
            approach_from = (bearing + 180) % 360
            assert 100 <= approach_from <= 180, (
                f"LAX→KSFO approach_from {approach_from:.1f}° not in [100, 180] — "
                f"expected approach from the south-southeast"
            )

    def test_heading_matches_osm_not_fallback(self):
        """_get_runway_heading must return OSM-derived value, not fallback."""
        config = _make_config(LGAV_RUNWAY)
        set_airport_center(37.9364, 23.9445, "ATH")

        with patch(
            "app.backend.services.airport_config_service.get_airport_config_service",
            return_value=_mock_service(config),
        ):
            heading = _get_runway_heading()
            fallback = _get_fallback_runway()
            fallback_heading = fallback[2]

            assert heading is not None, "Heading should not be None with OSM data"
            # OSM heading for LGAV 21L should be ~217°
            assert 210 <= heading <= 225
            # Must be different from fallback (270° for lat>30°)
            assert abs(heading - fallback_heading) > 30, (
                f"heading={heading:.1f}° too close to fallback={fallback_heading:.1f}°"
            )

    def test_fallback_not_cached_when_osm_available(self):
        """If OSM resolves after initial empty config, waypoints must update."""
        set_airport_center(37.9364, 23.9445, "ATH")

        empty_config = {"osmRunways": []}
        full_config = _make_config(LGAV_RUNWAY)
        svc = MagicMock()

        with patch(
            "app.backend.services.airport_config_service.get_airport_config_service",
            return_value=svc,
        ):
            # First: empty config → fallback
            svc.get_config.return_value = empty_config
            rwy = _get_osm_primary_runway()
            assert rwy is None

            # Config object changes (Lakebase loads)
            svc.get_config.return_value = full_config
            rwy = _get_osm_primary_runway()
            assert rwy is not None, (
                "After config change, _get_osm_primary_runway must re-resolve "
                "and find the runway — staleness guard should fire"
            )
            assert rwy["ref"] == "03R/21L"

"""Tests for airport center computation fallback during activation."""

import pytest

from app.backend.api.routes_airport import _compute_center_from_config


class TestComputeCenterFromConfig:
    """Tests for _compute_center_from_config fallback."""

    def test_center_from_gates(self):
        """Test computing center from gate geo coordinates."""
        config = {
            "gates": [
                {"geo": {"latitude": 37.6, "longitude": -122.4}},
                {"geo": {"latitude": 37.7, "longitude": -122.5}},
            ],
            "terminals": [],
        }
        lat, lon = _compute_center_from_config(config)
        assert lat == pytest.approx(37.65)
        assert lon == pytest.approx(-122.45)

    def test_center_from_terminals_when_no_gates(self):
        """Test falling back to terminal geo coordinates."""
        config = {
            "gates": [],
            "terminals": [
                {"geo": {"latitude": 35.5, "longitude": 139.7}},
                {"geo": {"latitude": 35.6, "longitude": 139.8}},
            ],
        }
        lat, lon = _compute_center_from_config(config)
        assert lat == pytest.approx(35.55)
        assert lon == pytest.approx(139.75)

    def test_gates_preferred_over_terminals(self):
        """Test that gates are used even when terminals exist."""
        config = {
            "gates": [
                {"geo": {"latitude": 37.6, "longitude": -122.4}},
            ],
            "terminals": [
                {"geo": {"latitude": 0.0, "longitude": 0.0}},
            ],
        }
        lat, lon = _compute_center_from_config(config)
        assert lat == pytest.approx(37.6)
        assert lon == pytest.approx(-122.4)

    def test_no_coordinates_returns_none(self):
        """Test returns None when no geo data available."""
        config = {"gates": [], "terminals": []}
        lat, lon = _compute_center_from_config(config)
        assert lat is None
        assert lon is None

    def test_gates_without_geo_skipped(self):
        """Test gates without geo coordinates are skipped."""
        config = {
            "gates": [
                {"position": {"x": 0, "y": 0, "z": 0}},  # No geo
                {"geo": {"latitude": 37.6, "longitude": -122.4}},
            ],
            "terminals": [],
        }
        lat, lon = _compute_center_from_config(config)
        assert lat == pytest.approx(37.6)
        assert lon == pytest.approx(-122.4)

    def test_empty_config(self):
        """Test empty config returns None."""
        lat, lon = _compute_center_from_config({})
        assert lat is None
        assert lon is None

    def test_string_coordinates_converted(self):
        """Test that string-typed coordinates are converted to float."""
        config = {
            "gates": [
                {"geo": {"latitude": "37.6", "longitude": "-122.4"}},
            ],
        }
        lat, lon = _compute_center_from_config(config)
        assert lat == pytest.approx(37.6)
        assert lon == pytest.approx(-122.4)


class TestOSMConverterCenter:
    """Tests for center key in OSM converter output."""

    def test_to_config_includes_center(self):
        """Test that OSM converter output includes center key."""
        from unittest.mock import MagicMock
        from src.formats.osm.converter import OSMConverter
        from src.formats.base import CoordinateConverter

        converter = OSMConverter(CoordinateConverter(
            reference_lat=37.6, reference_lon=-122.4, reference_alt=0.0,
        ))

        # Create a minimal OSMDocument mock
        doc = MagicMock()
        doc.icao_code = "KSFO"
        doc.iata_code = "SFO"
        doc.airport_name = "San Francisco International"
        doc.airport_operator = None
        doc.timestamp = None
        doc.gates = []
        doc.terminals = []
        doc.taxiways = []
        doc.aprons = []
        doc.runways = []
        doc.hangars = []
        doc.helipads = []
        doc.parking_positions = []

        # Add nodes so centroid can be computed
        node1 = MagicMock()
        node1.lat = 37.6
        node1.lon = -122.4
        node2 = MagicMock()
        node2.lat = 37.7
        node2.lon = -122.5
        doc.nodes = [node1, node2]
        doc.ways = []

        config = converter.to_config(doc)
        assert "center" in config
        assert config["center"]["latitude"] == pytest.approx(37.65)
        assert config["center"]["longitude"] == pytest.approx(-122.45)

    def test_to_config_no_center_without_nodes(self):
        """Test no center key when no geometry data."""
        from unittest.mock import MagicMock
        from src.formats.osm.converter import OSMConverter
        from src.formats.base import CoordinateConverter

        converter = OSMConverter(CoordinateConverter(
            reference_lat=37.6, reference_lon=-122.4, reference_alt=0.0,
        ))

        doc = MagicMock()
        doc.icao_code = "XXXX"
        doc.iata_code = "XXX"
        doc.airport_name = "Test"
        doc.airport_operator = None
        doc.timestamp = None
        doc.gates = []
        doc.terminals = []
        doc.taxiways = []
        doc.aprons = []
        doc.runways = []
        doc.hangars = []
        doc.helipads = []
        doc.parking_positions = []
        doc.nodes = []
        doc.ways = []

        config = converter.to_config(doc)
        assert "center" not in config


# ==============================================================================
# Cached airport config validation
# ==============================================================================

ALL_CACHED_AIRPORTS = [
    "KSFO", "KJFK", "KLAX", "KORD", "KATL", "KDFW", "KDEN", "KMIA", "KSEA",
    "SBGR", "MMMX",
    "EGLL", "LFPG", "EHAM", "EDDF", "LEMD", "LIRF", "LSGG", "LGAV",
    "OMAA", "OMDB",
    "RJTT", "VHHH", "WSSS", "ZBAA", "RKSI", "VTBS",
    "FAOR", "GMMN",
]


class TestCachedAirportConfigValidation:
    """Validate that all cached airport configs have usable geometry.

    These tests load the airport config service with each cached airport
    and verify it has gates or terminals with valid geo coordinates,
    so the frontend map can recenter correctly.
    """

    @pytest.fixture
    def service(self):
        from app.backend.services.airport_config_service import AirportConfigService
        return AirportConfigService()

    @pytest.mark.parametrize("icao", ALL_CACHED_AIRPORTS)
    def test_config_has_valid_geometry(self, service, icao):
        """Each cached airport must have gates or terminals with geo coordinates."""
        loaded = service.initialize_from_lakehouse(icao_code=icao, fallback_to_osm=True)
        assert loaded, f"Failed to load config for {icao}"

        config = service.get_config()
        assert config, f"Empty config for {icao}"

        gates = config.get("gates", [])
        terminals = config.get("terminals", [])

        geo_items = []
        for g in gates:
            geo = g.get("geo", {})
            lat = float(geo.get("latitude", 0) or 0)
            lon = float(geo.get("longitude", 0) or 0)
            if lat != 0 and lon != 0:
                geo_items.append((lat, lon))

        for t in terminals:
            geo = t.get("geo", {})
            lat = float(geo.get("latitude", 0) or 0)
            lon = float(geo.get("longitude", 0) or 0)
            if lat != 0 and lon != 0:
                geo_items.append((lat, lon))

        assert len(geo_items) > 0, (
            f"{icao}: no gates or terminals with valid geo coordinates. "
            f"Gates: {len(gates)}, Terminals: {len(terminals)}"
        )

    @pytest.mark.parametrize("icao", ALL_CACHED_AIRPORTS)
    def test_config_has_icao_code(self, service, icao):
        """Each config must include its ICAO code."""
        loaded = service.initialize_from_lakehouse(icao_code=icao, fallback_to_osm=True)
        assert loaded

        config = service.get_config()
        assert config.get("icaoCode") == icao

    @pytest.mark.parametrize("icao", ALL_CACHED_AIRPORTS)
    def test_config_has_runways(self, service, icao):
        """Each airport should have at least one runway."""
        loaded = service.initialize_from_lakehouse(icao_code=icao, fallback_to_osm=True)
        assert loaded

        config = service.get_config()
        runways = config.get("osmRunways", [])
        assert len(runways) > 0, f"{icao}: no runways found"

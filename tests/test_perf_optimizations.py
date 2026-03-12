"""Tests for performance optimization changes.

Covers:
1. _slim_config() — strips OSM metadata, gate fields, truncates coordinates
2. /api/predictions/congestion-summary — merged endpoint returning areas + bottlenecks
3. /api/airport/config — returns slimmed config
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from fastapi.testclient import TestClient

from app.backend.main import app
from app.backend.api.routes import _slim_config


# =============================================================================
# 1. _slim_config() unit tests
# =============================================================================

class TestSlimConfig:
    """Tests for the _slim_config helper that strips verbose OSM metadata."""

    def test_empty_config_passthrough(self):
        assert _slim_config({}) == {}

    def test_none_config_passthrough(self):
        assert _slim_config(None) is None

    def test_strips_tags_from_osm_collections(self):
        config = {
            "osmTaxiways": [
                {"id": "tw1", "name": "A", "tags": {"highway": "taxiway"}, "source": "osm", "osmId": 123}
            ],
            "osmAprons": [
                {"id": "ap1", "tags": {"aeroway": "apron"}, "osmId": 456}
            ],
            "osmRunways": [
                {"id": "rw1", "tags": {"aeroway": "runway"}, "source": "osm"}
            ],
            "terminals": [
                {"id": "t1", "name": "Terminal 1", "tags": {"building": "terminal"}, "source": "osm", "osmId": 789}
            ],
        }
        result = _slim_config(config)

        # tags, source, osmId should be stripped
        for key in ("osmTaxiways", "osmAprons", "osmRunways", "terminals"):
            for item in result[key]:
                assert "tags" not in item
                assert "source" not in item
                assert "osmId" not in item

        # Other fields preserved
        assert result["osmTaxiways"][0]["id"] == "tw1"
        assert result["osmTaxiways"][0]["name"] == "A"

    def test_strips_gates_to_allowed_fields(self):
        config = {
            "gates": [
                {
                    "id": "g1",
                    "ref": "A1",
                    "name": "Gate A1",
                    "geo": {"latitude": 37.6, "longitude": -122.4},
                    "tags": {"aeroway": "gate"},
                    "source": "osm",
                    "osmId": 999,
                    "extra_field": "should be removed",
                }
            ]
        }
        result = _slim_config(config)

        gate = result["gates"][0]
        assert set(gate.keys()) == {"id", "ref", "name", "geo"}
        assert gate["geo"]["latitude"] == 37.6

    def test_truncates_geo_polygon_precision(self):
        config = {
            "osmTaxiways": [
                {
                    "id": "tw1",
                    "geoPolygon": [
                        {"latitude": 37.6190123456789, "longitude": -122.4001234567890},
                        {"latitude": 37.6200987654321, "longitude": -122.3999876543210},
                    ]
                }
            ],
        }
        result = _slim_config(config)

        points = result["osmTaxiways"][0]["geoPolygon"]
        for pt in points:
            lat_str = str(pt["latitude"])
            lon_str = str(pt["longitude"])
            # Should have at most 6 decimal places
            if "." in lat_str:
                assert len(lat_str.split(".")[1]) <= 7  # 6 decimals + possible float repr
            if "." in lon_str:
                assert len(lon_str.split(".")[1]) <= 7

    def test_truncates_geo_points_precision(self):
        config = {
            "terminals": [
                {
                    "id": "t1",
                    "geoPoints": [
                        {"latitude": 37.61901234567, "longitude": -122.40012345678},
                    ]
                }
            ],
        }
        result = _slim_config(config)
        pt = result["terminals"][0]["geoPoints"][0]
        assert pt["latitude"] == round(37.61901234567, 6)
        assert pt["longitude"] == round(-122.40012345678, 6)

    def test_preserves_non_osm_fields(self):
        config = {
            "icaoCode": "KSFO",
            "sources": ["osm"],
            "runways": [{"id": "r1", "name": "28L"}],
            "navaids": [{"id": "n1"}],
        }
        result = _slim_config(config)
        assert result["icaoCode"] == "KSFO"
        assert result["sources"] == ["osm"]
        assert result["runways"] == [{"id": "r1", "name": "28L"}]
        assert result["navaids"] == [{"id": "n1"}]

    def test_handles_missing_collections(self):
        config = {"icaoCode": "KJFK"}
        result = _slim_config(config)
        assert result == {"icaoCode": "KJFK"}

    def test_handles_non_list_collections(self):
        config = {"osmTaxiways": "not_a_list", "gates": 42}
        result = _slim_config(config)
        assert result["osmTaxiways"] == "not_a_list"
        assert result["gates"] == 42

    def test_handles_non_dict_geo_points(self):
        config = {
            "osmAprons": [
                {"id": "a1", "geoPolygon": ["not_a_dict", 123, None]}
            ]
        }
        result = _slim_config(config)
        # Non-dict entries should be filtered out
        assert result["osmAprons"][0]["geoPolygon"] == []

    def test_none_coordinate_preserved(self):
        config = {
            "osmRunways": [
                {
                    "id": "r1",
                    "geoPolygon": [
                        {"latitude": None, "longitude": -122.4}
                    ]
                }
            ]
        }
        result = _slim_config(config)
        pt = result["osmRunways"][0]["geoPolygon"][0]
        assert pt["latitude"] is None
        assert pt["longitude"] == round(-122.4, 6)


# =============================================================================
# 2. /api/predictions/congestion-summary endpoint tests
# =============================================================================

class TestCongestionSummaryEndpoint:
    """Tests for the merged congestion-summary endpoint."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        """Use FastAPI dependency_overrides for proper DI mocking."""
        from app.backend.services.prediction_service import get_prediction_service
        from app.backend.services.flight_service import get_flight_service

        self._orig_pred = app.dependency_overrides.get(get_prediction_service)
        self._orig_flight = app.dependency_overrides.get(get_flight_service)

        yield

        # Restore
        app.dependency_overrides.pop(get_prediction_service, None)
        app.dependency_overrides.pop(get_flight_service, None)

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def _setup_mocks(self, congestion_data):
        from app.backend.services.prediction_service import get_prediction_service, PredictionService
        from app.backend.services.flight_service import get_flight_service, FlightService

        flight_svc = MagicMock(spec=FlightService)
        flight_response = MagicMock()
        flight_response.flights = []
        flight_svc.get_flights = AsyncMock(return_value=flight_response)

        pred_svc = MagicMock(spec=PredictionService)
        pred_svc.get_congestion = AsyncMock(return_value=congestion_data)
        pred_svc.get_bottlenecks = AsyncMock()  # Should NOT be called by summary endpoint

        app.dependency_overrides[get_prediction_service] = lambda: pred_svc
        app.dependency_overrides[get_flight_service] = lambda: flight_svc

        return pred_svc, flight_svc

    @pytest.fixture
    def mock_congestion_data(self):
        """Create mock congestion data with mixed levels."""
        from src.ml.congestion_model import CongestionLevel

        class MockCongestion:
            def __init__(self, area_id, area_type, level, flight_count, wait_minutes):
                self.area_id = area_id
                self.area_type = area_type
                self.level = level
                self.flight_count = flight_count
                self.predicted_wait_minutes = wait_minutes

        return [
            MockCongestion("runway_28L", "runway", CongestionLevel.LOW, 1, 0),
            MockCongestion("taxiway_A", "taxiway", CongestionLevel.MODERATE, 3, 5),
            MockCongestion("apron_north", "apron", CongestionLevel.HIGH, 8, 15),
            MockCongestion("terminal_1", "terminal", CongestionLevel.CRITICAL, 12, 25),
        ]

    def test_returns_all_areas_and_bottlenecks(self, client, mock_congestion_data):
        self._setup_mocks(mock_congestion_data)

        response = client.get("/api/predictions/congestion-summary")
        assert response.status_code == 200

        data = response.json()
        assert data["areas_count"] == 4
        assert data["bottlenecks_count"] == 2  # HIGH + CRITICAL
        assert len(data["areas"]) == 4
        assert len(data["bottlenecks"]) == 2

        # Bottlenecks should only include high and critical
        bottleneck_levels = {b["level"] for b in data["bottlenecks"]}
        assert bottleneck_levels == {"high", "critical"}

    def test_no_bottlenecks_when_all_low(self, client):
        from src.ml.congestion_model import CongestionLevel

        class MockCongestion:
            def __init__(self, area_id):
                self.area_id = area_id
                self.area_type = "runway"
                self.level = CongestionLevel.LOW
                self.flight_count = 1
                self.predicted_wait_minutes = 0

        self._setup_mocks([MockCongestion("r1"), MockCongestion("r2")])

        response = client.get("/api/predictions/congestion-summary")
        assert response.status_code == 200

        data = response.json()
        assert data["areas_count"] == 2
        assert data["bottlenecks_count"] == 0
        assert data["bottlenecks"] == []

    def test_empty_congestion(self, client):
        self._setup_mocks([])

        response = client.get("/api/predictions/congestion-summary")
        assert response.status_code == 200

        data = response.json()
        assert data["areas_count"] == 0
        assert data["bottlenecks_count"] == 0

    def test_single_fetch_not_duplicate(self, client, mock_congestion_data):
        """Verify congestion-summary calls get_congestion once (not get_bottlenecks separately)."""
        pred_svc, _ = self._setup_mocks(mock_congestion_data)

        response = client.get("/api/predictions/congestion-summary")
        assert response.status_code == 200

        pred_svc.get_congestion.assert_called_once()
        pred_svc.get_bottlenecks.assert_not_called()


# =============================================================================
# 3. /api/airport/config endpoint returns slimmed config
# =============================================================================

class TestAirportConfigSlimmed:
    """Test that /api/airport/config returns slimmed config."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    @patch("app.backend.api.routes.get_airport_config_service")
    def test_config_endpoint_strips_tags(self, mock_svc, client):
        service = MagicMock()
        service.get_config.return_value = {
            "icaoCode": "KSFO",
            "sources": ["osm"],
            "osmTaxiways": [{"id": "tw1", "tags": {"highway": "taxiway"}, "osmId": 123}],
            "gates": [
                {"id": "g1", "ref": "A1", "name": "Gate A1",
                 "geo": {"latitude": 37.6, "longitude": -122.4},
                 "tags": {"aeroway": "gate"}, "osmId": 999}
            ],
        }
        service.get_last_updated.return_value = None
        service.get_element_counts.return_value = {"gates": 1, "taxiways": 1}
        mock_svc.return_value = service

        # Set app ready state
        app.state.ready = True

        response = client.get("/api/airport/config")
        assert response.status_code == 200

        data = response.json()
        config = data["config"]

        # Tags stripped from taxiways
        assert "tags" not in config["osmTaxiways"][0]
        assert "osmId" not in config["osmTaxiways"][0]

        # Gates trimmed to allowed fields only
        gate = config["gates"][0]
        assert set(gate.keys()) == {"id", "ref", "name", "geo"}

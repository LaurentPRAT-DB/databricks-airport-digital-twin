"""Tests for Airport Configuration API Routes."""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from app.backend.main import app
from app.backend.services.airport_config_service import AirportConfigService


# Sample test data
SAMPLE_AIXM = b"""<?xml version="1.0" encoding="UTF-8"?>
<message:AIXMBasicMessage xmlns:message="http://www.aixm.aero/schema/5.1.1/message"
    xmlns:aixm="http://www.aixm.aero/schema/5.1.1"
    xmlns:gml="http://www.opengis.net/gml/3.2">
    <message:hasMember>
        <aixm:Runway gml:id="RWY_28L">
            <aixm:timeSlice>
                <aixm:RunwayTimeSlice gml:id="RWY_TS1">
                    <aixm:identifier>RWY-28L</aixm:identifier>
                    <aixm:designator>28L/10R</aixm:designator>
                    <aixm:nominalLength>3048</aixm:nominalLength>
                    <aixm:nominalWidth>45</aixm:nominalWidth>
                    <aixm:centreLine>
                        <gml:posList>37.6190 -122.400 4.0 37.6236 -122.358 4.0</gml:posList>
                    </aixm:centreLine>
                </aixm:RunwayTimeSlice>
            </aixm:timeSlice>
        </aixm:Runway>
    </message:hasMember>
</message:AIXMBasicMessage>
"""

SAMPLE_AIDM = b"""{
    "version": "12.0",
    "airport": {"code": "SFO"},
    "flights": [
        {
            "flightId": {
                "airline": {"code": "UA"},
                "flightNumber": "123",
                "operationalDate": "2026-03-08T00:00:00Z"
            },
            "legs": [
                {
                    "legId": "leg-1",
                    "departureAirport": {"code": "LAX"},
                    "arrivalAirport": {"code": "SFO"}
                }
            ],
            "status": "SCHEDULED"
        }
    ]
}"""


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_service():
    """Create mock airport config service."""
    service = MagicMock(spec=AirportConfigService)
    service.get_config.return_value = {
        "runways": [{"id": "28L"}],
        "taxiways": [],
    }
    service.get_last_updated.return_value = datetime(2026, 3, 8, 10, 0, 0, tzinfo=timezone.utc)
    service.get_element_counts.return_value = {
        "runways": 1,
        "taxiways": 0,
        "buildings": 0,
        "aprons": 0,
        "navaids": 0,
        "ifc_elements": 0,
        "aidm_flights": 0,
    }
    return service


class TestGetAirportConfig:
    """Tests for GET /api/airport/config endpoint."""

    def test_get_config_success(self, client):
        """Test successful config retrieval."""
        response = client.get("/api/airport/config")

        assert response.status_code == 200
        data = response.json()
        assert "config" in data
        assert "elementCounts" in data

    def test_get_config_includes_counts(self, client):
        """Test that config includes element counts."""
        response = client.get("/api/airport/config")

        data = response.json()
        assert "elementCounts" in data
        assert "runways" in data["elementCounts"]


class TestImportAIXM:
    """Tests for POST /api/airport/import/aixm endpoint."""

    def test_import_aixm_success(self, client):
        """Test successful AIXM import."""
        response = client.post(
            "/api/airport/import/aixm",
            content=SAMPLE_AIXM,
            headers={"Content-Type": "application/octet-stream"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["format"] == "AIXM"
        assert "elementsImported" in data

    def test_import_aixm_with_reference_point(self, client):
        """Test AIXM import with custom reference point."""
        response = client.post(
            "/api/airport/import/aixm?reference_lat=40.6413&reference_lon=-73.7781",
            content=SAMPLE_AIXM,
            headers={"Content-Type": "application/octet-stream"},
        )

        assert response.status_code == 200

    def test_import_aixm_invalid_xml(self, client):
        """Test AIXM import with invalid XML."""
        response = client.post(
            "/api/airport/import/aixm",
            content=b"not valid xml",
            headers={"Content-Type": "application/octet-stream"},
        )

        assert response.status_code == 400
        assert "parsing error" in response.json()["detail"].lower()

    def test_import_aixm_no_merge(self, client):
        """Test AIXM import without merge."""
        response = client.post(
            "/api/airport/import/aixm?merge=false",
            content=SAMPLE_AIXM,
            headers={"Content-Type": "application/octet-stream"},
        )

        assert response.status_code == 200


class TestImportAIDM:
    """Tests for POST /api/airport/import/aidm endpoint."""

    def test_import_aidm_success(self, client):
        """Test successful AIDM import."""
        response = client.post(
            "/api/airport/import/aidm",
            content=SAMPLE_AIDM,
            headers={"Content-Type": "application/octet-stream"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "flightsImported" in data

    def test_import_aidm_with_local_airport(self, client):
        """Test AIDM import with custom local airport."""
        response = client.post(
            "/api/airport/import/aidm?local_airport=JFK",
            content=SAMPLE_AIDM,
            headers={"Content-Type": "application/octet-stream"},
        )

        assert response.status_code == 200

    def test_import_aidm_invalid_json(self, client):
        """Test AIDM import with invalid JSON."""
        response = client.post(
            "/api/airport/import/aidm",
            content=b"not valid json",
            headers={"Content-Type": "application/octet-stream"},
        )

        assert response.status_code == 400


class TestImportIFC:
    """Tests for POST /api/airport/import/ifc endpoint."""

    def test_import_ifc_without_library(self, client):
        """Test IFC import when ifcopenshell not installed."""
        # This should fail gracefully since ifcopenshell likely isn't installed
        response = client.post(
            "/api/airport/import/ifc",
            content=b"fake ifc content",
            headers={"Content-Type": "application/octet-stream"},
        )

        # Should return 400 with helpful error message
        assert response.status_code == 400
        assert "ifc" in response.json()["detail"].lower()

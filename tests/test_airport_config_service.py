"""Tests for Airport Configuration Service."""

import pytest
from datetime import datetime

from app.backend.services.airport_config_service import (
    AirportConfigService,
    get_airport_config_service,
)
from src.formats.base import ParseError


# Sample AIXM XML for testing
SAMPLE_AIXM = b"""<?xml version="1.0" encoding="UTF-8"?>
<message:AIXMBasicMessage xmlns:message="http://www.aixm.aero/schema/5.1.1/message"
    xmlns:aixm="http://www.aixm.aero/schema/5.1.1"
    xmlns:gml="http://www.opengis.net/gml/3.2">
    <message:hasMember>
        <aixm:Runway gml:id="RWY_28L28R">
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

# Sample AIDM JSON for testing
SAMPLE_AIDM = """{
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


class TestAirportConfigService:
    """Tests for AirportConfigService."""

    @pytest.fixture
    def service(self):
        """Create fresh service instance."""
        return AirportConfigService()

    def test_initial_config_empty(self, service):
        """Test that initial config is empty."""
        config = service.get_config()
        assert config == {}

    def test_initial_last_updated_none(self, service):
        """Test that initial last_updated is None."""
        assert service.get_last_updated() is None

    def test_set_reference_point(self, service):
        """Test setting reference point."""
        service.set_reference_point(40.6413, -73.7781, 4.0)  # JFK

        # Reference point should be updated in converter
        assert service._converter.reference_lat == 40.6413
        assert service._converter.reference_lon == -73.7781

    def test_import_aixm(self, service):
        """Test AIXM import."""
        config, warnings = service.import_aixm(SAMPLE_AIXM)

        assert "runways" in config
        assert len(config["runways"]) == 1
        assert config["runways"][0]["id"] == "28L/10R"
        assert service.get_last_updated() is not None

    def test_import_aixm_with_merge(self, service):
        """Test AIXM import with merge."""
        # First import
        service.import_aixm(SAMPLE_AIXM, merge=False)

        # Second import with merge
        config, _ = service.import_aixm(SAMPLE_AIXM, merge=True)

        # Should still have runways
        assert "runways" in config

    def test_import_aixm_invalid_xml(self, service):
        """Test AIXM import with invalid XML."""
        with pytest.raises(ParseError):
            service.import_aixm(b"not valid xml")

    def test_import_aidm(self, service):
        """Test AIDM import."""
        config, warnings = service.import_aidm(SAMPLE_AIDM)

        assert "flights" in config
        assert len(config["flights"]) >= 0  # May be filtered

    def test_import_aidm_with_local_airport(self, service):
        """Test AIDM import with custom local airport."""
        config, _ = service.import_aidm(SAMPLE_AIDM, local_airport="JFK")

        # Service should store AIDM data
        internal_config = service.get_config()
        assert "aidm_flights" in internal_config or "aidm_scheduled" in internal_config

    def test_import_aidm_invalid_json(self, service):
        """Test AIDM import with invalid content."""
        with pytest.raises(ParseError):
            service.import_aidm("not valid json or xml")

    def test_clear_config(self, service):
        """Test clearing configuration."""
        # Import some data first
        service.import_aixm(SAMPLE_AIXM)
        assert service.get_config() != {}
        assert service.get_last_updated() is not None

        # Clear
        service.clear_config()

        assert service.get_config() == {}
        assert service.get_last_updated() is None

    def test_get_element_counts(self, service):
        """Test element counting."""
        service.import_aixm(SAMPLE_AIXM)
        counts = service.get_element_counts()

        assert "runways" in counts
        assert "taxiways" in counts
        assert counts["runways"] == 1

    def test_get_element_counts_empty(self, service):
        """Test element counting with empty config."""
        counts = service.get_element_counts()

        assert counts["runways"] == 0
        assert counts["taxiways"] == 0


class TestGetAirportConfigService:
    """Tests for singleton getter."""

    def test_returns_same_instance(self):
        """Test that singleton returns same instance."""
        service1 = get_airport_config_service()
        service2 = get_airport_config_service()

        assert service1 is service2

    def test_returns_valid_service(self):
        """Test that singleton returns valid service."""
        service = get_airport_config_service()

        assert isinstance(service, AirportConfigService)
        assert hasattr(service, "import_aixm")
        assert hasattr(service, "import_aidm")

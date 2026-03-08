"""Tests for AIDM converter."""

import pytest
from datetime import datetime

from src.formats.base import CoordinateConverter
from src.formats.aidm.converter import AIDMConverter, merge_aidm_flights
from src.formats.aidm.models import (
    AIDMDocument,
    AIDMFlight,
    AIDMFlightId,
    AIDMFlightLeg,
    AIDMAirline,
    AIDMAirport,
    AIDMAircraft,
    AIDMGate,
    AIDMResource,
    AIDMEvent,
    AIDMEventType,
    AIDMResourceType,
    FlightType,
)


class TestAIDMConverter:
    """Tests for AIDM to internal format converter."""

    @pytest.fixture
    def converter(self):
        """Create converter with SFO reference point."""
        coord_converter = CoordinateConverter(
            reference_lat=37.6213,
            reference_lon=-122.379,
            reference_alt=4.0,
        )
        return AIDMConverter(coord_converter)

    @pytest.fixture
    def sample_flight(self):
        """Create sample flight with legs."""
        return AIDMFlight(
            flightId=AIDMFlightId(
                airline=AIDMAirline(code="UA", name="United Airlines"),
                flightNumber="123",
                operationalDate=datetime(2026, 3, 8, 12, 0, 0),
            ),
            flightType=FlightType.SCHEDULED,
            aircraft=AIDMAircraft(
                registration="N12345",
                aircraftType="B738",
                icaoType="B738",
            ),
            legs=[
                AIDMFlightLeg(
                    legId="leg-1",
                    sequence=1,
                    departureAirport=AIDMAirport(code="LAX", terminal="7"),
                    arrivalAirport=AIDMAirport(code="SFO", terminal="1"),
                    scheduledDeparture=datetime(2026, 3, 8, 8, 0, 0),
                    scheduledArrival=datetime(2026, 3, 8, 9, 30, 0),
                    runway="28L",
                )
            ],
            gate=AIDMGate(gateId="A1", terminal="1"),
            status=AIDMEventType.SCHEDULED,
        )

    def test_convert_to_config(self, converter, sample_flight):
        """Test full document conversion."""
        doc = AIDMDocument(
            airport=AIDMAirport(code="SFO"),
            timestamp=datetime(2026, 3, 8, 10, 0, 0),
            flights=[sample_flight],
        )

        config = converter.to_config(doc)

        assert config["source"] == "AIDM"
        assert config["airport"] == "SFO"
        assert "flights" in config
        assert "scheduled_flights" in config

    def test_convert_to_scheduled_flight(self, converter, sample_flight):
        """Test conversion to scheduled flight format."""
        doc = AIDMDocument(flights=[sample_flight])
        config = converter.to_config(doc)

        assert len(config["scheduled_flights"]) == 1
        scheduled = config["scheduled_flights"][0]

        assert scheduled["flight_number"] == "UA123"
        assert scheduled["airline"] == "UA"
        assert scheduled["airline_name"] == "United Airlines"
        assert scheduled["origin"] == "LAX"
        assert scheduled["destination"] == "SFO"
        assert scheduled["gate"] == "A1"
        assert scheduled["aircraft_type"] == "B738"

    def test_convert_resources(self, converter):
        """Test resource conversion."""
        doc = AIDMDocument(
            resources=[
                AIDMResource(
                    resourceType=AIDMResourceType.GATE,
                    resourceId="A1",
                    terminal="1",
                    startTime=datetime(2026, 3, 8, 8, 0, 0),
                    endTime=datetime(2026, 3, 8, 10, 0, 0),
                )
            ]
        )

        config = converter.to_config(doc)

        assert len(config["resources"]) == 1
        resource = config["resources"][0]
        assert resource["type"] == "GATE"
        assert resource["id"] == "A1"
        assert resource["terminal"] == "1"

    def test_convert_events(self, converter):
        """Test event conversion."""
        doc = AIDMDocument(
            events=[
                AIDMEvent(
                    eventId="EVT-001",
                    eventType=AIDMEventType.BOARDING,
                    timestamp=datetime(2026, 3, 8, 9, 0, 0),
                    description="Boarding started",
                    source="DCS",
                )
            ]
        )

        config = converter.to_config(doc)

        assert len(config["events"]) == 1
        event = config["events"][0]
        assert event["id"] == "EVT-001"
        assert event["type"] == "BOARDING"
        assert event["description"] == "Boarding started"

    def test_convert_gates(self, converter):
        """Test gate conversion."""
        doc = AIDMDocument(
            gates=[
                AIDMGate(
                    gateId="A1",
                    terminal="1",
                    gateType="Contact",
                )
            ]
        )

        config = converter.to_config(doc)

        # Gates should appear in resources
        gate_resources = [r for r in config["resources"] if r["type"] == "GATE"]
        assert len(gate_resources) == 1
        assert gate_resources[0]["id"] == "A1"

    def test_status_mapping(self, converter):
        """Test flight status mapping."""
        statuses_to_test = [
            (AIDMEventType.SCHEDULED, "scheduled"),
            (AIDMEventType.BOARDING, "boarding"),
            (AIDMEventType.DEPARTED, "departed"),
            (AIDMEventType.LANDED, "landed"),
            (AIDMEventType.ON_BLOCK, "at_gate"),
            (AIDMEventType.CANCELLED, "cancelled"),
        ]

        for aidm_status, expected_status in statuses_to_test:
            flight = AIDMFlight(
                flightId=AIDMFlightId(
                    airline=AIDMAirline(code="UA"),
                    flightNumber="100",
                    operationalDate=datetime(2026, 3, 8),
                ),
                legs=[
                    AIDMFlightLeg(
                        legId="leg-1",
                        departureAirport=AIDMAirport(code="LAX"),
                        arrivalAirport=AIDMAirport(code="SFO"),
                    )
                ],
                status=aidm_status,
            )

            doc = AIDMDocument(flights=[flight])
            config = converter.to_config(doc)

            if config["scheduled_flights"]:
                assert config["scheduled_flights"][0]["status"] == expected_status

    def test_flight_phase_determination(self, converter):
        """Test flight phase mapping from status."""
        phases = {
            AIDMEventType.BOARDING: "boarding",
            AIDMEventType.OFF_BLOCK: "taxi_out",
            AIDMEventType.DEPARTED: "climb",
            AIDMEventType.LANDED: "taxi_in",
            AIDMEventType.ON_BLOCK: "at_gate",
        }

        for status, expected_phase in phases.items():
            assert converter._determine_phase(status) == expected_phase

    def test_icao24_generation(self, converter, sample_flight):
        """Test pseudo ICAO24 generation."""
        icao24 = converter._generate_icao24(sample_flight)

        # Should be 6 hex characters
        assert len(icao24) == 6
        assert all(c in "0123456789abcdef" for c in icao24)

        # Same flight should produce same ICAO24
        icao24_2 = converter._generate_icao24(sample_flight)
        assert icao24 == icao24_2

    def test_position_estimation_at_gate(self, converter, sample_flight):
        """Test position estimation for flights at gate."""
        sample_flight.status = AIDMEventType.ON_BLOCK

        doc = AIDMDocument(flights=[sample_flight])
        config = converter.to_config(doc)

        if config["flights"]:
            flight = config["flights"][0]
            assert flight["on_ground"] is True
            assert flight["velocity"] == 0

    def test_position_estimation_departed(self, converter, sample_flight):
        """Test position estimation for departed flights."""
        sample_flight.status = AIDMEventType.DEPARTED

        doc = AIDMDocument(flights=[sample_flight])
        config = converter.to_config(doc)

        if config["flights"]:
            flight = config["flights"][0]
            assert flight["on_ground"] is False
            assert flight["altitude"] > 0

    def test_empty_document(self, converter):
        """Test conversion of empty document."""
        doc = AIDMDocument()
        config = converter.to_config(doc)

        assert config["flights"] == []
        assert config["scheduled_flights"] == []
        assert config["resources"] == []
        assert config["events"] == []


class TestMergeAIDMFlights:
    """Tests for merge_aidm_flights function."""

    def test_merge_updates_existing(self):
        """Test that AIDM data updates existing flights."""
        existing = [
            {
                "callsign": "UA123",
                "latitude": 37.6,
                "longitude": -122.4,
                "status": "en_route",
            }
        ]
        aidm = [
            {
                "callsign": "UA123",
                "latitude": 37.62,  # Different position
                "longitude": -122.38,
                "status": "landed",  # Updated status
                "gate": "A1",
            }
        ]

        result = merge_aidm_flights(existing, aidm)

        assert len(result) == 1
        # Position should be from existing (ADS-B is more accurate)
        assert result[0]["latitude"] == 37.6
        # Status should be from AIDM (authoritative)
        assert result[0]["status"] == "landed"
        assert result[0]["gate"] == "A1"

    def test_merge_adds_new_flights(self):
        """Test that new AIDM flights are added."""
        existing = [{"callsign": "UA123"}]
        aidm = [{"callsign": "UA456"}]

        result = merge_aidm_flights(existing, aidm)

        assert len(result) == 2
        callsigns = [f["callsign"] for f in result]
        assert "UA123" in callsigns
        assert "UA456" in callsigns

    def test_merge_preserves_unmatched_existing(self):
        """Test that existing flights not in AIDM are preserved."""
        existing = [
            {"callsign": "UA123"},
            {"callsign": "AA100"},
        ]
        aidm = [
            {"callsign": "UA123", "gate": "A1"},
        ]

        result = merge_aidm_flights(existing, aidm)

        assert len(result) == 2
        aa_flight = next(f for f in result if f["callsign"] == "AA100")
        assert aa_flight is not None

    def test_merge_empty_existing(self):
        """Test merge with empty existing flights."""
        existing = []
        aidm = [{"callsign": "UA123"}]

        result = merge_aidm_flights(existing, aidm)

        assert len(result) == 1
        assert result[0]["callsign"] == "UA123"

    def test_merge_empty_aidm(self):
        """Test merge with empty AIDM flights."""
        existing = [{"callsign": "UA123"}]
        aidm = []

        result = merge_aidm_flights(existing, aidm)

        assert len(result) == 1
        assert result[0]["callsign"] == "UA123"

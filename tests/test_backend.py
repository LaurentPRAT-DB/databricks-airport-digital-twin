"""Tests for the Airport Digital Twin FastAPI backend."""

import pytest
from fastapi.testclient import TestClient

from app.backend.main import app
from app.backend.models.flight import FlightPosition, FlightListResponse


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    def test_health_endpoint(self, client):
        """Test that health endpoint returns healthy status."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


class TestFlightsEndpoint:
    """Tests for the flights API endpoints."""

    def test_flights_endpoint(self, client):
        """Test that flights endpoint returns flight data."""
        response = client.get("/api/flights")

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "flights" in data
        assert "count" in data
        assert "timestamp" in data

        # Verify flights are returned
        assert isinstance(data["flights"], list)
        assert data["count"] == len(data["flights"])

    def test_flights_endpoint_with_count(self, client):
        """Test flights endpoint with custom count parameter."""
        response = client.get("/api/flights?count=10")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 10

    def test_flights_endpoint_invalid_count(self, client):
        """Test flights endpoint with invalid count."""
        response = client.get("/api/flights?count=0")
        assert response.status_code == 422  # Validation error

        response = client.get("/api/flights?count=1000")
        assert response.status_code == 422  # Exceeds max

    def test_single_flight_not_found(self, client):
        """Test that requesting a non-existent flight returns 404."""
        response = client.get("/api/flights/nonexistent")

        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()


class TestFlightModels:
    """Tests for flight data models."""

    def test_flight_position_model_validation(self):
        """Test FlightPosition model with valid data."""
        flight = FlightPosition(
            icao24="a12345",
            callsign="UAL123",
            latitude=37.6213,
            longitude=-122.379,
            altitude=5000.0,
            velocity=200.0,
            heading=270.0,
            on_ground=False,
            vertical_rate=5.0,
            last_seen=1709654400,
            data_source="synthetic",
            flight_phase="cruise",
        )

        assert flight.icao24 == "a12345"
        assert flight.callsign == "UAL123"
        assert flight.latitude == 37.6213
        assert flight.on_ground is False
        assert flight.data_source == "synthetic"

    def test_flight_position_minimal(self):
        """Test FlightPosition with minimal required fields."""
        flight = FlightPosition(icao24="abc123")

        assert flight.icao24 == "abc123"
        assert flight.callsign is None
        assert flight.on_ground is False
        assert flight.data_source == "synthetic"

    def test_flight_position_invalid_icao24(self):
        """Test FlightPosition requires icao24."""
        with pytest.raises(Exception):  # ValidationError
            FlightPosition()

    def test_flight_list_response_model(self):
        """Test FlightListResponse model."""
        flights = [
            FlightPosition(icao24="abc123", callsign="UAL1"),
            FlightPosition(icao24="def456", callsign="DAL2"),
        ]

        response = FlightListResponse(
            flights=flights,
            count=len(flights),
        )

        assert len(response.flights) == 2
        assert response.count == 2
        assert response.timestamp is not None


class TestFlightDataIntegrity:
    """Tests for flight data integrity from the API."""

    def test_flight_data_fields(self, client):
        """Test that flight data contains expected fields."""
        response = client.get("/api/flights?count=5")
        assert response.status_code == 200

        data = response.json()
        if data["flights"]:
            flight = data["flights"][0]

            # Check required fields exist
            assert "icao24" in flight
            assert "data_source" in flight

            # Check icao24 format (should be hex string)
            assert isinstance(flight["icao24"], str)
            assert len(flight["icao24"]) == 6

    def test_flight_positions_have_coordinates(self, client):
        """Test that flights have valid coordinate data."""
        response = client.get("/api/flights?count=10")
        assert response.status_code == 200

        data = response.json()
        for flight in data["flights"]:
            # Synthetic data should always have coordinates
            assert flight["latitude"] is not None
            assert flight["longitude"] is not None

            # Validate coordinate ranges
            assert -90 <= flight["latitude"] <= 90
            assert -180 <= flight["longitude"] <= 180

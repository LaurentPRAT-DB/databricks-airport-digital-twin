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

    def test_health_endpoint_includes_lakebase_status(self, client):
        """Test that health endpoint includes lakebase status."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "lakebase" in data
        assert isinstance(data["lakebase"], bool)

    def test_health_endpoint_includes_airport_info(self, client):
        """Test that health endpoint includes airport and source info."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "airport" in data
        assert "airport_source" in data

    def test_health_endpoint_lakebase_unavailable(self, client):
        """Test health endpoint gracefully handles unavailable lakebase."""
        from unittest.mock import patch, MagicMock
        mock_service = MagicMock()
        mock_service.is_available = False
        with patch("app.backend.services.lakebase_service.get_lakebase_service", return_value=mock_service):
            response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["lakebase"] is False


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


class TestPredictionEndpoints:
    """Tests for the ML prediction API endpoints."""

    def test_delays_endpoint(self, client):
        """Test that delays endpoint returns 200."""
        response = client.get("/api/predictions/delays")

        assert response.status_code == 200
        data = response.json()
        assert "delays" in data
        assert "count" in data
        assert isinstance(data["delays"], list)

    def test_delay_response_format(self, client):
        """Test delay response has required fields."""
        response = client.get("/api/predictions/delays")
        assert response.status_code == 200

        data = response.json()
        if data["delays"]:
            delay = data["delays"][0]

            # Verify required fields
            assert "icao24" in delay
            assert "delay_minutes" in delay
            assert "confidence" in delay
            assert "category" in delay

            # Verify field types and ranges
            assert isinstance(delay["delay_minutes"], (int, float))
            assert 0 <= delay["confidence"] <= 1
            assert delay["category"] in ["on_time", "slight", "moderate", "severe"]

    def test_delay_single_flight(self, client):
        """Test delay endpoint with single flight filter."""
        # First get a flight to filter by
        flights_response = client.get("/api/flights?count=1")
        assert flights_response.status_code == 200

        flights_data = flights_response.json()
        if flights_data["flights"]:
            icao24 = flights_data["flights"][0]["icao24"]

            # Get delay for that specific flight
            response = client.get(f"/api/predictions/delays?icao24={icao24}")
            assert response.status_code == 200

            data = response.json()
            assert data["count"] <= 1
            if data["delays"]:
                assert data["delays"][0]["icao24"] == icao24

    def test_gates_endpoint(self, client):
        """Test that gates endpoint returns recommendations."""
        # First get a flight
        flights_response = client.get("/api/flights?count=1")
        assert flights_response.status_code == 200

        flights_data = flights_response.json()
        if flights_data["flights"]:
            icao24 = flights_data["flights"][0]["icao24"]

            response = client.get(f"/api/predictions/gates/{icao24}")
            assert response.status_code == 200

            recommendations = response.json()
            assert isinstance(recommendations, list)

            if recommendations:
                rec = recommendations[0]
                assert "gate_id" in rec
                assert "score" in rec
                assert "reasons" in rec
                assert "taxi_time" in rec

    def test_gates_endpoint_top_k(self, client):
        """Test gates endpoint respects top_k parameter."""
        # First get a flight
        flights_response = client.get("/api/flights?count=1")
        assert flights_response.status_code == 200

        flights_data = flights_response.json()
        if flights_data["flights"]:
            icao24 = flights_data["flights"][0]["icao24"]

            response = client.get(f"/api/predictions/gates/{icao24}?top_k=5")
            assert response.status_code == 200

            recommendations = response.json()
            assert len(recommendations) <= 5

    def test_congestion_endpoint(self, client):
        """Test that congestion endpoint returns areas."""
        response = client.get("/api/predictions/congestion")

        assert response.status_code == 200
        data = response.json()

        assert "areas" in data
        assert "count" in data
        assert isinstance(data["areas"], list)

        if data["areas"]:
            area = data["areas"][0]
            assert "area_id" in area
            assert "area_type" in area
            assert "level" in area
            assert "flight_count" in area
            assert "wait_minutes" in area

            # Verify level is valid
            assert area["level"] in ["low", "moderate", "high", "critical"]

    def test_bottlenecks_endpoint(self, client):
        """Test bottlenecks endpoint filters correctly."""
        response = client.get("/api/predictions/bottlenecks")

        assert response.status_code == 200
        data = response.json()

        assert "areas" in data
        assert "count" in data

        # Bottlenecks should only contain HIGH or CRITICAL levels
        for area in data["areas"]:
            assert area["level"] in ["high", "critical"]

    def test_prediction_performance(self, client):
        """Test that prediction endpoints respond under 2 seconds."""
        import time

        endpoints = [
            "/api/predictions/delays",
            "/api/predictions/congestion",
            "/api/predictions/bottlenecks",
        ]

        for endpoint in endpoints:
            start = time.time()
            response = client.get(endpoint)
            elapsed = time.time() - start

            assert response.status_code == 200
            assert elapsed < 2.0, f"{endpoint} took {elapsed:.2f}s (> 2s limit)"

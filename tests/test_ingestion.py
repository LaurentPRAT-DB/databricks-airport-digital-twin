"""Tests for ingestion components - OpenSky client, fallback, circuit breaker, poll job."""

import pytest
import json
import os
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock


class TestOpenSkyClient:
    """Tests for OpenSky API client."""

    def test_opensky_client_returns_states(self, mock_opensky_response):
        """Test that OpenSkyClient.get_states() returns valid OpenSkyResponse."""
        from src.ingestion.opensky_client import OpenSkyClient
        from src.schemas.opensky import OpenSkyResponse

        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.ok = True
            mock_response.json.return_value = mock_opensky_response
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            client = OpenSkyClient()
            result = client.get_states()

            assert isinstance(result, OpenSkyResponse)
            assert result.time == mock_opensky_response["time"]
            assert result.states is not None
            assert len(result.states) == 2

    def test_opensky_client_retries_on_failure(self, mock_opensky_response):
        """Test that client retries on transient failure."""
        from src.ingestion.opensky_client import OpenSkyClient
        import requests

        with patch('requests.get') as mock_get:
            # First two calls fail, third succeeds
            mock_fail = Mock()
            mock_fail.raise_for_status.side_effect = requests.exceptions.HTTPError("503")

            mock_success = Mock()
            mock_success.ok = True
            mock_success.json.return_value = mock_opensky_response
            mock_success.raise_for_status = Mock()

            mock_get.side_effect = [mock_fail, mock_fail, mock_success]

            client = OpenSkyClient()
            result = client.get_states()

            assert result.time == mock_opensky_response["time"]
            assert mock_get.call_count == 3


class TestFallbackGenerator:
    """Tests for synthetic flight data generator."""

    def test_fallback_generates_valid_flights(self, sfo_bbox):
        """Test that generate_synthetic_flights returns valid data structure."""
        from src.ingestion.fallback import generate_synthetic_flights

        result = generate_synthetic_flights(count=10, bbox=sfo_bbox)

        assert "time" in result
        assert "states" in result
        assert len(result["states"]) == 10

        # Check first state has correct structure
        state = result["states"][0]
        assert len(state) == 18  # 18 fields per OpenSky state vector

        # Validate ICAO24 format (6 hex characters)
        icao24 = state[0]
        assert len(icao24) == 6
        assert all(c in "0123456789abcdef" for c in icao24)

        # Validate position is within bbox
        longitude = state[5]
        latitude = state[6]
        assert sfo_bbox["lomin"] <= longitude <= sfo_bbox["lomax"]
        assert sfo_bbox["lamin"] <= latitude <= sfo_bbox["lamax"]

    def test_fallback_uses_default_bbox(self):
        """Test that fallback works without explicit bbox."""
        from src.ingestion.fallback import generate_synthetic_flights

        result = generate_synthetic_flights(count=5)

        assert len(result["states"]) == 5


class TestCircuitBreaker:
    """Tests for API circuit breaker."""

    def test_circuit_breaker_opens_after_failures(self):
        """Test that circuit breaker opens after threshold failures."""
        from src.ingestion.circuit_breaker import APICircuitBreaker

        breaker = APICircuitBreaker(failure_threshold=5, recovery_timeout=60)

        # Should start closed
        assert breaker.state == "closed"
        assert breaker.can_execute() is True

        # Record failures up to threshold
        for i in range(4):
            breaker.record_failure()
            assert breaker.state == "closed"

        # 5th failure should open the circuit
        breaker.record_failure()
        assert breaker.state == "open"
        assert breaker.can_execute() is False

    def test_circuit_breaker_recovers_after_timeout(self):
        """Test that circuit breaker transitions to half-open after timeout."""
        from src.ingestion.circuit_breaker import APICircuitBreaker
        from datetime import datetime, timedelta

        breaker = APICircuitBreaker(failure_threshold=5, recovery_timeout=60)

        # Open the circuit
        for _ in range(5):
            breaker.record_failure()
        assert breaker.state == "open"

        # Simulate time passage by setting last_failure_time in the past
        breaker.last_failure_time = datetime.utcnow() - timedelta(seconds=61)

        # Should now allow execution (half-open)
        assert breaker.can_execute() is True
        assert breaker.state == "half-open"

    def test_circuit_breaker_closes_on_success(self):
        """Test that successful call closes the circuit."""
        from src.ingestion.circuit_breaker import APICircuitBreaker

        breaker = APICircuitBreaker(failure_threshold=5, recovery_timeout=60)

        # Record some failures (but not enough to open)
        for _ in range(3):
            breaker.record_failure()

        # Success should reset
        breaker.record_success()
        assert breaker.failures == 0
        assert breaker.state == "closed"


class TestPollJob:
    """Tests for poll and write job."""

    def test_poll_job_writes_to_landing(self, mock_landing_path, mock_opensky_response, sfo_bbox):
        """Test that poll_and_write creates JSON file in landing path."""
        from src.ingestion.poll_job import poll_and_write
        from src.ingestion.circuit_breaker import api_circuit_breaker

        # Reset circuit breaker state
        api_circuit_breaker.failures = 0
        api_circuit_breaker.state = "closed"

        with patch('src.ingestion.opensky_client.OpenSkyClient') as MockClient:
            mock_client = Mock()
            mock_client.get_states.return_value = Mock(
                time=mock_opensky_response["time"],
                states=mock_opensky_response["states"]
            )
            MockClient.return_value = mock_client

            count = poll_and_write(mock_landing_path, sfo_bbox)

            # Check file was created
            files = list(Path(mock_landing_path).glob("*.json"))
            assert len(files) == 1

            # Check content
            with open(files[0]) as f:
                data = json.load(f)

            assert "timestamp" in data
            assert "source" in data
            assert "states" in data
            assert data["source"] == "opensky"
            assert count == 2

    def test_poll_job_uses_fallback_when_circuit_open(self, mock_landing_path, sfo_bbox):
        """Test that poll_and_write uses synthetic data when circuit is open."""
        from src.ingestion.poll_job import poll_and_write
        from src.ingestion.circuit_breaker import api_circuit_breaker

        # Force circuit open
        api_circuit_breaker.failures = 5
        api_circuit_breaker.state = "open"

        count = poll_and_write(mock_landing_path, sfo_bbox)

        # Check file was created with synthetic source
        files = list(Path(mock_landing_path).glob("*.json"))
        assert len(files) == 1

        with open(files[0]) as f:
            data = json.load(f)

        assert data["source"] == "synthetic"
        assert count == 50  # Default synthetic count

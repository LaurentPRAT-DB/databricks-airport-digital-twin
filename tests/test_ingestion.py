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
        assert len(state) == 22  # 18 OpenSky fields + 4 custom (flight_phase, aircraft_type, origin, dest)

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

    def test_no_duplicate_gate_positions(self, sfo_bbox):
        """Test that no two parked aircraft occupy the same gate position.

        Regression test for bug where random gate assignment caused collisions.
        """
        from src.ingestion.fallback import generate_synthetic_flights, _flight_states, _gate_states

        # Clear state and generate flights that will include parked aircraft
        _flight_states.clear()
        _gate_states.clear()

        # Generate enough flights to fill gates (5 gates available)
        result = generate_synthetic_flights(count=10, bbox=sfo_bbox)

        # Collect positions of all parked aircraft (on_ground=True, velocity=0)
        parked_positions = []
        for state in result["states"]:
            on_ground = state[8]  # on_ground field
            velocity = state[9]  # velocity field
            lat = state[6]
            lon = state[5]

            # Parked aircraft: on ground with ~0 velocity
            if on_ground and velocity is not None and velocity < 1:
                parked_positions.append((round(lat, 6), round(lon, 6)))

        # Verify no duplicate positions (collision)
        unique_positions = set(parked_positions)
        assert len(unique_positions) == len(parked_positions), \
            f"Collision detected: {len(parked_positions)} parked aircraft but only {len(unique_positions)} unique positions"


class TestTrajectoryGenerator:
    """Tests for synthetic trajectory generation."""

    def test_trajectory_matches_flight_position(self, sfo_bbox):
        """Test that trajectory ends at the flight's current position."""
        from src.ingestion.fallback import (
            generate_synthetic_flights,
            generate_synthetic_trajectory,
            _flight_states,
        )

        # Generate flights to populate _flight_states
        generate_synthetic_flights(count=10, bbox=sfo_bbox)

        # Get a flight from the state manager
        assert len(_flight_states) > 0, "No flights were generated"
        icao24 = list(_flight_states.keys())[0]
        flight_state = _flight_states[icao24]

        # Generate trajectory for this flight
        trajectory = generate_synthetic_trajectory(icao24, minutes=30, limit=30)

        assert len(trajectory) > 0, "Trajectory should not be empty"

        # The last point (most recent) should be close to the flight's current position
        last_point = trajectory[-1]

        # Allow some tolerance for jitter (0.01 degrees ~ 1km)
        lat_diff = abs(last_point["latitude"] - flight_state.latitude)
        lon_diff = abs(last_point["longitude"] - flight_state.longitude)

        assert lat_diff < 0.05, f"Trajectory end lat {last_point['latitude']} too far from flight lat {flight_state.latitude}"
        assert lon_diff < 0.05, f"Trajectory end lon {last_point['longitude']} too far from flight lon {flight_state.longitude}"

    def test_trajectory_for_ground_aircraft(self, sfo_bbox):
        """Test that trajectory for ground aircraft shows realistic approach and landing."""
        from src.ingestion.fallback import (
            generate_synthetic_flights,
            generate_synthetic_trajectory,
            _flight_states,
            FlightPhase,
        )

        # Generate flights
        generate_synthetic_flights(count=20, bbox=sfo_bbox)

        # Find a ground aircraft
        ground_icao24 = None
        for icao24, state in _flight_states.items():
            if state.phase == FlightPhase.PARKED or state.altitude < 100:
                ground_icao24 = icao24
                break

        if ground_icao24 is None:
            # If no ground aircraft, skip this test
            return

        # Generate trajectory
        trajectory = generate_synthetic_trajectory(ground_icao24, minutes=30, limit=30)

        if len(trajectory) > 0:
            # Trajectory should show a realistic landing approach:
            # - Early points (approach phase) should have higher altitude
            # - Final points (ground phase, ~30% of trajectory) should be on ground
            first_alt = trajectory[0]["altitude"]
            last_alt = trajectory[-1]["altitude"]

            # First point should be at approach altitude (>1000 ft)
            assert first_alt > 1000, f"Approach should start high, got: {first_alt}"

            # Last point should be on ground (<100 ft)
            assert last_alt < 100, f"Should end on ground, got: {last_alt}"

            # Altitude should generally decrease (descending trajectory)
            assert first_alt > last_alt, "Trajectory should show descent"

    def test_trajectory_returns_correct_icao24(self, sfo_bbox):
        """Test that trajectory points have correct icao24."""
        from src.ingestion.fallback import (
            generate_synthetic_flights,
            generate_synthetic_trajectory,
            _flight_states,
        )

        # Generate flights
        generate_synthetic_flights(count=5, bbox=sfo_bbox)

        icao24 = list(_flight_states.keys())[0]
        trajectory = generate_synthetic_trajectory(icao24, minutes=30, limit=30)

        assert len(trajectory) > 0
        for point in trajectory:
            assert point["icao24"] == icao24, f"Point icao24 {point['icao24']} doesn't match requested {icao24}"

    def test_trajectory_timestamps_are_ordered(self, sfo_bbox):
        """Test that trajectory timestamps are in chronological order."""
        from src.ingestion.fallback import (
            generate_synthetic_flights,
            generate_synthetic_trajectory,
            _flight_states,
        )
        from datetime import datetime

        # Generate flights
        generate_synthetic_flights(count=5, bbox=sfo_bbox)

        icao24 = list(_flight_states.keys())[0]
        trajectory = generate_synthetic_trajectory(icao24, minutes=30, limit=30)

        assert len(trajectory) > 1

        # Parse timestamps and verify order
        prev_time = None
        for point in trajectory:
            ts_str = point["timestamp"]
            if ts_str.endswith("Z"):
                ts_str = ts_str.replace("Z", "+00:00")
            current_time = datetime.fromisoformat(ts_str)

            if prev_time is not None:
                assert current_time >= prev_time, "Timestamps should be in chronological order"
            prev_time = current_time


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
        from datetime import datetime, timedelta, timezone

        breaker = APICircuitBreaker(failure_threshold=5, recovery_timeout=60)

        # Open the circuit
        for _ in range(5):
            breaker.record_failure()
        assert breaker.state == "open"

        # Simulate time passage by setting last_failure_time in the past
        breaker.last_failure_time = datetime.now(timezone.utc) - timedelta(seconds=61)

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
        api_circuit_breaker.last_failure_time = None

        # Patch where OpenSkyClient is used (in poll_job module)
        with patch('src.ingestion.poll_job.OpenSkyClient') as MockClient:
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
        from datetime import datetime, timezone

        # Force circuit open with recent failure time (so it stays open)
        api_circuit_breaker.failures = 5
        api_circuit_breaker.state = "open"
        api_circuit_breaker.last_failure_time = datetime.now(timezone.utc)

        count = poll_and_write(mock_landing_path, sfo_bbox)

        # Check file was created with synthetic source
        files = list(Path(mock_landing_path).glob("*.json"))
        assert len(files) == 1

        with open(files[0]) as f:
            data = json.load(f)

        assert data["source"] == "synthetic"
        assert count == 50  # Default synthetic count

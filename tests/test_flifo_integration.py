"""Integration test: FLIFO mock server → flifo_client → flifo_mapper → schedule_service.

Requires mock server running on port 8089. Start with:
    uv run uvicorn tools.flifo_mock.server:app --port 8089
"""

import os
import pytest
import subprocess
import time

from src.ingestion.flifo_client import FlifoClient
from src.ingestion.flifo_mapper import map_flifo_response
from app.backend.services.flifo_service import FlifoService


@pytest.fixture(scope="module")
def mock_server():
    """Start FLIFO mock server for integration tests."""
    proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "tools.flifo_mock.server:app", "--port", "8099", "--log-level", "warning"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(3)
    yield proc
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture
def flifo_client():
    return FlifoClient(
        base_url="http://localhost:8099",
        client_id="test",
        client_secret="test",
    )


class TestFlifoIntegration:
    def test_full_pipeline_arrivals(self, mock_server, flifo_client):
        """Test: client → API → mapper → internal format."""
        raw = flifo_client.get_flights_by_airport("SFO", direction="arrival", limit=10)

        assert "flightRecords" in raw
        assert len(raw["flightRecords"]) > 0

        mapped = map_flifo_response(raw, "SFO", direction="arrival")
        assert len(mapped) > 0

        for flight in mapped:
            assert flight["flight_type"] == "arrival"
            assert flight["destination"] == "SFO"
            assert flight["flight_number"]
            assert flight["airline"]
            assert flight["scheduled_time"]
            assert flight["status"] in [
                "scheduled", "on_time", "delayed", "boarding",
                "final_call", "gate_closed", "departed", "arrived", "cancelled",
            ]
            assert flight["data_source"] == "flifo"

    def test_full_pipeline_departures(self, mock_server, flifo_client):
        raw = flifo_client.get_flights_by_airport("SFO", direction="departure", limit=10)
        mapped = map_flifo_response(raw, "SFO", direction="departure")
        assert len(mapped) > 0

        for flight in mapped:
            assert flight["flight_type"] == "departure"
            assert flight["origin"] == "SFO"

    def test_different_airports(self, mock_server, flifo_client):
        sfo = flifo_client.get_flights_by_airport("SFO", limit=5)
        fra = flifo_client.get_flights_by_airport("FRA", limit=5)

        sfo_numbers = {r["flightNumber"] for r in sfo["flightRecords"]}
        fra_numbers = {r["flightNumber"] for r in fra["flightRecords"]}
        # Different airports should have different flights (seeded differently)
        assert sfo_numbers != fra_numbers

    def test_auth_required(self, mock_server):
        bad_client = FlifoClient(
            base_url="http://localhost:8099",
            client_id="wrong",
            client_secret="wrong",
        )
        with pytest.raises(PermissionError):
            bad_client.get_flights_by_airport("SFO")

    def test_flifo_service_integration(self, mock_server):
        """Test FlifoService against live mock."""
        os.environ["FLIFO_BASE_URL"] = "http://localhost:8099"
        os.environ["FLIFO_CLIENT_ID"] = "test"
        os.environ["FLIFO_CLIENT_SECRET"] = "test"
        try:
            service = FlifoService()
            assert service.is_available

            result = service.get_schedule("SFO", flight_type="arrival", limit=15)
            assert result is not None
            assert len(result) > 0
            assert all(f["data_source"] == "flifo" for f in result)
            assert all(f["flight_type"] == "arrival" for f in result)
        finally:
            del os.environ["FLIFO_BASE_URL"]
            del os.environ["FLIFO_CLIENT_ID"]
            del os.environ["FLIFO_CLIENT_SECRET"]

    def test_mapped_fields_complete(self, mock_server, flifo_client):
        """Verify all expected fields are present in mapped output."""
        raw = flifo_client.get_flights_by_airport("SFO", direction="arrival", limit=20)
        mapped = map_flifo_response(raw, "SFO")

        required_keys = {
            "flight_number", "airline", "airline_code", "origin", "destination",
            "scheduled_time", "status", "flight_type", "data_source",
        }
        optional_keys = {
            "estimated_time", "actual_time", "gate", "terminal", "belt",
            "stand", "registration", "codeshares", "delay_minutes",
            "delay_reason", "aircraft_type",
        }

        for flight in mapped:
            for key in required_keys:
                assert key in flight, f"Missing required key: {key}"
                assert flight[key] is not None, f"Required key is None: {key}"
            for key in optional_keys:
                assert key in flight, f"Missing optional key: {key}"

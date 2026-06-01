"""Tests for FLIFO service layer."""

import pytest
from unittest.mock import patch, MagicMock

from app.backend.services.flifo_service import FlifoService


class TestFlifoService:
    @patch.dict("os.environ", {"FLIFO_BASE_URL": "", "FLIFO_CLIENT_ID": "", "FLIFO_CLIENT_SECRET": ""})
    def test_not_available_when_unconfigured(self):
        service = FlifoService()
        assert service.is_available is False
        assert service.get_schedule("SFO") is None

    @patch.dict("os.environ", {
        "FLIFO_BASE_URL": "http://localhost:8089",
        "FLIFO_CLIENT_ID": "test",
        "FLIFO_CLIENT_SECRET": "test",
    })
    def test_available_when_configured(self):
        service = FlifoService()
        assert service.is_available is True

    @patch.dict("os.environ", {
        "FLIFO_BASE_URL": "http://localhost:8089",
        "FLIFO_CLIENT_ID": "test",
        "FLIFO_CLIENT_SECRET": "test",
    })
    @patch("app.backend.services.flifo_service.FlifoClient")
    def test_get_schedule_returns_mapped_data(self, MockClient):
        mock_client = MockClient.return_value
        mock_client.is_configured = True
        mock_client.get_flights_by_airport.return_value = {
            "flightRecords": [{
                "flightNumber": "UA100",
                "airline": {"iataCode": "UA", "icaoCode": "UAL", "name": "United"},
                "departure": {"iataCode": "LAX", "icaoCode": "KLAX", "scheduledTime": "2026-06-01T10:00:00Z"},
                "arrival": {"iataCode": "SFO", "icaoCode": "KSFO", "scheduledTime": "2026-06-01T11:00:00Z",
                            "terminal": "1", "gate": "A1", "baggageBelt": "5"},
                "statusCode": "ON",
                "statusDescription": "On Time",
                "delayMinutes": 0,
                "aircraft": {"registration": "N999", "iataType": "738", "icaoType": "B738"},
                "codeshares": [],
                "updatedAt": "2026-06-01T09:00:00Z",
            }],
            "totalRecords": 1,
        }

        service = FlifoService()
        result = service.get_schedule("SFO", flight_type="arrival")
        assert result is not None
        assert len(result) == 1
        assert result[0]["flight_number"] == "UA100"
        assert result[0]["status"] == "on_time"
        assert result[0]["data_source"] == "flifo"

    @patch.dict("os.environ", {
        "FLIFO_BASE_URL": "http://localhost:8089",
        "FLIFO_CLIENT_ID": "test",
        "FLIFO_CLIENT_SECRET": "test",
    })
    @patch("app.backend.services.flifo_service.FlifoClient")
    def test_graceful_degradation_on_error(self, MockClient):
        mock_client = MockClient.return_value
        mock_client.is_configured = True
        mock_client.get_flights_by_airport.side_effect = ConnectionError("timeout")

        service = FlifoService()
        result = service.get_schedule("SFO")
        assert result is None

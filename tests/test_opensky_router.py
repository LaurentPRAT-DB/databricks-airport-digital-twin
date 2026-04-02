"""Tests for OpenSky API router endpoints."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.backend.api.opensky import opensky_router, _get_airport_center


# ── _get_airport_center ──

class TestGetAirportCenter:
    def test_from_reference_point(self):
        mock_service = MagicMock()
        mock_service.get_config.return_value = {
            "reference_point": {"latitude": 48.3538, "longitude": 11.7861},
        }

        with patch("app.backend.api.opensky.get_airport_config_service", return_value=mock_service):
            lat, lon = _get_airport_center()

        assert abs(lat - 48.3538) < 0.001
        assert abs(lon - 11.7861) < 0.001

    def test_from_camelcase_reference_point(self):
        mock_service = MagicMock()
        mock_service.get_config.return_value = {
            "referencePoint": {"latitude": 40.6413, "longitude": -73.7781},
        }

        with patch("app.backend.api.opensky.get_airport_config_service", return_value=mock_service):
            lat, lon = _get_airport_center()

        assert abs(lat - 40.6413) < 0.001

    def test_fallback_to_converter(self):
        mock_converter = MagicMock()
        mock_converter.reference_lat = 37.6213
        mock_converter.reference_lon = -122.379

        mock_service = MagicMock()
        mock_service.get_config.return_value = {}
        mock_service._converter = mock_converter

        with patch("app.backend.api.opensky.get_airport_config_service", return_value=mock_service):
            lat, lon = _get_airport_center()

        assert abs(lat - 37.6213) < 0.001
        assert abs(lon - (-122.379)) < 0.001

    def test_raises_503_when_no_airport(self):
        mock_service = MagicMock()
        mock_service.get_config.return_value = {}
        # Remove _converter so fallback also fails
        del mock_service._converter

        with patch("app.backend.api.opensky.get_airport_config_service", return_value=mock_service):
            with pytest.raises(HTTPException) as exc_info:
                _get_airport_center()

        assert exc_info.value.status_code == 503


# ── GET /api/opensky/flights ──

class TestGetOpenSkyFlights:
    @pytest.fixture
    def app(self):
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(opensky_router)
        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_returns_flights(self, client):
        mock_flights = [
            {"icao24": "abc123", "callsign": "UAL1", "latitude": 37.6, "longitude": -122.4},
            {"icao24": "def456", "callsign": "DAL2", "latitude": 37.7, "longitude": -122.3},
        ]
        mock_opensky = AsyncMock()
        mock_opensky.fetch_flights = AsyncMock(return_value=mock_flights)

        mock_config = MagicMock()
        mock_config.get_config.return_value = {
            "reference_point": {"latitude": 37.6213, "longitude": -122.379},
        }

        with patch("app.backend.api.opensky.get_opensky_service", return_value=mock_opensky), \
             patch("app.backend.api.opensky.get_airport_config_service", return_value=mock_config):
            resp = client.get("/api/opensky/flights")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert data["data_source"] == "opensky"
        assert len(data["flights"]) == 2

    def test_returns_empty_when_no_flights(self, client):
        mock_opensky = AsyncMock()
        mock_opensky.fetch_flights = AsyncMock(return_value=[])

        mock_config = MagicMock()
        mock_config.get_config.return_value = {
            "reference_point": {"latitude": 37.6213, "longitude": -122.379},
        }

        with patch("app.backend.api.opensky.get_opensky_service", return_value=mock_opensky), \
             patch("app.backend.api.opensky.get_airport_config_service", return_value=mock_config):
            resp = client.get("/api/opensky/flights")

        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_503_when_no_airport_loaded(self, client):
        mock_config = MagicMock()
        mock_config.get_config.return_value = {}
        del mock_config._converter

        with patch("app.backend.api.opensky.get_airport_config_service", return_value=mock_config):
            resp = client.get("/api/opensky/flights")

        assert resp.status_code == 503


# ── GET /api/opensky/status ──

class TestGetOpenSkyStatus:
    @pytest.fixture
    def app(self):
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(opensky_router)
        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_returns_status(self, client):
        mock_opensky = MagicMock()
        mock_opensky.get_status.return_value = {
            "available": True,
            "last_fetch_time": None,
            "last_flight_count": 0,
            "last_error": None,
            "authenticated": False,
        }

        with patch("app.backend.api.opensky.get_opensky_service", return_value=mock_opensky):
            resp = client.get("/api/opensky/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is True
        assert data["authenticated"] is False

    def test_status_reflects_authenticated(self, client):
        mock_opensky = MagicMock()
        mock_opensky.get_status.return_value = {
            "available": True,
            "last_fetch_time": "2026-04-02T10:00:00+00:00",
            "last_flight_count": 42,
            "last_error": None,
            "authenticated": True,
        }

        with patch("app.backend.api.opensky.get_opensky_service", return_value=mock_opensky):
            resp = client.get("/api/opensky/status")

        data = resp.json()
        assert data["authenticated"] is True
        assert data["last_flight_count"] == 42

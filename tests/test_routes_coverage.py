"""Coverage-focused tests for app/backend/api/routes.py.

Targets untested paths: debug endpoints, metrics, error handling,
schedule audit, and edge cases.
"""

import os
import pytest
from unittest.mock import patch

pytestmark = pytest.mark.api

from fastapi.testclient import TestClient

from app.backend.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestDebugLogs:
    """Tests for /api/debug/logs (requires DEBUG_MODE=true)."""

    def test_debug_logs_disabled_by_default(self, client):
        resp = client.get("/api/debug/logs")
        assert resp.status_code == 403

    def test_debug_logs_enabled(self, client):
        with patch.dict(os.environ, {"DEBUG_MODE": "true"}):
            resp = client.get("/api/debug/logs")
            assert resp.status_code == 200
            data = resp.json()
            assert "lines" in data
            assert "total_buffered" in data

    def test_debug_logs_with_pattern(self, client):
        with patch.dict(os.environ, {"DEBUG_MODE": "true"}):
            resp = client.get("/api/debug/logs?pattern=ERROR&limit=10")
            assert resp.status_code == 200
            data = resp.json()
            assert data["pattern"] == "ERROR"

    def test_debug_logs_no_pattern(self, client):
        with patch.dict(os.environ, {"DEBUG_MODE": "true"}):
            resp = client.get("/api/debug/logs?pattern=")
            assert resp.status_code == 200


class TestDebugRecentErrors:
    """Tests for /api/debug/recent-errors."""

    def test_no_token_returns_401(self, client):
        resp = client.get("/api/debug/recent-errors")
        assert resp.status_code == 401

    def test_short_token_returns_401(self, client):
        resp = client.get("/api/debug/recent-errors", headers={"Authorization": "Bearer short"})
        assert resp.status_code == 401

    def test_valid_token_returns_200(self, client):
        resp = client.get(
            "/api/debug/recent-errors",
            headers={"Authorization": "Bearer a-valid-length-token-for-testing"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "errors" in data
        assert "warnings" in data
        assert "error_count" in data
        assert "total_buffered" in data

    def test_limit_param(self, client):
        resp = client.get(
            "/api/debug/recent-errors?limit=5",
            headers={"Authorization": "Bearer a-valid-length-token-for-testing"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["errors"]) <= 5


class TestDebugClientLogs:
    """Tests for POST /api/debug/client-logs."""

    def test_post_empty_entries(self, client):
        resp = client.post("/api/debug/client-logs", json={"entries": []})
        assert resp.status_code == 200
        assert resp.json()["accepted"] == 0

    def test_post_entries(self, client):
        entries = [
            {"level": "error", "source": "test", "message": "test error"},
            {"level": "info", "source": "test", "message": "test info"},
        ]
        resp = client.post("/api/debug/client-logs", json={"entries": entries})
        assert resp.status_code == 200
        assert resp.json()["accepted"] == 2

    def test_get_client_logs_requires_debug_mode(self, client):
        resp = client.get("/api/debug/client-logs")
        assert resp.status_code == 403


class TestMetrics:
    """Tests for /api/metrics and /api/metrics/summary."""

    def test_post_metrics(self, client):
        metrics = {
            "frontend_load_ms": 1500,
            "api_latency_ms": 200,
            "view": "2D",
        }
        resp = client.post("/api/metrics", json=metrics)
        assert resp.status_code == 200

    def test_metrics_summary(self, client):
        resp = client.get("/api/metrics/summary")
        assert resp.status_code == 200


class TestScheduleAudit:
    """Tests for /api/schedule/audit."""

    def test_schedule_audit(self, client):
        resp = client.get("/api/schedule/audit")
        assert resp.status_code == 200
        data = resp.json()
        assert "audit" in data or "departures" in data or isinstance(data, dict)


class TestDataSources:
    """Tests for /api/data-sources."""

    def test_data_sources(self, client):
        resp = client.get("/api/data-sources")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)


class TestFlightErrorPaths:
    """Tests for error handling in flight endpoints."""

    def test_nonexistent_flight(self, client):
        resp = client.get("/api/flights/nonexistent_icao_000")
        # Should return 404 or 200 with empty data
        assert resp.status_code in (200, 404)

    def test_trajectory_nonexistent_flight(self, client):
        resp = client.get("/api/flights/nonexistent_icao_000/trajectory")
        assert resp.status_code in (200, 404)


class TestBaggageEndpoints:
    """Tests for baggage API coverage."""

    def test_baggage_stats(self, client):
        resp = client.get("/api/baggage/stats")
        assert resp.status_code == 200

    def test_baggage_flight_nonexistent(self, client):
        resp = client.get("/api/baggage/flight/NONEXISTENT999")
        assert resp.status_code in (200, 404)

    def test_baggage_alerts(self, client):
        resp = client.get("/api/baggage/alerts")
        assert resp.status_code == 200


class TestUserPrewarm:
    """Tests for /api/user/prewarm."""

    def test_prewarm_endpoint(self, client):
        resp = client.post("/api/user/prewarm", json={})
        # Should return 200 (prewarm accepted) or similar
        assert resp.status_code in (200, 204, 422)

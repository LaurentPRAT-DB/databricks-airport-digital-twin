"""Tests for the OpenSky ADS-B data collector service."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from app.backend.services.opensky_collector import (
    OpenSkyCollector,
    COLLECTOR_AIRPORTS,
)


# ── Configuration ──

class TestCollectorConfig:
    def test_default_airports(self):
        collector = OpenSkyCollector()
        assert collector.airport_count == 9

    def test_default_airports_include_required(self):
        required = {"KJFK", "KLAX", "KATL", "KORD", "KDEN", "KSFO", "OMAA", "LGAV", "LSGG"}
        assert required == set(COLLECTOR_AIRPORTS.keys())

    def test_custom_airports(self):
        custom = {"EGLL": (51.4775, -0.4614)}
        collector = OpenSkyCollector(airports=custom)
        assert collector.airport_count == 1

    def test_session_id_format(self):
        collector = OpenSkyCollector()
        assert collector.session_id.startswith("collector-")

    def test_not_running_initially(self):
        collector = OpenSkyCollector()
        assert collector.running is False


# ── Start / Stop ──

class TestCollectorLifecycle:
    async def test_start_sets_running(self):
        collector = OpenSkyCollector()
        with patch.object(collector, "_collect_loop", new_callable=AsyncMock):
            task = collector.start()
            assert collector.running is True
            assert task is not None
            await collector.stop()

    async def test_start_is_idempotent(self):
        collector = OpenSkyCollector()
        with patch.object(collector, "_collect_loop", new_callable=AsyncMock):
            task1 = collector.start()
            task2 = collector.start()
            assert task1 is task2
            await collector.stop()

    async def test_stop_sets_not_running(self):
        collector = OpenSkyCollector()
        with patch.object(collector, "_collect_loop", new_callable=AsyncMock):
            collector.start()
            await collector.stop()
            assert collector.running is False

    async def test_stop_when_not_started_is_noop(self):
        collector = OpenSkyCollector()
        await collector.stop()  # Should not raise
        assert collector.running is False


# ── Status ──

class TestCollectorStatus:
    def test_initial_status(self):
        collector = OpenSkyCollector()
        status = collector.get_status()
        assert status["running"] is False
        assert status["airport_count"] == 9
        assert status["total_snapshots"] == 0
        assert status["started_at"] is None
        assert len(status["airports"]) == 9

    async def test_status_after_start(self):
        collector = OpenSkyCollector()
        with patch.object(collector, "_collect_loop", new_callable=AsyncMock):
            collector.start()
            status = collector.get_status()
            assert status["running"] is True
            assert status["started_at"] is not None
            await collector.stop()

    def test_per_airport_status_structure(self):
        collector = OpenSkyCollector()
        status = collector.get_status()
        for icao, airport_stats in status["airports"].items():
            assert "snapshots_saved" in airport_stats
            assert "last_fetch_time" in airport_stats
            assert "last_flight_count" in airport_stats
            assert "last_error" in airport_stats
            assert "error_count" in airport_stats


# ── Collection loop ──

class TestCollectLoop:
    async def test_fetches_all_airports(self):
        """Collector cycles through all configured airports."""
        airports = {
            "KSFO": (37.6213, -122.379),
            "KJFK": (40.6413, -73.7781),
        }
        collector = OpenSkyCollector(airports=airports, inter_airport_delay=0)

        mock_opensky = AsyncMock()
        mock_opensky.fetch_flights = AsyncMock(return_value=[])
        mock_lakebase = MagicMock()
        mock_lakebase.is_available = False

        fetched_airports = []

        async def track_fetch(lat, lon):
            fetched_airports.append((round(lat, 4), round(lon, 4)))
            if len(fetched_airports) >= 2:
                collector._running = False
            return []

        mock_opensky.fetch_flights = track_fetch

        with patch("app.backend.services.opensky_service.get_opensky_service", return_value=mock_opensky):
            collector._running = True
            await collector._collect_loop()

        assert len(fetched_airports) == 2
        assert (37.6213, -122.379) in fetched_airports
        assert (40.6413, -73.7781) in fetched_airports

    async def test_persists_snapshots_to_lakebase(self):
        """Collected flights are written to Lakebase with data_source='opensky'."""
        airports = {"KSFO": (37.6213, -122.379)}
        collector = OpenSkyCollector(airports=airports, inter_airport_delay=0)

        mock_flights = [
            {"icao24": "abc123", "callsign": "UAL1", "latitude": 37.6,
             "longitude": -122.4, "altitude": 5000, "velocity": 200,
             "heading": 90, "vertical_rate": 0, "on_ground": False,
             "flight_phase": "enroute", "aircraft_type": None,
             "assigned_gate": None, "origin_airport": None,
             "destination_airport": None, "data_source": "opensky",
             "last_seen": 1700000000},
        ]

        call_count = 0

        async def fetch_once(lat, lon):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                collector._running = False
                return []
            return mock_flights

        mock_opensky = MagicMock()
        mock_opensky.fetch_flights = fetch_once

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = True
        mock_lakebase.insert_flight_snapshots = MagicMock(return_value=1)

        with patch("app.backend.services.opensky_service.get_opensky_service", return_value=mock_opensky), \
             patch("app.backend.services.lakebase_service.get_lakebase_service", return_value=mock_lakebase):
            collector._running = True
            await collector._collect_loop()

        mock_lakebase.insert_flight_snapshots.assert_called_once()
        args = mock_lakebase.insert_flight_snapshots.call_args
        snapshots = args[0][0]
        session_id = args[0][1]
        airport_icao = args[0][2]

        assert airport_icao == "KSFO"
        assert session_id.startswith("collector-")
        assert len(snapshots) == 1
        assert snapshots[0]["data_source"] == "opensky"
        assert snapshots[0]["icao24"] == "abc123"
        assert "snapshot_time" in snapshots[0]

    async def test_updates_stats_on_success(self):
        """Per-airport stats are updated after successful fetch."""
        airports = {"LGAV": (37.9364, 23.9445)}
        collector = OpenSkyCollector(airports=airports, inter_airport_delay=0)

        async def fetch_and_stop(lat, lon):
            collector._running = False  # Stop after first airport
            return [{"icao24": "abc123"}]

        mock_opensky = MagicMock()
        mock_opensky.fetch_flights = fetch_and_stop

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = True
        mock_lakebase.insert_flight_snapshots = MagicMock(return_value=1)

        with patch("app.backend.services.opensky_service.get_opensky_service", return_value=mock_opensky), \
             patch("app.backend.services.lakebase_service.get_lakebase_service", return_value=mock_lakebase):
            collector._running = True
            await collector._collect_loop()

        status = collector.get_status()
        lgav = status["airports"]["LGAV"]
        assert lgav["snapshots_saved"] == 1
        assert lgav["last_flight_count"] == 1
        assert lgav["last_fetch_time"] is not None
        assert lgav["last_error"] is None

    async def test_handles_fetch_error_gracefully(self):
        """Errors on one airport don't stop the loop."""
        airports = {
            "KSFO": (37.6213, -122.379),
            "KJFK": (40.6413, -73.7781),
        }
        collector = OpenSkyCollector(airports=airports, inter_airport_delay=0)

        call_count = 0

        async def failing_then_stop(lat, lon):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Network down")
            collector._running = False
            return []

        mock_opensky = MagicMock()
        mock_opensky.fetch_flights = failing_then_stop

        with patch("app.backend.services.opensky_service.get_opensky_service", return_value=mock_opensky):
            collector._running = True
            await collector._collect_loop()

        # First airport errored, but loop continued to second
        assert call_count == 2
        status = collector.get_status()
        ksfo = status["airports"]["KSFO"]
        assert ksfo["error_count"] == 1
        assert "Network down" in ksfo["last_error"]

    async def test_lakebase_unavailable_returns_zero(self):
        """When Lakebase is unavailable, persist returns 0 without error."""
        airports = {"KSFO": (37.6213, -122.379)}
        collector = OpenSkyCollector(airports=airports)

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = False

        with patch("app.backend.services.lakebase_service.get_lakebase_service", return_value=mock_lakebase):
            result = collector._persist_snapshots("KSFO", [{"icao24": "abc"}])

        assert result == 0


# ── Singleton ──

class TestCollectorSingleton:
    def test_returns_same_instance(self):
        from app.backend.services.opensky_collector import get_opensky_collector
        import app.backend.services.opensky_collector as mod
        mod._collector = None
        c1 = get_opensky_collector()
        c2 = get_opensky_collector()
        assert c1 is c2
        mod._collector = None  # cleanup


# ── API Endpoints ──

class TestCollectorAPI:
    @pytest.fixture
    def app(self):
        from fastapi import FastAPI
        from app.backend.api.collector import collector_router
        app = FastAPI()
        app.include_router(collector_router)
        return app

    @pytest.fixture
    def client(self, app):
        from fastapi.testclient import TestClient
        return TestClient(app)

    def test_get_status(self, client):
        mock_collector = MagicMock()
        mock_collector.get_status.return_value = {
            "running": True,
            "session_id": "collector-test",
            "started_at": "2026-04-02T10:00:00+00:00",
            "airport_count": 9,
            "total_snapshots": 42,
            "airports": {},
        }

        with patch("app.backend.api.collector.get_opensky_collector", return_value=mock_collector):
            resp = client.get("/api/collector/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is True
        assert data["total_snapshots"] == 42

    def test_start_collector(self, client):
        mock_collector = MagicMock()
        mock_collector.session_id = "collector-test"
        mock_collector.start.return_value = None

        with patch("app.backend.api.collector.get_opensky_collector", return_value=mock_collector):
            resp = client.post("/api/collector/start")

        assert resp.status_code == 200
        assert resp.json()["status"] == "running"
        mock_collector.start.assert_called_once()

    def test_stop_collector(self, client):
        mock_collector = AsyncMock()

        with patch("app.backend.api.collector.get_opensky_collector", return_value=mock_collector):
            resp = client.post("/api/collector/stop")

        assert resp.status_code == 200
        assert resp.json()["status"] == "stopped"

    def test_get_airports(self, client):
        mock_collector = MagicMock()
        mock_collector.get_status.return_value = {
            "running": True,
            "airports": {
                "KSFO": {"snapshots_saved": 100, "last_fetch_time": "2026-04-02T10:00:00+00:00", "last_flight_count": 15, "last_error": None, "error_count": 0},
                "KJFK": {"snapshots_saved": 200, "last_fetch_time": "2026-04-02T10:00:01+00:00", "last_flight_count": 20, "last_error": None, "error_count": 0},
            },
        }

        with patch("app.backend.api.collector.get_opensky_collector", return_value=mock_collector):
            resp = client.get("/api/collector/airports")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_airports"] == 2
        assert data["collector_running"] is True
        assert len(data["airports"]) == 2

"""Tests for Data Operations API routes."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.backend.main import app
from app.backend.services.data_ops_service import DataOpsStats, DataOpsService


# Use TestClient for sync tests
client = TestClient(app)


class TestGetDataOpsStats:
    """Tests for GET /api/data-ops/stats endpoint."""

    def test_get_stats_empty(self):
        """Test getting stats with no data."""
        mock_stats = DataOpsStats()

        mock_service = MagicMock()
        mock_service.get_stats.return_value = mock_stats

        with patch('app.backend.api.data_ops.get_data_ops_service', return_value=mock_service):
            response = client.get("/api/data-ops/stats")

        assert response.status_code == 200
        data = response.json()
        assert "acquisition" in data
        assert "sync" in data
        assert "freshness" in data
        assert data["sync"]["total"] == 0
        assert data["sync"]["last_sync"] is None

    def test_get_stats_with_data(self):
        """Test getting stats with populated data."""
        mock_stats = DataOpsStats(
            acquisition_by_source={"opensky": {"count": 10, "records": 100}},
            acquisition_by_endpoint={"/api/flights": {"count": 10, "records": 100}},
            total_syncs=5,
            successful_syncs=4,
            failed_syncs=1,
            total_records_synced=500,
            last_sync_time=datetime.now(timezone.utc),
            delta_staleness_seconds=30.0,
            lakebase_staleness_seconds=15.0,
            delta_record_count=100,
            lakebase_record_count=95,
        )

        mock_service = MagicMock()
        mock_service.get_stats.return_value = mock_stats

        with patch('app.backend.api.data_ops.get_data_ops_service', return_value=mock_service):
            response = client.get("/api/data-ops/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["sync"]["total"] == 5
        assert data["sync"]["successful"] == 4
        assert data["sync"]["failed"] == 1
        assert data["sync"]["total_records"] == 500
        assert data["freshness"]["delta"]["staleness_seconds"] == 30.0
        assert data["freshness"]["lakebase"]["record_count"] == 95


class TestGetRecentAcquisitions:
    """Tests for GET /api/data-ops/acquisitions endpoint."""

    def test_get_acquisitions_default_limit(self):
        """Test getting acquisitions with default limit."""
        mock_acquisitions = [
            {"timestamp": "2024-03-08T10:00:00Z", "source": "opensky", "endpoint": "/api/flights"},
        ]

        mock_service = MagicMock()
        mock_service.get_recent_acquisitions.return_value = mock_acquisitions

        with patch('app.backend.api.data_ops.get_data_ops_service', return_value=mock_service):
            response = client.get("/api/data-ops/acquisitions")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert len(data["acquisitions"]) == 1
        mock_service.get_recent_acquisitions.assert_called_once_with(limit=50)

    def test_get_acquisitions_custom_limit(self):
        """Test getting acquisitions with custom limit."""
        mock_service = MagicMock()
        mock_service.get_recent_acquisitions.return_value = []

        with patch('app.backend.api.data_ops.get_data_ops_service', return_value=mock_service):
            response = client.get("/api/data-ops/acquisitions?limit=100")

        assert response.status_code == 200
        mock_service.get_recent_acquisitions.assert_called_once_with(limit=100)

    def test_get_acquisitions_limit_validation(self):
        """Test that limit is validated."""
        # Test minimum
        response = client.get("/api/data-ops/acquisitions?limit=0")
        assert response.status_code == 422  # Validation error

        # Test maximum
        response = client.get("/api/data-ops/acquisitions?limit=300")
        assert response.status_code == 422  # Validation error


class TestGetRecentSyncs:
    """Tests for GET /api/data-ops/syncs endpoint."""

    def test_get_syncs_default_limit(self):
        """Test getting syncs with default limit."""
        mock_syncs = [
            {"timestamp": "2024-03-08T10:00:00Z", "direction": "delta_to_lakebase", "records_synced": 50},
        ]

        mock_service = MagicMock()
        mock_service.get_recent_syncs.return_value = mock_syncs

        with patch('app.backend.api.data_ops.get_data_ops_service', return_value=mock_service):
            response = client.get("/api/data-ops/syncs")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        mock_service.get_recent_syncs.assert_called_once_with(limit=50)

    def test_get_syncs_custom_limit(self):
        """Test getting syncs with custom limit."""
        mock_service = MagicMock()
        mock_service.get_recent_syncs.return_value = []

        with patch('app.backend.api.data_ops.get_data_ops_service', return_value=mock_service):
            response = client.get("/api/data-ops/syncs?limit=25")

        mock_service.get_recent_syncs.assert_called_once_with(limit=25)


class TestGetSyncValidationStatus:
    """Tests for GET /api/data-ops/sync-status endpoint."""

    def test_get_sync_status(self):
        """Test getting sync validation status."""
        mock_status = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "delta": {"record_count": 100},
            "lakebase": {"record_count": 98},
            "in_sync": True,
            "sync_lag_seconds": 5.0,
        }

        mock_service = MagicMock()
        mock_service.get_sync_validation_status.return_value = mock_status

        with patch('app.backend.api.data_ops.get_data_ops_service', return_value=mock_service):
            response = client.get("/api/data-ops/sync-status")

        assert response.status_code == 200
        data = response.json()
        assert data["in_sync"] is True
        assert data["sync_lag_seconds"] == 5.0


class TestCheckDataFreshness:
    """Tests for POST /api/data-ops/check-freshness endpoint."""

    def test_check_freshness_starts_background_task(self):
        """Test that freshness check triggers background task."""
        response = client.post("/api/data-ops/check-freshness")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "checking"
        assert "background" in data["message"].lower()


class TestGetDashboardData:
    """Tests for GET /api/data-ops/dashboard endpoint."""

    def test_get_dashboard_healthy(self):
        """Test getting dashboard data with healthy status."""
        mock_stats = DataOpsStats(
            acquisition_by_source={},
            total_syncs=10,
            successful_syncs=10,
            failed_syncs=0,
            delta_staleness_seconds=30,
            lakebase_staleness_seconds=30,
        )
        mock_sync_status = {"in_sync": True, "sync_lag_seconds": 5}

        mock_service = MagicMock()
        mock_service.get_stats.return_value = mock_stats
        mock_service.get_sync_validation_status.return_value = mock_sync_status
        mock_service.get_recent_acquisitions.return_value = []
        mock_service.get_recent_syncs.return_value = []

        with patch('app.backend.api.data_ops.get_data_ops_service', return_value=mock_service):
            response = client.get("/api/data-ops/dashboard")

        assert response.status_code == 200
        data = response.json()
        assert "health" in data
        assert data["health"]["sync"] == "healthy"
        assert data["health"]["freshness"] == "healthy"

    def test_get_dashboard_degraded_acquisition(self):
        """Test dashboard shows degraded acquisition health."""
        mock_stats = DataOpsStats(
            acquisition_by_source={
                "opensky": {"count": 100, "records": 1000, "errors": 15},
            },
            total_syncs=0,
            delta_staleness_seconds=100,
            lakebase_staleness_seconds=100,
        )

        mock_service = MagicMock()
        mock_service.get_stats.return_value = mock_stats
        mock_service.get_sync_validation_status.return_value = {}
        mock_service.get_recent_acquisitions.return_value = []
        mock_service.get_recent_syncs.return_value = []

        with patch('app.backend.api.data_ops.get_data_ops_service', return_value=mock_service):
            response = client.get("/api/data-ops/dashboard")

        assert response.status_code == 200
        data = response.json()
        assert data["health"]["acquisition"] == "degraded"

    def test_get_dashboard_unhealthy_acquisition(self):
        """Test dashboard shows unhealthy acquisition health."""
        mock_stats = DataOpsStats(
            acquisition_by_source={
                "opensky": {"count": 100, "records": 1000, "errors": 60},  # 60% error rate
            },
            total_syncs=0,
            delta_staleness_seconds=100,
            lakebase_staleness_seconds=100,
        )

        mock_service = MagicMock()
        mock_service.get_stats.return_value = mock_stats
        mock_service.get_sync_validation_status.return_value = {}
        mock_service.get_recent_acquisitions.return_value = []
        mock_service.get_recent_syncs.return_value = []

        with patch('app.backend.api.data_ops.get_data_ops_service', return_value=mock_service):
            response = client.get("/api/data-ops/dashboard")

        assert response.status_code == 200
        data = response.json()
        assert data["health"]["acquisition"] == "unhealthy"

    def test_get_dashboard_degraded_sync(self):
        """Test dashboard shows degraded sync health."""
        mock_stats = DataOpsStats(
            acquisition_by_source={},
            total_syncs=100,
            successful_syncs=85,  # 15% failure rate
            failed_syncs=15,
            delta_staleness_seconds=100,
            lakebase_staleness_seconds=100,
        )

        mock_service = MagicMock()
        mock_service.get_stats.return_value = mock_stats
        mock_service.get_sync_validation_status.return_value = {}
        mock_service.get_recent_acquisitions.return_value = []
        mock_service.get_recent_syncs.return_value = []

        with patch('app.backend.api.data_ops.get_data_ops_service', return_value=mock_service):
            response = client.get("/api/data-ops/dashboard")

        data = response.json()
        assert data["health"]["sync"] == "degraded"

    def test_get_dashboard_degraded_freshness(self):
        """Test dashboard shows degraded freshness health."""
        mock_stats = DataOpsStats(
            acquisition_by_source={},
            total_syncs=0,
            delta_staleness_seconds=400,  # > 5 minutes
            lakebase_staleness_seconds=100,
        )

        mock_service = MagicMock()
        mock_service.get_stats.return_value = mock_stats
        mock_service.get_sync_validation_status.return_value = {}
        mock_service.get_recent_acquisitions.return_value = []
        mock_service.get_recent_syncs.return_value = []

        with patch('app.backend.api.data_ops.get_data_ops_service', return_value=mock_service):
            response = client.get("/api/data-ops/dashboard")

        data = response.json()
        assert data["health"]["freshness"] == "degraded"

    def test_get_dashboard_unhealthy_freshness(self):
        """Test dashboard shows unhealthy freshness health."""
        mock_stats = DataOpsStats(
            acquisition_by_source={},
            total_syncs=0,
            delta_staleness_seconds=1000,  # > 15 minutes
            lakebase_staleness_seconds=100,
        )

        mock_service = MagicMock()
        mock_service.get_stats.return_value = mock_stats
        mock_service.get_sync_validation_status.return_value = {}
        mock_service.get_recent_acquisitions.return_value = []
        mock_service.get_recent_syncs.return_value = []

        with patch('app.backend.api.data_ops.get_data_ops_service', return_value=mock_service):
            response = client.get("/api/data-ops/dashboard")

        data = response.json()
        assert data["health"]["freshness"] == "unhealthy"


class TestResetSyntheticData:
    """Tests for POST /api/data-ops/reset-synthetic endpoint."""

    def test_reset_synthetic_success(self):
        """Test resetting synthetic data."""
        mock_result = {
            "flights_cleared": 5,
            "gates_cleared": 3,
            "runways_cleared": 1,
        }

        with patch('app.backend.api.data_ops.reset_synthetic_state', return_value=mock_result):
            response = client.post("/api/data-ops/reset-synthetic")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["flights_cleared"] == 5
        assert data["gates_cleared"] == 3


class TestGetHistorySyncStatus:
    """Tests for GET /api/data-ops/history-sync-status endpoint."""

    def test_history_sync_status_unavailable(self):
        """Test history sync status when delta service unavailable."""
        mock_delta_service = MagicMock()
        mock_delta_service.is_available = False

        with patch('app.backend.api.data_ops.get_delta_service', return_value=mock_delta_service):
            response = client.get("/api/data-ops/history-sync-status")

        assert response.status_code == 200
        data = response.json()
        assert data["available"] is False
        assert "error" in data

    def test_history_sync_status_available(self):
        """Test history sync status when delta service available."""
        mock_delta_service = MagicMock()
        mock_delta_service.is_available = True

        with patch('app.backend.api.data_ops.get_delta_service', return_value=mock_delta_service):
            response = client.get("/api/data-ops/history-sync-status")

        assert response.status_code == 200
        data = response.json()
        assert data["available"] is True
        assert data["history_table"] == "flight_positions_history"
        assert data["status"] == "configured"


class TestCheckFreshnessTask:
    """Tests for _check_freshness_task background function."""

    @pytest.mark.asyncio
    async def test_check_freshness_task_records_metrics(self):
        """Test that freshness task records metrics correctly."""
        from app.backend.api.data_ops import _check_freshness_task

        # Mock flight service response
        mock_flight = MagicMock()
        mock_flight.last_seen = 1709900000

        mock_flight_response = MagicMock()
        mock_flight_response.flights = [mock_flight]
        mock_flight_response.count = 10
        mock_flight_response.data_source = "lakebase"

        mock_flight_service = AsyncMock()
        mock_flight_service.get_flights.return_value = mock_flight_response

        # Mock delta service
        mock_delta_service = MagicMock()
        mock_delta_service.is_available = True
        mock_delta_service.get_flights.return_value = [{"last_seen": 1709900000}]

        # Mock data ops service
        mock_data_ops = MagicMock()

        with patch('app.backend.api.data_ops.get_data_ops_service', return_value=mock_data_ops):
            with patch('app.backend.api.data_ops.get_flight_service', return_value=mock_flight_service):
                with patch('app.backend.api.data_ops.get_delta_service', return_value=mock_delta_service):
                    await _check_freshness_task()

        # Should have recorded freshness for both sources
        assert mock_data_ops.record_freshness.call_count == 2
        assert mock_data_ops.record_acquisition.call_count == 2

    @pytest.mark.asyncio
    async def test_check_freshness_task_handles_lakebase_error(self):
        """Test that freshness task handles lakebase errors gracefully."""
        from app.backend.api.data_ops import _check_freshness_task

        mock_flight_service = AsyncMock()
        mock_flight_service.get_flights.side_effect = Exception("Lakebase error")

        mock_delta_service = MagicMock()
        mock_delta_service.is_available = False

        mock_data_ops = MagicMock()

        with patch('app.backend.api.data_ops.get_data_ops_service', return_value=mock_data_ops):
            with patch('app.backend.api.data_ops.get_flight_service', return_value=mock_flight_service):
                with patch('app.backend.api.data_ops.get_delta_service', return_value=mock_delta_service):
                    # Should not raise
                    await _check_freshness_task()

    @pytest.mark.asyncio
    async def test_check_freshness_task_handles_delta_error(self):
        """Test that freshness task handles delta errors gracefully."""
        from app.backend.api.data_ops import _check_freshness_task

        # Mock successful flight service
        mock_flight_response = MagicMock()
        mock_flight_response.flights = []
        mock_flight_response.count = 0
        mock_flight_response.data_source = "synthetic"

        mock_flight_service = AsyncMock()
        mock_flight_service.get_flights.return_value = mock_flight_response

        # Mock delta service with error
        mock_delta_service = MagicMock()
        mock_delta_service.is_available = True
        mock_delta_service.get_flights.side_effect = Exception("Delta error")

        mock_data_ops = MagicMock()

        with patch('app.backend.api.data_ops.get_data_ops_service', return_value=mock_data_ops):
            with patch('app.backend.api.data_ops.get_flight_service', return_value=mock_flight_service):
                with patch('app.backend.api.data_ops.get_delta_service', return_value=mock_delta_service):
                    # Should not raise
                    await _check_freshness_task()

    @pytest.mark.asyncio
    async def test_check_freshness_task_with_no_last_seen(self):
        """Test freshness task when flights have no last_seen."""
        from app.backend.api.data_ops import _check_freshness_task

        mock_flight = MagicMock()
        mock_flight.last_seen = None

        mock_flight_response = MagicMock()
        mock_flight_response.flights = [mock_flight]
        mock_flight_response.count = 1
        mock_flight_response.data_source = "synthetic"

        mock_flight_service = AsyncMock()
        mock_flight_service.get_flights.return_value = mock_flight_response

        mock_delta_service = MagicMock()
        mock_delta_service.is_available = False

        mock_data_ops = MagicMock()

        with patch('app.backend.api.data_ops.get_data_ops_service', return_value=mock_data_ops):
            with patch('app.backend.api.data_ops.get_flight_service', return_value=mock_flight_service):
                with patch('app.backend.api.data_ops.get_delta_service', return_value=mock_delta_service):
                    await _check_freshness_task()

        # Should still record freshness but with None time
        mock_data_ops.record_freshness.assert_called()

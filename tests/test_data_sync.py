"""Tests for data sync validation between Lakebase and Unity Catalog.

These tests verify:
1. Data operations service functionality
2. Sync metrics recording and retrieval
3. Freshness monitoring
4. Sync validation between Lakebase and Delta tables
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from app.backend.main import app
from app.backend.services.data_ops_service import (
    DataOpsService,
    DataAcquisitionMetric,
    SyncMetric,
    DataFreshnessMetric,
    get_data_ops_service,
)


class TestDataOpsService:
    """Tests for the DataOpsService class."""

    def test_service_initialization(self):
        """Test service initializes with empty metrics."""
        service = DataOpsService()
        stats = service.get_stats()

        assert stats.total_syncs == 0
        assert stats.successful_syncs == 0
        assert stats.failed_syncs == 0
        assert stats.acquisition_by_source == {}

    def test_record_acquisition(self):
        """Test recording data acquisition events."""
        service = DataOpsService()

        service.record_acquisition(
            source="opensky",
            endpoint="/api/flights",
            record_count=50,
            latency_ms=150.5,
            success=True,
        )

        acquisitions = service.get_recent_acquisitions(limit=10)
        assert len(acquisitions) == 1
        assert acquisitions[0]["source"] == "opensky"
        assert acquisitions[0]["endpoint"] == "/api/flights"
        assert acquisitions[0]["record_count"] == 50
        assert acquisitions[0]["success"] is True

    def test_record_acquisition_failure(self):
        """Test recording failed acquisition events."""
        service = DataOpsService()

        service.record_acquisition(
            source="opensky",
            endpoint="/api/flights",
            record_count=0,
            latency_ms=5000,
            success=False,
            error_message="Connection timeout",
        )

        acquisitions = service.get_recent_acquisitions(limit=10)
        assert acquisitions[0]["success"] is False
        assert acquisitions[0]["error"] == "Connection timeout"

    def test_record_sync(self):
        """Test recording sync operations."""
        service = DataOpsService()

        service.record_sync(
            direction="delta_to_lakebase",
            records_synced=100,
            records_failed=2,
            latency_ms=500,
            success=True,
            delta_count=100,
            lakebase_count=98,
        )

        syncs = service.get_recent_syncs(limit=10)
        assert len(syncs) == 1
        assert syncs[0]["direction"] == "delta_to_lakebase"
        assert syncs[0]["records_synced"] == 100
        assert syncs[0]["records_failed"] == 2
        assert syncs[0]["delta_count"] == 100
        assert syncs[0]["lakebase_count"] == 98

    def test_record_sync_failure(self):
        """Test recording failed sync operations."""
        service = DataOpsService()

        service.record_sync(
            direction="delta_to_lakebase",
            records_synced=0,
            records_failed=100,
            latency_ms=1000,
            success=False,
            error_message="Lakebase connection failed",
        )

        stats = service.get_stats()
        assert stats.total_syncs == 1
        assert stats.successful_syncs == 0
        assert stats.failed_syncs == 1

    def test_record_freshness(self):
        """Test recording data freshness metrics."""
        service = DataOpsService()
        now = datetime.now(timezone.utc)

        service.record_freshness(
            source="lakebase",
            latest_record_time=now - timedelta(seconds=30),
            record_count=50,
        )

        stats = service.get_stats()
        assert stats.lakebase_record_count == 50
        assert stats.lakebase_staleness_seconds >= 30
        assert stats.lakebase_staleness_seconds < 35  # Allow small variance

    def test_freshness_with_none_timestamp(self):
        """Test freshness recording when no latest record exists."""
        service = DataOpsService()

        service.record_freshness(
            source="delta",
            latest_record_time=None,
            record_count=0,
        )

        stats = service.get_stats()
        assert stats.delta_record_count == 0
        assert stats.delta_staleness_seconds == 0

    def test_get_stats_aggregation(self):
        """Test stats aggregation across multiple events."""
        service = DataOpsService()

        # Record multiple acquisitions
        for i in range(5):
            service.record_acquisition(
                source="synthetic",
                endpoint="/api/flights",
                record_count=50,
                latency_ms=100 + i * 10,
                success=True,
            )

        for i in range(3):
            service.record_acquisition(
                source="lakebase",
                endpoint="/api/flights",
                record_count=50,
                latency_ms=50 + i * 5,
                success=True,
            )

        stats = service.get_stats()
        assert stats.acquisition_by_source["synthetic"]["count"] == 5
        assert stats.acquisition_by_source["lakebase"]["count"] == 3
        assert stats.acquisition_by_endpoint["/api/flights"]["count"] == 8

    def test_sync_validation_status_no_data(self):
        """Test sync validation when no data available."""
        service = DataOpsService()
        status = service.get_sync_validation_status()

        assert status["in_sync"] is False
        assert status["delta"] is None
        assert status["lakebase"] is None

    def test_sync_validation_status_with_data(self):
        """Test sync validation with data from both sources."""
        service = DataOpsService()
        now = datetime.now(timezone.utc)

        # Both sources have similar data
        service.record_freshness(
            source="delta",
            latest_record_time=now - timedelta(seconds=10),
            record_count=100,
        )
        service.record_freshness(
            source="lakebase",
            latest_record_time=now - timedelta(seconds=15),
            record_count=98,
        )

        status = service.get_sync_validation_status()
        assert status["delta"]["record_count"] == 100
        assert status["lakebase"]["record_count"] == 98
        assert status["record_count_diff"] == 2
        assert status["sync_lag_seconds"] < 10  # 5 second difference
        assert status["in_sync"] is True  # Small lag, small count diff

    def test_sync_validation_out_of_sync(self):
        """Test sync validation when systems are out of sync."""
        service = DataOpsService()
        now = datetime.now(timezone.utc)

        # Delta is much newer than Lakebase
        service.record_freshness(
            source="delta",
            latest_record_time=now - timedelta(seconds=10),
            record_count=150,
        )
        service.record_freshness(
            source="lakebase",
            latest_record_time=now - timedelta(minutes=10),  # 10 minutes old
            record_count=100,
        )

        status = service.get_sync_validation_status()
        assert status["in_sync"] is False
        assert status["sync_lag_seconds"] > 300  # > 5 minutes

    def test_max_history_limit(self):
        """Test that metrics are limited to max history size."""
        service = DataOpsService(max_history=10)

        # Record more than max_history
        for i in range(20):
            service.record_acquisition(
                source="test",
                endpoint="/test",
                record_count=i,
                latency_ms=100,
                success=True,
            )

        acquisitions = service.get_recent_acquisitions(limit=100)
        assert len(acquisitions) == 10  # Limited to max_history


class TestDataOpsAPI:
    """Tests for Data Operations API endpoints."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_get_stats_endpoint(self, client):
        """Test /api/data-ops/stats endpoint."""
        response = client.get("/api/data-ops/stats")
        assert response.status_code == 200

        data = response.json()
        assert "acquisition" in data
        assert "sync" in data
        assert "freshness" in data

    def test_get_acquisitions_endpoint(self, client):
        """Test /api/data-ops/acquisitions endpoint."""
        response = client.get("/api/data-ops/acquisitions?limit=10")
        assert response.status_code == 200

        data = response.json()
        assert "count" in data
        assert "acquisitions" in data
        assert isinstance(data["acquisitions"], list)

    def test_get_syncs_endpoint(self, client):
        """Test /api/data-ops/syncs endpoint."""
        response = client.get("/api/data-ops/syncs?limit=10")
        assert response.status_code == 200

        data = response.json()
        assert "count" in data
        assert "syncs" in data

    def test_get_sync_status_endpoint(self, client):
        """Test /api/data-ops/sync-status endpoint."""
        response = client.get("/api/data-ops/sync-status")
        assert response.status_code == 200

        data = response.json()
        assert "checked_at" in data
        assert "in_sync" in data
        assert "delta" in data
        assert "lakebase" in data

    def test_get_dashboard_endpoint(self, client):
        """Test /api/data-ops/dashboard endpoint."""
        response = client.get("/api/data-ops/dashboard")
        assert response.status_code == 200

        data = response.json()
        assert "timestamp" in data
        assert "health" in data
        assert "summary" in data
        assert "sync_status" in data
        assert "recent_acquisitions" in data

    def test_dashboard_health_indicators(self, client):
        """Test dashboard health indicator calculation."""
        response = client.get("/api/data-ops/dashboard")
        data = response.json()

        health = data["health"]
        assert health["acquisition"] in ["healthy", "degraded", "unhealthy"]
        assert health["sync"] in ["healthy", "degraded", "unhealthy"]
        assert health["freshness"] in ["healthy", "degraded", "unhealthy"]
        assert health["overall"] in ["healthy", "degraded", "unhealthy"]

    def test_check_freshness_endpoint(self, client):
        """Test /api/data-ops/check-freshness endpoint."""
        response = client.post("/api/data-ops/check-freshness")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "checking"

    def test_history_sync_status_endpoint(self, client):
        """Test /api/data-ops/history-sync-status endpoint."""
        response = client.get("/api/data-ops/history-sync-status")
        assert response.status_code == 200

        data = response.json()
        assert "checked_at" in data
        assert "history_table" in data
        assert data["history_table"] == "flight_positions_history"


class TestSyncValidation:
    """Integration tests for sync validation between Lakebase and Unity Catalog."""

    def test_lakebase_delta_consistency_mock(self):
        """Test sync validation with mocked services."""
        service = DataOpsService()

        # Simulate successful sync
        service.record_sync(
            direction="delta_to_lakebase",
            records_synced=100,
            records_failed=0,
            latency_ms=500,
            success=True,
            delta_count=100,
            lakebase_count=100,
        )

        now = datetime.now(timezone.utc)
        service.record_freshness(
            source="delta",
            latest_record_time=now,
            record_count=100,
        )
        service.record_freshness(
            source="lakebase",
            latest_record_time=now,
            record_count=100,
        )

        status = service.get_sync_validation_status()
        assert status["in_sync"] is True
        assert status["record_count_diff"] == 0

    def test_detect_sync_drift(self):
        """Test detection of sync drift between systems."""
        service = DataOpsService()
        now = datetime.now(timezone.utc)

        # Simulate drift - Delta has more recent data
        service.record_freshness(
            source="delta",
            latest_record_time=now,
            record_count=120,  # More records
        )
        service.record_freshness(
            source="lakebase",
            latest_record_time=now - timedelta(minutes=15),  # Stale
            record_count=100,
        )

        status = service.get_sync_validation_status()
        assert status["in_sync"] is False
        assert status["record_count_diff"] == 20
        assert status["sync_lag_seconds"] > 800  # ~15 minutes

    def test_multiple_sync_tracking(self):
        """Test tracking multiple sync operations over time."""
        service = DataOpsService()

        # Simulate multiple syncs
        for i in range(5):
            service.record_sync(
                direction="delta_to_lakebase",
                records_synced=50 + i * 10,
                records_failed=i,
                latency_ms=500 + i * 50,
                success=i < 4,  # Last one fails
            )

        stats = service.get_stats()
        assert stats.total_syncs == 5
        assert stats.successful_syncs == 4
        assert stats.failed_syncs == 1
        assert stats.total_records_synced == sum(50 + i * 10 for i in range(5))

    def test_acquisition_by_source_tracking(self):
        """Test tracking acquisitions by different data sources."""
        service = DataOpsService()

        sources = ["opensky", "synthetic", "lakebase", "delta"]
        for source in sources:
            for _ in range(3):
                service.record_acquisition(
                    source=source,
                    endpoint="/api/flights",
                    record_count=50,
                    latency_ms=100,
                    success=True,
                )

        stats = service.get_stats()
        for source in sources:
            assert stats.acquisition_by_source[source]["count"] == 3
            assert stats.acquisition_by_source[source]["records"] == 150

    def test_endpoint_tracking(self):
        """Test tracking acquisitions by different endpoints."""
        service = DataOpsService()

        endpoints = [
            "/api/flights",
            "/api/trajectory",
            "/api/schedule/arrivals",
            "/api/weather/current",
        ]

        for endpoint in endpoints:
            service.record_acquisition(
                source="synthetic",
                endpoint=endpoint,
                record_count=10,
                latency_ms=50,
                success=True,
            )

        stats = service.get_stats()
        assert len(stats.acquisition_by_endpoint) == len(endpoints)


class TestDataFreshnessMonitoring:
    """Tests for data freshness monitoring."""

    def test_freshness_staleness_calculation(self):
        """Test staleness is calculated correctly."""
        service = DataOpsService()
        now = datetime.now(timezone.utc)

        # Record with known staleness
        staleness_seconds = 120
        service.record_freshness(
            source="delta",
            latest_record_time=now - timedelta(seconds=staleness_seconds),
            record_count=50,
        )

        stats = service.get_stats()
        # Allow 1 second variance for test execution time
        assert abs(stats.delta_staleness_seconds - staleness_seconds) < 2

    def test_freshness_alert_thresholds(self):
        """Test freshness health degrades based on staleness."""
        from app.backend.api.data_ops import router
        from fastapi.testclient import TestClient

        client = TestClient(app)
        service = get_data_ops_service()

        # Clear any existing data
        service._freshness_metrics.clear()

        # Record very stale data
        now = datetime.now(timezone.utc)
        service.record_freshness(
            source="delta",
            latest_record_time=now - timedelta(minutes=20),
            record_count=50,
        )
        service.record_freshness(
            source="lakebase",
            latest_record_time=now - timedelta(minutes=20),
            record_count=50,
        )

        response = client.get("/api/data-ops/dashboard")
        data = response.json()

        # With 20 minute staleness, freshness should be unhealthy
        assert data["health"]["freshness"] == "unhealthy"

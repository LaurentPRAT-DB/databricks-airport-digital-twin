"""Tests for DataOpsService - monitoring data operations and sync status."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from app.backend.services.data_ops_service import (
    DataOpsService,
    DataAcquisitionMetric,
    SyncMetric,
    DataFreshnessMetric,
    DataOpsStats,
    get_data_ops_service,
)


class TestDataAcquisitionMetric:
    """Tests for DataAcquisitionMetric dataclass."""

    def test_create_success_metric(self):
        """Test creating a successful acquisition metric."""
        metric = DataAcquisitionMetric(
            timestamp=datetime.now(timezone.utc),
            source="opensky",
            endpoint="/api/flights",
            record_count=10,
            latency_ms=150.5,
            success=True,
        )
        assert metric.source == "opensky"
        assert metric.record_count == 10
        assert metric.success is True
        assert metric.error_message is None

    def test_create_failure_metric(self):
        """Test creating a failed acquisition metric."""
        metric = DataAcquisitionMetric(
            timestamp=datetime.now(timezone.utc),
            source="delta",
            endpoint="/api/trajectory",
            record_count=0,
            latency_ms=5000.0,
            success=False,
            error_message="Connection timeout",
        )
        assert metric.success is False
        assert metric.error_message == "Connection timeout"


class TestSyncMetric:
    """Tests for SyncMetric dataclass."""

    def test_create_sync_metric(self):
        """Test creating a sync metric."""
        metric = SyncMetric(
            timestamp=datetime.now(timezone.utc),
            direction="delta_to_lakebase",
            records_synced=100,
            records_failed=2,
            latency_ms=2500.0,
            success=True,
            delta_count=150,
            lakebase_count=148,
        )
        assert metric.direction == "delta_to_lakebase"
        assert metric.records_synced == 100
        assert metric.records_failed == 2
        assert metric.delta_count == 150

    def test_create_failed_sync_metric(self):
        """Test creating a failed sync metric."""
        metric = SyncMetric(
            timestamp=datetime.now(timezone.utc),
            direction="lakebase_to_history",
            records_synced=0,
            records_failed=50,
            latency_ms=100.0,
            success=False,
            error_message="Database unavailable",
        )
        assert metric.success is False
        assert metric.error_message == "Database unavailable"


class TestDataFreshnessMetric:
    """Tests for DataFreshnessMetric dataclass."""

    def test_create_freshness_metric(self):
        """Test creating a freshness metric."""
        now = datetime.now(timezone.utc)
        metric = DataFreshnessMetric(
            timestamp=now,
            source="lakebase",
            latest_record_time=now - timedelta(seconds=30),
            staleness_seconds=30.0,
            record_count=500,
        )
        assert metric.source == "lakebase"
        assert metric.staleness_seconds == 30.0
        assert metric.record_count == 500


class TestDataOpsStats:
    """Tests for DataOpsStats dataclass."""

    def test_default_values(self):
        """Test default values for DataOpsStats."""
        stats = DataOpsStats()
        assert stats.acquisition_by_source == {}
        assert stats.acquisition_by_endpoint == {}
        assert stats.total_syncs == 0
        assert stats.successful_syncs == 0
        assert stats.failed_syncs == 0
        assert stats.total_records_synced == 0
        assert stats.last_sync_time is None
        assert stats.delta_staleness_seconds == 0
        assert stats.lakebase_staleness_seconds == 0


class TestDataOpsService:
    """Tests for DataOpsService class."""

    def test_init(self):
        """Test service initialization."""
        service = DataOpsService(max_history=100)
        assert service._max_history == 100
        assert len(service._acquisition_metrics) == 0
        assert len(service._sync_metrics) == 0
        assert len(service._freshness_metrics) == 0

    def test_record_acquisition_success(self):
        """Test recording a successful acquisition."""
        service = DataOpsService()
        service.record_acquisition(
            source="opensky",
            endpoint="/api/flights",
            record_count=15,
            latency_ms=200.0,
            success=True,
        )
        assert len(service._acquisition_metrics) == 1
        metric = service._acquisition_metrics[0]
        assert metric.source == "opensky"
        assert metric.record_count == 15
        assert metric.success is True

    def test_record_acquisition_failure(self):
        """Test recording a failed acquisition."""
        service = DataOpsService()
        service.record_acquisition(
            source="delta",
            endpoint="/api/trajectory",
            record_count=0,
            latency_ms=5000.0,
            success=False,
            error_message="Timeout",
        )
        metric = service._acquisition_metrics[0]
        assert metric.success is False
        assert metric.error_message == "Timeout"

    def test_record_acquisition_max_history(self):
        """Test that acquisition history is limited to max_history."""
        service = DataOpsService(max_history=5)
        for i in range(10):
            service.record_acquisition(
                source=f"source_{i}",
                endpoint="/api/flights",
                record_count=i,
                latency_ms=100.0,
            )
        # Should only keep last 5
        assert len(service._acquisition_metrics) == 5
        # First entry should be source_5 (oldest kept)
        assert service._acquisition_metrics[0].source == "source_5"

    def test_record_sync_success(self):
        """Test recording a successful sync."""
        service = DataOpsService()
        service.record_sync(
            direction="delta_to_lakebase",
            records_synced=100,
            records_failed=0,
            latency_ms=1500.0,
            success=True,
            delta_count=100,
            lakebase_count=100,
        )
        assert len(service._sync_metrics) == 1
        metric = service._sync_metrics[0]
        assert metric.direction == "delta_to_lakebase"
        assert metric.records_synced == 100
        assert metric.success is True

    def test_record_sync_failure(self):
        """Test recording a failed sync."""
        service = DataOpsService()
        service.record_sync(
            direction="lakebase_to_history",
            records_synced=0,
            records_failed=50,
            latency_ms=100.0,
            success=False,
            error_message="Connection refused",
        )
        metric = service._sync_metrics[0]
        assert metric.success is False
        assert metric.error_message == "Connection refused"

    def test_record_sync_max_history(self):
        """Test that sync history is limited to max_history."""
        service = DataOpsService(max_history=3)
        for i in range(5):
            service.record_sync(
                direction=f"dir_{i}",
                records_synced=i * 10,
                records_failed=0,
                latency_ms=100.0,
            )
        assert len(service._sync_metrics) == 3

    def test_record_freshness_with_timestamp(self):
        """Test recording freshness with a valid timestamp."""
        service = DataOpsService()
        now = datetime.now(timezone.utc)
        latest = now - timedelta(seconds=60)
        service.record_freshness(
            source="delta",
            latest_record_time=latest,
            record_count=200,
        )
        assert len(service._freshness_metrics) == 1
        metric = service._freshness_metrics[0]
        assert metric.source == "delta"
        assert metric.record_count == 200
        assert metric.staleness_seconds >= 59  # At least 59 seconds

    def test_record_freshness_without_timestamp(self):
        """Test recording freshness without a timestamp."""
        service = DataOpsService()
        service.record_freshness(
            source="lakebase",
            latest_record_time=None,
            record_count=0,
        )
        metric = service._freshness_metrics[0]
        assert metric.staleness_seconds == 0

    def test_record_freshness_naive_datetime(self):
        """Test recording freshness with naive datetime is handled.

        When a naive datetime is passed, the service treats it as UTC by
        adding timezone.utc. This may not match local time, but ensures
        consistent handling.
        """
        service = DataOpsService()
        # Use UTC time directly to avoid local/UTC conversion issues
        now_utc = datetime.now(timezone.utc)
        naive_time = datetime(
            now_utc.year, now_utc.month, now_utc.day,
            now_utc.hour, now_utc.minute, now_utc.second
        ) - timedelta(seconds=120)  # naive datetime 120s ago in UTC
        service.record_freshness(
            source="delta",
            latest_record_time=naive_time,
            record_count=50,
        )
        metric = service._freshness_metrics[0]
        # After converting naive to UTC, staleness should be ~120 seconds
        assert 115 <= metric.staleness_seconds <= 125

    def test_record_freshness_max_history(self):
        """Test that freshness history is limited to max_history."""
        service = DataOpsService(max_history=2)
        for i in range(5):
            service.record_freshness(
                source=f"source_{i}",
                latest_record_time=datetime.now(timezone.utc),
                record_count=i,
            )
        assert len(service._freshness_metrics) == 2

    def test_get_stats_empty(self):
        """Test getting stats with no data."""
        service = DataOpsService()
        stats = service.get_stats()
        assert stats.acquisition_by_source == {}
        assert stats.total_syncs == 0
        assert stats.last_sync_time is None

    def test_get_stats_with_acquisitions(self):
        """Test getting stats with acquisition data."""
        service = DataOpsService()
        # Add successful acquisitions
        service.record_acquisition("opensky", "/api/flights", 10, 100.0, success=True)
        service.record_acquisition("opensky", "/api/flights", 12, 150.0, success=True)
        # Add failed acquisition
        service.record_acquisition("delta", "/api/trajectory", 0, 5000.0, success=False)

        stats = service.get_stats()
        assert stats.acquisition_by_source["opensky"]["count"] == 2
        assert stats.acquisition_by_source["opensky"]["records"] == 22
        assert stats.acquisition_by_source["opensky"]["errors"] == 0
        assert stats.acquisition_by_source["delta"]["count"] == 1
        assert stats.acquisition_by_source["delta"]["errors"] == 1

    def test_get_stats_with_syncs(self):
        """Test getting stats with sync data."""
        service = DataOpsService()
        service.record_sync("delta_to_lakebase", 100, 0, 1000.0, success=True)
        service.record_sync("delta_to_lakebase", 50, 5, 500.0, success=True)
        service.record_sync("lakebase_to_history", 0, 10, 100.0, success=False)

        stats = service.get_stats()
        assert stats.total_syncs == 3
        assert stats.successful_syncs == 2
        assert stats.failed_syncs == 1
        assert stats.total_records_synced == 150
        assert stats.last_sync_time is not None

    def test_get_stats_with_freshness(self):
        """Test getting stats with freshness data."""
        service = DataOpsService()
        now = datetime.now(timezone.utc)

        # Delta freshness
        service.record_freshness("delta", now - timedelta(seconds=30), 100)
        # Lakebase freshness
        service.record_freshness("lakebase", now - timedelta(seconds=60), 90)

        stats = service.get_stats()
        assert 29 <= stats.delta_staleness_seconds <= 31
        assert 59 <= stats.lakebase_staleness_seconds <= 61
        assert stats.delta_record_count == 100
        assert stats.lakebase_record_count == 90

    def test_get_recent_acquisitions(self):
        """Test getting recent acquisitions."""
        service = DataOpsService()
        for i in range(10):
            service.record_acquisition(f"source_{i}", "/api/flights", i, 100.0)

        recent = service.get_recent_acquisitions(limit=5)
        assert len(recent) == 5
        # Should be in reverse order (most recent first)
        assert recent[0]["source"] == "source_9"
        assert recent[4]["source"] == "source_5"

    def test_get_recent_acquisitions_empty(self):
        """Test getting recent acquisitions when empty."""
        service = DataOpsService()
        recent = service.get_recent_acquisitions()
        assert recent == []

    def test_get_recent_syncs(self):
        """Test getting recent syncs."""
        service = DataOpsService()
        for i in range(10):
            service.record_sync(f"dir_{i}", i * 10, 0, 100.0)

        recent = service.get_recent_syncs(limit=3)
        assert len(recent) == 3
        # Should be in reverse order (most recent first)
        assert recent[0]["direction"] == "dir_9"
        assert recent[0]["records_synced"] == 90

    def test_get_recent_syncs_empty(self):
        """Test getting recent syncs when empty."""
        service = DataOpsService()
        recent = service.get_recent_syncs()
        assert recent == []

    def test_get_sync_validation_status_empty(self):
        """Test sync validation status with no data."""
        service = DataOpsService()
        status = service.get_sync_validation_status()
        assert status["delta"] is None
        assert status["lakebase"] is None
        assert status["in_sync"] is False

    def test_get_sync_validation_status_in_sync(self):
        """Test sync validation status when systems are in sync."""
        service = DataOpsService()
        now = datetime.now(timezone.utc)

        # Both systems have similar data
        service.record_freshness("delta", now - timedelta(seconds=10), 100)
        service.record_freshness("lakebase", now - timedelta(seconds=15), 102)

        status = service.get_sync_validation_status()
        assert status["delta"] is not None
        assert status["lakebase"] is not None
        assert status["record_count_diff"] == 2
        assert status["sync_lag_seconds"] == 5.0
        assert status["in_sync"] is True

    def test_get_sync_validation_status_out_of_sync(self):
        """Test sync validation status when systems are out of sync."""
        service = DataOpsService()
        now = datetime.now(timezone.utc)

        # Systems have large difference
        service.record_freshness("delta", now - timedelta(minutes=10), 100)
        service.record_freshness("lakebase", now - timedelta(seconds=30), 50)

        status = service.get_sync_validation_status()
        assert status["record_count_diff"] == 50
        assert status["sync_lag_seconds"] > 300  # More than 5 minutes
        assert status["in_sync"] is False

    def test_get_sync_validation_status_partial_data(self):
        """Test sync validation status with only delta data."""
        service = DataOpsService()
        now = datetime.now(timezone.utc)
        service.record_freshness("delta", now, 100)

        status = service.get_sync_validation_status()
        assert status["delta"] is not None
        assert status["lakebase"] is None
        assert status["in_sync"] is False
        assert status["record_count_diff"] is None

    def test_thread_safety(self):
        """Test that service operations are thread-safe."""
        import threading
        service = DataOpsService(max_history=100)
        errors = []

        def record_acquisitions():
            try:
                for i in range(50):
                    service.record_acquisition(f"source_{i}", "/api/flights", i, 100.0)
            except Exception as e:
                errors.append(e)

        def record_syncs():
            try:
                for i in range(50):
                    service.record_sync(f"dir_{i}", i * 10, 0, 100.0)
            except Exception as e:
                errors.append(e)

        def read_stats():
            try:
                for _ in range(50):
                    service.get_stats()
                    service.get_recent_acquisitions()
                    service.get_recent_syncs()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=record_acquisitions),
            threading.Thread(target=record_syncs),
            threading.Thread(target=read_stats),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


class TestGetDataOpsService:
    """Tests for get_data_ops_service singleton function."""

    def test_returns_singleton(self):
        """Test that get_data_ops_service returns same instance."""
        # Note: This uses the global singleton, so the instance may already exist
        service1 = get_data_ops_service()
        service2 = get_data_ops_service()
        assert service1 is service2

    def test_service_is_functional(self):
        """Test that singleton service is functional."""
        service = get_data_ops_service()
        # Should be able to call methods
        stats = service.get_stats()
        assert isinstance(stats, DataOpsStats)

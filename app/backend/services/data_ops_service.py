"""Data Operations Monitoring Service.

Tracks data acquisition from APIs/endpoints and sync operations
between Lakebase (PostgreSQL) and Unity Catalog (Delta tables).
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass, field
from collections import defaultdict
from threading import Lock

logger = logging.getLogger(__name__)


@dataclass
class DataAcquisitionMetric:
    """Metric for a single data acquisition event."""
    timestamp: datetime
    source: str  # 'opensky', 'synthetic', 'lakebase', 'delta'
    endpoint: str  # '/api/flights', '/api/trajectory', etc.
    record_count: int
    latency_ms: float
    success: bool
    error_message: Optional[str] = None


@dataclass
class SyncMetric:
    """Metric for a sync operation between Lakebase and Unity Catalog."""
    timestamp: datetime
    direction: str  # 'delta_to_lakebase', 'lakebase_to_history'
    records_synced: int
    records_failed: int
    latency_ms: float
    success: bool
    delta_count: Optional[int] = None  # Records in Delta at sync time
    lakebase_count: Optional[int] = None  # Records in Lakebase at sync time
    error_message: Optional[str] = None


@dataclass
class DataFreshnessMetric:
    """Metric for data freshness check."""
    timestamp: datetime
    source: str
    latest_record_time: Optional[datetime]
    staleness_seconds: float
    record_count: int


@dataclass
class DataOpsStats:
    """Aggregated data operations statistics."""
    # Acquisition stats by source
    acquisition_by_source: dict = field(default_factory=dict)
    acquisition_by_endpoint: dict = field(default_factory=dict)

    # Sync stats
    total_syncs: int = 0
    successful_syncs: int = 0
    failed_syncs: int = 0
    total_records_synced: int = 0
    last_sync_time: Optional[datetime] = None

    # Freshness stats
    delta_staleness_seconds: float = 0
    lakebase_staleness_seconds: float = 0
    delta_record_count: int = 0
    lakebase_record_count: int = 0


class DataOpsService:
    """Service for monitoring data operations and sync status."""

    def __init__(self, max_history: int = 1000):
        self._max_history = max_history
        self._acquisition_metrics: list[DataAcquisitionMetric] = []
        self._sync_metrics: list[SyncMetric] = []
        self._freshness_metrics: list[DataFreshnessMetric] = []
        self._lock = Lock()

        # Counters for quick access
        self._acquisition_counts = defaultdict(int)
        self._sync_counts = {"success": 0, "failed": 0, "total_records": 0}

    def record_acquisition(
        self,
        source: str,
        endpoint: str,
        record_count: int,
        latency_ms: float,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> None:
        """Record a data acquisition event."""
        metric = DataAcquisitionMetric(
            timestamp=datetime.now(timezone.utc),
            source=source,
            endpoint=endpoint,
            record_count=record_count,
            latency_ms=latency_ms,
            success=success,
            error_message=error_message,
        )

        with self._lock:
            self._acquisition_metrics.append(metric)
            if len(self._acquisition_metrics) > self._max_history:
                self._acquisition_metrics = self._acquisition_metrics[-self._max_history:]

            # Update counters
            self._acquisition_counts[f"{source}:{endpoint}"] += 1
            self._acquisition_counts[f"source:{source}"] += 1
            self._acquisition_counts[f"endpoint:{endpoint}"] += 1

        logger.debug(
            f"Data acquisition: {source} via {endpoint} - "
            f"{record_count} records in {latency_ms:.1f}ms"
        )

    def record_sync(
        self,
        direction: str,
        records_synced: int,
        records_failed: int,
        latency_ms: float,
        success: bool = True,
        delta_count: Optional[int] = None,
        lakebase_count: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Record a sync operation between Lakebase and Unity Catalog."""
        metric = SyncMetric(
            timestamp=datetime.now(timezone.utc),
            direction=direction,
            records_synced=records_synced,
            records_failed=records_failed,
            latency_ms=latency_ms,
            success=success,
            delta_count=delta_count,
            lakebase_count=lakebase_count,
            error_message=error_message,
        )

        with self._lock:
            self._sync_metrics.append(metric)
            if len(self._sync_metrics) > self._max_history:
                self._sync_metrics = self._sync_metrics[-self._max_history:]

            # Update counters
            self._sync_counts["success" if success else "failed"] += 1
            self._sync_counts["total_records"] += records_synced

        logger.info(
            f"Sync {direction}: {records_synced} records synced, "
            f"{records_failed} failed in {latency_ms:.1f}ms"
        )

    def record_freshness(
        self,
        source: str,
        latest_record_time: Optional[datetime],
        record_count: int,
    ) -> None:
        """Record data freshness check results."""
        now = datetime.now(timezone.utc)
        staleness = 0.0
        if latest_record_time:
            # Ensure timezone aware
            if latest_record_time.tzinfo is None:
                latest_record_time = latest_record_time.replace(tzinfo=timezone.utc)
            staleness = (now - latest_record_time).total_seconds()

        metric = DataFreshnessMetric(
            timestamp=now,
            source=source,
            latest_record_time=latest_record_time,
            staleness_seconds=staleness,
            record_count=record_count,
        )

        with self._lock:
            self._freshness_metrics.append(metric)
            if len(self._freshness_metrics) > self._max_history:
                self._freshness_metrics = self._freshness_metrics[-self._max_history:]

    def get_stats(self) -> DataOpsStats:
        """Get aggregated data operations statistics."""
        stats = DataOpsStats()

        with self._lock:
            # Aggregate acquisition stats
            source_counts = defaultdict(lambda: {"count": 0, "records": 0, "errors": 0})
            endpoint_counts = defaultdict(lambda: {"count": 0, "records": 0, "errors": 0})

            for m in self._acquisition_metrics:
                source_counts[m.source]["count"] += 1
                source_counts[m.source]["records"] += m.record_count
                if not m.success:
                    source_counts[m.source]["errors"] += 1

                endpoint_counts[m.endpoint]["count"] += 1
                endpoint_counts[m.endpoint]["records"] += m.record_count
                if not m.success:
                    endpoint_counts[m.endpoint]["errors"] += 1

            stats.acquisition_by_source = dict(source_counts)
            stats.acquisition_by_endpoint = dict(endpoint_counts)

            # Sync stats
            stats.total_syncs = len(self._sync_metrics)
            stats.successful_syncs = sum(1 for m in self._sync_metrics if m.success)
            stats.failed_syncs = stats.total_syncs - stats.successful_syncs
            stats.total_records_synced = sum(m.records_synced for m in self._sync_metrics)

            if self._sync_metrics:
                stats.last_sync_time = self._sync_metrics[-1].timestamp

            # Latest freshness
            delta_freshness = [m for m in self._freshness_metrics if m.source == "delta"]
            lakebase_freshness = [m for m in self._freshness_metrics if m.source == "lakebase"]

            if delta_freshness:
                latest = delta_freshness[-1]
                stats.delta_staleness_seconds = latest.staleness_seconds
                stats.delta_record_count = latest.record_count

            if lakebase_freshness:
                latest = lakebase_freshness[-1]
                stats.lakebase_staleness_seconds = latest.staleness_seconds
                stats.lakebase_record_count = latest.record_count

        return stats

    def get_recent_acquisitions(self, limit: int = 50) -> list[dict]:
        """Get recent data acquisition events."""
        with self._lock:
            recent = self._acquisition_metrics[-limit:]

        return [
            {
                "timestamp": m.timestamp.isoformat(),
                "source": m.source,
                "endpoint": m.endpoint,
                "record_count": m.record_count,
                "latency_ms": m.latency_ms,
                "success": m.success,
                "error": m.error_message,
            }
            for m in reversed(recent)
        ]

    def get_recent_syncs(self, limit: int = 50) -> list[dict]:
        """Get recent sync operations."""
        with self._lock:
            recent = self._sync_metrics[-limit:]

        return [
            {
                "timestamp": m.timestamp.isoformat(),
                "direction": m.direction,
                "records_synced": m.records_synced,
                "records_failed": m.records_failed,
                "latency_ms": m.latency_ms,
                "success": m.success,
                "delta_count": m.delta_count,
                "lakebase_count": m.lakebase_count,
                "error": m.error_message,
            }
            for m in reversed(recent)
        ]

    def get_sync_validation_status(self) -> dict:
        """
        Get sync validation status between Lakebase and Unity Catalog.

        Returns record counts and staleness for both systems to help
        identify sync issues.
        """
        with self._lock:
            delta_metrics = [m for m in self._freshness_metrics if m.source == "delta"]
            lakebase_metrics = [m for m in self._freshness_metrics if m.source == "lakebase"]

        delta_latest = delta_metrics[-1] if delta_metrics else None
        lakebase_latest = lakebase_metrics[-1] if lakebase_metrics else None

        status = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "delta": None,
            "lakebase": None,
            "in_sync": False,
            "sync_lag_seconds": None,
            "record_count_diff": None,
        }

        if delta_latest:
            status["delta"] = {
                "record_count": delta_latest.record_count,
                "latest_record": delta_latest.latest_record_time.isoformat() if delta_latest.latest_record_time else None,
                "staleness_seconds": delta_latest.staleness_seconds,
            }

        if lakebase_latest:
            status["lakebase"] = {
                "record_count": lakebase_latest.record_count,
                "latest_record": lakebase_latest.latest_record_time.isoformat() if lakebase_latest.latest_record_time else None,
                "staleness_seconds": lakebase_latest.staleness_seconds,
            }

        # Calculate sync status
        if delta_latest and lakebase_latest:
            status["record_count_diff"] = abs(delta_latest.record_count - lakebase_latest.record_count)

            if delta_latest.latest_record_time and lakebase_latest.latest_record_time:
                lag = abs((delta_latest.latest_record_time - lakebase_latest.latest_record_time).total_seconds())
                status["sync_lag_seconds"] = lag
                # Consider in sync if lag < 5 minutes and record counts similar
                status["in_sync"] = lag < 300 and status["record_count_diff"] < 10

        return status


# Singleton instance
_data_ops_service: Optional[DataOpsService] = None


def get_data_ops_service() -> DataOpsService:
    """Get or create DataOps service singleton."""
    global _data_ops_service
    if _data_ops_service is None:
        _data_ops_service = DataOpsService()
    return _data_ops_service

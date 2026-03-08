"""Data Operations API routes for monitoring and dashboard.

Provides endpoints for:
- Data acquisition metrics (API calls, latency, record counts)
- Sync status between Lakebase and Unity Catalog
- Data freshness monitoring
"""

import time
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query, BackgroundTasks

from app.backend.services.data_ops_service import get_data_ops_service
from app.backend.services.delta_service import get_delta_service
from app.backend.services.flight_service import get_flight_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/data-ops", tags=["data-ops"])


@router.get("/stats")
async def get_data_ops_stats() -> dict:
    """
    Get aggregated data operations statistics.

    Returns summary of data acquisition and sync operations including:
    - Acquisition counts by source and endpoint
    - Sync success/failure rates
    - Total records synced
    - Last sync timestamp
    """
    service = get_data_ops_service()
    stats = service.get_stats()

    return {
        "acquisition": {
            "by_source": stats.acquisition_by_source,
            "by_endpoint": stats.acquisition_by_endpoint,
        },
        "sync": {
            "total": stats.total_syncs,
            "successful": stats.successful_syncs,
            "failed": stats.failed_syncs,
            "total_records": stats.total_records_synced,
            "last_sync": stats.last_sync_time.isoformat() if stats.last_sync_time else None,
        },
        "freshness": {
            "delta": {
                "staleness_seconds": stats.delta_staleness_seconds,
                "record_count": stats.delta_record_count,
            },
            "lakebase": {
                "staleness_seconds": stats.lakebase_staleness_seconds,
                "record_count": stats.lakebase_record_count,
            },
        },
    }


@router.get("/acquisitions")
async def get_recent_acquisitions(
    limit: int = Query(default=50, ge=1, le=200, description="Number of records"),
) -> dict:
    """
    Get recent data acquisition events.

    Returns list of recent API calls with source, endpoint, latency,
    and record counts.
    """
    service = get_data_ops_service()
    acquisitions = service.get_recent_acquisitions(limit=limit)

    return {
        "count": len(acquisitions),
        "acquisitions": acquisitions,
    }


@router.get("/syncs")
async def get_recent_syncs(
    limit: int = Query(default=50, ge=1, le=200, description="Number of records"),
) -> dict:
    """
    Get recent sync operations.

    Returns list of sync operations between Lakebase and Unity Catalog
    with record counts, success status, and timing.
    """
    service = get_data_ops_service()
    syncs = service.get_recent_syncs(limit=limit)

    return {
        "count": len(syncs),
        "syncs": syncs,
    }


@router.get("/sync-status")
async def get_sync_validation_status() -> dict:
    """
    Get current sync validation status between Lakebase and Unity Catalog.

    Compares record counts and latest timestamps to determine if
    systems are in sync.

    Returns:
    - Record counts for both systems
    - Latest record timestamps
    - Staleness metrics
    - Overall sync status (in_sync: true/false)
    - Sync lag in seconds
    """
    service = get_data_ops_service()
    return service.get_sync_validation_status()


@router.post("/check-freshness")
async def check_data_freshness(background_tasks: BackgroundTasks) -> dict:
    """
    Trigger a data freshness check for all sources.

    Queries both Lakebase and Delta tables to update freshness metrics.
    This runs in the background to avoid blocking.
    """
    background_tasks.add_task(_check_freshness_task)
    return {
        "status": "checking",
        "message": "Freshness check started in background",
    }


async def _check_freshness_task():
    """Background task to check data freshness."""
    data_ops = get_data_ops_service()
    flight_service = get_flight_service()
    delta_service = get_delta_service()

    # Check Lakebase via flight service
    try:
        start = time.time()
        response = await flight_service.get_flights(count=1)
        latency = (time.time() - start) * 1000

        if response.flights:
            latest_time = None
            if hasattr(response.flights[0], 'last_seen') and response.flights[0].last_seen:
                latest_time = datetime.fromtimestamp(response.flights[0].last_seen, tz=timezone.utc)

            data_ops.record_freshness(
                source="lakebase",
                latest_record_time=latest_time,
                record_count=response.count,
            )
            data_ops.record_acquisition(
                source=response.data_source or "unknown",
                endpoint="/api/flights",
                record_count=response.count,
                latency_ms=latency,
                success=True,
            )
    except Exception as e:
        logger.warning(f"Lakebase freshness check failed: {e}")

    # Check Delta tables
    if delta_service.is_available:
        try:
            start = time.time()
            flights = delta_service.get_flights(limit=1)
            latency = (time.time() - start) * 1000

            if flights:
                latest_time = None
                if flights[0].get("last_seen"):
                    latest_time = datetime.fromtimestamp(flights[0]["last_seen"], tz=timezone.utc)

                data_ops.record_freshness(
                    source="delta",
                    latest_record_time=latest_time,
                    record_count=len(flights),
                )
                data_ops.record_acquisition(
                    source="delta",
                    endpoint="unity_catalog",
                    record_count=len(flights),
                    latency_ms=latency,
                    success=True,
                )
        except Exception as e:
            logger.warning(f"Delta freshness check failed: {e}")


@router.get("/dashboard")
async def get_dashboard_data() -> dict:
    """
    Get all data for the Data Operations Dashboard.

    Combines stats, sync status, and recent operations into a single
    response optimized for dashboard rendering.
    """
    service = get_data_ops_service()

    stats = service.get_stats()
    sync_status = service.get_sync_validation_status()
    recent_acquisitions = service.get_recent_acquisitions(limit=20)
    recent_syncs = service.get_recent_syncs(limit=10)

    # Calculate health indicators
    acquisition_health = "healthy"
    if stats.acquisition_by_source:
        total_errors = sum(
            s.get("errors", 0) for s in stats.acquisition_by_source.values()
        )
        total_calls = sum(
            s.get("count", 0) for s in stats.acquisition_by_source.values()
        )
        if total_calls > 0 and total_errors / total_calls > 0.1:
            acquisition_health = "degraded"
        if total_calls > 0 and total_errors / total_calls > 0.5:
            acquisition_health = "unhealthy"

    sync_health = "healthy"
    if stats.total_syncs > 0:
        failure_rate = stats.failed_syncs / stats.total_syncs
        if failure_rate > 0.1:
            sync_health = "degraded"
        if failure_rate > 0.5:
            sync_health = "unhealthy"

    freshness_health = "healthy"
    max_staleness = max(stats.delta_staleness_seconds, stats.lakebase_staleness_seconds)
    if max_staleness > 300:  # > 5 minutes
        freshness_health = "degraded"
    if max_staleness > 900:  # > 15 minutes
        freshness_health = "unhealthy"

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "health": {
            "acquisition": acquisition_health,
            "sync": sync_health,
            "freshness": freshness_health,
            "overall": "healthy" if all(
                h == "healthy" for h in [acquisition_health, sync_health, freshness_health]
            ) else "degraded" if any(
                h == "unhealthy" for h in [acquisition_health, sync_health, freshness_health]
            ) else "degraded",
        },
        "summary": {
            "total_acquisitions": sum(
                s.get("count", 0) for s in stats.acquisition_by_source.values()
            ),
            "total_records_acquired": sum(
                s.get("records", 0) for s in stats.acquisition_by_source.values()
            ),
            "total_syncs": stats.total_syncs,
            "records_synced": stats.total_records_synced,
            "last_sync": stats.last_sync_time.isoformat() if stats.last_sync_time else None,
        },
        "sync_status": sync_status,
        "sources": stats.acquisition_by_source,
        "endpoints": stats.acquisition_by_endpoint,
        "recent_acquisitions": recent_acquisitions,
        "recent_syncs": recent_syncs,
    }


@router.get("/history-sync-status")
async def get_history_sync_status() -> dict:
    """
    Get sync status for historical data layer (Unity Catalog).

    Returns information about data being synced to the
    flight_positions_history table for trajectory and analytics.
    """
    delta_service = get_delta_service()

    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "history_table": "flight_positions_history",
        "available": delta_service.is_available,
        "latest_record": None,
        "record_count": None,
        "time_range": None,
    }

    if not delta_service.is_available:
        result["error"] = "Delta service not available"
        return result

    # Try to query history table stats
    try:
        # This would query the history table if connected
        # For now, return placeholder indicating the table exists
        result["status"] = "configured"
        result["note"] = "History table configured in Unity Catalog"
    except Exception as e:
        result["error"] = str(e)

    return result

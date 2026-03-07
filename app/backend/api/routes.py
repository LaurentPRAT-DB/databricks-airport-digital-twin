"""REST API routes for the Airport Digital Twin."""

import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from app.backend.models.flight import (
    FlightListResponse,
    FlightPosition,
    TrajectoryPoint,
    TrajectoryResponse,
)
from app.backend.services.flight_service import FlightService, get_flight_service
from app.backend.services.delta_service import get_delta_service
from src.ingestion.fallback import generate_synthetic_trajectory


router = APIRouter(prefix="/api", tags=["flights"])


@router.get("/flights", response_model=FlightListResponse)
async def get_flights(
    count: int = Query(default=50, ge=1, le=500, description="Number of flights"),
    service: FlightService = Depends(get_flight_service),
) -> FlightListResponse:
    """
    Get current flight positions.

    Returns a list of flight positions with their current status.
    """
    return await service.get_flights(count=count)


@router.get("/flights/{icao24}", response_model=FlightPosition)
async def get_flight(
    icao24: str,
    service: FlightService = Depends(get_flight_service),
) -> FlightPosition:
    """
    Get a specific flight by ICAO24 address.

    Args:
        icao24: The ICAO24 address (hex) of the aircraft.

    Returns:
        Flight position data if found.

    Raises:
        404: If flight not found.
    """
    flight = await service.get_flight_by_icao24(icao24)
    if flight is None:
        raise HTTPException(status_code=404, detail=f"Flight {icao24} not found")
    return flight


@router.get("/flights/{icao24}/trajectory", response_model=TrajectoryResponse)
async def get_flight_trajectory(
    icao24: str,
    minutes: int = Query(default=60, ge=1, le=1440, description="Minutes of history"),
    limit: int = Query(default=1000, ge=1, le=5000, description="Max points to return"),
) -> TrajectoryResponse:
    """
    Get trajectory history for a specific flight.

    Returns a time-series of positions for trajectory visualization,
    analytics, and ML training. In mock mode, returns synthetic trajectory.
    In live mode, queries Unity Catalog Delta tables.

    Args:
        icao24: The ICAO24 address (hex) of the aircraft.
        minutes: How many minutes of history to retrieve (default: 60, max: 1440/24h).
        limit: Maximum number of points to return (default: 1000).

    Returns:
        Trajectory with list of positions ordered by time.

    Raises:
        404: If no trajectory data found for this flight.
    """
    use_mock = os.getenv("USE_MOCK_BACKEND", "true").lower() == "true"
    trajectory_data = None

    # Try Delta tables first if not in mock mode
    if not use_mock:
        delta = get_delta_service()
        trajectory_data = delta.get_trajectory(icao24, minutes=minutes, limit=limit)

    # Fall back to synthetic trajectory if no data or in mock mode
    if trajectory_data is None or len(trajectory_data) == 0:
        trajectory_data = generate_synthetic_trajectory(icao24, minutes=minutes, limit=limit)

    if trajectory_data is None or len(trajectory_data) == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No trajectory data found for flight {icao24}"
        )

    # Parse timestamps - convert to Unix timestamp (int)
    for p in trajectory_data:
        ts = p.get("timestamp")
        if isinstance(ts, str):
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            p["timestamp"] = int(dt.timestamp())
        elif isinstance(ts, datetime):
            p["timestamp"] = int(ts.timestamp())

    points = [TrajectoryPoint(**p) for p in trajectory_data]
    callsign = points[0].callsign if points else None

    return TrajectoryResponse(
        icao24=icao24,
        callsign=callsign,
        points=points,
        count=len(points),
        start_time=points[0].timestamp if points else None,
        end_time=points[-1].timestamp if points else None,
    )


@router.get("/data-sources")
async def get_data_sources_status(
    service: FlightService = Depends(get_flight_service),
) -> dict:
    """
    Get status of all data sources.

    Returns availability and health of:
    - Lakebase (PostgreSQL)
    - Delta tables (Databricks SQL)
    - Synthetic fallback
    """
    return service.get_data_sources_status()


# In-memory storage for web vitals (in production, use a proper store)
_web_vitals_buffer: list = []
_MAX_BUFFER_SIZE = 1000


@router.post("/metrics")
async def collect_web_vitals(request_data: dict) -> dict:
    """
    Collect Web Vitals metrics from frontend.

    Receives Core Web Vitals (LCP, INP, CLS, FCP, TTFB) from real users.
    These metrics help monitor real user experience and identify
    performance regressions.

    In production, these would be sent to a monitoring service
    like Datadog, New Relic, or stored in Delta tables for analysis.
    """
    global _web_vitals_buffer

    metric = {
        "name": request_data.get("name"),
        "value": request_data.get("value"),
        "rating": request_data.get("rating"),
        "delta": request_data.get("delta"),
        "id": request_data.get("id"),
        "navigationType": request_data.get("navigationType"),
        "timestamp": request_data.get("timestamp"),
        "received_at": datetime.utcnow().isoformat(),
    }

    # Add to buffer (simple in-memory store)
    _web_vitals_buffer.append(metric)
    if len(_web_vitals_buffer) > _MAX_BUFFER_SIZE:
        _web_vitals_buffer = _web_vitals_buffer[-_MAX_BUFFER_SIZE:]

    return {"status": "ok", "count": len(_web_vitals_buffer)}


@router.get("/metrics/summary")
async def get_web_vitals_summary() -> dict:
    """
    Get summary of collected Web Vitals metrics.

    Returns aggregated statistics for each metric type,
    useful for dashboards and performance monitoring.
    """
    from collections import defaultdict

    if not _web_vitals_buffer:
        return {"message": "No metrics collected yet", "metrics": {}}

    # Group by metric name
    by_name = defaultdict(list)
    for m in _web_vitals_buffer:
        if m.get("name") and m.get("value") is not None:
            by_name[m["name"]].append(m["value"])

    # Calculate p75 for each metric (used by CrUX)
    summary = {}
    for name, values in by_name.items():
        sorted_vals = sorted(values)
        count = len(sorted_vals)
        p75_idx = int(count * 0.75)
        summary[name] = {
            "count": count,
            "min": round(min(values), 2),
            "max": round(max(values), 2),
            "avg": round(sum(values) / count, 2),
            "p75": round(sorted_vals[p75_idx] if p75_idx < count else sorted_vals[-1], 2),
        }

    return {
        "total_metrics": len(_web_vitals_buffer),
        "metrics": summary,
    }

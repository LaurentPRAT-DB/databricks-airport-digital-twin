"""REST API routes — flights, metrics, user prewarm."""

import asyncio
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.backend.models.flight import (
    FlightListResponse,
    FlightPosition,
    TrajectoryPoint,
    TrajectoryResponse,
)
from app.backend.demo_config import DEFAULT_FLIGHT_COUNT
from app.backend.services.flight_service import FlightService, get_flight_service
from app.backend.services.delta_service import get_delta_service
from app.backend.services.lakebase_service import get_lakebase_service
from app.backend.services.airport_config_service import get_airport_config_service
from app.backend.api.deps import get_current_user
from src.ingestion.fallback import generate_synthetic_trajectory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["flights"])


@router.get("/flights", response_model=FlightListResponse)
async def get_flights(
    count: int = Query(default=DEFAULT_FLIGHT_COUNT, ge=1, le=500, description="Number of flights"),
    service: FlightService = Depends(get_flight_service),
) -> FlightListResponse:
    """Get current flight positions."""
    try:
        return await service.get_flights(count=count)
    except Exception as e:
        logger.error(f"Failed to get flights: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Flight service error: {str(e)}")


@router.get("/flights/{icao24}", response_model=FlightPosition)
async def get_flight(
    icao24: str,
    service: FlightService = Depends(get_flight_service),
) -> FlightPosition:
    """Get a specific flight by ICAO24 address."""
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
    """Get trajectory history for a specific flight."""
    trajectory_data = None

    delta = get_delta_service()
    if delta.is_available:
        trajectory_data = delta.get_trajectory(icao24, minutes=minutes, limit=limit)

    if trajectory_data is None or len(trajectory_data) == 0:
        trajectory_data = generate_synthetic_trajectory(icao24, minutes=minutes, limit=limit)

    if trajectory_data is None or len(trajectory_data) == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No trajectory data found for flight {icao24}"
        )

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
    """Get status of all data sources."""
    return service.get_data_sources_status()


# In-memory storage for web vitals (in production, use a proper store)
_web_vitals_buffer: list = []
_MAX_BUFFER_SIZE = 1000


@router.post("/metrics")
async def collect_web_vitals(request_data: dict) -> dict:
    """Collect Web Vitals metrics from frontend."""
    global _web_vitals_buffer

    metric = {
        "name": request_data.get("name"),
        "value": request_data.get("value"),
        "rating": request_data.get("rating"),
        "delta": request_data.get("delta"),
        "id": request_data.get("id"),
        "navigationType": request_data.get("navigationType"),
        "timestamp": request_data.get("timestamp"),
        "received_at": datetime.now(timezone.utc).isoformat(),
    }

    _web_vitals_buffer.append(metric)
    if len(_web_vitals_buffer) > _MAX_BUFFER_SIZE:
        _web_vitals_buffer = _web_vitals_buffer[-_MAX_BUFFER_SIZE:]

    return {"status": "ok", "count": len(_web_vitals_buffer)}


@router.get("/metrics/summary")
async def get_web_vitals_summary() -> dict:
    """Get summary of collected Web Vitals metrics."""
    from collections import defaultdict

    if not _web_vitals_buffer:
        return {"message": "No metrics collected yet", "metrics": {}}

    by_name = defaultdict(list)
    for m in _web_vitals_buffer:
        if m.get("name") and m.get("value") is not None:
            by_name[m["name"]].append(m["value"])

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


@router.post("/user/prewarm", tags=["user"])
async def prewarm_user_airports(user: str = Depends(get_current_user)) -> dict:
    """Pre-warm user's most-used airports from UC into Lakebase cache."""
    lakebase = get_lakebase_service()
    if not lakebase.is_available:
        return {"status": "skipped", "reason": "lakebase_unavailable"}

    top_airports = lakebase.get_user_top_airports(user, limit=5)

    if not top_airports:
        default = os.getenv("DEMO_DEFAULT_AIRPORT", "KSFO")
        top_airports = [default]

    cached = set(lakebase.get_cached_airport_codes())
    to_warm = [icao for icao in top_airports if icao not in cached]

    if not to_warm:
        return {
            "status": "ok",
            "user": user,
            "airports": top_airports,
            "already_cached": len(top_airports),
            "warming": 0,
        }

    async def _warm_airports():
        service = get_airport_config_service()
        for icao in to_warm:
            try:
                loaded = await asyncio.to_thread(
                    service.initialize_from_lakehouse,
                    icao_code=icao,
                    fallback_to_osm=False,
                )
                if loaded:
                    await asyncio.to_thread(service.save_to_lakebase_cache, icao)
                    logger.info(f"Pre-warmed {icao} into Lakebase for {user}")
            except Exception as e:
                logger.warning(f"Failed to pre-warm {icao}: {e}")

    asyncio.create_task(_warm_airports())

    return {
        "status": "warming",
        "user": user,
        "airports": top_airports,
        "already_cached": len(top_airports) - len(to_warm),
        "warming": len(to_warm),
    }

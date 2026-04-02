"""REST endpoints for the OpenSky ADS-B data collector."""

import logging

from fastapi import APIRouter

from app.backend.services.opensky_collector import get_opensky_collector

logger = logging.getLogger(__name__)

collector_router = APIRouter(tags=["collector"])


@collector_router.get("/api/collector/status")
async def get_collector_status():
    """Return collector running state and per-airport statistics."""
    collector = get_opensky_collector()
    return collector.get_status()


@collector_router.post("/api/collector/start")
async def start_collector():
    """Start the background collector. Idempotent."""
    collector = get_opensky_collector()
    collector.start()
    return {"status": "running", "session_id": collector.session_id}


@collector_router.post("/api/collector/stop")
async def stop_collector():
    """Stop the background collector."""
    collector = get_opensky_collector()
    await collector.stop()
    return {"status": "stopped"}


@collector_router.get("/api/collector/airports")
async def get_collector_airports():
    """Return list of airports with data availability."""
    collector = get_opensky_collector()
    status = collector.get_status()

    airports = []
    for icao, stats in status["airports"].items():
        airports.append({
            "icao": icao,
            "snapshots_saved": stats["snapshots_saved"],
            "last_fetch_time": stats["last_fetch_time"],
            "last_flight_count": stats["last_flight_count"],
            "collecting": status["running"],
        })

    return {
        "airports": airports,
        "total_airports": len(airports),
        "collector_running": status["running"],
    }

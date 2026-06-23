"""Debug endpoints — ring-buffer logs, client logs, runway diagnostics."""

import logging
import os
from collections import deque
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["debug"])


class _RingBufferHandler(logging.Handler):
    """Keeps the last N log records in memory for diagnostic retrieval."""

    def __init__(self, capacity: int = 500):
        super().__init__()
        self._buffer: deque[str] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord):
        try:
            self._buffer.append(self.format(record))
        except Exception:
            pass

    def get_lines(self, pattern: str | None = None) -> list[str]:
        lines = list(self._buffer)
        if pattern:
            lines = [l for l in lines if pattern in l]
        return lines


_ring_handler = _RingBufferHandler(capacity=1000)
_ring_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
_ring_handler.setLevel(logging.DEBUG)
for _logger_name in (
    None,
    "app.backend.services.airport_config_service",
    "app.backend.services.data_generator_service",
    "app.backend.api.routes",
    "src.persistence.airport_repository",
    "app.backend.services.lakebase_service",
    "app.backend.services.opensky_service",
    "app.backend.services.opensky_collector",
    "app.backend.api.opensky",
    "src.ingestion.fallback",
    "src.ingestion._taxi_routing",
    "src.ingestion._flight_lifecycle",
):
    _lg = logging.getLogger(_logger_name)
    _lg.addHandler(_ring_handler)
    if _lg.level > logging.DEBUG:
        _lg.setLevel(logging.DEBUG)


_CLIENT_LOG_LEVELS = {"error": logging.ERROR, "warn": logging.WARNING, "info": logging.INFO, "debug": logging.DEBUG}


@router.get("/debug/logs")
async def get_debug_logs(
    pattern: Optional[str] = Query(default="DIAG", description="Filter pattern (default: DIAG)"),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict:
    """Return recent log lines matching a pattern."""
    if os.environ.get("DEBUG_MODE", "false").lower() != "true":
        raise HTTPException(status_code=403, detail="Debug endpoints are disabled in production")

    lines = _ring_handler.get_lines(pattern if pattern else None)
    return {
        "pattern": pattern,
        "total_buffered": len(_ring_handler._buffer),
        "matched": len(lines),
        "lines": lines[-limit:],
    }


@router.post("/debug/client-logs")
async def post_client_logs(request: Request) -> dict:
    """Receive frontend log entries — persist to ring buffer + Lakebase."""
    body = await request.json()
    entries = body.get("entries", [])
    if not entries:
        return {"accepted": 0}

    for entry in entries:
        lvl = _CLIENT_LOG_LEVELS.get(entry.get("level", "info"), logging.INFO)
        logger.log(lvl, "[CLIENT:%s] %s", entry.get("source", "?"), entry.get("message", ""))

    from app.backend.services.lakebase_service import get_lakebase_service
    lakebase = get_lakebase_service()
    if lakebase.is_available:
        lakebase.insert_client_logs(entries)

    _uc_catalog = os.getenv("DATABRICKS_CATALOG", "")
    _uc_schema = os.getenv("DATABRICKS_SCHEMA", "")
    if _uc_catalog and _uc_schema:
        try:
            from datetime import datetime as _dt
            debug_dir = f"/Volumes/{_uc_catalog}/{_uc_schema}/simulation_data/debug"
            os.makedirs(debug_dir, exist_ok=True)
            log_path = f"{debug_dir}/client_debug.log"
            with open(log_path, "a") as f:
                ts = _dt.utcnow().isoformat(timespec="seconds")
                import json as _json
                for entry in entries:
                    meta = entry.get("metadata")
                    meta_str = f" | {_json.dumps(meta, default=str)}" if meta else ""
                    f.write(f"[{ts}] [{entry.get('level', 'info')}] [{entry.get('source', '?')}] {entry.get('message', '')}{meta_str}\n")
        except Exception:
            pass

    return {"accepted": len(entries)}


@router.get("/debug/client-logs")
async def get_client_logs(
    source: Optional[str] = Query(default=None, description="Filter by source tag"),
    level: Optional[str] = Query(default=None, description="Filter by level (error, warn, info, debug)"),
    limit: int = Query(default=100, ge=1, le=500),
    since_minutes: int = Query(default=60, ge=1, le=1440),
) -> dict:
    """Query persisted client debug logs from Lakebase."""
    if os.environ.get("DEBUG_MODE", "false").lower() != "true":
        raise HTTPException(status_code=403, detail="Debug endpoints are disabled in production")

    from app.backend.services.lakebase_service import get_lakebase_service
    lakebase = get_lakebase_service()
    if not lakebase.is_available:
        raise HTTPException(status_code=503, detail="Lakebase not available")

    rows = lakebase.query_client_logs(source=source, level=level, limit=limit, since_minutes=since_minutes)
    for row in rows:
        if hasattr(row.get("logged_at"), "isoformat"):
            row["logged_at"] = row["logged_at"].isoformat()
    return {"entries": rows, "count": len(rows)}


@router.get("/debug/recent-errors")
async def get_recent_errors(
    limit: int = Query(default=50, ge=1, le=200),
    authorization: str = Header(default="", alias="Authorization"),
) -> dict:
    """Return recent ERROR/WARNING lines from the ring buffer."""
    if not authorization.startswith("Bearer ") or len(authorization) < 20:
        raise HTTPException(status_code=401, detail="Bearer token required")

    all_lines = list(_ring_handler._buffer)
    errors = [l for l in all_lines if " ERROR " in l]
    warnings = [l for l in all_lines if " WARNING " in l]

    return {
        "errors": errors[-limit:],
        "warnings": warnings[-limit:],
        "error_count": len(errors),
        "warning_count": len(warnings),
        "total_buffered": len(all_lines),
    }


@router.get("/debug/runway-diag")
async def get_runway_diagnostics() -> dict:
    """Return runway diagnostic data — what the simulator sees."""
    from app.backend.services.airport_config_service import get_airport_config_service
    config = get_airport_config_service().get_config()
    osm_runways = config.get("osmRunways", [])

    runway_info = []
    for r in osm_runways:
        pts = r.get("geoPoints", [])
        info = {
            "ref": r.get("ref"),
            "name": r.get("name"),
            "geoPoints_count": len(pts),
        }
        if len(pts) >= 2:
            info["first_pt"] = pts[0]
            info["last_pt"] = pts[-1]
        runway_info.append(info)

    from src.ingestion.fallback import _get_osm_primary_runway, _osm_runway_endpoints, _get_runway_heading
    primary = _get_osm_primary_runway()
    heading = _get_runway_heading()
    endpoints = None
    if primary:
        thr, far, hdg = _osm_runway_endpoints(primary)
        endpoints = {
            "threshold": {"lon": thr[0], "lat": thr[1]},
            "far_end": {"lon": far[0], "lat": far[1]},
            "heading": hdg,
            "ref": primary.get("ref"),
        }

    return {
        "config_keys": list(config.keys())[:20],
        "osmRunways_count": len(osm_runways),
        "runways": runway_info,
        "primary_runway": {
            "ref": primary.get("ref") if primary else None,
            "geoPoints_count": len(primary.get("geoPoints", [])) if primary else 0,
        },
        "computed_heading": heading,
        "endpoints": endpoints,
        "config_source": config.get("source"),
        "config_ready": get_airport_config_service().config_ready,
    }


@router.get("/debug/approach-state")
async def get_approach_state() -> dict:
    """Lightweight approach state check (no auth required for diagnostics)."""
    from src.ingestion._approach_departure import (
        _cached_osm_primary_runway,
        _osm_primary_runway_resolved,
        _osm_runway_config_id,
        _approach_waypoints_cache,
        _get_osm_primary_runway,
        _get_runway_heading,
        _get_runway_threshold,
        _get_fallback_runway,
    )
    from app.backend.services.airport_config_service import get_airport_config_service

    service = get_airport_config_service()
    config = service.get_config()
    osm_runways = config.get("osmRunways", [])

    # Try resolving fresh
    try:
        fresh_rwy = _get_osm_primary_runway()
        fresh_ref = fresh_rwy.get("ref") if fresh_rwy else None
        fresh_pts = len(fresh_rwy.get("geoPoints", [])) if fresh_rwy else 0
    except Exception as e:
        fresh_ref = f"ERROR: {e}"
        fresh_pts = 0

    # Get heading
    try:
        heading = _get_runway_heading()
    except Exception as e:
        heading = f"ERROR: {e}"

    # Get threshold
    try:
        threshold = _get_runway_threshold()
    except Exception as e:
        threshold = f"ERROR: {e}"

    # Fallback for comparison
    fb = _get_fallback_runway()

    return {
        "cache_state": {
            "resolved": _osm_primary_runway_resolved,
            "cached_ref": _cached_osm_primary_runway.get("ref") if _cached_osm_primary_runway else None,
            "cached_pts": len(_cached_osm_primary_runway.get("geoPoints", [])) if _cached_osm_primary_runway else 0,
            "config_id_tracked": _osm_runway_config_id,
            "config_id_current": id(config),
            "waypoints_cached_keys": list(_approach_waypoints_cache.keys())[:10],
        },
        "config": {
            "ready": service.config_ready,
            "osmRunways_count": len(osm_runways),
            "top_runways": [{"ref": r.get("ref"), "pts": len(r.get("geoPoints", []))} for r in osm_runways[:5]],
        },
        "resolved": {
            "fresh_ref": fresh_ref,
            "fresh_pts": fresh_pts,
            "heading": heading,
            "threshold": threshold,
        },
        "fallback": {
            "heading": fb[2],
            "threshold": (fb[0][0], fb[0][1]),
        },
    }

"""FastAPI application entry point for Airport Digital Twin."""

import asyncio
import os
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.backend.api.routes import router
from app.backend.api.routes_debug import router as debug_router
from app.backend.api.routes_baggage import router as baggage_router
from app.backend.api.routes_gse import router as gse_router
from app.backend.api.routes_weather import router as weather_router
from app.backend.api.routes_schedule import router as schedule_router
from app.backend.api.routes_airport import router as airport_router
from app.backend.api.websocket import websocket_router
from app.backend.api.predictions import prediction_router
from app.backend.api.data_ops import router as data_ops_router
from app.backend.api.simulation import simulation_router
from app.backend.api.opensky import opensky_router
from app.backend.api.collector import collector_router
from app.backend.api.genie import genie_router
from app.backend.api.inpainting import inpainting_router
from app.backend.api.mcp import mcp_router
from app.backend.api.assistant import assistant_router
from app.backend.api.simulation_jobs import simulation_jobs_router
from app.backend.demo_config import (
    DEMO_MODE, DEFAULT_AIRPORT_ICAO, DEFAULT_AIRPORT_IATA, DEFAULT_FLIGHT_COUNT,
)
from app.backend.services.data_generator_service import get_data_generator_service
from app.backend.services.airport_config_service import get_airport_config_service, AirportConfigService
from app.backend.services.prediction_service import get_prediction_service
from src.ingestion.fallback import apply_airport_offset, reload_gates, reset_airport_offset, set_airport_center
from src.ingestion.schedule_generator import AIRPORT_COORDINATES
from src.ml.gate_model import reload_gate_recommender
from src.ml.registry import get_model_registry
from app.backend.services.weather_service import get_weather_service

# Configure logging based on DEBUG_MODE env var
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() in ("true", "1", "yes")
log_level = logging.DEBUG if DEBUG_MODE else logging.INFO
log_format = (
    "%(asctime)s [%(levelname)-8s] %(name)s:%(funcName)s:%(lineno)d - %(message)s"
    if DEBUG_MODE
    else "%(asctime)s [%(levelname)-8s] %(name)s - %(message)s"
)
logging.basicConfig(level=log_level, format=log_format, force=True)

# --- In-memory ring buffer log handler ---
from collections import deque
import threading

class RingBufferHandler(logging.Handler):
    """Logging handler that stores the last N log records in memory."""

    def __init__(self, capacity: int = 2000):
        super().__init__()
        self._buffer: deque[str] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            with self._lock:
                self._buffer.append(msg)
        except Exception:
            self.handleError(record)

    def get_lines(self, n: int | None = None, level: str | None = None,
                  search: str | None = None) -> list[str]:
        """Return buffered log lines, optionally filtered."""
        with self._lock:
            lines = list(self._buffer)
        if level:
            level_upper = level.upper()
            lines = [l for l in lines if f"[{level_upper}" in l]
        if search:
            search_lower = search.lower()
            lines = [l for l in lines if search_lower in l.lower()]
        if n:
            lines = lines[-n:]
        return lines

_ring_handler = RingBufferHandler(capacity=2000)
_ring_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)-8s] %(name)s:%(funcName)s:%(lineno)d - %(message)s"
))
logging.getLogger().addHandler(_ring_handler)

logger = logging.getLogger(__name__)

# Resolve frontend dist path
FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"
logger.info(f"FRONTEND_DIST resolved to: {FRONTEND_DIST} (exists: {FRONTEND_DIST.exists()})")


_SOURCE_LABELS = {
    "lakebase_cache": "Lakebase cache (Tier 1, <10ms)",
    "unity_catalog": "Unity Catalog (Tier 2, SQL Warehouse)",
    "osm_api": "OSM Overpass API (Tier 3, external)",
}


async def _prewarm_airports_background():
    """Pre-warm Lakebase cache for all well-known airports after startup.

    Loading chain (fast → slow):
    1. UC Volume static_assets/airport_cache/ — bulk seed from pre-computed JSON
    2. OSM Overpass API — fallback for airports not in the Volume

    Skips airports already in Lakebase cache.
    """
    import time
    import json
    from app.backend.api.routes_airport import WELL_KNOWN_AIRPORT_INFO
    from app.backend.services.lakebase_service import get_lakebase_service

    await asyncio.sleep(5)

    service = get_airport_config_service()
    lakebase = get_lakebase_service()

    persisted = service.list_persisted_airports()
    persisted_codes = {a.get("icao_code", a.get("icaoCode", "")).upper() for a in persisted}

    to_prewarm = [icao for icao in WELL_KNOWN_AIRPORT_INFO if icao not in persisted_codes]
    if not to_prewarm:
        logger.info("PREWARM | All %d well-known airports already cached in Lakebase", len(WELL_KNOWN_AIRPORT_INFO))
        return

    logger.info("PREWARM | Starting background pre-warm for %d/%d airports", len(to_prewarm), len(WELL_KNOWN_AIRPORT_INFO))

    # Phase 1: Bulk-load from UC Volume (fast, no rate limits)
    volume_loaded = 0
    try:
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient()
        catalog = os.getenv("DATABRICKS_CATALOG", "serverless_stable_3n0ihb_catalog")
        schema = os.getenv("DATABRICKS_SCHEMA", "airport_digital_twin")
        volume_base = f"/Volumes/{catalog}/{schema}/static_assets/airport_cache"

        for icao in list(to_prewarm):
            volume_path = f"{volume_base}/airport_{icao}.json"
            try:
                resp = w.files.download(volume_path)
                config = json.loads(resp.contents.read())
                if lakebase.upsert_airport_config(icao, config):
                    volume_loaded += 1
                    to_prewarm.remove(icao)
                    logger.info("PREWARM | %s seeded from UC Volume", icao)
            except Exception:
                pass  # File not in Volume — will try OSM below

        if volume_loaded:
            logger.info("PREWARM | Phase 1 complete: %d airports seeded from UC Volume", volume_loaded)
    except Exception as e:
        logger.info("PREWARM | UC Volume unavailable (%s), falling back to OSM", e)

    # Phase 2: OSM fallback for remaining airports
    if not to_prewarm:
        logger.info("PREWARM | Complete: %d airports seeded (all from Volume)", volume_loaded)
        return

    logger.info("PREWARM | Phase 2: %d airports remaining, trying OSM", len(to_prewarm))
    warmed = 0
    for i, icao in enumerate(to_prewarm, 1):
        try:
            t0 = time.monotonic()
            prewarm_svc = AirportConfigService()
            loaded = await asyncio.to_thread(
                prewarm_svc.initialize_from_lakehouse,
                icao_code=icao,
                fallback_to_osm=True,
            )
            elapsed = time.monotonic() - t0
            if loaded:
                warmed += 1
                logger.info("PREWARM | [%d/%d] %s cached in %.1fs (source=%s)", i, len(to_prewarm), icao, elapsed, loaded)
            else:
                logger.warning("PREWARM | [%d/%d] %s failed", i, len(to_prewarm), icao)
        except Exception as e:
            logger.warning("PREWARM | [%d/%d] %s error: %s", i, len(to_prewarm), icao, e)
        await asyncio.sleep(2)

    logger.info("PREWARM | Complete: %d from Volume + %d from OSM", volume_loaded, warmed)


async def _background_init(app: FastAPI):
    """Run heavy initialization in the background so the app accepts requests immediately."""
    import time
    from app.backend.services.lakebase_service import get_lakebase_service
    from app.backend.services.delta_service import get_delta_service

    airport_icao = DEFAULT_AIRPORT_ICAO
    airport_iata = DEFAULT_AIRPORT_IATA
    t_start = time.monotonic()
    app.state.init_timings = {}  # phase -> seconds
    app.state.init_steps = []    # ordered list of {phase, label, status, duration_ms, detail}

    def _step(phase: int, label: str, status: str = "running", detail: str = "", duration_ms: float = 0):
        """Track an init step for the loading screen."""
        for s in app.state.init_steps:
            if s["phase"] == phase:
                s.update(status=status, detail=detail, duration_ms=round(duration_ms))
                return
        app.state.init_steps.append({
            "phase": phase, "label": label,
            "status": status, "detail": detail, "duration_ms": round(duration_ms),
        })

    logger.info("=" * 70)
    logger.info(f"INIT | Airport Digital Twin — Build {BUILD_NUMBER}")
    logger.info("=" * 70)
    logger.info(f"INIT | Demo mode: {DEMO_MODE}")
    logger.info(f"INIT | Default airport: {airport_icao} ({airport_iata})")
    logger.info(f"INIT | Default flight count: {DEFAULT_FLIGHT_COUNT}")
    logger.info(f"INIT | Debug mode: {DEBUG_MODE}")
    logger.info("-" * 70)

    try:
        # ── Phase 0: Test database connections ────────────────────────────
        app.state.startup_status = "Testing database connections..."
        _step(0, "Database connections", "running")
        logger.info("INIT | Phase 0: Testing database connections")
        t_phase = time.monotonic()

        lakebase = get_lakebase_service()
        db_details = []
        if lakebase.is_available:
            logger.info(f"INIT |   Lakebase: CONNECTED (host={os.getenv('LAKEBASE_HOST', 'n/a')})")
            db_details.append("Lakebase: connected")
            try:
                flight_records = lakebase.get_flights(limit=1)
                schedule_records = lakebase.get_schedule(hours_behind=24, hours_ahead=24, limit=1, airport_icao=airport_icao)
                logger.info(f"INIT |   Lakebase flight_status table: {'has data' if flight_records else 'empty'}")
                logger.info(f"INIT |   Lakebase schedule table: {'has data' if schedule_records else 'empty'}")
            except Exception as e:
                logger.info(f"INIT |   Lakebase record check: skipped ({e})")
        else:
            logger.warning("INIT |   Lakebase: NOT AVAILABLE — synthetic data only")
            db_details.append("Lakebase: unavailable")

        delta = get_delta_service()
        if delta.is_available:
            logger.info(f"INIT |   Delta tables (Unity Catalog): configured (host={os.getenv('DATABRICKS_HOST', 'n/a')})")
            db_details.append("Unity Catalog: configured")
        else:
            logger.info("INIT |   Delta tables (Unity Catalog): NOT CONFIGURED")
            db_details.append("Unity Catalog: not configured")

        phase0_ms = (time.monotonic() - t_phase) * 1000
        app.state.init_timings["phase0_db_connections"] = round(phase0_ms / 1000, 2)
        _step(0, "Database connections", "done", ", ".join(db_details), phase0_ms)
        logger.info("-" * 70)

        # ── Phase 1: Load airport configuration ──────────────────────────
        app.state.startup_status = f"Loading airport config for {airport_icao}..."
        _step(1, f"Airport config ({airport_icao})", "running")
        logger.info(f"INIT | Phase 1: Loading airport configuration for {airport_icao}")

        airport_config = get_airport_config_service()
        t0 = time.monotonic()
        source = airport_config.initialize_from_lakehouse(
            icao_code=airport_icao,
            fallback_to_osm=True,
        )
        load_ms = (time.monotonic() - t0) * 1000

        if source:
            source_label = _SOURCE_LABELS.get(source, source)
            config = airport_config.get_config()
            n_terminals = len(config.get('terminals', []))
            n_gates = len(config.get('gates', []))
            n_taxiways = len(config.get('osmTaxiways', []))
            n_aprons = len(config.get('osmAprons', []))
            n_runways = len(config.get('osmRunways', []))
            logger.info(f"INIT |   Source: {source_label}")
            logger.info(f"INIT |   Load time: {load_ms:.0f}ms")
            logger.info(f"INIT |   Elements: {n_terminals} terminals, {n_gates} gates, {n_runways} runways, {n_taxiways} taxiways, {n_aprons} aprons")
            app.state.startup_status = f"Airport data loaded from {source_label} in {load_ms:.0f}ms"

            # Set airport center for synthetic data generation
            if airport_iata in AIRPORT_COORDINATES:
                _lat, _lon = AIRPORT_COORDINATES[airport_iata]
            else:
                from src.ingestion.fallback import AIRPORT_CENTER
                _lat, _lon = AIRPORT_CENTER[0], AIRPORT_CENTER[1]
            set_airport_center(_lat, _lon, airport_iata)
            if airport_iata != "SFO":
                apply_airport_offset(_lat, _lon)
            else:
                reset_airport_offset()
            gates = reload_gates()
            logger.info(f"INIT |   Reloaded {len(gates)} gates for synthetic data generation")

            gate_count = reload_gate_recommender()
            logger.info(f"INIT |   Gate recommender initialized with {gate_count} OSM gates")

            # Refresh the AirportModelRegistry so PredictionService uses OSM gates too
            # Deferred to background — not needed for initial flight display
            async def _retrain_ml_background():
                registry = get_model_registry()
                t_ml = time.monotonic()
                await asyncio.to_thread(registry.retrain, airport_icao)
                ml_ms = (time.monotonic() - t_ml) * 1000
                logger.info(f"INIT | ML models retrained in {ml_ms:.0f}ms (background)")
                app.state.init_timings["ml_retrain"] = round(ml_ms / 1000, 2)
            asyncio.create_task(_retrain_ml_background())

            phase1_detail = f"{source_label}: {n_gates} gates, {n_runways} runways, {n_taxiways} taxiways, {n_aprons} aprons"
        else:
            logger.warning("INIT |   FAILED to load airport config from any source (tried all 3 tiers)")
            app.state.startup_status = "Warning: airport config failed to load from all sources"
            phase1_detail = "FAILED — all 3 tiers"

        if not airport_config.config_ready:
            logger.warning(
                "INIT |   Airport config not ready — "
                "synthetic data will use default 9-gate fallback until config loads"
            )

        phase1_ms = (time.monotonic() - t0) * 1000
        app.state.init_timings["phase1_airport_config"] = round(phase1_ms / 1000, 2)
        app.state.init_timings["phase1_source"] = source or "none"
        _step(1, f"Airport config ({airport_icao})", "done" if source else "error", phase1_detail, phase1_ms)
        logger.info("-" * 70)

        # ── Phase 2: Generate synthetic data ─────────────────────────────
        app.state.startup_status = f"Generating synthetic flight data ({DEFAULT_FLIGHT_COUNT} flights)..."
        _step(2, "Synthetic flight data", "running")
        logger.info(f"INIT | Phase 2: Generating synthetic data ({DEFAULT_FLIGHT_COUNT} flights for {airport_icao})")

        data_generator = get_data_generator_service()
        t1 = time.monotonic()
        init_success = await data_generator.initialize_all_data(airport_icao=airport_icao)
        gen_ms = (time.monotonic() - t1) * 1000
        if init_success:
            logger.info(f"INIT |   Synthetic data generated in {gen_ms:.0f}ms")
            await data_generator.start_periodic_refresh()
            logger.info("INIT |   Periodic refresh started (weather=10m, schedule=1m, baggage=30s, GSE=30s, snapshots=15s)")
            app.state.startup_status = f"Synthetic data generated in {gen_ms:.0f}ms — periodic refresh active"
            _step(2, "Synthetic flight data", "done", f"{DEFAULT_FLIGHT_COUNT} flights, periodic refresh active", gen_ms)
        else:
            logger.warning("INIT |   Data initialization FAILED — using fallback generators only")
            app.state.startup_status = "Warning: data init failed, using fallback generators"
            _step(2, "Synthetic flight data", "error", "using fallback generators", gen_ms)

        app.state.init_timings["phase2_synthetic_data"] = round(gen_ms / 1000, 2)
        logger.info("-" * 70)

        # ── Phase 3: Pre-warm weather cache ──────────────────────────────
        _step(3, "Weather cache", "running")
        logger.info(f"INIT | Phase 3: Pre-warming weather cache for {airport_icao}")
        t_weather = time.monotonic()
        try:
            weather_svc = get_weather_service()
            await weather_svc.get_current_weather()
            weather_ms = (time.monotonic() - t_weather) * 1000
            logger.info(f"INIT |   Weather cache pre-warmed for {airport_icao}")
            _step(3, "Weather cache", "done", f"METAR/TAF for {airport_icao}", weather_ms)
        except Exception as e:
            weather_ms = (time.monotonic() - t_weather) * 1000
            logger.warning(f"INIT |   Weather pre-warm failed (non-critical): {e}")
            _step(3, "Weather cache", "done", "skipped (non-critical)", weather_ms)

        app.state.init_timings["phase3_weather"] = round(weather_ms / 1000, 2)
        total_ms = (time.monotonic() - t_start) * 1000
        app.state.init_timings["total_ready"] = round(total_ms / 1000, 2)
        app.state.ready = True
        app.state.startup_status = "Ready"
        logger.info("=" * 70)
        logger.info(f"INIT | Initialization COMPLETE in {total_ms:.0f}ms — app ready")
        logger.info(f"INIT | Serving {airport_icao} ({airport_iata}) with {DEFAULT_FLIGHT_COUNT} flights in {'demo' if DEMO_MODE else 'live'} mode")
        logger.info("=" * 70)

        # ── Phase 4: Generate demo simulation (background, non-blocking) ──
        _step(4, "Demo simulation", "running", "background")
        async def _generate_demo_background():
            from app.backend.services.demo_simulation_service import get_demo_simulation_service
            from app.backend.api.websocket import broadcaster
            try:
                demo_svc = get_demo_simulation_service()
                app.state.startup_status = "Loading demo simulation..."
                t_demo = time.monotonic()
                await asyncio.to_thread(demo_svc.generate_demo, airport_icao)
                demo_ms = (time.monotonic() - t_demo) * 1000
                source = demo_svc.get_source(airport_icao)
                logger.info(f"INIT | Demo simulation {source} in {demo_ms:.0f}ms")
                app.state.init_timings["phase4_demo_sim"] = round(demo_ms / 1000, 2)
                app.state.init_timings["phase4_source"] = source
                app.state.startup_status = "Ready"
                _step(4, "Demo simulation", "done", f"{source}", demo_ms)
                await broadcaster.broadcast({
                    "type": "demo_ready",
                    "data": {"icao": airport_icao},
                })
            except Exception as e:
                logger.error(f"INIT | Demo simulation generation FAILED: {e}", exc_info=True)
                app.state.init_timings["phase4_demo_sim"] = f"FAILED: {type(e).__name__}: {e}"
                app.state.startup_status = "Ready"
                _step(4, "Demo simulation", "error", str(e)[:80], 0)

        asyncio.create_task(_generate_demo_background())

        # Phase 5 (pre-warm all airports) removed — only load the selected
        # airport on startup.  Other airports load on-demand via /activate.

        # ── Phase 6: Ensure MCP UC HTTP Connection ──────────────────────
        try:
            from app.backend.services.mcp_connection_service import ensure_mcp_connection
            conn = await asyncio.to_thread(ensure_mcp_connection)
            if conn:
                app.state.init_timings["phase6_mcp_connection"] = conn
        except Exception as e:
            logger.warning(f"INIT | MCP connection setup skipped: {e}")

        # ── Phase 7: Probe OpenSky API connectivity ──────────────────────
        async def _probe_opensky():
            try:
                from app.backend.services.opensky_service import get_opensky_service
                opensky = get_opensky_service()
                reachable = await opensky.probe_connectivity()
                app.state.opensky_available = reachable
                logger.info(f"INIT | OpenSky connectivity: {'reachable' if reachable else 'BLOCKED'}")
            except Exception as e:
                app.state.opensky_available = False
                logger.warning(f"INIT | OpenSky probe failed: {e}")

        asyncio.create_task(_probe_opensky())

    except Exception as e:
        total_ms = (time.monotonic() - t_start) * 1000
        logger.error(f"INIT | Initialization FAILED after {total_ms:.0f}ms: {e}", exc_info=DEBUG_MODE)
        app.state.startup_status = f"Initialization error: {e}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown events."""
    logger.info("=" * 70)
    logger.info("Starting Airport Digital Twin API")
    logger.info(f"  Python PID: {os.getpid()}")
    logger.info(f"  Working directory: {os.getcwd()}")
    logger.info("=" * 70)

    # Mark app as not ready, then kick off heavy init in background
    app.state.ready = False
    app.state.startup_status = "Initializing..."

    asyncio.create_task(_background_init(app))

    yield

    # Shutdown: Stop periodic refresh tasks
    data_generator = get_data_generator_service()
    logger.info("Shutting down data generation service...")
    await data_generator.stop_periodic_refresh()

    # Stop the OpenSky collector if it was started via API
    from app.backend.services.opensky_collector import get_opensky_collector
    collector = get_opensky_collector()
    if collector.running:
        logger.info("Shutting down OpenSky collector...")
        await collector.stop()

    logger.info("Airport Digital Twin API stopped")


app = FastAPI(
    title="Airport Digital Twin API",
    description="Real-time flight data API for the Airport Digital Twin visualization",
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS middleware — restrict to known origins
_CORS_ORIGINS = [
    # Databricks App production URL
    "https://airport-digital-twin-dev-7474645572615955.aws.databricksapps.com",
    # Local development
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8000",
]
# Allow override via environment variable (comma-separated)
_extra_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "")
if _extra_origins:
    _CORS_ORIGINS.extend(o.strip() for o in _extra_origins.split(",") if o.strip())

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Include routers
app.include_router(router)
app.include_router(debug_router)
app.include_router(baggage_router)
app.include_router(gse_router)
app.include_router(weather_router)
app.include_router(schedule_router)
app.include_router(airport_router)
app.include_router(websocket_router)
app.include_router(prediction_router)
app.include_router(data_ops_router)
app.include_router(simulation_router)
app.include_router(opensky_router)
app.include_router(collector_router)

# Mount embedded FLIFO mock when FLIFO_MOCK_MODE is enabled
if os.getenv("FLIFO_MOCK_MODE", "").lower() in ("true", "1", "yes"):
    from tools.flifo_mock.server import app as flifo_mock_app
    app.mount("/mock/flifo", flifo_mock_app)
    logger.info("FLIFO mock server mounted at /mock/flifo")
app.include_router(genie_router)
app.include_router(inpainting_router)
app.include_router(mcp_router)
app.include_router(assistant_router)
app.include_router(simulation_jobs_router)


@app.get("/health")
async def health_check():
    """Health check endpoint with service status."""
    from app.backend.services.lakebase_service import get_lakebase_service
    lakebase = get_lakebase_service()
    config_service = get_airport_config_service()
    config = config_service.get_config() if config_service else {}
    return {
        "status": "healthy",
        "lakebase": lakebase.health_check() if lakebase and lakebase.is_available else False,
        "airport": config.get("icaoCode", "unknown"),
        "airport_source": config.get("source", "unknown"),
    }


@app.get("/api/ready")
async def readiness():
    """Readiness endpoint — returns background init progress."""
    from app.backend.services.demo_simulation_service import get_demo_simulation_service
    demo_svc = get_demo_simulation_service()
    # Check demo readiness for current airport (not just the default)
    config_service = get_airport_config_service()
    current_icao = config_service.get_config().get("icaoCode", DEFAULT_AIRPORT_ICAO)
    return {
        "ready": getattr(app.state, "ready", False),
        "status": getattr(app.state, "startup_status", "Initializing..."),
        "demo_ready": demo_svc.has_demo(current_icao),
        "demo_ready_icao": current_icao,
        "opensky_available": getattr(app.state, "opensky_available", None),
        "debug_client_logs": os.environ.get("DEBUG_MODE", "false").lower() == "true",
        "init_steps": getattr(app.state, "init_steps", []),
        "init_timings": getattr(app.state, "init_timings", {}),
    }


_DEBUG_MODE_ENABLED = os.environ.get("DEBUG_MODE", "false").lower() == "true"


@app.get("/api/logs")
async def get_logs(
    n: int = 200,
    level: str | None = None,
    search: str | None = None,
    format: str = "json",
):
    """Return recent application log lines from the in-memory ring buffer.

    Only available when DEBUG_MODE=true.
    """
    if not _DEBUG_MODE_ENABLED:
        raise HTTPException(status_code=403, detail="Debug endpoints are disabled in production")

    from fastapi.responses import PlainTextResponse

    n = min(n, 2000)
    lines = _ring_handler.get_lines(n=n, level=level, search=search)

    if format == "text":
        return PlainTextResponse("\n".join(lines), media_type="text/plain")

    return {
        "count": len(lines),
        "total_buffered": len(_ring_handler._buffer),
        "filters": {"n": n, "level": level, "search": search},
        "lines": lines,
    }


_build_number_file = Path(__file__).resolve().parent.parent.parent / "BUILD_NUMBER"
BUILD_NUMBER = _build_number_file.read_text().strip() if _build_number_file.exists() else "dev"
_git_commit_file = Path(__file__).resolve().parent.parent.parent / "GIT_COMMIT"
GIT_COMMIT = _git_commit_file.read_text().strip() if _git_commit_file.exists() else "unknown"
_APP_START_TIME = datetime.now(timezone.utc)


@app.get("/api/version")
async def get_version(request: Request):
    """Return build version, git commit, and startup timing."""
    import time
    ready = getattr(request.app.state, "ready", False)
    startup_status = getattr(request.app.state, "startup_status", "unknown")
    timings = getattr(request.app.state, "init_timings", {})
    return {
        "build_number": BUILD_NUMBER,
        "git_commit": GIT_COMMIT,
        "started_at": _APP_START_TIME.isoformat(),
        "uptime_seconds": round((datetime.now(timezone.utc) - _APP_START_TIME).total_seconds()),
        "ready": ready,
        "startup_status": startup_status,
        "init_timings": timings,
    }


@app.get("/api/config")
async def get_demo_config():
    """Return current demo configuration including platform links."""
    host = os.getenv("DATABRICKS_HOST", "")
    workspace_url = f"https://{host}" if host else ""
    return {
        "build_number": BUILD_NUMBER,
        "git_commit": GIT_COMMIT,
        "demo_mode": DEMO_MODE,
        "default_airport_icao": DEFAULT_AIRPORT_ICAO,
        "default_airport_iata": DEFAULT_AIRPORT_IATA,
        "default_flight_count": DEFAULT_FLIGHT_COUNT,
        "inpainting_available": bool(os.getenv("INPAINTING_ENDPOINT_NAME", "")),
        "platform": {
            "workspace_url": workspace_url,
            "catalog": os.getenv("DATABRICKS_CATALOG", ""),
            "schema": os.getenv("DATABRICKS_SCHEMA", ""),
            "dashboard_id": os.getenv("DASHBOARD_ID", ""),
            "genie_space_id": os.getenv("GENIE_SPACE_ID", ""),
            "lakebase_project_id": os.getenv("LAKEBASE_PROJECT_ID", ""),
        },
    }


@app.get("/api/debug/paths")
async def debug_paths():
    """Debug endpoint to check file paths. Only available when DEBUG_MODE=true."""
    if not _DEBUG_MODE_ENABLED:
        raise HTTPException(status_code=403, detail="Debug endpoints are disabled in production")

    models_dir = FRONTEND_DIST / "models"
    models_aircraft_dir = models_dir / "aircraft"

    return {
        "frontend_dist": str(FRONTEND_DIST),
        "frontend_dist_exists": FRONTEND_DIST.exists(),
        "models_dir": str(models_dir),
        "models_dir_exists": models_dir.exists(),
        "models_aircraft_dir": str(models_aircraft_dir),
        "models_aircraft_dir_exists": models_aircraft_dir.exists(),
        "glb_files": [str(f.name) for f in models_aircraft_dir.glob("*.glb")] if models_aircraft_dir.exists() else [],
        "cwd": os.getcwd(),
        "__file__": __file__,
    }


# Serve static frontend files (must be after API routes)
if FRONTEND_DIST.exists():
    logger.info(f"Mounting static assets from {FRONTEND_DIST}")

    # Serve static assets (JS, CSS, etc.)
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
        logger.info(f"Mounted /assets from {assets_dir}")

    # Serve 3D model files from UC Volumes (with local dist/ fallback for dev)
    UC_VOLUMES_MODEL_PATH = "/Volumes/serverless_stable_3n0ihb_catalog/airport_digital_twin/static_assets/models"
    models_dir = FRONTEND_DIST / "models"

    @app.get("/models/{subpath:path}")
    async def serve_model(subpath: str):
        """Serve 3D model files from UC Volumes, falling back to local dist/models/."""
        import re
        # Sanitize path to prevent directory traversal
        if ".." in subpath or not re.match(r'^[\w/._-]+$', subpath):
            raise HTTPException(status_code=400, detail="Invalid path")

        # Try UC Volumes first (Databricks deployment)
        uc_path = f"{UC_VOLUMES_MODEL_PATH}/{subpath}"
        workspace_path = f"/Workspace{uc_path}"
        wp = Path(workspace_path)
        if wp.exists():
            media = "model/gltf-binary" if subpath.endswith(".glb") else "application/octet-stream"
            return FileResponse(wp, media_type=media, headers={"Cache-Control": "public, max-age=86400"})

        # Fallback to local dist/models/ (local dev)
        local_path = models_dir / subpath
        if local_path.exists():
            media = "model/gltf-binary" if subpath.endswith(".glb") else "application/octet-stream"
            return FileResponse(local_path, media_type=media, headers={"Cache-Control": "public, max-age=86400"})

        raise HTTPException(status_code=404, detail=f"Model not found: {subpath}")

    logger.info(f"Registered /models route (UC Volumes: {UC_VOLUMES_MODEL_PATH}, fallback: {models_dir})")
    # Serve PWA manifest
    @app.get("/manifest.json")
    async def serve_manifest():
        """Serve PWA web app manifest."""
        manifest_file = FRONTEND_DIST / "manifest.json"
        if manifest_file.exists():
            return FileResponse(
                manifest_file,
                media_type="application/manifest+json",
                headers={"Cache-Control": "public, max-age=86400"},
            )
        raise HTTPException(status_code=404, detail="Manifest not found")

    # Serve PWA icons
    icons_dir = FRONTEND_DIST / "icons"
    if icons_dir.exists():
        app.mount("/icons", StaticFiles(directory=icons_dir), name="icons")
        logger.info(f"Mounted /icons from {icons_dir}")

    # Serve apple-touch-icon at root (iOS checks this path automatically)
    @app.get("/apple-touch-icon.png")
    @app.get("/apple-touch-icon-precomposed.png")
    async def serve_apple_touch_icon():
        for path in [FRONTEND_DIST / "apple-touch-icon.png", FRONTEND_DIST / "icons" / "apple-touch-icon.png"]:
            if path.exists():
                return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
        raise HTTPException(status_code=404, detail="Apple touch icon not found")

    # Serve favicon SVG
    @app.get("/airport.svg")
    async def serve_favicon():
        """Serve SVG favicon."""
        svg_file = FRONTEND_DIST / "airport.svg"
        if svg_file.exists():
            return FileResponse(svg_file, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})
        raise HTTPException(status_code=404, detail="Favicon not found")

    # Serve company logo (brand-specific, copied at build time)
    @app.get("/company-logo.svg")
    async def serve_company_logo_svg():
        logo = FRONTEND_DIST / "company-logo.svg"
        if logo.exists():
            return FileResponse(logo, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=3600"})
        raise HTTPException(status_code=404, detail="Company logo not found")

    @app.get("/company-logo.jpeg")
    async def serve_company_logo_jpeg():
        logo = FRONTEND_DIST / "company-logo.jpeg"
        if logo.exists():
            return FileResponse(logo, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=3600"})
        raise HTTPException(status_code=404, detail="Company logo not found")

    # Serve Databricks logo (legacy path)
    @app.get("/databricks-logo.svg")
    async def serve_databricks_logo():
        logo = FRONTEND_DIST / "databricks-logo.svg"
        if logo.exists():
            return FileResponse(logo, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})
        raise HTTPException(status_code=404, detail="Logo not found")

    # Serve service worker with correct MIME type
    @app.get("/sw.js")
    async def serve_service_worker():
        """Serve service worker with correct JavaScript MIME type."""
        sw_file = FRONTEND_DIST / "sw.js"
        if sw_file.exists():
            return FileResponse(
                sw_file,
                media_type="application/javascript",
                headers={"Cache-Control": "no-cache, must-revalidate"},
            )
        return {"error": "Service worker not found"}

    # Catch-all route for SPA - serves index.html for all non-API routes
    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        """Serve the SPA for all non-API routes."""
        # Skip API paths
        if full_path.startswith("api/") or full_path.startswith("ws"):
            return {"error": "Not found"}

        index_file = FRONTEND_DIST / "index.html"
        if index_file.exists():
            return FileResponse(
                index_file,
                headers={"Cache-Control": "no-cache, must-revalidate"},
            )
        return {"error": "Frontend not built"}
else:
    logger.warning(f"Frontend dist not found at {FRONTEND_DIST}")

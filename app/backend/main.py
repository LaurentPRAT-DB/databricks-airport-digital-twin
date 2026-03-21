"""FastAPI application entry point for Airport Digital Twin."""

import asyncio
import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.backend.api.routes import router
from app.backend.api.websocket import websocket_router
from app.backend.api.predictions import prediction_router
from app.backend.api.data_ops import router as data_ops_router
from app.backend.api.simulation import simulation_router
from app.backend.demo_config import (
    DEMO_MODE, DEFAULT_AIRPORT_ICAO, DEFAULT_AIRPORT_IATA, DEFAULT_FLIGHT_COUNT,
)
from app.backend.services.data_generator_service import get_data_generator_service
from app.backend.services.airport_config_service import get_airport_config_service, AirportConfigService
from app.backend.services.prediction_service import get_prediction_service
from src.ingestion.fallback import reload_gates, set_airport_center
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

    Runs sequentially to respect Overpass API rate limits. Skips airports
    already in Lakebase cache (instant Tier 1 check). This makes subsequent
    airport switches near-instant (<1s) instead of 15-18s.
    """
    import time
    from app.backend.api.routes import WELL_KNOWN_AIRPORT_INFO

    # Brief delay to let the app finish any post-startup work
    await asyncio.sleep(5)

    service = get_airport_config_service()

    # Check which airports are already cached
    persisted = service.list_persisted_airports()
    persisted_codes = {a.get("icao_code", a.get("icaoCode", "")).upper() for a in persisted}

    to_prewarm = [icao for icao in WELL_KNOWN_AIRPORT_INFO if icao not in persisted_codes]
    if not to_prewarm:
        logger.info("PREWARM | All %d well-known airports already cached in Lakebase", len(WELL_KNOWN_AIRPORT_INFO))
        return

    logger.info("PREWARM | Starting background pre-warm for %d/%d airports", len(to_prewarm), len(WELL_KNOWN_AIRPORT_INFO))

    warmed = 0
    for i, icao in enumerate(to_prewarm, 1):
        try:
            t0 = time.monotonic()
            # Use a fresh service instance so we don't clobber the active airport config
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

        # Small delay between OSM requests to be polite to Overpass API
        await asyncio.sleep(2)

    logger.info("PREWARM | Complete: %d/%d airports newly cached", warmed, len(to_prewarm))


async def _background_init(app: FastAPI):
    """Run heavy initialization in the background so the app accepts requests immediately."""
    import time
    from app.backend.services.lakebase_service import get_lakebase_service
    from app.backend.services.delta_service import get_delta_service

    airport_icao = DEFAULT_AIRPORT_ICAO
    airport_iata = DEFAULT_AIRPORT_IATA
    t_start = time.monotonic()

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
        logger.info("INIT | Phase 0: Testing database connections")

        lakebase = get_lakebase_service()
        if lakebase.is_available:
            logger.info(f"INIT |   Lakebase: CONNECTED (host={os.getenv('LAKEBASE_HOST', 'n/a')})")
            # Check existing record counts
            try:
                flight_records = lakebase.get_flights(limit=1)
                schedule_records = lakebase.get_schedule(hours_behind=24, hours_ahead=24, limit=1, airport_icao=airport_icao)
                logger.info(f"INIT |   Lakebase flight_status table: {'has data' if flight_records else 'empty'}")
                logger.info(f"INIT |   Lakebase schedule table: {'has data' if schedule_records else 'empty'}")
            except Exception as e:
                logger.info(f"INIT |   Lakebase record check: skipped ({e})")
        else:
            logger.warning("INIT |   Lakebase: NOT AVAILABLE — synthetic data only")

        delta = get_delta_service()
        if delta.is_available:
            logger.info(f"INIT |   Delta tables (Unity Catalog): configured (host={os.getenv('DATABRICKS_HOST', 'n/a')})")
        else:
            logger.info("INIT |   Delta tables (Unity Catalog): NOT CONFIGURED")

        logger.info("-" * 70)

        # ── Phase 1: Load airport configuration ──────────────────────────
        app.state.startup_status = f"Loading airport config for {airport_icao}..."
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
            logger.info(f"INIT |   Source: {source_label}")
            logger.info(f"INIT |   Load time: {load_ms:.0f}ms")
            logger.info(f"INIT |   Elements: {n_terminals} terminals, {n_gates} gates, {n_taxiways} taxiways, {n_aprons} aprons")
            app.state.startup_status = f"Airport data loaded from {source_label} in {load_ms:.0f}ms"

            # Set airport center for synthetic data generation
            if airport_iata in AIRPORT_COORDINATES:
                _lat, _lon = AIRPORT_COORDINATES[airport_iata]
            else:
                from src.ingestion.fallback import AIRPORT_CENTER
                _lat, _lon = AIRPORT_CENTER[0], AIRPORT_CENTER[1]
            set_airport_center(_lat, _lon, airport_iata)
            gates = reload_gates()
            logger.info(f"INIT |   Reloaded {len(gates)} gates for synthetic data generation")

            gate_count = reload_gate_recommender()
            logger.info(f"INIT |   Gate recommender initialized with {gate_count} OSM gates")

            # Refresh the AirportModelRegistry so PredictionService uses OSM gates too
            logger.info("INIT |   Retraining ML models with airport data...")
            app.state.startup_status = "Retraining ML models with airport data..."
            registry = get_model_registry()
            t_ml = time.monotonic()
            registry.retrain(airport_icao)
            ml_ms = (time.monotonic() - t_ml) * 1000
            logger.info(f"INIT |   ML models retrained in {ml_ms:.0f}ms")
        else:
            logger.warning("INIT |   FAILED to load airport config from any source (tried all 3 tiers)")
            app.state.startup_status = "Warning: airport config failed to load from all sources"

        if not airport_config.config_ready:
            logger.warning(
                "INIT |   Airport config not ready — "
                "synthetic data will use default 9-gate fallback until config loads"
            )

        logger.info("-" * 70)

        # ── Phase 2: Generate synthetic data ─────────────────────────────
        app.state.startup_status = f"Generating synthetic flight data ({DEFAULT_FLIGHT_COUNT} flights)..."
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
        else:
            logger.warning("INIT |   Data initialization FAILED — using fallback generators only")
            app.state.startup_status = "Warning: data init failed, using fallback generators"

        logger.info("-" * 70)

        # ── Phase 3: Pre-warm weather cache ──────────────────────────────
        logger.info(f"INIT | Phase 3: Pre-warming weather cache for {airport_icao}")
        try:
            weather_svc = get_weather_service()
            weather_svc.get_current_weather()
            logger.info(f"INIT |   Weather cache pre-warmed for {airport_icao}")
        except Exception as e:
            logger.warning(f"INIT |   Weather pre-warm failed (non-critical): {e}")

        total_ms = (time.monotonic() - t_start) * 1000
        app.state.ready = True
        app.state.startup_status = "Ready"
        logger.info("=" * 70)
        logger.info(f"INIT | Initialization COMPLETE in {total_ms:.0f}ms — app ready")
        logger.info(f"INIT | Serving {airport_icao} ({airport_iata}) with {DEFAULT_FLIGHT_COUNT} flights in {'demo' if DEMO_MODE else 'live'} mode")
        logger.info("=" * 70)

        # ── Phase 4: Pre-warm Lakebase cache for all well-known airports ──
        # This runs after the app is ready and serves users, so it doesn't
        # block startup. Airports already in Lakebase are skipped (Tier 1 hit).
        asyncio.create_task(_prewarm_airports_background())

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
    logger.info("Airport Digital Twin API stopped")


app = FastAPI(
    title="Airport Digital Twin API",
    description="Real-time flight data API for the Airport Digital Twin visualization",
    version="0.1.0",
    lifespan=lifespan,
)

# Configure CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Include routers
app.include_router(router)
app.include_router(websocket_router)
app.include_router(prediction_router)
app.include_router(data_ops_router)
app.include_router(simulation_router)


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
    return {
        "ready": getattr(app.state, "ready", False),
        "status": getattr(app.state, "startup_status", "Initializing..."),
    }


@app.get("/api/logs")
async def get_logs(
    n: int = 200,
    level: str | None = None,
    search: str | None = None,
    format: str = "json",
):
    """Return recent application log lines from the in-memory ring buffer.

    Query params:
        n: Number of most recent lines to return (default 200, max 2000)
        level: Filter by log level (e.g. ERROR, WARNING, INFO)
        search: Case-insensitive substring search
        format: "json" (default) or "text" for plain-text output
    """
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


BUILD_NUMBER = "2026-03-15-001"

@app.get("/api/config")
async def get_demo_config():
    """Return current demo configuration."""
    return {
        "build_number": BUILD_NUMBER,
        "demo_mode": DEMO_MODE,
        "default_airport_icao": DEFAULT_AIRPORT_ICAO,
        "default_airport_iata": DEFAULT_AIRPORT_IATA,
        "default_flight_count": DEFAULT_FLIGHT_COUNT,
    }


@app.get("/api/debug/paths")
async def debug_paths():
    """Debug endpoint to check file paths in production."""
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

    # Serve 3D model files (GLB, GLTF)
    models_dir = FRONTEND_DIST / "models"
    if models_dir.exists():
        app.mount("/models", StaticFiles(directory=models_dir), name="models")
        logger.info(f"Mounted /models from {models_dir} (files: {list(models_dir.glob('**/*'))})")
    else:
        logger.warning(f"Models directory not found at {models_dir}")
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

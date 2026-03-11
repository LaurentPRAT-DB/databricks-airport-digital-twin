"""FastAPI application entry point for Airport Digital Twin."""

import asyncio
import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.backend.api.routes import router
from app.backend.api.websocket import websocket_router
from app.backend.api.predictions import prediction_router
from app.backend.api.data_ops import router as data_ops_router
from app.backend.services.data_generator_service import get_data_generator_service
from app.backend.services.airport_config_service import get_airport_config_service
from app.backend.services.prediction_service import get_prediction_service
from src.ingestion.fallback import reload_gates, set_airport_center, AIRPORT_CENTER
from src.ml.gate_model import reload_gate_recommender
from src.ml.registry import get_model_registry

# Configure logging based on DEBUG_MODE env var
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() in ("true", "1", "yes")
log_level = logging.DEBUG if DEBUG_MODE else logging.INFO
log_format = (
    "%(asctime)s [%(levelname)-8s] %(name)s:%(funcName)s:%(lineno)d - %(message)s"
    if DEBUG_MODE
    else "%(asctime)s [%(levelname)-8s] %(name)s - %(message)s"
)
logging.basicConfig(level=log_level, format=log_format, force=True)

logger = logging.getLogger(__name__)

# Resolve frontend dist path
FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"
logger.info(f"FRONTEND_DIST resolved to: {FRONTEND_DIST} (exists: {FRONTEND_DIST.exists()})")


_SOURCE_LABELS = {
    "lakebase_cache": "Lakebase cache (Tier 1, <10ms)",
    "unity_catalog": "Unity Catalog (Tier 2, SQL Warehouse)",
    "osm_api": "OSM Overpass API (Tier 3, external)",
}


async def _background_init(app: FastAPI):
    """Run heavy initialization in the background so the app accepts requests immediately."""
    import time

    try:
        # Phase 1: Load airport configuration (3-tier: Lakebase cache → Unity Catalog → OSM)
        app.state.startup_status = "Loading airport config (trying Lakebase cache → Unity Catalog → OSM)..."
        logger.info(app.state.startup_status)

        airport_config = get_airport_config_service()
        t0 = time.monotonic()
        source = airport_config.initialize_from_lakehouse(
            icao_code="KSFO",
            fallback_to_osm=True,
        )
        load_ms = (time.monotonic() - t0) * 1000

        if source:
            source_label = _SOURCE_LABELS.get(source, source)
            config = airport_config.get_config()
            counts = (
                f"{len(config.get('terminals', []))} terminals, "
                f"{len(config.get('gates', []))} gates, "
                f"{len(config.get('osmTaxiways', []))} taxiways, "
                f"{len(config.get('osmAprons', []))} aprons"
            )
            app.state.startup_status = f"Airport data loaded from {source_label} in {load_ms:.0f}ms — {counts}"
            logger.info(app.state.startup_status)

            # Ensure airport center is set to SFO default on startup
            set_airport_center(AIRPORT_CENTER[0], AIRPORT_CENTER[1], "SFO")
            gates = reload_gates()
            logger.info(f"Reloaded {len(gates)} gates for synthetic data generation")

            gate_count = reload_gate_recommender()
            logger.info(f"Gate recommender initialized with {gate_count} OSM gates")

            # Refresh the AirportModelRegistry so PredictionService uses OSM gates too
            app.state.startup_status = "Retraining ML models with airport data..."
            logger.info(app.state.startup_status)
            registry = get_model_registry()
            registry.retrain("KSFO")
            logger.info("AirportModelRegistry retrained with fresh OSM gate data")
        else:
            logger.warning("Failed to load airport config from any source (tried all 3 tiers)")
            app.state.startup_status = "Warning: airport config failed to load from all sources"

        if not airport_config.config_ready:
            logger.warning(
                "Airport config not ready before data generation — "
                "synthetic data will use default 9-gate fallback until config loads"
            )

        # Phase 2: Generate synthetic data
        app.state.startup_status = "Generating synthetic flight data..."
        logger.info(app.state.startup_status)

        data_generator = get_data_generator_service()
        t1 = time.monotonic()
        init_success = await data_generator.initialize_all_data(airport_icao="KSFO")
        gen_ms = (time.monotonic() - t1) * 1000
        if init_success:
            await data_generator.start_periodic_refresh()
            app.state.startup_status = f"Synthetic data generated in {gen_ms:.0f}ms — starting periodic refresh"
            logger.info(app.state.startup_status)
        else:
            logger.warning("Data initialization failed - using fallback generators only")
            app.state.startup_status = "Warning: data init failed, using fallback generators"

        app.state.ready = True
        app.state.startup_status = "Ready"
        logger.info("Background initialization complete — app ready")

    except Exception as e:
        logger.error(f"Background initialization failed: {e}", exc_info=DEBUG_MODE)
        app.state.startup_status = f"Initialization error: {e}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown events."""
    logger.info("=" * 60)
    logger.info("Starting Airport Digital Twin API")
    logger.info("=" * 60)

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

# Include routers
app.include_router(router)
app.include_router(websocket_router)
app.include_router(prediction_router)
app.include_router(data_ops_router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/api/ready")
async def readiness():
    """Readiness endpoint — returns background init progress."""
    return {
        "ready": getattr(app.state, "ready", False),
        "status": getattr(app.state, "startup_status", "Initializing..."),
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
            return FileResponse(sw_file, media_type="application/javascript")
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
            return FileResponse(index_file)
        return {"error": "Frontend not built"}
else:
    logger.warning(f"Frontend dist not found at {FRONTEND_DIST}")

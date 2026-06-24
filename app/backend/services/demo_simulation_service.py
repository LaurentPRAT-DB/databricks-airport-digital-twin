"""Demo simulation service — generates replay simulations per airport.

On startup (and on airport switch), provides a demo simulation for
auto-playing timeline replay. For the default airport (KSFO), a
pre-generated static file is loaded from UC Volume (on Databricks)
or local data/demo/ (local dev). Other airports generate a shorter
6h simulation on demand.
"""

import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_LOCAL_DEMO_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "demo"


def _run_engine_subprocess(airport_icao: str, output_path: str, osm_runway: dict | None = None) -> None:
    """Entry point for subprocess-based demo generation.

    Runs in a completely separate process — module globals are independent
    copies, so SimulationEngine cannot corrupt the parent's live state.

    osm_runway: OSM runway dict from the parent process's airport_config_service.
    Injected into _get_osm_primary_runway so approach paths use real runway data
    instead of latitude-based fallback (heading 270° for lat≥30°).
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

    from src.calibration.profile import _icao_to_iata
    from src.simulation.config import SimulationConfig
    from src.simulation.engine import SimulationEngine

    iata = _icao_to_iata(airport_icao)

    config = SimulationConfig(
        airport=iata,
        arrivals=40,
        departures=40,
        duration_hours=6.0,
        time_step_seconds=10.0,
        seed=42,
        start_time=datetime.now(timezone.utc).replace(
            hour=6, minute=0, second=0, microsecond=0
        ),
    )

    # Inject OSM runway data BEFORE engine init. The subprocess has no
    # airport_config_service, so _get_osm_primary_runway would return None
    # and approach paths would use fallback heading (270° for lat≥30°).
    # Monkey-patch the function to return the parent's runway data directly.
    if osm_runway:
        import src.ingestion._approach_departure as _ad
        import src.ingestion._generation as _gen
        _ad._get_osm_primary_runway = lambda: osm_runway
        _gen._get_osm_primary_runway = lambda: osm_runway

    engine = SimulationEngine(config)
    recorder = engine.run()
    recorder.write_output(output_path, config.model_dump())


def _volume_path() -> str | None:
    """Return the UC Volume path for demo files, or None if not configured."""
    catalog = os.environ.get("DATABRICKS_CATALOG")
    schema = os.environ.get("DATABRICKS_SCHEMA")
    if catalog and schema:
        return f"/Volumes/{catalog}/{schema}/demo_simulations"
    return None


class DemoSimulationService:
    """Singleton that generates and caches demo simulation files per airport."""

    _instance: Optional["DemoSimulationService"] = None

    def __init__(self) -> None:
        self._demo_files: dict[str, Path] = {}  # icao -> path
        self._demo_sources: dict[str, str] = {}  # icao -> "volume" | "local" | "generated"
        self._generating: set[str] = set()
        self._lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "DemoSimulationService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _download_from_volume(airport_icao: str) -> Path | None:
        """Download demo file from UC Volume via Databricks SDK."""
        vol = _volume_path()
        if not vol:
            return None
        try:
            from databricks.sdk import WorkspaceClient

            w = WorkspaceClient()
            remote_path = f"{vol}/demo_{airport_icao}.json"
            logger.info("Downloading static demo from Volume: %s", remote_path)
            resp = w.files.download(remote_path)
            output_path = Path(tempfile.gettempdir()) / f"demo_{airport_icao}.json"
            with open(output_path, "wb") as f:
                f.write(resp.contents.read())
            size_mb = output_path.stat().st_size / (1024 * 1024)
            logger.info("Downloaded demo from Volume: %.1f MB", size_mb)
            return output_path
        except Exception as e:
            logger.warning("Volume download failed for %s: %s", airport_icao, e)
            return None

    @staticmethod
    def _get_local_demo_path(airport_icao: str) -> Path | None:
        """Return path to a local bundled demo file, or None."""
        path = _LOCAL_DEMO_DIR / f"demo_{airport_icao}.json"
        if path.exists():
            return path
        return None

    @staticmethod
    def _seed_volume(airport_icao: str, local_path: Path) -> None:
        """Upload local demo file to UC Volume so future startups use it."""
        vol = _volume_path()
        if not vol:
            return
        try:
            from databricks.sdk import WorkspaceClient

            w = WorkspaceClient()
            remote_path = f"{vol}/demo_{airport_icao}.json"
            with open(local_path, "rb") as f:
                w.files.upload(remote_path, f, overwrite=True)
            logger.info("Seeded Volume with %s", remote_path)
        except Exception as e:
            logger.warning("Volume seeding failed for %s: %s", airport_icao, e)

    def _load_static_demo(self, airport_icao: str) -> Path | None:
        """Load a pre-generated static demo, patching start_time to today.

        Tries UC Volume first (Databricks), then local file (dev).
        If loaded from local on Databricks, seeds the Volume for next time.
        """
        raw_path = self._download_from_volume(airport_icao)
        source = "volume"
        if not raw_path:
            local = self._get_local_demo_path(airport_icao)
            if not local:
                return None
            logger.info("Loading static demo for %s from local: %s", airport_icao, local.name)
            raw_path = local
            source = "local"
            self._seed_volume(airport_icao, local)

        today_start = datetime.now(timezone.utc).replace(
            hour=6, minute=0, second=0, microsecond=0
        )

        # Fast path: patch start_time via string replace to avoid full JSON parse/serialize
        # of 10+ MB files (saves ~2s on startup)
        import re
        raw_content = raw_path.read_text()
        patched = re.sub(
            r'"start_time":\s*"[^"]*"',
            f'"start_time": "{today_start.isoformat()}"',
            raw_content,
            count=1,
        )

        output_path = Path(tempfile.gettempdir()) / f"demo_{airport_icao}.json"
        output_path.write_text(patched)

        size_mb = output_path.stat().st_size / (1024 * 1024)
        logger.info("Static demo for %s loaded from %s: %.1f MB", airport_icao, source, size_mb)
        self._demo_sources[airport_icao] = source
        return output_path

    def generate_demo(self, airport_icao: str) -> Path:
        """Generate or load a demo simulation for the airport.

        For airports with a pre-generated file (Volume or local), loads it.
        Otherwise runs SimulationEngine (CPU-bound, ~45s for 6h on Databricks).
        Returns path to the JSON output file.
        """
        static = self._load_static_demo(airport_icao)
        if static:
            self._demo_files[airport_icao] = static
            return static

        from src.calibration.profile import _icao_to_iata as icao_to_iata
        from src.simulation.config import SimulationConfig
        from src.simulation.engine import SimulationEngine

        with self._lock:
            if airport_icao in self._generating:
                logger.warning("Demo already generating for %s", airport_icao)
                existing = self._demo_files.get(airport_icao)
                if existing and existing.exists():
                    return existing
                raise RuntimeError(f"Demo generation in progress for {airport_icao}")
            self._generating.add(airport_icao)

        try:
            iata = icao_to_iata(airport_icao)
            logger.info("Generating demo simulation for %s (%s)...", airport_icao, iata)

            arrivals = 40
            departures = 40

            config = SimulationConfig(
                airport=iata,
                arrivals=arrivals,
                departures=departures,
                duration_hours=6.0,
                time_step_seconds=10.0,
                seed=42,
                start_time=datetime.now(timezone.utc).replace(
                    hour=6, minute=0, second=0, microsecond=0
                ),
            )

            engine = SimulationEngine(config)
            recorder = engine.run()

            output_path = Path(tempfile.gettempdir()) / f"demo_{airport_icao}.json"
            recorder.write_output(str(output_path), config.model_dump())

            self._demo_files[airport_icao] = output_path
            self._demo_sources[airport_icao] = "generated"
            size_mb = output_path.stat().st_size / (1024 * 1024)
            logger.info(
                "Demo simulation for %s complete: %d arr + %d dep, %.1f MB",
                airport_icao, arrivals, departures, size_mb,
            )
            return output_path

        finally:
            with self._lock:
                self._generating.discard(airport_icao)

    def generate_demo_isolated(self, airport_icao: str) -> Path | None:
        """Generate demo in a subprocess to avoid corrupting live broadcast state.

        SimulationEngine.run() mutates 30+ module-level globals shared with the
        live synthetic flight generator. Running it in-process causes the WS
        broadcast loop to emit 0 flights. Subprocess gets its own memory space.
        """
        static = self._load_static_demo(airport_icao)
        if static:
            self._demo_files[airport_icao] = static
            return static

        with self._lock:
            if airport_icao in self._generating:
                return self._demo_files.get(airport_icao)
            self._generating.add(airport_icao)

        try:
            import multiprocessing
            output_path = Path(tempfile.gettempdir()) / f"demo_{airport_icao}.json"

            # Pass OSM runway data to subprocess so it uses real approach heading
            osm_runway = None
            try:
                from src.ingestion._approach_departure import _get_osm_primary_runway
                rwy = _get_osm_primary_runway()
                if rwy:
                    osm_runway = dict(rwy)
            except Exception:
                pass

            ctx = multiprocessing.get_context("spawn")
            proc = ctx.Process(
                target=_run_engine_subprocess,
                args=(airport_icao, str(output_path), osm_runway),
            )
            proc.start()
            proc.join(timeout=120)

            if proc.exitcode != 0:
                logger.warning(
                    "Demo subprocess for %s exited with code %s",
                    airport_icao, proc.exitcode,
                )
                return None

            if not output_path.exists():
                logger.warning("Demo subprocess for %s produced no output", airport_icao)
                return None

            self._demo_files[airport_icao] = output_path
            self._demo_sources[airport_icao] = "generated"
            size_mb = output_path.stat().st_size / (1024 * 1024)
            logger.info(
                "Demo (subprocess) for %s: %.1f MB", airport_icao, size_mb,
            )
            return output_path

        except Exception as e:
            logger.warning("Isolated demo generation failed for %s: %s", airport_icao, e)
            return None
        finally:
            with self._lock:
                self._generating.discard(airport_icao)

    def get_demo_path(self, airport_icao: str) -> Path | None:
        """Return path to demo file if generated, else None."""
        path = self._demo_files.get(airport_icao)
        if path and path.exists():
            return path
        return None

    def has_demo(self, airport_icao: str) -> bool:
        return self.get_demo_path(airport_icao) is not None

    def is_generating(self, airport_icao: str) -> bool:
        return airport_icao in self._generating

    def get_source(self, airport_icao: str) -> str:
        return self._demo_sources.get(airport_icao, "unknown")

def get_demo_simulation_service() -> DemoSimulationService:
    """Get the singleton DemoSimulationService."""
    return DemoSimulationService.get_instance()

"""Demo simulation service — generates replay simulations per airport.

On startup (and on airport switch), provides a demo simulation for
auto-playing timeline replay. For the default airport (KSFO), a
pre-generated static file is shipped to avoid the 90s+ engine run.
Other airports generate a shorter 6h simulation on demand.
"""

import json
import logging
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_STATIC_DEMO_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "demo"


class DemoSimulationService:
    """Singleton that generates and caches demo simulation files per airport."""

    _instance: Optional["DemoSimulationService"] = None

    def __init__(self) -> None:
        self._demo_files: dict[str, Path] = {}  # icao -> path
        self._generating: set[str] = set()
        self._lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "DemoSimulationService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _get_static_demo_path(airport_icao: str) -> Path | None:
        """Return path to a bundled static demo file, or None."""
        path = _STATIC_DEMO_DIR / f"demo_{airport_icao}.json"
        if path.exists():
            return path
        return None

    def _load_static_demo(self, airport_icao: str) -> Path | None:
        """Load a pre-generated static demo, patching start_time to today."""
        static_path = self._get_static_demo_path(airport_icao)
        if not static_path:
            return None

        logger.info("Loading static demo for %s from %s", airport_icao, static_path.name)
        output_path = Path(tempfile.gettempdir()) / f"demo_{airport_icao}.json"

        today_start = datetime.now(timezone.utc).replace(
            hour=6, minute=0, second=0, microsecond=0
        )

        with open(static_path) as f:
            data = json.load(f)

        if "config" in data and "start_time" in data["config"]:
            data["config"]["start_time"] = today_start.isoformat()

        with open(output_path, "w") as f:
            json.dump(data, f, default=str)

        size_mb = output_path.stat().st_size / (1024 * 1024)
        logger.info("Static demo for %s loaded: %.1f MB", airport_icao, size_mb)
        return output_path

    def generate_demo(self, airport_icao: str) -> Path:
        """Generate or load a demo simulation for the airport.

        For airports with a bundled static file, loads it instantly.
        Otherwise runs SimulationEngine (CPU-bound, ~45s for 6h on Databricks).
        Returns path to the JSON output file.
        """
        static = self._load_static_demo(airport_icao)
        if static:
            self._demo_files[airport_icao] = static
            return static

        from app.backend.demo_config import icao_to_iata
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
            size_mb = output_path.stat().st_size / (1024 * 1024)
            logger.info(
                "Demo simulation for %s complete: %d arr + %d dep, %.1f MB",
                airport_icao, arrivals, departures, size_mb,
            )
            return output_path

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

def get_demo_simulation_service() -> DemoSimulationService:
    """Get the singleton DemoSimulationService."""
    return DemoSimulationService.get_instance()

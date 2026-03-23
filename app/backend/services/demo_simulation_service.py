"""Demo simulation service — generates 24h replay simulations per airport.

On startup (and on airport switch), generates a full 24h simulation using
the existing SimulationEngine. The output is served to the frontend for
auto-playing timeline replay with seek/speed controls.
"""

import logging
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


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

    def generate_demo(self, airport_icao: str) -> Path:
        """Generate a 24h demo simulation for the airport.

        Runs the SimulationEngine synchronously (CPU-bound, ~10-30s).
        Returns path to the JSON output file.
        """
        from app.backend.demo_config import icao_to_iata
        from src.calibration.profile import AirportProfileLoader
        from src.simulation.config import SimulationConfig
        from src.simulation.engine import SimulationEngine

        with self._lock:
            if airport_icao in self._generating:
                logger.warning("Demo already generating for %s", airport_icao)
                # Wait for it — return existing path if available
                existing = self._demo_files.get(airport_icao)
                if existing and existing.exists():
                    return existing
                raise RuntimeError(f"Demo generation in progress for {airport_icao}")
            self._generating.add(airport_icao)

        try:
            iata = icao_to_iata(airport_icao)
            logger.info("Generating demo simulation for %s (%s)...", airport_icao, iata)

            # Use a fixed flight count for the demo (profile doesn't store daily counts)
            arrivals = 150
            departures = 150

            config = SimulationConfig(
                airport=iata,
                arrivals=arrivals,
                departures=departures,
                duration_hours=24.0,
                time_step_seconds=5.0,
                seed=42,
                start_time=datetime.now(timezone.utc).replace(
                    hour=0, minute=0, second=0, microsecond=0
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

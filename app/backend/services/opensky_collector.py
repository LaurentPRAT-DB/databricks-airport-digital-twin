"""Continuous OpenSky ADS-B data collector for ML training.

Polls the OpenSky Network API for multiple airports in parallel,
writing flight position snapshots to Lakebase for downstream ML training.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# Target airports: ICAO → (latitude, longitude)
# Sourced from src/ingestion/airport_table.py AIRPORTS dict
COLLECTOR_AIRPORTS: dict[str, tuple[float, float]] = {
    # US majors
    "KJFK": (40.6413, -73.7781),
    "KLAX": (33.9425, -118.4081),
    "KATL": (33.6407, -84.4277),
    "KORD": (41.9742, -87.9073),
    "KDEN": (39.8561, -104.6737),
    "KSFO": (37.6213, -122.3790),
    # International
    "OMAA": (24.4431, 54.6511),   # Abu Dhabi
    "LGAV": (37.9364, 23.9445),   # Athens
    "LSGG": (46.2381, 6.1090),    # Geneva
}


@dataclass
class AirportStats:
    """Per-airport collection statistics."""
    snapshots_saved: int = 0
    last_fetch_time: Optional[datetime] = None
    last_flight_count: int = 0
    last_error: Optional[str] = None
    error_count: int = 0


class OpenSkyCollector:
    """Background collector that polls OpenSky for multiple airports."""

    def __init__(
        self,
        airports: Optional[dict[str, tuple[float, float]]] = None,
        inter_airport_delay: float = 1.0,
    ):
        self._airports = airports or COLLECTOR_AIRPORTS
        self._inter_airport_delay = inter_airport_delay
        self._session_id = f"collector-{uuid.uuid4()}"
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._stats: dict[str, AirportStats] = {
            icao: AirportStats() for icao in self._airports
        }
        self._started_at: Optional[datetime] = None

    @property
    def running(self) -> bool:
        return self._running

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def airport_count(self) -> int:
        return len(self._airports)

    def start(self) -> Optional[asyncio.Task]:
        """Start the collection loop. Idempotent — no-op if already running."""
        if self._running:
            return self._task
        self._running = True
        self._started_at = datetime.now(timezone.utc)
        self._task = asyncio.create_task(self._collect_loop())
        logger.info(
            "OpenSky collector started: session=%s, airports=%d",
            self._session_id, len(self._airports),
        )
        return self._task

    async def stop(self) -> None:
        """Stop the collection loop gracefully."""
        if not self._running:
            return
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info(
            "OpenSky collector stopped: session=%s, total_snapshots=%d",
            self._session_id,
            sum(s.snapshots_saved for s in self._stats.values()),
        )

    def get_status(self) -> dict:
        """Return collector status and per-airport statistics."""
        airports = {}
        for icao, stats in self._stats.items():
            airports[icao] = {
                "snapshots_saved": stats.snapshots_saved,
                "last_fetch_time": stats.last_fetch_time.isoformat() if stats.last_fetch_time else None,
                "last_flight_count": stats.last_flight_count,
                "last_error": stats.last_error,
                "error_count": stats.error_count,
            }

        return {
            "running": self._running,
            "session_id": self._session_id,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "airport_count": len(self._airports),
            "total_snapshots": sum(s.snapshots_saved for s in self._stats.values()),
            "airports": airports,
        }

    async def _collect_loop(self) -> None:
        """Main collection loop — cycles through airports continuously."""
        from app.backend.services.opensky_service import get_opensky_service

        opensky = get_opensky_service()

        while self._running:
            for icao, (lat, lon) in self._airports.items():
                if not self._running:
                    return

                stats = self._stats[icao]
                try:
                    flights = await opensky.fetch_flights(lat, lon)
                    stats.last_fetch_time = datetime.now(timezone.utc)
                    stats.last_flight_count = len(flights)

                    if flights:
                        saved = self._persist_snapshots(icao, flights)
                        stats.snapshots_saved += saved
                        stats.last_error = None
                    else:
                        stats.last_error = None  # Empty is valid (no traffic)

                except Exception as e:
                    stats.last_error = str(e)
                    stats.error_count += 1
                    logger.warning("Collector fetch failed for %s: %s", icao, e)

                # Rate limit: ~1s between airports
                if self._running:
                    await asyncio.sleep(self._inter_airport_delay)

    def _persist_snapshots(self, airport_icao: str, flights: list[dict]) -> int:
        """Write flight snapshots to Lakebase."""
        from app.backend.services.lakebase_service import get_lakebase_service

        lakebase = get_lakebase_service()
        if not lakebase.is_available:
            return 0

        now = datetime.now(timezone.utc).isoformat()
        snapshots = []
        for f in flights:
            snapshots.append({
                "icao24": f["icao24"],
                "callsign": f.get("callsign"),
                "latitude": f.get("latitude"),
                "longitude": f.get("longitude"),
                "altitude": f.get("altitude"),
                "velocity": f.get("velocity"),
                "heading": f.get("heading"),
                "vertical_rate": f.get("vertical_rate"),
                "on_ground": f.get("on_ground"),
                "flight_phase": f.get("flight_phase"),
                "aircraft_type": f.get("aircraft_type"),
                "assigned_gate": f.get("assigned_gate"),
                "origin_airport": f.get("origin_airport"),
                "destination_airport": f.get("destination_airport"),
                "data_source": "opensky",
                "snapshot_time": now,
            })

        return lakebase.insert_flight_snapshots(
            snapshots, self._session_id, airport_icao
        )


# ── Singleton ──

_collector: Optional[OpenSkyCollector] = None


def get_opensky_collector() -> OpenSkyCollector:
    """Get or create the singleton collector instance."""
    global _collector
    if _collector is None:
        _collector = OpenSkyCollector()
    return _collector

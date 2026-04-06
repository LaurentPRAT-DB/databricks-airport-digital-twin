"""Aircraft type database service.

Provides icao24 → aircraft type code lookup using the OpenSky aircraft
database. Used to enrich recorded ADS-B data where aircraft_type is often
missing from the state vectors.

Source: https://opensky-network.org/datasets/metadata/aircraftDatabase.csv
  - ~30MB CSV, refreshed weekly
  - Maps icao24 hex addresses to typecodes (B738, A320, etc.)

Ported from scripts/opensky_collector.py:136-202.
"""

import csv
import logging
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

OPENSKY_AIRCRAFT_DB_URL = "https://opensky-network.org/datasets/metadata/aircraftDatabase.csv"
DEFAULT_CACHE_DIR = Path("data")
CACHE_TTL_DAYS = 7


class AircraftDatabase:
    """Singleton-style service for icao24 → aircraft type lookup."""

    def __init__(self, cache_dir: Path = DEFAULT_CACHE_DIR):
        self._cache_dir = cache_dir
        self._db: dict[str, dict[str, str]] = {}
        self._loaded = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def entry_count(self) -> int:
        return len(self._db)

    async def ensure_loaded(self) -> int:
        """Download (if needed) and load the aircraft database. Returns entry count."""
        if self._loaded:
            return len(self._db)

        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = self._cache_dir / "aircraft_db.csv"

        # Use cached version if less than 7 days old
        if cache_file.exists():
            age_days = (time.time() - cache_file.stat().st_mtime) / 86400
            if age_days < CACHE_TTL_DAYS:
                count = self._parse_csv(cache_file)
                self._loaded = True
                return count

        # Download fresh copy
        logger.info("Downloading OpenSky aircraft database...")
        try:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                resp = await client.get(OPENSKY_AIRCRAFT_DB_URL)
                resp.raise_for_status()
                cache_file.write_bytes(resp.content)
                logger.info("Aircraft database cached: %.1f MB", len(resp.content) / 1e6)
        except httpx.HTTPError as e:
            logger.warning("Failed to download aircraft database: %s", e)
            if not cache_file.exists():
                self._loaded = True
                return 0
            # Fall back to stale cache

        count = self._parse_csv(cache_file)
        self._loaded = True
        return count

    def load_from_file(self, path: Path) -> int:
        """Load from a local CSV file (for testing or offline use)."""
        count = self._parse_csv(path)
        self._loaded = True
        return count

    def lookup(self, icao24: str) -> tuple[str, str]:
        """Look up aircraft type and registration for an icao24 address.

        Returns:
            (typecode, registration) — empty strings if not found.
        """
        entry = self._db.get(icao24.lower(), {})
        return entry.get("typecode", ""), entry.get("registration", "")

    def _parse_csv(self, path: Path) -> int:
        """Parse the OpenSky aircraft CSV into the lookup dict."""
        self._db = {}
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    icao24 = (row.get("icao24") or "").strip().lower()
                    if not icao24:
                        continue
                    typecode = (row.get("typecode") or "").strip()
                    registration = (row.get("registration") or "").strip()
                    if typecode or registration:
                        self._db[icao24] = {
                            "typecode": typecode,
                            "registration": registration,
                        }
        except Exception as e:
            logger.warning("Error parsing aircraft database: %s", e)

        logger.info("Aircraft database loaded: %d entries", len(self._db))
        return len(self._db)


# Module-level singleton
_instance: AircraftDatabase | None = None


def get_aircraft_database(cache_dir: Path = DEFAULT_CACHE_DIR) -> AircraftDatabase:
    """Get or create the singleton AircraftDatabase instance."""
    global _instance
    if _instance is None:
        _instance = AircraftDatabase(cache_dir=cache_dir)
    return _instance

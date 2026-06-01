"""FLIFO service layer with caching and graceful degradation.

Active only when FLIFO_BASE_URL + FLIFO_CLIENT_ID + FLIFO_CLIENT_SECRET are set.
"""

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.ingestion.flifo_client import FlifoClient
from src.ingestion.flifo_mapper import map_flifo_response
from app.backend.services.lakebase_service import get_lakebase_service

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 60


class FlifoService:
    """Service for FLIFO flight data with polling cache."""

    def __init__(self):
        base_url = os.getenv("FLIFO_BASE_URL", "")
        client_id = os.getenv("FLIFO_CLIENT_ID", "")
        client_secret = os.getenv("FLIFO_CLIENT_SECRET", "")
        self._mock_mode = os.getenv("FLIFO_MOCK_MODE", "").lower() in ("true", "1", "yes")

        self._client: Optional[FlifoClient] = None
        if base_url and client_id and client_secret:
            self._client = FlifoClient(base_url, client_id, client_secret)
            logger.info(f"FLIFO service configured: {base_url} (mock={self._mock_mode})")

        self._cache: dict[str, tuple[float, list[dict]]] = {}
        self._last_error: Optional[str] = None

    @property
    def is_available(self) -> bool:
        return self._client is not None and self._client.is_configured

    def get_schedule(
        self,
        airport_iata: str,
        flight_type: Optional[str] = None,
        hours_behind: int = 1,
        hours_ahead: int = 2,
        limit: int = 50,
    ) -> Optional[list[dict]]:
        """Fetch schedule from FLIFO, with cache.

        Returns None if FLIFO is not configured or errors out (graceful degradation).
        """
        if not self.is_available:
            return None

        cache_key = f"{airport_iata}:{flight_type or 'both'}:{hours_behind}:{hours_ahead}"
        cached = self._cache.get(cache_key)
        if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
            return cached[1][:limit]

        try:
            now = datetime.now(timezone.utc)
            from_date = (now - timedelta(hours=hours_behind)).strftime("%Y-%m-%dT%H:%M:%SZ")
            to_date = (now + timedelta(hours=hours_ahead)).strftime("%Y-%m-%dT%H:%M:%SZ")

            raw = self._fetch_raw(airport_iata, flight_type, from_date, to_date, limit)

            mapped = map_flifo_response(raw, airport_iata, direction=flight_type)
            self._cache[cache_key] = (time.time(), mapped)
            self._last_error = None
            logger.info(f"FLIFO: fetched {len(mapped)} flights for {airport_iata}/{flight_type}")

            # Persist to Lakebase for analytics/ML pipelines
            self._persist_to_lakebase(mapped, airport_iata)

            return mapped[:limit]

        except Exception as e:
            self._last_error = str(e)
            logger.warning(f"FLIFO fetch failed, falling back: {e}")
            # Return stale cache if available
            if cached:
                return cached[1][:limit]
            return None


    def _fetch_raw(self, airport_iata: str, flight_type: Optional[str], from_date: str, to_date: str, limit: int) -> dict:
        """Fetch raw FLIFO data — direct in-process call for mock, HTTP for real."""
        if self._mock_mode:
            from tools.flifo_mock.generator import generate_flights
            from datetime import datetime, timezone
            from_dt = datetime.fromisoformat(from_date.replace("Z", "+00:00"))
            to_dt = datetime.fromisoformat(to_date.replace("Z", "+00:00"))
            records = generate_flights(
                airport_iata=airport_iata,
                direction=flight_type,
                from_time=from_dt,
                to_time=to_dt,
                count=limit,
            )
            return {
                "flightRecords": [r.model_dump() for r in records],
                "totalRecords": len(records),
                "airport": airport_iata,
            }

        return self._client.get_flights_by_airport(
            airport_iata=airport_iata,
            direction=flight_type,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
        )

    def _persist_to_lakebase(self, flights: list[dict], airport_iata: str) -> None:
        """Write FLIFO data to Lakebase for DLT pipeline and ML models."""
        try:
            lakebase = get_lakebase_service()
            if not lakebase.is_available:
                return

            # Resolve ICAO from IATA for Lakebase (uses airport_icao)
            from src.ingestion.schedule_generator import AIRPORT_COORDINATES
            airport_icao = f"K{airport_iata}" if len(airport_iata) == 3 else airport_iata
            for code, coords in AIRPORT_COORDINATES.items():
                if code == airport_iata:
                    airport_icao = f"K{airport_iata}"
                    break

            count = lakebase.upsert_schedule(flights, airport_icao=airport_icao)
            if count > 0:
                logger.debug(f"FLIFO: persisted {count} flights to Lakebase")
        except Exception as e:
            logger.warning(f"FLIFO: Lakebase persistence failed (non-fatal): {e}")


_flifo_service: Optional[FlifoService] = None


def get_flifo_service() -> FlifoService:
    global _flifo_service
    if _flifo_service is None:
        _flifo_service = FlifoService()
    return _flifo_service

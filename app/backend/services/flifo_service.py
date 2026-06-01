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

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 60


class FlifoService:
    """Service for FLIFO flight data with polling cache."""

    def __init__(self):
        base_url = os.getenv("FLIFO_BASE_URL", "")
        client_id = os.getenv("FLIFO_CLIENT_ID", "")
        client_secret = os.getenv("FLIFO_CLIENT_SECRET", "")

        self._client: Optional[FlifoClient] = None
        if base_url and client_id and client_secret:
            self._client = FlifoClient(base_url, client_id, client_secret)
            logger.info(f"FLIFO service configured: {base_url}")

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

            raw = self._client.get_flights_by_airport(
                airport_iata=airport_iata,
                direction=flight_type,
                from_date=from_date,
                to_date=to_date,
                limit=limit,
            )

            mapped = map_flifo_response(raw, airport_iata, direction=flight_type)
            self._cache[cache_key] = (time.time(), mapped)
            self._last_error = None
            logger.info(f"FLIFO: fetched {len(mapped)} flights for {airport_iata}/{flight_type}")
            return mapped[:limit]

        except Exception as e:
            self._last_error = str(e)
            logger.warning(f"FLIFO fetch failed, falling back: {e}")
            # Return stale cache if available
            if cached:
                return cached[1][:limit]
            return None


_flifo_service: Optional[FlifoService] = None


def get_flifo_service() -> FlifoService:
    global _flifo_service
    if _flifo_service is None:
        _flifo_service = FlifoService()
    return _flifo_service

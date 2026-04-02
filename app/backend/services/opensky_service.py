"""OpenSky Network service for live ADS-B flight data.

Fetches real-time aircraft positions from the OpenSky Network REST API
and converts them to our FlightPosition schema.

API docs: https://openskynetwork.github.io/opensky-api/rest.html
Rate limits: 10 requests per 10 seconds (anonymous), better with account.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# OpenSky state vector field indices
_ICAO24 = 0
_CALLSIGN = 1
_ORIGIN_COUNTRY = 2
_TIME_POSITION = 3
_LAST_CONTACT = 4
_LONGITUDE = 5
_LATITUDE = 6
_BARO_ALTITUDE = 7  # meters
_ON_GROUND = 8
_VELOCITY = 9  # m/s
_TRUE_TRACK = 10  # degrees
_VERTICAL_RATE = 11  # m/s
_GEO_ALTITUDE = 13  # meters

# Unit conversions
_M_TO_FT = 3.28084
_MS_TO_KTS = 1.94384
_MS_TO_FTMIN = 196.85

# Default bounding box radius in degrees (~30nm ≈ 0.5°)
_DEFAULT_RADIUS_DEG = 0.5

OPENSKY_API_URL = "https://opensky-network.org/api/states/all"


def _determine_flight_phase(
    altitude_ft: float, vertical_rate_ftmin: float, on_ground: bool
) -> str:
    """Determine flight phase from altitude, vertical rate, and ground status."""
    if on_ground:
        return "ground"
    if altitude_ft < 3000 and vertical_rate_ftmin > 200:
        return "takeoff"
    if altitude_ft < 3000 and vertical_rate_ftmin < -200:
        return "landing"
    if altitude_ft < 10000 and vertical_rate_ftmin < -500:
        return "approaching"
    if altitude_ft < 10000 and vertical_rate_ftmin > 500:
        return "departing"
    if vertical_rate_ftmin > 200:
        return "climb"
    if vertical_rate_ftmin < -200:
        return "descent"
    return "cruise"


class OpenSkyService:
    """Fetches live ADS-B data from the OpenSky Network API."""

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: float = 15.0,
    ):
        self._auth = (username, password) if username and password else None
        self._timeout = timeout
        self._last_fetch_time: Optional[float] = None
        self._last_flight_count: int = 0
        self._last_error: Optional[str] = None
        self._client = httpx.AsyncClient(timeout=timeout)

    async def fetch_flights(
        self,
        lat: float,
        lon: float,
        radius_deg: float = _DEFAULT_RADIUS_DEG,
    ) -> list[dict]:
        """Fetch live flights within a bounding box around the given coordinates.

        Args:
            lat: Airport center latitude.
            lon: Airport center longitude.
            radius_deg: Bounding box half-size in degrees (~0.5° ≈ 30nm).

        Returns:
            List of dicts compatible with FlightPosition fields.
        """
        params = {
            "lamin": lat - radius_deg,
            "lamax": lat + radius_deg,
            "lomin": lon - radius_deg,
            "lomax": lon + radius_deg,
        }

        try:
            kwargs: dict = {"params": params}
            if self._auth:
                kwargs["auth"] = self._auth

            response = await self._client.get(OPENSKY_API_URL, **kwargs)

            if response.status_code == 429:
                logger.warning("OpenSky rate limited (429), backing off")
                self._last_error = "Rate limited"
                return []

            response.raise_for_status()
            data = response.json()

            states = data.get("states") or []
            flights = []

            for state in states:
                flight = self._state_to_flight(state)
                if flight:
                    flights.append(flight)

            self._last_fetch_time = time.time()
            self._last_flight_count = len(flights)
            self._last_error = None

            logger.info("OpenSky: fetched %d flights near (%.2f, %.2f)", len(flights), lat, lon)
            return flights

        except httpx.HTTPStatusError as e:
            self._last_error = f"HTTP {e.response.status_code}"
            logger.warning("OpenSky API error: %s", e)
            return []
        except Exception as e:
            self._last_error = str(e)
            logger.warning("OpenSky fetch failed: %s", e)
            return []

    def _state_to_flight(self, state: list) -> Optional[dict]:
        """Convert an OpenSky state vector to our flight dict format."""
        if len(state) < 12:
            return None

        icao24 = state[_ICAO24]
        callsign = (state[_CALLSIGN] or "").strip()
        latitude = state[_LATITUDE]
        longitude = state[_LONGITUDE]

        # Skip flights with no position
        if latitude is None or longitude is None:
            return None

        on_ground = bool(state[_ON_GROUND])
        baro_alt_m = state[_BARO_ALTITUDE] or 0.0
        velocity_ms = state[_VELOCITY] or 0.0
        heading = state[_TRUE_TRACK]
        vrate_ms = state[_VERTICAL_RATE] or 0.0
        last_contact = state[_LAST_CONTACT]

        # Convert units
        altitude_ft = baro_alt_m * _M_TO_FT
        velocity_kts = velocity_ms * _MS_TO_KTS
        vrate_ftmin = vrate_ms * _MS_TO_FTMIN

        flight_phase = _determine_flight_phase(altitude_ft, vrate_ftmin, on_ground)

        return {
            "icao24": icao24,
            "callsign": callsign or icao24.upper(),
            "latitude": latitude,
            "longitude": longitude,
            "altitude": altitude_ft,
            "velocity": velocity_kts,
            "heading": heading,
            "on_ground": on_ground,
            "vertical_rate": vrate_ftmin,
            "last_seen": last_contact,
            "data_source": "opensky",
            "flight_phase": flight_phase,
            "aircraft_type": None,
            "assigned_gate": None,
            "origin_airport": None,
            "destination_airport": None,
        }

    def get_status(self) -> dict:
        """Return service health status."""
        return {
            "available": True,
            "last_fetch_time": (
                datetime.fromtimestamp(self._last_fetch_time, tz=timezone.utc).isoformat()
                if self._last_fetch_time
                else None
            ),
            "last_flight_count": self._last_flight_count,
            "last_error": self._last_error,
            "authenticated": self._auth is not None,
        }

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()


# Singleton
_opensky_service: Optional[OpenSkyService] = None


def get_opensky_service() -> OpenSkyService:
    """Get or create the OpenSky service singleton."""
    global _opensky_service
    if _opensky_service is None:
        import os
        _opensky_service = OpenSkyService(
            username=os.getenv("OPENSKY_USERNAME"),
            password=os.getenv("OPENSKY_PASSWORD"),
        )
    return _opensky_service

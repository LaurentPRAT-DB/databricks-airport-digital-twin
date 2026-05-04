"""Weather service for aviation METAR/TAF data.

Provides current weather observations and forecasts.
In live mode, fetches real METAR from aviationweather.gov.
Otherwise reads from Lakebase first, falls back to synthetic generator.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from src.ingestion.weather_generator import (
    generate_metar,
    generate_taf,
    get_cached_weather,
)
from app.backend.models.weather import (
    METAR,
    TAF,
    CloudLayer,
    FlightCategory,
    SkyCondition,
    WeatherResponse,
)
from app.backend.services.lakebase_service import get_lakebase_service

logger = logging.getLogger(__name__)

AVIATION_WEATHER_API = "https://aviationweather.gov/api/data/metar"


async def _fetch_live_metar(station: str) -> Optional[dict]:
    """Fetch real METAR from aviationweather.gov.

    Returns a dict compatible with _dict_to_metar, or None on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                AVIATION_WEATHER_API,
                params={"ids": station, "format": "json", "taf": "false", "hours": 1},
            )
            if resp.status_code != 200:
                logger.warning("aviationweather.gov returned HTTP %d for %s", resp.status_code, station)
                return None

            data = resp.json()
            if not data:
                return None

            obs = data[0]

            # Map cloud layers
            clouds = []
            for c in obs.get("clouds", []):
                cover = c.get("cover", "")
                base = c.get("base")
                if cover in ("SKC", "CLR"):
                    continue
                if cover in ("FEW", "SCT", "BKN", "OVC") and base is not None:
                    clouds.append({"coverage": cover, "altitude_ft": int(base)})

            # Convert altimeter from hPa to inHg (1 hPa = 0.02953 inHg)
            altim_hpa = obs.get("altim")
            altimeter_inhg = round(altim_hpa * 0.02953, 2) if altim_hpa else 29.92

            wdir = obs.get("wdir")
            wind_direction = int(wdir) if wdir and str(wdir).isdigit() else None

            return {
                "station": obs.get("icaoId", station),
                "observation_time": obs.get("reportTime", datetime.now(timezone.utc).isoformat()),
                "wind_direction": wind_direction,
                "wind_speed_kts": int(obs.get("wspd", 0)),
                "wind_gust_kts": int(obs["wgst"]) if obs.get("wgst") else None,
                "visibility_sm": float(obs.get("visib", 10)),
                "clouds": clouds,
                "temperature_c": int(obs.get("temp", 15)),
                "dewpoint_c": int(obs.get("dewp", 10)),
                "altimeter_inhg": altimeter_inhg,
                "weather": [],
                "flight_category": obs.get("fltcat", "VFR"),
                "raw_metar": obs.get("rawOb", ""),
            }
    except Exception as e:
        logger.warning("Failed to fetch live METAR for %s: %s", station, e)
        return None


def _dict_to_metar(data: dict) -> METAR:
    """Convert weather dictionary to METAR model."""
    clouds = [
        CloudLayer(
            coverage=SkyCondition(c["coverage"]),
            altitude_ft=c["altitude_ft"]
        )
        for c in data.get("clouds", [])
    ]

    return METAR(
        station=data["station"],
        observation_time=datetime.fromisoformat(data["observation_time"]),
        wind_direction=data.get("wind_direction"),
        wind_speed_kts=data.get("wind_speed_kts", 0),
        wind_gust_kts=data.get("wind_gust_kts"),
        visibility_sm=data["visibility_sm"],
        clouds=clouds,
        temperature_c=data["temperature_c"],
        dewpoint_c=data["dewpoint_c"],
        altimeter_inhg=data["altimeter_inhg"],
        weather=data.get("weather", []),
        flight_category=FlightCategory(data["flight_category"]),
        raw_metar=data.get("raw_metar"),
    )


def _dict_to_taf(data: dict) -> TAF:
    """Convert TAF dictionary to TAF model."""
    return TAF(
        station=data["station"],
        issue_time=datetime.fromisoformat(data["issue_time"]),
        valid_from=datetime.fromisoformat(data["valid_from"]),
        valid_to=datetime.fromisoformat(data["valid_to"]),
        forecast_text=data["forecast_text"],
    )


class WeatherService:
    """Service for weather operations."""

    def __init__(self, default_station: str = "KSFO"):
        """Initialize weather service."""
        self._default_station = default_station

    async def get_current_weather(self, station: Optional[str] = None, live: bool = False) -> WeatherResponse:
        """
        Get current weather observation and forecast.

        When live=True, fetches real METAR from aviationweather.gov.
        Otherwise reads from Lakebase first, falls back to in-memory generator.

        Args:
            station: ICAO station identifier (defaults to KSFO)
            live: If True, fetch real METAR from aviationweather.gov

        Returns:
            WeatherResponse with METAR and TAF
        """
        station = station or self._default_station

        if live:
            live_data = await _fetch_live_metar(station)
            if live_data:
                logger.info("Live METAR for %s: %s", station, live_data.get("flight_category"))
                metar = _dict_to_metar(live_data)
                return WeatherResponse(metar=metar, taf=None, station=station)
            logger.warning("Live METAR fetch failed for %s, falling back", station)

        # Try Lakebase first (persisted data)
        lakebase = get_lakebase_service()
        cached = lakebase.get_weather(station) if lakebase.is_available else None

        if cached:
            logger.debug(f"Weather from Lakebase for {station}")
            metar = _dict_to_metar({
                "station": cached["station"],
                "observation_time": cached["observation_time"].isoformat() if hasattr(cached["observation_time"], "isoformat") else cached["observation_time"],
                "wind_direction": cached.get("wind_direction"),
                "wind_speed_kts": cached.get("wind_speed_kts", 0),
                "wind_gust_kts": cached.get("wind_gust_kts"),
                "visibility_sm": float(cached["visibility_sm"]),
                "clouds": cached.get("clouds", []),
                "temperature_c": cached["temperature_c"],
                "dewpoint_c": cached["dewpoint_c"],
                "altimeter_inhg": float(cached["altimeter_inhg"]),
                "weather": cached.get("weather", []),
                "flight_category": cached["flight_category"],
                "raw_metar": cached.get("raw_metar"),
            })
            taf = TAF(
                station=cached["station"],
                issue_time=cached.get("observation_time") or datetime.now(timezone.utc),
                valid_from=cached.get("taf_valid_from") or datetime.now(timezone.utc),
                valid_to=cached.get("taf_valid_to") or datetime.now(timezone.utc),
                forecast_text=cached.get("taf_text", ""),
            )
        else:
            # Fallback to in-memory generator
            logger.debug(f"Weather from generator for {station}")
            generated = get_cached_weather(station=station)
            metar = _dict_to_metar(generated["metar"])
            taf = _dict_to_taf(generated["taf"])

        logger.info(f"Weather service returning {metar.flight_category} conditions for {station}")

        return WeatherResponse(
            metar=metar,
            taf=taf,
            station=station,
        )

    def get_metar(self, station: Optional[str] = None) -> METAR:
        """
        Get current METAR observation only.

        Args:
            station: ICAO station identifier

        Returns:
            METAR observation
        """
        station = station or self._default_station
        raw_metar = generate_metar(station=station)
        return _dict_to_metar(raw_metar)

    def get_taf(self, station: Optional[str] = None) -> TAF:
        """
        Get current TAF forecast only.

        Args:
            station: ICAO station identifier

        Returns:
            TAF forecast
        """
        station = station or self._default_station
        raw_taf = generate_taf(station=station)
        return _dict_to_taf(raw_taf)

    def get_flight_category(self, station: Optional[str] = None) -> str:
        """
        Get current flight category for a station.

        Args:
            station: ICAO station identifier

        Returns:
            Flight category string (VFR, MVFR, IFR, LIFR)
        """
        metar = self.get_metar(station)
        return metar.flight_category.value


# Singleton instance
_weather_service: Optional[WeatherService] = None


def get_weather_service() -> WeatherService:
    """Get or create weather service singleton."""
    global _weather_service
    if _weather_service is None:
        _weather_service = WeatherService()
    return _weather_service

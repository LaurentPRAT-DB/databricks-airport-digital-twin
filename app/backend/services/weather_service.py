"""Weather service for aviation METAR/TAF data.

Provides current weather observations and forecasts.
Reads from Lakebase first for persistence, falls back to generator.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

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

    def get_current_weather(self, station: Optional[str] = None) -> WeatherResponse:
        """
        Get current weather observation and forecast.

        Reads from Lakebase first for persistence, falls back to in-memory generator.

        Args:
            station: ICAO station identifier (defaults to KSFO)

        Returns:
            WeatherResponse with METAR and TAF
        """
        station = station or self._default_station

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

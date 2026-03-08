"""Weather service for aviation METAR/TAF data.

Provides current weather observations and forecasts using synthetic generation.
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

        Args:
            station: ICAO station identifier (defaults to KSFO)

        Returns:
            WeatherResponse with METAR and TAF
        """
        station = station or self._default_station
        cached = get_cached_weather(station=station)

        metar = _dict_to_metar(cached["metar"])
        taf = _dict_to_taf(cached["taf"])

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

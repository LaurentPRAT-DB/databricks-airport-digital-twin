"""Weather endpoints — current conditions."""

from typing import Optional

from fastapi import APIRouter, Query

from app.backend.models.weather import WeatherResponse
from app.backend.services.weather_service import get_weather_service

router = APIRouter(prefix="/api", tags=["weather"])


@router.get("/weather/current", response_model=WeatherResponse)
async def get_current_weather(
    station: Optional[str] = Query(default=None, description="ICAO station (default: KSFO)"),
    live: bool = Query(default=False, description="Fetch real METAR from aviationweather.gov"),
) -> WeatherResponse:
    """Get current weather observation and forecast."""
    service = get_weather_service()
    return await service.get_current_weather(station=station, live=live)

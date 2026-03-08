"""Weather models for METAR/TAF aviation weather data."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class FlightCategory(str, Enum):
    """Flight category based on visibility and ceiling."""
    VFR = "VFR"      # Visual Flight Rules - ceiling > 3000 ft, visibility > 5 SM
    MVFR = "MVFR"    # Marginal VFR - ceiling 1000-3000 ft or visibility 3-5 SM
    IFR = "IFR"      # Instrument Flight Rules - ceiling 500-1000 ft or visibility 1-3 SM
    LIFR = "LIFR"    # Low IFR - ceiling < 500 ft or visibility < 1 SM


class SkyCondition(str, Enum):
    """Sky condition coverage."""
    SKC = "SKC"      # Sky clear
    FEW = "FEW"      # Few clouds (1-2 oktas)
    SCT = "SCT"      # Scattered (3-4 oktas)
    BKN = "BKN"      # Broken (5-7 oktas)
    OVC = "OVC"      # Overcast (8 oktas)


class WeatherPhenomenon(str, Enum):
    """Weather phenomena."""
    RA = "RA"        # Rain
    SN = "SN"        # Snow
    FG = "FG"        # Fog
    BR = "BR"        # Mist
    HZ = "HZ"        # Haze
    TS = "TS"        # Thunderstorm
    SH = "SH"        # Showers


class CloudLayer(BaseModel):
    """A single cloud layer in the METAR."""
    coverage: SkyCondition
    altitude_ft: int = Field(..., description="Cloud base altitude in feet AGL")


class METAR(BaseModel):
    """METAR (Meteorological Aerodrome Report) model."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "station": "KSFO",
                "observation_time": "2026-03-08T12:00:00Z",
                "wind_direction": 280,
                "wind_speed_kts": 12,
                "wind_gust_kts": None,
                "visibility_sm": 10.0,
                "clouds": [{"coverage": "SCT", "altitude_ft": 4500}],
                "temperature_c": 15,
                "dewpoint_c": 8,
                "altimeter_inhg": 30.05,
                "flight_category": "VFR",
                "raw_metar": "KSFO 081200Z 28012KT 10SM SCT045 15/08 A3005",
            }
        }
    )

    station: str = Field(..., description="ICAO station identifier")
    observation_time: datetime = Field(..., description="Observation time")
    wind_direction: Optional[int] = Field(None, description="Wind direction in degrees")
    wind_speed_kts: int = Field(0, description="Wind speed in knots")
    wind_gust_kts: Optional[int] = Field(None, description="Wind gust speed in knots")
    wind_variable_from: Optional[int] = Field(None, description="Variable wind from direction")
    wind_variable_to: Optional[int] = Field(None, description="Variable wind to direction")
    visibility_sm: float = Field(..., description="Visibility in statute miles")
    clouds: list[CloudLayer] = Field(default_factory=list, description="Cloud layers")
    temperature_c: int = Field(..., description="Temperature in Celsius")
    dewpoint_c: int = Field(..., description="Dewpoint in Celsius")
    altimeter_inhg: float = Field(..., description="Altimeter setting in inches Hg")
    weather: list[str] = Field(default_factory=list, description="Weather phenomena")
    flight_category: FlightCategory = Field(..., description="Flight category")
    raw_metar: Optional[str] = Field(None, description="Raw METAR string")


class TAF(BaseModel):
    """TAF (Terminal Aerodrome Forecast) model - simplified."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "station": "KSFO",
                "issue_time": "2026-03-08T06:00:00Z",
                "valid_from": "2026-03-08T06:00:00Z",
                "valid_to": "2026-03-09T06:00:00Z",
                "forecast_text": "28012KT P6SM SCT045",
            }
        }
    )

    station: str = Field(..., description="ICAO station identifier")
    issue_time: datetime = Field(..., description="TAF issue time")
    valid_from: datetime = Field(..., description="Forecast valid from")
    valid_to: datetime = Field(..., description="Forecast valid to")
    forecast_text: str = Field(..., description="Simplified forecast summary")


class WeatherResponse(BaseModel):
    """Response model for weather endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "metar": {},
                "taf": {},
                "timestamp": "2026-03-08T12:00:00Z",
                "station": "KSFO",
            }
        }
    )

    metar: METAR = Field(..., description="Current METAR observation")
    taf: Optional[TAF] = Field(None, description="TAF forecast")
    timestamp: datetime = Field(default_factory=_utc_now, description="Response timestamp")
    station: str = Field(..., description="Station identifier")

"""Shared weather data types used by both the synthetic generator and the real METAR parser.

Both weather_generator.generate_metar() and metar_history._to_weather_snapshot()
must produce dicts that are valid WeatherSnapshot instances.  Tests verify this
contract so the two paths cannot silently drift apart.
"""

from typing import Literal, Optional

from pydantic import BaseModel

FlightCategory = Literal["VFR", "MVFR", "IFR", "LIFR"]


class WeatherSnapshot(BaseModel):
    """Common weather fields that all weather sources must provide."""

    wind_speed_kts: int
    wind_gust_kts: Optional[int] = None
    wind_direction: int
    visibility_sm: float
    temperature_c: Optional[float] = None
    dewpoint_c: Optional[float] = None
    flight_category: FlightCategory
    raw_metar: str

"""Synthetic METAR/TAF weather generator for aviation weather display.

Generates realistic weather patterns with:
- Morning fog (6-9am)
- Afternoon convection
- Diurnal temperature variation
"""

import random
from datetime import datetime, timedelta, timezone
from typing import Optional


def _determine_flight_category(visibility_sm: float, ceiling_ft: Optional[int]) -> str:
    """Determine flight category from visibility and ceiling."""
    # Use very high ceiling if no clouds reported
    effective_ceiling = ceiling_ft if ceiling_ft else 99999

    # LIFR: ceiling < 500 ft OR visibility < 1 SM
    if effective_ceiling < 500 or visibility_sm < 1:
        return "LIFR"
    # IFR: ceiling 500-999 ft OR visibility 1-2.99 SM
    if effective_ceiling < 1000 or visibility_sm < 3:
        return "IFR"
    # MVFR: ceiling 1000-2999 ft OR visibility 3-4.99 SM
    if effective_ceiling < 3000 or visibility_sm < 5:
        return "MVFR"
    # VFR: ceiling >= 3000 ft AND visibility >= 5 SM
    return "VFR"


def _get_wind_for_hour(hour: int, base_direction: int = 280) -> tuple[int, int, Optional[int]]:
    """Get wind parameters based on time of day."""
    # Morning: calm winds
    if 5 <= hour < 9:
        direction = base_direction + random.randint(-20, 20)
        speed = random.randint(2, 8)
        gust = None
    # Midday/afternoon: stronger, gusty
    elif 12 <= hour < 18:
        direction = base_direction + random.randint(-30, 30)
        speed = random.randint(8, 18)
        gust = speed + random.randint(5, 12) if random.random() < 0.3 else None
    # Evening: calming
    elif 18 <= hour < 22:
        direction = base_direction + random.randint(-20, 20)
        speed = random.randint(5, 12)
        gust = None
    # Night: light
    else:
        direction = base_direction + random.randint(-15, 15)
        speed = random.randint(0, 6)
        gust = None

    # Normalize direction
    direction = direction % 360
    return direction, speed, gust


def _get_visibility_for_hour(hour: int) -> float:
    """Get visibility based on time of day."""
    # Morning fog (6-9am): 20% chance of reduced visibility
    if 6 <= hour < 10 and random.random() < 0.2:
        return round(random.uniform(0.5, 3.0), 1)
    # Afternoon rain (14-18): 10% chance of reduced visibility
    if 14 <= hour < 18 and random.random() < 0.1:
        return round(random.uniform(3.0, 6.0), 1)
    # Clear conditions
    return 10.0


def _get_clouds_for_hour(hour: int, visibility_sm: float) -> list[dict]:
    """Generate cloud layers based on conditions."""
    clouds = []

    # Fog/mist produces low clouds
    if visibility_sm < 3:
        clouds.append({
            "coverage": "BKN" if visibility_sm < 1 else "SCT",
            "altitude_ft": random.randint(100, 500) if visibility_sm < 1 else random.randint(500, 1500)
        })
        return clouds

    # Clear morning/evening
    if hour < 8 or hour > 20:
        if random.random() < 0.3:
            clouds.append({
                "coverage": "FEW",
                "altitude_ft": random.randint(8000, 15000)
            })
        return clouds

    # Daytime: some cloud development
    if random.random() < 0.6:
        coverage = random.choice(["FEW", "SCT", "BKN"])
        base = random.randint(3000, 8000)
        clouds.append({
            "coverage": coverage,
            "altitude_ft": base
        })

        # Sometimes add a second layer
        if random.random() < 0.3:
            clouds.append({
                "coverage": "SCT",
                "altitude_ft": base + random.randint(4000, 10000)
            })

    return clouds


def _get_temperature_for_hour(hour: int, base_temp: int = 15) -> tuple[int, int]:
    """Get temperature and dewpoint based on time of day."""
    # Diurnal temperature variation
    if 5 <= hour < 8:
        temp = base_temp - random.randint(3, 6)  # Cool morning
    elif 8 <= hour < 12:
        temp = base_temp + random.randint(0, 4)  # Warming
    elif 12 <= hour < 16:
        temp = base_temp + random.randint(4, 8)  # Warm afternoon
    elif 16 <= hour < 20:
        temp = base_temp + random.randint(2, 5)  # Cooling
    else:
        temp = base_temp - random.randint(0, 3)  # Night

    # Dewpoint spread (affects fog formation)
    spread = random.randint(3, 12)
    dewpoint = temp - spread

    return temp, dewpoint


def _get_weather_phenomena(visibility_sm: float, hour: int) -> list[str]:
    """Get weather phenomena codes."""
    phenomena = []

    if visibility_sm < 1:
        phenomena.append("FG")  # Fog
    elif visibility_sm < 3:
        phenomena.append("BR")  # Mist

    # Afternoon rain chance
    if 14 <= hour < 18 and random.random() < 0.1:
        if random.random() < 0.3:
            phenomena.append("-RA")  # Light rain
        else:
            phenomena.append("RA")  # Rain

    return phenomena


def _format_raw_metar(
    station: str,
    obs_time: datetime,
    wind_dir: int,
    wind_speed: int,
    wind_gust: Optional[int],
    visibility: float,
    clouds: list[dict],
    temp: int,
    dewpoint: int,
    altimeter: float,
    phenomena: list[str],
) -> str:
    """Format a raw METAR string."""
    parts = [
        station,
        obs_time.strftime("%d%H%MZ"),
    ]

    # Wind
    wind_str = f"{wind_dir:03d}{wind_speed:02d}"
    if wind_gust:
        wind_str += f"G{wind_gust:02d}"
    wind_str += "KT"
    parts.append(wind_str)

    # Visibility
    if visibility >= 10:
        parts.append("10SM")
    else:
        parts.append(f"{visibility}SM")

    # Weather phenomena
    parts.extend(phenomena)

    # Clouds
    for cloud in clouds:
        altitude_100s = cloud["altitude_ft"] // 100
        parts.append(f"{cloud['coverage']}{altitude_100s:03d}")
    if not clouds:
        parts.append("SKC")

    # Temp/dewpoint
    temp_str = f"M{abs(temp):02d}" if temp < 0 else f"{temp:02d}"
    dp_str = f"M{abs(dewpoint):02d}" if dewpoint < 0 else f"{dewpoint:02d}"
    parts.append(f"{temp_str}/{dp_str}")

    # Altimeter
    parts.append(f"A{int(altimeter * 100)}")

    return " ".join(parts)


# Per-station weather defaults (base temperature °C, prevailing wind direction °)
# Sources: historical averages from weather stations at each airport
STATION_WEATHER_PARAMS: dict[str, dict[str, int]] = {
    "KSFO": {"base_temp": 15, "base_wind_dir": 280},
    "KJFK": {"base_temp": 14, "base_wind_dir": 290},
    "KATL": {"base_temp": 18, "base_wind_dir": 300},
    "KORD": {"base_temp": 12, "base_wind_dir": 270},
    "KLAX": {"base_temp": 19, "base_wind_dir": 250},
    "KDFW": {"base_temp": 20, "base_wind_dir": 180},
    "KDEN": {"base_temp": 12, "base_wind_dir": 200},
    "KSEA": {"base_temp": 12, "base_wind_dir": 200},
    "KMIA": {"base_temp": 26, "base_wind_dir": 140},
    "KEWR": {"base_temp": 14, "base_wind_dir": 280},
    "KBOS": {"base_temp": 12, "base_wind_dir": 270},
    "KPHX": {"base_temp": 28, "base_wind_dir": 240},
    "KLAS": {"base_temp": 24, "base_wind_dir": 210},
    "KMCO": {"base_temp": 24, "base_wind_dir": 290},
    "KCLT": {"base_temp": 17, "base_wind_dir": 230},
    "KMSP": {"base_temp": 8, "base_wind_dir": 310},
    "KDTW": {"base_temp": 10, "base_wind_dir": 250},
    "KPHL": {"base_temp": 14, "base_wind_dir": 270},
    "KIAH": {"base_temp": 22, "base_wind_dir": 170},
    "KSAN": {"base_temp": 19, "base_wind_dir": 280},
    "KPDX": {"base_temp": 13, "base_wind_dir": 190},
    # International
    "EGLL": {"base_temp": 12, "base_wind_dir": 260},  # London Heathrow
    "LSGG": {"base_temp": 10, "base_wind_dir": 220},  # Geneva
    "LFPG": {"base_temp": 13, "base_wind_dir": 250},  # Paris CDG
    "EDDF": {"base_temp": 11, "base_wind_dir": 240},  # Frankfurt
    "EHAM": {"base_temp": 11, "base_wind_dir": 230},  # Amsterdam
    "OMDB": {"base_temp": 32, "base_wind_dir": 330},  # Dubai
    "RJAA": {"base_temp": 16, "base_wind_dir": 200},  # Narita
    "RJTT": {"base_temp": 17, "base_wind_dir": 190},  # Haneda
    "WSSS": {"base_temp": 28, "base_wind_dir": 0},    # Singapore
    "VHHH": {"base_temp": 25, "base_wind_dir": 90},   # Hong Kong
    "YSSY": {"base_temp": 20, "base_wind_dir": 230},  # Sydney
    "RKSI": {"base_temp": 13, "base_wind_dir": 270},  # Incheon
    "SBGR": {"base_temp": 22, "base_wind_dir": 150},  # Sao Paulo
    "FAOR": {"base_temp": 18, "base_wind_dir": 350},  # Johannesburg
    "LEMD": {"base_temp": 16, "base_wind_dir": 230},  # Madrid
    "LGAV": {"base_temp": 19, "base_wind_dir": 340},  # Athens
    "LIRF": {"base_temp": 17, "base_wind_dir": 250},  # Rome FCO
    "OMAA": {"base_temp": 30, "base_wind_dir": 320},  # Abu Dhabi
    "ZBAA": {"base_temp": 13, "base_wind_dir": 180},  # Beijing
    "VTBS": {"base_temp": 30, "base_wind_dir": 180},  # Bangkok
    "GMMN": {"base_temp": 20, "base_wind_dir": 340},  # Casablanca
    "MMMX": {"base_temp": 18, "base_wind_dir": 180},  # Mexico City
}


def generate_metar(
    station: str = "KSFO",
    obs_time: Optional[datetime] = None,
    base_temp: int = 15,
    base_wind_dir: int = 280,
) -> dict:
    """
    Generate synthetic METAR observation.

    Args:
        station: ICAO station identifier
        obs_time: Observation time (defaults to now)
        base_temp: Base temperature in Celsius
        base_wind_dir: Prevailing wind direction

    Returns:
        METAR dictionary
    """
    if obs_time is None:
        obs_time = datetime.now(timezone.utc)

    # Override defaults with per-station weather params if available
    station_params = STATION_WEATHER_PARAMS.get(station)
    if station_params:
        base_temp = station_params["base_temp"]
        base_wind_dir = station_params["base_wind_dir"]

    hour = obs_time.hour

    wind_direction, wind_speed, wind_gust = _get_wind_for_hour(hour, base_wind_dir)
    visibility = _get_visibility_for_hour(hour)
    clouds = _get_clouds_for_hour(hour, visibility)
    temp, dewpoint = _get_temperature_for_hour(hour, base_temp)
    phenomena = _get_weather_phenomena(visibility, hour)

    # Altimeter (standard is 29.92, vary slightly)
    altimeter = round(29.92 + random.uniform(-0.30, 0.30), 2)

    # Determine ceiling (lowest BKN or OVC layer)
    ceiling = None
    for cloud in clouds:
        if cloud["coverage"] in ["BKN", "OVC"]:
            ceiling = cloud["altitude_ft"]
            break

    flight_category = _determine_flight_category(visibility, ceiling)

    raw_metar = _format_raw_metar(
        station, obs_time, wind_direction, wind_speed, wind_gust,
        visibility, clouds, temp, dewpoint, altimeter, phenomena
    )

    return {
        "station": station,
        "observation_time": obs_time.isoformat(),
        "wind_direction": wind_direction,
        "wind_speed_kts": wind_speed,
        "wind_gust_kts": wind_gust,
        "visibility_sm": visibility,
        "clouds": clouds,
        "temperature_c": temp,
        "dewpoint_c": dewpoint,
        "altimeter_inhg": altimeter,
        "weather": phenomena,
        "flight_category": flight_category,
        "raw_metar": raw_metar,
    }


def generate_taf(
    station: str = "KSFO",
    issue_time: Optional[datetime] = None,
) -> dict:
    """
    Generate simplified TAF forecast.

    Args:
        station: ICAO station identifier
        issue_time: TAF issue time (defaults to now)

    Returns:
        TAF dictionary
    """
    if issue_time is None:
        issue_time = datetime.now(timezone.utc)

    valid_from = issue_time
    valid_to = issue_time + timedelta(hours=24)

    # Simple forecast text
    wind_dir = random.randint(250, 310)
    wind_speed = random.randint(8, 15)
    forecast_text = f"{wind_dir:03d}{wind_speed:02d}KT P6SM SCT040"

    return {
        "station": station,
        "issue_time": issue_time.isoformat(),
        "valid_from": valid_from.isoformat(),
        "valid_to": valid_to.isoformat(),
        "forecast_text": forecast_text,
    }


# Per-station weather cache with individual TTLs (prevents stampede at slot boundary)
_weather_cache: dict = {}  # station -> weather dict
_weather_cache_timestamps: dict = {}  # station -> datetime of last generation
_WEATHER_CACHE_TTL_S = 600  # 10 minutes


def get_cached_weather(station: str = "KSFO") -> dict:
    """Get cached weather (regenerates per-station after TTL expires).

    Each station has its own TTL, so slot boundaries only regenerate
    the specific station being requested — not all cached stations.
    """
    now = datetime.now(timezone.utc)
    last_generated = _weather_cache_timestamps.get(station)

    if (
        station not in _weather_cache
        or last_generated is None
        or (now - last_generated).total_seconds() >= _WEATHER_CACHE_TTL_S
    ):
        _weather_cache[station] = {
            "metar": generate_metar(station=station),
            "taf": generate_taf(station=station),
        }
        _weather_cache_timestamps[station] = now

    return _weather_cache[station]

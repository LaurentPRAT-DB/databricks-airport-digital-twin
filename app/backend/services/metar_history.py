"""Historical METAR weather data fetcher.

Fetches METAR observations from the Iowa State ASOS archive for a given
airport and date. Used to enrich recorded OpenSky data with weather context
that ADS-B alone cannot provide.

Source: https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py
  - Free, no authentication required
  - Covers all US airports (ASOS/AWOS stations)
"""

import logging
import re
from datetime import date, datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

IOWA_STATE_ASOS_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"

# Regex patterns for METAR parsing (minimal set for OBT features)
_WIND_RE = re.compile(r"(\d{3}|VRB)(\d{2,3})(G(\d{2,3}))?KT")
_VIS_SM_RE = re.compile(r"\b(\d+)\s*SM\b")
_VIS_FRAC_RE = re.compile(r"\b(\d+)\s+(\d)/(\d)\s*SM\b")
_VIS_FRAC_ONLY_RE = re.compile(r"\b(\d)/(\d)\s*SM\b")
_TEMP_RE = re.compile(r"\b(M?\d{2})/(M?\d{2})\b")
_ALT_RE = re.compile(r"A(\d{4})")
_CEILING_RE = re.compile(r"(BKN|OVC|VV)(\d{3})")


def _parse_metar_temp(s: str) -> float | None:
    """Parse METAR temperature string like '14' or 'M02' → float."""
    if not s:
        return None
    if s.startswith("M"):
        return -float(s[1:])
    return float(s)


def parse_metar(raw: str) -> dict[str, Any]:
    """Parse a raw METAR string into structured weather fields.

    Returns dict with: wind_speed_kts, wind_gust_kts, wind_direction,
    visibility_sm, temperature_c, dewpoint_c, ceiling_ft, flight_category.
    """
    result: dict[str, Any] = {
        "wind_speed_kts": 0,
        "wind_gust_kts": None,
        "wind_direction": 0,
        "visibility_sm": 10.0,
        "temperature_c": None,
        "dewpoint_c": None,
        "ceiling_ft": None,
        "flight_category": "VFR",
    }

    # Wind
    m = _WIND_RE.search(raw)
    if m:
        result["wind_direction"] = 0 if m.group(1) == "VRB" else int(m.group(1))
        result["wind_speed_kts"] = int(m.group(2))
        if m.group(4):
            result["wind_gust_kts"] = int(m.group(4))

    # Visibility — try "1 1/2SM" first, then "1/2SM", then "10SM"
    m = _VIS_FRAC_RE.search(raw)
    if m:
        result["visibility_sm"] = int(m.group(1)) + int(m.group(2)) / int(m.group(3))
    else:
        m = _VIS_FRAC_ONLY_RE.search(raw)
        if m:
            result["visibility_sm"] = int(m.group(1)) / int(m.group(2))
        else:
            m = _VIS_SM_RE.search(raw)
            if m:
                result["visibility_sm"] = float(m.group(1))

    # Temperature / dewpoint
    m = _TEMP_RE.search(raw)
    if m:
        result["temperature_c"] = _parse_metar_temp(m.group(1))
        result["dewpoint_c"] = _parse_metar_temp(m.group(2))

    # Ceiling (lowest BKN/OVC/VV layer)
    m = _CEILING_RE.search(raw)
    if m:
        result["ceiling_ft"] = int(m.group(2)) * 100

    # Flight category from visibility + ceiling
    vis = result["visibility_sm"]
    ceil = result["ceiling_ft"]
    if vis < 1 or (ceil is not None and ceil < 500):
        result["flight_category"] = "LIFR"
    elif vis < 3 or (ceil is not None and ceil < 1000):
        result["flight_category"] = "IFR"
    elif vis <= 5 or (ceil is not None and ceil < 3000):
        result["flight_category"] = "MVFR"
    else:
        result["flight_category"] = "VFR"

    return result


def _to_weather_snapshot(timestamp: str, raw_metar: str) -> dict[str, Any]:
    """Convert a METAR observation into a weather snapshot matching simulation format."""
    parsed = parse_metar(raw_metar)
    return {
        "time": timestamp,
        "wind_speed_kts": parsed["wind_speed_kts"],
        "wind_gust_kts": parsed["wind_gust_kts"],
        "wind_direction": parsed["wind_direction"],
        "visibility_sm": parsed["visibility_sm"],
        "flight_category": parsed["flight_category"],
        "temperature_c": parsed["temperature_c"],
        "dewpoint_c": parsed["dewpoint_c"],
        "raw_metar": raw_metar.strip(),
    }


async def fetch_historical_metar(
    station: str,
    target_date: date,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """Fetch historical METAR observations from Iowa State ASOS archive.

    Args:
        station: ICAO station code (e.g. 'KSFO'). The leading 'K' is stripped
                 for the Iowa State API which expects 3-letter identifiers for US stations.
        target_date: Date to fetch observations for.
        timeout: HTTP request timeout in seconds.

    Returns:
        List of weather snapshot dicts matching simulation format, sorted by time.
    """
    # Iowa State uses 3-letter station IDs for US airports
    api_station = station.upper()
    if len(api_station) == 4 and api_station.startswith("K"):
        api_station = api_station[1:]

    params = {
        "station": api_station,
        "data": "metar",
        "year1": str(target_date.year),
        "month1": str(target_date.month),
        "day1": str(target_date.day),
        "year2": str(target_date.year),
        "month2": str(target_date.month),
        "day2": str(target_date.day),
        "tz": "Etc/UTC",
        "format": "onlycomma",
        "latlon": "no",
        "missing": "M",
        "trace": "T",
        "direct": "no",
        "report_type": "3",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(IOWA_STATE_ASOS_URL, params=params)
            resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("Failed to fetch METAR for %s on %s: %s", station, target_date, e)
        return []

    text = resp.text.strip()
    if not text:
        return []

    snapshots: list[dict[str, Any]] = []
    lines = text.split("\n")

    # First line is header: "station,valid,metar"
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split(",", 2)
        if len(parts) < 3:
            continue
        _station, valid_str, raw_metar = parts
        if not raw_metar or raw_metar == "M":
            continue

        # Normalize timestamp to ISO format
        try:
            dt = datetime.strptime(valid_str.strip(), "%Y-%m-%d %H:%M")
            iso_time = dt.replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue

        snapshots.append(_to_weather_snapshot(iso_time, raw_metar))

    logger.info("Fetched %d METAR observations for %s on %s", len(snapshots), station, target_date)
    return snapshots

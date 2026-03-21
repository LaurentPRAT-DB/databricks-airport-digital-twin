"""Lightweight UTC offset estimation from coordinates.

Uses longitude-based approximation (1 hour per 15 degrees) refined by
a lookup table for countries with non-standard timezone offsets.
Avoids adding timezonefinder (~50MB) as a dependency.

Accuracy: within +/- 1 hour for most airports. The country override
table handles the major exceptions (China, India, etc.).
"""

from __future__ import annotations


# Countries whose standard timezone diverges significantly from their
# longitude-based estimate. Maps ISO country code → UTC offset in hours.
TIMEZONE_OVERRIDES: dict[str, float] = {
    # China uses a single timezone (UTC+8) despite spanning ~60 degrees
    "CN": 8.0,
    "HK": 8.0,
    "MO": 8.0,
    "TW": 8.0,
    # India uses UTC+5:30
    "IN": 5.5,
    # Nepal uses UTC+5:45
    "NP": 5.75,
    # Iran uses UTC+3:30
    "IR": 3.5,
    # Afghanistan uses UTC+4:30
    "AF": 4.5,
    # Myanmar uses UTC+6:30
    "MM": 6.5,
    # Spain uses CET (UTC+1) despite being at ~4W longitude
    "ES": 1.0,
    # France uses CET (UTC+1)
    "FR": 1.0,
    # Argentina uses UTC-3 despite spanning wide longitude range
    "AR": -3.0,
    # Iceland uses UTC+0 year-round despite being ~20W
    "IS": 0.0,
    # Western Australia is UTC+8 but longitude suggests ~7
    # (handled by longitude for Perth, but WA is wide)
    # Singapore is UTC+8
    "SG": 8.0,
    # Malaysia is UTC+8
    "MY": 8.0,
}


def estimate_utc_offset(lat: float, lon: float, country: str = "") -> float:
    """Estimate UTC offset in hours from coordinates and optional country.

    Args:
        lat: Latitude (not used directly, reserved for DST heuristics)
        lon: Longitude in degrees (-180 to 180)
        country: ISO 3166-1 alpha-2 country code (e.g., "CN", "IN")

    Returns:
        Estimated UTC offset in hours (e.g., 8.0 for UTC+8, -5.0 for UTC-5)
    """
    if country and country.upper() in TIMEZONE_OVERRIDES:
        return TIMEZONE_OVERRIDES[country.upper()]

    # Longitude-based: 15 degrees per hour, rounded to nearest 0.5
    raw = lon / 15.0
    return round(raw * 2) / 2


def utc_to_local_hourly(hourly_utc: list[float], utc_offset: float) -> list[float]:
    """Rotate a 24-element hourly profile from UTC to local time.

    Args:
        hourly_utc: 24-element list of weights in UTC hours (index 0 = 00:00 UTC)
        utc_offset: Offset in hours (e.g., 8.0 means local = UTC + 8)

    Returns:
        24-element list rotated so index 0 = 00:00 local time
    """
    if len(hourly_utc) != 24:
        return hourly_utc

    # Round offset to nearest integer for shifting (half-hours get nearest)
    shift = int(round(utc_offset))
    # Rotate: local hour 0 corresponds to UTC hour (-shift) mod 24
    # So we shift the array right by `shift` positions
    result = [0.0] * 24
    for utc_hour in range(24):
        local_hour = (utc_hour + shift) % 24
        result[local_hour] = hourly_utc[utc_hour]
    return result

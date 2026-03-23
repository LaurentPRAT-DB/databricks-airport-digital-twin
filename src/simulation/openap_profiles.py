"""Cached OpenAP flight performance profiles for realistic trajectories.

Pre-generates descent and climb profiles per aircraft type using OpenAP's
physics-based FlightGenerator. Profiles are normalized to 0.0–1.0 progress
for easy interpolation during simulation ticks.

Units returned:
- altitude: feet
- speed: knots (TAS)
- vertical_rate: feet/min
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Conversion factors
_M_TO_FT = 3.28084
_MS_TO_KTS = 1.94384
_MS_TO_FPM = 196.85

# Map our ICAO type codes to OpenAP's lowercase identifiers.
# OpenAP uses a subset; we map everything we can and fall back to A320.
_TYPE_MAP: Dict[str, str] = {
    "A318": "a318", "A319": "a319", "A320": "a320", "A321": "a321",
    "A20N": "a20n", "A21N": "a21n", "A19N": "a19n",
    "A330": "a332", "A332": "a332", "A333": "a333",
    "A340": "a343", "A345": "a343",
    "A350": "a359", "A359": "a359",
    "A380": "a388", "A388": "a388",
    "B737": "b737", "B738": "b738", "B739": "b739",
    "B37M": "b37m", "B38M": "b38m", "B39M": "b39m",
    "B744": "b744", "B748": "b748",
    "B752": "b752", "B753": "b752",
    "B763": "b763", "B767": "b763",
    "B772": "b772", "B773": "b773", "B77W": "b77w",
    "B777": "b772", "B787": "b788", "B788": "b788", "B789": "b789",
    "CRJ9": "crj9", "CRJ7": "crj9",
    "E170": "e170", "E175": "e75l", "E190": "e190", "E195": "e195",
    "E75L": "e75l",
}

_FALLBACK_OPENAP_TYPE = "a320"


@dataclass
class FlightProfile:
    """Altitude/speed/vrate as arrays indexed by normalized progress [0, 1]."""
    progress: np.ndarray          # 0.0 → 1.0
    altitude_ft: np.ndarray       # feet
    speed_kts: np.ndarray         # knots TAS
    vertical_rate_fpm: np.ndarray  # ft/min (negative = descent)


# Module-level cache: aircraft_type → profile
_descent_cache: Dict[str, FlightProfile] = {}
_climb_cache: Dict[str, FlightProfile] = {}


def _openap_type(aircraft_type: str) -> str:
    """Resolve our type code to an OpenAP identifier."""
    return _TYPE_MAP.get(aircraft_type, _FALLBACK_OPENAP_TYPE)


def _build_descent_profile(openap_type: str) -> FlightProfile:
    """Generate a descent profile using OpenAP FlightGenerator."""
    from openap import FlightGenerator

    fg = FlightGenerator(ac=openap_type)
    df = fg.descent(dt=10, random=False)

    # Filter to airborne portion only (h > 0 and before ground roll)
    airborne = df[df["h"] > 0].copy()
    if airborne.empty:
        airborne = df.copy()

    n = len(airborne)
    progress = np.linspace(0.0, 1.0, n)
    alt_ft = airborne["h"].values * _M_TO_FT
    speed_kts = airborne["v"].values * _MS_TO_KTS
    vrate_fpm = airborne["vs"].values * _MS_TO_FPM

    return FlightProfile(
        progress=progress,
        altitude_ft=alt_ft,
        speed_kts=speed_kts,
        vertical_rate_fpm=vrate_fpm,
    )


def _build_climb_profile(openap_type: str) -> FlightProfile:
    """Generate a climb profile using OpenAP FlightGenerator."""
    from openap import FlightGenerator

    fg = FlightGenerator(ac=openap_type)
    df = fg.climb(dt=10, random=False)

    # Filter to airborne portion (after takeoff roll)
    airborne = df[df["h"] > 0].copy()
    if airborne.empty:
        airborne = df.copy()

    n = len(airborne)
    progress = np.linspace(0.0, 1.0, n)
    alt_ft = airborne["h"].values * _M_TO_FT
    speed_kts = airborne["v"].values * _MS_TO_KTS
    vrate_fpm = airborne["vs"].values * _MS_TO_FPM

    return FlightProfile(
        progress=progress,
        altitude_ft=alt_ft,
        speed_kts=speed_kts,
        vertical_rate_fpm=vrate_fpm,
    )


def get_descent_profile(aircraft_type: str) -> FlightProfile:
    """Return cached OpenAP descent profile for *aircraft_type*.

    Progress 0.0 = top of descent (cruise altitude), 1.0 = touchdown.
    Altitude decreases, speed decreases, vrate is negative.
    """
    if aircraft_type not in _descent_cache:
        oa_type = _openap_type(aircraft_type)
        try:
            _descent_cache[aircraft_type] = _build_descent_profile(oa_type)
        except Exception:
            logger.warning(
                "OpenAP descent failed for %s (%s), falling back to A320",
                aircraft_type, oa_type,
            )
            if _FALLBACK_OPENAP_TYPE not in _descent_cache:
                _descent_cache[_FALLBACK_OPENAP_TYPE] = _build_descent_profile(_FALLBACK_OPENAP_TYPE)
            _descent_cache[aircraft_type] = _descent_cache[_FALLBACK_OPENAP_TYPE]
    return _descent_cache[aircraft_type]


def get_climb_profile(aircraft_type: str) -> FlightProfile:
    """Return cached OpenAP climb profile for *aircraft_type*.

    Progress 0.0 = liftoff, 1.0 = top of climb (cruise altitude).
    Altitude increases, speed increases, vrate is positive.
    """
    if aircraft_type not in _climb_cache:
        oa_type = _openap_type(aircraft_type)
        try:
            _climb_cache[aircraft_type] = _build_climb_profile(oa_type)
        except Exception:
            logger.warning(
                "OpenAP climb failed for %s (%s), falling back to A320",
                aircraft_type, oa_type,
            )
            if _FALLBACK_OPENAP_TYPE not in _climb_cache:
                _climb_cache[_FALLBACK_OPENAP_TYPE] = _build_climb_profile(_FALLBACK_OPENAP_TYPE)
            _climb_cache[aircraft_type] = _climb_cache[_FALLBACK_OPENAP_TYPE]
    return _climb_cache[aircraft_type]


def interpolate_profile(profile: FlightProfile, progress: float) -> Tuple[float, float, float]:
    """Interpolate altitude, speed, and vrate at a given progress [0, 1].

    Returns (altitude_ft, speed_kts, vertical_rate_fpm).
    """
    progress = max(0.0, min(1.0, progress))
    alt = float(np.interp(progress, profile.progress, profile.altitude_ft))
    spd = float(np.interp(progress, profile.progress, profile.speed_kts))
    vr = float(np.interp(progress, profile.progress, profile.vertical_rate_fpm))
    return alt, spd, vr

"""Profile builder — orchestrates data ingestion into AirportProfile artifacts.

Combines BTS, OpenSky, and OurAirports data sources to build per-airport
calibration profiles. Falls back gracefully when data sources are unavailable.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.calibration.profile import AirportProfile, _iata_to_icao, _build_fallback_profile

logger = logging.getLogger(__name__)

# Default raw data directory
_RAW_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "calibration" / "raw"
_PROFILES_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "calibration" / "profiles"

# Well-known US airports (covered by BTS)
US_AIRPORTS = [
    "SFO", "LAX", "ORD", "DFW", "JFK", "ATL", "DEN", "SEA", "BOS",
    "PHX", "LAS", "MCO", "MIA", "CLT", "MSP", "DTW", "EWR", "PHL",
    "IAH", "SAN", "PDX",
]

# International airports (need OpenSky or static profiles)
INTERNATIONAL_AIRPORTS = [
    "LHR", "CDG", "FRA", "AMS", "HKG", "NRT", "SIN", "SYD", "DXB",
    "ICN", "GRU", "JNB",
]


def build_profiles(
    airports: Optional[list[str]] = None,
    raw_data_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    use_opensky: bool = False,
    opensky_auth: Optional[tuple[str, str]] = None,
) -> list[AirportProfile]:
    """Build calibration profiles for a list of airports.

    For US airports: uses BTS T-100 and On-Time Performance CSVs.
    For international airports: uses OpenSky API (if enabled) or fallback.

    Args:
        airports: List of IATA codes. Defaults to all known airports.
        raw_data_dir: Directory containing raw CSV files
        output_dir: Directory to write profile JSONs
        use_opensky: Whether to query OpenSky for international airports
        opensky_auth: Optional (username, password) for OpenSky

    Returns:
        List of built AirportProfile objects
    """
    if airports is None:
        airports = US_AIRPORTS + INTERNATIONAL_AIRPORTS
    raw_dir = raw_data_dir or _RAW_DATA_DIR
    out_dir = output_dir or _PROFILES_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    profiles: list[AirportProfile] = []

    for iata in airports:
        logger.info("Building profile for %s...", iata)
        profile = _build_single_profile(
            iata, raw_dir, use_opensky=use_opensky, opensky_auth=opensky_auth,
        )
        profile.profile_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        profile.save(out_dir / f"{profile.icao_code}.json")
        profiles.append(profile)
        logger.info(
            "  → %s: source=%s, airlines=%d, routes=%d+%d, sample=%d",
            profile.icao_code,
            profile.data_source,
            len(profile.airline_shares),
            len(profile.domestic_route_shares),
            len(profile.international_route_shares),
            profile.sample_size,
        )

    logger.info("Built %d profiles in %s", len(profiles), out_dir)
    return profiles


def _build_single_profile(
    iata: str,
    raw_dir: Path,
    use_opensky: bool = False,
    opensky_auth: Optional[tuple[str, str]] = None,
) -> AirportProfile:
    """Build profile for a single airport, trying data sources in priority order."""

    # Try BTS data (US airports)
    t100_dom = raw_dir / "T_T100_SEGMENT_ALL_CARRIER.csv"
    t100_intl = raw_dir / "T_T100_INTERNATIONAL_SEGMENT.csv"
    ontime = raw_dir / "On_Time_Reporting_Carrier_On_Time_Performance.csv"

    has_bts = t100_dom.exists() or ontime.exists()

    if has_bts and iata in US_AIRPORTS:
        from src.calibration.bts_ingest import build_profile_from_bts
        return build_profile_from_bts(
            iata,
            t100_domestic_path=t100_dom if t100_dom.exists() else None,
            t100_international_path=t100_intl if t100_intl.exists() else None,
            ontime_path=ontime if ontime.exists() else None,
        )

    # Try OpenSky (international airports)
    if use_opensky:
        try:
            from src.calibration.opensky_ingest import build_profile_from_opensky
            return build_profile_from_opensky(
                iata, days=7, auth=opensky_auth,
            )
        except Exception as e:
            logger.warning("OpenSky failed for %s: %s, falling back", iata, e)

    # Fallback to hardcoded distributions
    return _build_fallback_profile(iata)

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
_DB28_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "calibration" / "download_manual"
_OTP_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "calibration" / "raw" / "otp"

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
    opensky_client_id: Optional[str] = None,
    opensky_client_secret: Optional[str] = None,
    use_openflights: bool = True,
) -> list[AirportProfile]:
    """Build calibration profiles for a list of airports.

    For US airports: uses BTS T-100 and On-Time Performance CSVs.
    For international airports: uses OpenSky API (if enabled) or fallback.

    Args:
        airports: List of IATA codes. Defaults to all known airports.
        raw_data_dir: Directory containing raw CSV files
        output_dir: Directory to write profile JSONs
        use_opensky: Whether to query OpenSky for international airports
        opensky_client_id: OpenSky OAuth2 client ID
        opensky_client_secret: OpenSky OAuth2 client secret
        use_openflights: Whether to use OpenFlights routes.dat (default True)

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
            iata, raw_dir, use_opensky=use_opensky,
            opensky_client_id=opensky_client_id, opensky_client_secret=opensky_client_secret,
            use_openflights=use_openflights,
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
    opensky_client_id: Optional[str] = None,
    opensky_client_secret: Optional[str] = None,
    use_openflights: bool = True,
) -> AirportProfile:
    """Build profile for a single airport, trying data sources in priority order."""

    # 1. Try DB28 pipe-delimited zips (real BTS T-100 data, highest priority for US)
    if iata in US_AIRPORTS and _DB28_DIR.exists():
        db28_zips = list(_DB28_DIR.glob("DB28SEG*.zip"))
        if db28_zips:
            from src.calibration.bts_ingest import build_profile_from_db28
            profile = build_profile_from_db28(iata, _DB28_DIR)
            if profile is not None:
                # DB28 lacks hourly/delay data — enrich from OTP PREZIP or known_stats
                _enrich_with_otp(profile, iata)
                return profile

    # 2. Try BTS CSV data (field-selector format)
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

    # 3. Try OpenFlights routes.dat (worldwide route data)
    if use_openflights:
        try:
            from src.calibration.openflights_ingest import build_profile_from_openflights
            profile = build_profile_from_openflights(iata, raw_dir=raw_dir, download=True)
            if profile is not None and (
                profile.domestic_route_shares or profile.international_route_shares
            ):
                # OpenFlights lacks hourly/delay — enrich from known_stats
                _enrich_openflights_with_known_stats(profile, iata)
                return profile
        except Exception as e:
            logger.warning("OpenFlights failed for %s: %s, falling back", iata, e)

    # 4. Try OpenSky (international airports)
    if use_opensky:
        try:
            from src.calibration.opensky_ingest import build_profile_from_opensky
            return build_profile_from_opensky(
                iata, days=7,
                client_id=opensky_client_id, client_secret=opensky_client_secret,
            )
        except Exception as e:
            logger.warning("OpenSky failed for %s: %s, falling back", iata, e)

    # 5. Try known hand-researched profiles
    from src.calibration.known_profiles import get_known_profile
    known = get_known_profile(iata)
    if known is not None:
        return known

    # 6. Fallback to hardcoded distributions
    return _build_fallback_profile(iata)


def _enrich_with_otp(profile: AirportProfile, iata: str) -> None:
    """Fill in hourly/delay fields that DB28 doesn't provide.

    Priority: real OTP PREZIP data > known_stats approximations.
    """
    otp_used = False

    # Try real OTP PREZIP data first
    if _OTP_DIR.exists():
        otp_zips = list(_OTP_DIR.glob("otp_*.zip"))
        if otp_zips:
            from src.calibration.bts_ingest import parse_otp_prezip
            otp = parse_otp_prezip(_OTP_DIR, iata)
            if otp["total_flights"] > 0:
                otp_used = True

                # Hourly profile from real data
                from collections import Counter
                combined: Counter = Counter(otp["hourly_departures"])
                combined.update(otp["hourly_arrivals"])
                if combined:
                    total_hourly = sum(combined.values()) or 1
                    profile.hourly_profile = [
                        combined.get(h, 0) / total_hourly for h in range(24)
                    ]

                # Real delay stats
                profile.delay_rate = otp["delay_rate"]
                profile.mean_delay_minutes = otp["mean_delay_minutes"]

                # Map BTS delay causes to IATA delay codes
                cause_total = sum(otp["delay_causes"].values()) or 1
                cause_map = {
                    "carrier": {"62": 0.4, "67": 0.3, "63": 0.3},
                    "weather": {"71": 0.6, "72": 0.4},
                    "nas": {"81": 1.0},
                    "security": {"41": 1.0},
                    "late_aircraft": {"68": 1.0},
                }
                delay_dist: dict[str, float] = {}
                for cause, count in otp["delay_causes"].items():
                    weight = count / cause_total
                    for code, frac in cause_map.get(cause, {}).items():
                        delay_dist[code] = delay_dist.get(code, 0) + weight * frac
                profile.delay_distribution = delay_dist

                # Taxi time stats
                taxi_out = otp.get("taxi_out_stats", {})
                if taxi_out and taxi_out.get("n", 0) > 100:
                    profile.taxi_out_mean_min = taxi_out["mean"]
                    profile.taxi_out_p95_min = taxi_out["p95"]

                taxi_in = otp.get("taxi_in_stats", {})
                if taxi_in and taxi_in.get("n", 0) > 100:
                    profile.taxi_in_mean_min = taxi_in["mean"]
                    profile.taxi_in_p95_min = taxi_in["p95"]

                # Turnaround proxy stats (tail-number matching)
                ta = otp.get("turnaround_stats", {})
                if ta and ta.get("n", 0) > 50:
                    profile.turnaround_median_min = ta["median"]
                    profile.turnaround_p75_min = ta["p75"]
                    profile.turnaround_p95_min = ta["p95"]

                profile.data_source = "BTS_DB28+OTP"
                logger.info(
                    "  Enriched %s with real OTP: %.1f%% delayed, %.1f min avg, %d flights"
                    " | taxi_out=%.1fmin, taxi_in=%.1fmin, turnaround_med=%.1fmin",
                    iata, otp["delay_rate"] * 100, otp["mean_delay_minutes"],
                    otp["total_flights"],
                    profile.taxi_out_mean_min, profile.taxi_in_mean_min,
                    profile.turnaround_median_min,
                )

    # Fall back to known_stats if OTP not available
    if not otp_used:
        _enrich_with_known_stats(profile, iata)


def _enrich_with_known_stats(profile: AirportProfile, iata: str) -> None:
    """Fill in fields that DB28 doesn't provide using known_stats data."""
    from src.calibration.known_profiles import get_known_profile
    known = get_known_profile(iata)
    if known is None:
        return

    if not profile.hourly_profile and known.hourly_profile:
        profile.hourly_profile = known.hourly_profile

    if profile.delay_rate == 0.0 and known.delay_rate > 0:
        profile.delay_rate = known.delay_rate
    if not profile.delay_distribution and known.delay_distribution:
        profile.delay_distribution = known.delay_distribution
    if profile.mean_delay_minutes == 0.0 and known.mean_delay_minutes > 0:
        profile.mean_delay_minutes = known.mean_delay_minutes

    if "BTS_DB28" in profile.data_source:
        profile.data_source = "BTS_DB28+known_stats"


def _enrich_openflights_with_known_stats(profile: AirportProfile, iata: str) -> None:
    """Fill in hourly/delay fields that OpenFlights doesn't provide."""
    from src.calibration.known_profiles import get_known_profile
    known = get_known_profile(iata)
    if known is None:
        return

    if not profile.hourly_profile and known.hourly_profile:
        profile.hourly_profile = known.hourly_profile

    if profile.delay_rate == 0.0 and known.delay_rate > 0:
        profile.delay_rate = known.delay_rate
    if not profile.delay_distribution and known.delay_distribution:
        profile.delay_distribution = known.delay_distribution
    if profile.mean_delay_minutes == 0.0 and known.mean_delay_minutes > 0:
        profile.mean_delay_minutes = known.mean_delay_minutes

    profile.data_source = "openflights+known_stats"

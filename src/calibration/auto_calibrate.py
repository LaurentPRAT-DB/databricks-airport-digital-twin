"""Automatic calibration for airports without hand-researched profiles.

Combines OpenSky flight data, OurAirports metadata, regional templates,
and airline fleet inference to build a realistic AirportProfile for any
airport in the world. Falls back gracefully at each step — even without
network access, produces a region-appropriate profile instead of the
US-centric fallback.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.calibration.profile import AirportProfile, _iata_to_icao, _icao_to_iata

logger = logging.getLogger(__name__)

_RAW_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "calibration" / "raw"
_PROFILES_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "calibration" / "profiles"

# Cache for OurAirports data (loaded once)
_airports_cache: dict[str, dict] | None = None


def _load_airports_csv() -> dict[str, dict]:
    """Load and cache OurAirports airports.csv."""
    global _airports_cache
    if _airports_cache is not None:
        return _airports_cache

    csv_path = _RAW_DIR / "airports.csv"
    if not csv_path.exists():
        logger.warning("airports.csv not found at %s", csv_path)
        _airports_cache = {}
        return _airports_cache

    from src.calibration.ourairports_ingest import parse_airports_csv
    _airports_cache = parse_airports_csv(csv_path)
    return _airports_cache


def _get_airport_country(icao: str) -> str:
    """Get ISO country code for an airport from OurAirports data."""
    airports = _load_airports_csv()
    meta = airports.get(icao, {})
    return meta.get("country", "")


def _get_airport_coords(icao: str) -> tuple[float, float]:
    """Get (lat, lon) for an airport from OurAirports data."""
    airports = _load_airports_csv()
    meta = airports.get(icao, {})
    return meta.get("latitude", 0.0), meta.get("longitude", 0.0)


def _get_airport_iata(icao: str) -> str:
    """Get IATA code for an airport from OurAirports data."""
    # Try the built-in mapping first
    iata = _icao_to_iata(icao)
    if iata != icao:
        return iata
    # Fall back to OurAirports
    airports = _load_airports_csv()
    meta = airports.get(icao, {})
    return meta.get("iata", icao)


def _classify_routes(
    route_counts: Counter,
    home_country: str,
) -> tuple[dict[str, float], dict[str, float], float]:
    """Classify routes as domestic or international using OurAirports country data.

    Returns:
        (domestic_route_shares, international_route_shares, domestic_ratio)
    """
    airports = _load_airports_csv()
    domestic: Counter = Counter()
    international: Counter = Counter()

    for dest_icao, count in route_counts.items():
        dest_meta = airports.get(dest_icao, {})
        dest_country = dest_meta.get("country", "")
        if dest_country and dest_country == home_country:
            domestic[dest_icao] += count
        else:
            international[dest_icao] += count

    total_dom = sum(domestic.values()) or 0
    total_intl = sum(international.values()) or 0
    total = total_dom + total_intl

    if total == 0:
        return {}, {}, 0.5

    domestic_ratio = total_dom / total

    # Normalize to shares (top 20 each)
    dom_shares = {k: v / total_dom for k, v in domestic.most_common(20)} if total_dom else {}
    intl_shares = {k: v / total_intl for k, v in international.most_common(20)} if total_intl else {}

    return dom_shares, intl_shares, domestic_ratio


def _build_fleet_mix(airline_shares: dict[str, float], region: str) -> dict[str, dict[str, float]]:
    """Build fleet mix for each airline using the airline_fleets lookup."""
    from src.calibration.airline_fleets import get_fleet_mix

    fleet_mix: dict[str, dict[str, float]] = {}
    for carrier in airline_shares:
        fleet_mix[carrier] = get_fleet_mix(carrier, region)
    return fleet_mix


def _build_regional_airlines(region: str) -> dict[str, float]:
    """Build airline shares from regional defaults when OpenSky data is unavailable."""
    from src.calibration.airline_fleets import AIRLINE_FLEET

    # Map regions to their typical major airlines
    regional_airlines: dict[str, dict[str, float]] = {
        "europe_west": {"DLH": 0.15, "AFR": 0.12, "KLM": 0.10, "BAW": 0.10, "RYR": 0.12, "EZY": 0.10, "SWR": 0.06, "SAS": 0.05, "AUA": 0.04, "TAP": 0.04, "VLG": 0.04, "WZZ": 0.04, "SWA": 0.04},
        "europe_south": {"AZA": 0.15, "IBE": 0.12, "VLG": 0.12, "RYR": 0.15, "EZY": 0.10, "AEE": 0.08, "WZZ": 0.06, "TAP": 0.06, "AEA": 0.05, "THY": 0.04, "AFR": 0.04, "DLH": 0.03},
        "middle_east": {"UAE": 0.25, "QTR": 0.15, "ETD": 0.12, "THY": 0.12, "FDB": 0.08, "SIA": 0.04, "BAW": 0.04, "DLH": 0.04, "AFR": 0.04, "AIC": 0.04, "KAL": 0.04, "CPA": 0.04},
        "east_asia": {"ANA": 0.15, "JAL": 0.12, "CCA": 0.12, "CES": 0.10, "CSN": 0.10, "KAL": 0.10, "AAR": 0.06, "EVA": 0.05, "CPA": 0.05, "SIA": 0.04, "THA": 0.04, "UAE": 0.03, "DLH": 0.02, "BAW": 0.02},
        "southeast_asia": {"SIA": 0.15, "THA": 0.10, "MAS": 0.08, "AIC": 0.08, "IGO": 0.06, "CPA": 0.06, "CES": 0.05, "KAL": 0.05, "ANA": 0.04, "JAL": 0.04, "QFA": 0.04, "UAE": 0.04, "EVA": 0.04, "BAW": 0.03, "DLH": 0.03, "AFR": 0.03, "ETH": 0.04, "QTR": 0.04},
        "south_america": {"TAM": 0.25, "GLO": 0.20, "AMX": 0.10, "VOI": 0.08, "AAL": 0.05, "UAL": 0.05, "DAL": 0.04, "AFR": 0.03, "BAW": 0.03, "DLH": 0.03, "IBE": 0.03, "UAE": 0.03, "CPA": 0.02, "KLM": 0.03, "TAP": 0.03},
        "central_america": {"AMX": 0.20, "VOI": 0.15, "UAL": 0.10, "AAL": 0.10, "DAL": 0.08, "SWA": 0.08, "JBU": 0.06, "IBE": 0.04, "AFR": 0.03, "BAW": 0.03, "DLH": 0.03, "CPA": 0.02, "ANA": 0.02, "KLM": 0.03, "TAP": 0.03},
        "africa": {"SAA": 0.15, "RAM": 0.12, "ETH": 0.12, "UAE": 0.08, "AFR": 0.06, "BAW": 0.06, "DLH": 0.05, "THY": 0.05, "QTR": 0.04, "KLM": 0.04, "TAP": 0.04, "IBE": 0.03, "RYR": 0.03, "SIA": 0.03, "AIC": 0.03, "CPA": 0.03, "KAL": 0.02, "EZY": 0.02},
        "oceania": {"QFA": 0.30, "VOZ": 0.15, "SIA": 0.06, "UAE": 0.06, "CPA": 0.05, "ANA": 0.04, "JAL": 0.03, "UAL": 0.03, "DAL": 0.03, "AAL": 0.03, "BAW": 0.03, "DLH": 0.03, "AFR": 0.02, "KAL": 0.03, "EVA": 0.03, "THA": 0.03, "MAS": 0.03, "CES": 0.02},
        "north_america": {"UAL": 0.20, "DAL": 0.15, "AAL": 0.15, "SWA": 0.12, "ASA": 0.08, "JBU": 0.06, "FFT": 0.05, "SPI": 0.05, "BAW": 0.03, "ANA": 0.02, "DLH": 0.02, "AFR": 0.02, "UAE": 0.02, "CPA": 0.02, "KAL": 0.01},
    }

    return regional_airlines.get(region, regional_airlines["europe_west"])


def auto_calibrate_airport(
    icao_code: str,
    use_opensky: bool = True,
) -> AirportProfile | None:
    """Auto-calibrate an airport by combining multiple data sources.

    Steps:
    1. Load OurAirports metadata (country, coordinates)
    2. Determine region from country code
    3. Optionally query OpenSky for airline shares, routes, hourly profile
    4. Convert hourly profile from UTC to local time
    5. Classify routes as domestic/international
    6. Infer fleet mix from airline identities
    7. Fill delay stats from regional template
    8. Save and return profile

    Falls back gracefully: if OpenSky fails, returns a region-based profile
    with regional airline shares — still much better than the US fallback.

    Args:
        icao_code: ICAO airport code (e.g., "EDDF", "VABB")
        use_opensky: Whether to query OpenSky API (set False for offline/testing)

    Returns:
        AirportProfile or None if airport not found in OurAirports
    """
    from src.calibration.regional_templates import get_region, get_regional_template
    from src.calibration.timezone_util import estimate_utc_offset, utc_to_local_hourly

    # Step 1: Get airport metadata
    country = _get_airport_country(icao_code)
    lat, lon = _get_airport_coords(icao_code)
    iata = _get_airport_iata(icao_code)

    if not country and lat == 0.0 and lon == 0.0:
        logger.warning("Airport %s not found in OurAirports data", icao_code)
        return None

    # Step 2: Determine region
    region = get_region(country)
    template = get_regional_template(country)

    logger.info(
        "Auto-calibrating %s (%s): country=%s, region=%s",
        icao_code, iata, country, region,
    )

    # Step 3: Try OpenSky
    airline_shares: dict[str, float] = {}
    route_counts: Counter = Counter()
    hourly_utc: list[float] = []
    total_flights = 0
    opensky_success = False

    if use_opensky:
        try:
            from src.calibration.opensky_ingest import (
                query_departures,
                query_arrivals,
                _extract_carrier,
            )
            from collections import Counter as _Counter

            airline_counts: Counter = Counter()
            hourly_combined: Counter = Counter()
            now = int(datetime.now(timezone.utc).timestamp())

            # Query 7 days of data (2 API calls per day = 14 calls)
            import time
            for day_offset in range(7):
                end_ts = now - day_offset * 86400
                begin_ts = end_ts - 86400

                deps = query_departures(icao_code, begin_ts, end_ts)
                for flight in deps:
                    total_flights += 1
                    callsign = (flight.get("callsign") or "").strip()
                    carrier = _extract_carrier(callsign)
                    if carrier:
                        airline_counts[carrier] += 1
                    first_seen = flight.get("firstSeen")
                    if first_seen:
                        hour = datetime.fromtimestamp(first_seen, tz=timezone.utc).hour
                        hourly_combined[hour] += 1
                    est_dest = flight.get("estArrivalAirport", "")
                    if est_dest:
                        route_counts[est_dest] += 1

                time.sleep(2.0)

                arrs = query_arrivals(icao_code, begin_ts, end_ts)
                for flight in arrs:
                    total_flights += 1
                    callsign = (flight.get("callsign") or "").strip()
                    carrier = _extract_carrier(callsign)
                    if carrier:
                        airline_counts[carrier] += 1
                    last_seen = flight.get("lastSeen")
                    if last_seen:
                        hour = datetime.fromtimestamp(last_seen, tz=timezone.utc).hour
                        hourly_combined[hour] += 1
                    est_origin = flight.get("estDepartureAirport", "")
                    if est_origin:
                        route_counts[est_origin] += 1

                time.sleep(2.0)

            # Build normalized distributions
            total_airlines = sum(airline_counts.values()) or 1
            airline_shares = {
                k: v / total_airlines
                for k, v in airline_counts.most_common(20)
            }

            total_hourly = sum(hourly_combined.values()) or 1
            hourly_utc = [hourly_combined.get(h, 0) / total_hourly for h in range(24)]

            opensky_success = total_flights > 0
            logger.info(
                "OpenSky data for %s: %d flights, %d carriers",
                icao_code, total_flights, len(airline_shares),
            )

        except Exception as e:
            logger.warning("OpenSky query failed for %s: %s", icao_code, e)

    # Step 4: Convert hourly UTC → local
    utc_offset = estimate_utc_offset(lat, lon, country)
    if hourly_utc:
        hourly_local = utc_to_local_hourly(hourly_utc, utc_offset)
    else:
        hourly_local = list(template["hourly_profile"])

    # Step 5: Classify routes
    if route_counts:
        dom_shares, intl_shares, domestic_ratio = _classify_routes(route_counts, country)
    else:
        dom_shares = {}
        intl_shares = {}
        domestic_ratio = template["domestic_ratio"]

    # Step 6: If no OpenSky data, use regional airlines
    if not airline_shares:
        airline_shares = _build_regional_airlines(region)

    # Step 7: Build fleet mix
    fleet_mix = _build_fleet_mix(airline_shares, region)

    # Step 8: Build profile
    data_source = f"auto_calibrate+OpenSky" if opensky_success else f"auto_calibrate+{region}"
    profile = AirportProfile(
        icao_code=icao_code,
        iata_code=iata,
        airline_shares=airline_shares,
        domestic_route_shares=dom_shares,
        international_route_shares=intl_shares,
        domestic_ratio=domestic_ratio,
        fleet_mix=fleet_mix,
        hourly_profile=hourly_local,
        delay_rate=template["delay_rate"],
        delay_distribution=dict(template["delay_distribution"]),
        mean_delay_minutes=template["mean_delay_minutes"],
        data_source=data_source,
        region=region,
        profile_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        sample_size=total_flights,
    )

    # Save profile
    try:
        saved_path = profile.save()
        logger.info("Saved auto-calibrated profile for %s to %s", icao_code, saved_path)
    except Exception as e:
        logger.warning("Failed to save profile for %s: %s", icao_code, e)

    return profile

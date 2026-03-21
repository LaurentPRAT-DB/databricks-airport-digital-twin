"""OpenFlights route data ingestion for worldwide airport route profiles.

Parses the free OpenFlights routes.dat and airlines.dat files to build
per-airport route distributions (domestic/international shares, airline
shares, fleet mix approximations) for any airport worldwide.

Data source: https://github.com/jpatokal/openflights/tree/master/data
- routes.dat: ~67,000 airline routes
- airlines.dat: airline IATA/ICAO code mappings

The routes.dat CSV has no header. Fields:
  airline, airline_id, src_airport, src_id, dst_airport, dst_id,
  codeshare, stops, equipment
"""

from __future__ import annotations

import csv
import logging
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Optional

from src.calibration.profile import AirportProfile, _iata_to_icao, _icao_to_iata

logger = logging.getLogger(__name__)

_RAW_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "calibration" / "raw"

_ROUTES_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/routes.dat"
_AIRLINES_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airlines.dat"

_ROUTES_FILENAME = "openflights_routes.dat"
_AIRLINES_FILENAME = "openflights_airlines.dat"

# Map common IATA equipment codes to ICAO type designators
_EQUIPMENT_MAP: dict[str, str] = {
    "320": "A320", "321": "A321", "319": "A319", "318": "A318",
    "332": "A330", "333": "A330", "338": "A330", "339": "A330",
    "350": "A350", "351": "A350", "359": "A350",
    "380": "A380", "388": "A380",
    "737": "B737", "738": "B738", "739": "B739", "73H": "B738",
    "73G": "B737", "73J": "B739", "7M8": "B738", "7M9": "B739",
    "752": "B752", "753": "B752",
    "763": "B767", "764": "B767", "767": "B767",
    "772": "B777", "773": "B777", "77W": "B777", "779": "B777",
    "777": "B777", "77L": "B777",
    "787": "B787", "788": "B787", "789": "B787", "78J": "B787",
    "E70": "E175", "E75": "E175", "E90": "E190", "E95": "E190",
    "CR9": "CRJ9", "CR7": "CRJ7", "CRJ": "CRJ9",
    "DH4": "DH8D", "AT7": "AT76", "AT5": "AT76",
    "744": "B744", "748": "B748",
}


def _download_file(url: str, dest: Path) -> Path:
    """Download a file if it doesn't already exist locally."""
    if dest.exists():
        logger.debug("Using cached %s", dest)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading %s → %s", url, dest)
    urllib.request.urlretrieve(url, dest)
    return dest


def _ensure_routes_file(raw_dir: Path | None = None, download: bool = True) -> Path | None:
    """Ensure routes.dat exists locally, downloading if needed."""
    d = raw_dir or _RAW_DIR
    path = d / _ROUTES_FILENAME
    if path.exists():
        return path
    if download:
        return _download_file(_ROUTES_URL, path)
    return None


def _ensure_airlines_file(raw_dir: Path | None = None, download: bool = True) -> Path | None:
    """Ensure airlines.dat exists locally, downloading if needed."""
    d = raw_dir or _RAW_DIR
    path = d / _AIRLINES_FILENAME
    if path.exists():
        return path
    if download:
        return _download_file(_AIRLINES_URL, path)
    return None


def parse_airlines(path: Path) -> dict[str, str]:
    """Parse airlines.dat → mapping of IATA 2-letter code to ICAO 3-letter code.

    airlines.dat fields (no header):
      id, name, alias, iata, icao, callsign, country, active
    """
    iata_to_icao: dict[str, str] = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 5:
                continue
            iata_code = row[3].strip()
            icao_code = row[4].strip()
            if iata_code and iata_code != "\\N" and icao_code and icao_code != "\\N":
                iata_to_icao[iata_code] = icao_code
    logger.debug("Parsed %d airline IATA→ICAO mappings", len(iata_to_icao))
    return iata_to_icao


def parse_routes(
    path: Path,
    airline_map: dict[str, str] | None = None,
) -> list[dict]:
    """Parse routes.dat into a list of route dicts.

    Each dict has: airline_icao, src_iata, dst_iata, equipment (list of types).
    Skips codeshares, rows with missing data, and non-IATA airports.
    """
    if airline_map is None:
        airline_map = {}

    routes: list[dict] = []
    with open(path, encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 9:
                continue

            airline_code = row[0].strip()
            src_airport = row[2].strip()
            dst_airport = row[4].strip()
            codeshare = row[6].strip()
            equipment_str = row[8].strip()

            # Skip rows with missing data
            if "\\N" in (airline_code, src_airport, dst_airport):
                continue

            # Skip codeshares — we only want operating carrier routes
            if codeshare == "Y":
                continue

            # Only keep IATA-coded airports (2-4 letter codes, mostly 3)
            if not (2 <= len(src_airport) <= 4 and src_airport.isalpha()):
                continue
            if not (2 <= len(dst_airport) <= 4 and dst_airport.isalpha()):
                continue

            # Resolve airline code to ICAO (airline_code may be 2-letter IATA)
            if len(airline_code) == 2 and airline_code in airline_map:
                airline_icao = airline_map[airline_code]
            elif len(airline_code) == 3:
                airline_icao = airline_code
            else:
                airline_icao = airline_code  # best effort

            # Parse equipment list (space-separated IATA equipment codes)
            equip_list: list[str] = []
            if equipment_str and equipment_str != "\\N":
                for eq in equipment_str.replace("/", " ").split():
                    mapped = _EQUIPMENT_MAP.get(eq)
                    if mapped:
                        equip_list.append(mapped)

            routes.append({
                "airline_icao": airline_icao,
                "src_iata": src_airport,
                "dst_iata": dst_airport,
                "equipment": equip_list,
            })

    logger.info("Parsed %d operating routes from %s", len(routes), path)
    return routes


def _get_country(iata: str) -> str | None:
    """Get ISO country code for an airport IATA code."""
    try:
        from src.ingestion.airport_table import AIRPORTS
        entry = AIRPORTS.get(iata)
        return entry[3] if entry else None
    except ImportError:
        return None


def build_profile_from_openflights(
    iata: str,
    routes_path: Path | None = None,
    airlines_path: Path | None = None,
    raw_dir: Path | None = None,
    download: bool = True,
    _parsed_routes: list[dict] | None = None,
    _airline_map: dict[str, str] | None = None,
) -> AirportProfile | None:
    """Build an AirportProfile from OpenFlights route data.

    Args:
        iata: IATA code of the target airport (e.g., "JFK")
        routes_path: Path to routes.dat (auto-downloaded if None)
        airlines_path: Path to airlines.dat (auto-downloaded if None)
        raw_dir: Directory for downloaded files
        download: Whether to download missing files
        _parsed_routes: Pre-parsed routes (for batch processing)
        _airline_map: Pre-parsed airline map (for batch processing)

    Returns:
        AirportProfile or None if no routes found for this airport.
    """
    d = raw_dir or _RAW_DIR

    # Get airline mapping
    if _airline_map is None:
        apath = airlines_path or _ensure_airlines_file(d, download)
        if apath and apath.exists():
            _airline_map = parse_airlines(apath)
        else:
            _airline_map = {}

    # Get routes
    if _parsed_routes is None:
        rpath = routes_path or _ensure_routes_file(d, download)
        if rpath is None or not rpath.exists():
            logger.warning("No routes.dat available for %s", iata)
            return None
        _parsed_routes = parse_routes(rpath, _airline_map)

    # Filter routes for this airport (as origin or destination)
    airport_routes = [
        r for r in _parsed_routes
        if r["src_iata"] == iata or r["dst_iata"] == iata
    ]

    if not airport_routes:
        logger.info("No OpenFlights routes found for %s", iata)
        return None

    # Count destinations (the "other end" of each route)
    dest_counts: Counter[str] = Counter()
    airline_counts: Counter[str] = Counter()
    fleet_by_airline: dict[str, Counter[str]] = {}

    for route in airport_routes:
        dest = route["dst_iata"] if route["src_iata"] == iata else route["src_iata"]
        dest_counts[dest] += 1
        airline_counts[route["airline_icao"]] += 1

        # Track equipment per airline
        if route["equipment"]:
            if route["airline_icao"] not in fleet_by_airline:
                fleet_by_airline[route["airline_icao"]] = Counter()
            for eq in route["equipment"]:
                fleet_by_airline[route["airline_icao"]][eq] += 1

    # Determine the home country of this airport
    home_country = _get_country(iata)

    # Split destinations into domestic/international
    domestic_counts: Counter[str] = Counter()
    international_counts: Counter[str] = Counter()

    for dest_iata, count in dest_counts.items():
        dest_country = _get_country(dest_iata)
        if home_country and dest_country and dest_country == home_country:
            domestic_counts[dest_iata] = count
        else:
            international_counts[dest_iata] = count

    # Normalize to shares
    total_domestic = sum(domestic_counts.values()) or 1
    total_international = sum(international_counts.values()) or 1
    total_all = sum(dest_counts.values()) or 1

    domestic_route_shares = {
        d: c / total_domestic for d, c in domestic_counts.most_common()
    }
    international_route_shares = {
        d: c / total_international for d, c in international_counts.most_common()
    }

    # Domestic ratio
    domestic_total = sum(domestic_counts.values())
    domestic_ratio = domestic_total / total_all if total_all > 0 else 0.5

    # Airline shares
    total_airlines = sum(airline_counts.values()) or 1
    airline_shares = {
        a: c / total_airlines for a, c in airline_counts.most_common()
    }

    # Fleet mix per airline (normalize per airline)
    fleet_mix: dict[str, dict[str, float]] = {}
    for airline, equip_counts in fleet_by_airline.items():
        total_equip = sum(equip_counts.values()) or 1
        fleet_mix[airline] = {
            eq: c / total_equip for eq, c in equip_counts.most_common()
        }

    icao = _iata_to_icao(iata)

    return AirportProfile(
        icao_code=icao,
        iata_code=iata,
        airline_shares=airline_shares,
        domestic_route_shares=domestic_route_shares,
        international_route_shares=international_route_shares,
        domestic_ratio=round(domestic_ratio, 3),
        fleet_mix=fleet_mix,
        hourly_profile=[],  # OpenFlights doesn't have schedule times
        delay_rate=0.0,  # No delay data in OpenFlights
        delay_distribution={},
        mean_delay_minutes=0.0,
        data_source="openflights",
        sample_size=len(airport_routes),
    )


def build_profiles_batch(
    iata_codes: list[str],
    raw_dir: Path | None = None,
    download: bool = True,
) -> dict[str, AirportProfile]:
    """Build profiles for multiple airports efficiently (parse files once).

    Returns dict of iata → AirportProfile (only airports with data).
    """
    d = raw_dir or _RAW_DIR

    # Parse data files once
    apath = _ensure_airlines_file(d, download)
    airline_map = parse_airlines(apath) if apath and apath.exists() else {}

    rpath = _ensure_routes_file(d, download)
    if rpath is None or not rpath.exists():
        logger.warning("No routes.dat available")
        return {}
    parsed_routes = parse_routes(rpath, airline_map)

    # Build profiles
    results: dict[str, AirportProfile] = {}
    for iata in iata_codes:
        profile = build_profile_from_openflights(
            iata, raw_dir=d, download=False,
            _parsed_routes=parsed_routes, _airline_map=airline_map,
        )
        if profile is not None:
            results[iata] = profile
            logger.info(
                "  %s: airlines=%d, dom_routes=%d, intl_routes=%d, ratio=%.2f",
                iata, len(profile.airline_shares),
                len(profile.domestic_route_shares),
                len(profile.international_route_shares),
                profile.domestic_ratio,
            )

    logger.info("Built %d OpenFlights profiles out of %d requested", len(results), len(iata_codes))
    return results

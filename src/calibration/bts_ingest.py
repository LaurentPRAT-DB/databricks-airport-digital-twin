"""BTS T-100 and On-Time Performance data ingestion.

Parses Bureau of Transportation Statistics CSV files to extract
per-airport statistical distributions for synthetic flight calibration.

Data sources:
- T-100 Domestic Segment: airline market share, route frequencies, fleet mix
- T-100 International Segment: international route frequencies
- On-Time Performance: delay rates, delay cause breakdown, hourly patterns
"""

from __future__ import annotations

import csv
import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

from src.calibration.profile import AirportProfile, _iata_to_icao, _icao_to_iata

logger = logging.getLogger(__name__)


def parse_t100_segment(
    csv_path: Path,
    target_airport: str,
    is_international: bool = False,
) -> dict:
    """Parse BTS T-100 segment data for a specific airport.

    Extracts from T-100 CSV:
    - airline_departures: {carrier_code: total_departures}
    - route_volumes: {destination_iata: total_passengers}
    - fleet_usage: {carrier_code: {aircraft_type: count}}

    Args:
        csv_path: Path to T-100 segment CSV file
        target_airport: IATA code of the target airport (e.g., "SFO")
        is_international: Whether this is international segment data

    Returns:
        Dict with airline_departures, route_volumes, fleet_usage
    """
    airline_departures: Counter = Counter()
    route_volumes: Counter = Counter()
    fleet_usage: dict[str, Counter] = defaultdict(Counter)
    total_rows = 0

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            origin = row.get("ORIGIN", "").strip()
            dest = row.get("DEST", "").strip()

            # Only process rows where target airport is origin or destination
            if origin != target_airport and dest != target_airport:
                continue

            total_rows += 1
            carrier = row.get("UNIQUE_CARRIER", row.get("CARRIER", "")).strip()
            departures = _safe_int(row.get("DEPARTURES_PERFORMED", "0"))
            passengers = _safe_int(row.get("PASSENGERS", "0"))
            aircraft_type = row.get("AIRCRAFT_TYPE", "").strip()

            # Airline departures (only count when target is origin)
            if origin == target_airport and departures > 0:
                airline_departures[carrier] += departures

                # Route volumes
                route_volumes[dest] += passengers

                # Fleet usage
                if aircraft_type:
                    fleet_usage[carrier][aircraft_type] += departures

    logger.info(
        "Parsed T-100 %s for %s: %d rows, %d carriers, %d routes",
        "international" if is_international else "domestic",
        target_airport,
        total_rows,
        len(airline_departures),
        len(route_volumes),
    )

    return {
        "airline_departures": dict(airline_departures),
        "route_volumes": dict(route_volumes),
        "fleet_usage": {k: dict(v) for k, v in fleet_usage.items()},
    }


def parse_ontime_performance(
    csv_path: Path,
    target_airport: str,
) -> dict:
    """Parse BTS On-Time Performance data for a specific airport.

    Extracts:
    - delay_rate: fraction of flights with >15 min delay
    - delay_causes: {cause_code: count}
    - hourly_departures: {hour: count}
    - hourly_arrivals: {hour: count}
    - mean_delay_minutes: average delay for delayed flights

    Args:
        csv_path: Path to On-Time Performance CSV file
        target_airport: IATA code of the target airport

    Returns:
        Dict with delay stats and hourly patterns
    """
    total_flights = 0
    delayed_flights = 0
    total_delay_minutes = 0.0
    delay_causes: Counter = Counter()
    hourly_departures: Counter = Counter()
    hourly_arrivals: Counter = Counter()

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            origin = row.get("ORIGIN", "").strip()
            dest = row.get("DEST", "").strip()

            is_departure = origin == target_airport
            is_arrival = dest == target_airport

            if not (is_departure or is_arrival):
                continue

            total_flights += 1

            # Hourly pattern
            dep_time = row.get("CRS_DEP_TIME", "").strip()
            arr_time = row.get("CRS_ARR_TIME", "").strip()
            if is_departure and dep_time and len(dep_time) >= 3:
                hour = int(dep_time[:-2]) if len(dep_time) > 2 else 0
                hourly_departures[hour % 24] += 1
            if is_arrival and arr_time and len(arr_time) >= 3:
                hour = int(arr_time[:-2]) if len(arr_time) > 2 else 0
                hourly_arrivals[hour % 24] += 1

            # Delay stats (only count departures for delay rate)
            if is_departure:
                dep_delay = _safe_float(row.get("DEP_DELAY", "0"))
                if dep_delay > 15:
                    delayed_flights += 1
                    total_delay_minutes += dep_delay

                    # Delay cause breakdown
                    if _safe_float(row.get("CARRIER_DELAY", "0")) > 0:
                        delay_causes["carrier"] += 1
                    if _safe_float(row.get("WEATHER_DELAY", "0")) > 0:
                        delay_causes["weather"] += 1
                    if _safe_float(row.get("NAS_DELAY", "0")) > 0:
                        delay_causes["nas"] += 1
                    if _safe_float(row.get("SECURITY_DELAY", "0")) > 0:
                        delay_causes["security"] += 1
                    if _safe_float(row.get("LATE_AIRCRAFT_DELAY", "0")) > 0:
                        delay_causes["late_aircraft"] += 1

    delay_rate = delayed_flights / total_flights if total_flights > 0 else 0.15
    mean_delay = total_delay_minutes / delayed_flights if delayed_flights > 0 else 20.0

    logger.info(
        "Parsed On-Time for %s: %d flights, %.1f%% delayed, %.1f min avg delay",
        target_airport,
        total_flights,
        delay_rate * 100,
        mean_delay,
    )

    return {
        "delay_rate": delay_rate,
        "delay_causes": dict(delay_causes),
        "hourly_departures": dict(hourly_departures),
        "hourly_arrivals": dict(hourly_arrivals),
        "mean_delay_minutes": mean_delay,
        "total_flights": total_flights,
        "delayed_flights": delayed_flights,
    }


def build_profile_from_bts(
    target_airport: str,
    t100_domestic_path: Optional[Path] = None,
    t100_international_path: Optional[Path] = None,
    ontime_path: Optional[Path] = None,
) -> AirportProfile:
    """Build an AirportProfile from BTS data files.

    Args:
        target_airport: IATA code (e.g., "SFO")
        t100_domestic_path: Path to T-100 domestic segment CSV
        t100_international_path: Path to T-100 international segment CSV
        ontime_path: Path to On-Time Performance CSV

    Returns:
        AirportProfile with distributions learned from BTS data
    """
    icao = _iata_to_icao(target_airport)
    iata = target_airport

    airline_shares: dict[str, float] = {}
    domestic_route_shares: dict[str, float] = {}
    international_route_shares: dict[str, float] = {}
    fleet_mix: dict[str, dict[str, float]] = {}
    domestic_ratio = 0.7
    hourly_profile: list[float] = []
    delay_rate = 0.15
    delay_distribution: dict[str, float] = {}
    mean_delay_minutes = 20.0
    sample_size = 0
    data_sources: list[str] = []

    # --- T-100 Domestic ---
    dom_departures = 0
    if t100_domestic_path and t100_domestic_path.exists():
        dom_data = parse_t100_segment(t100_domestic_path, iata, is_international=False)
        dom_departures = sum(dom_data["airline_departures"].values())
        data_sources.append("BTS_T100_domestic")

        # Domestic route shares
        total_pax = sum(dom_data["route_volumes"].values()) or 1
        domestic_route_shares = {
            k: v / total_pax for k, v in dom_data["route_volumes"].items()
        }

        # Fleet usage (domestic)
        for carrier, types in dom_data["fleet_usage"].items():
            total = sum(types.values()) or 1
            fleet_mix[carrier] = {t: c / total for t, c in types.items()}

    # --- T-100 International ---
    intl_departures = 0
    if t100_international_path and t100_international_path.exists():
        intl_data = parse_t100_segment(t100_international_path, iata, is_international=True)
        intl_departures = sum(intl_data["airline_departures"].values())
        data_sources.append("BTS_T100_international")

        total_pax = sum(intl_data["route_volumes"].values()) or 1
        international_route_shares = {
            k: v / total_pax for k, v in intl_data["route_volumes"].items()
        }

        # Merge fleet from international
        for carrier, types in intl_data["fleet_usage"].items():
            if carrier not in fleet_mix:
                total = sum(types.values()) or 1
                fleet_mix[carrier] = {t: c / total for t, c in types.items()}

    # Compute airline shares from combined domestic + international departures
    if t100_domestic_path and t100_domestic_path.exists():
        dom_data_airlines = parse_t100_segment(t100_domestic_path, iata)["airline_departures"]
    else:
        dom_data_airlines = {}
    if t100_international_path and t100_international_path.exists():
        intl_data_airlines = parse_t100_segment(t100_international_path, iata)["airline_departures"]
    else:
        intl_data_airlines = {}

    all_airlines: Counter = Counter(dom_data_airlines)
    all_airlines.update(intl_data_airlines)
    total_deps = sum(all_airlines.values()) or 1
    airline_shares = {k: v / total_deps for k, v in all_airlines.items()}

    # Domestic ratio
    total_all = dom_departures + intl_departures
    if total_all > 0:
        domestic_ratio = dom_departures / total_all

    # --- On-Time Performance ---
    if ontime_path and ontime_path.exists():
        ontime = parse_ontime_performance(ontime_path, iata)
        delay_rate = ontime["delay_rate"]
        mean_delay_minutes = ontime["mean_delay_minutes"]
        sample_size = ontime["total_flights"]
        data_sources.append("BTS_OnTime")

        # Map BTS delay causes to IATA delay codes
        cause_total = sum(ontime["delay_causes"].values()) or 1
        cause_map = {
            "carrier": {"62": 0.4, "67": 0.3, "63": 0.3},  # cleaning/crew/baggage
            "weather": {"71": 0.6, "72": 0.4},  # weather dep/dest
            "nas": {"81": 1.0},  # ATC
            "security": {"41": 1.0},  # security → aircraft defect bucket
            "late_aircraft": {"68": 1.0},  # late inbound
        }
        delay_distribution = {}
        for cause, count in ontime["delay_causes"].items():
            weight = count / cause_total
            for code, frac in cause_map.get(cause, {}).items():
                delay_distribution[code] = delay_distribution.get(code, 0) + weight * frac

        # Hourly profile from combined departures + arrivals
        combined_hourly: Counter = Counter(ontime["hourly_departures"])
        combined_hourly.update(ontime["hourly_arrivals"])
        if combined_hourly:
            total_hourly = sum(combined_hourly.values()) or 1
            hourly_profile = [
                combined_hourly.get(h, 0) / total_hourly for h in range(24)
            ]

    return AirportProfile(
        icao_code=icao,
        iata_code=iata,
        airline_shares=airline_shares,
        domestic_route_shares=domestic_route_shares,
        international_route_shares=international_route_shares,
        domestic_ratio=domestic_ratio,
        fleet_mix=fleet_mix,
        hourly_profile=hourly_profile,
        delay_rate=delay_rate,
        delay_distribution=delay_distribution,
        mean_delay_minutes=mean_delay_minutes,
        data_source="+".join(data_sources) if data_sources else "fallback",
        profile_date="",
        sample_size=sample_size,
    )


# ============================================================================
# BTS aircraft type code → common type code mapping
# ============================================================================

BTS_AIRCRAFT_MAP: dict[str, str] = {
    # Narrow body
    "612": "A319", "613": "A320", "614": "A321",
    "624": "B737", "625": "B738", "626": "B739",
    "627": "B73H",
    "637": "E170", "638": "E175", "639": "E190",
    # Wide body
    "654": "B772", "655": "B773", "656": "B77W",
    "660": "B788", "661": "B789",
    "632": "A332", "633": "A333", "634": "A339",
    "635": "A359",
    "636": "A388",
}


def _safe_int(val: str) -> int:
    """Parse an int from a string, returning 0 on failure."""
    try:
        return int(float(val.strip().replace(",", "")))
    except (ValueError, AttributeError):
        return 0


def _safe_float(val: str) -> float:
    """Parse a float from a string, returning 0.0 on failure."""
    try:
        return float(val.strip().replace(",", ""))
    except (ValueError, AttributeError):
        return 0.0

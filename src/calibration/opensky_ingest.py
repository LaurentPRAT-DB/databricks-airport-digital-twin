"""OpenSky Network data ingestion for international airport profiles.

Uses the OpenSky REST API (free tier) to derive airline mix and hourly
patterns for airports not covered by BTS data.

API documentation: https://openskynetwork.github.io/opensky-api/
Rate limit: ~400 requests/day, 1-hour data windows.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

from src.calibration.profile import AirportProfile, _iata_to_icao

logger = logging.getLogger(__name__)

# OpenSky REST API base URL
_OPENSKY_API = "https://opensky-network.org/api"

# Common airline ICAO prefixes → 3-letter carrier code
_CALLSIGN_TO_CARRIER: dict[str, str] = {
    "UAL": "UAL", "DAL": "DAL", "AAL": "AAL", "SWA": "SWA",
    "ASA": "ASA", "JBU": "JBU",
    "BAW": "BAW", "SHT": "BAW",  # BA shuttle
    "DLH": "DLH", "EWG": "DLH",  # Lufthansa + Eurowings
    "AFR": "AFR",
    "KLM": "KLM",
    "UAE": "UAE",
    "ANA": "ANA", "NCA": "ANA",
    "JAL": "JAL",
    "SIA": "SIA",
    "QFA": "QFA", "QLK": "QFA",  # Qantas + QantasLink
    "CPA": "CPA",
    "SAA": "SAA",
    "TAM": "TAM", "GLO": "GLO",
    "RYR": "RYR",
    "EZY": "EZY",
    "THY": "THY",
    "ETH": "ETH",
    "CCA": "CCA",
    "CES": "CES",
    "CSN": "CSN",
    "KAL": "KAL",
    "AAR": "AAR",
    "EVA": "EVA",
}


def query_departures(
    airport_icao: str,
    begin_ts: int,
    end_ts: int,
    auth: Optional[tuple[str, str]] = None,
) -> list[dict]:
    """Query OpenSky departures API for an airport in a time window.

    Args:
        airport_icao: ICAO code (e.g., "EGLL")
        begin_ts: Unix timestamp for window start
        end_ts: Unix timestamp for window end
        auth: Optional (username, password) for authenticated access

    Returns:
        List of departure dicts from OpenSky API
    """
    import urllib.request
    import json

    url = f"{_OPENSKY_API}/flights/departure?airport={airport_icao}&begin={begin_ts}&end={end_ts}"
    req = urllib.request.Request(url)
    if auth:
        import base64
        credentials = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {credentials}")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning("OpenSky API error for %s: %s", airport_icao, e)
        return []


def query_arrivals(
    airport_icao: str,
    begin_ts: int,
    end_ts: int,
    auth: Optional[tuple[str, str]] = None,
) -> list[dict]:
    """Query OpenSky arrivals API for an airport in a time window."""
    import urllib.request
    import json

    url = f"{_OPENSKY_API}/flights/arrival?airport={airport_icao}&begin={begin_ts}&end={end_ts}"
    req = urllib.request.Request(url)
    if auth:
        import base64
        credentials = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {credentials}")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning("OpenSky API error for %s: %s", airport_icao, e)
        return []


def build_profile_from_opensky(
    airport_iata: str,
    days: int = 7,
    auth: Optional[tuple[str, str]] = None,
    rate_limit_delay: float = 2.0,
) -> AirportProfile:
    """Build an AirportProfile by querying OpenSky for recent flight data.

    Queries departures and arrivals over the specified number of days,
    extracting airline mix and hourly patterns from callsigns and timestamps.

    Args:
        airport_iata: IATA code (e.g., "LHR")
        days: Number of days of data to fetch (max 7 for free tier)
        auth: Optional (username, password) for higher rate limits
        rate_limit_delay: Seconds to wait between API calls

    Returns:
        AirportProfile with distributions from OpenSky data
    """
    icao = _iata_to_icao(airport_iata)

    airline_counts: Counter = Counter()
    hourly_dep: Counter = Counter()
    hourly_arr: Counter = Counter()
    route_counts: Counter = Counter()
    total_flights = 0

    now = int(datetime.now(timezone.utc).timestamp())

    for day_offset in range(days):
        end_ts = now - day_offset * 86400
        begin_ts = end_ts - 86400  # 24-hour window

        # Query departures
        deps = query_departures(icao, begin_ts, end_ts, auth=auth)
        for flight in deps:
            total_flights += 1
            callsign = (flight.get("callsign") or "").strip()
            carrier = _extract_carrier(callsign)
            if carrier:
                airline_counts[carrier] += 1

            # Hourly pattern
            first_seen = flight.get("firstSeen")
            if first_seen:
                hour = datetime.fromtimestamp(first_seen, tz=timezone.utc).hour
                hourly_dep[hour] += 1

            # Destination
            est_dest = flight.get("estArrivalAirport", "")
            if est_dest:
                route_counts[est_dest] += 1

        time.sleep(rate_limit_delay)

        # Query arrivals
        arrs = query_arrivals(icao, begin_ts, end_ts, auth=auth)
        for flight in arrs:
            total_flights += 1
            callsign = (flight.get("callsign") or "").strip()
            carrier = _extract_carrier(callsign)
            if carrier:
                airline_counts[carrier] += 1

            last_seen = flight.get("lastSeen")
            if last_seen:
                hour = datetime.fromtimestamp(last_seen, tz=timezone.utc).hour
                hourly_arr[hour] += 1

        time.sleep(rate_limit_delay)

    # Build normalized distributions
    total_airlines = sum(airline_counts.values()) or 1
    airline_shares = {k: v / total_airlines for k, v in airline_counts.most_common(20)}

    # Route shares (top 30)
    total_routes = sum(route_counts.values()) or 1
    route_shares = {k: v / total_routes for k, v in route_counts.most_common(30)}

    # Hourly profile
    combined = Counter(hourly_dep)
    combined.update(hourly_arr)
    total_hourly = sum(combined.values()) or 1
    hourly_profile = [combined.get(h, 0) / total_hourly for h in range(24)]

    logger.info(
        "Built OpenSky profile for %s: %d flights over %d days, %d carriers",
        airport_iata, total_flights, days, len(airline_shares),
    )

    return AirportProfile(
        icao_code=icao,
        iata_code=airport_iata,
        airline_shares=airline_shares,
        domestic_route_shares={},  # OpenSky doesn't distinguish domestic/intl
        international_route_shares=route_shares,
        domestic_ratio=0.5,  # Unknown — use 50/50
        fleet_mix={},  # OpenSky doesn't provide aircraft type in free tier
        hourly_profile=hourly_profile,
        delay_rate=0.15,  # OpenSky doesn't provide delay data
        delay_distribution={},
        mean_delay_minutes=20.0,
        data_source="OpenSky",
        profile_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        sample_size=total_flights,
    )


def _extract_carrier(callsign: str) -> Optional[str]:
    """Extract airline carrier code from a callsign (e.g., 'BAW123' → 'BAW')."""
    if not callsign or len(callsign) < 4:
        return None
    prefix = callsign[:3]
    return _CALLSIGN_TO_CARRIER.get(prefix, prefix)

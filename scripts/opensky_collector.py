#!/usr/bin/env python3
"""Local OpenSky ADS-B data collector for ML training data.

Downloads real-time aircraft state vectors from the OpenSky Network REST API
and saves them as JSON-lines files for later upload to a Databricks UC Volume.

Enriches each record with aircraft type (from OpenSky aircraft database),
airline ICAO code (from callsign), and collection metadata.

## Recommended Collection Strategies

### Quick test (verify connectivity)
    uv run python scripts/opensky_collector.py --airport LSGG --duration 120

### Single-airport ML session (capture full turnarounds)
    uv run python scripts/opensky_collector.py --airport LSGG --duration 14400

    2h default captures most turnarounds (30-90 min). Use 4h (14400s) for
    wide-body turnarounds and to ensure multiple parked→pushback cycles.

### Multi-airport diversity collection
    uv run python scripts/opensky_collector.py --airports LSGG,LFPG,EDDF --duration 7200

    Round-robins through airports. Each airport is fetched every
    (interval × num_airports) seconds. Builds diverse training data.

### Overnight batch (maximum data)
    uv run python scripts/opensky_collector.py --airports LSGG,EDDF,EGLL,LFPG --duration 28800

    8-hour session across 4 major European airports. Authenticated
    accounts recommended (set OPENSKY_USERNAME/OPENSKY_PASSWORD) for
    higher rate limits.

## Upload to Databricks
    databricks fs cp data/opensky_raw/ \\
        dbfs:/Volumes/serverless_stable_3n0ihb_catalog/airport_digital_twin/opensky_raw/ \\
        --recursive
    databricks bundle run opensky_ingestion --target dev

Environment variables:
    OPENSKY_USERNAME  — OpenSky account username (optional, improves rate limits)
    OPENSKY_PASSWORD  — OpenSky account password
"""

import argparse
import csv
import io
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("opensky_collector")

OPENSKY_API_URL = "https://opensky-network.org/api/states/all"
OPENSKY_AIRCRAFT_DB_URL = "https://opensky-network.org/datasets/metadata/aircraftDatabase.csv"

# Bounding-box half-size in degrees (~0.5° ≈ 30 nm)
DEFAULT_RADIUS_DEG = 0.5

# Defaults tuned for ML training data collection
DEFAULT_INTERVAL_S = 10      # Higher temporal resolution for event inference
DEFAULT_DURATION_S = 7200    # 2 hours — captures full turnarounds (30-90 min)

# OpenSky state vector field names (index → name)
STATE_FIELDS = [
    "icao24",           # 0
    "callsign",         # 1
    "origin_country",   # 2
    "time_position",    # 3
    "last_contact",     # 4
    "longitude",        # 5
    "latitude",         # 6
    "baro_altitude",    # 7  meters
    "on_ground",        # 8
    "velocity",         # 9  m/s
    "true_track",       # 10 degrees
    "vertical_rate",    # 11 m/s
    "sensors",          # 12
    "geo_altitude",     # 13 meters
    "squawk",           # 14
    "spi",              # 15
    "position_source",  # 16
]

# Airport reference coordinates (for collector bounding box only — not geometry)
AIRPORT_COORDS: dict[str, tuple[float, float]] = {
    "KSFO": (37.6213, -122.3790),
    "KJFK": (40.6413, -73.7781),
    "KLAX": (33.9425, -118.4081),
    "KORD": (41.9742, -87.9073),
    "KATL": (33.6407, -84.4277),
    "KDEN": (39.8561, -104.6737),
    "KDFW": (32.8998, -97.0403),
    "EGLL": (51.4700, -0.4543),   # London Heathrow
    "LFPG": (49.0097, 2.5479),    # Paris CDG
    "UKBB": (50.3450, 30.8947),   # Kyiv Boryspil
    "LEMD": (40.4936, -3.5668),   # Madrid Barajas
    "EDDF": (50.0379, 8.5622),    # Frankfurt
    "LSGG": (46.2381, 6.1089),    # Geneva
    "EHAM": (52.3086, 4.7639),    # Amsterdam Schiphol
    "LIRF": (41.8003, 12.2389),   # Rome Fiumicino
    "LSZH": (47.4647, 8.5492),    # Zurich
    "EIDW": (53.4213, -6.2701),   # Dublin
    "ESSA": (59.6519, 17.9186),   # Stockholm Arlanda
    "LOWW": (48.1103, 16.5697),   # Vienna
    "LPPT": (38.7742, -9.1342),   # Lisbon
}

_shutdown = False


def _signal_handler(sig, frame):
    global _shutdown
    logger.info("Shutdown requested (Ctrl+C)")
    _shutdown = True


# ── Aircraft type database ───────────────────────────────────────────────

_aircraft_db: dict[str, dict[str, str]] = {}  # icao24 → {typecode, registration}


def load_aircraft_database(cache_dir: Path) -> int:
    """Download and cache the OpenSky aircraft database for icao24→type enrichment.

    The database maps icao24 hex addresses to aircraft type codes (e.g., B738, A320)
    and registration numbers. It's a ~30MB CSV that we cache locally.

    Returns:
        Number of aircraft entries loaded.
    """
    global _aircraft_db
    cache_file = cache_dir / "aircraft_db.csv"

    # Use cached version if less than 7 days old
    if cache_file.exists():
        age_days = (time.time() - cache_file.stat().st_mtime) / 86400
        if age_days < 7:
            return _parse_aircraft_csv(cache_file)

    logger.info("Downloading OpenSky aircraft database...")
    try:
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            resp = client.get(OPENSKY_AIRCRAFT_DB_URL)
            resp.raise_for_status()
            cache_file.write_bytes(resp.content)
            logger.info("Aircraft database cached: %.1f MB", len(resp.content) / 1e6)
            return _parse_aircraft_csv(cache_file)
    except Exception as e:
        logger.warning("Failed to download aircraft database: %s (enrichment disabled)", e)
        if cache_file.exists():
            # Fall back to stale cache
            return _parse_aircraft_csv(cache_file)
        return 0


def _parse_aircraft_csv(path: Path) -> int:
    """Parse the OpenSky aircraft CSV into the lookup dict."""
    global _aircraft_db
    _aircraft_db = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                icao24 = (row.get("icao24") or "").strip().lower()
                if not icao24:
                    continue
                typecode = (row.get("typecode") or "").strip()
                registration = (row.get("registration") or "").strip()
                if typecode or registration:
                    _aircraft_db[icao24] = {
                        "typecode": typecode,
                        "registration": registration,
                    }
    except Exception as e:
        logger.warning("Error parsing aircraft database: %s", e)

    logger.info("Aircraft database loaded: %d entries", len(_aircraft_db))
    return len(_aircraft_db)


def enrich_aircraft_type(icao24: str) -> tuple[str, str]:
    """Look up aircraft type and registration for an icao24 address.

    Returns:
        (typecode, registration) — empty strings if not found.
    """
    entry = _aircraft_db.get(icao24.lower(), {})
    return entry.get("typecode", ""), entry.get("registration", "")


def extract_airline_icao(callsign: str | None) -> str:
    """Extract ICAO airline code from callsign (first 3 alpha characters).

    Examples: "SWR100" → "SWR", "EZY12AB" → "EZY", "N12345" → ""
    """
    if not callsign:
        return ""
    cs = callsign.strip()
    if len(cs) >= 3 and cs[:3].isalpha():
        return cs[:3].upper()
    return ""


# ── Data collection ──────────────────────────────────────────────────────

def fetch_states(
    client: httpx.Client,
    lat: float,
    lon: float,
    radius_deg: float,
    auth: tuple[str, str] | None,
) -> tuple[int | None, list[list] | None]:
    """Fetch state vectors from OpenSky. Returns (api_time, states) or (None, None)."""
    params = {
        "lamin": lat - radius_deg,
        "lamax": lat + radius_deg,
        "lomin": lon - radius_deg,
        "lomax": lon + radius_deg,
    }
    kwargs: dict = {"params": params, "timeout": 15.0}
    if auth:
        kwargs["auth"] = auth

    resp = client.get(OPENSKY_API_URL, **kwargs)

    if resp.status_code == 429:
        return None, None  # caller handles backoff

    resp.raise_for_status()
    data = resp.json()
    return data.get("time"), data.get("states") or []


def state_to_record(state: list, collection_time: str, airport_icao: str) -> dict | None:
    """Convert a raw OpenSky state array to a named-field dict with enrichment."""
    if len(state) < 14:
        return None
    lat = state[6]
    lon = state[5]
    if lat is None or lon is None:
        return None

    record = {}
    for i, name in enumerate(STATE_FIELDS):
        if i < len(state):
            record[name] = state[i]
    # Strip callsign whitespace
    if record.get("callsign"):
        record["callsign"] = record["callsign"].strip()

    # Enrich with aircraft type from OpenSky database
    icao24 = record.get("icao24", "")
    typecode, registration = enrich_aircraft_type(icao24)
    record["aircraft_type"] = typecode
    record["registration"] = registration

    # Extract airline ICAO code from callsign
    record["airline_icao"] = extract_airline_icao(record.get("callsign"))

    # Add collection metadata
    record["collection_time"] = collection_time
    record["airport_icao"] = airport_icao
    record["data_source"] = "opensky_live"
    return record


def collect_once(
    client: httpx.Client,
    airport_icao: str,
    lat: float,
    lon: float,
    radius_deg: float,
    auth: tuple[str, str] | None,
    output_dir: Path,
) -> int:
    """Run one collection cycle. Returns number of states written, or -1 for rate limit."""
    now = datetime.now(timezone.utc)
    collection_time = now.isoformat()

    api_time, states = fetch_states(client, lat, lon, radius_deg, auth)
    if states is None:
        return -1  # rate limited

    if not states:
        logger.info("[%s] No aircraft in bounding box", airport_icao)
        return 0

    # Build records
    records = []
    for s in states:
        rec = state_to_record(s, collection_time, airport_icao)
        if rec:
            records.append(rec)

    if not records:
        return 0

    # Count enrichment stats
    typed = sum(1 for r in records if r.get("aircraft_type"))
    airlines = sum(1 for r in records if r.get("airline_icao"))

    # Write JSONL file
    ts_str = now.strftime("%Y-%m-%dT%H-%M-%SZ")
    filename = f"{airport_icao}_{ts_str}.jsonl"
    filepath = output_dir / filename

    with open(filepath, "w") as f:
        for rec in records:
            f.write(json.dumps(rec, default=str) + "\n")

    logger.info(
        "[%s] %d states → %s (type: %d/%d, airline: %d/%d)",
        airport_icao, len(records), filepath.name,
        typed, len(records), airlines, len(records),
    )
    return len(records)


def main():
    parser = argparse.ArgumentParser(
        description="Collect OpenSky ADS-B data for airport ML training",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  Quick test:          %(prog)s --airport LSGG --duration 120
  2-hour session:      %(prog)s --airport LSGG
  Multi-airport:       %(prog)s --airports LSGG,LFPG,EDDF
  Overnight batch:     %(prog)s --airports LSGG,EDDF,EGLL,LFPG --duration 28800
  No aircraft DB:      %(prog)s --airport LSGG --no-aircraft-db
""",
    )
    parser.add_argument("--airport", default=None, help="ICAO code for single-airport collection")
    parser.add_argument(
        "--airports", default=None,
        help="Comma-separated ICAO codes for multi-airport collection (e.g., LSGG,LFPG,EDDF)",
    )
    parser.add_argument(
        "--interval", type=int, default=DEFAULT_INTERVAL_S,
        help=f"Seconds between fetches per airport (default: {DEFAULT_INTERVAL_S})",
    )
    parser.add_argument(
        "--duration", type=int, default=DEFAULT_DURATION_S,
        help=f"Total seconds to run, 0=indefinite (default: {DEFAULT_DURATION_S} = 2h)",
    )
    parser.add_argument(
        "--radius", type=float, default=DEFAULT_RADIUS_DEG,
        help=f"Bounding box half-size in degrees (default: {DEFAULT_RADIUS_DEG})",
    )
    parser.add_argument("--output-dir", default="data/opensky_raw", help="Output directory")
    parser.add_argument("--lat", type=float, help="Override airport latitude (single-airport only)")
    parser.add_argument("--lon", type=float, help="Override airport longitude (single-airport only)")
    parser.add_argument(
        "--no-aircraft-db", action="store_true",
        help="Skip downloading the OpenSky aircraft database (no type enrichment)",
    )
    args = parser.parse_args()

    # ── Resolve airport list ──
    airports: list[tuple[str, float, float]] = []  # (icao, lat, lon)

    if args.airports:
        for code in args.airports.split(","):
            code = code.strip().upper()
            if code in AIRPORT_COORDS:
                lat, lon = AIRPORT_COORDS[code]
                airports.append((code, lat, lon))
            else:
                logger.error("Unknown airport %s — add to AIRPORT_COORDS or use --lat/--lon", code)
                sys.exit(1)
    elif args.airport:
        airport = args.airport.upper()
        if args.lat is not None and args.lon is not None:
            airports.append((airport, args.lat, args.lon))
        elif airport in AIRPORT_COORDS:
            lat, lon = AIRPORT_COORDS[airport]
            airports.append((airport, lat, lon))
        else:
            logger.error("Unknown airport %s — provide --lat/--lon or add to AIRPORT_COORDS", airport)
            sys.exit(1)
    else:
        # Default: LSGG (Geneva)
        airports.append(("LSGG", *AIRPORT_COORDS["LSGG"]))

    # Auth from env
    username = os.getenv("OPENSKY_USERNAME")
    password = os.getenv("OPENSKY_PASSWORD")
    auth = (username, password) if username and password else None

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # ── Load aircraft database for type enrichment ──
    if not args.no_aircraft_db:
        db_count = load_aircraft_database(output_dir)
        if db_count:
            logger.info("Aircraft type enrichment: %d entries loaded", db_count)
        else:
            logger.info("Aircraft type enrichment: disabled (no database)")

    # ── Log collection plan ──
    airport_names = ", ".join(f"{a[0]} ({a[1]:.4f}, {a[2]:.4f})" for a in airports)
    effective_interval = args.interval * len(airports)
    duration_str = f"{args.duration}s ({args.duration / 3600:.1f}h)" if args.duration else "indefinite"

    logger.info("OpenSky Collector starting")
    logger.info("  Airports: %s", airport_names)
    logger.info("  Interval: %ds per airport (%ds effective cycle for %d airports)",
                args.interval, effective_interval, len(airports))
    logger.info("  Duration: %s", duration_str)
    logger.info("  Radius: %.2f°", args.radius)
    logger.info("  Auth: %s", "authenticated" if auth else "anonymous (lower rate limits)")
    logger.info("  Output: %s", output_dir.resolve())

    client = httpx.Client()
    start_time = time.monotonic()
    total_states = 0
    total_fetches = 0
    stats_by_airport: dict[str, int] = {a[0]: 0 for a in airports}
    backoff = 1  # exponential backoff for rate limits
    airport_idx = 0

    try:
        while not _shutdown:
            if args.duration and (time.monotonic() - start_time) >= args.duration:
                logger.info("Duration reached (%s), stopping", duration_str)
                break

            # Round-robin through airports
            airport_icao, lat, lon = airports[airport_idx]
            airport_idx = (airport_idx + 1) % len(airports)

            try:
                count = collect_once(client, airport_icao, lat, lon, args.radius, auth, output_dir)
                if count == -1:
                    # Rate limited — exponential backoff
                    wait = min(backoff * 10, 120)
                    logger.warning("Rate limited (429), backing off %ds", wait)
                    backoff *= 2
                    time.sleep(wait)
                    continue
                else:
                    backoff = 1  # reset on success
                    total_states += count
                    total_fetches += 1
                    stats_by_airport[airport_icao] = stats_by_airport.get(airport_icao, 0) + count

            except httpx.HTTPStatusError as e:
                logger.error("HTTP error: %s", e)
            except Exception as e:
                logger.error("Fetch error: %s", e)

            # Wait for next cycle
            for _ in range(args.interval):
                if _shutdown:
                    break
                time.sleep(1)

    finally:
        client.close()
        elapsed = time.monotonic() - start_time
        logger.info("=" * 60)
        logger.info("Collector stopped after %.0fs (%d fetches, %d total states)", elapsed, total_fetches, total_states)
        for apt, count in sorted(stats_by_airport.items()):
            logger.info("  %s: %d states", apt, count)

        # List output files
        for apt_icao, _, _ in airports:
            files = sorted(output_dir.glob(f"{apt_icao}_*.jsonl"))
            if files:
                total_size = sum(f.stat().st_size for f in files)
                logger.info("  %s: %d files, %.1f MB", apt_icao, len(files), total_size / 1e6)
        logger.info("=" * 60)


if __name__ == "__main__":
    main()

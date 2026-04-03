#!/usr/bin/env python3
"""Local OpenSky ADS-B data collector.

Downloads real-time aircraft state vectors from the OpenSky Network REST API
and saves them as JSON-lines files for later upload to a Databricks UC Volume.

Usage:
    uv run python scripts/opensky_collector.py --airport KSFO --interval 15
    uv run python scripts/opensky_collector.py --airport KJFK --interval 30 --duration 3600

Environment variables:
    OPENSKY_USERNAME  — OpenSky account username (optional, improves rate limits)
    OPENSKY_PASSWORD  — OpenSky account password
"""

import argparse
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

# Bounding-box half-size in degrees (~0.5° ≈ 30 nm)
DEFAULT_RADIUS_DEG = 0.5

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
}

_shutdown = False


def _signal_handler(sig, frame):
    global _shutdown
    logger.info("Shutdown requested (Ctrl+C)")
    _shutdown = True


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
    """Convert a raw OpenSky state array to a named-field dict."""
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
        logger.info("No aircraft in bounding box")
        return 0

    # Build records
    records = []
    for s in states:
        rec = state_to_record(s, collection_time, airport_icao)
        if rec:
            records.append(rec)

    if not records:
        return 0

    # Write JSONL file
    ts_str = now.strftime("%Y-%m-%dT%H-%M-%SZ")
    filename = f"{airport_icao}_{ts_str}.jsonl"
    filepath = output_dir / filename

    with open(filepath, "w") as f:
        for rec in records:
            f.write(json.dumps(rec, default=str) + "\n")

    logger.info("Wrote %d states → %s", len(records), filepath.name)
    return len(records)


def main():
    parser = argparse.ArgumentParser(description="Collect OpenSky ADS-B data for an airport")
    parser.add_argument("--airport", default="KSFO", help="ICAO code (default: KSFO)")
    parser.add_argument("--interval", type=int, default=15, help="Seconds between fetches (default: 15)")
    parser.add_argument("--duration", type=int, default=0, help="Total seconds to run, 0=indefinite (default: 0)")
    parser.add_argument("--radius", type=float, default=DEFAULT_RADIUS_DEG, help="Bounding box half-size in degrees (default: 0.5)")
    parser.add_argument("--output-dir", default="data/opensky_raw", help="Output directory (default: data/opensky_raw)")
    parser.add_argument("--lat", type=float, help="Override airport latitude")
    parser.add_argument("--lon", type=float, help="Override airport longitude")
    args = parser.parse_args()

    airport = args.airport.upper()

    # Resolve coordinates
    if args.lat is not None and args.lon is not None:
        lat, lon = args.lat, args.lon
    elif airport in AIRPORT_COORDS:
        lat, lon = AIRPORT_COORDS[airport]
    else:
        logger.error("Unknown airport %s — provide --lat/--lon or add to AIRPORT_COORDS", airport)
        sys.exit(1)

    # Auth from env
    username = os.getenv("OPENSKY_USERNAME")
    password = os.getenv("OPENSKY_PASSWORD")
    auth = (username, password) if username and password else None

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    logger.info("OpenSky Collector starting")
    logger.info("  Airport: %s (%.4f, %.4f), radius=%.2f°", airport, lat, lon, args.radius)
    logger.info("  Interval: %ds, duration: %s", args.interval, f"{args.duration}s" if args.duration else "indefinite")
    logger.info("  Auth: %s", "authenticated" if auth else "anonymous (lower rate limits)")
    logger.info("  Output: %s", output_dir.resolve())

    client = httpx.Client()
    start_time = time.monotonic()
    total_states = 0
    total_fetches = 0
    backoff = 1  # exponential backoff for rate limits

    try:
        while not _shutdown:
            if args.duration and (time.monotonic() - start_time) >= args.duration:
                logger.info("Duration reached (%ds), stopping", args.duration)
                break

            try:
                count = collect_once(client, airport, lat, lon, args.radius, auth, output_dir)
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
        logger.info(
            "Collector stopped. %d fetches, %d total states, %.0fs elapsed",
            total_fetches, total_states, elapsed,
        )
        # List output files
        files = sorted(output_dir.glob(f"{airport}_*.jsonl"))
        if files:
            total_size = sum(f.stat().st_size for f in files)
            logger.info("Output: %d files, %.1f MB in %s", len(files), total_size / 1e6, output_dir)


if __name__ == "__main__":
    main()

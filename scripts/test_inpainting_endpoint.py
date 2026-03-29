"""Test the aircraft inpainting endpoint across all available airports.

Captures before/after satellite tiles, measures latency, and generates
a performance report. Run after deploying the serving endpoint.

Usage:
    uv run python scripts/test_inpainting_endpoint.py [--base-url URL] [--airports N]
"""

import argparse
import asyncio
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

# Esri World Imagery tile URL
ESRI_TILE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"

# Default: the Databricks App URL
DEFAULT_BASE_URL = "https://airport-digital-twin-dev-7474645572615955.aws.databricksapps.com"

OUTPUT_DIR = Path(__file__).parent.parent / "reports" / "inpainting"

DATABRICKS_PROFILE = "FEVM_SERVERLESS_STABLE"


def get_databricks_token(token: str | None = None) -> str:
    """Get a Databricks OAuth token via CLI or explicit value."""
    if token:
        return token
    if tok := os.getenv("DATABRICKS_TOKEN"):
        return tok
    try:
        result = subprocess.run(
            ["databricks", "auth", "token", "--profile", DATABRICKS_PROFILE],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)["access_token"]
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError):
        pass
    raise SystemExit("No auth token: set --token, DATABRICKS_TOKEN, or configure `databricks auth`")


def lat_lon_to_tile(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    """Convert lat/lon to tile x, y at a given zoom level."""
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    lat_rad = math.radians(lat)
    y = int((1 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2 * n)
    return x, y


# Curated terminal coordinates where Esri satellite imagery shows parked aircraft.
# Each verified visually at zoom 17.  Format: IATA -> (terminal_lat, terminal_lon)
TERMINAL_COORDS: dict[str, tuple[float, float]] = {
    "ATL": (33.6407, -84.4277),   # Concourse T — many aircraft
    "FRA": (50.0500, 8.5700),     # Terminal 1 — many aircraft
    "HKG": (22.3107, 113.9159),   # Terminal 1 — several aircraft
    "JFK": (40.6413, -73.7781),   # Terminal 4 — many aircraft
    "LAX": (33.9422, -118.4093),  # TBIT — aircraft visible
    "LHR": (51.4703, -0.4601),    # Terminal 5 — one aircraft
    "NRT": (35.7721, 140.3929),   # Terminal 1 apron — a few aircraft
    "ORD": (41.9742, -87.9073),   # Terminal 5 — many aircraft
    "SFO": (37.6197, -122.3836),  # International Terminal — many aircraft
}


def get_airport_tiles(zoom: int = 17, max_airports: int | None = None, use_curated: bool = True):
    """Get airport tile coordinates for testing.

    With use_curated=True (default), uses TERMINAL_COORDS for airports where we
    know the terminal location. Falls back to AIRPORTS table center coords.
    """
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.ingestion.airport_table import AIRPORTS

    airports = []

    if use_curated:
        # Use curated terminal coordinates first
        for iata, (lat, lon) in sorted(TERMINAL_COORDS.items()):
            icao = AIRPORTS.get(iata, (0, 0, iata, ""))[2]
            tx, ty = lat_lon_to_tile(lat, lon, zoom)
            airports.append({
                "icao": icao, "iata": iata, "name": "",
                "lat": lat, "lon": lon,
                "tile_x": tx, "tile_y": ty, "zoom": zoom,
            })
    else:
        # Use all airports from AIRPORTS table (center coords)
        for iata, (lat, lon, icao, cc) in sorted(AIRPORTS.items()):
            tx, ty = lat_lon_to_tile(lat, lon, zoom)
            airports.append({
                "icao": icao, "iata": iata, "name": "",
                "lat": lat, "lon": lon,
                "tile_x": tx, "tile_y": ty, "zoom": zoom,
            })

    if max_airports:
        airports = airports[:max_airports]
    return airports


async def fetch_original_tile(client: httpx.AsyncClient, zoom: int, x: int, y: int) -> bytes:
    """Fetch the original satellite tile from Esri."""
    url = ESRI_TILE_URL.format(z=zoom, y=y, x=x)
    resp = await client.get(url)
    resp.raise_for_status()
    return resp.content


import base64


DATABRICKS_HOST = "fevm-serverless-stable-3n0ihb.cloud.databricks.com"
SERVING_ENDPOINT_NAME = "airport-dt-aircraft-inpainting-dev"


async def call_inpainting_via_app(
    client: httpx.AsyncClient, base_url: str, tile_url: str, airport_icao: str,
    token: str | None = None,
) -> tuple[bytes | None, dict]:
    """Call inpainting through the Databricks App proxy (clean-tile API)."""
    url = f"{base_url}/api/inpainting/clean-tile"
    params = {"url": tile_url, "airport_icao": airport_icao}
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    t0 = time.monotonic()
    try:
        resp = await client.post(url, params=params, headers=headers, timeout=180)
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        if resp.status_code == 200:
            return resp.content, {
                "status": "ok",
                "latency_ms": elapsed_ms,
                "cache": resp.headers.get("X-Cache", "UNKNOWN"),
                "aircraft_count": int(resp.headers.get("X-Aircraft-Count", "0")),
                "processing_ms": resp.headers.get("X-Processing-Ms", ""),
                "size_bytes": len(resp.content),
            }
        else:
            return None, {
                "status": "error",
                "latency_ms": elapsed_ms,
                "http_status": resp.status_code,
                "detail": resp.text[:200],
            }
    except Exception as e:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return None, {"status": "error", "latency_ms": elapsed_ms, "error": str(e)}


async def call_inpainting_direct(
    client: httpx.AsyncClient, image_bytes: bytes, token: str,
) -> tuple[bytes | None, dict]:
    """Call the Databricks serving endpoint directly (bypass app proxy)."""
    url = f"https://{DATABRICKS_HOST}/serving-endpoints/{SERVING_ENDPOINT_NAME}/invocations"
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    payload = {"dataframe_split": {"columns": ["image_b64"], "data": [[image_b64]]}}

    t0 = time.monotonic()
    try:
        resp = await client.post(
            url, json=payload, timeout=180,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        if resp.status_code != 200:
            return None, {
                "status": "error", "latency_ms": elapsed_ms,
                "http_status": resp.status_code, "detail": resp.text[:300],
            }

        result = resp.json()
        predictions = result.get("predictions", result.get("dataframe_split", {}))
        if isinstance(predictions, dict):
            data = predictions.get("data", [[]])[0]
            clean_b64 = data[0] if data else ""
            aircraft_count = data[1] if len(data) > 1 else 0
        elif isinstance(predictions, list):
            pred = predictions[0]
            clean_b64 = pred.get("clean_image_b64", "")
            aircraft_count = pred.get("aircraft_count", 0)
        else:
            clean_b64 = ""
            aircraft_count = 0

        clean_bytes = base64.b64decode(clean_b64) if clean_b64 else None
        return clean_bytes, {
            "status": "ok",
            "latency_ms": elapsed_ms,
            "cache": "DIRECT",
            "aircraft_count": int(aircraft_count),
            "processing_ms": str(elapsed_ms),
            "size_bytes": len(clean_bytes) if clean_bytes else 0,
        }
    except Exception as e:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return None, {"status": "error", "latency_ms": elapsed_ms, "error": str(e)}


async def test_airport(
    client: httpx.AsyncClient, base_url: str, airport: dict, output_dir: Path,
    token: str | None = None, direct: bool = False,
) -> dict:
    """Test inpainting for a single airport."""
    z, tx, ty = airport["zoom"], airport["tile_x"], airport["tile_y"]
    icao = airport["icao"]
    iata = airport["iata"]

    tile_url = ESRI_TILE_URL.format(z=z, y=ty, x=tx)

    # Fetch original
    try:
        original_bytes = await fetch_original_tile(client, z, tx, ty)
    except Exception as e:
        return {"airport": icao, "iata": iata, "status": "error", "error": f"Tile fetch: {e}"}

    # Call inpainting
    if direct:
        clean_bytes, result = await call_inpainting_direct(client, original_bytes, token)
    else:
        clean_bytes, result = await call_inpainting_via_app(client, base_url, tile_url, icao, token=token)

    # Save before/after
    airport_dir = output_dir / icao.upper()
    airport_dir.mkdir(parents=True, exist_ok=True)

    (airport_dir / f"before_{z}_{tx}_{ty}.png").write_bytes(original_bytes)
    if clean_bytes:
        (airport_dir / f"after_{z}_{tx}_{ty}.png").write_bytes(clean_bytes)

    return {
        "airport": icao,
        "iata": iata,
        "name": airport.get("name", ""),
        "tile": f"{z}/{tx}/{ty}",
        **result,
    }


async def main(base_url: str, max_airports: int | None, zoom: int, concurrency: int,
               token: str | None = None, all_airports: bool = False, direct: bool = False):
    token = get_databricks_token(token)

    airports = get_airport_tiles(zoom=zoom, max_airports=max_airports, use_curated=not all_airports)

    mode = "DIRECT (serving endpoint)" if direct else f"APP ({base_url})"
    print(f"Testing {len(airports)} airports at zoom {zoom}")
    print(f"Mode: {mode}")
    print(f"Auth: Bearer token ({len(token)} chars)")
    print(f"Output: {OUTPUT_DIR}")
    print()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    semaphore = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(timeout=180) as client:
        async def bounded_test(airport):
            async with semaphore:
                return await test_airport(client, base_url, airport, OUTPUT_DIR,
                                          token=token, direct=direct)

        tasks = [bounded_test(a) for a in airports]
        for i, coro in enumerate(asyncio.as_completed(tasks)):
            result = await coro
            results.append(result)
            status = result.get("status", "?")
            cache = result.get("cache", "")
            aircraft = result.get("aircraft_count", "?")
            latency = result.get("latency_ms", "?")
            print(f"  [{i+1}/{len(airports)}] {result['airport']} ({result.get('iata', '')}) "
                  f"— {status} cache={cache} aircraft={aircraft} {latency}ms")

    # Summary
    print("\n" + "=" * 60)
    ok = [r for r in results if r.get("status") == "ok"]
    errors = [r for r in results if r.get("status") != "ok"]
    cache_hits = [r for r in ok if r.get("cache") == "HIT"]
    total_aircraft = sum(r.get("aircraft_count", 0) for r in ok)
    avg_latency = sum(r.get("latency_ms", 0) for r in ok) / len(ok) if ok else 0
    avg_processing = [int(r["processing_ms"]) for r in ok if r.get("processing_ms")]
    avg_proc = sum(avg_processing) / len(avg_processing) if avg_processing else 0

    print(f"Total airports tested: {len(results)}")
    print(f"  OK: {len(ok)}  Errors: {len(errors)}  Cache hits: {len(cache_hits)}")
    print(f"  Total aircraft detected: {total_aircraft}")
    print(f"  Avg latency: {avg_latency:.0f}ms  Avg processing: {avg_proc:.0f}ms")

    if errors:
        print(f"\nErrors:")
        for e in errors[:10]:
            print(f"  {e['airport']}: {e.get('error', e.get('detail', 'unknown'))}")

    # Save report
    report_path = OUTPUT_DIR / "results.json"
    report_path.write_text(json.dumps(results, indent=2))
    print(f"\nResults saved to {report_path}")

    # Generate markdown summary
    md_lines = [
        "# Inpainting Test Results\n",
        f"- **Airports tested:** {len(results)}",
        f"- **Success:** {len(ok)} | **Errors:** {len(errors)} | **Cache hits:** {len(cache_hits)}",
        f"- **Total aircraft detected:** {total_aircraft}",
        f"- **Avg latency:** {avg_latency:.0f}ms | **Avg processing:** {avg_proc:.0f}ms\n",
        "## Per-Airport Results\n",
        "| Airport | IATA | Status | Cache | Aircraft | Latency |",
        "|---------|------|--------|-------|----------|---------|",
    ]
    for r in sorted(results, key=lambda x: x.get("airport", "")):
        md_lines.append(
            f"| {r.get('airport', '')} | {r.get('iata', '')} | {r.get('status', '')} "
            f"| {r.get('cache', '')} | {r.get('aircraft_count', '')} "
            f"| {r.get('latency_ms', '')}ms |"
        )
    md_path = OUTPUT_DIR / "report.md"
    md_path.write_text("\n".join(md_lines))
    print(f"Report saved to {md_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test aircraft inpainting across airports")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="App base URL")
    parser.add_argument("--airports", type=int, default=None, help="Max airports to test (default: all)")
    parser.add_argument("--zoom", type=int, default=16, help="Tile zoom level (default: 16)")
    parser.add_argument("--concurrency", type=int, default=5, help="Parallel requests (default: 5)")
    parser.add_argument("--token", default=None, help="Databricks auth token (default: auto from CLI)")
    parser.add_argument("--all", action="store_true", help="Test all airports (not just curated terminal tiles)")
    parser.add_argument("--direct", action="store_true", help="Call serving endpoint directly (bypass app proxy)")
    args = parser.parse_args()

    asyncio.run(main(args.base_url, args.airports, args.zoom, args.concurrency,
                     token=args.token, all_airports=args.all, direct=args.direct))

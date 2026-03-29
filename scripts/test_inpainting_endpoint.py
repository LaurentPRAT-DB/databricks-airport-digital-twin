"""Test the aircraft inpainting endpoint across all available airports.

Captures before/after satellite tiles, measures latency, and generates
a performance report. Run after deploying the serving endpoint.

Usage:
    uv run python scripts/test_inpainting_endpoint.py [--base-url URL] [--airports N]
"""

import argparse
import asyncio
import base64
import io
import json
import math
import os
import sys
import time
from pathlib import Path

import httpx

# Esri World Imagery tile URL
ESRI_TILE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"

# Default: the Databricks App URL
DEFAULT_BASE_URL = "https://airport-digital-twin-dev-7474645572615955.aws.databricksapps.com"

OUTPUT_DIR = Path(__file__).parent.parent / "reports" / "inpainting"


def lat_lon_to_tile(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    """Convert lat/lon to tile x, y at a given zoom level."""
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    lat_rad = math.radians(lat)
    y = int((1 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2 * n)
    return x, y


def get_airport_center_tiles(profiles_dir: Path, zoom: int = 16, max_airports: int | None = None):
    """Read airport profiles and compute the center tile for each."""
    airports = []
    for f in sorted(profiles_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            lat = data.get("latitude") or data.get("lat")
            lon = data.get("longitude") or data.get("lon")
            icao = data.get("icao_code") or data.get("icao") or f.stem
            if lat and lon:
                tx, ty = lat_lon_to_tile(float(lat), float(lon), zoom)
                airports.append({
                    "icao": icao,
                    "iata": data.get("iata_code") or data.get("iata") or f.stem,
                    "name": data.get("name", ""),
                    "lat": float(lat),
                    "lon": float(lon),
                    "tile_x": tx,
                    "tile_y": ty,
                    "zoom": zoom,
                })
        except (json.JSONDecodeError, ValueError):
            continue

    if max_airports:
        airports = airports[:max_airports]
    return airports


async def fetch_original_tile(client: httpx.AsyncClient, zoom: int, x: int, y: int) -> bytes:
    """Fetch the original satellite tile from Esri."""
    url = ESRI_TILE_URL.format(z=zoom, y=y, x=x)
    resp = await client.get(url)
    resp.raise_for_status()
    return resp.content


async def call_inpainting_endpoint(
    client: httpx.AsyncClient, base_url: str, tile_url: str, airport_icao: str
) -> tuple[bytes | None, dict]:
    """Call the inpainting clean-tile endpoint."""
    url = f"{base_url}/api/inpainting/clean-tile"
    params = {"url": tile_url, "airport_icao": airport_icao}

    t0 = time.monotonic()
    try:
        resp = await client.post(url, params=params, timeout=180)
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


async def test_airport(
    client: httpx.AsyncClient, base_url: str, airport: dict, output_dir: Path
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
    clean_bytes, result = await call_inpainting_endpoint(client, base_url, tile_url, icao)

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


async def main(base_url: str, max_airports: int | None, zoom: int, concurrency: int):
    profiles_dir = Path(__file__).parent.parent / "data" / "calibration" / "profiles"
    airports = get_airport_center_tiles(profiles_dir, zoom=zoom, max_airports=max_airports)

    print(f"Testing {len(airports)} airports at zoom {zoom}")
    print(f"Endpoint: {base_url}")
    print(f"Output: {OUTPUT_DIR}")
    print()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    semaphore = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(timeout=180) as client:
        async def bounded_test(airport):
            async with semaphore:
                return await test_airport(client, base_url, airport, OUTPUT_DIR)

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
    args = parser.parse_args()

    asyncio.run(main(args.base_url, args.airports, args.zoom, args.concurrency))

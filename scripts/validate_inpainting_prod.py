"""Validate inpainting service on PROD: compare before/after tiles, measure detection quality.

Tests all cached airports by:
1. Fetching original satellite tiles from Esri (with aircraft visible)
2. Fetching inpainted tiles from app cache (aircraft removed)
3. Comparing pixel differences to measure inpainting impact
4. Reporting detection rates and cleanup quality

Usage:
    uv run python scripts/validate_inpainting_prod.py
"""

import asyncio
import base64
import io
import json
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

BASE_URL = "https://airport-digital-twin-dev-7474645572615955.aws.databricksapps.com"
ESRI_TILE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
DATABRICKS_PROFILE = "FEVM_SERVERLESS_STABLE"
OUTPUT_DIR = Path(__file__).parent.parent / "reports" / "inpainting_validation"


def get_token() -> str:
    if tok := os.getenv("DATABRICKS_TOKEN"):
        return tok
    result = subprocess.run(
        ["databricks", "auth", "token", "--profile", DATABRICKS_PROFILE],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode == 0:
        return json.loads(result.stdout)["access_token"]
    raise SystemExit("No auth token available")


def lat_lon_to_tile(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    lat_rad = math.radians(lat)
    y = int((1 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2 * n)
    return x, y


@dataclass
class TileResult:
    airport_icao: str
    zoom: int
    tile_x: int
    tile_y: int
    cache_status: str = ""
    aircraft_count: int = 0
    detections: list = field(default_factory=list)
    # Pixel analysis
    original_size: int = 0
    inpainted_size: int = 0
    pixel_diff_mean: float = 0.0
    pixel_diff_max: int = 0
    changed_pixels_pct: float = 0.0
    # Regions where aircraft were removed
    region_analysis: list = field(default_factory=list)
    error: str = ""

    @property
    def has_visible_change(self) -> bool:
        return self.changed_pixels_pct > 0.1

    @property
    def successful_cleanup(self) -> bool:
        """Aircraft detected AND visible pixel changes in detection regions."""
        return self.aircraft_count > 0 and self.has_visible_change


def analyze_pixel_diff(original_bytes: bytes, inpainted_bytes: bytes, detections: list) -> dict:
    """Compare original and inpainted tiles pixel by pixel."""
    orig_img = Image.open(io.BytesIO(original_bytes)).convert("RGB")
    inp_img = Image.open(io.BytesIO(inpainted_bytes)).convert("RGB")

    orig_arr = np.array(orig_img, dtype=np.float32)
    inp_arr = np.array(inp_img, dtype=np.float32)

    # Global diff
    diff = np.abs(orig_arr - inp_arr)
    diff_magnitude = np.sqrt(np.sum(diff ** 2, axis=2))  # per-pixel L2 distance

    # Threshold for "changed" — anything > 5 RGB units L2 distance
    changed_mask = diff_magnitude > 5.0
    changed_pct = np.mean(changed_mask) * 100
    mean_diff = np.mean(diff_magnitude)
    max_diff = int(np.max(diff_magnitude))

    # Analyze detection regions specifically
    region_results = []
    h, w = orig_arr.shape[:2]
    for det in detections:
        if isinstance(det, dict):
            x1 = max(0, det.get("x1", 0))
            y1 = max(0, det.get("y1", 0))
            x2 = min(w, det.get("x2", w))
            y2 = min(h, det.get("y2", h))
        elif isinstance(det, list) and len(det) >= 4:
            x1, y1, x2, y2 = int(det[0]), int(det[1]), int(det[2]), int(det[3])
        else:
            continue

        region_diff = diff_magnitude[y1:y2, x1:x2]
        region_changed = np.mean(region_diff > 5.0) * 100
        region_results.append({
            "bbox": [x1, y1, x2, y2],
            "mean_diff": float(np.mean(region_diff)),
            "changed_pct": float(region_changed),
            "effective_cleanup": region_changed > 20.0,  # >20% pixels changed in bbox = effective
        })

    return {
        "mean_diff": float(mean_diff),
        "max_diff": max_diff,
        "changed_pct": float(changed_pct),
        "region_results": region_results,
    }


# Airport areas to scan — extended grid around terminals
AIRPORT_SCAN_AREAS = {
    "KSFO": {"center": (37.6197, -122.3836), "grid_radius": 4, "zoom": 16},
    # Will discover more from cache
}

# Additional airports to probe
PROBE_AIRPORTS = {
    "EDDF": (50.033, 8.5706),
    "EDDM": (48.354, 11.786),
    "KJFK": (40.6413, -73.7781),
    "KLAX": (33.9422, -118.4093),
    "EGLL": (51.4703, -0.4601),
    "KATL": (33.6407, -84.4277),
    "KORD": (41.9742, -87.9073),
    "RJTT": (35.5533, 139.7811),
    "VHHH": (22.3107, 113.9159),
    "OERK": (24.957, 46.698),
}


async def scan_cached_tiles(
    client: httpx.AsyncClient, headers: dict, icao: str,
    center_lat: float, center_lon: float, zoom: int, radius: int = 4,
) -> list[tuple[int, int, int, bytes, dict]]:
    """Scan a grid around airport center and return cached tiles."""
    cx, cy = lat_lon_to_tile(center_lat, center_lon, zoom)
    cached_tiles = []

    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            tx, ty = cx + dx, cy + dy
            tile_url = ESRI_TILE_URL.format(z=zoom, y=ty, x=tx)
            resp = await client.post(
                f"{BASE_URL}/api/inpainting/clean-tile",
                params={"url": tile_url, "airport_icao": icao, "cache_only": "true"},
                headers=headers,
                timeout=15,
            )
            cache = resp.headers.get("X-Cache", "")
            if cache in ("HIT", "STALE") and len(resp.content) > 100:
                aircraft = int(resp.headers.get("X-Aircraft-Count", "0"))
                det_str = resp.headers.get("X-Detections", "[]")
                try:
                    detections = json.loads(det_str)
                except json.JSONDecodeError:
                    detections = []
                cached_tiles.append((zoom, tx, ty, resp.content, {
                    "aircraft_count": aircraft,
                    "detections": detections,
                    "cache": cache,
                }))

    return cached_tiles


async def validate_tile(
    client: httpx.AsyncClient, zoom: int, tx: int, ty: int,
    inpainted_bytes: bytes, meta: dict, airport_icao: str,
) -> TileResult:
    """Validate a single tile: fetch original, compare."""
    result = TileResult(
        airport_icao=airport_icao, zoom=zoom, tile_x=tx, tile_y=ty,
        cache_status=meta["cache"],
        aircraft_count=meta["aircraft_count"],
        detections=meta["detections"],
        inpainted_size=len(inpainted_bytes),
    )

    # Fetch original from Esri
    tile_url = ESRI_TILE_URL.format(z=zoom, y=ty, x=tx)
    try:
        resp = await client.get(tile_url, timeout=15)
        resp.raise_for_status()
        original_bytes = resp.content
        result.original_size = len(original_bytes)
    except Exception as e:
        result.error = f"Failed to fetch original: {e}"
        return result

    # Pixel-level comparison
    try:
        analysis = analyze_pixel_diff(original_bytes, inpainted_bytes, meta["detections"])
        result.pixel_diff_mean = analysis["mean_diff"]
        result.pixel_diff_max = analysis["max_diff"]
        result.changed_pixels_pct = analysis["changed_pct"]
        result.region_analysis = analysis["region_results"]
    except Exception as e:
        result.error = f"Pixel analysis failed: {e}"

    return result


async def main():
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("INPAINTING SERVICE VALIDATION — PROD")
    print("=" * 70)
    print(f"App: {BASE_URL}")
    print(f"Output: {OUTPUT_DIR}")
    print()

    all_results: list[TileResult] = []

    async with httpx.AsyncClient(timeout=30) as client:
        # Step 1: Check status
        status_resp = await client.get(
            f"{BASE_URL}/api/inpainting/status", headers=headers
        )
        status = status_resp.json()
        print(f"Endpoint: {status.get('endpoint')} — Ready: {status.get('ready')}")
        print(f"Scaled to zero: {status.get('scaled_to_zero')}")
        cache_info = status.get("cache", {})
        print(f"Cache: {cache_info.get('total_tiles', 0)} tiles, "
              f"{cache_info.get('total_aircraft_removed', 0)} aircraft removed, "
              f"{cache_info.get('airports_covered', 0)} airports")
        print()

        # Step 2: Scan known airports for cached tiles
        airports_found = {}

        # Start with KSFO (known to have 29+ tiles cached)
        print("Scanning KSFO (known cached)...")
        ksfo_tiles = await scan_cached_tiles(
            client, headers, "KSFO", 37.6197, -122.3836, zoom=16, radius=4
        )
        if ksfo_tiles:
            airports_found["KSFO"] = ksfo_tiles
            print(f"  Found {len(ksfo_tiles)} cached tiles")

        # Also check KSFO z17
        ksfo_z17 = await scan_cached_tiles(
            client, headers, "KSFO", 37.6197, -122.3836, zoom=17, radius=6
        )
        if ksfo_z17:
            airports_found["KSFO_z17"] = ksfo_z17
            print(f"  Found {len(ksfo_z17)} cached tiles at z17")

        # Probe other airports
        print("Probing other airports...")
        for icao, (lat, lon) in PROBE_AIRPORTS.items():
            for zoom in [16, 17]:
                tiles = await scan_cached_tiles(
                    client, headers, icao, lat, lon, zoom=zoom, radius=3
                )
                if tiles:
                    key = f"{icao}_z{zoom}" if zoom != 16 else icao
                    airports_found[key] = tiles
                    print(f"  {icao} z{zoom}: {len(tiles)} cached tiles")

        total_cached = sum(len(v) for v in airports_found.values())
        print(f"\nTotal cached tiles found: {total_cached}")
        print()

        # Step 3: Validate each cached tile (fetch original, compare)
        print("Validating tiles (fetching originals from Esri, comparing)...")
        print("-" * 70)

        for airport_key, tiles in airports_found.items():
            icao = airport_key.split("_")[0]
            print(f"\n  {airport_key}: {len(tiles)} tiles")

            for zoom, tx, ty, inpainted_bytes, meta in tiles:
                result = await validate_tile(
                    client, zoom, tx, ty, inpainted_bytes, meta, icao
                )
                all_results.append(result)

                # Save before/after images for tiles with detections
                if result.aircraft_count > 0:
                    tile_dir = OUTPUT_DIR / icao / f"z{zoom}"
                    tile_dir.mkdir(parents=True, exist_ok=True)
                    # Save inpainted
                    (tile_dir / f"after_{tx}_{ty}.png").write_bytes(inpainted_bytes)
                    # Save original
                    orig_url = ESRI_TILE_URL.format(z=zoom, y=ty, x=tx)
                    try:
                        orig_resp = await client.get(orig_url, timeout=10)
                        if orig_resp.status_code == 200:
                            (tile_dir / f"before_{tx}_{ty}.png").write_bytes(orig_resp.content)
                    except Exception:
                        pass

            # Print per-airport summary
            airport_results = [r for r in all_results if r.airport_icao == icao]
            with_aircraft = [r for r in airport_results if r.aircraft_count > 0]
            successful = [r for r in airport_results if r.successful_cleanup]
            print(f"    Tiles: {len(airport_results)} | With aircraft: {len(with_aircraft)} "
                  f"| Successful cleanup: {len(successful)}")

    # === REPORT ===
    print("\n" + "=" * 70)
    print("VALIDATION REPORT")
    print("=" * 70)

    total = len(all_results)
    with_detections = [r for r in all_results if r.aircraft_count > 0]
    without_detections = [r for r in all_results if r.aircraft_count == 0]
    successful_cleanups = [r for r in all_results if r.successful_cleanup]
    visible_changes = [r for r in all_results if r.has_visible_change]
    errors = [r for r in all_results if r.error]

    # Detection metrics
    detection_rate = len(with_detections) / total * 100 if total else 0
    cleanup_rate = len(successful_cleanups) / len(with_detections) * 100 if with_detections else 0
    false_positive_rate = len([r for r in without_detections if r.has_visible_change]) / len(without_detections) * 100 if without_detections else 0

    print(f"\n### Summary")
    print(f"  Total tiles validated: {total}")
    print(f"  Tiles with aircraft detected: {len(with_detections)} ({detection_rate:.1f}%)")
    print(f"  Tiles without detections: {len(without_detections)}")
    print(f"  Tiles with visible pixel changes: {len(visible_changes)}")
    print(f"  Errors: {len(errors)}")
    print()
    print(f"### Detection & Cleanup Metrics")
    print(f"  Positive detection rate: {detection_rate:.1f}% ({len(with_detections)}/{total})")
    print(f"  Successful cleanup rate: {cleanup_rate:.1f}% ({len(successful_cleanups)}/{len(with_detections)})")
    print(f"  False positive rate (no detection but pixels changed): {false_positive_rate:.1f}%")
    print()

    # Per-region analysis for tiles with detections
    all_regions = []
    for r in with_detections:
        all_regions.extend(r.region_analysis)

    if all_regions:
        effective = [rg for rg in all_regions if rg.get("effective_cleanup")]
        print(f"### Region-Level Analysis (detection bounding boxes)")
        print(f"  Total detection regions: {len(all_regions)}")
        print(f"  Effectively cleaned (>20% pixels changed in bbox): {len(effective)} ({len(effective)/len(all_regions)*100:.1f}%)")
        avg_region_change = np.mean([rg["changed_pct"] for rg in all_regions])
        print(f"  Average pixel change in detection region: {avg_region_change:.1f}%")
    print()

    # Pixel diff stats for tiles with detections
    if with_detections:
        diffs = [r.pixel_diff_mean for r in with_detections if r.pixel_diff_mean > 0]
        changes = [r.changed_pixels_pct for r in with_detections if r.changed_pixels_pct > 0]
        if diffs:
            print(f"### Pixel Difference Stats (tiles with aircraft)")
            print(f"  Mean pixel diff: {np.mean(diffs):.2f} (L2 RGB distance)")
            print(f"  Max pixel diff: {max(r.pixel_diff_max for r in with_detections)}")
            print(f"  Avg changed pixels: {np.mean(changes):.2f}%")
            print(f"  Min/Max changed pixels: {min(changes):.2f}% / {max(changes):.2f}%")
    print()

    # Per-airport breakdown
    airports = set(r.airport_icao for r in all_results)
    print(f"### Per-Airport Breakdown")
    print(f"{'Airport':<8} {'Tiles':>6} {'w/Aircraft':>11} {'Cleanup OK':>11} {'Avg Δ%':>7}")
    print(f"{'-'*8} {'-'*6} {'-'*11} {'-'*11} {'-'*7}")
    for icao in sorted(airports):
        ar = [r for r in all_results if r.airport_icao == icao]
        wa = [r for r in ar if r.aircraft_count > 0]
        sc = [r for r in ar if r.successful_cleanup]
        avg_change = np.mean([r.changed_pixels_pct for r in wa]) if wa else 0
        print(f"{icao:<8} {len(ar):>6} {len(wa):>11} {len(sc):>11} {avg_change:>6.2f}%")
    print()

    # Tiles with no detection but changes (potential false negatives in reverse)
    unchanged_with_detection = [r for r in with_detections if not r.has_visible_change]
    if unchanged_with_detection:
        print(f"### Potential Issues")
        print(f"  Tiles with detections but NO visible change: {len(unchanged_with_detection)}")
        print(f"  (These might be false positive detections)")
        for r in unchanged_with_detection[:5]:
            print(f"    {r.airport_icao} z{r.zoom}/{r.tile_x}/{r.tile_y}: "
                  f"aircraft={r.aircraft_count} Δ={r.changed_pixels_pct:.3f}%")

    # Save full report
    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "app_url": BASE_URL,
        "summary": {
            "total_tiles": total,
            "tiles_with_aircraft": len(with_detections),
            "tiles_without_aircraft": len(without_detections),
            "successful_cleanups": len(successful_cleanups),
            "detection_rate_pct": round(detection_rate, 1),
            "cleanup_rate_pct": round(cleanup_rate, 1),
            "false_positive_rate_pct": round(false_positive_rate, 1),
            "airports_tested": list(sorted(airports)),
        },
        "tiles": [
            {
                "airport": r.airport_icao,
                "zoom": r.zoom,
                "tile_x": r.tile_x,
                "tile_y": r.tile_y,
                "aircraft_count": r.aircraft_count,
                "pixel_diff_mean": round(r.pixel_diff_mean, 2),
                "changed_pixels_pct": round(r.changed_pixels_pct, 3),
                "successful_cleanup": r.successful_cleanup,
                "detections": r.detections[:5],  # limit for JSON size
                "region_analysis": r.region_analysis,
                "error": r.error,
            }
            for r in all_results
        ],
    }

    report_json = OUTPUT_DIR / "validation_report.json"
    report_json.write_text(json.dumps(report, indent=2, default=str))
    print(f"Full report: {report_json}")

    # Markdown report
    md = generate_markdown_report(report, all_results, all_regions)
    report_md = OUTPUT_DIR / "REPORT.md"
    report_md.write_text(md)
    print(f"Markdown report: {report_md}")

    return report


def generate_markdown_report(report: dict, results: list[TileResult], regions: list) -> str:
    s = report["summary"]
    lines = [
        "# Inpainting Service Validation Report — PROD",
        "",
        f"**Date:** {report['timestamp']}",
        f"**App:** {report['app_url']}",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total tiles validated | {s['total_tiles']} |",
        f"| Tiles with aircraft detected | {s['tiles_with_aircraft']} ({s['detection_rate_pct']}%) |",
        f"| Tiles without detections | {s['tiles_without_aircraft']} |",
        f"| Successful cleanups | {s['successful_cleanups']} ({s['cleanup_rate_pct']}%) |",
        f"| False positive rate | {s['false_positive_rate_pct']}% |",
        f"| Airports tested | {', '.join(s['airports_tested'])} |",
        "",
        "## Detection & Cleanup Quality",
        "",
        f"- **Positive detection rate:** {s['detection_rate_pct']}% — tiles where YOLO found aircraft",
        f"- **Successful cleanup rate:** {s['cleanup_rate_pct']}% — of detected tiles, ones with visible inpainting",
        f"- **False positive rate:** {s['false_positive_rate_pct']}% — tiles with no detection but unexpected changes",
        "",
    ]

    if regions:
        effective = [rg for rg in regions if rg.get("effective_cleanup")]
        lines.extend([
            "## Region-Level Analysis",
            "",
            f"- Total detection bounding boxes: {len(regions)}",
            f"- Effectively cleaned (>20% bbox pixels changed): {len(effective)} ({len(effective)/len(regions)*100:.1f}%)",
            f"- Average pixel change in detection regions: {np.mean([rg['changed_pct'] for rg in regions]):.1f}%",
            "",
        ])

    # Per-airport table
    airports = set(r.airport_icao for r in results)
    lines.extend([
        "## Per-Airport Breakdown",
        "",
        "| Airport | Tiles | With Aircraft | Cleanup OK | Avg Change % |",
        "|---------|-------|---------------|------------|--------------|",
    ])
    for icao in sorted(airports):
        ar = [r for r in results if r.airport_icao == icao]
        wa = [r for r in ar if r.aircraft_count > 0]
        sc = [r for r in ar if r.successful_cleanup]
        avg_c = np.mean([r.changed_pixels_pct for r in wa]) if wa else 0
        lines.append(f"| {icao} | {len(ar)} | {len(wa)} | {len(sc)} | {avg_c:.2f}% |")

    lines.extend([
        "",
        "## Improvement Suggestions",
        "",
        "1. **Lower confidence threshold** — current 0.5 may miss small/distant aircraft.",
        "   Change `confidence_threshold` in `src/ml/inpainting/pipeline.py` from 0.5 to 0.35.",
        "",
        "2. **Increase mask dilation** — tight masks leave edge artifacts.",
        "   Change `mask_dilation_px` from 10 to 15 in pipeline init.",
        "",
        "3. **Add tile overlap** — aircraft split across tile boundaries get missed.",
        "   Fetch 3x3 grid, detect on stitched image, split back to tiles.",
        "",
        "4. **Cache pre-warming** — only 2 airports cached, should cover all active airports.",
        "   Add a scheduled job to pre-warm cache for top airports on deploy.",
        "",
        "5. **Multi-scale detection** — run YOLO at multiple scales (256, 512, 1024) for small aircraft.",
        "   Single-scale misses small aircraft at lower zoom levels.",
        "",
    ])

    return "\n".join(lines)


if __name__ == "__main__":
    result = asyncio.run(main())

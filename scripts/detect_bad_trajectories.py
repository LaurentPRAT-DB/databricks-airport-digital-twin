"""Detect saved simulations with bad trajectory data (tangled position clusters).

Scans simulation JSON files for flights whose position snapshots form dense
clusters (many points in a tiny area), indicating stuck/looping aircraft.
These files need to be re-generated to fix trajectory display.

Usage:
    uv run python scripts/detect_bad_trajectories.py [--dir PATH] [--threshold N] [--delete]
"""

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in nautical miles."""
    R_NM = 3440.065
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R_NM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def analyze_flight_positions(positions: list[dict]) -> dict:
    """Analyze a single flight's position history for trajectory quality.

    Returns metrics about clustering and spread.
    """
    if len(positions) < 10:
        return {"count": len(positions), "bad": False, "reason": "too_few_points"}

    airborne = [p for p in positions if not p.get("on_ground", False) and p.get("altitude", 0) > 200]
    if len(airborne) < 10:
        return {"count": len(positions), "airborne": len(airborne), "bad": False, "reason": "mostly_ground"}

    lats = [p["latitude"] for p in airborne]
    lons = [p["longitude"] for p in airborne]

    lat_range = max(lats) - min(lats)
    lon_range = max(lons) - min(lons)

    center_lat = sum(lats) / len(lats)
    center_lon = sum(lons) / len(lons)
    spread_nm = haversine_nm(min(lats), min(lons), max(lats), max(lons))

    # Detect clustering: many airborne points in a small area
    # A normal approach covers 15-30 NM; a tangled ball is < 5 NM with 50+ points
    points_per_nm = len(airborne) / max(spread_nm, 0.01)

    # Check for looping: count how many times the flight crosses its center
    crossings = 0
    for i in range(1, len(airborne)):
        d_prev = (airborne[i-1]["latitude"] - center_lat) ** 2 + (airborne[i-1]["longitude"] - center_lon) ** 2
        d_curr = (airborne[i]["latitude"] - center_lat) ** 2 + (airborne[i]["longitude"] - center_lon) ** 2
        if (d_prev > 0.0001 and d_curr < 0.0001) or (d_prev < 0.0001 and d_curr > 0.0001):
            crossings += 1

    # Heuristics for "bad" trajectory (visual "tangled ball" on map):
    # 1. Dense cluster: many airborne points packed in < 5 NM (stuck/orbiting in place)
    # 2. Tight loop: moderate area but excessive points (extended holding without diversion)
    # Note: 2s-timestep sims produce ~20 pts/NM on normal approach paths — that's fine.
    # The visual problem is spatial clustering, not just high point count.
    is_bad = False
    reason = "ok"

    if spread_nm < 5.0 and len(airborne) > 80:
        is_bad = True
        reason = f"dense_cluster: {len(airborne)} airborne pts in {spread_nm:.1f} NM"
    elif spread_nm < 8.0 and len(airborne) > 200:
        is_bad = True
        reason = f"tight_loop: {len(airborne)} airborne pts in {spread_nm:.1f} NM"
    elif spread_nm < 10.0 and len(airborne) > 300:
        is_bad = True
        reason = f"extended_hold: {len(airborne)} airborne pts in {spread_nm:.1f} NM"

    return {
        "count": len(positions),
        "airborne": len(airborne),
        "spread_nm": round(spread_nm, 2),
        "points_per_nm": round(points_per_nm, 1),
        "crossings": crossings,
        "lat_range": round(lat_range, 4),
        "lon_range": round(lon_range, 4),
        "bad": is_bad,
        "reason": reason,
    }


def analyze_simulation_file(filepath: Path, verbose: bool = False) -> dict:
    """Analyze a simulation file for bad trajectories.

    Returns summary with list of problematic flights.
    """
    with open(filepath) as f:
        data = json.load(f)

    snapshots = data.get("position_snapshots", [])
    config = data.get("config", {})
    airport = config.get("airport", "unknown")

    # Group snapshots by flight
    flights: dict[str, list[dict]] = defaultdict(list)
    for snap in snapshots:
        icao24 = snap.get("icao24", "")
        if icao24:
            flights[icao24].append(snap)

    bad_flights = []
    total_flights = len(flights)

    for icao24, positions in flights.items():
        result = analyze_flight_positions(positions)
        if result["bad"]:
            callsign = positions[0].get("callsign", "???") if positions else "???"
            bad_flights.append({
                "icao24": icao24,
                "callsign": callsign,
                **result,
            })
            if verbose:
                print(f"    BAD: {callsign} ({icao24}) — {result['reason']}")

    return {
        "file": str(filepath),
        "airport": airport,
        "total_flights": total_flights,
        "bad_flights": len(bad_flights),
        "bad_ratio": round(len(bad_flights) / max(total_flights, 1), 3),
        "details": bad_flights,
    }


def main():
    parser = argparse.ArgumentParser(description="Detect simulations with bad trajectory data")
    parser.add_argument("--dir", type=Path, default=None, help="Directory to scan (default: project root + simulation_output/)")
    parser.add_argument("--threshold", type=int, default=1, help="Min bad flights to flag a file (default: 1)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show per-flight details")
    parser.add_argument("--delete", action="store_true", help="Delete flagged simulation files")
    args = parser.parse_args()

    # Collect simulation files
    sim_files: list[Path] = []

    if args.dir:
        sim_files.extend(sorted(args.dir.glob("simulation_*.json")))
        sim_files.extend(sorted(args.dir.glob("*/simulation_*.json")))
    else:
        sim_files.extend(sorted(PROJECT_ROOT.glob("simulation_output_*.json")))
        sim_output_dir = PROJECT_ROOT / "simulation_output"
        if sim_output_dir.is_dir():
            sim_files.extend(sorted(sim_output_dir.glob("simulation_*.json")))
            sim_files.extend(sorted(sim_output_dir.glob("*/simulation_*.json")))

    if not sim_files:
        print("No simulation files found.")
        return

    print(f"Scanning {len(sim_files)} simulation files...\n")

    flagged = []
    for filepath in sim_files:
        size_mb = filepath.stat().st_size / (1024 * 1024)
        print(f"  {filepath.name} ({size_mb:.1f} MB) ... ", end="", flush=True)

        try:
            result = analyze_simulation_file(filepath, verbose=args.verbose)
        except (json.JSONDecodeError, KeyError) as e:
            print(f"ERROR: {e}")
            continue

        if result["bad_flights"] >= args.threshold:
            pct = result["bad_ratio"] * 100
            print(f"FLAGGED — {result['bad_flights']}/{result['total_flights']} flights bad ({pct:.0f}%)")
            flagged.append(result)
        else:
            print("OK")

    print(f"\n{'='*60}")
    print(f"Results: {len(flagged)}/{len(sim_files)} files have bad trajectories")
    print(f"{'='*60}\n")

    if flagged:
        for r in flagged:
            print(f"  {Path(r['file']).name}")
            print(f"    Airport: {r['airport']}, Bad flights: {r['bad_flights']}/{r['total_flights']}")
            if args.verbose:
                for d in r["details"][:5]:
                    print(f"      {d['callsign']}: {d['reason']}")
            print()

        if args.delete:
            print("Deleting flagged files...")
            for r in flagged:
                p = Path(r["file"])
                p.unlink()
                print(f"  Deleted: {p.name}")
            print(f"\nDeleted {len(flagged)} files. Re-generate with the simulation engine.")
        else:
            print("Run with --delete to remove these files, then re-generate.")
    else:
        print("All simulations look clean!")


if __name__ == "__main__":
    main()

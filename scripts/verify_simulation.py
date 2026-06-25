#!/usr/bin/env python3
"""Run simulation verification across airports and print scorecard.

Usage:
    uv run python scripts/verify_simulation.py
    uv run python scripts/verify_simulation.py --airports SFO,CDG,JFK
    uv run python scripts/verify_simulation.py --tier 1
    uv run python scripts/verify_simulation.py --verbose
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime, timezone

from src.simulation.config import SimulationConfig
from src.simulation.engine import SimulationEngine
from src.simulation.verify import CheckResult, verify_simulation

DEFAULT_AIRPORTS = ["SFO", "JFK", "CDG", "ATL", "LHR", "DXB", "FRA", "AMS", "SIN", "SYD"]


def _reset_state():
    import app.backend.services.airport_config_service as _acs
    _acs._service_instance = None
    import src.ingestion._approach_departure as _ad
    _ad._cached_osm_primary_runway = None
    _ad._osm_primary_runway_resolved = False
    _ad._osm_runway_config_id = None
    _ad._approach_waypoints_cache.clear()
    _ad._bearing_cache.clear()
    import src.ingestion.fallback as _fb
    if hasattr(_fb, '_flight_states'):
        _fb._flight_states.clear()
    if hasattr(_fb, '_gate_states'):
        _fb._gate_states.clear()
    _fb._loaded_gates = None


def _get_all_runway_headings(service) -> list[float]:
    """Extract all unique runway headings from OSM config."""
    import math
    config = service.get_config()
    runways = config.get("osmRunways", [])
    headings = []
    for rwy in runways:
        pts = rwy.get("geoPoints", [])
        if len(pts) >= 2:
            p0, p1 = pts[0], pts[-1]
            dlat = p1["latitude"] - p0["latitude"]
            dlon = (p1["longitude"] - p0["longitude"]) * math.cos(
                math.radians((p0["latitude"] + p1["latitude"]) / 2)
            )
            hdg = (math.degrees(math.atan2(dlon, dlat)) + 360) % 360
            headings.append(hdg)
    return headings if headings else None


def run_airport(iata: str, arrivals: int, departures: int, seed: int):
    """Run sim + verification for one airport."""
    from app.backend.services.airport_config_service import get_airport_config_service

    _reset_state()

    service = get_airport_config_service()

    config = SimulationConfig(
        airport=iata,
        arrivals=arrivals,
        departures=departures,
        duration_hours=2.5,
        time_step_seconds=2.0,
        seed=seed,
        start_time=datetime(2026, 6, 1, 8, 0, 0, tzinfo=timezone.utc),
    )

    engine = SimulationEngine(config)
    recorder = engine.run()

    rwy_headings = _get_all_runway_headings(service)
    num_runways = max(len(rwy_headings), 2) if rwy_headings else 2
    results = verify_simulation(recorder, runway_headings=rwy_headings, num_runways=num_runways)
    return results


def print_scorecard(all_results: dict[str, list[CheckResult]], tier_filter: int | None, verbose: bool):
    print(f"\n{'='*80}")
    print(f"  SIMULATION VERIFICATION SCORECARD")
    print(f"  {len(all_results)} airports | {sum(len(r) for r in all_results.values())} checks")
    print(f"{'='*80}\n")

    # Header
    check_names = []
    if all_results:
        first = next(iter(all_results.values()))
        check_names = [r.name for r in first if tier_filter is None or r.tier == tier_filter]

    # Per-airport results
    for airport, results in sorted(all_results.items()):
        filtered = [r for r in results if tier_filter is None or r.tier == tier_filter]
        pass_count = sum(1 for r in filtered if r.passed)
        total = len(filtered)
        status = "PASS" if pass_count == total else "FAIL"
        tier1_fail = any(not r.passed for r in filtered if r.tier == 1)

        icon = "x" if tier1_fail else ("!" if status == "FAIL" else " ")
        print(f"  [{icon}] {airport:<4} {pass_count}/{total} checks passed")

        if verbose or not all(r.passed for r in filtered):
            for r in filtered:
                if not r.passed or verbose:
                    mark = "FAIL" if not r.passed else "PASS"
                    rate = f" ({r.violation_rate*100:.1f}%)" if r.violations > 0 else ""
                    print(f"       T{r.tier} {mark} {r.name}: {r.violations}/{r.total_checked}{rate}")
                    if not r.passed and r.details:
                        for d in r.details[:3]:
                            print(f"            {d}")

    # Summary
    print(f"\n{'─'*60}")
    total_checks = sum(len(r) for r in all_results.values())
    total_passed = sum(1 for results in all_results.values() for r in results if r.passed)
    tier1_fails = sum(
        1 for results in all_results.values() for r in results
        if r.tier == 1 and not r.passed
    )
    print(f"  Total: {total_passed}/{total_checks} passed | Tier 1 failures: {tier1_fails}")
    print(f"{'='*80}")

    return tier1_fails


def main():
    parser = argparse.ArgumentParser(description="Verify simulation aviation invariants")
    parser.add_argument("--airports", type=str, help="Comma-separated airport list")
    parser.add_argument("--arrivals", type=int, default=15)
    parser.add_argument("--departures", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--tier", type=int, choices=[1, 2, 3], help="Filter to specific tier")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    airports = args.airports.split(",") if args.airports else DEFAULT_AIRPORTS

    print(f"Verifying {len(airports)} airports ({args.arrivals}A/{args.departures}D, seed={args.seed})...")

    all_results: dict[str, list[CheckResult]] = {}
    start = time.time()

    for i, airport in enumerate(airports):
        t0 = time.time()
        try:
            results = run_airport(airport, args.arrivals, args.departures, args.seed)
            all_results[airport] = results
            elapsed = time.time() - t0
            fails = sum(1 for r in results if not r.passed)
            print(f"  [{i+1}/{len(airports)}] {airport}: {len(results)-fails}/{len(results)} pass ({elapsed:.1f}s)")
        except Exception as e:
            print(f"  [{i+1}/{len(airports)}] {airport}: ERROR - {e}", file=sys.stderr)

    elapsed = time.time() - start
    print(f"\nCompleted in {elapsed:.1f}s")

    tier1_fails = print_scorecard(all_results, args.tier, args.verbose)
    return 1 if tier1_fails > 0 else 0


if __name__ == "__main__":
    sys.exit(main())

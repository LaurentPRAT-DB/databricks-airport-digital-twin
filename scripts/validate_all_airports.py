"""Run simulation for all calibrated airports and produce a realism report.

Usage:
    uv run python scripts/validate_all_airports.py
    uv run python scripts/validate_all_airports.py --airports SFO,JFK,ATL
    uv run python scripts/validate_all_airports.py --arrivals 30 --departures 30
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

# Real-world benchmarks for validation
REAL_WORLD_BENCHMARKS = {
    "go_around_rate_pct": {"min": 0.0, "max": 5.0, "typical": 1.5},
    "on_time_pct": {"min": 60.0, "max": 100.0, "typical": 78.0},
    "cancellation_rate_pct": {"min": 0.0, "max": 5.0, "typical": 2.0},
    "avg_turnaround_min": {"min": 25.0, "max": 90.0, "typical": 45.0},
}

ALL_AIRPORTS = [
    "SFO", "JFK", "ATL", "ORD", "LAX", "DFW", "DEN", "SEA", "MIA", "EWR",
    "BOS", "PHX", "LAS", "MCO", "CLT", "MSP", "DTW", "PHL", "IAH", "SAN",
    "PDX", "LHR", "DXB", "NRT", "SIN", "HKG", "CDG", "FRA", "AMS", "SYD",
    "ICN", "GRU", "JNB",
]


def run_single_airport(airport: str, arrivals: int, departures: int, seed: int) -> dict:
    """Run simulation for one airport and return summary metrics."""
    from src.simulation.config import SimulationConfig
    from src.simulation.engine import SimulationEngine
    from src.ingestion.fallback import get_airport_center

    config = SimulationConfig(
        airport=airport,
        arrivals=arrivals,
        departures=departures,
        seed=seed,
        duration_hours=2.0,
        time_step_seconds=3.0,
        skip_positions=True,
    )

    engine = SimulationEngine(config)
    recorder = engine.run()

    if hasattr(config, "model_dump"):
        config_dict = config.model_dump(mode="json")
    else:
        config_dict = config.dict()
    center = get_airport_center()
    config_dict["airport_center"] = {"latitude": center[0], "longitude": center[1]}

    summary = recorder.compute_summary(config_dict)

    # Compute go-around rate
    total_arrivals = summary["arrivals"]
    go_arounds = summary["total_go_arounds"]
    go_around_rate = (go_arounds / total_arrivals * 100) if total_arrivals > 0 else 0.0
    summary["go_around_rate_pct"] = round(go_around_rate, 1)
    summary["diversions"] = summary["total_diversions"]

    return summary


def check_realism(results: dict[str, dict]) -> list[dict]:
    """Check each airport against real-world benchmarks. Return issues."""
    issues = []
    for airport, summary in results.items():
        for metric, bounds in REAL_WORLD_BENCHMARKS.items():
            value = summary.get(metric)
            if value is None:
                continue
            if value < bounds["min"] or value > bounds["max"]:
                issues.append({
                    "airport": airport,
                    "metric": metric,
                    "value": value,
                    "bounds": f"[{bounds['min']}, {bounds['max']}]",
                    "severity": "HIGH" if abs(value - bounds["typical"]) > 2 * (bounds["max"] - bounds["min"]) else "MEDIUM",
                })
    return issues


def print_report(results: dict[str, dict], issues: list[dict], elapsed: float) -> None:
    """Print formatted realism report."""
    print(f"\n{'='*80}")
    print(f"  AIRPORT SIMULATION REALISM REPORT")
    print(f"  {len(results)} airports | elapsed {elapsed:.1f}s")
    print(f"{'='*80}\n")

    # Summary table
    header = f"{'Airport':<6} {'Arr':>4} {'Dep':>4} {'GA%':>5} {'OTP%':>5} {'Canc%':>5} {'Turn':>5} {'Gates':>5} {'Peak':>5}"
    print(header)
    print("-" * len(header))

    for airport, s in sorted(results.items()):
        ga = s.get("go_around_rate_pct", 0)
        flag = " *" if ga > 5.0 else ""
        print(
            f"{airport:<6} {s['arrivals']:>4} {s['departures']:>4} "
            f"{ga:>5.1f}{flag} {s['on_time_pct']:>4.0f}% "
            f"{s['cancellation_rate_pct']:>5.1f} {s['avg_turnaround_min']:>5.1f} "
            f"{s['gate_utilization_gates_used']:>5} {s['peak_simultaneous_flights']:>5}"
        )

    # Aggregate stats
    ga_rates = [s["go_around_rate_pct"] for s in results.values()]
    otp_rates = [s["on_time_pct"] for s in results.values()]
    print(f"\n{'─'*60}")
    print(f"  Go-around rate: mean={sum(ga_rates)/len(ga_rates):.1f}%, "
          f"max={max(ga_rates):.1f}%, median={sorted(ga_rates)[len(ga_rates)//2]:.1f}%")
    print(f"  On-time perf:   mean={sum(otp_rates)/len(otp_rates):.1f}%")

    # Issues
    if issues:
        print(f"\n{'─'*60}")
        print(f"  REALISM ISSUES ({len(issues)}):")
        for issue in sorted(issues, key=lambda x: (x["severity"], x["airport"])):
            print(f"    [{issue['severity']}] {issue['airport']}: {issue['metric']}="
                  f"{issue['value']} (expected {issue['bounds']})")
    else:
        print(f"\n  All metrics within real-world bounds.")

    print(f"\n{'='*80}")


def main():
    parser = argparse.ArgumentParser(description="Validate simulation realism across airports")
    parser.add_argument("--airports", type=str, help="Comma-separated airport list (default: all 33)")
    parser.add_argument("--arrivals", type=int, default=25, help="Arrivals per airport")
    parser.add_argument("--departures", type=int, default=25, help="Departures per airport")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--output", type=str, help="Save results JSON to file")
    args = parser.parse_args()

    airports = args.airports.split(",") if args.airports else ALL_AIRPORTS

    print(f"Running simulation for {len(airports)} airports "
          f"({args.arrivals}A/{args.departures}D each, seed={args.seed})...")

    results = {}
    start = time.time()

    for i, airport in enumerate(airports):
        t0 = time.time()
        try:
            summary = run_single_airport(airport, args.arrivals, args.departures, args.seed)
            results[airport] = summary
            ga = summary["go_around_rate_pct"]
            elapsed = time.time() - t0
            status = "OK" if ga <= 5.0 else "HIGH GA"
            print(f"  [{i+1}/{len(airports)}] {airport}: GA={ga:.1f}% OTP={summary['on_time_pct']:.0f}% "
                  f"({elapsed:.1f}s) [{status}]")
        except Exception as e:
            print(f"  [{i+1}/{len(airports)}] {airport}: FAILED - {e}", file=sys.stderr)
            results[airport] = {"error": str(e)}

    elapsed = time.time() - start
    valid_results = {k: v for k, v in results.items() if "error" not in v}
    issues = check_realism(valid_results)
    print_report(valid_results, issues, elapsed)

    if args.output:
        Path(args.output).write_text(json.dumps(results, indent=2, default=str))
        print(f"\n  Results saved to: {args.output}")

    # Exit code: non-zero if HIGH severity issues
    high_issues = [i for i in issues if i["severity"] == "HIGH"]
    return 1 if high_issues else 0


if __name__ == "__main__":
    sys.exit(main())

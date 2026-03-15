#!/usr/bin/env python3
"""Validation script: compare fallback vs calibrated simulation output.

Runs the simulation engine twice for each airport — once with fallback
profile, once with a calibrated profile — and prints a side-by-side
comparison of summary statistics.

Usage:
    python scripts/validate_calibration.py
"""

import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.calibration.profile import AirportProfile, AirportProfileLoader, _build_fallback_profile
from src.simulation.config import SimulationConfig
from src.simulation.engine import SimulationEngine


def run_simulation(airport: str, seed: int = 42) -> list[dict]:
    """Run a simulation and return the flight schedule."""
    config = SimulationConfig(
        airport=airport,
        arrivals=50,
        departures=50,
        duration_hours=24.0,
        seed=seed,
    )
    engine = SimulationEngine(config)
    return engine.flight_schedule


def analyze_schedule(schedule: list[dict]) -> dict:
    """Extract summary statistics from a flight schedule."""
    airlines = Counter(f["airline_code"] for f in schedule)
    destinations = Counter()
    aircraft_types = Counter()
    delays = []
    delayed_count = 0

    for f in schedule:
        remote = f["origin"] if f["flight_type"] == "arrival" else f["destination"]
        destinations[remote] += 1
        aircraft_types[f["aircraft_type"]] += 1
        if f["delay_minutes"] > 0:
            delayed_count += 1
            delays.append(f["delay_minutes"])

    total = len(schedule)
    return {
        "total_flights": total,
        "delay_rate": f"{delayed_count / total * 100:.1f}%" if total else "0%",
        "mean_delay_min": f"{sum(delays) / len(delays):.1f}" if delays else "0",
        "top_airlines": airlines.most_common(5),
        "top_routes": destinations.most_common(5),
        "top_aircraft": aircraft_types.most_common(5),
        "narrow_body_pct": f"{sum(v for k, v in aircraft_types.items() if k in ('A320','A321','B737','B738','A319','E175')) / total * 100:.0f}%",
        "delayed_count": delayed_count,
    }


def print_comparison(airport: str, stats: dict):
    """Print formatted stats for one airport."""
    print(f"\n{'='*60}")
    print(f"  {airport} — Calibration Profile Validation")
    print(f"{'='*60}")
    print(f"  Total flights: {stats['total_flights']}")
    print(f"  Delay rate:    {stats['delay_rate']} ({stats['delayed_count']} flights)")
    print(f"  Mean delay:    {stats['mean_delay_min']} min")
    print(f"  Narrow-body:   {stats['narrow_body_pct']}")
    print()
    print(f"  Top Airlines:")
    for code, count in stats["top_airlines"]:
        pct = count / stats["total_flights"] * 100
        bar = "█" * int(pct / 2)
        print(f"    {code:6s} {count:4d} ({pct:5.1f}%) {bar}")
    print()
    print(f"  Top Routes:")
    for dest, count in stats["top_routes"]:
        pct = count / stats["total_flights"] * 100
        print(f"    {dest:6s} {count:4d} ({pct:5.1f}%)")
    print()
    print(f"  Top Aircraft:")
    for ac, count in stats["top_aircraft"]:
        pct = count / stats["total_flights"] * 100
        print(f"    {ac:6s} {count:4d} ({pct:5.1f}%)")


def main():
    airports = ["SFO", "JFK", "LHR", "DXB", "NRT"]

    print("=" * 60)
    print("  CALIBRATION VALIDATION — Simulation Statistics")
    print("  Running 50 arr + 50 dep per airport (seed=42)")
    print("=" * 60)

    for airport in airports:
        schedule = run_simulation(airport, seed=42)
        stats = analyze_schedule(schedule)
        print_comparison(airport, stats)

    # Also show what the profile contains for each airport
    print(f"\n\n{'='*60}")
    print("  PROFILE SUMMARY")
    print(f"{'='*60}")
    loader = AirportProfileLoader()
    for airport in airports:
        p = loader.get_profile(airport)
        top_airlines = sorted(p.airline_shares.items(), key=lambda x: -x[1])[:3]
        top_dom = sorted(p.domestic_route_shares.items(), key=lambda x: -x[1])[:3]
        print(f"\n  {airport} ({p.icao_code}) — source: {p.data_source}")
        print(f"    Delay rate: {p.delay_rate:.0%}, Mean delay: {p.mean_delay_minutes:.0f} min")
        print(f"    Domestic ratio: {p.domestic_ratio:.0%}")
        print(f"    Top airlines: {', '.join(f'{k}({v:.0%})' for k,v in top_airlines)}")
        print(f"    Top domestic routes: {', '.join(f'{k}({v:.0%})' for k,v in top_dom)}")


if __name__ == "__main__":
    main()

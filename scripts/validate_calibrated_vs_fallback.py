#!/usr/bin/env python3
"""Compare fallback vs realistic-calibrated profiles side by side.

Creates a realistic SFO profile (approximating real BTS data) and compares
simulation output against the generic fallback profile.
"""

import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.calibration.profile import AirportProfile, AirportProfileLoader, _build_fallback_profile
from src.ingestion.schedule_generator import (
    _select_airline, _select_destination, _select_aircraft, _generate_delay,
)


def build_realistic_sfo_profile() -> AirportProfile:
    """Build a realistic SFO profile approximating real BTS data."""
    return AirportProfile(
        icao_code="KSFO",
        iata_code="SFO",
        airline_shares={
            "UAL": 0.46,  # United hub
            "SWA": 0.12,  # Southwest significant
            "ASA": 0.09,  # Alaska partner
            "DAL": 0.07,
            "AAL": 0.06,
            "JBU": 0.04,
            "BAW": 0.03,
            "ANA": 0.03,
            "CPA": 0.02,
            "UAE": 0.02,
            "KAL": 0.02,  # Korean Air
            "SIA": 0.02,  # Singapore Airlines
            "EVA": 0.02,  # EVA Air
        },
        domestic_route_shares={
            "LAX": 0.15, "ORD": 0.08, "JFK": 0.07, "SEA": 0.07,
            "DEN": 0.06, "BOS": 0.05, "DFW": 0.04, "ATL": 0.04,
            "PHX": 0.04, "LAS": 0.04, "PDX": 0.04, "SAN": 0.03,
            "EWR": 0.03, "IAH": 0.03, "MSP": 0.03, "DTW": 0.02,
            "MIA": 0.02, "CLT": 0.02, "MCO": 0.02, "PHL": 0.02,
        },
        international_route_shares={
            "LHR": 0.12, "NRT": 0.10, "ICN": 0.08, "HKG": 0.08,
            "SIN": 0.06, "SYD": 0.05, "CDG": 0.05, "FRA": 0.05,
            "AMS": 0.04, "DXB": 0.04, "GRU": 0.03, "MEX": 0.05,
            "YVR": 0.08, "PVG": 0.07, "TPE": 0.05, "DEL": 0.05,
        },
        domestic_ratio=0.72,
        fleet_mix={
            "UAL": {"B738": 0.30, "A320": 0.20, "B77W": 0.15, "B789": 0.15, "E175": 0.10, "A319": 0.10},
            "SWA": {"B738": 0.70, "B737": 0.30},
            "ASA": {"B738": 0.40, "E175": 0.35, "B739": 0.25},
            "DAL": {"B738": 0.35, "A321": 0.25, "A320": 0.20, "B739": 0.20},
            "AAL": {"B738": 0.30, "A321": 0.30, "B772": 0.20, "A320": 0.20},
        },
        hourly_profile=[
            0.005, 0.003, 0.002, 0.002, 0.005, 0.015,  # 00-05: red-eye arrivals
            0.055, 0.070, 0.075, 0.065, 0.050, 0.045,   # 06-11: morning peak
            0.040, 0.040, 0.045, 0.050, 0.060, 0.065,   # 12-17: afternoon build
            0.070, 0.065, 0.050, 0.040, 0.025, 0.008,   # 18-23: evening peak then wind-down
        ],
        delay_rate=0.22,  # SFO is fog-prone
        delay_distribution={
            "71": 0.25,  # Weather at departure (fog!)
            "72": 0.10,  # Weather at destination
            "68": 0.20,  # Late inbound aircraft
            "81": 0.18,  # ATC restriction
            "62": 0.10,  # Cleaning/Catering
            "63": 0.07,  # Baggage handling
            "67": 0.05,  # Late crew
            "61": 0.03,  # Cargo/Mail
            "41": 0.02,  # Aircraft defect
        },
        mean_delay_minutes=28.0,  # SFO has higher average delays due to fog
        data_source="simulated_BTS",
        sample_size=180000,
    )


def sample_flights(profile: AirportProfile, n: int = 500, seed: int = 42) -> list[dict]:
    """Generate N flight samples using the given profile."""
    random.seed(seed)
    flights = []
    for _ in range(n):
        code, name = _select_airline(profile=profile)
        dest = _select_destination("departure", code, profile=profile)
        aircraft = _select_aircraft(dest, airline_code=code, profile=profile)
        delay_min, delay_code, delay_reason = _generate_delay(profile=profile)
        flights.append({
            "airline_code": code,
            "destination": dest,
            "aircraft_type": aircraft,
            "delay_minutes": delay_min,
        })
    return flights


def analyze(flights: list[dict]) -> dict:
    airlines = Counter(f["airline_code"] for f in flights)
    dests = Counter(f["destination"] for f in flights)
    aircraft = Counter(f["aircraft_type"] for f in flights)
    delays = [f["delay_minutes"] for f in flights if f["delay_minutes"] > 0]
    n = len(flights)
    return {
        "airlines": airlines.most_common(8),
        "routes": dests.most_common(8),
        "aircraft": aircraft.most_common(8),
        "delay_rate": len(delays) / n * 100,
        "mean_delay": sum(delays) / len(delays) if delays else 0,
        "total": n,
    }


def print_side_by_side(label_a, stats_a, label_b, stats_b):
    """Print two stat blocks side by side."""
    w = 35
    print(f"\n  {'─'*w}  {'─'*w}")
    print(f"  {label_a:^{w}}  {label_b:^{w}}")
    print(f"  {'─'*w}  {'─'*w}")

    # Delay rate
    print(f"  {'Delay rate:':<15} {stats_a['delay_rate']:>5.1f}%{'':<14}  {'Delay rate:':<15} {stats_b['delay_rate']:>5.1f}%")
    print(f"  {'Mean delay:':<15} {stats_a['mean_delay']:>5.1f} min{'':<11}  {'Mean delay:':<15} {stats_b['mean_delay']:>5.1f} min")

    # Airlines
    print(f"\n  {'Airlines':^{w}}  {'Airlines':^{w}}")
    max_rows = max(len(stats_a["airlines"]), len(stats_b["airlines"]))
    for i in range(max_rows):
        left = ""
        if i < len(stats_a["airlines"]):
            code, count = stats_a["airlines"][i]
            pct = count / stats_a["total"] * 100
            bar = "█" * int(pct / 2)
            left = f"  {code:5s} {pct:5.1f}% {bar}"
        right = ""
        if i < len(stats_b["airlines"]):
            code, count = stats_b["airlines"][i]
            pct = count / stats_b["total"] * 100
            bar = "█" * int(pct / 2)
            right = f"  {code:5s} {pct:5.1f}% {bar}"
        print(f"{left:<{w+2}}{right}")

    # Routes
    print(f"\n  {'Top Routes':^{w}}  {'Top Routes':^{w}}")
    max_rows = max(len(stats_a["routes"]), len(stats_b["routes"]))
    for i in range(min(max_rows, 8)):
        left = ""
        if i < len(stats_a["routes"]):
            dest, count = stats_a["routes"][i]
            pct = count / stats_a["total"] * 100
            left = f"  {dest:5s} {pct:5.1f}%"
        right = ""
        if i < len(stats_b["routes"]):
            dest, count = stats_b["routes"][i]
            pct = count / stats_b["total"] * 100
            right = f"  {dest:5s} {pct:5.1f}%"
        print(f"{left:<{w+2}}{right}")

    # Aircraft
    print(f"\n  {'Aircraft':^{w}}  {'Aircraft':^{w}}")
    max_rows = max(len(stats_a["aircraft"]), len(stats_b["aircraft"]))
    for i in range(min(max_rows, 6)):
        left = ""
        if i < len(stats_a["aircraft"]):
            ac, count = stats_a["aircraft"][i]
            pct = count / stats_a["total"] * 100
            left = f"  {ac:5s} {pct:5.1f}%"
        right = ""
        if i < len(stats_b["aircraft"]):
            ac, count = stats_b["aircraft"][i]
            pct = count / stats_b["total"] * 100
            right = f"  {ac:5s} {pct:5.1f}%"
        print(f"{left:<{w+2}}{right}")


def main():
    N = 500

    print("=" * 75)
    print("  CALIBRATION COMPARISON: Fallback vs Realistic SFO Profile")
    print(f"  Sampling {N} flights with seed=42")
    print("=" * 75)

    fallback = _build_fallback_profile("SFO")
    calibrated = build_realistic_sfo_profile()

    flights_fallback = sample_flights(fallback, N)
    flights_calibrated = sample_flights(calibrated, N)

    stats_fallback = analyze(flights_fallback)
    stats_calibrated = analyze(flights_calibrated)

    print_side_by_side(
        "FALLBACK (generic)", stats_fallback,
        "CALIBRATED (realistic SFO)", stats_calibrated,
    )

    print(f"\n{'='*75}")
    print("  KEY DIFFERENCES:")
    print(f"{'='*75}")
    print(f"  - UAL share: {stats_fallback['airlines'][0][1]/N*100:.0f}% → "
          f"{stats_calibrated['airlines'][0][1]/N*100:.0f}% (real SFO is ~46% United)")
    print(f"  - Delay rate: {stats_fallback['delay_rate']:.0f}% → "
          f"{stats_calibrated['delay_rate']:.0f}% (SFO fog-prone, real ~22%)")
    print(f"  - Mean delay: {stats_fallback['mean_delay']:.0f} min → "
          f"{stats_calibrated['mean_delay']:.0f} min (SFO delays longer due to fog)")
    print(f"  - Route diversity: calibrated shows LAX as top route (~15%)")
    print(f"  - Fleet: calibrated has airline-specific fleet mix (SWA=B738 heavy)")
    print()


if __name__ == "__main__":
    main()

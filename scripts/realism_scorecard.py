#!/usr/bin/env python3
"""Realism scorecard — measure how close synthetic output matches real-world profiles.

Runs generate_daily_schedule() multiple times per airport, collects output distributions,
and scores against ground truth (BTS / known profiles) across 7 dimensions.

Usage:
    python scripts/realism_scorecard.py                      # all 33 profiled airports
    python scripts/realism_scorecard.py --airports SFO JFK   # subset
    python scripts/realism_scorecard.py --schedules 5        # fewer runs (faster)
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import Counter
from pathlib import Path

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.calibration.profile import AirportProfileLoader, _icao_to_iata
from src.ingestion.schedule_generator import (
    generate_daily_schedule,
    AIRPORT_COUNTRY,
    COUNTRY_DOMESTIC_AIRPORTS,
    DOMESTIC_AIRPORTS,
)


# ---------------------------------------------------------------------------
# Statistical helpers (pure Python — no scipy)
# ---------------------------------------------------------------------------

def _kl_divergence(p: dict[str, float], q: dict[str, float]) -> float:
    """KL(P || Q) with smoothing.  Keys must be the union of both dicts."""
    eps = 1e-12
    total = 0.0
    for k in p:
        pk = max(p.get(k, 0.0), eps)
        qk = max(q.get(k, 0.0), eps)
        total += pk * math.log2(pk / qk)
    return total


def js_divergence(p: dict[str, float], q: dict[str, float]) -> float:
    """Jensen-Shannon divergence between two distributions.

    Returns a value in [0, 1]: 0 = identical, 1 = maximally different.
    Handles dicts with different key sets by taking their union.
    """
    all_keys = set(p) | set(q)
    if not all_keys:
        return 0.0

    # Normalize both to sum=1
    sp = sum(p.values()) or 1.0
    sq = sum(q.values()) or 1.0
    pn = {k: p.get(k, 0.0) / sp for k in all_keys}
    qn = {k: q.get(k, 0.0) / sq for k in all_keys}

    # M = (P + Q) / 2
    m = {k: (pn[k] + qn[k]) / 2.0 for k in all_keys}
    return ((_kl_divergence(pn, m) + _kl_divergence(qn, m)) / 2.0)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors. Returns value in [0, 1]."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return max(0.0, dot / (mag_a * mag_b))


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------

def score_jsd(jsd: float, threshold: float = 0.2) -> float:
    """Convert JSD to 0-100 score. 0 JSD → 100, ≥threshold → 0."""
    return max(0.0, 100.0 * (1.0 - jsd / threshold))


def score_abs_diff(diff: float, threshold: float = 0.10) -> float:
    """Convert absolute difference to 0-100 score. 0 diff → 100, ≥threshold → 0."""
    return max(0.0, 100.0 * (1.0 - diff / threshold))


def score_cosine(sim: float) -> float:
    """Convert cosine similarity to 0-100 score."""
    return max(0.0, sim * 100.0)


# Dimension weights for overall score
DIMENSION_WEIGHTS = {
    "airline": 0.25,
    "route": 0.20,
    "fleet": 0.15,
    "hourly": 0.15,
    "delay_rate": 0.10,
    "delay_codes": 0.10,
    "domestic_ratio": 0.05,
}


# ---------------------------------------------------------------------------
# Airport scorer
# ---------------------------------------------------------------------------

def score_airport(icao: str, loader: AirportProfileLoader, n_schedules: int = 10) -> dict:
    """Generate schedules, aggregate distributions, compare to profile, return scores."""
    iata = _icao_to_iata(icao)
    profile = loader.get_profile(icao)

    # Generate schedules and collect all flights
    all_flights: list[dict] = []
    for _ in range(n_schedules):
        schedule = generate_daily_schedule(airport=iata, profile=profile)
        all_flights.extend(schedule)

    if not all_flights:
        return {"icao": icao, "iata": iata, "error": "no flights generated", "overall": 0.0}

    n_flights = len(all_flights)

    # --- Extract synthetic distributions ---

    # 1. Airline mix
    airline_counts: Counter[str] = Counter()
    for f in all_flights:
        airline_counts[f["airline_code"]] += 1
    syn_airline = {k: v / n_flights for k, v in airline_counts.items()}

    # 2. Route frequency (destination distribution)
    dest_counts: Counter[str] = Counter()
    for f in all_flights:
        remote = f["origin"] if f["flight_type"] == "arrival" else f["destination"]
        dest_counts[remote] += 1
    syn_routes = {k: v / n_flights for k, v in dest_counts.items()}

    # Build ground truth route distribution (merge domestic + international)
    gt_routes: dict[str, float] = {}
    if profile.domestic_route_shares:
        dom_weight = profile.domestic_ratio
        for k, v in profile.domestic_route_shares.items():
            gt_routes[k] = gt_routes.get(k, 0.0) + v * dom_weight
    if profile.international_route_shares:
        intl_weight = 1.0 - profile.domestic_ratio
        for k, v in profile.international_route_shares.items():
            gt_routes[k] = gt_routes.get(k, 0.0) + v * intl_weight

    # 3. Domestic ratio — classify using country-based lookup.
    #    A flight to a same-country airport is domestic.
    country = AIRPORT_COUNTRY.get(iata)
    if country:
        # Build set of all known domestic IATA codes for this country
        same_country_airports = set(COUNTRY_DOMESTIC_AIRPORTS.get(country, []))
        # Also include US domestic airports if the airport is US
        if country == "US":
            same_country_airports.update(DOMESTIC_AIRPORTS)
        # Also include airports from the profile's domestic_route_shares
        if profile.domestic_route_shares:
            same_country_airports.update(profile.domestic_route_shares.keys())
        domestic_count = 0
        for f in all_flights:
            remote = f["origin"] if f["flight_type"] == "arrival" else f["destination"]
            if remote in same_country_airports:
                domestic_count += 1
    else:
        # US airports or unknown country: use profile's domestic_route_shares
        # or fall back to the DOMESTIC_AIRPORTS list
        domestic_set = set(DOMESTIC_AIRPORTS)
        if profile.domestic_route_shares:
            domestic_set.update(profile.domestic_route_shares.keys())
        domestic_count = 0
        for f in all_flights:
            remote = f["origin"] if f["flight_type"] == "arrival" else f["destination"]
            if remote in domestic_set:
                domestic_count += 1
    syn_domestic_ratio = domestic_count / n_flights if n_flights else 0.5

    # 4. Fleet mix per airline (averaged JSD)
    fleet_jsds: list[float] = []
    for airline_code in profile.fleet_mix:
        gt_fleet = profile.fleet_mix[airline_code]
        # Collect synthetic fleet for this airline
        airline_flights = [f for f in all_flights if f["airline_code"] == airline_code]
        if not airline_flights:
            continue
        ac_counts: Counter[str] = Counter()
        for f in airline_flights:
            ac_counts[f["aircraft_type"]] += 1
        n_af = len(airline_flights)
        syn_fleet = {k: v / n_af for k, v in ac_counts.items()}
        fleet_jsds.append(js_divergence(gt_fleet, syn_fleet))

    avg_fleet_jsd = sum(fleet_jsds) / len(fleet_jsds) if fleet_jsds else 0.2

    # 5. Hourly pattern
    hourly_counts = [0.0] * 24
    for f in all_flights:
        try:
            hour = int(f["scheduled_time"][11:13])
            hourly_counts[hour] += 1
        except (ValueError, IndexError):
            pass
    total_hourly = sum(hourly_counts) or 1.0
    syn_hourly = [c / total_hourly for c in hourly_counts]
    gt_hourly = profile.hourly_profile if len(profile.hourly_profile) == 24 else [1/24]*24

    # 6. Delay rate
    delayed_count = sum(1 for f in all_flights if f["delay_minutes"] > 0)
    syn_delay_rate = delayed_count / n_flights if n_flights else 0.0

    # 7. Delay code distribution
    delay_code_counts: Counter[str] = Counter()
    for f in all_flights:
        if f.get("delay_reason") and f["delay_minutes"] > 0:
            # Map reason back to code via schedule_generator.DELAY_CODES
            code = _reason_to_code(f["delay_reason"])
            if code:
                delay_code_counts[code] += 1
    n_delayed = sum(delay_code_counts.values()) or 1
    syn_delay_codes = {k: v / n_delayed for k, v in delay_code_counts.items()}
    gt_delay_codes = profile.delay_distribution if profile.delay_distribution else {}

    # --- Compute scores ---
    scores = {}
    scores["airline"] = score_jsd(js_divergence(profile.airline_shares, syn_airline))
    scores["route"] = score_jsd(js_divergence(gt_routes, syn_routes)) if gt_routes else 50.0
    scores["fleet"] = score_jsd(avg_fleet_jsd)
    scores["hourly"] = score_cosine(cosine_similarity(gt_hourly, syn_hourly))
    scores["delay_rate"] = score_abs_diff(abs(profile.delay_rate - syn_delay_rate))
    scores["delay_codes"] = score_jsd(js_divergence(gt_delay_codes, syn_delay_codes)) if gt_delay_codes else 50.0
    scores["domestic_ratio"] = score_abs_diff(abs(profile.domestic_ratio - syn_domestic_ratio))

    # Overall weighted average
    overall = sum(scores[dim] * DIMENSION_WEIGHTS[dim] for dim in DIMENSION_WEIGHTS)

    return {
        "icao": icao,
        "iata": iata,
        "scores": scores,
        "overall": overall,
        "n_flights": n_flights,
    }


# Helpers

_INTERNATIONAL_IATAS = {
    "LHR", "CDG", "FRA", "AMS", "HKG", "NRT", "SIN", "SYD", "DXB", "ICN",
    "GRU", "JNB", "CPT", "IST", "MUC", "MEX", "SCL", "TPE", "AUH", "YYZ",
    "YVR", "HND", "MEL", "DUB", "STN", "LGW", "LTN", "FLL",
}


def _reason_to_code(reason: str) -> str | None:
    """Map delay reason string back to IATA delay code."""
    _MAP = {
        "Cargo/Mail": "61",
        "Cleaning/Catering": "62",
        "Baggage handling": "63",
        "Late crew": "67",
        "Late inbound aircraft": "68",
        "Weather at departure": "71",
        "Weather at destination": "72",
        "ATC restriction": "81",
        "Aircraft defect": "41",
    }
    return _MAP.get(reason)


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def print_report(results: list[dict], n_schedules: int) -> None:
    """Print formatted scorecard table."""
    n_airports = len(results)
    print()
    print("=" * 88)
    print(f"  REALISM SCORECARD — {n_airports} airports, {n_schedules} schedules each")
    print("=" * 88)
    header = (
        f"  {'Airport':<9} {'Airline':>7}  {'Route':>5}  {'Fleet':>5}  "
        f"{'Hourly':>6}  {'Delay%':>6}  {'DelayCd':>7}  {'DomRat':>6}  {'OVERALL':>7}"
    )
    print(header)
    print(f"  {'─' * 8}  {'─' * 7}  {'─' * 5}  {'─' * 5}  {'─' * 6}  {'─' * 6}  {'─' * 7}  {'─' * 6}  {'─' * 7}")

    dim_totals: dict[str, float] = {dim: 0.0 for dim in DIMENSION_WEIGHTS}
    overall_total = 0.0

    for r in results:
        if "error" in r:
            print(f"  {r['iata']:<9} ERROR: {r['error']}")
            continue
        s = r["scores"]
        line = (
            f"  {r['iata']:<9} {s['airline']:>7.0f}  {s['route']:>5.0f}  {s['fleet']:>5.0f}  "
            f"{s['hourly']:>6.0f}  {s['delay_rate']:>6.0f}  {s['delay_codes']:>7.0f}  "
            f"{s['domestic_ratio']:>6.0f}  {r['overall']:>7.0f}"
        )
        print(line)
        for dim in DIMENSION_WEIGHTS:
            dim_totals[dim] += s[dim]
        overall_total += r["overall"]

    valid = [r for r in results if "error" not in r]
    n_valid = len(valid) or 1
    print(f"  {'─' * 8}  {'─' * 7}  {'─' * 5}  {'─' * 5}  {'─' * 6}  {'─' * 6}  {'─' * 7}  {'─' * 6}  {'─' * 7}")
    avg_line = (
        f"  {'AVERAGE':<9} {dim_totals['airline']/n_valid:>7.0f}  "
        f"{dim_totals['route']/n_valid:>5.0f}  {dim_totals['fleet']/n_valid:>5.0f}  "
        f"{dim_totals['hourly']/n_valid:>6.0f}  {dim_totals['delay_rate']/n_valid:>6.0f}  "
        f"{dim_totals['delay_codes']/n_valid:>7.0f}  {dim_totals['domestic_ratio']/n_valid:>6.0f}  "
        f"{overall_total/n_valid:>7.0f}"
    )
    print(avg_line)

    # Weakest dimensions
    dim_avgs = {dim: dim_totals[dim] / n_valid for dim in DIMENSION_WEIGHTS}
    ranked = sorted(dim_avgs.items(), key=lambda x: x[1])
    print()
    print("  WEAKEST DIMENSIONS (across all airports):")
    dim_labels = {
        "airline": "Airline mix", "route": "Route frequency", "fleet": "Fleet mix",
        "hourly": "Hourly pattern", "delay_rate": "Delay rate",
        "delay_codes": "Delay code distribution", "domestic_ratio": "Domestic ratio",
    }
    for i, (dim, avg) in enumerate(ranked[:3], 1):
        print(f"  {i}. {dim_labels[dim]} (avg {avg:.0f})")
    print("=" * 88)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Realism scorecard for synthetic flight generation")
    parser.add_argument("--airports", nargs="+", help="IATA codes to score (default: all profiled)")
    parser.add_argument("--schedules", type=int, default=10, help="Number of schedules per airport")
    args = parser.parse_args()

    loader = AirportProfileLoader()
    available = loader.list_available()

    if args.airports:
        # Convert IATA to ICAO if needed
        from src.calibration.profile import _iata_to_icao
        icao_list = [_iata_to_icao(a) for a in args.airports]
    else:
        icao_list = available

    if not icao_list:
        print("No profiled airports found.")
        sys.exit(1)

    print(f"Scoring {len(icao_list)} airports with {args.schedules} schedules each...")

    results: list[dict] = []
    for i, icao in enumerate(icao_list):
        iata = _icao_to_iata(icao)
        print(f"  [{i+1}/{len(icao_list)}] {iata} ({icao})...", end=" ", flush=True)
        result = score_airport(icao, loader, n_schedules=args.schedules)
        overall = result.get("overall", 0)
        print(f"score={overall:.0f}, flights={result.get('n_flights', 0)}")
        results.append(result)

    print_report(results, args.schedules)


if __name__ == "__main__":
    main()

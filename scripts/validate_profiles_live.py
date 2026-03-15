#!/usr/bin/env python3
"""Validate known_profiles against live OpenSky data and OurAirports metadata.

Samples live ADS-B data from OpenSky state vectors (free, no auth needed)
and compares the observed airline mix to our profile distributions. Also
enriches profiles with OurAirports metadata (elevation, runway count, type).

Usage:
    python scripts/validate_profiles_live.py [--samples N] [--airports SFO JFK ...]
"""

import argparse
import json
import logging
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.calibration.known_profiles import get_known_profile
from src.calibration.ourairports_ingest import parse_airports_csv, parse_runways_csv
from src.calibration.profile import _iata_to_icao, _icao_to_iata

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "calibration" / "raw"

# Bounding boxes for OpenSky queries (lat_min, lat_max, lon_min, lon_max)
# Roughly 10-15 nm radius around each airport
AIRPORT_BOXES = {
    "KSFO": (37.53, 37.72, -122.48, -122.28),
    "KJFK": (40.58, 40.72, -73.88, -73.68),
    "KLAX": (33.88, 34.02, -118.48, -118.32),
    "KORD": (41.93, 42.03, -87.98, -87.82),
    "KDFW": (32.84, 32.96, -97.10, -96.94),
    "KATL": (33.58, 33.72, -84.50, -84.36),
    "KDEN": (39.82, 39.92, -104.72, -104.62),
    "KSEA": (47.40, 47.50, -122.36, -122.26),
    "EGLL": (51.43, 51.51, -0.53, -0.39),
    "OMDB": (25.21, 25.31, 55.32, 55.43),
    "RJAA": (35.73, 35.83, 140.33, 140.44),
    "WSSS": (1.33, 1.40, 103.96, 104.02),
    "YSSY": (-33.97, -33.91, 151.15, 151.22),
    "EDDF": (50.01, 50.07, 8.52, 8.60),
    "SBGR": (-23.47, -23.40, -46.50, -46.42),
    "FAOR": (-26.17, -26.10, 28.20, 28.28),
    "RKSI": (37.43, 37.50, 126.42, 126.48),
    "VHHH": (22.28, 22.35, 113.88, 113.95),
    "LFPG": (48.98, 49.04, 2.52, 2.60),
    "EHAM": (52.28, 52.34, 4.72, 4.82),
}

# Callsign prefix → ICAO airline code (expanded)
CALLSIGN_MAP = {
    "UAL": "UAL", "DAL": "DAL", "AAL": "AAL", "SWA": "SWA",
    "ASA": "ASA", "JBU": "JBU", "NKS": "NKS", "SKW": "SKW",
    "RPA": "RPA", "ENY": "ENY", "PDT": "PDT", "PSA": "PSA",
    "EDV": "DAL", "OPT": "DAL",  # Delta Connection
    "BAW": "BAW", "SHT": "BAW",  # BA shuttle
    "DLH": "DLH", "EWG": "DLH",
    "AFR": "AFR", "HOP": "AFR",
    "KLM": "KLM",
    "UAE": "UAE", "FDB": "FDB", "ETD": "ETD",
    "ANA": "ANA", "JAL": "JAL", "JJP": "JJP", "APJ": "APJ",
    "SIA": "SIA", "QFA": "QFA", "QLK": "QFA",
    "CPA": "CPA", "SAA": "SAA",
    "TAM": "TAM", "GLO": "GLO", "AZU": "AZU",
    "RYR": "RYR", "EZY": "EZY", "THY": "THY",
    "CCA": "CCA", "CES": "CES", "CSN": "CSN",
    "KAL": "KAL", "AAR": "AAR", "EVA": "EVA",
    "JST": "JST", "VIR": "VIR", "SVA": "SVA",
}


def sample_opensky(icao: str, box: tuple, samples: int = 3, delay: float = 11.0) -> list[str]:
    """Sample live callsigns near an airport from OpenSky state vectors."""
    callsigns = []
    for i in range(samples):
        url = (f"https://opensky-network.org/api/states/all?"
               f"lamin={box[0]}&lamax={box[1]}&lomin={box[2]}&lomax={box[3]}")
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 AirportDigitalTwin/1.0"
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                states = data.get("states") or []
                for s in states:
                    cs = (s[1] or "").strip()
                    if cs and len(cs) >= 3:
                        callsigns.append(cs)
        except Exception as e:
            logger.debug("OpenSky error for %s sample %d: %s", icao, i + 1, e)
        if i < samples - 1:
            time.sleep(delay)
    return callsigns


def validate_airport(icao: str, callsigns: list[str], profile_airlines: dict) -> dict:
    """Compare observed callsigns to profile airline shares."""
    # Map callsigns to carrier codes
    observed = Counter()
    for cs in callsigns:
        prefix = cs[:3]
        carrier = CALLSIGN_MAP.get(prefix, prefix)
        observed[carrier] += 1

    total_observed = sum(observed.values())
    if total_observed == 0:
        return {"status": "no_data", "observed": 0}

    observed_shares = {k: v / total_observed for k, v in observed.items()}

    # Compare to profile
    matches = 0
    mismatches = []
    for carrier, profile_share in sorted(profile_airlines.items(), key=lambda x: -x[1])[:8]:
        obs_share = observed_shares.get(carrier, 0.0)
        diff = abs(obs_share - profile_share)
        if diff < 0.15:  # Within 15 percentage points
            matches += 1
        else:
            mismatches.append((carrier, profile_share, obs_share))

    return {
        "status": "ok",
        "observed": total_observed,
        "unique_carriers": len(observed),
        "top_observed": observed.most_common(8),
        "matches": matches,
        "mismatches": mismatches,
        "observed_shares": observed_shares,
    }


def main():
    parser = argparse.ArgumentParser(description="Validate profiles against live data")
    parser.add_argument("--samples", type=int, default=2, help="OpenSky samples per airport")
    parser.add_argument("--airports", nargs="+", default=None, help="IATA codes to validate")
    args = parser.parse_args()

    # Load OurAirports data
    airports_csv = RAW_DIR / "airports.csv"
    runways_csv = RAW_DIR / "runways.csv"
    oa_airports = {}
    oa_runways = {}
    if airports_csv.exists():
        oa_airports = parse_airports_csv(airports_csv)
    if runways_csv.exists():
        oa_runways = parse_runways_csv(runways_csv)

    # Determine airports to validate
    if args.airports:
        target_icaos = [_iata_to_icao(a) for a in args.airports]
    else:
        target_icaos = sorted(AIRPORT_BOXES.keys())

    print(f"\n{'='*80}")
    print(f"  PROFILE VALIDATION — Live OpenSky + OurAirports")
    print(f"  {len(target_icaos)} airports, {args.samples} samples each")
    print(f"{'='*80}")

    results = []
    for icao in target_icaos:
        iata = _icao_to_iata(icao)
        profile = get_known_profile(iata)

        # OurAirports metadata
        oa = oa_airports.get(icao, {})
        rw = oa_runways.get(icao, [])
        active_rw = [r for r in rw if not r.get("closed")]

        print(f"\n  {iata} ({icao})")
        if oa:
            print(f"  OurAirports: {oa.get('name', '?')[:50]}")
            print(f"    Country: {oa.get('country')}, Type: {oa.get('type')}, "
                  f"Elev: {oa.get('elevation_ft', 0)}ft, Runways: {len(active_rw)}")

        if not profile:
            print(f"    No known_profile — using fallback")
            results.append({"icao": icao, "status": "no_profile"})
            continue

        print(f"  Profile: source={profile.data_source}, "
              f"airlines={len(profile.airline_shares)}, "
              f"delay_rate={profile.delay_rate:.0%}, "
              f"domestic_ratio={profile.domestic_ratio:.0%}")

        # Sample live data
        box = AIRPORT_BOXES.get(icao)
        if not box:
            print(f"    No bounding box defined")
            results.append({"icao": icao, "status": "no_bbox"})
            continue

        print(f"  Sampling OpenSky ({args.samples}x)...", end="", flush=True)
        callsigns = sample_opensky(icao, box, samples=args.samples)
        print(f" got {len(callsigns)} callsigns")

        result = validate_airport(icao, callsigns, profile.airline_shares)
        result["icao"] = icao
        result["iata"] = iata
        results.append(result)

        if result["status"] == "no_data":
            print(f"    No aircraft observed (off-peak or low coverage)")
        else:
            print(f"    Observed: {result['observed']} flights, {result['unique_carriers']} carriers")
            # Side by side: profile vs observed
            print(f"    {'Carrier':8s} {'Profile':>8s} {'Observed':>8s} {'Match':>6s}")
            print(f"    {'─'*34}")
            profile_top = sorted(profile.airline_shares.items(), key=lambda x: -x[1])[:8]
            for carrier, pshare in profile_top:
                oshare = result["observed_shares"].get(carrier, 0.0)
                match = "ok" if abs(oshare - pshare) < 0.15 else "DIFF"
                print(f"    {carrier:8s} {pshare:>7.0%} {oshare:>7.0%}  {match:>6s}")

        # Rate limit between airports
        if icao != target_icaos[-1]:
            time.sleep(2)

    # Summary
    validated = [r for r in results if r.get("status") == "ok"]
    no_data = [r for r in results if r.get("status") == "no_data"]
    print(f"\n{'='*80}")
    print(f"  SUMMARY")
    print(f"{'='*80}")
    print(f"  Validated with live data: {len(validated)}/{len(results)}")
    print(f"  No data (off-peak/coverage): {len(no_data)}")
    if validated:
        avg_matches = sum(r["matches"] for r in validated) / len(validated)
        print(f"  Average carrier matches (within 15pp): {avg_matches:.1f}/8")
    print()


if __name__ == "__main__":
    main()

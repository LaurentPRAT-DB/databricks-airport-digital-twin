#!/usr/bin/env python3
"""Build airport calibration profiles from downloaded data.

Reads raw BTS/OpenSky/OurAirports data and produces per-airport
AirportProfile JSON files in data/calibration/profiles/.

Usage:
    # Build profiles for all known airports (using available data)
    python scripts/build_airport_profiles.py

    # Build for specific airports
    python scripts/build_airport_profiles.py --airports SFO JFK LHR

    # Enable OpenSky API for international airports
    python scripts/build_airport_profiles.py --opensky --opensky-user USER --opensky-pass PASS

    # Build fallback-only profiles (no external data needed)
    python scripts/build_airport_profiles.py --fallback-only
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.calibration.profile_builder import build_profiles, US_AIRPORTS, INTERNATIONAL_AIRPORTS
from src.calibration.profile import _build_fallback_profile, _PROFILES_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Build airport calibration profiles")
    parser.add_argument(
        "--airports", nargs="+", default=None,
        help="IATA codes to build (default: all known airports)",
    )
    parser.add_argument(
        "--raw-dir", type=Path, default=None,
        help="Directory containing raw CSV files",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=None,
        help="Directory to write profile JSONs",
    )
    parser.add_argument(
        "--opensky", action="store_true",
        help="Query OpenSky API for international airports",
    )
    parser.add_argument("--opensky-user", default=None, help="OpenSky username")
    parser.add_argument("--opensky-pass", default=None, help="OpenSky password")
    parser.add_argument(
        "--fallback-only", action="store_true",
        help="Build fallback profiles only (no external data needed)",
    )
    args = parser.parse_args()

    airports = args.airports or (US_AIRPORTS + INTERNATIONAL_AIRPORTS)
    output_dir = args.output_dir or _PROFILES_DIR

    if args.fallback_only:
        logger.info("Building fallback-only profiles for %d airports", len(airports))
        output_dir.mkdir(parents=True, exist_ok=True)
        for iata in airports:
            profile = _build_fallback_profile(iata)
            path = profile.save(output_dir / f"{profile.icao_code}.json")
            logger.info("  %s → %s", iata, path)
        logger.info("Done. %d fallback profiles written to %s", len(airports), output_dir)
        return

    opensky_auth = None
    if args.opensky and args.opensky_user and args.opensky_pass:
        opensky_auth = (args.opensky_user, args.opensky_pass)

    profiles = build_profiles(
        airports=airports,
        raw_data_dir=args.raw_dir,
        output_dir=output_dir,
        use_opensky=args.opensky,
        opensky_auth=opensky_auth,
    )

    # Summary
    print(f"\n{'='*60}")
    print(f"Built {len(profiles)} airport profiles")
    print(f"{'='*60}")
    for p in profiles:
        print(f"  {p.iata_code} ({p.icao_code}): source={p.data_source}, "
              f"airlines={len(p.airline_shares)}, "
              f"delay_rate={p.delay_rate:.1%}, "
              f"samples={p.sample_size}")
    print(f"\nProfiles saved to: {output_dir}")


if __name__ == "__main__":
    main()

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
from src.ingestion.airport_table import AIRPORTS as ALL_AIRPORTS_TABLE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _persist_to_unity_catalog(profiles: list, args) -> None:
    """Persist profiles to Unity Catalog airport_profiles table."""
    import os

    try:
        from databricks.sdk import WorkspaceClient
    except ImportError:
        logger.error("databricks-sdk not installed — cannot persist to UC")
        return

    from src.calibration.profile import save_batch_to_unity_catalog

    catalog = args.catalog or os.environ.get("DATABRICKS_CATALOG", "serverless_stable_3n0ihb_catalog")
    schema = args.schema or os.environ.get("DATABRICKS_SCHEMA", "airport_digital_twin")
    warehouse_id = args.warehouse_id or os.environ.get("DATABRICKS_WAREHOUSE_ID", "")

    if not warehouse_id:
        logger.error("No warehouse ID — set --warehouse-id or DATABRICKS_WAREHOUSE_ID")
        return

    client = WorkspaceClient()
    save_batch_to_unity_catalog(profiles, client, warehouse_id, catalog, schema)


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
        "--source", choices=["auto", "openflights", "fallback"],
        default="auto",
        help="Data source: auto (priority chain), openflights (routes.dat only), fallback (no external data)",
    )
    parser.add_argument(
        "--all-airports", action="store_true",
        help="Process all ~1,180 airports from airport_table.py (not just the 33 default)",
    )
    parser.add_argument(
        "--fallback-only", action="store_true",
        help="Build fallback profiles only (no external data needed). Deprecated: use --source fallback",
    )
    parser.add_argument(
        "--persist-to-uc", action="store_true",
        help="Persist built profiles to Unity Catalog airport_profiles table",
    )
    parser.add_argument("--catalog", default=None, help="UC catalog name (default: from env or serverless_stable_3n0ihb_catalog)")
    parser.add_argument("--schema", default=None, help="UC schema name (default: airport_digital_twin)")
    parser.add_argument("--warehouse-id", default=None, help="SQL warehouse ID (default: from env DATABRICKS_WAREHOUSE_ID)")
    args = parser.parse_args()

    if args.all_airports:
        airports = args.airports or sorted(ALL_AIRPORTS_TABLE.keys())
    else:
        airports = args.airports or (US_AIRPORTS + INTERNATIONAL_AIRPORTS)
    output_dir = args.output_dir or _PROFILES_DIR

    if args.source == "openflights":
        logger.info("Building OpenFlights-only profiles for %d airports", len(airports))
        output_dir.mkdir(parents=True, exist_ok=True)
        from src.calibration.openflights_ingest import build_profiles_batch
        profiles_dict = build_profiles_batch(airports, download=True)
        built = []
        from datetime import datetime, timezone
        for iata in airports:
            profile = profiles_dict.get(iata)
            if profile is None:
                logger.warning("  %s: no OpenFlights data, using fallback", iata)
                profile = _build_fallback_profile(iata)
            profile.profile_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            profile.save(output_dir / f"{profile.icao_code}.json")
            built.append(profile)
        logger.info("Done. %d profiles written to %s", len(built), output_dir)
        # Summary
        of_count = sum(1 for p in built if p.data_source == "openflights")
        fb_count = len(built) - of_count
        print(f"\n{'='*60}")
        print(f"Built {len(built)} profiles ({of_count} OpenFlights, {fb_count} fallback)")
        print(f"{'='*60}")
        if args.persist_to_uc:
            _persist_to_unity_catalog(built, args)
        return

    if args.fallback_only or args.source == "fallback":
        logger.info("Building fallback-only profiles for %d airports", len(airports))
        output_dir.mkdir(parents=True, exist_ok=True)
        built = []
        for iata in airports:
            profile = _build_fallback_profile(iata)
            path = profile.save(output_dir / f"{profile.icao_code}.json")
            built.append(profile)
            logger.info("  %s → %s", iata, path)
        logger.info("Done. %d fallback profiles written to %s", len(airports), output_dir)
        if args.persist_to_uc:
            _persist_to_unity_catalog(built, args)
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

    if args.persist_to_uc:
        _persist_to_unity_catalog(profiles, args)


if __name__ == "__main__":
    main()

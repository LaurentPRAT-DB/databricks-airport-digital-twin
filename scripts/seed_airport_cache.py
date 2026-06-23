#!/usr/bin/env python3
"""Seed Lakebase airport_config_cache from UC Volume.

Reads pre-computed airport OSM config JSONs from the static_assets Volume
and upserts them into the Lakebase airport_config_cache table.

Usage:
    python scripts/seed_airport_cache.py --profile FEVM_SERVERLESS_STABLE --branch dev
    python scripts/seed_airport_cache.py --profile FEVM_SERVERLESS_STABLE --branch production
    python scripts/seed_airport_cache.py --profile FEVM_SERVERLESS_STABLE --branch dev --force
"""

import argparse
import json
import sys

import psycopg2

WELL_KNOWN_AIRPORTS = [
    "KSFO", "KJFK", "KLAX", "KORD", "KATL", "KDFW", "KDEN", "KMIA", "KSEA",
    "SBGR", "MMMX", "EGLL", "LFPG", "EHAM", "EDDF", "LEMD", "LIRF", "LSGG",
    "LGAV", "OMAA", "OMDB", "RJTT", "VHHH", "WSSS", "ZBAA", "RKSI", "VTBS",
    "FAOR", "GMMN",
]


def main():
    parser = argparse.ArgumentParser(description="Seed Lakebase airport cache from UC Volume")
    parser.add_argument("--profile", required=True, help="Databricks CLI profile")
    parser.add_argument("--branch", required=True, help="Lakebase branch (dev or production)")
    parser.add_argument("--project", default="airport-digital-twin", help="Lakebase project name")
    parser.add_argument("--catalog", default="serverless_stable_3n0ihb_catalog", help="UC catalog")
    parser.add_argument("--schema", default="airport_digital_twin", help="UC schema")
    parser.add_argument("--force", action="store_true", help="Re-seed all airports even if already cached")
    args = parser.parse_args()

    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient(profile=args.profile)
    endpoint = f"projects/{args.project}/branches/{args.branch}/endpoints/primary"

    # Get endpoint host
    ep_info = w.postgres.get_endpoint(endpoint)
    host = ep_info.status.hosts.host
    print(f"Lakebase endpoint: {host} (branch: {args.branch})")

    # Get credentials
    cred = w.postgres.generate_database_credential(endpoint=endpoint)
    me = w.current_user.me()

    conn = psycopg2.connect(
        host=host, port=5432, database="databricks_postgres",
        user=me.user_name, password=cred.token, sslmode="require",
    )

    # Ensure table exists
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS airport_config_cache (
                icao_code VARCHAR(10) PRIMARY KEY,
                config_json JSONB NOT NULL,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        conn.commit()

    # Check existing — only skip if cached entry has osmRunways
    with conn.cursor() as cur:
        cur.execute(
            "SELECT icao_code FROM airport_config_cache "
            "WHERE config_json ? 'osmRunways' AND jsonb_array_length(config_json->'osmRunways') > 0"
        )
        valid_existing = {r[0] for r in cur.fetchall()}

    if args.force:
        to_seed = WELL_KNOWN_AIRPORTS
    else:
        to_seed = [a for a in WELL_KNOWN_AIRPORTS if a not in valid_existing]

    if not to_seed:
        print(f"All {len(WELL_KNOWN_AIRPORTS)} airports already cached. Nothing to do.")
        conn.close()
        return

    print(f"Seeding {len(to_seed)} airports (skipping {len(existing)} already cached)...")

    volume_base = f"/Volumes/{args.catalog}/{args.schema}/static_assets/airport_cache"
    seeded = 0
    failed = 0

    for icao in to_seed:
        volume_path = f"{volume_base}/airport_{icao}.json"
        try:
            resp = w.files.download(volume_path)
            config = json.loads(resp.contents.read())
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO airport_config_cache (icao_code, config_json, updated_at)
                       VALUES (%s, %s, NOW())
                       ON CONFLICT (icao_code) DO UPDATE SET
                           config_json = EXCLUDED.config_json, updated_at = EXCLUDED.updated_at""",
                    (icao, json.dumps(config)),
                )
                conn.commit()
            seeded += 1
            print(f"  {icao}: seeded ({len(json.dumps(config)) // 1024}KB)")
        except Exception as e:
            failed += 1
            print(f"  {icao}: FAILED ({e})")

    conn.close()
    print(f"\nDone: {seeded} seeded, {failed} failed, {len(existing)} already cached")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

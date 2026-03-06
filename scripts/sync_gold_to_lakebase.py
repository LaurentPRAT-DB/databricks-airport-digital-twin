"""Sync Gold Delta table to Lakebase via Databricks SQL + psycopg2.

This script runs locally with Databricks CLI authentication to:
1. Query the Gold Delta table via Databricks SQL
2. Upsert the data to Lakebase PostgreSQL

Usage:
    python scripts/sync_gold_to_lakebase.py --profile FEVM_SERVERLESS_STABLE
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone

import psycopg2
from databricks import sql


def get_databricks_config(profile: str) -> dict:
    """Get Databricks config from CLI profile."""
    # Get auth env for the profile
    result = subprocess.run(
        ["databricks", "auth", "env", "--profile", profile],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to get auth config: {result.stderr}")

    data = json.loads(result.stdout)
    return data.get("env", {})


def get_lakebase_connection(instance_name: str, profile: str, database: str = "airport_digital_twin"):
    """Get a connection to Lakebase using OAuth."""
    # Generate credentials
    result = subprocess.run(
        [
            "databricks", "database", "generate-database-credential",
            "--json", json.dumps({"request_id": "sync", "instance_names": [instance_name]}),
            "--profile", profile,
            "--output", "json",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to get Lakebase credentials: {result.stderr}")

    creds = json.loads(result.stdout)
    token = creds["token"]

    # Get instance info
    result = subprocess.run(
        [
            "databricks", "database", "get-database-instance", instance_name,
            "--profile", profile, "--output", "json",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to get instance info: {result.stderr}")

    instance = json.loads(result.stdout)
    host = instance["read_write_dns"]

    # Get user email
    result = subprocess.run(
        ["databricks", "current-user", "me", "--profile", profile, "--output", "json"],
        capture_output=True,
        text=True,
    )
    user_email = json.loads(result.stdout).get("userName", "user@databricks.com")

    return psycopg2.connect(
        host=host,
        port=5432,
        database=database,
        user=user_email,
        password=token,
        sslmode="require",
    )


def get_delta_connection(profile: str, catalog: str, schema: str):
    """Get Databricks SQL connection."""
    auth = get_databricks_config(profile)
    host = auth.get("DATABRICKS_HOST", "").replace("https://", "")

    # Get warehouse ID
    result = subprocess.run(
        ["databricks", "warehouses", "list", "--profile", profile, "--output", "json"],
        capture_output=True,
        text=True,
    )
    warehouses = json.loads(result.stdout)
    if not warehouses:
        raise RuntimeError("No SQL warehouses found")

    warehouse = warehouses[0]
    http_path = f"/sql/1.0/warehouses/{warehouse['id']}"

    # Get token
    result = subprocess.run(
        ["databricks", "auth", "token", "--profile", profile],
        capture_output=True,
        text=True,
    )
    token_data = result.stdout.strip()
    # Check if it's JSON format
    try:
        token_json = json.loads(token_data)
        token = token_json.get("access_token", token_data)
    except json.JSONDecodeError:
        token = token_data

    return sql.connect(
        server_hostname=host,
        http_path=http_path,
        access_token=token,
        catalog=catalog,
        schema=schema,
    )


def fetch_flights_from_delta(conn, table: str = "flight_status_gold") -> list[dict]:
    """Fetch flights from Delta Gold table."""
    print(f"Fetching flights from {table}...")

    with conn.cursor() as cursor:
        cursor.execute(f"""
            SELECT
                icao24,
                callsign,
                origin_country,
                latitude,
                longitude,
                altitude,
                velocity,
                heading,
                on_ground,
                vertical_rate,
                last_seen,
                flight_phase,
                data_source
            FROM {table}
        """)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()

    flights = [dict(zip(columns, row)) for row in rows]
    print(f"Found {len(flights)} flights in Delta")
    return flights


def sync_to_lakebase(lb_conn, flights: list[dict]) -> int:
    """Upsert flights to Lakebase."""
    if not flights:
        print("No flights to sync")
        return 0

    print(f"Syncing {len(flights)} flights to Lakebase...")

    upsert_sql = """
        INSERT INTO flight_status (
            icao24, callsign, origin_country, latitude, longitude,
            altitude, velocity, heading, on_ground, vertical_rate,
            last_seen, flight_phase, data_source
        ) VALUES (
            %(icao24)s, %(callsign)s, %(origin_country)s, %(latitude)s, %(longitude)s,
            %(altitude)s, %(velocity)s, %(heading)s, %(on_ground)s, %(vertical_rate)s,
            %(last_seen)s, %(flight_phase)s, %(data_source)s
        )
        ON CONFLICT (icao24) DO UPDATE SET
            callsign = EXCLUDED.callsign,
            origin_country = EXCLUDED.origin_country,
            latitude = EXCLUDED.latitude,
            longitude = EXCLUDED.longitude,
            altitude = EXCLUDED.altitude,
            velocity = EXCLUDED.velocity,
            heading = EXCLUDED.heading,
            on_ground = EXCLUDED.on_ground,
            vertical_rate = EXCLUDED.vertical_rate,
            last_seen = EXCLUDED.last_seen,
            flight_phase = EXCLUDED.flight_phase,
            data_source = EXCLUDED.data_source
    """

    synced = 0
    with lb_conn.cursor() as cur:
        for flight in flights:
            cur.execute(upsert_sql, flight)
            synced += 1

    lb_conn.commit()
    print(f"Synced {synced} flights to Lakebase")
    return synced


def main():
    parser = argparse.ArgumentParser(description="Sync Gold Delta table to Lakebase")
    parser.add_argument("--profile", required=True, help="Databricks CLI profile")
    parser.add_argument("--catalog", default="serverless_stable_3n0ihb_catalog")
    parser.add_argument("--schema", default="airport_digital_twin")
    parser.add_argument("--instance", default="airport-digital-twin-db")
    args = parser.parse_args()

    print("=" * 60)
    print("Delta to Lakebase Sync")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    # Connect to Delta
    print("\nConnecting to Databricks SQL...")
    delta_conn = get_delta_connection(args.profile, args.catalog, args.schema)

    # Fetch flights
    flights = fetch_flights_from_delta(delta_conn)
    delta_conn.close()

    if not flights:
        print("No flights found in Delta Gold table")
        return 1

    # Connect to Lakebase
    print("\nConnecting to Lakebase...")
    lb_conn = get_lakebase_connection(args.instance, args.profile)

    # Sync
    synced = sync_to_lakebase(lb_conn, flights)
    lb_conn.close()

    print("\n" + "=" * 60)
    print("Sync complete!")
    print(f"Flights synced: {synced}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())

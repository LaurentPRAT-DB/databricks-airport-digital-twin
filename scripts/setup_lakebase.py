"""Set up Lakebase database schema.

Usage:
    python scripts/setup_lakebase.py --profile FEVM_SERVERLESS_STABLE --instance airport-digital-twin-db
"""

import argparse
import json
import subprocess
import sys

import psycopg2


def get_lakebase_connection(instance_name: str, profile: str, database: str = "postgres"):
    """Get a connection to Lakebase using OAuth."""
    # Generate credentials
    result = subprocess.run(
        [
            "databricks",
            "database",
            "generate-database-credential",
            "--json",
            json.dumps({"request_id": "setup", "instance_names": [instance_name]}),
            "--profile",
            profile,
            "--output",
            "json",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to get credentials: {result.stderr}")

    creds = json.loads(result.stdout)
    token = creds["token"]

    # Get instance info
    result = subprocess.run(
        [
            "databricks",
            "database",
            "get-database-instance",
            instance_name,
            "--profile",
            profile,
            "--output",
            "json",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to get instance info: {result.stderr}")

    instance = json.loads(result.stdout)
    host = instance["read_write_dns"]

    # Get user email from CLI
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


def create_database(conn, db_name: str):
    """Create database if not exists."""
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f"SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
        if not cur.fetchone():
            print(f"Creating database: {db_name}")
            cur.execute(f'CREATE DATABASE "{db_name}"')
            print(f"Database {db_name} created")
        else:
            print(f"Database {db_name} already exists")


def create_schema(conn):
    """Create flight_status table and indexes."""
    schema_sql = """
    -- Flight status table (mirrors Gold layer schema)
    CREATE TABLE IF NOT EXISTS flight_status (
        icao24 VARCHAR(6) PRIMARY KEY,
        callsign VARCHAR(10),
        origin_country VARCHAR(100),
        latitude DOUBLE PRECISION NOT NULL,
        longitude DOUBLE PRECISION NOT NULL,
        altitude DOUBLE PRECISION,
        velocity DOUBLE PRECISION,
        heading DOUBLE PRECISION,
        on_ground BOOLEAN DEFAULT FALSE,
        vertical_rate DOUBLE PRECISION,
        last_seen TIMESTAMP WITH TIME ZONE NOT NULL,
        flight_phase VARCHAR(20) NOT NULL DEFAULT 'unknown',
        data_source VARCHAR(20) NOT NULL DEFAULT 'opensky',
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    -- Index for efficient time-based queries
    CREATE INDEX IF NOT EXISTS idx_flight_status_last_seen
    ON flight_status(last_seen DESC);

    -- Index for flight phase filtering
    CREATE INDEX IF NOT EXISTS idx_flight_status_phase
    ON flight_status(flight_phase);
    """

    with conn.cursor() as cur:
        cur.execute(schema_sql)
    conn.commit()
    print("Schema created successfully")


def insert_sample_data(conn):
    """Insert sample flight data for testing."""
    sample_data = [
        ("a12345", "UAL123", "United States", 37.62, -122.38, 5000.0, 200.0, 270.0, False, 5.0, "climbing"),
        ("b67890", "DAL456", "United States", 37.65, -122.35, 10000.0, 250.0, 180.0, False, 0.0, "cruising"),
        ("c11111", "SWA789", "United States", 37.60, -122.40, 0.0, 15.0, 90.0, True, 0.0, "ground"),
    ]

    with conn.cursor() as cur:
        for icao24, callsign, country, lat, lon, alt, vel, hdg, ground, vr, phase in sample_data:
            cur.execute(
                """
                INSERT INTO flight_status (icao24, callsign, origin_country, latitude, longitude,
                    altitude, velocity, heading, on_ground, vertical_rate, last_seen, flight_phase)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s)
                ON CONFLICT (icao24) DO UPDATE SET
                    callsign = EXCLUDED.callsign,
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude,
                    altitude = EXCLUDED.altitude,
                    velocity = EXCLUDED.velocity,
                    heading = EXCLUDED.heading,
                    on_ground = EXCLUDED.on_ground,
                    vertical_rate = EXCLUDED.vertical_rate,
                    last_seen = NOW(),
                    flight_phase = EXCLUDED.flight_phase
                """,
                (icao24, callsign, country, lat, lon, alt, vel, hdg, ground, vr, phase),
            )
    conn.commit()
    print(f"Inserted {len(sample_data)} sample flights")


def main():
    parser = argparse.ArgumentParser(description="Set up Lakebase schema")
    parser.add_argument("--profile", required=True, help="Databricks CLI profile")
    parser.add_argument("--instance", required=True, help="Lakebase instance name")
    parser.add_argument("--database", default="airport_digital_twin", help="Database name")
    parser.add_argument("--sample-data", action="store_true", help="Insert sample data")
    args = parser.parse_args()

    print(f"Connecting to Lakebase instance: {args.instance}")

    # Create database
    conn = get_lakebase_connection(args.instance, args.profile, "postgres")
    create_database(conn, args.database)
    conn.close()

    # Create schema in the new database
    conn = get_lakebase_connection(args.instance, args.profile, args.database)
    create_schema(conn)

    if args.sample_data:
        insert_sample_data(conn)

    # Verify
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM flight_status")
        count = cur.fetchone()[0]
        print(f"flight_status table has {count} rows")

    conn.close()
    print("Lakebase setup complete!")


if __name__ == "__main__":
    main()

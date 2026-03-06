"""Sync Delta Gold tables to Lakebase PostgreSQL.

This script runs as a Databricks job to keep Lakebase in sync with the
Delta Gold layer for low-latency frontend serving.

Usage:
    # Run locally (requires both Delta and Lakebase credentials)
    python scripts/sync_delta_to_lakebase.py

    # Or via Databricks notebook/job with environment variables set
"""

import os
import sys
import logging
from datetime import datetime, timezone

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def get_delta_connection():
    """Create Databricks SQL connection."""
    from databricks import sql

    return sql.connect(
        server_hostname=os.getenv("DATABRICKS_HOST"),
        http_path=os.getenv("DATABRICKS_HTTP_PATH"),
        access_token=os.getenv("DATABRICKS_TOKEN"),
    )


def get_lakebase_connection():
    """Create Lakebase Autoscaling PostgreSQL connection."""
    import psycopg2

    conn_string = os.getenv("LAKEBASE_CONNECTION_STRING")
    if conn_string:
        return psycopg2.connect(conn_string)

    # Check for direct credentials first
    user = os.getenv("LAKEBASE_USER")
    password = os.getenv("LAKEBASE_PASSWORD")

    # Use OAuth for Lakebase Autoscaling if endpoint is configured
    endpoint_name = os.getenv("LAKEBASE_ENDPOINT_NAME")
    if endpoint_name and not password:
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient()
        cred = w.postgres.generate_database_credential(endpoint=endpoint_name)
        password = cred.token
        user = w.current_user.me().user_name
        logger.info(f"Using OAuth for Lakebase Autoscaling as {user}")

    return psycopg2.connect(
        host=os.getenv("LAKEBASE_HOST"),
        port=os.getenv("LAKEBASE_PORT", "5432"),
        database=os.getenv("LAKEBASE_DATABASE", "databricks_postgres"),
        user=user,
        password=password,
        sslmode="require",
    )


def fetch_from_delta(catalog: str, schema: str) -> list[dict]:
    """Fetch current flight data from Delta Gold table."""
    logger.info(f"Fetching flights from {catalog}.{schema}.flight_status_gold")

    with get_delta_connection() as conn:
        with conn.cursor() as cursor:
            query = f"""
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
                FROM {catalog}.{schema}.flight_status_gold
                WHERE last_seen > CURRENT_TIMESTAMP() - INTERVAL 10 MINUTES
            """
            cursor.execute(query)
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()

    flights = [dict(zip(columns, row)) for row in rows]
    logger.info(f"Fetched {len(flights)} flights from Delta")
    return flights


def upsert_to_lakebase(flights: list[dict]) -> int:
    """Upsert flight data into Lakebase PostgreSQL."""
    if not flights:
        logger.info("No flights to sync")
        return 0

    logger.info(f"Syncing {len(flights)} flights to Lakebase")

    with get_lakebase_connection() as conn:
        with conn.cursor() as cursor:
            upsert_query = """
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

            for flight in flights:
                cursor.execute(upsert_query, flight)

            conn.commit()

    logger.info(f"Successfully synced {len(flights)} flights to Lakebase")
    return len(flights)


def cleanup_stale_data(max_age_minutes: int = 60) -> int:
    """Remove stale flight data from Lakebase."""
    logger.info(f"Cleaning up flights older than {max_age_minutes} minutes")

    with get_lakebase_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM flight_status
                WHERE last_seen < NOW() - INTERVAL '%s minutes'
                """,
                (max_age_minutes,)
            )
            deleted = cursor.rowcount
            conn.commit()

    logger.info(f"Deleted {deleted} stale flight records")
    return deleted


def main():
    """Main sync function."""
    catalog = os.getenv("DATABRICKS_CATALOG", "main")
    schema = os.getenv("DATABRICKS_SCHEMA", "airport_digital_twin")

    logger.info("=" * 60)
    logger.info("Starting Delta → Lakebase sync")
    logger.info(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    logger.info("=" * 60)

    try:
        # Fetch from Delta
        flights = fetch_from_delta(catalog, schema)

        # Upsert to Lakebase
        synced = upsert_to_lakebase(flights)

        # Cleanup stale data
        deleted = cleanup_stale_data(max_age_minutes=60)

        logger.info("=" * 60)
        logger.info("Sync complete")
        logger.info(f"  Flights synced: {synced}")
        logger.info(f"  Stale records deleted: {deleted}")
        logger.info("=" * 60)

        return 0

    except Exception as e:
        logger.error(f"Sync failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""Sync Delta Gold tables to Lakebase PostgreSQL and history table.

Architecture:
- Lakebase: Recent positions only (<10ms latency for UI)
- Unity Catalog Delta: Full history for analytics/ML

This script runs as a Databricks job to:
1. Sync current positions to Lakebase (upsert)
2. Append positions to Delta history table (append-only)

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


def append_to_history(flights: list[dict], catalog: str, schema: str) -> int:
    """Append flight positions to Unity Catalog Delta history table.

    Stores full trajectory history in Delta for:
    - Analytics and reporting
    - ML model training
    - Historical trajectory queries

    Lakebase only stores recent data for fast UI queries.
    """
    if not flights:
        return 0

    table_name = f"{catalog}.{schema}.flight_positions_history"
    logger.info(f"Appending {len(flights)} positions to {table_name}")

    now_dt = datetime.now(timezone.utc)
    now = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    today = now_dt.strftime("%Y-%m-%d")

    with get_delta_connection() as conn:
        with conn.cursor() as cursor:
            # Check if history table exists
            try:
                cursor.execute(f"DESCRIBE TABLE {table_name}")
            except Exception:
                logger.warning(f"{table_name} not found, skipping history append")
                return 0

            # Build VALUES clause for batch insert
            values_list = []
            for f in flights:
                values_list.append(f"""(
                    '{now}',
                    '{today}',
                    '{f.get("icao24", "")}',
                    {repr(f.get("callsign")) if f.get("callsign") else "NULL"},
                    {repr(f.get("origin_country")) if f.get("origin_country") else "NULL"},
                    {f.get("latitude") if f.get("latitude") is not None else "NULL"},
                    {f.get("longitude") if f.get("longitude") is not None else "NULL"},
                    {f.get("altitude") if f.get("altitude") is not None else "NULL"},
                    {f.get("velocity") if f.get("velocity") is not None else "NULL"},
                    {f.get("heading") if f.get("heading") is not None else "NULL"},
                    {f.get("vertical_rate") if f.get("vertical_rate") is not None else "NULL"},
                    {str(f.get("on_ground", False)).lower()},
                    {repr(f.get("flight_phase")) if f.get("flight_phase") else "NULL"},
                    {repr(f.get("data_source")) if f.get("data_source") else "NULL"}
                )""")

            if values_list:
                insert_query = f"""
                    INSERT INTO {table_name} (
                        recorded_at, recorded_date, icao24, callsign, origin_country,
                        latitude, longitude, altitude, velocity, heading,
                        vertical_rate, on_ground, flight_phase, data_source
                    ) VALUES {", ".join(values_list)}
                """
                cursor.execute(insert_query)

    logger.info(f"Appended {len(flights)} positions to Delta history")
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

        # Upsert to Lakebase (latest positions)
        synced = upsert_to_lakebase(flights)

        # Append to Delta history table (trajectory tracking for analytics/ML)
        history_count = append_to_history(flights, catalog, schema)

        # Cleanup stale data from current positions table
        deleted = cleanup_stale_data(max_age_minutes=60)

        logger.info("=" * 60)
        logger.info("Sync complete")
        logger.info(f"  Flights synced: {synced}")
        logger.info(f"  Positions added to history: {history_count}")
        logger.info(f"  Stale records deleted: {deleted}")
        logger.info("=" * 60)

        return 0

    except Exception as e:
        logger.error(f"Sync failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

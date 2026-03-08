"""Sync all data from Lakebase to Unity Catalog.

This script syncs operational data from Lakebase PostgreSQL to Unity Catalog
Delta tables for analytics and ML training.

Architecture:
- Lakebase: Operational data for low-latency UI serving
- Unity Catalog: Historical data for analytics, reporting, and ML

Sync patterns:
- Current state tables (weather, schedule, GSE fleet): MERGE/upsert
- History tables (baggage, turnaround): Append-only for ML training

Usage:
    # Run locally (requires both Lakebase and Delta credentials)
    python scripts/sync_all_to_unity_catalog.py

    # Or via Databricks notebook/job with environment variables set
"""

import os
import sys
import logging
from datetime import datetime, timezone
from typing import Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


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


def get_delta_connection():
    """Create Databricks SQL connection."""
    from databricks import sql

    return sql.connect(
        server_hostname=os.getenv("DATABRICKS_HOST"),
        http_path=os.getenv("DATABRICKS_HTTP_PATH"),
        access_token=os.getenv("DATABRICKS_TOKEN"),
    )


def fetch_weather_from_lakebase() -> list[dict]:
    """Fetch weather observations from Lakebase."""
    import json
    from psycopg2.extras import RealDictCursor

    logger.info("Fetching weather from Lakebase")

    with get_lakebase_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT
                    station, observation_time, wind_direction, wind_speed_kts,
                    wind_gust_kts, visibility_sm, clouds, temperature_c,
                    dewpoint_c, altimeter_inhg, weather, flight_category,
                    raw_metar, taf_text, taf_valid_from, taf_valid_to
                FROM weather_observations
                """
            )
            rows = cursor.fetchall()

    observations = []
    for row in rows:
        obs = dict(row)
        # Convert JSONB to string for Delta
        if obs.get("clouds"):
            obs["clouds"] = json.dumps(obs["clouds"]) if not isinstance(obs["clouds"], str) else obs["clouds"]
        if obs.get("weather"):
            obs["weather"] = json.dumps(obs["weather"]) if not isinstance(obs["weather"], str) else obs["weather"]
        observations.append(obs)

    logger.info(f"Fetched {len(observations)} weather observations from Lakebase")
    return observations


def fetch_schedule_from_lakebase() -> list[dict]:
    """Fetch flight schedule from Lakebase."""
    from psycopg2.extras import RealDictCursor

    logger.info("Fetching schedule from Lakebase")

    with get_lakebase_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT
                    flight_number, airline, airline_code, origin, destination,
                    scheduled_time, estimated_time, actual_time, gate, status,
                    delay_minutes, delay_reason, aircraft_type, flight_type
                FROM flight_schedule
                ORDER BY scheduled_time
                """
            )
            rows = cursor.fetchall()

    flights = [dict(row) for row in rows]
    logger.info(f"Fetched {len(flights)} flights from Lakebase schedule")
    return flights


def fetch_baggage_from_lakebase() -> list[dict]:
    """Fetch baggage status from Lakebase."""
    from psycopg2.extras import RealDictCursor

    logger.info("Fetching baggage status from Lakebase")

    with get_lakebase_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT
                    flight_number, total_bags, checked_in, loaded, unloaded,
                    on_carousel, loading_progress_pct, connecting_bags, misconnects, carousel
                FROM baggage_status
                """
            )
            rows = cursor.fetchall()

    stats = [dict(row) for row in rows]
    logger.info(f"Fetched {len(stats)} baggage stats from Lakebase")
    return stats


def fetch_gse_fleet_from_lakebase() -> list[dict]:
    """Fetch GSE fleet from Lakebase."""
    from psycopg2.extras import RealDictCursor

    logger.info("Fetching GSE fleet from Lakebase")

    with get_lakebase_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT
                    unit_id, gse_type, status, assigned_flight,
                    assigned_gate, position_x, position_y
                FROM gse_fleet
                """
            )
            rows = cursor.fetchall()

    units = [dict(row) for row in rows]
    logger.info(f"Fetched {len(units)} GSE units from Lakebase")
    return units


def fetch_turnaround_from_lakebase() -> list[dict]:
    """Fetch turnaround status from Lakebase."""
    from psycopg2.extras import RealDictCursor

    logger.info("Fetching turnaround status from Lakebase")

    with get_lakebase_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT
                    icao24, flight_number, gate, arrival_time, current_phase,
                    phase_progress_pct, total_progress_pct, estimated_departure, aircraft_type
                FROM gse_turnaround
                """
            )
            rows = cursor.fetchall()

    turnarounds = [dict(row) for row in rows]
    logger.info(f"Fetched {len(turnarounds)} turnarounds from Lakebase")
    return turnarounds


def _quote_value(val) -> str:
    """Safely quote a value for SQL."""
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return str(val).lower()
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, datetime):
        return f"'{val.isoformat()}'"
    # String - escape quotes
    return f"'{str(val).replace(chr(39), chr(39)+chr(39))}'"


def sync_weather_to_delta(observations: list[dict], catalog: str, schema: str) -> int:
    """Sync weather to Unity Catalog Delta table (MERGE)."""
    if not observations:
        return 0

    table_name = f"{catalog}.{schema}.weather_observations_gold"
    logger.info(f"Syncing {len(observations)} weather obs to {table_name}")

    with get_delta_connection() as conn:
        with conn.cursor() as cursor:
            for obs in observations:
                cursor.execute(f"""
                    MERGE INTO {table_name} AS target
                    USING (SELECT {_quote_value(obs.get('station'))} as station) AS source
                    ON target.station = source.station
                    WHEN MATCHED THEN UPDATE SET
                        observation_time = {_quote_value(obs.get('observation_time'))},
                        wind_direction = {_quote_value(obs.get('wind_direction'))},
                        wind_speed_kts = {_quote_value(obs.get('wind_speed_kts'))},
                        wind_gust_kts = {_quote_value(obs.get('wind_gust_kts'))},
                        visibility_sm = {_quote_value(obs.get('visibility_sm'))},
                        clouds = {_quote_value(obs.get('clouds'))},
                        temperature_c = {_quote_value(obs.get('temperature_c'))},
                        dewpoint_c = {_quote_value(obs.get('dewpoint_c'))},
                        altimeter_inhg = {_quote_value(obs.get('altimeter_inhg'))},
                        weather = {_quote_value(obs.get('weather'))},
                        flight_category = {_quote_value(obs.get('flight_category'))},
                        raw_metar = {_quote_value(obs.get('raw_metar'))},
                        taf_text = {_quote_value(obs.get('taf_text'))},
                        taf_valid_from = {_quote_value(obs.get('taf_valid_from'))},
                        taf_valid_to = {_quote_value(obs.get('taf_valid_to'))},
                        synced_at = CURRENT_TIMESTAMP()
                    WHEN NOT MATCHED THEN INSERT (
                        station, observation_time, wind_direction, wind_speed_kts,
                        wind_gust_kts, visibility_sm, clouds, temperature_c,
                        dewpoint_c, altimeter_inhg, weather, flight_category,
                        raw_metar, taf_text, taf_valid_from, taf_valid_to
                    ) VALUES (
                        {_quote_value(obs.get('station'))}, {_quote_value(obs.get('observation_time'))},
                        {_quote_value(obs.get('wind_direction'))}, {_quote_value(obs.get('wind_speed_kts'))},
                        {_quote_value(obs.get('wind_gust_kts'))}, {_quote_value(obs.get('visibility_sm'))},
                        {_quote_value(obs.get('clouds'))}, {_quote_value(obs.get('temperature_c'))},
                        {_quote_value(obs.get('dewpoint_c'))}, {_quote_value(obs.get('altimeter_inhg'))},
                        {_quote_value(obs.get('weather'))}, {_quote_value(obs.get('flight_category'))},
                        {_quote_value(obs.get('raw_metar'))}, {_quote_value(obs.get('taf_text'))},
                        {_quote_value(obs.get('taf_valid_from'))}, {_quote_value(obs.get('taf_valid_to'))}
                    )
                """)

    logger.info(f"Synced {len(observations)} weather observations to Delta")
    return len(observations)


def sync_schedule_to_delta(flights: list[dict], catalog: str, schema: str) -> int:
    """Sync schedule to Unity Catalog Delta table (MERGE)."""
    if not flights:
        return 0

    table_name = f"{catalog}.{schema}.flight_schedule_gold"
    logger.info(f"Syncing {len(flights)} flights to {table_name}")

    with get_delta_connection() as conn:
        with conn.cursor() as cursor:
            for f in flights:
                cursor.execute(f"""
                    MERGE INTO {table_name} AS target
                    USING (SELECT {_quote_value(f.get('flight_number'))} as flight_number,
                                  {_quote_value(f.get('scheduled_time'))} as scheduled_time) AS source
                    ON target.flight_number = source.flight_number
                       AND target.scheduled_time = source.scheduled_time
                    WHEN MATCHED THEN UPDATE SET
                        airline = {_quote_value(f.get('airline'))},
                        airline_code = {_quote_value(f.get('airline_code'))},
                        origin = {_quote_value(f.get('origin'))},
                        destination = {_quote_value(f.get('destination'))},
                        estimated_time = {_quote_value(f.get('estimated_time'))},
                        actual_time = {_quote_value(f.get('actual_time'))},
                        gate = {_quote_value(f.get('gate'))},
                        status = {_quote_value(f.get('status'))},
                        delay_minutes = {_quote_value(f.get('delay_minutes'))},
                        delay_reason = {_quote_value(f.get('delay_reason'))},
                        aircraft_type = {_quote_value(f.get('aircraft_type'))},
                        flight_type = {_quote_value(f.get('flight_type'))},
                        synced_at = CURRENT_TIMESTAMP()
                    WHEN NOT MATCHED THEN INSERT (
                        flight_number, airline, airline_code, origin, destination,
                        scheduled_time, estimated_time, actual_time, gate, status,
                        delay_minutes, delay_reason, aircraft_type, flight_type
                    ) VALUES (
                        {_quote_value(f.get('flight_number'))}, {_quote_value(f.get('airline'))},
                        {_quote_value(f.get('airline_code'))}, {_quote_value(f.get('origin'))},
                        {_quote_value(f.get('destination'))}, {_quote_value(f.get('scheduled_time'))},
                        {_quote_value(f.get('estimated_time'))}, {_quote_value(f.get('actual_time'))},
                        {_quote_value(f.get('gate'))}, {_quote_value(f.get('status'))},
                        {_quote_value(f.get('delay_minutes'))}, {_quote_value(f.get('delay_reason'))},
                        {_quote_value(f.get('aircraft_type'))}, {_quote_value(f.get('flight_type'))}
                    )
                """)

    logger.info(f"Synced {len(flights)} flights to Delta")
    return len(flights)


def append_baggage_history(stats: list[dict], catalog: str, schema: str) -> int:
    """Append baggage stats to history table (append-only for ML)."""
    if not stats:
        return 0

    table_name = f"{catalog}.{schema}.baggage_events_history"
    logger.info(f"Appending {len(stats)} baggage stats to {table_name}")

    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    today = now.strftime("%Y-%m-%d")

    with get_delta_connection() as conn:
        with conn.cursor() as cursor:
            values_list = []
            for s in stats:
                values_list.append(f"""(
                    '{now_str}', '{today}', {_quote_value(s.get('flight_number'))},
                    {_quote_value(s.get('total_bags'))}, {_quote_value(s.get('checked_in'))},
                    {_quote_value(s.get('loaded'))}, {_quote_value(s.get('unloaded'))},
                    {_quote_value(s.get('on_carousel'))}, {_quote_value(s.get('loading_progress_pct'))},
                    {_quote_value(s.get('connecting_bags'))}, {_quote_value(s.get('misconnects'))},
                    {_quote_value(s.get('carousel'))}
                )""")

            if values_list:
                cursor.execute(f"""
                    INSERT INTO {table_name} (
                        recorded_at, recorded_date, flight_number, total_bags, checked_in,
                        loaded, unloaded, on_carousel, loading_progress_pct,
                        connecting_bags, misconnects, carousel
                    ) VALUES {", ".join(values_list)}
                """)

    logger.info(f"Appended {len(stats)} baggage stats to Delta history")
    return len(stats)


def sync_gse_fleet_to_delta(units: list[dict], catalog: str, schema: str) -> int:
    """Sync GSE fleet to Unity Catalog Delta table (MERGE)."""
    if not units:
        return 0

    table_name = f"{catalog}.{schema}.gse_fleet_gold"
    logger.info(f"Syncing {len(units)} GSE units to {table_name}")

    with get_delta_connection() as conn:
        with conn.cursor() as cursor:
            for u in units:
                cursor.execute(f"""
                    MERGE INTO {table_name} AS target
                    USING (SELECT {_quote_value(u.get('unit_id'))} as unit_id) AS source
                    ON target.unit_id = source.unit_id
                    WHEN MATCHED THEN UPDATE SET
                        gse_type = {_quote_value(u.get('gse_type'))},
                        status = {_quote_value(u.get('status'))},
                        assigned_flight = {_quote_value(u.get('assigned_flight'))},
                        assigned_gate = {_quote_value(u.get('assigned_gate'))},
                        position_x = {_quote_value(u.get('position_x'))},
                        position_y = {_quote_value(u.get('position_y'))},
                        synced_at = CURRENT_TIMESTAMP()
                    WHEN NOT MATCHED THEN INSERT (
                        unit_id, gse_type, status, assigned_flight,
                        assigned_gate, position_x, position_y
                    ) VALUES (
                        {_quote_value(u.get('unit_id'))}, {_quote_value(u.get('gse_type'))},
                        {_quote_value(u.get('status'))}, {_quote_value(u.get('assigned_flight'))},
                        {_quote_value(u.get('assigned_gate'))}, {_quote_value(u.get('position_x'))},
                        {_quote_value(u.get('position_y'))}
                    )
                """)

    logger.info(f"Synced {len(units)} GSE units to Delta")
    return len(units)


def append_turnaround_history(turnarounds: list[dict], catalog: str, schema: str) -> int:
    """Append turnaround status to history table (append-only for ML)."""
    if not turnarounds:
        return 0

    table_name = f"{catalog}.{schema}.gse_turnaround_history"
    logger.info(f"Appending {len(turnarounds)} turnarounds to {table_name}")

    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    today = now.strftime("%Y-%m-%d")

    with get_delta_connection() as conn:
        with conn.cursor() as cursor:
            values_list = []
            for t in turnarounds:
                values_list.append(f"""(
                    '{now_str}', '{today}', {_quote_value(t.get('icao24'))},
                    {_quote_value(t.get('flight_number'))}, {_quote_value(t.get('gate'))},
                    {_quote_value(t.get('arrival_time'))}, {_quote_value(t.get('current_phase'))},
                    {_quote_value(t.get('phase_progress_pct'))}, {_quote_value(t.get('total_progress_pct'))},
                    {_quote_value(t.get('estimated_departure'))}, {_quote_value(t.get('aircraft_type'))}
                )""")

            if values_list:
                cursor.execute(f"""
                    INSERT INTO {table_name} (
                        recorded_at, recorded_date, icao24, flight_number, gate,
                        arrival_time, current_phase, phase_progress_pct,
                        total_progress_pct, estimated_departure, aircraft_type
                    ) VALUES {", ".join(values_list)}
                """)

    logger.info(f"Appended {len(turnarounds)} turnarounds to Delta history")
    return len(turnarounds)


def main():
    """Main sync function."""
    catalog = os.getenv("DATABRICKS_CATALOG", "main")
    schema = os.getenv("DATABRICKS_SCHEMA", "airport_digital_twin")

    logger.info("=" * 60)
    logger.info("Starting Lakebase → Unity Catalog sync")
    logger.info(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    logger.info(f"Target: {catalog}.{schema}")
    logger.info("=" * 60)

    results = {
        "weather": 0,
        "schedule": 0,
        "baggage_history": 0,
        "gse_fleet": 0,
        "turnaround_history": 0,
    }

    try:
        # Sync weather (current state)
        weather = fetch_weather_from_lakebase()
        results["weather"] = sync_weather_to_delta(weather, catalog, schema)

        # Sync schedule (current state)
        schedule = fetch_schedule_from_lakebase()
        results["schedule"] = sync_schedule_to_delta(schedule, catalog, schema)

        # Append baggage history (append-only)
        baggage = fetch_baggage_from_lakebase()
        results["baggage_history"] = append_baggage_history(baggage, catalog, schema)

        # Sync GSE fleet (current state)
        gse_fleet = fetch_gse_fleet_from_lakebase()
        results["gse_fleet"] = sync_gse_fleet_to_delta(gse_fleet, catalog, schema)

        # Append turnaround history (append-only)
        turnarounds = fetch_turnaround_from_lakebase()
        results["turnaround_history"] = append_turnaround_history(turnarounds, catalog, schema)

        logger.info("=" * 60)
        logger.info("Sync complete")
        for key, count in results.items():
            logger.info(f"  {key}: {count} records")
        logger.info("=" * 60)

        return 0

    except Exception as e:
        logger.error(f"Sync failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""Setup flight trajectory history tables in Lakebase.

Creates the flight_positions_history table for storing time-series
position data to enable trajectory tracking and ML training.
"""

import os
import sys
import logging

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

    user = os.getenv("LAKEBASE_USER")
    password = os.getenv("LAKEBASE_PASSWORD")

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


def create_history_table():
    """Create the flight_positions_history table."""
    logger.info("Creating flight_positions_history table...")

    with get_lakebase_connection() as conn:
        with conn.cursor() as cursor:
            # Create the history table (append-only, time-series)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS flight_positions_history (
                    id BIGSERIAL PRIMARY KEY,
                    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    icao24 VARCHAR(10) NOT NULL,
                    callsign VARCHAR(20),
                    latitude DOUBLE PRECISION,
                    longitude DOUBLE PRECISION,
                    altitude DOUBLE PRECISION,
                    velocity DOUBLE PRECISION,
                    heading DOUBLE PRECISION,
                    vertical_rate DOUBLE PRECISION,
                    on_ground BOOLEAN DEFAULT FALSE,
                    flight_phase VARCHAR(20),
                    data_source VARCHAR(20)
                )
            """)

            # Create indexes for efficient trajectory queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_history_icao24_time
                ON flight_positions_history (icao24, recorded_at DESC)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_history_time
                ON flight_positions_history (recorded_at DESC)
            """)

            # Create index for callsign lookups
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_history_callsign
                ON flight_positions_history (callsign, recorded_at DESC)
            """)

            conn.commit()

    logger.info("flight_positions_history table created successfully")


def setup_retention_policy():
    """Create a function to clean up old history data.

    By default, keeps 24 hours of data in Lakebase.
    Older data should be archived to Delta Lake for long-term analytics.
    """
    logger.info("Setting up retention policy...")

    with get_lakebase_connection() as conn:
        with conn.cursor() as cursor:
            # Create cleanup function
            cursor.execute("""
                CREATE OR REPLACE FUNCTION cleanup_old_positions(retention_hours INT DEFAULT 24)
                RETURNS INTEGER AS $$
                DECLARE
                    deleted_count INTEGER;
                BEGIN
                    DELETE FROM flight_positions_history
                    WHERE recorded_at < NOW() - (retention_hours || ' hours')::INTERVAL;
                    GET DIAGNOSTICS deleted_count = ROW_COUNT;
                    RETURN deleted_count;
                END;
                $$ LANGUAGE plpgsql
            """)

            conn.commit()

    logger.info("Retention policy function created")


def main():
    """Setup all trajectory tables."""
    logger.info("=" * 60)
    logger.info("Setting up trajectory history tables")
    logger.info("=" * 60)

    try:
        create_history_table()
        setup_retention_policy()

        logger.info("=" * 60)
        logger.info("Setup complete!")
        logger.info("=" * 60)
        return 0

    except Exception as e:
        logger.error(f"Setup failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

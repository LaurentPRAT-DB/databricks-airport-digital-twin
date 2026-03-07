"""Setup flight trajectory history table in Unity Catalog.

Creates the flight_positions_history Delta table for storing time-series
position data for analytics and ML training.

Lakebase stores only recent data for fast UI queries.
Unity Catalog stores full history for analytics and ML.
"""

import os
import sys
import logging

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


def create_history_table(catalog: str, schema: str):
    """Create the flight_positions_history Delta table in Unity Catalog."""
    table_name = f"{catalog}.{schema}.flight_positions_history"
    logger.info(f"Creating {table_name} table...")

    with get_delta_connection() as conn:
        with conn.cursor() as cursor:
            # Create the history table (append-only, time-series)
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    recorded_at TIMESTAMP NOT NULL,
                    icao24 STRING NOT NULL,
                    callsign STRING,
                    origin_country STRING,
                    latitude DOUBLE,
                    longitude DOUBLE,
                    altitude DOUBLE,
                    velocity DOUBLE,
                    heading DOUBLE,
                    vertical_rate DOUBLE,
                    on_ground BOOLEAN,
                    flight_phase STRING,
                    data_source STRING
                )
                USING DELTA
                PARTITIONED BY (DATE(recorded_at))
                COMMENT 'Flight position history for trajectory analysis and ML training'
            """)

            # Optimize for time-series queries
            cursor.execute(f"""
                ALTER TABLE {table_name}
                SET TBLPROPERTIES (
                    'delta.autoOptimize.optimizeWrite' = 'true',
                    'delta.autoOptimize.autoCompact' = 'true'
                )
            """)

    logger.info(f"{table_name} table created successfully")


def main():
    """Setup trajectory history table in Unity Catalog."""
    catalog = os.getenv("DATABRICKS_CATALOG", "main")
    schema = os.getenv("DATABRICKS_SCHEMA", "airport_digital_twin")

    logger.info("=" * 60)
    logger.info("Setting up trajectory history table in Unity Catalog")
    logger.info(f"Target: {catalog}.{schema}.flight_positions_history")
    logger.info("=" * 60)

    try:
        create_history_table(catalog, schema)

        logger.info("=" * 60)
        logger.info("Setup complete!")
        logger.info("=" * 60)
        return 0

    except Exception as e:
        logger.error(f"Setup failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

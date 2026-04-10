"""Bronze layer DLT pipeline for flight data.

Reads from the Delta table synced from Lakebase by the lakebase_to_delta_sync job.
The sync job writes flight_status_gold from Lakebase PostgreSQL to Delta.
"""

import dlt
from pyspark.sql import functions as F

from src.pipelines import FLIGHTS_BRONZE, LAKEBASE_FLIGHT_STATUS


@dlt.table(
    name=FLIGHTS_BRONZE,
    comment="Flight data from Lakebase sync (Delta table)",
    table_properties={
        "quality": "bronze",
        "pipelines.autoOptimize.managed": "true",
        "delta.autoOptimize.optimizeWrite": "true",
    },
)
def flights_bronze():
    """Read flight data from the synced Delta table.

    The lakebase_to_delta_sync job writes flight_status_gold from Lakebase.
    This bronze layer reads that table and adds ingestion metadata.

    Returns:
        DataFrame: Flight data with metadata columns
    """
    return (
        spark.read.table(LAKEBASE_FLIGHT_STATUS)
        .withColumn("_ingested_at", F.current_timestamp())
        .withColumn("_source_file", F.lit("lakebase_sync"))
    )

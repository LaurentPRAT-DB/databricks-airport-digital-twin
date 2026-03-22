"""Bronze layer DLT pipeline for baggage data.

Reads from the Delta table synced from Lakebase by the lakebase_to_delta_sync job.
The sync job writes baggage_status_gold from Lakebase PostgreSQL to Delta.
"""

import dlt
from pyspark.sql import functions as F


@dlt.table(
    name="baggage_events_bronze",
    comment="Baggage data from Lakebase sync (Delta table)",
    table_properties={
        "quality": "bronze",
        "pipelines.autoOptimize.managed": "true",
        "delta.autoOptimize.optimizeWrite": "true",
    },
)
def baggage_events_bronze():
    """Read baggage data from the synced Delta table.

    The lakebase_to_delta_sync job writes baggage_status_gold from Lakebase.
    This bronze layer reads that table and adds ingestion metadata.

    Returns:
        DataFrame: Baggage data with metadata columns
    """
    return (
        spark.read.table("serverless_stable_3n0ihb_catalog.airport_digital_twin.baggage_status_gold")
        .withColumn("_ingested_at", F.current_timestamp())
        .withColumn("_source_file", F.lit("lakebase_sync"))
    )

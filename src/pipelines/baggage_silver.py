"""Silver layer DLT pipeline for cleaned and validated baggage events.

This module defines the Silver layer table that applies data quality
expectations and transformations to the raw Bronze layer baggage data.
"""

import dlt
from pyspark.sql import functions as F


@dlt.table(
    name="baggage_events_silver",
    comment="Cleaned and validated baggage events",
    table_properties={
        "quality": "silver",
        "pipelines.autoOptimize.managed": "true",
        "delta.autoOptimize.optimizeWrite": "true",
    },
)
@dlt.expect_or_drop("valid_flight_number", "flight_number IS NOT NULL")
@dlt.expect_or_drop("valid_total_bags", "total_bags >= 0")
@dlt.expect_or_drop("valid_load_percentage", "loading_progress_pct >= 0 AND loading_progress_pct <= 100")
def baggage_events_silver():
    """Transform and validate baggage events from Bronze layer.

    This function:
    1. Reads from the Bronze layer baggage_events_bronze table
    2. Normalizes airport_icao to uppercase
    3. Adds recorded_date partition column
    4. Deduplicates by airport_icao, flight_number, and recorded_at

    Returns:
        DataFrame: Cleaned baggage events with quality expectations
    """
    return (
        dlt.read_stream("baggage_events_bronze")
        .withColumn("recorded_date", F.to_date("recorded_at"))
        .withColumn("airport_icao", F.upper(F.col("airport_icao")))
        .dropDuplicates(["airport_icao", "flight_number", "recorded_at"])
    )

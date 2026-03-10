"""Gold layer DLT pipeline for business-ready baggage data.

This module defines two Gold layer tables:
- baggage_status_gold: Current baggage status per flight (latest snapshot)
- baggage_events_gold: Complete baggage event history for analytics
"""

import dlt
from pyspark.sql import functions as F


@dlt.table(
    name="baggage_status_gold",
    comment="Current baggage status per flight (latest snapshot)",
    table_properties={
        "quality": "gold",
        "pipelines.autoOptimize.managed": "true",
        "delta.autoOptimize.optimizeWrite": "true",
        "delta.autoOptimize.autoCompact": "true",
    },
)
def baggage_status_gold():
    """Aggregate baggage events to get latest status per flight.

    Groups by airport and flight number, keeping the most recent values
    for each metric. Uses a 10-minute watermark for late data handling.

    Returns:
        DataFrame: Latest baggage status per flight
    """
    return (
        dlt.read_stream("baggage_events_silver")
        .withWatermark("recorded_at", "10 minutes")
        .groupBy("airport_icao", "flight_number")
        .agg(
            F.last("total_bags").alias("total_bags"),
            F.last("loaded").alias("loaded"),
            F.last("connecting_bags").alias("connecting_bags"),
            F.last("loading_progress_pct").alias("loading_progress_pct"),
            F.last("misconnects").alias("misconnects"),
            F.max("recorded_at").alias("last_updated"),
        )
    )


@dlt.table(
    name="baggage_events_gold",
    comment="Complete baggage event history for analytics",
    table_properties={
        "quality": "gold",
        "pipelines.autoOptimize.managed": "true",
        "delta.autoOptimize.optimizeWrite": "true",
    },
    partition_cols=["recorded_date"],
)
def baggage_events_gold():
    """Append-only history of all baggage events for analytics.

    Preserves the full timeline of baggage status changes, partitioned
    by recorded_date for efficient time-range queries.

    Returns:
        DataFrame: Complete baggage event history
    """
    return dlt.read_stream("baggage_events_silver")

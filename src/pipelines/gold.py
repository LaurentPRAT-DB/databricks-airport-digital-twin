"""Gold layer DLT pipeline for business-ready aggregated flight data.

This module defines the Gold layer table that aggregates flight data
from the Silver layer and computes derived metrics like flight phase.
"""

import dlt
from pyspark.sql import functions as F


@dlt.table(
    name="flight_status_gold",
    comment="Business-ready aggregated flight status with computed metrics",
    table_properties={
        "quality": "gold",
        "pipelines.autoOptimize.managed": "true",
        "delta.autoOptimize.optimizeWrite": "true",
        "delta.autoOptimize.autoCompact": "true",
    },
)
def flight_status_gold():
    """Aggregate flight data from Silver layer with computed metrics.

    This function:
    1. Reads from the Silver layer flights_silver table
    2. Groups by icao24 to get the latest state per aircraft
    3. Computes flight_phase based on on_ground and vertical_rate
    4. Adds data_source identifier

    Flight phase logic:
    - ground: on_ground = true
    - climbing: vertical_rate > 1.0 m/s
    - descending: vertical_rate < -1.0 m/s
    - cruising: abs(vertical_rate) <= 1.0 m/s
    - unknown: no vertical_rate data

    Returns:
        DataFrame: Aggregated flight status with computed metrics
    """
    return (
        dlt.read_stream("flights_silver")
        .groupBy("icao24")
        .agg(
            F.last("callsign").alias("callsign"),
            F.last("origin_country").alias("origin_country"),
            F.max("position_time").alias("last_seen"),
            F.last("longitude").alias("longitude"),
            F.last("latitude").alias("latitude"),
            F.last("baro_altitude").alias("altitude"),
            F.last("velocity").alias("velocity"),
            F.last("true_track").alias("heading"),
            F.last("on_ground").alias("on_ground"),
            F.last("vertical_rate").alias("vertical_rate"),
        )
        .withColumn(
            "flight_phase",
            F.when(F.col("on_ground") == True, F.lit("ground"))
            .when(F.col("vertical_rate") > 1.0, F.lit("climbing"))
            .when(F.col("vertical_rate") < -1.0, F.lit("descending"))
            .when(
                (F.col("vertical_rate").isNotNull())
                & (F.abs(F.col("vertical_rate")) <= 1.0),
                F.lit("cruising"),
            )
            .otherwise(F.lit("unknown")),
        )
        .withColumn("data_source", F.lit("opensky"))
    )

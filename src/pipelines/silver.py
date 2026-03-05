"""Silver layer DLT pipeline for cleaned and validated flight data.

This module defines the Silver layer table that applies data quality
expectations and transformations to the raw Bronze layer data.
"""

import dlt
from pyspark.sql import functions as F
from pyspark.sql.types import (
    BooleanType,
    DoubleType,
    IntegerType,
    StringType,
    TimestampType,
)


@dlt.table(
    name="flights_silver",
    comment="Cleaned and validated flight position data with quality checks",
    table_properties={
        "quality": "silver",
        "pipelines.autoOptimize.managed": "true",
        "delta.autoOptimize.optimizeWrite": "true",
    },
)
@dlt.expect_or_drop("valid_position", "latitude IS NOT NULL AND longitude IS NOT NULL")
@dlt.expect_or_drop("valid_icao24", "icao24 IS NOT NULL AND LENGTH(icao24) = 6")
@dlt.expect("valid_altitude", "baro_altitude >= 0 OR baro_altitude IS NULL")
def flights_silver():
    """Transform and validate flight data from Bronze layer.

    This function:
    1. Reads from the Bronze layer flights_bronze table
    2. Explodes the states array into individual flight records
    3. Extracts all 17 fields from each state vector by index
    4. Applies watermark for late data handling
    5. Deduplicates by icao24 and position_time

    OpenSky state vector indices:
    0: icao24, 1: callsign, 2: origin_country, 3: time_position,
    4: last_contact, 5: longitude, 6: latitude, 7: baro_altitude,
    8: on_ground, 9: velocity, 10: true_track, 11: vertical_rate,
    12: sensors, 13: geo_altitude, 14: squawk, 15: spi, 16: position_source

    Returns:
        DataFrame: Cleaned flight position data with quality expectations
    """
    return (
        dlt.read_stream("flights_bronze")
        # Explode the states array to get individual flight records
        .withColumn("state", F.explode("states"))
        # Extract all 17 fields from the state vector by index
        .withColumn("icao24", F.col("state").getItem(0).cast(StringType()))
        .withColumn("callsign", F.trim(F.col("state").getItem(1).cast(StringType())))
        .withColumn("origin_country", F.col("state").getItem(2).cast(StringType()))
        .withColumn(
            "position_time",
            F.to_timestamp(F.col("state").getItem(3).cast(IntegerType())),
        )
        .withColumn(
            "last_contact",
            F.to_timestamp(F.col("state").getItem(4).cast(IntegerType())),
        )
        .withColumn("longitude", F.col("state").getItem(5).cast(DoubleType()))
        .withColumn("latitude", F.col("state").getItem(6).cast(DoubleType()))
        .withColumn("baro_altitude", F.col("state").getItem(7).cast(DoubleType()))
        .withColumn("on_ground", F.col("state").getItem(8).cast(BooleanType()))
        .withColumn("velocity", F.col("state").getItem(9).cast(DoubleType()))
        .withColumn("true_track", F.col("state").getItem(10).cast(DoubleType()))
        .withColumn("vertical_rate", F.col("state").getItem(11).cast(DoubleType()))
        # Index 12 is sensors array - skipping as not needed
        .withColumn("geo_altitude", F.col("state").getItem(13).cast(DoubleType()))
        .withColumn("squawk", F.col("state").getItem(14).cast(StringType()))
        # Index 15 is spi (special purpose indicator) - skipping
        .withColumn("position_source", F.col("state").getItem(16).cast(IntegerType()))
        .withColumn("category", F.col("state").getItem(17).cast(IntegerType()))
        # Apply watermark for late data handling (2 minutes)
        .withWatermark("position_time", "2 minutes")
        # Deduplicate by icao24 and position_time
        .dropDuplicates(["icao24", "position_time"])
        # Select final columns
        .select(
            "icao24",
            "callsign",
            "origin_country",
            "position_time",
            "last_contact",
            "longitude",
            "latitude",
            "baro_altitude",
            "on_ground",
            "velocity",
            "true_track",
            "vertical_rate",
            "geo_altitude",
            "squawk",
            "position_source",
            "category",
            "_ingested_at",
            "_source_file",
        )
    )

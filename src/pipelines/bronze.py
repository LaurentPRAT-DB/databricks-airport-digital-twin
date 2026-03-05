"""Bronze layer DLT pipeline for raw data ingestion.

This module defines the Bronze layer table that ingests raw flight data
from the OpenSky Network API using Databricks Auto Loader (cloudFiles).
"""

import dlt
from pyspark.sql import functions as F


@dlt.table(
    name="flights_bronze",
    comment="Raw flight data ingested from OpenSky Network API",
    table_properties={
        "quality": "bronze",
        "pipelines.autoOptimize.managed": "true",
        "delta.autoOptimize.optimizeWrite": "true",
    },
)
def flights_bronze():
    """Ingest raw flight data from cloud storage using Auto Loader.

    This table reads JSON files from the configured cloud storage path
    and adds metadata columns for tracking ingestion time and source file.

    The raw OpenSky API response format is:
    {
        "time": <unix_timestamp>,
        "states": [[state_vector], [state_vector], ...]
    }

    Returns:
        DataFrame: Raw flight data with metadata columns
    """
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "json")
        .option("cloudFiles.schemaLocation", "/mnt/airport_digital_twin/schema/bronze")
        .option("cloudFiles.inferColumnTypes", "true")
        .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
        .load("/mnt/airport_digital_twin/raw/opensky/")
        .withColumn("_ingested_at", F.current_timestamp())
        .withColumn("_source_file", F.input_file_name())
    )

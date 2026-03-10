"""Bronze layer DLT pipeline for raw baggage event ingestion.

This module defines the Bronze layer table that ingests raw baggage events
from the JSON landing zone using Databricks Auto Loader (cloudFiles).
"""

import dlt
from pyspark.sql import functions as F


@dlt.table(
    name="baggage_events_bronze",
    comment="Raw baggage events ingested from JSON landing zone",
    table_properties={
        "quality": "bronze",
        "pipelines.autoOptimize.managed": "true",
        "delta.autoOptimize.optimizeWrite": "true",
    },
)
def baggage_events_bronze():
    """Ingest raw baggage events from cloud storage using Auto Loader.

    Reads JSON-lines files written by baggage_writer.py from a Unity Catalog
    Volume landing zone. Each line contains one baggage event with fields:
    airport_icao, flight_number, total_bags, loaded, connecting_bags,
    status, load_percentage, last_updated, recorded_at.

    Returns:
        DataFrame: Raw baggage events with metadata columns
    """
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "json")
        .option("cloudFiles.inferColumnTypes", "true")
        .option("cloudFiles.schemaLocation", "/tmp/baggage_bronze_schema")
        .load("/Volumes/catalog/schema/baggage_landing")
        .withColumn("_ingested_at", F.current_timestamp())
        .withColumn("_source_file", F.input_file_name())
    )

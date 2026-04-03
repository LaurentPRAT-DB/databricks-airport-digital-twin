# Databricks notebook source
# MAGIC %md
# MAGIC # Load OpenSky Raw Data from UC Volume
# MAGIC
# MAGIC Reads JSON-lines files uploaded to the `opensky_raw` UC Volume and appends them
# MAGIC to the `opensky_states_raw` Delta table. Processed files are moved to a `processed/`
# MAGIC subfolder to avoid re-ingestion.
# MAGIC
# MAGIC **Data source:** Real ADS-B data from OpenSky Network, collected locally via
# MAGIC `scripts/opensky_collector.py` and uploaded to the Volume.
# MAGIC
# MAGIC **Direction:** UC Volume (JSONL) → Delta table (append)

# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType, DoubleType, BooleanType, LongType,
    TimestampType, IntegerType,
)

# Configuration
CATALOG = "serverless_stable_3n0ihb_catalog"
SCHEMA = "airport_digital_twin"
VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/opensky_raw"
PROCESSED_PATH = f"{VOLUME_PATH}/processed"
DELTA_TABLE = f"{CATALOG}.{SCHEMA}.opensky_states_raw"

print(f"Volume path: {VOLUME_PATH}")
print(f"Delta table: {DELTA_TABLE}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. List pending JSONL files

# COMMAND ----------

import os

pending_files = []
try:
    entries = dbutils.fs.ls(VOLUME_PATH)
    for entry in entries:
        if entry.name.endswith(".jsonl"):
            pending_files.append(entry.path)
except Exception as e:
    print(f"Error listing volume: {e}")

print(f"Found {len(pending_files)} pending JSONL files")
if not pending_files:
    dbutils.notebook.exit("No new files to process")

for f in pending_files[:10]:
    print(f"  {f}")
if len(pending_files) > 10:
    print(f"  ... and {len(pending_files) - 10} more")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Read and parse JSONL files

# COMMAND ----------

# Schema matching the collector output (raw OpenSky units)
OPENSKY_SCHEMA = StructType([
    StructField("icao24", StringType(), True),
    StructField("callsign", StringType(), True),
    StructField("origin_country", StringType(), True),
    StructField("time_position", LongType(), True),
    StructField("last_contact", LongType(), True),
    StructField("longitude", DoubleType(), True),
    StructField("latitude", DoubleType(), True),
    StructField("baro_altitude", DoubleType(), True),
    StructField("on_ground", BooleanType(), True),
    StructField("velocity", DoubleType(), True),
    StructField("true_track", DoubleType(), True),
    StructField("vertical_rate", DoubleType(), True),
    StructField("sensors", StringType(), True),
    StructField("geo_altitude", DoubleType(), True),
    StructField("squawk", StringType(), True),
    StructField("spi", BooleanType(), True),
    StructField("position_source", IntegerType(), True),
    StructField("collection_time", StringType(), True),
    StructField("airport_icao", StringType(), True),
    StructField("data_source", StringType(), True),
])

# Read all pending files
df_raw = spark.read.schema(OPENSKY_SCHEMA).json(pending_files)

row_count = df_raw.count()
print(f"Read {row_count} state vectors from {len(pending_files)} files")

if row_count == 0:
    print("No valid records found in files")
    dbutils.notebook.exit("No valid records in files")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Add derived columns and write to Delta

# COMMAND ----------

df = (
    df_raw
    # Parse collection_time ISO string to proper timestamp
    .withColumn("collection_timestamp", F.to_timestamp("collection_time"))
    # Partition column
    .withColumn("collection_date", F.to_date("collection_timestamp"))
    # Drop the string version, keep the timestamp
    .drop("collection_time")
    .withColumnRenamed("collection_timestamp", "collection_time")
    # Add ingestion metadata
    .withColumn("_ingested_at", F.current_timestamp())
    .withColumn("_source_file_count", F.lit(len(pending_files)))
)

# Show sample
df.select("airport_icao", "icao24", "callsign", "latitude", "longitude",
          "baro_altitude", "velocity", "on_ground", "collection_time", "data_source").show(5, truncate=False)

# Append to Delta table (create if not exists, with partition)
(
    df.write
    .mode("append")
    .partitionBy("collection_date")
    .option("mergeSchema", "true")
    .saveAsTable(DELTA_TABLE)
)

final_count = spark.table(DELTA_TABLE).count()
print(f"Appended {row_count} rows to {DELTA_TABLE} (total now: {final_count})")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Move processed files

# COMMAND ----------

# Ensure processed directory exists
try:
    dbutils.fs.mkdirs(PROCESSED_PATH)
except Exception:
    pass  # already exists

moved = 0
errors = 0
for filepath in pending_files:
    filename = filepath.split("/")[-1]
    dest = f"{PROCESSED_PATH}/{filename}"
    try:
        dbutils.fs.mv(filepath, dest)
        moved += 1
    except Exception as e:
        print(f"  Error moving {filename}: {e}")
        errors += 1

print(f"Moved {moved} files to processed/ ({errors} errors)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Summary

# COMMAND ----------

# Quick stats on the table
stats = spark.sql(f"""
    SELECT
        count(*) as total_rows,
        count(DISTINCT airport_icao) as airports,
        count(DISTINCT icao24) as unique_aircraft,
        min(collection_time) as earliest,
        max(collection_time) as latest,
        count(DISTINCT collection_date) as days
    FROM {DELTA_TABLE}
""").collect()[0]

print(f"\n{'='*60}")
print(f"OpenSky States Raw — Table Summary")
print(f"{'='*60}")
print(f"  Total rows:       {stats.total_rows:,}")
print(f"  Airports:         {stats.airports}")
print(f"  Unique aircraft:  {stats.unique_aircraft:,}")
print(f"  Date range:       {stats.earliest} → {stats.latest}")
print(f"  Days of data:     {stats.days}")
print(f"{'='*60}")

exit_msg = f"SUCCESS: ingested {row_count} rows from {len(pending_files)} files, table total: {stats.total_rows:,}"
dbutils.notebook.exit(exit_msg)

# Databricks notebook source
# MAGIC %md
# MAGIC # Baggage Pipeline Integration Tests
# MAGIC Tests Spark transformation logic from the baggage DLT pipeline (bronze/silver/gold)
# MAGIC without DLT decorators. Writes test data to temp Delta tables and asserts results.

# COMMAND ----------

import json
import time
from datetime import datetime, timedelta

from pyspark.sql import functions as F
from pyspark.sql.types import (
    DateType,
    IntegerType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

# COMMAND ----------

# Setup: create isolated temp schema
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
test_schema = f"_test_baggage_{int(time.time())}"

spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.`{test_schema}`")
print(f"Created temp schema: {catalog}.{test_schema}")

results = {}

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test 1 - Bronze: JSON ingestion with metadata columns

# COMMAND ----------

try:
    sample_events = [
        {"airport_icao": "KJFK", "flight_number": "UA123", "total_bags": 180,
         "loaded": 160, "connecting_bags": 25, "loading_progress_pct": 89,
         "misconnects": 0, "recorded_at": "2026-03-10T10:00:00Z"},
        {"airport_icao": "KJFK", "flight_number": "DL456", "total_bags": 200,
         "loaded": 195, "connecting_bags": 30, "loading_progress_pct": 97,
         "misconnects": 1, "recorded_at": "2026-03-10T10:01:00Z"},
        {"airport_icao": "EGLL", "flight_number": "BA789", "total_bags": 250,
         "loaded": 120, "connecting_bags": 40, "loading_progress_pct": 48,
         "misconnects": 2, "recorded_at": "2026-03-10T10:02:00Z"},
    ]

    # Write JSON-lines to temp volume path
    temp_path = f"/tmp/test_baggage_bronze_{int(time.time())}"
    dbutils.fs.mkdirs(temp_path)
    json_lines = "\n".join(json.dumps(e) for e in sample_events)
    dbutils.fs.put(f"{temp_path}/events.json", json_lines, overwrite=True)

    # Batch read (equivalent of cloudFiles Auto Loader)
    df = (
        spark.read.format("json")
        .option("inferSchema", "true")
        .load(temp_path)
        .withColumn("_ingested_at", F.current_timestamp())
        .withColumn("_source_file", F.input_file_name())
    )

    # Assertions
    assert df.count() == 3, f"Expected 3 rows, got {df.count()}"

    columns = set(df.columns)
    expected_cols = {"airport_icao", "flight_number", "total_bags", "loaded",
                     "connecting_bags", "loading_progress_pct", "misconnects",
                     "recorded_at", "_ingested_at", "_source_file"}
    missing = expected_cols - columns
    assert not missing, f"Missing columns: {missing}"

    # Check types
    schema_fields = {f.name: f.dataType for f in df.schema.fields}
    assert isinstance(schema_fields["_ingested_at"], TimestampType), \
        f"_ingested_at should be TimestampType, got {schema_fields['_ingested_at']}"
    assert isinstance(schema_fields["total_bags"], (IntegerType,)), \
        f"total_bags should be IntegerType, got {schema_fields['total_bags']}"
    assert isinstance(schema_fields["flight_number"], StringType), \
        f"flight_number should be StringType, got {schema_fields['flight_number']}"

    # Cleanup temp files
    dbutils.fs.rm(temp_path, recurse=True)

    results["test_1_bronze_ingestion"] = "PASS"
    print("Test 1 PASSED: Bronze JSON ingestion with metadata columns")

except Exception as e:
    results["test_1_bronze_ingestion"] = f"FAIL: {e}"
    print(f"Test 1 FAILED: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test 2 - Silver: expect_or_drop quality gates

# COMMAND ----------

try:
    from pyspark.sql import Row

    rows = [
        # Good rows
        Row(airport_icao="KJFK", flight_number="UA123", total_bags=180,
            loaded=160, connecting_bags=25, loading_progress_pct=89,
            misconnects=0, recorded_at="2026-03-10T10:00:00Z"),
        Row(airport_icao="EGLL", flight_number="BA789", total_bags=250,
            loaded=120, connecting_bags=40, loading_progress_pct=48,
            misconnects=2, recorded_at="2026-03-10T10:02:00Z"),
        # Bad: null flight_number
        Row(airport_icao="KJFK", flight_number=None, total_bags=100,
            loaded=50, connecting_bags=10, loading_progress_pct=50,
            misconnects=0, recorded_at="2026-03-10T10:03:00Z"),
        # Bad: negative total_bags
        Row(airport_icao="KJFK", flight_number="AA111", total_bags=-5,
            loaded=0, connecting_bags=0, loading_progress_pct=0,
            misconnects=0, recorded_at="2026-03-10T10:04:00Z"),
        # Bad: loading_progress_pct > 100
        Row(airport_icao="KJFK", flight_number="SW222", total_bags=100,
            loaded=100, connecting_bags=10, loading_progress_pct=150,
            misconnects=0, recorded_at="2026-03-10T10:05:00Z"),
    ]

    df = spark.createDataFrame(rows)

    # Apply the same filters as @dlt.expect_or_drop decorators
    filtered = (
        df.filter("flight_number IS NOT NULL")
          .filter("total_bags >= 0")
          .filter("loading_progress_pct >= 0 AND loading_progress_pct <= 100")
    )

    assert filtered.count() == 2, f"Expected 2 rows after quality gates, got {filtered.count()}"

    surviving_flights = {r.flight_number for r in filtered.collect()}
    assert surviving_flights == {"UA123", "BA789"}, \
        f"Expected UA123 and BA789 to survive, got {surviving_flights}"

    results["test_2_silver_quality_gates"] = "PASS"
    print("Test 2 PASSED: Silver quality gates reject bad rows")

except Exception as e:
    results["test_2_silver_quality_gates"] = f"FAIL: {e}"
    print(f"Test 2 FAILED: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test 3 - Silver: dedup, uppercase, and date extraction

# COMMAND ----------

try:
    rows = [
        Row(airport_icao="kjfk", flight_number="UA123",
            recorded_at="2026-03-10T10:00:00Z", total_bags=180),
        # Duplicate of above (same airport, flight, recorded_at)
        Row(airport_icao="kjfk", flight_number="UA123",
            recorded_at="2026-03-10T10:00:00Z", total_bags=185),
        Row(airport_icao="egll", flight_number="BA789",
            recorded_at="2026-03-10T10:01:00Z", total_bags=250),
        Row(airport_icao="kjfk", flight_number="DL456",
            recorded_at="2026-03-10T10:02:00Z", total_bags=200),
    ]

    df = spark.createDataFrame(rows)

    # Apply same transformations as baggage_silver.py
    transformed = (
        df.withColumn("recorded_date", F.to_date("recorded_at"))
          .withColumn("airport_icao", F.upper(F.col("airport_icao")))
          .dropDuplicates(["airport_icao", "flight_number", "recorded_at"])
    )

    assert transformed.count() == 3, f"Expected 3 unique rows, got {transformed.count()}"

    # Check uppercase
    icao_values = {r.airport_icao for r in transformed.collect()}
    for v in icao_values:
        assert v == v.upper(), f"airport_icao should be uppercased, got {v}"

    # Check recorded_date column exists and is DateType
    schema_fields = {f.name: f.dataType for f in transformed.schema.fields}
    assert "recorded_date" in schema_fields, "recorded_date column missing"
    assert isinstance(schema_fields["recorded_date"], DateType), \
        f"recorded_date should be DateType, got {schema_fields['recorded_date']}"

    results["test_3_silver_dedup_transforms"] = "PASS"
    print("Test 3 PASSED: Silver dedup, uppercase, and date extraction")

except Exception as e:
    results["test_3_silver_dedup_transforms"] = f"FAIL: {e}"
    print(f"Test 3 FAILED: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test 4 - Gold: groupBy aggregation with F.last()

# COMMAND ----------

try:
    rows = [
        # UA123: 3 events over time
        Row(airport_icao="KJFK", flight_number="UA123", total_bags=180,
            loaded=100, connecting_bags=25, loading_progress_pct=55,
            misconnects=0, recorded_at="2026-03-10T10:00:00Z"),
        Row(airport_icao="KJFK", flight_number="UA123", total_bags=180,
            loaded=140, connecting_bags=25, loading_progress_pct=78,
            misconnects=0, recorded_at="2026-03-10T10:05:00Z"),
        Row(airport_icao="KJFK", flight_number="UA123", total_bags=180,
            loaded=175, connecting_bags=25, loading_progress_pct=97,
            misconnects=1, recorded_at="2026-03-10T10:10:00Z"),
        # DL456: 3 events over time
        Row(airport_icao="KJFK", flight_number="DL456", total_bags=200,
            loaded=50, connecting_bags=30, loading_progress_pct=25,
            misconnects=0, recorded_at="2026-03-10T10:00:00Z"),
        Row(airport_icao="KJFK", flight_number="DL456", total_bags=200,
            loaded=150, connecting_bags=30, loading_progress_pct=75,
            misconnects=0, recorded_at="2026-03-10T10:05:00Z"),
        Row(airport_icao="KJFK", flight_number="DL456", total_bags=200,
            loaded=195, connecting_bags=30, loading_progress_pct=97,
            misconnects=2, recorded_at="2026-03-10T10:10:00Z"),
    ]

    df = spark.createDataFrame(rows)

    # Sort by recorded_at to ensure F.last() picks the latest
    df_sorted = df.orderBy("recorded_at")

    # Apply same aggregation as baggage_status_gold
    aggregated = (
        df_sorted.groupBy("airport_icao", "flight_number")
        .agg(
            F.last("total_bags").alias("total_bags"),
            F.last("loaded").alias("loaded"),
            F.last("connecting_bags").alias("connecting_bags"),
            F.last("loading_progress_pct").alias("loading_progress_pct"),
            F.last("misconnects").alias("misconnects"),
            F.max("recorded_at").alias("last_updated"),
        )
    )

    assert aggregated.count() == 2, f"Expected 2 aggregated rows, got {aggregated.count()}"

    results_map = {r.flight_number: r for r in aggregated.collect()}

    ua = results_map["UA123"]
    assert ua.loaded == 175, f"UA123 loaded should be 175 (latest), got {ua.loaded}"
    assert ua.misconnects == 1, f"UA123 misconnects should be 1 (latest), got {ua.misconnects}"
    assert ua.last_updated == "2026-03-10T10:10:00Z", \
        f"UA123 last_updated should be max timestamp, got {ua.last_updated}"

    dl = results_map["DL456"]
    assert dl.loaded == 195, f"DL456 loaded should be 195 (latest), got {dl.loaded}"
    assert dl.misconnects == 2, f"DL456 misconnects should be 2 (latest), got {dl.misconnects}"

    results["test_4_gold_aggregation"] = "PASS"
    print("Test 4 PASSED: Gold groupBy aggregation with F.last()")

except Exception as e:
    results["test_4_gold_aggregation"] = f"FAIL: {e}"
    print(f"Test 4 FAILED: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test 5 - Gold: append-only history with date partitioning

# COMMAND ----------

try:
    rows = [
        Row(airport_icao="KJFK", flight_number="UA123", total_bags=180,
            loaded=160, connecting_bags=25, loading_progress_pct=89,
            misconnects=0, recorded_at="2026-03-10T10:00:00Z",
            recorded_date="2026-03-10"),
        Row(airport_icao="KJFK", flight_number="UA123", total_bags=180,
            loaded=175, connecting_bags=25, loading_progress_pct=97,
            misconnects=1, recorded_at="2026-03-10T10:10:00Z",
            recorded_date="2026-03-10"),
        Row(airport_icao="EGLL", flight_number="BA789", total_bags=250,
            loaded=245, connecting_bags=40, loading_progress_pct=98,
            misconnects=0, recorded_at="2026-03-11T08:00:00Z",
            recorded_date="2026-03-11"),
    ]

    df = spark.createDataFrame(rows)

    table_name = f"`{catalog}`.`{test_schema}`.test_baggage_events_gold"

    # Write with partitioning (same as baggage_events_gold partition_cols)
    (
        df.write.format("delta")
        .mode("overwrite")
        .partitionBy("recorded_date")
        .saveAsTable(table_name)
    )

    # Read back and verify
    read_back = spark.table(table_name)
    assert read_back.count() == 3, \
        f"Expected 3 rows (append-only, no aggregation), got {read_back.count()}"

    # Verify partition column
    assert "recorded_date" in read_back.columns, "recorded_date partition column missing"

    # Check Delta metadata for partitioning
    detail = spark.sql(f"DESCRIBE DETAIL {table_name}").collect()[0]
    partitions = detail.partitionColumns
    assert "recorded_date" in partitions, \
        f"Table should be partitioned by recorded_date, got {partitions}"

    results["test_5_gold_history_partitioning"] = "PASS"
    print("Test 5 PASSED: Gold append-only history with date partitioning")

except Exception as e:
    results["test_5_gold_history_partitioning"] = f"FAIL: {e}"
    print(f"Test 5 FAILED: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Teardown

# COMMAND ----------

# Drop temp schema
try:
    spark.sql(f"DROP SCHEMA IF EXISTS `{catalog}`.`{test_schema}` CASCADE")
    print(f"Dropped temp schema: {catalog}.{test_schema}")
except Exception as e:
    print(f"Warning: failed to drop temp schema: {e}")

# Report results
print("\n=== Test Results ===")
passed = sum(1 for v in results.values() if v == "PASS")
total = len(results)
for name, status in results.items():
    print(f"  {name}: {status}")
print(f"\n{passed}/{total} tests passed")

if passed < total:
    dbutils.notebook.exit(json.dumps({"status": "FAIL", "results": results}))
else:
    dbutils.notebook.exit(json.dumps({"status": "PASS", "results": results}))

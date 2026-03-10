# Plan: Integration Tests for Baggage DLT Pipeline on Databricks

**Phase:** 07 — Post-v1
**Date:** 2026-03-09
**Status:** Implemented

---

## Context

The baggage DLT pipeline files (baggage_bronze.py, baggage_silver.py, baggage_gold.py) have 0% runtime coverage because the `dlt` module and spark session only exist inside Databricks. Local tests validate code structure via string inspection but can't execute the actual Spark transformations.

**Approach:** Create a Databricks notebook that runs as a DABs job, testing the Spark transformation logic without DLT decorators — by writing test data to temp Delta tables, applying the same transformations, and asserting results. This follows the existing `sync_job.yml` + notebook pattern (`databricks/notebooks/run_poll.py`).

---

## Plan — 2 New Files, 1 Edit

### File 1: `databricks/notebooks/test_baggage_pipeline.py` (NEW)

A Databricks notebook (with `# COMMAND ----------` separators) that runs 5 test cases:

**Setup cell:**
- Reads catalog and schema from widget params (passed by the job)
- Creates temp schema `_test_baggage_{timestamp}` for isolation
- Writes sample JSON-lines to a temp path in the catalog's volume

**Test 1 — Bronze:** Auto Loader JSON ingestion with schema inference
- Writes 3 sample baggage JSON-lines to a temp directory
- Reads with `spark.read.format("json")` (batch equivalent of cloudFiles)
- Adds `_ingested_at` and `_source_file` columns (same as baggage_bronze.py)
- Asserts: correct row count, all expected columns present, `_ingested_at` is timestamp type, column types inferred correctly (int for total_bags, string for flight_number)

**Test 2 — Silver:** expect_or_drop quality gates rejecting bad rows
- Creates DataFrame with 5 rows: 2 good + 3 bad (null flight_number, negative total_bags, loading_progress_pct=150)
- Applies the exact SQL filter expressions: `flight_number IS NOT NULL`, `total_bags >= 0`, `loading_progress_pct >= 0 AND loading_progress_pct <= 100`
- Asserts: exactly 2 rows survive, bad rows are gone

**Test 3 — Silver:** dropDuplicates dedup behavior
- Creates DataFrame with 4 rows where 2 share the same (airport_icao, flight_number, recorded_at)
- Applies `.dropDuplicates(["airport_icao", "flight_number", "recorded_at"])`
- Also checks `.withColumn("airport_icao", F.upper(...))` and `.withColumn("recorded_date", F.to_date(...))`
- Asserts: 3 unique rows, airport_icao is uppercased, recorded_date column exists and is DateType

**Test 4 — Gold:** groupBy aggregation with F.last()
- Creates DataFrame with 6 rows: 3 events for flight UA123, 3 for DL456
- Applies `groupBy("airport_icao", "flight_number").agg(F.last("total_bags"), F.last("loaded"), ..., F.max("recorded_at"))`
- Asserts: 2 result rows, each has the latest total_bags/loaded values and max recorded_at

**Test 5 — Gold:** append-only history with date partitioning
- Writes silver-like data to a Delta table with `partitionBy("recorded_date")`
- Reads back and asserts: all rows preserved (no aggregation), partition column exists
- Checks Delta table metadata to verify partitioning is applied

**Teardown cell:**
- Drops temp schema CASCADE
- `dbutils.notebook.exit(json.dumps(results))` with pass/fail per test

### File 2: `resources/integration_test_job.yml` (NEW)

DABs job definition (follows `resources/sync_job.yml` pattern):

```yaml
resources:
  jobs:
    baggage_pipeline_integration_test:
      name: "[${bundle.target}] Airport DT - Baggage Pipeline Integration Test"
      tasks:
        - task_key: test_baggage_pipeline
          notebook_task:
            notebook_path: ../databricks/notebooks/test_baggage_pipeline.py
            base_parameters:
              catalog: ${var.catalog}
              schema: ${var.schema}
          environment_key: test_env
      environments:
        - environment_key: test_env
          spec:
            client: "1"
      tags:
        project: airport-digital-twin
        component: integration-test
        target: ${bundle.target}
      timeout_seconds: 600
```

No schedule — on-demand only (triggered via `databricks bundle run` or CI).

### File 3: `tests/test_dlt.py` (EDIT)

Update `TestDLTPipelineConfig.test_pipeline_has_libraries` assertion from `>= 3` to `>= 6` to reflect the 6 pipeline library entries.

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Test Spark logic without DLT decorators | DLT decorators are thin wrappers; the real logic is Spark DataFrame ops. Standard pattern for testing DLT. |
| Serverless environment (client: "1") | Matches existing sync_job.yml; no cluster config needed. |
| Temp schema per run | `_test_baggage_{timestamp}` ensures parallel runs don't conflict; CASCADE drop cleans up. |
| Batch reads instead of streaming | Tests validate transformation correctness. Streaming mechanics (watermarks, triggers) are DLT runtime concerns. |
| No schedule on the job | Integration tests run on-demand, not continuously. |

---

## Verification

```bash
# Deploy
databricks bundle deploy --target dev

# Run integration test
databricks bundle run baggage_pipeline_integration_test --target dev

# Local tests still pass
uv run pytest tests/test_dlt.py -v
```

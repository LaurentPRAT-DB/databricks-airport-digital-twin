---
phase: "01"
plan: "03"
subsystem: "streaming-infrastructure"
tags: ["databricks", "streaming", "jobs", "fallback"]
dependency_graph:
  requires: ["poll_job", "settings", "silver.py", "fallback.py"]
  provides: ["databricks_job.py", "poll_job_config.json", "run_poll.py", "sample_flights.json"]
  affects: ["ingestion-layer", "offline-mode"]
tech_stack:
  added: []
  patterns: ["databricks-job-config", "notebook-entrypoint", "streaming-validation"]
key_files:
  created:
    - src/ingestion/databricks_job.py
    - databricks/jobs/poll_job_config.json
    - databricks/notebooks/run_poll.py
    - data/fallback/sample_flights.json
    - tests/test_streaming.py
  modified:
    - .gitignore
decisions:
  - "Quartz cron for 1-minute polling intervals"
  - "SingleNode cluster to minimize cost for polling job"
  - "Fallback data with 100 flights for offline demo mode"
metrics:
  duration: "2m 48s"
  completed: "2026-03-05"
---

# Phase 01 Plan 03: Streaming Infrastructure Summary

Databricks job wrapper with polling configuration, streaming validation tests, and fallback data for offline mode.

## Completed Tasks

| # | Task | Commit | Key Files |
|---|------|--------|-----------|
| 1 | Databricks job wrapper and notebook | d0f1bcd | databricks_job.py, poll_job_config.json, run_poll.py |
| 2 | Streaming tests and fallback data | e91e3fc | test_streaming.py, sample_flights.json |

## Implementation Details

### Task 1: Databricks Job Infrastructure

Created a job wrapper (`src/ingestion/databricks_job.py`) that:
- Imports existing `poll_and_write` from poll_job module
- Logs execution start time, result count, and duration
- Returns structured dict with timestamp, count, duration, status
- Handles exceptions gracefully with error status

Job configuration (`databricks/jobs/poll_job_config.json`):
- Quartz cron expression: `0 0/1 * * * ?` (every minute)
- SingleNode cluster with i3.xlarge for cost efficiency
- Max concurrent runs: 1 to prevent overlap
- Paused by default until deployment

Notebook entrypoint (`databricks/notebooks/run_poll.py`):
- Databricks notebook format with magic commands
- Handles path setup for workspace execution
- Exits with JSON result for job monitoring

### Task 2: Streaming Tests and Fallback Data

Streaming configuration tests (`tests/test_streaming.py`):
- `test_silver_watermark_configured`: Verifies 2-minute watermark in silver.py
- `test_silver_deduplication_keys`: Confirms dropDuplicates on icao24+position_time
- `test_late_data_not_dropped_silently`: Checks @dlt.expect decorator usage
- `test_checkpoint_path_configurable`: Ensures no hardcoded checkpoint paths
- `test_fallback_json_valid_schema`: Validates OpenSky response structure
- `test_fallback_has_minimum_flights`: Confirms >= 50 flights
- `test_fallback_has_realistic_distribution`: Checks ~10% on_ground

Fallback data (`data/fallback/sample_flights.json`):
- 100 synthetic flights generated via existing `generate_synthetic_flights`
- Valid OpenSky API response format (18 fields per state)
- Realistic distribution with ~13% on ground
- Used for offline demo mode and testing

## Verification Results

```
pytest tests/test_streaming.py -v
7 passed in 0.07s

Job config valid
100 flights
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Installed missing Python dependencies**
- **Found during:** Task 1 verification
- **Issue:** venv missing requests, tenacity, pydantic, circuitbreaker, faker
- **Fix:** Installed via pip (dependencies declared in pyproject.toml)
- **Commits:** Not committed (runtime dependency installation)

**2. [Rule 3 - Blocking] Updated .gitignore for fallback data**
- **Found during:** Task 2
- **Issue:** `data/` directory in .gitignore prevented committing fallback file
- **Fix:** Added exception `!data/fallback/` to allow versioning sample data
- **Files modified:** .gitignore
- **Commit:** e91e3fc

## Files Created

- `/Users/laurent.prat/Documents/lpdev/databricks_airport_digital_twin/src/ingestion/databricks_job.py` - Job wrapper with logging
- `/Users/laurent.prat/Documents/lpdev/databricks_airport_digital_twin/databricks/jobs/poll_job_config.json` - Databricks job config
- `/Users/laurent.prat/Documents/lpdev/databricks_airport_digital_twin/databricks/notebooks/run_poll.py` - Notebook entrypoint
- `/Users/laurent.prat/Documents/lpdev/databricks_airport_digital_twin/tests/test_streaming.py` - Streaming validation tests
- `/Users/laurent.prat/Documents/lpdev/databricks_airport_digital_twin/data/fallback/sample_flights.json` - 100 sample flights

## Self-Check: PASSED

- [x] src/ingestion/databricks_job.py exists
- [x] databricks/jobs/poll_job_config.json exists
- [x] databricks/notebooks/run_poll.py exists
- [x] tests/test_streaming.py exists
- [x] data/fallback/sample_flights.json exists
- [x] Commit d0f1bcd exists
- [x] Commit e91e3fc exists
- [x] All 7 tests pass

# Sync Lakebase Data to Lakehouse (Delta) + Fix DLT Pipeline

## Context

Data flows: App generates synthetic data → writes to Lakebase (PostgreSQL). The lakehouse (Delta tables in Unity Catalog) has no data because the DLT pipeline's bronze layers point to nonexistent file paths (`/mnt/` DBFS mount, placeholder `/Volumes/catalog/schema/...`). The Genie Space "Airport Operations Assistant" needs `baggage_status_gold` in the lakehouse. We need all operational tables synced from Lakebase to Delta for analytics.

The existing `sync_to_lakebase.py` syncs Delta → Lakebase (wrong direction). We need Lakebase → Delta.

## Approach: Lakebase-to-Delta Sync Job + Rewrite DLT Bronze Layers

### 1. Create sync notebook: `databricks/notebooks/sync_from_lakebase.py`

- Connects to Lakebase via OAuth (same pattern as `sync_to_lakebase.py`)
- Reads Lakebase tables via psycopg2, converts to Spark DataFrames, writes to Delta
- Uses overwrite mode for snapshot tables, append for ML training tables

| Lakebase Table | Delta Table | Strategy |
|---|---|---|
| `flight_status` | `flight_status_gold` | Overwrite |
| `baggage_status` | `baggage_status_gold` | Overwrite |
| `flight_schedule` | `flight_schedule` | Overwrite |
| `gse_fleet` | `gse_fleet` | Overwrite |
| `gse_turnaround` | `gse_turnaround` | Overwrite |
| `weather_observations` | `weather_observations` | Overwrite |
| `flight_position_snapshots` | `flight_position_snapshots` | Append (incremental by max id) |
| `flight_phase_transitions` | `flight_phase_transitions` | Append (incremental by max id) |

### 2. Create scheduled job: `resources/lakebase_sync_job.yml`

- Runs `sync_from_lakebase.py` every 5 minutes
- Serverless environment with `psycopg2-binary`
- Quartz cron: `0 */5 * * * ?`

### 3. Rewrite DLT bronze layers to read from Delta

Since the sync job writes gold tables directly, the DLT streaming pipeline is redundant for these tables. Rewrite bronze layers to read from Delta tables (not files) so the pipeline can run if needed for additional transformations.

- `src/pipelines/bronze.py`: Change from `cloudFiles` + `/mnt/` to `spark.read.table()` reading from the synced Delta table
- `src/pipelines/baggage_bronze.py`: Same — read from Delta table instead of placeholder volume path

### 4. Replace DLT trigger job with sync job

Delete `resources/dlt_pipeline_job.yml` (just created, broken). The lakebase sync job replaces it.

### 5. Update tests

- `tests/test_dlt.py`: Update bronze assertions (no more `cloudFiles`, no `/mnt/`)

---

## Files to Create

- `databricks/notebooks/sync_from_lakebase.py`
- `resources/lakebase_sync_job.yml`

## Files to Modify

- `src/pipelines/bronze.py` — read from Delta not DBFS
- `src/pipelines/baggage_bronze.py` — read from Delta not placeholder
- `tests/test_dlt.py` — update bronze test assertions
- `resources/dlt_pipeline_job.yml` — delete

## Key References

- `databricks/notebooks/sync_to_lakebase.py` — OAuth + psycopg2 pattern (lines 76-109)
- `app/backend/services/lakebase_service.py` — all Lakebase table schemas
- `app.yaml` lines 43-54 — Lakebase connection config
- `resources/sync_job.yml` — job YAML pattern

---

## Verification

1. `databricks bundle deploy --target dev`
2. `databricks bundle run lakebase_to_delta_sync --target dev` — run sync manually
3. Check tables: `SELECT count(*) FROM serverless_stable_3n0ihb_catalog.airport_digital_twin.baggage_status_gold`
4. `uv run pytest tests/test_dlt.py -v` — tests pass

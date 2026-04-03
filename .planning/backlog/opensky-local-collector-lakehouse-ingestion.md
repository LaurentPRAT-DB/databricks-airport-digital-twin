# Plan: OpenSky Local Collector + Lakehouse Ingestion Pipeline

**Status:** Backlog
**Date added:** 2026-04-03
**Depends on:** OpenSky Live Data Integration
**Scope:** Local collector script + UC Volume + ingestion notebook + DABs job

---

## Context

OpenSky Network API is unreachable from Databricks on AWS (likely IP/firewall blocking). We need to collect real ADS-B data locally (where OpenSky works), store it as files, upload to a UC Volume, and load into Delta tables. This real data can then be replayed as live-but-deferred feeds. Lakebase gets populated downstream from the lakehouse (existing sync job handles that).

## Architecture

```
Local machine                    Databricks
─────────────                    ──────────
opensky_collector.py             Volume: opensky_raw/
  │ polls OpenSky every N sec      ↑
  │ writes JSON-lines files        │ manual upload / databricks fs cp
  └──→ data/opensky_raw/  ────────┘
                                   ↓
                                 load_opensky_volume notebook
                                   │ reads JSON-lines from Volume
                                   │ writes to Delta: opensky_states_raw (append)
                                   └──→ lakehouse (Delta)
                                          ↓ (existing lakebase sync)
                                        Lakebase
```

## Deliverables

### 1. Local collector script: `scripts/opensky_collector.py`

Standalone Python script (runs locally with `uv run`). Features:

- Polls OpenSky `/api/states/all` for a bounding box around a configured airport
- Configurable via CLI args: `--airport KSFO`, `--interval 15`, `--output-dir data/opensky_raw`
- Saves raw OpenSky state vectors (not converted) as JSON-lines files, one file per fetch
- File naming: `{airport}_{timestamp_utc}.jsonl` (e.g., `KSFO_2026-04-03T14-30-00Z.jsonl`)
- Each line = one state vector as JSON object with named fields (not array indices)
- Adds metadata per line: `collection_time`, `airport_icao`, `data_source: "opensky_live"`
- Reuses OpenSkyService auth pattern (env vars `OPENSKY_USERNAME`/`OPENSKY_PASSWORD`)
- Handles rate limits (429 → exponential backoff), logs progress
- Graceful Ctrl+C shutdown

Airport coordinates: use a small lookup from `src/calibration/known_profiles.py` or hardcode the few airports we care about (this is the collector config, not geometry — acceptable per project rules).

### 2. UC Volume resource: `resources/opensky_volume.yml`

DABs resource definition for a UC Volume:

```yaml
resources:
  volumes:
    opensky_raw:
      catalog_name: ${var.catalog}
      schema_name: ${var.schema}
      name: opensky_raw
      volume_type: MANAGED
```

### 3. Ingestion notebook: `databricks/notebooks/load_opensky_from_volume.py`

Databricks notebook (serverless) that:

- Lists JSON-lines files in the Volume (`/Volumes/{catalog}/{schema}/opensky_raw/`)
- Reads all `.jsonl` files via `spark.read.json()`
- Writes to Delta table `opensky_states_raw` (append mode, partitioned by `collection_date`)
- Moves processed files to a `processed/` subfolder in the Volume
- Schema: all raw OpenSky fields + `collection_time`, `airport_icao`, `data_source`

### 4. Ingestion job: `resources/opensky_ingestion_job.yml`

DABs job definition:

- Runs the ingestion notebook on serverless
- Schedule: every 15 minutes (or manual trigger)
- Tags: `component: opensky-ingestion`

### 5. Delta table schema: `opensky_states_raw`

| Column | Type | Description |
|--------|------|-------------|
| `icao24` | STRING | Aircraft transponder address |
| `callsign` | STRING | Flight callsign |
| `origin_country` | STRING | |
| `longitude` | DOUBLE | |
| `latitude` | DOUBLE | |
| `baro_altitude` | DOUBLE | Meters (raw, not converted) |
| `geo_altitude` | DOUBLE | Meters |
| `velocity` | DOUBLE | m/s (raw) |
| `true_track` | DOUBLE | Heading degrees |
| `vertical_rate` | DOUBLE | m/s (raw) |
| `on_ground` | BOOLEAN | |
| `position_time` | LONG | Unix epoch from OpenSky |
| `last_contact` | LONG | Unix epoch |
| `collection_time` | TIMESTAMP | When we fetched it |
| `airport_icao` | STRING | Which airport we were monitoring |
| `data_source` | STRING | `"opensky_live"` |
| `collection_date` | DATE | Partition column (derived from collection_time) |

Store raw units (meters, m/s) — conversion to ft/kts happens at read time, like the existing `opensky_service.py` does.

## Files to Create/Modify

| File | Action |
|------|--------|
| `scripts/opensky_collector.py` | Create — local collector |
| `resources/opensky_volume.yml` | Create — UC Volume definition |
| `databricks/notebooks/load_opensky_from_volume.py` | Create — ingestion notebook |
| `resources/opensky_ingestion_job.yml` | Create — DABs job |

No modifications to existing files needed. The existing `lakebase_sync_job` already handles Delta → Lakebase sync for downstream.

## Verification

1. Local collector: `uv run python scripts/opensky_collector.py --airport KSFO --interval 30 --duration 120` → produces `.jsonl` files in `data/opensky_raw/`
2. File content: Inspect a `.jsonl` file — each line is a valid JSON with all expected fields
3. Volume deploy: `databricks bundle deploy --target dev` → Volume created in UC
4. Upload: `databricks fs cp data/opensky_raw/*.jsonl dbfs:/Volumes/serverless_stable_3n0ihb_catalog/airport_digital_twin/opensky_raw/`
5. Ingestion job: `databricks bundle run opensky_ingestion --target dev` → Delta table populated
6. Query: `SELECT count(*), airport_icao, min(collection_time), max(collection_time) FROM opensky_states_raw GROUP BY airport_icao`

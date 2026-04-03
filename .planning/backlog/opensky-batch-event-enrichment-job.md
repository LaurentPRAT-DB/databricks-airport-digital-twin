# Plan: Batch OpenSky Event Enrichment Job

**Status:** Backlog
**Date added:** 2026-04-03
**Depends on:** OpenSky Event Inference Pipeline
**Scope:** Batch enrichment notebook + 3 new Delta tables + DABs job + ML-ready output

---

## Context

Raw ADS-B data in `opensky_states_raw` has positions but no gate assignments, phase transitions, or gate events. Aircraft need to get close to OSM gates for quality matching — the enrichment must process the full trajectory per aircraft across all frames, matching only when the aircraft is truly stationary near a gate.

The existing `OpenSkyEventInferrer` (`src/inference/opensky_events.py`) does this at API query time but results aren't persisted. We need a batch job that enriches lakehouse data and writes to three new Delta tables, plus produces ML-ready JSON files.

## Output Tables

### 1. `opensky_phase_transitions` — all inferred phase changes

```sql
CREATE TABLE opensky_phase_transitions (
  airport_icao STRING NOT NULL,
  collection_date DATE NOT NULL,
  time STRING NOT NULL,             -- ISO timestamp
  icao24 STRING NOT NULL,
  callsign STRING,
  from_phase STRING NOT NULL,
  to_phase STRING NOT NULL,
  latitude DOUBLE,
  longitude DOUBLE,
  altitude DOUBLE,                  -- feet
  aircraft_type STRING,
  assigned_gate STRING,
  _enriched_at TIMESTAMP
) PARTITIONED BY (collection_date)
```

### 2. `opensky_gate_events` — assign/occupy/release events

```sql
CREATE TABLE opensky_gate_events (
  airport_icao STRING NOT NULL,
  collection_date DATE NOT NULL,
  time STRING NOT NULL,
  icao24 STRING NOT NULL,
  callsign STRING,
  gate STRING NOT NULL,
  event_type STRING NOT NULL,       -- 'assign', 'occupy', 'release'
  aircraft_type STRING,
  gate_distance_m DOUBLE,           -- distance to gate at event time
  _enriched_at TIMESTAMP
) PARTITIONED BY (collection_date)
```

### 3. `opensky_enriched_snapshots` — positions with assigned_gate + aircraft_type filled in

```sql
CREATE TABLE opensky_enriched_snapshots (
  airport_icao STRING NOT NULL,
  collection_date DATE NOT NULL,
  time STRING NOT NULL,
  icao24 STRING NOT NULL,
  callsign STRING,
  latitude DOUBLE,
  longitude DOUBLE,
  altitude DOUBLE,                  -- feet
  velocity DOUBLE,                  -- knots
  heading DOUBLE,
  vertical_rate DOUBLE,             -- ft/min
  phase STRING,                     -- inferred sim-compatible phase
  on_ground BOOLEAN,
  aircraft_type STRING,             -- from aircraft_db enrichment
  assigned_gate STRING,             -- from gate proximity inference
  _enriched_at TIMESTAMP
) PARTITIONED BY (collection_date)
```

## Implementation

### 1. `src/persistence/airport_tables.py` — add 3 DDLs

Add `OPENSKY_PHASE_TRANSITIONS_DDL`, `OPENSKY_GATE_EVENTS_DDL`, `OPENSKY_ENRICHED_SNAPSHOTS_DDL` to `ALL_TABLES`.

### 2. `src/inference/opensky_events.py` — add `gate_distance_m` + enriched snapshots

- Add `gate_distance_m` to `_emit_gate_event()` for quality tracking
- Add `get_enriched_snapshots()` method that returns all processed frames with `assigned_gate` and inferred phase filled in
- These are the same changes we already do at API time in `opensky.py:get_recording_data()`, but now returned as structured data for batch persistence

### 3. `databricks/notebooks/enrich_opensky_events.py` — enrichment notebook

Steps:

1. **Import setup:** Add bundle root to `sys.path` (same pattern as `preload_osm_airports.py`)
2. **Find unenriched data:** Query `opensky_states_raw` for `(airport_icao, collection_date)` pairs not yet in `opensky_enriched_snapshots`
3. **For each airport/date combo:**
   - a. Load gate positions from UC gates table: `SELECT ref, latitude, longitude, terminal FROM gates WHERE icao_code = '{airport}'`
   - b. Load raw states: `SELECT * FROM opensky_states_raw WHERE airport_icao = '{airport}' AND collection_date = '{date}' ORDER BY collection_time, icao24`
   - c. Convert to frames (meters→feet, m/s→kts — reuse constants from `opensky_service.py`)
   - d. Run `OpenSkyEventInferrer(gates)` across frames
   - e. Write results to all 3 tables
4. **Produce ML-ready JSON** (optional): Write a JSON file per airport/date to UC Volume in the same format as simulation output, so `obt_features.py:extract_training_data()` can consume it directly

### 4. `resources/opensky_enrichment_job.yml` — DABs job

```yaml
resources:
  jobs:
    opensky_enrichment:
      name: "[${bundle.target}] Airport Digital Twin - OpenSky Event Enrichment"
      tasks:
        - task_key: enrich_opensky_events
          notebook_task:
            notebook_path: ../databricks/notebooks/enrich_opensky_events.py
      schedule:
        quartz_cron_expression: "0 */30 * * * ?"
        pause_status: PAUSED
      timeout_seconds: 1800
```

## Key Reuse

| Existing code | Reuse |
|--------------|-------|
| `src/inference/opensky_events.py:OpenSkyEventInferrer` | Core inference engine |
| `src/persistence/airport_tables.py` | DDL pattern + `ALL_TABLES` list |
| `app/backend/services/opensky_service.py` | `M_TO_FT`, `MS_TO_KTS`, `MS_TO_FTMIN`, `determine_flight_phase()` |
| `databricks/notebooks/preload_osm_airports.py` | `sys.path` setup + `spark.sql` pattern |
| `databricks/notebooks/load_opensky_from_volume.py` | Delta write pattern |
| `src/ml/obt_features.py:extract_training_data()` | Consumer — validates output format |

## Files to Create/Modify

| File | Action |
|------|--------|
| `src/persistence/airport_tables.py` | Add 3 DDLs to `ALL_TABLES` |
| `src/inference/opensky_events.py` | Add `gate_distance_m`, `get_enriched_snapshots()` |
| `databricks/notebooks/enrich_opensky_events.py` | Create — enrichment notebook |
| `resources/opensky_enrichment_job.yml` | Create — DABs job definition |

## Verification

1. Deploy: `databricks bundle deploy --target dev` — creates tables + job
2. Run: `databricks bundle run opensky_enrichment --target dev`
3. Check phase transitions: `SELECT count(*), to_phase FROM opensky_phase_transitions GROUP BY to_phase`
4. Check gate events: `SELECT gate, event_type, gate_distance_m FROM opensky_gate_events ORDER BY gate_distance_m` — verify distances < 100m
5. Check enriched snapshots: `SELECT count(*), assigned_gate IS NOT NULL as has_gate FROM opensky_enriched_snapshots GROUP BY 2`
6. ML compatibility: Verify enriched JSON can be consumed by `extract_training_data()`
7. Existing tests: `uv run pytest tests/inference/ -v`

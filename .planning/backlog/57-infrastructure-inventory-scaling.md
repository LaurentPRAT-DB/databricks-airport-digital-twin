# Infrastructure Inventory & Scaling Estimate

## 1. Airplane 3D Model Files

Location: `app/frontend/public/models/aircraft/` (7.9 MB total)

| File | Size | Aircraft Types |
|------|------|----------------|
| pan_am_airbus_a310-324.glb | 3.0 MB | A310 |
| cathay_pacific_airbus_a330-300.glb | 1.1 MB | A330, A350, B777, B787 |
| emirates_airbus_a345.glb | 861 KB | Emirates A340/A345 |
| airbus_a345.glb | 825 KB | A340, A345 |
| low-poly_airplane.glb | 479 KB | (unused fallback) |
| air_france_airbus_a318-100.glb | 468 KB | Air France A318-A320 |
| airbus_a320.glb | 424 KB | A318-A321, A310 |
| airbus_a380.glb | 393 KB | A380 |
| generic-jet.glb | 268 KB | DEFAULT fallback |
| boeing-737.glb | 34 KB | B737, B738, B739 |

Loading: `aircraftModels.ts` maps ICAO type codes to GLB URLs via `AIRCRAFT_MODELS` and `AIRLINE_SPECIFIC_MODELS` dicts. `GLTFAircraft.tsx` loads them with Three.js GLTF loader.

---

## 2. Airport Definitions

Not hardcoded — loaded dynamically from:
- **OSM Overpass API** at runtime (gates, terminals, taxiways, aprons per ICAO code)
- **Calibration profiles:** `data/calibration/profiles/` — 1,182 airport JSON profiles (5.8 MB)
- **Calibration raw data:** `data/calibration/raw/` — BTS/OpenSky/OurAirports CSVs (356 MB)
- **Known profiles:** `src/calibration/known_profiles.py` — 33 hand-researched airport stats

---

## 3. Storage Layers

### Layer 1: Unity Catalog (Delta Lake) — serverless

- **Catalog:** `serverless_stable_3n0ihb_catalog.airport_digital_twin`
- **DLT Pipeline:** `[dev] Airport Digital Twin DLT` (triggers every 5 min, serverless)
  - Bronze: `flights_bronze` — raw OpenSky JSON via Auto Loader from `/mnt/airport_digital_twin/raw/opensky/`
  - Silver: `flights_silver` — cleaned/deduped
  - Gold: `flight_status_gold` — aggregated by icao24 with computed flight_phase
  - Baggage Bronze/Silver/Gold — baggage event pipeline (3 tables)
- Also: `flight_positions_history` — append-only trajectory history

### Layer 2: Lakebase Autoscaling (PostgreSQL) — low-latency serving

- **Host:** `ep-summer-scene-d2ew95fl.database.us-east-1.cloud.databricks.com`
- **5 tables** (all airport-scoped):

| Table | PK | Purpose |
|-------|-----|---------|
| flight_status | icao24 | Real-time positions (<10ms) |
| flight_schedule | airport_icao + flight_number + scheduled_time | FIDS display |
| baggage_status | airport_icao + flight_number | Baggage tracking |
| gse_fleet | airport_icao + unit_id | Ground equipment |
| gse_turnaround | airport_icao + icao24 | Turnaround ops |
| weather_observations | station (ICAO) | METAR/TAF |

---

## 4. Sync Job & Pipelines

### Scheduled Jobs

| Job Name | Schedule | What it does |
|----------|----------|--------------|
| Delta to Lakebase Sync | Every minute (`0 * * * * ?`) | Copies Gold Delta → Lakebase PostgreSQL |
| Airport Digital Twin DLT | Every 5 min (continuous=false) | Bronze→Silver→Gold flight + baggage pipeline |
| Realism Scorecard | Weekly Mon 9am PT | Scores synthetic data quality across 7 dimensions |

### On-demand Jobs

| Job Name | Purpose |
|----------|---------|
| Multi-Airport Simulation Batch | 33 airports sequential sim → analysis → OBT model training (12h timeout) |
| Calibration Batch (132 sims) | 33 airports x 4 runs (3 normal + 1 weather), 36h sims (2h timeout) |
| OBT Model Training | CatBoost + scikit-learn model training on sim data, registers in UC |
| OSM Airport Pre-load | Pre-fetches OSM data for 26 airports into UC |
| Unit Test / E2E Smoke Test / Integration Test | Testing jobs on serverless |

---

## 5. Workflow Names (DABs)

All defined in `resources/*.yml`:

1. `airport_dlt_pipeline` — DLT pipeline
2. `delta_lakebase_sync` — sync job
3. `simulation_batch` — multi-airport sim
4. `calibration_batch` — 132 simulation runs
5. `obt_model_training` — ML training
6. `osm_preload` — OSM pre-fetch
7. `realism_scorecard` — quality scorecard
8. `unit_test` / `e2e_smoke_test` / `baggage_pipeline_integration_test` — test jobs

---

## 6. Current Storage Size

| Location | Size | What |
|----------|------|------|
| data/calibration/profiles/ | 5.8 MB | 1,182 airport profiles (JSON) |
| data/calibration/raw/ | 356 MB | BTS/OpenSky/OurAirports raw CSVs |
| data/ total | 478 MB | All calibration + reference data |
| simulation_output/calibrated/ | 809 MB | 10 calibrated simulation JSONs |
| simulation_output/ total | 824 MB | All sim outputs + reports |
| app/frontend/public/models/ | 7.9 MB | 10 GLB aircraft models |
| app/frontend/dist/ | 14 MB | Built frontend bundle |
| Project total | 3.2 GB | Including .git, .venv, .planning |
| Data-only total | ~1.3 GB | calibration + simulation output |

---

## 7. Estimate at 100 Airports

| Component | Current (33 airports) | At 100 airports | Notes |
|-----------|----------------------|-----------------|-------|
| Calibration profiles | 5.8 MB (1,182 profiles already) | ~5.8 MB (already covers 1,182) | Already have most airports |
| Calibration raw data | 356 MB | ~1.1 GB | Linear growth with BTS/OpenSky data |
| Simulation output | 809 MB (10 sims) | ~24 GB (100 x 4 runs x ~60 MB/sim) | Biggest growth driver |
| DLT tables (UC) | ~small (1 airport active) | ~3x if 100 airports active | Depends on concurrent flights |
| Lakebase tables | ~small (flight_status per airport) | ~100x rows per table | Still small — hundreds of flights per airport |
| OSM cache | ~small (26 airports) | ~4x | OSM data is compact |
| Aircraft models | 7.9 MB | 7.9 MB | Same models for all airports |
| Frontend dist | 14 MB | 14 MB | No change |
| **Estimated total data** | **~1.3 GB** | **~25-27 GB** | **Dominated by simulation output** |

The simulation output is the scaling bottleneck. Each 36h sim with 1,000 flights produces ~60-80 MB of JSON. At 100 airports x 4 runs each = 400 sims = ~24-32 GB. The calibration raw data grows linearly but more modestly. Everything else (models, profiles, Lakebase) is negligible.

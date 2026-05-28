# OBT Model Pipeline — Training, Collection & Evaluation

End-to-end documentation for the Off-Block Time (OBT) turnaround prediction model:
how it's trained, how real ADS-B data is collected and enriched, and how to evaluate
the model against real-world observations.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [OBT Model Training](#2-obt-model-training)
3. [Real Data Collection (OpenSky)](#3-real-data-collection-opensky)
4. [Data Ingestion Pipeline](#4-data-ingestion-pipeline)
5. [Enrichment Pipeline](#5-enrichment-pipeline)
6. [Model Evaluation](#6-model-evaluation)
7. [Dependencies & Infrastructure](#7-dependencies--infrastructure)
8. [Step-by-Step Runbook](#8-step-by-step-runbook)

---

## 1. Architecture Overview

```
                        TRAINING PATH
                        =============

  Calibration Profiles          Simulation Configs
  (data/calibration/            (scripts/generate_calibration_batch.py)
   profiles/*.json)                      |
        |                                v
        +---> Simulation Runs (calibration_batch DABs job)
                      |
                      v
              Simulation JSONs
              (UC Volume: /Volumes/.../simulation_data/cal_*.json)
                      |
                      v
              OBT Model Training (obt_model_training DABs job)
                      |
                      v
              UC Model Registry + UC Volume pickles


                     EVALUATION PATH
                     ===============

  OpenSky API  --->  Local Collector  --->  JSONL files
  (REST)             (scripts/               (data/opensky_raw/)
                      opensky_collector.py)        |
                                                   v
                                        Upload to UC Volume
                                        (databricks fs cp)
                                                   |
                                                   v
                                        Ingestion Job (every 15 min)
                                        JSONL -> Delta: opensky_states_raw
                                                   |
                                                   v
                                        Enrichment Job (every 30 min)
                                        Raw states -> OpenSkyEventInferrer
                                        + OSM gate matching
                                                   |
                                                   v
                                        Delta tables:
                                        - opensky_phase_transitions
                                        - opensky_gate_events
                                        - opensky_enriched_snapshots
                                                   |
                                                   v
                                        Evaluation Job (on-demand)
                                        Load model from UC -> compare
                                        predicted vs observed turnarounds
```

---

## 2. OBT Model Training

### 2.1 What the model predicts

The OBT model predicts departure punctuality (AOBT - SOBT offset) — the difference in
minutes between Actual Off-Block Time and Scheduled Off-Block Time. Positive values
indicate late departures. The turnaround model (separate, see `src/ml/turnaround_model.py`)
predicts gate occupancy duration.

The model has three stages for progressive refinement:

| Stage | Horizon | When triggered | Features |
|-------|---------|---------------|----------|
| **T-90** (coarse) | 90 min before departure | Pre-arrival, schedule-only | 15 features |
| **T-park** (refined) | At gate parking | Full gate-side context | 19 features |
| **T-board** (boarding) | ~70% through turnaround | In-progress turnaround | 22 features |

### 2.2 Training data source

Training data comes from **calibrated simulations**, not real flights. Each simulation
produces a JSON file with schedule, phase transitions, gate events, and weather snapshots.

**Generation pipeline:**

1. **Calibration profiles** (UC Volume `calibration_profiles`, fallback: `data/calibration/profiles/*.json`)
   - Hand-researched airport statistics from BTS, OpenSky, OurAirports
   - Provide delay_rate, mean_delay_minutes, runway configs, traffic patterns
   - 1,183 profile files stored in UC Volume; 43 airports with hand-researched known stats

2. **Batch config generation** (`scripts/generate_calibration_batch.py`)
   - 33 airports x 4 runs = 132 simulation tasks
   - 3 normal-day runs per airport (seeds 100/200/300)
   - 1 weather-scenario run per airport (seed 42)
   - Each run: 500 arrivals + 500 departures, 36h duration

3. **Simulation execution** (DABs job: `calibration_batch`)
   - Runs `databricks/notebooks/run_simulation_airport.py` per task
   - Engine: `src/simulation/engine.py`
   - Output: `simulation_output/calibrated/cal_{IATA}_{variant}.json`

4. **Upload to UC Volume**
   ```bash
   databricks fs cp simulation_output/calibrated/ \
       dbfs:/Volumes/serverless_stable_3n0ihb_catalog/airport_digital_twin/simulation_data/ \
       --recursive
   ```

### 2.3 Feature extraction

**File:** `src/ml/obt_features.py`

Key functions:
- `extract_obt_training_data(sim_json_path)` — parses simulation JSON, joins schedule +
  phase_transitions + gate_events + weather to produce feature/target pairs
- `extract_training_data_from_recording(recording_data)` — same logic for enriched
  OpenSky recorded data (in-memory dict)
- `classify_aircraft(type_code)` — maps ICAO type codes to categories: "wide", "narrow", "regional"

**T-park feature set** (19 features):

| Type | Features |
|------|----------|
| Numeric (10) | `hour_of_day`, `arrival_delay_min`, `concurrent_gate_ops`, `wind_speed_kt`, `visibility_sm`, `scheduled_departure_hour`, `day_of_week`, `hour_sin`, `hour_cos`, `scheduled_buffer_min` |
| Categorical (4) | `aircraft_category`, `airline_code`, `gate_id_prefix`, `airport_code` |
| Binary (5) | `is_international`, `is_remote_stand`, `has_active_ground_stop`, `is_weather_scenario`, `is_hub_connecting` |

### 2.4 Training process

**DABs job:** `obt_model_training`
**Notebook:** `databricks/notebooks/train_obt_model.py`

1. Reads simulation JSONs from UC Volume
2. Extracts features + targets via `extract_obt_training_data()`
3. 80/20 train/test split, stratified by airport
4. 5-fold stratified cross-validation
5. Trains CatBoost (preferred) or sklearn HistGradientBoostingRegressor (fallback)
6. Trains P10/P90 quantile models for prediction intervals
7. Applies Conformalized Quantile Regression (CQR) calibration
8. Registers models in UC + saves pickles to UC Volume

**Install deps (on cluster):**
```
%pip install scikit-learn catboost>=1.2 pyyaml pydantic
```

### 2.5 Where models are stored

**UC Model Registry (3-level namespace):**

| Model | UC Name |
|-------|---------|
| T-90 coarse | `serverless_stable_3n0ihb_catalog.airport_digital_twin.obt_coarse_model` |
| T-park refined | `serverless_stable_3n0ihb_catalog.airport_digital_twin.obt_refined_model` |
| T-board | `serverless_stable_3n0ihb_catalog.airport_digital_twin.obt_board_model` |

**UC Volume pickles (backup):**

| Model | Path |
|-------|------|
| Refined | `/Volumes/.../simulation_data/ml_models/obt_refined.pkl` |
| Coarse | `/Volumes/.../simulation_data/ml_models/obt_coarse.pkl` |
| Board | `/Volumes/.../simulation_data/ml_models/obt_board.pkl` |
| Metadata | `/Volumes/.../simulation_data/ml_models/obt_training_metadata.json` |

**MLflow experiment:** `/Users/{username}/airport_dt_obt_three_stage_model`

### 2.6 Training metrics (last run)

- 33 airports, 53,642 training samples
- Baseline MAE (GSE constants): ~15 min
- T-90 MAE: ~10 min
- T-park MAE: 8.39 min
- T-board MAE: ~6 min
- CQR prediction interval coverage: ~80% (P10-P90)

---

## 3. Real Data Collection (OpenSky)

### 3.1 Why collect real data

The model is trained on simulated data. Real ADS-B data from the OpenSky Network
provides ground truth to evaluate model accuracy against actual turnaround durations
observed at real airports.

### 3.2 Local collector

**File:** `scripts/opensky_collector.py`

The OpenSky REST API is **blocked from Databricks compute**. Collection must run locally.

**What it does:**
- Polls `https://opensky-network.org/api/states/all` for aircraft state vectors
- Filters to a bounding box around the target airport
- Enriches with aircraft type (from OpenSky aircraft database, ~30MB CSV, cached 7 days)
- Enriches with airline ICAO code (callsign first 3 chars)
- Writes JSON-lines files to `data/opensky_raw/`

**Usage:**
```bash
# Quick test (2 min)
uv run python scripts/opensky_collector.py --airport EDDF --duration 120

# Full 24h collection for turnaround evaluation
OPENSKY_CLIENT_ID=... OPENSKY_CLIENT_SECRET=... \
    uv run python scripts/opensky_collector.py --airport EDDF --duration 86400 --interval 10

# Multi-airport
uv run python scripts/opensky_collector.py --airports EDDF,EGLL,LFPG --duration 28800
```

**CLI arguments:**

| Arg | Default | Description |
|-----|---------|-------------|
| `--airport` | LSGG | Single ICAO code |
| `--airports` | — | Comma-separated ICAO codes (round-robin) |
| `--interval` | 10s | Seconds between fetches per airport |
| `--duration` | 7200s (2h) | Total collection time (0 = indefinite) |
| `--radius` | 0.5 deg | Bounding box half-size |
| `--output-dir` | `data/opensky_raw` | Output directory |
| `--no-aircraft-db` | false | Skip aircraft type enrichment |

**Authentication (optional but recommended):**
- `OPENSKY_CLIENT_ID` — OAuth2 client ID
- `OPENSKY_CLIENT_SECRET` — OAuth2 client secret
- On Databricks: stored in secret scope `airport-digital-twin` (keys: `opensky-username`, `opensky-password`)

**Output format:** One JSONL file per fetch cycle, named `{ICAO}_{timestamp}.jsonl`.
Each line contains:
```json
{
    "icao24": "3c4b26",
    "callsign": "DLH1234",
    "latitude": 50.0379,
    "longitude": 8.5622,
    "baro_altitude": 0.0,
    "on_ground": true,
    "velocity": 0.0,
    "true_track": 180.0,
    "vertical_rate": 0.0,
    "aircraft_type": "A320",
    "registration": "D-AIBC",
    "airline_icao": "DLH",
    "collection_time": "2026-04-07T09:00:00+00:00",
    "airport_icao": "EDDF",
    "data_source": "opensky_live"
}
```

**20 pre-configured airports** in `AIRPORT_COORDS`:
KSFO, KJFK, KLAX, KORD, KATL, KDEN, KDFW, EGLL, LFPG, UKBB, LEMD, EDDF, LSGG, EHAM, LIRF, LSZH, EIDW, ESSA, LOWW, LPPT

### 3.3 Collection recommendations

| Goal | Duration | Airports | Expected turnarounds |
|------|----------|----------|---------------------|
| Quick test | 2 min | 1 | 0 (just verify connectivity) |
| Short session | 2h | 1 | 5-15 (partial turnarounds) |
| Full evaluation | 24h | 1 | 30-100+ per airport |
| Overnight batch | 8h | 4 | 20-60 per airport |

Turnarounds typically take 30-90 min (narrow-body) or 60-180 min (wide-body).
You need continuous coverage of an aircraft from landing through pushback to capture one.

---

## 4. Data Ingestion Pipeline

### 4.1 Upload to UC Volume

After local collection, upload JSONL files to the Databricks UC Volume:

```bash
databricks fs cp data/opensky_raw/ \
    dbfs:/Volumes/serverless_stable_3n0ihb_catalog/airport_digital_twin/opensky_raw/ \
    --recursive
```

### 4.2 Ingestion job (JSONL to Delta)

**DABs job:** `opensky_ingestion`
**Schedule:** Every 15 minutes
**Notebook:** `databricks/notebooks/load_opensky_from_volume.py`

**What it does:**
1. Lists pending `*.jsonl` files in `/Volumes/.../opensky_raw/`
2. Reads and parses with explicit schema
3. MERGEs into Delta table on natural key `(icao24, collection_time, airport_icao)` — deduplicates on re-upload
4. Moves processed files to `opensky_raw/processed/` subfolder
5. Adds `collection_date` partition column and `_ingested_at` timestamp

**Source:** `/Volumes/serverless_stable_3n0ihb_catalog/airport_digital_twin/opensky_raw/*.jsonl`

**Target:** `serverless_stable_3n0ihb_catalog.airport_digital_twin.opensky_states_raw`

Units in this table are **raw OpenSky units**: velocity in m/s, altitude in meters, vertical_rate in m/s.

---

## 5. Enrichment Pipeline

### 5.1 Enrichment job (Phase inference + Gate assignment)

**DABs job:** `opensky_enrichment`
**Schedule:** Every 30 minutes
**Notebook:** `databricks/notebooks/enrich_opensky_events.py`

**What it does:**
1. Finds unenriched `(airport_icao, collection_date)` pairs in raw table
2. Loads OSM gate positions from `gates` table in UC
3. Per airport/date: groups raw states into time-ordered frames
4. Converts units: m → ft, m/s → kts, m/s → ft/min
5. Runs `OpenSkyEventInferrer` (from `src/inference/opensky_events.py`)
6. Writes results to 3 Delta tables

**Reads:**
- `serverless_stable_3n0ihb_catalog.airport_digital_twin.opensky_states_raw`
- `serverless_stable_3n0ihb_catalog.airport_digital_twin.gates`

**Writes:**

| Delta Table | Content | Key Columns |
|-------------|---------|-------------|
| `opensky_phase_transitions` | Phase changes (parked, taxi, takeoff, landing...) | time, icao24, callsign, from_phase, to_phase, aircraft_type, assigned_gate |
| `opensky_gate_events` | Gate assign/occupy/release | time, icao24, callsign, gate, event_type, gate_distance_m |
| `opensky_enriched_snapshots` | Every state vector with inferred phase + gate | time, icao24, callsign, lat, lon, alt, vel, phase, assigned_gate |

### 5.2 OpenSkyEventInferrer

**File:** `src/inference/opensky_events.py`

Core logic:
- Matches on-ground stationary aircraft to nearest OSM gate via haversine distance
- Gate match radius: 100m
- Stationary threshold: < 2 m/s (≈ 4 kts)
- Tracks per-aircraft state machines detecting phase transitions
- Inferred phases: `parked`, `taxi_to_gate`, `taxi_to_runway`, `takeoff`, `landing`, `approaching`, `departing`, `enroute`
- Snaps parked aircraft positions to gate coordinates for cleaner data

---

## 6. Model Evaluation

### 6.1 Evaluation job

**DABs job:** `opensky_evaluation` (on-demand, no schedule)
**Notebook:** `databricks/notebooks/evaluate_obt_model.py`

**Parameters (Databricks widgets):**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `airport_icao` | EDDF | ICAO code of airport to evaluate |
| `airport_iata` | FRA | IATA code (must match model training) |
| `days` | 7 | Days of enriched data to include |

### 6.2 What it does

1. **Reads** enriched phase transitions from `opensky_phase_transitions` Delta table
2. **Extracts turnarounds**: matches `parked` → `pushback/taxi_to_runway` transition pairs per aircraft. Filters to 10-180 min duration range.
3. **Loads OBT model** from UC Model Registry (`models:/.../obt_refined_model/latest`), falls back to UC Volume pickle, then GSE constants (45/90 min)
4. **Builds features** per turnaround: aircraft category, airline code, gate prefix, hour, weekday, airport IATA
5. **Runs predictions** and computes:
   - MAE (Mean Absolute Error)
   - RMSE (Root Mean Squared Error)
   - Bias (positive = model under-predicts)
   - Prediction interval coverage (% of observed within [P10, P90])
   - Per-category breakdown (narrow/wide/regional)

### 6.3 ICAO to IATA mapping

The model was trained with IATA codes. When evaluating:

| ICAO | IATA | Airport |
|------|------|---------|
| EDDF | FRA | Frankfurt |
| EGLL | LHR | London Heathrow |
| LFPG | CDG | Paris CDG |
| KJFK | JFK | New York JFK |
| KLAX | LAX | Los Angeles |

---

## 7. Dependencies & Infrastructure

### 7.1 Databricks resources

**Catalog:** `serverless_stable_3n0ihb_catalog`
**Schema:** `airport_digital_twin`
**Profile:** `FEVM_SERVERLESS_STABLE`

**Delta Tables:**

| Table | Purpose |
|-------|---------|
| `opensky_states_raw` | Raw ADS-B state vectors from collector |
| `opensky_phase_transitions` | Enriched phase transitions with gate assignments |
| `opensky_gate_events` | Gate assign/occupy/release events |
| `opensky_enriched_snapshots` | Full enriched state vectors |
| `gates` | OSM gate geometry per airport |

**UC Volumes:**

| Volume | Path | Content |
|--------|------|---------|
| `opensky_raw` | `/Volumes/.../opensky_raw/` | Uploaded JSONL files from local collector |
| `simulation_data` | `/Volumes/.../simulation_data/` | Simulation JSONs + trained model pickles |

**UC Model Registry:**

| Model | UC Name |
|-------|---------|
| T-90 coarse | `.../obt_coarse_model` |
| T-park refined | `.../obt_refined_model` |
| T-board | `.../obt_board_model` |

**DABs Jobs:**

| Job | Resource YAML | Schedule |
|-----|--------------|----------|
| `opensky_ingestion` | `resources/opensky_ingestion_job.yml` | Every 15 min (paused by default) |
| `opensky_enrichment` | `resources/opensky_enrichment_job.yml` | Every 30 min (paused by default) |
| `opensky_evaluation` | `resources/opensky_evaluation_job.yml` | On-demand |
| `obt_model_training` | `resources/turnaround_training_job.yml` | On-demand |
| `calibration_batch` | `resources/calibration_batch_job.yml` | On-demand |

### 7.2 Python dependencies

| Package | Used by | Purpose |
|---------|---------|---------|
| `catboost>=1.2` | Training + inference | Gradient boosted trees with native categoricals |
| `scikit-learn` | Training + inference | HistGradientBoostingRegressor fallback, preprocessing |
| `mlflow` | Training + evaluation | Model registry, experiment tracking |
| `httpx` | Local collector | HTTP client for OpenSky API |
| `pydantic` | Feature models | Data validation |
| `pyyaml` | Config loading | Simulation configs |

### 7.3 Key source files

| File | Role |
|------|------|
| `src/ml/obt_model.py` | OBTPredictor, OBTCoarsePredictor, OBTBoardPredictor |
| `src/ml/obt_features.py` | OBTFeatureSet, classify_aircraft(), extract_obt_training_data() |
| `src/inference/opensky_events.py` | OpenSkyEventInferrer (phase + gate inference) |
| `scripts/opensky_collector.py` | Local CLI ADS-B data collector |
| `scripts/generate_calibration_batch.py` | Generate 132-task simulation batch |
| `scripts/evaluate_obt_eddf.py` | Local evaluation script (legacy, prefer notebook) |
| `databricks/notebooks/train_obt_model.py` | Training notebook |
| `databricks/notebooks/load_opensky_from_volume.py` | JSONL ingestion notebook |
| `databricks/notebooks/enrich_opensky_events.py` | Phase/gate enrichment notebook |
| `databricks/notebooks/evaluate_obt_model.py` | Evaluation notebook |

---

## 8. Step-by-Step Runbook

### Phase 1: Train the model (one-time, then retrain as needed)

```bash
# 1. Generate simulation configs
uv run python scripts/generate_calibration_batch.py

# 2. Run simulations on Databricks
databricks bundle deploy --target dev
databricks bundle run calibration_batch --target dev

# 3. Upload simulation output to UC Volume
databricks fs cp simulation_output/calibrated/ \
    dbfs:/Volumes/serverless_stable_3n0ihb_catalog/airport_digital_twin/simulation_data/ \
    --recursive

# 4. Train the model
databricks bundle run obt_model_training --target dev
```

### Phase 2: Collect real data (24h+ recommended)

```bash
# Start local collector (24h for EDDF)
OPENSKY_CLIENT_ID=... OPENSKY_CLIENT_SECRET=... \
    uv run python scripts/opensky_collector.py \
        --airport EDDF --duration 86400 --interval 10 &

# Monitor progress
ls data/opensky_raw/EDDF_*.jsonl | wc -l
du -sh data/opensky_raw/
```

### Phase 3: Ingest and enrich

```bash
# 1. Upload collected JSONL to UC Volume
databricks fs cp data/opensky_raw/EDDF_*.jsonl \
    dbfs:/Volumes/serverless_stable_3n0ihb_catalog/airport_digital_twin/opensky_raw/ \
    --recursive

# 2. Unpause ingestion + enrichment jobs (if paused)
# Or run manually:
databricks bundle run opensky_ingestion --target dev
databricks bundle run opensky_enrichment --target dev
```

### Phase 4: Evaluate

```bash
databricks bundle run opensky_evaluation --target dev
```

Or run with custom parameters:
```bash
databricks bundle run opensky_evaluation --target dev \
    --params airport_icao=EDDF,airport_iata=FRA,days=7
```

**Expected output:** JSON with turnaround count, MAE, RMSE, bias, per-category breakdown.

### Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| 0 JSONL files uploaded | Collection not started | Run local collector first |
| 0 phase transitions | Ingestion/enrichment hasn't run | Check job status, run manually |
| 0 turnarounds | < 1h continuous data per aircraft | Collect 24h+ for full turnarounds |
| High MAE (> 20 min) | Model not trained, using fallback | Check `model_trained` in output, retrain if needed |
| "No SQL warehouses" | Warehouse not running | Start a SQL warehouse in the workspace |
| OpenSky 429 errors | Rate limited | Use authenticated credentials, increase interval |

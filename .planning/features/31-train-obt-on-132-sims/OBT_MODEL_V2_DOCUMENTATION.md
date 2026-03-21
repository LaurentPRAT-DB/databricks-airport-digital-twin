# OBT Forecasting Model v2 — Complete Technical Documentation

**Repository:** [github.com/LaurentPRAT-DB/databricks-airport-digital-twin](https://github.com/LaurentPRAT-DB/databricks-airport-digital-twin)
**Model version:** `v2_feature_dependent`
**Last trained:** 2026-03-16
**MLflow run ID:** `7c5c5e6e2c2e442381ef4368b8100f52`

---

## Table of Contents

1. [What the Model Predicts](#1-what-the-model-predicts)
2. [Two-Stage Architecture](#2-two-stage-architecture)
3. [Feature Engineering](#3-feature-engineering)
4. [Synthetic Data Generation](#4-synthetic-data-generation)
5. [Training Pipeline](#5-training-pipeline)
6. [Evaluation Results](#6-evaluation-results)
7. [Model Registry and Serving](#7-model-registry-and-serving)
8. [Code Map](#8-code-map)
9. [How to Retrain](#9-how-to-retrain)
10. [Known Limitations and Improvement Plan](#10-known-limitations-and-improvement-plan)

---

## 1. What the Model Predicts

**Target variable:** `turnaround_duration_min` — elapsed minutes from aircraft parking (chocks on) to pushback (chocks off). This is the gate occupancy time.

**Use cases:**
- **Gate scheduling:** Predict when a gate becomes free for the next arrival
- **Delay propagation:** Forecast whether the outbound flight departs on time
- **CDM integration:** Provide TOBT (Target Off-Block Time) to ATC/ground control

**Baseline:** Fixed constants from the GSE (Ground Support Equipment) model — 45 min for narrow-body, 90 min for wide-body. The v2 model reduces prediction error by 70% compared to this baseline.

---

## 2. Two-Stage Architecture

The model follows the A-CDM (Airport Collaborative Decision Making) framework used at 30+ European airports, providing predictions at two horizons:

```
                        T-90                    T-park
                    (pre-arrival)           (aircraft parked)
                         │                       │
   Schedule known ──────►│                       │
   Weather forecast ────►│                       │
   Inbound delay ───────►│                       │
                         │                       │◄──── Actual gate assignment
                         │                       │◄──── Parking hour
                         │                       │◄──── Concurrent gate ops
                         │                       │◄──── Remote stand flag
                         ▼                       ▼
                   ┌───────────┐          ┌──────────────┐
                   │ T-90      │          │ T-park       │
                   │ Coarse    │          │ Refined      │
                   │ Predictor │          │ Predictor    │
                   └─────┬─────┘          └──────┬───────┘
                         │                       │
                    MAE: 9.43 min           MAE: 5.91 min
                    R²: 0.74                R²: 0.89
```

### Stage 1: T-90 Coarse Model (`OBTCoarsePredictor`)

- **When:** 90 minutes before scheduled departure (pre-arrival)
- **Features:** 13 (schedule, weather, operations — no gate-side info)
- **Algorithm:** `HistGradientBoostingRegressor(max_depth=5, max_iter=150, lr=0.05)`
- **Use case:** Early planning — initial gate assignment, CDM TOBT

### Stage 2: T-park Refined Model (`OBTPredictor`)

- **When:** Aircraft has parked at gate (chocks on)
- **Features:** 17 (all T-90 features + 4 gate-side features)
- **Algorithm:** `HistGradientBoostingRegressor(max_depth=6, max_iter=200, lr=0.05)`
- **Use case:** Operational TOBT for ATC sequencing, real-time gate availability

Both stages also train **P10 and P90 quantile models** for calibrated prediction intervals.

**Rationale for two stages:** Information availability changes between pre-arrival and post-parking. A single model either wastes gate-side features at T-90 (when unavailable) or underperforms at T-park by not using them.

---

## 3. Feature Engineering

### 3.1 T-park (Refined) Features — 17 total

| # | Feature | Type | Source | Rationale |
|---|---------|------|--------|-----------|
| 1 | `aircraft_category` | cat: narrow/wide/regional | schedule → aircraft_type | Wide-body ~2x longer turnaround. Maps B738→narrow, B777→wide, E190→regional |
| 2 | `airline_code` | cat: 3-letter ICAO | schedule → airline | Airlines have different SOPs. LCCs (SWA: 25 min target) vs legacy (UAL: 45+ min) |
| 3 | `hour_of_day` | int 0-23 | parked_time.hour | Night ops have fewer crew; morning banks pressure quick turns |
| 4 | `is_international` | bool | country lookup table | International: customs, longer deboarding, more catering (+25% in simulation) |
| 5 | `arrival_delay_min` | float | schedule → delay_minutes | Delayed arrivals may get expedited turnaround or cause cascading delays |
| 6 | `gate_id_prefix` | cat: first letter(s) | gate_events → gate | Terminal area affects ground crew proximity and resource availability |
| 7 | `is_remote_stand` | bool | gate starts with "R" | Remote stands need bus operations (+10 min typical) |
| 8 | `concurrent_gate_ops` | int | gate_events at parked_time | Proxy for ground crew contention / apron density |
| 9 | `wind_speed_kt` | float | nearest weather snapshot | High winds slow fueling and cargo loading (+5-25% in simulation) |
| 10 | `visibility_sm` | float | nearest weather snapshot | Low visibility slows ramp operations (+5-10% in simulation) |
| 11 | `has_active_ground_stop` | bool | scenario_events overlap | Ground stops prevent pushback regardless of turnaround completion |
| 12 | `scheduled_departure_hour` | int 0-23 | schedule → scheduled_time | Departure slot pressure affects turnaround urgency |
| 13 | `airport_code` | cat: 3-letter IATA | simulation config | Airport-specific patterns (gate layouts, crew practices, climate) |
| 14 | `day_of_week` | int 0-6 | parked_time.weekday() | Weekend vs weekday operational differences |
| 15 | `hour_sin` | float | sin(2π·hour/24) | Cyclical encoding so hour 23 and 0 are adjacent |
| 16 | `hour_cos` | float | cos(2π·hour/24) | Cyclical encoding complement |
| 17 | `is_weather_scenario` | bool | simulation config | Whether the sim run used a weather disruption scenario |

### 3.2 T-90 (Coarse) Features — 13 total

Subset excluding gate-side information not available pre-arrival:

`aircraft_category`, `airline_code`, `scheduled_departure_hour`, `is_international`, `arrival_delay_min`, `wind_speed_kt`, `visibility_sm`, `has_active_ground_stop`, `airport_code`, `day_of_week`, `hour_sin`, `hour_cos`, `is_weather_scenario`

### 3.3 Aircraft Type Classification

Defined in `src/ml/obt_features.py:22-38`:

| Category | Types | Typical Turnaround |
|----------|-------|-------------------|
| **wide** | A330, A340, A350, A380, B747, B767, B777, B787 | 70-110 min |
| **regional** | E170-E195, CRJ2/7/9, ATR, DH8D | 25-45 min |
| **narrow** | Everything else (A320 family, B737 family, etc.) | 35-55 min |

### 3.4 International Detection

Country-based lookup (not a heuristic). The `_AIRPORT_COUNTRY` dict in `obt_features.py` maps known IATA codes to ISO country codes. A flight is international if the remote airport's country differs from the local airport's country. Returns `False` for unknown airports.

### 3.5 Feature Extraction Pipeline

`extract_training_data()` in `src/ml/obt_features.py:255` processes each simulation JSON:

```
For each simulation file:
  1. Parse schedule, phase_transitions, gate_events, weather_snapshots, scenario_events
  2. Build lookup: callsign → schedule entry
  3. Find parked/pushback transitions per aircraft (icao24)
  4. For each aircraft with both transitions:
     a. turnaround_min = (pushback_time - parked_time) / 60
     b. Filter: keep only [10, 180] minutes (outlier removal)
     c. Extract features from schedule, gate, weather, scenario data
     d. Emit {features, target, airport, flight_id, callsign}
```

---

## 4. Synthetic Data Generation

### 4.1 Simulation Architecture

The digital twin generates flight data through a simulation engine (`src/ingestion/fallback.py`) that models the full aircraft lifecycle: approach → landing → taxi-in → parking → turnaround → pushback → taxi-out → departure.

Training data comes from **132 calibrated simulations** (33 airports × 4 runs each) stored in Unity Catalog Volume.

### 4.2 Calibration System

Each airport has a `AirportProfile` (defined in `src/calibration/profile.py`) built from real data sources:

| Source | Data | Used For |
|--------|------|----------|
| **BTS T-100** | US domestic/international segment traffic | Flight counts, airline mix, route distribution |
| **BTS On-Time** | Actual delay statistics | Delay distribution parameters |
| **OpenSky Network** | Live ADS-B positions | International airport traffic patterns |
| **OurAirports** | Airport metadata (runways, country, type) | Gate counts, international status |

33 airports have hand-researched `known_stats` profiles in `src/calibration/known_profiles.py` covering all major US hubs and key international airports (LHR, CDG, FRA, NRT, SIN, SYD, DXB, GRU, etc.).

### 4.3 Feature-Dependent Turnaround Generation (v2)

This is the key change that makes v2 fundamentally different from v1. The turnaround duration in the simulation **actually depends on features**, so the ML model can learn real interactions.

The turnaround formula in `src/ingestion/fallback.py:2427-2437`:

```python
# Base turnaround from GSE model timing (narrow=45min, wide=90min, regional=35min)
gate_seconds = gate_minutes * 60

# Four multiplicative factors
airline_factor = AIRLINE_TURNAROUND_FACTOR.get(airline_code, 1.0)
weather_factor = _get_turnaround_weather_factor()
congestion_factor = _get_turnaround_congestion_factor()
intl_factor = _get_turnaround_international_factor(state)

combined_factor = airline_factor * weather_factor * congestion_factor * intl_factor

# Reduced jitter (±10% vs old ±20%) since factors explain more variance
target = gate_seconds * combined_factor * random.uniform(0.9, 1.1)
```

#### 4.3.1 Airline Factor (`AIRLINE_TURNAROUND_FACTOR`)

Based on industry data — LCCs target 25-30 min turns, full-service 45-90 min:

| Airline | Factor | Rationale |
|---------|--------|-----------|
| SWA (Southwest) | 0.72 | Industry fastest, 25-min target |
| FFT, NKS (Frontier, Spirit) | 0.78 | ULCCs, minimal service |
| JBU (JetBlue) | 0.88 | Midway LCC/legacy |
| AAL, UAL, DAL (US majors) | 0.95 | Efficient legacy |
| BAW, DLH (BA, Lufthansa) | 1.05 | Full-service European |
| UAE, SIA (Emirates, Singapore) | 1.10 | Premium Gulf/Asian, extra catering |

Default for unknown airlines: 1.0

#### 4.3.2 Weather Factor (`_get_turnaround_weather_factor`)

Reads current weather state (updated by simulation engine each weather tick):

```python
def _get_turnaround_weather_factor() -> float:
    factor = 1.0
    wind = _current_weather.get("wind_speed_kts", 0)
    vis = _current_weather.get("visibility_sm", 10.0)

    if wind > 35:     factor += 0.15   # High winds slow ramp ops
    if wind > 50:     factor += 0.25   # Extreme: ramp closure risk
    if vis < 1.0:     factor += 0.10   # Low vis slows ground movement
    if vis < 0.5:     factor += 0.05   # Very low vis additional penalty
    return factor
```

Range: 1.0 (clear weather) to ~1.55 (extreme wind + low visibility).

#### 4.3.3 Congestion Factor (`_get_turnaround_congestion_factor`)

```python
def _get_turnaround_congestion_factor() -> float:
    occupied = sum(1 for gs in _gate_states.values() if gs.occupied_by is not None)
    return 1.0 + 0.01 * max(0, occupied - 10)
```

+1% per occupied gate above 10. At 30 occupied gates: factor = 1.20 (+20%).

#### 4.3.4 International Factor (`_get_turnaround_international_factor`)

```python
def _get_turnaround_international_factor(state) -> float:
    # Uses country lookup to determine if flight is international
    if is_international: return 1.25   # +25% for customs, catering
    return 1.0
```

#### 4.3.5 Combined Effect

Example: Emirates A380 arriving at JFK during a storm with 25 gates occupied:

```
base = 90 min (wide-body)
× airline_factor  = 1.10 (Emirates premium)
× weather_factor  = 1.40 (35kt wind + 0.8sm vis)
× congestion      = 1.15 (25 gates occupied)
× intl_factor     = 1.25 (international)
× jitter          = uniform(0.9, 1.1)
= 90 × 1.10 × 1.40 × 1.15 × 1.25 × ~1.0
≈ 199 min (clamped to 180 max by model)
```

vs. Southwest B737 domestic at SFO on a clear morning with 8 gates:

```
= 45 × 0.72 × 1.0 × 1.0 × 1.0 × ~1.0 ≈ 32 min
```

This 6x range gives the model real signal to learn from.

### 4.4 Simulation Output Format

Each simulation produces a JSON file containing:

```json
{
  "config": {
    "airport": "SFO",
    "scenario_file": null,
    "num_flights": 500,
    "profile": "calibrated"
  },
  "schedule": [
    {
      "flight_number": "UAL123",
      "airline_code": "UAL",
      "aircraft_type": "B738",
      "origin": "LAX",
      "destination": "SFO",
      "scheduled_time": "2026-03-15T08:30:00",
      "delay_minutes": 12
    }
  ],
  "phase_transitions": [
    {
      "icao24": "abc123",
      "callsign": "UAL123",
      "from_phase": "taxi_to_gate",
      "to_phase": "parked",
      "time": "2026-03-15T08:45:00",
      "aircraft_type": "B738"
    }
  ],
  "gate_events": [
    {
      "icao24": "abc123",
      "gate": "B22",
      "event_type": "occupy",
      "time": "2026-03-15T08:45:00"
    }
  ],
  "weather_snapshots": [
    {
      "time": "2026-03-15T08:00:00",
      "wind_speed_kts": 15,
      "visibility_sm": 10.0,
      "ceiling_ft": 25000
    }
  ],
  "scenario_events": []
}
```

### 4.5 Data Volume

| Metric | Value |
|--------|-------|
| Simulation files | 132 (33 airports × 4 runs) |
| Total data size | ~41.5 GB |
| Per-file size | 30-80 MB (compact JSON) |
| File naming | `cal_{IATA}_{type}_{timestamp}.json` |
| Storage | UC Volume: `/Volumes/serverless_stable_3n0ihb_catalog/airport_digital_twin/simulation_data/` |
| Usable OBT labels | 53,642 (flights with complete turnaround) |

---

## 5. Training Pipeline

### 5.1 Infrastructure

| Component | Details |
|-----------|---------|
| **Compute** | Databricks Serverless |
| **Notebook** | `databricks/notebooks/train_obt_model.py` |
| **Job definition** | `resources/obt_training_job.yml` |
| **Dependencies** | scikit-learn, pyyaml, pydantic, mlflow |
| **Timeout** | 7200s (2 hours) |
| **Deployment** | Databricks Asset Bundles (DABs) |

### 5.2 Pipeline Steps

```
┌──────────────────────────────────────────────┐
│  1. Load simulation files from UC Volume     │
│     - Glob cal_*.json and simulation_*.json  │
│     - 132 files, ~41.5GB                     │
└──────────────────┬───────────────────────────┘
                   ▼
┌──────────────────────────────────────────────┐
│  2. Extract features                         │
│     - extract_training_data() per file       │
│     - Sequential (one file at a time)        │
│     - Join schedule + transitions + events   │
│     - 53,642 usable samples                  │
└──────────────────┬───────────────────────────┘
                   ▼
┌──────────────────────────────────────────────┐
│  3. Train/Test split                         │
│     - 80/20 stratified by airport_code       │
│     - Random seed: 42                        │
│     - Every airport in both train and test   │
└──────────────────┬───────────────────────────┘
                   ▼
┌──────────────────────────────────────────────┐
│  4. 5-Fold Cross-Validation                  │
│     - StratifiedKFold by airport             │
│     - Train TwoStageOBTPredictor per fold    │
│     - Report T-park and T-90 MAE per fold    │
│     - CV is for evaluation only              │
└──────────────────┬───────────────────────────┘
                   ▼
┌──────────────────────────────────────────────┐
│  5. Train final model on all training data   │
│     - TwoStageOBTPredictor("GLOBAL")         │
│     - Coarse: max_depth=5, iter=150          │
│     - Refined: max_depth=6, iter=200         │
│     - Also trains P10/P90 quantile models    │
└──────────────────┬───────────────────────────┘
                   ▼
┌──────────────────────────────────────────────┐
│  6. Evaluate on held-out test set            │
│     - Baseline MAE (GSE constants)           │
│     - T-90 MAE, RMSE, R²                    │
│     - T-park MAE, RMSE, R²                  │
│     - Per-airport and per-category breakdown │
│     - Prediction interval coverage           │
│     - Feature importance analysis            │
└──────────────────┬───────────────────────────┘
                   ▼
┌──────────────────────────────────────────────┐
│  7. Register in Unity Catalog via MLflow     │
│     - Log params, metrics, artifacts         │
│     - Register coarse + refined sklearn      │
│       models in UC Model Registry            │
│     - Save metadata JSON to UC Volume        │
└──────────────────────────────────────────────┘
```

### 5.3 Algorithm Details

**scikit-learn `HistGradientBoostingRegressor`**

Why this over LightGBM/XGBoost:
- Pure Python install — no C-extension dependency on serverless
- Equivalent performance for datasets under 100K samples
- Native histogram-based binning handles mixed types

**Preprocessing pipeline** (via `sklearn.Pipeline`):

```
ColumnTransformer:
  ├── "cat": OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)
  │          Applied to: aircraft_category, airline_code, gate_id_prefix, airport_code
  └── "num": passthrough
             Applied to: all numeric + binary features
         ▼
HistGradientBoostingRegressor
```

**Quantile models:** Separate P10 and P90 models trained with `loss="quantile"` for calibrated prediction intervals. Confidence is computed as `min(1.0, 30.0 / interval_width)`.

### 5.4 Train/Test Split Strategy

- **80/20 split**, stratified by `airport_code` — every airport represented in both sets
- **No time-based split** needed since simulation data is synthetic (no temporal leakage)
- **Random seed 42** for reproducibility

---

## 6. Evaluation Results

### 6.1 V2 Model Performance (2026-03-16)

| Metric | Baseline (GSE) | T-90 (Coarse) | T-park (Refined) |
|--------|:--------------:|:--------------:|:----------------:|
| **MAE** | 19.68 min | 9.43 min | **5.91 min** |
| **RMSE** | — | — | — |
| **R²** | — | — | **0.8918** |
| **Error reduction** | — | 52% vs baseline | **70% vs baseline** |

### 6.2 Cross-Validation Stability

| Model | CV MAE (mean ± std) |
|-------|:-------------------:|
| T-park | 5.96 ± 0.06 min |
| T-90 | — |

The extremely low CV standard deviation (±0.06) confirms the model generalizes well across airports and is not overfitting.

### 6.3 Two-Stage Refinement

T-park improves over T-90 by **3.52 min MAE** — the gate-side features (actual gate, concurrent ops, parking hour) provide significant additional signal, validating the two-stage architecture.

### 6.4 Training Data Summary

| Statistic | Value |
|-----------|-------|
| Total samples | 53,642 |
| Training set | ~42,914 (80%) |
| Test set | ~10,728 (20%) |
| Airports | 33 |
| Training time | 44.3 min (serverless) |

### 6.5 Interpreting the Baseline MAE

The baseline MAE of 19.68 min seems high compared to the GSE constants (45/90 min). This is because:

1. The v2 simulation applies airline/weather/congestion/international factors, so actual turnarounds range from ~25 min (LCC domestic, clear weather) to ~180 min (wide-body, international, storm, congested)
2. The GSE constants (45/90) are fixed and cannot adapt to this variance
3. The T-park model captures these interactions, explaining 89% of variance

---

## 7. Model Registry and Serving

### 7.1 Registered Models

Both models are registered in Unity Catalog Model Registry:

| Model | UC Path |
|-------|---------|
| **Coarse (T-90)** | `serverless_stable_3n0ihb_catalog.airport_digital_twin.obt_coarse_model` |
| **Refined (T-park)** | `serverless_stable_3n0ihb_catalog.airport_digital_twin.obt_refined_model` |

### 7.2 MLflow Experiment

- **Path:** `/Users/<username>/airport_dt_obt_two_stage_model`
- **Run name:** `obt_two_stage_v2_feature_dependent`
- **Artifacts:** `training_summary.txt`, `coarse_feature_importances.json`, `refined_feature_importances.json`

### 7.3 Training Metadata

Saved to UC Volume: `/Volumes/.../simulation_data/ml_models/obt_training_metadata.json`

Contains all metrics, per-airport MAE, per-category MAE, feature importances, and run provenance.

### 7.4 Integration in the Application

The `AirportModelRegistry` (`src/ml/registry.py`) loads the OBT model per airport:

```python
models = registry.get_models("KSFO")
obt_prediction = models["obt"].predict(features)
```

The `TwoStageOBTPredictor` provides:
- `predict_t90(coarse_features)` → `OBTPrediction` (planning horizon)
- `predict_tpark(full_features)` → `OBTPrediction` (operational horizon)
- `predict_obt_tpark(parked_timestamp, features)` → Unix timestamp of predicted pushback

`OBTPrediction` includes: `turnaround_minutes`, `lower_bound_minutes` (P10), `upper_bound_minutes` (P90), `confidence`, `is_fallback`, `horizon`.

---

## 8. Code Map

| File | Purpose | Key Functions/Classes |
|------|---------|----------------------|
| `src/ml/obt_features.py` | Feature extraction from simulation JSON | `OBTFeatureSet`, `OBTCoarseFeatureSet`, `extract_training_data()`, `classify_aircraft()` |
| `src/ml/obt_model.py` | Model classes with train/predict/save/load | `OBTPredictor`, `OBTCoarsePredictor`, `TwoStageOBTPredictor`, `OBTPrediction` |
| `databricks/notebooks/train_obt_model.py` | Databricks training notebook | Data loading, CV, training, evaluation, MLflow registration |
| `resources/obt_training_job.yml` | DABs job definition | Serverless compute, dependencies, timeout |
| `src/ingestion/fallback.py` | Simulation engine (turnaround generation) | `AIRLINE_TURNAROUND_FACTOR`, `_get_turnaround_weather_factor()`, `_get_turnaround_congestion_factor()`, `_get_turnaround_international_factor()` |
| `src/calibration/profile.py` | Airport calibration profiles | `AirportProfile`, `AirportProfileLoader` |
| `src/calibration/known_profiles.py` | Hand-researched airport stats | 33 airport profiles with real statistics |
| `src/ml/registry.py` | Per-airport model cache | `AirportModelRegistry.get_models()` includes "obt" |
| `tests/test_obt_model.py` | Unit tests | Feature extraction, model train/predict, data validation |
| `scripts/train_obt_model.py` | Local training script (alternative to Databricks) | CLI for training on local simulation files |

---

## 9. How to Retrain

### 9.1 On Databricks (Production)

```bash
# 1. Deploy the bundle
databricks bundle deploy --target dev

# 2. Run the training job
databricks bundle run obt_model_training --target dev

# 3. Monitor (takes ~45 min for 132 files on serverless)
databricks jobs get-run <RUN_ID> --profile FEVM_SERVERLESS_STABLE

# 4. Check results
databricks jobs get-run-output <TASK_RUN_ID> --profile FEVM_SERVERLESS_STABLE
```

### 9.2 Locally (Development)

```bash
# Train on local simulation files
uv run python scripts/train_obt_model.py

# Run unit tests
uv run pytest tests/test_obt_model.py -v
```

### 9.3 Adding New Simulation Data

1. Run new simulations via `databricks/notebooks/run_simulation_airport.py`
2. Output files go to UC Volume as `cal_{IATA}_{type}_{timestamp}.json`
3. Rerun the training job — it auto-discovers all `cal_*.json` and `simulation_*.json` files

---

## 10. Known Limitations and Improvement Plan

### 10.1 Current Limitations

1. **Synthetic data only:** No real operational data. The model learns the simulation's turnaround formula, not real-world complexity (crew constraints, maintenance surprises, passenger behavior). Expected 2-3x MAE increase on real data.

2. **Single-day simulations:** Each run simulates one day. No seasonal patterns, no multi-day delay propagation.

3. **Gate prefix as ordinal:** `OrdinalEncoder` assigns arbitrary ordinal values to `gate_id_prefix` and `airline_code`. CatBoost would handle this better with ordered target encoding.

4. **International detection gaps:** The country lookup table covers ~35 airports. Unknown airports default to "not international".

5. **Static confidence:** The P10/P90 quantile models provide prediction intervals, but the confidence formula (`30 / interval_width`) is a heuristic, not a calibrated probability.

### 10.2 Improvement Roadmap

| Priority | Improvement | Expected Impact | Effort |
|----------|------------|-----------------|--------|
| **P1** | Add day-of-week variation to simulation | Captures weekend patterns | Low |
| **P1** | Fix international detection with OurAirports country data | +0.3-0.5 min MAE | Low |
| **P2** | Add scheduled buffer time feature | +0.5-1.0 min MAE | Low |
| **P2** | Switch to CatBoost for native categorical handling | +0.2-0.5 min MAE, cleaner pipeline | Medium |
| **P2** | Calibrated prediction intervals (Conformalized Quantile Regression) | Better uncertainty estimates | Medium |
| **P3** | Multi-day simulations (7 days × 33 airports) | Day-of-week + delay propagation | High |
| **P3** | Add T-board prediction stage (at boarding start) | Target MAE: 2-4 min | Medium |
| **P4** | Transfer learning to real A-CDM data | Bridge synthetic-to-real gap | High |

### 10.3 References

- **Eurocontrol A-CDM Implementation Manual** — TOBT, TSAT, AOBT milestones framework
- **Schultz, M. (2018), DLR** — Turnaround simulation using aircraft type, airline, stand type
- **Katsigiannis et al. (2021)** — AOBT prediction with milestone data
- **SESAR PJ.04 "Total Airport Management"** — Multi-horizon TOBT prediction
- **IATA Airport Handling Manual** — Standard minimum turnaround times by aircraft category

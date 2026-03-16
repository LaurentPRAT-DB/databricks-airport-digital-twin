# Phase 31: Train OBT Model on 132 Calibrated Simulations (Databricks)

## Goal

Retrain the OBT (Off-Block Time) forecasting model using the full corpus of 132 calibrated simulations (~41.5GB), replacing the previous model trained on only 10 airport runs.

## Status: Plan — Not Started

## Prerequisites: Phase 30 (132 Calibrated Simulations) must be complete — all 132 simulation outputs must be in UC Volume.

---

## Context

132 calibrated simulations (33 airports x 4 runs) completed successfully, producing ~41.5GB of training data in UC Volume (`/Volumes/serverless_stable_3n0ihb_catalog/airport_digital_twin/simulation_data/`). Files are named `cal_{iata}_{type}_{timestamp}.json`.

The training notebook (`databricks/notebooks/train_obt_model.py`) and job definition (`resources/obt_training_job.yml`) already exist with a complete pipeline: data loading, feature extraction, two-stage model training (T-90 coarse + T-park refined), MLflow logging, and UC Model Registry registration.

One fix needed: The file filter only matches `simulation_*.json` — must include `cal_*.json` files too.

---

## Changes

### 1. Update file filter in `databricks/notebooks/train_obt_model.py` (line 62-65)

**Current:**
```python
sim_files = sorted([
    f for f in os.listdir(VOLUME_PATH)
    if f.startswith("simulation_") and f.endswith(".json")
])
```

**New:**
```python
sim_files = sorted([
    f for f in os.listdir(VOLUME_PATH)
    if f.endswith(".json") and (f.startswith("simulation_") or f.startswith("cal_"))
])
```

This picks up both legacy `simulation_*.json` and new `cal_*.json` files. No other code changes needed — `extract_training_data()` reads the `airport` field from each JSON's config dict, so it handles any filename.

### 2. Memory consideration

`extract_training_data()` (`src/ml/obt_features.py:231`) loads each JSON fully via `json.load(f)`. Files are 30-80MB each (compact JSON). Processing is sequential (one file at a time), so peak memory is ~1 file + extracted features. Serverless compute has sufficient memory for this. No changes needed.

### 3. No other modifications

Everything else is already wired:
- **Feature extraction:** `src/ml/obt_features.py` — joins schedule/phase_transitions/gate_events/weather to produce OBT features
- **Model training:** `src/ml/obt_model.py` — `TwoStageOBTPredictor` with `HistGradientBoostingRegressor`
- **MLflow + UC Registry:** Notebook registers both `obt_coarse_model` and `obt_refined_model` in UC
- **Job definition:** `resources/obt_training_job.yml` — single-task job with scikit-learn dependency

---

## Deploy and Run

```bash
databricks bundle deploy --target dev
databricks bundle run obt_model_training --target dev
```

---

## Verification

1. Job completes with status PASS
2. MLflow experiment at `/Users/.../airport-digital-twin/obt_two_stage_model` shows metrics:
   - Baseline MAE (GSE constants) vs T-90 MAE vs T-park MAE
   - R² score, per-airport MAE, per-category MAE
3. UC Model Registry has two new model versions:
   - `serverless_stable_3n0ihb_catalog.airport_digital_twin.obt_coarse_model`
   - `serverless_stable_3n0ihb_catalog.airport_digital_twin.obt_refined_model`
4. Training metadata saved to UC Volume at `simulation_data/ml_models/obt_training_metadata.json`
5. Notebook exit JSON includes `n_samples`, `tpark_mae`, `tpark_r2`

---

## Files Modified

| File | Change |
|------|--------|
| `databricks/notebooks/train_obt_model.py` | Update file filter to include `cal_*.json` |

## Estimated Scope

- **Lines changed:** ~2 (file filter update)
- **Risk:** Low — single filter change, all pipeline infrastructure already tested with 10-airport batch.

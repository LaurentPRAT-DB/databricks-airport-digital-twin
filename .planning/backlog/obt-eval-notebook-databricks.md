# Plan: OBT Model Evaluation Notebook (Databricks-native)

**Status:** Backlog
**Date added:** 2026-04-07
**Depends on:** Batch OpenSky Event Enrichment Job
**Scope:** Databricks notebook + DABs job for OBT model evaluation against real ADS-B data

---

## Context

The OBT model evaluation should run natively on Databricks — the enriched data (phase transitions with gate assignments) lives in Lakehouse Delta tables, and the trained model is registered in Unity Catalog. No reason to pull data to a local machine.

The enrichment pipeline writes to `opensky_phase_transitions` with: `time`, `icao24`, `callsign`, `from_phase`, `to_phase`, `aircraft_type`, `assigned_gate`.

The trained OBT model (CatBoost) is registered in UC Model Registry as `serverless_stable_3n0ihb_catalog.airport_digital_twin.obt_refined_model`.

## Files to Create

### 1. `databricks/notebooks/evaluate_obt_model.py`

Databricks notebook that:

**Cell 1** — Header markdown: Title + description.

**Cell 2** — Install deps + restart:

```python
%pip install scikit-learn catboost>=1.2 pyyaml pydantic --quiet
dbutils.library.restartPython()
```

**Cell 3** — Bundle root + sys.path: Same pattern as `enrich_opensky_events.py:17-29`.

**Cell 4** — Configuration:

- Catalog/schema constants
- `PHASE_TABLE = f"{CATALOG}.{SCHEMA}.opensky_phase_transitions"`
- Load model from UC Model Registry via `mlflow.sklearn.load_model(f"models:/{CATALOG}.{SCHEMA}.obt_refined_model/latest")`
- Fallback: load pickle from UC Volume at `/Volumes/{CATALOG}/{SCHEMA}/simulation_data/ml_models/obt_refined.pkl`
- Widgets: `airport_icao` (default "EDDF"), `airport_iata` (default "FRA"), `days` (default "7")

**Cell 5** — Load phase transitions from Delta:

```sql
SELECT time, icao24, callsign, from_phase, to_phase, aircraft_type, assigned_gate
FROM {PHASE_TABLE}
WHERE airport_icao = '{airport_icao}'
  AND collection_date >= date_sub(current_date(), {days})
ORDER BY time, icao24
```

**Cell 6** — Extract turnarounds: Reuse parked→departure matching logic from `scripts/evaluate_obt_eddf.py:412-434`. Filter 10-180 min range (matching `obt_features.py` constants).

**Cell 7** — Load trained OBT model from UC:

```python
import mlflow
mlflow.set_registry_uri("databricks-uc")

# Try UC Model Registry first
try:
    model_uri = f"models:/{CATALOG}.{SCHEMA}.obt_refined_model/latest"
    loaded_pipeline = mlflow.sklearn.load_model(model_uri)
    # Wrap in OBTPredictor
except:
    # Fallback: load pickle from UC Volume
    predictor = OBTPredictor()
    predictor.load(f"/Volumes/{CATALOG}/{SCHEMA}/simulation_data/ml_models/obt_refined.pkl")
```

**Cell 8** — Build features + predict: Reuse `build_feature_set()` from `scripts/evaluate_obt_eddf.py:248-289` using `classify_aircraft()` and `OBTFeatureSet` from `src/ml/obt_features.py`.

**Cell 9** — Results table + metrics:

- Comparison table: callsign, gate, type, observed, predicted, error, fallback
- MAE, RMSE, bias
- Per-category breakdown (narrow/wide/regional)
- Display as Spark DataFrame for notebook rendering

**Cell 10** — Exit with summary JSON.

### 2. `resources/opensky_evaluation_job.yml`

On-demand job (no schedule, manual trigger) following `opensky_enrichment_job.yml` pattern.

## Key Code to Reuse (not rewrite)

| What | Source |
|------|--------|
| `OBTPredictor` + `.load()` + `.predict()` | `src/ml/obt_model.py:309-593` |
| `OBTFeatureSet` dataclass | `src/ml/obt_features.py` |
| `classify_aircraft()` | `src/ml/obt_features.py:72-84` |
| `build_feature_set()` logic | `scripts/evaluate_obt_eddf.py:248-289` |
| Turnaround extraction | `scripts/evaluate_obt_eddf.py:412-434` |
| Notebook bundle_root pattern | `databricks/notebooks/enrich_opensky_events.py:17-29` |

## Verification

```bash
databricks bundle deploy --target dev
databricks bundle run opensky_evaluation --target dev
```

Expected: JSON with `n_turnarounds`, `MAE`, `RMSE`, `bias`. With 24h+ continuous EDDF data, expect 30-100+ turnarounds.

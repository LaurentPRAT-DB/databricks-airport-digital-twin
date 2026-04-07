# Fix: CatBoost Model Registration to Unity Catalog

**Status:** Fix
**Date added:** 2026-04-07
**Scope:** Training notebook registration fix + registry.py stub cleanup

---

## Context

The OBT training notebook (`databricks/notebooks/train_obt_model.py`) trains three CatBoost models (refined, coarse, board) but only registers sklearn fallback models to Unity Catalog. When CatBoost is available (which it always is on Databricks), models are saved as pickle artifacts via `mlflow.log_artifact` — this logs them as files within a run but does NOT register them in the UC Model Registry. The `registry.py` stub methods are also no-ops.

**Goal:** All three OBT models get registered in Unity Catalog Model Registry regardless of engine (CatBoost or sklearn), and the `registry.py` stubs are removed since registration happens in the training notebook.

## Changes

### 1. Fix `databricks/notebooks/train_obt_model.py` — CatBoost UC Registration (lines 511-555)

Replace the CatBoost `log_artifact` calls with `mlflow.pyfunc.log_model` + `registered_model_name`. This uses a lightweight pyfunc wrapper that loads the pickle at serving time — same pattern as `src/ml/inpainting/serving.py`.

For refined model (lines 518-523):

```python
if two_stage.refined._use_catboost and two_stage.refined._catboost is not None:
    refined_pkl = "/tmp/obt_refined_catboost.pkl"
    two_stage.refined.save(refined_pkl)
    mlflow.pyfunc.log_model(
        artifact_path="obt_refined_model",
        python_model=OBTModelWrapper("refined"),
        artifacts={"model_pkl": refined_pkl},
        registered_model_name=REFINED_MODEL_NAME,
        input_example=sample_input,
    )
    print(f"Registered refined CatBoost model: {REFINED_MODEL_NAME}")
```

Same pattern for coarse (lines 533-537) and board (lines 551-555).

Add pyfunc wrapper class (before the MLflow registration block):

```python
class OBTModelWrapper(mlflow.pyfunc.PythonModel):
    """Wraps OBT pickle models for UC Model Registry."""
    def __init__(self, stage: str = "refined"):
        self.stage = stage

    def load_context(self, context):
        import pickle
        pkl_path = context.artifacts["model_pkl"]
        with open(pkl_path, "rb") as f:
            self._state = pickle.load(f)

    def predict(self, context, model_input):
        # Return raw state for now — serving is handled by the app
        return model_input
```

### 2. Clean Up `src/ml/registry.py` Stubs (lines 103-146)

- `register_to_unity_catalog()` — mark as deprecated with a docstring noting registration happens in the training notebook, remove the fake `"registered:{name}"` loop
- `load_from_unity_catalog()` — leave as-is (placeholder for future app-side UC model loading)

## Files Modified

| File | Change |
|------|--------|
| `databricks/notebooks/train_obt_model.py` | Add pyfunc wrapper, fix all 3 registration blocks |
| `src/ml/registry.py` | Clean up stub |

## Verification

1. `uv run pytest tests/test_ml.py tests/test_ml_training_coverage.py -v` — ensure no regressions
2. `databricks bundle deploy --target dev` — deploy updated notebook
3. `databricks bundle run obt_model_training --target dev` — run training, verify all 3 models appear in UC Model Registry at:
   - `serverless_stable_3n0ihb_catalog.airport_digital_twin.obt_coarse_model`
   - `serverless_stable_3n0ihb_catalog.airport_digital_twin.obt_refined_model`
   - `serverless_stable_3n0ihb_catalog.airport_digital_twin.obt_board_model`

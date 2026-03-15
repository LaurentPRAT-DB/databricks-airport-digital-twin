# Databricks notebook source
# MAGIC %md
# MAGIC # OBT Model Training Pipeline
# MAGIC Trains the two-stage OBT (Off-Block Time) forecasting model on calibrated
# MAGIC simulation data stored in Unity Catalog Volume.
# MAGIC
# MAGIC **Two-stage approach:**
# MAGIC 1. **T-90 coarse model** — pre-arrival features only (schedule + weather)
# MAGIC 2. **T-park refined model** — full gate-side features (after aircraft parks)
# MAGIC
# MAGIC Registers models in Unity Catalog Model Registry via MLflow.

# COMMAND ----------

%pip install scikit-learn pyyaml pydantic --quiet

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import os, sys, json, time
import numpy as np

# Bundle root (notebook is at .../files/databricks/notebooks/train_obt_model.py)
nb_path = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
ws_path = "/Workspace" + nb_path
bundle_root = os.path.dirname(os.path.dirname(os.path.dirname(ws_path)))
print(f"Bundle root: {bundle_root}")
sys.path.insert(0, bundle_root)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

UC_CATALOG = "serverless_stable_3n0ihb_catalog"
UC_SCHEMA = "airport_digital_twin"
UC_VOLUME = "simulation_data"
VOLUME_PATH = f"/Volumes/{UC_CATALOG}/{UC_SCHEMA}/{UC_VOLUME}"

# UC Model Registry names (3-level namespace)
COARSE_MODEL_NAME = f"{UC_CATALOG}.{UC_SCHEMA}.obt_coarse_model"
REFINED_MODEL_NAME = f"{UC_CATALOG}.{UC_SCHEMA}.obt_refined_model"

# MLflow experiment (workspace-scoped)
EXPERIMENT_NAME = f"/Users/{dbutils.notebook.entry_point.getDbutils().notebook().getContext().userName().get()}/airport-digital-twin/obt_two_stage_model"

MIN_SIMULATION_FILES = 3  # Minimum files to proceed (soft threshold)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load Training Data from UC Volume

# COMMAND ----------

# List simulation files in the volume
sim_files = sorted([
    f for f in os.listdir(VOLUME_PATH)
    if f.startswith("simulation_") and f.endswith(".json")
])
print(f"Found {len(sim_files)} simulation files in UC Volume:")
for f in sim_files:
    size_mb = os.path.getsize(os.path.join(VOLUME_PATH, f)) / (1024 * 1024)
    print(f"  {f} ({size_mb:.1f} MB)")

if len(sim_files) < MIN_SIMULATION_FILES:
    msg = f"Only {len(sim_files)} simulation files (need >={MIN_SIMULATION_FILES}). Skipping training."
    print(f"WARNING: {msg}")
    dbutils.notebook.exit(json.dumps({"status": "SKIP", "reason": msg}))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Extract Features

# COMMAND ----------

from src.ml.obt_features import extract_training_data

all_data = []
for fname in sim_files:
    path = os.path.join(VOLUME_PATH, fname)
    print(f"  Extracting from {fname}...", end=" ")
    samples = extract_training_data(path)
    print(f"{len(samples)} samples")
    all_data.extend(samples)

print(f"\nTotal training samples: {len(all_data)}")

# Quick data summary
airports = set(d["airport"] for d in all_data)
categories = {}
for d in all_data:
    cat = d["features"]["aircraft_category"]
    categories[cat] = categories.get(cat, 0) + 1
print(f"Airports: {sorted(airports)}")
print(f"Categories: {categories}")
print(f"Target range: {min(d['target'] for d in all_data):.1f} - {max(d['target'] for d in all_data):.1f} min")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Train/Test Split

# COMMAND ----------

rng = np.random.RandomState(42)
by_airport = {}
for d in all_data:
    by_airport.setdefault(d.get("airport", "UNK"), []).append(d)

train_data, test_data = [], []
for airport, samples in by_airport.items():
    rng.shuffle(samples)
    n_test = max(1, int(len(samples) * 0.2))
    test_data.extend(samples[:n_test])
    train_data.extend(samples[n_test:])

print(f"Train: {len(train_data)}, Test: {len(test_data)}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Train Two-Stage Model

# COMMAND ----------

from src.ml.obt_model import (
    TwoStageOBTPredictor,
    OBTPredictor,
    OBTCoarsePredictor,
    _dict_to_feature_set,
    _dict_to_coarse_feature_set,
)

two_stage = TwoStageOBTPredictor(airport_code="GLOBAL")
train_features = [_dict_to_feature_set(d["features"]) for d in train_data]
train_targets = [d["target"] for d in train_data]

start_time = time.time()
train_result = two_stage.train(train_features, train_targets)
train_elapsed = time.time() - start_time

print(f"Training completed in {train_elapsed:.1f}s")
print(f"  Coarse (T-90):   {train_result['coarse']['status']}")
print(f"  Refined (T-park): {train_result['refined']['status']}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Evaluate

# COMMAND ----------

def compute_metrics(targets, preds, data):
    targets_arr = np.array(targets)
    preds_arr = np.array(preds)
    errors = targets_arr - preds_arr
    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(errors**2)))
    ss_res = float(np.sum(errors**2))
    ss_tot = float(np.sum((targets_arr - np.mean(targets_arr))**2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    airport_mae = {}
    cat_mae = {}
    for s, t, p in zip(data, targets, preds):
        a = s.get("airport", "UNK")
        c = s["features"]["aircraft_category"]
        airport_mae.setdefault(a, []).append(abs(t - p))
        cat_mae.setdefault(c, []).append(abs(t - p))

    return {
        "mae": round(mae, 2),
        "rmse": round(rmse, 2),
        "r2": round(r2, 4),
        "per_airport_mae": {a: round(float(np.mean(e)), 2) for a, e in airport_mae.items()},
        "per_category_mae": {c: round(float(np.mean(e)), 2) for c, e in cat_mae.items()},
    }

# Baseline (GSE constants)
fallback = {"narrow": 45.0, "wide": 90.0, "regional": 35.0}
baseline_errors = [abs(d["target"] - fallback.get(d["features"]["aircraft_category"], 45.0)) for d in test_data]
baseline_mae = float(np.mean(baseline_errors))
print(f"Baseline MAE (GSE constants): {baseline_mae:.2f} min")

# T-90 coarse
t90_targets, t90_preds = [], []
for s in test_data:
    fs = _dict_to_coarse_feature_set(s["features"])
    pred = two_stage.coarse.predict(fs)
    t90_targets.append(s["target"])
    t90_preds.append(pred.turnaround_minutes)
t90_metrics = compute_metrics(t90_targets, t90_preds, test_data)
print(f"\nT-90 (coarse):  MAE={t90_metrics['mae']:.2f}  RMSE={t90_metrics['rmse']:.2f}  R²={t90_metrics['r2']:.4f}")

# T-park refined
tpark_targets, tpark_preds = [], []
for s in test_data:
    fs = _dict_to_feature_set(s["features"])
    pred = two_stage.refined.predict(fs)
    tpark_targets.append(s["target"])
    tpark_preds.append(pred.turnaround_minutes)
tpark_metrics = compute_metrics(tpark_targets, tpark_preds, test_data)
print(f"T-park (refined): MAE={tpark_metrics['mae']:.2f}  RMSE={tpark_metrics['rmse']:.2f}  R²={tpark_metrics['r2']:.4f}")

improvement = t90_metrics["mae"] - tpark_metrics["mae"]
print(f"\nT-park refines T-90 by {improvement:.2f} min MAE")

# Per-airport breakdown
print(f"\n{'Airport':<8} {'T-90 MAE':>10} {'T-park MAE':>12}")
print("-" * 32)
for airport in sorted(t90_metrics["per_airport_mae"]):
    t90 = t90_metrics["per_airport_mae"].get(airport, 0)
    tpark = tpark_metrics["per_airport_mae"].get(airport, 0)
    print(f"{airport:<8} {t90:>10.2f} {tpark:>12.2f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Register Models in Unity Catalog via MLflow

# COMMAND ----------

import mlflow
from mlflow.models.signature import infer_signature

# Use Unity Catalog as the model registry
mlflow.set_registry_uri("databricks-uc")
mlflow.set_experiment(EXPERIMENT_NAME)

# Prepare sample input/output for model signature
sample_input = np.array(
    [[_dict_to_feature_set(train_data[0]["features"]).__dict__[k] for k in [
        "hour_of_day", "arrival_delay_min", "concurrent_gate_ops",
        "wind_speed_kt", "visibility_sm", "scheduled_departure_hour",
        "aircraft_category", "airline_code", "gate_id_prefix",
        "is_international", "is_remote_stand", "has_active_ground_stop",
    ]]],
    dtype=object,
)

with mlflow.start_run(run_name="obt_two_stage_calibrated") as run:
    run_id = run.info.run_id

    # Parameters
    mlflow.log_param("model_type", "TwoStage_HistGBT")
    mlflow.log_param("data_source", "calibrated_simulations")
    mlflow.log_param("uc_catalog", UC_CATALOG)
    mlflow.log_param("uc_schema", UC_SCHEMA)
    mlflow.log_param("n_train", len(train_data))
    mlflow.log_param("n_test", len(test_data))
    mlflow.log_param("n_airports", len(airports))
    mlflow.log_param("n_simulation_files", len(sim_files))

    # Baseline
    mlflow.log_metric("baseline_mae", baseline_mae)

    # T-90 metrics
    mlflow.log_metric("t90_mae", t90_metrics["mae"])
    mlflow.log_metric("t90_rmse", t90_metrics["rmse"])
    mlflow.log_metric("t90_r2", t90_metrics["r2"])

    # T-park metrics
    mlflow.log_metric("tpark_mae", tpark_metrics["mae"])
    mlflow.log_metric("tpark_rmse", tpark_metrics["rmse"])
    mlflow.log_metric("tpark_r2", tpark_metrics["r2"])

    # Per-airport T-park MAE
    for airport, mae in tpark_metrics["per_airport_mae"].items():
        mlflow.log_metric(f"tpark_mae_{airport}", mae)

    # Per-category MAE
    for cat, mae in tpark_metrics["per_category_mae"].items():
        mlflow.log_metric(f"tpark_mae_{cat}", mae)

    # Feature importances as artifacts
    coarse_imp = two_stage.coarse.get_feature_importances() or {}
    refined_imp = two_stage.refined.get_feature_importances() or {}
    mlflow.log_dict(coarse_imp, "coarse_feature_importances.json")
    mlflow.log_dict(refined_imp, "refined_feature_importances.json")

    # ── Register T-park (refined) model in UC Model Registry ──
    # Log the sklearn pipeline directly so it can be served
    mlflow.sklearn.log_model(
        sk_model=two_stage.refined._pipeline,
        artifact_path="obt_refined_model",
        registered_model_name=REFINED_MODEL_NAME,
        input_example=sample_input,
    )
    print(f"Registered refined model: {REFINED_MODEL_NAME}")

    # ── Register T-90 (coarse) model in UC Model Registry ──
    coarse_sample = np.array(
        [[_dict_to_coarse_feature_set(train_data[0]["features"]).__dict__[k] for k in [
            "arrival_delay_min", "wind_speed_kt", "visibility_sm",
            "scheduled_departure_hour", "aircraft_category", "airline_code",
            "is_international", "has_active_ground_stop",
        ]]],
        dtype=object,
    )
    mlflow.sklearn.log_model(
        sk_model=two_stage.coarse._pipeline,
        artifact_path="obt_coarse_model",
        registered_model_name=COARSE_MODEL_NAME,
        input_example=coarse_sample,
    )
    print(f"Registered coarse model: {COARSE_MODEL_NAME}")

    # Log comparison summary
    summary_text = f"""OBT Two-Stage Model Training Summary
=====================================
Data: {len(all_data)} samples from {len(sim_files)} calibrated simulations
Train/Test: {len(train_data)}/{len(test_data)}
Airports: {sorted(airports)}

Baseline MAE (GSE constants): {baseline_mae:.2f} min
T-90  (coarse):  MAE={t90_metrics['mae']:.2f}  RMSE={t90_metrics['rmse']:.2f}  R²={t90_metrics['r2']:.4f}
T-park (refined): MAE={tpark_metrics['mae']:.2f}  RMSE={tpark_metrics['rmse']:.2f}  R²={tpark_metrics['r2']:.4f}
T-park refines T-90 by {improvement:.2f} min MAE

Models registered in Unity Catalog:
  Coarse:  {COARSE_MODEL_NAME}
  Refined: {REFINED_MODEL_NAME}
"""
    mlflow.log_text(summary_text, "training_summary.txt")

    print(f"\nMLflow run: {run_id}")
    print(f"Experiment: {EXPERIMENT_NAME}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Save Training Metadata to UC Volume

# COMMAND ----------

model_dir = f"{VOLUME_PATH}/ml_models"
os.makedirs(model_dir, exist_ok=True)

metadata = {
    "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "mlflow_run_id": run_id,
    "uc_coarse_model": COARSE_MODEL_NAME,
    "uc_refined_model": REFINED_MODEL_NAME,
    "n_train": len(train_data),
    "n_test": len(test_data),
    "n_airports": len(airports),
    "baseline_mae": baseline_mae,
    "t90_mae": t90_metrics["mae"],
    "t90_rmse": t90_metrics["rmse"],
    "t90_r2": t90_metrics["r2"],
    "tpark_mae": tpark_metrics["mae"],
    "tpark_rmse": tpark_metrics["rmse"],
    "tpark_r2": tpark_metrics["r2"],
    "per_airport_tpark_mae": tpark_metrics["per_airport_mae"],
    "per_category_tpark_mae": tpark_metrics["per_category_mae"],
}
metadata_path = os.path.join(model_dir, "obt_training_metadata.json")
with open(metadata_path, "w") as f:
    json.dump(metadata, f, indent=2)
print(f"Metadata saved: {metadata_path}")

# COMMAND ----------

# Exit with summary
dbutils.notebook.exit(json.dumps({
    "status": "PASS",
    "n_samples": len(all_data),
    "baseline_mae": baseline_mae,
    "t90_mae": t90_metrics["mae"],
    "tpark_mae": tpark_metrics["mae"],
    "tpark_r2": tpark_metrics["r2"],
    "mlflow_run_id": run_id,
    "uc_coarse_model": COARSE_MODEL_NAME,
    "uc_refined_model": REFINED_MODEL_NAME,
}))

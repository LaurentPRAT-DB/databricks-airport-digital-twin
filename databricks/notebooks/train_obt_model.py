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
EXPERIMENT_NAME = f"/Users/{dbutils.notebook.entry_point.getDbutils().notebook().getContext().userName().get()}/airport_dt_obt_two_stage_model"

MIN_SIMULATION_FILES = 3  # Minimum files to proceed (soft threshold)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load Training Data from UC Volume

# COMMAND ----------

# List simulation files in the volume
sim_files = sorted([
    f for f in os.listdir(VOLUME_PATH)
    if f.endswith(".json") and (f.startswith("simulation_") or f.startswith("cal_"))
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

# New features summary
airlines = set(d["features"]["airline_code"] for d in all_data)
intl_count = sum(1 for d in all_data if d["features"]["is_international"])
weather_count = sum(1 for d in all_data if d["features"]["is_weather_scenario"])
print(f"Unique airlines: {len(airlines)}")
print(f"International flights: {intl_count} ({100*intl_count/len(all_data):.1f}%)")
print(f"Weather scenario samples: {weather_count} ({100*weather_count/len(all_data):.1f}%)")

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
# MAGIC ## Cross-Validation (5-Fold)

# COMMAND ----------

from sklearn.model_selection import StratifiedKFold
from src.ml.obt_model import (
    TwoStageOBTPredictor,
    OBTPredictor,
    OBTCoarsePredictor,
    _dict_to_feature_set,
    _dict_to_coarse_feature_set,
)

# 5-fold CV stratified by airport for evaluation
all_airports = [d["airport"] for d in all_data]
all_features_list = [_dict_to_feature_set(d["features"]) for d in all_data]
all_targets_arr = np.array([d["target"] for d in all_data])

skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
cv_tpark_maes = []
cv_t90_maes = []

print("Running 5-fold cross-validation...")
for fold, (train_idx, val_idx) in enumerate(skf.split(range(len(all_data)), all_airports)):
    fold_train_f = [all_features_list[i] for i in train_idx]
    fold_train_t = all_targets_arr[train_idx].tolist()

    fold_predictor = TwoStageOBTPredictor(airport_code="CV")
    fold_predictor.train(fold_train_f, fold_train_t)

    # T-park MAE
    fold_tpark_errors = []
    fold_t90_errors = []
    for i in val_idx:
        fs = all_features_list[i]
        target = all_targets_arr[i]
        tpark_pred = fold_predictor.predict_tpark(fs)
        t90_pred = fold_predictor.predict_t90(fs.to_coarse())
        fold_tpark_errors.append(abs(target - tpark_pred.turnaround_minutes))
        fold_t90_errors.append(abs(target - t90_pred.turnaround_minutes))

    fold_tpark_mae = float(np.mean(fold_tpark_errors))
    fold_t90_mae = float(np.mean(fold_t90_errors))
    cv_tpark_maes.append(fold_tpark_mae)
    cv_t90_maes.append(fold_t90_mae)
    print(f"  Fold {fold+1}: T-park MAE={fold_tpark_mae:.2f}, T-90 MAE={fold_t90_mae:.2f}")

cv_tpark_mean = float(np.mean(cv_tpark_maes))
cv_tpark_std = float(np.std(cv_tpark_maes))
cv_t90_mean = float(np.mean(cv_t90_maes))
cv_t90_std = float(np.std(cv_t90_maes))
print(f"\nCV T-park MAE: {cv_tpark_mean:.2f} +/- {cv_tpark_std:.2f}")
print(f"CV T-90 MAE:   {cv_t90_mean:.2f} +/- {cv_t90_std:.2f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Train Final Two-Stage Model (All Training Data)

# COMMAND ----------

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
    airline_mae = {}
    for s, t, p in zip(data, targets, preds):
        a = s.get("airport", "UNK")
        c = s["features"]["aircraft_category"]
        al = s["features"]["airline_code"]
        airport_mae.setdefault(a, []).append(abs(t - p))
        cat_mae.setdefault(c, []).append(abs(t - p))
        airline_mae.setdefault(al, []).append(abs(t - p))

    return {
        "mae": round(mae, 2),
        "rmse": round(rmse, 2),
        "r2": round(r2, 4),
        "per_airport_mae": {a: round(float(np.mean(e)), 2) for a, e in airport_mae.items()},
        "per_category_mae": {c: round(float(np.mean(e)), 2) for c, e in cat_mae.items()},
        "per_airline_mae": {al: round(float(np.mean(e)), 2) for al, e in airline_mae.items()},
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
tpark_intervals = []
for s in test_data:
    fs = _dict_to_feature_set(s["features"])
    pred = two_stage.refined.predict(fs)
    tpark_targets.append(s["target"])
    tpark_preds.append(pred.turnaround_minutes)
    tpark_intervals.append((pred.lower_bound_minutes, pred.upper_bound_minutes))
tpark_metrics = compute_metrics(tpark_targets, tpark_preds, test_data)
print(f"T-park (refined): MAE={tpark_metrics['mae']:.2f}  RMSE={tpark_metrics['rmse']:.2f}  R²={tpark_metrics['r2']:.4f}")

improvement = t90_metrics["mae"] - tpark_metrics["mae"]
print(f"\nT-park refines T-90 by {improvement:.2f} min MAE")

# Prediction interval coverage
if tpark_intervals:
    in_interval = sum(
        1 for t, (lo, hi) in zip(tpark_targets, tpark_intervals) if lo <= t <= hi
    )
    coverage = in_interval / len(tpark_targets) * 100
    avg_width = float(np.mean([hi - lo for lo, hi in tpark_intervals]))
    print(f"\nPrediction interval coverage (P10-P90): {coverage:.1f}% (target: ~80%)")
    print(f"Average interval width: {avg_width:.1f} min")

# Per-airport breakdown
print(f"\n{'Airport':<8} {'T-90 MAE':>10} {'T-park MAE':>12}")
print("-" * 32)
for airport in sorted(t90_metrics["per_airport_mae"]):
    t90 = t90_metrics["per_airport_mae"].get(airport, 0)
    tpark = tpark_metrics["per_airport_mae"].get(airport, 0)
    print(f"{airport:<8} {t90:>10.2f} {tpark:>12.2f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Feature Importance Analysis

# COMMAND ----------

print("=" * 60)
print("T-PARK (REFINED) FEATURE IMPORTANCES")
print("=" * 60)
refined_imp = two_stage.refined.get_feature_importances() or {}
for name, imp in sorted(refined_imp.items(), key=lambda x: -x[1]):
    bar = "█" * int(imp * 200)
    print(f"  {name:<30} {imp:.4f} {bar}")

print()
print("=" * 60)
print("T-90 (COARSE) FEATURE IMPORTANCES")
print("=" * 60)
coarse_imp = two_stage.coarse.get_feature_importances() or {}
for name, imp in sorted(coarse_imp.items(), key=lambda x: -x[1]):
    bar = "█" * int(imp * 200)
    print(f"  {name:<30} {imp:.4f} {bar}")

# Sanity check: aircraft_category should be in top 3
if refined_imp:
    sorted_features = sorted(refined_imp.items(), key=lambda x: -x[1])
    top_3_names = [name for name, _ in sorted_features[:3]]
    if "aircraft_category" in top_3_names:
        print("\n✓ Sanity check PASSED: aircraft_category is in top 3 features")
    else:
        print(f"\n⚠ Sanity check: aircraft_category not in top 3 (top 3: {top_3_names})")

    # Check feature spread — no single feature should dominate >50%
    max_imp = sorted_features[0][1]
    if max_imp < 0.50:
        print(f"✓ Feature spread GOOD: max importance = {max_imp:.2%} (<50%)")
    else:
        print(f"⚠ Feature concentration: {sorted_features[0][0]} = {max_imp:.2%} (>50%)")

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
from src.ml.obt_model import ALL_FEATURE_NAMES, ALL_COARSE_FEATURE_NAMES, _features_to_row, _coarse_features_to_row

sample_input = np.array(
    [_features_to_row(_dict_to_feature_set(train_data[0]["features"]))],
    dtype=object,
)

with mlflow.start_run(run_name="obt_two_stage_v2_feature_dependent") as run:
    run_id = run.info.run_id

    # Parameters
    mlflow.log_param("model_type", "TwoStage_HistGBT")
    mlflow.log_param("model_version", "v2_feature_dependent")
    mlflow.log_param("data_source", "calibrated_simulations")
    mlflow.log_param("uc_catalog", UC_CATALOG)
    mlflow.log_param("uc_schema", UC_SCHEMA)
    mlflow.log_param("n_train", len(train_data))
    mlflow.log_param("n_test", len(test_data))
    mlflow.log_param("n_airports", len(airports))
    mlflow.log_param("n_simulation_files", len(sim_files))
    mlflow.log_param("n_features_tpark", len(ALL_FEATURE_NAMES))
    mlflow.log_param("n_features_t90", len(ALL_COARSE_FEATURE_NAMES))

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

    # Cross-validation metrics
    mlflow.log_metric("cv_tpark_mae_mean", cv_tpark_mean)
    mlflow.log_metric("cv_tpark_mae_std", cv_tpark_std)
    mlflow.log_metric("cv_t90_mae_mean", cv_t90_mean)
    mlflow.log_metric("cv_t90_mae_std", cv_t90_std)

    # Prediction interval coverage
    if tpark_intervals:
        mlflow.log_metric("tpark_pi_coverage_pct", coverage)
        mlflow.log_metric("tpark_pi_avg_width_min", avg_width)

    # Per-airport T-park MAE
    for airport, mae in tpark_metrics["per_airport_mae"].items():
        mlflow.log_metric(f"tpark_mae_{airport}", mae)

    # Per-category MAE
    for cat, mae in tpark_metrics["per_category_mae"].items():
        mlflow.log_metric(f"tpark_mae_{cat}", mae)

    # Feature importances as artifacts
    mlflow.log_dict(coarse_imp, "coarse_feature_importances.json")
    mlflow.log_dict(refined_imp, "refined_feature_importances.json")

    # ── Register T-park (refined) model in UC Model Registry ──
    mlflow.sklearn.log_model(
        sk_model=two_stage.refined._pipeline,
        artifact_path="obt_refined_model",
        registered_model_name=REFINED_MODEL_NAME,
        input_example=sample_input,
    )
    print(f"Registered refined model: {REFINED_MODEL_NAME}")

    # ── Register T-90 (coarse) model in UC Model Registry ──
    coarse_sample = np.array(
        [_coarse_features_to_row(_dict_to_coarse_feature_set(train_data[0]["features"]))],
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
    summary_text = f"""OBT Two-Stage Model Training Summary (v2 — Feature-Dependent Turnarounds)
=========================================================================
Data: {len(all_data)} samples from {len(sim_files)} calibrated simulations
Train/Test: {len(train_data)}/{len(test_data)}
Airports: {sorted(airports)}
Unique airlines: {len(airlines)}
International flights: {intl_count} ({100*intl_count/len(all_data):.1f}%)
Weather scenario samples: {weather_count} ({100*weather_count/len(all_data):.1f}%)

Baseline MAE (GSE constants): {baseline_mae:.2f} min
T-90  (coarse):  MAE={t90_metrics['mae']:.2f}  RMSE={t90_metrics['rmse']:.2f}  R²={t90_metrics['r2']:.4f}
T-park (refined): MAE={tpark_metrics['mae']:.2f}  RMSE={tpark_metrics['rmse']:.2f}  R²={tpark_metrics['r2']:.4f}
T-park refines T-90 by {improvement:.2f} min MAE

Cross-Validation (5-fold):
  T-park: {cv_tpark_mean:.2f} +/- {cv_tpark_std:.2f} min
  T-90:   {cv_t90_mean:.2f} +/- {cv_t90_std:.2f} min

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
    "model_version": "v2_feature_dependent",
    "mlflow_run_id": run_id,
    "uc_coarse_model": COARSE_MODEL_NAME,
    "uc_refined_model": REFINED_MODEL_NAME,
    "n_train": len(train_data),
    "n_test": len(test_data),
    "n_airports": len(airports),
    "n_airlines": len(airlines),
    "baseline_mae": baseline_mae,
    "t90_mae": t90_metrics["mae"],
    "t90_rmse": t90_metrics["rmse"],
    "t90_r2": t90_metrics["r2"],
    "tpark_mae": tpark_metrics["mae"],
    "tpark_rmse": tpark_metrics["rmse"],
    "tpark_r2": tpark_metrics["r2"],
    "cv_tpark_mae_mean": cv_tpark_mean,
    "cv_tpark_mae_std": cv_tpark_std,
    "cv_t90_mae_mean": cv_t90_mean,
    "cv_t90_mae_std": cv_t90_std,
    "per_airport_tpark_mae": tpark_metrics["per_airport_mae"],
    "per_category_tpark_mae": tpark_metrics["per_category_mae"],
    "refined_feature_importances": refined_imp,
    "coarse_feature_importances": coarse_imp,
}
metadata_path = os.path.join(model_dir, "obt_training_metadata.json")
with open(metadata_path, "w") as f:
    json.dump(metadata, f, indent=2)
print(f"Metadata saved: {metadata_path}")

# COMMAND ----------

# Exit with summary
dbutils.notebook.exit(json.dumps({
    "status": "PASS",
    "model_version": "v2_feature_dependent",
    "n_samples": len(all_data),
    "baseline_mae": baseline_mae,
    "t90_mae": t90_metrics["mae"],
    "tpark_mae": tpark_metrics["mae"],
    "tpark_r2": tpark_metrics["r2"],
    "cv_tpark_mae": f"{cv_tpark_mean:.2f}+/-{cv_tpark_std:.2f}",
    "mlflow_run_id": run_id,
    "uc_coarse_model": COARSE_MODEL_NAME,
    "uc_refined_model": REFINED_MODEL_NAME,
}))

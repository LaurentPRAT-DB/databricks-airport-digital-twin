# Databricks notebook source
# MAGIC %md
# MAGIC # OBT (Off-Block Time) Model Training Pipeline
# MAGIC Trains the two-stage OBT forecasting model on calibrated simulation data.
# MAGIC
# MAGIC **Target:** `departure_offset_min = AOBT - SOBT` (minutes early/late vs schedule)
# MAGIC
# MAGIC **Two-stage approach:**
# MAGIC 1. **T-schedule coarse** — schedule + weather only (hours before departure)
# MAGIC 2. **T-park refined** — full gate-side features (after aircraft parks)
# MAGIC
# MAGIC Registers models in Unity Catalog Model Registry via MLflow.

# COMMAND ----------

%pip install scikit-learn catboost>=1.2 pyyaml pydantic --quiet

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import os, sys, json, time
import numpy as np

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

COARSE_MODEL_NAME = f"{UC_CATALOG}.{UC_SCHEMA}.obt_departure_coarse_model"
REFINED_MODEL_NAME = f"{UC_CATALOG}.{UC_SCHEMA}.obt_departure_refined_model"

EXPERIMENT_NAME = f"/Users/{dbutils.notebook.entry_point.getDbutils().notebook().getContext().userName().get()}/airport_dt_obt_departure_model"

MIN_SIMULATION_FILES = 3
MAX_SIMULATION_FILES = 60
MAX_TRAINING_SAMPLES = 15_000

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load Training Data from UC Volume

# COMMAND ----------

all_sim_files = sorted([
    f for f in os.listdir(VOLUME_PATH)
    if f.endswith(".json") and (f.startswith("simulation_") or f.startswith("cal_"))
])
print(f"Found {len(all_sim_files)} simulation files in UC Volume")

if len(all_sim_files) < MIN_SIMULATION_FILES:
    msg = f"Only {len(all_sim_files)} simulation files (need >={MIN_SIMULATION_FILES}). Skipping training."
    print(f"WARNING: {msg}")
    dbutils.notebook.exit(json.dumps({"status": "SKIP", "reason": msg}))

if len(all_sim_files) > MAX_SIMULATION_FILES:
    by_airport = {}
    for f in all_sim_files:
        parts = f.split("_")
        airport = parts[1] if len(parts) > 1 else "unknown"
        by_airport.setdefault(airport, []).append(f)

    per_airport = max(1, MAX_SIMULATION_FILES // len(by_airport))
    sim_files = []
    for airport in sorted(by_airport):
        files = by_airport[airport]
        weather = [f for f in files if "weather" in f]
        normal = [f for f in files if "weather" not in f]
        selected = weather[:max(1, per_airport // 4)] + normal[:per_airport - len(weather[:max(1, per_airport // 4)])]
        sim_files.extend(selected[:per_airport])
    sim_files = sorted(sim_files)[:MAX_SIMULATION_FILES]
    print(f"Sampled {len(sim_files)} files from {len(by_airport)} airports (cap={MAX_SIMULATION_FILES})")
else:
    sim_files = all_sim_files

for f in sim_files:
    size_mb = os.path.getsize(os.path.join(VOLUME_PATH, f)) / (1024 * 1024)
    print(f"  {f} ({size_mb:.1f} MB)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Extract OBT Features

# COMMAND ----------

from src.ml.obt_features import extract_obt_training_data

all_data = []
for fname in sim_files:
    path = os.path.join(VOLUME_PATH, fname)
    print(f"  Extracting from {fname}...", end=" ")
    samples = extract_obt_training_data(path)
    print(f"{len(samples)} samples")
    all_data.extend(samples)
    if len(all_data) >= MAX_TRAINING_SAMPLES:
        print(f"  Reached sample cap ({MAX_TRAINING_SAMPLES}), stopping.")
        all_data = all_data[:MAX_TRAINING_SAMPLES]
        break

print(f"\nTotal OBT training samples: {len(all_data)}")

if len(all_data) < 20:
    msg = f"Only {len(all_data)} OBT samples extracted. Need departure flights with parked→pushback transitions."
    print(f"WARNING: {msg}")
    dbutils.notebook.exit(json.dumps({"status": "SKIP", "reason": msg}))

airports = set(d["airport"] for d in all_data)
targets = [d["target"] for d in all_data]
print(f"Airports: {sorted(airports)}")
print(f"Target (departure_offset_min) range: {min(targets):.1f} to {max(targets):.1f} min")
print(f"Target mean: {np.mean(targets):.1f} min, median: {np.median(targets):.1f} min")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Train/Test Split (stratified by airport)

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
    _HAS_CATBOOST,
    ALL_FEATURE_NAMES,
    ALL_COARSE_FEATURE_NAMES,
    _features_to_row,
    _coarse_features_to_row,
)
from src.ml.obt_features import OBTFeatureSet, OBTCoarseFeatureSet

print(f"CatBoost available: {_HAS_CATBOOST}")

all_airports_list = [d["airport"] for d in all_data]
all_features_list = [_dict_to_feature_set(d["features"]) for d in all_data]
all_targets_arr = np.array([d["target"] for d in all_data])

skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
cv_refined_maes = []
cv_coarse_maes = []

print("Running 5-fold cross-validation...")
for fold, (train_idx, val_idx) in enumerate(skf.split(range(len(all_data)), all_airports_list)):
    fold_train_f = [all_features_list[i] for i in train_idx]
    fold_train_t = all_targets_arr[train_idx].tolist()

    fold_predictor = TwoStageOBTPredictor(airport_code="CV")
    fold_predictor.train(fold_train_f, fold_train_t)

    fold_refined_errors = []
    fold_coarse_errors = []
    for i in val_idx:
        fs = all_features_list[i]
        target = all_targets_arr[i]
        refined_pred = fold_predictor.predict_t_park(fs)
        coarse_fs = OBTCoarseFeatureSet(
            scheduled_departure_hour=fs.scheduled_departure_hour,
            aircraft_category=fs.aircraft_category,
            airline_code=fs.airline_code,
            is_international=fs.is_international,
            is_hub_connecting=fs.is_hub_connecting,
            airport_code=fs.airport_code,
            day_of_week=fs.day_of_week,
            hour_sin=fs.hour_sin,
            hour_cos=fs.hour_cos,
            wind_speed_kt=fs.wind_speed_kt,
            visibility_sm=fs.visibility_sm,
            has_active_ground_stop=fs.has_active_ground_stop,
        )
        coarse_pred = fold_predictor.predict_t_schedule(coarse_fs)
        fold_refined_errors.append(abs(target - refined_pred.departure_offset_min))
        fold_coarse_errors.append(abs(target - coarse_pred.departure_offset_min))

    fold_refined_mae = float(np.mean(fold_refined_errors))
    fold_coarse_mae = float(np.mean(fold_coarse_errors))
    cv_refined_maes.append(fold_refined_mae)
    cv_coarse_maes.append(fold_coarse_mae)
    print(f"  Fold {fold+1}: T-park MAE={fold_refined_mae:.2f}, T-schedule MAE={fold_coarse_mae:.2f}")

cv_refined_mean = float(np.mean(cv_refined_maes))
cv_refined_std = float(np.std(cv_refined_maes))
cv_coarse_mean = float(np.mean(cv_coarse_maes))
cv_coarse_std = float(np.std(cv_coarse_maes))
print(f"\nCV T-park MAE: {cv_refined_mean:.2f} +/- {cv_refined_std:.2f}")
print(f"CV T-schedule MAE: {cv_coarse_mean:.2f} +/- {cv_coarse_std:.2f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Train Final Two-Stage OBT Model

# COMMAND ----------

two_stage = TwoStageOBTPredictor(airport_code="GLOBAL")
train_features = [_dict_to_feature_set(d["features"]) for d in train_data]
train_targets = [d["target"] for d in train_data]

start_time = time.time()
train_result = two_stage.train(train_features, train_targets)
train_elapsed = time.time() - start_time

engine_refined = "catboost" if two_stage.refined._use_catboost else "sklearn"
engine_coarse = "catboost" if two_stage.coarse._use_catboost else "sklearn"
cal_offset_refined = two_stage.refined._calibration_offset
cal_offset_coarse = two_stage.coarse._calibration_offset

print(f"Training completed in {train_elapsed:.1f}s")
print(f"  Coarse (T-schedule): {train_result['coarse']['status']} (engine={engine_coarse}, CQR offset={cal_offset_coarse:.2f})")
print(f"  Refined (T-park):    {train_result['refined']['status']} (engine={engine_refined}, CQR offset={cal_offset_refined:.2f})")

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

# Baseline: assume pushback at scheduled time (offset = 0)
baseline_errors = [abs(d["target"]) for d in test_data]
baseline_mae = float(np.mean(baseline_errors))
print(f"Baseline MAE (offset=0, on-time assumption): {baseline_mae:.2f} min")

# T-schedule coarse
coarse_targets, coarse_preds = [], []
for s in test_data:
    fs = _dict_to_feature_set(s["features"])
    coarse_fs = OBTCoarseFeatureSet(
        scheduled_departure_hour=fs.scheduled_departure_hour,
        aircraft_category=fs.aircraft_category,
        airline_code=fs.airline_code,
        is_international=fs.is_international,
        is_hub_connecting=fs.is_hub_connecting,
        airport_code=fs.airport_code,
        day_of_week=fs.day_of_week,
        hour_sin=fs.hour_sin,
        hour_cos=fs.hour_cos,
        wind_speed_kt=fs.wind_speed_kt,
        visibility_sm=fs.visibility_sm,
        has_active_ground_stop=fs.has_active_ground_stop,
    )
    pred = two_stage.predict_t_schedule(coarse_fs)
    coarse_targets.append(s["target"])
    coarse_preds.append(pred.departure_offset_min)
coarse_metrics = compute_metrics(coarse_targets, coarse_preds, test_data)
print(f"\nT-schedule (coarse): MAE={coarse_metrics['mae']:.2f}  RMSE={coarse_metrics['rmse']:.2f}  R²={coarse_metrics['r2']:.4f}")

# T-park refined
refined_targets, refined_preds = [], []
refined_intervals = []
for s in test_data:
    fs = _dict_to_feature_set(s["features"])
    pred = two_stage.predict_t_park(fs)
    refined_targets.append(s["target"])
    refined_preds.append(pred.departure_offset_min)
    refined_intervals.append((pred.lower_bound_min, pred.upper_bound_min))
refined_metrics = compute_metrics(refined_targets, refined_preds, test_data)
print(f"T-park (refined):    MAE={refined_metrics['mae']:.2f}  RMSE={refined_metrics['rmse']:.2f}  R²={refined_metrics['r2']:.4f}")

improvement = coarse_metrics["mae"] - refined_metrics["mae"]
print(f"\nT-park refines T-schedule by {improvement:.2f} min MAE")

if refined_intervals:
    in_interval = sum(
        1 for t, (lo, hi) in zip(refined_targets, refined_intervals) if lo <= t <= hi
    )
    coverage = in_interval / len(refined_targets) * 100
    avg_width = float(np.mean([hi - lo for lo, hi in refined_intervals]))
    print(f"\nCQR prediction interval coverage (P10-P90): {coverage:.1f}% (target: ~80%)")
    print(f"Average interval width: {avg_width:.1f} min")

# Per-airport breakdown
print(f"\n{'Airport':<8} {'T-schedule MAE':>16} {'T-park MAE':>12}")
print("-" * 38)
for airport in sorted(coarse_metrics["per_airport_mae"]):
    c = coarse_metrics["per_airport_mae"].get(airport, 0)
    r = refined_metrics["per_airport_mae"].get(airport, 0)
    print(f"{airport:<8} {c:>16.2f} {r:>12.2f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Feature Importance

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
print("T-SCHEDULE (COARSE) FEATURE IMPORTANCES")
print("=" * 60)
coarse_imp = two_stage.coarse.get_feature_importances() or {}
for name, imp in sorted(coarse_imp.items(), key=lambda x: -x[1]):
    bar = "█" * int(imp * 200)
    print(f"  {name:<30} {imp:.4f} {bar}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Register Models in Unity Catalog via MLflow

# COMMAND ----------

import mlflow
import pickle

mlflow.set_registry_uri("databricks-uc")
mlflow.set_experiment(EXPERIMENT_NAME)


class OBTDepartureModelWrapper(mlflow.pyfunc.PythonModel):
    def __init__(self, stage: str = "refined"):
        self.stage = stage

    def load_context(self, context):
        import pickle as _pickle
        with open(context.artifacts["model_pkl"], "rb") as f:
            self._state = _pickle.load(f)

    def predict(self, context, model_input):
        return model_input

with mlflow.start_run(run_name="obt_departure_two_stage") as run:
    run_id = run.info.run_id

    mlflow.log_param("model_type", f"TwoStage_OBT_{engine_refined}")
    mlflow.log_param("target", "departure_offset_min")
    mlflow.log_param("engine_refined", engine_refined)
    mlflow.log_param("engine_coarse", engine_coarse)
    mlflow.log_param("catboost_available", _HAS_CATBOOST)
    mlflow.log_param("cqr_offset_refined", round(cal_offset_refined, 4))
    mlflow.log_param("cqr_offset_coarse", round(cal_offset_coarse, 4))
    mlflow.log_param("n_train", len(train_data))
    mlflow.log_param("n_test", len(test_data))
    mlflow.log_param("n_airports", len(airports))
    mlflow.log_param("n_simulation_files", len(sim_files))

    mlflow.log_metric("baseline_mae", baseline_mae)
    mlflow.log_metric("coarse_mae", coarse_metrics["mae"])
    mlflow.log_metric("coarse_rmse", coarse_metrics["rmse"])
    mlflow.log_metric("coarse_r2", coarse_metrics["r2"])
    mlflow.log_metric("refined_mae", refined_metrics["mae"])
    mlflow.log_metric("refined_rmse", refined_metrics["rmse"])
    mlflow.log_metric("refined_r2", refined_metrics["r2"])
    mlflow.log_metric("cv_refined_mae_mean", cv_refined_mean)
    mlflow.log_metric("cv_refined_mae_std", cv_refined_std)
    mlflow.log_metric("cv_coarse_mae_mean", cv_coarse_mean)
    mlflow.log_metric("cv_coarse_mae_std", cv_coarse_std)

    if refined_intervals:
        mlflow.log_metric("refined_pi_coverage_pct", coverage)
        mlflow.log_metric("refined_pi_avg_width_min", avg_width)

    for airport, mae in refined_metrics["per_airport_mae"].items():
        mlflow.log_metric(f"refined_mae_{airport}", mae)

    mlflow.log_dict(coarse_imp, "coarse_feature_importances.json")
    mlflow.log_dict(refined_imp, "refined_feature_importances.json")

    sample_input = np.array(
        [_features_to_row(_dict_to_feature_set(train_data[0]["features"]))],
        dtype=object,
    )

    if two_stage.refined._use_catboost and two_stage.refined._catboost is not None:
        refined_pkl = "/tmp/obt_departure_refined_catboost.pkl"
        two_stage.refined.save(refined_pkl)
        mlflow.pyfunc.log_model(
            artifact_path="obt_departure_refined_model",
            python_model=OBTDepartureModelWrapper("refined"),
            artifacts={"model_pkl": refined_pkl},
            registered_model_name=REFINED_MODEL_NAME,
            input_example=sample_input,
        )
        print(f"Registered refined CatBoost model: {REFINED_MODEL_NAME}")
    elif two_stage.refined._pipeline is not None:
        mlflow.sklearn.log_model(
            sk_model=two_stage.refined._pipeline,
            artifact_path="obt_departure_refined_model",
            registered_model_name=REFINED_MODEL_NAME,
            input_example=sample_input,
        )
        print(f"Registered refined sklearn model: {REFINED_MODEL_NAME}")

    from src.ml.obt_features import OBTCoarseFeatureSet as _OBTCoarseFS
    coarse_sample = np.array(
        [_coarse_features_to_row(_OBTCoarseFS(
            scheduled_departure_hour=train_data[0]["features"]["scheduled_departure_hour"],
            aircraft_category=train_data[0]["features"]["aircraft_category"],
            airline_code=train_data[0]["features"]["airline_code"],
            is_international=train_data[0]["features"].get("is_international", False),
            is_hub_connecting=train_data[0]["features"].get("is_hub_connecting", False),
            airport_code=train_data[0]["features"].get("airport_code", ""),
            day_of_week=train_data[0]["features"].get("day_of_week", 0),
            hour_sin=train_data[0]["features"].get("hour_sin", 0.0),
            hour_cos=train_data[0]["features"].get("hour_cos", 1.0),
            wind_speed_kt=train_data[0]["features"].get("wind_speed_kt", 0.0),
            visibility_sm=train_data[0]["features"].get("visibility_sm", 10.0),
            has_active_ground_stop=train_data[0]["features"].get("has_active_ground_stop", False),
        ))],
        dtype=object,
    )

    if two_stage.coarse._use_catboost and two_stage.coarse._catboost is not None:
        coarse_pkl = "/tmp/obt_departure_coarse_catboost.pkl"
        two_stage.coarse.save(coarse_pkl)
        mlflow.pyfunc.log_model(
            artifact_path="obt_departure_coarse_model",
            python_model=OBTDepartureModelWrapper("coarse"),
            artifacts={"model_pkl": coarse_pkl},
            registered_model_name=COARSE_MODEL_NAME,
            input_example=coarse_sample,
        )
        print(f"Registered coarse CatBoost model: {COARSE_MODEL_NAME}")
    elif two_stage.coarse._pipeline is not None:
        mlflow.sklearn.log_model(
            sk_model=two_stage.coarse._pipeline,
            artifact_path="obt_departure_coarse_model",
            registered_model_name=COARSE_MODEL_NAME,
            input_example=coarse_sample,
        )
        print(f"Registered coarse sklearn model: {COARSE_MODEL_NAME}")

    summary_text = f"""OBT Departure Model Training Summary
=====================================
Target: departure_offset_min = AOBT - SOBT (minutes)
Data: {len(all_data)} samples from {len(sim_files)} simulations
Train/Test: {len(train_data)}/{len(test_data)}
Airports: {sorted(airports)}

Engine: {engine_refined} (refined), {engine_coarse} (coarse)
CQR offset: refined={cal_offset_refined:.2f}, coarse={cal_offset_coarse:.2f}

Baseline MAE (on-time assumption): {baseline_mae:.2f} min
T-schedule (coarse): MAE={coarse_metrics['mae']:.2f}  RMSE={coarse_metrics['rmse']:.2f}  R²={coarse_metrics['r2']:.4f}
T-park (refined):    MAE={refined_metrics['mae']:.2f}  RMSE={refined_metrics['rmse']:.2f}  R²={refined_metrics['r2']:.4f}
T-park refines T-schedule by {improvement:.2f} min MAE

CV (5-fold):
  T-park: {cv_refined_mean:.2f} +/- {cv_refined_std:.2f} min
  T-schedule: {cv_coarse_mean:.2f} +/- {cv_coarse_std:.2f} min
"""
    mlflow.log_text(summary_text, "training_summary.txt")
    print(f"\nMLflow run: {run_id}")
    print(f"Experiment: {EXPERIMENT_NAME}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Save to UC Volume

# COMMAND ----------

model_dir = f"{VOLUME_PATH}/ml_models"
os.makedirs(model_dir, exist_ok=True)

metadata = {
    "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "model_type": "obt_departure",
    "target": "departure_offset_min",
    "mlflow_run_id": run_id,
    "engine_refined": engine_refined,
    "engine_coarse": engine_coarse,
    "cqr_offset_refined": cal_offset_refined,
    "cqr_offset_coarse": cal_offset_coarse,
    "n_train": len(train_data),
    "n_test": len(test_data),
    "n_airports": len(airports),
    "baseline_mae": baseline_mae,
    "coarse_mae": coarse_metrics["mae"],
    "coarse_rmse": coarse_metrics["rmse"],
    "coarse_r2": coarse_metrics["r2"],
    "refined_mae": refined_metrics["mae"],
    "refined_rmse": refined_metrics["rmse"],
    "refined_r2": refined_metrics["r2"],
    "cv_refined_mae_mean": cv_refined_mean,
    "cv_refined_mae_std": cv_refined_std,
    "per_airport_refined_mae": refined_metrics["per_airport_mae"],
    "per_category_refined_mae": refined_metrics["per_category_mae"],
    "refined_feature_importances": refined_imp,
    "coarse_feature_importances": coarse_imp,
}
metadata_path = os.path.join(model_dir, "obt_departure_training_metadata.json")
with open(metadata_path, "w") as f:
    json.dump(metadata, f, indent=2)
print(f"Metadata saved: {metadata_path}")

for name, predictor in [("refined", two_stage.refined), ("coarse", two_stage.coarse)]:
    pkl_path = os.path.join(model_dir, f"obt_departure_{name}.pkl")
    predictor.save(pkl_path)
    print(f"Model saved: {pkl_path}")

# COMMAND ----------

dbutils.notebook.exit(json.dumps({
    "status": "PASS",
    "model_type": "obt_departure",
    "engine": engine_refined,
    "n_samples": len(all_data),
    "baseline_mae": baseline_mae,
    "coarse_mae": coarse_metrics["mae"],
    "refined_mae": refined_metrics["mae"],
    "refined_r2": refined_metrics["r2"],
    "cv_refined_mae": f"{cv_refined_mean:.2f}+/-{cv_refined_std:.2f}",
    "cqr_coverage_pct": coverage if refined_intervals else None,
    "mlflow_run_id": run_id,
}))

#!/usr/bin/env python3
"""Training pipeline for the two-stage OBT (Off-Block Time) forecasting model.

Usage:
    uv run python scripts/train_obt_model.py [--sim-dir simulation_output] [--output-dir data/ml_models]

Trains two models:
    1. T-90 coarse model  — pre-arrival features only (schedule + weather)
    2. T-park refined model — full gate-side features (after aircraft parks)

Workflow:
    1. Glob simulation JSON files from --sim-dir
    2. Extract features + targets from each file
    3. Train/test split (80/20, stratified by airport)
    4. Train both coarse (T-90) and refined (T-park) models
    5. Evaluate both on test set (MAE, RMSE, R²)
    6. Log to MLflow (if available)
    7. Save model pickles
    8. Print feature importance rankings and comparison
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

# Ensure project root is on the path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.ml.obt_features import extract_training_data
from src.ml.obt_model import (
    OBTPredictor,
    OBTCoarsePredictor,
    TwoStageOBTPredictor,
    _dict_to_feature_set,
    _dict_to_coarse_feature_set,
)

try:
    import mlflow

    MLFLOW_AVAILABLE = True
except ImportError:
    MLFLOW_AVAILABLE = False


def collect_data(sim_dir: Path) -> list[dict]:
    """Extract training data from all simulation files in a directory."""
    all_data: list[dict] = []
    sim_files = sorted(sim_dir.glob("simulation_*.json"))

    if not sim_files:
        print(f"No simulation files found in {sim_dir}")
        return all_data

    for path in sim_files:
        print(f"  Extracting from {path.name}...", end=" ")
        samples = extract_training_data(path)
        print(f"{len(samples)} samples")
        all_data.extend(samples)

    return all_data


def stratified_split(
    data: list[dict], test_fraction: float = 0.2, seed: int = 42
) -> tuple[list[dict], list[dict]]:
    """Split data into train/test, stratified by airport."""
    rng = np.random.RandomState(seed)

    by_airport: dict[str, list[dict]] = {}
    for d in data:
        airport = d.get("airport", "UNK")
        by_airport.setdefault(airport, []).append(d)

    train, test = [], []
    for airport, samples in by_airport.items():
        rng.shuffle(samples)
        n_test = max(1, int(len(samples) * test_fraction))
        test.extend(samples[:n_test])
        train.extend(samples[n_test:])

    return train, test


def _compute_metrics(
    targets: list[float],
    preds: list[float],
    test_data: list[dict],
) -> dict:
    """Compute MAE, RMSE, R², per-airport and per-category breakdowns."""
    targets_arr = np.array(targets)
    preds_arr = np.array(preds)
    errors = targets_arr - preds_arr

    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(errors**2)))
    ss_res = float(np.sum(errors**2))
    ss_tot = float(np.sum((targets_arr - np.mean(targets_arr)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    airport_errors: dict[str, list[float]] = {}
    cat_errors: dict[str, list[float]] = {}
    for sample, t, p in zip(test_data, targets, preds):
        airport = sample.get("airport", "UNK")
        cat = sample["features"]["aircraft_category"]
        airport_errors.setdefault(airport, []).append(abs(t - p))
        cat_errors.setdefault(cat, []).append(abs(t - p))

    return {
        "mae": round(mae, 2),
        "rmse": round(rmse, 2),
        "r2": round(r2, 4),
        "n_test": len(test_data),
        "per_airport_mae": {a: round(float(np.mean(e)), 2) for a, e in airport_errors.items()},
        "per_category_mae": {c: round(float(np.mean(e)), 2) for c, e in cat_errors.items()},
    }


def evaluate_refined(predictor: OBTPredictor, test_data: list[dict]) -> dict:
    """Evaluate refined (T-park) model."""
    targets, preds = [], []
    for sample in test_data:
        fs = _dict_to_feature_set(sample["features"])
        pred = predictor.predict(fs)
        targets.append(sample["target"])
        preds.append(pred.turnaround_minutes)
    return _compute_metrics(targets, preds, test_data)


def evaluate_coarse(predictor: OBTCoarsePredictor, test_data: list[dict]) -> dict:
    """Evaluate coarse (T-90) model."""
    targets, preds = [], []
    for sample in test_data:
        fs = _dict_to_coarse_feature_set(sample["features"])
        pred = predictor.predict(fs)
        targets.append(sample["target"])
        preds.append(pred.turnaround_minutes)
    return _compute_metrics(targets, preds, test_data)


def compute_baseline_mae(test_data: list[dict]) -> float:
    """Compute GSE-constant baseline MAE (45/90/35 min)."""
    fallback = {"narrow": 45.0, "wide": 90.0, "regional": 35.0}
    errors = []
    for sample in test_data:
        cat = sample["features"]["aircraft_category"]
        baseline = fallback.get(cat, 45.0)
        errors.append(abs(sample["target"] - baseline))
    return float(np.mean(errors)) if errors else 0.0


def _print_metrics(label: str, metrics: dict, importances: dict | None = None):
    """Print formatted metrics block."""
    print(f"\n  {label}:")
    print(f"    MAE:  {metrics['mae']:.2f} min")
    print(f"    RMSE: {metrics['rmse']:.2f} min")
    print(f"    R²:   {metrics['r2']:.4f}")

    print(f"\n    Per-airport MAE:")
    for airport, mae in sorted(metrics["per_airport_mae"].items()):
        print(f"      {airport}: {mae:.2f} min")

    print(f"\n    Per-category MAE:")
    for cat, mae in sorted(metrics["per_category_mae"].items()):
        print(f"      {cat}: {mae:.2f} min")

    if importances:
        print(f"\n    Feature importances:")
        for name, imp in sorted(importances.items(), key=lambda x: -x[1]):
            print(f"      {name}: {imp:.4f}")


def main():
    parser = argparse.ArgumentParser(description="Train two-stage OBT forecasting model")
    parser.add_argument(
        "--sim-dir",
        type=Path,
        default=project_root / "simulation_output",
        help="Directory with simulation JSON files",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=project_root / "data" / "ml_models",
        help="Output directory for model pickles",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Two-Stage OBT Forecasting Model — Training Pipeline")
    print("=" * 60)

    # 1. Collect data
    print(f"\n[1/6] Extracting training data from {args.sim_dir}/")
    all_data = collect_data(args.sim_dir)
    if not all_data:
        print("No training data found. Exiting.")
        return

    print(f"\n  Total samples: {len(all_data)}")

    # 2. Split
    print("\n[2/6] Stratified train/test split (80/20)")
    train_data, test_data = stratified_split(all_data)
    print(f"  Train: {len(train_data)}, Test: {len(test_data)}")

    # 3. Train both models
    print("\n[3/6] Training two-stage model")
    two_stage = TwoStageOBTPredictor(airport_code="GLOBAL")
    train_features = [_dict_to_feature_set(d["features"]) for d in train_data]
    train_targets = [d["target"] for d in train_data]
    train_result = two_stage.train(train_features, train_targets)
    print(f"  Coarse (T-90):  {train_result['coarse']['status']}")
    print(f"  Refined (T-park): {train_result['refined']['status']}")

    # 4. Evaluate
    print("\n[4/6] Evaluating on test set")
    baseline_mae = compute_baseline_mae(test_data)
    print(f"\n  Baseline MAE (GSE constants): {baseline_mae:.2f} min")

    coarse_metrics = evaluate_coarse(two_stage.coarse, test_data)
    _print_metrics(
        "Stage 1: T-90 (coarse, pre-arrival)",
        coarse_metrics,
        two_stage.coarse.get_feature_importances(),
    )

    refined_metrics = evaluate_refined(two_stage.refined, test_data)
    _print_metrics(
        "Stage 2: T-park (refined, at gate)",
        refined_metrics,
        two_stage.refined.get_feature_importances(),
    )

    # 5. Comparison summary
    print("\n" + "=" * 60)
    print("  COMPARISON SUMMARY")
    print("=" * 60)
    print(f"  {'Metric':<20} {'Baseline':>10} {'T-90':>10} {'T-park':>10}")
    print(f"  {'-'*20} {'-'*10} {'-'*10} {'-'*10}")
    print(f"  {'MAE (min)':<20} {baseline_mae:>10.2f} {coarse_metrics['mae']:>10.2f} {refined_metrics['mae']:>10.2f}")
    print(f"  {'RMSE (min)':<20} {'—':>10} {coarse_metrics['rmse']:>10.2f} {refined_metrics['rmse']:>10.2f}")
    print(f"  {'R²':<20} {'—':>10} {coarse_metrics['r2']:>10.4f} {refined_metrics['r2']:>10.4f}")
    improvement = coarse_metrics["mae"] - refined_metrics["mae"]
    print(f"\n  T-park refines T-90 by {improvement:.2f} min MAE")

    # 6. Save
    coarse_path = args.output_dir / "obt_coarse_model.pkl"
    refined_path = args.output_dir / "obt_model.pkl"
    print(f"\n[5/6] Saving models")
    print(f"  Coarse:  {coarse_path}")
    print(f"  Refined: {refined_path}")
    two_stage.save(coarse_path, refined_path)

    # MLflow logging
    print("\n[6/6] MLflow logging")
    if MLFLOW_AVAILABLE:
        try:
            # Try UC model registry if on Databricks, else local MLflow
            try:
                mlflow.set_registry_uri("databricks-uc")
                uc_catalog = "serverless_stable_3n0ihb_catalog"
                uc_schema = "airport_digital_twin"
                coarse_model_name = f"{uc_catalog}.{uc_schema}.obt_coarse_model"
                refined_model_name = f"{uc_catalog}.{uc_schema}.obt_refined_model"
                use_uc = True
                print("  Using Unity Catalog model registry")
            except Exception:
                use_uc = False
                coarse_model_name = None
                refined_model_name = None
                print("  Using local MLflow (no UC registry)")

            experiment_name = "airport_models/obt_two_stage"
            mlflow.set_experiment(experiment_name)
            with mlflow.start_run():
                mlflow.log_param("model_type", "TwoStage_HistGBT")
                mlflow.log_param("n_train", len(train_data))
                mlflow.log_param("n_test", len(test_data))
                mlflow.log_param("n_airports", len(refined_metrics["per_airport_mae"]))
                mlflow.log_metric("baseline_mae", baseline_mae)
                mlflow.log_metric("t90_mae", coarse_metrics["mae"])
                mlflow.log_metric("t90_rmse", coarse_metrics["rmse"])
                mlflow.log_metric("t90_r2", coarse_metrics["r2"])
                mlflow.log_metric("tpark_mae", refined_metrics["mae"])
                mlflow.log_metric("tpark_rmse", refined_metrics["rmse"])
                mlflow.log_metric("tpark_r2", refined_metrics["r2"])

                # Register sklearn pipelines (UC if available, else log as artifact)
                if use_uc and two_stage.refined._pipeline is not None:
                    mlflow.sklearn.log_model(
                        sk_model=two_stage.refined._pipeline,
                        artifact_path="obt_refined_model",
                        registered_model_name=refined_model_name,
                    )
                    mlflow.sklearn.log_model(
                        sk_model=two_stage.coarse._pipeline,
                        artifact_path="obt_coarse_model",
                        registered_model_name=coarse_model_name,
                    )
                    print(f"  Registered: {refined_model_name}, {coarse_model_name}")
                else:
                    mlflow.log_artifact(str(coarse_path))
                    mlflow.log_artifact(str(refined_path))

            print(f"  Logged to: {experiment_name}")
        except Exception as e:
            print(f"  MLflow logging failed (non-fatal): {e}")
    else:
        print("  MLflow not available, skipped")

    print("\nDone.")


if __name__ == "__main__":
    main()

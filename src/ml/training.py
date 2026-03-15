"""MLflow training script for delay prediction model.

This module provides training functionality with MLflow experiment tracking.
When an AirportProfile is available, the trained model uses calibrated
delay priors from real data.
"""

from __future__ import annotations

import json
import os
import pickle
import tempfile
from datetime import datetime
from pathlib import Path
from statistics import mean, stdev
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from src.ml.delay_model import DelayPredictor
from src.ml.features import extract_features

if TYPE_CHECKING:
    from src.calibration.profile import AirportProfile

# Try to import mlflow, but make it optional for demo purposes
try:
    import mlflow

    MLFLOW_AVAILABLE = True
except ImportError:
    MLFLOW_AVAILABLE = False


def train_delay_model(
    training_data: List[Dict[str, Any]],
    airport_code: str = "KSFO",
    experiment_name: Optional[str] = None,
    model_output_path: Optional[str] = None,
    catalog: str = "",
    schema: str = "",
    airport_profile: Optional[AirportProfile] = None,
) -> Dict[str, Any]:
    """Train and evaluate the delay prediction model.

    This function:
    1. Sets up MLflow experiment (if available) namespaced by airport
    2. Creates a DelayPredictor instance for the airport
    3. Runs predictions on training data
    4. Logs metrics and parameters
    5. Saves model artifact
    6. Optionally registers to Unity Catalog

    Args:
        training_data: List of flight data dictionaries
        airport_code: ICAO airport code for namespacing
        experiment_name: Name for MLflow experiment (auto-generated if None)
        model_output_path: Optional path to save model artifact
        catalog: Unity Catalog catalog name for model registration
        schema: Unity Catalog schema name for model registration

    Returns:
        Dictionary with run_id, metrics, and model_path
    """
    if experiment_name is None:
        experiment_name = f"airport_models/{airport_code}/delay_model"

    run_id = None
    metrics: Dict[str, float] = {}
    model_path = model_output_path

    # Create predictor instance for the airport (with calibrated profile if available)
    predictor = DelayPredictor(airport_code=airport_code, airport_profile=airport_profile)

    # Run predictions on training data
    predictions = predictor.predict_batch(training_data)

    # Calculate metrics
    delays = [p.delay_minutes for p in predictions]
    confidences = [p.confidence for p in predictions]

    metrics["mean_delay"] = round(mean(delays), 2) if delays else 0.0
    metrics["std_delay"] = round(stdev(delays), 2) if len(delays) > 1 else 0.0
    metrics["mean_confidence"] = round(mean(confidences), 2) if confidences else 0.0
    metrics["training_samples"] = len(training_data)

    # Calculate accuracy by category
    category_counts: Dict[str, int] = {}
    for pred in predictions:
        cat = pred.delay_category
        category_counts[cat] = category_counts.get(cat, 0) + 1

    total = len(predictions)
    if total > 0:
        metrics["pct_on_time"] = round(
            category_counts.get("on_time", 0) / total * 100, 1
        )
        metrics["pct_slight_delay"] = round(
            category_counts.get("slight", 0) / total * 100, 1
        )
        metrics["pct_moderate_delay"] = round(
            category_counts.get("moderate", 0) / total * 100, 1
        )
        metrics["pct_severe_delay"] = round(
            category_counts.get("severe", 0) / total * 100, 1
        )

    # Save model artifact
    if model_path is None:
        model_dir = Path(tempfile.gettempdir()) / "airport_ml_models" / airport_code
        model_dir.mkdir(parents=True, exist_ok=True)
        model_path = str(
            model_dir / f"delay_model_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pkl"
        )

    with open(model_path, "wb") as f:
        pickle.dump(predictor, f)

    # MLflow tracking (if available)
    if MLFLOW_AVAILABLE:
        try:
            # Set up experiment
            mlflow.set_experiment(experiment_name)

            with mlflow.start_run() as run:
                run_id = run.info.run_id

                # Log parameters
                mlflow.log_param("model_type", "rule_based")
                mlflow.log_param("airport_code", airport_code)
                mlflow.log_param("feature_count", 14)  # Based on features_to_array
                mlflow.log_param("training_samples", len(training_data))

                # Log metrics
                for key, value in metrics.items():
                    mlflow.log_metric(key, value)

                # Log model artifact
                mlflow.log_artifact(model_path, "model")

                # Log category distribution as a JSON artifact
                category_file = Path(tempfile.gettempdir()) / "category_distribution.json"
                with open(category_file, "w") as f:
                    json.dump(category_counts, f, indent=2)
                mlflow.log_artifact(str(category_file), "metrics")

                # Register to Unity Catalog if configured
                if catalog and schema:
                    uc_model_name = f"{catalog}.{schema}.delay_model_{airport_code}"
                    try:
                        model_uri = f"runs:/{run_id}/model"
                        mlflow.register_model(model_uri, uc_model_name)
                    except Exception as uc_err:
                        print(f"UC registration failed for {uc_model_name}: {uc_err}")

        except Exception as e:
            # MLflow tracking failed, but model training succeeded
            print(f"MLflow tracking failed: {e}")
            run_id = f"local_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    else:
        run_id = f"local_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    return {
        "run_id": run_id,
        "metrics": metrics,
        "model_path": model_path,
        "mlflow_enabled": MLFLOW_AVAILABLE,
    }


def load_training_data_from_file(file_path: str) -> List[Dict[str, Any]]:
    """Load training data from a JSON file.

    Supports the OpenSky Network API response format.

    Args:
        file_path: Path to JSON file with flight data

    Returns:
        List of flight data dictionaries
    """
    with open(file_path, "r") as f:
        data = json.load(f)

    # Handle OpenSky format (states array with positional data)
    if "states" in data:
        flights = []
        for state in data["states"]:
            flight = {
                "icao24": state[0],
                "callsign": state[1].strip() if state[1] else None,
                "origin_country": state[2],
                "position_time": state[3],
                "last_contact": state[4],
                "longitude": state[5],
                "latitude": state[6],
                "baro_altitude": state[7],
                "on_ground": state[8],
                "velocity": state[9],
                "true_track": state[10],
                "vertical_rate": state[11],
                "sensors": state[12],
                "geo_altitude": state[13],
                "squawk": state[14],
                "spi": state[15],
                "position_source": state[16],
                "category": state[17] if len(state) > 17 else None,
            }
            flights.append(flight)
        return flights

    # Handle direct list format
    if isinstance(data, list):
        return data

    return []


def train_obt_model(
    sim_json_path: str,
    airport_code: str = "KSFO",
    experiment_name: Optional[str] = None,
    model_output_path: Optional[str] = None,
    airport_profile: Optional["AirportProfile"] = None,
) -> Dict[str, Any]:
    """Train the OBT turnaround prediction model from simulation data.

    Args:
        sim_json_path: Path to simulation JSON file.
        airport_code: ICAO airport code.
        experiment_name: MLflow experiment name (auto-generated if None).
        model_output_path: Path to save model pickle.
        airport_profile: Optional calibrated profile.

    Returns:
        Dict with training metadata and metrics.
    """
    from src.ml.obt_features import extract_training_data, OBTFeatureSet
    from src.ml.obt_model import OBTPredictor, _dict_to_feature_set

    if experiment_name is None:
        experiment_name = f"airport_models/{airport_code}/obt_model"

    # Extract training data
    samples = extract_training_data(sim_json_path)
    if not samples:
        return {"status": "no_data", "n_samples": 0}

    features = [_dict_to_feature_set(s["features"]) for s in samples]
    targets = [s["target"] for s in samples]

    # Train
    predictor = OBTPredictor(airport_code=airport_code, airport_profile=airport_profile)
    train_result = predictor.train(features, targets)

    # Save model
    if model_output_path is None:
        model_dir = Path(tempfile.gettempdir()) / "airport_ml_models" / airport_code
        model_dir.mkdir(parents=True, exist_ok=True)
        model_output_path = str(
            model_dir / f"obt_model_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pkl"
        )

    predictor.save(model_output_path)

    result = {
        "status": train_result.get("status", "unknown"),
        "n_samples": len(samples),
        "model_path": model_output_path,
        "mlflow_enabled": MLFLOW_AVAILABLE,
    }

    # MLflow tracking
    if MLFLOW_AVAILABLE:
        try:
            mlflow.set_experiment(experiment_name)
            with mlflow.start_run() as run:
                result["run_id"] = run.info.run_id
                mlflow.log_param("model_type", "HistGradientBoostingRegressor")
                mlflow.log_param("airport_code", airport_code)
                mlflow.log_param("training_samples", len(samples))
                mlflow.log_artifact(model_output_path, "model")
        except Exception as e:
            print(f"MLflow tracking failed: {e}")

    return result


if __name__ == "__main__":
    # Demo: train on sample data
    sample_data_path = "data/fallback/sample_flights.json"
    if os.path.exists(sample_data_path):
        training_data = load_training_data_from_file(sample_data_path)
        result = train_delay_model(training_data)
        print(f"Training completed:")
        print(f"  Run ID: {result['run_id']}")
        print(f"  Model path: {result['model_path']}")
        print(f"  Metrics: {result['metrics']}")
    else:
        print(f"Sample data not found at {sample_data_path}")

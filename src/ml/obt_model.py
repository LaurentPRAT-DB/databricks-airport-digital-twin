"""Off-Block Time (OBT) forecasting model.

Predicts turnaround duration (minutes) — the time an aircraft spends
at the gate from parking to pushback.  Uses a gradient-boosted tree
trained on simulation data, falling back to GSE model constants
(45 min narrow-body, 90 min wide-body) when no trained model exists.
"""

from __future__ import annotations

import logging
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

from src.ml.obt_features import OBTCoarseFeatureSet, OBTFeatureSet, classify_aircraft

if TYPE_CHECKING:
    from src.calibration.profile import AirportProfile

logger = logging.getLogger(__name__)

# Feature column ordering — must match _features_to_row()
NUMERIC_FEATURES = [
    "hour_of_day",
    "arrival_delay_min",
    "concurrent_gate_ops",
    "wind_speed_kt",
    "visibility_sm",
    "scheduled_departure_hour",
    "day_of_week",
    "hour_sin",
    "hour_cos",
]
CATEGORICAL_FEATURES = [
    "aircraft_category",
    "airline_code",
    "gate_id_prefix",
    "airport_code",
]
BINARY_FEATURES = [
    "is_international",
    "is_remote_stand",
    "has_active_ground_stop",
    "is_weather_scenario",
]

ALL_FEATURE_NAMES = NUMERIC_FEATURES + CATEGORICAL_FEATURES + BINARY_FEATURES

# T-90 coarse features — pre-arrival only (no gate-side info)
COARSE_NUMERIC_FEATURES = [
    "arrival_delay_min",
    "wind_speed_kt",
    "visibility_sm",
    "scheduled_departure_hour",
    "day_of_week",
    "hour_sin",
    "hour_cos",
]
COARSE_CATEGORICAL_FEATURES = [
    "aircraft_category",
    "airline_code",
    "airport_code",
]
COARSE_BINARY_FEATURES = [
    "is_international",
    "has_active_ground_stop",
    "is_weather_scenario",
]
ALL_COARSE_FEATURE_NAMES = (
    COARSE_NUMERIC_FEATURES + COARSE_CATEGORICAL_FEATURES + COARSE_BINARY_FEATURES
)


@dataclass
class OBTPrediction:
    """Result of an OBT turnaround prediction."""

    turnaround_minutes: float
    lower_bound_minutes: float = 0.0   # P10 quantile
    upper_bound_minutes: float = 0.0   # P90 quantile
    confidence: float = 0.5
    is_fallback: bool = False
    horizon: str = "t_park"  # "t90" or "t_park"


def _features_to_row(f: OBTFeatureSet) -> List[Any]:
    """Convert OBTFeatureSet to a flat row matching ALL_FEATURE_NAMES order."""
    return [
        f.hour_of_day,
        f.arrival_delay_min,
        f.concurrent_gate_ops,
        f.wind_speed_kt,
        f.visibility_sm,
        f.scheduled_departure_hour,
        f.day_of_week,
        f.hour_sin,
        f.hour_cos,
        f.aircraft_category,
        f.airline_code,
        f.gate_id_prefix,
        f.airport_code,
        int(f.is_international),
        int(f.is_remote_stand),
        int(f.has_active_ground_stop),
        int(f.is_weather_scenario),
    ]


def _coarse_features_to_row(f: OBTCoarseFeatureSet) -> List[Any]:
    """Convert OBTCoarseFeatureSet to a flat row matching ALL_COARSE_FEATURE_NAMES."""
    return [
        f.arrival_delay_min,
        f.wind_speed_kt,
        f.visibility_sm,
        f.scheduled_departure_hour,
        f.day_of_week,
        f.hour_sin,
        f.hour_cos,
        f.aircraft_category,
        f.airline_code,
        f.airport_code,
        int(f.is_international),
        int(f.has_active_ground_stop),
        int(f.is_weather_scenario),
    ]


def _dict_to_coarse_feature_set(d: Dict[str, Any]) -> OBTCoarseFeatureSet:
    """Reconstruct OBTCoarseFeatureSet from a dict."""
    return OBTCoarseFeatureSet(
        aircraft_category=d["aircraft_category"],
        airline_code=d["airline_code"],
        scheduled_departure_hour=int(d["scheduled_departure_hour"]),
        is_international=bool(d["is_international"]),
        arrival_delay_min=float(d["arrival_delay_min"]),
        wind_speed_kt=float(d["wind_speed_kt"]),
        visibility_sm=float(d["visibility_sm"]),
        has_active_ground_stop=bool(d["has_active_ground_stop"]),
        airport_code=d.get("airport_code", ""),
        day_of_week=int(d.get("day_of_week", 0)),
        hour_sin=float(d.get("hour_sin", 0.0)),
        hour_cos=float(d.get("hour_cos", 1.0)),
        is_weather_scenario=bool(d.get("is_weather_scenario", False)),
    )


def _dict_to_feature_set(d: Dict[str, Any]) -> OBTFeatureSet:
    """Reconstruct OBTFeatureSet from a dict (e.g. from training data)."""
    return OBTFeatureSet(
        aircraft_category=d["aircraft_category"],
        airline_code=d["airline_code"],
        hour_of_day=int(d["hour_of_day"]),
        is_international=bool(d["is_international"]),
        arrival_delay_min=float(d["arrival_delay_min"]),
        gate_id_prefix=d["gate_id_prefix"],
        is_remote_stand=bool(d["is_remote_stand"]),
        concurrent_gate_ops=int(d["concurrent_gate_ops"]),
        wind_speed_kt=float(d["wind_speed_kt"]),
        visibility_sm=float(d["visibility_sm"]),
        has_active_ground_stop=bool(d["has_active_ground_stop"]),
        scheduled_departure_hour=int(d["scheduled_departure_hour"]),
        airport_code=d.get("airport_code", ""),
        day_of_week=int(d.get("day_of_week", 0)),
        hour_sin=float(d.get("hour_sin", 0.0)),
        hour_cos=float(d.get("hour_cos", 1.0)),
        is_weather_scenario=bool(d.get("is_weather_scenario", False)),
    )


def _build_pipeline(
    feature_names: List[str],
    categorical_features: List[str],
    *,
    max_depth: int = 6,
    n_estimators: int = 200,
    learning_rate: float = 0.05,
    loss: str = "squared_error",
    quantile: Optional[float] = None,
) -> Pipeline:
    """Build a preprocessing + GBT pipeline."""
    cat_indices = [feature_names.index(c) for c in categorical_features]
    num_indices = [i for i in range(len(feature_names)) if i not in cat_indices]

    preprocessor = ColumnTransformer(
        transformers=[
            (
                "cat",
                OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1),
                cat_indices,
            ),
            ("num", "passthrough", num_indices),
        ]
    )

    model_kwargs: dict[str, Any] = dict(
        max_depth=max_depth,
        max_iter=n_estimators,
        learning_rate=learning_rate,
        random_state=42,
    )
    if quantile is not None:
        model_kwargs["loss"] = "quantile"
        model_kwargs["quantile"] = quantile
    else:
        model_kwargs["loss"] = loss

    model = HistGradientBoostingRegressor(**model_kwargs)

    return Pipeline([
        ("preprocessor", preprocessor),
        ("model", model),
    ])


def _extract_feature_importances(
    pipeline: Pipeline,
    feature_names: List[str],
    categorical_features: List[str],
    X: np.ndarray,
    y: np.ndarray,
) -> Dict[str, float]:
    """Extract feature importances from a trained pipeline."""
    cat_indices = [feature_names.index(c) for c in categorical_features]
    num_indices = [i for i in range(len(feature_names)) if i not in cat_indices]
    reordered_names = [feature_names[i] for i in cat_indices] + [
        feature_names[i] for i in num_indices
    ]

    fitted_model = pipeline.named_steps["model"]
    try:
        raw_importances = fitted_model.feature_importances_
        return {
            name: float(imp)
            for name, imp in zip(reordered_names, raw_importances)
        }
    except AttributeError:
        from sklearn.inspection import permutation_importance
        X_transformed = pipeline.named_steps["preprocessor"].transform(X)
        result = permutation_importance(
            fitted_model, X_transformed, y, n_repeats=5, random_state=42,
        )
        return {
            name: float(imp)
            for name, imp in zip(reordered_names, result.importances_mean)
        }


class OBTPredictor:
    """Predicts turnaround duration (minutes) for Off-Block Time forecasting.

    When trained, uses a HistGradientBoostingRegressor on simulation-derived
    features. When untrained, falls back to the GSE model constants so there
    is zero regression from current behavior.

    Optionally trains P10/P90 quantile models for prediction intervals.
    """

    def __init__(
        self,
        airport_code: str = "KSFO",
        airport_profile: Optional[AirportProfile] = None,
    ):
        self.airport_code = airport_code
        self._profile = airport_profile
        self._pipeline: Optional[Pipeline] = None
        self._pipeline_p10: Optional[Pipeline] = None
        self._pipeline_p90: Optional[Pipeline] = None
        self._feature_importances: Optional[Dict[str, float]] = None
        self._fallback_durations = {"narrow": 45.0, "wide": 90.0, "regional": 35.0}

    @property
    def is_trained(self) -> bool:
        return self._pipeline is not None

    def train(
        self,
        features: List[OBTFeatureSet],
        targets: List[float],
        *,
        max_depth: int = 6,
        n_estimators: int = 200,
        learning_rate: float = 0.05,
        train_quantiles: bool = True,
    ) -> Dict[str, Any]:
        """Train the GBT model on feature/target pairs.

        Args:
            features: List of OBTFeatureSet instances.
            targets: List of turnaround durations in minutes.
            max_depth: Tree depth.
            n_estimators: Number of boosting rounds.
            learning_rate: Step size shrinkage.
            train_quantiles: If True, also train P10/P90 quantile models.

        Returns:
            Dict with training metadata (n_samples, feature_importances).
        """
        if len(features) < 10:
            logger.warning(
                f"Only {len(features)} samples for {self.airport_code}; "
                "skipping training, using fallback."
            )
            return {"n_samples": len(features), "status": "insufficient_data"}

        X_raw = [_features_to_row(f) for f in features]
        X = np.array(X_raw, dtype=object)
        y = np.array(targets, dtype=np.float64)

        # Main model (squared error / mean prediction)
        self._pipeline = _build_pipeline(
            ALL_FEATURE_NAMES, CATEGORICAL_FEATURES,
            max_depth=max_depth, n_estimators=n_estimators,
            learning_rate=learning_rate,
        )
        self._pipeline.fit(X, y)

        # Quantile models for prediction intervals
        if train_quantiles:
            self._pipeline_p10 = _build_pipeline(
                ALL_FEATURE_NAMES, CATEGORICAL_FEATURES,
                max_depth=max_depth, n_estimators=n_estimators,
                learning_rate=learning_rate, quantile=0.1,
            )
            self._pipeline_p10.fit(X, y)

            self._pipeline_p90 = _build_pipeline(
                ALL_FEATURE_NAMES, CATEGORICAL_FEATURES,
                max_depth=max_depth, n_estimators=n_estimators,
                learning_rate=learning_rate, quantile=0.9,
            )
            self._pipeline_p90.fit(X, y)

        # Feature importances
        self._feature_importances = _extract_feature_importances(
            self._pipeline, ALL_FEATURE_NAMES, CATEGORICAL_FEATURES, X, y,
        )

        logger.info(
            f"OBT model trained for {self.airport_code} on {len(features)} samples"
        )

        return {
            "n_samples": len(features),
            "status": "trained",
            "feature_importances": self._feature_importances,
        }

    def predict(self, features: OBTFeatureSet) -> OBTPrediction:
        """Predict turnaround duration in minutes.

        Falls back to GSE constants if untrained.
        """
        if self._pipeline is None:
            duration = self._fallback_durations.get(
                features.aircraft_category, 45.0
            )
            return OBTPrediction(
                turnaround_minutes=duration,
                lower_bound_minutes=duration * 0.8,
                upper_bound_minutes=duration * 1.2,
                confidence=0.3,
                is_fallback=True,
            )

        row = np.array([_features_to_row(features)], dtype=object)
        pred = float(self._pipeline.predict(row)[0])
        pred = max(10.0, min(180.0, pred))

        # Quantile bounds
        if self._pipeline_p10 is not None and self._pipeline_p90 is not None:
            p10 = max(10.0, float(self._pipeline_p10.predict(row)[0]))
            p90 = min(180.0, float(self._pipeline_p90.predict(row)[0]))
            # Ensure ordering
            p10 = min(p10, pred)
            p90 = max(p90, pred)
            interval_width = max(p90 - p10, 1.0)
            confidence = round(min(1.0, 30.0 / interval_width), 2)
        else:
            p10 = pred * 0.8
            p90 = pred * 1.2
            confidence = 0.75

        return OBTPrediction(
            turnaround_minutes=round(pred, 1),
            lower_bound_minutes=round(p10, 1),
            upper_bound_minutes=round(p90, 1),
            confidence=confidence,
            is_fallback=False,
        )

    def predict_obt(self, parked_time: float, features: OBTFeatureSet) -> float:
        """Predict actual OBT timestamp = parked_time + predicted_turnaround.

        Args:
            parked_time: Unix timestamp when aircraft parked.
            features: OBTFeatureSet for the flight.

        Returns:
            Predicted OBT as Unix timestamp.
        """
        prediction = self.predict(features)
        return parked_time + prediction.turnaround_minutes * 60.0

    def get_feature_importances(self) -> Optional[Dict[str, float]]:
        """Return feature importances if model is trained."""
        return self._feature_importances

    def save(self, path: str | Path) -> None:
        """Save model to pickle file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(
                {
                    "airport_code": self.airport_code,
                    "pipeline": self._pipeline,
                    "pipeline_p10": self._pipeline_p10,
                    "pipeline_p90": self._pipeline_p90,
                    "feature_importances": self._feature_importances,
                    "fallback_durations": self._fallback_durations,
                },
                f,
            )
        logger.info(f"OBT model saved to {path}")

    def load(self, path: str | Path) -> bool:
        """Load model from pickle file.

        Returns:
            True if loaded successfully.
        """
        path = Path(path)
        if not path.exists():
            return False
        try:
            with open(path, "rb") as f:
                state = pickle.load(f)
            self._pipeline = state["pipeline"]
            self._pipeline_p10 = state.get("pipeline_p10")
            self._pipeline_p90 = state.get("pipeline_p90")
            self._feature_importances = state.get("feature_importances")
            self._fallback_durations = state.get(
                "fallback_durations", self._fallback_durations
            )
            logger.info(f"OBT model loaded from {path}")
            return True
        except Exception as e:
            logger.warning(f"Failed to load OBT model from {path}: {e}")
            return False


class OBTCoarsePredictor:
    """T-90 coarse predictor using only pre-arrival features.

    Uses schedule, inbound delay, weather, and ops status — no gate-side
    information. Lower accuracy than the refined T-park model, but
    available 90 minutes before departure for planning purposes.
    """

    def __init__(
        self,
        airport_code: str = "KSFO",
        airport_profile: Optional["AirportProfile"] = None,
    ):
        self.airport_code = airport_code
        self._profile = airport_profile
        self._pipeline: Optional[Pipeline] = None
        self._pipeline_p10: Optional[Pipeline] = None
        self._pipeline_p90: Optional[Pipeline] = None
        self._feature_importances: Optional[Dict[str, float]] = None
        self._fallback_durations = {"narrow": 45.0, "wide": 90.0, "regional": 35.0}

    @property
    def is_trained(self) -> bool:
        return self._pipeline is not None

    def train(
        self,
        features: List[OBTCoarseFeatureSet],
        targets: List[float],
        *,
        max_depth: int = 5,
        n_estimators: int = 150,
        learning_rate: float = 0.05,
        train_quantiles: bool = True,
    ) -> Dict[str, Any]:
        """Train the coarse GBT model on T-90 features."""
        if len(features) < 10:
            logger.warning(
                f"Only {len(features)} samples for coarse model {self.airport_code}; "
                "skipping training, using fallback."
            )
            return {"n_samples": len(features), "status": "insufficient_data"}

        X_raw = [_coarse_features_to_row(f) for f in features]
        X = np.array(X_raw, dtype=object)
        y = np.array(targets, dtype=np.float64)

        self._pipeline = _build_pipeline(
            ALL_COARSE_FEATURE_NAMES, COARSE_CATEGORICAL_FEATURES,
            max_depth=max_depth, n_estimators=n_estimators,
            learning_rate=learning_rate,
        )
        self._pipeline.fit(X, y)

        if train_quantiles:
            self._pipeline_p10 = _build_pipeline(
                ALL_COARSE_FEATURE_NAMES, COARSE_CATEGORICAL_FEATURES,
                max_depth=max_depth, n_estimators=n_estimators,
                learning_rate=learning_rate, quantile=0.1,
            )
            self._pipeline_p10.fit(X, y)

            self._pipeline_p90 = _build_pipeline(
                ALL_COARSE_FEATURE_NAMES, COARSE_CATEGORICAL_FEATURES,
                max_depth=max_depth, n_estimators=n_estimators,
                learning_rate=learning_rate, quantile=0.9,
            )
            self._pipeline_p90.fit(X, y)

        self._feature_importances = _extract_feature_importances(
            self._pipeline, ALL_COARSE_FEATURE_NAMES, COARSE_CATEGORICAL_FEATURES, X, y,
        )

        logger.info(
            f"OBT coarse (T-90) model trained for {self.airport_code} "
            f"on {len(features)} samples"
        )

        return {
            "n_samples": len(features),
            "status": "trained",
            "feature_importances": self._feature_importances,
        }

    def predict(self, features: OBTCoarseFeatureSet) -> OBTPrediction:
        """Predict turnaround duration using T-90 features only."""
        if self._pipeline is None:
            duration = self._fallback_durations.get(
                features.aircraft_category, 45.0
            )
            return OBTPrediction(
                turnaround_minutes=duration,
                lower_bound_minutes=duration * 0.8,
                upper_bound_minutes=duration * 1.2,
                confidence=0.2,
                is_fallback=True,
                horizon="t90",
            )

        row = np.array([_coarse_features_to_row(features)], dtype=object)
        pred = float(self._pipeline.predict(row)[0])
        pred = max(10.0, min(180.0, pred))

        if self._pipeline_p10 is not None and self._pipeline_p90 is not None:
            p10 = max(10.0, float(self._pipeline_p10.predict(row)[0]))
            p90 = min(180.0, float(self._pipeline_p90.predict(row)[0]))
            p10 = min(p10, pred)
            p90 = max(p90, pred)
            interval_width = max(p90 - p10, 1.0)
            confidence = round(min(1.0, 30.0 / interval_width), 2)
        else:
            p10 = pred * 0.75
            p90 = pred * 1.25
            confidence = 0.55

        return OBTPrediction(
            turnaround_minutes=round(pred, 1),
            lower_bound_minutes=round(p10, 1),
            upper_bound_minutes=round(p90, 1),
            confidence=confidence,
            is_fallback=False,
            horizon="t90",
        )

    def get_feature_importances(self) -> Optional[Dict[str, float]]:
        return self._feature_importances

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(
                {
                    "airport_code": self.airport_code,
                    "pipeline": self._pipeline,
                    "pipeline_p10": self._pipeline_p10,
                    "pipeline_p90": self._pipeline_p90,
                    "feature_importances": self._feature_importances,
                    "fallback_durations": self._fallback_durations,
                },
                f,
            )
        logger.info(f"OBT coarse model saved to {path}")

    def load(self, path: str | Path) -> bool:
        path = Path(path)
        if not path.exists():
            return False
        try:
            with open(path, "rb") as f:
                state = pickle.load(f)
            self._pipeline = state["pipeline"]
            self._pipeline_p10 = state.get("pipeline_p10")
            self._pipeline_p90 = state.get("pipeline_p90")
            self._feature_importances = state.get("feature_importances")
            self._fallback_durations = state.get(
                "fallback_durations", self._fallback_durations
            )
            logger.info(f"OBT coarse model loaded from {path}")
            return True
        except Exception as e:
            logger.warning(f"Failed to load OBT coarse model from {path}: {e}")
            return False


class TwoStageOBTPredictor:
    """Two-stage OBT predictor: coarse at T-90, refined at T-park.

    At T-90 (90 min before scheduled departure), only schedule and
    weather data is available — the coarse model gives a planning estimate.

    At T-park (aircraft parks at gate), full gate-side features become
    available — the refined model gives an operational estimate.

    Usage:
        predictor = TwoStageOBTPredictor(airport_code="KSFO")
        predictor.train(full_features, coarse_features, targets)

        # Pre-arrival planning
        t90_pred = predictor.predict_t90(coarse_features)

        # After parking — refined
        tpark_pred = predictor.predict_tpark(full_features)
    """

    def __init__(
        self,
        airport_code: str = "KSFO",
        airport_profile: Optional["AirportProfile"] = None,
    ):
        self.airport_code = airport_code
        self.coarse = OBTCoarsePredictor(
            airport_code=airport_code, airport_profile=airport_profile,
        )
        self.refined = OBTPredictor(
            airport_code=airport_code, airport_profile=airport_profile,
        )

    @property
    def is_trained(self) -> bool:
        return self.coarse.is_trained and self.refined.is_trained

    def train(
        self,
        full_features: List[OBTFeatureSet],
        targets: List[float],
    ) -> Dict[str, Any]:
        """Train both stages from the same labeled data.

        Coarse features are derived automatically by projecting the full
        feature set down to the T-90 subset.
        """
        coarse_features = [f.to_coarse() for f in full_features]

        coarse_result = self.coarse.train(coarse_features, targets)
        refined_result = self.refined.train(full_features, targets)

        return {
            "coarse": coarse_result,
            "refined": refined_result,
        }

    def predict_t90(self, features: OBTCoarseFeatureSet) -> OBTPrediction:
        """Predict at T-90 horizon (pre-arrival)."""
        return self.coarse.predict(features)

    def predict_tpark(self, features: OBTFeatureSet) -> OBTPrediction:
        """Predict at T-park horizon (aircraft parked, full features)."""
        return self.refined.predict(features)

    def predict_obt_t90(
        self, scheduled_departure: float, features: OBTCoarseFeatureSet,
    ) -> float:
        """Predict OBT timestamp at T-90 horizon.

        At T-90 we don't know the actual parking time, so we estimate:
        OBT = scheduled_departure - taxi_out_buffer (typically ~15 min).

        Args:
            scheduled_departure: Unix timestamp of scheduled departure.
            features: Coarse feature set.

        Returns:
            Predicted OBT as Unix timestamp (pushback time).
        """
        taxi_out_buffer_sec = 15.0 * 60.0  # 15 min typical taxi-out
        return scheduled_departure - taxi_out_buffer_sec

    def predict_obt_tpark(
        self, parked_time: float, features: OBTFeatureSet,
    ) -> float:
        """Predict OBT timestamp at T-park horizon.

        Args:
            parked_time: Unix timestamp when aircraft parked.
            features: Full feature set.

        Returns:
            Predicted OBT as Unix timestamp.
        """
        return self.refined.predict_obt(parked_time, features)

    def save(self, coarse_path: str | Path, refined_path: str | Path) -> None:
        """Save both models."""
        self.coarse.save(coarse_path)
        self.refined.save(refined_path)

    def load(self, coarse_path: str | Path, refined_path: str | Path) -> bool:
        """Load both models. Returns True only if both loaded."""
        c = self.coarse.load(coarse_path)
        r = self.refined.load(refined_path)
        return c and r

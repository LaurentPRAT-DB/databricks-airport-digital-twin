"""Tests for OBT (Off-Block Time) forecasting model.

Covers feature extraction, model training/prediction, data validation,
and integration with the ML registry.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import math

from src.ml.obt_features import (
    OBTCoarseFeatureSet,
    OBTFeatureSet,
    classify_aircraft,
    extract_training_data,
    _gate_prefix,
    _is_remote_stand,
    _cyclical_hour,
    _is_international_route,
)
from src.ml.obt_model import (
    OBTPredictor,
    OBTCoarsePredictor,
    TwoStageOBTPredictor,
    OBTPrediction,
    _dict_to_feature_set,
    _dict_to_coarse_feature_set,
    _features_to_row,
    _coarse_features_to_row,
    ALL_FEATURE_NAMES,
    ALL_COARSE_FEATURE_NAMES,
)

# Path to a real simulation file for integration tests
SIM_DIR = Path(__file__).resolve().parent.parent / "simulation_output"
SIM_FILE_SFO = SIM_DIR / "simulation_sfo_1000_thunderstorm.json"


def _has_sim_files() -> bool:
    return SIM_FILE_SFO.exists()


# Default new fields for v2 feature sets (used to DRY up test constructors)
_V2_DEFAULTS = dict(
    airport_code="SFO",
    day_of_week=2,
    hour_sin=0.0,
    hour_cos=1.0,
    is_weather_scenario=False,
)


def _make_full_fs(**overrides) -> OBTFeatureSet:
    """Create OBTFeatureSet with sensible defaults for all fields."""
    defaults = dict(
        aircraft_category="narrow",
        airline_code="UAL",
        hour_of_day=14,
        is_international=False,
        arrival_delay_min=0.0,
        gate_id_prefix="B",
        is_remote_stand=False,
        concurrent_gate_ops=3,
        wind_speed_kt=5.0,
        visibility_sm=10.0,
        has_active_ground_stop=False,
        scheduled_departure_hour=16,
        **_V2_DEFAULTS,
    )
    defaults.update(overrides)
    return OBTFeatureSet(**defaults)


def _make_coarse_fs(**overrides) -> OBTCoarseFeatureSet:
    """Create OBTCoarseFeatureSet with sensible defaults for all fields."""
    defaults = dict(
        aircraft_category="narrow",
        airline_code="UAL",
        scheduled_departure_hour=16,
        is_international=False,
        arrival_delay_min=0.0,
        wind_speed_kt=5.0,
        visibility_sm=10.0,
        has_active_ground_stop=False,
        **_V2_DEFAULTS,
    )
    defaults.update(overrides)
    return OBTCoarseFeatureSet(**defaults)


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------


class TestAircraftCategoryMapping:
    def test_narrow_body(self):
        assert classify_aircraft("B738") == "narrow"
        assert classify_aircraft("A320") == "narrow"
        assert classify_aircraft("A321") == "narrow"
        assert classify_aircraft("B737") == "narrow"

    def test_wide_body(self):
        assert classify_aircraft("B777") == "wide"
        assert classify_aircraft("A380") == "wide"
        assert classify_aircraft("B787") == "wide"
        assert classify_aircraft("A350") == "wide"
        assert classify_aircraft("A330") == "wide"

    def test_regional(self):
        assert classify_aircraft("E190") == "regional"
        assert classify_aircraft("CRJ9") == "regional"
        assert classify_aircraft("AT72") == "regional"

    def test_unknown_defaults_to_narrow(self):
        assert classify_aircraft("ZZZZ") == "narrow"
        assert classify_aircraft("") == "narrow"


class TestGatePrefix:
    def test_letter_prefix(self):
        assert _gate_prefix("B2") == "B"
        assert _gate_prefix("T1") == "T"
        assert _gate_prefix("AA12") == "AA"

    def test_numeric_gate(self):
        assert _gate_prefix("42") == "4"

    def test_empty(self):
        assert _gate_prefix("") == "UNK"


class TestRemoteStand:
    def test_remote(self):
        assert _is_remote_stand("R1") is True
        assert _is_remote_stand("REM5") is True

    def test_not_remote(self):
        assert _is_remote_stand("B2") is False
        assert _is_remote_stand("") is False


class TestOBTFeatureSet:
    def test_dataclass_fields(self):
        fs = _make_full_fs(arrival_delay_min=10.0, concurrent_gate_ops=5, wind_speed_kt=8.0)
        assert fs.aircraft_category == "narrow"
        assert fs.hour_of_day == 14
        assert fs.airport_code == "SFO"
        assert fs.day_of_week == 2

    def test_v2_fields_present(self):
        fs = _make_full_fs()
        assert hasattr(fs, "airport_code")
        assert hasattr(fs, "day_of_week")
        assert hasattr(fs, "hour_sin")
        assert hasattr(fs, "hour_cos")
        assert hasattr(fs, "is_weather_scenario")

    def test_features_to_row_length(self):
        fs = _make_full_fs(concurrent_gate_ops=5, wind_speed_kt=8.0)
        row = _features_to_row(fs)
        assert len(row) == len(ALL_FEATURE_NAMES)

    def test_dict_roundtrip(self):
        from dataclasses import asdict

        fs = _make_full_fs(
            aircraft_category="wide", airline_code="BAW", hour_of_day=8,
            is_international=True, arrival_delay_min=15.0, gate_id_prefix="A",
            is_remote_stand=True, concurrent_gate_ops=3, wind_speed_kt=12.0,
            visibility_sm=5.0, has_active_ground_stop=True, scheduled_departure_hour=10,
            airport_code="LHR", day_of_week=5, is_weather_scenario=True,
        )
        d = asdict(fs)
        reconstructed = _dict_to_feature_set(d)
        assert reconstructed == fs

    def test_dict_backward_compat(self):
        """Dicts missing v2 fields should still reconstruct with defaults."""
        d = {
            "aircraft_category": "narrow", "airline_code": "UAL", "hour_of_day": 14,
            "is_international": False, "arrival_delay_min": 0.0, "gate_id_prefix": "B",
            "is_remote_stand": False, "concurrent_gate_ops": 3, "wind_speed_kt": 5.0,
            "visibility_sm": 10.0, "has_active_ground_stop": False,
            "scheduled_departure_hour": 16,
        }
        fs = _dict_to_feature_set(d)
        assert fs.airport_code == ""
        assert fs.day_of_week == 0
        assert fs.hour_sin == 0.0
        assert fs.hour_cos == 1.0
        assert fs.is_weather_scenario is False


@pytest.mark.skipif(not _has_sim_files(), reason="No simulation files")
class TestExtractTrainingData:
    def test_extract_from_real_file(self):
        samples = extract_training_data(SIM_FILE_SFO)
        assert len(samples) > 50, f"Expected >50 OBT samples, got {len(samples)}"

    def test_sample_has_required_keys(self):
        samples = extract_training_data(SIM_FILE_SFO)
        sample = samples[0]
        assert "features" in sample
        assert "target" in sample
        assert "airport" in sample
        assert "flight_id" in sample

    def test_features_have_all_fields(self):
        samples = extract_training_data(SIM_FILE_SFO)
        features = samples[0]["features"]
        for field in OBTFeatureSet.__dataclass_fields__:
            assert field in features, f"Missing feature: {field}"

    def test_turnaround_durations_within_bounds(self):
        samples = extract_training_data(SIM_FILE_SFO)
        for s in samples:
            assert 10.0 <= s["target"] <= 180.0, (
                f"Turnaround {s['target']} out of bounds"
            )

    def test_no_nan_in_critical_features(self):
        samples = extract_training_data(SIM_FILE_SFO)
        for s in samples:
            f = s["features"]
            assert f["aircraft_category"] in ("narrow", "wide", "regional")
            assert isinstance(f["hour_of_day"], int)
            assert 0 <= f["hour_of_day"] <= 23


# ---------------------------------------------------------------------------
# OBT Predictor
# ---------------------------------------------------------------------------


class TestOBTPredictorFallback:
    def test_fallback_when_untrained(self):
        predictor = OBTPredictor(airport_code="KSFO")
        assert not predictor.is_trained

        fs = _make_full_fs()
        pred = predictor.predict(fs)
        assert pred.turnaround_minutes == 45.0
        assert pred.is_fallback is True
        assert pred.lower_bound_minutes == 45.0 * 0.8
        assert pred.upper_bound_minutes == 45.0 * 1.2

    def test_fallback_wide_body(self):
        predictor = OBTPredictor()
        fs = _make_full_fs(
            aircraft_category="wide", airline_code="BAW", hour_of_day=10,
            is_international=True, gate_id_prefix="A", concurrent_gate_ops=2,
            wind_speed_kt=3.0, scheduled_departure_hour=12,
        )
        pred = predictor.predict(fs)
        assert pred.turnaround_minutes == 90.0
        assert pred.is_fallback is True

    def test_fallback_regional(self):
        predictor = OBTPredictor()
        fs = _make_full_fs(
            aircraft_category="regional", airline_code="SKW", hour_of_day=7,
            gate_id_prefix="F", concurrent_gate_ops=1, wind_speed_kt=0.0,
            scheduled_departure_hour=8,
        )
        pred = predictor.predict(fs)
        assert pred.turnaround_minutes == 35.0


class TestOBTPredictorOBT:
    def test_predict_obt_adds_duration(self):
        predictor = OBTPredictor()
        fs = _make_full_fs()
        parked_ts = 1000000.0
        obt = predictor.predict_obt(parked_ts, fs)
        # Fallback: 45 min = 2700 sec
        assert obt == parked_ts + 45.0 * 60.0


# ---------------------------------------------------------------------------
# Training and prediction end-to-end
# ---------------------------------------------------------------------------


def _make_sample_features(n: int = 100) -> tuple[list[OBTFeatureSet], list[float]]:
    """Generate synthetic training data for unit tests."""
    import random

    rng = random.Random(42)
    features = []
    targets = []

    for _ in range(n):
        cat = rng.choice(["narrow", "wide", "regional"])
        base = {"narrow": 45.0, "wide": 90.0, "regional": 35.0}[cat]
        noise = rng.gauss(0, 5)
        target = max(15.0, base + noise)

        hour = rng.randint(0, 23)
        h_sin, h_cos = _cyclical_hour(hour)
        fs = OBTFeatureSet(
            aircraft_category=cat,
            airline_code=rng.choice(["UAL", "AAL", "DAL", "BAW", "AFR"]),
            hour_of_day=hour,
            is_international=rng.random() > 0.7,
            arrival_delay_min=rng.uniform(0, 30),
            gate_id_prefix=rng.choice(["A", "B", "C", "D"]),
            is_remote_stand=rng.random() > 0.9,
            concurrent_gate_ops=rng.randint(0, 20),
            wind_speed_kt=rng.uniform(0, 25),
            visibility_sm=rng.uniform(1, 10),
            has_active_ground_stop=rng.random() > 0.95,
            scheduled_departure_hour=rng.randint(0, 23),
            airport_code=rng.choice(["SFO", "LAX", "ORD", "JFK", "ATL"]),
            day_of_week=rng.randint(0, 6),
            hour_sin=h_sin,
            hour_cos=h_cos,
            is_weather_scenario=rng.random() > 0.8,
        )
        features.append(fs)
        targets.append(target)

    return features, targets


class TestOBTPredictorTraining:
    def test_train_and_predict(self):
        predictor = OBTPredictor(airport_code="TEST")
        features, targets = _make_sample_features(200)
        result = predictor.train(features, targets)
        assert result["status"] == "trained"
        assert predictor.is_trained

        # Predict on a narrow-body sample
        pred = predictor.predict(features[0])
        assert not pred.is_fallback
        assert 10.0 <= pred.turnaround_minutes <= 180.0

    def test_prediction_in_reasonable_range(self):
        predictor = OBTPredictor(airport_code="TEST")
        features, targets = _make_sample_features(200)
        predictor.train(features, targets)

        for fs in features[:20]:
            pred = predictor.predict(fs)
            assert 10.0 <= pred.turnaround_minutes <= 180.0

    def test_wide_body_generally_longer_than_narrow(self):
        """On average, wide-body predictions should exceed narrow-body."""
        predictor = OBTPredictor(airport_code="TEST")
        features, targets = _make_sample_features(500)
        predictor.train(features, targets)

        narrow_preds = []
        wide_preds = []
        for fs in features:
            pred = predictor.predict(fs)
            if fs.aircraft_category == "narrow":
                narrow_preds.append(pred.turnaround_minutes)
            elif fs.aircraft_category == "wide":
                wide_preds.append(pred.turnaround_minutes)

        if narrow_preds and wide_preds:
            mean_narrow = sum(narrow_preds) / len(narrow_preds)
            mean_wide = sum(wide_preds) / len(wide_preds)
            assert mean_wide > mean_narrow, (
                f"Wide mean ({mean_wide:.1f}) should exceed narrow ({mean_narrow:.1f})"
            )

    def test_feature_importance_available(self):
        predictor = OBTPredictor(airport_code="TEST")
        features, targets = _make_sample_features(200)
        predictor.train(features, targets)

        importances = predictor.get_feature_importances()
        assert importances is not None
        assert len(importances) > 0
        assert "aircraft_category" in importances

    def test_insufficient_data_skips_training(self):
        predictor = OBTPredictor(airport_code="TEST")
        features, targets = _make_sample_features(5)
        result = predictor.train(features[:5], targets[:5])
        assert result["status"] == "insufficient_data"
        assert not predictor.is_trained


class TestOBTModelPersistence:
    def test_save_and_load(self):
        predictor = OBTPredictor(airport_code="TEST")
        features, targets = _make_sample_features(200)
        predictor.train(features, targets)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "obt_model.pkl"
            predictor.save(path)
            assert path.exists()

            loaded = OBTPredictor(airport_code="TEST")
            assert loaded.load(path) is True
            assert loaded.is_trained

            # Predictions should match
            pred_orig = predictor.predict(features[0])
            pred_loaded = loaded.predict(features[0])
            assert abs(pred_orig.turnaround_minutes - pred_loaded.turnaround_minutes) < 0.01

    def test_load_nonexistent(self):
        predictor = OBTPredictor()
        assert predictor.load("/nonexistent/path.pkl") is False


# ---------------------------------------------------------------------------
# Data validation (on real sim files)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _has_sim_files(), reason="No simulation files")
class TestOBTDataValidation:
    def test_all_airports_have_obt_labels(self):
        """Each simulation file should produce at least some OBT samples."""
        for sim_file in sorted(SIM_DIR.glob("simulation_*.json")):
            samples = extract_training_data(sim_file)
            assert len(samples) > 10, (
                f"{sim_file.name} has only {len(samples)} OBT samples"
            )

    def test_turnaround_durations_within_bounds(self):
        samples = extract_training_data(SIM_FILE_SFO)
        for s in samples:
            assert 10.0 <= s["target"] <= 180.0

    def test_no_nan_in_critical_features(self):
        samples = extract_training_data(SIM_FILE_SFO)
        for s in samples:
            f = s["features"]
            assert f["aircraft_category"] in ("narrow", "wide", "regional")
            assert isinstance(f["hour_of_day"], int)
            assert 0 <= f["hour_of_day"] <= 23
            assert isinstance(f["wind_speed_kt"], float)
            assert isinstance(f["visibility_sm"], float)

    def test_baseline_mae_is_calculable(self):
        """Verify we can compute GSE baseline MAE on real data."""
        samples = extract_training_data(SIM_FILE_SFO)
        fallback = {"narrow": 45.0, "wide": 90.0, "regional": 35.0}
        errors = []
        for s in samples:
            cat = s["features"]["aircraft_category"]
            baseline = fallback.get(cat, 45.0)
            errors.append(abs(s["target"] - baseline))
        mae = sum(errors) / len(errors) if errors else 0
        assert mae > 0, "Baseline MAE should be positive (data has variance)"
        assert mae < 50, f"Baseline MAE too high ({mae:.1f}); something is wrong"


# ---------------------------------------------------------------------------
# Integration with ML registry
# ---------------------------------------------------------------------------


class TestOBTRegistryIntegration:
    @patch("src.ml.registry.AirportProfileLoader")
    def test_registry_includes_obt_model(self, mock_loader_cls):
        mock_loader = mock_loader_cls.return_value
        mock_loader.get_profile.return_value = None

        from src.ml.registry import AirportModelRegistry

        registry = AirportModelRegistry()
        models = registry.get_models("KTEST")
        assert "obt" in models
        assert isinstance(models["obt"], OBTPredictor)
        assert models["obt"].airport_code == "KTEST"

    @patch("src.ml.registry.AirportProfileLoader")
    def test_registry_retrain_includes_obt(self, mock_loader_cls):
        mock_loader = mock_loader_cls.return_value
        mock_loader.get_profile.return_value = None

        from src.ml.registry import AirportModelRegistry

        registry = AirportModelRegistry()
        models = registry.retrain("KTEST")
        assert "obt" in models


# ---------------------------------------------------------------------------
# Training pipeline end-to-end (on real sim files)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _has_sim_files(), reason="No simulation files")
class TestOBTTrainingPipeline:
    def test_train_on_real_data(self):
        """Train on SFO simulation and verify basic quality."""
        samples = extract_training_data(SIM_FILE_SFO)
        features = [_dict_to_feature_set(s["features"]) for s in samples]
        targets = [s["target"] for s in samples]

        predictor = OBTPredictor(airport_code="KSFO")
        result = predictor.train(features, targets)
        assert result["status"] == "trained"

        # Verify predictions are in range
        for fs in features[:10]:
            pred = predictor.predict(fs)
            assert 10.0 <= pred.turnaround_minutes <= 180.0
            assert not pred.is_fallback

    def test_multi_airport_training(self):
        """Train on all airports combined."""
        all_features = []
        all_targets = []

        for sim_file in sorted(SIM_DIR.glob("simulation_*.json")):
            samples = extract_training_data(sim_file)
            for s in samples:
                all_features.append(_dict_to_feature_set(s["features"]))
                all_targets.append(s["target"])

        assert len(all_features) > 1000, f"Only {len(all_features)} total samples"

        predictor = OBTPredictor(airport_code="GLOBAL")
        result = predictor.train(all_features, all_targets)
        assert result["status"] == "trained"
        assert predictor.get_feature_importances() is not None


# ---------------------------------------------------------------------------
# T-90 coarse feature set
# ---------------------------------------------------------------------------


class TestOBTCoarseFeatureSet:
    def test_coarse_dataclass_fields(self):
        fs = _make_coarse_fs(arrival_delay_min=10.0, wind_speed_kt=8.0)
        assert fs.aircraft_category == "narrow"
        assert fs.scheduled_departure_hour == 16
        assert fs.airport_code == "SFO"
        assert fs.day_of_week == 2

    def test_coarse_v2_fields_present(self):
        fs = _make_coarse_fs()
        assert hasattr(fs, "airport_code")
        assert hasattr(fs, "day_of_week")
        assert hasattr(fs, "hour_sin")
        assert hasattr(fs, "hour_cos")
        assert hasattr(fs, "is_weather_scenario")

    def test_coarse_features_to_row_length(self):
        fs = _make_coarse_fs(arrival_delay_min=10.0, wind_speed_kt=8.0)
        row = _coarse_features_to_row(fs)
        assert len(row) == len(ALL_COARSE_FEATURE_NAMES)

    def test_full_to_coarse_projection(self):
        full = _make_full_fs(
            aircraft_category="wide", airline_code="BAW", hour_of_day=8,
            is_international=True, arrival_delay_min=15.0, gate_id_prefix="A",
            is_remote_stand=True, concurrent_gate_ops=3, wind_speed_kt=12.0,
            visibility_sm=5.0, has_active_ground_stop=True, scheduled_departure_hour=10,
            airport_code="LHR", day_of_week=4, is_weather_scenario=True,
        )
        coarse = full.to_coarse()
        assert isinstance(coarse, OBTCoarseFeatureSet)
        assert coarse.aircraft_category == "wide"
        assert coarse.airline_code == "BAW"
        assert coarse.scheduled_departure_hour == 10
        assert coarse.is_international is True
        assert coarse.wind_speed_kt == 12.0
        # v2 fields should be projected
        assert coarse.airport_code == "LHR"
        assert coarse.day_of_week == 4
        assert coarse.is_weather_scenario is True
        # Gate-side features should NOT be in coarse
        assert not hasattr(coarse, "gate_id_prefix")
        assert not hasattr(coarse, "concurrent_gate_ops")
        assert not hasattr(coarse, "hour_of_day")

    def test_dict_roundtrip_coarse(self):
        from dataclasses import asdict

        fs = _make_coarse_fs(
            aircraft_category="regional", airline_code="SKW",
            scheduled_departure_hour=7, arrival_delay_min=5.0,
            wind_speed_kt=3.0, visibility_sm=8.0,
            airport_code="ORD", day_of_week=1,
        )
        d = asdict(fs)
        reconstructed = _dict_to_coarse_feature_set(d)
        assert reconstructed == fs

    def test_coarse_dict_backward_compat(self):
        """Dicts missing v2 fields should still reconstruct with defaults."""
        d = {
            "aircraft_category": "narrow", "airline_code": "UAL",
            "scheduled_departure_hour": 16, "is_international": False,
            "arrival_delay_min": 0.0, "wind_speed_kt": 5.0,
            "visibility_sm": 10.0, "has_active_ground_stop": False,
        }
        fs = _dict_to_coarse_feature_set(d)
        assert fs.airport_code == ""
        assert fs.day_of_week == 0


# ---------------------------------------------------------------------------
# T-90 coarse predictor
# ---------------------------------------------------------------------------


class TestOBTCoarsePredictorFallback:
    def test_fallback_when_untrained(self):
        predictor = OBTCoarsePredictor(airport_code="KSFO")
        assert not predictor.is_trained

        fs = _make_coarse_fs()
        pred = predictor.predict(fs)
        assert pred.turnaround_minutes == 45.0
        assert pred.is_fallback is True
        assert pred.horizon == "t90"

    def test_fallback_wide_body(self):
        predictor = OBTCoarsePredictor()
        fs = _make_coarse_fs(
            aircraft_category="wide", airline_code="BAW",
            scheduled_departure_hour=12, is_international=True,
            wind_speed_kt=3.0,
        )
        pred = predictor.predict(fs)
        assert pred.turnaround_minutes == 90.0
        assert pred.horizon == "t90"


class TestOBTCoarsePredictorTraining:
    def test_train_and_predict(self):
        features, targets = _make_sample_features(200)
        coarse_features = [f.to_coarse() for f in features]

        predictor = OBTCoarsePredictor(airport_code="TEST")
        result = predictor.train(coarse_features, targets)
        assert result["status"] == "trained"
        assert predictor.is_trained

        pred = predictor.predict(coarse_features[0])
        assert not pred.is_fallback
        assert pred.horizon == "t90"
        assert 10.0 <= pred.turnaround_minutes <= 180.0

    def test_coarse_has_fewer_features_than_refined(self):
        assert len(ALL_COARSE_FEATURE_NAMES) < len(ALL_FEATURE_NAMES)

    def test_feature_importance_available(self):
        features, targets = _make_sample_features(200)
        coarse_features = [f.to_coarse() for f in features]

        predictor = OBTCoarsePredictor(airport_code="TEST")
        predictor.train(coarse_features, targets)

        importances = predictor.get_feature_importances()
        assert importances is not None
        assert "aircraft_category" in importances
        # Gate-side features should NOT be in importances
        assert "gate_id_prefix" not in importances
        assert "concurrent_gate_ops" not in importances

    def test_save_and_load(self):
        features, targets = _make_sample_features(200)
        coarse_features = [f.to_coarse() for f in features]

        predictor = OBTCoarsePredictor(airport_code="TEST")
        predictor.train(coarse_features, targets)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "obt_coarse.pkl"
            predictor.save(path)

            loaded = OBTCoarsePredictor(airport_code="TEST")
            assert loaded.load(path) is True
            assert loaded.is_trained

            pred_orig = predictor.predict(coarse_features[0])
            pred_loaded = loaded.predict(coarse_features[0])
            assert abs(pred_orig.turnaround_minutes - pred_loaded.turnaround_minutes) < 0.01


# ---------------------------------------------------------------------------
# Two-stage predictor
# ---------------------------------------------------------------------------


class TestTwoStageOBTPredictor:
    def test_train_both_stages(self):
        features, targets = _make_sample_features(300)

        ts = TwoStageOBTPredictor(airport_code="TEST")
        result = ts.train(features, targets)

        assert result["coarse"]["status"] == "trained"
        assert result["refined"]["status"] == "trained"
        assert ts.is_trained

    def test_t90_prediction(self):
        features, targets = _make_sample_features(300)
        ts = TwoStageOBTPredictor(airport_code="TEST")
        ts.train(features, targets)

        coarse = features[0].to_coarse()
        pred = ts.predict_t90(coarse)
        assert pred.horizon == "t90"
        assert 10.0 <= pred.turnaround_minutes <= 180.0

    def test_tpark_prediction(self):
        features, targets = _make_sample_features(300)
        ts = TwoStageOBTPredictor(airport_code="TEST")
        ts.train(features, targets)

        pred = ts.predict_tpark(features[0])
        assert pred.horizon == "t_park"
        assert 10.0 <= pred.turnaround_minutes <= 180.0

    def test_tpark_more_accurate_than_t90(self):
        """Refined model should have lower MAE than coarse on same data."""
        features, targets = _make_sample_features(500)
        ts = TwoStageOBTPredictor(airport_code="TEST")
        ts.train(features, targets)

        t90_errors = []
        tpark_errors = []
        for fs, target in zip(features, targets):
            t90_pred = ts.predict_t90(fs.to_coarse())
            tpark_pred = ts.predict_tpark(fs)
            t90_errors.append(abs(t90_pred.turnaround_minutes - target))
            tpark_errors.append(abs(tpark_pred.turnaround_minutes - target))

        t90_mae = sum(t90_errors) / len(t90_errors)
        tpark_mae = sum(tpark_errors) / len(tpark_errors)
        assert tpark_mae <= t90_mae, (
            f"T-park MAE ({tpark_mae:.1f}) should be <= T-90 MAE ({t90_mae:.1f})"
        )

    def test_t90_confidence_lte_tpark(self):
        """T-90 confidence should be <= T-park (coarse has wider/equal intervals)."""
        features, targets = _make_sample_features(200)
        ts = TwoStageOBTPredictor(airport_code="TEST")
        ts.train(features, targets)

        t90_pred = ts.predict_t90(features[0].to_coarse())
        tpark_pred = ts.predict_tpark(features[0])
        assert t90_pred.confidence <= tpark_pred.confidence

    def test_save_and_load_both(self):
        features, targets = _make_sample_features(200)
        ts = TwoStageOBTPredictor(airport_code="TEST")
        ts.train(features, targets)

        with tempfile.TemporaryDirectory() as tmpdir:
            coarse_path = Path(tmpdir) / "coarse.pkl"
            refined_path = Path(tmpdir) / "refined.pkl"
            ts.save(coarse_path, refined_path)

            loaded = TwoStageOBTPredictor(airport_code="TEST")
            assert loaded.load(coarse_path, refined_path) is True
            assert loaded.is_trained

            # Both stages should produce same predictions
            orig_t90 = ts.predict_t90(features[0].to_coarse())
            loaded_t90 = loaded.predict_t90(features[0].to_coarse())
            assert abs(orig_t90.turnaround_minutes - loaded_t90.turnaround_minutes) < 0.01

    def test_predict_obt_timestamps(self):
        features, targets = _make_sample_features(200)
        ts = TwoStageOBTPredictor(airport_code="TEST")
        ts.train(features, targets)

        scheduled_dep = 1000000.0
        parked_time = 997000.0  # ~50 min before scheduled dep

        obt_t90 = ts.predict_obt_t90(scheduled_dep, features[0].to_coarse())
        obt_tpark = ts.predict_obt_tpark(parked_time, features[0])

        # Both should be reasonable timestamps
        assert obt_t90 > 0
        assert obt_tpark > parked_time


# ---------------------------------------------------------------------------
# Two-stage on real simulation data
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _has_sim_files(), reason="No simulation files")
class TestTwoStageOnRealData:
    def test_train_and_compare(self):
        """Train two-stage on SFO data and verify refined beats coarse."""
        samples = extract_training_data(SIM_FILE_SFO)
        features = [_dict_to_feature_set(s["features"]) for s in samples]
        targets = [s["target"] for s in samples]

        ts = TwoStageOBTPredictor(airport_code="KSFO")
        result = ts.train(features, targets)
        assert result["coarse"]["status"] == "trained"
        assert result["refined"]["status"] == "trained"

        # Compute MAE for both
        t90_errors = []
        tpark_errors = []
        for fs, target in zip(features, targets):
            t90_pred = ts.predict_t90(fs.to_coarse())
            tpark_pred = ts.predict_tpark(fs)
            t90_errors.append(abs(t90_pred.turnaround_minutes - target))
            tpark_errors.append(abs(tpark_pred.turnaround_minutes - target))

        t90_mae = sum(t90_errors) / len(t90_errors)
        tpark_mae = sum(tpark_errors) / len(tpark_errors)

        # T-park should be at least as good (likely better)
        assert tpark_mae <= t90_mae + 1.0, (
            f"T-park MAE ({tpark_mae:.1f}) unexpectedly worse than T-90 ({t90_mae:.1f})"
        )


# ---------------------------------------------------------------------------
# Calibrated data validation
# ---------------------------------------------------------------------------

CALIBRATED_DIR = Path(__file__).resolve().parent.parent / "simulation_output" / "calibrated"


def _has_calibrated_files() -> bool:
    return CALIBRATED_DIR.exists() and len(list(CALIBRATED_DIR.glob("simulation_*.json"))) >= 10


@pytest.mark.skipif(not _has_calibrated_files(), reason="No calibrated simulation files")
class TestCalibratedDataValidation:
    """Validate calibrated simulation data quality and integrity."""

    def test_all_10_airports_present(self):
        """Each calibrated simulation should produce OBT samples."""
        airports_seen = set()
        for sim_file in sorted(CALIBRATED_DIR.glob("simulation_*.json")):
            samples = extract_training_data(sim_file)
            assert len(samples) > 50, (
                f"{sim_file.name} has only {len(samples)} OBT samples (expected >50)"
            )
            for s in samples:
                airports_seen.add(s["airport"])
        assert len(airports_seen) >= 10, (
            f"Expected 10 airports, found {len(airports_seen)}: {airports_seen}"
        )

    def test_total_sample_count(self):
        """Calibrated data should produce sufficient total training samples."""
        total = 0
        for sim_file in sorted(CALIBRATED_DIR.glob("simulation_*.json")):
            total += len(extract_training_data(sim_file))
        assert total >= 2000, f"Only {total} total samples (expected >=2000)"

    def test_turnaround_distribution_has_variance(self):
        """Calibrated data should have realistic turnaround variance, not fixed constants."""
        all_targets = []
        for sim_file in sorted(CALIBRATED_DIR.glob("simulation_*.json")):
            for s in extract_training_data(sim_file):
                all_targets.append(s["target"])

        import numpy as np
        targets = np.array(all_targets)
        std = float(np.std(targets))
        # Calibrated data should have meaningful variance — not just 45/90 min blocks
        assert std > 10.0, (
            f"Turnaround std dev is {std:.1f} min — too low, may indicate uncalibrated data"
        )
        # Range should span from short regionals to long wide-body turnarounds
        assert float(np.max(targets) - np.min(targets)) > 50.0, (
            "Turnaround range too narrow for calibrated data"
        )

    def test_category_balance(self):
        """All three aircraft categories should be represented."""
        categories = set()
        for sim_file in sorted(CALIBRATED_DIR.glob("simulation_*.json")):
            for s in extract_training_data(sim_file):
                categories.add(s["features"]["aircraft_category"])
        assert "narrow" in categories
        assert "wide" in categories
        assert "regional" in categories

    def test_feature_completeness(self):
        """All features should be populated (no NaN/None in critical fields)."""
        for sim_file in sorted(CALIBRATED_DIR.glob("simulation_*.json")):
            for s in extract_training_data(sim_file):
                f = s["features"]
                assert f["aircraft_category"] in ("narrow", "wide", "regional")
                assert isinstance(f["hour_of_day"], int) and 0 <= f["hour_of_day"] <= 23
                assert isinstance(f["wind_speed_kt"], float) and f["wind_speed_kt"] >= 0
                assert isinstance(f["visibility_sm"], float) and f["visibility_sm"] >= 0
                assert isinstance(f["concurrent_gate_ops"], int) and f["concurrent_gate_ops"] >= 0
                assert f["airline_code"] and len(f["airline_code"]) >= 2
                assert f["gate_id_prefix"] and len(f["gate_id_prefix"]) >= 1


@pytest.mark.skipif(not _has_calibrated_files(), reason="No calibrated simulation files")
class TestCalibratedModelQuality:
    """Train on calibrated data and validate model quality thresholds."""

    @pytest.fixture(scope="class")
    def trained_model(self):
        """Train two-stage model on all calibrated data, shared across tests."""
        all_data = []
        for sim_file in sorted(CALIBRATED_DIR.glob("simulation_*.json")):
            all_data.extend(extract_training_data(sim_file))

        # Stratified split
        import numpy as np
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

        ts = TwoStageOBTPredictor(airport_code="GLOBAL")
        train_features = [_dict_to_feature_set(d["features"]) for d in train_data]
        train_targets = [d["target"] for d in train_data]
        ts.train(train_features, train_targets)

        return ts, test_data

    def test_tpark_beats_baseline(self, trained_model):
        """T-park model must beat the GSE constant baseline."""
        ts, test_data = trained_model
        fallback = {"narrow": 45.0, "wide": 90.0, "regional": 35.0}

        baseline_errors = [
            abs(d["target"] - fallback.get(d["features"]["aircraft_category"], 45.0))
            for d in test_data
        ]
        baseline_mae = sum(baseline_errors) / len(baseline_errors)

        tpark_errors = []
        for d in test_data:
            fs = _dict_to_feature_set(d["features"])
            pred = ts.predict_tpark(fs)
            tpark_errors.append(abs(pred.turnaround_minutes - d["target"]))
        tpark_mae = sum(tpark_errors) / len(tpark_errors)

        assert tpark_mae < baseline_mae, (
            f"T-park MAE ({tpark_mae:.2f}) should beat baseline ({baseline_mae:.2f})"
        )

    def test_t90_beats_baseline(self, trained_model):
        """T-90 model must beat the GSE constant baseline."""
        ts, test_data = trained_model
        fallback = {"narrow": 45.0, "wide": 90.0, "regional": 35.0}

        baseline_errors = [
            abs(d["target"] - fallback.get(d["features"]["aircraft_category"], 45.0))
            for d in test_data
        ]
        baseline_mae = sum(baseline_errors) / len(baseline_errors)

        t90_errors = []
        for d in test_data:
            fs = _dict_to_coarse_feature_set(d["features"])
            pred = ts.predict_t90(fs)
            t90_errors.append(abs(pred.turnaround_minutes - d["target"]))
        t90_mae = sum(t90_errors) / len(t90_errors)

        assert t90_mae < baseline_mae, (
            f"T-90 MAE ({t90_mae:.2f}) should beat baseline ({baseline_mae:.2f})"
        )

    def test_tpark_mae_under_threshold(self, trained_model):
        """T-park MAE should be under 8 minutes on calibrated test data."""
        ts, test_data = trained_model
        errors = []
        for d in test_data:
            fs = _dict_to_feature_set(d["features"])
            pred = ts.predict_tpark(fs)
            errors.append(abs(pred.turnaround_minutes - d["target"]))
        mae = sum(errors) / len(errors)
        assert mae < 8.0, f"T-park MAE ({mae:.2f}) exceeds 8 min threshold"

    def test_tpark_r2_above_threshold(self, trained_model):
        """T-park R² should be above 0.7 (meaningful explained variance)."""
        import numpy as np
        ts, test_data = trained_model
        targets, preds = [], []
        for d in test_data:
            fs = _dict_to_feature_set(d["features"])
            pred = ts.predict_tpark(fs)
            targets.append(d["target"])
            preds.append(pred.turnaround_minutes)

        targets_arr = np.array(targets)
        preds_arr = np.array(preds)
        ss_res = float(np.sum((targets_arr - preds_arr) ** 2))
        ss_tot = float(np.sum((targets_arr - np.mean(targets_arr)) ** 2))
        r2 = 1.0 - ss_res / ss_tot
        assert r2 > 0.7, f"T-park R² ({r2:.4f}) below 0.7 threshold"

    def test_tpark_refines_t90(self, trained_model):
        """T-park should have lower MAE than T-90 (more features → better)."""
        ts, test_data = trained_model
        t90_errors, tpark_errors = [], []
        for d in test_data:
            full_fs = _dict_to_feature_set(d["features"])
            coarse_fs = _dict_to_coarse_feature_set(d["features"])
            t90_errors.append(abs(ts.predict_t90(coarse_fs).turnaround_minutes - d["target"]))
            tpark_errors.append(abs(ts.predict_tpark(full_fs).turnaround_minutes - d["target"]))

        t90_mae = sum(t90_errors) / len(t90_errors)
        tpark_mae = sum(tpark_errors) / len(tpark_errors)
        assert tpark_mae < t90_mae, (
            f"T-park MAE ({tpark_mae:.2f}) should be lower than T-90 ({t90_mae:.2f})"
        )

    def test_no_airport_has_extreme_mae(self, trained_model):
        """No single airport should have T-park MAE above 15 minutes."""
        ts, test_data = trained_model
        airport_errors: dict[str, list[float]] = {}
        for d in test_data:
            fs = _dict_to_feature_set(d["features"])
            pred = ts.predict_tpark(fs)
            airport = d.get("airport", "UNK")
            airport_errors.setdefault(airport, []).append(
                abs(pred.turnaround_minutes - d["target"])
            )

        for airport, errors in airport_errors.items():
            mae = sum(errors) / len(errors)
            assert mae < 15.0, (
                f"Airport {airport} has T-park MAE of {mae:.2f} min (threshold: 15)"
            )

    def test_aircraft_category_is_top_feature(self, trained_model):
        """aircraft_category should be among the top 3 features for both models."""
        ts, _ = trained_model

        coarse_imp = ts.coarse.get_feature_importances()
        assert coarse_imp is not None
        top_3_coarse = sorted(coarse_imp, key=coarse_imp.get, reverse=True)[:3]
        assert "aircraft_category" in top_3_coarse, (
            f"aircraft_category not in top 3 coarse features: {top_3_coarse}"
        )

        refined_imp = ts.refined.get_feature_importances()
        assert refined_imp is not None
        top_3_refined = sorted(refined_imp, key=refined_imp.get, reverse=True)[:3]
        assert "aircraft_category" in top_3_refined, (
            f"aircraft_category not in top 3 refined features: {top_3_refined}"
        )


@pytest.mark.skipif(not _has_calibrated_files(), reason="No calibrated simulation files")
class TestCalibratedCrossValidation:
    """Leave-one-airport-out cross-validation to verify generalization."""

    def test_leave_one_airport_out(self):
        """Model trained on 9 airports should predict the 10th reasonably."""
        all_data_by_airport: dict[str, list[dict]] = {}
        for sim_file in sorted(CALIBRATED_DIR.glob("simulation_*.json")):
            for s in extract_training_data(sim_file):
                all_data_by_airport.setdefault(s["airport"], []).append(s)

        # Pick 3 airports to test (not all 10 to keep test fast)
        test_airports = sorted(all_data_by_airport.keys())[:3]
        for held_out_airport in test_airports:
            # Train on all except held-out
            train_data = []
            for airport, samples in all_data_by_airport.items():
                if airport != held_out_airport:
                    train_data.extend(samples)

            predictor = OBTPredictor(airport_code="CV")
            features = [_dict_to_feature_set(d["features"]) for d in train_data]
            targets = [d["target"] for d in train_data]
            predictor.train(features, targets)

            # Evaluate on held-out
            test_samples = all_data_by_airport[held_out_airport]
            errors = []
            for s in test_samples:
                fs = _dict_to_feature_set(s["features"])
                pred = predictor.predict(fs)
                errors.append(abs(pred.turnaround_minutes - s["target"]))

            mae = sum(errors) / len(errors)
            # Held-out airport MAE should still be reasonable (< 20 min)
            assert mae < 20.0, (
                f"Leave-one-out MAE for {held_out_airport} is {mae:.2f} min (threshold: 20)"
            )


# ---------------------------------------------------------------------------
# Edge cases and robustness
# ---------------------------------------------------------------------------


class TestOBTEdgeCases:
    """Test edge cases and robustness of the prediction pipeline."""

    def test_predict_with_extreme_delay(self):
        """Model should handle very high arrival delays gracefully."""
        predictor = OBTPredictor(airport_code="TEST")
        features, targets = _make_sample_features(200)
        predictor.train(features, targets)

        extreme = _make_full_fs(
            hour_of_day=3, arrival_delay_min=120.0,
            concurrent_gate_ops=15, wind_speed_kt=35.0,
            visibility_sm=0.5, has_active_ground_stop=True,
            scheduled_departure_hour=5,
        )
        pred = predictor.predict(extreme)
        assert 10.0 <= pred.turnaround_minutes <= 180.0, (
            f"Extreme conditions gave out-of-range prediction: {pred.turnaround_minutes}"
        )

    def test_predict_with_unseen_airline(self):
        """Model should handle airlines not in training data."""
        predictor = OBTPredictor(airport_code="TEST")
        features, targets = _make_sample_features(200)
        predictor.train(features, targets)

        unseen = _make_full_fs(
            aircraft_category="wide", airline_code="ZZZZZ",
            is_international=True, arrival_delay_min=10.0,
            gate_id_prefix="X", concurrent_gate_ops=5, wind_speed_kt=8.0,
        )
        pred = predictor.predict(unseen)
        assert 10.0 <= pred.turnaround_minutes <= 180.0
        assert not pred.is_fallback

    def test_coarse_predict_with_unseen_airline(self):
        """Coarse model should handle unseen airlines too."""
        features, targets = _make_sample_features(200)
        coarse_features = [f.to_coarse() for f in features]

        predictor = OBTCoarsePredictor(airport_code="TEST")
        predictor.train(coarse_features, targets)

        unseen = _make_coarse_fs(
            aircraft_category="regional", airline_code="NEWAIR",
            scheduled_departure_hour=22, wind_speed_kt=0.0,
        )
        pred = predictor.predict(unseen)
        assert 10.0 <= pred.turnaround_minutes <= 180.0

    def test_two_stage_untrained_uses_fallback(self):
        """Untrained two-stage predictor should use fallback for both horizons."""
        ts = TwoStageOBTPredictor(airport_code="EMPTY")
        assert not ts.is_trained

        coarse_fs = _make_coarse_fs(
            aircraft_category="wide", airline_code="BAW",
            scheduled_departure_hour=10, is_international=True,
        )
        t90_pred = ts.predict_t90(coarse_fs)
        assert t90_pred.is_fallback is True
        assert t90_pred.turnaround_minutes == 90.0
        assert t90_pred.horizon == "t90"

        full_fs = _make_full_fs(
            aircraft_category="wide", airline_code="BAW", hour_of_day=10,
            is_international=True, gate_id_prefix="A", concurrent_gate_ops=2,
            scheduled_departure_hour=12,
        )
        tpark_pred = ts.predict_tpark(full_fs)
        assert tpark_pred.is_fallback is True
        assert tpark_pred.turnaround_minutes == 90.0

    def test_prediction_consistency(self):
        """Same input should always produce same output (deterministic)."""
        predictor = OBTPredictor(airport_code="TEST")
        features, targets = _make_sample_features(200)
        predictor.train(features, targets)

        fs = features[0]
        pred1 = predictor.predict(fs)
        pred2 = predictor.predict(fs)
        assert pred1.turnaround_minutes == pred2.turnaround_minutes

    def test_obt_timestamp_ordering(self):
        """predict_obt should always return a time after parked_time."""
        predictor = OBTPredictor(airport_code="TEST")
        features, targets = _make_sample_features(200)
        predictor.train(features, targets)

        parked_ts = 1700000000.0
        for fs in features[:20]:
            obt = predictor.predict_obt(parked_ts, fs)
            assert obt > parked_ts, (
                f"OBT ({obt}) should be after parked_time ({parked_ts})"
            )


# ---------------------------------------------------------------------------
# Prediction intervals (P10/P90 quantile regression)
# ---------------------------------------------------------------------------


class TestPredictionIntervals:
    def test_trained_model_has_bounds(self):
        """Trained model should produce non-trivial prediction intervals."""
        predictor = OBTPredictor(airport_code="TEST")
        features, targets = _make_sample_features(200)
        predictor.train(features, targets, train_quantiles=True)

        pred = predictor.predict(features[0])
        assert pred.lower_bound_minutes > 0
        assert pred.upper_bound_minutes > pred.lower_bound_minutes
        assert pred.lower_bound_minutes <= pred.turnaround_minutes
        assert pred.upper_bound_minutes >= pred.turnaround_minutes

    def test_quantile_ordering(self):
        """P10 <= median <= P90 for all predictions."""
        predictor = OBTPredictor(airport_code="TEST")
        features, targets = _make_sample_features(300)
        predictor.train(features, targets, train_quantiles=True)

        for fs in features[:30]:
            pred = predictor.predict(fs)
            assert pred.lower_bound_minutes <= pred.turnaround_minutes, (
                f"P10 ({pred.lower_bound_minutes}) > median ({pred.turnaround_minutes})"
            )
            assert pred.upper_bound_minutes >= pred.turnaround_minutes, (
                f"P90 ({pred.upper_bound_minutes}) < median ({pred.turnaround_minutes})"
            )

    def test_confidence_from_interval_width(self):
        """Confidence should be inversely related to interval width."""
        predictor = OBTPredictor(airport_code="TEST")
        features, targets = _make_sample_features(200)
        predictor.train(features, targets, train_quantiles=True)

        pred = predictor.predict(features[0])
        assert 0 < pred.confidence <= 1.0

    def test_no_quantiles_still_works(self):
        """train_quantiles=False should still produce fallback intervals."""
        predictor = OBTPredictor(airport_code="TEST")
        features, targets = _make_sample_features(200)
        predictor.train(features, targets, train_quantiles=False)

        pred = predictor.predict(features[0])
        assert pred.lower_bound_minutes > 0
        assert pred.upper_bound_minutes > 0
        assert not pred.is_fallback

    def test_coarse_prediction_intervals(self):
        """Coarse model should also produce prediction intervals."""
        features, targets = _make_sample_features(200)
        coarse_features = [f.to_coarse() for f in features]

        predictor = OBTCoarsePredictor(airport_code="TEST")
        predictor.train(coarse_features, targets, train_quantiles=True)

        pred = predictor.predict(coarse_features[0])
        assert pred.lower_bound_minutes <= pred.turnaround_minutes
        assert pred.upper_bound_minutes >= pred.turnaround_minutes


# ---------------------------------------------------------------------------
# Cyclical encoding and international detection
# ---------------------------------------------------------------------------


class TestCyclicalEncoding:
    def test_hour_0_and_24_equivalent(self):
        """Hour 0 should produce same encoding as wrapping from 23."""
        h0_sin, h0_cos = _cyclical_hour(0)
        assert abs(h0_cos - 1.0) < 0.001
        assert abs(h0_sin - 0.0) < 0.001

    def test_hour_6(self):
        h_sin, h_cos = _cyclical_hour(6)
        assert abs(h_sin - 1.0) < 0.001
        assert abs(h_cos - 0.0) < 0.001

    def test_hour_12(self):
        h_sin, h_cos = _cyclical_hour(12)
        assert abs(h_sin - 0.0) < 0.001
        assert abs(h_cos - (-1.0)) < 0.001

    def test_hour_23_near_hour_0(self):
        """Hours 23 and 0 should be close in cyclical space."""
        s0, c0 = _cyclical_hour(0)
        s23, c23 = _cyclical_hour(23)
        dist = math.sqrt((s0 - s23) ** 2 + (c0 - c23) ** 2)
        # Should be small — much less than distance between 0 and 12
        dist_0_12 = math.sqrt((s0 - _cyclical_hour(12)[0]) ** 2 + (c0 - _cyclical_hour(12)[1]) ** 2)
        assert dist < dist_0_12


class TestInternationalDetection:
    def test_us_to_us_domestic(self):
        assert _is_international_route("SFO", "LAX", "SFO") is False

    def test_us_to_uk_international(self):
        assert _is_international_route("SFO", "LHR", "SFO") is True

    def test_uk_to_us_international(self):
        assert _is_international_route("LHR", "JFK", "JFK") is True

    def test_unknown_airport_returns_false(self):
        assert _is_international_route("SFO", "ZZZZ", "SFO") is False

    def test_empty_returns_false(self):
        assert _is_international_route("", "SFO", "SFO") is False

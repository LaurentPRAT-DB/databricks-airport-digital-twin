"""Tests for src/ml/obt_model.py — Off-Block Time prediction."""

from __future__ import annotations

import math
import os
import tempfile
from pathlib import Path

import pytest

from src.ml.obt_features import OBTCoarseFeatureSet, OBTFeatureSet
from src.ml.obt_model import (
    OBTCoarsePredictor,
    OBTPrediction,
    OBTPredictor,
    TwoStageOBTPredictor,
    _dict_to_coarse_feature_set,
    _dict_to_feature_set,
    _features_to_row,
    _coarse_features_to_row,
    ALL_FEATURE_NAMES,
    ALL_COARSE_FEATURE_NAMES,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_feature(
    arrival_delay: float = 0.0,
    hour: int = 14,
    turnaround_predicted: float = 0.0,
    **overrides,
) -> OBTFeatureSet:
    h_sin = math.sin(2 * math.pi * hour / 24)
    h_cos = math.cos(2 * math.pi * hour / 24)
    defaults = dict(
        scheduled_departure_hour=hour,
        scheduled_turnaround_min=60.0,
        arrival_delay_min=arrival_delay,
        aircraft_category="narrow",
        airline_code="UAL",
        is_international=False,
        is_hub_connecting=False,
        gate_id_prefix="B",
        is_remote_stand=False,
        concurrent_gate_ops=3,
        airport_code="KSFO",
        hour_of_day=hour,
        day_of_week=2,
        hour_sin=h_sin,
        hour_cos=h_cos,
        wind_speed_kt=8.0,
        visibility_sm=10.0,
        has_active_ground_stop=False,
        turnaround_predicted_min=turnaround_predicted,
    )
    defaults.update(overrides)
    return OBTFeatureSet(**defaults)


def _make_coarse_feature(hour: int = 14, **overrides) -> OBTCoarseFeatureSet:
    h_sin = math.sin(2 * math.pi * hour / 24)
    h_cos = math.cos(2 * math.pi * hour / 24)
    defaults = dict(
        scheduled_departure_hour=hour,
        aircraft_category="narrow",
        airline_code="UAL",
        is_international=False,
        is_hub_connecting=False,
        airport_code="KSFO",
        day_of_week=2,
        hour_sin=h_sin,
        hour_cos=h_cos,
        wind_speed_kt=8.0,
        visibility_sm=10.0,
        has_active_ground_stop=False,
    )
    defaults.update(overrides)
    return OBTCoarseFeatureSet(**defaults)


def _make_training_data(
    n: int = 30,
    base_offset: float = 5.0,
) -> tuple[list[OBTFeatureSet], list[float]]:
    features = []
    targets = []
    for i in range(n):
        hour = 6 + (i % 18)
        delay = float(i * 1.5)
        f = _make_feature(
            arrival_delay=delay,
            hour=hour,
            turnaround_predicted=45.0 + i * 0.5,
            airline_code=["UAL", "DAL", "AAL"][i % 3],
            gate_id_prefix=["A", "B", "C"][i % 3],
            day_of_week=i % 7,
        )
        features.append(f)
        targets.append(base_offset + delay * 0.5 + (i % 5) * 2.0)
    return features, targets


# ---------------------------------------------------------------------------
# Feature conversion tests
# ---------------------------------------------------------------------------

class TestFeatureConversion:
    def test_features_to_row_length(self):
        f = _make_feature()
        row = _features_to_row(f)
        assert len(row) == len(ALL_FEATURE_NAMES)

    def test_coarse_features_to_row_length(self):
        f = _make_coarse_feature()
        row = _coarse_features_to_row(f)
        assert len(row) == len(ALL_COARSE_FEATURE_NAMES)

    def test_dict_roundtrip(self):
        original = _make_feature(arrival_delay=12.5, turnaround_predicted=50.0)
        from dataclasses import asdict
        d = asdict(original)
        reconstructed = _dict_to_feature_set(d)
        assert reconstructed.arrival_delay_min == 12.5
        assert reconstructed.turnaround_predicted_min == 50.0
        assert reconstructed.aircraft_category == "narrow"

    def test_coarse_dict_roundtrip(self):
        original = _make_coarse_feature(hour=10)
        from dataclasses import asdict
        d = asdict(original)
        reconstructed = _dict_to_coarse_feature_set(d)
        assert reconstructed.scheduled_departure_hour == 10
        assert reconstructed.airline_code == "UAL"


# ---------------------------------------------------------------------------
# OBTPredictor — fallback (untrained)
# ---------------------------------------------------------------------------

class TestOBTFallback:
    def test_untrained_prediction_returns_fallback(self):
        pred = OBTPredictor(airport_code="KSFO")
        assert not pred.is_trained
        result = pred.predict(_make_feature())
        assert isinstance(result, OBTPrediction)
        assert result.is_fallback is True
        assert result.confidence == 0.3

    def test_fallback_propagates_arrival_delay(self):
        pred = OBTPredictor()
        result = pred.predict(_make_feature(arrival_delay=20.0))
        assert result.departure_offset_min > 0.0

    def test_fallback_no_delay_returns_zero(self):
        pred = OBTPredictor()
        result = pred.predict(_make_feature(arrival_delay=0.0))
        assert result.departure_offset_min == 0.0

    def test_predict_aobt_untrained(self):
        pred = OBTPredictor()
        sobt = 1700000000.0
        aobt = pred.predict_aobt(sobt, _make_feature())
        assert aobt == sobt  # no delay → AOBT = SOBT

    def test_predict_aobt_with_delay(self):
        pred = OBTPredictor()
        sobt = 1700000000.0
        aobt = pred.predict_aobt(sobt, _make_feature(arrival_delay=20.0))
        assert aobt > sobt


# ---------------------------------------------------------------------------
# OBTPredictor — trained (sklearn)
# ---------------------------------------------------------------------------

class TestOBTTrained:
    def test_train_and_predict(self):
        pred = OBTPredictor(airport_code="KSFO")
        features, targets = _make_training_data(30)
        result = pred.train(features, targets, use_catboost=False)
        assert result["status"] == "trained"
        assert result["n_samples"] == 30
        assert pred.is_trained

        prediction = pred.predict(features[0])
        assert not prediction.is_fallback
        assert -30.0 <= prediction.departure_offset_min <= 120.0
        assert prediction.lower_bound_min <= prediction.departure_offset_min
        assert prediction.departure_offset_min <= prediction.upper_bound_min

    def test_insufficient_data(self):
        pred = OBTPredictor()
        features, targets = _make_training_data(5)
        result = pred.train(features[:5], targets[:5])
        assert result["status"] == "insufficient_data"
        assert not pred.is_trained

    def test_feature_importances(self):
        pred = OBTPredictor()
        features, targets = _make_training_data(30)
        pred.train(features, targets, use_catboost=False)
        imp = pred.get_feature_importances()
        assert imp is not None
        assert len(imp) > 0

    def test_predict_aobt_trained(self):
        pred = OBTPredictor()
        features, targets = _make_training_data(30)
        pred.train(features, targets, use_catboost=False)

        sobt = 1700000000.0
        aobt = pred.predict_aobt(sobt, features[0])
        assert isinstance(aobt, float)

    def test_train_without_quantiles(self):
        pred = OBTPredictor()
        features, targets = _make_training_data(30)
        result = pred.train(
            features, targets,
            use_catboost=False, train_quantiles=False,
        )
        assert result["status"] == "trained"
        prediction = pred.predict(features[0])
        assert not prediction.is_fallback

    def test_confidence_varies_with_interval(self):
        pred = OBTPredictor()
        features, targets = _make_training_data(30)
        pred.train(features, targets, use_catboost=False)

        p1 = pred.predict(features[0])
        assert 0.0 <= p1.confidence <= 1.0


# ---------------------------------------------------------------------------
# OBTPredictor — save/load
# ---------------------------------------------------------------------------

class TestOBTSaveLoad:
    def test_save_and_load(self, tmp_path: Path):
        pred = OBTPredictor(airport_code="EDDF")
        features, targets = _make_training_data(30)
        pred.train(features, targets, use_catboost=False)

        model_path = tmp_path / "obt.pkl"
        pred.save(model_path)
        assert model_path.exists()

        pred2 = OBTPredictor(airport_code="EDDF")
        assert not pred2.is_trained
        assert pred2.load(model_path)
        assert pred2.is_trained

        r1 = pred.predict(features[5])
        r2 = pred2.predict(features[5])
        assert abs(r1.departure_offset_min - r2.departure_offset_min) < 0.01

    def test_load_nonexistent(self):
        pred = OBTPredictor()
        assert not pred.load("/nonexistent/path.pkl")

    def test_load_corrupt(self, tmp_path: Path):
        bad = tmp_path / "corrupt.pkl"
        bad.write_bytes(b"not a pickle")
        pred = OBTPredictor()
        assert not pred.load(bad)


# ---------------------------------------------------------------------------
# OBTCoarsePredictor
# ---------------------------------------------------------------------------

class TestOBTCoarse:
    def test_untrained_fallback(self):
        pred = OBTCoarsePredictor()
        result = pred.predict(_make_coarse_feature())
        assert result.is_fallback
        assert result.horizon == "t_schedule"
        assert result.departure_offset_min == 0.0

    def test_train_and_predict(self):
        pred = OBTCoarsePredictor(airport_code="KSFO")
        features, targets = _make_training_data(30)
        coarse = [
            OBTCoarseFeatureSet(
                scheduled_departure_hour=f.scheduled_departure_hour,
                aircraft_category=f.aircraft_category,
                airline_code=f.airline_code,
                is_international=f.is_international,
                is_hub_connecting=f.is_hub_connecting,
                airport_code=f.airport_code,
                day_of_week=f.day_of_week,
                hour_sin=f.hour_sin,
                hour_cos=f.hour_cos,
                wind_speed_kt=f.wind_speed_kt,
                visibility_sm=f.visibility_sm,
                has_active_ground_stop=f.has_active_ground_stop,
            )
            for f in features
        ]
        result = pred.train(coarse, targets, use_catboost=False)
        assert result["status"] == "trained"
        assert pred.is_trained

        prediction = pred.predict(coarse[0])
        assert not prediction.is_fallback
        assert prediction.horizon == "t_schedule"

    def test_insufficient_data(self):
        pred = OBTCoarsePredictor()
        coarse = [_make_coarse_feature()] * 5
        result = pred.train(coarse, [1.0] * 5)
        assert result["status"] == "insufficient_data"

    def test_predict_aobt(self):
        pred = OBTCoarsePredictor()
        sobt = 1700000000.0
        aobt = pred.predict_aobt(sobt, _make_coarse_feature())
        assert aobt == sobt  # fallback returns 0 offset

    def test_save_load(self, tmp_path: Path):
        pred = OBTCoarsePredictor()
        features, targets = _make_training_data(30)
        coarse = [
            OBTCoarseFeatureSet(
                scheduled_departure_hour=f.scheduled_departure_hour,
                aircraft_category=f.aircraft_category,
                airline_code=f.airline_code,
                is_international=f.is_international,
                is_hub_connecting=f.is_hub_connecting,
                airport_code=f.airport_code,
                day_of_week=f.day_of_week,
                hour_sin=f.hour_sin,
                hour_cos=f.hour_cos,
                wind_speed_kt=f.wind_speed_kt,
                visibility_sm=f.visibility_sm,
                has_active_ground_stop=f.has_active_ground_stop,
            )
            for f in features
        ]
        pred.train(coarse, targets, use_catboost=False)

        p = tmp_path / "coarse.pkl"
        pred.save(p)

        pred2 = OBTCoarsePredictor()
        assert pred2.load(p)
        assert pred2.is_trained


# ---------------------------------------------------------------------------
# TwoStageOBTPredictor
# ---------------------------------------------------------------------------

class TestTwoStageOBT:
    def test_train_both_stages(self):
        pred = TwoStageOBTPredictor(airport_code="KSFO")
        features, targets = _make_training_data(30)
        result = pred.train(features, targets)
        assert result["coarse"]["status"] == "trained"
        assert result["refined"]["status"] == "trained"
        assert pred.is_trained

    def test_predict_at_both_horizons(self):
        pred = TwoStageOBTPredictor()
        features, targets = _make_training_data(30)
        pred.train(features, targets)

        t_park = pred.predict_t_park(features[0])
        assert t_park.horizon == "t_park"
        assert not t_park.is_fallback

        coarse_f = _make_coarse_feature()
        t_sched = pred.predict_t_schedule(coarse_f)
        assert t_sched.horizon == "t_schedule"
        assert not t_sched.is_fallback

    def test_predict_aobt_both(self):
        pred = TwoStageOBTPredictor()
        features, targets = _make_training_data(30)
        pred.train(features, targets)
        sobt = 1700000000.0

        aobt_park = pred.predict_aobt_t_park(sobt, features[0])
        assert isinstance(aobt_park, float)

        aobt_sched = pred.predict_aobt_t_schedule(sobt, _make_coarse_feature())
        assert isinstance(aobt_sched, float)

    def test_save_load(self, tmp_path: Path):
        pred = TwoStageOBTPredictor()
        features, targets = _make_training_data(30)
        pred.train(features, targets)

        cp = tmp_path / "coarse.pkl"
        rp = tmp_path / "refined.pkl"
        pred.save(cp, rp)

        pred2 = TwoStageOBTPredictor()
        assert pred2.load(cp, rp)
        assert pred2.is_trained

    def test_untrained_two_stage(self):
        pred = TwoStageOBTPredictor()
        assert not pred.is_trained


# ---------------------------------------------------------------------------
# OBT training data integration (obt_features.py)
# ---------------------------------------------------------------------------

class TestOBTTrainingDataIntegration:
    def test_extract_and_train_roundtrip(self, tmp_path: Path):
        """Verify extract_obt_training_data output feeds directly into OBTPredictor.train()."""
        import json
        from src.ml.obt_features import extract_obt_training_data

        sim_data = {
            "config": {"airport": "EDDF"},
            "schedule": [
                {
                    "flight_number": "DLH100",
                    "flight_type": "departure",
                    "scheduled_time": "2026-04-15T14:00:00",
                    "airline_code": "DLH",
                    "aircraft_type": "A320",
                    "origin": "EDDF",
                    "destination": "EGLL",
                    "delay_minutes": 5,
                },
            ],
            "phase_transitions": [
                {
                    "time": "2026-04-15T12:30:00",
                    "icao24": "abc001",
                    "callsign": "DLH100",
                    "from_phase": "taxi_to_gate",
                    "to_phase": "parked",
                    "aircraft_type": "A320",
                },
                {
                    "time": "2026-04-15T14:10:00",
                    "icao24": "abc001",
                    "callsign": "DLH100",
                    "from_phase": "parked",
                    "to_phase": "pushback",
                    "aircraft_type": "A320",
                },
            ],
            "gate_events": [
                {
                    "time": "2026-04-15T12:30:00",
                    "icao24": "abc001",
                    "gate": "B12",
                    "event_type": "occupy",
                },
            ],
            "weather_snapshots": [
                {
                    "time": "2026-04-15T12:00:00",
                    "wind_speed_kts": 12,
                    "visibility_sm": 8.0,
                },
            ],
            "scenario_events": [],
        }

        sim_file = tmp_path / "sim.json"
        sim_file.write_text(json.dumps(sim_data))

        samples = extract_obt_training_data(str(sim_file))
        assert len(samples) == 1

        sample = samples[0]
        assert sample["airport"] == "EDDF"
        assert sample["target"] == 10.0  # 14:10 - 14:00 = 10 min offset

        f = _dict_to_feature_set(sample["features"])
        assert f.scheduled_departure_hour == 14
        assert f.airline_code == "DLH"

        pred = OBTPredictor(airport_code="EDDF")
        result = pred.predict(f)
        assert result.is_fallback  # untrained, but proves pipeline works

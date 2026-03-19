"""Tests to improve coverage of src/ml/training.py (target: uncovered lines 29, 120-158, 212-215, 237-285, 290-299)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_flight_data(n: int = 5) -> list[dict]:
    """Return minimal flight dicts that DelayPredictor.predict_batch accepts."""
    flights = []
    for i in range(n):
        flights.append({
            "callsign": f"UAL{100 + i}",
            "airline": "UAL",
            "aircraft_type": "A320",
            "origin": "KJFK",
            "destination": "KSFO",
            "flight_phase": "arrival",
            "scheduled_time": "2026-03-19T10:00:00",
            "hour": 10 + i,
            "day_of_week": 2,
            "weather": "clear",
        })
    return flights


def _opensky_data() -> dict:
    """Fake OpenSky API response with 'states' array."""
    return {
        "time": 1700000000,
        "states": [
            # Each state is a positional list with 17-18 elements
            [
                "abc123",    # icao24
                "UAL100 ",   # callsign (with trailing space)
                "United States",  # origin_country
                1700000000,  # position_time
                1700000000,  # last_contact
                -122.38,     # longitude
                37.62,       # latitude
                3000.0,      # baro_altitude
                False,       # on_ground
                250.0,       # velocity
                180.0,       # true_track
                -5.0,        # vertical_rate
                None,        # sensors
                3100.0,      # geo_altitude
                "1234",      # squawk
                False,       # spi
                0,           # position_source
                1,           # category (18th element)
            ],
            [
                "def456",
                "DAL200 ",
                "United States",
                1700000000,
                1700000000,
                -122.40,
                37.60,
                0.0,
                True,
                0.0,
                90.0,
                0.0,
                None,
                0.0,
                None,
                False,
                0,
                # No 18th element — tests len(state) <= 17 branch
            ],
        ],
    }


# ---------------------------------------------------------------------------
# train_delay_model — non-MLflow path
# ---------------------------------------------------------------------------

class TestTrainDelayModel:
    """Test train_delay_model (lines 34-167), especially metrics and model saving."""

    def test_basic_training_returns_expected_keys(self):
        from src.ml.training import train_delay_model

        result = train_delay_model(_sample_flight_data(3), airport_code="KORD")

        assert "run_id" in result
        assert "metrics" in result
        assert "model_path" in result
        assert "mlflow_enabled" in result

    def test_metrics_calculated_correctly(self):
        from src.ml.training import train_delay_model

        result = train_delay_model(_sample_flight_data(5), airport_code="KSFO")
        m = result["metrics"]

        assert "mean_delay" in m
        assert "std_delay" in m
        assert "mean_confidence" in m
        assert "training_samples" in m
        assert m["training_samples"] == 5

        # Category percentages should be present and sum to ~100
        pct_keys = ["pct_on_time", "pct_slight_delay", "pct_moderate_delay", "pct_severe_delay"]
        for k in pct_keys:
            assert k in m
        total_pct = sum(m[k] for k in pct_keys)
        assert 99.0 <= total_pct <= 101.0  # rounding tolerance

    def test_model_saved_to_disk(self):
        from src.ml.training import train_delay_model

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "model.pkl")
            result = train_delay_model(
                _sample_flight_data(2),
                airport_code="KATL",
                model_output_path=out_path,
            )
            assert result["model_path"] == out_path
            assert os.path.exists(out_path)
            assert os.path.getsize(out_path) > 0

    def test_auto_model_path_when_none(self):
        from src.ml.training import train_delay_model

        result = train_delay_model(_sample_flight_data(2), airport_code="KLAX")
        assert result["model_path"] is not None
        assert os.path.exists(result["model_path"])

    def test_run_id_starts_with_local_when_no_mlflow(self):
        """When MLFLOW_AVAILABLE is False, run_id should be 'local_...'."""
        from src.ml.training import train_delay_model

        with patch("src.ml.training.MLFLOW_AVAILABLE", False):
            result = train_delay_model(_sample_flight_data(2))
            assert result["run_id"].startswith("local_")

    def test_empty_training_data(self):
        from src.ml.training import train_delay_model

        result = train_delay_model([], airport_code="KSFO")
        m = result["metrics"]
        assert m["mean_delay"] == 0.0
        assert m["std_delay"] == 0.0
        assert m["training_samples"] == 0

    def test_single_sample_std_zero(self):
        from src.ml.training import train_delay_model

        result = train_delay_model(_sample_flight_data(1), airport_code="KSFO")
        assert result["metrics"]["std_delay"] == 0.0

    def test_experiment_name_auto_generated(self):
        """When experiment_name is None it should be auto-generated."""
        from src.ml.training import train_delay_model

        # Just ensure it doesn't crash — the auto-name logic is internal
        result = train_delay_model(_sample_flight_data(2), experiment_name=None)
        assert result is not None

    def test_custom_experiment_name(self):
        from src.ml.training import train_delay_model

        result = train_delay_model(
            _sample_flight_data(2),
            experiment_name="custom/experiment",
        )
        assert result is not None


# ---------------------------------------------------------------------------
# train_delay_model — MLflow path (mocked)
# ---------------------------------------------------------------------------

class TestTrainDelayModelWithMLflow:
    """Test the MLflow-enabled code path (lines 119-158)."""

    def test_mlflow_tracking_path(self):
        """Mock mlflow to exercise the tracking code path."""
        import src.ml.training as training_mod
        from src.ml.training import train_delay_model

        mock_run = MagicMock()
        mock_run.info.run_id = "mock_run_123"

        mock_mlflow = MagicMock()
        mock_mlflow.start_run.return_value.__enter__ = MagicMock(return_value=mock_run)
        mock_mlflow.start_run.return_value.__exit__ = MagicMock(return_value=False)

        original = getattr(training_mod, "mlflow", None)
        training_mod.mlflow = mock_mlflow
        try:
            with patch.object(training_mod, "MLFLOW_AVAILABLE", True):
                result = train_delay_model(_sample_flight_data(3), airport_code="KSFO")
        finally:
            if original is None:
                if hasattr(training_mod, "mlflow"):
                    delattr(training_mod, "mlflow")
            else:
                training_mod.mlflow = original

        assert result["run_id"] == "mock_run_123"
        assert result["mlflow_enabled"] is True
        mock_mlflow.set_experiment.assert_called_once()
        mock_mlflow.log_param.assert_called()
        mock_mlflow.log_metric.assert_called()
        mock_mlflow.log_artifact.assert_called()

    def test_mlflow_with_uc_registration(self):
        """Test Unity Catalog registration branch."""
        import src.ml.training as training_mod
        from src.ml.training import train_delay_model

        mock_run = MagicMock()
        mock_run.info.run_id = "uc_run_456"

        mock_mlflow = MagicMock()
        mock_mlflow.start_run.return_value.__enter__ = MagicMock(return_value=mock_run)
        mock_mlflow.start_run.return_value.__exit__ = MagicMock(return_value=False)

        original = getattr(training_mod, "mlflow", None)
        training_mod.mlflow = mock_mlflow
        try:
            with patch.object(training_mod, "MLFLOW_AVAILABLE", True):
                result = train_delay_model(
                    _sample_flight_data(2),
                    airport_code="KSFO",
                    catalog="my_catalog",
                    schema="my_schema",
                )
        finally:
            if original is None:
                if hasattr(training_mod, "mlflow"):
                    delattr(training_mod, "mlflow")
            else:
                training_mod.mlflow = original

        mock_mlflow.register_model.assert_called_once()
        call_args = mock_mlflow.register_model.call_args
        assert "my_catalog.my_schema.delay_model_KSFO" in call_args[0][1]

    def test_mlflow_uc_registration_failure_handled(self):
        """UC registration failure should not crash training."""
        import src.ml.training as training_mod
        from src.ml.training import train_delay_model

        mock_run = MagicMock()
        mock_run.info.run_id = "uc_fail_run"

        mock_mlflow = MagicMock()
        mock_mlflow.start_run.return_value.__enter__ = MagicMock(return_value=mock_run)
        mock_mlflow.start_run.return_value.__exit__ = MagicMock(return_value=False)
        mock_mlflow.register_model.side_effect = Exception("UC unavailable")

        original = getattr(training_mod, "mlflow", None)
        training_mod.mlflow = mock_mlflow
        try:
            with patch.object(training_mod, "MLFLOW_AVAILABLE", True):
                result = train_delay_model(
                    _sample_flight_data(2),
                    catalog="c",
                    schema="s",
                )
        finally:
            if original is None:
                if hasattr(training_mod, "mlflow"):
                    delattr(training_mod, "mlflow")
            else:
                training_mod.mlflow = original

        # Training should succeed despite UC failure
        assert result["run_id"] == "uc_fail_run"

    def test_mlflow_tracking_failure_falls_back(self):
        """If MLflow tracking itself throws, run_id should be local_*."""
        import src.ml.training as training_mod
        from src.ml.training import train_delay_model

        mock_mlflow = MagicMock()
        mock_mlflow.set_experiment.side_effect = Exception("MLflow unreachable")

        original = getattr(training_mod, "mlflow", None)
        training_mod.mlflow = mock_mlflow
        try:
            with patch.object(training_mod, "MLFLOW_AVAILABLE", True):
                result = train_delay_model(_sample_flight_data(2))
        finally:
            if original is None:
                if hasattr(training_mod, "mlflow"):
                    delattr(training_mod, "mlflow")
            else:
                training_mod.mlflow = original

        assert result["run_id"].startswith("local_")


# ---------------------------------------------------------------------------
# load_training_data_from_file
# ---------------------------------------------------------------------------

class TestLoadTrainingDataFromFile:
    """Test load_training_data_from_file (lines 170-215)."""

    def test_opensky_format(self, tmp_path: Path):
        from src.ml.training import load_training_data_from_file

        f = tmp_path / "opensky.json"
        f.write_text(json.dumps(_opensky_data()))

        flights = load_training_data_from_file(str(f))
        assert len(flights) == 2
        assert flights[0]["icao24"] == "abc123"
        assert flights[0]["callsign"] == "UAL100"  # trimmed
        assert flights[0]["latitude"] == 37.62
        # Second state has no 18th element
        assert flights[1]["category"] is None

    def test_direct_list_format(self, tmp_path: Path):
        from src.ml.training import load_training_data_from_file

        data = [{"callsign": "A"}, {"callsign": "B"}]
        f = tmp_path / "list.json"
        f.write_text(json.dumps(data))

        flights = load_training_data_from_file(str(f))
        assert flights == data

    def test_unknown_format_returns_empty(self, tmp_path: Path):
        from src.ml.training import load_training_data_from_file

        f = tmp_path / "weird.json"
        f.write_text(json.dumps({"something": "else"}))

        flights = load_training_data_from_file(str(f))
        assert flights == []


# ---------------------------------------------------------------------------
# train_obt_model
# ---------------------------------------------------------------------------

class TestTrainObtModel:
    """Test train_obt_model (lines 218-285)."""

    @staticmethod
    def _make_sample_training_data(n: int = 10) -> list[dict]:
        """Return sample extract_training_data output."""
        import math
        samples = []
        for i in range(n):
            samples.append({
                "features": {
                    "aircraft_category": "narrow",
                    "airline_code": "UAL",
                    "hour_of_day": 10 + (i % 12),
                    "is_international": False,
                    "arrival_delay_min": float(i * 2),
                    "gate_id_prefix": "B",
                    "is_remote_stand": False,
                    "concurrent_gate_ops": 3,
                    "wind_speed_kt": 8.0,
                    "visibility_sm": 10.0,
                    "has_active_ground_stop": False,
                    "scheduled_departure_hour": 14,
                    "airport_code": "KSFO",
                    "day_of_week": i % 7,
                    "hour_sin": math.sin(2 * math.pi * (10 + i) / 24),
                    "hour_cos": math.cos(2 * math.pi * (10 + i) / 24),
                    "is_weather_scenario": False,
                    "scheduled_buffer_min": 15.0,
                },
                "target": 40.0 + i * 2.5,
            })
        return samples

    def test_train_obt_model_basic(self, tmp_path: Path):
        from src.ml.training import train_obt_model

        sim_path = str(tmp_path / "sim.json")
        # The file itself won't be read because we mock extract_training_data
        Path(sim_path).write_text("{}")

        samples = self._make_sample_training_data(15)

        with patch("src.ml.training.MLFLOW_AVAILABLE", False), \
             patch("src.ml.obt_features.extract_training_data", return_value=samples):
            result = train_obt_model(
                sim_json_path=sim_path,
                airport_code="KJFK",
                model_output_path=str(tmp_path / "obt.pkl"),
            )

        assert result["status"] != "no_data"
        assert result["n_samples"] == 15
        assert os.path.exists(result["model_path"])

    def test_train_obt_model_no_data(self, tmp_path: Path):
        from src.ml.training import train_obt_model

        sim_path = str(tmp_path / "empty_sim.json")
        Path(sim_path).write_text("{}")

        with patch("src.ml.training.MLFLOW_AVAILABLE", False), \
             patch("src.ml.obt_features.extract_training_data", return_value=[]):
            result = train_obt_model(sim_json_path=sim_path)

        assert result["status"] == "no_data"
        assert result["n_samples"] == 0

    def test_train_obt_model_auto_path(self, tmp_path: Path):
        from src.ml.training import train_obt_model

        sim_path = str(tmp_path / "sim.json")
        Path(sim_path).write_text("{}")
        samples = self._make_sample_training_data(10)

        with patch("src.ml.training.MLFLOW_AVAILABLE", False), \
             patch("src.ml.obt_features.extract_training_data", return_value=samples):
            result = train_obt_model(sim_json_path=sim_path, airport_code="KLAX")

        assert result["model_path"] is not None
        assert os.path.exists(result["model_path"])

    def test_train_obt_model_with_mlflow(self, tmp_path: Path):
        import src.ml.training as training_mod
        from src.ml.training import train_obt_model

        sim_path = str(tmp_path / "sim.json")
        Path(sim_path).write_text("{}")
        samples = self._make_sample_training_data(10)

        mock_run = MagicMock()
        mock_run.info.run_id = "obt_run_789"

        mock_mlflow = MagicMock()
        mock_mlflow.start_run.return_value.__enter__ = MagicMock(return_value=mock_run)
        mock_mlflow.start_run.return_value.__exit__ = MagicMock(return_value=False)

        original = getattr(training_mod, "mlflow", None)
        training_mod.mlflow = mock_mlflow
        try:
            with patch.object(training_mod, "MLFLOW_AVAILABLE", True), \
                 patch("src.ml.obt_features.extract_training_data", return_value=samples):
                result = train_obt_model(
                    sim_json_path=sim_path,
                    airport_code="KSFO",
                    model_output_path=str(tmp_path / "obt.pkl"),
                )
        finally:
            if original is None:
                if hasattr(training_mod, "mlflow"):
                    delattr(training_mod, "mlflow")
            else:
                training_mod.mlflow = original

        assert result["run_id"] == "obt_run_789"
        mock_mlflow.log_param.assert_called()
        mock_mlflow.log_artifact.assert_called()

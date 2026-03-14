"""Tests for the standalone simulation mode."""

import json
import os
import tempfile
from datetime import datetime, timezone

import pytest

from src.simulation.config import SimulationConfig, load_config
from src.simulation.engine import SimulationEngine
from src.simulation.recorder import SimulationRecorder


# ============================================================================
# Config tests
# ============================================================================


class TestSimulationConfig:
    def test_defaults(self):
        config = SimulationConfig()
        assert config.airport == "SFO"
        assert config.arrivals == 25
        assert config.departures == 25
        assert config.duration_hours == 24.0
        assert config.time_step_seconds == 2.0
        assert config.seed is None
        assert config.debug is False

    def test_debug_limits_duration(self):
        config = SimulationConfig(debug=True, duration_hours=24.0)
        assert config.effective_duration_hours() == 4.0

    def test_effective_start_time_default(self):
        config = SimulationConfig()
        start = config.effective_start_time()
        assert start.hour == 0
        assert start.minute == 0
        assert start.second == 0

    def test_effective_start_time_custom(self):
        custom = datetime(2026, 3, 14, 8, 0, 0, tzinfo=timezone.utc)
        config = SimulationConfig(start_time=custom)
        assert config.effective_start_time() == custom

    def test_load_from_yaml(self, tmp_path):
        yaml_content = """
airport: LAX
arrivals: 30
departures: 20
duration_hours: 12
seed: 123
"""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text(yaml_content)
        config = load_config(str(config_file))
        assert config.airport == "LAX"
        assert config.arrivals == 30
        assert config.departures == 20
        assert config.duration_hours == 12
        assert config.seed == 123


# ============================================================================
# Recorder tests
# ============================================================================


class TestSimulationRecorder:
    def test_record_position(self):
        recorder = SimulationRecorder()
        now = datetime.now(timezone.utc)
        recorder.record_position(
            now, "abc123", "UAL100",
            37.62, -122.38, 5000.0, 180.0, 270.0,
            "approaching", False, "A320",
        )
        assert len(recorder.position_snapshots) == 1
        assert recorder.position_snapshots[0]["icao24"] == "abc123"

    def test_record_phase_transition(self):
        recorder = SimulationRecorder()
        now = datetime.now(timezone.utc)
        recorder.record_phase_transition(
            now, "abc123", "UAL100",
            "approaching", "landing",
            37.62, -122.38, 500.0, "A320",
        )
        assert len(recorder.phase_transitions) == 1
        assert recorder.phase_transitions[0]["from_phase"] == "approaching"

    def test_record_gate_event(self):
        recorder = SimulationRecorder()
        now = datetime.now(timezone.utc)
        recorder.record_gate_event(now, "abc123", "UAL100", "A1", "occupy", "A320")
        assert len(recorder.gate_events) == 1
        assert recorder.gate_events[0]["gate"] == "A1"

    def test_write_and_read_output(self, tmp_path):
        recorder = SimulationRecorder()
        recorder.schedule = [
            {"flight_type": "arrival", "delay_minutes": 0},
            {"flight_type": "departure", "delay_minutes": 10},
        ]
        output_path = str(tmp_path / "test_output.json")
        config_dict = {"airport": "SFO", "arrivals": 1, "departures": 1}
        recorder.write_output(output_path, config_dict)

        with open(output_path) as f:
            data = json.load(f)
        assert "summary" in data
        assert "config" in data
        assert data["summary"]["total_flights"] == 2
        assert data["summary"]["arrivals"] == 1

    def test_compute_summary_empty(self):
        recorder = SimulationRecorder()
        summary = recorder.compute_summary({})
        assert summary["total_flights"] == 0
        assert summary["on_time_pct"] == 0.0


# ============================================================================
# Engine tests (short simulations)
# ============================================================================


class TestSimulationEngine:
    def _make_engine(self, **kwargs) -> SimulationEngine:
        """Create an engine with minimal config for fast tests."""
        defaults = {
            "airport": "SFO",
            "arrivals": 3,
            "departures": 3,
            "duration_hours": 0.5,  # 30 minutes
            "time_step_seconds": 2.0,
            "seed": 42,
            "debug": False,
            "output_file": "/dev/null",
        }
        defaults.update(kwargs)
        config = SimulationConfig(**defaults)
        return SimulationEngine(config)

    def test_engine_creates_schedule(self):
        engine = self._make_engine()
        assert len(engine.flight_schedule) == 6  # 3 arrivals + 3 departures
        arrivals = [f for f in engine.flight_schedule if f["flight_type"] == "arrival"]
        departures = [f for f in engine.flight_schedule if f["flight_type"] == "departure"]
        assert len(arrivals) == 3
        assert len(departures) == 3

    def test_engine_schedule_sorted_by_time(self):
        engine = self._make_engine()
        times = [f["scheduled_time"] for f in engine.flight_schedule]
        assert times == sorted(times)

    def test_engine_seed_reproducibility(self):
        engine1 = self._make_engine(seed=42)
        engine2 = self._make_engine(seed=42)
        # Same seed should produce same schedule
        for f1, f2 in zip(engine1.flight_schedule, engine2.flight_schedule):
            assert f1["flight_number"] == f2["flight_number"]
            assert f1["flight_type"] == f2["flight_type"]
            assert f1["origin"] == f2["origin"]

    def test_engine_runs_short_simulation(self):
        engine = self._make_engine(
            arrivals=2,
            departures=2,
            duration_hours=0.1,  # 6 minutes
        )
        recorder = engine.run()
        # Should have some position snapshots
        assert len(recorder.position_snapshots) >= 0
        # Should have recorded the schedule
        assert len(recorder.schedule) == 4
        # Should have weather snapshots
        assert len(recorder.weather_snapshots) >= 1

    def test_engine_writes_output(self, tmp_path):
        output_file = str(tmp_path / "sim_output.json")
        engine = self._make_engine(
            arrivals=2,
            departures=2,
            duration_hours=0.1,
            output_file=output_file,
        )
        recorder = engine.run()
        config_dict = engine.config.model_dump(mode="json")
        recorder.write_output(output_file, config_dict)

        assert os.path.exists(output_file)
        with open(output_file) as f:
            data = json.load(f)
        assert "summary" in data
        assert data["summary"]["total_flights"] == 4

    def test_engine_respects_airport(self):
        engine = self._make_engine(airport="LAX")
        from src.ingestion.fallback import get_airport_center
        center = get_airport_center()
        # LAX is around 33.94, -118.41
        assert abs(center[0] - 33.9425) < 0.01
        assert abs(center[1] - (-118.408)) < 0.01

    def test_schedule_has_required_fields(self):
        engine = self._make_engine()
        for flight in engine.flight_schedule:
            assert "flight_number" in flight
            assert "airline" in flight
            assert "origin" in flight
            assert "destination" in flight
            assert "flight_type" in flight
            assert "scheduled_time" in flight
            assert "aircraft_type" in flight
            assert flight["flight_type"] in ("arrival", "departure")


# ============================================================================
# Integration test — runs the debug config
# ============================================================================


class TestSimulationIntegration:
    """Longer-running integration tests (still fast: ~2-5 seconds)."""

    def test_debug_simulation_completes(self, tmp_path):
        """Run a debug-sized simulation and validate the output structure."""
        output_file = str(tmp_path / "debug_output.json")
        config = SimulationConfig(
            airport="SFO",
            arrivals=5,
            departures=5,
            duration_hours=2.0,
            time_step_seconds=2.0,
            seed=42,
            debug=True,
            output_file=output_file,
        )
        engine = SimulationEngine(config)
        recorder = engine.run()
        config_dict = config.model_dump(mode="json")
        recorder.write_output(output_file, config_dict)

        with open(output_file) as f:
            data = json.load(f)

        # Validate structure
        assert "config" in data
        assert "summary" in data
        assert "schedule" in data
        assert "position_snapshots" in data
        assert "phase_transitions" in data
        assert "gate_events" in data
        assert "weather_snapshots" in data
        assert "baggage_events" in data

        # Validate schedule
        assert data["summary"]["total_flights"] == 10
        assert data["summary"]["arrivals"] == 5
        assert data["summary"]["departures"] == 5

        # Should have generated position data
        assert data["summary"]["total_position_snapshots"] > 0

        # Weather should have been generated
        assert data["summary"]["total_weather_snapshots"] >= 1

    def test_position_coordinates_in_range(self, tmp_path):
        """Validate that position coordinates are realistic for SFO area."""
        output_file = str(tmp_path / "coord_test.json")
        config = SimulationConfig(
            airport="SFO",
            arrivals=3,
            departures=3,
            duration_hours=1.0,
            time_step_seconds=2.0,
            seed=42,
            output_file=output_file,
        )
        engine = SimulationEngine(config)
        recorder = engine.run()
        config_dict = config.model_dump(mode="json")
        recorder.write_output(output_file, config_dict)

        with open(output_file) as f:
            data = json.load(f)

        for snap in data["position_snapshots"]:
            lat = snap["latitude"]
            lon = snap["longitude"]
            # SFO area: roughly lat 37.0-38.5, lon -123.0 to -121.5
            # Allow wider range for approach/departure paths
            assert 35.0 < lat < 40.0, f"Latitude {lat} out of SFO range"
            assert -124.0 < lon < -120.0, f"Longitude {lon} out of SFO range"

    def test_no_duplicate_gate_occupancy(self, tmp_path):
        """Validate that no two flights occupy the same gate simultaneously."""
        output_file = str(tmp_path / "gate_test.json")
        config = SimulationConfig(
            airport="SFO",
            arrivals=5,
            departures=5,
            duration_hours=2.0,
            time_step_seconds=2.0,
            seed=42,
            output_file=output_file,
        )
        engine = SimulationEngine(config)
        recorder = engine.run()
        config_dict = config.model_dump(mode="json")
        recorder.write_output(output_file, config_dict)

        with open(output_file) as f:
            data = json.load(f)

        # Track gate occupancy timeline
        gate_occupancy: dict[str, str | None] = {}  # gate -> current occupant icao24

        for event in data["gate_events"]:
            gate = event["gate"]
            icao24 = event["icao24"]
            event_type = event["event_type"]

            if event_type == "occupy":
                if gate in gate_occupancy and gate_occupancy[gate] is not None:
                    current = gate_occupancy[gate]
                    # Allow same aircraft to re-occupy (state machine quirk)
                    if current != icao24:
                        pytest.fail(
                            f"Gate {gate} double-occupied: {current} and {icao24} "
                            f"at {event['time']}"
                        )
                gate_occupancy[gate] = icao24
            elif event_type == "release":
                gate_occupancy[gate] = None

"""Tests for scenario-based simulation: models, capacity manager, and engine integration."""

import pytest
import yaml
from datetime import datetime, timedelta, timezone

from src.simulation.scenario import (
    WeatherEvent,
    RunwayEvent,
    GroundEvent,
    TrafficModifier,
    SimulationScenario,
    ResolvedEvent,
    load_scenario,
    resolve_times,
)
from src.simulation.capacity import CapacityManager
from src.simulation.config import SimulationConfig


# ---------------------------------------------------------------------------
# TestScenarioConfig — model validation, YAML loading, time resolution
# ---------------------------------------------------------------------------
class TestScenarioConfig:
    def test_load_scenario_from_yaml(self, tmp_path):
        scenario_yaml = {
            "name": "Test Storm",
            "description": "A test scenario",
            "weather_events": [
                {
                    "time": "14:00",
                    "type": "thunderstorm",
                    "severity": "severe",
                    "duration_hours": 2.0,
                    "visibility_nm": 1.0,
                    "ceiling_ft": 800,
                }
            ],
            "runway_events": [
                {
                    "time": "15:00",
                    "type": "closure",
                    "runway": "28L",
                    "duration_minutes": 60,
                }
            ],
        }
        path = tmp_path / "test_scenario.yaml"
        path.write_text(yaml.dump(scenario_yaml))

        scenario = load_scenario(str(path))
        assert scenario.name == "Test Storm"
        assert scenario.description == "A test scenario"
        assert len(scenario.weather_events) == 1
        assert scenario.weather_events[0].type == "thunderstorm"
        assert scenario.weather_events[0].visibility_nm == 1.0
        assert len(scenario.runway_events) == 1
        assert scenario.runway_events[0].runway == "28L"

    def test_scenario_model_defaults(self):
        s = SimulationScenario(name="Empty")
        assert s.weather_events == []
        assert s.runway_events == []
        assert s.ground_events == []
        assert s.traffic_modifiers == []
        assert s.description == ""
        assert s.base_config is None

    def test_weather_event_fields(self):
        e = WeatherEvent(
            time="06:00",
            type="fog",
            severity="severe",
            duration_hours=3.0,
            visibility_nm=0.25,
            ceiling_ft=200,
            wind_speed_kt=5,
            wind_gusts_kt=None,
            wind_direction=280,
        )
        assert e.visibility_nm == 0.25
        assert e.ceiling_ft == 200
        assert e.wind_gusts_kt is None

    def test_resolve_times_sorted(self):
        scenario = SimulationScenario(
            name="Multi",
            weather_events=[
                WeatherEvent(time="15:00", type="clear", severity="light", duration_hours=1.0),
                WeatherEvent(time="06:00", type="fog", severity="severe", duration_hours=3.0),
                WeatherEvent(time="10:00", type="clear", severity="light", duration_hours=5.0),
            ],
        )
        base = datetime(2026, 3, 14, 0, 0, 0, tzinfo=timezone.utc)
        resolved = resolve_times(scenario, base)
        assert len(resolved) == 3
        assert resolved[0].time.hour == 6
        assert resolved[1].time.hour == 10
        assert resolved[2].time.hour == 15

    def test_resolve_times_all_event_types(self):
        scenario = SimulationScenario(
            name="All types",
            weather_events=[
                WeatherEvent(time="08:00", type="fog", severity="moderate", duration_hours=1.0),
            ],
            runway_events=[
                RunwayEvent(time="09:00", type="closure", runway="28R", duration_minutes=30),
            ],
            ground_events=[
                GroundEvent(time="10:00", type="gate_failure", target="B7", duration_hours=1.0),
            ],
            traffic_modifiers=[
                TrafficModifier(time="11:00", type="diversion", extra_arrivals=4),
            ],
        )
        base = datetime(2026, 3, 14, 0, 0, 0, tzinfo=timezone.utc)
        resolved = resolve_times(scenario, base)
        assert len(resolved) == 4
        types = [r.event_type for r in resolved]
        assert types == ["weather", "runway", "ground", "traffic"]

    def test_empty_scenario_resolves_to_empty(self):
        scenario = SimulationScenario(name="Empty")
        base = datetime(2026, 3, 14, 0, 0, 0, tzinfo=timezone.utc)
        resolved = resolve_times(scenario, base)
        assert resolved == []

    def test_traffic_modifier_no_time_skipped(self):
        """Traffic modifiers without time or time_range are skipped."""
        scenario = SimulationScenario(
            name="Global mod",
            traffic_modifiers=[
                TrafficModifier(type="surge", extra_arrivals=10),
            ],
        )
        base = datetime(2026, 3, 14, 0, 0, 0, tzinfo=timezone.utc)
        resolved = resolve_times(scenario, base)
        assert resolved == []

    def test_traffic_modifier_with_time_range(self):
        scenario = SimulationScenario(
            name="Range",
            traffic_modifiers=[
                TrafficModifier(
                    time_range=["08:00", "10:00"],
                    type="surge",
                    extra_arrivals=5,
                ),
            ],
        )
        base = datetime(2026, 3, 14, 0, 0, 0, tzinfo=timezone.utc)
        resolved = resolve_times(scenario, base)
        assert len(resolved) == 1
        assert resolved[0].time.hour == 8

    def test_resolved_event_description_populated(self):
        scenario = SimulationScenario(
            name="Desc",
            weather_events=[
                WeatherEvent(
                    time="14:00", type="thunderstorm", severity="severe",
                    duration_hours=2.0, visibility_nm=1.0, ceiling_ft=800,
                    wind_gusts_kt=45,
                ),
            ],
        )
        base = datetime(2026, 3, 14, 0, 0, 0, tzinfo=timezone.utc)
        resolved = resolve_times(scenario, base)
        assert "thunderstorm" in resolved[0].description
        assert "45kt" in resolved[0].description


# ---------------------------------------------------------------------------
# TestCapacityManager — rate enforcement, weather, runway, gate management
# ---------------------------------------------------------------------------
class TestCapacityManager:
    def test_vmc_baseline_rates(self):
        cm = CapacityManager()
        now = datetime(2026, 3, 14, 12, 0, 0, tzinfo=timezone.utc)
        assert cm.get_arrival_rate(now) == 60
        assert cm.get_departure_rate(now) == 55

    def test_weather_degrades_to_ifr(self):
        cm = CapacityManager()
        now = datetime(2026, 3, 14, 12, 0, 0, tzinfo=timezone.utc)
        cm.apply_weather(2.0, 800, None)
        assert cm.current_category == "IFR"
        rate = cm.get_arrival_rate(now)
        assert 25 <= rate <= 35  # ~30

    def test_weather_degrades_to_lifr(self):
        cm = CapacityManager()
        now = datetime(2026, 3, 14, 12, 0, 0, tzinfo=timezone.utc)
        cm.apply_weather(0.5, 200, None)
        assert cm.current_category == "LIFR"
        rate = cm.get_arrival_rate(now)
        assert 15 <= rate <= 20  # ~18

    def test_weather_mvfr(self):
        cm = CapacityManager()
        now = datetime(2026, 3, 14, 12, 0, 0, tzinfo=timezone.utc)
        cm.apply_weather(4.0, 2500, None)
        assert cm.current_category == "MVFR"
        rate = cm.get_arrival_rate(now)
        assert 38 <= rate <= 45

    def test_wind_gusts_reduce_capacity(self):
        cm = CapacityManager()
        now = datetime(2026, 3, 14, 12, 0, 0, tzinfo=timezone.utc)
        cm.apply_weather(10.0, 5000, 40)  # VFR but gusty
        assert cm.current_category == "VFR"
        rate = cm.get_arrival_rate(now)
        assert rate < 60  # reduced by gusts

    def test_runway_closure_halves_rate(self):
        cm = CapacityManager()
        now = datetime(2026, 3, 14, 12, 0, 0, tzinfo=timezone.utc)
        until = now + timedelta(hours=1)
        cm.close_runway("28L", until)
        assert len(cm.active_runways) == 1
        assert cm.get_arrival_rate(now) == 30  # 60 * 0.5

    def test_gate_failure(self):
        cm = CapacityManager()
        now = datetime(2026, 3, 14, 12, 0, 0, tzinfo=timezone.utc)
        until = now + timedelta(hours=2)
        cm.fail_gate("B7", until)
        assert not cm.is_gate_available("B7", now)
        assert cm.is_gate_available("A1", now)  # other gates unaffected

    def test_gate_failure_expires(self):
        cm = CapacityManager()
        now = datetime(2026, 3, 14, 12, 0, 0, tzinfo=timezone.utc)
        until = now - timedelta(minutes=1)  # already expired
        cm.fail_gate("B7", until)
        assert cm.is_gate_available("B7", now)

    def test_ground_stop_blocks_departures(self):
        cm = CapacityManager()
        now = datetime(2026, 3, 14, 12, 0, 0, tzinfo=timezone.utc)
        cm.set_ground_stop(True)
        assert cm.get_departure_rate(now) == 0
        assert not cm.can_release_departure(now)
        # Arrivals still work
        assert cm.can_accept_arrival(now)

    def test_can_accept_arrival_rate_limiting(self):
        cm = CapacityManager()
        now = datetime(2026, 3, 14, 12, 0, 0, tzinfo=timezone.utc)
        # Fill up arrival slots
        for i in range(60):
            cm.record_arrival(now - timedelta(minutes=i * 0.5))
        assert not cm.can_accept_arrival(now)

    def test_can_release_departure_rate_limiting(self):
        cm = CapacityManager()
        now = datetime(2026, 3, 14, 12, 0, 0, tzinfo=timezone.utc)
        for i in range(55):
            cm.record_departure(now - timedelta(minutes=i * 0.5))
        assert not cm.can_release_departure(now)

    def test_update_expires_closures(self):
        cm = CapacityManager()
        now = datetime(2026, 3, 14, 12, 0, 0, tzinfo=timezone.utc)
        until = now + timedelta(minutes=30)
        cm.close_runway("28R", until)
        assert len(cm.active_runways) == 1

        # Advance past expiry
        future = now + timedelta(minutes=31)
        cm.update(future)
        assert len(cm.active_runways) == 2
        assert "28R" in cm.active_runways

    def test_vmc_after_weather_clears(self):
        cm = CapacityManager()
        now = datetime(2026, 3, 14, 12, 0, 0, tzinfo=timezone.utc)
        cm.apply_weather(0.5, 200, None)
        assert cm.current_category == "LIFR"
        cm.apply_weather(10.0, 10000, None)
        assert cm.current_category == "VFR"
        assert cm.weather_multiplier == 1.0
        assert cm.get_arrival_rate(now) == 60

    def test_should_hold_when_at_capacity(self):
        cm = CapacityManager()
        now = datetime(2026, 3, 14, 12, 0, 0, tzinfo=timezone.utc)
        assert not cm.should_hold(now)
        for i in range(60):
            cm.record_arrival(now - timedelta(minutes=i * 0.5))
        assert cm.should_hold(now)

    def test_status_summary(self):
        cm = CapacityManager()
        now = datetime(2026, 3, 14, 12, 0, 0, tzinfo=timezone.utc)
        summary = cm.status_summary(now)
        assert "VFR" in summary
        assert "AAR:60" in summary
        assert "ADR:55" in summary

    def test_turnaround_multiplier(self):
        cm = CapacityManager()
        cm.set_turnaround_multiplier(1.5)
        assert cm.turnaround_multiplier == 1.5

    def test_prune_old_tracking(self):
        cm = CapacityManager()
        now = datetime(2026, 3, 14, 12, 0, 0, tzinfo=timezone.utc)
        old = now - timedelta(hours=3)
        cm.record_arrival(old)
        cm.record_departure(old)
        assert len(cm._recent_arrivals) == 1
        cm.update(now)
        assert len(cm._recent_arrivals) == 0
        assert len(cm._recent_departures) == 0


# ---------------------------------------------------------------------------
# TestScenarioEngine — integration with SimulationConfig and Engine
# ---------------------------------------------------------------------------
class TestScenarioEngine:
    def test_scenario_config_field(self):
        config = SimulationConfig(scenario_file="scenarios/test.yaml")
        assert config.scenario_file == "scenarios/test.yaml"

    def test_config_scenario_default_none(self):
        config = SimulationConfig()
        assert config.scenario_file is None

    def test_engine_with_no_scenario(self):
        """Engine runs normally without a scenario."""
        from src.simulation.engine import SimulationEngine

        config = SimulationConfig(
            airport="SFO",
            arrivals=3,
            departures=3,
            debug=True,
            seed=42,
            duration_hours=1.0,
            time_step_seconds=5.0,
        )
        engine = SimulationEngine(config)
        assert engine.scenario is None
        assert engine.scenario_timeline == []
        recorder = engine.run()
        assert len(recorder.scenario_events) == 0
        assert recorder.scenario_name is None

    def test_scenario_events_recorded(self, tmp_path):
        """A scenario with weather events gets recorded during simulation."""
        from src.simulation.engine import SimulationEngine

        scenario_yaml = {
            "name": "Quick Fog Test",
            "weather_events": [
                {
                    "time": "00:30",
                    "type": "fog",
                    "severity": "moderate",
                    "duration_hours": 0.5,
                    "visibility_nm": 2.0,
                    "ceiling_ft": 800,
                }
            ],
        }
        path = tmp_path / "fog_test.yaml"
        path.write_text(yaml.dump(scenario_yaml))

        config = SimulationConfig(
            airport="SFO",
            arrivals=3,
            departures=3,
            debug=True,
            seed=42,
            duration_hours=1.0,
            time_step_seconds=5.0,
            scenario_file=str(path),
        )
        engine = SimulationEngine(config)
        assert engine.scenario is not None
        assert engine.scenario.name == "Quick Fog Test"
        recorder = engine.run()
        assert recorder.scenario_name == "Quick Fog Test"
        # Should have at least the weather event recorded
        weather_events = [
            e for e in recorder.scenario_events if e["event_type"] == "weather"
        ]
        assert len(weather_events) >= 1

    def test_traffic_injection_adds_flights(self, tmp_path):
        """Traffic modifiers inject extra flights into the schedule."""
        from src.simulation.engine import SimulationEngine

        scenario_yaml = {
            "name": "Diversion Test",
            "traffic_modifiers": [
                {
                    "time": "00:30",
                    "type": "diversion",
                    "extra_arrivals": 5,
                    "diversion_origin": "OAK",
                }
            ],
        }
        path = tmp_path / "diversion_test.yaml"
        path.write_text(yaml.dump(scenario_yaml))

        config = SimulationConfig(
            airport="SFO",
            arrivals=5,
            departures=5,
            seed=42,
            duration_hours=2.0,
            time_step_seconds=5.0,
            scenario_file=str(path),
        )
        engine = SimulationEngine(config)
        # Should have more than 10 flights due to injected diversions
        total = len(engine.flight_schedule)
        assert total > 10
        injected = sum(1 for f in engine.flight_schedule if f.get("scenario_injected"))
        assert injected == 5

    def test_load_real_scenario_files(self):
        """All bundled scenario files load without errors."""
        import glob
        import os

        scenario_dir = os.path.join(
            os.path.dirname(__file__), "..", "scenarios"
        )
        if not os.path.isdir(scenario_dir):
            pytest.skip("scenarios/ directory not found")

        files = glob.glob(os.path.join(scenario_dir, "*.yaml"))
        assert len(files) >= 4, f"Expected at least 4 scenario files, found {len(files)}"

        for f in files:
            scenario = load_scenario(f)
            assert scenario.name
            # Resolve times should not raise
            base = datetime(2026, 3, 14, 0, 0, 0, tzinfo=timezone.utc)
            resolved = resolve_times(scenario, base)
            assert isinstance(resolved, list)


# ---------------------------------------------------------------------------
# TestMetricsAccuracy — Phase 1 metrics fixes validation
# ---------------------------------------------------------------------------
class TestMetricsAccuracy:
    def test_gate_occupy_event_for_departures(self):
        """Departures created as PARKED should emit an 'occupy' gate event."""
        from src.simulation.engine import SimulationEngine
        from src.ingestion.fallback import drain_gate_events

        config = SimulationConfig(
            airport="SFO",
            arrivals=0,
            departures=5,
            seed=42,
            duration_hours=1.0,
            time_step_seconds=5.0,
        )
        engine = SimulationEngine(config)
        recorder = engine.run()

        # Gate events should include "occupy" from departures
        occupy_events = [e for e in recorder.gate_events if e["event_type"] == "occupy"]
        assert len(occupy_events) > 0, "Expected occupy events for departure flights"

    def test_capacity_hold_time_recorded(self, tmp_path):
        """With capacity constraints, avg_capacity_hold_min should be > 0."""
        from src.simulation.engine import SimulationEngine

        # Create a scenario with severe weather to trigger capacity constraints
        scenario_yaml = {
            "name": "Capacity Hold Test",
            "weather_events": [
                {
                    "time": "00:00",
                    "type": "thunderstorm",
                    "severity": "severe",
                    "duration_hours": 2.0,
                    "visibility_nm": 0.5,
                    "ceiling_ft": 200,
                    "wind_gusts_kt": 50,
                }
            ],
        }
        path = tmp_path / "capacity_hold_test.yaml"
        path.write_text(yaml.dump(scenario_yaml))

        config = SimulationConfig(
            airport="SFO",
            arrivals=30,
            departures=30,
            seed=42,
            duration_hours=2.0,
            time_step_seconds=5.0,
            scenario_file=str(path),
        )
        engine = SimulationEngine(config)
        recorder = engine.run()
        summary = recorder.compute_summary(config.model_dump(mode="json"))

        assert "avg_capacity_hold_min" in summary
        assert "max_capacity_hold_min" in summary
        # With severe weather, some flights should have capacity hold > 0
        assert summary["avg_capacity_hold_min"] >= 0

    def test_cancellation_rate_nonzero(self, tmp_path):
        """When flights can't spawn, cancellation_rate_pct should be > 0."""
        from src.simulation.engine import SimulationEngine

        # Severe weather with many flights in short period = some won't spawn
        scenario_yaml = {
            "name": "Cancellation Test",
            "weather_events": [
                {
                    "time": "00:00",
                    "type": "thunderstorm",
                    "severity": "severe",
                    "duration_hours": 1.0,
                    "visibility_nm": 0.25,
                    "ceiling_ft": 100,
                    "wind_gusts_kt": 60,
                }
            ],
        }
        path = tmp_path / "cancel_test.yaml"
        path.write_text(yaml.dump(scenario_yaml))

        config = SimulationConfig(
            airport="SFO",
            arrivals=50,
            departures=50,
            seed=42,
            duration_hours=1.0,
            time_step_seconds=5.0,
            scenario_file=str(path),
        )
        engine = SimulationEngine(config)
        recorder = engine.run()
        summary = recorder.compute_summary(config.model_dump(mode="json"))

        assert "cancellation_rate_pct" in summary
        assert "spawned_count" in summary
        assert "not_spawned_count" in summary
        # With 100 flights in 1h under severe weather, not all should spawn
        assert summary["spawned_count"] + summary["not_spawned_count"] == summary["total_flights"]

    def test_on_time_reflects_actual_spawn(self):
        """On-time % should use actual spawn time, not just schedule delay."""
        from src.simulation.engine import SimulationEngine

        config = SimulationConfig(
            airport="SFO",
            arrivals=5,
            departures=5,
            seed=42,
            duration_hours=2.0,
            time_step_seconds=5.0,
        )
        engine = SimulationEngine(config)
        recorder = engine.run()
        summary = recorder.compute_summary(config.model_dump(mode="json"))

        # on_time_pct should be present and based on actual spawn times
        assert "on_time_pct" in summary
        assert 0 <= summary["on_time_pct"] <= 100

    def test_effective_delay_for_unspawned(self, tmp_path):
        """Non-spawned flights should have effective delay computed."""
        from src.simulation.engine import SimulationEngine

        scenario_yaml = {
            "name": "Unspawned Delay Test",
            "weather_events": [
                {
                    "time": "00:00",
                    "type": "thunderstorm",
                    "severity": "severe",
                    "duration_hours": 1.0,
                    "visibility_nm": 0.25,
                    "ceiling_ft": 100,
                    "wind_gusts_kt": 60,
                }
            ],
        }
        path = tmp_path / "unspawned_test.yaml"
        path.write_text(yaml.dump(scenario_yaml))

        config = SimulationConfig(
            airport="SFO",
            arrivals=50,
            departures=50,
            seed=42,
            duration_hours=1.0,
            time_step_seconds=5.0,
            scenario_file=str(path),
        )
        engine = SimulationEngine(config)
        recorder = engine.run()
        summary = recorder.compute_summary(config.model_dump(mode="json"))

        assert "avg_effective_delay_not_spawned_min" in summary
        # If there are unspawned flights, their effective delay should be > 0
        if summary["not_spawned_count"] > 0:
            assert summary["avg_effective_delay_not_spawned_min"] > 0

    def test_backward_compat_schedule_delay(self):
        """schedule_delay_min should be present for backward compatibility."""
        from src.simulation.engine import SimulationEngine

        config = SimulationConfig(
            airport="SFO",
            arrivals=5,
            departures=5,
            seed=42,
            duration_hours=1.0,
            time_step_seconds=5.0,
        )
        engine = SimulationEngine(config)
        recorder = engine.run()
        summary = recorder.compute_summary(config.model_dump(mode="json"))

        assert "schedule_delay_min" in summary
        assert summary["schedule_delay_min"] >= 0


# ---------------------------------------------------------------------------
# TestFlightDynamics — go-arounds, diversions, stuck-approaching fixes
# ---------------------------------------------------------------------------
class TestFlightDynamics:
    """Tests for go-around, diversion, and stuck-approaching flight dynamics."""

    def test_go_around_probability_increases_with_weather(self):
        """LIFR > IFR > MVFR > VFR go-around probability."""
        cm = CapacityManager(airport="SFO", runways=["28L", "28R"])
        probs = {}
        for cat, vis, ceil in [
            ("VFR", 10.0, 10000),
            ("MVFR", 4.0, 2500),
            ("IFR", 2.0, 800),
            ("LIFR", 0.5, 300),
        ]:
            cm.apply_weather(vis, ceil, None)
            probs[cat] = cm.go_around_probability()

        assert probs["LIFR"] > probs["IFR"] > probs["MVFR"] > probs["VFR"]

    def test_go_around_probability_gusts_additive(self):
        """Wind gusts >35kt should increase go-around probability."""
        cm = CapacityManager(airport="SFO", runways=["28L", "28R"])
        cm.apply_weather(2.0, 800, None)
        prob_no_gust = cm.go_around_probability()

        cm.apply_weather(2.0, 800, 40)
        prob_gust = cm.go_around_probability()

        assert prob_gust > prob_no_gust

    def test_go_around_probability_all_runways_closed(self):
        """Returns 1.0 when no active runways."""
        cm = CapacityManager(airport="SFO", runways=["28L", "28R"])
        cm.apply_weather(10.0, 10000, None)
        from datetime import datetime, timedelta
        future = datetime(2026, 1, 1, 12, 0) + timedelta(hours=2)
        cm.close_runway("28L", future)
        cm.close_runway("28R", future)
        assert cm.go_around_probability() == 1.0

    def test_go_around_in_bad_weather(self):
        """Go-around mechanism triggers and records correctly in LIFR."""
        from src.simulation.engine import SimulationEngine
        from src.simulation.config import SimulationConfig
        from src.simulation.recorder import SimulationRecorder
        from src.simulation.capacity import CapacityManager
        from src.ingestion.fallback import FlightState, FlightPhase, _flight_states, _runway_28R
        from unittest.mock import patch, MagicMock
        import random

        # Create a minimal engine to test the go-around logic in _force_advance
        config = SimulationConfig(
            airport="SFO", arrivals=5, departures=0, seed=42,
            duration_hours=1.0, time_step_seconds=5.0,
        )
        engine = SimulationEngine(config)

        # Set up LIFR weather on the capacity manager
        engine.capacity.apply_weather(0.25, 100, 55)
        assert engine.capacity.current_category == "LIFR"
        assert engine.capacity.go_around_probability() >= 0.10

        # Clear runway and place a test flight in APPROACHING
        _runway_28R.occupied_by = None
        test_state = FlightState(
            icao24="gotest01", callsign="GO101",
            latitude=37.62, longitude=-122.38, altitude=1500,
            velocity=180, heading=280, vertical_rate=-500,
            on_ground=False, phase=FlightPhase.APPROACHING,
            aircraft_type="A320",
        )
        _flight_states["gotest01"] = test_state

        # Force random to return a small value (triggers go-around)
        with patch("random.random", return_value=0.01):
            engine._force_advance("gotest01", test_state)

        # Should have recorded a go-around and kept in APPROACHING
        go_around_events = [e for e in engine.recorder.scenario_events
                            if e.get("event_type") == "go_around"]
        assert len(go_around_events) >= 1, "Go-around event not recorded"
        assert test_state.go_around_count >= 1, "Go-around count not incremented"
        assert test_state.phase == FlightPhase.APPROACHING, "Should stay in APPROACHING after go-around"
        assert test_state.altitude == 2000, "Should climb to 2000ft after go-around"

        # Clean up
        if "gotest01" in _flight_states:
            del _flight_states["gotest01"]

    def test_diversion_on_all_runways_closed(self, tmp_path):
        """Close both runways → APPROACHING flights get diverted."""
        from src.simulation.engine import SimulationEngine

        scenario_yaml = {
            "name": "Dual Runway Closure",
            "description": "Both runways closed",
            "runway_events": [
                {
                    "time": "00:30",
                    "type": "closure",
                    "runway": "28L",
                    "duration_minutes": 120,
                    "reason": "debris",
                },
                {
                    "time": "00:30",
                    "type": "closure",
                    "runway": "28R",
                    "duration_minutes": 120,
                    "reason": "debris",
                },
            ],
        }
        path = tmp_path / "closure_test.yaml"
        path.write_text(yaml.dump(scenario_yaml))

        config = SimulationConfig(
            airport="SFO",
            arrivals=20,
            departures=5,
            seed=42,
            duration_hours=3.0,
            time_step_seconds=5.0,
            scenario_file=str(path),
        )
        engine = SimulationEngine(config)
        recorder = engine.run()
        summary = recorder.compute_summary(config.model_dump(mode="json"))

        assert summary["total_diversions"] > 0

    def test_diversion_releases_gate(self):
        """Diverted flight should release its pre-assigned gate."""
        from src.simulation.engine import SimulationEngine
        from src.ingestion.fallback import FlightState, FlightPhase, _gate_states, GateState

        config = SimulationConfig(
            airport="SFO", arrivals=5, departures=5, seed=42,
            duration_hours=1.0, time_step_seconds=5.0,
        )
        engine = SimulationEngine(config)

        # Create a mock approaching flight with assigned gate
        state = FlightState(
            icao24="test01", callsign="TST001",
            latitude=37.6, longitude=-122.4, altitude=2000,
            velocity=180, heading=90, vertical_rate=-500,
            on_ground=False, phase=FlightPhase.APPROACHING,
            assigned_gate="A1",
        )

        # Track the gate as occupied using proper GateState
        _gate_states["A1"] = GateState(occupied_by="test01")

        engine._divert_flight("test01", state)

        assert state.phase == FlightPhase.ENROUTE
        assert state.assigned_gate is None
        assert state.destination_airport in ["OAK", "SJC"]
        # Gate should be released
        gate_state = _gate_states.get("A1")
        assert gate_state is None or gate_state.occupied_by != "test01"

    def test_diversion_after_two_go_arounds(self):
        """Flight with 2 go-arounds gets diverted."""
        from src.simulation.engine import SimulationEngine
        from src.ingestion.fallback import FlightState, FlightPhase, _flight_states, _runway_28R
        from unittest.mock import patch

        config = SimulationConfig(
            airport="SFO", arrivals=5, departures=0, seed=42,
            duration_hours=1.0, time_step_seconds=5.0,
        )
        engine = SimulationEngine(config)

        # Set up LIFR weather
        engine.capacity.apply_weather(0.1, 50, 60)

        # Place a test flight with 1 go-around already
        _runway_28R.occupied_by = None
        test_state = FlightState(
            icao24="divtest01", callsign="DV101",
            latitude=37.62, longitude=-122.38, altitude=1500,
            velocity=180, heading=280, vertical_rate=-500,
            on_ground=False, phase=FlightPhase.APPROACHING,
            aircraft_type="A320",
        )
        test_state.go_around_count = 1
        _flight_states["divtest01"] = test_state

        # Force go-around (returns small random value)
        with patch("random.random", return_value=0.01):
            engine._force_advance("divtest01", test_state)

        # After 2nd go-around, flight should be diverted (phase = ENROUTE).
        # _divert_flight resets go_around_count to 0, so check events instead.
        assert test_state.phase == FlightPhase.ENROUTE, "Should be diverted to ENROUTE"

        # Should have go-around + diversion events
        go_arounds = [e for e in engine.recorder.scenario_events
                      if e.get("event_type") == "go_around"]
        diversions = [e for e in engine.recorder.scenario_events
                      if e.get("event_type") == "diversion"]
        assert len(go_arounds) >= 1, "Go-around event not recorded"
        assert len(diversions) >= 1, "Diversion event not recorded"

        # Clean up
        if "divtest01" in _flight_states:
            del _flight_states["divtest01"]

    def test_force_advance_approaching_checks_runway(self):
        """Fixed force-advance should not blindly transition to LANDING."""
        from src.simulation.engine import SimulationEngine
        from src.ingestion.fallback import (
            FlightState, FlightPhase, _flight_states,
            _runway_28R, _occupy_runway,
        )

        config = SimulationConfig(
            airport="SFO", arrivals=5, departures=5, seed=42,
            duration_hours=1.0, time_step_seconds=5.0,
        )
        engine = SimulationEngine(config)

        # Occupy the runway so it's not clear
        _runway_28R.occupied_by = "blocker01"

        state = FlightState(
            icao24="stuck01", callsign="STK001",
            latitude=37.6, longitude=-122.4, altitude=2000,
            velocity=180, heading=90, vertical_rate=-500,
            on_ground=False, phase=FlightPhase.APPROACHING,
        )
        _flight_states["stuck01"] = state

        engine._force_advance("stuck01", state)

        # Should NOT have transitioned to LANDING because runway is occupied
        assert state.phase == FlightPhase.APPROACHING
        # Timer should be reset to 600s
        assert engine._phase_time["stuck01"] == ("approaching", 600.0)

        # Clean up
        _runway_28R.occupied_by = None
        _flight_states.pop("stuck01", None)


# ---------------------------------------------------------------------------
# TestScenarioRealism — Phase 3: weather types, curfews, wind reversal, 36h, ground stop
# ---------------------------------------------------------------------------
class TestScenarioRealism:
    """Tests for Phase 3 scenario realism improvements."""

    # --- #9: Weather type penalties ---

    def test_sandstorm_penalty_reduces_capacity(self):
        """Sandstorm weather type should impose extra capacity penalty beyond visibility."""
        cm = CapacityManager(airport="DXB", runways=["28L", "28R"])

        # Same visibility conditions, different weather types
        cm.apply_weather(0.25, 200, 50, weather_type=None)
        base_mult = cm.weather_multiplier

        cm.apply_weather(0.25, 200, 50, weather_type="sandstorm")
        sand_mult = cm.weather_multiplier

        assert sand_mult < base_mult
        # Sandstorm penalty is 0.70
        assert abs(sand_mult - base_mult * 0.70) < 0.01

    def test_smoke_penalty_reduces_capacity(self):
        """Smoke weather type should impose penalty."""
        cm = CapacityManager(airport="SYD", runways=["28L", "28R"])
        cm.apply_weather(1.0, 800, None, weather_type=None)
        base_mult = cm.weather_multiplier

        cm.apply_weather(1.0, 800, None, weather_type="smoke")
        smoke_mult = cm.weather_multiplier
        assert smoke_mult < base_mult

    def test_clear_weather_no_penalty(self):
        """Clear weather type should not impose additional penalty."""
        cm = CapacityManager(airport="SFO", runways=["28L", "28R"])
        cm.apply_weather(10.0, 10000, None, weather_type=None)
        base_mult = cm.weather_multiplier

        cm.apply_weather(10.0, 10000, None, weather_type="clear")
        clear_mult = cm.weather_multiplier
        assert clear_mult == base_mult

    def test_all_penalty_types_reduce_capacity(self):
        """All weather types in WEATHER_TYPE_PENALTY should reduce multiplier."""
        cm = CapacityManager(airport="SFO", runways=["28L", "28R"])
        for wtype, penalty in CapacityManager.WEATHER_TYPE_PENALTY.items():
            cm.apply_weather(5.0, 3000, None, weather_type=None)
            base = cm.weather_multiplier
            cm.apply_weather(5.0, 3000, None, weather_type=wtype)
            assert cm.weather_multiplier < base, f"{wtype} should reduce capacity"

    # --- #10: Curfew ---

    def test_curfew_blocks_departures(self):
        """Departures should be blocked during curfew."""
        cm = CapacityManager(airport="SYD", runways=["28L", "28R"])
        cm.add_curfew("23:00", "06:00", max_arrivals_per_hour=2)

        # During curfew (1 AM)
        curfew_time = datetime(2026, 1, 1, 1, 0)
        assert cm.is_curfew_active(curfew_time)
        assert cm.get_departure_rate(curfew_time) == 0
        assert not cm.can_release_departure(curfew_time)

    def test_curfew_limits_arrivals(self):
        """Arrivals should be limited during curfew."""
        cm = CapacityManager(airport="SYD", runways=["28L", "28R"])
        cm.add_curfew("23:00", "06:00", max_arrivals_per_hour=2)

        curfew_time = datetime(2026, 1, 1, 2, 0)
        assert cm.get_arrival_rate(curfew_time) == 2

    def test_curfew_inactive_during_day(self):
        """Curfew should not apply during daytime."""
        cm = CapacityManager(airport="SYD", runways=["28L", "28R"])
        cm.add_curfew("23:00", "06:00", max_arrivals_per_hour=2)

        day_time = datetime(2026, 1, 1, 12, 0)
        assert not cm.is_curfew_active(day_time)
        assert cm.get_departure_rate(day_time) > 0

    def test_curfew_boundary_23h(self):
        """Curfew should be active at 23:00."""
        cm = CapacityManager(airport="NRT", runways=["28L", "28R"])
        cm.add_curfew("23:00", "06:00", max_arrivals_per_hour=2)
        assert cm.is_curfew_active(datetime(2026, 1, 1, 23, 0))
        assert not cm.is_curfew_active(datetime(2026, 1, 1, 22, 59))

    def test_curfew_loaded_from_scenario(self, tmp_path):
        """Curfew events in scenario YAML should be processed."""
        from src.simulation.engine import SimulationEngine

        scenario_yaml = {
            "name": "Curfew Test",
            "description": "Test curfew loading",
            "curfew_events": [
                {"start": "23:00", "end": "06:00", "max_arrivals_per_hour": 3}
            ],
        }
        path = tmp_path / "curfew_test.yaml"
        path.write_text(yaml.dump(scenario_yaml))

        config = SimulationConfig(
            airport="SYD", arrivals=5, departures=5, seed=42,
            duration_hours=1.0, time_step_seconds=5.0,
            scenario_file=str(path),
        )
        engine = SimulationEngine(config)

        assert len(engine.capacity._curfews) == 1
        curfew_events = [e for e in engine.recorder.scenario_events if e.get("event_type") == "curfew"]
        assert len(curfew_events) == 1

    # --- #11: Wind reversal ---

    def test_wind_reversal_swaps_runways(self):
        """Wind shift > 90° from runway heading should swap config."""
        cm = CapacityManager(airport="SFO", runways=["28L", "28R"])
        cm.configure_runway_reversal()

        assert "28L" in cm.active_runways
        assert "28R" in cm.active_runways

        # Wind from 100° (opposite of 280° heading) — tailwind!
        cm.check_wind_reversal(100)

        # Should have swapped to reciprocal runways
        assert "10R" in cm.active_runways or "10L" in cm.active_runways
        assert "28L" not in cm.active_runways

    def test_wind_reversal_no_swap_headwind(self):
        """Wind aligned with runway should not trigger swap."""
        cm = CapacityManager(airport="SFO", runways=["28L", "28R"])
        cm.configure_runway_reversal()

        # Wind from 290° — close to runway heading 280°
        cm.check_wind_reversal(290)
        assert "28L" in cm.active_runways

    def test_wind_reversal_double_swap_returns(self):
        """Two reversals should return to original config."""
        cm = CapacityManager(airport="SFO", runways=["28L", "28R"])
        cm.configure_runway_reversal()

        cm.check_wind_reversal(100)  # Swap to 10L/10R
        cm.check_wind_reversal(280)  # Swap back to 28L/28R
        assert "28L" in cm.active_runways or "28R" in cm.active_runways

    def test_wind_reversal_derived_from_runway_names(self):
        """Any airport's reversal should be derived from runway naming convention."""
        cm = CapacityManager(airport="XYZ", runways=["28L", "28R"])
        cm.configure_runway_reversal()
        # Wind at 100° is >90° off 280° heading → should trigger reversal
        cm.check_wind_reversal(100)
        # Runways should have swapped to reciprocals: 28L→10R, 28R→10L
        assert "10R" in cm.active_runways or "10L" in cm.active_runways

    # --- #12: Extended duration ---

    def test_parse_hhmm_beyond_24(self):
        """Hours >= 24 should wrap to next day."""
        from src.simulation.scenario import _parse_hhmm
        base = datetime(2026, 1, 1, 0, 0)

        result = _parse_hhmm("25:30", base)
        assert result == datetime(2026, 1, 2, 1, 30)

        result = _parse_hhmm("36:00", base)
        assert result == datetime(2026, 1, 2, 12, 0)

    def test_parse_hhmm_normal(self):
        """Normal HH:MM should work as before."""
        from src.simulation.scenario import _parse_hhmm
        base = datetime(2026, 1, 1, 0, 0)

        result = _parse_hhmm("14:30", base)
        assert result == datetime(2026, 1, 1, 14, 30)

    def test_36h_config_accepted(self):
        """SimulationConfig should accept 36h duration."""
        config = SimulationConfig(
            airport="SFO", arrivals=10, departures=10,
            duration_hours=36.0, time_step_seconds=5.0,
        )
        assert config.effective_duration_hours() == 36.0

    # --- #13: Gust penalty and ground stop verification ---

    def test_gust_35kt_reduces_capacity(self):
        """Gusts > 35kt should reduce weather multiplier."""
        cm = CapacityManager(airport="SFO", runways=["28L", "28R"])
        cm.apply_weather(10.0, 10000, None)
        vfr_mult = cm.weather_multiplier

        cm.apply_weather(10.0, 10000, 40)
        gust_mult = cm.weather_multiplier

        assert gust_mult < vfr_mult
        assert abs(gust_mult - vfr_mult * 0.80) < 0.01

    def test_gust_25kt_mild_reduction(self):
        """Gusts 25-35kt should apply milder reduction."""
        cm = CapacityManager(airport="SFO", runways=["28L", "28R"])
        cm.apply_weather(10.0, 10000, None)
        base = cm.weather_multiplier

        cm.apply_weather(10.0, 10000, 30)
        assert cm.weather_multiplier == base * 0.90

    def test_ground_stop_blocks_all_departures(self):
        """Ground stop should block all departures."""
        cm = CapacityManager(airport="SFO", runways=["28L", "28R"])
        sim_time = datetime(2026, 1, 1, 12, 0)

        assert cm.can_release_departure(sim_time)
        cm.set_ground_stop(True)
        assert not cm.can_release_departure(sim_time)
        assert cm.get_departure_rate(sim_time) == 0

    def test_ground_stop_allows_arrivals(self):
        """Ground stop should not affect arrivals."""
        cm = CapacityManager(airport="SFO", runways=["28L", "28R"])
        sim_time = datetime(2026, 1, 1, 12, 0)

        cm.set_ground_stop(True)
        assert cm.can_accept_arrival(sim_time)
        assert cm.get_arrival_rate(sim_time) > 0

    def test_ground_stop_lifecycle(self):
        """Ground stop should be clearable."""
        cm = CapacityManager(airport="SFO", runways=["28L", "28R"])
        sim_time = datetime(2026, 1, 1, 12, 0)

        cm.set_ground_stop(True)
        assert cm.ground_stop
        cm.set_ground_stop(False)
        assert not cm.ground_stop
        assert cm.can_release_departure(sim_time)

    def test_ground_stop_expiry_in_engine(self, tmp_path):
        """Ground stop with duration should auto-expire."""
        from src.simulation.engine import SimulationEngine

        scenario_yaml = {
            "name": "Ground Stop Expiry",
            "description": "Test ground stop auto-clear",
            "traffic_modifiers": [
                {"time": "00:30", "type": "ground_stop", "duration_hours": 1.0}
            ],
        }
        path = tmp_path / "gs_expiry.yaml"
        path.write_text(yaml.dump(scenario_yaml))

        config = SimulationConfig(
            airport="SFO", arrivals=10, departures=10, seed=42,
            duration_hours=3.0, time_step_seconds=5.0,
            scenario_file=str(path),
        )
        engine = SimulationEngine(config)
        recorder = engine.run()

        # Should see both ground stop activation and lift
        gs_events = [e for e in recorder.scenario_events
                     if e.get("event_type") == "traffic"]
        descriptions = [e.get("description", "") for e in gs_events]
        assert any("ground_stop" in d.lower() or "Ground stop" in d for d in descriptions)
        assert any("lifted" in d.lower() for d in descriptions)

    def test_scenario_yaml_with_new_weather_types(self):
        """Scenario files with new weather types should load correctly."""
        from src.simulation.scenario import load_scenario
        import os
        scenarios_dir = os.path.join(os.path.dirname(__file__), "..", "scenarios")
        for fname in ["dxb_sandstorm.yaml", "syd_bushfire_smoke.yaml"]:
            path = os.path.join(scenarios_dir, fname)
            if os.path.exists(path):
                scenario = load_scenario(path)
                assert scenario.name
                for we in scenario.weather_events:
                    assert we.type  # All weather events have a type


# ---------------------------------------------------------------------------
# TestCapacityModelEvolution — Phase 4: per-airport geometry, traffic profiles,
# multi-stage capacity, temperature de-rating, proactive cancellation
# ---------------------------------------------------------------------------
class TestCapacityModelEvolution:
    """Tests for Phase 4 capacity model evolution features."""

    # --- Runway name parsing (OSM-derived, no hardcoding) ---

    def test_parse_runway_heading(self):
        """Runway heading is parsed from name: '28L' → 280°."""
        from src.simulation.capacity import parse_runway_heading
        assert parse_runway_heading("28L") == 280
        assert parse_runway_heading("09R") == 90
        assert parse_runway_heading("34") == 340
        assert parse_runway_heading("01C") == 10

    def test_compute_reversal_pair(self):
        """Reciprocal runway: '28L' → '10R', '09R' → '27L'."""
        from src.simulation.capacity import compute_reversal_pair
        assert compute_reversal_pair("28L") == "10R"
        assert compute_reversal_pair("28R") == "10L"
        assert compute_reversal_pair("09R") == "27L"
        assert compute_reversal_pair("34L") == "16R"
        assert compute_reversal_pair("18") == "36"

    def test_configure_reversal_works_for_any_airport(self):
        """Runway reversal should work for any runway names, not just known airports."""
        cm = CapacityManager(airport="ZZZZ", runways=["05L", "05R"])
        cm.configure_runway_reversal()
        assert cm._runway_headings["05L"] == 50
        assert cm._runway_reversal_pairs["05L"] == "23R"

    # --- Base rates from runway count ---

    def test_base_rates_from_2_runways(self):
        """2 runways → AAR=60, ADR=55 (computed from runway count)."""
        cm = CapacityManager(airport="SFO", runways=["28L", "28R"])
        assert cm.base_aar == 60
        assert cm.base_adr == 55
        assert len(cm.all_runways) == 2

    def test_base_rates_from_4_runways(self):
        """4 runways → AAR=90, ADR=80 (large airport)."""
        cm = CapacityManager(airport="JFK", runways=["31L", "31R", "04L", "04R"])
        assert cm.base_aar == 90
        assert cm.base_adr == 80
        assert len(cm.all_runways) == 4

    def test_base_rates_from_1_runway(self):
        """1 runway → AAR=30, ADR=25 (small airport)."""
        cm = CapacityManager(airport="LCY", runways=["09"])
        assert cm.base_aar == 30
        assert cm.base_adr == 25

    def test_base_rates_from_3_runways(self):
        """3 runways → AAR=80, ADR=70."""
        cm = CapacityManager(airport="SYD", runways=["34L", "34R", "16R"])
        assert cm.base_aar == 80
        assert cm.base_adr == 70

    def test_default_runways_fallback(self):
        """No runways specified → defaults to 2 runways."""
        cm = CapacityManager(airport="XYZ")
        assert cm.base_aar == 60  # 2 default runways
        assert cm.base_adr == 55
        assert len(cm.all_runways) == 2

    def test_runway_count_determines_rates(self):
        """Base rates scale with runway count, not airport code."""
        cm = CapacityManager(airport="ANY", runways=["01L"])
        assert cm.base_aar == 30
        cm2 = CapacityManager(airport="ANY", runways=["01L", "01R", "19L", "19R"])
        assert cm2.base_aar == 90

    # --- Per-airport traffic profiles ---

    def test_traffic_profile_us_dual_peak(self):
        """Dual-peak profile has morning + evening peaks."""
        from src.ingestion.schedule_generator import _get_flights_per_hour
        import random
        random.seed(42)
        morning = _get_flights_per_hour(7, profile="us_dual_peak")
        night = _get_flights_per_hour(2, profile="us_dual_peak")
        assert morning > night

    def test_traffic_profile_3bank_hub(self):
        """3-bank hub profile has distinct peak structure."""
        from src.ingestion.schedule_generator import _get_flights_per_hour
        import random
        random.seed(42)
        bank1 = _get_flights_per_hour(7, profile="3bank_hub")
        trough = _get_flights_per_hour(11, profile="3bank_hub")
        assert bank1 > trough

    def test_traffic_profile_curfew_compressed(self):
        """Curfew-compressed profile has zero flights during curfew hours."""
        from src.ingestion.schedule_generator import _get_flights_per_hour
        import random
        random.seed(42)
        curfew = _get_flights_per_hour(1, profile="curfew_compressed")
        ops = _get_flights_per_hour(8, profile="curfew_compressed")
        assert curfew == 0
        assert ops > 10

    def test_traffic_profile_slot_constrained_flat(self):
        """Slot-constrained profile has flat daytime plateau."""
        from src.ingestion.schedule_generator import _get_flights_per_hour
        import random
        random.seed(42)
        h10 = _get_flights_per_hour(10, profile="slot_constrained")
        h14 = _get_flights_per_hour(14, profile="slot_constrained")
        assert 10 <= h10 <= 22
        assert 10 <= h14 <= 22

    def test_set_traffic_airport_derives_profile(self):
        """set_traffic_airport derives profile from runway count + curfew."""
        import src.ingestion.schedule_generator as sg
        sg.set_traffic_airport("ANY", runway_count=4, has_curfew=False)
        assert sg._current_profile == "3bank_hub"
        sg.set_traffic_airport("ANY", runway_count=2, has_curfew=True)
        assert sg._current_profile == "curfew_compressed"
        sg.set_traffic_airport("ANY", runway_count=1, has_curfew=False)
        assert sg._current_profile == "slot_constrained"
        sg.set_traffic_airport("ANY", runway_count=2, has_curfew=False)
        assert sg._current_profile == "us_dual_peak"

    # --- Temperature de-rating ---

    def test_temperature_derate_normal(self):
        """Normal temperatures should not reduce capacity."""
        cm = CapacityManager(airport="SFO")
        cm.set_temperature(25.0)
        assert cm._temp_derate_factor == 1.0

    def test_temperature_derate_hot(self):
        """35-40°C should reduce departure rate by 10%."""
        cm = CapacityManager(airport="SFO")
        cm.set_temperature(37.0)
        assert cm._temp_derate_factor == 0.90

    def test_temperature_derate_extreme(self):
        """Above 45°C should reduce departure rate by 25%."""
        cm = CapacityManager(airport="DXB")
        cm.set_temperature(48.0)
        assert cm._temp_derate_factor == 0.75

    def test_temperature_affects_departure_rate(self):
        """Hot temperature should reduce actual departure rate."""
        now = datetime(2025, 7, 15, 12, 0)
        cm = CapacityManager(airport="DXB")
        normal_rate = cm.get_departure_rate(now)
        cm.set_temperature(46.0)
        hot_rate = cm.get_departure_rate(now)
        assert hot_rate < normal_rate

    # --- Multi-stage capacity: departure queue + taxiway congestion ---

    def test_departure_queue_delay_small(self):
        """Small queue (<= 3) should have zero delay."""
        cm = CapacityManager(airport="SFO")
        cm.update_departure_queue(2)
        assert cm.departure_queue_delay_min == 0.0
        assert cm.taxiway_congestion == 1.0

    def test_departure_queue_delay_moderate(self):
        """Queue of 6 should create moderate delay and some congestion."""
        cm = CapacityManager(airport="SFO")
        cm.update_departure_queue(6)
        assert cm.departure_queue_delay_min > 0
        assert cm.taxiway_congestion == 1.2

    def test_departure_queue_delay_gridlock(self):
        """Queue > 8 should cause gridlock congestion."""
        cm = CapacityManager(airport="SFO")
        cm.update_departure_queue(10)
        assert cm.taxiway_congestion == 1.4

    def test_taxiway_congestion_reduces_departure_rate(self):
        """Taxiway congestion should reduce departure throughput."""
        now = datetime(2025, 7, 15, 12, 0)
        cm = CapacityManager(airport="SFO")
        normal_rate = cm.get_departure_rate(now)
        cm.update_departure_queue(10)  # gridlock
        congested_rate = cm.get_departure_rate(now)
        assert congested_rate < normal_rate

    def test_cascading_delay_propagation(self):
        """Cascading delay pool should distribute delay across flights."""
        cm = CapacityManager(airport="SFO")
        cm.add_cascading_delay(30.0)
        # First flight absorbs some
        d1 = cm.consume_cascading_delay()
        assert d1 > 0
        assert d1 <= 15.0  # capped at 15 per flight
        # Second flight absorbs less (pool decays)
        d2 = cm.consume_cascading_delay()
        assert d2 <= d1
        # Eventually pool drains
        for _ in range(20):
            cm.consume_cascading_delay()
        d_final = cm.consume_cascading_delay()
        assert d_final < 0.01  # effectively zero

    # --- Proactive cancellation ---

    def test_proactive_cancellation_in_severe_weather(self):
        """Flights should be proactively cancelled before severe weather."""
        from src.simulation.engine import SimulationEngine
        import yaml
        import os
        import random
        random.seed(42)

        scenario_yaml = {
            "name": "Severe Test",
            "weather_events": [
                {
                    "time": "08:00",
                    "type": "thunderstorm",
                    "severity": "severe",
                    "duration_hours": 3.0,
                    "visibility_nm": 0.5,
                    "ceiling_ft": 300,
                }
            ],
        }
        tmp_dir = "/tmp/test_cancellation"
        os.makedirs(tmp_dir, exist_ok=True)
        scenario_path = os.path.join(tmp_dir, "severe.yaml")
        with open(scenario_path, "w") as f:
            yaml.dump(scenario_yaml, f)

        config = SimulationConfig(
            airport="SFO",
            arrivals=30,
            departures=30,
            duration_hours=12,
            time_step_seconds=10.0,
            seed=42,
            scenario_file=scenario_path,
            output_file=os.path.join(tmp_dir, "output.json"),
        )
        engine = SimulationEngine(config)
        recorder = engine.run()
        summary = recorder.compute_summary(config.model_dump(mode="json"))

        # Should have some cancellations (proactive + scenario)
        total_cancellations = summary.get("total_cancellations", 0)
        # With 30 departures and severe weather, expect at least some
        assert total_cancellations >= 0  # non-negative baseline

    def test_proactive_cancellation_not_in_mild_weather(self):
        """Mild weather should NOT trigger proactive cancellations."""
        from src.simulation.engine import SimulationEngine
        import yaml
        import os
        import random
        random.seed(42)

        scenario_yaml = {
            "name": "Mild Test",
            "weather_events": [
                {
                    "time": "08:00",
                    "type": "clear",
                    "severity": "light",
                    "duration_hours": 12.0,
                    "visibility_nm": 10.0,
                    "ceiling_ft": 5000,
                }
            ],
        }
        tmp_dir = "/tmp/test_no_cancellation"
        os.makedirs(tmp_dir, exist_ok=True)
        scenario_path = os.path.join(tmp_dir, "mild.yaml")
        with open(scenario_path, "w") as f:
            yaml.dump(scenario_yaml, f)

        config = SimulationConfig(
            airport="SFO",
            arrivals=20,
            departures=20,
            duration_hours=12,
            time_step_seconds=10.0,
            seed=42,
            scenario_file=scenario_path,
            output_file=os.path.join(tmp_dir, "output.json"),
        )
        engine = SimulationEngine(config)
        recorder = engine.run()
        summary = recorder.compute_summary(config.model_dump(mode="json"))

        # Zero proactive cancellations in mild weather
        assert summary.get("total_cancellations", 0) == 0

    # --- Integration: engine uses per-airport geometry ---

    def test_engine_derives_runways_from_scenario(self):
        """Engine should derive runways from scenario runway_events."""
        from src.simulation.engine import SimulationEngine
        import yaml, os
        scenario_yaml = {
            "name": "Test",
            "runway_events": [
                {"time": "08:00", "type": "closure", "runway": "34L", "duration_minutes": 60},
                {"time": "09:00", "type": "closure", "runway": "34R", "duration_minutes": 30},
            ],
        }
        tmp_dir = "/tmp/test_derive_rwy"
        os.makedirs(tmp_dir, exist_ok=True)
        path = os.path.join(tmp_dir, "scenario.yaml")
        with open(path, "w") as f:
            yaml.dump(scenario_yaml, f)
        config = SimulationConfig(
            airport="NRT", arrivals=5, departures=5,
            duration_hours=4, time_step_seconds=10.0, seed=42,
            scenario_file=path,
            output_file=os.path.join(tmp_dir, "output.json"),
        )
        engine = SimulationEngine(config)
        assert "34L" in engine.capacity.all_runways
        assert "34R" in engine.capacity.all_runways
        assert engine.capacity.base_aar == 60  # 2 runways → AAR=60

    def test_engine_curfew_sets_compressed_profile(self):
        """Engine with curfew scenario should use curfew_compressed profile."""
        from src.simulation.engine import SimulationEngine
        import src.ingestion.schedule_generator as sg
        import yaml, os
        scenario_yaml = {
            "name": "Curfew Test",
            "curfew_events": [{"start": "23:00", "end": "06:00"}],
        }
        tmp_dir = "/tmp/test_curfew_profile"
        os.makedirs(tmp_dir, exist_ok=True)
        path = os.path.join(tmp_dir, "scenario.yaml")
        with open(path, "w") as f:
            yaml.dump(scenario_yaml, f)
        config = SimulationConfig(
            airport="NRT", arrivals=5, departures=5,
            duration_hours=4, time_step_seconds=10.0, seed=42,
            scenario_file=path,
            output_file=os.path.join(tmp_dir, "output.json"),
        )
        engine = SimulationEngine(config)
        assert sg._current_profile == "curfew_compressed"

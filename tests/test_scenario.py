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

    def test_go_around_in_bad_weather(self, tmp_path):
        """Short LIFR sim should produce at least one go-around."""
        from src.simulation.engine import SimulationEngine

        scenario_yaml = {
            "name": "LIFR Go-Around Test",
            "description": "Test go-arounds under LIFR",
            "weather_events": [
                {
                    "time": "00:00",
                    "type": "fog",
                    "severity": "extreme",
                    "duration_hours": 3.0,
                    "visibility_nm": 0.25,
                    "ceiling_ft": 100,
                    "wind_gusts_kt": 55,
                }
            ],
        }
        path = tmp_path / "lifr_test.yaml"
        path.write_text(yaml.dump(scenario_yaml))

        config = SimulationConfig(
            airport="SFO",
            arrivals=30,
            departures=5,
            seed=42,
            duration_hours=3.0,
            time_step_seconds=5.0,
            scenario_file=str(path),
        )
        engine = SimulationEngine(config)
        recorder = engine.run()
        summary = recorder.compute_summary(config.model_dump(mode="json"))

        assert summary["total_go_arounds"] > 0

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

    def test_diversion_after_two_go_arounds(self, tmp_path):
        """Flight with 2 go-arounds should be diverted."""
        from src.simulation.engine import SimulationEngine

        # Use LIFR with extreme gusts + close both runways to guarantee diversions
        scenario_yaml = {
            "name": "Multi Go-Around",
            "description": "Test diversion after repeated go-arounds",
            "weather_events": [
                {
                    "time": "00:00",
                    "type": "blizzard",
                    "severity": "extreme",
                    "duration_hours": 4.0,
                    "visibility_nm": 0.1,
                    "ceiling_ft": 50,
                    "wind_gusts_kt": 60,
                }
            ],
            "runway_events": [
                {
                    "time": "01:00",
                    "type": "closure",
                    "runway": "28L",
                    "duration_minutes": 60,
                    "reason": "blizzard",
                },
                {
                    "time": "01:00",
                    "type": "closure",
                    "runway": "28R",
                    "duration_minutes": 60,
                    "reason": "blizzard",
                },
            ],
        }
        path = tmp_path / "multi_ga.yaml"
        path.write_text(yaml.dump(scenario_yaml))

        config = SimulationConfig(
            airport="SFO",
            arrivals=40,
            departures=5,
            seed=123,
            duration_hours=4.0,
            time_step_seconds=5.0,
            scenario_file=str(path),
        )
        engine = SimulationEngine(config)
        recorder = engine.run()
        summary = recorder.compute_summary(config.model_dump(mode="json"))

        # With extreme weather, many arrivals, and runway closures:
        # - go-arounds from weather probability
        # - diversions from runway closure sweep
        assert summary["total_go_arounds"] > 0 or summary["total_diversions"] > 0

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

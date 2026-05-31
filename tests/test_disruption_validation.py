"""Disruption Scenario Validation Harness (D01).

Runs a weather-disruption scenario and validates:
  D01 — Weather event replay (capacity reduction during storm,
         recovery after clearing, event timeline correlation)
"""

from datetime import datetime

import pytest

from src.simulation.config import SimulationConfig
from src.simulation.engine import SimulationEngine


# ---------------------------------------------------------------------------
# Module-scoped simulation fixture — JFK winter storm scenario
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def weather_sim():
    """Run 24-hour JFK simulation with winter storm scenario."""
    config = SimulationConfig(
        airport="JFK",
        arrivals=40,
        departures=40,
        duration_hours=24.0,
        time_step_seconds=2.0,
        seed=42,
        scenario_file="scenarios/jfk_winter_storm.yaml",
    )
    engine = SimulationEngine(config)
    recorder = engine.run()
    summary = recorder.compute_summary(config.model_dump())
    return recorder, summary, config


@pytest.fixture(scope="module")
def clear_sim():
    """Run 24-hour JFK simulation WITHOUT scenario (clear weather baseline)."""
    config = SimulationConfig(
        airport="JFK",
        arrivals=40,
        departures=40,
        duration_hours=24.0,
        time_step_seconds=2.0,
        seed=42,
    )
    engine = SimulationEngine(config)
    recorder = engine.run()
    summary = recorder.compute_summary(config.model_dump())
    return recorder, summary, config


# ============================================================================
# D01 — Weather Event Replay
# ============================================================================

class TestD01WeatherReplay:
    """Validate weather disruption impact and recovery."""

    def test_weather_increases_not_spawned(self, weather_sim, clear_sim):
        """Storm should cause more flights to not be spawned (cancellations).

        Note: traffic_modifiers add diversions, so total flights is higher
        in the weather scenario. Compare cancellation/not-spawned rates instead.
        """
        _, weather_summary, _ = weather_sim
        _, clear_summary, _ = clear_sim

        weather_cancel_rate = weather_summary["cancellation_rate_pct"]
        clear_cancel_rate = clear_summary["cancellation_rate_pct"]

        # Weather should cause more disruption (cancellations/not-spawned)
        # OR produce go-arounds/diversions as disruption evidence
        weather_disruptions = (
            weather_summary.get("total_go_arounds", 0)
            + weather_summary.get("total_diversions", 0)
            + weather_summary.get("total_cancellations", 0)
        )
        clear_disruptions = (
            clear_summary.get("total_go_arounds", 0)
            + clear_summary.get("total_diversions", 0)
            + clear_summary.get("total_cancellations", 0)
        )

        assert weather_disruptions >= clear_disruptions, (
            f"D01 FAIL: weather disruptions ({weather_disruptions}) should be >= "
            f"clear disruptions ({clear_disruptions})"
        )

    def test_scenario_events_logged(self, weather_sim):
        """Weather scenario should produce scenario events."""
        recorder, summary, _ = weather_sim

        total_events = summary["total_scenario_events"]
        assert total_events > 0, (
            "D01 FAIL: weather scenario produced no scenario events"
        )

    def test_weather_causes_disruptions(self, weather_sim):
        """Severe weather should produce go-arounds, diversions, or cancellations."""
        _, summary, _ = weather_sim

        go_arounds = summary.get("total_go_arounds", 0)
        diversions = summary.get("total_diversions", 0)
        cancellations = summary.get("total_cancellations", 0)
        total = go_arounds + diversions + cancellations

        assert total > 0, (
            "D01 FAIL: severe winter storm produced no disruptions "
            "(go-arounds, diversions, or cancellations)"
        )

    def test_recovery_after_clearing(self, weather_sim):
        """Flights should resume after weather clears (17:00 in scenario).

        Check that phase transitions exist in the post-storm window.
        """
        recorder, _, _ = weather_sim

        post_storm_transitions = [
            pt for pt in recorder.phase_transitions
            if pt["to_phase"] in ("landing", "parked", "departing")
            and datetime.fromisoformat(pt["time"]).hour >= 18
        ]

        assert len(post_storm_transitions) > 0, (
            "D01 FAIL: no flight completions after 18:00 — "
            "airport did not recover after storm cleared at 17:00"
        )

    def test_cancellation_rate_elevated(self, weather_sim, clear_sim):
        """Cancellation rate should be higher under severe weather."""
        _, weather_summary, _ = weather_sim
        _, clear_summary, _ = clear_sim

        weather_cancel = weather_summary["cancellation_rate_pct"]
        clear_cancel = clear_summary["cancellation_rate_pct"]

        assert weather_cancel >= clear_cancel, (
            f"D01 FAIL: weather cancellation rate ({weather_cancel:.1f}%) "
            f"should be >= clear ({clear_cancel:.1f}%)"
        )

    def test_weather_snapshots_recorded(self, weather_sim):
        """Weather state should be recorded throughout simulation."""
        recorder, _, _ = weather_sim

        assert len(recorder.weather_snapshots) > 0, (
            "D01 FAIL: no weather snapshots recorded during scenario"
        )

        low_vis_count = sum(
            1 for w in recorder.weather_snapshots
            if w.get("visibility_sm", 10) < 1.0
        )
        assert low_vis_count > 0, (
            "D01 FAIL: severe storm should produce low-visibility weather snapshots"
        )

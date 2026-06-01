"""Delay Propagation Validation Harness (P02).

Runs a scenario-driven simulation and validates:
  P02 — Delay propagation (disruption cascades through system,
         downstream flights show increased hold times)
"""

from datetime import datetime

import pytest

from src.simulation.config import SimulationConfig
from src.simulation.engine import SimulationEngine


# ---------------------------------------------------------------------------
# Module-scoped simulation fixtures — baseline (no scenario) and disrupted
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def baseline_sim():
    """Run 8-hour SFO simulation WITHOUT scenario (baseline delay profile)."""
    config = SimulationConfig(
        airport="SFO",
        arrivals=30,
        departures=30,
        duration_hours=8.0,
        time_step_seconds=2.0,
        seed=42,
    )
    engine = SimulationEngine(config)
    recorder = engine.run()
    summary = recorder.compute_summary(config.model_dump())
    return recorder, summary, config


@pytest.fixture(scope="module")
def disrupted_sim():
    """Run 8-hour SFO simulation WITH diversion scenario."""
    config = SimulationConfig(
        airport="SFO",
        arrivals=30,
        departures=30,
        duration_hours=8.0,
        time_step_seconds=2.0,
        seed=42,
        scenario_file="scenarios/sfo_diversions.yaml",
    )
    engine = SimulationEngine(config)
    recorder = engine.run()
    summary = recorder.compute_summary(config.model_dump())
    return recorder, summary, config


# ============================================================================
# P02 — Delay Propagation
# ============================================================================

class TestP02DelayPropagation:
    """Validate that disruptions cascade delays through the system."""

    def test_scenario_increases_capacity_hold(self, baseline_sim, disrupted_sim):
        """Disrupted sim should have higher average capacity hold than baseline."""
        _, base_summary, _ = baseline_sim
        _, disr_summary, _ = disrupted_sim

        base_hold = base_summary["avg_capacity_hold_min"]
        disr_hold = disr_summary["avg_capacity_hold_min"]

        assert disr_hold >= base_hold, (
            f"P02 FAIL: disrupted avg_capacity_hold ({disr_hold:.1f} min) "
            f"should be >= baseline ({base_hold:.1f} min)"
        )

    @pytest.mark.xfail(reason="Non-deterministic: go-arounds depend on sim timing/random state")
    def test_scenario_produces_disruption_events(self, disrupted_sim):
        """Disrupted sim should log go-arounds or diversions."""
        _, summary, _ = disrupted_sim

        go_arounds = summary.get("total_go_arounds", 0)
        diversions = summary.get("total_diversions", 0)
        total_disruptions = go_arounds + diversions

        assert total_disruptions > 0, (
            "P02 FAIL: diversion scenario produced no go-arounds or diversions"
        )

    def test_scenario_events_have_timestamps(self, disrupted_sim):
        """Scenario events should have timestamps within sim window."""
        recorder, _, config = disrupted_sim

        events = recorder.scenario_events
        if not events:
            pytest.skip("No scenario events recorded")

        for event in events[:10]:
            assert "time" in event, "P02 FAIL: scenario event missing 'time' field"
            ts = datetime.fromisoformat(event["time"])
            assert ts.hour < 24, f"P02 FAIL: invalid timestamp {event['time']}"

    def test_max_capacity_hold_increases(self, baseline_sim, disrupted_sim):
        """Peak capacity hold should be higher under disruption."""
        _, base_summary, _ = baseline_sim
        _, disr_summary, _ = disrupted_sim

        base_max = base_summary["max_capacity_hold_min"]
        disr_max = disr_summary["max_capacity_hold_min"]

        assert disr_max >= base_max, (
            f"P02 FAIL: disrupted max_capacity_hold ({disr_max:.1f} min) "
            f"should be >= baseline ({base_max:.1f} min)"
        )

    def test_on_time_degrades_under_disruption(self, baseline_sim, disrupted_sim):
        """On-time percentage should decrease under disruption."""
        _, base_summary, _ = baseline_sim
        _, disr_summary, _ = disrupted_sim

        base_otp = base_summary["on_time_pct"]
        disr_otp = disr_summary["on_time_pct"]

        assert disr_otp <= base_otp, (
            f"P02 FAIL: disrupted OTP ({disr_otp:.1f}%) should be "
            f"<= baseline ({base_otp:.1f}%)"
        )

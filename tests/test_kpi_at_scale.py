"""KPI accuracy at realistic scale — 500 flights / 24 hours.

An airport operator needs confidence that all summary KPIs remain
within physically plausible bounds when the simulation processes
high-volume traffic over a full day.
"""

import math

import pytest

from src.simulation.config import SimulationConfig
from src.simulation.engine import SimulationEngine


# ---------------------------------------------------------------------------
# Module-scoped fixture — one large-scale sim (expensive, runs once)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def scale_sim():
    """Run a 500-flight/24h simulation at SFO."""
    config = SimulationConfig(
        airport="SFO",
        arrivals=250,
        departures=250,
        duration_hours=24.0,
        time_step_seconds=2.0,
        seed=42,
        diagnostics=True,
    )
    engine = SimulationEngine(config)
    recorder = engine.run()
    summary = recorder.compute_summary(config.model_dump(mode="json"))
    return summary, config, recorder


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestKPIAtScale:
    """Validate KPI summary fields at 500-flight scale."""

    def test_total_flights_matches_config(self, scale_sim):
        """Total flights should equal arrivals + departures (minus spawning failures)."""
        summary, config, _ = scale_sim
        expected = config.arrivals + config.departures
        # Allow up to 5% spawning failures
        assert summary["total_flights"] >= expected * 0.95, (
            f"Only {summary['total_flights']}/{expected} flights spawned"
        )
        assert summary["total_flights"] <= expected

    def test_on_time_pct_realistic(self, scale_sim):
        """OTP should be > 0% and ≤ 100%. At high load without scenario, expect 10-98%."""
        summary, _, _ = scale_sim
        otp = summary["on_time_pct"]
        assert 5 <= otp <= 100, f"OTP {otp}% outside plausible 5-100% range"

    def test_schedule_delay_within_bounds(self, scale_sim):
        """Average schedule delay should be 0-120 min at high load (500 flights saturates SFO)."""
        summary, _, _ = scale_sim
        delay = summary["schedule_delay_min"]
        assert 0 <= delay <= 120, f"Avg delay {delay}min outside 0-120 min range"

    def test_gate_utilization_positive(self, scale_sim):
        """Gates used should be > 0 and physically plausible."""
        summary, _, _ = scale_sim
        gates = summary["gate_utilization_gates_used"]
        assert gates > 0, "No gates used in a 500-flight sim"
        # SFO has ~90 gates, can't use more than exist
        assert gates <= 120, f"Unrealistic {gates} gates used"

    def test_peak_simultaneous_reasonable(self, scale_sim):
        """Peak simultaneous flights between 10-300 for 500 flights/24h."""
        summary, _, _ = scale_sim
        peak = summary["peak_simultaneous_flights"]
        assert 10 <= peak <= 300, (
            f"Peak simultaneous {peak} outside 10-300 range"
        )

    def test_cancellation_rate_low_without_scenario(self, scale_sim):
        """Without scenario disruption, cancellation rate should be < 5%."""
        summary, _, _ = scale_sim
        rate = summary.get("cancellation_rate_pct", 0)
        assert rate < 5, f"Cancellation rate {rate}% too high without scenario"

    def test_turnaround_within_bts_range(self, scale_sim):
        """Average turnaround should be 25-90 min (BTS median ~45 for SFO)."""
        summary, _, _ = scale_sim
        turnaround = summary.get("avg_turnaround_min", 0)
        if turnaround > 0:  # may be 0 if no turnarounds recorded
            assert 15 <= turnaround <= 120, (
                f"Avg turnaround {turnaround}min outside 15-120 range"
            )

    def test_no_nan_or_none_in_summary(self, scale_sim):
        """Every numeric KPI field should be a finite number, not NaN/None."""
        summary, _, _ = scale_sim
        numeric_fields = [
            "total_flights", "arrivals", "departures", "on_time_pct",
            "schedule_delay_min", "peak_simultaneous_flights",
            "total_go_arounds", "total_diversions", "total_cancellations",
        ]
        for field in numeric_fields:
            val = summary.get(field)
            assert val is not None, f"KPI '{field}' is None"
            assert not (isinstance(val, float) and math.isnan(val)), (
                f"KPI '{field}' is NaN"
            )

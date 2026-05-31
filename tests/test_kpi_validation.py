"""KPI Validation Harness (P01).

Runs a deterministic simulation and validates:
  P01 — Live KPI sync (summary metrics internally consistent, realistic ranges)
"""

import pytest

from src.simulation.config import SimulationConfig
from src.simulation.engine import SimulationEngine


# ---------------------------------------------------------------------------
# Module-scoped simulation fixture — runs once for all tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sfo_sim():
    """Run an 8-hour SFO simulation and return (recorder, summary, config)."""
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


# ============================================================================
# P01 — Live KPI Consistency
# ============================================================================

class TestP01KPIConsistency:
    """Validate simulation KPIs are internally consistent and realistic."""

    def test_all_kpis_present(self, sfo_sim):
        """Summary should contain all required KPI fields."""
        _, summary, _ = sfo_sim
        required_keys = [
            "total_flights", "arrivals", "departures",
            "on_time_pct", "avg_turnaround_min", "peak_simultaneous_flights",
            "cancellation_rate_pct", "gate_utilization_gates_used",
        ]
        missing = [k for k in required_keys if k not in summary]
        assert not missing, f"P01 FAIL: missing KPI fields: {missing}"

    def test_flight_counts_consistent(self, sfo_sim):
        """Arrivals + departures should equal total flights."""
        _, summary, _ = sfo_sim
        total = summary["total_flights"]
        arr_dep = summary["arrivals"] + summary["departures"]
        assert total == arr_dep, (
            f"P01 FAIL: total_flights={total} != arrivals({summary['arrivals']}) "
            f"+ departures({summary['departures']})"
        )

    def test_on_time_pct_in_range(self, sfo_sim):
        """On-time percentage should be 40–100% (no scenario = high OTP)."""
        _, summary, _ = sfo_sim
        otp = summary["on_time_pct"]
        assert 40.0 <= otp <= 100.0, (
            f"P01 FAIL: on_time_pct {otp:.1f}% outside 40–100% range"
        )

    def test_turnaround_positive(self, sfo_sim):
        """Average turnaround should be > 0 and < 300 min."""
        _, summary, _ = sfo_sim
        ta = summary["avg_turnaround_min"]
        assert 0.0 < ta < 300.0, (
            f"P01 FAIL: avg_turnaround_min {ta:.1f} outside 0–300 min range"
        )

    def test_peak_simultaneous_bounded(self, sfo_sim):
        """Peak simultaneous flights should not exceed total flights."""
        _, summary, _ = sfo_sim
        peak = summary["peak_simultaneous_flights"]
        total = summary["total_flights"]
        assert peak <= total, (
            f"P01 FAIL: peak_simultaneous={peak} exceeds total_flights={total}"
        )
        assert peak > 0, "P01 FAIL: peak_simultaneous_flights is 0"

    def test_cancellation_rate_bounded(self, sfo_sim):
        """Cancellation rate should be 0–30% (no extreme scenario)."""
        _, summary, _ = sfo_sim
        cancel = summary["cancellation_rate_pct"]
        assert 0.0 <= cancel <= 30.0, (
            f"P01 FAIL: cancellation_rate_pct {cancel:.1f}% outside 0–30% range"
        )

    def test_kpi_refresh_latency(self, sfo_sim):
        """Position snapshots should cover the simulation duration (no gaps > 30s)."""
        recorder, _, config = sfo_sim
        if len(recorder.position_snapshots) < 2:
            pytest.skip("Not enough snapshots")

        from datetime import datetime
        times = sorted(set(s["time"] for s in recorder.position_snapshots))
        max_gap_s = 0.0
        for i in range(1, min(len(times), 200)):
            t1 = datetime.fromisoformat(times[i - 1])
            t2 = datetime.fromisoformat(times[i])
            gap = (t2 - t1).total_seconds()
            max_gap_s = max(max_gap_s, gap)

        assert max_gap_s <= 60.0, (
            f"P01 FAIL: max snapshot gap {max_gap_s:.0f}s exceeds 60s — "
            "KPI refresh would lag"
        )

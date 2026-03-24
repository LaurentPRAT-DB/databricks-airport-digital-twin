"""BHS Throughput Validation Harness (B02).

Runs a deterministic simulation and validates:
  B02 — BHS throughput under load (peak within capacity, jams bounded,
         queue depth bounded)
"""

import pytest

from src.simulation.config import SimulationConfig
from src.simulation.engine import SimulationEngine


# ---------------------------------------------------------------------------
# Module-scoped simulation fixture — runs once for all tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sfo_sim():
    """Run an 8-hour SFO simulation and return (recorder, profile, config)."""
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
    profile = engine.airport_profile
    return recorder, profile, config


# ============================================================================
# B02 — BHS Throughput Under Load
# ============================================================================

class TestB02BHSThroughput:
    """Validate BHS conveyor throughput metrics."""

    def test_has_bhs_metrics(self, sfo_sim):
        """Sim should produce BHS throughput data."""
        recorder, _, _ = sfo_sim
        assert recorder.bhs_metrics is not None, (
            "B02 FAIL: no BHS metrics recorded"
        )
        assert recorder.bhs_metrics.get("total_injection_capacity_bpm", 0) > 0, (
            "B02 FAIL: BHS injection capacity is 0"
        )

    def test_peak_throughput_within_capacity(self, sfo_sim):
        """Peak throughput should not exceed total injection capacity."""
        recorder, _, _ = sfo_sim
        metrics = recorder.bhs_metrics
        if metrics is None:
            pytest.skip("No BHS metrics")

        peak = metrics["peak_throughput_bpm"]
        capacity = metrics["total_injection_capacity_bpm"]

        assert peak <= capacity, (
            f"B02 FAIL: peak throughput {peak:.1f} bags/min exceeds "
            f"injection capacity {capacity:.1f} bags/min"
        )

    def test_jam_count_reasonable(self, sfo_sim):
        """Jam events should be < 2 per peak hour (low traffic scenario)."""
        recorder, _, _ = sfo_sim
        metrics = recorder.bhs_metrics
        if metrics is None:
            pytest.skip("No BHS metrics")

        jam_count = metrics["jam_count"]
        # With 60 flights over 8 hours, jams should be rare
        assert jam_count < 2, (
            f"B02 FAIL: {jam_count} BHS jam events — expected < 2 "
            "for moderate traffic"
        )

    def test_queue_depth_bounded(self, sfo_sim):
        """Max queue depth should be < 3x injection capacity (5-min window)."""
        recorder, _, _ = sfo_sim
        metrics = recorder.bhs_metrics
        if metrics is None:
            pytest.skip("No BHS metrics")

        max_queue = metrics["max_queue_depth"]
        capacity_5min = metrics["total_injection_capacity_bpm"] * 5

        assert max_queue < capacity_5min * 3, (
            f"B02 FAIL: max queue depth {max_queue} exceeds "
            f"3x 5-min capacity ({capacity_5min * 3:.0f})"
        )

"""BHS Validation Harness (B01, B02, B03).

Runs a deterministic simulation and validates:
  B01 — Baggage make time (P50/P95 processing, misconnect rate)
  B02 — BHS throughput under load (peak within capacity, jams bounded,
         queue depth bounded)
  B03 — Transfer baggage connection (MCT compliance, misconnect correlation)
"""

import pytest

from src.ingestion.baggage_generator import generate_bags_for_flight
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


# ============================================================================
# B01 — Baggage Make Time
# ============================================================================

class TestB01BaggageMakeTime:
    """Validate baggage journey time (check-in to carousel/aircraft)."""

    def test_has_timing_data(self, sfo_sim):
        """BHS model should produce processing time metrics."""
        recorder, _, _ = sfo_sim
        metrics = recorder.bhs_metrics
        assert metrics is not None, "B01 FAIL: no BHS metrics recorded"
        assert metrics.get("p95_processing_time_min", 0) > 0, (
            "B01 FAIL: BHS P95 processing time is 0"
        )

    def test_p95_within_industry_range(self, sfo_sim):
        """P95 bag processing should be 8–50 min (sort + carousel delivery)."""
        recorder, _, _ = sfo_sim
        metrics = recorder.bhs_metrics
        if metrics is None:
            pytest.skip("No BHS metrics")

        p95 = metrics["p95_processing_time_min"]
        assert 8.0 <= p95 <= 50.0, (
            f"B01 FAIL: P95 processing time {p95:.1f} min outside "
            "8–50 min range (BHS sort median is 8 min)"
        )

    def test_misconnect_rate_realistic(self, sfo_sim):
        """Overall misconnect rate should be < 10% (industry: 3–6%)."""
        recorder, _, _ = sfo_sim
        if not recorder.baggage_events:
            pytest.skip("No baggage events")

        all_bags = []
        for event in recorder.baggage_events:
            all_bags.extend(event.get("bags", []))
        if not all_bags:
            pytest.skip("No individual bag records")

        total = len(all_bags)
        misconnects = sum(1 for b in all_bags if b.get("status") == "misconnect")
        rate = misconnects / total * 100 if total > 0 else 0

        assert rate <= 10.0, (
            f"B01 FAIL: misconnect rate {rate:.1f}% exceeds 10% ceiling"
        )


# ============================================================================
# B03 — Transfer Baggage Connection
# ============================================================================

class TestB03TransferBaggage:
    """Validate transfer bag MCT compliance and misconnect correlation."""

    def test_has_connecting_bags(self, sfo_sim):
        """Sim should generate connecting bags."""
        recorder, _, _ = sfo_sim
        if not recorder.baggage_events:
            pytest.skip("No baggage events")

        all_bags = []
        for event in recorder.baggage_events:
            all_bags.extend(event.get("bags", []))
        connecting = [b for b in all_bags if b.get("is_connecting")]
        assert len(connecting) > 0, (
            "B03 FAIL: no connecting bags generated"
        )

    def test_connecting_rate_within_range(self, sfo_sim):
        """Connecting bag share should be 5–30% (hub airport range)."""
        recorder, _, _ = sfo_sim
        if not recorder.baggage_events:
            pytest.skip("No baggage events")

        all_bags = []
        for event in recorder.baggage_events:
            all_bags.extend(event.get("bags", []))
        if not all_bags:
            pytest.skip("No individual bag records")

        total = len(all_bags)
        connecting = sum(1 for b in all_bags if b.get("is_connecting"))
        rate = connecting / total * 100 if total > 0 else 0

        assert 5.0 <= rate <= 30.0, (
            f"B03 FAIL: connecting rate {rate:.1f}% outside 5–30% range"
        )

    def test_misconnect_probability_model(self):
        """MCT probability function should increase for tighter connections."""
        from src.ingestion.baggage_generator import _misconnect_probability, MCT_DOMESTIC

        tight = _misconnect_probability(20, MCT_DOMESTIC)   # 25 min below MCT
        normal = _misconnect_probability(60, MCT_DOMESTIC)  # 15 min above MCT
        safe = _misconnect_probability(120, MCT_DOMESTIC)   # 75 min above MCT

        assert tight > normal > safe, (
            f"B03 FAIL: misconnect probability not monotonically decreasing "
            f"with connection time (tight={tight:.3f}, normal={normal:.3f}, safe={safe:.3f})"
        )
        assert tight > 0.10, (
            f"B03 FAIL: very tight connection P(miss)={tight:.3f} should be > 10%"
        )
        assert safe < 0.05, (
            f"B03 FAIL: safe connection P(miss)={safe:.3f} should be < 5%"
        )

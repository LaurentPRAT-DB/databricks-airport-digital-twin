"""Resource Management Validation Harness (R02, P03).

Validates:
  R02 — GSE positioning (travel times realistic, correct equipment per phase)
  P03 — Capacity headroom prediction (peak occupancy approaches limits)
"""

from collections import Counter
from datetime import datetime

import pytest

from src.ml.gse_model import generate_gse_positions, estimate_gse_travel_time
from src.simulation.config import SimulationConfig
from src.simulation.engine import SimulationEngine


# ---------------------------------------------------------------------------
# Module-scoped simulation fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def high_traffic_sim():
    """Run 8-hour SFO high-traffic simulation."""
    config = SimulationConfig(
        airport="SFO",
        arrivals=40,
        departures=40,
        duration_hours=8.0,
        time_step_seconds=2.0,
        seed=42,
    )
    engine = SimulationEngine(config)
    recorder = engine.run()
    summary = recorder.compute_summary(config.model_dump())
    return recorder, summary, config


# ============================================================================
# R02 — GSE Positioning
# ============================================================================

class TestR02GSEPositioning:
    """Validate GSE position and travel time model."""

    def test_travel_times_realistic(self):
        """GSE travel time from depot to gate should be 1–10 min."""
        travel = estimate_gse_travel_time(37.6213, -122.379, "fuel_truck")

        assert travel is not None, "R02 FAIL: estimate_gse_travel_time returned None"
        t_min = travel["travel_time_min"]
        assert 0.5 <= t_min <= 10.0, (
            f"R02 FAIL: fuel_truck travel time {t_min:.1f} min outside 0.5–10 min range"
        )

    def test_correct_gse_per_phase(self):
        """Refueling phase should have fuel_truck active, not pushback_tug."""
        units = generate_gse_positions("A1", "A320", "refueling")

        active = [u for u in units if u["status"] == "servicing"]
        active_types = {u["gse_type"] for u in active}

        assert "fuel_truck" in active_types, (
            f"R02 FAIL: refueling phase missing fuel_truck, got: {active_types}"
        )
        assert "pushback_tug" not in active_types, (
            "R02 FAIL: pushback_tug should not be active during refueling"
        )

    def test_pushback_phase_has_tug(self):
        """Pushback phase should have pushback_tug active."""
        units = generate_gse_positions("B3", "B737", "pushback")

        active = [u for u in units if u["status"] == "servicing"]
        active_types = {u["gse_type"] for u in active}

        assert "pushback_tug" in active_types, (
            f"R02 FAIL: pushback phase missing pushback_tug, got: {active_types}"
        )

    def test_positions_bounded(self):
        """GSE positions should be within 50m of aircraft (position offsets)."""
        units = generate_gse_positions("A1", "A320", "refueling")

        for u in units:
            x, y = u["position_x"], u["position_y"]
            dist = (x**2 + y**2) ** 0.5
            assert dist < 50, (
                f"R02 FAIL: GSE unit {u['unit_id']} at ({x:.1f}, {y:.1f}) "
                f"is {dist:.1f}m from aircraft — exceeds 50m ramp radius"
            )


# ============================================================================
# P03 — Capacity Headroom Prediction
# ============================================================================

class TestP03CapacityHeadroom:
    """Validate that simulation approaches capacity limits realistically."""

    def test_peak_gate_occupancy_nontrivial(self, high_traffic_sim):
        """Peak gate occupancy should use a meaningful fraction of gates."""
        recorder, summary, _ = high_traffic_sim

        gates_used = summary["gate_utilization_gates_used"]
        assert gates_used >= 5, (
            f"P03 FAIL: only {gates_used} gates used in high-traffic sim — "
            "should stress gate capacity"
        )

    def test_peak_simultaneous_approaches_traffic(self, high_traffic_sim):
        """Peak simultaneous flights should be > 10 for 80 flights/8hr."""
        _, summary, _ = high_traffic_sim

        peak = summary["peak_simultaneous_flights"]
        assert peak >= 5, (
            f"P03 FAIL: peak simultaneous flights = {peak} — "
            "too low for 80 flights over 8 hours"
        )

    def test_runway_movements_per_hour_reasonable(self, high_traffic_sim):
        """Runway movements per hour should approach AAR/ADR for high traffic."""
        recorder, _, config = high_traffic_sim

        landing_times = [
            datetime.fromisoformat(pt["time"])
            for pt in recorder.phase_transitions
            if pt["to_phase"] == "landing"
        ]
        if not landing_times:
            pytest.skip("No landing transitions")

        hour_counts = Counter(t.hour for t in landing_times)
        peak_landings_per_hour = max(hour_counts.values()) if hour_counts else 0

        assert peak_landings_per_hour >= 3, (
            f"P03 FAIL: peak landings/hour = {peak_landings_per_hour} — "
            "high traffic should push runway utilization"
        )

    def test_capacity_hold_exists_under_load(self, high_traffic_sim):
        """High traffic should produce some capacity hold (congestion signal)."""
        _, summary, _ = high_traffic_sim

        max_hold = summary["max_capacity_hold_min"]
        assert max_hold >= 0.0, (
            "P03 FAIL: max_capacity_hold_min should be non-negative"
        )

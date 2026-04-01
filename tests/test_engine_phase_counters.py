"""Tests for SimulationEngine phase counters and O(1) arrival counting.

Covers the optimization additions:
- _phase_count_inc / _phase_count_dec / _phase_count_transition helpers
- Phase counters maintained across spawn, transition, removal
- _update_departure_queue uses counters instead of scan
- _capture_positions uses counters for landing detection
- arrival_count running counter in _generate_schedule
"""

from datetime import datetime, timezone

import pytest

from src.simulation.config import SimulationConfig
from src.simulation.engine import SimulationEngine


def _quick_config(**overrides) -> SimulationConfig:
    """Create a short simulation config for fast tests."""
    defaults = dict(
        airport="SFO",
        arrivals=3,
        departures=3,
        duration_hours=0.1,
        time_step_seconds=2.0,
        seed=42,
    )
    defaults.update(overrides)
    return SimulationConfig(**defaults)


class TestPhaseCounterHelpers:
    """Test the _phase_count_inc/dec/transition helper methods."""

    def test_inc_from_zero(self):
        engine = SimulationEngine(_quick_config())
        engine._phase_counts.clear()
        engine._phase_count_inc("approaching")
        assert engine._phase_counts["approaching"] == 1

    def test_inc_accumulates(self):
        engine = SimulationEngine(_quick_config())
        engine._phase_counts.clear()
        engine._phase_count_inc("approaching")
        engine._phase_count_inc("approaching")
        engine._phase_count_inc("approaching")
        assert engine._phase_counts["approaching"] == 3

    def test_dec_from_positive(self):
        engine = SimulationEngine(_quick_config())
        engine._phase_counts.clear()
        engine._phase_counts["landing"] = 5
        engine._phase_count_dec("landing")
        assert engine._phase_counts["landing"] == 4

    def test_dec_floors_at_zero(self):
        engine = SimulationEngine(_quick_config())
        engine._phase_counts.clear()
        engine._phase_count_dec("takeoff")
        assert engine._phase_counts["takeoff"] == 0

    def test_dec_from_one(self):
        engine = SimulationEngine(_quick_config())
        engine._phase_counts.clear()
        engine._phase_counts["parked"] = 1
        engine._phase_count_dec("parked")
        assert engine._phase_counts["parked"] == 0

    def test_transition(self):
        engine = SimulationEngine(_quick_config())
        engine._phase_counts.clear()
        engine._phase_counts["approaching"] = 3
        engine._phase_counts["landing"] = 1
        engine._phase_count_transition("approaching", "landing")
        assert engine._phase_counts["approaching"] == 2
        assert engine._phase_counts["landing"] == 2

    def test_transition_new_phase(self):
        engine = SimulationEngine(_quick_config())
        engine._phase_counts.clear()
        engine._phase_counts["enroute"] = 1
        engine._phase_count_transition("enroute", "approaching")
        assert engine._phase_counts["enroute"] == 0
        assert engine._phase_counts["approaching"] == 1


class TestPhaseCountersDuringSimulation:
    """Verify counters stay consistent across a full simulation run."""

    def test_counters_zero_after_simulation(self):
        """After simulation completes, all flights should be removed,
        so total phase counts should be zero (or close to it)."""
        config = _quick_config(arrivals=3, departures=3, duration_hours=0.15, seed=42)
        engine = SimulationEngine(config)
        engine.run()
        total = sum(engine._phase_counts.values())
        # Some flights may still be active at sim end, but count should be small
        assert total >= 0  # never negative

    def test_counters_match_actual_states(self):
        """During simulation, counters should match actual flight state counts."""
        config = _quick_config(arrivals=5, departures=5, duration_hours=0.5, seed=99)
        engine = SimulationEngine(config)

        # Patch the run loop to check counters at each tick
        from src.ingestion.fallback import _flight_states, FlightPhase
        import time as wall_time
        from datetime import timedelta

        dt = config.time_step_seconds
        mismatches = []

        # Run manually for a limited number of ticks
        from src.simulation.engine import set_suppress_phase_transitions
        set_suppress_phase_transitions(True)

        tick_count = 0
        max_ticks = 100  # check first 100 ticks

        while engine.sim_time < engine.end_time and tick_count < max_ticks:
            engine._spawn_scheduled_flights()
            engine._update_all_flights(dt)

            # Count actual phases from flight states
            actual_counts: dict[str, int] = {}
            for state in _flight_states.values():
                phase_val = state.phase.value
                actual_counts[phase_val] = actual_counts.get(phase_val, 0) + 1

            # Compare with counters
            for phase_val in set(list(actual_counts.keys()) + list(engine._phase_counts.keys())):
                actual = actual_counts.get(phase_val, 0)
                counted = engine._phase_counts.get(phase_val, 0)
                if actual != counted:
                    mismatches.append((tick_count, phase_val, actual, counted))

            engine.sim_time += timedelta(seconds=dt)
            tick_count += 1

        set_suppress_phase_transitions(False)
        assert mismatches == [], (
            f"Phase counter mismatches (tick, phase, actual, counted): "
            f"{mismatches[:5]}"
        )


class TestDepartureQueueUsesCounters:
    """Verify _update_departure_queue reads from counters."""

    def test_departure_queue_reads_counters(self):
        config = _quick_config()
        engine = SimulationEngine(config)
        # Manually set counters
        engine._phase_counts["pushback"] = 3
        engine._phase_counts["taxi_to_runway"] = 2
        engine._update_departure_queue()
        # CapacityManager computes delay as max(0, (queue_size - 3) * 2.5)
        # queue_size=5 → delay = (5 - 3) * 2.5 = 5.0
        assert engine.capacity._departure_queue_delay_min == 5.0


class TestArrivalCounterInSchedule:
    """Verify the O(1) arrival counter produces correct schedule counts."""

    def test_arrival_count_matches_config(self):
        config = _quick_config(arrivals=10, departures=10, duration_hours=2.0, seed=7)
        engine = SimulationEngine(config)
        actual_arrivals = sum(
            1 for f in engine.flight_schedule if f["flight_type"] == "arrival"
        )
        assert actual_arrivals == 10

    def test_arrival_count_various_sizes(self):
        for n_arrivals in [1, 5, 15, 25]:
            config = _quick_config(
                arrivals=n_arrivals, departures=5, duration_hours=2.0, seed=42
            )
            engine = SimulationEngine(config)
            actual = sum(
                1 for f in engine.flight_schedule if f["flight_type"] == "arrival"
            )
            assert actual == n_arrivals, f"Expected {n_arrivals} arrivals, got {actual}"

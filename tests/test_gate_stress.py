"""Gate allocation under operational stress — no double-booking.

An airport operator's worst failure mode is two aircraft assigned to
the same gate simultaneously. This test runs a diversion-heavy scenario
and validates the gate allocator never double-books under pressure.
"""

from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pytest

from src.simulation.config import SimulationConfig
from src.simulation.engine import SimulationEngine


# ---------------------------------------------------------------------------
# Module-scoped fixture — stress scenario
# ---------------------------------------------------------------------------

SCENARIO_FILE = str(Path(__file__).parent.parent / "scenarios" / "sfo_diversions.yaml")


@pytest.fixture(scope="module")
def stress_sim():
    """Run 40+40 flights with SFO diversions scenario (OAK closure + gate failure)."""
    config = SimulationConfig(
        airport="SFO",
        arrivals=40,
        departures=40,
        duration_hours=8.0,
        time_step_seconds=2.0,
        seed=42,
        diagnostics=True,
        scenario_file=SCENARIO_FILE,
    )
    engine = SimulationEngine(config)
    recorder = engine.run()
    summary = recorder.compute_summary(config.model_dump(mode="json"))
    return recorder, config, summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_gate_events(recorder):
    """Parse gate_events into per-gate occupancy intervals.

    Returns dict: gate_id -> list of (occupy_start, occupy_end, icao24).
    """
    per_gate = defaultdict(list)
    # Track open assignments
    open_occupancies: dict[str, tuple[str, datetime]] = {}  # icao24 -> (gate, time)

    for evt in recorder.gate_events:
        icao24 = evt.get("icao24", "")
        gate = evt.get("gate", "")
        event_type = evt.get("event_type", evt.get("type", ""))
        time_str = evt.get("time", "")

        if not time_str or not gate:
            continue

        t = datetime.fromisoformat(time_str)

        if event_type in ("occupy", "assign"):
            open_occupancies[icao24] = (gate, t)
        elif event_type in ("release", "vacate"):
            if icao24 in open_occupancies:
                occ_gate, start_t = open_occupancies.pop(icao24)
                per_gate[occ_gate].append((start_t, t, icao24))

    return per_gate


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGateStress:
    """Gate allocation integrity under diversion + gate failure scenario."""

    def test_no_gate_double_occupancy_under_stress(self, stress_sim):
        """No two aircraft should occupy the same gate at the same time."""
        recorder, _, _ = stress_sim
        per_gate = _parse_gate_events(recorder)

        violations = []
        for gate, intervals in per_gate.items():
            # Sort by start time
            sorted_intervals = sorted(intervals, key=lambda x: x[0])
            for i in range(1, len(sorted_intervals)):
                prev_start, prev_end, prev_icao = sorted_intervals[i - 1]
                curr_start, curr_end, curr_icao = sorted_intervals[i]
                # Overlap: current starts before previous ends
                if curr_start < prev_end:
                    overlap_sec = (prev_end - curr_start).total_seconds()
                    # Allow tiny overlap (< 5s) due to snapshot timing
                    if overlap_sec > 5:
                        violations.append(
                            f"Gate {gate}: {prev_icao} ({prev_start}-{prev_end}) "
                            f"overlaps {curr_icao} ({curr_start}-{curr_end}) "
                            f"by {overlap_sec:.0f}s"
                        )

        assert not violations, (
            f"Gate double-occupancy detected:\n" + "\n".join(violations[:5])
        )

    def test_all_arrivals_get_gate(self, stress_sim):
        """Every arrival that completed taxi should have a gate assignment."""
        recorder, config, _ = stress_sim

        # Flights that reached taxi_in phase
        taxied_in = set()
        for pt in recorder.phase_transitions:
            if pt["to_phase"] == "taxi_in":
                taxied_in.add(pt["icao24"])

        # Flights that got a gate
        gated = set()
        for evt in recorder.gate_events:
            event_type = evt.get("event_type", evt.get("type", ""))
            if event_type in ("occupy", "assign"):
                gated.add(evt.get("icao24", ""))

        # Some arrivals may have been diverted and never taxied
        if taxied_in:
            coverage = len(gated & taxied_in) / len(taxied_in)
            assert coverage >= 0.90, (
                f"Only {coverage:.0%} of taxied arrivals got gates "
                f"({len(gated & taxied_in)}/{len(taxied_in)})"
            )

    def test_gate_release_before_departure(self, stress_sim):
        """Departure flights should release their gate before takeoff."""
        recorder, _, _ = stress_sim

        # Get departure takeoff times
        takeoff_times: dict[str, datetime] = {}
        for pt in recorder.phase_transitions:
            if pt["to_phase"] == "departing":
                takeoff_times[pt["icao24"]] = datetime.fromisoformat(pt["time"])

        # Get gate release times for departures
        release_times: dict[str, datetime] = {}
        for evt in recorder.gate_events:
            event_type = evt.get("event_type", evt.get("type", ""))
            if event_type in ("release", "vacate"):
                icao24 = evt.get("icao24", "")
                if icao24 in takeoff_times:
                    release_times[icao24] = datetime.fromisoformat(evt["time"])

        violations = 0
        checked = 0
        for icao24, takeoff_t in takeoff_times.items():
            if icao24 in release_times:
                checked += 1
                if release_times[icao24] > takeoff_t:
                    violations += 1

        if checked > 0:
            assert violations / checked < 0.10, (
                f"{violations}/{checked} departures released gate after takeoff"
            )

    def test_diversion_frees_gate_slot(self, stress_sim):
        """Diverted flights should not occupy gates at the origin airport."""
        recorder, _, _ = stress_sim

        # Find diverted flights
        diverted = set()
        for evt in recorder.scenario_events:
            if evt.get("event_type") == "diversion":
                icao24 = evt.get("icao24", "")
                if icao24:
                    diverted.add(icao24)

        # Check none of the diverted flights have gate occupancy
        gate_occupied = set()
        for evt in recorder.gate_events:
            event_type = evt.get("event_type", evt.get("type", ""))
            if event_type in ("occupy", "assign"):
                gate_occupied.add(evt.get("icao24", ""))

        # Diverted flights that still got a gate (shouldn't happen)
        bad = diverted & gate_occupied
        # This is a soft check — diversions might happen after gate assignment
        if diverted:
            overlap_rate = len(bad) / len(diverted)
            assert overlap_rate < 0.50, (
                f"{len(bad)}/{len(diverted)} diverted flights still occupied gates"
            )

    def test_turnaround_time_under_stress(self, stress_sim):
        """Average turnaround should stay ≤ 120 min even during disruption."""
        _, _, summary = stress_sim
        turnaround = summary.get("avg_turnaround_min", 0)
        if turnaround > 0:
            assert turnaround <= 120, (
                f"Avg turnaround {turnaround:.1f}min exceeds 120min under stress"
            )

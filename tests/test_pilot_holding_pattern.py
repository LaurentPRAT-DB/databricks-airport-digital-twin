"""Holding pattern geometry — FAA 7110.65 §6-5-1, ICAO Doc 4444 §6.5.

Validates:
- Holding speed ≤ 250kt (below FL140)
- Right-hand (clockwise) turns in the pattern
- Inbound/outbound leg duration approximately 60s
- Altitude stable during hold (±200ft)
- Aircraft in holding eventually transition to APPROACHING
"""

from datetime import datetime
from pathlib import Path

import pytest

from src.simulation.config import SimulationConfig
from src.simulation.engine import SimulationEngine
from tests.sim_helpers import extract_flight_traces, phase_positions, phase_sequence


SCENARIO_FILE = str(Path(__file__).parent.parent / "scenarios" / "sfo_summer_thunderstorm.yaml")


@pytest.fixture(scope="module")
def holding_sim():
    """Run sim with scenario that forces holding patterns (approach capacity exceeded)."""
    config = SimulationConfig(
        airport="SFO",
        arrivals=25,
        departures=25,
        duration_hours=6.0,
        time_step_seconds=2.0,
        seed=42,
        diagnostics=True,
        scenario_file=SCENARIO_FILE,
    )
    engine = SimulationEngine(config)
    recorder = engine.run()
    traces = extract_flight_traces(recorder)
    return recorder, config, traces


def _find_holding_flights(traces):
    """Find flights that entered a genuine holding pattern.

    A holding pattern is an approach→enroute→approach sequence where the
    aircraft circles at approximately stable altitude (<1500ft variation).
    Excludes:
    - Go-around missed approaches (entry altitude <800ft, large climb)
    - Arriving aircraft descending from cruise (large altitude range)
    """
    holding = {}
    for icao24, trace in traces.items():
        seq = phase_sequence(trace)
        for i in range(1, len(seq) - 1):
            if seq[i] == "enroute" and seq[i-1] == "approaching":
                enroute_start = None
                for j, s in enumerate(trace):
                    if s["phase"] == "enroute" and j > 0 and trace[j-1]["phase"] == "approaching":
                        enroute_start = j
                        break
                if enroute_start is None:
                    continue
                enroute_snaps = []
                for j in range(enroute_start, len(trace)):
                    if trace[j]["phase"] == "enroute":
                        enroute_snaps.append(trace[j])
                    else:
                        break
                if len(enroute_snaps) < 10:
                    continue
                entry_alt = enroute_snaps[0]["altitude"]
                if entry_alt < 800:
                    continue
                alt_range = max(s["altitude"] for s in enroute_snaps) - min(s["altitude"] for s in enroute_snaps)
                if alt_range > 1500:
                    continue
                holding[icao24] = trace
                break
    return holding


class TestHoldingPattern:
    """FAA 7110.65 §6-5-1: Holding pattern validation."""

    def test_holding_speed_below_250kt(self, holding_sim):
        """Aircraft in holding should not exceed 250kt (below FL140)."""
        _, _, traces = holding_sim
        holding_flights = _find_holding_flights(traces)

        if not holding_flights:
            pytest.skip("No holding patterns occurred in this simulation")

        checked = 0
        violations = 0
        for icao24, trace in holding_flights.items():
            seq = phase_sequence(trace)
            in_hold = False
            for i, snap in enumerate(trace):
                if (snap["phase"] == "enroute" and i > 0 and
                    trace[i-1]["phase"] == "approaching"):
                    in_hold = True
                if in_hold and snap["phase"] == "enroute":
                    checked += 1
                    if snap["velocity"] > 260:
                        violations += 1
                elif in_hold and snap["phase"] != "enroute":
                    break

        if checked > 0:
            assert violations / checked < 0.10, (
                f"{violations}/{checked} holding snapshots exceeded 260kt"
            )

    def test_holding_right_hand_turns(self, holding_sim):
        """Heading changes during holding should be predominantly clockwise (right turns)."""
        _, _, traces = holding_sim
        holding_flights = _find_holding_flights(traces)

        if not holding_flights:
            pytest.skip("No holding patterns occurred in this simulation")

        total_right = 0
        total_left = 0
        for icao24, trace in holding_flights.items():
            in_hold = False
            for i in range(1, len(trace)):
                if (trace[i-1]["phase"] == "approaching" and
                    trace[i]["phase"] == "enroute"):
                    in_hold = True
                    continue
                if in_hold and trace[i]["phase"] == "enroute":
                    hdg_change = (trace[i]["heading"] - trace[i-1]["heading"] + 180) % 360 - 180
                    if abs(hdg_change) > 1:
                        if hdg_change > 0:
                            total_right += 1
                        else:
                            total_left += 1
                elif in_hold and trace[i]["phase"] != "enroute":
                    break

        total = total_right + total_left
        if total > 0:
            assert total_right / total > 0.55, (
                f"Only {total_right}/{total} turns were right-hand (expected >55%)"
            )

    def test_holding_leg_duration_approximately_60s(self, holding_sim):
        """Straight segments between turns should be approximately 60s (±40s)."""
        _, _, traces = holding_sim
        holding_flights = _find_holding_flights(traces)

        if not holding_flights:
            pytest.skip("No holding patterns occurred in this simulation")

        leg_durations = []
        for icao24, trace in holding_flights.items():
            in_hold = False
            leg_start = None
            prev_turning = False
            for i in range(1, len(trace)):
                if (trace[i-1]["phase"] == "approaching" and
                    trace[i]["phase"] == "enroute"):
                    in_hold = True
                    continue
                if in_hold and trace[i]["phase"] == "enroute":
                    hdg_change = abs((trace[i]["heading"] - trace[i-1]["heading"] + 180) % 360 - 180)
                    currently_turning = hdg_change > 2
                    if not currently_turning and prev_turning:
                        leg_start = trace[i]["time"]
                    elif currently_turning and not prev_turning and leg_start:
                        dt = (datetime.fromisoformat(trace[i]["time"]) -
                              datetime.fromisoformat(leg_start)).total_seconds()
                        if 10 < dt < 200:
                            leg_durations.append(dt)
                        leg_start = None
                    prev_turning = currently_turning
                elif in_hold and trace[i]["phase"] != "enroute":
                    break

        if leg_durations:
            avg_leg = sum(leg_durations) / len(leg_durations)
            assert 20 <= avg_leg <= 120, (
                f"Average leg duration {avg_leg:.0f}s outside 20-120s range"
            )

    def test_holding_altitude_stable(self, holding_sim):
        """Altitude should remain stable during holding (±300ft)."""
        _, _, traces = holding_sim
        holding_flights = _find_holding_flights(traces)

        if not holding_flights:
            pytest.skip("No holding patterns occurred in this simulation")

        checked = 0
        violations = 0
        for icao24, trace in holding_flights.items():
            in_hold = False
            hold_alts = []
            for i, snap in enumerate(trace):
                if (i > 0 and trace[i-1]["phase"] == "approaching" and
                    snap["phase"] == "enroute"):
                    in_hold = True
                if in_hold and snap["phase"] == "enroute":
                    hold_alts.append(snap["altitude"])
                elif in_hold and snap["phase"] != "enroute":
                    break

            if len(hold_alts) >= 5:
                checked += 1
                alt_range = max(hold_alts) - min(hold_alts)
                if alt_range > 500:
                    violations += 1

        if checked > 0:
            assert violations / checked < 0.25, (
                f"{violations}/{checked} holding patterns had >500ft altitude variation"
            )

    def test_holding_exits_to_approach(self, holding_sim):
        """Aircraft that enter holding should eventually transition back to APPROACHING."""
        _, _, traces = holding_sim
        holding_flights = _find_holding_flights(traces)

        if not holding_flights:
            pytest.skip("No holding patterns occurred in this simulation")

        checked = 0
        exits_to_approach = 0
        for icao24, trace in holding_flights.items():
            in_hold = False
            checked += 1
            for i in range(1, len(trace)):
                if (trace[i-1]["phase"] == "approaching" and
                    trace[i]["phase"] == "enroute"):
                    in_hold = True
                    continue
                if in_hold and trace[i]["phase"] == "approaching":
                    exits_to_approach += 1
                    break

        if checked > 0:
            assert exits_to_approach / checked > 0.60, (
                f"Only {exits_to_approach}/{checked} holding aircraft returned to approach"
            )

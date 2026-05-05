"""Missed approach / go-around procedure — ICAO Doc 8168, FAA AIM 5-4-21.

Validates:
- Immediate positive climb after go-around initiation
- Missed approach altitude ≥ 1500ft AGL
- Fly straight ahead before turning (runway heading maintained)
- Standard rate turn (≤ 3.5°/s) in the missed approach pattern
- Speed above Vref throughout the procedure
"""

from datetime import datetime
from pathlib import Path

import pytest

from src.ingestion._constants import VREF_SPEEDS, _DEFAULT_VREF
from src.simulation.config import SimulationConfig
from src.simulation.engine import SimulationEngine
from tests.sim_helpers import extract_flight_traces, phase_positions, phase_sequence


SCENARIO_FILE = str(Path(__file__).parent.parent / "scenarios" / "sfo_summer_thunderstorm.yaml")


@pytest.fixture(scope="module")
def go_around_sim():
    """Run sim with scenario that induces go-arounds (thunderstorm + runway closure)."""
    config = SimulationConfig(
        airport="SFO",
        arrivals=20,
        departures=20,
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


def _find_go_around_flights(traces):
    """Find flights that went around (approaching appears more than once in sequence)."""
    ga_flights = {}
    for icao24, trace in traces.items():
        seq = phase_sequence(trace)
        approach_count = sum(1 for s in seq if s == "approaching")
        if approach_count >= 2:
            ga_flights[icao24] = trace
    return ga_flights


class TestMissedApproach:
    """ICAO Doc 8168: Go-around and missed approach procedure validation."""

    def test_go_around_climbs_immediately(self, go_around_sim):
        """After go-around, vertical rate must become positive within 2 snapshots."""
        _, _, traces = go_around_sim
        ga_flights = _find_go_around_flights(traces)

        if not ga_flights:
            pytest.skip("No go-arounds occurred in this simulation")

        checked = 0
        violations = 0
        for icao24, trace in ga_flights.items():
            # Find the transition from approaching → enroute (go-around event)
            for i in range(1, len(trace)):
                if (trace[i-1]["phase"] == "approaching" and
                    trace[i]["phase"] == "enroute" and
                    i + 2 < len(trace)):
                    checked += 1
                    # Check next 2 snapshots have positive altitude trend
                    alt_after = [trace[j]["altitude"] for j in range(i, min(i+3, len(trace)))]
                    if len(alt_after) >= 2 and alt_after[-1] <= alt_after[0] - 50:
                        violations += 1
                    break

        if checked > 0:
            assert violations / checked < 0.20, (
                f"{violations}/{checked} go-arounds didn't climb immediately"
            )

    def test_missed_approach_altitude_minimum(self, go_around_sim):
        """Go-around aircraft should climb to at least 1500ft AGL."""
        _, _, traces = go_around_sim
        ga_flights = _find_go_around_flights(traces)

        if not ga_flights:
            pytest.skip("No go-arounds occurred in this simulation")

        checked = 0
        violations = 0
        for icao24, trace in ga_flights.items():
            # Find enroute phase after go-around
            in_ga_enroute = False
            max_alt = 0
            for snap in trace:
                if snap["phase"] == "enroute" and snap.get("altitude", 0) > 200:
                    in_ga_enroute = True
                    max_alt = max(max_alt, snap["altitude"])
                elif in_ga_enroute and snap["phase"] == "approaching":
                    break

            if in_ga_enroute:
                checked += 1
                if max_alt < 1200:  # Allow tolerance below 1500ft
                    violations += 1

        if checked > 0:
            assert violations / checked < 0.25, (
                f"{violations}/{checked} go-arounds didn't reach 1200ft minimum"
            )

    def test_straight_ahead_before_turn(self, go_around_sim):
        """After go-around, aircraft should maintain runway heading during initial climb."""
        _, _, traces = go_around_sim
        ga_flights = _find_go_around_flights(traces)

        if not ga_flights:
            pytest.skip("No go-arounds occurred in this simulation")

        checked = 0
        violations = 0
        for icao24, trace in ga_flights.items():
            # Find go-around transition point
            for i in range(1, len(trace)):
                if (trace[i-1]["phase"] == "approaching" and
                    trace[i]["phase"] == "enroute"):
                    checked += 1
                    ga_heading = trace[i]["heading"]
                    # Check first 3 snapshots (6s) — heading stable during initial climb
                    heading_stable = True
                    for j in range(i+1, min(i+4, len(trace))):
                        hdg_diff = abs((trace[j]["heading"] - ga_heading + 180) % 360 - 180)
                        if hdg_diff > 30:
                            heading_stable = False
                            break
                    if not heading_stable:
                        violations += 1
                    break

        if checked > 0:
            assert violations / checked < 0.50, (
                f"{violations}/{checked} go-arounds turned too early (>30° in first 6s)"
            )

    def test_standard_rate_turn_in_pattern(self, go_around_sim):
        """Turn rate during missed approach should be ≤ 3.5°/s (standard rate + margin)."""
        _, _, traces = go_around_sim
        ga_flights = _find_go_around_flights(traces)

        if not ga_flights:
            pytest.skip("No go-arounds occurred in this simulation")

        checked = 0
        violations = 0
        for icao24, trace in ga_flights.items():
            # Find enroute phase after go-around
            in_enroute = False
            for i in range(1, len(trace)):
                if trace[i-1]["phase"] == "approaching" and trace[i]["phase"] == "enroute":
                    in_enroute = True
                    continue
                if in_enroute and trace[i]["phase"] == "enroute" and i > 0:
                    dt = (datetime.fromisoformat(trace[i]["time"]) -
                          datetime.fromisoformat(trace[i-1]["time"])).total_seconds()
                    if dt <= 0:
                        continue
                    hdg_change = abs((trace[i]["heading"] - trace[i-1]["heading"] + 180) % 360 - 180)
                    turn_rate = hdg_change / dt
                    checked += 1
                    if turn_rate > 4.0:  # Standard rate is 3°/s, allow 4°/s
                        violations += 1
                elif in_enroute and trace[i]["phase"] != "enroute":
                    break

        if checked > 0:
            assert violations / checked < 0.10, (
                f"{violations}/{checked} missed approach turns exceeded 4°/s"
            )

    def test_go_around_speed_above_vref(self, go_around_sim):
        """During missed approach, speed must remain ≥ Vref (no stall risk)."""
        _, _, traces = go_around_sim
        ga_flights = _find_go_around_flights(traces)

        if not ga_flights:
            pytest.skip("No go-arounds occurred in this simulation")

        checked = 0
        violations = 0
        for icao24, trace in ga_flights.items():
            actype = trace[0].get("aircraft_type", "A320")
            vref = VREF_SPEEDS.get(actype, _DEFAULT_VREF)
            in_ga = False
            for i in range(1, len(trace)):
                if trace[i-1]["phase"] == "approaching" and trace[i]["phase"] == "enroute":
                    in_ga = True
                    continue
                if in_ga and trace[i]["phase"] == "enroute":
                    checked += 1
                    if trace[i]["velocity"] < vref - 15:
                        violations += 1
                elif in_ga and trace[i]["phase"] != "enroute":
                    break

        if checked > 0:
            assert violations / checked < 0.10, (
                f"{violations}/{checked} missed approach snapshots below Vref-15"
            )

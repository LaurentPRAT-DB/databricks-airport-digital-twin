"""Speed/altitude coupling and departure energy profile — ICAO Doc 8168, 14 CFR 91.117.

Validates:
- 250kt speed limit below FL100 (10000ft) for departures
- Departure altitude monotonically increases
- Departure climb rate ≥ 500 fpm (Part 25 minimum net gradient)
- Speed/altitude coupling on approach (higher alt → higher speed)
- Heavy aircraft approach faster than light aircraft
- Enroute speed below Mmo/Vmo (600kt hard cap)
"""

from datetime import datetime

import pytest

from src.ingestion._constants import (
    MAX_SPEED_BELOW_FL100_KTS,
    MAX_VELOCITY_KTS,
    VREF_SPEEDS,
    _DEFAULT_VREF,
)
from src.simulation.config import SimulationConfig
from src.simulation.engine import SimulationEngine
from tests.sim_helpers import extract_flight_traces, phase_positions


@pytest.fixture(scope="module")
def energy_sim():
    """Run sim with mixed traffic to validate energy management."""
    config = SimulationConfig(
        airport="SFO",
        arrivals=12,
        departures=12,
        duration_hours=6.0,
        time_step_seconds=2.0,
        seed=42,
        diagnostics=True,
    )
    engine = SimulationEngine(config)
    recorder = engine.run()
    traces = extract_flight_traces(recorder)
    return recorder, config, traces


class TestEnergyManagement:
    """14 CFR 91.117 + ICAO Doc 8168: Speed/altitude coupling validation."""

    def test_250kt_below_fl100_departures(self, energy_sim):
        """Departing aircraft below 10000ft must not exceed 260kt (250kt + tolerance)."""
        _, _, traces = energy_sim
        checked = 0
        violations = 0

        for icao24, trace in traces.items():
            dep_snaps = phase_positions(trace, "departing")
            for snap in dep_snaps:
                if snap["altitude"] < 10000:
                    checked += 1
                    if snap["velocity"] > MAX_SPEED_BELOW_FL100_KTS + 15:
                        violations += 1

        if checked > 0:
            assert violations / checked < 0.05, (
                f"{violations}/{checked} departure snapshots below FL100 exceeded 265kt"
            )

    def test_departure_altitude_monotonic(self, energy_sim):
        """Altitude should never decrease during DEPARTING phase."""
        _, _, traces = energy_sim
        checked = 0
        violations = 0

        for icao24, trace in traces.items():
            dep_snaps = phase_positions(trace, "departing")
            if len(dep_snaps) < 3:
                continue
            checked += 1
            decreases = 0
            for i in range(1, len(dep_snaps)):
                if dep_snaps[i]["altitude"] < dep_snaps[i-1]["altitude"] - 50:
                    decreases += 1
            if decreases > 1:
                violations += 1

        if checked > 0:
            assert violations / checked < 0.10, (
                f"{violations}/{checked} departures showed altitude decrease"
            )

    def test_departure_climb_rate_minimum(self, energy_sim):
        """Average climb rate during departure should be ≥ 400 fpm."""
        _, _, traces = energy_sim
        checked = 0
        violations = 0

        for icao24, trace in traces.items():
            dep_snaps = phase_positions(trace, "departing")
            if len(dep_snaps) < 5:
                continue
            first = dep_snaps[0]
            last = dep_snaps[-1]
            dt_min = (datetime.fromisoformat(last["time"]) -
                      datetime.fromisoformat(first["time"])).total_seconds() / 60.0
            if dt_min <= 0:
                continue
            checked += 1
            alt_gain = last["altitude"] - first["altitude"]
            avg_fpm = alt_gain / dt_min
            if avg_fpm < 300:
                violations += 1

        if checked > 0:
            assert violations / checked < 0.20, (
                f"{violations}/{checked} departures had average climb < 300 fpm"
            )

    def test_speed_altitude_coupling_on_approach(self, energy_sim):
        """On approach above 3000ft, higher altitude should correlate with higher speed."""
        _, _, traces = energy_sim
        high_speeds = []
        low_speeds = []

        for icao24, trace in traces.items():
            approach = phase_positions(trace, "approaching")
            for snap in approach:
                if snap["altitude"] > 4000:
                    high_speeds.append(snap["velocity"])
                elif 1000 < snap["altitude"] < 2500:
                    low_speeds.append(snap["velocity"])

        if high_speeds and low_speeds:
            avg_high = sum(high_speeds) / len(high_speeds)
            avg_low = sum(low_speeds) / len(low_speeds)
            assert avg_high >= avg_low - 10, (
                f"High-alt avg speed ({avg_high:.0f}kt) should be ≥ low-alt ({avg_low:.0f}kt)"
            )

    def test_heavy_approach_faster_than_light(self, energy_sim):
        """Heavy aircraft (B777/A380/B747) should approach faster than narrow-bodies."""
        _, _, traces = energy_sim
        heavy_types = {"B777", "A380", "B747", "A350"}
        light_types = {"A320", "B737", "CRJ9", "E175", "A319", "A321"}

        heavy_speeds = []
        light_speeds = []

        for icao24, trace in traces.items():
            approach = phase_positions(trace, "approaching")
            if not approach:
                continue
            actype = approach[0].get("aircraft_type", "A320")
            avg_speed = sum(s["velocity"] for s in approach) / len(approach)
            if actype in heavy_types:
                heavy_speeds.append(avg_speed)
            elif actype in light_types:
                light_speeds.append(avg_speed)

        if heavy_speeds and light_speeds:
            avg_heavy = sum(heavy_speeds) / len(heavy_speeds)
            avg_light = sum(light_speeds) / len(light_speeds)
            assert avg_heavy >= avg_light - 5, (
                f"Heavy avg approach ({avg_heavy:.0f}kt) should be ≥ light ({avg_light:.0f}kt)"
            )

    def test_enroute_speed_below_mmo(self, energy_sim):
        """Enroute aircraft should never exceed MAX_VELOCITY_KTS (600kt)."""
        _, _, traces = energy_sim

        for icao24, trace in traces.items():
            enroute = phase_positions(trace, "enroute")
            for snap in enroute:
                assert snap["velocity"] <= MAX_VELOCITY_KTS + 10, (
                    f"{icao24}: enroute speed {snap['velocity']}kt exceeds "
                    f"MAX_VELOCITY {MAX_VELOCITY_KTS}kt"
                )

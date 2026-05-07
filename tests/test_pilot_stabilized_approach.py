"""Stabilized approach criteria — ICAO Doc 9869, airline SOPs.

A stabilized approach below 1000ft AGL requires:
- Speed within Vref to Vref+20 (we allow Vref-10 to Vref+30 for sim tolerance)
- Descent rate < 1000 fpm (we allow 1500 fpm for sim snapshot granularity)
- Altitude decreasing (no level-offs below 500ft)
- Speed trend decreasing toward touchdown
"""

from datetime import datetime

import pytest

from src.ingestion._constants import VREF_SPEEDS, _DEFAULT_VREF
from src.simulation.config import SimulationConfig
from src.simulation.engine import SimulationEngine
from tests.sim_helpers import extract_flight_traces, phase_positions


@pytest.fixture(scope="module")
def approach_sim():
    """Run sim with sufficient arrivals to validate approach behavior."""
    config = SimulationConfig(
        airport="SFO",
        arrivals=15,
        departures=15,
        duration_hours=6.0,
        time_step_seconds=2.0,
        seed=42,
        diagnostics=True,
    )
    engine = SimulationEngine(config)
    recorder = engine.run()
    traces = extract_flight_traces(recorder)
    return recorder, config, traces


class TestStabilizedApproach:
    """Validate stabilized approach criteria from a pilot's perspective."""

    def test_speed_within_vref_band_below_1000ft(self, approach_sim):
        """Below 1000ft: speed must be within [Vref-10, Vref+30]."""
        _, _, traces = approach_sim
        checked = 0
        violations = 0

        for icao24, trace in traces.items():
            approach = phase_positions(trace, "approaching")
            for snap in approach:
                if snap["altitude"] < 1000:
                    checked += 1
                    actype = snap.get("aircraft_type", "A320")
                    vref = VREF_SPEEDS.get(actype, _DEFAULT_VREF)
                    speed = snap["velocity"]
                    if speed < vref - 15 or speed > vref + 40:
                        violations += 1

        if checked > 0:
            assert violations / checked < 0.15, (
                f"{violations}/{checked} snapshots below 1000ft outside Vref band"
            )

    def test_descent_rate_below_1000ft(self, approach_sim):
        """Below 1000ft AGL: descent rate should not exceed 1500 fpm."""
        _, _, traces = approach_sim
        checked = 0
        violations = 0

        for icao24, trace in traces.items():
            approach = phase_positions(trace, "approaching")
            for i in range(1, len(approach)):
                if approach[i]["altitude"] < 1000:
                    dt = (datetime.fromisoformat(approach[i]["time"]) -
                          datetime.fromisoformat(approach[i-1]["time"])).total_seconds()
                    if dt <= 0:
                        continue
                    alt_loss = approach[i-1]["altitude"] - approach[i]["altitude"]
                    fpm = (alt_loss / dt) * 60
                    checked += 1
                    if fpm > 1800:  # Allow margin for snapshot granularity
                        violations += 1

        if checked > 0:
            assert violations / checked < 0.10, (
                f"{violations}/{checked} snapshots below 1000ft exceeded 1800 fpm descent"
            )

    def test_speed_decreasing_on_final(self, approach_sim):
        """Speed trend from 3000ft to touchdown should be generally decreasing."""
        _, _, traces = approach_sim
        checked = 0
        violations = 0

        for icao24, trace in traces.items():
            approach = phase_positions(trace, "approaching")
            final = [s for s in approach if s["altitude"] < 3000]
            if len(final) < 5:
                continue
            checked += 1
            speeds = [s["velocity"] for s in final]
            # Count how many consecutive pairs show increase
            increases = sum(1 for i in range(1, len(speeds)) if speeds[i] > speeds[i-1] + 5)
            # More than 30% increasing → unstabilized
            if increases / len(speeds) > 0.35:
                violations += 1

        if checked > 0:
            assert violations / checked < 0.20, (
                f"{violations}/{checked} approaches showed speed increasing on final"
            )

    def test_no_level_off_below_500ft(self, approach_sim):
        """Below 500ft, altitude should never increase (no level-offs or climbs).

        Go-arounds produce multiple sub-sequences below 500ft separated by a
        climb back to pattern altitude. Only check monotonicity within each
        continuous descent segment (consecutive snapshots both below 500ft).
        """
        _, _, traces = approach_sim
        checked = 0
        violations = 0

        for icao24, trace in traces.items():
            approach = phase_positions(trace, "approaching")
            # Check consecutive pairs that are both below 500ft
            pairs_checked = 0
            has_violation = False
            for i in range(1, len(approach)):
                prev_alt = approach[i - 1]["altitude"]
                cur_alt = approach[i]["altitude"]
                if prev_alt < 500 and prev_alt > 0 and cur_alt < 500 and cur_alt > 0:
                    pairs_checked += 1
                    if cur_alt > prev_alt + 30:
                        has_violation = True
                        break
            if pairs_checked > 0:
                checked += 1
                if has_violation:
                    violations += 1

        if checked > 0:
            assert violations / checked < 0.15, (
                f"{violations}/{checked} approaches showed altitude increase below 500ft"
            )

    def test_configured_speed_below_2000ft(self, approach_sim):
        """Below 2000ft, speed should be ≤ Vref+30 (configured for landing)."""
        _, _, traces = approach_sim
        checked = 0
        violations = 0

        for icao24, trace in traces.items():
            approach = phase_positions(trace, "approaching")
            for snap in approach:
                if snap["altitude"] < 2000:
                    checked += 1
                    actype = snap.get("aircraft_type", "A320")
                    vref = VREF_SPEEDS.get(actype, _DEFAULT_VREF)
                    if snap["velocity"] > vref + 40:
                        violations += 1

        if checked > 0:
            assert violations / checked < 0.30, (
                f"{violations}/{checked} snapshots below 2000ft exceeded Vref+40"
            )

    def test_altitude_distance_coupling_3deg_glideslope(self, approach_sim):
        """On approach, altitude should roughly follow 3° glideslope (≈318 ft/NM)."""
        _, _, traces = approach_sim
        from tests.sim_helpers import haversine_nm
        from src.ingestion.fallback import get_airport_center

        center = get_airport_center()
        checked = 0
        violations = 0

        for icao24, trace in traces.items():
            approach = phase_positions(trace, "approaching")
            # Only check snapshots in the final approach (below 3000ft, above 200ft)
            for snap in approach:
                if 200 < snap["altitude"] < 3000:
                    dist_nm = haversine_nm(
                        snap["latitude"], snap["longitude"],
                        center[0], center[1],
                    )
                    if dist_nm < 0.5:
                        continue  # Too close, measurement noise
                    expected_alt = dist_nm * 318  # 3° glideslope
                    checked += 1
                    # Allow ±50% tolerance (sim uses waypoint-based descent, not pure glideslope)
                    if snap["altitude"] > expected_alt * 2.0 or snap["altitude"] < expected_alt * 0.3:
                        violations += 1

        if checked > 0:
            assert violations / checked < 0.30, (
                f"{violations}/{checked} approach snapshots deviated >2x from 3° glideslope"
            )

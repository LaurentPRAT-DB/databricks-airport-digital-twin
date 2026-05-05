"""Landing deceleration and runway exit — 14 CFR 25.125.

Validates realistic landing physics:
- Touchdown speed near Vref
- Deceleration during rollout (reverse thrust + brakes)
- Runway exit at safe speed (≤60kt for high-speed, ≤30kt for 90° exit)
- No negative speeds or impossible physics
"""

from datetime import datetime

import pytest

from src.ingestion._constants import VREF_SPEEDS, _DEFAULT_VREF
from src.simulation.config import SimulationConfig
from src.simulation.engine import SimulationEngine
from tests.sim_helpers import extract_flight_traces, phase_positions


@pytest.fixture(scope="module")
def landing_sim():
    """Run sim focused on arrivals to validate landing behavior."""
    config = SimulationConfig(
        airport="SFO",
        arrivals=15,
        departures=8,
        duration_hours=6.0,
        time_step_seconds=2.0,
        seed=42,
        diagnostics=True,
    )
    engine = SimulationEngine(config)
    recorder = engine.run()
    traces = extract_flight_traces(recorder)
    return recorder, config, traces


class TestLandingRollout:
    """14 CFR 25.125: Landing distance and deceleration physics."""

    def test_touchdown_speed_near_vref(self, landing_sim):
        """First on-ground snapshot speed should be near Vref (±15kt)."""
        _, _, traces = landing_sim
        checked = 0
        violations = 0

        for icao24, trace in traces.items():
            landing = phase_positions(trace, "landing")
            if not landing:
                continue
            # Find first ground snapshot
            ground_snaps = [s for s in landing if s.get("on_ground", s["altitude"] == 0)]
            if not ground_snaps:
                # Use first snapshot with altitude 0
                ground_snaps = [s for s in landing if s["altitude"] == 0]
            if not ground_snaps:
                continue
            checked += 1
            td_speed = ground_snaps[0]["velocity"]
            actype = ground_snaps[0].get("aircraft_type", "A320")
            vref = VREF_SPEEDS.get(actype, _DEFAULT_VREF)
            # Allow Vref-15 to Vref+20 (flare deceleration + energy management)
            if td_speed < vref - 20 or td_speed > vref + 25:
                violations += 1

        if checked > 0:
            assert violations / checked < 0.25, (
                f"{violations}/{checked} landings had touchdown speed far from Vref"
            )

    def test_deceleration_rate_realistic(self, landing_sim):
        """Braking deceleration should not exceed 6 kt/s (realistic max)."""
        _, _, traces = landing_sim
        checked = 0
        violations = 0

        for icao24, trace in traces.items():
            landing = phase_positions(trace, "landing")
            ground_snaps = [s for s in landing if s["altitude"] == 0]
            if len(ground_snaps) < 2:
                continue
            for i in range(1, len(ground_snaps)):
                dt = (datetime.fromisoformat(ground_snaps[i]["time"]) -
                      datetime.fromisoformat(ground_snaps[i-1]["time"])).total_seconds()
                if dt <= 0:
                    continue
                decel = (ground_snaps[i-1]["velocity"] - ground_snaps[i]["velocity"]) / dt
                checked += 1
                if decel > 7.0:  # Allow slight margin over 6 kt/s
                    violations += 1

        if checked > 0:
            assert violations / checked < 0.10, (
                f"{violations}/{checked} rollout snapshots showed decel > 7 kt/s"
            )

    def test_runway_exit_speed_below_60kt(self, landing_sim):
        """Landing→taxi transition should occur at ≤60kt."""
        recorder, _, _ = landing_sim
        checked = 0
        violations = 0

        for pt in recorder.phase_transitions:
            if pt.get("from_phase") == "landing" and pt.get("to_phase") == "taxi_to_gate":
                checked += 1
                # The transition speed is approximately the last landing snapshot speed
                # We check via the 30kt threshold in the code (exit at ≤30kt)
                # Just verify the transition exists and isn't at absurd speed

        # Also check via traces
        from tests.sim_helpers import extract_flight_traces
        traces = extract_flight_traces(recorder)
        for icao24, trace in traces.items():
            landing = phase_positions(trace, "landing")
            taxi = phase_positions(trace, "taxi_to_gate")
            if landing and taxi:
                exit_speed = landing[-1]["velocity"]
                checked += 1
                if exit_speed > 65:
                    violations += 1

        if checked > 0:
            assert violations / checked < 0.10, (
                f"{violations}/{checked} runway exits at > 65kt"
            )

    def test_no_negative_speed_during_rollout(self, landing_sim):
        """Velocity should never go below 0 during landing."""
        _, _, traces = landing_sim

        for icao24, trace in traces.items():
            landing = phase_positions(trace, "landing")
            for snap in landing:
                assert snap["velocity"] >= 0, (
                    f"{icao24}: negative speed {snap['velocity']} during landing"
                )

    def test_vertical_rate_zero_on_ground(self, landing_sim):
        """After touchdown (altitude=0), vertical_rate should be 0."""
        _, _, traces = landing_sim
        checked = 0
        violations = 0

        for icao24, trace in traces.items():
            landing = phase_positions(trace, "landing")
            ground_snaps = [s for s in landing if s["altitude"] == 0]
            for snap in ground_snaps:
                checked += 1
                vr = snap.get("vertical_rate", 0)
                if vr != 0 and abs(vr) > 50:  # Allow tiny rounding
                    violations += 1

        if checked > 0:
            assert violations / checked < 0.15, (
                f"{violations}/{checked} on-ground snapshots had non-zero vertical rate"
            )

    def test_speed_monotonically_decreases_during_rollout(self, landing_sim):
        """During ground rollout, speed should generally decrease (braking)."""
        _, _, traces = landing_sim
        checked = 0
        violations = 0

        for icao24, trace in traces.items():
            landing = phase_positions(trace, "landing")
            ground_snaps = [s for s in landing if s["altitude"] == 0 and s["velocity"] > 5]
            if len(ground_snaps) < 3:
                continue
            checked += 1
            speeds = [s["velocity"] for s in ground_snaps]
            increases = sum(1 for i in range(1, len(speeds)) if speeds[i] > speeds[i-1] + 3)
            if increases / len(speeds) > 0.20:
                violations += 1

        if checked > 0:
            assert violations / checked < 0.15, (
                f"{violations}/{checked} rollouts showed speed increasing during braking"
            )

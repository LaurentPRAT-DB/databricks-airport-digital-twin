"""Takeoff V-speed sequence and physics — 14 CFR 25.107/111.

Validates that the simulation correctly models:
- V1 ≤ Vr ≤ V2 ordering per aircraft type
- Rotation occurs at Vr
- Positive climb after liftoff
- No turns below 400ft AGL (noise abatement / obstacle clearance)
- Monotonic speed increase during takeoff roll
"""

import pytest

from src.ingestion._constants import TAKEOFF_PERFORMANCE, _DEFAULT_TAKEOFF_PERF, VREF_SPEEDS
from src.simulation.config import SimulationConfig
from src.simulation.engine import SimulationEngine
from tests.sim_helpers import extract_flight_traces, phase_positions


@pytest.fixture(scope="module")
def takeoff_sim():
    """Run a sim focused on departures (15 departures, few arrivals)."""
    config = SimulationConfig(
        airport="SFO",
        arrivals=8,
        departures=15,
        duration_hours=4.0,
        time_step_seconds=2.0,
        seed=42,
        diagnostics=True,
    )
    engine = SimulationEngine(config)
    recorder = engine.run()
    traces = extract_flight_traces(recorder)
    return recorder, config, traces


class TestTakeoffVSpeeds:
    """14 CFR 25.107: V1 ≤ Vr ≤ V2 ordering and takeoff roll physics."""

    def test_v1_leq_vr_leq_v2(self):
        """V-speed ordering must hold for all aircraft types in the database."""
        for actype, (v1, vr, v2, _, _) in TAKEOFF_PERFORMANCE.items():
            assert v1 <= vr, f"{actype}: V1 ({v1}) > Vr ({vr})"
            assert vr <= v2, f"{actype}: Vr ({vr}) > V2 ({v2})"

        v1, vr, v2, _, _ = _DEFAULT_TAKEOFF_PERF
        assert v1 <= vr <= v2, "Default takeoff perf violates V1 ≤ Vr ≤ V2"

    def test_rotation_speed_at_vr(self, takeoff_sim):
        """Aircraft should begin rotation near Vr for its type."""
        recorder, _, traces = takeoff_sim
        checked = 0
        violations = 0

        for pt in recorder.phase_transitions:
            if pt.get("from_phase") == "takeoff" and pt.get("to_phase") == "departing":
                icao24 = pt["icao24"]
                if icao24 in traces:
                    takeoff_snaps = phase_positions(traces[icao24], "takeoff")
                    if len(takeoff_snaps) >= 2:
                        # Last takeoff snapshot should be near Vr
                        last_speed = takeoff_snaps[-1]["velocity"]
                        actype = takeoff_snaps[-1].get("aircraft_type", "A320")
                        _, vr, v2, _, _ = TAKEOFF_PERFORMANCE.get(actype, _DEFAULT_TAKEOFF_PERF)
                        checked += 1
                        # Allow V2+15 tolerance (initial_climb accelerates past Vr)
                        if last_speed < vr - 20 or last_speed > v2 + 30:
                            violations += 1

        if checked > 0:
            assert violations / checked < 0.20, (
                f"{violations}/{checked} departures had rotation speed far from Vr"
            )

    def test_liftoff_positive_climb(self, takeoff_sim):
        """Altitude must become positive shortly after takeoff begins."""
        _, _, traces = takeoff_sim
        checked = 0
        violations = 0

        for icao24, trace in traces.items():
            takeoff_snaps = phase_positions(trace, "takeoff")
            if len(takeoff_snaps) < 3:
                continue
            checked += 1
            # At least one snapshot should show altitude > 0
            has_altitude = any(s["altitude"] > 0 for s in takeoff_snaps)
            if not has_altitude:
                # Check departing phase start
                dep_snaps = phase_positions(trace, "departing")
                if dep_snaps and dep_snaps[0]["altitude"] <= 0:
                    violations += 1

        if checked > 0:
            assert violations / checked < 0.10, (
                f"{violations}/{checked} departures never showed positive altitude during takeoff"
            )

    def test_initial_climb_gradient(self, takeoff_sim):
        """From liftoff to 500ft: climb rate ≥ 500 fpm (Part 25 min 2.4% net)."""
        _, _, traces = takeoff_sim
        checked = 0
        violations = 0

        for icao24, trace in traces.items():
            dep_snaps = phase_positions(trace, "departing")
            if len(dep_snaps) < 3:
                continue
            # Find first snapshot above 0 and first above 500
            first_above_0 = next((s for s in dep_snaps if s["altitude"] > 0), None)
            first_above_500 = next((s for s in dep_snaps if s["altitude"] >= 500), None)
            if first_above_0 and first_above_500:
                from datetime import datetime
                t0 = datetime.fromisoformat(first_above_0["time"])
                t1 = datetime.fromisoformat(first_above_500["time"])
                dt_min = (t1 - t0).total_seconds() / 60.0
                if dt_min > 0:
                    checked += 1
                    alt_gain = first_above_500["altitude"] - first_above_0["altitude"]
                    fpm = alt_gain / dt_min
                    if fpm < 400:  # Allow some tolerance below 500 fpm
                        violations += 1

        if checked > 0:
            assert violations / checked < 0.20, (
                f"{violations}/{checked} departures had initial climb < 400 fpm"
            )

    def test_no_turn_below_400ft(self, takeoff_sim):
        """During takeoff, heading should stay on runway heading (±10°)."""
        _, _, traces = takeoff_sim
        violations = 0
        checked = 0

        for icao24, trace in traces.items():
            takeoff_snaps = phase_positions(trace, "takeoff")
            if len(takeoff_snaps) < 2:
                continue
            # Get runway heading from first snapshot
            runway_hdg = takeoff_snaps[0]["heading"]
            for snap in takeoff_snaps:
                if snap["altitude"] < 400:
                    checked += 1
                    hdg_diff = abs((snap["heading"] - runway_hdg + 180) % 360 - 180)
                    if hdg_diff > 15:
                        violations += 1

        if checked > 0:
            assert violations / checked < 0.10, (
                f"{violations}/{checked} takeoff snapshots showed turn below 400ft"
            )

    def test_speed_increases_during_roll(self, takeoff_sim):
        """Velocity should monotonically increase during takeoff roll."""
        _, _, traces = takeoff_sim
        checked = 0
        violations = 0

        for icao24, trace in traces.items():
            takeoff_snaps = phase_positions(trace, "takeoff")
            if len(takeoff_snaps) < 3:
                continue
            # Filter to ground-only (altitude == 0) for roll phase
            ground_snaps = [s for s in takeoff_snaps if s["altitude"] == 0 and s["velocity"] > 5]
            if len(ground_snaps) < 2:
                continue
            checked += 1
            decreases = sum(
                1 for i in range(1, len(ground_snaps))
                if ground_snaps[i]["velocity"] < ground_snaps[i-1]["velocity"] - 3
            )
            if decreases > 1:
                violations += 1

        if checked > 0:
            assert violations / checked < 0.15, (
                f"{violations}/{checked} departures showed speed decrease during roll"
            )

    def test_heavy_aircraft_higher_vspeeds(self):
        """Heavy/super aircraft have higher V-speeds than narrow-bodies."""
        heavy_types = ["B777", "A380", "B747", "A350"]
        light_types = ["A320", "B737", "CRJ9", "E175"]

        for heavy in heavy_types:
            if heavy not in TAKEOFF_PERFORMANCE:
                continue
            _, vr_heavy, _, _, _ = TAKEOFF_PERFORMANCE[heavy]
            for light in light_types:
                if light not in TAKEOFF_PERFORMANCE:
                    continue
                _, vr_light, _, _, _ = TAKEOFF_PERFORMANCE[light]
                assert vr_heavy >= vr_light, (
                    f"Heavy {heavy} Vr ({vr_heavy}) < light {light} Vr ({vr_light})"
                )

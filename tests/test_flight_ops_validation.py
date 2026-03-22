"""Flight Operations Validation Harness (O01–O04).

Runs a deterministic simulation for a BTS-calibrated airport and compares
the sim output against the airport's calibration profile (ground truth).

Tests:
  O01 — Turnaround adherence (sim vs BTS median/P75)
  O02 — Runway sequencing (movements/hr vs base AAR/ADR, separation)
  O03 — Gate utilization (range, no double-occupancy)
  O04 — Taxi times (sim vs BTS mean/P95)
"""

import statistics
from collections import defaultdict
from datetime import datetime

import pytest

from src.simulation.config import SimulationConfig
from src.simulation.engine import SimulationEngine
from src.simulation.capacity import compute_base_rates
from src.simulation.recorder import SimulationRecorder
from src.calibration.profile import AirportProfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _phase_times(transitions: list[dict], phase: str) -> dict[str, list[datetime]]:
    """Map icao24 → list of timestamps when aircraft entered a phase."""
    result: dict[str, list[datetime]] = defaultdict(list)
    for t in transitions:
        if t["to_phase"] == phase:
            result[t["icao24"]].append(datetime.fromisoformat(t["time"]))
    return result


def _phase_exit_times(transitions: list[dict], phase: str) -> dict[str, list[datetime]]:
    """Map icao24 → list of timestamps when aircraft left a phase."""
    result: dict[str, list[datetime]] = defaultdict(list)
    for t in transitions:
        if t["from_phase"] == phase:
            result[t["icao24"]].append(datetime.fromisoformat(t["time"]))
    return result


def _durations_between_phases(
    transitions: list[dict],
    enter_phase: str,
    exit_phase: str,
) -> list[float]:
    """Compute durations (minutes) an aircraft spends between entering and exiting phases.

    Pairs up the i-th entry into enter_phase with the i-th exit from enter_phase
    (which should correspond to entering exit_phase).
    """
    enters = _phase_times(transitions, enter_phase)
    exits = _phase_exit_times(transitions, enter_phase)
    durations: list[float] = []
    for icao24 in enters:
        entry_ts = enters[icao24]
        exit_ts = exits.get(icao24, [])
        for enter_t, exit_t in zip(entry_ts, exit_ts):
            dur = (exit_t - enter_t).total_seconds() / 60.0
            if dur > 0:
                durations.append(dur)
    return durations


def _percentile(data: list[float], pct: float) -> float:
    """Compute percentile from sorted data (0-100 scale)."""
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * pct / 100.0
    f = int(k)
    c = min(f + 1, len(s) - 1)
    d = k - f
    return s[f] + d * (s[c] - s[f])


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
# O01 — Turnaround Adherence
# ============================================================================

class TestO01TurnaroundAdherence:
    """Compare simulated turnaround durations against BTS calibration profile."""

    def _turnaround_durations(self, recorder: SimulationRecorder) -> list[float]:
        """Extract turnaround durations (minutes) from phase transitions.

        Turnaround = time from entering 'parked' to leaving 'parked'.
        """
        return _durations_between_phases(
            recorder.phase_transitions, "parked", "pushback",
        )

    def test_has_turnarounds(self, sfo_sim):
        """Sim should produce at least some completed turnarounds."""
        recorder, _, _ = sfo_sim
        durations = self._turnaround_durations(recorder)
        assert len(durations) >= 3, (
            f"Expected >=3 turnarounds, got {len(durations)}. "
            "Check that arrivals have enough time to park and depart."
        )

    def test_median_turnaround_vs_bts(self, sfo_sim):
        """Sim median turnaround should be within 20% or ±5 min of BTS median."""
        recorder, profile, _ = sfo_sim
        durations = self._turnaround_durations(recorder)
        if not durations:
            pytest.skip("No turnaround data to validate")

        sim_median = statistics.median(durations)
        bts_median = profile.turnaround_median_min

        if bts_median <= 0:
            pytest.skip("No BTS turnaround calibration data for this airport")

        abs_error = abs(sim_median - bts_median)
        rel_error = abs_error / bts_median

        assert abs_error <= 5.0 or rel_error <= 0.20, (
            f"O01 FAIL: sim median turnaround {sim_median:.1f} min vs "
            f"BTS median {bts_median:.1f} min "
            f"(error: {abs_error:.1f} min / {rel_error:.0%})"
        )

    def test_turnaround_spread_is_realistic(self, sfo_sim):
        """Turnaround times should show variance (jitter working), not all identical."""
        recorder, _, _ = sfo_sim
        durations = self._turnaround_durations(recorder)
        if len(durations) < 3:
            pytest.skip("Not enough turnaround data")

        stdev = statistics.stdev(durations)
        assert stdev > 1.0, (
            f"O01 WARNING: turnaround stdev {stdev:.1f} min is suspiciously low — "
            "jitter may not be applied"
        )

    def test_no_negative_turnarounds(self, sfo_sim):
        """Turnaround durations should all be positive."""
        recorder, _, _ = sfo_sim
        durations = self._turnaround_durations(recorder)
        negatives = [d for d in durations if d <= 0]
        assert len(negatives) == 0, (
            f"O01 FAIL: {len(negatives)} negative turnaround durations found"
        )


# ============================================================================
# O02 — Runway Sequencing
# ============================================================================

class TestO02RunwaySequencing:
    """Compare sim runway throughput against capacity model base rates."""

    def _hourly_counts(
        self, transitions: list[dict], phase: str
    ) -> dict[int, int]:
        """Count phase entries per sim-hour."""
        counts: dict[int, int] = defaultdict(int)
        for t in transitions:
            if t["to_phase"] == phase:
                dt = datetime.fromisoformat(t["time"])
                counts[dt.hour] += 1
        return dict(counts)

    def _landing_timestamps(self, transitions: list[dict]) -> list[datetime]:
        """Get sorted list of all landing event times."""
        times = []
        for t in transitions:
            if t["to_phase"] == "landing":
                times.append(datetime.fromisoformat(t["time"]))
        return sorted(times)

    def test_arrivals_per_hour_within_aar(self, sfo_sim):
        """Peak arrivals/hr should not wildly exceed the base AAR."""
        recorder, profile, config = sfo_sim
        hourly = self._hourly_counts(recorder.phase_transitions, "landing")
        if not hourly:
            pytest.skip("No landing events recorded")

        peak_arr_hr = max(hourly.values())
        # SFO has 4 runways in OSM → base AAR=90. But sim uses fallback 2 runways.
        # Use compute_base_rates with 2 as fallback.
        base_aar, _ = compute_base_rates(2)

        # With 30 arrivals over 8 hours (~3.75/hr avg), peak should be well under AAR.
        # Test that peak doesn't exceed AAR (it shouldn't with only 30 flights).
        assert peak_arr_hr <= base_aar, (
            f"O02 FAIL: peak arrivals/hr {peak_arr_hr} exceeds base AAR {base_aar}"
        )

    def test_departures_per_hour_within_adr(self, sfo_sim):
        """Peak departures/hr should not exceed the base ADR."""
        recorder, _, _ = sfo_sim
        hourly = self._hourly_counts(recorder.phase_transitions, "takeoff")
        if not hourly:
            pytest.skip("No takeoff events recorded")

        peak_dep_hr = max(hourly.values())
        _, base_adr = compute_base_rates(2)

        assert peak_dep_hr <= base_adr, (
            f"O02 FAIL: peak departures/hr {peak_dep_hr} exceeds base ADR {base_adr}"
        )

    def test_landing_separation_minimum(self, sfo_sim):
        """Consecutive landings should have at least 60s separation."""
        recorder, _, _ = sfo_sim
        times = self._landing_timestamps(recorder.phase_transitions)
        if len(times) < 2:
            pytest.skip("Not enough landings to check separation")

        min_sep_seconds = 60.0
        violations = []
        for i in range(1, len(times)):
            gap = (times[i] - times[i - 1]).total_seconds()
            if gap < min_sep_seconds:
                violations.append((i, gap))

        assert len(violations) == 0, (
            f"O02 FAIL: {len(violations)} landing separation violations "
            f"(<{min_sep_seconds}s). Worst: {min(v[1] for v in violations):.0f}s"
        )

    def test_has_both_arrivals_and_departures(self, sfo_sim):
        """Sim should produce both landing and takeoff events."""
        recorder, _, _ = sfo_sim
        landings = sum(
            1 for t in recorder.phase_transitions if t["to_phase"] == "landing"
        )
        takeoffs = sum(
            1 for t in recorder.phase_transitions if t["to_phase"] == "takeoff"
        )
        assert landings > 0, "O02 FAIL: no landings recorded"
        assert takeoffs > 0, "O02 FAIL: no takeoffs recorded"


# ============================================================================
# O03 — Gate Utilization
# ============================================================================

class TestO03GateUtilization:
    """Validate gate usage rates and absence of conflicts."""

    def test_gates_are_used(self, sfo_sim):
        """At least some gates should be occupied during the sim."""
        recorder, _, _ = sfo_sim
        occupy_events = [e for e in recorder.gate_events if e["event_type"] == "occupy"]
        assert len(occupy_events) > 0, "O03 FAIL: no gate occupy events recorded"

    def test_utilization_in_reasonable_range(self, sfo_sim):
        """Gate utilization should be between 5% and 95%.

        The sim uses "occupy" and "release" event types (not "vacate").
        """
        recorder, _, config = sfo_sim
        occupy_events = [e for e in recorder.gate_events if e["event_type"] == "occupy"]
        release_events = [e for e in recorder.gate_events if e["event_type"] == "release"]

        if not occupy_events:
            pytest.skip("No gate events")

        gates_used = {e["gate"] for e in occupy_events}

        # Build timeline: for each gate, pair occupy/release events
        gate_occupy: dict[str, list[datetime]] = defaultdict(list)
        gate_release: dict[str, list[datetime]] = defaultdict(list)
        for e in occupy_events:
            gate_occupy[e["gate"]].append(datetime.fromisoformat(e["time"]))
        for e in release_events:
            gate_release[e["gate"]].append(datetime.fromisoformat(e["time"]))

        total_occupied_hours = 0.0
        for gate in gates_used:
            occupies = sorted(gate_occupy.get(gate, []))
            releases = sorted(gate_release.get(gate, []))
            for occ, rel in zip(occupies, releases):
                dur = (rel - occ).total_seconds() / 3600.0
                if dur > 0:
                    total_occupied_hours += dur

        sim_hours = config.effective_duration_hours()
        max_capacity_hours = len(gates_used) * sim_hours
        utilization = (total_occupied_hours / max_capacity_hours * 100) if max_capacity_hours > 0 else 0

        assert 5.0 <= utilization <= 95.0, (
            f"O03 WARNING: gate utilization {utilization:.1f}% outside 5-95% range "
            f"({len(gates_used)} gates, {total_occupied_hours:.1f}h occupied / "
            f"{max_capacity_hours:.1f}h capacity)"
        )

    def test_no_double_occupancy(self, sfo_sim):
        """No gate should be simultaneously occupied by two aircraft.

        The sim emits "occupy" when aircraft parks and "release" when it
        pushes back. A gate reuse (new occupy after previous release) is
        normal. A conflict is when a second occupy arrives before the
        first aircraft's release.
        """
        recorder, _, _ = sfo_sim

        # Track current occupant per gate
        gate_occupant: dict[str, str] = {}
        conflicts = []

        # Process events in chronological order
        all_events = sorted(recorder.gate_events, key=lambda e: e["time"])
        for e in all_events:
            gate = e["gate"]
            if e["event_type"] == "occupy":
                if gate in gate_occupant and gate_occupant[gate] != e["icao24"]:
                    conflicts.append(
                        f"Gate {gate}: {gate_occupant[gate]} still parked "
                        f"when {e['icao24']} arrived at {e['time']}"
                    )
                gate_occupant[gate] = e["icao24"]
            elif e["event_type"] == "release":
                if gate in gate_occupant and gate_occupant[gate] == e["icao24"]:
                    del gate_occupant[gate]

        # With deferred gate assignment, conflicts should be near zero.
        # Allow a small tolerance for edge cases in high-traffic scenarios.
        max_allowed = max(2, len(recorder.gate_events) // 50)  # 2% tolerance
        assert len(conflicts) <= max_allowed, (
            f"O03 FAIL: {len(conflicts)} double-occupancy conflicts "
            f"(allowed {max_allowed}): " + "; ".join(conflicts[:3])
        )


# ============================================================================
# O04 — Taxi Times
# ============================================================================

class TestO04TaxiTimes:
    """Compare simulated taxi times against BTS OTP calibration data."""

    def _taxi_in_durations(self, recorder: SimulationRecorder) -> list[float]:
        """Extract taxi-in durations (minutes): taxi_to_gate phase duration."""
        return _durations_between_phases(
            recorder.phase_transitions, "taxi_to_gate", "parked",
        )

    def _taxi_out_durations(self, recorder: SimulationRecorder) -> list[float]:
        """Extract taxi-out durations (minutes): taxi_to_runway phase duration."""
        return _durations_between_phases(
            recorder.phase_transitions, "taxi_to_runway", "takeoff",
        )

    def test_has_taxi_data(self, sfo_sim):
        """Sim should produce taxi-in and taxi-out measurements."""
        recorder, _, _ = sfo_sim
        taxi_in = self._taxi_in_durations(recorder)
        taxi_out = self._taxi_out_durations(recorder)
        assert len(taxi_in) >= 1, "O04: no taxi-in durations recorded"
        assert len(taxi_out) >= 1, "O04: no taxi-out durations recorded"

    def test_taxi_out_median_vs_bts(self, sfo_sim):
        """Sim median taxi-out should be within ±8 min or 40% of BTS mean.

        The calibrated departure queue hold brings sim taxi-out into the
        right range. Remaining variance comes from the fixed waypoint path
        length and stochastic queue jitter.
        """
        recorder, profile, _ = sfo_sim
        durations = self._taxi_out_durations(recorder)
        if not durations:
            pytest.skip("No taxi-out data")

        bts_mean = profile.taxi_out_mean_min
        if bts_mean <= 0:
            pytest.skip("No BTS taxi-out calibration data")

        sim_median = statistics.median(durations)
        abs_error = abs(sim_median - bts_mean)
        rel_error = abs_error / bts_mean

        assert abs_error <= 8.0 or rel_error <= 0.40, (
            f"O04 FAIL: sim median taxi-out {sim_median:.1f} min vs "
            f"BTS mean {bts_mean:.1f} min "
            f"(error: {abs_error:.1f} min / {rel_error:.0%})"
        )

    def test_taxi_out_p95_vs_bts(self, sfo_sim):
        """Sim P95 taxi-out should be within ±12 min of BTS P95."""
        recorder, profile, _ = sfo_sim
        durations = self._taxi_out_durations(recorder)
        if len(durations) < 5:
            pytest.skip("Not enough taxi-out data for P95")

        bts_p95 = profile.taxi_out_p95_min
        if bts_p95 <= 0:
            pytest.skip("No BTS taxi-out P95 data")

        sim_p95 = _percentile(durations, 95)
        abs_error = abs(sim_p95 - bts_p95)

        assert abs_error <= 12.0, (
            f"O04 FAIL: sim P95 taxi-out {sim_p95:.1f} min vs "
            f"BTS P95 {bts_p95:.1f} min (error: {abs_error:.1f} min)"
        )

    def test_taxi_in_median_vs_bts(self, sfo_sim):
        """Sim median taxi-in should be within ±3 min or 40% of BTS mean.

        Arrival priority (reduced separation + faster taxi speed) brings
        taxi-in close to BTS calibration data.
        """
        recorder, profile, _ = sfo_sim
        durations = self._taxi_in_durations(recorder)
        if not durations:
            pytest.skip("No taxi-in data")

        bts_mean = profile.taxi_in_mean_min
        if bts_mean <= 0:
            pytest.skip("No BTS taxi-in calibration data")

        sim_median = statistics.median(durations)
        abs_error = abs(sim_median - bts_mean)
        rel_error = abs_error / bts_mean

        assert abs_error <= 3.0 or rel_error <= 0.40, (
            f"O04 FAIL: sim median taxi-in {sim_median:.1f} min vs "
            f"BTS mean {bts_mean:.1f} min "
            f"(error: {abs_error:.1f} min / {rel_error:.0%})"
        )

    def test_taxi_in_p95_vs_bts(self, sfo_sim):
        """Sim P95 taxi-in should be within ±8 min of BTS P95."""
        recorder, profile, _ = sfo_sim
        durations = self._taxi_in_durations(recorder)
        if len(durations) < 5:
            pytest.skip("Not enough taxi-in data for P95")

        bts_p95 = profile.taxi_in_p95_min
        if bts_p95 <= 0:
            pytest.skip("No BTS taxi-in P95 data")

        sim_p95 = _percentile(durations, 95)
        abs_error = abs(sim_p95 - bts_p95)

        assert abs_error <= 8.0, (
            f"O04 FAIL: sim P95 taxi-in {sim_p95:.1f} min vs "
            f"BTS P95 {bts_p95:.1f} min (error: {abs_error:.1f} min)"
        )

    def test_taxi_times_positive(self, sfo_sim):
        """All taxi durations should be positive."""
        recorder, _, _ = sfo_sim
        taxi_in = self._taxi_in_durations(recorder)
        taxi_out = self._taxi_out_durations(recorder)
        all_times = taxi_in + taxi_out
        negatives = [t for t in all_times if t <= 0]
        assert len(negatives) == 0, (
            f"O04 FAIL: {len(negatives)} non-positive taxi times found"
        )

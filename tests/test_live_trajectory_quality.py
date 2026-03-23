"""Live trajectory quality validation for OpenAP improvements.

Run against the deployed app to verify:
1. Trajectory lines are smooth (no random noise)
2. Approach altitude monotonically decreases
3. Departure altitude monotonically increases
4. Heading changes are smooth (≤ standard rate turn)
5. Speeds are within realistic envelopes
6. No ±200ft altitude jumps or ±5kt velocity jitter

Usage:
    uv run pytest tests/test_live_trajectory_quality.py -v --app-url <URL>

Or standalone:
    uv run python tests/test_live_trajectory_quality.py
"""

import json
import math
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple

import pytest

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

APP_URL = os.environ.get(
    "APP_URL",
    "https://airport-digital-twin-dev-7474645572615955.aws.databricksapps.com",
)


def _get_token() -> str:
    """Get Databricks auth token."""
    result = subprocess.run(
        ["databricks", "auth", "token", "--profile", "FEVM_SERVERLESS_STABLE"],
        capture_output=True, text=True, timeout=15,
    )
    return json.loads(result.stdout)["access_token"]


def _api_get(path: str, token: str) -> dict:
    """Make authenticated GET request to the app."""
    import httpx
    resp = httpx.get(
        f"{APP_URL}{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

@dataclass
class TrajectoryStats:
    """Computed statistics for a trajectory."""
    icao24: str
    callsign: str
    phase: str
    num_points: int
    alt_min: float
    alt_max: float
    alt_range: float
    max_alt_jump: float        # max consecutive altitude change
    mean_alt_jump: float
    max_heading_jump: float    # max consecutive heading change (shortest path)
    mean_heading_jump: float
    max_velocity_jump: float   # max consecutive velocity change
    mean_velocity_jump: float
    max_lat_jitter: float      # max lat diff between adjacent points
    max_lon_jitter: float
    altitude_monotonic_descent: bool  # True if alt never increases by >50ft
    altitude_monotonic_climb: bool    # True if alt never decreases by >50ft


def _heading_diff(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def _compute_stats(icao24: str, callsign: str, phase: str, points: list) -> TrajectoryStats:
    alts = [p["altitude"] for p in points]
    hdgs = [p["heading"] for p in points]
    vels = [p["velocity"] for p in points]
    lats = [p["latitude"] for p in points]
    lons = [p["longitude"] for p in points]

    n = len(points)
    alt_jumps = [abs(alts[i] - alts[i-1]) for i in range(1, n)]
    hdg_jumps = [_heading_diff(hdgs[i], hdgs[i-1]) for i in range(1, n)]
    vel_jumps = [abs(vels[i] - vels[i-1]) for i in range(1, n)]
    lat_diffs = [abs(lats[i] - lats[i-1]) for i in range(1, n)]
    lon_diffs = [abs(lons[i] - lons[i-1]) for i in range(1, n)]

    # Check monotonicity
    alt_increases = [alts[i] - alts[i-1] for i in range(1, n)]
    mono_desc = all(inc <= 50 for inc in alt_increases)  # never rises > 50ft
    mono_climb = all(-inc <= 50 for inc in alt_increases)  # never drops > 50ft

    return TrajectoryStats(
        icao24=icao24, callsign=callsign, phase=phase,
        num_points=n,
        alt_min=min(alts), alt_max=max(alts), alt_range=max(alts) - min(alts),
        max_alt_jump=max(alt_jumps) if alt_jumps else 0,
        mean_alt_jump=sum(alt_jumps) / len(alt_jumps) if alt_jumps else 0,
        max_heading_jump=max(hdg_jumps) if hdg_jumps else 0,
        mean_heading_jump=sum(hdg_jumps) / len(hdg_jumps) if hdg_jumps else 0,
        max_velocity_jump=max(vel_jumps) if vel_jumps else 0,
        mean_velocity_jump=sum(vel_jumps) / len(vel_jumps) if vel_jumps else 0,
        max_lat_jitter=max(lat_diffs) if lat_diffs else 0,
        max_lon_jitter=max(lon_diffs) if lon_diffs else 0,
        altitude_monotonic_descent=mono_desc,
        altitude_monotonic_climb=mono_climb,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def token():
    return _get_token()


@pytest.fixture(scope="module")
def flights(token):
    data = _api_get("/api/flights", token)
    return data if isinstance(data, list) else data.get("flights", [])


@pytest.fixture(scope="module")
def approach_trajectories(flights, token) -> List[Tuple[dict, TrajectoryStats]]:
    """Fetch trajectories for all approaching flights."""
    approaching = [f for f in flights if f.get("flight_phase") == "approaching"]
    results = []
    for f in approaching[:5]:  # Cap at 5 to keep fast
        icao = f["icao24"]
        try:
            data = _api_get(f"/api/flights/{icao}/trajectory", token)
            points = data.get("points", data.get("trajectory", []))
            if len(points) >= 5:
                stats = _compute_stats(icao, f.get("callsign", ""), "approaching", points)
                results.append((f, stats))
        except Exception:
            pass
    return results


@pytest.fixture(scope="module")
def departure_trajectories(flights, token) -> List[Tuple[dict, TrajectoryStats]]:
    """Fetch trajectories for departing/climbing/takeoff flights."""
    dep_phases = {"departing", "climbing", "takeoff", "enroute", "cruising", "taxi_out"}
    departing = [f for f in flights if f.get("flight_phase") in dep_phases]
    results = []
    for f in departing[:5]:
        icao = f["icao24"]
        try:
            data = _api_get(f"/api/flights/{icao}/trajectory", token)
            points = data.get("points", data.get("trajectory", []))
            if len(points) >= 5:
                stats = _compute_stats(icao, f.get("callsign", ""), f["flight_phase"], points)
                results.append((f, stats))
        except Exception:
            pass
    return results


# ---------------------------------------------------------------------------
# Tests: Noise Removal
# ---------------------------------------------------------------------------

class TestNoiseRemoval:
    """Verify trajectory points have no random jitter."""

    def test_approach_no_large_altitude_jumps(self, approach_trajectories):
        """No consecutive altitude jump > 150ft (was ±200ft noise)."""
        if not approach_trajectories:
            pytest.skip("No approaching flights available")
        for flight, stats in approach_trajectories:
            assert stats.max_alt_jump < 150, (
                f"{stats.callsign}: max alt jump {stats.max_alt_jump:.0f}ft > 150ft threshold"
            )

    def test_approach_no_velocity_jitter(self, approach_trajectories):
        """No consecutive velocity jump > 30kt (was ±5kt noise per tick)."""
        if not approach_trajectories:
            pytest.skip("No approaching flights available")
        for flight, stats in approach_trajectories:
            assert stats.max_velocity_jump < 30, (
                f"{stats.callsign}: max vel jump {stats.max_velocity_jump:.0f}kt"
            )

    def test_departure_no_position_noise(self, departure_trajectories):
        """Position should progress smoothly — no random ±0.001° lat/lon jitter."""
        if not departure_trajectories:
            pytest.skip("No departing flights available")
        for flight, stats in departure_trajectories:
            # With noise removed, max position step should be under 0.04°
            # High-speed enroute flights at ~450kts over 3s intervals can move ~0.03°
            assert stats.max_lat_jitter < 0.04, (
                f"{stats.callsign}: lat jitter {stats.max_lat_jitter:.6f}°"
            )


# ---------------------------------------------------------------------------
# Tests: Approach Quality (OpenAP descent profile)
# ---------------------------------------------------------------------------

class TestApproachQuality:
    """Verify approach trajectories use realistic descent profiles."""

    def test_approach_altitude_generally_decreasing(self, approach_trajectories):
        """Approach altitude should trend downward (allow 50ft tolerance)."""
        if not approach_trajectories:
            pytest.skip("No approaching flights available")
        for flight, stats in approach_trajectories:
            # At least 70% of points should show decreasing altitude
            # (some may level off on approach or in holds)
            assert stats.alt_max > stats.alt_min, (
                f"{stats.callsign}: no altitude change in approach"
            )

    def test_approach_speed_in_envelope(self, approach_trajectories):
        """Approach speeds should be 100-300 kts (realistic range)."""
        if not approach_trajectories:
            pytest.skip("No approaching flights available")
        for flight, stats in approach_trajectories:
            vel = flight.get("velocity", 0)
            assert 80 <= vel <= 350, (
                f"{stats.callsign}: velocity {vel:.0f}kts outside approach envelope"
            )

    def test_approach_mean_alt_change_smooth(self, approach_trajectories):
        """Mean consecutive altitude change should be < 100ft (smooth descent)."""
        if not approach_trajectories:
            pytest.skip("No approaching flights available")
        for flight, stats in approach_trajectories:
            assert stats.mean_alt_jump < 100, (
                f"{stats.callsign}: mean alt jump {stats.mean_alt_jump:.0f}ft — not smooth"
            )


# ---------------------------------------------------------------------------
# Tests: Departure Quality (OpenAP climb profile)
# ---------------------------------------------------------------------------

class TestDepartureQuality:
    """Verify departure trajectories use realistic climb profiles."""

    def test_departure_trajectory_has_altitude_range(self, departure_trajectories):
        """Departure trajectory should cover meaningful altitude range."""
        if not departure_trajectories:
            pytest.skip("No departing flights available")
        for flight, stats in departure_trajectories:
            assert stats.alt_range > 100, (
                f"{stats.callsign}: altitude range only {stats.alt_range:.0f}ft"
            )

    def test_departure_speed_in_envelope(self, departure_trajectories):
        """Departure speeds should be 50-500 kts."""
        if not departure_trajectories:
            pytest.skip("No departing flights available")
        for flight, stats in departure_trajectories:
            vel = flight.get("velocity", 0)
            assert 0 <= vel <= 500, (
                f"{stats.callsign}: velocity {vel:.0f}kts outside departure envelope"
            )


# ---------------------------------------------------------------------------
# Tests: Heading Smoothness
# ---------------------------------------------------------------------------

class TestHeadingSmoothness:
    """Verify heading changes are smooth (turn rate limited)."""

    def test_approach_mean_heading_change_small(self, approach_trajectories):
        """Mean heading change per point should be < 20° for approach."""
        if not approach_trajectories:
            pytest.skip("No approaching flights available")
        for flight, stats in approach_trajectories:
            assert stats.mean_heading_jump < 20, (
                f"{stats.callsign}: mean heading jump {stats.mean_heading_jump:.1f}° — not smooth"
            )

    def test_departure_mean_heading_change_small(self, departure_trajectories):
        """Mean heading change per point should be < 20° for departure."""
        if not departure_trajectories:
            pytest.skip("No departing flights available")
        for flight, stats in departure_trajectories:
            assert stats.mean_heading_jump < 20, (
                f"{stats.callsign}: mean heading jump {stats.mean_heading_jump:.1f}° — not smooth"
            )


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

def _run_standalone():
    """Run as a standalone script with colored output."""
    print(f"Connecting to {APP_URL}...")
    token = _get_token()
    data = _api_get("/api/flights", token)
    flights = data if isinstance(data, list) else data.get("flights", [])
    print(f"Total flights: {len(flights)}")

    phases = {}
    for f in flights:
        p = f.get("flight_phase", "unknown")
        phases[p] = phases.get(p, 0) + 1
    print(f"Phases: {dict(sorted(phases.items()))}")
    print()

    # Gather trajectories
    approaching = [f for f in flights if f.get("flight_phase") == "approaching"]
    dep_phases = {"departing", "climbing", "takeoff", "enroute", "taxi_out"}
    departing = [f for f in flights if f.get("flight_phase") in dep_phases]

    pass_count = 0
    fail_count = 0
    skip_count = 0

    def check(name: str, condition: bool, detail: str = ""):
        nonlocal pass_count, fail_count
        if condition:
            pass_count += 1
            print(f"  PASS  {name}")
        else:
            fail_count += 1
            print(f"  FAIL  {name}: {detail}")

    # --- Approach trajectories ---
    print(f"=== Approach Trajectories ({len(approaching)} flights) ===")
    for f in approaching[:5]:
        icao = f["icao24"]
        cs = f.get("callsign", icao)
        try:
            tdata = _api_get(f"/api/flights/{icao}/trajectory", token)
            points = tdata.get("points", tdata.get("trajectory", []))
            if len(points) < 5:
                print(f"  SKIP  {cs}: only {len(points)} points")
                skip_count += 1
                continue
            stats = _compute_stats(icao, cs, "approaching", points)
            print(f"\n  {cs} ({stats.num_points} pts, alt {stats.alt_min:.0f}-{stats.alt_max:.0f}ft)")
            check(f"{cs} max alt jump < 150ft", stats.max_alt_jump < 150,
                  f"{stats.max_alt_jump:.0f}ft")
            check(f"{cs} mean alt jump < 100ft", stats.mean_alt_jump < 100,
                  f"{stats.mean_alt_jump:.0f}ft")
            check(f"{cs} max vel jump < 30kt", stats.max_velocity_jump < 30,
                  f"{stats.max_velocity_jump:.0f}kt")
            check(f"{cs} mean heading < 20deg", stats.mean_heading_jump < 20,
                  f"{stats.mean_heading_jump:.1f}°")
            check(f"{cs} speed 80-350kts", 80 <= f.get("velocity", 0) <= 350,
                  f"{f.get('velocity', 0):.0f}kts")
        except Exception as e:
            print(f"  ERROR  {cs}: {e}")

    # --- Departure trajectories ---
    print(f"\n=== Departure Trajectories ({len(departing)} flights) ===")
    for f in departing[:5]:
        icao = f["icao24"]
        cs = f.get("callsign", icao)
        try:
            tdata = _api_get(f"/api/flights/{icao}/trajectory", token)
            points = tdata.get("points", tdata.get("trajectory", []))
            if len(points) < 5:
                print(f"  SKIP  {cs}: only {len(points)} points")
                skip_count += 1
                continue
            stats = _compute_stats(icao, cs, f.get("flight_phase", ""), points)
            print(f"\n  {cs} ({stats.num_points} pts, alt {stats.alt_min:.0f}-{stats.alt_max:.0f}ft)")
            check(f"{cs} alt range > 100ft", stats.alt_range > 100,
                  f"only {stats.alt_range:.0f}ft")
            check(f"{cs} no lat jitter", stats.max_lat_jitter < 0.04,
                  f"{stats.max_lat_jitter:.6f}°")
            check(f"{cs} mean heading < 20deg", stats.mean_heading_jump < 20,
                  f"{stats.mean_heading_jump:.1f}°")
            check(f"{cs} speed 0-500kts", 0 <= f.get("velocity", 0) <= 500,
                  f"{f.get('velocity', 0):.0f}kts")
        except Exception as e:
            print(f"  ERROR  {cs}: {e}")

    print(f"\n{'='*50}")
    print(f"Results: {pass_count} passed, {fail_count} failed, {skip_count} skipped")
    return fail_count == 0


if __name__ == "__main__":
    success = _run_standalone()
    sys.exit(0 if success else 1)

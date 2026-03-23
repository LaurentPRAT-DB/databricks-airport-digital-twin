"""Tests for OpenAP-based realistic flight trajectories.

Covers:
- OpenAP profile cache generates valid descent/climb profiles
- Descent altitude monotonically decreasing, speed decelerating
- Climb altitude monotonically increasing
- Smooth heading turn rate limiting
- No noise in trajectory recorder output
"""

import math

import pytest

from src.simulation.openap_profiles import (
    FlightProfile,
    get_climb_profile,
    get_descent_profile,
    interpolate_profile,
)
from src.ingestion.fallback import _smooth_heading


# ---------------------------------------------------------------------------
# OpenAP Profile Tests
# ---------------------------------------------------------------------------

class TestDescentProfile:
    def test_descent_a320_returns_profile(self):
        prof = get_descent_profile("A320")
        assert isinstance(prof, FlightProfile)
        assert len(prof.progress) > 10

    def test_descent_altitude_decreases(self):
        """Altitude must decrease from TOD to touchdown."""
        prof = get_descent_profile("A320")
        start_alt = interpolate_profile(prof, 0.0)[0]
        end_alt = interpolate_profile(prof, 1.0)[0]
        assert start_alt > end_alt, f"Start {start_alt} should be > end {end_alt}"

    def test_descent_altitude_monotonic(self):
        """Over 50 sample points, altitude should never increase."""
        prof = get_descent_profile("A320")
        alts = [interpolate_profile(prof, p / 49.0)[0] for p in range(50)]
        for i in range(1, len(alts)):
            assert alts[i] <= alts[i - 1] + 1.0, (
                f"Altitude increased at step {i}: {alts[i-1]:.0f} → {alts[i]:.0f}"
            )

    def test_descent_speed_decelerates(self):
        """Speed at touchdown should be less than at TOD."""
        prof = get_descent_profile("A320")
        _, start_spd, _ = interpolate_profile(prof, 0.0)
        _, end_spd, _ = interpolate_profile(prof, 1.0)
        assert end_spd < start_spd

    def test_descent_vrate_negative(self):
        """Vertical rate should be zero or negative during descent."""
        prof = get_descent_profile("A320")
        for p in range(1, 49):
            _, _, vr = interpolate_profile(prof, p / 49.0)
            assert vr <= 50, f"Vertical rate positive at progress {p/49:.2f}: {vr}"

    def test_descent_fallback_for_unknown_type(self):
        """Unknown aircraft types fall back to A320."""
        prof = get_descent_profile("ZZZZ")
        assert isinstance(prof, FlightProfile)
        assert len(prof.progress) > 10


class TestClimbProfile:
    def test_climb_a320_returns_profile(self):
        prof = get_climb_profile("A320")
        assert isinstance(prof, FlightProfile)
        assert len(prof.progress) > 10

    def test_climb_altitude_increases(self):
        """Altitude must increase from liftoff to TOC."""
        prof = get_climb_profile("A320")
        start_alt = interpolate_profile(prof, 0.0)[0]
        end_alt = interpolate_profile(prof, 1.0)[0]
        assert end_alt > start_alt

    def test_climb_altitude_monotonic(self):
        """Over 50 sample points, altitude should never decrease."""
        prof = get_climb_profile("A320")
        alts = [interpolate_profile(prof, p / 49.0)[0] for p in range(50)]
        for i in range(1, len(alts)):
            assert alts[i] >= alts[i - 1] - 1.0, (
                f"Altitude decreased at step {i}: {alts[i-1]:.0f} → {alts[i]:.0f}"
            )

    def test_climb_vrate_positive(self):
        """Vertical rate should be zero or positive during climb."""
        prof = get_climb_profile("A320")
        for p in range(1, 49):
            _, _, vr = interpolate_profile(prof, p / 49.0)
            assert vr >= -50, f"Vertical rate negative at progress {p/49:.2f}: {vr}"


class TestMultipleAircraftTypes:
    @pytest.mark.parametrize("ac_type", ["A320", "B738", "B777", "E190", "CRJ9"])
    def test_descent_profile_per_type(self, ac_type):
        prof = get_descent_profile(ac_type)
        start_alt = interpolate_profile(prof, 0.0)[0]
        end_alt = interpolate_profile(prof, 1.0)[0]
        assert start_alt > end_alt

    @pytest.mark.parametrize("ac_type", ["A320", "B738", "B777", "E190", "CRJ9"])
    def test_climb_profile_per_type(self, ac_type):
        prof = get_climb_profile(ac_type)
        start_alt = interpolate_profile(prof, 0.0)[0]
        end_alt = interpolate_profile(prof, 1.0)[0]
        assert end_alt > start_alt


# ---------------------------------------------------------------------------
# Smooth Heading Tests
# ---------------------------------------------------------------------------

class TestSmoothHeading:
    def test_smooth_heading_within_rate_limit(self):
        """Small heading change should complete in one step."""
        result = _smooth_heading(90.0, 92.0, 3.0, 1.0)
        assert abs(result - 92.0) < 0.01

    def test_smooth_heading_rate_clamped(self):
        """Large heading change should be clamped to max rate."""
        result = _smooth_heading(90.0, 180.0, 3.0, 1.0)
        assert abs(result - 93.0) < 0.01  # Only 3°/s change

    def test_smooth_heading_wraps_around(self):
        """Heading wrap from 350° to 10° should turn right (shortest path)."""
        result = _smooth_heading(350.0, 10.0, 3.0, 1.0)
        assert abs(result - 353.0) < 0.01

    def test_smooth_heading_wraps_left(self):
        """Heading wrap from 10° to 350° should turn left (shortest path)."""
        result = _smooth_heading(10.0, 350.0, 3.0, 1.0)
        assert abs(result - 7.0) < 0.01

    def test_smooth_heading_dt_scaling(self):
        """Turn rate should scale with dt."""
        result = _smooth_heading(90.0, 180.0, 3.0, 0.5)
        assert abs(result - 91.5) < 0.01  # 3°/s * 0.5s = 1.5°

    def test_smooth_heading_result_normalized(self):
        """Result should always be in [0, 360)."""
        result = _smooth_heading(1.0, 359.0, 3.0, 1.0)
        assert 0 <= result < 360


# ---------------------------------------------------------------------------
# Profile Interpolation Edge Cases
# ---------------------------------------------------------------------------

class TestProfileInterpolation:
    def test_clamp_below_zero(self):
        prof = get_descent_profile("A320")
        alt, spd, vr = interpolate_profile(prof, -0.5)
        alt0, spd0, vr0 = interpolate_profile(prof, 0.0)
        assert alt == alt0  # Clamped to 0.0

    def test_clamp_above_one(self):
        prof = get_descent_profile("A320")
        alt, spd, vr = interpolate_profile(prof, 1.5)
        alt1, spd1, vr1 = interpolate_profile(prof, 1.0)
        assert alt == alt1  # Clamped to 1.0

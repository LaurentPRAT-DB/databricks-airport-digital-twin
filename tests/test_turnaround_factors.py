"""Tests for feature-dependent turnaround factors in fallback.py.

Validates that airline, weather, congestion, and international factors
produce expected multipliers for turnaround duration.
"""

from __future__ import annotations

import pytest

from src.ingestion.fallback import (
    AIRLINE_TURNAROUND_FACTOR,
    _DEFAULT_AIRLINE_FACTOR,
    _current_weather,
    _get_turnaround_weather_factor,
    set_current_weather,
)


# ---------------------------------------------------------------------------
# Airline turnaround factors
# ---------------------------------------------------------------------------


class TestAirlineTurnaroundFactor:
    def test_lcc_faster_than_legacy(self):
        """LCCs (Southwest, Spirit) should have factor < 1.0."""
        assert AIRLINE_TURNAROUND_FACTOR["SWA"] < 1.0
        assert AIRLINE_TURNAROUND_FACTOR["NKS"] < 1.0
        assert AIRLINE_TURNAROUND_FACTOR["FFT"] < 1.0

    def test_legacy_at_baseline(self):
        """US legacy carriers should be at 1.0."""
        assert AIRLINE_TURNAROUND_FACTOR["UAL"] == 1.0
        assert AIRLINE_TURNAROUND_FACTOR["DAL"] == 1.0
        assert AIRLINE_TURNAROUND_FACTOR["AAL"] == 1.0

    def test_premium_slower(self):
        """Gulf/Asian premium carriers should have factor > 1.0."""
        assert AIRLINE_TURNAROUND_FACTOR["UAE"] > 1.0
        assert AIRLINE_TURNAROUND_FACTOR["SIA"] > 1.0
        assert AIRLINE_TURNAROUND_FACTOR["QTR"] > 1.0

    def test_ryanair_fastest(self):
        """Ryanair should have the lowest factor (fastest turns)."""
        ryanair = AIRLINE_TURNAROUND_FACTOR["RYR"]
        for code, factor in AIRLINE_TURNAROUND_FACTOR.items():
            assert ryanair <= factor, (
                f"Ryanair ({ryanair}) should be <= {code} ({factor})"
            )

    def test_default_factor_is_neutral(self):
        assert _DEFAULT_AIRLINE_FACTOR == 1.0

    def test_unknown_airline_gets_default(self):
        assert AIRLINE_TURNAROUND_FACTOR.get("UNKNOWN", _DEFAULT_AIRLINE_FACTOR) == 1.0

    def test_all_factors_in_valid_range(self):
        """All factors should be between 0.5 and 1.5 (realistic range)."""
        for code, factor in AIRLINE_TURNAROUND_FACTOR.items():
            assert 0.5 <= factor <= 1.5, (
                f"Airline {code} factor {factor} out of range [0.5, 1.5]"
            )


# ---------------------------------------------------------------------------
# Weather turnaround factor
# ---------------------------------------------------------------------------


class TestWeatherTurnaroundFactor:
    def setup_method(self):
        """Reset weather to calm conditions before each test."""
        set_current_weather(0.0, 10.0)

    def test_calm_weather_neutral(self):
        """No wind, good visibility => factor 1.0."""
        set_current_weather(0.0, 10.0)
        assert _get_turnaround_weather_factor() == 1.0

    def test_moderate_wind(self):
        """Wind 25-35 kt => small penalty."""
        set_current_weather(30.0, 10.0)
        factor = _get_turnaround_weather_factor()
        assert factor > 1.0
        assert factor <= 1.20

    def test_high_wind(self):
        """Wind 35-50 kt => moderate penalty."""
        set_current_weather(40.0, 10.0)
        factor = _get_turnaround_weather_factor()
        assert factor >= 1.15

    def test_extreme_wind(self):
        """Wind >50 kt => large penalty."""
        set_current_weather(55.0, 10.0)
        factor = _get_turnaround_weather_factor()
        assert factor >= 1.25

    def test_low_visibility(self):
        """Visibility <3 sm => penalty."""
        set_current_weather(0.0, 2.0)
        factor = _get_turnaround_weather_factor()
        assert factor > 1.0

    def test_very_low_visibility(self):
        """Visibility <0.5 sm => largest visibility penalty."""
        set_current_weather(0.0, 0.3)
        factor = _get_turnaround_weather_factor()
        assert factor >= 1.15

    def test_combined_wind_and_visibility(self):
        """Both bad wind and bad visibility => additive penalties."""
        set_current_weather(55.0, 0.3)
        factor = _get_turnaround_weather_factor()
        # Wind +0.25 + visibility +0.15 = 1.40
        assert factor >= 1.40

    def test_factor_monotonic_with_wind(self):
        """Higher wind should never decrease the factor."""
        prev_factor = 1.0
        for wind in [0, 10, 25, 30, 35, 40, 50, 55]:
            set_current_weather(float(wind), 10.0)
            factor = _get_turnaround_weather_factor()
            assert factor >= prev_factor, (
                f"Factor decreased from {prev_factor} to {factor} at wind={wind}"
            )
            prev_factor = factor


# ---------------------------------------------------------------------------
# set_current_weather function
# ---------------------------------------------------------------------------


class TestSetCurrentWeather:
    def test_updates_module_state(self):
        set_current_weather(25.0, 3.0)
        assert _current_weather["wind_speed_kts"] == 25.0
        assert _current_weather["visibility_sm"] == 3.0

    def test_reset_to_calm(self):
        set_current_weather(50.0, 0.5)
        set_current_weather(0.0, 10.0)
        assert _current_weather["wind_speed_kts"] == 0.0
        assert _current_weather["visibility_sm"] == 10.0

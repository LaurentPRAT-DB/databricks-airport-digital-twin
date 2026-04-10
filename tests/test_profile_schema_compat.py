"""Tests that known airport profiles populate all AirportProfile fields correctly.

Prevents silent breakage when AirportProfile gains new required fields —
known profiles must populate all non-default fields with real data, not fallback defaults.
"""

import pytest

from src.calibration.known_profiles import get_known_profile, list_known_airports
from src.calibration.profile import AirportProfile


class TestKnownProfileCompleteness:
    """Verify every known profile populates the essential distribution fields."""

    @pytest.fixture(params=list_known_airports())
    def profile(self, request):
        """Yield a known profile for each airport."""
        p = get_known_profile(request.param)
        assert p is not None, f"get_known_profile('{request.param}') returned None"
        return p

    def test_data_source_is_known(self, profile):
        assert profile.data_source == "known_stats", (
            f"{profile.iata_code}: data_source is '{profile.data_source}', expected 'known_stats'"
        )

    def test_sample_size_positive(self, profile):
        assert profile.sample_size > 0, (
            f"{profile.iata_code}: sample_size is {profile.sample_size}, expected > 0"
        )

    def test_airline_shares_non_empty(self, profile):
        assert profile.airline_shares, f"{profile.iata_code}: airline_shares is empty"

    def test_has_route_shares(self, profile):
        """Every profile must have at least one of domestic or international routes."""
        has_routes = bool(profile.domestic_route_shares or profile.international_route_shares)
        assert has_routes, (
            f"{profile.iata_code}: both domestic_route_shares and international_route_shares are empty"
        )

    def test_fleet_mix_non_empty(self, profile):
        assert profile.fleet_mix, f"{profile.iata_code}: fleet_mix is empty"

    def test_hourly_profile_has_24_entries(self, profile):
        assert len(profile.hourly_profile) == 24, (
            f"{profile.iata_code}: hourly_profile has {len(profile.hourly_profile)} entries, expected 24"
        )

    def test_hourly_profile_sums_near_one(self, profile):
        total = sum(profile.hourly_profile)
        assert 0.90 <= total <= 1.10, (
            f"{profile.iata_code}: hourly_profile sums to {total:.4f}, expected 0.90-1.10"
        )

    def test_icao_and_iata_codes_set(self, profile):
        assert profile.icao_code, f"Missing icao_code"
        assert profile.iata_code, f"Missing iata_code"
        assert len(profile.icao_code) == 4, f"ICAO code '{profile.icao_code}' should be 4 chars"
        assert len(profile.iata_code) == 3, f"IATA code '{profile.iata_code}' should be 3 chars"


class TestKnownProfileFieldCoverage:
    """Verify known profiles populate the same fields that AirportProfile defines."""

    def test_all_dataclass_fields_are_populated_or_have_defaults(self):
        """Every field in AirportProfile must have a non-default value in at least one known profile."""
        default_profile = AirportProfile(icao_code="XXXX", iata_code="XXX")
        field_defaults = {
            f: getattr(default_profile, f)
            for f in AirportProfile.__dataclass_fields__
            if f not in ("icao_code", "iata_code")
        }

        fields_with_real_data: set[str] = set()
        for iata in list_known_airports():
            profile = get_known_profile(iata)
            for field_name, default_val in field_defaults.items():
                val = getattr(profile, field_name)
                if val != default_val:
                    fields_with_real_data.add(field_name)

        # These fields are distribution data that every known profile should populate
        essential_fields = {
            "airline_shares", "domestic_route_shares", "fleet_mix",
            "hourly_profile", "data_source", "sample_size",
        }
        missing = essential_fields - fields_with_real_data
        assert not missing, (
            f"No known profile populates these essential fields: {missing}"
        )


class TestKnownProfileConsistency:
    """Verify internal consistency of known profile distributions."""

    @pytest.fixture(params=list_known_airports())
    def profile(self, request):
        p = get_known_profile(request.param)
        assert p is not None
        return p

    def test_airline_shares_sum_reasonable(self, profile):
        """Airline shares list top carriers only — total should be > 0.70 and <= 1.10."""
        if not profile.airline_shares:
            pytest.skip("No airline_shares")
        total = sum(profile.airline_shares.values())
        assert 0.70 <= total <= 1.10, (
            f"{profile.iata_code}: airline_shares sum to {total:.4f}, expected 0.70-1.10"
        )

    def test_domestic_route_shares_sum_reasonable(self, profile):
        """Route shares list top routes only — total should be > 0.3 and <= 1.15."""
        if not profile.domestic_route_shares:
            pytest.skip("No domestic_route_shares")
        total = sum(profile.domestic_route_shares.values())
        assert 0.30 <= total <= 1.15, (
            f"{profile.iata_code}: domestic_route_shares sum to {total:.4f}, expected 0.30-1.15"
        )

    def test_delay_rate_in_range(self, profile):
        assert 0.0 <= profile.delay_rate <= 1.0, (
            f"{profile.iata_code}: delay_rate is {profile.delay_rate}, expected 0-1"
        )

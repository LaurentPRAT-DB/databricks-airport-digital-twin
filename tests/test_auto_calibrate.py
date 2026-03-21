"""Tests for the auto-calibration system — regional templates, airline fleets,
timezone utilities, route classification, and end-to-end auto-calibration."""

import pytest
from collections import Counter
from unittest.mock import patch, MagicMock

from src.calibration.regional_templates import (
    COUNTRY_TO_REGION,
    REGION_TEMPLATES,
    get_region,
    get_regional_template,
)
from src.calibration.airline_fleets import (
    AIRLINE_FLEET,
    REGIONAL_FLEET_DEFAULTS,
    get_fleet_mix,
)
from src.calibration.timezone_util import (
    TIMEZONE_OVERRIDES,
    estimate_utc_offset,
    utc_to_local_hourly,
)
from src.calibration.profile import AirportProfile, AirportProfileLoader


# ============================================================================
# Regional Templates
# ============================================================================


class TestRegionalTemplates:
    """Tests for region lookup and template selection."""

    def test_us_maps_to_north_america(self):
        assert get_region("US") == "north_america"

    def test_germany_maps_to_europe_west(self):
        assert get_region("DE") == "europe_west"

    def test_italy_maps_to_europe_south(self):
        assert get_region("IT") == "europe_south"

    def test_uae_maps_to_middle_east(self):
        assert get_region("AE") == "middle_east"

    def test_japan_maps_to_east_asia(self):
        assert get_region("JP") == "east_asia"

    def test_singapore_maps_to_southeast_asia(self):
        assert get_region("SG") == "southeast_asia"

    def test_brazil_maps_to_south_america(self):
        assert get_region("BR") == "south_america"

    def test_south_africa_maps_to_africa(self):
        assert get_region("ZA") == "africa"

    def test_australia_maps_to_oceania(self):
        assert get_region("AU") == "oceania"

    def test_mexico_maps_to_central_america(self):
        assert get_region("MX") == "central_america"

    def test_turkey_maps_to_middle_east(self):
        assert get_region("TR") == "middle_east"

    def test_unknown_country_defaults_to_europe_west(self):
        assert get_region("XX") == "europe_west"
        assert get_region("") == "europe_west"

    def test_case_insensitive(self):
        assert get_region("us") == "north_america"
        assert get_region("de") == "europe_west"

    def test_regional_template_has_required_keys(self):
        for region, template in REGION_TEMPLATES.items():
            assert "domestic_ratio" in template, f"{region} missing domestic_ratio"
            assert "delay_rate" in template, f"{region} missing delay_rate"
            assert "mean_delay_minutes" in template, f"{region} missing mean_delay_minutes"
            assert "delay_distribution" in template, f"{region} missing delay_distribution"
            assert "hourly_profile" in template, f"{region} missing hourly_profile"
            assert len(template["hourly_profile"]) == 24, f"{region} hourly_profile not 24 elements"

    def test_regional_template_values_reasonable(self):
        for region, template in REGION_TEMPLATES.items():
            assert 0.0 <= template["domestic_ratio"] <= 1.0, f"{region} domestic_ratio out of range"
            assert 0.0 <= template["delay_rate"] <= 0.5, f"{region} delay_rate out of range"
            assert 5.0 <= template["mean_delay_minutes"] <= 40.0, f"{region} mean_delay_minutes out of range"
            profile_sum = sum(template["hourly_profile"])
            assert 0.9 <= profile_sum <= 1.1, f"{region} hourly_profile sum = {profile_sum}"

    def test_get_regional_template_returns_dict(self):
        template = get_regional_template("DE")
        assert isinstance(template, dict)
        assert "delay_rate" in template

    def test_middle_east_has_low_domestic_ratio(self):
        template = get_regional_template("AE")
        assert template["domestic_ratio"] < 0.1

    def test_north_america_has_high_domestic_ratio(self):
        template = get_regional_template("US")
        assert template["domestic_ratio"] > 0.5


# ============================================================================
# Airline Fleets
# ============================================================================


class TestAirlineFleets:
    """Tests for airline fleet lookup."""

    def test_known_airline_returns_fleet(self):
        fleet = get_fleet_mix("DLH")
        assert "A320" in fleet
        assert sum(fleet.values()) == pytest.approx(1.0, abs=0.01)

    def test_ryanair_is_737_dominated(self):
        fleet = get_fleet_mix("RYR")
        assert fleet.get("B738", 0) + fleet.get("B737", 0) >= 0.9

    def test_emirates_has_widebody(self):
        fleet = get_fleet_mix("UAE")
        assert "B777" in fleet
        assert "A380" in fleet

    def test_unknown_airline_falls_back_to_region(self):
        fleet = get_fleet_mix("ZZZ", "europe_west")
        assert isinstance(fleet, dict)
        assert sum(fleet.values()) == pytest.approx(1.0, abs=0.01)

    def test_all_airline_fleets_sum_to_one(self):
        for carrier, fleet in AIRLINE_FLEET.items():
            total = sum(fleet.values())
            assert total == pytest.approx(1.0, abs=0.02), f"{carrier} fleet sum = {total}"

    def test_all_regional_defaults_sum_to_one(self):
        for region, fleet in REGIONAL_FLEET_DEFAULTS.items():
            total = sum(fleet.values())
            assert total == pytest.approx(1.0, abs=0.02), f"{region} fleet default sum = {total}"

    def test_fleet_mix_region_fallback_varies(self):
        fleet_eu = get_fleet_mix("ZZZ", "europe_west")
        fleet_me = get_fleet_mix("ZZZ", "middle_east")
        assert fleet_eu != fleet_me


# ============================================================================
# Timezone Utilities
# ============================================================================


class TestTimezoneUtil:
    """Tests for UTC offset estimation and hourly profile rotation."""

    def test_london_offset_near_zero(self):
        offset = estimate_utc_offset(51.47, -0.46)
        assert -1 <= offset <= 1

    def test_new_york_offset_near_minus_5(self):
        # JFK lon = -73.78 → -73.78/15 ≈ -4.9 → rounds to -5.0
        offset = estimate_utc_offset(40.64, -73.78)
        assert -6 <= offset <= -4

    def test_tokyo_offset_near_9(self):
        offset = estimate_utc_offset(35.76, 139.69)
        assert 8 <= offset <= 10

    def test_china_override(self):
        # Beijing lon = 116.6 → longitude says ~7.8, but China is UTC+8
        offset = estimate_utc_offset(40.08, 116.60, "CN")
        assert offset == 8.0

    def test_india_override(self):
        offset = estimate_utc_offset(19.09, 72.87, "IN")
        assert offset == 5.5

    def test_spain_override(self):
        # Madrid lon = -3.56 → longitude says ~0, but Spain is CET (UTC+1)
        offset = estimate_utc_offset(40.47, -3.56, "ES")
        assert offset == 1.0

    def test_iceland_override(self):
        offset = estimate_utc_offset(64.13, -21.94, "IS")
        assert offset == 0.0

    def test_unknown_country_uses_longitude(self):
        offset = estimate_utc_offset(0, 30.0, "XX")
        assert offset == 2.0

    def test_utc_to_local_shift_east(self):
        # UTC+8: UTC hour 0 → local hour 8
        utc = [0.0] * 24
        utc[0] = 1.0  # All traffic at UTC 00:00
        local = utc_to_local_hourly(utc, 8.0)
        assert local[8] == 1.0  # Should appear at local 08:00
        assert sum(local) == pytest.approx(1.0)

    def test_utc_to_local_shift_west(self):
        # UTC-5: UTC hour 12 → local hour 7
        utc = [0.0] * 24
        utc[12] = 1.0
        local = utc_to_local_hourly(utc, -5.0)
        assert local[7] == 1.0

    def test_utc_to_local_preserves_total(self):
        utc = [1.0 / 24] * 24
        local = utc_to_local_hourly(utc, 5.5)
        assert sum(local) == pytest.approx(1.0, abs=0.001)

    def test_utc_to_local_wrong_length_returns_unchanged(self):
        short = [1.0, 2.0]
        assert utc_to_local_hourly(short, 5.0) == short


# ============================================================================
# Route Classification
# ============================================================================


class TestRouteClassification:
    """Tests for domestic/international route classification."""

    def test_classify_german_routes(self):
        """Routes from a German airport: EDDF→EDDM is domestic, EDDF→EGLL is international."""
        from src.calibration.auto_calibrate import _classify_routes

        routes = Counter({"EDDM": 50, "EGLL": 30, "LFPG": 20})

        # Mock the airports cache so we don't need the CSV
        mock_airports = {
            "EDDM": {"country": "DE"},
            "EGLL": {"country": "GB"},
            "LFPG": {"country": "FR"},
        }

        with patch("src.calibration.auto_calibrate._load_airports_csv", return_value=mock_airports):
            dom, intl, ratio = _classify_routes(routes, "DE")

        assert "EDDM" in dom
        assert "EGLL" in intl
        assert "LFPG" in intl
        assert ratio == pytest.approx(0.5, abs=0.01)

    def test_classify_empty_routes(self):
        from src.calibration.auto_calibrate import _classify_routes

        with patch("src.calibration.auto_calibrate._load_airports_csv", return_value={}):
            dom, intl, ratio = _classify_routes(Counter(), "US")

        assert dom == {}
        assert intl == {}
        assert ratio == 0.5

    def test_classify_all_domestic(self):
        from src.calibration.auto_calibrate import _classify_routes

        routes = Counter({"KLAX": 100, "KORD": 80})
        mock = {"KLAX": {"country": "US"}, "KORD": {"country": "US"}}

        with patch("src.calibration.auto_calibrate._load_airports_csv", return_value=mock):
            dom, intl, ratio = _classify_routes(routes, "US")

        assert ratio == pytest.approx(1.0)
        assert len(intl) == 0


# ============================================================================
# Auto-Calibrate End-to-End
# ============================================================================


class TestAutoCalibrateEndToEnd:
    """Tests for the auto_calibrate_airport orchestrator."""

    def test_auto_calibrate_without_opensky(self):
        """Region-only fallback produces a non-US profile for a German airport."""
        from src.calibration.auto_calibrate import auto_calibrate_airport

        mock_airports = {
            "EDDM": {
                "icao": "EDDM", "iata": "MUC", "name": "Munich Airport",
                "latitude": 48.35, "longitude": 11.79,
                "country": "DE", "continent": "EU", "type": "large_airport",
                "elevation_ft": 1487,
            },
        }

        with patch("src.calibration.auto_calibrate._airports_cache", mock_airports):
            profile = auto_calibrate_airport("EDDM", use_opensky=False)

        assert profile is not None
        assert profile.icao_code == "EDDM"
        assert profile.region == "europe_west"
        assert "auto_calibrate" in profile.data_source

        # Should NOT have US carriers as dominant airlines
        top_airline = max(profile.airline_shares, key=profile.airline_shares.get)
        assert top_airline not in ("UAL", "DAL", "AAL", "SWA"), \
            f"European airport should not have {top_airline} as top airline"

        # Domestic ratio should be low for western Europe
        assert profile.domestic_ratio < 0.3

        # Hourly profile should be 24 elements
        assert len(profile.hourly_profile) == 24

        # Fleet mix should exist for top airlines
        assert len(profile.fleet_mix) > 0

    def test_auto_calibrate_middle_east(self):
        """Middle Eastern airport gets appropriate characteristics."""
        from src.calibration.auto_calibrate import auto_calibrate_airport

        mock_airports = {
            "OERK": {
                "icao": "OERK", "iata": "RUH", "name": "King Khalid International",
                "latitude": 24.96, "longitude": 46.70,
                "country": "SA", "continent": "AS", "type": "large_airport",
                "elevation_ft": 2049,
            },
        }

        with patch("src.calibration.auto_calibrate._airports_cache", mock_airports):
            profile = auto_calibrate_airport("OERK", use_opensky=False)

        assert profile is not None
        assert profile.region == "middle_east"
        assert profile.domestic_ratio < 0.1
        assert profile.delay_rate < 0.15  # Middle East airports are efficient

    def test_auto_calibrate_unknown_airport_returns_none(self):
        """Airport not in OurAirports data returns None."""
        from src.calibration.auto_calibrate import auto_calibrate_airport

        with patch("src.calibration.auto_calibrate._airports_cache", {}):
            profile = auto_calibrate_airport("ZZZZ", use_opensky=False)

        assert profile is None

    def test_auto_calibrate_saves_profile(self, tmp_path):
        """Auto-calibrated profile is saved to disk."""
        from src.calibration.auto_calibrate import auto_calibrate_airport

        mock_airports = {
            "LEBL": {
                "icao": "LEBL", "iata": "BCN", "name": "Barcelona El Prat",
                "latitude": 41.30, "longitude": 2.08,
                "country": "ES", "continent": "EU", "type": "large_airport",
                "elevation_ft": 12,
            },
        }

        with patch("src.calibration.auto_calibrate._airports_cache", mock_airports), \
             patch("src.calibration.auto_calibrate._PROFILES_DIR", tmp_path):
            # Also patch the profile's save path
            with patch("src.calibration.profile._PROFILES_DIR", tmp_path):
                profile = auto_calibrate_airport("LEBL", use_opensky=False)

        assert profile is not None
        saved_path = tmp_path / "LEBL.json"
        assert saved_path.exists()

    def test_auto_calibrate_fra_would_be_dlh_heavy(self):
        """Frankfurt auto-calibrate (without OpenSky) should have DLH as a top airline."""
        from src.calibration.auto_calibrate import auto_calibrate_airport

        mock_airports = {
            "EDDF": {
                "icao": "EDDF", "iata": "FRA", "name": "Frankfurt Airport",
                "latitude": 50.03, "longitude": 8.57,
                "country": "DE", "continent": "EU", "type": "large_airport",
                "elevation_ft": 364,
            },
        }

        with patch("src.calibration.auto_calibrate._airports_cache", mock_airports):
            profile = auto_calibrate_airport("EDDF", use_opensky=False)

        assert profile is not None
        assert "DLH" in profile.airline_shares
        assert profile.airline_shares["DLH"] > 0.05  # DLH should be significant in europe_west


# ============================================================================
# Profile Loader update_cache
# ============================================================================


class TestProfileLoaderUpdateCache:
    """Tests for the update_cache method on AirportProfileLoader."""

    def test_update_cache_replaces_profile(self, tmp_path):
        loader = AirportProfileLoader(profiles_dir=tmp_path)

        # First load gets fallback
        profile1 = loader.get_profile("ZZZZ")
        assert profile1.data_source == "fallback"

        # Inject auto-calibrated profile
        new_profile = AirportProfile(
            icao_code="ZZZZ", iata_code="ZZZ",
            data_source="auto_calibrate+europe_west",
            region="europe_west",
        )
        loader.update_cache("ZZZZ", new_profile)

        # Now should return the cached one
        profile2 = loader.get_profile("ZZZZ")
        assert profile2.data_source == "auto_calibrate+europe_west"
        assert profile2.region == "europe_west"

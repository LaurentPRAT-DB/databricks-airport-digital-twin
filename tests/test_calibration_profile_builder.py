"""Tests to improve coverage of src/calibration/profile_builder.py.

Targets uncovered lines: 61, 110-142, 200, 205-221.
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

from src.calibration.profile import AirportProfile, _build_fallback_profile
from src.calibration.profile_builder import (
    build_profiles,
    _build_single_profile,
    _enrich_with_known_stats,
    _enrich_with_otp,
    US_AIRPORTS,
    INTERNATIONAL_AIRPORTS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_profile(iata: str, **kwargs) -> AirportProfile:
    """Create a minimal AirportProfile for testing."""
    from src.calibration.profile import _iata_to_icao
    defaults = dict(
        icao_code=_iata_to_icao(iata),
        iata_code=iata,
        data_source="BTS_DB28",
        sample_size=100,
    )
    defaults.update(kwargs)
    return AirportProfile(**defaults)


# ---------------------------------------------------------------------------
# _build_single_profile fallback chain (lines 110-142)
# ---------------------------------------------------------------------------

class TestBuildSingleProfileFallbackChain:
    """Test the priority chain: DB28 → BTS CSV → OpenSky → known → fallback."""

    def test_falls_through_to_known_profile(self):
        """When no data files exist and OpenSky disabled, use known profile."""
        # Use a US airport that has a known profile (e.g., SFO)
        with patch("src.calibration.profile_builder._DB28_DIR") as mock_db28:
            mock_db28.exists.return_value = False
            profile = _build_single_profile(
                "SFO", raw_dir=Path("/nonexistent"), use_opensky=False,
            )
        # Should get a known profile or fallback
        assert profile.iata_code == "SFO"
        assert profile.icao_code == "KSFO"

    def test_falls_through_to_fallback_for_unknown_airport(self):
        """Line 142: unknown airport with no data → _build_fallback_profile."""
        with patch("src.calibration.profile_builder._DB28_DIR") as mock_db28:
            mock_db28.exists.return_value = False
            profile = _build_single_profile(
                "XYZ", raw_dir=Path("/nonexistent"), use_opensky=False,
            )
        assert profile.iata_code == "XYZ"
        assert profile.data_source == "fallback"

    def test_bts_csv_path_used_for_us_airport(self):
        """Lines 110-123: BTS CSV path is tried for US airports."""
        mock_profile = _make_profile("LAX", data_source="BTS_CSV")

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_dir = Path(tmpdir)
            # Create the T-100 domestic file to trigger has_bts
            (raw_dir / "T_T100_SEGMENT_ALL_CARRIER.csv").touch()

            with (
                patch("src.calibration.profile_builder._DB28_DIR") as mock_db28,
                patch(
                    "src.calibration.bts_ingest.build_profile_from_bts",
                    return_value=mock_profile,
                ),
            ):
                mock_db28.exists.return_value = False
                profile = _build_single_profile("LAX", raw_dir=raw_dir)

        assert profile.iata_code == "LAX"
        assert profile.data_source == "BTS_CSV"

    def test_opensky_path_tried_when_enabled(self):
        """Lines 126-133: OpenSky is tried for international airports."""
        mock_profile = _make_profile("LHR", data_source="OpenSky")

        with (
            patch("src.calibration.profile_builder._DB28_DIR") as mock_db28,
            patch(
                "src.calibration.opensky_ingest.build_profile_from_opensky",
                return_value=mock_profile,
            ),
        ):
            mock_db28.exists.return_value = False
            profile = _build_single_profile(
                "LHR", raw_dir=Path("/nonexistent"), use_opensky=True,
            )

        assert profile.iata_code == "LHR"
        assert profile.data_source == "OpenSky"

    def test_opensky_failure_falls_to_known(self):
        """Line 133: OpenSky exception falls through to known profile."""
        with (
            patch("src.calibration.profile_builder._DB28_DIR") as mock_db28,
            patch(
                "src.calibration.opensky_ingest.build_profile_from_opensky",
                side_effect=RuntimeError("API down"),
            ),
        ):
            mock_db28.exists.return_value = False
            profile = _build_single_profile(
                "LHR", raw_dir=Path("/nonexistent"), use_opensky=True,
            )

        # Should fall through to known profile for LHR
        assert profile.iata_code == "LHR"
        assert profile.data_source != "OpenSky"

    def test_db28_path_tried_for_us_airport(self):
        """Lines 99-107: DB28 path is tried first for US airports."""
        mock_profile = _make_profile("SFO", data_source="BTS_DB28")

        with (
            patch("src.calibration.profile_builder._DB28_DIR") as mock_db28_dir,
            patch(
                "src.calibration.bts_ingest.build_profile_from_db28",
                return_value=mock_profile,
            ),
            patch("src.calibration.profile_builder._enrich_with_otp") as mock_enrich,
        ):
            mock_db28_dir.exists.return_value = True
            # Simulate glob returning zip files
            mock_db28_dir.glob.return_value = [Path("/fake/DB28SEG_2024.zip")]

            profile = _build_single_profile(
                "SFO", raw_dir=Path("/nonexistent"),
            )

        assert profile.data_source == "BTS_DB28"
        mock_enrich.assert_called_once()

    def test_db28_returns_none_falls_through(self):
        """DB28 returns None → falls through to BTS CSV or beyond."""
        with (
            patch("src.calibration.profile_builder._DB28_DIR") as mock_db28_dir,
            patch(
                "src.calibration.bts_ingest.build_profile_from_db28",
                return_value=None,
            ),
        ):
            mock_db28_dir.exists.return_value = True
            mock_db28_dir.glob.return_value = [Path("/fake/DB28SEG_2024.zip")]

            profile = _build_single_profile(
                "SFO", raw_dir=Path("/nonexistent"),
            )

        # Falls through DB28 (returned None) → BTS CSV (no files) → known → fallback
        assert profile.iata_code == "SFO"


# ---------------------------------------------------------------------------
# _enrich_with_known_stats (lines 200, 205-221)
# ---------------------------------------------------------------------------

class TestEnrichWithKnownStats:
    def test_fills_empty_hourly_profile(self):
        """Line 210-211: empty hourly_profile filled from known."""
        profile = _make_profile("SFO", hourly_profile=[], delay_rate=0.0,
                                mean_delay_minutes=0.0, delay_distribution={})
        _enrich_with_known_stats(profile, "SFO")

        # SFO has a known profile, so hourly should be filled
        assert len(profile.hourly_profile) == 24

    def test_fills_empty_delay_stats(self):
        """Lines 213-218: zero delay stats filled from known."""
        profile = _make_profile("JFK", delay_rate=0.0, mean_delay_minutes=0.0,
                                delay_distribution={})
        _enrich_with_known_stats(profile, "JFK")

        assert profile.delay_rate > 0
        assert profile.mean_delay_minutes > 0

    def test_preserves_existing_delay_rate(self):
        """Lines 213: non-zero delay_rate is not overwritten."""
        profile = _make_profile("SFO", delay_rate=0.25, mean_delay_minutes=15.0)
        _enrich_with_known_stats(profile, "SFO")

        assert profile.delay_rate == 0.25
        assert profile.mean_delay_minutes == 15.0

    def test_updates_data_source_for_db28(self):
        """Line 220-221: data_source updated when enriching a BTS_DB28 profile."""
        profile = _make_profile("SFO", data_source="BTS_DB28",
                                hourly_profile=[], delay_rate=0.0,
                                mean_delay_minutes=0.0, delay_distribution={})
        _enrich_with_known_stats(profile, "SFO")

        assert profile.data_source == "BTS_DB28+known_stats"

    def test_unknown_airport_no_enrichment(self):
        """Lines 207-208: unknown IATA returns early without changes."""
        profile = _make_profile("XYZ", data_source="BTS_DB28",
                                hourly_profile=[], delay_rate=0.0)
        _enrich_with_known_stats(profile, "XYZ")

        # No known profile for XYZ, so nothing changes
        assert profile.hourly_profile == []
        assert profile.delay_rate == 0.0
        # data_source unchanged because no known profile was found
        assert profile.data_source == "BTS_DB28"

    def test_fills_delay_distribution_when_empty(self):
        """Line 215-216: empty delay_distribution filled from known."""
        profile = _make_profile("ATL", delay_distribution={}, delay_rate=0.0,
                                mean_delay_minutes=0.0)
        _enrich_with_known_stats(profile, "ATL")

        assert len(profile.delay_distribution) > 0


# ---------------------------------------------------------------------------
# build_profiles orchestration (line 61 and iteration)
# ---------------------------------------------------------------------------

class TestBuildProfiles:
    def test_builds_profiles_for_given_airports(self):
        """Lines 60-87: full orchestration with mocked _build_single_profile."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "profiles"

            with patch(
                "src.calibration.profile_builder._build_single_profile",
            ) as mock_build:
                mock_build.side_effect = lambda iata, *a, **kw: _make_profile(
                    iata, data_source="test",
                    airline_shares={"UAL": 0.5},
                    domestic_route_shares={"LAX": 1.0},
                    international_route_shares={},
                )

                result = build_profiles(
                    airports=["SFO", "LAX"],
                    output_dir=out_dir,
                )

            assert len(result) == 2
            assert result[0].iata_code == "SFO"
            assert result[1].iata_code == "LAX"
            # Check profiles were saved
            assert (out_dir / "KSFO.json").exists()
            assert (out_dir / "KLAX.json").exists()
            # profile_date should be set
            assert result[0].profile_date != ""

    def test_default_airports_when_none(self):
        """Line 61: airports=None uses all US + international airports."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "profiles"

            with patch(
                "src.calibration.profile_builder._build_single_profile",
            ) as mock_build:
                mock_build.side_effect = lambda iata, *a, **kw: _make_profile(
                    iata, data_source="test",
                    airline_shares={"UAL": 0.5},
                    domestic_route_shares={"LAX": 1.0},
                    international_route_shares={},
                )

                result = build_profiles(output_dir=out_dir)

            expected_count = len(US_AIRPORTS) + len(INTERNATIONAL_AIRPORTS)
            assert len(result) == expected_count
            assert mock_build.call_count == expected_count


# ---------------------------------------------------------------------------
# _enrich_with_otp (lines 145-200)
# ---------------------------------------------------------------------------

class TestEnrichWithOtp:
    def test_otp_not_available_falls_to_known_stats(self):
        """Line 199-200: when OTP dir doesn't exist, falls back to known_stats."""
        profile = _make_profile("SFO", data_source="BTS_DB28",
                                hourly_profile=[], delay_rate=0.0,
                                mean_delay_minutes=0.0, delay_distribution={})

        with patch("src.calibration.profile_builder._OTP_DIR") as mock_otp:
            mock_otp.exists.return_value = False
            _enrich_with_otp(profile, "SFO")

        # Should have fallen through to _enrich_with_known_stats
        assert profile.data_source == "BTS_DB28+known_stats"

    def test_otp_dir_exists_but_no_zips(self):
        """OTP dir exists but has no zip files → falls to known_stats."""
        profile = _make_profile("SFO", data_source="BTS_DB28",
                                hourly_profile=[], delay_rate=0.0,
                                mean_delay_minutes=0.0, delay_distribution={})

        with patch("src.calibration.profile_builder._OTP_DIR") as mock_otp:
            mock_otp.exists.return_value = True
            mock_otp.glob.return_value = []
            _enrich_with_otp(profile, "SFO")

        assert profile.data_source == "BTS_DB28+known_stats"

    def test_otp_with_real_data(self):
        """Lines 156-191: OTP data available and has flights."""
        profile = _make_profile("SFO", data_source="BTS_DB28",
                                hourly_profile=[], delay_rate=0.0,
                                mean_delay_minutes=0.0, delay_distribution={})

        mock_otp_result = {
            "total_flights": 500,
            "hourly_departures": {8: 30, 9: 40, 17: 50, 18: 35},
            "hourly_arrivals": {10: 25, 11: 30, 19: 40, 20: 35},
            "delay_rate": 0.22,
            "mean_delay_minutes": 18.5,
            "delay_causes": {
                "carrier": 100,
                "weather": 50,
                "nas": 30,
                "security": 5,
                "late_aircraft": 65,
            },
        }

        with (
            patch("src.calibration.profile_builder._OTP_DIR") as mock_otp_dir,
            patch("src.calibration.bts_ingest.parse_otp_prezip",
                  return_value=mock_otp_result),
        ):
            mock_otp_dir.exists.return_value = True
            mock_otp_dir.glob.return_value = [Path("/fake/otp_2024.zip")]
            _enrich_with_otp(profile, "SFO")

        assert profile.data_source == "BTS_DB28+OTP"
        assert profile.delay_rate == 0.22
        assert profile.mean_delay_minutes == 18.5
        assert len(profile.hourly_profile) == 24
        assert len(profile.delay_distribution) > 0

    def test_otp_with_zero_flights_falls_to_known(self):
        """Line 158: OTP data has 0 flights → falls to known_stats."""
        profile = _make_profile("SFO", data_source="BTS_DB28",
                                hourly_profile=[], delay_rate=0.0,
                                mean_delay_minutes=0.0, delay_distribution={})

        mock_otp_result = {
            "total_flights": 0,
            "hourly_departures": {},
            "hourly_arrivals": {},
            "delay_rate": 0.0,
            "mean_delay_minutes": 0.0,
            "delay_causes": {},
        }

        with (
            patch("src.calibration.profile_builder._OTP_DIR") as mock_otp_dir,
            patch("src.calibration.bts_ingest.parse_otp_prezip",
                  return_value=mock_otp_result),
        ):
            mock_otp_dir.exists.return_value = True
            mock_otp_dir.glob.return_value = [Path("/fake/otp_2024.zip")]
            _enrich_with_otp(profile, "SFO")

        assert profile.data_source == "BTS_DB28+known_stats"

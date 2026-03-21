"""Tests for the calibration system — airport profiles, loading, and generation integration."""

import json
import random
import tempfile
from collections import Counter
from pathlib import Path

import pytest

from src.calibration.profile import (
    AirportProfile,
    AirportProfileLoader,
    _build_fallback_profile,
    _iata_to_icao,
    _icao_to_iata,
)


# ============================================================================
# AirportProfile dataclass tests
# ============================================================================


class TestAirportProfile:
    """Tests for the AirportProfile dataclass."""

    def test_create_minimal_profile(self):
        p = AirportProfile(icao_code="KSFO", iata_code="SFO")
        assert p.icao_code == "KSFO"
        assert p.iata_code == "SFO"
        assert p.delay_rate == 0.15
        assert p.domestic_ratio == 0.7

    def test_create_full_profile(self):
        p = AirportProfile(
            icao_code="KSFO",
            iata_code="SFO",
            airline_shares={"UAL": 0.46, "SWA": 0.12},
            domestic_route_shares={"LAX": 0.15, "ORD": 0.10},
            international_route_shares={"LHR": 0.08},
            domestic_ratio=0.72,
            fleet_mix={"UAL": {"B738": 0.35, "A320": 0.25}},
            hourly_profile=[0.02] * 24,
            delay_rate=0.22,
            delay_distribution={"71": 0.3, "68": 0.2},
            mean_delay_minutes=25.0,
            data_source="BTS_T100",
            sample_size=150000,
        )
        assert p.airline_shares["UAL"] == 0.46
        assert p.delay_rate == 0.22
        assert len(p.hourly_profile) == 24

    def test_to_json_roundtrip(self):
        p = AirportProfile(
            icao_code="KSFO",
            iata_code="SFO",
            airline_shares={"UAL": 0.5, "DAL": 0.3},
            delay_rate=0.2,
        )
        json_str = p.to_json()
        data = json.loads(json_str)
        p2 = AirportProfile.from_json(data)
        assert p2.icao_code == "KSFO"
        assert p2.airline_shares == {"UAL": 0.5, "DAL": 0.3}
        assert p2.delay_rate == 0.2

    def test_save_and_load(self, tmp_path):
        p = AirportProfile(
            icao_code="KSFO",
            iata_code="SFO",
            airline_shares={"UAL": 0.5},
            delay_rate=0.22,
        )
        path = p.save(tmp_path / "KSFO.json")
        assert path.exists()

        p2 = AirportProfile.load(path)
        assert p2.icao_code == "KSFO"
        assert p2.airline_shares == {"UAL": 0.5}
        assert p2.delay_rate == 0.22

    def test_from_json_ignores_unknown_fields(self):
        data = {
            "icao_code": "KSFO",
            "iata_code": "SFO",
            "unknown_field": "should be ignored",
        }
        p = AirportProfile.from_json(data)
        assert p.icao_code == "KSFO"
        assert not hasattr(p, "unknown_field") or "unknown_field" not in p.__dict__


# ============================================================================
# IATA ↔ ICAO mapping tests
# ============================================================================


class TestCodeMapping:
    def test_iata_to_icao_us(self):
        assert _iata_to_icao("SFO") == "KSFO"
        assert _iata_to_icao("JFK") == "KJFK"
        assert _iata_to_icao("ORD") == "KORD"

    def test_iata_to_icao_international(self):
        assert _iata_to_icao("LHR") == "EGLL"
        assert _iata_to_icao("NRT") == "RJAA"
        assert _iata_to_icao("DXB") == "OMDB"

    def test_icao_passthrough(self):
        assert _iata_to_icao("KSFO") == "KSFO"
        assert _iata_to_icao("EGLL") == "EGLL"

    def test_unknown_code(self):
        assert _iata_to_icao("XYZ") == "XYZ"

    def test_icao_to_iata(self):
        assert _icao_to_iata("KSFO") == "SFO"
        assert _icao_to_iata("EGLL") == "LHR"


# ============================================================================
# Fallback profile tests
# ============================================================================


class TestFallbackProfile:
    def test_fallback_has_all_fields(self):
        p = _build_fallback_profile("SFO")
        assert p.icao_code == "KSFO"
        assert p.iata_code == "SFO"
        assert len(p.airline_shares) == 10
        assert len(p.domestic_route_shares) > 0
        assert len(p.international_route_shares) > 0
        assert len(p.hourly_profile) == 24
        assert len(p.delay_distribution) > 0
        assert p.data_source == "fallback"

    def test_fallback_airline_shares_sum_to_one(self):
        p = _build_fallback_profile("SFO")
        total = sum(p.airline_shares.values())
        assert abs(total - 1.0) < 0.01

    def test_fallback_route_shares_sum_to_one(self):
        p = _build_fallback_profile("SFO")
        dom_total = sum(p.domestic_route_shares.values())
        intl_total = sum(p.international_route_shares.values())
        assert abs(dom_total - 1.0) < 0.01
        assert abs(intl_total - 1.0) < 0.01

    def test_fallback_hourly_profile_sums_to_one(self):
        p = _build_fallback_profile("SFO")
        total = sum(p.hourly_profile)
        assert abs(total - 1.0) < 0.01

    def test_fallback_excludes_self_from_routes(self):
        p = _build_fallback_profile("SFO")
        assert "SFO" not in p.domestic_route_shares
        assert "SFO" not in p.international_route_shares

    def test_fallback_different_airports(self):
        sfo = _build_fallback_profile("SFO")
        jfk = _build_fallback_profile("JFK")
        assert sfo.icao_code != jfk.icao_code
        # JFK should not be in JFK's domestic routes
        assert "JFK" not in jfk.domestic_route_shares
        # SFO should not be in SFO's domestic routes
        assert "SFO" not in sfo.domestic_route_shares

    def test_fallback_international_airport(self):
        p = _build_fallback_profile("LHR")
        assert p.icao_code == "EGLL"
        assert p.iata_code == "LHR"
        assert "LHR" not in p.international_route_shares

    def test_fallback_matches_hardcoded_delay_rate(self):
        p = _build_fallback_profile("SFO")
        assert p.delay_rate == 0.15  # matches schedule_generator

    def test_fallback_delay_distribution_keys(self):
        p = _build_fallback_profile("SFO")
        # Should have the same IATA delay codes as schedule_generator.DELAY_CODES
        expected_codes = {"61", "62", "63", "67", "68", "71", "72", "81", "41"}
        assert set(p.delay_distribution.keys()) == expected_codes


# ============================================================================
# AirportProfileLoader tests
# ============================================================================


class TestAirportProfileLoader:
    def test_loader_returns_fallback_when_no_files(self, tmp_path):
        # Use an unknown airport to test true fallback (SFO has a known-stats profile)
        loader = AirportProfileLoader(profiles_dir=tmp_path)
        p = loader.get_profile("ZZZZ")
        assert p.icao_code == "ZZZZ"
        assert p.data_source == "fallback"

    def test_loader_returns_known_stats_profile(self, tmp_path):
        loader = AirportProfileLoader(profiles_dir=tmp_path)
        p = loader.get_profile("SFO")
        assert p.icao_code == "KSFO"
        assert p.data_source == "known_stats"

    def test_loader_reads_json_file(self, tmp_path):
        # Write a profile JSON
        profile = AirportProfile(
            icao_code="KSFO",
            iata_code="SFO",
            airline_shares={"UAL": 0.8},
            data_source="test",
        )
        profile.save(tmp_path / "KSFO.json")

        loader = AirportProfileLoader(profiles_dir=tmp_path)
        p = loader.get_profile("SFO")
        assert p.airline_shares == {"UAL": 0.8}
        assert p.data_source == "test"

    def test_loader_caches_profiles(self, tmp_path):
        loader = AirportProfileLoader(profiles_dir=tmp_path)
        p1 = loader.get_profile("SFO")
        p2 = loader.get_profile("SFO")
        assert p1 is p2  # Same object from cache

    def test_loader_clear_cache(self, tmp_path):
        loader = AirportProfileLoader(profiles_dir=tmp_path)
        p1 = loader.get_profile("SFO")
        loader.clear_cache()
        p2 = loader.get_profile("SFO")
        assert p1 is not p2  # Different objects after cache clear

    def test_loader_accepts_icao_code(self, tmp_path):
        loader = AirportProfileLoader(profiles_dir=tmp_path)
        p = loader.get_profile("KSFO")
        assert p.icao_code == "KSFO"

    def test_loader_list_available(self, tmp_path):
        # Create some profile files
        for icao in ["KSFO", "KJFK", "EGLL"]:
            AirportProfile(icao_code=icao, iata_code="").save(tmp_path / f"{icao}.json")

        loader = AirportProfileLoader(profiles_dir=tmp_path)
        available = loader.list_available()
        assert "KSFO" in available
        assert "KJFK" in available
        assert "EGLL" in available

    def test_loader_handles_corrupt_json(self, tmp_path):
        # Write corrupt JSON for an unknown airport (no known-stats fallback)
        (tmp_path / "ZZZZ.json").write_text("not valid json{{{")
        loader = AirportProfileLoader(profiles_dir=tmp_path)
        p = loader.get_profile("ZZZZ")
        # Should fall back to hardcoded
        assert p.data_source == "fallback"

    def test_loader_loads_real_profiles(self):
        """Test that the pre-built fallback profiles load correctly."""
        loader = AirportProfileLoader()
        available = loader.list_available()
        if not available:
            pytest.skip("No pre-built profiles found")

        for icao in available:
            p = loader.get_profile(icao)
            assert p.icao_code == icao
            assert len(p.airline_shares) > 0


# ============================================================================
# Generation integration tests
# ============================================================================


class TestGenerationIntegration:
    """Test that profile-driven generation produces valid output."""

    def test_select_airline_with_profile(self):
        from src.ingestion.schedule_generator import _select_airline

        profile = AirportProfile(
            icao_code="KSFO", iata_code="SFO",
            airline_shares={"UAL": 0.9, "DAL": 0.1},
        )
        random.seed(42)
        codes = [_select_airline(profile=profile)[0] for _ in range(100)]
        counter = Counter(codes)
        # UAL should dominate with 90% share
        assert counter["UAL"] > 70
        assert set(codes) <= {"UAL", "DAL"}

    def test_select_airline_without_profile(self):
        from src.ingestion.schedule_generator import _select_airline

        random.seed(42)
        code, name = _select_airline()
        assert isinstance(code, str)
        assert isinstance(name, str)

    def test_select_destination_with_profile(self):
        from src.ingestion.schedule_generator import _select_destination

        profile = AirportProfile(
            icao_code="KSFO", iata_code="SFO",
            domestic_route_shares={"LAX": 0.8, "ORD": 0.2},
            international_route_shares={"LHR": 1.0},
            domestic_ratio=0.9,
        )
        random.seed(42)
        dests = [_select_destination("departure", "UAL", profile=profile) for _ in range(100)]
        counter = Counter(dests)
        # Should mostly be LAX (domestic dominant)
        assert counter["LAX"] > 50

    def test_select_aircraft_with_profile(self):
        from src.ingestion.schedule_generator import _select_aircraft

        profile = AirportProfile(
            icao_code="KSFO", iata_code="SFO",
            fleet_mix={"UAL": {"B738": 0.7, "A320": 0.3}},
        )
        random.seed(42)
        types = [_select_aircraft("LAX", airline_code="UAL", profile=profile) for _ in range(100)]
        counter = Counter(types)
        assert counter["B738"] > 50
        assert set(types) <= {"B738", "A320"}

    def test_select_aircraft_falls_back_without_airline(self):
        from src.ingestion.schedule_generator import _select_aircraft

        profile = AirportProfile(
            icao_code="KSFO", iata_code="SFO",
            fleet_mix={"UAL": {"B738": 1.0}},
        )
        # Unknown airline should fall back to default logic
        result = _select_aircraft("LAX", airline_code="XXX", profile=profile)
        assert isinstance(result, str)

    def test_generate_delay_with_profile(self):
        from src.ingestion.schedule_generator import _generate_delay

        # High delay rate profile
        profile = AirportProfile(
            icao_code="KSFO", iata_code="SFO",
            delay_rate=0.8,  # 80% delayed
            delay_distribution={"71": 1.0},
            mean_delay_minutes=30.0,
        )
        random.seed(42)
        delays = [_generate_delay(profile=profile) for _ in range(100)]
        delayed = [d for d in delays if d[0] > 0]
        # Should have ~80% delays
        assert len(delayed) > 60

    def test_generate_delay_without_profile(self):
        from src.ingestion.schedule_generator import _generate_delay

        random.seed(42)
        delay_min, code, reason = _generate_delay()
        assert isinstance(delay_min, int)

    def test_generate_daily_schedule_with_profile(self):
        from src.ingestion.schedule_generator import generate_daily_schedule
        from datetime import datetime, timezone

        profile = AirportProfile(
            icao_code="KSFO", iata_code="SFO",
            airline_shares={"UAL": 0.7, "DAL": 0.3},
            domestic_route_shares={"LAX": 0.5, "ORD": 0.5},
            international_route_shares={"LHR": 1.0},
            domestic_ratio=0.8,
            fleet_mix={"UAL": {"B738": 1.0}, "DAL": {"A320": 1.0}},
            hourly_profile=[0.04] * 24,  # flat
            delay_rate=0.1,
            delay_distribution={"71": 1.0},
            mean_delay_minutes=15.0,
        )

        date = datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
        schedule = generate_daily_schedule(
            airport="SFO", date=date, profile=profile,
        )
        assert len(schedule) > 0

        # Verify airlines come from profile
        airlines = {f["airline_code"] for f in schedule}
        assert airlines <= {"UAL", "DAL"}

    def test_simulation_engine_loads_profile(self):
        """Test that SimulationEngine loads a profile on init."""
        from src.simulation.config import SimulationConfig
        from src.simulation.engine import SimulationEngine

        config = SimulationConfig(
            airport="SFO", arrivals=5, departures=5,
            duration_hours=1.0, seed=42,
        )
        engine = SimulationEngine(config)
        assert engine.airport_profile is not None
        assert engine.airport_profile.icao_code == "KSFO"


# ============================================================================
# BTS ingestion tests (with synthetic CSV data)
# ============================================================================


class TestBTSIngestion:
    """Test BTS CSV parsing with synthetic test data."""

    def test_parse_t100_segment(self, tmp_path):
        from src.calibration.bts_ingest import parse_t100_segment

        csv_content = (
            "ORIGIN,DEST,UNIQUE_CARRIER,DEPARTURES_PERFORMED,PASSENGERS,AIRCRAFT_TYPE\n"
            "SFO,LAX,UAL,100,15000,613\n"
            "SFO,ORD,UAL,80,12000,625\n"
            "SFO,LAX,DAL,30,4500,613\n"
            "LAX,SFO,UAL,95,14000,613\n"  # Not origin=SFO, skipped for departures
        )
        csv_path = tmp_path / "t100.csv"
        csv_path.write_text(csv_content)

        result = parse_t100_segment(csv_path, "SFO")
        assert result["airline_departures"]["UAL"] == 180  # 100 + 80
        assert result["airline_departures"]["DAL"] == 30
        assert result["route_volumes"]["LAX"] == 19500  # 15000 + 4500
        assert result["route_volumes"]["ORD"] == 12000

    def test_parse_ontime_performance(self, tmp_path):
        from src.calibration.bts_ingest import parse_ontime_performance

        csv_content = (
            "ORIGIN,DEST,CRS_DEP_TIME,CRS_ARR_TIME,DEP_DELAY,UNIQUE_CARRIER,"
            "CARRIER_DELAY,WEATHER_DELAY,NAS_DELAY,SECURITY_DELAY,LATE_AIRCRAFT_DELAY\n"
            "SFO,LAX,0800,0930,5,UAL,0,0,0,0,0\n"
            "SFO,ORD,0900,1500,30,UAL,15,0,0,0,15\n"
            "SFO,JFK,1700,0100,0,DAL,0,0,0,0,0\n"
            "LAX,SFO,1200,1330,-5,UAL,0,0,0,0,0\n"  # arrival at SFO
        )
        csv_path = tmp_path / "ontime.csv"
        csv_path.write_text(csv_content)

        result = parse_ontime_performance(csv_path, "SFO")
        assert result["total_flights"] == 4
        assert result["delayed_flights"] == 1  # only DEP_DELAY > 15 for departures
        assert result["hourly_departures"][8] == 1
        assert result["hourly_departures"][9] == 1
        assert result["hourly_departures"][17] == 1

    def test_build_profile_from_bts(self, tmp_path):
        from src.calibration.bts_ingest import build_profile_from_bts

        # Create minimal T-100 CSV
        t100 = tmp_path / "t100.csv"
        t100.write_text(
            "ORIGIN,DEST,UNIQUE_CARRIER,DEPARTURES_PERFORMED,PASSENGERS,AIRCRAFT_TYPE\n"
            "SFO,LAX,UAL,200,30000,613\n"
            "SFO,ORD,DAL,100,15000,625\n"
        )

        profile = build_profile_from_bts("SFO", t100_domestic_path=t100)
        assert profile.icao_code == "KSFO"
        assert profile.airline_shares["UAL"] > profile.airline_shares["DAL"]
        assert "LAX" in profile.domestic_route_shares
        assert "BTS" in profile.data_source


# ============================================================================
# OurAirports ingestion tests
# ============================================================================


class TestOurAirportsIngestion:
    def test_parse_airports_csv(self, tmp_path):
        from src.calibration.ourairports_ingest import parse_airports_csv

        csv_content = (
            "id,ident,type,name,latitude_deg,longitude_deg,elevation_ft,"
            "continent,iso_country,iso_region,municipality,scheduled_service,"
            "gps_code,iata_code,local_code,home_link,wikipedia_link,keywords\n"
            '1,KSFO,large_airport,"San Francisco International Airport",'
            '37.6213,-122.379,13,NA,US,US-CA,San Francisco,yes,KSFO,SFO,SFO,,,\n'
        )
        csv_path = tmp_path / "airports.csv"
        csv_path.write_text(csv_content)

        airports = parse_airports_csv(csv_path)
        assert "KSFO" in airports
        assert airports["KSFO"]["iata"] == "SFO"
        assert abs(airports["KSFO"]["latitude"] - 37.6213) < 0.001

    def test_parse_runways_csv(self, tmp_path):
        from src.calibration.ourairports_ingest import parse_runways_csv

        csv_content = (
            "id,airport_ref,airport_ident,length_ft,width_ft,surface,"
            "lighted,closed,le_ident,le_latitude_deg,le_longitude_deg,"
            "le_elevation_ft,le_heading_degT,le_displaced_threshold_ft,"
            "he_ident,he_latitude_deg,he_longitude_deg,he_elevation_ft,"
            "he_heading_degT,he_displaced_threshold_ft\n"
            "1,1,KSFO,11870,200,ASP,1,0,01L,37.6,122.4,13,15,600,"
            "19R,37.6,122.4,13,195,600\n"
            "2,1,KSFO,10600,200,ASP,1,0,10L,37.6,122.4,13,105,0,"
            "28R,37.6,122.4,13,285,0\n"
        )
        csv_path = tmp_path / "runways.csv"
        csv_path.write_text(csv_content)

        runways = parse_runways_csv(csv_path)
        assert "KSFO" in runways
        assert len(runways["KSFO"]) == 2


# ============================================================================
# Profile builder tests
# ============================================================================


class TestProfileBuilder:
    def test_build_fallback_profiles(self, tmp_path):
        from src.calibration.profile_builder import build_profiles

        profiles = build_profiles(
            airports=["SFO", "JFK"],
            raw_data_dir=tmp_path / "empty",  # no raw data
            output_dir=tmp_path / "profiles",
        )
        assert len(profiles) == 2
        assert profiles[0].icao_code == "KSFO"
        assert profiles[1].icao_code == "KJFK"
        assert (tmp_path / "profiles" / "KSFO.json").exists()

    def test_build_with_bts_data(self, tmp_path):
        from src.calibration.profile_builder import build_profiles

        # Create minimal BTS data
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        (raw_dir / "T_T100_SEGMENT_ALL_CARRIER.csv").write_text(
            "ORIGIN,DEST,UNIQUE_CARRIER,DEPARTURES_PERFORMED,PASSENGERS,AIRCRAFT_TYPE\n"
            "SFO,LAX,UAL,500,75000,613\n"
            "SFO,ORD,DAL,200,30000,625\n"
        )

        profiles = build_profiles(
            airports=["SFO"],
            raw_data_dir=raw_dir,
            output_dir=tmp_path / "profiles",
        )
        assert len(profiles) == 1
        assert "BTS" in profiles[0].data_source
        assert profiles[0].airline_shares.get("UAL", 0) > 0.5

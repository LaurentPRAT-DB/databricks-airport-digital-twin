"""Tests for OpenFlights route data ingestion.

Uses mock data — no downloads required.
"""

import csv
import io
import pytest
from pathlib import Path
from unittest.mock import patch

from src.calibration.openflights_ingest import (
    parse_airlines,
    parse_routes,
    build_profile_from_openflights,
    build_profiles_batch,
    _EQUIPMENT_MAP,
)
from src.calibration.profile import AirportProfile


# ── Sample data fixtures ──────────────────────────────────────────────


SAMPLE_AIRLINES_CSV = """\
1,"Aeroflot","\\N",SU,AFL,AEROFLOT,Russia,Y
2,"United Airlines","\\N",UA,UAL,UNITED,United States,Y
3,"American Airlines","\\N",AA,AAL,AMERICAN,United States,Y
4,"Delta Air Lines","\\N",DL,DAL,DELTA,United States,Y
5,"Japan Airlines","\\N",JL,JAL,JAPANAIR,Japan,Y
6,"All Nippon Airways","\\N",NH,ANA,ALL NIPPON,Japan,Y
7,"Bad Entry","\\N",\\N,\\N,NONE,Nowhere,N
"""

SAMPLE_ROUTES_CSV = """\
UA,2,JFK,3797,LAX,3484,,0,738 320
AA,3,JFK,3797,LAX,3484,,0,738 321
DL,4,JFK,3797,ATL,3682,,0,738 320
UA,2,JFK,3797,SFO,3469,,0,777 320
UA,2,JFK,3797,LHR,507,,0,777 787
BA,5,JFK,3797,LHR,507,,0,777 787
DL,4,JFK,3797,CDG,1382,,0,767 330
NH,6,JFK,3797,NRT,2279,,0,777 787
JL,5,JFK,3797,NRT,2279,,0,777 787
AA,3,JFK,3797,ORD,3830,,0,738 321
UA,2,LAX,3484,JFK,3797,,0,738 320
DL,4,LAX,3484,ATL,3682,,0,738
UA,2,SFO,3469,JFK,3797,,0,777 320
DL,4,JFK,3797,MIA,3576,,0,738
AA,3,JFK,3797,DFW,3670,,0,738 321
UA,2,JFK,3797,DEN,3751,,0,738
DL,4,JFK,3797,BOS,3448,,0,738 320
UA,2,JFK,3797,ORD,3830,,0,738 320
DL,4,JFK,3797,SEA,3577,,0,738
AA,3,LAX,3484,SFO,3469,,0,320
NH,6,NRT,2279,HND,2359,,0,320 738
JL,5,NRT,2279,CTS,2287,,0,738
JL,5,NRT,2279,KIX,2325,,0,738 320
NH,6,NRT,2279,FUK,2305,,0,738
NH,6,NRT,2279,SIN,3316,,0,787 777
JL,5,NRT,2279,LAX,3484,,0,777
DL,4,NRT,2279,LAX,3484,Y,0,777
"""

# The last line is a codeshare — should be skipped


@pytest.fixture
def airlines_file(tmp_path: Path) -> Path:
    p = tmp_path / "airlines.dat"
    p.write_text(SAMPLE_AIRLINES_CSV)
    return p


@pytest.fixture
def routes_file(tmp_path: Path) -> Path:
    p = tmp_path / "routes.dat"
    p.write_text(SAMPLE_ROUTES_CSV)
    return p


# ── parse_airlines tests ─────────────────────────────────────────────


class TestParseAirlines:
    def test_basic_mapping(self, airlines_file: Path):
        mapping = parse_airlines(airlines_file)
        assert mapping["UA"] == "UAL"
        assert mapping["AA"] == "AAL"
        assert mapping["DL"] == "DAL"
        assert mapping["JL"] == "JAL"
        assert mapping["NH"] == "ANA"

    def test_skips_missing_codes(self, airlines_file: Path):
        mapping = parse_airlines(airlines_file)
        # Entry 7 has \\N for both codes — should not appear
        assert len(mapping) == 6  # SU, UA, AA, DL, JL, NH


# ── parse_routes tests ───────────────────────────────────────────────


class TestParseRoutes:
    def test_basic_parse(self, routes_file: Path, airlines_file: Path):
        airline_map = parse_airlines(airlines_file)
        routes = parse_routes(routes_file, airline_map)
        # 27 lines minus 1 codeshare = 26 operating routes
        assert len(routes) == 26

    def test_codeshare_skipped(self, routes_file: Path, airlines_file: Path):
        airline_map = parse_airlines(airlines_file)
        routes = parse_routes(routes_file, airline_map)
        # No route should have codeshare flag
        codeshares = [r for r in routes if r["src_iata"] == "NRT" and r["dst_iata"] == "LAX"
                      and r["airline_icao"] == "DAL"]
        assert len(codeshares) == 0

    def test_airline_code_resolution(self, routes_file: Path, airlines_file: Path):
        airline_map = parse_airlines(airlines_file)
        routes = parse_routes(routes_file, airline_map)
        # UA should be resolved to UAL
        ua_routes = [r for r in routes if r["airline_icao"] == "UAL"]
        assert len(ua_routes) > 0

    def test_equipment_parsing(self, routes_file: Path, airlines_file: Path):
        airline_map = parse_airlines(airlines_file)
        routes = parse_routes(routes_file, airline_map)
        # JFK→LHR by UA has equipment "777 787"
        jfk_lhr_ua = [r for r in routes if r["src_iata"] == "JFK" and r["dst_iata"] == "LHR"
                      and r["airline_icao"] == "UAL"]
        assert len(jfk_lhr_ua) == 1
        assert "B777" in jfk_lhr_ua[0]["equipment"]
        assert "B787" in jfk_lhr_ua[0]["equipment"]

    def test_no_airline_map(self, routes_file: Path):
        """Routes parse even without airline map — codes stay as-is."""
        routes = parse_routes(routes_file, airline_map=None)
        assert len(routes) == 26
        # 2-letter codes remain as-is when no map
        ua_routes = [r for r in routes if r["airline_icao"] == "UA"]
        assert len(ua_routes) > 0


# ── build_profile_from_openflights tests ─────────────────────────────


class TestBuildProfile:
    def test_jfk_profile(self, tmp_path: Path, routes_file: Path, airlines_file: Path):
        """JFK should have domestic and international routes."""
        profile = build_profile_from_openflights(
            "JFK",
            routes_path=routes_file,
            airlines_path=airlines_file,
            raw_dir=tmp_path,
            download=False,
        )
        assert profile is not None
        assert profile.iata_code == "JFK"
        assert profile.icao_code == "KJFK"
        assert profile.data_source == "openflights"

        # Should have domestic routes (LAX, ATL, SFO, ORD, etc.)
        assert len(profile.domestic_route_shares) > 0
        assert "LAX" in profile.domestic_route_shares

        # Should have international routes (LHR, CDG, NRT)
        assert len(profile.international_route_shares) > 0
        assert "LHR" in profile.international_route_shares

        # Should have airline shares
        assert len(profile.airline_shares) > 0
        assert "UAL" in profile.airline_shares

    def test_nrt_profile(self, tmp_path: Path, routes_file: Path, airlines_file: Path):
        """NRT should have both domestic Japanese and international routes."""
        profile = build_profile_from_openflights(
            "NRT",
            routes_path=routes_file,
            airlines_path=airlines_file,
            raw_dir=tmp_path,
            download=False,
        )
        assert profile is not None
        assert profile.iata_code == "NRT"

        # Domestic Japanese routes
        dom_dests = set(profile.domestic_route_shares.keys())
        # HND, CTS, KIX, FUK are domestic to NRT (all JP)
        assert len(dom_dests) > 0

        # International routes
        intl_dests = set(profile.international_route_shares.keys())
        assert len(intl_dests) > 0

    def test_no_routes_returns_none(self, tmp_path: Path, routes_file: Path, airlines_file: Path):
        """Airport with no routes in data should return None."""
        profile = build_profile_from_openflights(
            "ZZZ",
            routes_path=routes_file,
            airlines_path=airlines_file,
            raw_dir=tmp_path,
            download=False,
        )
        assert profile is None

    def test_route_shares_sum_to_one(self, tmp_path: Path, routes_file: Path, airlines_file: Path):
        profile = build_profile_from_openflights(
            "JFK",
            routes_path=routes_file,
            airlines_path=airlines_file,
            raw_dir=tmp_path,
            download=False,
        )
        assert profile is not None
        if profile.domestic_route_shares:
            total = sum(profile.domestic_route_shares.values())
            assert abs(total - 1.0) < 0.01
        if profile.international_route_shares:
            total = sum(profile.international_route_shares.values())
            assert abs(total - 1.0) < 0.01

    def test_airline_shares_sum_to_one(self, tmp_path: Path, routes_file: Path, airlines_file: Path):
        profile = build_profile_from_openflights(
            "JFK",
            routes_path=routes_file,
            airlines_path=airlines_file,
            raw_dir=tmp_path,
            download=False,
        )
        assert profile is not None
        total = sum(profile.airline_shares.values())
        assert abs(total - 1.0) < 0.01

    def test_domestic_ratio(self, tmp_path: Path, routes_file: Path, airlines_file: Path):
        profile = build_profile_from_openflights(
            "JFK",
            routes_path=routes_file,
            airlines_path=airlines_file,
            raw_dir=tmp_path,
            download=False,
        )
        assert profile is not None
        assert 0.0 <= profile.domestic_ratio <= 1.0

    def test_fleet_mix_populated(self, tmp_path: Path, routes_file: Path, airlines_file: Path):
        profile = build_profile_from_openflights(
            "JFK",
            routes_path=routes_file,
            airlines_path=airlines_file,
            raw_dir=tmp_path,
            download=False,
        )
        assert profile is not None
        assert len(profile.fleet_mix) > 0
        for airline, fleet in profile.fleet_mix.items():
            total = sum(fleet.values())
            assert abs(total - 1.0) < 0.01

    def test_no_download_missing_file(self, tmp_path: Path):
        """With download=False and no file, should return None."""
        profile = build_profile_from_openflights(
            "JFK", raw_dir=tmp_path, download=False,
        )
        assert profile is None

    def test_sample_size(self, tmp_path: Path, routes_file: Path, airlines_file: Path):
        profile = build_profile_from_openflights(
            "JFK",
            routes_path=routes_file,
            airlines_path=airlines_file,
            raw_dir=tmp_path,
            download=False,
        )
        assert profile is not None
        assert profile.sample_size > 0

    def test_openflights_has_no_hourly_or_delay(self, tmp_path: Path, routes_file: Path, airlines_file: Path):
        """OpenFlights doesn't provide hourly or delay data."""
        profile = build_profile_from_openflights(
            "JFK",
            routes_path=routes_file,
            airlines_path=airlines_file,
            raw_dir=tmp_path,
            download=False,
        )
        assert profile is not None
        assert profile.hourly_profile == []
        assert profile.delay_rate == 0.0


# ── build_profiles_batch tests ───────────────────────────────────────


class TestBuildProfilesBatch:
    def test_batch_multiple_airports(self, tmp_path: Path, routes_file: Path, airlines_file: Path):
        """Batch builds profiles for multiple airports from shared parsed data."""
        # Copy files to expected locations
        import shutil
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        shutil.copy(routes_file, raw_dir / "openflights_routes.dat")
        shutil.copy(airlines_file, raw_dir / "openflights_airlines.dat")

        results = build_profiles_batch(
            ["JFK", "NRT", "LAX", "ZZZ"],
            raw_dir=raw_dir,
            download=False,
        )
        # JFK, NRT, LAX should have profiles; ZZZ should not
        assert "JFK" in results
        assert "NRT" in results
        assert "LAX" in results
        assert "ZZZ" not in results

    def test_batch_empty_list(self, tmp_path: Path, routes_file: Path, airlines_file: Path):
        import shutil
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        shutil.copy(routes_file, raw_dir / "openflights_routes.dat")
        shutil.copy(airlines_file, raw_dir / "openflights_airlines.dat")

        results = build_profiles_batch([], raw_dir=raw_dir, download=False)
        assert results == {}


# ── Equipment map coverage ───────────────────────────────────────────


class TestEquipmentMap:
    def test_common_types_mapped(self):
        assert _EQUIPMENT_MAP["320"] == "A320"
        assert _EQUIPMENT_MAP["738"] == "B738"
        assert _EQUIPMENT_MAP["777"] == "B777"
        assert _EQUIPMENT_MAP["787"] == "B787"
        assert _EQUIPMENT_MAP["380"] == "A380"

    def test_regional_types_mapped(self):
        assert _EQUIPMENT_MAP["E75"] == "E175"
        assert _EQUIPMENT_MAP["CR9"] == "CRJ9"


# ── Integration with profile_builder priority chain ──────────────────


class TestProfileBuilderIntegration:
    def test_openflights_in_priority_chain(self, tmp_path: Path, routes_file: Path, airlines_file: Path):
        """OpenFlights should be used when BTS data is unavailable."""
        import shutil
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        shutil.copy(routes_file, raw_dir / "openflights_routes.dat")
        shutil.copy(airlines_file, raw_dir / "openflights_airlines.dat")

        from src.calibration.profile_builder import _build_single_profile
        # NRT is not a US airport, so BTS won't apply — OpenFlights should be used
        profile = _build_single_profile(
            "NRT", raw_dir, use_opensky=False, use_openflights=True,
        )
        # Should get OpenFlights data (not fallback)
        assert profile.data_source in ("openflights", "openflights+known_stats")

    def test_openflights_disabled(self, tmp_path: Path):
        """When use_openflights=False, should fall through to known/fallback."""
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()

        from src.calibration.profile_builder import _build_single_profile
        profile = _build_single_profile(
            "NRT", raw_dir, use_opensky=False, use_openflights=False,
        )
        # Should be known_stats or fallback, not openflights
        assert "openflights" not in profile.data_source

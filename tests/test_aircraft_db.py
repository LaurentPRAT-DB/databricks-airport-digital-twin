"""Tests for aircraft type database service."""

import pytest
from pathlib import Path

from app.backend.services.aircraft_db import AircraftDatabase


# ── CSV fixture ───────────────────────────────────────────────────────────

SAMPLE_CSV = """\
icao24,registration,manufacturericao,manufacturername,model,typecode,serialnumber,linenumber,icaoaircrafttype,operator,operatorcallsign,operatoricao,operatoriata,owner,testreg,registered,reguntil,status,built,firstflightdate,seatconfiguration,engines,modes,adsb,acars,notes,categoryDescription
a12345,N12345,BOEING,Boeing,737-800,B738,12345,1234,L2J,United Airlines,UNITED,UAL,UA,,,2020-01-01,,,,,,,,,,Large
a67890,N67890,AIRBUS,Airbus,A320-200,A320,67890,5678,L2J,Delta Air Lines,DELTA,DAL,DL,,,2019-06-15,,,,,,,,,,Large
abcdef,,EMBRAER,Embraer,ERJ-175,E170,99999,9999,L2J,Republic Airways,,,YX,,,2021-03-01,,,,,,,,,,Large
"""


@pytest.fixture
def csv_file(tmp_path):
    path = tmp_path / "aircraft_db.csv"
    path.write_text(SAMPLE_CSV)
    return path


# ── Tests ─────────────────────────────────────────────────────────────────


class TestAircraftDatabase:
    def test_load_from_file(self, csv_file):
        db = AircraftDatabase()
        count = db.load_from_file(csv_file)
        assert count == 3
        assert db.loaded is True
        assert db.entry_count == 3

    def test_lookup_existing(self, csv_file):
        db = AircraftDatabase()
        db.load_from_file(csv_file)
        typecode, reg = db.lookup("a12345")
        assert typecode == "B738"
        assert reg == "N12345"

    def test_lookup_case_insensitive(self, csv_file):
        db = AircraftDatabase()
        db.load_from_file(csv_file)
        typecode, _ = db.lookup("A12345")
        assert typecode == "B738"

    def test_lookup_missing(self, csv_file):
        db = AircraftDatabase()
        db.load_from_file(csv_file)
        typecode, reg = db.lookup("ffffff")
        assert typecode == ""
        assert reg == ""

    def test_lookup_no_registration(self, csv_file):
        db = AircraftDatabase()
        db.load_from_file(csv_file)
        typecode, reg = db.lookup("abcdef")
        assert typecode == "E170"
        assert reg == ""

    def test_empty_before_load(self):
        db = AircraftDatabase()
        assert db.loaded is False
        assert db.entry_count == 0
        typecode, reg = db.lookup("a12345")
        assert typecode == ""

    def test_load_invalid_csv(self, tmp_path):
        bad_file = tmp_path / "bad.csv"
        bad_file.write_text("not,a,valid,csv\nwith,no,icao24,columns\n")
        db = AircraftDatabase()
        count = db.load_from_file(bad_file)
        assert count == 0

    def test_load_empty_file(self, tmp_path):
        empty_file = tmp_path / "empty.csv"
        empty_file.write_text("")
        db = AircraftDatabase()
        count = db.load_from_file(empty_file)
        assert count == 0

    async def test_ensure_loaded_uses_cache(self, tmp_path):
        """ensure_loaded() uses cached file if fresh."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / "aircraft_db.csv").write_text(SAMPLE_CSV)

        db = AircraftDatabase(cache_dir=cache_dir)
        count = await db.ensure_loaded()
        assert count == 3
        assert db.loaded is True

    async def test_ensure_loaded_idempotent(self, tmp_path):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / "aircraft_db.csv").write_text(SAMPLE_CSV)

        db = AircraftDatabase(cache_dir=cache_dir)
        count1 = await db.ensure_loaded()
        count2 = await db.ensure_loaded()
        assert count1 == count2

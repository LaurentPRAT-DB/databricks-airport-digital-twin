"""Tests for recording persistence: schedule derivation and Lakebase persistence."""

import pytest
from unittest.mock import MagicMock, patch

from src.inference.opensky_events import OpenSkyEventInferrer

# Import the functions under test
from app.backend.api.opensky import (
    _derive_schedule_from_recording,
    _extract_airline,
    _extract_airline_code,
    _persist_recording_to_lakebase,
)


# ── Fixtures ────────────────────────────────────────────────────────────

SAMPLE_GATES = [
    {"ref": "G1", "geo": {"latitude": 37.6190, "longitude": -122.3750}},
    {"ref": "G2", "geo": {"latitude": 37.6192, "longitude": -122.3755}},
]


def _make_snap(icao24, callsign, lat, lon, time, velocity=0.0, on_ground=True,
               altitude=0.0, heading=90.0, vertical_rate=0.0, phase="parked",
               aircraft_type=""):
    return {
        "icao24": icao24,
        "callsign": callsign,
        "latitude": lat,
        "longitude": lon,
        "altitude": altitude,
        "velocity": velocity,
        "heading": heading,
        "on_ground": on_ground,
        "phase": phase,
        "aircraft_type": aircraft_type,
        "assigned_gate": None,
        "vertical_rate": vertical_rate,
        "time": time,
    }


# ── Tests: _extract_airline ─────────────────────────────────────────────

class TestExtractAirline:
    def test_standard_callsign(self):
        assert _extract_airline("UAL123") == "UAL"

    def test_two_letter_prefix(self):
        assert _extract_airline("BA456") == "BA"

    def test_numeric_only(self):
        assert _extract_airline("12345") == "12345"

    def test_airline_code_truncates(self):
        assert _extract_airline_code("SWISS123") == "SWI"

    def test_short_callsign(self):
        assert _extract_airline_code("UA1") == "UA"


# ── Tests: _derive_schedule_from_recording ──────────────────────────────

class TestDeriveSchedule:
    """Test schedule derivation from observed aircraft lifecycles."""

    def _run_inferrer(self, frame_sequence):
        """Helper: run inferrer over frame sequence and return all needed data."""
        inferrer = OpenSkyEventInferrer(SAMPLE_GATES)
        timestamps = sorted(frame_sequence.keys())
        for ts in timestamps:
            inferrer.process_frame(ts, frame_sequence[ts])
        enrichment = inferrer.get_results()
        return inferrer, enrichment, timestamps

    def test_arriving_flight(self):
        """Aircraft first seen airborne, then lands and parks at gate."""
        frames = {
            "2026-04-03T16:00:00": [
                _make_snap("abc123", "UAL100", 37.65, -122.40, "2026-04-03T16:00:00",
                           velocity=140, on_ground=False, altitude=2000,
                           vertical_rate=-800, phase="approaching"),
            ],
            "2026-04-03T16:02:00": [
                _make_snap("abc123", "UAL100", 37.62, -122.38, "2026-04-03T16:02:00",
                           velocity=60, on_ground=True, altitude=0,
                           phase="taxi_to_gate"),
            ],
            "2026-04-03T16:05:00": [
                _make_snap("abc123", "UAL100", 37.6190, -122.3750, "2026-04-03T16:05:00",
                           velocity=0, on_ground=True, altitude=0,
                           phase="parked"),
            ],
        }
        inferrer, enrichment, timestamps = self._run_inferrer(frames)
        origins = {"abc123": ("KJFK", "KSFO")}

        schedule = _derive_schedule_from_recording(
            inferrer, enrichment, origins, "KSFO", timestamps, frames,
        )

        # Should have at least one arrival entry
        arrivals = [s for s in schedule if s["flight_type"] == "arrival"]
        assert len(arrivals) >= 1
        arr = arrivals[0]
        assert arr["flight_number"] == "UAL100"
        assert arr["origin"] == "KJFK"
        assert arr["destination"] == "KSFO"
        assert arr["status"] == "Landed"
        assert arr["airline"] == "UAL"

    def test_departing_flight(self):
        """Aircraft starts parked at gate, then taxis and takes off."""
        frames = {
            "2026-04-03T16:00:00": [
                _make_snap("def456", "DLH200", 37.6190, -122.3750, "2026-04-03T16:00:00",
                           velocity=0, on_ground=True, phase="parked"),
            ],
            "2026-04-03T16:10:00": [
                _make_snap("def456", "DLH200", 37.625, -122.380, "2026-04-03T16:10:00",
                           velocity=15, on_ground=True, phase="taxi_to_runway"),
            ],
            "2026-04-03T16:15:00": [
                _make_snap("def456", "DLH200", 37.630, -122.385, "2026-04-03T16:15:00",
                           velocity=150, on_ground=False, altitude=500,
                           vertical_rate=2000, phase="takeoff"),
            ],
        }
        inferrer, enrichment, timestamps = self._run_inferrer(frames)
        origins = {"def456": ("KSFO", "EDDF")}

        schedule = _derive_schedule_from_recording(
            inferrer, enrichment, origins, "KSFO", timestamps, frames,
        )

        departures = [s for s in schedule if s["flight_type"] == "departure"]
        assert len(departures) >= 1
        dep = departures[0]
        assert dep["flight_number"] == "DLH200"
        assert dep["origin"] == "KSFO"
        assert dep["status"] == "Departed"

    def test_full_turnaround(self):
        """Aircraft arrives, parks, then departs — creates both schedule entries."""
        frames = {
            "2026-04-03T14:00:00": [
                _make_snap("ghi789", "SWA300", 37.65, -122.40, "2026-04-03T14:00:00",
                           velocity=140, on_ground=False, altitude=2000,
                           vertical_rate=-800, phase="approaching"),
            ],
            "2026-04-03T14:05:00": [
                _make_snap("ghi789", "SWA300", 37.6190, -122.3750, "2026-04-03T14:05:00",
                           velocity=0, on_ground=True, phase="parked"),
            ],
            "2026-04-03T15:30:00": [
                _make_snap("ghi789", "SWA300", 37.625, -122.380, "2026-04-03T15:30:00",
                           velocity=15, on_ground=True, phase="taxi_to_runway"),
            ],
            "2026-04-03T15:35:00": [
                _make_snap("ghi789", "SWA300", 37.630, -122.385, "2026-04-03T15:35:00",
                           velocity=150, on_ground=False, altitude=500,
                           vertical_rate=2000, phase="takeoff"),
            ],
        }
        inferrer, enrichment, timestamps = self._run_inferrer(frames)
        origins = {"ghi789": ("KLAX", "KDEN")}

        schedule = _derive_schedule_from_recording(
            inferrer, enrichment, origins, "KSFO", timestamps, frames,
        )

        arrivals = [s for s in schedule if s["flight_type"] == "arrival"]
        departures = [s for s in schedule if s["flight_type"] == "departure"]
        assert len(arrivals) >= 1, f"Expected arrival, got: {schedule}"
        assert len(departures) >= 1, f"Expected departure, got: {schedule}"
        assert arrivals[0]["origin"] == "KLAX"
        assert departures[0]["status"] == "Departed"

    def test_parked_only(self):
        """Aircraft only seen parked — creates a single entry."""
        frames = {
            "2026-04-03T16:00:00": [
                _make_snap("jkl012", "AAL400", 37.6190, -122.3750, "2026-04-03T16:00:00",
                           velocity=0, on_ground=True, phase="parked"),
            ],
            "2026-04-03T16:05:00": [
                _make_snap("jkl012", "AAL400", 37.6190, -122.3750, "2026-04-03T16:05:00",
                           velocity=0, on_ground=True, phase="parked"),
            ],
        }
        inferrer, enrichment, timestamps = self._run_inferrer(frames)
        origins = {}

        schedule = _derive_schedule_from_recording(
            inferrer, enrichment, origins, "KSFO", timestamps, frames,
        )

        assert len(schedule) >= 1
        assert schedule[0]["flight_number"] == "AAL400"
        assert schedule[0]["status"] == "On Time"

    def test_no_origins_available(self):
        """Schedule works even without origin/destination data."""
        frames = {
            "2026-04-03T16:00:00": [
                _make_snap("xyz999", "FFT500", 37.65, -122.40, "2026-04-03T16:00:00",
                           velocity=140, on_ground=False, altitude=2000,
                           vertical_rate=-800, phase="approaching"),
            ],
            "2026-04-03T16:05:00": [
                _make_snap("xyz999", "FFT500", 37.6190, -122.3750, "2026-04-03T16:05:00",
                           velocity=0, on_ground=True, phase="parked"),
            ],
        }
        inferrer, enrichment, timestamps = self._run_inferrer(frames)

        schedule = _derive_schedule_from_recording(
            inferrer, enrichment, {}, "KSFO", timestamps, frames,
        )

        arrivals = [s for s in schedule if s["flight_type"] == "arrival"]
        assert len(arrivals) >= 1
        assert arrivals[0]["origin"] is None
        assert arrivals[0]["destination"] == "KSFO"

    def test_empty_timestamps(self):
        """Empty recording returns empty schedule."""
        inferrer = OpenSkyEventInferrer([])
        enrichment = inferrer.get_results()
        schedule = _derive_schedule_from_recording(
            inferrer, enrichment, {}, "KSFO", [], {},
        )
        assert schedule == []


# ── Tests: _persist_recording_to_lakebase ───────────────────────────────

class TestPersistRecording:
    """Test that persistence calls Lakebase methods correctly."""

    @patch("app.backend.services.lakebase_service.get_lakebase_service")
    def test_persists_all_data_types(self, mock_get_lakebase):
        mock_lakebase = MagicMock()
        mock_lakebase.is_available = True
        mock_lakebase.insert_flight_snapshots.return_value = 5
        mock_lakebase.insert_gate_events.return_value = 2
        mock_lakebase.insert_phase_transitions.return_value = 3
        mock_lakebase.upsert_schedule.return_value = 4
        mock_get_lakebase.return_value = mock_lakebase

        enrichment = {
            "gate_events": [
                {"time": "2026-04-03T16:00:00", "icao24": "abc", "callsign": "UAL1",
                 "gate": "G1", "event_type": "assign", "aircraft_type": ""},
            ],
            "phase_transitions": [
                {"time": "2026-04-03T16:00:00", "icao24": "abc", "callsign": "UAL1",
                 "from_phase": "taxi_to_gate", "to_phase": "parked",
                 "latitude": 37.0, "longitude": -122.0, "altitude": 0.0,
                 "aircraft_type": "", "assigned_gate": "G1"},
            ],
        }
        snapshots = [
            {"icao24": "abc", "callsign": "UAL1", "latitude": 37.0, "longitude": -122.0,
             "altitude": 0, "velocity": 0, "heading": 90, "vertical_rate": 0,
             "on_ground": True, "phase": "parked", "aircraft_type": "",
             "assigned_gate": "G1", "time": "2026-04-03T16:00:00"},
        ]
        schedule = [{"flight_number": "UAL1", "gate": "G1"}]
        origins = {"abc": ("KJFK", "KSFO")}

        _persist_recording_to_lakebase(
            enrichment, snapshots, schedule, origins, "KSFO", "2026-04-03",
        )

        mock_lakebase.insert_flight_snapshots.assert_called_once()
        mock_lakebase.insert_gate_events.assert_called_once()
        mock_lakebase.insert_phase_transitions.assert_called_once()
        mock_lakebase.upsert_schedule.assert_called_once_with(schedule, airport_icao="KSFO")

        # Verify session_id is deterministic
        call_args = mock_lakebase.insert_flight_snapshots.call_args
        assert call_args[0][1] == "recorded-KSFO-2026-04-03"

    @patch("app.backend.services.lakebase_service.get_lakebase_service")
    def test_skips_when_lakebase_unavailable(self, mock_get_lakebase):
        mock_lakebase = MagicMock()
        mock_lakebase.is_available = False
        mock_get_lakebase.return_value = mock_lakebase

        _persist_recording_to_lakebase(
            {"gate_events": [], "phase_transitions": []}, [], [], {}, "KSFO", "2026-04-03",
        )

        mock_lakebase.insert_flight_snapshots.assert_not_called()

    @patch("app.backend.services.lakebase_service.get_lakebase_service")
    def test_snapshot_data_source_is_opensky_recorded(self, mock_get_lakebase):
        mock_lakebase = MagicMock()
        mock_lakebase.is_available = True
        mock_lakebase.insert_flight_snapshots.return_value = 1
        mock_lakebase.insert_gate_events.return_value = 0
        mock_lakebase.insert_phase_transitions.return_value = 0
        mock_lakebase.upsert_schedule.return_value = 0
        mock_get_lakebase.return_value = mock_lakebase

        snapshots = [
            {"icao24": "abc", "time": "2026-04-03T16:00:00", "phase": "parked"},
        ]

        _persist_recording_to_lakebase(
            {"gate_events": [], "phase_transitions": []},
            snapshots, [], {}, "KSFO", "2026-04-03",
        )

        inserted = mock_lakebase.insert_flight_snapshots.call_args[0][0]
        assert inserted[0]["data_source"] == "opensky_recorded"

    @patch("app.backend.services.lakebase_service.get_lakebase_service")
    def test_event_time_mapping(self, mock_get_lakebase):
        mock_lakebase = MagicMock()
        mock_lakebase.is_available = True
        mock_lakebase.insert_flight_snapshots.return_value = 0
        mock_lakebase.insert_gate_events.return_value = 1
        mock_lakebase.insert_phase_transitions.return_value = 1
        mock_lakebase.upsert_schedule.return_value = 0
        mock_get_lakebase.return_value = mock_lakebase

        enrichment = {
            "gate_events": [
                {"time": "2026-04-03T16:00:00", "icao24": "abc", "callsign": "X",
                 "gate": "G1", "event_type": "assign", "aircraft_type": ""},
            ],
            "phase_transitions": [
                {"time": "2026-04-03T16:01:00", "icao24": "abc", "callsign": "X",
                 "from_phase": "taxi", "to_phase": "parked",
                 "latitude": 0, "longitude": 0, "altitude": 0,
                 "aircraft_type": "", "assigned_gate": "G1"},
            ],
        }

        _persist_recording_to_lakebase(
            enrichment, [], [], {}, "KSFO", "2026-04-03",
        )

        gate_events = mock_lakebase.insert_gate_events.call_args[0][0]
        assert gate_events[0]["event_time"] == "2026-04-03T16:00:00"

        transitions = mock_lakebase.insert_phase_transitions.call_args[0][0]
        assert transitions[0]["event_time"] == "2026-04-03T16:01:00"

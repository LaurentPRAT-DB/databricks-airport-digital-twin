"""Tests for OBT feature extraction from recorded OpenSky data."""

import pytest
from datetime import datetime, timezone

from src.ml.obt_features import (
    extract_training_data_from_recording,
    _sample_calibrated_delay,
)


def _make_recording_data(
    n_flights: int = 2,
    with_weather: bool = True,
    with_aircraft_type: bool = True,
) -> dict:
    """Build a minimal recording_data dict for testing."""
    schedule = []
    phase_transitions = []
    gate_events = []

    for i in range(n_flights):
        icao24 = f"abc{i:03d}"
        callsign = f"UAL{100+i}"
        parked_time = datetime(2026, 4, 6, 14 + i, 0, 0, tzinfo=timezone.utc)
        pushback_time = datetime(2026, 4, 6, 14 + i, 35, 0, tzinfo=timezone.utc)

        schedule.append({
            "flight_number": callsign,
            "airline_code": "UAL",
            "origin": "KJFK",
            "destination": "KSFO",
            "aircraft_type": "B738" if with_aircraft_type else "",
            "scheduled_time": parked_time.isoformat(),
            "delay_minutes": 0,
            "direction": "arrival",
        })

        phase_transitions.extend([
            {
                "time": parked_time.isoformat(),
                "icao24": icao24,
                "callsign": callsign,
                "from_phase": "taxi_in",
                "to_phase": "parked",
                "aircraft_type": "B738" if with_aircraft_type else "",
            },
            {
                "time": pushback_time.isoformat(),
                "icao24": icao24,
                "callsign": callsign,
                "from_phase": "parked",
                "to_phase": "pushback",
                "aircraft_type": "B738" if with_aircraft_type else "",
            },
        ])

        gate_events.append({
            "time": parked_time.isoformat(),
            "icao24": icao24,
            "gate": f"B{30+i}",
            "event_type": "assign",
        })

    weather_snapshots = []
    if with_weather:
        weather_snapshots = [
            {
                "time": "2026-04-06T13:56:00+00:00",
                "wind_speed_kts": 12,
                "wind_gust_kts": None,
                "wind_direction": 280,
                "visibility_sm": 10.0,
                "flight_category": "VFR",
                "temperature_c": 14,
                "dewpoint_c": 8,
                "raw_metar": "KSFO 061356Z 28012KT 10SM FEW020 14/08 A3012",
            },
            {
                "time": "2026-04-06T14:56:00+00:00",
                "wind_speed_kts": 15,
                "wind_gust_kts": 22,
                "wind_direction": 290,
                "visibility_sm": 8.0,
                "flight_category": "VFR",
                "temperature_c": 15,
                "dewpoint_c": 9,
                "raw_metar": "KSFO 061456Z 29015G22KT 8SM SCT025 15/09 A3014",
            },
        ]

    return {
        "config": {
            "airport": "KSFO",
            "source": "opensky_recorded",
            "date": "2026-04-06",
        },
        "schedule": schedule,
        "phase_transitions": phase_transitions,
        "gate_events": gate_events,
        "weather_snapshots": weather_snapshots,
        "scenario_events": [],
    }


class TestExtractTrainingDataFromRecording:
    def test_basic_extraction(self):
        data = _make_recording_data(n_flights=2)
        results = extract_training_data_from_recording(data)
        assert len(results) == 2

    def test_turnaround_duration(self):
        data = _make_recording_data(n_flights=1)
        results = extract_training_data_from_recording(data)
        assert len(results) == 1
        # 35 minutes between parked and pushback
        assert results[0]["target"] == pytest.approx(35.0)

    def test_source_is_recorded(self):
        data = _make_recording_data(n_flights=1)
        results = extract_training_data_from_recording(data)
        assert results[0]["source"] == "recorded"

    def test_features_structure(self):
        data = _make_recording_data(n_flights=1)
        results = extract_training_data_from_recording(data)
        features = results[0]["features"]

        # All OBTFeatureSet fields present
        expected_keys = {
            "aircraft_category", "airline_code", "hour_of_day",
            "is_international", "arrival_delay_min", "gate_id_prefix",
            "is_remote_stand", "concurrent_gate_ops", "wind_speed_kt",
            "visibility_sm", "has_active_ground_stop",
            "scheduled_departure_hour", "airport_code", "day_of_week",
            "hour_sin", "hour_cos", "is_weather_scenario",
            "scheduled_buffer_min", "is_hub_connecting",
        }
        assert set(features.keys()) == expected_keys

    def test_recorded_defaults(self):
        data = _make_recording_data(n_flights=1)
        results = extract_training_data_from_recording(data)
        features = results[0]["features"]

        # Delay features are now sampled from calibration (may be 0 or positive)
        assert features["arrival_delay_min"] >= 0.0
        assert features["is_weather_scenario"] is False
        assert features["has_active_ground_stop"] is False

    def test_weather_features_from_metar(self):
        data = _make_recording_data(n_flights=1, with_weather=True)
        results = extract_training_data_from_recording(data)
        features = results[0]["features"]

        # First flight parked at 14:00, nearest METAR is 13:56 (wind=12)
        assert features["wind_speed_kt"] == 12.0
        assert features["visibility_sm"] == 10.0

    def test_no_weather_defaults(self):
        data = _make_recording_data(n_flights=1, with_weather=False)
        results = extract_training_data_from_recording(data)
        features = results[0]["features"]

        assert features["wind_speed_kt"] == 0.0
        assert features["visibility_sm"] == 10.0

    def test_aircraft_category(self):
        data = _make_recording_data(n_flights=1, with_aircraft_type=True)
        results = extract_training_data_from_recording(data)
        features = results[0]["features"]
        assert features["aircraft_category"] == "narrow"

    def test_missing_aircraft_type_defaults(self):
        data = _make_recording_data(n_flights=1, with_aircraft_type=False)
        results = extract_training_data_from_recording(data)
        features = results[0]["features"]
        assert features["aircraft_category"] == "narrow"

    def test_gate_prefix(self):
        data = _make_recording_data(n_flights=1)
        results = extract_training_data_from_recording(data)
        features = results[0]["features"]
        assert features["gate_id_prefix"] == "B"

    def test_airline_code(self):
        data = _make_recording_data(n_flights=1)
        results = extract_training_data_from_recording(data)
        features = results[0]["features"]
        assert features["airline_code"] == "UAL"

    def test_airport_code(self):
        data = _make_recording_data(n_flights=1)
        results = extract_training_data_from_recording(data)
        assert results[0]["airport"] == "KSFO"
        assert results[0]["features"]["airport_code"] == "KSFO"

    def test_filters_short_turnaround(self):
        """Turnaround < 5 min should be filtered out."""
        data = _make_recording_data(n_flights=1)
        # Override pushback to 3 min after parked
        data["phase_transitions"][1]["time"] = "2026-04-06T14:03:00+00:00"
        results = extract_training_data_from_recording(data)
        assert len(results) == 0

    def test_filters_long_turnaround(self):
        """Turnaround > 600 min should be filtered out."""
        data = _make_recording_data(n_flights=1)
        # Override pushback to 12 hours after parked
        data["phase_transitions"][1]["time"] = "2026-04-07T02:00:00+00:00"
        results = extract_training_data_from_recording(data)
        assert len(results) == 0

    def test_empty_data(self):
        data = {
            "config": {"airport": "KSFO"},
            "schedule": [],
            "phase_transitions": [],
            "gate_events": [],
            "weather_snapshots": [],
            "scenario_events": [],
        }
        results = extract_training_data_from_recording(data)
        assert results == []

    def test_only_parked_no_pushback(self):
        """Flights with only parked transition (no pushback) should be skipped."""
        data = _make_recording_data(n_flights=1)
        # Remove the pushback transition
        data["phase_transitions"] = [
            pt for pt in data["phase_transitions"]
            if pt["to_phase"] != "pushback"
        ]
        results = extract_training_data_from_recording(data)
        assert len(results) == 0


class TestCalibratedDelaySampling:
    """Tests for calibrated delay sampling from airport profiles."""

    def test_sample_returns_tuple(self):
        delay, buffer = _sample_calibrated_delay("SFO")
        assert isinstance(delay, float)
        assert isinstance(buffer, float)

    def test_delay_non_negative(self):
        for _ in range(100):
            delay, buffer = _sample_calibrated_delay("ATL")
            assert delay >= 0.0

    def test_buffer_non_positive_when_delayed(self):
        """When delayed, buffer should be negative (arrived late)."""
        for _ in range(200):
            delay, buffer = _sample_calibrated_delay("ATL")
            if delay > 0:
                assert buffer < 0, "Buffer should be negative when delayed"

    def test_delay_rate_nonzero_fraction(self):
        """Over many samples, some fraction should be delayed (not all zero)."""
        n = 2000
        delayed = sum(1 for _ in range(n) if _sample_calibrated_delay("ATL")[0] > 0)
        rate = delayed / n
        # ATL calibration profile has ~9.5% delay rate — just verify it's working
        assert 0.03 < rate < 0.50, f"Delay rate {rate:.2f} outside expected range"

    def test_unknown_airport_uses_fallback(self):
        """Unknown airport should still produce valid output (fallback profile)."""
        delay, buffer = _sample_calibrated_delay("ZZZ")
        assert isinstance(delay, float)

    def test_empty_airport_code(self):
        delay, buffer = _sample_calibrated_delay("")
        assert isinstance(delay, float)

    def test_delay_magnitude_reasonable(self):
        """Sampled delays should be between 5 and 120 minutes."""
        for _ in range(200):
            delay, _ = _sample_calibrated_delay("JFK")
            if delay > 0:
                assert 5 <= delay <= 120

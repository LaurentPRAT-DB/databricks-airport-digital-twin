"""Tests for FLIFO → simulation schedule queue."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from src.ingestion._schedule_queue import ScheduleQueue


def _make_flight(fn, flight_type, status, minutes_from_now):
    now = datetime.now(timezone.utc)
    sched = (now + timedelta(minutes=minutes_from_now)).isoformat()
    return {
        "flight_number": fn,
        "flight_type": flight_type,
        "status": status,
        "origin": "LAX" if flight_type == "arrival" else "SFO",
        "destination": "SFO" if flight_type == "arrival" else "JFK",
        "scheduled_time": sched,
        "aircraft_type": "A320",
    }


class TestScheduleQueue:
    def test_empty_queue_not_active(self):
        q = ScheduleQueue()
        assert q.is_active is False
        assert q.next_arrival() is None
        assert q.next_departure() is None

    def test_pop_arrival_within_window(self):
        q = ScheduleQueue()
        q._available = True
        q._rebuild_queues([
            _make_flight("UA100", "arrival", "on_time", 30),
        ])
        assert q.is_active is True

        flight = q.next_arrival()
        assert flight is not None
        assert flight["flight_number"] == "UA100"

    def test_arrival_outside_window_not_popped(self):
        q = ScheduleQueue()
        q._available = True
        q._rebuild_queues([
            _make_flight("UA200", "arrival", "scheduled", 60),
        ])

        flight = q.next_arrival()
        assert flight is None

    def test_departure_within_window(self):
        q = ScheduleQueue()
        q._available = True
        q._rebuild_queues([
            _make_flight("DL300", "departure", "boarding", 15),
        ])

        flight = q.next_departure()
        assert flight is not None
        assert flight["flight_number"] == "DL300"

    def test_no_duplicate_spawn(self):
        q = ScheduleQueue()
        q._available = True
        q._rebuild_queues([
            _make_flight("UA100", "arrival", "on_time", 20),
        ])

        f1 = q.next_arrival()
        assert f1 is not None

        # Rebuild again with same flight
        q._rebuild_queues([
            _make_flight("UA100", "arrival", "on_time", 20),
        ])
        f2 = q.next_arrival()
        assert f2 is None

    def test_mark_spawned_prevents_pop(self):
        q = ScheduleQueue()
        q._available = True
        q.mark_spawned("BA456")
        q._rebuild_queues([
            _make_flight("BA456", "arrival", "on_time", 10),
        ])

        assert q.next_arrival() is None

    def test_past_flights_within_limit_still_spawn(self):
        q = ScheduleQueue()
        q._available = True
        q._rebuild_queues([
            _make_flight("EK500", "arrival", "arrived", -30),
        ])

        flight = q.next_arrival()
        assert flight is not None
        assert flight["flight_number"] == "EK500"

    def test_very_old_flights_skipped(self):
        q = ScheduleQueue()
        q._available = True
        q._rebuild_queues([
            _make_flight("OLD1", "arrival", "arrived", -90),
        ])

        flight = q.next_arrival()
        assert flight is None

    def test_phase_mapping_arrival(self):
        q = ScheduleQueue()
        assert q.get_phase_for_flight({"flight_type": "arrival", "status": "on_time"}) == "APPROACHING"
        assert q.get_phase_for_flight({"flight_type": "arrival", "status": "arrived"}) == "PARKED"
        assert q.get_phase_for_flight({"flight_type": "arrival", "status": "delayed"}) == "APPROACHING"

    def test_phase_mapping_departure(self):
        q = ScheduleQueue()
        assert q.get_phase_for_flight({"flight_type": "departure", "status": "boarding"}) == "PARKED"
        assert q.get_phase_for_flight({"flight_type": "departure", "status": "departed"}) == "TAXI_TO_RUNWAY"
        assert q.get_phase_for_flight({"flight_type": "departure", "status": "scheduled"}) == "PARKED"

    def test_sorted_order_respects_time(self):
        q = ScheduleQueue()
        q._available = True
        q._rebuild_queues([
            _make_flight("LATE1", "arrival", "on_time", 40),
            _make_flight("SOON1", "arrival", "on_time", 10),
            _make_flight("MID1", "arrival", "on_time", 25),
        ])

        f1 = q.next_arrival()
        assert f1["flight_number"] == "SOON1"
        f2 = q.next_arrival()
        assert f2["flight_number"] == "MID1"
        f3 = q.next_arrival()
        assert f3["flight_number"] == "LATE1"

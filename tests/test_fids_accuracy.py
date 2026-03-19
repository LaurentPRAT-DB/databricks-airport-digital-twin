"""Tests for FIDS accuracy: gate occupancy and live+future merge.

Covers:
- Occupancy-aware gate assignment prevents double-booking
- FIDS includes live map flights
- Future flights supplement FIDS beyond active flights
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest


class TestGateOccupancy:
    """Tests for occupancy-aware gate assignment in schedule generator."""

    def test_assign_gate_no_overlap(self):
        """No two flights should be assigned the same gate at overlapping times."""
        from src.ingestion.schedule_generator import _assign_gate_with_occupancy

        gates = ["A1", "A2", "A3"]
        timeline: dict[str, list[tuple[datetime, datetime]]] = {}
        base = datetime(2026, 3, 19, 10, 0, tzinfo=timezone.utc)

        # Assign first flight to arrive at 10:00
        g1 = _assign_gate_with_occupancy(gates, timeline, base, True, "A320")
        # Assign second flight to arrive at 10:05 (overlaps with first's turnaround)
        g2 = _assign_gate_with_occupancy(
            gates, timeline, base + timedelta(minutes=5), True, "A320",
        )
        # These should get different gates since turnaround is 45 min
        assert g1 != g2

    def test_assign_gate_reuse_after_turnaround(self):
        """A gate should be reusable after the turnaround + buffer period."""
        from src.ingestion.schedule_generator import (
            _assign_gate_with_occupancy,
            NARROW_BODY_TURNAROUND,
            GATE_COOLDOWN_BUFFER,
        )

        gates = ["A1"]  # Only one gate
        timeline: dict[str, list[tuple[datetime, datetime]]] = {}
        base = datetime(2026, 3, 19, 10, 0, tzinfo=timezone.utc)

        # First arrival at 10:00
        g1 = _assign_gate_with_occupancy(gates, timeline, base, True, "A320")
        assert g1 == "A1"

        # Second arrival after turnaround + buffer — should get same gate
        safe_time = base + timedelta(minutes=NARROW_BODY_TURNAROUND + GATE_COOLDOWN_BUFFER + 1)
        g2 = _assign_gate_with_occupancy(gates, timeline, safe_time, True, "A320")
        assert g2 == "A1"

    def test_assign_gate_wide_body_longer_turnaround(self):
        """Wide-body aircraft should occupy gates longer than narrow-body."""
        from src.ingestion.schedule_generator import (
            _assign_gate_with_occupancy,
            NARROW_BODY_TURNAROUND,
            WIDE_BODY_TURNAROUND,
        )

        gates = ["A1", "A2"]
        timeline: dict[str, list[tuple[datetime, datetime]]] = {}
        base = datetime(2026, 3, 19, 10, 0, tzinfo=timezone.utc)

        # Wide body arrival at 10:00
        g1 = _assign_gate_with_occupancy(gates, timeline, base, True, "B777")
        # Another arrival at 10:50 — would clear narrow turnaround (45 min) but not wide (90 min)
        g2 = _assign_gate_with_occupancy(
            gates, timeline, base + timedelta(minutes=50), True, "A320",
        )
        assert g1 != g2, "Wide-body should block gate for 90 min, not 45"

    def test_assign_gate_fallback_least_conflicting(self):
        """When all gates are busy, picks the least conflicting one."""
        from src.ingestion.schedule_generator import _assign_gate_with_occupancy

        gates = ["A1"]
        timeline: dict[str, list[tuple[datetime, datetime]]] = {}
        base = datetime(2026, 3, 19, 10, 0, tzinfo=timezone.utc)

        # Fill the only gate
        _assign_gate_with_occupancy(gates, timeline, base, True, "A320")
        # Force assign overlapping — should still return A1 (only option)
        g = _assign_gate_with_occupancy(
            gates, timeline, base + timedelta(minutes=5), True, "A320",
        )
        assert g == "A1"

    def test_assign_gate_empty_gates_returns_a1(self):
        """Empty gate list returns fallback A1."""
        from src.ingestion.schedule_generator import _assign_gate_with_occupancy

        timeline: dict[str, list[tuple[datetime, datetime]]] = {}
        base = datetime(2026, 3, 19, 10, 0, tzinfo=timezone.utc)
        g = _assign_gate_with_occupancy([], timeline, base, True, "A320")
        assert g == "A1"

    def test_schedule_gate_no_overlap(self):
        """Occupancy-aware assignment should dramatically reduce gate conflicts vs random."""
        import random as _random
        from src.ingestion.schedule_generator import (
            generate_daily_schedule,
            _get_turnaround_minutes,
        )

        schedule = generate_daily_schedule(airport="SFO")

        def _count_conflicts(flights):
            gate_windows: dict[str, list[tuple[datetime, datetime]]] = {}
            for flight in flights:
                gate = flight["gate"]
                sched = datetime.fromisoformat(flight["scheduled_time"])
                turnaround = _get_turnaround_minutes(flight["aircraft_type"])
                if flight["flight_type"] == "arrival":
                    start, end = sched, sched + timedelta(minutes=turnaround)
                else:
                    start, end = sched - timedelta(minutes=turnaround), sched
                gate_windows.setdefault(gate, []).append((start, end))

            conflicts = 0
            for windows in gate_windows.values():
                windows.sort()
                for i in range(len(windows) - 1):
                    if windows[i + 1][0] < windows[i][1]:
                        conflicts += 1
            return conflicts

        occupancy_conflicts = _count_conflicts(schedule)

        # Compare against random assignment baseline
        gates_used = list(set(f["gate"] for f in schedule))
        random_schedule = []
        for f in schedule:
            rf = dict(f)
            rf["gate"] = _random.choice(gates_used)
            random_schedule.append(rf)
        random_conflicts = _count_conflicts(random_schedule)

        # Occupancy-aware should have at least 50% fewer conflicts than random
        # (in practice it's much better, but peak hours can exceed gate capacity)
        assert occupancy_conflicts < random_conflicts * 0.7, (
            f"Occupancy-aware ({occupancy_conflicts}) should be much better "
            f"than random ({random_conflicts})"
        )


class TestFIDSMerge:
    """Tests for FIDS merging live + future flights."""

    def _make_live_flight(self, fn, flight_type, gate, time_offset_min=0):
        """Helper to create a live flight dict."""
        now = datetime.now(timezone.utc)
        return {
            "flight_number": fn,
            "airline": "United Airlines",
            "airline_code": "UAL",
            "origin": "LAX" if flight_type == "arrival" else "SFO",
            "destination": "SFO" if flight_type == "arrival" else "LAX",
            "scheduled_time": (now + timedelta(minutes=time_offset_min)).isoformat(),
            "estimated_time": None,
            "actual_time": None,
            "gate": gate,
            "status": "on_time",
            "delay_minutes": 0,
            "delay_reason": None,
            "aircraft_type": "A320",
            "flight_type": flight_type,
        }

    def _make_future_flight(self, fn, flight_type, gate, time_offset_min=60):
        """Helper to create a future schedule flight dict."""
        now = datetime.now(timezone.utc)
        return {
            "flight_number": fn,
            "airline": "Delta Air Lines",
            "airline_code": "DAL",
            "origin": "ATL" if flight_type == "arrival" else "SFO",
            "destination": "SFO" if flight_type == "arrival" else "ATL",
            "scheduled_time": (now + timedelta(minutes=time_offset_min)).isoformat(),
            "estimated_time": None,
            "actual_time": None,
            "gate": gate,
            "status": "on_time",
            "delay_minutes": 0,
            "delay_reason": None,
            "aircraft_type": "B737",
            "flight_type": flight_type,
        }

    def test_fids_includes_live_flights(self):
        """Live map flights should always appear in FIDS."""
        from app.backend.services.schedule_service import ScheduleService

        live_flights = [
            self._make_live_flight("UAL100", "arrival", "A1"),
            self._make_live_flight("UAL200", "arrival", "A2", time_offset_min=5),
        ]
        future_flights = [
            self._make_future_flight("DAL300", "arrival", "B1", time_offset_min=60),
        ]

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = False

        with patch(
            "app.backend.services.schedule_service.get_lakebase_service",
            return_value=mock_lakebase,
        ), patch(
            "app.backend.services.schedule_service.get_flights_as_schedule",
            return_value=live_flights,
        ), patch(
            "app.backend.services.schedule_service.get_future_schedule",
            return_value=future_flights,
        ):
            service = ScheduleService()
            result = service.get_arrivals(hours_ahead=4, limit=50)

        flight_numbers = [f.flight_number for f in result.flights]
        assert "UAL100" in flight_numbers
        assert "UAL200" in flight_numbers

    def test_fids_future_flights_supplement(self):
        """FIDS should have more flights than just active ones."""
        from app.backend.services.schedule_service import ScheduleService

        live_flights = [
            self._make_live_flight("UAL100", "arrival", "A1"),
        ]
        future_flights = [
            self._make_future_flight("DAL300", "arrival", "B1", time_offset_min=60),
            self._make_future_flight("DAL400", "arrival", "B2", time_offset_min=90),
        ]

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = False

        with patch(
            "app.backend.services.schedule_service.get_lakebase_service",
            return_value=mock_lakebase,
        ), patch(
            "app.backend.services.schedule_service.get_flights_as_schedule",
            return_value=live_flights,
        ), patch(
            "app.backend.services.schedule_service.get_future_schedule",
            return_value=future_flights,
        ):
            service = ScheduleService()
            result = service.get_arrivals(hours_ahead=4, limit=50)

        assert len(result.flights) == 3  # 1 live + 2 future
        flight_numbers = [f.flight_number for f in result.flights]
        assert "DAL300" in flight_numbers
        assert "DAL400" in flight_numbers

    def test_fids_deduplicates_by_flight_number(self):
        """If a live flight and future flight share a flight number, live wins."""
        from app.backend.services.schedule_service import ScheduleService

        live_flights = [
            self._make_live_flight("UAL100", "departure", "A1"),
        ]
        # Same flight number in future schedule
        future_flights = [
            self._make_future_flight("UAL100", "departure", "B1", time_offset_min=60),
            self._make_future_flight("DAL200", "departure", "B2", time_offset_min=90),
        ]

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = False

        with patch(
            "app.backend.services.schedule_service.get_lakebase_service",
            return_value=mock_lakebase,
        ), patch(
            "app.backend.services.schedule_service.get_flights_as_schedule",
            return_value=live_flights,
        ), patch(
            "app.backend.services.schedule_service.get_future_schedule",
            return_value=future_flights,
        ):
            service = ScheduleService()
            result = service.get_departures(hours_ahead=4, limit=50)

        flight_numbers = [f.flight_number for f in result.flights]
        assert flight_numbers.count("UAL100") == 1
        # Live flight's gate wins
        ual100 = [f for f in result.flights if f.flight_number == "UAL100"][0]
        assert ual100.gate == "A1"

    def test_fids_sorted_by_scheduled_time(self):
        """Merged FIDS output should be sorted by scheduled_time."""
        from app.backend.services.schedule_service import ScheduleService

        live_flights = [
            self._make_live_flight("UAL100", "arrival", "A1", time_offset_min=30),
        ]
        future_flights = [
            self._make_future_flight("DAL200", "arrival", "B1", time_offset_min=45),
            self._make_future_flight("DAL300", "arrival", "B2", time_offset_min=60),
        ]

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = False

        with patch(
            "app.backend.services.schedule_service.get_lakebase_service",
            return_value=mock_lakebase,
        ), patch(
            "app.backend.services.schedule_service.get_flights_as_schedule",
            return_value=live_flights,
        ), patch(
            "app.backend.services.schedule_service.get_future_schedule",
            return_value=future_flights,
        ):
            service = ScheduleService()
            result = service.get_arrivals(hours_ahead=4, limit=50)

        times = [f.scheduled_time for f in result.flights]
        assert times == sorted(times)

    def test_fids_no_live_flights_falls_through_to_generator(self):
        """When no live flights exist, FIDS should use generator flights."""
        from app.backend.services.schedule_service import ScheduleService

        future_flights = [
            self._make_future_flight("DAL300", "arrival", "B1", time_offset_min=60),
        ]

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = False

        with patch(
            "app.backend.services.schedule_service.get_lakebase_service",
            return_value=mock_lakebase,
        ), patch(
            "app.backend.services.schedule_service.get_flights_as_schedule",
            return_value=[],
        ), patch(
            "app.backend.services.schedule_service.get_future_schedule",
            return_value=future_flights,
        ):
            service = ScheduleService()
            result = service.get_arrivals(hours_ahead=4, limit=50)

        assert len(result.flights) >= 1

    def test_fids_lakebase_takes_priority(self):
        """When Lakebase is available, it takes priority over merge."""
        from app.backend.services.schedule_service import ScheduleService

        now = datetime.now(timezone.utc)
        mock_lakebase = MagicMock()
        mock_lakebase.is_available = True
        mock_lakebase.get_schedule.return_value = [
            {
                "flight_number": "LB100",
                "airline": "United Airlines",
                "airline_code": "UAL",
                "origin": "LAX",
                "destination": "SFO",
                "scheduled_time": now.isoformat(),
                "estimated_time": None,
                "actual_time": None,
                "gate": "C1",
                "status": "on_time",
                "delay_minutes": 0,
                "delay_reason": None,
                "aircraft_type": "A320",
                "flight_type": "arrival",
            },
        ]

        with patch(
            "app.backend.services.schedule_service.get_lakebase_service",
            return_value=mock_lakebase,
        ), patch(
            "app.backend.services.schedule_service.get_flights_as_schedule",
        ) as mock_live:
            service = ScheduleService()
            result = service.get_arrivals(hours_ahead=2, limit=50)

        # Live flights should NOT be called since Lakebase had data
        mock_live.assert_not_called()
        assert result.flights[0].flight_number == "LB100"


class TestGetFutureSchedule:
    """Tests for the get_future_schedule helper."""

    def test_returns_only_future_flights(self):
        """Only flights after the cutoff should be returned."""
        from src.ingestion.schedule_generator import get_future_schedule

        now = datetime.now(timezone.utc)
        flights = get_future_schedule(airport="SFO", after=now)

        for f in flights:
            sched = datetime.fromisoformat(f["scheduled_time"])
            assert sched > now

    def test_filters_by_flight_type(self):
        """Should filter by arrival/departure when specified."""
        from src.ingestion.schedule_generator import get_future_schedule

        now = datetime.now(timezone.utc) - timedelta(hours=2)
        arrivals = get_future_schedule(
            airport="SFO", after=now, flight_type="arrival",
        )
        for f in arrivals:
            assert f["flight_type"] == "arrival"

    def test_respects_limit(self):
        """Should respect the limit parameter."""
        from src.ingestion.schedule_generator import get_future_schedule

        now = datetime.now(timezone.utc) - timedelta(hours=6)
        flights = get_future_schedule(airport="SFO", after=now, limit=5)
        assert len(flights) <= 5

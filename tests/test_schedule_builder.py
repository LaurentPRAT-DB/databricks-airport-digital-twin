"""Tests for ScheduleBuilder — flight schedule generation in isolation.

Tests that schedule generation produces correct structure, counts,
distribution, and determinism without instantiating SimulationEngine.
"""

import random
from datetime import datetime, timezone

import pytest

from src.calibration.profile import AirportProfile
from src.simulation.config import SimulationConfig
from src.simulation.schedule_builder import ScheduleBuilder


def _quick_config(**overrides) -> SimulationConfig:
    defaults = dict(
        airport="SFO",
        arrivals=20,
        departures=20,
        duration_hours=6.0,
        seed=42,
    )
    defaults.update(overrides)
    return SimulationConfig(**defaults)


def _default_profile() -> AirportProfile:
    from src.calibration.profile import AirportProfileLoader
    loader = AirportProfileLoader()
    return loader.get_profile("SFO")


class TestArrivalGeneration:

    def test_arrivals_match_config_count(self):
        config = _quick_config(arrivals=50, departures=0)
        builder = ScheduleBuilder(config, _default_profile())
        schedule = builder.build()
        arrivals = [f for f in schedule if f["flight_type"] == "arrival"]
        assert len(arrivals) == 50

    def test_arrivals_have_required_fields(self):
        config = _quick_config(arrivals=5, departures=0)
        builder = ScheduleBuilder(config, _default_profile())
        schedule = builder.build()
        required = {"flight_number", "airline", "airline_code", "origin",
                    "destination", "aircraft_type", "flight_type", "scheduled_time",
                    "delay_minutes", "delay_code", "delay_reason"}
        for flight in schedule:
            assert required.issubset(flight.keys()), f"Missing fields: {required - flight.keys()}"

    def test_arrivals_destination_is_local_airport(self):
        config = _quick_config(airport="LAX", arrivals=10, departures=0)
        builder = ScheduleBuilder(config, _default_profile())
        schedule = builder.build()
        for flight in schedule:
            if flight["flight_type"] == "arrival":
                assert flight["destination"] == "LAX"


class TestDepartureLinkedToArrival:

    def test_departures_linked_to_arrivals(self):
        config = _quick_config(arrivals=15, departures=15)
        builder = ScheduleBuilder(config, _default_profile())
        schedule = builder.build()
        departures = [f for f in schedule if f["flight_type"] == "departure"]
        linked = [d for d in departures if "linked_arrival" in d]
        assert len(linked) > 0

    def test_linked_departure_after_arrival(self):
        config = _quick_config(arrivals=10, departures=10, seed=123)
        builder = ScheduleBuilder(config, _default_profile())
        schedule = builder.build()
        arrivals_by_num = {f["flight_number"]: f for f in schedule if f["flight_type"] == "arrival"}
        departures = [f for f in schedule if f["flight_type"] == "departure" and "linked_arrival" in f]
        for dep in departures:
            arr = arrivals_by_num.get(dep["linked_arrival"])
            if arr:
                assert dep["scheduled_time"] >= arr["scheduled_time"]


class TestSurplusDepartures:

    def test_surplus_departures_in_early_window(self):
        config = _quick_config(arrivals=5, departures=20, duration_hours=8.0, seed=99)
        builder = ScheduleBuilder(config, _default_profile())
        schedule = builder.build()
        departures = [f for f in schedule if f["flight_type"] == "departure"]
        unlinked = [d for d in departures if "linked_arrival" not in d]
        assert len(unlinked) > 0
        start = config.effective_start_time()
        for dep in unlinked:
            dep_time = datetime.fromisoformat(dep["scheduled_time"])
            hours_after_start = (dep_time - start).total_seconds() / 3600
            assert hours_after_start <= 2.0


class TestScheduleOrdering:

    def test_schedule_sorted_by_time(self):
        config = _quick_config(arrivals=30, departures=30)
        builder = ScheduleBuilder(config, _default_profile())
        schedule = builder.build()
        times = [f["scheduled_time"] for f in schedule]
        assert times == sorted(times)


class TestHourlyDistribution:

    def test_hourly_distribution_follows_profile(self):
        config = _quick_config(arrivals=100, departures=0, duration_hours=24.0, seed=7)
        builder = ScheduleBuilder(config, _default_profile())
        schedule = builder.build()
        start = config.effective_start_time()
        hour_counts = [0] * 24
        for f in schedule:
            t = datetime.fromisoformat(f["scheduled_time"])
            h = int((t - start).total_seconds() // 3600)
            if 0 <= h < 24:
                hour_counts[h] += 1
        # Flights should NOT be uniformly distributed (profile has peaks)
        assert max(hour_counts) > 2 * min(hour_counts) or min(hour_counts) == 0


class TestFighterSorties:

    def test_fighter_sorties_only_for_ukrainian_airports(self):
        # SFO is not Ukrainian — no sorties
        config = _quick_config(airport="SFO", arrivals=10, departures=10)
        builder = ScheduleBuilder(config, _default_profile())
        schedule = builder.build()
        fighters = [f for f in schedule if f.get("airline_code") == "UAF"]
        assert len(fighters) == 0

    def test_fighter_sorties_for_ukrainian_airport(self):
        # KBP (Kyiv Boryspil) is Ukrainian
        config = _quick_config(airport="KBP", arrivals=10, departures=10, seed=42)
        profile = _default_profile()  # generic profile is fine for this test
        builder = ScheduleBuilder(config, profile)
        schedule = builder.build()
        fighters = [f for f in schedule if f.get("airline_code") == "UAF"]
        assert len(fighters) > 0
        for f in fighters:
            assert f.get("scenario_injected") is True


class TestDeterminism:

    def test_deterministic_with_seed(self):
        config = _quick_config(arrivals=15, departures=15, seed=77)
        profile = _default_profile()

        random.seed(77)
        builder1 = ScheduleBuilder(config, profile)
        schedule1 = builder1.build()

        random.seed(77)
        builder2 = ScheduleBuilder(config, profile)
        schedule2 = builder2.build()

        assert len(schedule1) == len(schedule2)
        for f1, f2 in zip(schedule1, schedule2):
            assert f1["flight_number"] == f2["flight_number"]
            assert f1["scheduled_time"] == f2["scheduled_time"]


class TestExtensibility:

    def test_custom_subclass_override(self):
        """Subclass ScheduleBuilder and override _generate_arrivals."""

        class FixedArrivalBuilder(ScheduleBuilder):
            def _generate_arrivals(self):
                start = self.config.effective_start_time()
                return [{
                    "flight_number": "FIX001",
                    "airline": "Test Air",
                    "airline_code": "TST",
                    "origin": "LAX",
                    "destination": self.config.airport,
                    "aircraft_type": "B737",
                    "flight_type": "arrival",
                    "scheduled_time": start.isoformat(),
                    "delay_minutes": 0,
                    "delay_code": None,
                    "delay_reason": None,
                }]

        config = _quick_config(arrivals=50, departures=0)
        builder = FixedArrivalBuilder(config, _default_profile())
        schedule = builder.build()
        arrivals = [f for f in schedule if f["flight_type"] == "arrival"]
        assert len(arrivals) == 1
        assert arrivals[0]["flight_number"] == "FIX001"

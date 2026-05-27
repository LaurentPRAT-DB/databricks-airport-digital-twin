"""Tests for PhaseResolver — stuck-flight resolution in isolation.

Tests that phase resolution produces correct decisions without
instantiating SimulationEngine. Each resolve_* method tested independently.
"""

import random
from unittest.mock import MagicMock, patch

import pytest

from src.ingestion._state import FlightPhase, FlightState
from src.simulation.capacity import CapacityManager
from src.simulation.phase_resolver import PhaseResolution, PhaseResolver


def _make_state(**overrides) -> FlightState:
    defaults = dict(
        icao24="test01", callsign="TST001",
        latitude=37.6, longitude=-122.4, altitude=0,
        velocity=0, heading=280, vertical_rate=0,
        on_ground=True, phase=FlightPhase.PARKED,
        aircraft_type="A320",
    )
    defaults.update(overrides)
    return FlightState(**defaults)


def _make_resolver(**overrides) -> PhaseResolver:
    capacity = MagicMock(spec=CapacityManager)
    capacity.go_around_probability.return_value = 0.0
    capacity.current_category = "VMC"
    defaults = dict(
        capacity=capacity,
        airport_code="KSFO",
        alternate_airports={"KSFO": ["KOAK", "KSJC"]},
    )
    defaults.update(overrides)
    return PhaseResolver(**defaults)


class TestTaxiToGateResolution:

    def test_resolves_to_parked(self):
        resolver = _make_resolver()
        state = _make_state(phase=FlightPhase.TAXI_TO_GATE, assigned_gate="A1")
        result = resolver.resolve("test01", state, 600.0)

        assert result.new_phase == FlightPhase.PARKED
        assert result.state_mutations["velocity"] == 0
        assert result.snap_to_gate is True
        assert result.reset_phase_time == "parked"

    def test_sets_time_at_gate_zero(self):
        resolver = _make_resolver()
        state = _make_state(phase=FlightPhase.TAXI_TO_GATE)
        result = resolver.resolve("test01", state, 600.0)

        assert result.state_mutations["time_at_gate"] == 0


class TestPushbackResolution:

    def test_resolves_to_taxi_to_runway(self):
        resolver = _make_resolver()
        state = _make_state(phase=FlightPhase.PUSHBACK, assigned_gate="B5")
        result = resolver.resolve("test01", state, 300.0)

        assert result.new_phase == FlightPhase.TAXI_TO_RUNWAY
        assert result.gate_release == "B5"
        assert result.state_mutations["waypoint_index"] == 0

    def test_releases_assigned_gate(self):
        resolver = _make_resolver()
        state = _make_state(phase=FlightPhase.PUSHBACK, assigned_gate="C12")
        result = resolver.resolve("test01", state, 300.0)

        assert result.gate_release == "C12"


class TestTaxiToRunwayResolution:

    def test_not_at_hold_snaps_to_hold_line(self):
        resolver = _make_resolver()
        state = _make_state(phase=FlightPhase.TAXI_TO_RUNWAY, waypoint_index=0)
        state.taxi_route = [(37.6, -122.4), (37.61, -122.41), (37.62, -122.42)]
        result = resolver.resolve("test01", state, 600.0)

        assert result.new_phase is None  # stays in same phase
        assert result.snap_to_hold_line is True
        assert result.state_mutations["velocity"] == 0
        assert result.reset_phase_time == "taxi_to_runway"

    def test_already_at_hold_resolves_to_takeoff(self):
        resolver = _make_resolver()
        state = _make_state(phase=FlightPhase.TAXI_TO_RUNWAY, waypoint_index=5)
        state.taxi_route = [(37.6, -122.4), (37.61, -122.41)]  # len=2, index=5 >= 2
        result = resolver.resolve("test01", state, 600.0)

        assert result.new_phase == FlightPhase.TAKEOFF
        assert result.state_mutations["takeoff_subphase"] == "lineup"
        assert result.state_mutations["velocity"] == 0
        assert result.reset_phase_time == "takeoff"


class TestApproachingResolution:

    @patch("src.ingestion.fallback._is_runway_clear", return_value=True)
    @patch("src.ingestion.fallback._is_arrival_separation_met", return_value=True)
    @patch("src.ingestion.fallback._get_arrival_runway_name", return_value="28R")
    def test_low_altitude_resolves_to_landing(self, *_mocks):
        resolver = _make_resolver()
        state = _make_state(
            phase=FlightPhase.APPROACHING, altitude=500,
            on_ground=False, velocity=140,
        )
        result = resolver.resolve("test01", state, 600.0)

        assert result.new_phase == FlightPhase.LANDING
        assert result.runway_occupy == "28R"
        assert result.reset_phase_time == "landing"

    @patch("src.ingestion.fallback._is_runway_clear", return_value=True)
    @patch("src.ingestion.fallback._is_arrival_separation_met", return_value=True)
    @patch("src.ingestion.fallback._get_arrival_runway_name", return_value="28R")
    def test_high_altitude_force_lands_when_stuck(self, *_mocks):
        """Stuck approach with clear runway → force-land (go-arounds happen in lifecycle)."""
        resolver = _make_resolver()
        state = _make_state(
            phase=FlightPhase.APPROACHING, altitude=1500,
            on_ground=False, velocity=180,
        )
        result = resolver.resolve("test01", state, 600.0)

        assert result.new_phase == FlightPhase.LANDING
        assert result.state_mutations["altitude"] == 200.0
        assert result.runway_occupy == "28R"
        assert result.reset_phase_time == "landing"

    @patch("src.ingestion.fallback._is_runway_clear", return_value=False)
    @patch("src.ingestion.fallback._is_arrival_separation_met", return_value=True)
    @patch("src.ingestion.fallback._get_arrival_runway_name", return_value="28R")
    def test_runway_occupied_waits(self, *_mocks):
        resolver = _make_resolver()
        state = _make_state(
            phase=FlightPhase.APPROACHING, altitude=500,
            on_ground=False, go_around_count=0,
        )
        result = resolver.resolve("test01", state, 600.0)

        assert result.new_phase is None
        assert result.reset_phase_time == "approaching"
        assert result.phase_time_value == 600.0  # retry next tick

    @patch("src.ingestion.fallback._is_runway_clear", return_value=True)
    @patch("src.ingestion.fallback._is_arrival_separation_met", return_value=True)
    @patch("src.ingestion.fallback._get_arrival_runway_name", return_value="28R")
    def test_stuck_approach_force_lands_regardless_of_weather(self, *_mocks):
        """PhaseResolver force-lands stuck flights — weather go-arounds happen in lifecycle."""
        resolver = _make_resolver()
        state = _make_state(
            phase=FlightPhase.APPROACHING, altitude=500,
            on_ground=False, velocity=140, go_around_count=0,
        )
        result = resolver.resolve("test01", state, 600.0)

        assert result.new_phase == FlightPhase.LANDING
        assert result.state_mutations["altitude"] == 200.0
        assert result.runway_occupy == "28R"

    @patch("src.ingestion.fallback._is_runway_clear", return_value=True)
    @patch("src.ingestion.fallback._is_arrival_separation_met", return_value=True)
    @patch("src.ingestion.fallback._get_arrival_runway_name", return_value="28R")
    def test_three_go_arounds_force_lands_on_approach(self, *_mocks):
        """With go_around_count>=2, resolver force-lands immediately (no more waiting)."""
        resolver = _make_resolver()
        state = _make_state(
            phase=FlightPhase.APPROACHING, altitude=1500,
            on_ground=False, velocity=180, go_around_count=2,
        )
        result = resolver.resolve("test01", state, 600.0)

        assert result.new_phase == FlightPhase.LANDING
        assert result.state_mutations["altitude"] == 200.0
        assert result.runway_occupy == "28R"


class TestLandingResolution:

    def test_resolves_to_taxi_to_gate(self):
        resolver = _make_resolver()
        state = _make_state(
            phase=FlightPhase.LANDING, altitude=10,
            on_ground=False, velocity=80,
        )
        result = resolver.resolve("test01", state, 600.0)

        assert result.new_phase == FlightPhase.TAXI_TO_GATE
        assert result.state_mutations["altitude"] == 0
        assert result.state_mutations["on_ground"] is True
        assert result.runway_release == "test01"


class TestEnrouteResolution:

    def test_departing_flight_marks_exit(self):
        resolver = _make_resolver()
        state = _make_state(
            phase=FlightPhase.ENROUTE, altitude=35000,
            on_ground=False, velocity=450,
            destination_airport="KJFK",
        )
        result = resolver.resolve("test01", state, 600.0)

        assert result.mark_exit is True

    def test_arriving_flight_forces_approach(self):
        resolver = _make_resolver()
        state = _make_state(
            phase=FlightPhase.ENROUTE, altitude=3000,
            on_ground=False, velocity=200,
            destination_airport="KSFO", go_around_count=0,
        )
        result = resolver.resolve("test01", state, 600.0)

        assert result.new_phase == FlightPhase.APPROACHING
        assert result.force_approach is True
        assert result.state_mutations["go_around_count"] == 1

    def test_arriving_with_many_go_arounds_diverts(self):
        resolver = _make_resolver()
        state = _make_state(
            phase=FlightPhase.ENROUTE, altitude=3000,
            on_ground=False, velocity=200,
            destination_airport="KSFO", go_around_count=3,
        )
        random.seed(42)
        result = resolver.resolve("test01", state, 600.0)

        assert result.new_phase == FlightPhase.ENROUTE
        assert result.divert_to in ["KOAK", "KSJC"]
        assert result.event_type == "diversion"

    def test_origin_only_treated_as_arriving(self):
        """Flight with origin_airport but no destination is arriving."""
        resolver = _make_resolver()
        state = _make_state(
            phase=FlightPhase.ENROUTE, altitude=5000,
            on_ground=False, velocity=200,
            origin_airport="KLAX", go_around_count=0,
        )
        state.destination_airport = None
        result = resolver.resolve("test01", state, 600.0)

        assert result.force_approach is True


class TestExtensibility:

    def test_subclass_override_single_phase(self):
        """Subclass can override one resolve method without touching others."""

        class CustomResolver(PhaseResolver):
            def resolve_pushback(self, icao24, state):
                return PhaseResolution(
                    new_phase=FlightPhase.TAXI_TO_RUNWAY,
                    state_mutations={"waypoint_index": 0, "custom_flag": True},
                    reset_phase_time="taxi_to_runway",
                )

        resolver = CustomResolver(
            capacity=MagicMock(spec=CapacityManager),
            airport_code="KSFO",
        )
        state = _make_state(phase=FlightPhase.PUSHBACK, assigned_gate="A1")
        result = resolver.resolve("test01", state, 300.0)

        assert result.state_mutations["custom_flag"] is True
        assert result.gate_release is None  # custom override skips gate release

    def test_resolution_is_pure_data(self):
        """PhaseResolution is a plain dataclass — no side effects."""
        r = PhaseResolution(
            new_phase=FlightPhase.PARKED,
            state_mutations={"velocity": 0},
            gate_release="A1",
        )
        assert r.new_phase == FlightPhase.PARKED
        assert r.gate_release == "A1"
        assert r.runway_release is None
        assert r.divert_to is None

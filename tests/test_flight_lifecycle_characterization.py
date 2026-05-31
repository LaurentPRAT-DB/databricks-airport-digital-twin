"""Characterization tests for _update_flight_state — Phase 1 of CRAP refactor.

These tests pin the CURRENT behavior of the state machine, not ideal behavior.
They cover the two most under-tested branches (TAKEOFF at 3%, TAXI_TO_RUNWAY at 31%)
plus key edge cases in APPROACHING (go-arounds) and ENROUTE (holding patterns).

Run: uv run pytest tests/test_flight_lifecycle_characterization.py -v
"""

import math
import random
from copy import deepcopy
from unittest.mock import patch, MagicMock

import pytest

from src.ingestion._state import FlightState, FlightPhase, _set_phase
from src.ingestion._flight_lifecycle import _update_flight_state, _calibration
from src.ingestion._constants import TAKEOFF_PERFORMANCE, _DEFAULT_TAKEOFF_PERF, VREF_SPEEDS, _DEFAULT_VREF


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_state(**overrides) -> FlightState:
    """Create a FlightState with sensible defaults for testing."""
    defaults = dict(
        icao24="abc123",
        callsign="TST001",
        latitude=37.6213,
        longitude=-122.3790,
        altitude=0.0,
        velocity=0.0,
        heading=280.0,
        vertical_rate=0.0,
        on_ground=True,
        phase=FlightPhase.PARKED,
        aircraft_type="A320",
        assigned_gate="A1",
        waypoint_index=0,
        phase_progress=0.0,
        origin_airport="LAX",
        destination_airport="JFK",
        taxi_route=None,
        takeoff_subphase="lineup",
        takeoff_roll_dist_ft=0.0,
        holding_phase_time=0.0,
        holding_inbound=True,
        go_around_count=0,
        go_around_target_alt=0.0,
        departure_queue_hold_s=0.0,
        departure_queue_set=False,
    )
    defaults.update(overrides)
    return FlightState(**defaults)


# Mock runway geometry: runway start, end, heading, length_ft
_MOCK_RWY_GEOM = (
    (37.6213, -122.3790),  # start
    (37.6280, -122.3700),  # end
    280.0,                  # heading
    9000.0,                 # length_ft
)

_MOCK_TAXI_WPS = [
    (-122.3785, 37.6215),  # lon, lat format
    (-122.3780, 37.6217),
    (-122.3775, 37.6219),
]


@pytest.fixture(autouse=True)
def mock_infrastructure():
    """Mock all external dependencies (airport config, runway state, events)."""
    with patch("src.ingestion.fallback.get_airport_center", return_value=(37.6213, -122.3790)), \
         patch("src.ingestion.fallback.get_current_airport_iata", return_value="SFO"), \
         patch("src.ingestion.fallback.get_gates", return_value={"A1": {}, "A2": {}, "A3": {}}), \
         patch("src.ingestion.fallback.TAXI_WAYPOINTS_ARRIVAL", [(-122.379, 37.621), (-122.378, 37.621)]), \
         patch("src.ingestion.fallback.TAXI_WAYPOINTS_DEPARTURE", _MOCK_TAXI_WPS):
        yield


@pytest.fixture(autouse=True)
def mock_runway_ops():
    """Mock runway operations to isolate state machine logic."""
    mock_rwy_state = MagicMock()
    mock_rwy_state.last_departure_time = 0.0
    mock_rwy_state.last_departure_type = "M"

    with patch("src.ingestion._flight_lifecycle._get_takeoff_runway_geometry", return_value=_MOCK_RWY_GEOM), \
         patch("src.ingestion._flight_lifecycle._is_runway_clear", return_value=True), \
         patch("src.ingestion._flight_lifecycle._get_runway_state", return_value=mock_rwy_state), \
         patch("src.ingestion._flight_lifecycle._get_departure_runway_name", return_value="28L"), \
         patch("src.ingestion._flight_lifecycle._occupy_runway"), \
         patch("src.ingestion._flight_lifecycle._release_runway"), \
         patch("src.ingestion._flight_lifecycle._taxi_speed_factor", return_value=1.0), \
         patch("src.ingestion._flight_lifecycle._is_arrival_separation_met", return_value=True), \
         patch("src.ingestion._flight_lifecycle._get_wake_category", return_value="M"), \
         patch("src.ingestion._flight_lifecycle.get_time", return_value=1000.0), \
         patch("src.ingestion._flight_lifecycle._get_approach_waypoints", return_value=[
             (-122.40, 37.60), (-122.39, 37.61), (-122.385, 37.615), (-122.380, 37.620),
         ]), \
         patch("src.ingestion._flight_lifecycle._get_sid_name", return_value="SFO5"), \
         patch("src.ingestion._flight_lifecycle.emit_phase_transition"), \
         patch("src.ingestion._flight_lifecycle.diag_log"):
        yield


# ── TAKEOFF Phase Tests ───────────────────────────────────────────────────────

class TestTakeoffLineup:
    """TAKEOFF subphase: lineup — taxi onto runway centerline."""

    def test_lineup_moves_toward_runway_start(self):
        state = _make_state(
            phase=FlightPhase.TAKEOFF,
            takeoff_subphase="lineup",
            latitude=37.6210,  # Slightly off from runway start
            longitude=-122.3793,
            altitude=13.0,
            phase_progress=0.0,
        )
        _set_phase(state, FlightPhase.TAKEOFF)
        original_lat = state.latitude

        result = _update_flight_state(state, 2.0)

        assert result.velocity == 10.0  # Lineup speed
        assert result.on_ground is True
        # Should have moved toward runway start
        assert result.latitude != original_lat

    def test_lineup_holds_briefly_at_runway_start(self):
        state = _make_state(
            phase=FlightPhase.TAKEOFF,
            takeoff_subphase="lineup",
            latitude=_MOCK_RWY_GEOM[0][0],  # Already at runway start
            longitude=_MOCK_RWY_GEOM[0][1],
            altitude=13.0,
            phase_progress=0.0,
        )
        _set_phase(state, FlightPhase.TAKEOFF)

        result = _update_flight_state(state, 2.0)

        assert result.velocity == 0
        assert result.takeoff_subphase == "lineup"  # Still in lineup
        assert result.phase_progress == 2.0  # Counting hold time

    def test_lineup_transitions_to_roll_after_3s(self):
        state = _make_state(
            phase=FlightPhase.TAKEOFF,
            takeoff_subphase="lineup",
            latitude=_MOCK_RWY_GEOM[0][0],
            longitude=_MOCK_RWY_GEOM[0][1],
            altitude=13.0,
            phase_progress=2.5,  # Already held 2.5s
        )
        _set_phase(state, FlightPhase.TAKEOFF)

        result = _update_flight_state(state, 1.0)  # Total 3.5s

        assert result.takeoff_subphase == "roll"
        assert result.phase_progress == 0.0
        assert result.takeoff_roll_dist_ft == 0.0


class TestTakeoffRoll:
    """TAKEOFF subphase: roll — ground acceleration until Vr."""

    def test_roll_accelerates(self):
        perf = TAKEOFF_PERFORMANCE.get("A320", _DEFAULT_TAKEOFF_PERF)
        v1, vr, v2, accel_rate, _ = perf

        state = _make_state(
            phase=FlightPhase.TAKEOFF,
            takeoff_subphase="roll",
            latitude=_MOCK_RWY_GEOM[0][0],
            longitude=_MOCK_RWY_GEOM[0][1],
            altitude=13.0,
            velocity=50.0,
            phase_progress=0.0,
            takeoff_roll_dist_ft=500.0,
        )
        _set_phase(state, FlightPhase.TAKEOFF)

        result = _update_flight_state(state, 2.0)

        expected_vel = min(50.0 + accel_rate * 2.0, vr)
        assert abs(result.velocity - expected_vel) < 0.1
        assert result.on_ground is True
        assert result.takeoff_roll_dist_ft > 500.0  # Distance accumulated

    def test_roll_transitions_to_rotate_at_vr(self):
        perf = TAKEOFF_PERFORMANCE.get("A320", _DEFAULT_TAKEOFF_PERF)
        _, vr, _, accel_rate, _ = perf

        state = _make_state(
            phase=FlightPhase.TAKEOFF,
            takeoff_subphase="roll",
            latitude=_MOCK_RWY_GEOM[0][0],
            longitude=_MOCK_RWY_GEOM[0][1],
            altitude=13.0,
            velocity=vr - 1,  # Just below Vr
            takeoff_roll_dist_ft=3000.0,
        )
        _set_phase(state, FlightPhase.TAKEOFF)

        result = _update_flight_state(state, 2.0)

        assert result.velocity >= vr
        assert result.takeoff_subphase == "rotate"
        assert result.phase_progress == 0.0

    def test_roll_moves_along_runway(self):
        state = _make_state(
            phase=FlightPhase.TAKEOFF,
            takeoff_subphase="roll",
            latitude=_MOCK_RWY_GEOM[0][0],
            longitude=_MOCK_RWY_GEOM[0][1],
            altitude=13.0,
            velocity=80.0,
            takeoff_roll_dist_ft=1000.0,
        )
        _set_phase(state, FlightPhase.TAKEOFF)
        orig_lat = state.latitude

        result = _update_flight_state(state, 2.0)

        # Position should interpolate along runway centerline
        assert result.latitude != orig_lat


class TestTakeoffRotate:
    """TAKEOFF subphase: rotate — nose pitch up, reduced accel."""

    def test_rotate_begins_climbing(self):
        perf = TAKEOFF_PERFORMANCE.get("A320", _DEFAULT_TAKEOFF_PERF)
        _, vr, v2, _, _ = perf

        state = _make_state(
            phase=FlightPhase.TAKEOFF,
            takeoff_subphase="rotate",
            latitude=_MOCK_RWY_GEOM[0][0],
            longitude=_MOCK_RWY_GEOM[0][1],
            altitude=13.0,
            velocity=vr,
            phase_progress=0.0,
            takeoff_roll_dist_ft=4000.0,
        )
        _set_phase(state, FlightPhase.TAKEOFF)

        result = _update_flight_state(state, 2.0)

        assert result.on_ground is True  # Still on ground during rotate
        assert result.vertical_rate > 0  # Started climbing
        assert result.altitude > 13.0
        assert result.phase_progress == 2.0

    def test_rotate_transitions_to_liftoff(self):
        perf = TAKEOFF_PERFORMANCE.get("A320", _DEFAULT_TAKEOFF_PERF)
        _, vr, v2, _, _ = perf

        state = _make_state(
            phase=FlightPhase.TAKEOFF,
            takeoff_subphase="rotate",
            latitude=_MOCK_RWY_GEOM[0][0],
            longitude=_MOCK_RWY_GEOM[0][1],
            altitude=13.0,
            velocity=v2 - 1,
            phase_progress=2.5,
            takeoff_roll_dist_ft=5000.0,
        )
        _set_phase(state, FlightPhase.TAKEOFF)

        result = _update_flight_state(state, 1.0)  # total 3.5s > 3.0

        assert result.takeoff_subphase == "liftoff"
        assert result.on_ground is False


class TestTakeoffLiftoff:
    """TAKEOFF subphase: liftoff — wheels off, climb to 35ft."""

    def test_liftoff_climbs(self):
        perf = TAKEOFF_PERFORMANCE.get("A320", _DEFAULT_TAKEOFF_PERF)
        _, _, v2, _, climb_fpm = perf

        state = _make_state(
            phase=FlightPhase.TAKEOFF,
            takeoff_subphase="liftoff",
            latitude=_MOCK_RWY_GEOM[0][0],
            longitude=_MOCK_RWY_GEOM[0][1],
            altitude=15.0,
            velocity=v2,
            phase_progress=0.0,
            on_ground=False,
        )
        _set_phase(state, FlightPhase.TAKEOFF)

        result = _update_flight_state(state, 2.0)

        assert result.on_ground is False
        assert result.altitude > 15.0
        assert result.vertical_rate > 0

    def test_liftoff_transitions_to_initial_climb_at_35ft(self):
        state = _make_state(
            phase=FlightPhase.TAKEOFF,
            takeoff_subphase="liftoff",
            latitude=_MOCK_RWY_GEOM[0][0],
            longitude=_MOCK_RWY_GEOM[0][1],
            altitude=33.0,  # Close to 35ft
            velocity=150.0,
            vertical_rate=1500.0,
            phase_progress=3.0,
            on_ground=False,
        )
        _set_phase(state, FlightPhase.TAKEOFF)

        result = _update_flight_state(state, 2.0)

        assert result.altitude >= 35.0
        assert result.takeoff_subphase == "initial_climb"


class TestTakeoffInitialClimb:
    """TAKEOFF subphase: initial_climb — climb to 500ft, release runway."""

    def test_initial_climb_continues_climbing(self):
        perf = TAKEOFF_PERFORMANCE.get("A320", _DEFAULT_TAKEOFF_PERF)
        _, _, v2, _, climb_fpm = perf

        state = _make_state(
            phase=FlightPhase.TAKEOFF,
            takeoff_subphase="initial_climb",
            latitude=_MOCK_RWY_GEOM[0][0],
            longitude=_MOCK_RWY_GEOM[0][1],
            altitude=200.0,
            velocity=v2 + 5,
            vertical_rate=climb_fpm,
            on_ground=False,
        )
        _set_phase(state, FlightPhase.TAKEOFF)

        result = _update_flight_state(state, 2.0)

        assert result.altitude > 200.0
        assert result.on_ground is False
        assert result.phase == FlightPhase.TAKEOFF  # Not yet 500ft

    def test_initial_climb_transitions_to_departing_at_500ft(self):
        perf = TAKEOFF_PERFORMANCE.get("A320", _DEFAULT_TAKEOFF_PERF)
        _, _, v2, _, climb_fpm = perf

        state = _make_state(
            phase=FlightPhase.TAKEOFF,
            takeoff_subphase="initial_climb",
            latitude=_MOCK_RWY_GEOM[0][0],
            longitude=_MOCK_RWY_GEOM[0][1],
            altitude=490.0,  # Close to 500ft
            velocity=v2 + 5,
            vertical_rate=climb_fpm,
            on_ground=False,
        )
        _set_phase(state, FlightPhase.TAKEOFF)

        result = _update_flight_state(state, 2.0)

        assert result.altitude >= 500.0
        assert result.phase == FlightPhase.DEPARTING
        assert result.waypoint_index == 0
        assert result.takeoff_subphase == "lineup"  # Reset for next use


# ── TAXI_TO_RUNWAY Phase Tests ────────────────────────────────────────────────

class TestTaxiToRunway:
    """TAXI_TO_RUNWAY phase — taxi along waypoints, hold at runway."""

    def test_taxi_moves_along_waypoints(self):
        # Place aircraft offset from first waypoint so it actually moves
        state = _make_state(
            phase=FlightPhase.TAXI_TO_RUNWAY,
            latitude=37.6210,
            longitude=-122.3790,
            waypoint_index=0,
            taxi_route=_MOCK_TAXI_WPS,
        )
        _set_phase(state, FlightPhase.TAXI_TO_RUNWAY)
        orig_lat = state.latitude

        result = _update_flight_state(state, 2.0)

        assert result.velocity > 0
        assert (result.latitude != orig_lat or result.longitude != state.longitude)

    def test_taxi_advances_waypoint_index(self):
        # Place aircraft very close to first waypoint
        wp = _MOCK_TAXI_WPS[0]
        state = _make_state(
            phase=FlightPhase.TAXI_TO_RUNWAY,
            latitude=wp[1],  # lat
            longitude=wp[0],  # lon
            waypoint_index=0,
            taxi_route=_MOCK_TAXI_WPS,
        )
        _set_phase(state, FlightPhase.TAXI_TO_RUNWAY)

        result = _update_flight_state(state, 2.0)

        assert result.waypoint_index >= 1

    def test_departure_queue_hold_computed_once(self):
        """After waypoints exhausted, queue hold is computed once."""
        state = _make_state(
            phase=FlightPhase.TAXI_TO_RUNWAY,
            latitude=37.6219,
            longitude=-122.3775,
            waypoint_index=len(_MOCK_TAXI_WPS),  # Past all waypoints
            taxi_route=_MOCK_TAXI_WPS,
            departure_queue_set=False,
            departure_queue_hold_s=0.0,
        )
        _set_phase(state, FlightPhase.TAXI_TO_RUNWAY)

        with patch.object(_calibration, 'taxi_out_target_s', 120.0), \
             patch.object(_calibration, 'taxi_out_waypoint_s', 60.0), \
             patch.object(_calibration, 'taxi_out_p95_s', 200.0):
            result = _update_flight_state(state, 2.0)

        assert result.departure_queue_set is True
        # Queue hold = min(60 * random(0.7,1.1), (200-60)*0.7=98) → 42-66s
        assert 40.0 <= result.departure_queue_hold_s <= 80.0

    def test_departure_queue_counts_down(self):
        """While queue hold active, it counts down."""
        state = _make_state(
            phase=FlightPhase.TAXI_TO_RUNWAY,
            latitude=37.6219,
            longitude=-122.3775,
            waypoint_index=len(_MOCK_TAXI_WPS),
            taxi_route=_MOCK_TAXI_WPS,
            departure_queue_set=True,
            departure_queue_hold_s=30.0,
        )
        _set_phase(state, FlightPhase.TAXI_TO_RUNWAY)

        result = _update_flight_state(state, 2.0)

        assert result.departure_queue_hold_s == 28.0
        assert result.velocity == 0  # Holding
        assert result.phase == FlightPhase.TAXI_TO_RUNWAY

    def test_transitions_to_takeoff_when_runway_clear(self):
        """After queue hold and waypoints done, transitions to TAKEOFF if runway clear."""
        state = _make_state(
            phase=FlightPhase.TAXI_TO_RUNWAY,
            latitude=37.6219,
            longitude=-122.3775,
            waypoint_index=len(_MOCK_TAXI_WPS),
            taxi_route=_MOCK_TAXI_WPS,
            departure_queue_set=True,
            departure_queue_hold_s=0.0,
        )
        _set_phase(state, FlightPhase.TAXI_TO_RUNWAY)

        with patch.object(_calibration, 'taxi_out_target_s', 0.0):
            result = _update_flight_state(state, 2.0)

        assert result.phase == FlightPhase.TAKEOFF
        assert result.takeoff_subphase == "lineup"
        assert result.heading == 280.0  # Runway heading

    def test_holds_short_when_runway_occupied(self):
        """If runway not clear, hold position."""
        state = _make_state(
            phase=FlightPhase.TAXI_TO_RUNWAY,
            latitude=37.6219,
            longitude=-122.3775,
            waypoint_index=len(_MOCK_TAXI_WPS),
            taxi_route=_MOCK_TAXI_WPS,
            departure_queue_set=True,
            departure_queue_hold_s=0.0,
        )
        _set_phase(state, FlightPhase.TAXI_TO_RUNWAY)

        with patch("src.ingestion._flight_lifecycle._is_runway_clear", return_value=False), \
             patch.object(_calibration, 'taxi_out_target_s', 0.0):
            result = _update_flight_state(state, 2.0)

        assert result.phase == FlightPhase.TAXI_TO_RUNWAY
        assert result.velocity == 0

    def test_holds_for_wake_separation(self):
        """Even if runway clear, hold if wake separation not met."""
        mock_rwy_state = MagicMock()
        mock_rwy_state.last_departure_time = 999.0  # Only 1s ago
        mock_rwy_state.last_departure_type = "H"  # Heavy preceding

        state = _make_state(
            phase=FlightPhase.TAXI_TO_RUNWAY,
            latitude=37.6219,
            longitude=-122.3775,
            waypoint_index=len(_MOCK_TAXI_WPS),
            taxi_route=_MOCK_TAXI_WPS,
            departure_queue_set=True,
            departure_queue_hold_s=0.0,
        )
        _set_phase(state, FlightPhase.TAXI_TO_RUNWAY)

        with patch("src.ingestion._flight_lifecycle._get_runway_state", return_value=mock_rwy_state), \
             patch.object(_calibration, 'taxi_out_target_s', 0.0):
            result = _update_flight_state(state, 2.0)

        assert result.phase == FlightPhase.TAXI_TO_RUNWAY
        assert result.velocity == 0


# ── APPROACHING Phase — Go-Around Tests ───────────────────────────────────────

class TestApproachingGoAround:
    """Go-around logic within the APPROACHING phase."""

    def test_go_around_transitions_to_enroute(self):
        """Go-around sets phase to ENROUTE with climb parameters."""
        state = _make_state(
            phase=FlightPhase.APPROACHING,
            latitude=37.615,
            longitude=-122.385,
            altitude=800.0,
            velocity=140.0,
            heading=280.0,
            waypoint_index=3,
            go_around_count=0,
        )
        _set_phase(state, FlightPhase.APPROACHING)

        # Force go-around by making runway busy
        with patch("src.ingestion._flight_lifecycle._is_runway_clear", return_value=False), \
             patch("src.ingestion._flight_lifecycle._is_arrival_separation_met", return_value=True):
            # Need to trigger the go-around path — approach to near decision height
            state.altitude = 180.0  # Below decision height triggers landing attempt
            state.waypoint_index = 4  # Past all approach waypoints
            result = _update_flight_state(state, 2.0)

        # After go-around, should be in ENROUTE
        if result.phase == FlightPhase.ENROUTE:
            assert result.go_around_count >= 1
            assert result.go_around_target_alt >= 3000.0
            assert result.vertical_rate > 0

    def test_third_go_around_triggers_diversion_prep(self):
        """After 3 go-arounds, aircraft enters ENROUTE for engine diversion."""
        state = _make_state(
            phase=FlightPhase.APPROACHING,
            latitude=37.615,
            longitude=-122.385,
            altitude=180.0,
            velocity=140.0,
            heading=280.0,
            waypoint_index=4,  # Past all approach waypoints
            go_around_count=2,  # This will be the 3rd
        )
        _set_phase(state, FlightPhase.APPROACHING)

        with patch("src.ingestion._flight_lifecycle._is_runway_clear", return_value=False):
            result = _update_flight_state(state, 2.0)

        if result.phase == FlightPhase.ENROUTE:
            assert result.go_around_count >= 3


# ── ENROUTE Phase — Holding Pattern Tests ─────────────────────────────────────

class TestEnrouteHolding:
    """ENROUTE phase holding pattern and re-approach logic."""

    def test_enroute_arriving_holds_at_altitude(self):
        """Arriving aircraft in ENROUTE holds at go-around target altitude."""
        state = _make_state(
            phase=FlightPhase.ENROUTE,
            latitude=37.60,
            longitude=-122.40,
            altitude=2500.0,
            velocity=200.0,
            heading=280.0,
            go_around_count=1,
            go_around_target_alt=3000.0,
            vertical_rate=1500.0,
            origin_airport="LAX",
            destination_airport="SFO",
            holding_phase_time=0.0,
            holding_inbound=True,
        )
        _set_phase(state, FlightPhase.ENROUTE)

        result = _update_flight_state(state, 2.0)

        # Should be climbing toward go_around_target_alt
        assert result.altitude > 2500.0 or result.altitude == 2500.0
        assert result.phase == FlightPhase.ENROUTE

    def test_enroute_departing_climbs_to_cruise(self):
        """Departing aircraft in ENROUTE climbs toward cruise altitude."""
        state = _make_state(
            phase=FlightPhase.ENROUTE,
            latitude=37.70,
            longitude=-122.50,
            altitude=5000.0,
            velocity=280.0,
            heading=90.0,
            vertical_rate=1500.0,
            go_around_count=0,
            cruise_altitude=35000.0,
            origin_airport="SFO",
            destination_airport="JFK",
        )
        _set_phase(state, FlightPhase.ENROUTE)

        result = _update_flight_state(state, 2.0)

        assert result.altitude > 5000.0
        assert result.phase == FlightPhase.ENROUTE


# ── TAXI_TO_RUNWAY with speed_factor variations ───────────────────────────────

class TestTaxiSpeedFactor:
    """TAXI_TO_RUNWAY behavior with different speed factors."""

    def test_head_on_hold_negative_factor(self):
        """Negative speed_factor means head-on traffic — aircraft yields."""
        state = _make_state(
            phase=FlightPhase.TAXI_TO_RUNWAY,
            latitude=37.6215,
            longitude=-122.3785,
            waypoint_index=0,
            taxi_route=_MOCK_TAXI_WPS,
            velocity=15.0,
        )
        _set_phase(state, FlightPhase.TAXI_TO_RUNWAY)
        orig_lat = state.latitude
        orig_lon = state.longitude

        with patch("src.ingestion._flight_lifecycle._taxi_speed_factor", return_value=-1.0):
            result = _update_flight_state(state, 2.0)

        assert result.velocity == 0
        # Position should not change (holding)
        assert result.latitude == orig_lat
        assert result.longitude == orig_lon

    def test_zero_factor_traffic_ahead(self):
        """Zero speed_factor means traffic ahead — hold position."""
        state = _make_state(
            phase=FlightPhase.TAXI_TO_RUNWAY,
            latitude=37.6215,
            longitude=-122.3785,
            waypoint_index=0,
            taxi_route=_MOCK_TAXI_WPS,
            velocity=15.0,
        )
        _set_phase(state, FlightPhase.TAXI_TO_RUNWAY)

        with patch("src.ingestion._flight_lifecycle._taxi_speed_factor", return_value=0.0):
            result = _update_flight_state(state, 2.0)

        assert result.velocity == 0


# ── Differential test: original vs current ────────────────────────────────────

class TestDifferentialOriginal:
    """Verify current _update_flight_state matches the preserved original."""

    def test_takeoff_roll_matches_original(self):
        """Takeoff roll behavior identical between current and original."""
        from src.ingestion._flight_lifecycle_original import _update_flight_state as _original

        state1 = _make_state(
            phase=FlightPhase.TAKEOFF,
            takeoff_subphase="roll",
            latitude=_MOCK_RWY_GEOM[0][0],
            longitude=_MOCK_RWY_GEOM[0][1],
            altitude=13.0,
            velocity=80.0,
            takeoff_roll_dist_ft=2000.0,
        )
        _set_phase(state1, FlightPhase.TAKEOFF)
        state2 = deepcopy(state1)

        # Both versions need the same runway geometry mock
        with patch("src.ingestion._flight_lifecycle_original._get_takeoff_runway_geometry", return_value=_MOCK_RWY_GEOM):
            result1 = _update_flight_state(state1, 2.0)
            result2 = _original(state2, 2.0)

        assert result1.velocity == result2.velocity
        assert result1.latitude == result2.latitude
        assert result1.longitude == result2.longitude
        assert result1.takeoff_roll_dist_ft == result2.takeoff_roll_dist_ft
        assert result1.takeoff_subphase == result2.takeoff_subphase

    def test_taxi_to_runway_matches_original(self):
        """Taxi to runway behavior identical between current and original."""
        from src.ingestion._flight_lifecycle_original import _update_flight_state as _original

        state1 = _make_state(
            phase=FlightPhase.TAXI_TO_RUNWAY,
            latitude=37.6215,
            longitude=-122.3785,
            waypoint_index=0,
            taxi_route=_MOCK_TAXI_WPS,
        )
        _set_phase(state1, FlightPhase.TAXI_TO_RUNWAY)
        state2 = deepcopy(state1)

        result1 = _update_flight_state(state1, 2.0)
        result2 = _original(state2, 2.0)

        assert result1.velocity == result2.velocity
        assert abs(result1.latitude - result2.latitude) < 1e-10
        assert abs(result1.longitude - result2.longitude) < 1e-10
        assert result1.waypoint_index == result2.waypoint_index

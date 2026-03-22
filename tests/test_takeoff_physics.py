"""Tests for realistic takeoff physics, V-speeds, and departure separation.

Validates compliance with:
- 14 CFR 25.107: V1/VR/V2 speed definitions
- 14 CFR 25.111: Takeoff path climb gradient
- FAA 7110.65 5-8-1: Departure wake separation
- ICAO Doc 4444 6.3.3: Wake turbulence departure separation
"""

import math
import time

import pytest

import src.ingestion.fallback as _fallback
from src.ingestion.fallback import (
    FlightPhase,
    FlightState,
    RunwayState,
    TAKEOFF_PERFORMANCE,
    DEPARTURE_SEPARATION_S,
    DEFAULT_DEPARTURE_SEPARATION_S,
    _DEFAULT_TAKEOFF_PERF,
    _get_wake_category,
    _get_takeoff_runway_geometry,
    _update_flight_state,
)


def _get_runway_28R():
    """Get the current _runway_28R from the module (survives re-binding)."""
    return _fallback._runway_28R


@pytest.fixture(autouse=True)
def _reset_runway_state():
    """Reset runway 28R state before each test to ensure isolation."""
    rwy = _get_runway_28R()
    rwy.occupied_by = None
    rwy.last_departure_time = 0.0
    rwy.last_arrival_time = 0.0
    rwy.last_departure_type = "LARGE"
    yield


def _make_takeoff_state(aircraft_type: str = "A320", **overrides) -> FlightState:
    """Create a FlightState ready for takeoff using dynamic runway geometry."""
    rwy_start, _, rwy_heading, _ = _get_takeoff_runway_geometry()
    defaults = dict(
        icao24="test01",
        callsign="TST001",
        latitude=rwy_start[0],
        longitude=rwy_start[1],
        altitude=0,
        velocity=0,
        heading=rwy_heading,
        vertical_rate=0,
        on_ground=True,
        phase=FlightPhase.TAKEOFF,
        aircraft_type=aircraft_type,
        takeoff_subphase="lineup",
        phase_progress=0.0,
        takeoff_roll_dist_ft=0.0,
    )
    defaults.update(overrides)
    return FlightState(**defaults)


class TestTakeoffSubphases:
    """Test that takeoff progresses through all sub-phases in order."""

    def test_subphase_progression(self):
        """lineup -> roll -> rotate -> liftoff -> initial_climb -> DEPARTING."""
        state = _make_takeoff_state()
        seen_subphases = ["lineup"]
        max_iterations = 2000
        dt = 0.5

        for _ in range(max_iterations):
            state = _update_flight_state(state, dt)
            if state.phase == FlightPhase.DEPARTING:
                seen_subphases.append("DEPARTING")
                break
            if state.takeoff_subphase != seen_subphases[-1]:
                seen_subphases.append(state.takeoff_subphase)

        expected = ["lineup", "roll", "rotate", "liftoff", "initial_climb", "DEPARTING"]
        assert seen_subphases == expected, f"Got: {seen_subphases}"

    def test_lineup_snaps_to_runway_start(self):
        """During lineup, aircraft should be positioned at start of departure runway."""
        rwy_start, _, _, _ = _get_takeoff_runway_geometry()
        state = _make_takeoff_state()
        state = _update_flight_state(state, 0.5)
        assert state.takeoff_subphase == "lineup"
        assert abs(state.latitude - rwy_start[0]) < 0.001
        assert abs(state.longitude - rwy_start[1]) < 0.001
        assert state.velocity == 0

    def test_lineup_lasts_about_3_seconds(self):
        """Lineup sub-phase should last ~3 seconds."""
        state = _make_takeoff_state()
        # After 2.5s should still be in lineup
        for _ in range(5):
            state = _update_flight_state(state, 0.5)
        assert state.takeoff_subphase == "lineup"
        # After another 1s should transition to roll
        for _ in range(2):
            state = _update_flight_state(state, 0.5)
        assert state.takeoff_subphase == "roll"


class TestVSpeeds:
    """Test V-speed compliance per 14 CFR 25.107."""

    def test_reaches_vr_during_roll(self):
        """Aircraft should reach VR at end of roll sub-phase."""
        state = _make_takeoff_state()
        perf = TAKEOFF_PERFORMANCE["A320"]
        vr = perf[1]

        for _ in range(2000):
            state = _update_flight_state(state, 0.5)
            if state.takeoff_subphase == "rotate":
                assert state.velocity >= vr - 2, f"Velocity {state.velocity} < VR {vr}"
                break
        else:
            pytest.fail("Never reached rotate sub-phase")

    def test_reaches_v2_during_rotate_or_liftoff(self):
        """Aircraft should reach V2 by liftoff."""
        state = _make_takeoff_state()
        perf = TAKEOFF_PERFORMANCE["A320"]
        v2 = perf[2]

        for _ in range(2000):
            state = _update_flight_state(state, 0.5)
            if state.takeoff_subphase == "liftoff":
                assert state.velocity >= v2 - 5, f"Velocity {state.velocity} < V2 {v2}"
                break
        else:
            pytest.fail("Never reached liftoff sub-phase")

    @pytest.mark.parametrize("aircraft_type", ["A320", "B747", "A380", "CRJ9", "E175"])
    def test_aircraft_specific_vspeeds(self, aircraft_type):
        """Each aircraft type should use its own V-speed schedule."""
        state = _make_takeoff_state(aircraft_type=aircraft_type)
        perf = TAKEOFF_PERFORMANCE.get(aircraft_type, _DEFAULT_TAKEOFF_PERF)
        vr = perf[1]

        for _ in range(2000):
            state = _update_flight_state(state, 0.5)
            if state.takeoff_subphase == "rotate":
                assert state.velocity >= vr - 2
                break
        else:
            pytest.fail(f"{aircraft_type} never reached rotate")


class TestRunwayCenterlineTracking:
    """Test that aircraft stays on runway centerline during ground roll."""

    def test_position_between_thresholds(self):
        """Position should remain between runway thresholds during roll."""
        rwy_start, rwy_end, _, _ = _get_takeoff_runway_geometry()
        state = _make_takeoff_state()

        for _ in range(2000):
            state = _update_flight_state(state, 0.5)
            if state.takeoff_subphase in ("roll", "rotate") and state.on_ground:
                min_lat = min(rwy_start[0], rwy_end[0]) - 0.001
                max_lat = max(rwy_start[0], rwy_end[0]) + 0.001
                min_lon = min(rwy_start[1], rwy_end[1]) - 0.001
                max_lon = max(rwy_start[1], rwy_end[1]) + 0.001
                assert min_lat <= state.latitude <= max_lat, \
                    f"Lat {state.latitude} outside runway bounds [{min_lat}, {max_lat}]"
                assert min_lon <= state.longitude <= max_lon, \
                    f"Lon {state.longitude} outside runway bounds [{min_lon}, {max_lon}]"
            if state.phase == FlightPhase.DEPARTING:
                break


class TestAltitudeTransitions:
    """Test altitude behavior through takeoff sub-phases."""

    def test_zero_altitude_during_ground_roll(self):
        """Altitude should be 0 during lineup and roll; small rise allowed during rotate."""
        state = _make_takeoff_state()
        for _ in range(2000):
            state = _update_flight_state(state, 0.5)
            if state.takeoff_subphase in ("lineup", "roll"):
                assert state.altitude == 0, \
                    f"Altitude {state.altitude} != 0 during {state.takeoff_subphase}"
            elif state.takeoff_subphase == "rotate":
                # Rotation ramps vertical rate from 0→500 fpm over ~3s;
                # aircraft is still on ground but nose pitches up — small
                # altitude increase is physically correct.
                assert state.altitude < 10, \
                    f"Altitude {state.altitude} too high during rotate (expect <10 ft)"
            if state.takeoff_subphase == "liftoff":
                break

    def test_positive_altitude_at_liftoff(self):
        """Altitude should become positive after liftoff."""
        state = _make_takeoff_state()
        found_liftoff = False
        for _ in range(2000):
            state = _update_flight_state(state, 0.5)
            if state.takeoff_subphase == "liftoff" and state.altitude > 0:
                found_liftoff = True
                break
        assert found_liftoff, "Never saw positive altitude during liftoff"

    def test_altitude_500ft_at_departing(self):
        """Altitude should be ~500 ft when transitioning to DEPARTING."""
        state = _make_takeoff_state()
        for _ in range(2000):
            prev_phase = state.phase
            state = _update_flight_state(state, 0.5)
            if state.phase == FlightPhase.DEPARTING and prev_phase == FlightPhase.TAKEOFF:
                assert state.altitude >= 500, \
                    f"Altitude {state.altitude} < 500 at DEPARTING transition"
                break
        else:
            pytest.fail("Never transitioned to DEPARTING")

    def test_on_ground_false_after_liftoff(self):
        """on_ground should be False from liftoff onward."""
        state = _make_takeoff_state()
        seen_liftoff = False
        for _ in range(2000):
            state = _update_flight_state(state, 0.5)
            if state.takeoff_subphase in ("liftoff", "initial_climb"):
                seen_liftoff = True
                assert not state.on_ground, \
                    f"on_ground=True during {state.takeoff_subphase}"
            if state.phase == FlightPhase.DEPARTING:
                break
        assert seen_liftoff


class TestDepartureSeparation:
    """Test departure wake turbulence separation (FAA 7110.65 5-8-1)."""

    def test_hold_short_when_separation_not_met(self):
        """Aircraft should hold short if wake separation time not elapsed."""
        state = FlightState(
            icao24="follow01",
            callsign="TST002",
            latitude=37.615,
            longitude=-122.360,
            altitude=0,
            velocity=0,
            heading=280,
            vertical_rate=0,
            on_ground=True,
            phase=FlightPhase.TAXI_TO_RUNWAY,
            aircraft_type="A320",
            waypoint_index=999,  # Past all taxi waypoints to trigger hold line logic
        )

        # Simulate a HEAVY just departed 30s ago (need 120s separation)
        rwy = _get_runway_28R()
        rwy.occupied_by = None
        rwy.last_departure_time = time.time() - 30
        rwy.last_departure_type = "HEAVY"

        state = _update_flight_state(state, 0.5)
        # Should still be TAXI_TO_RUNWAY (holding short)
        assert state.phase == FlightPhase.TAXI_TO_RUNWAY
        assert state.velocity == 0

    def test_proceed_when_separation_met(self):
        """Aircraft should enter takeoff when wake separation is met."""
        state = FlightState(
            icao24="follow02",
            callsign="TST003",
            latitude=37.615,
            longitude=-122.360,
            altitude=0,
            velocity=0,
            heading=280,
            vertical_rate=0,
            on_ground=True,
            phase=FlightPhase.TAXI_TO_RUNWAY,
            aircraft_type="A320",
            waypoint_index=999,
            departure_queue_hold_s=0.0,
            departure_queue_set=True,  # bypass calibrated queue hold
        )

        # LARGE behind LARGE: 60s default, set 120s ago
        rwy = _get_runway_28R()
        rwy.occupied_by = None
        rwy.last_departure_time = time.time() - 120
        rwy.last_departure_type = "LARGE"

        state = _update_flight_state(state, 0.5)
        assert state.phase == FlightPhase.TAKEOFF

    def test_super_requires_180s_separation(self):
        """Following a SUPER, need 180s separation."""
        required = DEPARTURE_SEPARATION_S.get(("SUPER", "LARGE"))
        assert required == 180

    def test_heavy_requires_120s_separation(self):
        """Following a HEAVY, need 120s for HEAVY/LARGE followers."""
        assert DEPARTURE_SEPARATION_S[("HEAVY", "HEAVY")] == 120
        assert DEPARTURE_SEPARATION_S[("HEAVY", "LARGE")] == 120


class TestAircraftPerformanceVariation:
    """Test that different aircraft types have different takeoff characteristics."""

    def test_a380_slower_acceleration_than_crj9(self):
        """A380 should take longer to reach rotation than CRJ9."""
        iterations_a380 = self._count_iterations_to_rotate("A380")
        iterations_crj9 = self._count_iterations_to_rotate("CRJ9")
        assert iterations_a380 > iterations_crj9, \
            f"A380 ({iterations_a380} iters) should be slower than CRJ9 ({iterations_crj9})"

    def test_heavy_higher_vspeeds(self):
        """HEAVY aircraft should have higher V-speeds than SMALL."""
        for heavy in ["B747", "A380", "B777"]:
            for small in ["CRJ9", "E175"]:
                h_perf = TAKEOFF_PERFORMANCE[heavy]
                s_perf = TAKEOFF_PERFORMANCE[small]
                assert h_perf[1] > s_perf[1], \
                    f"{heavy} VR ({h_perf[1]}) should exceed {small} VR ({s_perf[1]})"

    def _count_iterations_to_rotate(self, aircraft_type: str) -> int:
        state = _make_takeoff_state(aircraft_type=aircraft_type)
        for i in range(3000):
            state = _update_flight_state(state, 0.5)
            if state.takeoff_subphase == "rotate":
                return i
        return 3000


class TestRunwayRelease:
    """Test that runway is only released after initial climb, not during ground roll."""

    def test_runway_occupied_during_roll(self):
        """Runway should remain occupied during ground roll."""
        state = _make_takeoff_state()
        rwy = _get_runway_28R()
        rwy.occupied_by = state.icao24
        checked_ground_phases = False

        for _ in range(2000):
            subphase_before = state.takeoff_subphase
            phase_before = state.phase
            state = _update_flight_state(state, 0.5)
            rwy = _get_runway_28R()  # Re-fetch in case of rebinding
            if phase_before == FlightPhase.TAKEOFF and subphase_before in ("lineup", "roll", "rotate"):
                checked_ground_phases = True
                assert rwy.occupied_by == state.icao24, \
                    f"Runway released during {subphase_before}"
            if state.phase == FlightPhase.DEPARTING:
                break
        assert checked_ground_phases, "Never checked ground phases"

    def test_runway_released_at_departing(self):
        """Runway should be released when transitioning to DEPARTING."""
        state = _make_takeoff_state()
        rwy = _get_runway_28R()
        rwy.occupied_by = state.icao24

        for _ in range(2000):
            state = _update_flight_state(state, 0.5)
            if state.phase == FlightPhase.DEPARTING:
                rwy = _get_runway_28R()
                assert rwy.occupied_by is None, \
                    "Runway not released at DEPARTING"
                break

    def test_release_stores_wake_category(self):
        """_release_runway should store the departing aircraft's wake category."""
        state = _make_takeoff_state(aircraft_type="A380")
        rwy = _get_runway_28R()
        rwy.occupied_by = state.icao24
        rwy.last_departure_type = "LARGE"  # Reset

        for _ in range(2000):
            state = _update_flight_state(state, 0.5)
            if state.phase == FlightPhase.DEPARTING:
                rwy = _get_runway_28R()
                assert rwy.last_departure_type == "SUPER", \
                    f"Expected SUPER, got {rwy.last_departure_type}"
                break


class TestTakeoffPerformanceData:
    """Test the performance data tables are consistent."""

    def test_all_wake_categories_have_performance(self):
        """Every aircraft type in WAKE_CATEGORY should have TAKEOFF_PERFORMANCE."""
        from src.ingestion.fallback import WAKE_CATEGORY
        for atype in WAKE_CATEGORY:
            assert atype in TAKEOFF_PERFORMANCE, \
                f"{atype} in WAKE_CATEGORY but not TAKEOFF_PERFORMANCE"

    def test_v1_less_than_vr_less_than_v2(self):
        """V1 < VR < V2 for all aircraft types."""
        for atype, (v1, vr, v2, _, _) in TAKEOFF_PERFORMANCE.items():
            assert v1 < vr < v2, f"{atype}: V1={v1}, VR={vr}, V2={v2} not ordered"

    def test_positive_acceleration_and_climb(self):
        """All acceleration rates and climb rates should be positive."""
        for atype, (_, _, _, accel, climb) in TAKEOFF_PERFORMANCE.items():
            assert accel > 0, f"{atype} has non-positive acceleration"
            assert climb > 0, f"{atype} has non-positive climb rate"


class TestDynamicRunwayGeometry:
    """Test that takeoff uses dynamic runway geometry from _get_takeoff_runway_geometry."""

    def test_geometry_returns_valid_data(self):
        """_get_takeoff_runway_geometry should return valid start, end, heading, length."""
        start, end, heading, length_ft = _get_takeoff_runway_geometry()
        assert len(start) == 2, "start should be (lat, lon)"
        assert len(end) == 2, "end should be (lat, lon)"
        assert 0 <= heading < 360, f"Heading {heading} out of range"
        assert length_ft > 1000, f"Runway length {length_ft} ft too short"

    def test_heading_used_in_takeoff(self):
        """Aircraft heading during takeoff should match runway heading."""
        _, _, rwy_heading, _ = _get_takeoff_runway_geometry()
        state = _make_takeoff_state()
        # Run through lineup
        for _ in range(10):
            state = _update_flight_state(state, 0.5)
        assert abs(state.heading - rwy_heading) < 0.1, \
            f"Heading {state.heading} != runway heading {rwy_heading}"

    def test_osm_geometry_with_mock_data(self):
        """When OSM data is available, _get_takeoff_runway_geometry uses it."""
        from unittest.mock import patch

        mock_runway = {
            "geoPoints": [
                {"latitude": 40.0, "longitude": -74.0},
                {"latitude": 40.01, "longitude": -74.02},
                {"latitude": 40.02, "longitude": -74.04},
            ]
        }
        with patch.object(_fallback, "_get_osm_primary_runway", return_value=mock_runway):
            start, end, heading, length_ft = _get_takeoff_runway_geometry()
            # With OSM data, should NOT return SFO fallback
            assert length_ft > 1000
            # Start = departure end (far end from approach threshold = last geoPoint)
            assert abs(start[0] - 40.02) < 0.01
            # End = approach threshold (first geoPoint)
            assert abs(end[0] - 40.0) < 0.01


class TestClimbGradient:
    """Test compliance with 14 CFR 25.111 climb gradient requirements."""

    def test_minimum_climb_gradient(self):
        """Net climb gradient must be >= 2.4% (all-engine, 14 CFR 25.111)."""
        state = _make_takeoff_state()
        # Run to initial_climb phase and measure gradient
        found_climb = False
        for _ in range(2000):
            state = _update_flight_state(state, 0.5)
            if state.takeoff_subphase == "initial_climb" and state.altitude > 100:
                # Gradient = vertical_rate / ground_speed
                # vertical_rate is in fpm, ground_speed in kts
                # Convert: vertical_rate(fpm) / (ground_speed(kts) * 101.3) = gradient ratio
                # 101.3 ft/min per knot
                if state.velocity > 0:
                    gradient = state.vertical_rate / (state.velocity * 101.3)
                    assert gradient >= 0.024, \
                        f"Climb gradient {gradient:.3f} < 0.024 (2.4%) at alt {state.altitude:.0f}ft"
                    found_climb = True
                    break
        assert found_climb, "Never reached initial_climb with measurable gradient"

    def test_positive_climb_rate_throughout(self):
        """Vertical rate should be positive from liftoff through initial climb."""
        state = _make_takeoff_state()
        climbing = False
        for _ in range(2000):
            state = _update_flight_state(state, 0.5)
            if state.takeoff_subphase in ("liftoff", "initial_climb") and state.altitude > 5:
                climbing = True
                assert state.vertical_rate > 0, \
                    f"Non-positive vertical rate {state.vertical_rate} at alt {state.altitude:.0f}ft"
            if state.phase == FlightPhase.DEPARTING:
                break
        assert climbing, "Never saw climbing state"


class TestUnknownAircraftFallback:
    """Test fallback behavior for unknown aircraft types."""

    def test_unknown_type_uses_default_performance(self):
        """Aircraft types not in TAKEOFF_PERFORMANCE should use A320-class defaults."""
        state = _make_takeoff_state(aircraft_type="ZZZZ")
        seen_roll = False
        for _ in range(2000):
            state = _update_flight_state(state, 0.5)
            if state.takeoff_subphase == "roll" and state.velocity > 0:
                seen_roll = True
            if state.phase == FlightPhase.DEPARTING:
                break
        assert seen_roll, "Unknown aircraft never entered roll"
        # Should complete takeoff (not crash)
        assert state.phase == FlightPhase.DEPARTING

    def test_default_perf_matches_a320_class(self):
        """Default performance values should be reasonable A320-class numbers."""
        assert _DEFAULT_TAKEOFF_PERF[1] > 100  # VR > 100 kts
        assert _DEFAULT_TAKEOFF_PERF[1] < 170  # VR < 170 kts
        assert _DEFAULT_TAKEOFF_PERF[3] > 0    # Positive acceleration
        assert _DEFAULT_TAKEOFF_PERF[4] > 0    # Positive climb rate


class TestVerticalRateProgression:
    """Test that vertical rate ramps correctly through sub-phases."""

    def test_zero_vertical_rate_during_ground_roll(self):
        """Vertical rate should be ~0 during lineup and most of roll."""
        state = _make_takeoff_state()
        for _ in range(2000):
            state = _update_flight_state(state, 0.5)
            if state.takeoff_subphase == "lineup":
                assert state.vertical_rate == 0
            if state.takeoff_subphase == "roll" and state.velocity < 100:
                assert state.vertical_rate == 0
            if state.takeoff_subphase == "rotate":
                break

    def test_vertical_rate_ramps_during_rotate(self):
        """Vertical rate should ramp from 0 to ~500 fpm during rotation."""
        state = _make_takeoff_state()
        max_vr_in_rotate = 0
        for _ in range(2000):
            state = _update_flight_state(state, 0.5)
            if state.takeoff_subphase == "rotate":
                max_vr_in_rotate = max(max_vr_in_rotate, state.vertical_rate)
            if state.takeoff_subphase == "liftoff":
                break
        assert max_vr_in_rotate > 0, "Vertical rate never increased during rotate"
        assert max_vr_in_rotate <= 500, f"Vertical rate {max_vr_in_rotate} exceeded 500 fpm during rotate"

    def test_vertical_rate_increases_through_liftoff(self):
        """Vertical rate should increase from ~500 fpm toward initial climb rate during liftoff."""
        state = _make_takeoff_state()
        liftoff_vrates = []
        for _ in range(2000):
            state = _update_flight_state(state, 0.5)
            if state.takeoff_subphase == "liftoff":
                liftoff_vrates.append(state.vertical_rate)
            if state.takeoff_subphase == "initial_climb":
                break
        assert len(liftoff_vrates) > 1, "Liftoff phase too short to measure"
        assert liftoff_vrates[-1] > liftoff_vrates[0], \
            f"Vertical rate didn't increase during liftoff: {liftoff_vrates[0]:.0f} → {liftoff_vrates[-1]:.0f}"


class TestGroundRollDistance:
    """Test that ground roll distance accumulates correctly."""

    def test_roll_distance_increases_monotonically(self):
        """takeoff_roll_dist_ft should only increase during roll and rotate."""
        state = _make_takeoff_state()
        prev_dist = 0.0
        for _ in range(2000):
            state = _update_flight_state(state, 0.5)
            if state.takeoff_subphase in ("roll", "rotate"):
                assert state.takeoff_roll_dist_ft >= prev_dist, \
                    f"Roll distance decreased: {prev_dist:.0f} → {state.takeoff_roll_dist_ft:.0f}"
                prev_dist = state.takeoff_roll_dist_ft
            if state.takeoff_subphase == "liftoff":
                break
        assert prev_dist > 0, "No ground roll distance accumulated"

    def test_roll_distance_within_runway_length(self):
        """Ground roll should not exceed runway length."""
        _, _, _, rwy_len_ft = _get_takeoff_runway_geometry()
        state = _make_takeoff_state()
        for _ in range(2000):
            state = _update_flight_state(state, 0.5)
            if state.on_ground:
                assert state.takeoff_roll_dist_ft <= rwy_len_ft * 1.01, \
                    f"Roll distance {state.takeoff_roll_dist_ft:.0f}ft exceeds runway {rwy_len_ft:.0f}ft"
            if state.phase == FlightPhase.DEPARTING:
                break

    def test_heavy_aircraft_longer_roll(self):
        """HEAVY aircraft should use more runway than SMALL aircraft."""
        def get_max_roll(atype):
            state = _make_takeoff_state(aircraft_type=atype)
            max_dist = 0
            for _ in range(2000):
                state = _update_flight_state(state, 0.5)
                if state.on_ground:
                    max_dist = max(max_dist, state.takeoff_roll_dist_ft)
                if not state.on_ground:
                    break
            return max_dist

        heavy_roll = get_max_roll("B747")
        small_roll = get_max_roll("CRJ9")
        assert heavy_roll > small_roll, \
            f"B747 roll {heavy_roll:.0f}ft should exceed CRJ9 roll {small_roll:.0f}ft"


class TestPhaseTransitionEvents:
    """Test that phase transition events are emitted correctly."""

    def test_takeoff_to_departing_emits_event(self):
        """Transition from TAKEOFF to DEPARTING should emit a phase transition event."""
        from src.ingestion.fallback import drain_phase_transitions
        # Clear any existing events
        drain_phase_transitions()

        state = _make_takeoff_state()
        for _ in range(2000):
            state = _update_flight_state(state, 0.5)
            if state.phase == FlightPhase.DEPARTING:
                break

        events = drain_phase_transitions()
        takeoff_events = [
            e for e in events
            if e["from_phase"] == "takeoff" and e["to_phase"] == "departing"
        ]
        assert len(takeoff_events) == 1, \
            f"Expected 1 takeoff→departing event, got {len(takeoff_events)}"
        assert takeoff_events[0]["icao24"] == "test01"
        assert takeoff_events[0]["altitude"] >= 500


class TestStateResetAfterDeparting:
    """Test that takeoff state is properly reset after transitioning to DEPARTING."""

    def test_subphase_resets_to_lineup(self):
        """takeoff_subphase should reset to 'lineup' after transitioning to DEPARTING."""
        state = _make_takeoff_state()
        for _ in range(2000):
            state = _update_flight_state(state, 0.5)
            if state.phase == FlightPhase.DEPARTING:
                assert state.takeoff_subphase == "lineup", \
                    f"Subphase not reset: {state.takeoff_subphase}"
                break

    def test_roll_distance_resets_to_zero(self):
        """takeoff_roll_dist_ft should reset to 0 after transitioning to DEPARTING."""
        state = _make_takeoff_state()
        for _ in range(2000):
            state = _update_flight_state(state, 0.5)
            if state.phase == FlightPhase.DEPARTING:
                assert state.takeoff_roll_dist_ft == 0.0, \
                    f"Roll distance not reset: {state.takeoff_roll_dist_ft}"
                break

    def test_waypoint_index_resets_to_zero(self):
        """waypoint_index should reset to 0 for departure waypoint following."""
        state = _make_takeoff_state()
        for _ in range(2000):
            state = _update_flight_state(state, 0.5)
            if state.phase == FlightPhase.DEPARTING:
                assert state.waypoint_index == 0, \
                    f"waypoint_index not reset: {state.waypoint_index}"
                break


class TestRunwayOccupiedHoldShort:
    """Test hold short when runway is occupied (not wake separation)."""

    def test_hold_short_when_runway_occupied(self):
        """Aircraft should hold short if runway is physically occupied."""
        state = FlightState(
            icao24="hold01",
            callsign="TST010",
            latitude=37.615,
            longitude=-122.360,
            altitude=0,
            velocity=0,
            heading=280,
            vertical_rate=0,
            on_ground=True,
            phase=FlightPhase.TAXI_TO_RUNWAY,
            aircraft_type="A320",
            waypoint_index=999,
        )

        rwy = _get_runway_28R()
        rwy.occupied_by = "other_aircraft"  # Runway physically occupied
        rwy.last_departure_time = 0.0  # Long ago

        state = _update_flight_state(state, 0.5)
        assert state.phase == FlightPhase.TAXI_TO_RUNWAY, \
            "Should hold short when runway is occupied"
        assert state.velocity == 0

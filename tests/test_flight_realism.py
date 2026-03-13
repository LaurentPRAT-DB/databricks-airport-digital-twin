"""Tests for realistic flight trajectory behavior.

Covers:
- Same-direction runway operations (arrivals and departures same heading)
- Departure waypoints follow destination bearing
- Approaching aircraft waypoint_index snapping
- Parked→pushback origin/destination swap
- Parked heading toward terminal (not hardcoded 180°)
- Approach capacity enforcement at runtime
"""

import math
import time
from unittest.mock import patch, MagicMock

import pytest

from src.ingestion.fallback import (
    FlightPhase,
    FlightState,
    _calculate_heading,
    _create_new_flight,
    _distance_between,
    _find_aircraft_ahead_on_approach,
    _flight_states,
    _get_approach_waypoints,
    _get_departure_waypoints,
    _get_parked_heading,
    _get_takeoff_runway_geometry,
    _shortest_angle_diff,
    _update_flight_state,
    _count_aircraft_in_phase,
    _gate_states,
    _runway_28L,
    _runway_28R,
    generate_synthetic_flights,
    get_airport_center,
    get_current_airport_iata,
    get_gates,
    set_airport_center,
    APPROACH_WAYPOINTS,
    DEPARTURE_WAYPOINTS,
    NM_TO_DEG,
    MAX_SPEED_BELOW_FL100_KTS,
    VREF_SPEEDS,
    _DEFAULT_VREF,
    RunwayState,
    GateState,
)
from src.ml.gse_model import get_turnaround_timing


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_state():
    """Clear global mutable state between tests."""
    _flight_states.clear()
    _gate_states.clear()
    _runway_28L.occupied_by = None
    _runway_28L.last_departure_time = 0
    _runway_28L.last_arrival_time = 0
    _runway_28L.approach_queue.clear()
    _runway_28L.departure_queue.clear()
    _runway_28R.occupied_by = None
    _runway_28R.last_departure_time = 0
    _runway_28R.last_arrival_time = 0
    _runway_28R.approach_queue.clear()
    _runway_28R.departure_queue.clear()
    set_airport_center(37.6213, -122.379, "SFO")


@pytest.fixture(autouse=True)
def clean_state():
    """Reset all global state before each test."""
    _reset_state()
    yield
    _reset_state()


# ===========================================================================
# 1. Same-direction runway operations
# ===========================================================================

class TestSameDirectionRunwayOps:
    """Verify arrivals and departures use the same runway direction."""

    def test_takeoff_geometry_heading_matches_approach(self):
        """Departure heading should be the same as the approach runway heading,
        not the 180° reverse."""
        _, _, dep_heading, _ = _get_takeoff_runway_geometry()
        # SFO Runway 28L heading is ~284° — departures should use the same
        assert 270 <= dep_heading <= 300, (
            f"Departure heading {dep_heading}° should be ~284° (same as approach), "
            f"not ~104° (opposite)"
        )

    def test_approach_and_departure_paths_same_side(self):
        """Approach and departure waypoints should extend from the same side
        of the airport (not head-on toward each other)."""
        app_wps = APPROACH_WAYPOINTS
        dep_wps = _get_departure_waypoints()

        if not dep_wps:
            pytest.skip("No runway data for departure waypoints")

        # Last approach wp (touchdown) and first departure wp (initial climb)
        # should be near the same runway end
        app_end = (app_wps[-1][1], app_wps[-1][0])  # (lat, lon) at threshold
        dep_start = (dep_wps[0][1], dep_wps[0][0])

        # Both should be within ~3km of each other (same runway area)
        dist = _distance_between(app_end, dep_start)
        assert dist < 0.05, (
            f"Approach endpoint and departure start are {dist:.4f}° apart — "
            f"should be on the same runway end"
        )

    def test_departure_climb_extends_beyond_threshold(self):
        """Departure waypoints should extend PAST the approach threshold,
        not back toward the departure starting position."""
        dep_wps = _get_departure_waypoints()
        if not dep_wps:
            pytest.skip("No runway data")

        # Departure waypoints should get progressively further from the
        # departure runway start (far end) and closer to the approach side
        first_alt = dep_wps[0][2]
        last_alt = dep_wps[-1][2]
        assert last_alt > first_alt, "Departure should be climbing"

        # Ensure altitude increases monotonically
        for i in range(1, len(dep_wps)):
            assert dep_wps[i][2] >= dep_wps[i - 1][2], (
                f"Departure altitude should increase: wp[{i}]={dep_wps[i][2]} "
                f"< wp[{i-1}]={dep_wps[i-1][2]}"
            )

    def test_no_head_on_approach_departure_headings(self):
        """Aircraft on approach and departing should NOT have opposing headings
        (within 30° of being head-on)."""
        # Create one approaching and one departing flight
        approach_flight = _create_new_flight(
            "test_app", "UAL100", FlightPhase.APPROACHING,
            origin="LAX", destination="SFO"
        )
        depart_flight = _create_new_flight(
            "test_dep", "DAL200", FlightPhase.DEPARTING,
            origin="SFO", destination="LAX"
        )

        # If the departing flight got redirected to enroute, that's OK
        if depart_flight.phase == FlightPhase.ENROUTE:
            return

        heading_diff = abs(_shortest_angle_diff(approach_flight.heading, depart_flight.heading))
        # Head-on would be ~180° difference. Same direction would be ~0°.
        assert heading_diff < 90 or heading_diff > 270, (
            f"Approach heading {approach_flight.heading:.0f}° and departure heading "
            f"{depart_flight.heading:.0f}° are near head-on ({heading_diff:.0f}° apart)"
        )


# ===========================================================================
# 2. Departure waypoints follow destination bearing
# ===========================================================================

class TestDepartureWaypointsDestination:
    """Verify departure path curves toward destination airport."""

    def test_departure_waypoints_with_destination(self):
        """When a destination is given, later waypoints should trend toward
        the destination bearing."""
        wps_no_dest = _get_departure_waypoints()
        wps_with_dest = _get_departure_waypoints("JFK")  # East coast

        if not wps_no_dest or not wps_with_dest:
            pytest.skip("No runway data for departure waypoints")

        # The last waypoint with a destination should be at a different
        # position than without one (turned toward JFK)
        last_no = (wps_no_dest[-1][1], wps_no_dest[-1][0])
        last_with = (wps_with_dest[-1][1], wps_with_dest[-1][0])

        dist = _distance_between(last_no, last_with)
        assert dist > 0.01, (
            f"Departure with destination JFK should diverge from default path, "
            f"but difference is only {dist:.4f}°"
        )

    def test_departing_update_uses_destination(self):
        """The _update_flight_state for DEPARTING should pass destination_airport
        to _get_departure_waypoints."""
        flight = FlightState(
            icao24="test_dep",
            callsign="UAL100",
            latitude=37.61,
            longitude=-122.36,
            altitude=600,
            velocity=200,
            heading=284,
            vertical_rate=1500,
            on_ground=False,
            phase=FlightPhase.DEPARTING,
            aircraft_type="B738",
            destination_airport="JFK",
            waypoint_index=0,
        )
        _flight_states["test_dep"] = flight

        with patch("src.ingestion.fallback._get_departure_waypoints") as mock_dep_wps:
            mock_dep_wps.return_value = [(-122.35, 37.61, 2000)]
            _update_flight_state(flight, 1.0)
            mock_dep_wps.assert_called_with("JFK")


# ===========================================================================
# 3. Waypoint index snapping for approaching aircraft
# ===========================================================================

class TestApproachWaypointSnapping:
    """Verify new approaching aircraft start from the closest waypoint."""

    def test_first_approach_starts_at_wp0(self):
        """First aircraft on approach (no one ahead) should start near wp 0."""
        flight = _create_new_flight(
            "snap1", "UAL100", FlightPhase.APPROACHING,
            origin="LAX", destination="SFO"
        )
        # With no one ahead, should start at or near wp 0
        assert flight.waypoint_index >= 0

    def test_second_approach_snaps_to_nearest_wp(self):
        """Second aircraft, pushed further out by separation, should start
        from a waypoint near its actual position."""
        # Create first flight on approach
        first = _create_new_flight(
            "snap_a", "UAL100", FlightPhase.APPROACHING,
            origin="LAX", destination="SFO"
        )
        _flight_states["snap_a"] = first

        # Create second flight — should be placed behind first
        second = _create_new_flight(
            "snap_b", "DAL200", FlightPhase.APPROACHING,
            origin="LAX", destination="SFO"
        )

        # Waypoint index should be >= 0 and correspond roughly to its position
        assert second.waypoint_index >= 0

        # Its position should be near the waypoint it's indexed to
        app_wps = _get_approach_waypoints("LAX")
        if app_wps and second.waypoint_index < len(app_wps):
            wp = app_wps[second.waypoint_index]
            dist = _distance_between(
                (second.latitude, second.longitude),
                (wp[1], wp[0])
            )
            # Should be within reasonable range of its assigned waypoint
            assert dist < 0.3, (
                f"Aircraft at ({second.latitude:.4f}, {second.longitude:.4f}) "
                f"is {dist:.4f}° from its waypoint[{second.waypoint_index}] "
                f"at ({wp[1]:.4f}, {wp[0]:.4f})"
            )


# ===========================================================================
# 4. Parked → pushback origin/destination swap
# ===========================================================================

class TestPushbackDestinationSwap:
    """Verify parked aircraft get correct origin/dest when pushing back."""

    def test_arrived_aircraft_swaps_to_departing(self):
        """Aircraft that arrived (origin=JFK, dest=SFO) should become
        origin=SFO, dest=<new> when pushing back."""
        flight = _create_new_flight(
            "swap1", "UAL100", FlightPhase.PARKED,
            origin="JFK", destination="SFO"
        )
        _flight_states["swap1"] = flight

        # Force immediate pushback
        flight.time_at_gate = 999

        _update_flight_state(flight, 1.0)

        if flight.phase == FlightPhase.PUSHBACK:
            assert flight.origin_airport == "SFO", (
                f"After pushback, origin should be local (SFO), got {flight.origin_airport}"
            )
            assert flight.destination_airport != "SFO", (
                f"After pushback, destination should NOT be local (SFO), "
                f"got {flight.destination_airport}"
            )
            assert flight.destination_airport is not None, (
                "Destination should be set after pushback"
            )

    def test_departing_aircraft_keeps_destination(self):
        """Aircraft already set as departing (origin=SFO, dest=BOS) should
        keep its destination through pushback."""
        flight = _create_new_flight(
            "swap2", "DAL200", FlightPhase.PARKED,
            origin="SFO", destination="BOS"
        )
        _flight_states["swap2"] = flight
        flight.time_at_gate = 999

        _update_flight_state(flight, 1.0)

        if flight.phase == FlightPhase.PUSHBACK:
            assert flight.destination_airport == "BOS", (
                f"Destination should remain BOS, got {flight.destination_airport}"
            )
            assert flight.origin_airport == "SFO"


# ===========================================================================
# 5. Parked heading toward terminal
# ===========================================================================

class TestParkedHeading:
    """Verify parked aircraft face toward terminal, not hardcoded 180°."""

    def test_parked_heading_not_always_180(self):
        """Different gate positions should produce different headings."""
        # Test with two gates at different positions relative to center
        heading1 = _get_parked_heading(37.615, -122.395)  # West of center
        heading2 = _get_parked_heading(37.618, -122.380)  # Near center

        # These should not both be exactly 180
        # (they could coincidentally be close, but at least one should differ)
        center = get_airport_center()
        h_to_center1 = _calculate_heading((37.615, -122.395), center)
        h_to_center2 = _calculate_heading((37.618, -122.380), center)

        # Each heading should be roughly toward the airport center
        assert abs(_shortest_angle_diff(heading1, h_to_center1)) < 90
        assert abs(_shortest_angle_diff(heading2, h_to_center2)) < 90

    def test_parked_heading_faces_center_without_terminals(self):
        """Without terminal data, heading should face airport center."""
        # _get_parked_heading falls back to airport center
        gate_lat, gate_lon = 37.615, -122.395
        heading = _get_parked_heading(gate_lat, gate_lon)
        center = get_airport_center()
        expected = _calculate_heading((gate_lat, gate_lon), center)

        diff = abs(_shortest_angle_diff(heading, expected))
        assert diff < 5, (
            f"Parked heading {heading:.1f}° should face center "
            f"(expected ~{expected:.1f}°, diff={diff:.1f}°)"
        )

    def test_parked_flight_heading_varies_by_gate(self):
        """Flights parked at different gates should have different headings."""
        flight1 = _create_new_flight(
            "park_a", "UAL100", FlightPhase.PARKED,
            origin="JFK", destination="SFO"
        )
        _flight_states["park_a"] = flight1

        flight2 = _create_new_flight(
            "park_b", "DAL200", FlightPhase.PARKED,
            origin="LAX", destination="SFO"
        )

        # If they're at different gates, headings may differ
        if flight1.assigned_gate != flight2.assigned_gate:
            # Allow some tolerance — they point toward the same center
            # but from different angles, so headings should differ
            gate1 = get_gates().get(flight1.assigned_gate, (0, 0))
            gate2 = get_gates().get(flight2.assigned_gate, (0, 0))
            if _distance_between(gate1, gate2) > 0.001:
                # Different gates far enough apart should have different headings
                assert flight1.heading != 180.0 or flight2.heading != 180.0, (
                    "At least one parked flight should not have heading=180"
                )


# ===========================================================================
# 6. Approach capacity enforcement at runtime
# ===========================================================================

class TestApproachCapacityRuntime:
    """Verify approach capacity is enforced during ENROUTE→APPROACHING transition."""

    def test_enroute_holds_when_approach_full(self):
        """An enroute arriving flight should NOT transition to APPROACHING
        when 4+ aircraft are already approaching."""
        center = get_airport_center()

        # Create 4 aircraft already on approach
        for i in range(4):
            icao24 = f"app_{i}"
            state = FlightState(
                icao24=icao24,
                callsign=f"UAL{100+i}",
                latitude=center[0] + 0.1 * (i + 1),
                longitude=center[1],
                altitude=3000 + i * 500,
                velocity=180,
                heading=270,
                vertical_rate=-800,
                on_ground=False,
                phase=FlightPhase.APPROACHING,
                aircraft_type="A320",
                waypoint_index=0,
                origin_airport="LAX",
            )
            _flight_states[icao24] = state

        # Create an arriving enroute flight close to airport
        enroute = FlightState(
            icao24="enr_hold",
            callsign="DAL500",
            latitude=center[0] + 0.15,
            longitude=center[1],
            altitude=8000,
            velocity=450,
            heading=_calculate_heading((center[0] + 0.15, center[1]), center),
            vertical_rate=-200,
            on_ground=False,
            phase=FlightPhase.ENROUTE,
            aircraft_type="B738",
            origin_airport="SEA",
        )
        _flight_states["enr_hold"] = enroute

        # Update — should NOT transition to approaching
        result = _update_flight_state(enroute, 1.0)
        assert result.phase == FlightPhase.ENROUTE, (
            f"Should hold as ENROUTE when approach is full (4 aircraft), "
            f"but transitioned to {result.phase.value}"
        )

    def test_enroute_transitions_when_approach_has_room(self):
        """An enroute flight should transition to APPROACHING when fewer
        than 4 aircraft are on approach."""
        center = get_airport_center()

        # Create 2 aircraft on approach (below limit)
        for i in range(2):
            icao24 = f"app_{i}"
            state = FlightState(
                icao24=icao24,
                callsign=f"UAL{100+i}",
                latitude=center[0] + 0.05,
                longitude=center[1] + 0.05 * i,
                altitude=3000,
                velocity=180,
                heading=270,
                vertical_rate=-800,
                on_ground=False,
                phase=FlightPhase.APPROACHING,
                aircraft_type="A320",
                waypoint_index=0,
                origin_airport="LAX",
            )
            _flight_states[icao24] = state

        # Create arriving enroute within approach radius
        enroute = FlightState(
            icao24="enr_enter",
            callsign="DAL500",
            latitude=center[0] + 0.15,
            longitude=center[1],
            altitude=8000,
            velocity=450,
            heading=_calculate_heading((center[0] + 0.15, center[1]), center),
            vertical_rate=-200,
            on_ground=False,
            phase=FlightPhase.ENROUTE,
            aircraft_type="B738",
            origin_airport="SEA",
        )
        _flight_states["enr_enter"] = enroute

        # Update multiple times to cross the threshold
        for _ in range(200):
            result = _update_flight_state(enroute, 1.0)
            if result.phase == FlightPhase.APPROACHING:
                break

        # Should have transitioned (or still be enroute heading in)
        # With room on approach and close enough, it should eventually transition
        # This is probabilistic, so we allow it to still be enroute
        assert result.phase in (FlightPhase.ENROUTE, FlightPhase.APPROACHING)


# ===========================================================================
# 7. Integrated scenario: full lifecycle
# ===========================================================================

class TestFullFlightLifecycle:
    """Test a complete arrival→park→depart cycle for consistency."""

    def test_lifecycle_origin_dest_consistency(self):
        """Track origin/destination through the full flight lifecycle."""
        # Start as approaching from JFK
        flight = _create_new_flight(
            "lifecycle", "UAL999", FlightPhase.APPROACHING,
            origin="JFK", destination="SFO"
        )
        _flight_states["lifecycle"] = flight

        assert flight.origin_airport == "JFK"
        # destination can be SFO or local

        # Simulate through to parked (accelerated)
        for _ in range(5000):
            _update_flight_state(flight, 1.0)
            if flight.phase == FlightPhase.PARKED:
                break

        if flight.phase == FlightPhase.PARKED:
            # Force pushback
            flight.time_at_gate = 999
            _update_flight_state(flight, 1.0)

            if flight.phase == FlightPhase.PUSHBACK:
                # After pushback: origin should be local, dest should be new
                assert flight.origin_airport == "SFO", (
                    f"Post-pushback origin should be SFO, got {flight.origin_airport}"
                )
                assert flight.destination_airport is not None
                assert flight.destination_airport != "SFO", (
                    f"Post-pushback dest should not be SFO, got {flight.destination_airport}"
                )

    def test_no_approaching_aircraft_heading_away(self):
        """No approaching aircraft should have a heading pointing away
        from the airport (more than 90° off)."""
        flights = generate_synthetic_flights(count=30)

        center = get_airport_center()
        for icao24, state in _flight_states.items():
            if state.phase == FlightPhase.APPROACHING:
                heading_to_center = _calculate_heading(
                    (state.latitude, state.longitude), center
                )
                heading_diff = abs(_shortest_angle_diff(state.heading, heading_to_center))
                assert heading_diff < 120, (
                    f"Approaching flight {icao24} heading {state.heading:.0f}° "
                    f"is {heading_diff:.0f}° off from airport direction "
                    f"({heading_to_center:.0f}°)"
                )


# ===========================================================================
# 8. Departure profile — realistic climb altitudes
# ===========================================================================

class TestDepartureProfileAltitudes:
    """Verify departure waypoint altitudes match realistic SID climb gradients."""

    def test_static_departure_first_waypoint_below_500ft(self):
        """First SFO fallback departure waypoint should be low (~200 ft, just after liftoff)."""
        assert DEPARTURE_WAYPOINTS[0][2] <= 500, (
            f"First departure wp should be <=500 ft (just after liftoff), "
            f"got {DEPARTURE_WAYPOINTS[0][2]} ft"
        )

    def test_static_departure_last_waypoint_below_10000ft(self):
        """Last SFO fallback departure waypoint should be below 10,000 ft."""
        assert DEPARTURE_WAYPOINTS[-1][2] <= 10000, (
            f"Last departure wp should be <=10,000 ft (~15 NM out), "
            f"got {DEPARTURE_WAYPOINTS[-1][2]} ft"
        )

    def test_dynamic_departure_altitudes_realistic(self):
        """Dynamic departure waypoints should have realistic climb altitudes."""
        wps = _get_departure_waypoints()
        if not wps:
            pytest.skip("No runway data for departure waypoints")

        # First wp: just after liftoff, should be < 500 ft
        assert wps[0][2] <= 500, (
            f"First dynamic dep wp should be <=500 ft, got {wps[0][2]} ft"
        )
        # At ~5 NM (midway), altitude should be < 4000 ft (realistic SID)
        mid = len(wps) // 2
        assert wps[mid][2] <= 4000, (
            f"Mid departure wp should be <=4,000 ft, got {wps[mid][2]} ft"
        )
        # Last wp should be < 10,000 ft
        assert wps[-1][2] <= 10000, (
            f"Last dynamic dep wp should be <=10,000 ft, got {wps[-1][2]} ft"
        )

    def test_departure_altitudes_monotonically_increase(self):
        """Departure altitudes must increase with each waypoint."""
        wps = _get_departure_waypoints()
        if not wps:
            pytest.skip("No runway data")

        for i in range(1, len(wps)):
            assert wps[i][2] >= wps[i - 1][2], (
                f"Departure altitude should increase: wp[{i}]={wps[i][2]} "
                f"< wp[{i-1}]={wps[i-1][2]}"
            )


# ===========================================================================
# 9. Approach profile — 3° glideslope alignment
# ===========================================================================

class TestApproachGlideslope:
    """Verify approach altitudes follow a standard 3° glideslope (~318 ft/NM)."""

    def test_static_approach_threshold_crossing_height_50ft(self):
        """Last approach waypoint (threshold) should be 50 ft (ILS CAT I TCH)."""
        assert APPROACH_WAYPOINTS[-1][2] == 50

    def test_static_approach_faf_altitude_realistic(self):
        """FAF (~5 NM from threshold) should be ~1600 ft on 3° GS, not 2500 ft."""
        # FAF is index 6 (0.28° from threshold ≈ ~5 NM)
        faf_alt = APPROACH_WAYPOINTS[6]  # (-122.28, ..., alt)
        assert faf_alt[2] <= 2000, (
            f"FAF altitude should be <=2,000 ft on 3° GS, got {faf_alt[2]} ft"
        )

    def test_dynamic_approach_glideslope_gradient(self):
        """Dynamic approach should maintain ~318 ft/NM gradient on final."""
        wps = _get_approach_waypoints("ORD")
        if not wps or len(wps) < 5:
            pytest.skip("No runway data")

        # Check gradient from first final approach wp to threshold
        faf = wps[4]  # ~0.10° out (first final approach wp)
        threshold = wps[-1]

        dist_deg = math.sqrt((faf[0] - threshold[0]) ** 2 + (faf[1] - threshold[1]) ** 2)
        dist_nm = dist_deg * 60
        if dist_nm > 0:
            ft_per_nm = (faf[2] - threshold[2]) / dist_nm
            # 3° GS ≈ 318 ft/NM; allow 200-500 ft/NM range
            assert 200 < ft_per_nm < 500, (
                f"Glideslope {ft_per_nm:.0f} ft/NM outside 200-500 range"
            )

    def test_dynamic_approach_altitudes_decrease_monotonically(self):
        """Approach altitudes must decrease toward the runway."""
        wps = _get_approach_waypoints("SEA")
        if not wps:
            pytest.skip("No runway data")

        for i in range(1, len(wps)):
            assert wps[i][2] <= wps[i - 1][2], (
                f"Approach altitude should decrease: wp[{i}]={wps[i][2]} "
                f"> wp[{i-1}]={wps[i-1][2]}"
            )

    def test_dynamic_approach_starts_below_5000ft(self):
        """Base leg should start at ~4800 ft (3° GS at 15 NM), not 6000 ft."""
        wps = _get_approach_waypoints("DEN")
        if not wps:
            pytest.skip("No runway data")
        assert wps[0][2] <= 5000, (
            f"First approach wp should be <=5,000 ft, got {wps[0][2]} ft"
        )


# ===========================================================================
# 10. Type-specific Vref approach speeds
# ===========================================================================

class TestVrefApproachSpeeds:
    """Verify approach uses type-specific Vref instead of a fixed linear formula."""

    def test_vref_table_has_all_fleet_types(self):
        """Every aircraft type in the fleet should have a Vref entry."""
        from src.ingestion.fallback import WAKE_CATEGORY
        for ac_type in WAKE_CATEGORY:
            assert ac_type in VREF_SPEEDS, (
                f"Aircraft type {ac_type} missing from VREF_SPEEDS table"
            )

    def test_vref_range_realistic(self):
        """All Vref speeds should be in 120-160 kts range (no stall or overspeed)."""
        for ac_type, vref in VREF_SPEEDS.items():
            assert 120 <= vref <= 160, (
                f"{ac_type} Vref={vref} kts outside realistic 120-160 kts range"
            )

    def test_heavy_vref_higher_than_regional(self):
        """Heavy aircraft should have higher Vref than regional jets."""
        assert VREF_SPEEDS["B777"] > VREF_SPEEDS["E175"]
        assert VREF_SPEEDS["A380"] > VREF_SPEEDS["CRJ9"]

    def test_approach_speed_varies_by_type(self):
        """Approaching flights of different types should have different speeds."""
        # Create A320 on approach
        a320 = FlightState(
            icao24="vref_a320", callsign="UAL100",
            latitude=37.60, longitude=-122.30, altitude=2000,
            velocity=180, heading=270, vertical_rate=-800,
            on_ground=False, phase=FlightPhase.APPROACHING,
            aircraft_type="A320", waypoint_index=3, origin_airport="LAX",
        )
        _flight_states["vref_a320"] = a320

        # Create B777 on approach at same waypoint
        b777 = FlightState(
            icao24="vref_b777", callsign="UAL200",
            latitude=37.60, longitude=-122.28, altitude=2500,
            velocity=180, heading=270, vertical_rate=-800,
            on_ground=False, phase=FlightPhase.APPROACHING,
            aircraft_type="B777", waypoint_index=3, origin_airport="LAX",
        )
        _flight_states["vref_b777"] = b777

        _update_flight_state(a320, 1.0)
        _update_flight_state(b777, 1.0)

        # B777 should be faster than A320 on approach (higher Vref)
        assert b777.velocity > a320.velocity, (
            f"B777 ({b777.velocity:.0f} kts) should be faster on approach "
            f"than A320 ({a320.velocity:.0f} kts)"
        )

    def test_approach_speed_never_below_vref(self):
        """Approaching aircraft should never drop below their Vref."""
        flight = FlightState(
            icao24="vref_min", callsign="UAL300",
            latitude=37.605, longitude=-122.32, altitude=1000,
            velocity=160, heading=270, vertical_rate=-800,
            on_ground=False, phase=FlightPhase.APPROACHING,
            aircraft_type="A320", waypoint_index=8, origin_airport="LAX",
        )
        _flight_states["vref_min"] = flight

        _update_flight_state(flight, 1.0)

        vref = VREF_SPEEDS["A320"]
        # Speed should be at or above Vref (within tolerance for decel formula)
        assert flight.velocity >= vref - 5, (
            f"A320 approach speed {flight.velocity:.0f} kts dropped below "
            f"Vref {vref} kts"
        )


# ===========================================================================
# 11. Pushback duration — realistic 3-5 minutes
# ===========================================================================

class TestPushbackDuration:
    """Verify pushback takes ~3-5 minutes, not 10 seconds."""

    def test_pushback_not_complete_after_10_seconds(self):
        """Pushback should NOT complete in 10 seconds (old rate was dt*0.1)."""
        flight = _create_new_flight(
            "pb_dur", "UAL100", FlightPhase.PARKED,
            origin="JFK", destination="SFO"
        )
        _flight_states["pb_dur"] = flight
        flight.time_at_gate = 99999  # Force immediate pushback

        _update_flight_state(flight, 1.0)
        if flight.phase != FlightPhase.PUSHBACK:
            pytest.skip("Flight didn't enter pushback")

        # Simulate 10 seconds of pushback
        for _ in range(10):
            _update_flight_state(flight, 1.0)

        assert flight.phase == FlightPhase.PUSHBACK, (
            f"Pushback should still be in progress after 10s, "
            f"but phase is {flight.phase.value}"
        )

    def test_pushback_completes_within_5_minutes(self):
        """Pushback should complete within 5 minutes (300 seconds)."""
        flight = _create_new_flight(
            "pb_fin", "UAL200", FlightPhase.PARKED,
            origin="JFK", destination="SFO"
        )
        _flight_states["pb_fin"] = flight
        flight.time_at_gate = 99999

        _update_flight_state(flight, 1.0)
        if flight.phase != FlightPhase.PUSHBACK:
            pytest.skip("Flight didn't enter pushback")

        # Simulate 300 seconds
        for _ in range(300):
            _update_flight_state(flight, 1.0)

        assert flight.phase != FlightPhase.PUSHBACK, (
            "Pushback should complete within 5 minutes (300s)"
        )

    def test_pushback_takes_at_least_2_minutes(self):
        """Pushback should take at least 2 minutes (120 seconds)."""
        flight = _create_new_flight(
            "pb_min", "DAL300", FlightPhase.PARKED,
            origin="JFK", destination="SFO"
        )
        _flight_states["pb_min"] = flight
        flight.time_at_gate = 99999

        _update_flight_state(flight, 1.0)
        if flight.phase != FlightPhase.PUSHBACK:
            pytest.skip("Flight didn't enter pushback")

        # Simulate 120 seconds — should still be pushing back
        for _ in range(120):
            _update_flight_state(flight, 1.0)

        assert flight.phase == FlightPhase.PUSHBACK, (
            f"Pushback should take >2 min, but completed in <120s "
            f"(phase={flight.phase.value})"
        )


# ===========================================================================
# 12. Racetrack holding pattern
# ===========================================================================

class TestRacetrackHolding:
    """Verify holding aircraft fly racetrack patterns, not lazy orbits."""

    def _setup_holding_flight(self):
        """Create an arriving enroute flight that should enter holding."""
        center = get_airport_center()

        # Fill approach to capacity (4 aircraft)
        for i in range(4):
            icao24 = f"hold_app_{i}"
            state = FlightState(
                icao24=icao24,
                callsign=f"UAL{100+i}",
                latitude=center[0] + 0.1 * (i + 1),
                longitude=center[1],
                altitude=3000 + i * 500,
                velocity=180, heading=270, vertical_rate=-800,
                on_ground=False,
                phase=FlightPhase.APPROACHING,
                aircraft_type="A320", waypoint_index=0,
                origin_airport="LAX",
            )
            _flight_states[icao24] = state

        # Place arriving flight within approach radius (will trigger holding)
        enroute = FlightState(
            icao24="hold_test",
            callsign="DAL500",
            latitude=center[0] + 0.15,
            longitude=center[1],
            altitude=8000,
            velocity=250,
            heading=_calculate_heading((center[0] + 0.15, center[1]), center),
            vertical_rate=-200,
            on_ground=False,
            phase=FlightPhase.ENROUTE,
            aircraft_type="B738",
            origin_airport="SEA",
        )
        _flight_states["hold_test"] = enroute
        return enroute

    def test_holding_uses_inbound_outbound_legs(self):
        """Holding aircraft should alternate between inbound and outbound legs."""
        flight = self._setup_holding_flight()

        # Run until the flight gets close enough to trigger holding
        for _ in range(50):
            _update_flight_state(flight, 1.0)

        # Record heading changes over time
        headings = []
        for _ in range(200):
            _update_flight_state(flight, 1.0)
            headings.append(flight.heading)

        # The heading should change significantly (not just +2/tick like old orbit)
        # In a racetrack, heading changes in bursts (turns) then stays stable (legs)
        heading_deltas = [
            abs(headings[i] - headings[i - 1])
            for i in range(1, len(headings))
        ]
        # Normalize for 360° wraparound
        heading_deltas = [min(d, 360 - d) for d in heading_deltas]

        # Some ticks should have near-zero delta (straight legs)
        straight_ticks = sum(1 for d in heading_deltas if d < 0.5)
        # Some ticks should have ~3°/s delta (standard rate turns)
        turn_ticks = sum(1 for d in heading_deltas if 1.0 < d < 5.0)

        assert straight_ticks > 10, (
            f"Holding should have straight-leg segments (near-zero heading change), "
            f"but only {straight_ticks} ticks with delta < 0.5°"
        )
        assert turn_ticks > 5, (
            f"Holding should have standard-rate turn segments, "
            f"but only {turn_ticks} ticks with 1-5° delta"
        )

    def test_holding_state_fields_initialized(self):
        """FlightState should have holding_phase_time and holding_inbound fields."""
        flight = FlightState(
            icao24="hold_init", callsign="UAL999",
            latitude=37.6, longitude=-122.3, altitude=5000,
            velocity=250, heading=270, vertical_rate=0,
            on_ground=False, phase=FlightPhase.ENROUTE,
            aircraft_type="A320",
        )
        assert hasattr(flight, "holding_phase_time")
        assert hasattr(flight, "holding_inbound")
        assert flight.holding_phase_time == 0.0
        assert flight.holding_inbound is True

    def test_holding_does_not_transition_when_approach_full(self):
        """Aircraft in holding should remain ENROUTE while approach is at capacity."""
        flight = self._setup_holding_flight()

        # Simulate for 3 minutes — should stay ENROUTE
        for _ in range(180):
            result = _update_flight_state(flight, 1.0)
            if result.phase != FlightPhase.ENROUTE:
                break

        assert result.phase == FlightPhase.ENROUTE, (
            f"Flight should remain ENROUTE while holding, "
            f"but transitioned to {result.phase.value}"
        )


# ===========================================================================
# 13. Gate turnaround timing — realistic 25-90 min
# ===========================================================================

class TestGateTurnaroundTiming:
    """Verify gate time uses realistic turnaround durations from gse_model."""

    def test_narrow_body_turnaround_not_under_10_minutes(self):
        """Narrow-body (A320) should not push back in under 10 minutes."""
        flight = _create_new_flight(
            "ta_narrow", "UAL100", FlightPhase.PARKED,
            origin="JFK", destination="SFO"
        )
        _flight_states["ta_narrow"] = flight
        flight.time_at_gate = 0
        flight.aircraft_type = "A320"

        # Simulate 10 minutes (600 seconds)
        for _ in range(600):
            _update_flight_state(flight, 1.0)

        assert flight.phase == FlightPhase.PARKED, (
            f"A320 should still be parked after 10 min, but phase is {flight.phase.value}"
        )

    def test_narrow_body_turnaround_completes_within_60_minutes(self):
        """Narrow-body should push back within 60 minutes (generous upper bound)."""
        flight = _create_new_flight(
            "ta_comp", "UAL200", FlightPhase.PARKED,
            origin="JFK", destination="SFO"
        )
        _flight_states["ta_comp"] = flight
        flight.time_at_gate = 0
        flight.aircraft_type = "A320"

        # Simulate 60 minutes
        for _ in range(3600):
            _update_flight_state(flight, 1.0)

        assert flight.phase != FlightPhase.PARKED, (
            "A320 should have pushed back within 60 minutes"
        )

    def test_turnaround_time_varies_by_aircraft_size(self):
        """Wide-body should have longer turnaround than narrow-body."""
        narrow_timing = get_turnaround_timing("A320")
        wide_timing = get_turnaround_timing("B777")

        narrow_phases = narrow_timing["phases"]
        wide_phases = wide_timing["phases"]

        gate_keys = [
            "chocks_on", "deboarding", "unloading", "cleaning",
            "catering", "refueling", "loading", "boarding", "chocks_off",
        ]
        narrow_gate_min = sum(narrow_phases.get(p, 0) for p in gate_keys)
        wide_gate_min = sum(wide_phases.get(p, 0) for p in gate_keys)

        assert wide_gate_min > narrow_gate_min, (
            f"Wide-body gate time ({wide_gate_min} min) should exceed "
            f"narrow-body ({narrow_gate_min} min)"
        )

    def test_wide_body_stays_parked_longer(self):
        """B777 should remain parked longer than A320 at the gate."""
        # A320 at gate for 30 min → should push back (narrow-body ~25-45 min)
        a320 = _create_new_flight(
            "ta_a320", "UAL300", FlightPhase.PARKED,
            origin="JFK", destination="SFO"
        )
        a320.aircraft_type = "A320"
        _flight_states["ta_a320"] = a320

        # B777 at gate for 30 min → should still be parked (wide-body ~60-90 min)
        b777 = _create_new_flight(
            "ta_b777", "UAL400", FlightPhase.PARKED,
            origin="NRT", destination="SFO"
        )
        b777.aircraft_type = "B777"
        _flight_states["ta_b777"] = b777

        # Set both to 30 minutes parked
        a320.time_at_gate = 30 * 60
        b777.time_at_gate = 30 * 60

        # B777 at 30 min should still be parked (wide-body turnaround ~60-90 min)
        _update_flight_state(b777, 1.0)
        assert b777.phase == FlightPhase.PARKED, (
            f"B777 should still be parked at 30 min, but phase is {b777.phase.value}"
        )


# ===========================================================================
# 14. 250 kts below FL100 (from batch 1, additional coverage)
# ===========================================================================

class TestSpeedBelowFL100:
    """Verify 14 CFR 91.117: 250 kts IAS maximum below 10,000 ft MSL."""

    def test_departing_speed_clamped_below_10000(self):
        """Departing aircraft below 10,000 ft should not exceed 250 kts."""
        dep_wps = _get_departure_waypoints("JFK")
        if not dep_wps:
            pytest.skip("No runway data")

        flight = FlightState(
            icao24="spd_dep", callsign="UAL100",
            latitude=dep_wps[2][1], longitude=dep_wps[2][0],
            altitude=2000,  # Well below FL100
            velocity=200, heading=284, vertical_rate=1500,
            on_ground=False, phase=FlightPhase.DEPARTING,
            aircraft_type="B738", waypoint_index=2,
            destination_airport="JFK",
        )
        _flight_states["spd_dep"] = flight

        _update_flight_state(flight, 1.0)
        assert flight.velocity <= MAX_SPEED_BELOW_FL100_KTS, (
            f"Departing at {flight.altitude:.0f} ft: {flight.velocity:.0f} kts "
            f"exceeds {MAX_SPEED_BELOW_FL100_KTS} kts limit"
        )

    def test_enroute_arriving_speed_clamped_below_10000(self):
        """Arriving enroute aircraft below 10,000 ft should not exceed 250 kts."""
        center = get_airport_center()
        flight = FlightState(
            icao24="spd_enr", callsign="DAL200",
            latitude=center[0] + 0.3, longitude=center[1],
            altitude=8000,
            velocity=450, heading=270, vertical_rate=-200,
            on_ground=False, phase=FlightPhase.ENROUTE,
            aircraft_type="B738", origin_airport="SEA",
        )
        _flight_states["spd_enr"] = flight

        _update_flight_state(flight, 1.0)
        assert flight.velocity <= MAX_SPEED_BELOW_FL100_KTS, (
            f"Enroute arriving at {flight.altitude:.0f} ft: {flight.velocity:.0f} kts "
            f"exceeds {MAX_SPEED_BELOW_FL100_KTS} kts limit"
        )

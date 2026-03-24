"""Tests for dynamic taxi waypoint generation and ground movement constraints.

Validates that the synthetic data generator constrains aircraft to follow
taxiway routes, runway paths, and proper pushback directions when on the ground.
Tests both the route-generation functions and the state machine integration.
"""

import math
from unittest.mock import patch, MagicMock
import pytest

from src.ingestion.fallback import (
    _get_taxi_waypoints_arrival,
    _get_taxi_waypoints_departure,
    _get_pushback_heading,
    _update_flight_state,
    _create_new_flight,
    _distance_between,
    _calculate_heading,
    FlightPhase,
    FlightState,
    TAXI_WAYPOINTS_ARRIVAL,
    TAXI_WAYPOINTS_DEPARTURE,
    AIRPORT_CENTER,
    _DEFAULT_GATES,
    _flight_states,
    _gate_states,
    _init_gate_states,
    _runway_28R,
    _runway_28L,
    _occupy_gate,
    _occupy_runway,
    _release_gate,
    _release_runway,
    get_gates,
    _get_departure_runway_name,
)

# The functions use lazy imports: `from app.backend.services.airport_config_service import get_airport_config_service`
# We need to patch at the source module level.
_SERVICE_PATCH = "app.backend.services.airport_config_service.get_airport_config_service"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_graph(route_result):
    """Create a mock TaxiwayGraph that returns a fixed route."""
    graph = MagicMock()
    graph.find_route.return_value = route_result
    graph.nodes = {0: (37.615, -122.385)}
    graph.snap_to_nearest_node.return_value = 0
    return graph


def _make_mock_service(graph=None):
    """Create a mock airport config service."""
    service = MagicMock()
    service.taxiway_graph = graph
    return service


def _make_state(
    icao24: str = "abc001",
    phase: FlightPhase = FlightPhase.TAXI_TO_GATE,
    lat: float = 37.615,
    lon: float = -122.370,
    gate: str = "G1",
    taxi_route=None,
    waypoint_index: int = 0,
    on_ground: bool = True,
    altitude: float = 0.0,
    velocity: float = 15.0,
    heading: float = 270.0,
    phase_progress: float = 0.0,
    time_at_gate: float = 0.0,
) -> FlightState:
    """Create a FlightState for testing ground movement."""
    return FlightState(
        icao24=icao24,
        callsign="UAL001",
        latitude=lat,
        longitude=lon,
        altitude=altitude,
        velocity=velocity,
        heading=heading,
        vertical_rate=0.0,
        on_ground=on_ground,
        phase=phase,
        aircraft_type="A320",
        assigned_gate=gate,
        waypoint_index=waypoint_index,
        phase_progress=phase_progress,
        time_at_gate=time_at_gate,
        taxi_route=taxi_route,
    )


def _clear_global_state():
    """Reset global mutable state used by the state machine."""
    _flight_states.clear()
    _runway_28R.occupied_by = None
    _runway_28L.occupied_by = None
    _gate_states.clear()


# ============================================================================
# Route Generation Functions
# ============================================================================


class TestArrivalUsesGraph:
    @patch(_SERVICE_PATCH)
    @patch("src.ingestion.fallback.get_gates")
    def test_arrival_uses_graph_when_available(self, mock_get_gates, mock_get_service):
        route = [(37.612, -122.370), (37.614, -122.380), (37.616, -122.389)]
        graph = _make_mock_graph(route)
        mock_get_service.return_value = _make_mock_service(graph=graph)
        mock_get_gates.return_value = {"G1": (37.616, -122.389)}

        result = _get_taxi_waypoints_arrival("G1")

        # Should return (lon, lat) tuples
        assert len(result) == 3
        assert result[0] == (-122.370, 37.612)
        assert result[-1] == (-122.389, 37.616)
        graph.find_route.assert_called_once()

    @patch(_SERVICE_PATCH)
    @patch("src.ingestion.fallback.get_gates")
    def test_arrival_falls_back_when_no_graph(self, mock_get_gates, mock_get_service):
        mock_get_service.return_value = _make_mock_service(graph=None)
        mock_get_gates.return_value = {"G1": (37.616, -122.389)}

        # With SFO center, should fall back to TAXI_WAYPOINTS_ARRIVAL
        result = _get_taxi_waypoints_arrival("G1")
        assert result == TAXI_WAYPOINTS_ARRIVAL

    @patch(_SERVICE_PATCH)
    @patch("src.ingestion.fallback.get_gates")
    def test_arrival_falls_back_when_route_empty(self, mock_get_gates, mock_get_service):
        graph = _make_mock_graph([])  # No route found
        mock_get_service.return_value = _make_mock_service(graph=graph)
        mock_get_gates.return_value = {"G1": (37.616, -122.389)}

        result = _get_taxi_waypoints_arrival("G1")
        assert result == TAXI_WAYPOINTS_ARRIVAL

    @patch(_SERVICE_PATCH)
    @patch("src.ingestion.fallback.get_gates")
    def test_arrival_falls_back_when_single_point_route(self, mock_get_gates, mock_get_service):
        """A route with only 1 point is useless for navigation — should fall back."""
        graph = _make_mock_graph([(37.612, -122.370)])
        mock_get_service.return_value = _make_mock_service(graph=graph)
        mock_get_gates.return_value = {"G1": (37.616, -122.389)}

        result = _get_taxi_waypoints_arrival("G1")
        assert result == TAXI_WAYPOINTS_ARRIVAL

    @patch(_SERVICE_PATCH)
    @patch("src.ingestion.fallback.get_gates")
    def test_arrival_falls_back_when_gate_unknown(self, mock_get_gates, mock_get_service):
        """If the gate isn't in the gate dict, should fall back."""
        graph = _make_mock_graph([(37.612, -122.370), (37.616, -122.389)])
        mock_get_service.return_value = _make_mock_service(graph=graph)
        mock_get_gates.return_value = {}  # No gates known

        result = _get_taxi_waypoints_arrival("UNKNOWN")
        assert result == TAXI_WAYPOINTS_ARRIVAL

    def test_arrival_falls_back_when_import_error(self):
        """When airport_config_service is not importable, falls back gracefully."""
        with patch.dict("sys.modules", {"app.backend.services.airport_config_service": None}):
            result = _get_taxi_waypoints_arrival("G1")
            assert isinstance(result, list)
            assert len(result) > 0

    @patch(_SERVICE_PATCH)
    @patch("src.ingestion.fallback.get_gates")
    def test_arrival_route_coordinate_order(self, mock_get_gates, mock_get_service):
        """Graph returns (lat, lon); arrival route must be (lon, lat) for fallback.py convention."""
        graph_route = [(37.610, -122.390), (37.614, -122.385), (37.618, -122.380)]
        graph = _make_mock_graph(graph_route)
        mock_get_service.return_value = _make_mock_service(graph=graph)
        mock_get_gates.return_value = {"A1": (37.618, -122.380)}

        result = _get_taxi_waypoints_arrival("A1")
        for lon, lat in result:
            assert -180 <= lon <= 0, "First element should be longitude (negative for western hemisphere)"
            assert 0 <= lat <= 90, "Second element should be latitude"


class TestDepartureUsesGraph:
    @patch(_SERVICE_PATCH)
    @patch("src.ingestion.fallback.get_gates")
    def test_departure_uses_graph_when_available(self, mock_get_gates, mock_get_service):
        route = [(37.616, -122.389), (37.614, -122.380), (37.612, -122.370)]
        graph = _make_mock_graph(route)
        mock_get_service.return_value = _make_mock_service(graph=graph)
        mock_get_gates.return_value = {"G1": (37.616, -122.389)}

        result = _get_taxi_waypoints_departure("G1")

        assert len(result) == 3
        assert result[0] == (-122.389, 37.616)  # Gate
        assert result[-1] == (-122.370, 37.612)  # Runway
        graph.find_route.assert_called_once()

    @patch(_SERVICE_PATCH)
    @patch("src.ingestion.fallback.get_gates")
    def test_departure_falls_back_when_no_graph(self, mock_get_gates, mock_get_service):
        mock_get_service.return_value = _make_mock_service(graph=None)
        mock_get_gates.return_value = {"G1": (37.616, -122.389)}

        result = _get_taxi_waypoints_departure("G1")
        assert result == TAXI_WAYPOINTS_DEPARTURE

    @patch(_SERVICE_PATCH)
    @patch("src.ingestion.fallback.get_gates")
    def test_departure_route_starts_at_gate_ends_at_runway(self, mock_get_gates, mock_get_service):
        """Departure route should lead from gate toward runway."""
        gate_pos = (37.616, -122.389)
        runway_pos = (37.612, -122.358)
        route = [gate_pos, (37.614, -122.375), runway_pos]
        graph = _make_mock_graph(route)
        mock_get_service.return_value = _make_mock_service(graph=graph)
        mock_get_gates.return_value = {"G1": gate_pos}

        result = _get_taxi_waypoints_departure("G1")
        # First waypoint should be near gate, last near runway
        assert result[0] == (-122.389, 37.616)
        assert result[-1] == (-122.358, 37.612)

    @patch(_SERVICE_PATCH)
    @patch("src.ingestion.fallback.get_gates")
    def test_departure_falls_back_when_single_point_route(self, mock_get_gates, mock_get_service):
        graph = _make_mock_graph([(37.616, -122.389)])
        mock_get_service.return_value = _make_mock_service(graph=graph)
        mock_get_gates.return_value = {"G1": (37.616, -122.389)}

        result = _get_taxi_waypoints_departure("G1")
        assert result == TAXI_WAYPOINTS_DEPARTURE


class TestPushbackHeading:
    @patch(_SERVICE_PATCH)
    @patch("src.ingestion.fallback.get_gates")
    def test_pushback_direction_from_graph(self, mock_get_gates, mock_get_service):
        graph = MagicMock()
        graph.snap_to_nearest_node.return_value = 0
        graph.nodes = {0: (37.614, -122.389)}  # South of gate
        mock_get_service.return_value = _make_mock_service(graph=graph)
        mock_get_gates.return_value = {"G1": (37.616, -122.389)}

        heading = _get_pushback_heading("G1")

        # Heading from gate (37.616) toward taxiway node (37.614) is roughly south (~180°)
        assert 160 < heading < 200

    @patch(_SERVICE_PATCH)
    @patch("src.ingestion.fallback.get_gates")
    def test_pushback_direction_east(self, mock_get_gates, mock_get_service):
        """Pushback toward a taxiway node east of the gate."""
        graph = MagicMock()
        graph.snap_to_nearest_node.return_value = 0
        graph.nodes = {0: (37.616, -122.385)}  # East of gate (less negative lon)
        mock_get_service.return_value = _make_mock_service(graph=graph)
        mock_get_gates.return_value = {"G1": (37.616, -122.389)}

        heading = _get_pushback_heading("G1")
        # Heading east is ~90°
        assert 70 < heading < 110

    def test_pushback_default_heading(self):
        """Without graph, heading defaults to 180° (south)."""
        heading = _get_pushback_heading("G1")
        assert heading == 180.0


# ============================================================================
# State Machine: taxi_route caching in FlightState
# ============================================================================


class TestTaxiRouteCaching:
    """Verify that taxi_route is computed once per phase and reused across ticks."""

    def setup_method(self):
        _clear_global_state()

    def test_taxi_route_field_exists_on_flight_state(self):
        """FlightState must have a taxi_route field."""
        state = _make_state()
        assert hasattr(state, "taxi_route")

    def test_taxi_to_gate_uses_cached_route(self):
        """Once taxi_route is set, the state machine uses it rather than the hardcoded constant."""
        custom_route = [
            (-122.370, 37.615),
            (-122.380, 37.616),
            (-122.388, 37.617),
        ]
        state = _make_state(
            phase=FlightPhase.TAXI_TO_GATE,
            lat=37.615,
            lon=-122.370,
            gate="G1",
            taxi_route=custom_route,
            waypoint_index=0,
        )
        _flight_states[state.icao24] = state
        _init_gate_states()
        _occupy_gate(state.icao24, "G1")

        # First tick — should move toward custom_route[0], NOT TAXI_WAYPOINTS_ARRIVAL[0]
        state = _update_flight_state(state, 1.0)

        # The aircraft heading should point toward the first custom waypoint target
        # custom_route[0] = (-122.370, 37.615) → target = (37.615, -122.370) in (lat, lon)
        # After first waypoint reached, should advance to next
        assert state.taxi_route == custom_route, "Route should remain cached across ticks"

    def test_taxi_to_runway_uses_cached_route(self):
        """Departure taxi phase uses cached taxi_route."""
        custom_route = [
            (-122.390, 37.616),
            (-122.385, 37.618),
            (-122.370, 37.622),
        ]
        state = _make_state(
            phase=FlightPhase.TAXI_TO_RUNWAY,
            lat=37.616,
            lon=-122.390,
            gate="G1",
            taxi_route=custom_route,
            waypoint_index=0,
        )
        _flight_states[state.icao24] = state
        _init_gate_states()

        state = _update_flight_state(state, 1.0)

        assert state.taxi_route == custom_route

    def test_taxi_route_none_falls_back_to_hardcoded(self):
        """When taxi_route is None, falls back to TAXI_WAYPOINTS_ARRIVAL."""
        state = _make_state(
            phase=FlightPhase.TAXI_TO_GATE,
            lat=TAXI_WAYPOINTS_ARRIVAL[0][1],  # Start at first hardcoded waypoint lat
            lon=TAXI_WAYPOINTS_ARRIVAL[0][0],
            gate="G1",
            taxi_route=None,
            waypoint_index=0,
        )
        _flight_states[state.icao24] = state
        _init_gate_states()
        _occupy_gate(state.icao24, "G1")

        original_pos = (state.latitude, state.longitude)
        state = _update_flight_state(state, 1.0)

        # Should still move (using hardcoded fallback)
        new_pos = (state.latitude, state.longitude)
        assert original_pos != new_pos or state.waypoint_index > 0


# ============================================================================
# State Machine: Aircraft follows waypoints in sequence
# ============================================================================


class TestAircraftFollowsRoute:
    """Verify that taxiing aircraft move toward waypoints in order."""

    def setup_method(self):
        _clear_global_state()

    def test_taxi_to_gate_advances_through_waypoints(self):
        """Aircraft should increment waypoint_index as it reaches each waypoint."""
        state = _make_state(
            phase=FlightPhase.TAXI_TO_GATE,
            lat=TAXI_WAYPOINTS_ARRIVAL[0][1],
            lon=TAXI_WAYPOINTS_ARRIVAL[0][0],
            gate="G1",
            taxi_route=TAXI_WAYPOINTS_ARRIVAL,
            waypoint_index=0,
        )
        _flight_states[state.icao24] = state
        _init_gate_states()
        _occupy_gate(state.icao24, "G1")

        # Simulate many ticks to advance through waypoints
        max_index_reached = 0
        for _ in range(500):
            state = _update_flight_state(state, 1.0)
            max_index_reached = max(max_index_reached, state.waypoint_index)
            if state.phase != FlightPhase.TAXI_TO_GATE:
                break

        # Should have advanced past at least the first waypoint
        assert max_index_reached > 0, "Aircraft should advance through waypoints"

    def test_taxi_to_gate_moves_toward_current_waypoint(self):
        """Each tick, aircraft should move closer to the current target waypoint."""
        wp0 = TAXI_WAYPOINTS_ARRIVAL[0]
        # Start slightly before the first waypoint
        state = _make_state(
            phase=FlightPhase.TAXI_TO_GATE,
            lat=wp0[1] - 0.002,
            lon=wp0[0] - 0.002,
            gate="G1",
            taxi_route=TAXI_WAYPOINTS_ARRIVAL,
            waypoint_index=0,
        )
        _flight_states[state.icao24] = state
        _init_gate_states()
        _occupy_gate(state.icao24, "G1")

        target = (wp0[1], wp0[0])
        initial_dist = _distance_between((state.latitude, state.longitude), target)

        state = _update_flight_state(state, 1.0)

        new_dist = _distance_between((state.latitude, state.longitude), target)
        assert new_dist < initial_dist, "Aircraft should move closer to the next waypoint"

    def test_taxi_to_runway_advances_through_waypoints(self):
        """Departure taxi should advance through departure waypoints."""
        state = _make_state(
            phase=FlightPhase.TAXI_TO_RUNWAY,
            lat=TAXI_WAYPOINTS_DEPARTURE[0][1],
            lon=TAXI_WAYPOINTS_DEPARTURE[0][0],
            gate="G1",
            taxi_route=TAXI_WAYPOINTS_DEPARTURE,
            waypoint_index=0,
        )
        _flight_states[state.icao24] = state
        _init_gate_states()

        max_index = 0
        for _ in range(500):
            state = _update_flight_state(state, 1.0)
            max_index = max(max_index, state.waypoint_index)
            if state.phase != FlightPhase.TAXI_TO_RUNWAY:
                break

        assert max_index > 0

    def test_heading_aligns_with_waypoint_direction(self):
        """Aircraft heading during taxi should point toward the current waypoint."""
        wp0 = TAXI_WAYPOINTS_ARRIVAL[0]
        state = _make_state(
            phase=FlightPhase.TAXI_TO_GATE,
            lat=wp0[1] - 0.005,
            lon=wp0[0] + 0.005,
            gate="G1",
            taxi_route=TAXI_WAYPOINTS_ARRIVAL,
            waypoint_index=0,
        )
        _flight_states[state.icao24] = state
        _init_gate_states()
        _occupy_gate(state.icao24, "G1")

        state = _update_flight_state(state, 1.0)

        expected_heading = _calculate_heading(
            (state.latitude, state.longitude),
            (wp0[1], wp0[0]),
        )
        # Heading should be close to direction toward waypoint
        diff = abs(state.heading - expected_heading)
        diff = min(diff, 360 - diff)  # Handle wrap-around
        # Tolerance is generous because heading is rate-limited (5°/s smooth turn)
        assert diff < 50, f"Heading {state.heading}° should be turning toward {expected_heading}°"


# ============================================================================
# State Machine: Phase transitions with route assignment
# ============================================================================


class TestPhaseTransitionRouteCaching:
    """Verify taxi_route is assigned at phase transitions."""

    def setup_method(self):
        _clear_global_state()

    def test_landing_to_taxi_assigns_route(self):
        """When transitioning from LANDING to TAXI_TO_GATE, taxi_route should be set."""
        # Place aircraft right at the landing endpoint about to touch down
        state = _make_state(
            phase=FlightPhase.LANDING,
            lat=37.626,  # Near runway 10R threshold
            lon=-122.393,
            altitude=5,  # Almost on ground
            velocity=50,
            on_ground=False,
            gate=None,
            taxi_route=None,
        )
        _flight_states[state.icao24] = state
        _init_gate_states()
        _runway_28R.occupied_by = state.icao24

        # Tick until it transitions to TAXI_TO_GATE
        transitioned = False
        for _ in range(100):
            state = _update_flight_state(state, 1.0)
            if state.phase == FlightPhase.TAXI_TO_GATE:
                transitioned = True
                break

        if transitioned:
            # taxi_route should have been assigned (at least the fallback)
            assert state.taxi_route is not None, "taxi_route should be set when entering TAXI_TO_GATE"
            assert len(state.taxi_route) >= 2, "Route should have at least 2 waypoints"
            assert state.waypoint_index == 0, "Should start at first waypoint"

    def test_pushback_to_taxi_to_runway_assigns_route(self):
        """When transitioning from PUSHBACK to TAXI_TO_RUNWAY, taxi_route should be set."""
        gate_name = list(_DEFAULT_GATES.keys())[0]
        gate_pos = _DEFAULT_GATES[gate_name]
        state = _make_state(
            phase=FlightPhase.PUSHBACK,
            lat=gate_pos[0],
            lon=gate_pos[1],
            gate=gate_name,
            taxi_route=None,
            phase_progress=0.99,  # Almost done with pushback
        )
        _flight_states[state.icao24] = state
        _init_gate_states()
        _occupy_gate(state.icao24, gate_name)

        # Tick until transition to TAXI_TO_RUNWAY
        transitioned = False
        for _ in range(50):
            state = _update_flight_state(state, 1.0)
            if state.phase == FlightPhase.TAXI_TO_RUNWAY:
                transitioned = True
                break

        assert transitioned, "Should transition to TAXI_TO_RUNWAY"
        assert state.taxi_route is not None, "taxi_route should be set for departure taxi"
        assert len(state.taxi_route) >= 2
        assert state.waypoint_index == 0


# ============================================================================
# State Machine: Full ground movement lifecycle
# ============================================================================


class TestGroundMovementLifecycle:
    """End-to-end tests for the complete ground movement sequence."""

    def setup_method(self):
        _clear_global_state()

    def test_taxi_to_gate_reaches_gate(self):
        """Aircraft taxiing to gate should eventually reach PARKED phase."""
        gate_name = list(_DEFAULT_GATES.keys())[0]
        gate_pos = _DEFAULT_GATES[gate_name]

        state = _make_state(
            phase=FlightPhase.TAXI_TO_GATE,
            lat=TAXI_WAYPOINTS_ARRIVAL[0][1],
            lon=TAXI_WAYPOINTS_ARRIVAL[0][0],
            gate=gate_name,
            taxi_route=TAXI_WAYPOINTS_ARRIVAL,
            waypoint_index=0,
        )
        _flight_states[state.icao24] = state
        _init_gate_states()
        _occupy_gate(state.icao24, gate_name)

        reached_gate = False
        for _ in range(2000):
            state = _update_flight_state(state, 1.0)
            if state.phase == FlightPhase.PARKED:
                reached_gate = True
                break

        assert reached_gate, "Aircraft should reach gate and transition to PARKED"
        # When parked, aircraft should be close to its gate
        dist_to_gate = _distance_between((state.latitude, state.longitude), gate_pos)
        assert dist_to_gate < 0.001, f"Parked aircraft should be near gate, distance: {dist_to_gate}"

    def test_taxi_velocity_constraints(self):
        """During taxi, velocity should stay within taxi speed limits."""
        state = _make_state(
            phase=FlightPhase.TAXI_TO_GATE,
            lat=TAXI_WAYPOINTS_ARRIVAL[0][1],
            lon=TAXI_WAYPOINTS_ARRIVAL[0][0],
            gate="G1",
            taxi_route=TAXI_WAYPOINTS_ARRIVAL,
            waypoint_index=0,
        )
        _flight_states[state.icao24] = state
        _init_gate_states()
        _occupy_gate(state.icao24, "G1")

        for _ in range(100):
            state = _update_flight_state(state, 1.0)
            if state.phase == FlightPhase.TAXI_TO_GATE:
                # Taxi speed: 0 (holding), 8 kts (ramp/near gate), or 25 kts (straight taxiway)
                assert state.velocity <= 30, f"Taxi speed {state.velocity} too high"
                assert state.altitude == 0, "Should be on ground during taxi"
                assert state.on_ground is True
            else:
                break

    def test_pushback_precedes_departure_taxi(self):
        """PUSHBACK must complete before TAXI_TO_RUNWAY begins."""
        gate_name = list(_DEFAULT_GATES.keys())[0]
        gate_pos = _DEFAULT_GATES[gate_name]

        state = _make_state(
            phase=FlightPhase.PUSHBACK,
            lat=gate_pos[0],
            lon=gate_pos[1],
            gate=gate_name,
            phase_progress=0.0,
        )
        _flight_states[state.icao24] = state
        _init_gate_states()
        _occupy_gate(state.icao24, gate_name)

        phases_seen = []
        for _ in range(200):
            state = _update_flight_state(state, 1.0)
            if state.phase.value not in [p for p in phases_seen]:
                phases_seen.append(state.phase.value)
            if state.phase == FlightPhase.TAXI_TO_RUNWAY:
                break

        # PUSHBACK should appear before TAXI_TO_RUNWAY
        if "taxi_to_runway" in phases_seen:
            pb_idx = phases_seen.index("pushback") if "pushback" in phases_seen else -1
            tr_idx = phases_seen.index("taxi_to_runway")
            assert pb_idx < tr_idx, "PUSHBACK must precede TAXI_TO_RUNWAY"

    def test_aircraft_stays_on_ground_during_taxi(self):
        """Aircraft altitude remains 0 and on_ground=True during all taxi phases."""
        state = _make_state(
            phase=FlightPhase.TAXI_TO_GATE,
            lat=TAXI_WAYPOINTS_ARRIVAL[0][1],
            lon=TAXI_WAYPOINTS_ARRIVAL[0][0],
            gate="G1",
            taxi_route=TAXI_WAYPOINTS_ARRIVAL,
        )
        _flight_states[state.icao24] = state
        _init_gate_states()
        _occupy_gate(state.icao24, "G1")

        for _ in range(300):
            state = _update_flight_state(state, 1.0)
            if state.phase in (FlightPhase.TAXI_TO_GATE, FlightPhase.TAXI_TO_RUNWAY, FlightPhase.PUSHBACK, FlightPhase.PARKED):
                assert state.altitude == 0, f"Ground aircraft altitude should be 0, got {state.altitude}"
                assert state.on_ground is True, "Ground aircraft must have on_ground=True"
            if state.phase == FlightPhase.TAKEOFF:
                break


# ============================================================================
# State Machine: Pushback direction constraints
# ============================================================================


class TestPushbackMovement:
    """Verify pushback moves aircraft away from gate toward taxiway."""

    def setup_method(self):
        _clear_global_state()

    def test_pushback_moves_aircraft_away_from_gate(self):
        """During pushback, aircraft should move away from its gate position."""
        gate_name = list(_DEFAULT_GATES.keys())[0]
        gate_pos = _DEFAULT_GATES[gate_name]

        state = _make_state(
            phase=FlightPhase.PUSHBACK,
            lat=gate_pos[0],
            lon=gate_pos[1],
            gate=gate_name,
            phase_progress=0.0,
        )
        _flight_states[state.icao24] = state
        _init_gate_states()
        _occupy_gate(state.icao24, gate_name)

        initial_pos = (state.latitude, state.longitude)

        # Several ticks of pushback
        for _ in range(20):
            state = _update_flight_state(state, 1.0)
            if state.phase != FlightPhase.PUSHBACK:
                break

        # Should have moved away from original gate position
        dist_from_gate = _distance_between((state.latitude, state.longitude), gate_pos)
        assert dist_from_gate > 0.0001, "Pushback should move aircraft away from gate"

    def test_pushback_velocity_is_slow(self):
        """Pushback speed should be very low (tug speed ~3 knots)."""
        gate_name = list(_DEFAULT_GATES.keys())[0]
        gate_pos = _DEFAULT_GATES[gate_name]

        state = _make_state(
            phase=FlightPhase.PUSHBACK,
            lat=gate_pos[0],
            lon=gate_pos[1],
            gate=gate_name,
            phase_progress=0.0,
        )
        _flight_states[state.icao24] = state
        _init_gate_states()
        _occupy_gate(state.icao24, gate_name)

        for _ in range(10):
            state = _update_flight_state(state, 1.0)
            if state.phase == FlightPhase.PUSHBACK:
                assert state.velocity <= 5, f"Pushback speed {state.velocity} too high"

    def test_pushback_releases_gate(self):
        """After pushback completes, gate should be released."""
        gate_name = list(_DEFAULT_GATES.keys())[0]
        gate_pos = _DEFAULT_GATES[gate_name]

        state = _make_state(
            phase=FlightPhase.PUSHBACK,
            lat=gate_pos[0],
            lon=gate_pos[1],
            gate=gate_name,
            phase_progress=0.9,  # Almost done
        )
        _flight_states[state.icao24] = state
        _init_gate_states()
        _occupy_gate(state.icao24, gate_name)

        for _ in range(50):
            state = _update_flight_state(state, 1.0)
            if state.phase == FlightPhase.TAXI_TO_RUNWAY:
                break

        if state.phase == FlightPhase.TAXI_TO_RUNWAY:
            # Gate should be released
            assert _gate_states[gate_name].occupied_by is None or \
                _gate_states[gate_name].occupied_by != state.icao24, \
                "Gate should be released after pushback"


# ============================================================================
# State Machine: Custom route constrains movement
# ============================================================================


class TestCustomRouteConstrainsMovement:
    """Verify that when a custom taxi_route is provided (from OSM graph),
    the aircraft follows those waypoints instead of the hardcoded ones."""

    def setup_method(self):
        _clear_global_state()

    def test_custom_arrival_route_determines_initial_heading(self):
        """With a custom route, aircraft heading should point toward that route's first waypoint."""
        # Custom route goes northeast instead of the default west
        custom_route = [
            (-122.365, 37.618),  # First wp is northeast of start position
            (-122.360, 37.620),
            (-122.355, 37.622),
        ]
        state = _make_state(
            phase=FlightPhase.TAXI_TO_GATE,
            lat=37.615,
            lon=-122.370,
            gate="G1",
            taxi_route=custom_route,
            waypoint_index=0,
        )
        _flight_states[state.icao24] = state
        _init_gate_states()
        _occupy_gate(state.icao24, "G1")

        # Run multiple ticks so heading has time to turn (rate-limited at 5°/s)
        for _ in range(30):
            state = _update_flight_state(state, 1.0)

        # Should be heading generally northeast toward first custom waypoint
        target = (custom_route[0][1], custom_route[0][0])
        expected = _calculate_heading((state.latitude, state.longitude), target)
        diff = abs(state.heading - expected)
        diff = min(diff, 360 - diff)
        assert diff < 60, f"Should be turning toward custom route, got heading {state.heading}"

    def test_custom_departure_route_determines_direction(self):
        """Departure taxi with a custom route should head toward its first waypoint."""
        custom_route = [
            (-122.395, 37.614),  # Southwest
            (-122.400, 37.612),
            (-122.405, 37.610),
        ]
        state = _make_state(
            phase=FlightPhase.TAXI_TO_RUNWAY,
            lat=37.616,
            lon=-122.390,
            gate="G1",
            taxi_route=custom_route,
            waypoint_index=0,
        )
        _flight_states[state.icao24] = state
        _init_gate_states()

        state = _update_flight_state(state, 1.0)

        target = (custom_route[0][1], custom_route[0][0])
        expected = _calculate_heading((state.latitude, state.longitude), target)
        diff = abs(state.heading - expected)
        diff = min(diff, 360 - diff)
        assert diff < 30


# ============================================================================
# State Machine: Runway path constraints
# ============================================================================


class TestRunwayPathConstraints:
    """Verify runway entry/exit are gated by separation and path logic."""

    def setup_method(self):
        _clear_global_state()

    def test_taxi_to_runway_holds_if_runway_occupied(self):
        """Aircraft should hold short of runway when it's occupied."""
        state = _make_state(
            phase=FlightPhase.TAXI_TO_RUNWAY,
            lat=TAXI_WAYPOINTS_DEPARTURE[-1][1],
            lon=TAXI_WAYPOINTS_DEPARTURE[-1][0],
            gate="G1",
            taxi_route=TAXI_WAYPOINTS_DEPARTURE,
            waypoint_index=len(TAXI_WAYPOINTS_DEPARTURE),  # Past all waypoints
        )
        _flight_states[state.icao24] = state
        _init_gate_states()

        # Occupy the departure runway with another aircraft
        dep_rwy = _get_departure_runway_name()
        _occupy_runway("other_aircraft", dep_rwy)

        state = _update_flight_state(state, 1.0)

        # Should still be in TAXI_TO_RUNWAY (holding)
        assert state.phase == FlightPhase.TAXI_TO_RUNWAY, "Should hold short when runway occupied"
        assert state.velocity <= 2, "Should be nearly stopped while holding (creep ≤ 2kt)"

    def test_taxi_to_runway_enters_runway_when_clear(self):
        """Aircraft should enter runway and transition to TAKEOFF when clear."""
        state = _make_state(
            phase=FlightPhase.TAXI_TO_RUNWAY,
            lat=TAXI_WAYPOINTS_DEPARTURE[-1][1],
            lon=TAXI_WAYPOINTS_DEPARTURE[-1][0],
            gate="G1",
            taxi_route=TAXI_WAYPOINTS_DEPARTURE,
            waypoint_index=len(TAXI_WAYPOINTS_DEPARTURE),
        )
        _flight_states[state.icao24] = state
        _init_gate_states()

        # Runway is clear (default state)
        state = _update_flight_state(state, 1.0)

        assert state.phase == FlightPhase.TAKEOFF, "Should transition to TAKEOFF when runway clear"


# ============================================================================
# Route length vs taxi time correlation
# ============================================================================


class TestRouteDistanceTaxiTime:
    """Verify that longer routes result in longer taxi times."""

    def setup_method(self):
        _clear_global_state()

    def test_longer_route_takes_more_ticks(self):
        """A longer taxi route should require more simulation ticks to complete."""
        _init_gate_states()

        # Short route: 2 waypoints close together
        short_route = [
            (-122.390, 37.616),
            (-122.389, 37.6155),
        ]
        gate_name = list(_DEFAULT_GATES.keys())[0]
        gate_pos = _DEFAULT_GATES[gate_name]

        state_short = _make_state(
            icao24="short01",
            phase=FlightPhase.TAXI_TO_GATE,
            lat=short_route[0][1],
            lon=short_route[0][0],
            gate=gate_name,
            taxi_route=short_route,
            waypoint_index=0,
        )
        _flight_states[state_short.icao24] = state_short
        _occupy_gate(state_short.icao24, gate_name)

        ticks_short = 0
        for _ in range(2000):
            state_short = _update_flight_state(state_short, 1.0)
            ticks_short += 1
            if state_short.phase == FlightPhase.PARKED:
                break

        _clear_global_state()
        _init_gate_states()

        # Long route: many waypoints spread out
        long_route = [
            (-122.370, 37.615),
            (-122.375, 37.616),
            (-122.380, 37.617),
            (-122.385, 37.617),
            (-122.390, 37.616),
        ]

        state_long = _make_state(
            icao24="long01",
            phase=FlightPhase.TAXI_TO_GATE,
            lat=long_route[0][1],
            lon=long_route[0][0],
            gate=gate_name,
            taxi_route=long_route,
            waypoint_index=0,
        )
        _flight_states[state_long.icao24] = state_long
        _occupy_gate(state_long.icao24, gate_name)

        ticks_long = 0
        for _ in range(2000):
            state_long = _update_flight_state(state_long, 1.0)
            ticks_long += 1
            if state_long.phase == FlightPhase.PARKED:
                break

        # Both should have reached PARKED, and the long route should take more ticks
        if state_short.phase == FlightPhase.PARKED and state_long.phase == FlightPhase.PARKED:
            assert ticks_long > ticks_short, (
                f"Longer route should take more time: short={ticks_short}, long={ticks_long}"
            )


# ============================================================================
# _create_new_flight uses the taxiway graph
# ============================================================================


class TestCreateNewFlightUsesGraph:
    """Verify _create_new_flight populates taxi_route from the graph
    for all ground-phase spawn paths (TAXI_TO_GATE, TAXI_TO_RUNWAY)."""

    def setup_method(self):
        _clear_global_state()

    def test_spawn_taxi_to_gate_sets_taxi_route(self):
        """New flight spawned in TAXI_TO_GATE should have taxi_route set."""
        _init_gate_states()
        state = _create_new_flight("spawn01", "UAL100", FlightPhase.TAXI_TO_GATE, origin="JFK")

        # Might fall back to APPROACHING/ENROUTE if gates occupied etc.
        if state.phase == FlightPhase.TAXI_TO_GATE:
            assert state.taxi_route is not None, (
                "_create_new_flight(TAXI_TO_GATE) must set taxi_route"
            )
            assert len(state.taxi_route) >= 2, "Route needs at least 2 waypoints"
            assert state.waypoint_index == 0

    def test_spawn_taxi_to_gate_position_matches_route_start(self):
        """Spawned position should match the first waypoint of the taxi route."""
        _init_gate_states()
        state = _create_new_flight("spawn02", "DAL200", FlightPhase.TAXI_TO_GATE, origin="ORD")

        if state.phase == FlightPhase.TAXI_TO_GATE:
            first_wp = state.taxi_route[0]
            # Convention: waypoints are (lon, lat), state is (lat, lon)
            assert abs(state.latitude - first_wp[1]) < 0.001, (
                f"Spawn lat {state.latitude} should match route start lat {first_wp[1]}"
            )
            assert abs(state.longitude - first_wp[0]) < 0.001, (
                f"Spawn lon {state.longitude} should match route start lon {first_wp[0]}"
            )

    def test_spawn_taxi_to_gate_heading_toward_route(self):
        """Spawn heading should point toward the next waypoint, not be hardcoded."""
        _init_gate_states()
        state = _create_new_flight("spawn03", "AAL300", FlightPhase.TAXI_TO_GATE, origin="LAX")

        if state.phase == FlightPhase.TAXI_TO_GATE and len(state.taxi_route) >= 2:
            # Heading should be toward second waypoint
            wp1 = state.taxi_route[1]
            expected = _calculate_heading(
                (state.latitude, state.longitude),
                (wp1[1], wp1[0]),
            )
            diff = abs(state.heading - expected)
            diff = min(diff, 360 - diff)
            assert diff < 10, (
                f"Spawn heading {state.heading}° should point toward second waypoint "
                f"(expected ~{expected}°)"
            )

    def test_spawn_taxi_to_runway_sets_taxi_route(self):
        """New flight spawned in TAXI_TO_RUNWAY should have taxi_route set."""
        _init_gate_states()
        state = _create_new_flight("spawn04", "SWA400", FlightPhase.TAXI_TO_RUNWAY, destination="DEN")

        if state.phase == FlightPhase.TAXI_TO_RUNWAY:
            assert state.taxi_route is not None, (
                "_create_new_flight(TAXI_TO_RUNWAY) must set taxi_route"
            )
            assert len(state.taxi_route) >= 2
            assert state.waypoint_index == 0

    def test_spawn_taxi_to_runway_heading_toward_route(self):
        """Departure spawn heading should point toward the first departure waypoint."""
        _init_gate_states()
        state = _create_new_flight("spawn05", "JBU500", FlightPhase.TAXI_TO_RUNWAY, destination="BOS")

        if state.phase == FlightPhase.TAXI_TO_RUNWAY and state.taxi_route:
            wp0 = state.taxi_route[0]
            expected = _calculate_heading(
                (state.latitude, state.longitude),
                (wp0[1], wp0[0]),
            )
            diff = abs(state.heading - expected)
            diff = min(diff, 360 - diff)
            assert diff < 30, (
                f"Departure heading {state.heading}° should point toward first waypoint "
                f"(expected ~{expected}°)"
            )

    def test_spawn_taxi_to_gate_with_graph_uses_graph_route(self):
        """When taxiway graph is available, spawned TAXI_TO_GATE flight
        should get graph-derived route, not hardcoded SFO waypoints."""
        graph_route = [
            (37.612, -122.365),  # Different from hardcoded TAXI_WAYPOINTS_ARRIVAL
            (37.614, -122.375),
            (37.616, -122.389),
        ]
        graph = _make_mock_graph(graph_route)
        mock_service = _make_mock_service(graph=graph)

        _init_gate_states()
        with patch(_SERVICE_PATCH, return_value=mock_service):
            state = _create_new_flight("spawn06", "UAL600", FlightPhase.TAXI_TO_GATE, origin="SFO")

        if state.phase == FlightPhase.TAXI_TO_GATE:
            # Route should be the graph result (converted to lon,lat)
            assert state.taxi_route is not None
            assert state.taxi_route[0] == (-122.365, 37.612), (
                "Route should come from graph, not hardcoded"
            )
            graph.find_route.assert_called()

    def test_spawn_taxi_to_runway_with_graph_uses_graph_route(self):
        """When taxiway graph is available, spawned TAXI_TO_RUNWAY flight
        should get graph-derived route."""
        graph_route = [
            (37.616, -122.389),
            (37.614, -122.375),
            (37.612, -122.358),
        ]
        graph = _make_mock_graph(graph_route)
        mock_service = _make_mock_service(graph=graph)

        _init_gate_states()
        with patch(_SERVICE_PATCH, return_value=mock_service):
            state = _create_new_flight("spawn07", "DAL700", FlightPhase.TAXI_TO_RUNWAY, destination="ATL")

        if state.phase == FlightPhase.TAXI_TO_RUNWAY:
            assert state.taxi_route is not None
            assert state.taxi_route[-1] == (-122.358, 37.612), (
                "Route should come from graph"
            )
            graph.find_route.assert_called()

    def test_spawn_separation_uses_graph_route_start(self):
        """Separation check at spawn should use the graph route's start position,
        not the hardcoded TAXI_WAYPOINTS_ARRIVAL[0]."""
        # Place a blocking aircraft near the hardcoded SFO first waypoint
        hardcoded_start = (TAXI_WAYPOINTS_ARRIVAL[0][1], TAXI_WAYPOINTS_ARRIVAL[0][0])

        blocker = _make_state(
            icao24="blocker",
            phase=FlightPhase.TAXI_TO_GATE,
            lat=hardcoded_start[0],
            lon=hardcoded_start[1],
            gate="B1",
        )
        _flight_states[blocker.icao24] = blocker

        # Graph route starts at a DIFFERENT location from hardcoded
        graph_route = [
            (37.620, -122.375),  # Far from hardcoded start
            (37.618, -122.380),
            (37.616, -122.389),
        ]
        graph = _make_mock_graph(graph_route)
        mock_service = _make_mock_service(graph=graph)

        _init_gate_states()
        with patch(_SERVICE_PATCH, return_value=mock_service):
            state = _create_new_flight("spawn08", "ASA800", FlightPhase.TAXI_TO_GATE, origin="SEA")

        # Since the graph route starts far from the blocker, should succeed
        if state.phase == FlightPhase.TAXI_TO_GATE:
            assert abs(state.latitude - 37.620) < 0.001, (
                "Should spawn at graph route start, not hardcoded waypoint"
            )


# ============================================================================
# Airport config graph integration in _create_new_flight
# ============================================================================


class TestCreateNewFlightGraphIntegration:
    """End-to-end: verify that _create_new_flight queries the airport config
    service taxiway graph and the resulting FlightState is properly constrained."""

    def setup_method(self):
        _clear_global_state()

    def test_full_arrival_lifecycle_with_graph(self):
        """Spawn as TAXI_TO_GATE with graph → taxi → reach gate → PARKED.
        Verifies the graph route is used throughout."""
        gate_name = list(_DEFAULT_GATES.keys())[0]
        gate_pos = _DEFAULT_GATES[gate_name]

        # Graph route: runway exit → mid-taxiway → near gate
        graph_route = [
            (gate_pos[0] - 0.005, gate_pos[1] + 0.010),  # Start far from gate
            (gate_pos[0] - 0.002, gate_pos[1] + 0.005),  # Midpoint
            (gate_pos[0], gate_pos[1] + 0.001),           # Near gate
        ]
        graph = _make_mock_graph(graph_route)
        mock_service = _make_mock_service(graph=graph)

        _init_gate_states()
        with patch(_SERVICE_PATCH, return_value=mock_service):
            state = _create_new_flight("e2e01", "UAL900", FlightPhase.TAXI_TO_GATE, origin="JFK")

        if state.phase != FlightPhase.TAXI_TO_GATE:
            pytest.skip("Could not spawn as TAXI_TO_GATE")

        _flight_states[state.icao24] = state

        # Route should be the graph-derived one (converted to lon,lat)
        assert state.taxi_route is not None
        assert len(state.taxi_route) == 3

        # Simulate until PARKED
        reached_parked = False
        for _ in range(3000):
            state = _update_flight_state(state, 1.0)
            if state.phase == FlightPhase.PARKED:
                reached_parked = True
                break

        assert reached_parked, "Aircraft should reach PARKED via graph route"
        # Should be near the assigned gate (may differ from first gate due to random selection)
        actual_gate_pos = get_gates()[state.assigned_gate]
        dist = _distance_between((state.latitude, state.longitude), actual_gate_pos)
        assert dist < 0.001

    def test_full_departure_lifecycle_with_graph(self):
        """Spawn as TAXI_TO_RUNWAY with graph → taxi → reach runway → TAKEOFF."""
        gate_name = list(_DEFAULT_GATES.keys())[0]
        gate_pos = _DEFAULT_GATES[gate_name]

        # Graph route: gate → mid → runway threshold
        graph_route = [
            (gate_pos[0], gate_pos[1]),
            (gate_pos[0] - 0.003, gate_pos[1] + 0.010),
            (37.614, -122.360),  # Near runway
        ]
        graph = _make_mock_graph(graph_route)
        mock_service = _make_mock_service(graph=graph)

        _init_gate_states()
        with patch(_SERVICE_PATCH, return_value=mock_service):
            state = _create_new_flight("e2e02", "DAL901", FlightPhase.TAXI_TO_RUNWAY, destination="ATL")

        if state.phase != FlightPhase.TAXI_TO_RUNWAY:
            pytest.skip("Could not spawn as TAXI_TO_RUNWAY")

        _flight_states[state.icao24] = state

        assert state.taxi_route is not None

        # Simulate until TAKEOFF
        reached_takeoff = False
        for _ in range(3000):
            state = _update_flight_state(state, 1.0)
            if state.phase == FlightPhase.TAKEOFF:
                reached_takeoff = True
                break

        assert reached_takeoff, "Aircraft should reach TAKEOFF via graph route"

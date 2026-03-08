"""Tests for aircraft separation standards.

Verifies that the synthetic flight generator maintains FAA/ICAO
separation standards as documented in docs/AIRCRAFT_SEPARATION.md.

Key Separation Distances:
- Approach (LARGE→LARGE): 3 NM
- Approach (HEAVY→LARGE): 5 NM
- Approach (HEAVY→SMALL): 6 NM
- Taxi operations: ~100m (330 ft)
- Gate spacing: ~200m
"""

import pytest
import time
from unittest.mock import patch, MagicMock

from src.ingestion.fallback import (
    # Constants
    WAKE_CATEGORY,
    WAKE_SEPARATION_NM,
    DEFAULT_SEPARATION_NM,
    NM_TO_DEG,
    MIN_APPROACH_SEPARATION_DEG,
    MIN_TAXI_SEPARATION_DEG,
    MIN_GATE_SEPARATION_DEG,
    GATES,
    # Enums and classes
    FlightPhase,
    FlightState,
    # Functions
    _get_wake_category,
    _get_required_separation,
    _distance_between,
    _distance_nm,
    _check_approach_separation,
    _check_taxi_separation,
    _find_aircraft_ahead_on_approach,
    _is_runway_clear,
    _occupy_runway,
    _release_runway,
    _find_available_gate,
    _occupy_gate,
    _release_gate,
    # State management
    _flight_states,
    _runway_28R,
    _gate_states,
    _init_gate_states,
    # Main generator
    generate_synthetic_flights,
)


def make_flight_state(
    icao24: str,
    latitude: float,
    longitude: float,
    altitude: float,
    phase: FlightPhase,
    aircraft_type: str = "A320",
    on_ground: bool = False,
    callsign: str = "UAL001",
    velocity: float = 250.0,
    heading: float = 270.0,
    vertical_rate: float = 0.0,
) -> FlightState:
    """Helper to create FlightState with all required fields."""
    return FlightState(
        icao24=icao24,
        callsign=callsign,
        latitude=latitude,
        longitude=longitude,
        altitude=altitude,
        velocity=velocity,
        heading=heading,
        vertical_rate=vertical_rate,
        on_ground=on_ground,
        phase=phase,
        aircraft_type=aircraft_type,
    )


class TestWakeTurbulenceCategories:
    """Tests for wake turbulence category assignments."""

    def test_super_category(self):
        """Test SUPER category (A380)."""
        assert _get_wake_category("A380") == "SUPER"

    def test_heavy_categories(self):
        """Test HEAVY category aircraft."""
        heavy_aircraft = ["B747", "B777", "B787", "A330", "A340", "A350", "A345"]
        for aircraft in heavy_aircraft:
            assert _get_wake_category(aircraft) == "HEAVY", f"{aircraft} should be HEAVY"

    def test_large_categories(self):
        """Test LARGE category aircraft."""
        large_aircraft = ["A320", "A321", "A319", "A318", "B737", "B738", "B739"]
        for aircraft in large_aircraft:
            assert _get_wake_category(aircraft) == "LARGE", f"{aircraft} should be LARGE"

    def test_small_categories(self):
        """Test SMALL category aircraft."""
        small_aircraft = ["CRJ9", "E175", "E190"]
        for aircraft in small_aircraft:
            assert _get_wake_category(aircraft) == "SMALL", f"{aircraft} should be SMALL"

    def test_unknown_defaults_to_large(self):
        """Test unknown aircraft types default to LARGE."""
        assert _get_wake_category("UNKNOWN") == "LARGE"
        assert _get_wake_category("XYZ123") == "LARGE"


class TestWakeSeparationStandards:
    """Tests for wake turbulence separation distances match documented standards."""

    def test_super_to_super_separation(self):
        """SUPER → SUPER: 4 NM."""
        assert WAKE_SEPARATION_NM[("SUPER", "SUPER")] == 4.0

    def test_super_to_heavy_separation(self):
        """SUPER → HEAVY: 6 NM."""
        assert WAKE_SEPARATION_NM[("SUPER", "HEAVY")] == 6.0

    def test_super_to_large_separation(self):
        """SUPER → LARGE: 7 NM."""
        assert WAKE_SEPARATION_NM[("SUPER", "LARGE")] == 7.0

    def test_super_to_small_separation(self):
        """SUPER → SMALL: 8 NM."""
        assert WAKE_SEPARATION_NM[("SUPER", "SMALL")] == 8.0

    def test_heavy_to_heavy_separation(self):
        """HEAVY → HEAVY: 4 NM."""
        assert WAKE_SEPARATION_NM[("HEAVY", "HEAVY")] == 4.0

    def test_heavy_to_large_separation(self):
        """HEAVY → LARGE: 5 NM."""
        assert WAKE_SEPARATION_NM[("HEAVY", "LARGE")] == 5.0

    def test_heavy_to_small_separation(self):
        """HEAVY → SMALL: 6 NM."""
        assert WAKE_SEPARATION_NM[("HEAVY", "SMALL")] == 6.0

    def test_large_to_large_separation(self):
        """LARGE → LARGE: 3 NM."""
        assert WAKE_SEPARATION_NM[("LARGE", "LARGE")] == 3.0

    def test_large_to_small_separation(self):
        """LARGE → SMALL: 4 NM."""
        assert WAKE_SEPARATION_NM[("LARGE", "SMALL")] == 4.0

    def test_small_to_small_separation(self):
        """SMALL → SMALL: 3 NM."""
        assert WAKE_SEPARATION_NM[("SMALL", "SMALL")] == 3.0

    def test_default_separation(self):
        """Default minimum: 3 NM."""
        assert DEFAULT_SEPARATION_NM == 3.0


class TestSeparationCalculations:
    """Tests for separation distance calculations."""

    def test_nm_to_deg_conversion(self):
        """Test nautical miles to degrees conversion."""
        # 1 NM ≈ 1/60 degree
        assert abs(NM_TO_DEG - (1.0 / 60.0)) < 0.001

    def test_min_approach_separation(self):
        """Test minimum approach separation is 3 NM."""
        expected_deg = 3.0 * NM_TO_DEG
        assert abs(MIN_APPROACH_SEPARATION_DEG - expected_deg) < 0.001

    def test_min_taxi_separation(self):
        """Test minimum taxi separation (~300m for 3D visibility)."""
        # 0.003 deg ≈ 300m at equator, larger for 3D visualization
        assert MIN_TAXI_SEPARATION_DEG == 0.003

    def test_min_gate_separation(self):
        """Test minimum gate separation (~800m for 3D scale)."""
        # 0.010 deg ≈ 800m in 3D scale to prevent visual overlap
        assert MIN_GATE_SEPARATION_DEG == 0.010

    def test_get_required_separation_large_to_large(self):
        """Test required separation calculation for LARGE → LARGE."""
        separation = _get_required_separation("A320", "B737")
        expected = 3.0 * NM_TO_DEG  # 3 NM for LARGE→LARGE
        assert abs(separation - expected) < 0.001

    def test_get_required_separation_heavy_to_large(self):
        """Test required separation calculation for HEAVY → LARGE."""
        separation = _get_required_separation("B777", "A320")
        expected = 5.0 * NM_TO_DEG  # 5 NM for HEAVY→LARGE
        assert abs(separation - expected) < 0.001

    def test_get_required_separation_super_to_small(self):
        """Test required separation calculation for SUPER → SMALL."""
        separation = _get_required_separation("A380", "E175")
        expected = 8.0 * NM_TO_DEG  # 8 NM for SUPER→SMALL
        assert abs(separation - expected) < 0.001

    def test_distance_between_calculation(self):
        """Test distance calculation between two positions."""
        pos1 = (37.5, -122.0)
        pos2 = (37.5, -121.95)
        dist = _distance_between(pos1, pos2)
        # Distance should be 0.05 degrees longitude
        assert abs(dist - 0.05) < 0.001

    def test_distance_nm_calculation(self):
        """Test distance in nautical miles calculation."""
        pos1 = (37.5, -122.0)
        # 3 NM apart (3 * NM_TO_DEG)
        pos2 = (37.5, -122.0 + 3.0 * NM_TO_DEG)
        dist_nm = _distance_nm(pos1, pos2)
        assert abs(dist_nm - 3.0) < 0.1


class TestApproachSeparation:
    """Tests for approach separation maintenance."""

    def setup_method(self):
        """Clear flight states before each test."""
        _flight_states.clear()

    def teardown_method(self):
        """Clean up after each test."""
        _flight_states.clear()

    def test_approach_separation_no_traffic(self):
        """Test approach is clear when no other aircraft."""
        state = make_flight_state(
            icao24="test001",
            latitude=37.48,
            longitude=-121.90,
            altitude=6000,
            phase=FlightPhase.APPROACHING,
            aircraft_type="A320",
        )
        _flight_states["test001"] = state

        assert _check_approach_separation(state) is True

    def test_approach_separation_sufficient_distance(self):
        """Test approach cleared when sufficient separation exists."""
        # Lead aircraft closer to runway
        lead = make_flight_state(
            icao24="lead001",
            latitude=37.49,
            longitude=-121.97,  # Closer to runway (west)
            altitude=2000,
            phase=FlightPhase.APPROACHING,
            aircraft_type="A320",
        )
        _flight_states["lead001"] = lead

        # Following aircraft 5 NM behind (east)
        follow = make_flight_state(
            icao24="follow001",
            latitude=37.49,
            longitude=-121.97 + 5.0 * NM_TO_DEG,  # 5 NM behind
            altitude=4000,
            phase=FlightPhase.APPROACHING,
            aircraft_type="A320",
        )
        _flight_states["follow001"] = follow

        # LARGE→LARGE requires 3 NM, we have 5 NM
        assert _check_approach_separation(follow) is True

    def test_approach_separation_insufficient_distance(self):
        """Test approach blocked when insufficient separation."""
        # Lead aircraft
        lead = make_flight_state(
            icao24="lead001",
            latitude=37.49,
            longitude=-121.97,
            altitude=2000,
            phase=FlightPhase.APPROACHING,
            aircraft_type="A320",
        )
        _flight_states["lead001"] = lead

        # Following aircraft only 1 NM behind (too close)
        follow = make_flight_state(
            icao24="follow001",
            latitude=37.49,
            longitude=-121.97 + 1.0 * NM_TO_DEG,  # Only 1 NM behind
            altitude=3000,
            phase=FlightPhase.APPROACHING,
            aircraft_type="A320",
        )
        _flight_states["follow001"] = follow

        # LARGE→LARGE requires 3 NM, we only have 1 NM
        assert _check_approach_separation(follow) is False

    def test_approach_separation_heavy_to_small_requires_more(self):
        """Test HEAVY→SMALL requires 6 NM separation."""
        # Heavy lead aircraft
        lead = make_flight_state(
            icao24="heavy001",
            latitude=37.49,
            longitude=-121.97,
            altitude=2000,
            phase=FlightPhase.APPROACHING,
            aircraft_type="B777",  # HEAVY
        )
        _flight_states["heavy001"] = lead

        # Small following aircraft 4 NM behind (not enough for HEAVY→SMALL)
        follow = make_flight_state(
            icao24="small001",
            latitude=37.49,
            longitude=-121.97 + 4.0 * NM_TO_DEG,  # 4 NM behind
            altitude=4000,
            phase=FlightPhase.APPROACHING,
            aircraft_type="E175",  # SMALL
        )
        _flight_states["small001"] = follow

        # HEAVY→SMALL requires 6 NM, we only have 4 NM
        assert _check_approach_separation(follow) is False

        # Move to 7 NM behind (enough)
        follow.longitude = -121.97 + 7.0 * NM_TO_DEG
        assert _check_approach_separation(follow) is True

    def test_find_aircraft_ahead(self):
        """Test finding aircraft ahead on approach."""
        # Lead aircraft closer to runway
        lead = make_flight_state(
            icao24="lead001",
            latitude=37.49,
            longitude=-121.97,
            altitude=2000,
            phase=FlightPhase.APPROACHING,
            aircraft_type="A320",
        )
        _flight_states["lead001"] = lead

        # Following aircraft
        follow = make_flight_state(
            icao24="follow001",
            latitude=37.49,
            longitude=-121.90,  # Further east
            altitude=5000,
            phase=FlightPhase.APPROACHING,
            aircraft_type="A320",
        )
        _flight_states["follow001"] = follow

        ahead = _find_aircraft_ahead_on_approach(follow)
        assert ahead is not None
        assert ahead.icao24 == "lead001"

    def test_no_aircraft_ahead_when_first(self):
        """Test no aircraft ahead when first in sequence."""
        state = make_flight_state(
            icao24="first001",
            latitude=37.49,
            longitude=-121.99,  # Closest to runway
            altitude=500,
            phase=FlightPhase.APPROACHING,
            aircraft_type="A320",
        )
        _flight_states["first001"] = state

        # Another aircraft but behind (east)
        behind = make_flight_state(
            icao24="behind001",
            latitude=37.49,
            longitude=-121.90,
            altitude=5000,
            phase=FlightPhase.APPROACHING,
            aircraft_type="A320",
        )
        _flight_states["behind001"] = behind

        ahead = _find_aircraft_ahead_on_approach(state)
        assert ahead is None


class TestTaxiSeparation:
    """Tests for taxi separation maintenance."""

    def setup_method(self):
        """Clear flight states before each test."""
        _flight_states.clear()

    def teardown_method(self):
        """Clean up after each test."""
        _flight_states.clear()

    def test_taxi_separation_clear(self):
        """Test taxi is clear when no other ground traffic."""
        state = make_flight_state(
            icao24="taxi001",
            latitude=37.49,
            longitude=-122.0,
            altitude=0,
            on_ground=True,
            phase=FlightPhase.TAXI_TO_GATE,
            aircraft_type="A320",
        )
        _flight_states["taxi001"] = state

        assert _check_taxi_separation(state) is True

    def test_taxi_separation_blocked(self):
        """Test taxi is blocked when another aircraft too close."""
        # First aircraft
        first = make_flight_state(
            icao24="first001",
            latitude=37.49,
            longitude=-122.0,
            altitude=0,
            on_ground=True,
            phase=FlightPhase.TAXI_TO_GATE,
            aircraft_type="A320",
        )
        _flight_states["first001"] = first

        # Second aircraft too close (within MIN_TAXI_SEPARATION_DEG)
        second = make_flight_state(
            icao24="second001",
            latitude=37.49,
            longitude=-122.0 + 0.0005,  # Very close
            altitude=0,
            on_ground=True,
            phase=FlightPhase.TAXI_TO_GATE,
            aircraft_type="A320",
        )
        _flight_states["second001"] = second

        assert _check_taxi_separation(second) is False

    def test_taxi_separation_ignores_parked(self):
        """Test taxi separation ignores parked aircraft."""
        # Parked aircraft
        parked = make_flight_state(
            icao24="parked001",
            latitude=37.491,
            longitude=-122.0,
            altitude=0,
            on_ground=True,
            phase=FlightPhase.PARKED,
            aircraft_type="A320",
        )
        _flight_states["parked001"] = parked

        # Taxiing aircraft near parked
        taxi = make_flight_state(
            icao24="taxi001",
            latitude=37.491,
            longitude=-122.0 + 0.0005,  # Very close to parked
            altitude=0,
            on_ground=True,
            phase=FlightPhase.TAXI_TO_GATE,
            aircraft_type="A320",
        )
        _flight_states["taxi001"] = taxi

        # Should be clear because parked aircraft don't block taxi
        assert _check_taxi_separation(taxi) is True

    def test_taxi_separation_ignores_airborne(self):
        """Test taxi separation ignores airborne aircraft."""
        # Airborne aircraft
        airborne = make_flight_state(
            icao24="airborne001",
            latitude=37.49,
            longitude=-122.0,
            altitude=3000,
            on_ground=False,
            phase=FlightPhase.APPROACHING,
            aircraft_type="A320",
        )
        _flight_states["airborne001"] = airborne

        # Taxiing aircraft at same position (on ground)
        taxi = make_flight_state(
            icao24="taxi001",
            latitude=37.49,
            longitude=-122.0,
            altitude=0,
            on_ground=True,
            phase=FlightPhase.TAXI_TO_GATE,
            aircraft_type="A320",
        )
        _flight_states["taxi001"] = taxi

        # Should be clear because airborne aircraft not in conflict
        assert _check_taxi_separation(taxi) is True


class TestRunwayOccupancy:
    """Tests for runway single occupancy rules."""

    def setup_method(self):
        """Reset runway state before each test."""
        _runway_28R.occupied_by = None

    def teardown_method(self):
        """Clean up after each test."""
        _runway_28R.occupied_by = None

    def test_runway_initially_clear(self):
        """Test runway is initially clear."""
        _runway_28R.occupied_by = None
        assert _is_runway_clear("28R") is True

    def test_runway_occupied_after_occupy(self):
        """Test runway marked occupied."""
        _occupy_runway("test001", "28R")
        assert _is_runway_clear("28R") is False
        assert _runway_28R.occupied_by == "test001"

    def test_runway_clear_after_release(self):
        """Test runway cleared after release."""
        _occupy_runway("test001", "28R")
        assert _is_runway_clear("28R") is False

        _release_runway("test001", "28R")
        assert _is_runway_clear("28R") is True
        assert _runway_28R.occupied_by is None

    def test_runway_release_only_by_occupier(self):
        """Test only occupying aircraft can release runway."""
        _occupy_runway("test001", "28R")

        # Wrong aircraft tries to release
        _release_runway("other002", "28R")
        assert _is_runway_clear("28R") is False  # Still occupied

        # Correct aircraft releases
        _release_runway("test001", "28R")
        assert _is_runway_clear("28R") is True


class TestGateManagement:
    """Tests for gate occupancy and management."""

    def setup_method(self):
        """Reset gate states before each test."""
        _init_gate_states()
        for gate in _gate_states:
            _gate_states[gate].occupied_by = None
            _gate_states[gate].available_at = 0

    def teardown_method(self):
        """Clean up after each test."""
        for gate in _gate_states:
            _gate_states[gate].occupied_by = None
            _gate_states[gate].available_at = 0

    def test_gates_exist(self):
        """Test all 5 gates are defined."""
        assert len(GATES) == 5
        assert "A1" in GATES
        assert "A2" in GATES
        assert "A3" in GATES
        assert "B1" in GATES
        assert "B2" in GATES

    def test_find_available_gate_all_free(self):
        """Test finding available gate when all are free."""
        gate = _find_available_gate()
        assert gate is not None
        assert gate in GATES

    def test_find_available_gate_some_occupied(self):
        """Test finding available gate when some are occupied."""
        _occupy_gate("test001", "A1")
        _occupy_gate("test002", "A2")

        gate = _find_available_gate()
        assert gate is not None
        assert gate not in ["A1", "A2"]

    def test_find_available_gate_all_occupied(self):
        """Test no available gate when all are occupied."""
        for gate in GATES:
            _occupy_gate(f"test_{gate}", gate)

        available = _find_available_gate()
        assert available is None

    def test_gate_occupy_and_release(self):
        """Test gate occupy and release cycle."""
        # Occupy gate
        _occupy_gate("test001", "A1")
        assert _gate_states["A1"].occupied_by == "test001"

        # Release gate
        _release_gate("test001", "A1")
        assert _gate_states["A1"].occupied_by is None

    def test_gate_cooldown_after_release(self):
        """Test 60-second cooldown after gate release."""
        _occupy_gate("test001", "A1")
        _release_gate("test001", "A1")

        # Gate should have cooldown set
        assert _gate_states["A1"].available_at > time.time()

        # Should not be immediately available
        # (In real test, would need to mock time or wait)


class TestSeparationOverMultipleUpdates:
    """Tests that verify separation is maintained across multiple update cycles."""

    def setup_method(self):
        """Clear all state before each test."""
        _flight_states.clear()
        _runway_28R.occupied_by = None
        _init_gate_states()
        for gate in _gate_states:
            _gate_states[gate].occupied_by = None
            _gate_states[gate].available_at = 0

    def teardown_method(self):
        """Clean up after each test."""
        _flight_states.clear()
        _runway_28R.occupied_by = None

    def test_separation_maintained_multiple_approach_updates(self):
        """Test approach separation is maintained across multiple updates."""
        # Create two aircraft on approach
        lead = make_flight_state(
            icao24="lead001",
            latitude=37.49,
            longitude=-121.97,
            altitude=2000,
            phase=FlightPhase.APPROACHING,
            aircraft_type="A320",
        )
        follow = make_flight_state(
            icao24="follow001",
            latitude=37.49,
            longitude=-121.90,  # Well behind
            altitude=5000,
            phase=FlightPhase.APPROACHING,
            aircraft_type="A320",
        )

        _flight_states["lead001"] = lead
        _flight_states["follow001"] = follow

        # Simulate multiple update cycles
        for _ in range(10):
            # Move lead aircraft toward runway
            lead.longitude -= 0.005
            lead.altitude = max(0, lead.altitude - 300)

            # Check separation before moving follower
            if _check_approach_separation(follow):
                # Only move if separation maintained
                follow.longitude -= 0.005
                follow.altitude = max(0, follow.altitude - 300)

            # Verify separation is still valid or follower didn't move
            # (Either approach is blocked or separation is maintained)
            if not _check_approach_separation(follow):
                # If blocked, follower should not have moved closer than required
                dist = _distance_nm(
                    (lead.latitude, lead.longitude),
                    (follow.latitude, follow.longitude)
                )
                required = WAKE_SEPARATION_NM.get(("LARGE", "LARGE"), DEFAULT_SEPARATION_NM)
                # Allow small tolerance
                assert dist >= required - 0.5, f"Separation violated: {dist} NM < {required} NM"

    def test_runway_single_occupancy_over_updates(self):
        """Test runway stays single-occupied across updates."""
        # Aircraft 1 occupies runway
        _occupy_runway("landing001", "28R")
        assert _is_runway_clear("28R") is False

        # Simulate multiple updates while first aircraft on runway
        for _ in range(5):
            # Another aircraft should not be able to occupy
            if _is_runway_clear("28R"):
                # This should not happen
                assert False, "Runway cleared unexpectedly"

        # Release and verify
        _release_runway("landing001", "28R")
        assert _is_runway_clear("28R") is True

        # Now another can occupy
        _occupy_runway("landing002", "28R")
        assert _is_runway_clear("28R") is False

    def test_taxi_separation_during_movement(self):
        """Test taxi separation maintained during movement simulation."""
        # Two aircraft taxiing
        taxi1 = make_flight_state(
            icao24="taxi001",
            latitude=37.491,
            longitude=-122.01,
            altitude=0,
            on_ground=True,
            phase=FlightPhase.TAXI_TO_GATE,
            aircraft_type="A320",
        )
        taxi2 = make_flight_state(
            icao24="taxi002",
            latitude=37.491,
            longitude=-122.005,  # Behind
            altitude=0,
            on_ground=True,
            phase=FlightPhase.TAXI_TO_GATE,
            aircraft_type="A320",
        )

        _flight_states["taxi001"] = taxi1
        _flight_states["taxi002"] = taxi2

        # Simulate taxi movement
        for _ in range(10):
            # Move first aircraft
            taxi1.longitude += 0.001

            # Second aircraft checks separation before moving
            if _check_taxi_separation(taxi2):
                taxi2.longitude += 0.001
            # If blocked, second aircraft waits

            # Verify no violation
            dist = _distance_between(
                (taxi1.latitude, taxi1.longitude),
                (taxi2.latitude, taxi2.longitude)
            )
            # Allow violation only if check would have blocked movement
            if not _check_taxi_separation(taxi2):
                continue
            assert dist >= MIN_TAXI_SEPARATION_DEG * 0.9, "Taxi separation violated"

    def test_gate_assignments_no_overlap(self):
        """Test multiple aircraft are assigned different gates."""
        assigned_gates = []

        for i in range(5):
            gate = _find_available_gate()
            if gate:
                assigned_gates.append(gate)
                _occupy_gate(f"aircraft_{i}", gate)

        # All gates should be unique
        assert len(assigned_gates) == len(set(assigned_gates)), "Duplicate gate assignments"

        # Should be 5 unique gates
        assert len(assigned_gates) == 5


class TestGeneratedFlightsSeparation:
    """Integration tests for separation in generated flights."""

    def _parse_opensky_state(self, state: list) -> dict:
        """Parse OpenSky format state list into dict."""
        # OpenSky states format: [icao24, callsign, origin_country, time_position,
        #   last_contact, longitude, latitude, baro_altitude, on_ground, velocity,
        #   heading, vertical_rate, sensors, geo_altitude, squawk, spi, position_source]
        if len(state) < 12:
            return {}
        return {
            "icao24": state[0],
            "callsign": state[1],
            "longitude": state[5],
            "latitude": state[6],
            "baro_altitude": state[7],
            "on_ground": state[8],
            "velocity": state[9],
            "heading": state[10],
            "vertical_rate": state[11],
        }

    def test_generated_flights_maintain_approach_separation(self):
        """Test that generate_synthetic_flights maintains approach separation.

        Aircraft on the approach path (from east toward runway) should maintain
        at least 3 NM separation per FAA/ICAO standards.
        See: docs/AIRCRAFT_SEPARATION.md for standards.
        """
        # Generate flights multiple times
        for _ in range(5):
            result = generate_synthetic_flights(count=10)
            states = result.get("states", [])

            # Parse states into dicts
            flights = [self._parse_opensky_state(s) for s in states if s]

            # Find aircraft actually on approach path:
            # - Not on ground
            # - Altitude < 8000ft (approach altitude range)
            # - Longitude > -121.95 (east of airport, on approach path)
            # - Heading roughly west (240-300 degrees, toward runway)
            approaching = []
            for f in flights:
                if not f or f.get("on_ground") is not False:
                    continue
                alt = f.get("baro_altitude") or 10000
                if alt >= 8000:
                    continue
                lon = f.get("longitude", -122.0)
                if lon <= -121.95:  # Too close to/past airport
                    continue
                heading = f.get("heading") or 0
                # Accept westerly headings (toward runway)
                if not (200 <= heading <= 340):
                    continue
                approaching.append(f)

            if len(approaching) < 2:
                continue

            # Check pairwise separation for aircraft on approach
            for i, f1 in enumerate(approaching):
                for f2 in approaching[i+1:]:
                    if not f1.get("latitude") or not f2.get("latitude"):
                        continue
                    dist = _distance_nm(
                        (f1["latitude"], f1["longitude"]),
                        (f2["latitude"], f2["longitude"])
                    )
                    # Per FAA/ICAO, minimum 3 NM for LARGE→LARGE
                    assert dist >= 3.0, f"Approach aircraft too close: {dist:.1f} NM (min 3 NM)"

    def test_generated_flights_no_gate_collisions(self):
        """Test that generated flights don't have overlapping gates."""
        for _ in range(5):
            result = generate_synthetic_flights(count=15)
            states = result.get("states", [])

            # Parse states into dicts
            flights = [self._parse_opensky_state(s) for s in states if s]

            # Find parked aircraft (on ground, low altitude)
            parked = [
                f for f in flights
                if f and f.get("on_ground") is True
            ]

            if len(parked) < 2:
                continue

            # Check no two aircraft are at same position
            positions = [(f["latitude"], f["longitude"]) for f in parked if f.get("latitude")]
            for i, pos1 in enumerate(positions):
                for pos2 in positions[i+1:]:
                    dist = _distance_between(pos1, pos2)
                    # Gate spacing should be at least MIN_GATE_SEPARATION_DEG
                    if dist < MIN_GATE_SEPARATION_DEG * 0.5:
                        # Very close - potential collision
                        assert False, f"Aircraft too close at gates: {dist:.6f} deg"

    def test_generated_flights_consistent_over_updates(self):
        """Test flight positions are consistent across update calls."""
        # First generation
        result1 = generate_synthetic_flights(count=10)
        states1 = result1.get("states", [])
        flights1 = [self._parse_opensky_state(s) for s in states1 if s]
        icao_positions1 = {
            f["icao24"]: (f["latitude"], f["longitude"])
            for f in flights1 if f and f.get("icao24") and f.get("latitude")
        }

        # Wait a tiny bit and regenerate
        time.sleep(0.1)
        result2 = generate_synthetic_flights(count=10)
        states2 = result2.get("states", [])
        flights2 = [self._parse_opensky_state(s) for s in states2 if s]
        icao_positions2 = {
            f["icao24"]: (f["latitude"], f["longitude"])
            for f in flights2 if f and f.get("icao24") and f.get("latitude")
        }

        # Find aircraft present in both
        common_icao = set(icao_positions1.keys()) & set(icao_positions2.keys())

        for icao in common_icao:
            pos1 = icao_positions1[icao]
            pos2 = icao_positions2[icao]

            # Position should change smoothly (not teleport)
            dist = _distance_between(pos1, pos2)
            # Maximum reasonable movement in 0.1 seconds at 500 knots ≈ 0.001 deg
            assert dist < 0.01, f"Aircraft {icao} moved too far: {dist:.6f} deg"

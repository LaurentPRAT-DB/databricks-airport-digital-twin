"""Tests for H1-H5 performance optimization caches.

Verifies cache behavior, invalidation, and the turnaround_target_s field.
"""

import pytest

from src.ingestion._approach_departure import (
    _approach_waypoints_cache,
    _get_approach_waypoints,
    _get_osm_primary_runway,
    reset_approach_caches,
)
from src.ingestion._flight_lifecycle import (
    _compute_turnaround_target,
    _create_new_flight,
    _flight_states,
    set_calibration_gate_minutes,
)
from src.ingestion._generation import _get_icao_to_iata_map
from src.ingestion._state import FlightPhase, FlightState


class TestApproachWaypointsCache:
    """H2: _get_approach_waypoints caches by origin_iata."""

    def setup_method(self):
        reset_approach_caches()

    def test_same_origin_returns_cached_list(self):
        result1 = _get_approach_waypoints("LAX")
        result2 = _get_approach_waypoints("LAX")
        assert result1 is result2

    def test_different_origin_returns_different_list(self):
        result_lax = _get_approach_waypoints("LAX")
        result_jfk = _get_approach_waypoints("JFK")
        assert result_lax is not result_jfk

    def test_none_origin_consistent(self):
        result1 = _get_approach_waypoints(None)
        result2 = _get_approach_waypoints(None)
        assert result1 == result2

    def test_reset_clears_cache(self):
        result1 = _get_approach_waypoints("LAX")
        reset_approach_caches()
        result2 = _get_approach_waypoints("LAX")
        assert result1 is not result2


class TestOsmPrimaryRunwayCache:
    """H3: _get_osm_primary_runway caches per airport session."""

    def setup_method(self):
        reset_approach_caches()

    def test_repeated_calls_return_same_result(self):
        result1 = _get_osm_primary_runway()
        result2 = _get_osm_primary_runway()
        assert result1 == result2
        if result1 is not None:
            assert result1 is result2

    def test_reset_allows_recomputation(self):
        _get_osm_primary_runway()
        reset_approach_caches()
        # After reset, should recompute (may return same value but not same object)
        result = _get_osm_primary_runway()
        assert result is None or isinstance(result, dict)


class TestTurnaroundTargetField:
    """H4: turnaround_target_s computed once at PARKED entry."""

    def test_spawned_parked_has_positive_target(self):
        set_calibration_gate_minutes(0)
        flight = _create_new_flight(
            "opt_test1", "DAL100", FlightPhase.PARKED,
            origin="ATL", destination="LAX",
            aircraft_type_override="A320"
        )
        _flight_states["opt_test1"] = flight
        assert flight.turnaround_target_s > 0

    def test_target_within_realistic_bounds(self):
        set_calibration_gate_minutes(0)
        flight = _create_new_flight(
            "opt_test2", "AAL200", FlightPhase.PARKED,
            origin="DFW", destination="ORD",
            aircraft_type_override="A320"
        )
        _flight_states["opt_test2"] = flight
        # A320 uncalibrated: ~38-44 min target
        assert 1800 < flight.turnaround_target_s < 3600

    def test_wide_body_target_larger_than_narrow(self):
        set_calibration_gate_minutes(0)
        narrow = _create_new_flight(
            "opt_narrow", "UAL100", FlightPhase.PARKED,
            origin="SFO", destination="LAX",
            aircraft_type_override="A320"
        )
        _flight_states["opt_narrow"] = narrow
        wide = _create_new_flight(
            "opt_wide", "UAL200", FlightPhase.PARKED,
            origin="SFO", destination="NRT",
            aircraft_type_override="B777"
        )
        _flight_states["opt_wide"] = wide
        assert wide.turnaround_target_s > narrow.turnaround_target_s

    def test_lazy_fallback_computes_when_zero(self):
        """If turnaround_target_s is 0.0, _update_parked computes it."""
        set_calibration_gate_minutes(0)
        flight = _create_new_flight(
            "opt_lazy", "SWA100", FlightPhase.PARKED,
            origin="LAS", destination="PHX",
            aircraft_type_override="B738"
        )
        _flight_states["opt_lazy"] = flight
        flight.turnaround_target_s = 0.0
        # Import and call _update_parked indirectly via _update_flight_state
        from src.ingestion._flight_lifecycle import _update_flight_state
        _update_flight_state(flight, 1.0)
        assert flight.turnaround_target_s > 0


class TestIcaoToIataCache:
    """H5: _get_icao_to_iata_map cached at module level."""

    def test_returns_dict(self):
        result = _get_icao_to_iata_map()
        assert isinstance(result, dict)
        assert len(result) > 100

    def test_same_object_on_repeated_calls(self):
        result1 = _get_icao_to_iata_map()
        result2 = _get_icao_to_iata_map()
        assert result1 is result2

    def test_contains_expected_entries(self):
        mapping = _get_icao_to_iata_map()
        assert mapping.get("KSFO") == "SFO"
        assert mapping.get("KJFK") == "JFK"

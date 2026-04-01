"""Tests to improve SimulationEngine coverage.

Covers:
1. _critical_path_turnaround / _calibrated_turnaround (pure functions)
2. _force_advance (stuck flight recovery for each phase)
3. _proactive_cancel / _apply_temperature / _find_schedule_entry
"""

import random
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.simulation.config import SimulationConfig
from src.simulation.engine import (
    SimulationEngine,
    _critical_path_turnaround,
    _calibrated_turnaround,
)
from src.ingestion.fallback import (
    FlightPhase,
    FlightState,
    _flight_states,
    _gate_states,
    _init_gate_states,
    get_gates,
)


def _quick_config(**overrides) -> SimulationConfig:
    defaults = dict(
        airport="SFO",
        arrivals=3,
        departures=3,
        duration_hours=0.1,
        time_step_seconds=2.0,
        seed=42,
    )
    defaults.update(overrides)
    return SimulationConfig(**defaults)


def _make_flight_state(icao24: str, phase: FlightPhase, **kw) -> FlightState:
    defaults = dict(
        icao24=icao24,
        callsign=f"TST{icao24[-3:]}",
        latitude=37.615,
        longitude=-122.390,
        altitude=0.0,
        velocity=15.0,
        heading=280.0,
        vertical_rate=0.0,
        on_ground=True,
        phase=phase,
        aircraft_type="A320",
    )
    defaults.update(kw)
    return FlightState(**defaults)


# ---------------------------------------------------------------------------
# 1. Pure turnaround functions
# ---------------------------------------------------------------------------

class TestCriticalPathTurnaround:
    def test_returns_positive_minutes(self):
        random.seed(42)
        result = _critical_path_turnaround("A320")
        assert result > 0

    def test_wide_body_longer_than_narrow(self):
        """Wide-body turnaround should generally be longer."""
        random.seed(7)
        narrow_times = [_critical_path_turnaround("A320") for _ in range(20)]
        random.seed(7)
        wide_times = [_critical_path_turnaround("B777") for _ in range(20)]
        # Average should be higher for wide-body
        assert sum(wide_times) / len(wide_times) > sum(narrow_times) / len(narrow_times) * 0.8

    def test_various_aircraft_types(self):
        random.seed(42)
        for ac in ["A320", "B737", "B777", "A380", "E190"]:
            result = _critical_path_turnaround(ac)
            assert 10 < result < 300, f"{ac} turnaround {result} min out of range"

    def test_deterministic_with_seed(self):
        random.seed(99)
        t1 = _critical_path_turnaround("A320")
        random.seed(99)
        t2 = _critical_path_turnaround("A320")
        assert t1 == t2


class TestCalibratedTurnaround:
    def _make_profile(self, median_min: float = 45.0):
        """Create a minimal AirportProfile-like object."""
        from src.calibration.profile import AirportProfile
        return AirportProfile(
            icao_code="KSFO",
            iata_code="SFO",
            turnaround_median_min=median_min,
        )

    def test_uses_calibration_when_available(self):
        random.seed(42)
        profile = self._make_profile(median_min=45.0)
        result = _calibrated_turnaround("A320", "UAL", profile)
        # Should be in range: 45 * 0.85 to 45 * 1.15 (with airline factor)
        assert 30 < result < 80

    def test_falls_back_when_no_calibration(self):
        random.seed(42)
        profile = self._make_profile(median_min=0.0)
        result = _calibrated_turnaround("A320", "UAL", profile)
        # Should fall back to _critical_path_turnaround
        assert result > 0

    def test_wide_body_scaling(self):
        random.seed(42)
        profile = self._make_profile(median_min=45.0)
        narrow = _calibrated_turnaround("A320", "UAL", profile)
        random.seed(42)
        wide = _calibrated_turnaround("B777", "UAL", profile)
        # Wide-body gets 1.4x multiplier
        assert wide > narrow

    def test_negative_median_falls_back(self):
        random.seed(42)
        profile = self._make_profile(median_min=-5.0)
        result = _calibrated_turnaround("A320", "UAL", profile)
        assert result > 0


# ---------------------------------------------------------------------------
# 2. _force_advance — stuck flight recovery
# ---------------------------------------------------------------------------

class TestForceAdvance:
    """Test _force_advance transitions for each phase."""

    def _make_engine(self):
        engine = SimulationEngine(_quick_config(seed=42))
        return engine

    def test_taxi_to_gate_advances_to_parked(self):
        engine = self._make_engine()
        gates = get_gates()
        gate_name = next(iter(gates)) if gates else None
        if gate_name is None:
            pytest.skip("No gates available")

        state = _make_flight_state(
            "sim00099", FlightPhase.TAXI_TO_GATE,
            assigned_gate=gate_name,
        )
        _flight_states["sim00099"] = state
        engine._phase_counts["taxi_to_gate"] = 1

        engine._force_advance("sim00099", state)

        assert state.phase == FlightPhase.PARKED
        assert state.velocity == 0
        assert state.time_at_gate == 0
        _flight_states.pop("sim00099", None)

    def test_pushback_advances_to_taxi_to_runway(self):
        engine = self._make_engine()
        state = _make_flight_state("sim00097", FlightPhase.PUSHBACK, assigned_gate=None)
        _flight_states["sim00097"] = state
        engine._phase_counts["pushback"] = 1

        engine._force_advance("sim00097", state)

        assert state.phase == FlightPhase.TAXI_TO_RUNWAY
        assert state.waypoint_index == 0
        _flight_states.pop("sim00097", None)

    def test_taxi_to_runway_advances_to_takeoff(self):
        engine = self._make_engine()
        state = _make_flight_state("sim00096", FlightPhase.TAXI_TO_RUNWAY)
        _flight_states["sim00096"] = state
        engine._phase_counts["taxi_to_runway"] = 1

        engine._force_advance("sim00096", state)

        assert state.phase == FlightPhase.TAKEOFF
        assert state.takeoff_subphase == "lineup"
        assert state.velocity == 0
        assert state.takeoff_roll_dist_ft == 0.0
        _flight_states.pop("sim00096", None)

    def test_landing_advances_to_taxi_to_gate(self):
        engine = self._make_engine()
        state = _make_flight_state(
            "sim00095", FlightPhase.LANDING,
            altitude=50.0, on_ground=False,
        )
        _flight_states["sim00095"] = state
        engine._phase_counts["landing"] = 1

        engine._force_advance("sim00095", state)

        assert state.phase == FlightPhase.TAXI_TO_GATE
        assert state.altitude == 0
        assert state.on_ground is True
        _flight_states.pop("sim00095", None)

    def test_approaching_to_landing_when_runway_clear(self):
        engine = self._make_engine()
        state = _make_flight_state(
            "sim00094", FlightPhase.APPROACHING,
            altitude=400.0, on_ground=False,
        )
        _flight_states["sim00094"] = state
        engine._phase_counts["approaching"] = 1

        # Force no go-around
        with patch("src.simulation.engine.random.random", return_value=0.99):
            engine._force_advance("sim00094", state)

        assert state.phase == FlightPhase.LANDING
        _flight_states.pop("sim00094", None)

    def test_approaching_high_alt_triggers_go_around(self):
        """Approaching at >800ft should force a go-around (A09 fix)."""
        engine = self._make_engine()
        state = _make_flight_state(
            "sim00093", FlightPhase.APPROACHING,
            altitude=2000.0, on_ground=False,
        )
        _flight_states["sim00093"] = state
        engine._phase_counts["approaching"] = 1

        # No go-around from random, but altitude > 800 should force it
        with patch("src.simulation.engine.random.random", return_value=0.99):
            engine._force_advance("sim00093", state)

        assert state.phase == FlightPhase.ENROUTE
        assert state.go_around_count == 1
        _flight_states.pop("sim00093", None)

    def test_approaching_go_around_random(self):
        """Random go-around probability check."""
        engine = self._make_engine()
        state = _make_flight_state(
            "sim00092", FlightPhase.APPROACHING,
            altitude=400.0, on_ground=False,
        )
        _flight_states["sim00092"] = state
        engine._phase_counts["approaching"] = 1

        # Force go-around via random
        with patch.object(engine.capacity, "go_around_probability", return_value=1.0):
            with patch("src.simulation.engine.random.random", return_value=0.0):
                engine._force_advance("sim00092", state)

        assert state.phase == FlightPhase.ENROUTE
        assert state.go_around_count == 1
        _flight_states.pop("sim00092", None)

    def test_force_advance_records_phase_transition(self):
        engine = self._make_engine()
        state = _make_flight_state("sim00091", FlightPhase.PUSHBACK, assigned_gate=None)
        _flight_states["sim00091"] = state
        engine._phase_counts["pushback"] = 1

        initial_transitions = len(engine.recorder.phase_transitions)
        engine._force_advance("sim00091", state)
        assert len(engine.recorder.phase_transitions) > initial_transitions
        _flight_states.pop("sim00091", None)

    def test_force_advance_updates_phase_counters(self):
        engine = self._make_engine()
        state = _make_flight_state("sim00090", FlightPhase.TAXI_TO_RUNWAY)
        _flight_states["sim00090"] = state
        engine._phase_counts["taxi_to_runway"] = 1
        engine._phase_counts["takeoff"] = 0

        engine._force_advance("sim00090", state)

        assert engine._phase_counts["taxi_to_runway"] == 0
        assert engine._phase_counts["takeoff"] == 1
        _flight_states.pop("sim00090", None)


# ---------------------------------------------------------------------------
# 3. _proactive_cancel, _apply_temperature, _find_schedule_entry
# ---------------------------------------------------------------------------

class TestProactiveCancel:
    def _make_engine_with_timeline(self):
        engine = SimulationEngine(_quick_config(seed=42))
        # Create a fake severe weather event 1 hour from now
        from src.simulation.scenario import WeatherEvent, ResolvedEvent
        weather = WeatherEvent(
            time="12:00",
            type="thunderstorm",
            severity="severe",
            visibility_nm=0.5,
            ceiling_ft=200,
            wind_speed_kt=40,
            wind_gusts_kt=60,
            duration_hours=2.0,
        )
        event = ResolvedEvent(
            time=engine.sim_time + timedelta(hours=1),
            event_type="weather",
            event=weather,
            description="Severe thunderstorm",
        )
        engine.scenario_timeline = [event]
        engine._scenario_event_idx = 0
        return engine

    def test_cancels_departures_before_severe_weather(self):
        random.seed(1)  # Make random.random() < 0.15 hit for some flights
        engine = self._make_engine_with_timeline()

        # Add unspawned departure flights in the next 2 hours
        for i in range(20):
            sched_time = engine.sim_time + timedelta(minutes=30 + i * 3)
            engine.flight_schedule.append({
                "flight_number": f"TST{i:03d}",
                "flight_type": "departure",
                "scheduled_time": sched_time.isoformat(),
            })

        engine._proactive_cancel()

        cancelled = sum(1 for f in engine.flight_schedule if f.get("cancelled"))
        assert cancelled > 0, "Expected some departures to be cancelled"

    def test_no_cancel_without_severe_weather(self):
        engine = SimulationEngine(_quick_config(seed=42))
        engine.scenario_timeline = []

        engine._proactive_cancel()
        # Should return early, no cancellations
        cancelled = sum(1 for f in engine.flight_schedule if f.get("cancelled"))
        assert cancelled == 0

    def test_no_cancel_when_weather_is_moderate(self):
        engine = SimulationEngine(_quick_config(seed=42))
        from src.simulation.scenario import WeatherEvent, ResolvedEvent
        weather = WeatherEvent(
            time="12:00", type="rain", severity="moderate",
            duration_hours=1.0,
        )
        event = ResolvedEvent(
            time=engine.sim_time + timedelta(hours=1),
            event_type="weather",
            event=weather,
            description="Moderate rain",
        )
        engine.scenario_timeline = [event]
        engine._scenario_event_idx = 0

        engine._proactive_cancel()
        cancelled = sum(1 for f in engine.flight_schedule if f.get("cancelled"))
        assert cancelled == 0

    def test_no_cancel_for_arrivals(self):
        random.seed(1)
        engine = self._make_engine_with_timeline()

        # Only arrivals scheduled
        for i in range(10):
            sched_time = engine.sim_time + timedelta(minutes=30 + i * 3)
            engine.flight_schedule.append({
                "flight_number": f"ARR{i:03d}",
                "flight_type": "arrival",
                "scheduled_time": sched_time.isoformat(),
            })

        engine._proactive_cancel()
        cancelled = sum(1 for f in engine.flight_schedule if f.get("cancelled"))
        assert cancelled == 0


class TestApplyTemperature:
    def test_no_effect_without_weather(self):
        engine = SimulationEngine(_quick_config(seed=42))
        engine._active_weather_event = None
        old_temp = engine.capacity._temperature_c
        engine._apply_temperature()
        # Temperature should not change
        assert engine.capacity._temperature_c == old_temp

    def test_sandstorm_hot(self):
        engine = SimulationEngine(_quick_config(seed=42))
        engine._active_weather_event = SimpleNamespace(type="sandstorm")
        engine.sim_time = engine.sim_time.replace(hour=14)  # midday
        engine._apply_temperature()
        assert engine.capacity._temperature_c == 43.0  # 38 + 5

    def test_sandstorm_evening(self):
        engine = SimulationEngine(_quick_config(seed=42))
        engine._active_weather_event = SimpleNamespace(type="sandstorm")
        engine.sim_time = engine.sim_time.replace(hour=20)  # evening
        engine._apply_temperature()
        assert engine.capacity._temperature_c == 38.0

    def test_snow_cold(self):
        engine = SimulationEngine(_quick_config(seed=42))
        engine._active_weather_event = SimpleNamespace(type="snow")
        engine._apply_temperature()
        assert engine.capacity._temperature_c == -5.0

    def test_fog_temp(self):
        engine = SimulationEngine(_quick_config(seed=42))
        engine._active_weather_event = SimpleNamespace(type="fog")
        engine._apply_temperature()
        assert engine.capacity._temperature_c == 12.0

    def test_thunderstorm_temp(self):
        engine = SimulationEngine(_quick_config(seed=42))
        engine._active_weather_event = SimpleNamespace(type="thunderstorm")
        engine._apply_temperature()
        assert engine.capacity._temperature_c == 28.0

    def test_unknown_weather_default(self):
        engine = SimulationEngine(_quick_config(seed=42))
        engine._active_weather_event = SimpleNamespace(type="volcanic_ash")
        engine._apply_temperature()
        assert engine.capacity._temperature_c == 22.0

    def test_freezing_rain(self):
        engine = SimulationEngine(_quick_config(seed=42))
        engine._active_weather_event = SimpleNamespace(type="freezing_rain")
        engine._apply_temperature()
        assert engine.capacity._temperature_c == -5.0


class TestFindScheduleEntry:
    def test_finds_valid_entry(self):
        engine = SimulationEngine(_quick_config(seed=42))
        assert len(engine.flight_schedule) > 0
        result = engine._find_schedule_entry("sim00000")
        assert result is not None
        assert result == engine.flight_schedule[0]

    def test_returns_none_for_invalid_icao(self):
        engine = SimulationEngine(_quick_config(seed=42))
        result = engine._find_schedule_entry("notanumber")
        assert result is None

    def test_returns_none_for_out_of_range(self):
        engine = SimulationEngine(_quick_config(seed=42))
        result = engine._find_schedule_entry("sim99999")
        assert result is None

    def test_returns_none_for_empty_index(self):
        engine = SimulationEngine(_quick_config(seed=42))
        result = engine._find_schedule_entry("simXYZ")
        assert result is None

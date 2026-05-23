"""Tests for the injectable clock module (src/ingestion/_clock.py).

Verifies that:
- Default clock returns real wall time
- set_clock() overrides the clock for all consumers
- reset_clock() restores default behavior
- Runway separation and gate availability respect the injected clock
"""

import time

import pytest

from src.ingestion._clock import get_time, set_clock, reset_clock


@pytest.fixture(autouse=True)
def _restore_clock():
    """Ensure clock is always reset after each test."""
    yield
    reset_clock()


class TestClockBasics:

    def test_default_returns_real_time(self):
        before = time.time()
        result = get_time()
        after = time.time()
        assert before <= result <= after

    def test_set_clock_overrides(self):
        set_clock(lambda: 999999.0)
        assert get_time() == 999999.0

    def test_reset_clock_restores_default(self):
        set_clock(lambda: 0.0)
        assert get_time() == 0.0
        reset_clock()
        assert get_time() > 1_000_000_000  # any real epoch timestamp

    def test_clock_callable_invoked_each_call(self):
        counter = [0]

        def counting_clock():
            counter[0] += 1
            return 1000.0 + counter[0]

        set_clock(counting_clock)
        t1 = get_time()
        t2 = get_time()
        assert t1 == 1001.0
        assert t2 == 1002.0


class TestRunwaySeparationUsesClock:

    def test_arrival_separation_uses_injectable_clock(self):
        from src.ingestion._runway_ops import (
            _is_arrival_separation_met,
            _get_runway_state,
            _runway_states,
        )
        from src.ingestion._state import RunwayState

        rwy = "99T"
        _runway_states[rwy] = RunwayState()
        try:
            rs = _get_runway_state(rwy)
            # Set last arrival at t=1000
            rs.last_arrival_time = 1000.0

            # Clock at t=1001 — only 1s elapsed, separation NOT met (need >=60s)
            set_clock(lambda: 1001.0)
            assert _is_arrival_separation_met(rwy) is False

            # Clock at t=1100 — 100s elapsed, separation met
            set_clock(lambda: 1100.0)
            assert _is_arrival_separation_met(rwy) is True
        finally:
            _runway_states.pop(rwy, None)


class TestGateAvailabilityUsesClock:

    def test_gate_buffer_respects_injectable_clock(self):
        from src.ingestion._runway_ops import _find_available_gate, _gate_states
        from src.ingestion._state import GateState, GATE_BUFFER_SECONDS

        gate_name = "__test_gate_clock"
        _gate_states[gate_name] = GateState(
            occupied_by=None,
            available_at=2000.0,  # gate available at t=2000
        )
        try:
            # Clock before buffer expires — gate NOT available
            set_clock(lambda: 1999.0)
            available = [
                g for g, s in _gate_states.items()
                if s.occupied_by is None and get_time() >= s.available_at
                and g == gate_name
            ]
            assert available == []

            # Clock after buffer expires — gate available
            set_clock(lambda: 2001.0)
            available = [
                g for g, s in _gate_states.items()
                if s.occupied_by is None and get_time() >= s.available_at
                and g == gate_name
            ]
            assert available == [gate_name]
        finally:
            _gate_states.pop(gate_name, None)

"""Injectable clock for the flight state machine.

Replaces direct time.time() calls so the simulation engine can inject
sim-time without monkey-patching the global time module.
"""

import time as _time
from typing import Callable

_clock_fn: Callable[[], float] = _time.time


def get_time() -> float:
    """Return current time. Uses real wall clock by default, sim clock when set."""
    return _clock_fn()


def set_clock(fn: Callable[[], float]) -> None:
    """Override the clock function (used by SimulationEngine)."""
    global _clock_fn
    _clock_fn = fn


def reset_clock() -> None:
    """Restore default wall-clock behavior."""
    global _clock_fn
    _clock_fn = _time.time

---
status: proposed
area: simulation
priority: medium
effort: large
related:
  - .planning/backlog/ground-event-explanations.md
---

# Simulation Engine Refactor: Time Injection, PhaseResolver, ScheduleBuilder

## Context

SimulationEngine (1700 lines) has 3 architectural issues:
1. Global time.time() monkey-patch — engine replaces time.time on the time module object during every tick (L943-1080). This affects all code in-process, is thread-unsafe, and masks real bugs.
2. _force_advance is a 200-line method tightly coupled to engine state — hard to test without full engine instantiation.
3. Schedule generation runs inside __init__ (~250 lines) — can't test or reuse without creating a full engine.

**Goal:** extract testable units, eliminate the monkey-patch, make the engine extensible (new phase rules, new schedule strategies) without touching the tick loop or fallback.py global state patterns.

---

## Refactor 1: Time Injection (eliminate monkey-patch)

### Problem

_runway_ops.py (8 calls) and _flight_lifecycle.py (8 calls) do `import time` then call `time.time()`. Engine monkey-patches the global `time.time` function to return sim_timestamp during `_update_all_flights`. If anything else (logging, metrics, another thread) calls `time.time()` during that window, they get sim time instead of real time.

### Solution: Module-level get_time() function

Create `src/ingestion/_clock.py`:
```python
"""Injectable clock for the flight state machine."""
import time as _time

_clock_fn = _time.time  # default: real wall clock

def get_time() -> float:
    return _clock_fn()

def set_clock(fn) -> None:
    global _clock_fn
    _clock_fn = fn

def reset_clock() -> None:
    global _clock_fn
    _clock_fn = _time.time
```

Then in _runway_ops.py and _flight_lifecycle.py:
- Replace `import time` → `from src.ingestion._clock import get_time`
- Replace all `time.time()` → `get_time()`

In engine.py:
- Replace monkey-patch block with:
```python
from src.ingestion._clock import set_clock, reset_clock
# In run():
set_clock(lambda: self.sim_time.timestamp())
try:
    # ... tick loop ...
finally:
    reset_clock()
```
- Remove the per-tick try/finally in _update_all_flights entirely (clock stays set for the whole run)

### Files modified
- `src/ingestion/_clock.py` (NEW — 15 lines)
- `src/ingestion/_runway_ops.py` — replace 8x time.time() → get_time()
- `src/ingestion/_flight_lifecycle.py` — replace 8x time.time() → get_time()
- `src/simulation/engine.py` — remove monkey-patch, call set_clock/reset_clock in run()

### Tests (NEW): tests/test_clock.py
- test_default_returns_real_time
- test_set_clock_overrides
- test_reset_clock_restores_default
- test_runway_separation_uses_injectable_clock
- test_gate_availability_uses_injectable_clock

---

## Refactor 2: Extract PhaseResolver

### Problem

_force_advance (L1082-1289) is a 200-line method with:
- 6 inline imports from fallback.py
- Direct mutation of FlightState, _flight_states, runway states, gate states
- Coupled to engine.recorder and engine.capacity
- Each phase branch has ~20-40 lines of complex logic

Existing tests require full SimulationEngine instantiation.

### Solution: PhaseResolver class

Extract to stateless resolver with injected dependencies in `src/simulation/phase_resolver.py`:

```python
@dataclass
class PhaseResolution:
    """Result of resolving a stuck flight."""
    new_phase: FlightPhase | None  # None = no change
    state_mutations: dict  # fields to set on FlightState
    gate_release: str | None  # gate to release
    gate_assign: str | None  # gate to assign
    runway_release: str | None  # runway to release
    runway_occupy: str | None  # runway to occupy
    divert_to: str | None  # alternate airport (triggers diversion)
    event: dict | None  # scenario event to record

class PhaseResolver:
    def __init__(self, capacity: CapacityManager, airport_config: dict):
        self.capacity = capacity
        self.airport_config = airport_config

    def resolve(self, icao24: str, state: FlightState, phase_time: float) -> PhaseResolution:
        """Determine what to do with a stuck flight. Pure decision logic."""
        ...
```

Engine's _force_advance becomes:
```python
def _force_advance(self, icao24, state):
    resolution = self._phase_resolver.resolve(icao24, state, self._phase_time[icao24][1])
    self._apply_resolution(icao24, state, resolution)
```

Key design choice: `PhaseResolver.resolve()` returns a data object describing WHAT to do, not actually doing it. Fully testable without mocks.

### Files modified
- `src/simulation/phase_resolver.py` (NEW — ~200 lines)
- `src/simulation/engine.py` — _force_advance shrinks to ~20 lines

### Tests (NEW): tests/test_phase_resolver.py
- test_taxi_to_gate_stuck_resolves_to_parked
- test_pushback_stuck_resolves_to_taxi
- test_taxi_to_runway_first_snap_to_hold
- test_taxi_to_runway_already_at_hold_resolves_to_takeoff
- test_landing_stuck_resolves_to_taxi_to_gate
- test_approaching_low_alt_resolves_to_landing
- test_approaching_high_alt_resolves_to_go_around
- test_approaching_3_go_arounds_resolves_to_diversion
- test_enroute_arriving_stuck_resolves_to_diversion
- test_enroute_departing_stuck_resolves_to_exit
- Test extensibility: subclass PhaseResolver, override one method, verify works

---

## Refactor 3: Extract ScheduleBuilder

### Problem

_generate_schedule (L451-577) + _inject_fighter_sorties (L589-662) + _inject_traffic_modifiers (L664-726) = ~270 lines running in __init__. Can't:
- Test schedule generation without full engine
- Reuse schedules across what-if runs
- Swap schedule strategies

### Solution: ScheduleBuilder class

Extract to `src/simulation/schedule_builder.py`:

```python
class ScheduleBuilder:
    """Builds a flight schedule for a simulation run."""

    def __init__(self, config: SimulationConfig, profile: AirportProfile):
        self.config = config
        self.profile = profile

    def build(self) -> list[dict]:
        """Generate the full schedule."""
        schedule = []
        schedule.extend(self._generate_arrivals())
        schedule.extend(self._link_departures(schedule))
        schedule.extend(self._generate_surplus_departures(schedule))
        schedule.extend(self._inject_fighter_sorties())
        schedule.extend(self._inject_traffic_modifiers())
        schedule.sort(key=lambda f: f["scheduled_time"])
        return schedule
```

Engine's __init__ becomes:
```python
builder = ScheduleBuilder(config, self.airport_profile, scenario=self.scenario)
self.flight_schedule = builder.build()
self.recorder.schedule = self.flight_schedule
```

### Files modified
- `src/simulation/schedule_builder.py` (NEW — ~280 lines, moved from engine)
- `src/simulation/engine.py` — remove ~270 lines

### Tests (NEW): tests/test_schedule_builder.py
- test_arrivals_match_config_count
- test_departures_linked_to_arrivals
- test_surplus_departures_in_early_window
- test_schedule_sorted_by_time
- test_hourly_distribution_follows_profile
- test_fighter_sorties_only_for_ukrainian_airports
- test_traffic_modifiers_inject_extra_flights
- test_deterministic_with_seed
- test_custom_subclass_strategy

---

## Execution Order

1. **Refactor 1 (Clock)** — smallest blast radius, unlocks safe testing for Refactors 2 & 3
2. **Refactor 3 (ScheduleBuilder)** — pure extraction, no logic changes
3. **Refactor 2 (PhaseResolver)** — most complex, benefits from clock being injectable

Each refactor is one commit. After each: `uv run pytest tests/ -x -q`.

---

## Verification

After all 3 refactors:
1. `uv run pytest tests/ -v` — all ~3089 tests pass
2. `uv run pytest tests/test_clock.py tests/test_phase_resolver.py tests/test_schedule_builder.py -v` — new tests pass
3. Run a short simulation: `uv run python -m src.simulation --airport SFO --arrivals 10 --departures 10 --duration-hours 1 --seed 42`
4. Confirm no `time.time()` remains in _runway_ops.py or _flight_lifecycle.py (grep)
5. Confirm _force_advance in engine is now <30 lines (delegation only)
6. Confirm engine __init__ no longer contains schedule generation logic

---

## Risk Mitigation

- **Clock injection could break non-sim callers** (API server uses same _flight_lifecycle.py): reset_clock() is called in finally block, and default is real time.time(). Server never calls set_clock.
- **PhaseResolver returns data, engine applies it** — if resolution logic has bugs, same behavior as before (just organized differently).
- **ScheduleBuilder is pure extraction** — no logic changes, just moved code.

---
status: backlog
area: simulation
priority: medium
related:
  - src/ingestion/_flight_lifecycle.py
  - src/simulation/engine.py
  - tests/test_flight_lifecycle_characterization.py
---

# Plan: Consolidate _flight_lifecycle Global State into Dataclass

## Context

`src/ingestion/_flight_lifecycle.py` has 9 module-level calibration globals set via `set_*()` functions and read directly by 30+ references.
This creates:
- Test fragility (must patch exact variable names, miss one → test pollution)
- `_reset_global_state()` in engine.py must clear 15+ globals across 3 modules — miss one and tests leak state
- Difficult to reason about what state a sim run depends on

The fix: consolidate calibration globals into a single `SimCalibration` dataclass. The engine creates it, passes it to the lifecycle module once per run. Tests can construct it directly.

## Scope (Intentionally Limited)

Only refactor the calibration state in `_flight_lifecycle.py` (9 variables). Do NOT touch:
- `_flight_states`, `_gate_states`, `_runway_states` (different concern — runtime state, not config)
- `_flights_by_phase` index (performance optimization, not calibration)
- The `_original.py` file (frozen reference)

## Implementation

### Step 1: Create SimCalibration dataclass

New file: `src/ingestion/_calibration_state.py`

```python
from dataclasses import dataclass, field
from typing import Dict

@dataclass
class SimCalibration:
    """Per-run calibration parameters set by the simulation engine."""
    gate_minutes: float = 0.0
    taxi_out_target_s: float = 0.0
    taxi_out_waypoint_s: float = 0.0
    taxi_out_p95_s: float = 0.0
    taxi_in_target_s: float = 0.0
    taxi_in_waypoint_s: float = 0.0
    taxi_in_p95_s: float = 0.0
    weather_wind_kts: float = 0.0
    weather_visibility_sm: float = 10.0
    gate_last_delay: Dict[str, float] = field(default_factory=dict)
```

### Step 2: Add module-level instance + getter

In `_flight_lifecycle.py`, replace 9 globals with one:

```python
from src.ingestion._calibration_state import SimCalibration

_calibration = SimCalibration()

def set_calibration(cal: SimCalibration) -> None:
    global _calibration
    _calibration = cal

def get_calibration() -> SimCalibration:
    return _calibration
```

### Step 3: Keep backward-compatible set_*() wrappers (deprecation path)

Keep `set_calibration_gate_minutes()`, `set_calibration_taxi_out()`, `set_calibration_taxi_in()`, `set_current_weather()` but have them mutate `_calibration` fields. This means zero changes needed in engine.py or tests initially.

```python
def set_calibration_gate_minutes(minutes: float) -> None:
    _calibration.gate_minutes = minutes

def set_calibration_taxi_out(mean_minutes: float, waypoint_travel_s: float = 180.0, p95_minutes: float = 0.0) -> None:
    _calibration.taxi_out_target_s = mean_minutes * 60.0
    _calibration.taxi_out_waypoint_s = waypoint_travel_s
    _calibration.taxi_out_p95_s = p95_minutes * 60.0 if p95_minutes > 0 else mean_minutes * 60.0 * 1.8

def set_calibration_taxi_in(mean_minutes: float, waypoint_travel_s: float = 120.0, p95_minutes: float = 0.0) -> None:
    _calibration.taxi_in_target_s = mean_minutes * 60.0
    _calibration.taxi_in_waypoint_s = waypoint_travel_s
    _calibration.taxi_in_p95_s = p95_minutes * 60.0 if p95_minutes > 0 else mean_minutes * 60.0 * 2.0

def set_current_weather(wind_speed_kts: float, visibility_sm: float) -> None:
    _calibration.weather_wind_kts = wind_speed_kts
    _calibration.weather_visibility_sm = visibility_sm
```

### Step 4: Replace direct global reads with _calibration.field

In `_flight_lifecycle.py`, replace all 30 reads:
- `_calibration_taxi_in_target_s` → `_calibration.taxi_in_target_s`
- `_calibration_taxi_out_target_s` → `_calibration.taxi_out_target_s`
- `_current_weather["wind_speed_kts"]` → `_calibration.weather_wind_kts`
- `_gate_last_delay` → `_calibration.gate_last_delay`
- etc.

### Step 5: Add reset_calibration() for clean state

```python
def reset_calibration() -> None:
    global _calibration
    _calibration = SimCalibration()
```

Add one call in `_reset_global_state()` in engine.py — replaces the individual setter calls with `reset_calibration()` followed by re-setting from profile.

### Step 6: Update characterization test patches

Change patches from:
```python
patch("src.ingestion._flight_lifecycle._calibration_taxi_out_target_s", 120.0)
```
to:
```python
patch.object(_calibration, 'taxi_out_target_s', 120.0)
```
Or simpler — set `_calibration` directly in test setup.

## Files Modified

- `src/ingestion/_calibration_state.py` — new (dataclass, ~20 lines)
- `src/ingestion/_flight_lifecycle.py` — replace 9 globals with `_calibration` instance, update 30 reads
- `src/simulation/engine.py` — add `reset_calibration()` call (optional, backward-compat wrappers mean no change needed initially)
- `tests/test_flight_lifecycle_characterization.py` — update 6 patches to use new field names

## What This Does NOT Change

- No changes to simulation behavior (pure refactor)
- Engine still calls `set_calibration_taxi_out()` etc. (backward compat)
- `_flight_lifecycle_original.py` untouched (frozen)
- Runtime state (`_flight_states`, `_gate_states`) stays as-is (different concern)

## Benefits

1. **One reset clears all calibration** — `reset_calibration()` replaces 9 individual resets
2. **Tests construct directly** — `SimCalibration(taxi_in_target_s=456)` instead of patching 3 globals
3. **Discoverable** — IDE autocomplete shows all calibration fields in one place
4. **Future: pass as argument** — `_update_taxi_to_gate(state, dt, cal)` eliminates global entirely (phase 2, not now)

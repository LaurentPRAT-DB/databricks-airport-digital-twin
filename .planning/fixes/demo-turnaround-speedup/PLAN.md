# Consistent Demo Time Multiplier for Turnaround Lifecycle

## Context

`DEMO_TURNAROUND_SPEEDUP = 8.0` exists at `fallback.py:42` and is applied at line 3094 to divide the gate-time threshold. This makes flights push back after ~4 min instead of 35 min. But it's only applied in one place. Several other time-dependent paths still use real-time durations, causing inconsistencies:

- Turnaround sub-phases (deboarding, catering, boarding...) still fire at real-time speed — they never complete before the sped-up pushback trigger
- Gate cooldown is still 60s real-time after departure
- Initial parked time for pre-seeded flights (0-300s) can exceed the sped-up gate time
- GSE service estimated departure and progress calculations ignore the speedup

## Design Principle: Speed Up Waiting, Not Movement

The speedup should apply to stationary wait durations (aircraft sitting at gate while processes complete), NOT to physical movements (pushback, taxi, approach, takeoff) or safety separations (wake turbulence). This keeps the visual motion realistic while compressing the "boring" gate time.

| Category | Examples | Speed Up? |
|---|---|---|
| Gate wait durations | Gate time, sub-phase durations, gate cooldown | YES |
| Physical movement | Pushback, taxi, approach, landing, takeoff | NO |
| Safety separations | Runway wake turbulence (60-180s) | NO |
| Holding patterns | Racetrack legs (60s) | NO |
| dt / physics tick | `current_time - _last_update` | NO |

## Changes

### 1. `src/ingestion/fallback.py` — Rename + apply consistently

**Rename constant (line 42):**
```python
# Before
DEMO_TURNAROUND_SPEEDUP = 8.0

# After — clearer name, same value
DEMO_GATE_TIME_MULTIPLIER = 8.0  # Divides all gate-related wait durations
```

**`_build_turnaround_schedule()` (line 2437-2438) — Compress sub-phase durations:**
```python
# Before
schedule[phase] = {
    "start_offset_s": start[phase] * 60,
    "duration_s": jittered[phase] * 60,
    ...
}

# After — sub-phases compressed by same factor
schedule[phase] = {
    "start_offset_s": start[phase] * 60 / DEMO_GATE_TIME_MULTIPLIER,
    "duration_s": jittered[phase] * 60 / DEMO_GATE_TIME_MULTIPLIER,
    ...
}
```

This ensures chocks_on -> deboarding -> cleaning -> catering -> refueling -> loading -> boarding -> chocks_off all fire and complete WITHIN the sped-up gate time, keeping proportions correct.

**Initial parked time (line 2553):**
```python
# Before
initial_time_at_gate = random.uniform(0, 300)

# After — scale with gate time
initial_time_at_gate = random.uniform(0, 300 / DEMO_GATE_TIME_MULTIPLIER)
```

Without this, a pre-seeded flight could have 5 min of elapsed gate time which exceeds the ~4 min sped-up narrow-body turnaround.

**Gate cooldown (line 1847):**
```python
# Before
_gate_states[gate].available_at = time.time() + 60

# After
_gate_states[gate].available_at = time.time() + 60 / DEMO_GATE_TIME_MULTIPLIER
```

1 minute cooldown -> ~7.5 seconds. Keeps gate recycling proportional.

**Gate time threshold (line 3094) — Update variable name only:**
```python
# Before
target = target / DEMO_TURNAROUND_SPEEDUP

# After
target = target / DEMO_GATE_TIME_MULTIPLIER
```

### 2. `src/ml/gse_model.py` — Make `calculate_turnaround_status()` speedup-aware

**`calculate_turnaround_status()` (line 225) — Multiply elapsed time by speedup factor:**
```python
# Before
elapsed_minutes = (current_time - arrival_time).total_seconds() / 60

# After
from src.ingestion.fallback import DEMO_GATE_TIME_MULTIPLIER
elapsed_minutes = (current_time - arrival_time).total_seconds() / 60 * DEMO_GATE_TIME_MULTIPLIER
```

This makes the turnaround progress bar advance 8x faster, matching the compressed gate time. Used by the fallback path in `gse_service.py:174` and the `TurnaroundTimeline` frontend component.

### 3. `app/backend/services/gse_service.py` — Fix estimated departure

**Estimated departure (line 162):**
```python
# Before
estimated_departure = arrival_time + timedelta(minutes=timing["total_minutes"])

# After
from src.ingestion.fallback import DEMO_GATE_TIME_MULTIPLIER
estimated_departure = arrival_time + timedelta(minutes=timing["total_minutes"] / DEMO_GATE_TIME_MULTIPLIER)
```

### 4. Export the constant for import

Ensure `DEMO_GATE_TIME_MULTIPLIER` is importable from `fallback.py` (it already is by being a module-level constant — no `__all__` filtering exists).

## What NOT to Touch

- **Pushback** (`phase_progress += dt / 240.0` at line 3121) — Physical movement, takes 4 min regardless. Aircraft must clear the gate visually.
- **Taxi speeds** (`TAXI_SPEED_STRAIGHT_KTS`, `TAXI_SPEED_PUSHBACK_KTS`) — Physical speed.
- **Runway separation** (`DEPARTURE_SEPARATION_S`, `DEFAULT_DEPARTURE_SEPARATION_S`) — FAA wake turbulence minimums.
- **Holding pattern** (`HOLDING_LEG_SECONDS = 60.0`) — Physical racetrack legs.
- **Approach / landing / takeoff** — All position-based transitions.
- **dt computation** (line 3531) — Physics tick must reflect real elapsed time.

## Files Modified

| File | Changes |
|---|---|
| `src/ingestion/fallback.py` | Rename constant, apply to `_build_turnaround_schedule()`, initial parked time, gate cooldown |
| `src/ml/gse_model.py` | `calculate_turnaround_status()` uses multiplier for elapsed time |
| `app/backend/services/gse_service.py` | `estimated_departure` uses multiplier |

## Verification

1. Run tests: `uv run pytest tests/ -v` — all existing tests must pass (the constant change may require updating test assertions that check turnaround durations)
2. Run frontend tests: `cd app/frontend && npm test -- --run`
3. Local dev (`./dev.sh`):
   - Open browser, observe at KSFO
   - Watch a PARKED flight: turnaround sub-phases (deboarding, cleaning, etc.) should visibly progress in the TurnaroundTimeline component
   - Within ~4-5 min, the flight should push back — AND all turnaround sub-phases should show as completed by that point
   - After pushback, the gate should become available within ~8 seconds (not 60s)
   - The overall lifecycle should be: approach -> land -> taxi -> park (~4 min turnaround) -> pushback -> taxi -> takeoff -> depart — all visible within ~8-10 min
4. Check proportions: Sub-phase durations should still be proportional to each other (boarding takes longer than chocks_on, etc.) — just compressed

# Plan: Event-Driven Turnaround Simulation

## Context

Level 1 (commit 9c73cbc) wired real parked_since / assigned_gate into the GSE service, but turnaround sub-phases (deboarding, refueling, boarding…) are still clock-estimated by `calculate_turnaround_status()` using elapsed time since arrival. There are no actual turnaround events being simulated — the phase shown to the user is an interpolation, not a real state.

The goal is to make the simulation engine actually progress through turnaround phases while a flight is PARKED, emit events when each phase starts/completes, and have the GSE service read those real phase states instead of computing them from elapsed time.

## Existing Infrastructure

- Event buffers already exist in `fallback.py`: `_phase_transition_buffer`, `_gate_event_buffer`, `_prediction_buffer` — all thread-safe with locks, capped at 10K, drained by DataGeneratorService and the simulation engine.
- `emit_gate_event()` already emits assign/occupy/release events.
- `emit_phase_transition()` records flight-level phase changes (APPROACHING→LANDING, etc.).
- `PHASE_DEPENDENCIES` in `gse_model.py` defines the DAG (e.g., boarding depends on cleaning+catering).
- `TURNAROUND_TIMING` has per-phase durations for narrow/wide body.
- `AIRLINE_TURNAROUND_FACTOR` and weather/congestion/intl/dow factors already modulate total gate time in `_update_flight_state`.
- `FlightState` already has `parked_since`, `time_at_gate`, `assigned_gate`, `aircraft_type`.

## Approach

### 1. Add turnaround state to FlightState — `fallback.py`

Add two new fields to `FlightState`:
```python
turnaround_phase: str = ""                    # Current turnaround sub-phase (e.g. "deboarding")
turnaround_schedule: Optional[Dict] = None    # {phase_name: {"start": float, "end": float, "done": bool}}
```

### 2. Build turnaround schedule on PARKED entry — `fallback.py`

New function `_build_turnaround_schedule(aircraft_type, airline_code, parked_since)`:
- Gets base durations from `get_turnaround_timing(aircraft_type)`
- Applies combined factor (airline × weather × congestion × intl × dow) with ±10% per-phase jitter
- Walks the `PHASE_DEPENDENCIES` DAG to compute earliest-start for each phase (critical path scheduling, same approach as `_critical_path_turnaround` in `engine.py`)
- Skips `arrival_taxi` and `departure_taxi`/`pushback` (those are handled by sim movement phases)
- Returns dict: `{phase: {"start_offset_s": float, "duration_s": float, "done": bool}}`
- The gate-relevant phases are: `chocks_on`, `deboarding`, `unloading`, `cleaning`, `catering`, `refueling`, `loading`, `boarding`, `chocks_off`

Called at the two PARKED entry points:
1. `_create_new_flight()` when spawning as PARKED
2. `_update_flight_state()` when transitioning TAXI_TO_GATE → PARKED

### 3. Progress turnaround phases during PARKED update — `fallback.py`

In the existing `elif state.phase == FlightPhase.PARKED:` block of `_update_flight_state()`:
- After incrementing `time_at_gate += dt`, check `turnaround_schedule`
- For each phase in the schedule: if `time_at_gate >= start_offset_s` and not yet started → emit turnaround event, mark as active
- If `time_at_gate >= start_offset_s + duration_s` and not done → mark done, emit completion event
- Update `state.turnaround_phase` to the current active phase name
- Keep the existing pushback trigger logic (total gate time target) unchanged

### 4. New event emitter — `fallback.py`

Add `emit_turnaround_event()` following the same pattern as `emit_gate_event()`:
```python
def emit_turnaround_event(icao24, callsign, gate, phase, event_type, aircraft_type):
    # event_type: "phase_start" or "phase_complete"
    # Appends to _turnaround_event_buffer (new buffer + lock)
```

Add corresponding `drain_turnaround_events()`.

### 5. Expose turnaround state in `get_flight_turnaround_info()` — `fallback.py`

Extend the existing function to include:
```python
"turnaround_phase": state.turnaround_phase,
"turnaround_schedule": state.turnaround_schedule,
```

### 6. GSE service reads real phase — `gse_service.py`

In `get_turnaround_status()`, when `sim_info` is available:
- If `sim_info["turnaround_phase"]` is set, use it directly as `current_phase` instead of calling `calculate_turnaround_status()`
- Compute `phase_progress_pct` from the schedule's start/duration for the active phase
- Compute `total_progress_pct` from the schedule (fraction of phases completed)
- Keep `calculate_turnaround_status()` as fallback when `turnaround_schedule` is None

### 7. Wire drain into DataGeneratorService — `data_generator_service.py`

Add `drain_turnaround_events` import alongside existing drains. Persist events to the same mechanism as gate events (Lakebase or logging).

## Files to Modify

| File | Change |
|------|--------|
| `src/ingestion/fallback.py` | Add turnaround state fields to FlightState, `_build_turnaround_schedule()`, turnaround event buffer/emitter/drain, progress logic in PARKED update, extend `get_flight_turnaround_info()` |
| `src/ml/gse_model.py` | No changes — reuse `TURNAROUND_TIMING`, `PHASE_DEPENDENCIES`, `get_turnaround_timing()` as-is |
| `app/backend/services/gse_service.py` | Read real turnaround phase from sim_info instead of computing from elapsed time |
| `app/backend/services/data_generator_service.py` | Import and drain turnaround_events |

## Key Design Decisions

- **Gate-only phases:** The schedule covers `chocks_on` through `chocks_off`. `arrival_taxi`/`pushback`/`departure_taxi` are real movement phases already simulated.
- **Per-phase jitter:** Each phase gets independent ±10% random variation, making turnarounds feel organic rather than mechanically identical.
- **Combined factor applied once at schedule build:** Airline/weather/congestion/intl/dow factors scale all phase durations proportionally when the schedule is built. No re-computation each tick.
- **Existing pushback trigger unchanged:** The current `time_at_gate > target` logic stays as the authoritative gate exit trigger. The turnaround schedule phases are informational — they track what's happening during the gate stay, but the total duration is still governed by the existing factor-based target.
- **Backward compatible:** `turnaround_schedule` defaults to None, so flights created before the change still work via the `calculate_turnaround_status()` fallback.

## Verification

1. `uv run pytest tests/ -k "turnaround or gse" -v --ignore=tests/test_airport_persistence.py` — all existing tests pass
2. `uv run pytest tests/ -k "phase_transition or gate_event" -v` — event buffer tests pass
3. `cd app/frontend && npx vitest run src/components/FlightDetail/` — frontend unchanged
4. `./dev.sh` → click a parked flight → turnaround panel shows real sub-phase progression matching time at gate

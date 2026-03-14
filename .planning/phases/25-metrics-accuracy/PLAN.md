# Phase 25: Metrics Accuracy — Fix Disconnected Simulation Metrics

## Goal

Fix 5 metric accuracy issues that prevent meaningful cross-scenario and cross-airport comparison. After these fixes, metrics will reflect actual simulation behavior (capacity constraints, scenario disruptions) rather than pre-generated schedule data.

## Status: Plan — Not Started

## Prerequisites: Phase 23 (Simulation Mode) and Phase 24 (Scenario Simulation) must be complete.

---

## Context

After running 7 regional airport simulations (SFO, LHR, NRT, DXB, GRU, JFK, SYD) with severe weather scenarios, analysis revealed that key metrics are disconnected from scenario impact:

| Metric | Problem | Impact |
|--------|---------|--------|
| `avg_delay` (26.6 min across ALL airports) | Reflects pre-generated schedule delay, not capacity-caused delay | Can't distinguish fair weather from severe storm |
| `on_time_pct` (84.4-84.6% everywhere) | Computed from schedule, not actual spawn times | Same value regardless of scenario severity |
| `gates_used` (always 0) | Departures never emit "occupy" events | Gate utilization invisible |
| No cancellation metric | JFK spawned only 597/1020 flights but no metric surfaces this | Lost flights undetected |
| No capacity hold metric | No measurement of how long flights wait due to throughput limits | Scenario impact unmeasurable |

These 5 fixes are prerequisites for meaningful cross-scenario comparison.

---

## Tasks

### Task 1: Fix gate occupy event for departures

**File:** `src/ingestion/fallback.py` line 1648

**Root cause:** When departures are created as PARKED in `_create_new_flight()`, line 1648 calls `_occupy_gate(icao24, gate)` but never calls `emit_gate_event(icao24, callsign, gate, "occupy", aircraft_type)`. The "occupy" event only fires for arrivals completing the taxi-to-gate → parked transition (line 2030).

**Fix:** Add one line after line 1648:

```python
_occupy_gate(icao24, gate)
emit_gate_event(icao24, callsign, gate, "occupy", aircraft_type)  # NEW
```

---

### Task 2: Track actual spawn times in engine

**File:** `src/simulation/engine.py`

**Root cause:** `_spawn_scheduled_flights()` doesn't record when a flight actually spawns vs when it was scheduled. Without this, we can't compute capacity-caused delay.

**Changes in `__init__`** (after line 91):
```python
self._spawn_times: dict[int, datetime] = {}  # schedule_idx -> actual spawn time
```

**Changes in `_spawn_scheduled_flights()`** — after `self._spawned_indices.add(idx)` (line 493):
```python
self._spawn_times[idx] = self.sim_time
```

**Changes in `run()`** — before `self.recorder.write_output()`, enrich schedule entries:
```python
for idx, flight in enumerate(self.flight_schedule):
    flight["actual_spawn_time"] = self._spawn_times[idx].isoformat() if idx in self._spawn_times else None
    flight["spawned"] = idx in self._spawned_indices
```

---

### Task 3: Add capacity_hold_time metric (scenario-caused delay)

**File:** `src/simulation/recorder.py` lines 125-185 — in `compute_summary()`

**Current:** `avg_delay` (line 132) uses `f["delay_minutes"]` from pre-generated schedule.

**Add new capacity-aware metrics** after the existing delay calculation:

```python
# Scenario-caused delay: actual spawn time vs effective scheduled time
capacity_delays = []
for f in self.schedule:
    if f.get("actual_spawn_time") and f.get("scheduled_time"):
        scheduled = datetime.fromisoformat(f["scheduled_time"])
        effective = scheduled + timedelta(minutes=f.get("delay_minutes", 0))
        actual = datetime.fromisoformat(f["actual_spawn_time"])
        hold_min = max(0, (actual - effective).total_seconds() / 60.0)
        capacity_delays.append(hold_min)

avg_capacity_hold = sum(capacity_delays) / len(capacity_delays) if capacity_delays else 0.0
max_capacity_hold = max(capacity_delays) if capacity_delays else 0.0
```

**Add to summary dict:**
```python
"avg_capacity_hold_min": round(avg_capacity_hold, 1),
"max_capacity_hold_min": round(max_capacity_hold, 1),
```

---

### Task 4: Fix on-time % to use actual vs scheduled spawn times

**File:** `src/simulation/recorder.py` lines 134-135

**Current:**
```python
on_time = sum(1 for f in self.schedule if f.get("delay_minutes", 0) == 0)
on_time_pct = (on_time / total_flights * 100) if total_flights > 0 else 0.0
```

**Replace with** scenario-aware on-time that includes capacity hold and counts non-spawned flights as not on-time:

```python
on_time_threshold = 15  # minutes
on_time = 0
for f in self.schedule:
    if f.get("actual_spawn_time"):
        scheduled = datetime.fromisoformat(f["scheduled_time"])
        effective = scheduled + timedelta(minutes=f.get("delay_minutes", 0))
        actual = datetime.fromisoformat(f["actual_spawn_time"])
        if (actual - effective).total_seconds() / 60.0 <= on_time_threshold:
            on_time += 1
    # Non-spawned flights count as NOT on-time (don't increment)
on_time_pct = (on_time / total_flights * 100) if total_flights > 0 else 0.0
```

**Keep the old schedule-based metric** as `schedule_delay_min` for backward compat:
```python
"schedule_delay_min": round(avg_delay, 1),  # renamed from avg_delay_min
```

---

### Task 5: Add cancellation_rate and effective_delay for non-spawned flights

**File:** `src/simulation/recorder.py` — in `compute_summary()`

```python
# Cancellation metrics
spawned_count = sum(1 for f in self.schedule if f.get("spawned", True))
not_spawned = total_flights - spawned_count
cancellation_rate = (not_spawned / total_flights * 100) if total_flights > 0 else 0.0

# Effective delay for non-spawned flights (how late they'd be at sim end)
effective_delays = []
for f in self.schedule:
    if not f.get("spawned", True) and f.get("scheduled_time"):
        scheduled = datetime.fromisoformat(f["scheduled_time"])
        effective = scheduled + timedelta(minutes=f.get("delay_minutes", 0))
        if self.position_snapshots:
            last_time = datetime.fromisoformat(self.position_snapshots[-1]["time"])
        else:
            last_time = effective
        delay_min = max(0, (last_time - effective).total_seconds() / 60.0)
        effective_delays.append(delay_min)
```

**Add to summary dict:**
```python
"spawned_count": spawned_count,
"not_spawned_count": not_spawned,
"cancellation_rate_pct": round(cancellation_rate, 1),
"avg_effective_delay_not_spawned_min": round(
    sum(effective_delays) / len(effective_delays) if effective_delays else 0, 1
),
```

---

### Task 6: Update CLI output

**File:** `src/simulation/cli.py`

Add new metrics to the summary print block (after existing lines):

```
  Capacity hold (avg):    {avg_capacity_hold_min} min
  Capacity hold (max):    {max_capacity_hold_min} min
  Schedule delay (avg):   {schedule_delay_min} min
  Spawned:                {spawned_count}/{total_flights}
  Cancellation rate:      {cancellation_rate_pct}%
```

---

### Task 7: Update tests

**File:** `tests/test_scenario.py` — add new test class `TestMetricsAccuracy`:

- `test_gate_occupy_event_for_departures`: Create a PARKED flight, verify "occupy" event emitted
- `test_capacity_hold_time_recorded`: Run mini scenario with capacity constraint, verify `avg_capacity_hold_min > 0`
- `test_cancellation_rate_nonzero`: Simulate scenario where flights can't spawn, verify `cancellation_rate_pct > 0`
- `test_on_time_reflects_actual_spawn`: Verify on-time uses actual spawn time, not schedule delay
- `test_effective_delay_for_unspawned`: Verify large delay recorded for flights that never spawned
- `test_backward_compat_schedule_delay`: Verify `schedule_delay_min` still present for backward compat

---

## Files Modified

| File | Change | Lines |
|------|--------|-------|
| `src/ingestion/fallback.py` | Add `emit_gate_event("occupy")` for departures | +1 line at 1648 |
| `src/simulation/engine.py` | Add `_spawn_times`, record spawn time, enrich schedule | ~15 lines |
| `src/simulation/recorder.py` | New metrics in `compute_summary()` | ~40 lines |
| `src/simulation/cli.py` | Print new metrics | ~5 lines |
| `tests/test_scenario.py` | New `TestMetricsAccuracy` class | ~80 lines |

---

## Execution Order

1. Fix gate occupy in `fallback.py` (1 line)
2. Add spawn time tracking in `engine.py`
3. Add all new metrics in `recorder.py`
4. Update CLI output in `cli.py`
5. Add tests in `test_scenario.py`
6. Run tests: `uv run pytest tests/test_scenario.py -v`
7. Re-run SFO + JFK simulations to validate differentiation
8. Compare metrics between airports

---

## Verification

1. `uv run pytest tests/test_scenario.py tests/test_simulation.py -v` — all pass

2. **Re-run SFO:** `uv run python -m src.simulation.cli --config configs/simulation_sfo_1000.yaml --scenario scenarios/sfo_summer_thunderstorm.yaml`
   - Expect: `gates_used > 0`, `avg_capacity_hold_min > 0`, on-time lower than 84%

3. **Re-run JFK:** `uv run python -m src.simulation.cli --config configs/simulation_jfk_1000.yaml --scenario scenarios/jfk_winter_storm.yaml`
   - Expect: `cancellation_rate_pct ≈ 41%`, `avg_capacity_hold_min` much higher than SFO

4. **Compare SFO vs JFK** — metrics should now clearly differentiate scenario severity

---

## Expected Outcome

After these fixes, running the same scenario on different airports should produce meaningfully different metrics:

| Metric | SFO (mild storm) | JFK (severe winter) |
|--------|-------------------|---------------------|
| `on_time_pct` | ~70% | ~35% |
| `avg_capacity_hold_min` | ~5 min | ~45 min |
| `cancellation_rate_pct` | ~2% | ~40% |
| `gates_used` | 25-30 | 30-40 |
| `max_capacity_hold_min` | ~20 min | ~180+ min |

## Estimated Scope

- **Lines changed:** ~140 new code + ~80 tests
- **Risk:** Low — additive changes only, backward compatible with `schedule_delay_min`

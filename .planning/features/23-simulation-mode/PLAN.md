# Phase 23: Simulation Mode — Deterministic Accelerated Simulation Engine

## Goal

Create a standalone simulation mode that decouples the flight state machine from wall-clock time, runs at accelerated speed, and produces a complete structured event log for a full day of airport operations. Output is suitable for UI replay, metrics validation, and ML training data.

## Status: Plan — Not Started

---

## Context

The airport digital twin currently generates synthetic flights in real-time, tied to wall-clock time. There's no way to run a deterministic, accelerated simulation that produces a complete event log for a full day of operations. This plan creates a simulation mode that:
- Takes a config file (airport, number of arrivals/departures, duration, time acceleration)
- Runs the existing flight state machine at accelerated speed
- Records every event (phase transitions, gate events, positions, baggage, weather) into a structured output file
- Produces data suitable for UI replay and airport metrics validation

## Approach

Reuse the existing `fallback.py` state machine (`_update_flight_state`, `_create_new_flight`, `FlightPhase`, `FlightState`) and schedule generator but decouple them from wall-clock time by injecting a virtual clock. The simulation loops through time steps, scheduling new flights according to the hourly distribution, updating all flight states, and capturing events.

---

## Files to Create

### 1. `src/simulation/config.py` — Config model + loader

Pydantic model `SimulationConfig` with fields:
- `airport` (str, IATA code, default `"SFO"`)
- `arrivals` (int, number of arriving flights)
- `departures` (int, number of departing flights)
- `duration_hours` (float, default 24.0, 4.0 for debug)
- `time_step_seconds` (float, default 2.0 — simulated seconds per tick)
- `time_acceleration` (float, default 3600.0 — 1 real second = 1 sim hour by default)
- `start_time` (datetime, default midnight UTC today)
- `seed` (int, optional, for reproducibility)
- `debug` (bool, default False — if True, duration=4h, verbose logging)
- `output_file` (str, default `"simulation_output.json"`)

Load from YAML config file.

### 2. `src/simulation/engine.py` — Core simulation engine

`SimulationEngine` class:
- Owns a virtual clock (no `datetime.now()` — everything keyed to `sim_time`)
- Manages flight states dict (same `FlightState` dataclass from `fallback.py`)
- Uses a flight schedule pre-generated at init: distributes arrivals/departures across the duration using existing `_get_flights_per_hour()` distribution pattern
- Main loop `run()`: advances `sim_time` by `time_step_seconds` each tick, calls `_update_flight_state()` for all active flights, spawns new flights when their scheduled time arrives
- Captures events into lists: position snapshots (sampled every N ticks), phase transitions, gate events, baggage events, weather snapshots

**Reuses from `fallback.py`:**
- `FlightPhase`, `FlightState`, `_create_new_flight()`, `_update_flight_state()`
- `get_gates()`, separation constants, wake turbulence logic, all physics

**Reuses from `schedule_generator.py`:**
- `AIRLINES`, `AIRPORT_COORDINATES`, airline selection, aircraft selection

**Reuses from `baggage_generator.py`:**
- `generate_bags_for_flight()` — called when flight reaches PARKED phase

**Reuses from `weather_generator.py`:**
- Weather snapshots at hourly intervals

**Key difference:** Does NOT call `datetime.now()` — passes `sim_time` explicitly.

### 3. `src/simulation/recorder.py` — Event recorder + output writer

`SimulationRecorder` class:
- Collects events in categorized lists
- Event types:
  - `position_snapshots`: periodic position of all flights (every 30 sim-seconds)
  - `phase_transitions`: every phase change (approaching → landing → taxi → parked → pushback → taxi → takeoff → departing)
  - `gate_events`: assign/occupy/release for each gate
  - `baggage_events`: per-flight baggage generation at PARKED
  - `weather_snapshots`: hourly weather conditions
  - `schedule`: the full flight schedule with delays
- `write_output(path)`: writes JSON with all events + summary metrics

**Output JSON structure:**
```json
{
  "config": { ... },
  "summary": {
    "total_flights": 50,
    "arrivals": 25,
    "departures": 25,
    "avg_delay_min": 8.2,
    "gate_utilization_pct": 72.5,
    "avg_turnaround_min": 45.3,
    "on_time_pct": 85.0,
    "peak_simultaneous_flights": 12,
    "total_events": 4500
  },
  "schedule": [ ... ],
  "position_snapshots": [ ... ],
  "phase_transitions": [ ... ],
  "gate_events": [ ... ],
  "baggage_events": [ ... ],
  "weather_snapshots": [ ... ]
}
```

### 4. `src/simulation/__init__.py`

### 5. `src/simulation/cli.py` — CLI entry point

- `python -m src.simulation.cli --config config.yaml`
- Also supports direct args: `--airport SFO --arrivals 25 --departures 25 --debug`
- Progress bar showing sim time advancing (using print, no extra deps)
- Prints summary metrics at end

### 6. `configs/simulation_sfo_50.yaml` — First test config

```yaml
airport: SFO
arrivals: 25
departures: 25
duration_hours: 24
time_step_seconds: 2.0
seed: 42
output_file: simulation_output_sfo_50.json
```

### 7. `configs/simulation_sfo_50_debug.yaml` — Debug config (4h)

```yaml
airport: SFO
arrivals: 10
departures: 10
duration_hours: 4
time_step_seconds: 2.0
seed: 42
debug: true
output_file: simulation_output_sfo_50_debug.json
```

### 8. `tests/test_simulation.py` — Tests

---

## Key Design Decisions

1. **Decouple from wall-clock:** The simulation engine passes `sim_time` to all functions instead of calling `datetime.now()`. We'll refactor the reused functions to accept an optional `now` parameter, or create thin wrappers.

2. **Reuse, don't duplicate:** Import and call `_update_flight_state()`, `_create_new_flight()`, etc. directly from `fallback.py`. For functions that use `datetime.now()` internally (like `emit_phase_transition`), we'll provide a sim-aware wrapper in the engine that captures events with `sim_time` instead.

3. **Time acceleration:** The `run()` loop just increments `sim_time += time_step_seconds` each iteration. The `dt` passed to `_update_flight_state` is `time_step_seconds`. Real wall-clock doesn't matter — it runs as fast as the CPU allows. The `time_acceleration` config is informational (for the progress display).

4. **Flight scheduling:** Pre-generate the full schedule at init. Distribute arrivals/departures across hours using the existing `_get_flights_per_hour()` pattern, scaled to match the requested counts. Each flight gets a `scheduled_time`, and the engine spawns it when `sim_time` reaches that time.

5. **Position sampling:** Record positions every 30 sim-seconds (configurable). At 2s time steps, that's every 15 ticks. For 24h with 50 flights, this yields ~50 * (86400/30) = 144K position records — manageable in JSON.

6. **Gate management:** Initialize gates from airport config (OSM data for SFO). The engine manages gate occupancy as flights transition to/from PARKED.

---

## Modifications to Existing Files

- **`src/ingestion/fallback.py`:** Make key functions importable (they already are as module-level functions). No changes needed — we import `FlightPhase`, `FlightState`, `_update_flight_state`, `_create_new_flight`, `get_gates`, `set_airport_center`, etc. directly. The "private" underscore functions are fine to import within the same project.
- **`pyproject.toml`:** Add `pyyaml>=6.0` to dependencies (for YAML config loading).

---

## Execution Flow

1. **CLI** parses args / loads YAML config
2. **`Engine.__init__()`:**
   - Set airport center (lat/lon from `AIRPORT_COORDINATES`)
   - Load gates for airport
   - Generate flight schedule (spread arrivals/departures across duration)
   - Set random seed
3. **`Engine.run()`:**
   - `sim_time = start_time`
   - While `sim_time < start_time + duration`:
     - Spawn any flights whose `scheduled_time <= sim_time`
     - Update all active flight states (`dt = time_step_seconds`)
     - Record position snapshot (if sampling interval reached)
     - Capture phase transitions and gate events
     - Generate weather (if hour boundary crossed)
     - Advance `sim_time += time_step_seconds`
     - Print progress every ~1 sim-hour
4. **Post-simulation:**
   - Generate baggage data for all completed flights
   - Compute summary metrics
   - Write output JSON

---

## Verification

1. **Run debug simulation:** `python -m src.simulation.cli --config configs/simulation_sfo_50_debug.yaml`
   - Should complete in <10 seconds
   - Output file should have position snapshots, phase transitions, gate events

2. **Run full 24h simulation:** `python -m src.simulation.cli --config configs/simulation_sfo_50.yaml`
   - Should complete in <60 seconds
   - All 50 flights should complete their lifecycle

3. **Validate output:** Check that:
   - Every flight goes through expected phase sequence (approach → land → taxi → park → push → taxi → takeoff → depart for arrivals that also depart, or subset)
   - Gate utilization stays within gate count
   - No two flights at same gate simultaneously
   - Position coordinates are in realistic range for SFO
   - Delays are ~15% as configured

4. **Run tests:** `uv run pytest tests/test_simulation.py -v`

---

## Estimated Scope

- **New files:** 7 (config, engine, recorder, cli, __init__, 2 YAML configs) + tests
- **Modified files:** 1 (pyproject.toml for pyyaml)
- **Lines:** ~600-800 new code + ~200 tests
- **Risk:** Medium — refactoring `_update_flight_state()` to accept virtual time requires care to not break the real-time mode. Thin wrappers preferred over modifying function signatures.

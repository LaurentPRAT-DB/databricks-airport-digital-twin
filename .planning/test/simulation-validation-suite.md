---
status: backlog
area: simulation
related: [test, go-around, diversion, calibration, batch-sim]
---

# Simulation Validation Test Suite — download prod data & validate locally

## Context

Need a comprehensive local test suite that validates simulation output data generated on Databricks. The workflow is: (1) download simulation data from the UC Volume where batch jobs write results, (2) run pytest locally to validate flight behavior, phase transitions, go-arounds, diversions, routes, and seekability across all 33 airports.

Simulation data already exists on the UC Volume at:
`/Volumes/serverless_stable_3n0ihb_catalog/airport_digital_twin/simulation_data/cal_{iata}_normal_d1.json`
(~40-360 MB per airport, 33 airports × 4 configs = 132 files total)

## Approach

### Step 1: Download script — `scripts/download_simulation_data.py`

Downloads simulation JSON files from UC Volume to local `data/cache/simulations/`. Uses Databricks SDK (`WorkspaceClient.files.download`). Only downloads `*_normal_d1.json` files by default (one per airport, ~5 GB total). Accepts `--airport` filter for single-airport download.

```
Usage:
  uv run python scripts/download_simulation_data.py              # all airports, d1 only
  uv run python scripts/download_simulation_data.py --airport sfo  # single airport
  uv run python scripts/download_simulation_data.py --all        # all 4 configs per airport
```

Pattern for file selection: `cal_{iata}_normal_d1.json` (no timestamp = original batch run).

### Step 2: Test suite — `tests/test_simulation_validation.py`

Parametrized by airport. Reads downloaded JSON from `data/cache/simulations/`. Skips gracefully if data isn't downloaded (`pytest.skip("No data for {airport}")`).

#### Test categories:

**A. Structural integrity**
- JSON has all expected top-level keys: `config`, `summary`, `schedule`, `position_snapshots`, `phase_transitions`, `gate_events`, `scenario_events`
- `summary.total_flights == summary.arrivals + summary.departures`
- `position_snapshots` timestamps are monotonically non-decreasing
- All `icao24` values in snapshots match `sim\d{5}` pattern

**B. Phase transition validity**
- Every flight follows valid phase ordering: `enroute → approaching → landing → taxi_to_gate → parked → pushback → taxi_to_runway → takeoff → departed` (with go-around/diversion branches)
- No "impossible" transitions (e.g., `parked → approaching`, `takeoff → parked`)
- Every arrival ends in `parked` or `diverted`
- Every departure ends in `departed`
- Phase transition count per flight is within bounds (min 3, max ~15)

**C. Go-around behavior**
- Every `go_around` scenario_event has a matching phase_transition from `approaching` → `enroute`
- Go-around flight reappears in `approaching` phase within a reasonable time (5-20 min)
- Go-around count per flight ≤ 3 (max attempts before diversion)
- Go-arounds are seekable: flight is visible in position_snapshots at (event_time - 120s) ±30 frames, within 0.4° of airport center

**D. Diversion behavior**
- Every `diversion` scenario_event has a matching phase_transition to `diverted`/`departed` phase
- Diverted flights do NOT reappear later in `approaching`/`landing` phases
- Diversions typically follow multiple go-arounds (validate attempt count)

**E. Flight lifecycle completeness**
- Scheduled arrivals that are `spawned=true` have at least 1 position snapshot
- Scheduled departures that are `spawned=true` have at least 1 position snapshot
- No "orphan" flights: every `icao24` in snapshots maps to a schedule entry
- Gate events (occupy/vacate) are paired per flight

**F. Spatial/physics validation**
- Landing altitude decreases monotonically (within noise tolerance)
- Takeoff altitude increases after liftoff
- Parked flights have velocity == 0 and altitude == 0
- Taxi velocity < 30 kts (< 15 m/s)
- No position jumps > 0.1° between consecutive snapshots for same flight (teleportation)
- Flights within 0.4° of airport center (no runaway trajectories except during climb/cruise)

**G. Summary metrics sanity**
- `on_time_pct` between 50-100%
- `avg_turnaround_min` between 20-120 min
- `peak_simultaneous_flights` > 5
- `total_go_arounds` ≥ 0 (weather configs should have > 0)
- `cancellation_rate_pct` < 50%

**H. Weather scenario validation** (for `*_weather.json` if downloaded)
- Weather configs produce more go-arounds than normal configs
- Cancellation count > 0 when severe weather present
- Capacity hold increases during weather events

### Step 3: Conftest fixture — `tests/conftest_simulation_data.py`

Shared fixtures:
- `simulation_data(airport)` — loads and caches parsed JSON (lazy, per-airport)
- `AIRPORTS` — list of all 33 airports for parametrize
- `available_airports()` — only airports with downloaded data

### Files to create/modify:

| File | Action |
|------|--------|
| `scripts/download_simulation_data.py` | CREATE — download script using Databricks SDK |
| `tests/test_simulation_validation.py` | CREATE — comprehensive validation suite |
| `tests/conftest.py` | MODIFY — add `simulation_data` fixture + `AIRPORTS` constant |
| `data/cache/simulations/.gitkeep` | CREATE — empty dir for downloaded data |
| `.gitignore` | MODIFY — add `data/cache/simulations/*.json` |

### Key files to reference:

- `src/simulation/recorder.py` — JSON output format (write_output method, line 263)
- `src/simulation/engine.py` — phase transition logic, go-around/diversion recording
- `app/backend/services/demo_simulation_service.py` — SDK download pattern (line 51-68)
- `configs/calibration_batch/simulation_sfo_normal_d1.yaml` — config format
- `resources/simulation_batch_job.yml` — full airport list (33 airports in 3 batches)

### Airport list (from batch configs):

AMS, ATL, BOS, CDG, CLT, DEN, DFW, DTW, DXB, EWR, FRA, GRU, HKG, IAH, ICN, JFK, JNB, LAS, LAX, LHR, MCO, MIA, MSP, NRT, ORD, PDX, PHL, PHX, SAN, SEA, SFO, SIN, SYD

## Verification

1. Download data: `uv run python scripts/download_simulation_data.py --airport sfo`
2. Run tests: `uv run pytest tests/test_simulation_validation.py -v --tb=short`
3. Full run (all downloaded airports): `uv run pytest tests/test_simulation_validation.py -v`
4. Expected: all tests pass for well-formed simulations; failures indicate real bugs in the engine

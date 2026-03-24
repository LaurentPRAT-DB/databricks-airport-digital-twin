# Plan: Simulation Skill + Video Capture + Diagnostic Logging + Domain Expert Tests

## Context

The simulation codebase has grown sophisticated (flight state machine, STARs/SIDs, go-arounds, passenger flow, BHS) but lacks a unified workflow for running, analyzing, and auto-correcting simulation issues. Three gaps:
1. No Claude Code skill to orchestrate sim runs with automated analysis
2. No structured diagnostic logging for machine-readable anomaly detection
3. Tests are implementation-driven, not domain-expert-driven — missing the "what would a real ATC controller flag?" perspective

Existing infrastructure to build on:
- Video capture already exists: `src/simulation/video_renderer.py` (Playwright+ffmpeg), `scripts/capture_video.js`, `src/simulation/video_cli.py`
- Simulation CLI already exists: `src/simulation/cli.py` with YAML configs
- `SimulationRecorder` already captures positions, phase transitions, gate events, baggage, weather, scenarios
- Validate skill already exists at `.claude/commands/validate.md` (20 validation tests against real data)
- Test infrastructure: module-scoped sim fixture in `test_trajectory_coherence.py` runs 4-airport parametrized sims

## Deliverables

### 1. `/simulate` Skill — `.claude/commands/simulate.md`

A Claude Code slash command that orchestrates the full simulation lifecycle.

The skill instructs Claude to:
1. Run a simulation via `uv run python -m src.simulation.cli` with `--debug` flag (enables diagnostics)
2. Load and parse the diagnostic JSON output
3. Analyze for anomalies: excessive go-arounds (>5%), separation losses, unrealistic speeds, gate conflicts
4. Present findings with root-cause mapping to code locations in `fallback.py`
5. If user wants fixes: apply targeted edits, re-run tests
6. If user wants video: run `node scripts/capture_video.js` or `python -m src.simulation.video_cli` on the output
7. If user wants expert review: run `uv run pytest tests/test_expert_reviews.py -v`

The skill also documents the diagnostic-to-code mapping:
- `GO_AROUND` events → `_execute_go_around()` in `fallback.py` ~line 3230
- `SEPARATION_LOSS` → `_check_approach_separation()` in `fallback.py`
- `PHASE_TRANSITION` anomalies → `_update_flight_state()` APPROACHING/LANDING handlers
- `TAXI_VIOLATION` → taxi speed logic in `fallback.py`
- `RUNWAY_CONFLICT` → `_is_runway_clear()` / `_occupy_runway()` in `fallback.py`

### 2. Diagnostic Event Logger — `src/simulation/diagnostics.py`

A structured event logger captured alongside the existing `SimulationRecorder`. Not replacing Python logging — an additional machine-readable data layer.

Events captured:

| Event | Key Fields | Emitted From |
|---|---|---|
| `PHASE_TRANSITION` | icao24, from, to, alt, vel, reason | `fallback.py` `emit_phase_transition()` |
| `GO_AROUND` | icao24, reason, alt, count | `fallback.py` `_execute_go_around()` |
| `SEPARATION_LOSS` | icao24, leader, distance_nm | `fallback.py` `_check_approach_separation()` |
| `RUNWAY_CONFLICT` | runway, occupant, requester | `fallback.py` `_is_runway_clear()` |
| `APPROACH_UNSTABILIZED` | icao24, speed, vref, sink_rate | `fallback.py` APPROACHING handler |
| `TAXI_SPEED_VIOLATION` | icao24, speed, limit | `fallback.py` TAXI handler |
| `GATE_CONFLICT` | gate, occupant, requester | `fallback.py` gate management |
| `DEPARTURE_HOLD` | icao24, reason, hold_seconds | `engine.py` capacity hold |
| `TICK_STATS` | tick, active_flights, elapsed_ms | `engine.py` `_tick()` |

Class structure:
```python
class DiagnosticLogger:
    events: list[dict]
    enabled: bool

    def log(self, event_type: str, sim_time: datetime, **fields) -> None
    def summary(self) -> dict  # counts by type, top offenders, anomaly flags
    def write(self, path: str) -> None  # JSON output
```

Module-level `_diagnostics` reference (same pattern as `_flight_states`, `_gate_states`).

### 3. Domain Expert Tests — `tests/test_expert_reviews.py`

8 specialist personas, each a test class. Uses the same module-scoped 4-airport sim fixture as `test_trajectory_coherence.py`.

| # | Expert Persona | Tests | What They Validate |
|---|---|---|---|
| 1 | ATC Approach Controller | 5 | 3nm separation, decision height, go-around climb, runway occupancy, sequencing |
| 2 | Line Pilot (Type-Rated) | 5 | Vref per type, descent rate, FL100 speed limit, takeoff acceleration, climb rate |
| 3 | Airport Ops Manager | 4 | Gate conflicts, turnaround times, pushback sequence, peak utilization |
| 4 | Ground Movement Controller | 4 | Taxi speed, runway hold, departure queue, ground-air transition |
| 5 | Airline Dispatcher | 3 | OTP percentage, delay propagation, schedule coverage |
| 6 | Passenger Flow Analyst | 3 | Checkpoint throughput, dwell times, boarding timing |
| 7 | BHS Engineer | 3 | Belt throughput, jam rate, transfer connection |
| 8 | Safety/Compliance Auditor | 5 | ICAO separation minima, missed approach compliance, runway incursion, speed limits, phase legality |

Each test class has:
- `_EXPERTISE` docstring explaining the specialist's perspective
- Regulatory references in test docstrings (e.g., "ICAO Doc 4444 §8.7.3.2")
- Realistic thresholds from aviation domain knowledge
- Uses `sim` and `traces` fixtures (same as trajectory coherence tests)

Total: ~32 new tests across 8 expert personas.

### 4. Integration: Config + Engine + Fallback Changes

**`src/simulation/config.py`** — add field:
```python
diagnostics: bool = Field(default=True, description="Enable diagnostic event logging")
```

**`src/simulation/engine.py`** — wire diagnostics:
- Create `DiagnosticLogger` in `__init__` if `config.diagnostics`
- Set module-level `_diagnostics` reference for `fallback.py`
- Emit `TICK_STATS` at each tick, `DEPARTURE_HOLD` at capacity holds
- Write diagnostics JSON alongside simulation output in `run()`

**`src/ingestion/fallback.py`** — emit events (5-10 call sites):
- `emit_phase_transition()` → also emit diagnostic `PHASE_TRANSITION`
- `_execute_go_around()` → emit `GO_AROUND`
- Separation check → emit `SEPARATION_LOSS` when below threshold
- Taxi speed violations → emit `TAXI_SPEED_VIOLATION`
- Gate conflicts → emit `GATE_CONFLICT`

## Files

| Action | File | ~Lines |
|---|---|---|
| Create | `.claude/commands/simulate.md` | 150 |
| Create | `src/simulation/diagnostics.py` | 150 |
| Create | `tests/test_expert_reviews.py` | 500 |
| Modify | `src/simulation/config.py` | +3 |
| Modify | `src/simulation/engine.py` | +30 |
| Modify | `src/ingestion/fallback.py` | +20 |

## Implementation Order

1. `src/simulation/diagnostics.py` — standalone, no deps
2. `src/simulation/config.py` — add diagnostics flag
3. `src/simulation/engine.py` — wire up logger, emit tick stats
4. `src/ingestion/fallback.py` — emit events at key transitions
5. `tests/test_expert_reviews.py` — domain expert test suite
6. `.claude/commands/simulate.md` — the skill tying it all together

## Verification

```bash
# 1. Run diagnostic-enabled simulation
uv run python -m src.simulation.cli --airport SFO --arrivals 25 --departures 25 --debug

# 2. Verify diagnostics JSON was written
cat simulation_output_diagnostics.json | python -m json.tool | head -50

# 3. Run domain expert tests
uv run pytest tests/test_expert_reviews.py -v --tb=short

# 4. Regression check
uv run pytest tests/test_trajectory_coherence.py tests/test_synthetic_data_requirements.py -q

# 5. Test the skill
/simulate SFO --expert-review
```

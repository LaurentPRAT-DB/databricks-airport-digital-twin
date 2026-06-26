# Airport Digital Twin — Simulation Orchestrator

You are orchestrating a full simulation lifecycle for the airport digital twin.
Parse the user's request for airport code, flight counts, and options, then
execute the appropriate workflow.

## Arguments

Parse from `$ARGUMENTS`:
- Airport IATA code (default: SFO)
- `--arrivals N` / `--departures N` (default: 25 each)
- `--scenario <path>` (optional YAML scenario file)
- `--seed N` (optional random seed for reproducibility)
- `--video` — capture replay video after simulation
- `--expert-review` — run domain expert tests
- `--debug` — enable debug mode (4h max, verbose logging)

## Workflow

### Step 1: Run the simulation

```bash
uv run python -m src.simulation.cli \
  --airport <AIRPORT> \
  --arrivals <N> --departures <N> \
  --debug \
  --seed <SEED> \
  --output simulation_output.json
```

Add `--scenario <path>` if specified.

### Step 2: Load and analyze diagnostics

Read `simulation_output_diagnostics.json` and analyze for anomalies:

**Anomaly thresholds:**
- Go-around rate > 5% of approaches → flag
- Any SEPARATION_LOSS events → flag with aircraft pairs
- RUNWAY_CONFLICT events → flag (should be zero)
- GATE_CONFLICT > 3 events → flag
- Average tick time > 5ms → performance warning

Present findings as a table:
| Metric | Value | Status |
|--------|-------|--------|
| Go-around rate | X% | OK/WARN/FAIL |
| Separation losses | N | OK/WARN/FAIL |
| ... | ... | ... |

### Step 3: Root-cause mapping

If anomalies are found, map them to code locations:

| Anomaly | Code Location | Function |
|---------|--------------|----------|
| GO_AROUND | `src/ingestion/fallback.py` ~line 3231 | `_execute_go_around()` |
| SEPARATION_LOSS | `src/ingestion/fallback.py` ~line 2079 | `_check_approach_separation()` |
| PHASE_TRANSITION | `src/ingestion/fallback.py` ~line 3224+ | `_update_flight_state()` APPROACHING/LANDING handlers |
| TAXI_SPEED_VIOLATION | `src/ingestion/fallback.py` ~line 656 | taxi speed constants + `_taxi_speed_factor()` |
| RUNWAY_CONFLICT | `src/ingestion/fallback.py` ~line 2111 | `_is_runway_clear()` / `_occupy_runway()` |
| GATE_CONFLICT | `src/ingestion/fallback.py` ~line 2135 | `_find_available_gate()` |
| DEPARTURE_HOLD | `src/simulation/engine.py` | `_spawn_scheduled_flights()` capacity check |

### Step 4: Offer next actions

Ask the user what they'd like to do:

1. **Fix issues** — Apply targeted code edits to address the anomalies, then re-run
   the simulation to verify the fix.

2. **Capture video** — Run the video capture pipeline:
   ```bash
   uv run python -m src.simulation.video_cli --input simulation_output.json
   ```
   Or if the frontend dev server is running:
   ```bash
   node scripts/capture_video.js
   ```

3. **Run expert review** — Execute the domain expert test suite:
   ```bash
   uv run pytest tests/test_expert_reviews.py -v --tb=short
   ```

4. **Run regression** — Verify no existing tests broke:
   ```bash
   uv run pytest tests/test_trajectory_coherence.py tests/test_synthetic_data_requirements.py -q
   ```

5. **Compare airports** — Run the same simulation for multiple airports and
   compare metrics side-by-side.

### Auto-actions (when flags are passed)

If `--video` was specified, automatically run video capture after analysis.
If `--expert-review` was specified, automatically run expert tests after analysis.

## Output format

Always end with a summary block:

```
Simulation: <AIRPORT> | <arrivals>A/<departures>D | <duration>h
Diagnostics: <N> events | <anomaly_count> anomalies
Expert tests: <passed>/<total> passed (if run)
Video: <path> (if captured)
```

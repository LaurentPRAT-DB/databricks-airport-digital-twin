# Close Recorded Data Parity Gap — Derive scenario_events + Richer Summary

## Context

The recorded data enrichment job (`databricks/notebooks/enrich_opensky_events.py`) populates phase_transitions, gate_events, and enriched snapshots in Delta tables. But `_build_recording_response_from_enriched()` in `opensky.py:781-782` hardcodes `scenario_events: []` and returns a minimal 3-field summary (total_flights, data_source, scenario_name), even though enough data exists to derive both.

**Goal:** Derive scenario_events from enriched data and compute richer summary KPIs — no frontend changes needed.

## What the frontend expects

**scenario_events** — `{time, event_type, description, ...}`:
- Known event types with colors: weather, runway, ground, traffic, capacity, cancellation, go_around, diversion (`SimulationControls.tsx:150-159`)
- Used by: PlaybackBar timeline markers + SimulationReport events table

**summary KPIs** (`SimulationReport.tsx:302-310`):
- `on_time_pct`, `schedule_delay_min`, `total_cancellations`, `total_go_arounds`, `total_diversions`, `peak_simultaneous_flights`, `avg_capacity_hold_min`, `total_flights`
- Missing values render as `--` (already handled)

## Implementation

### 1. `_derive_scenario_events_from_enriched()` — new function

Derive scenario_events from phase_transitions and gate_events. Only derive what's observable from ADS-B:

| Source data | Derived event_type | Detection logic |
|---|---|---|
| phase_transitions | go_around | from_phase in (approaching, landing) -> to_phase in (enroute, departing, takeoff) = missed approach |
| gate_events | ground | gate assign/occupy/release events -> "Gate B12 assigned to UAL123" |

Not derivable (no data source): weather, runway, cancellation, diversion, traffic. These stay empty — honest representation.

### 2. `_compute_recording_summary()` — new function

Compute summary KPIs following patterns from `src/simulation/recorder.py:compute_summary()` (line 133-253):

| KPI | Source | Value |
|---|---|---|
| total_flights | `len(unique_aircraft)` | Computed |
| arrivals / departures | schedule flight_type counts | Computed |
| total_go_arounds | count from derived scenario_events | Computed |
| total_diversions | 0 (not detectable) | Hardcoded |
| total_cancellations | 0 (N/A) | Hardcoded |
| peak_simultaneous_flights | max frame size | Computed |
| gate_utilization_gates_used | unique gates from gate_events | Computed |
| on_time_pct | None (no scheduled vs actual comparison possible) | Renders as `--` |
| schedule_delay_min | None | Renders as `--` |
| avg_capacity_hold_min | None | Renders as `--` |

### 3. Wire into `_build_recording_response_from_enriched()` (line 768-787)

Replace:
```python
"weather_snapshots": [],
"scenario_events": [],
```
With:
```python
"weather_snapshots": [],
"scenario_events": derived_events,
```

Replace the minimal summary dict with the output of `_compute_recording_summary()`.

## File to modify

- `app/backend/api/opensky.py` — add 2 functions, update response builder (~60 lines)

## Verification

1. `uv run pytest tests/test_opensky_router.py -v -k recording` — existing recording tests pass
2. `uv run pytest tests/ -v --timeout=60` — no regressions
3. Live API: curl KSFO recording -> verify scenario_events non-empty, summary has peak_simultaneous_flights, total_go_arounds, etc.
4. Deploy + E2E: `uv run python scripts/test_ui_e2e.py` — PlaybackBar shows event markers in recorded mode

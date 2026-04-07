# Plan: Test Single-Flight Tracking Features

**Status:** Backlog
**Date added:** 2026-04-07
**Depends on:** Single-Flight Recording & Follow Mode (Done)
**Scope:** Unit tests + video rendering tests + JSONL→simulation converter + manual verification

---

## Context

We need to verify the 4 single-flight features (camera follow, isolation, CSV export, origin/dest) work correctly. Two test scenarios:

1. Real flight from EDDF — 1604 JSONL files in `data/opensky_raw/synced/`
2. Simulated flight from KSFO — existing `simulation_output_sfo_100.json` or run fresh sim

## Problem

The video renderer (`video_cli.py`) requires simulation JSON format (`{config, position_snapshots, ...}`), but EDDF data is raw OpenSky JSONL. We need a converter.

## Tasks

### Task 1: Run Existing Tests (Baseline)

Verify nothing is broken:

```bash
uv run pytest tests/ -v -x --timeout=30
cd app/frontend && npm test -- --run
```

### Task 2: Add Unit Tests for the 4 Features

Frontend tests needed (none exist today for these features):

- `app/frontend/src/hooks/useSimulationReplay.test.ts` — add test for `getFlightLog(icao24)` returning all frames for a specific flight
- `app/frontend/src/context/FlightContext.test.tsx` — add test for `isolateSelected` state toggle
- `app/frontend/src/components/FlightDetail/FlightDetail.test.tsx` — add test for "Download Flight Log" button presence and CSV generation
- `app/frontend/src/components/Map/AirportMap.test.tsx` — add test for `FlightFollower` component rendering

### Task 3: KSFO Simulation — Video with Flight Tracking

Use existing simulation output with `--track-flight`:

```bash
# Pick a flight from the simulation
python -c "
import json
data = json.load(open('simulation_output_sfo_100.json'))
flights = set(s['icao24'] for s in data['position_snapshots'][:1000])
for f in list(flights)[:5]: print(f)
"

# Render tracked flight video (short window to test)
uv run python -m src.simulation.video_cli \
    --simulation-file simulation_output_sfo_100.json \
    --output video_output/ksfo_tracked_flight.mp4 \
    --track-flight <icao24> \
    --start-hour 6 --end-hour 7 \
    --fps 15 --speed 2 -y
```

### Task 4: EDDF Real Data — Convert JSONL to Simulation JSON

Write a small script `scripts/opensky_to_sim_json.py` that:

1. Reads all EDDF JSONL files from `data/opensky_raw/synced/`
2. Converts to simulation JSON format: `{config: {airport: "EDDF", ...}, position_snapshots: [...]}`
3. Maps OpenSky fields → simulation snapshot fields (icao24, callsign, lat, lon, altitude, velocity m/s→kts, heading, phase="unknown", on_ground, aircraft_type)
4. Outputs `simulation_output_eddf_opensky.json`

Then render with flight tracking:

```bash
uv run python scripts/opensky_to_sim_json.py

# Pick a real EDDF flight (e.g., DLH572 / 3c4b26 from the sample data)
uv run python -m src.simulation.video_cli \
    --simulation-file simulation_output_eddf_opensky.json \
    --output video_output/eddf_tracked_flight.mp4 \
    --track-flight 3c4b26 \
    --fps 15 --speed 2 -y
```

### Task 5: Manual Dev Server Test

Start dev server, load a simulation replay, and verify each feature interactively:

```bash
./dev.sh
# Open http://localhost:5173
# 1. Load simulation replay → select a flight → verify map pans to follow it
# 2. Click "Isolate" toggle → verify other flights dim
# 3. Click "Download Flight Log" → verify CSV downloads with all columns
# 4. Check FlightDetail panel shows origin/destination
```

## Key Files

| File | Role |
|------|------|
| `src/simulation/video_cli.py` | CLI with `--track-flight` flag |
| `src/simulation/video_renderer.py:389-399` | Playwright `selectFlight()` injection |
| `app/frontend/src/components/Map/AirportMap.tsx:243-281` | `FlightFollower` component |
| `app/frontend/src/components/FlightDetail/FlightDetail.tsx:210,236-264` | Isolate toggle + CSV export |
| `data/opensky_raw/synced/EDDF_*.jsonl` | 1604 real EDDF snapshots |
| `simulation_output_sfo_100.json` | Existing KSFO simulation |

## Verification

- All existing tests pass (backend + frontend)
- New unit tests pass for the 4 features
- KSFO video renders with flight tracking visible
- EDDF converter produces valid simulation JSON
- EDDF video renders with real flight tracking

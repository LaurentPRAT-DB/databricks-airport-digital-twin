---
title: "Live Gate Proximity Assignment + Gate Departure Recording"
status: backlog
area: opensky
priority: medium
related:
  - src/inference/opensky_events.py
  - app/backend/services/opensky_service.py
  - app/backend/api/websocket.py
  - app/backend/services/opensky_collector.py
---

# Plan: Live Gate Proximity Assignment + Gate Departure Recording

## Context

Live OpenSky data never assigns gates — `_state_to_flight()` always sets `assigned_gate: None`.
Aircraft visibly parked at a gate (e.g., right next to F61 at LSGG) show no gate in the UI.
The recorded data path already has gate matching via `OpenSkyEventInferrer.find_nearest_gate()`,
but the live WebSocket path bypasses it entirely.

Additionally, the `opensky_events.py` inferrer has the same stale phase thresholds we just fixed
in `opensky_service.py` (shallow glideslope classified as "enroute").

The user also wants: when a parked aircraft starts moving (taxi-out), record the gate
departure time.

## Changes

### 1. Add `assign_nearest_gates()` utility to opensky_service.py

Reusable function that takes a list of flight dicts + gate list from config, and assigns the
nearest gate to on-ground stationary aircraft using haversine distance.

- Reuse `haversine_m` from `src/inference/opensky_events.py` (import it)
- Threshold: `GATE_MATCH_RADIUS_M = 200.0` (same as inferrer)
- Stationary: velocity < 5 kts (≈ 2.5 m/s — matches `STATIONARY_VELOCITY_MS = 2.0`)
- Mutates `assigned_gate` field in-place on matching flights

File: `app/backend/services/opensky_service.py`

### 2. Call it from `_fetch_opensky_flights()` in WebSocket

After fetching raw flights from OpenSky, load gates from `config_service.get_config()["gates"]`
and call `assign_nearest_gates()`.

File: `app/backend/api/websocket.py`

### 3. Call it from `_persist_snapshots()` in collector

Same logic for the background OpenSky collector that persists to Lakebase.

File: `app/backend/services/opensky_collector.py`

### 4. Track gate departures with stateful tracker in opensky_service.py

Add a lightweight `LiveGateTracker` class (per-airport, singleton-like) that:
- Remembers `icao24 → (gate, parked_since_timestamp)` for currently-parked aircraft
- On each live poll: if an aircraft was parked at a gate and is now moving (velocity > 5 kts
  or `on_ground=False`), emit a "release" gate event and record the departure time
- Persist gate events (assign + release) to Lakebase via `insert_gate_events()`

This also means: when a new aircraft is matched to a gate, emit an "assign"/"occupy" event.

File: `app/backend/services/opensky_service.py` (new class `LiveGateTracker`)
Called from: `app/backend/api/websocket.py` (`_fetch_opensky_flights`) and
`app/backend/services/opensky_collector.py`

### 5. Fix phase thresholds in opensky_events.py

Align the airborne phase classification (lines 256-265) with the updated
`determine_flight_phase`:
- Add: `altitude_ft < 2000` and `vrate_ftmin < -50` → "landing"
- Add: `altitude_ft < 5000` and `vrate_ftmin < -50` → "approaching"

File: `src/inference/opensky_events.py`

## Key Files

| File | Change |
|------|--------|
| `app/backend/services/opensky_service.py` | Add `assign_nearest_gates()` + `LiveGateTracker` class |
| `app/backend/api/websocket.py` | Call gate assignment + tracker in `_fetch_opensky_flights()` |
| `app/backend/services/opensky_collector.py` | Call gate assignment in `_persist_snapshots()` |
| `src/inference/opensky_events.py` | Fix phase thresholds (lines 256-265) |

## Reused Code

- `haversine_m()` from `src/inference/opensky_events.py:33`
- `GATE_MATCH_RADIUS_M = 200.0` from `src/inference/opensky_events.py:26`
- `insert_gate_events()` from `app/backend/services/lakebase_service.py:1729`
- Gate structure: `{"ref": "F61", "geo": {"latitude": ..., "longitude": ...}}` from OSM converter

## Verification

1. `uv run pytest tests/ -k "phase or gate or opensky" -v` — all existing tests pass
2. `uv run pytest tests/ -v` — full suite regression check
3. Deploy to Databricks and test with live data at LSGG:
   - Aircraft parked near gates should show gate assignment in Flight Details panel
   - Aircraft departing gate should emit "release" event visible in Data Ops
   - Aircraft on short final should show "landing" not "enroute"

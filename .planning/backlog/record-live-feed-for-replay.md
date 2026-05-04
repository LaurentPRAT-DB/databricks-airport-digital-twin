---
title: "Record Live Feed for Replay"
status: backlog
area: frontend, infrastructure
priority: medium
related:
  - ../features/opensky-recordings
---

# Feature: Record Live Feed for Replay

## Context

When live mode is active, the user wants a Record button that captures all incoming OpenSky flight data so it can be replayed later (like existing recorded sessions). The existing collection infrastructure (`scripts/opensky_collector.py`) is a standalone CLI script that saves JSONL files to `data/opensky_raw/`, then uploads to Databricks. Since Databricks Cloud IPs are sometimes blocked by OpenSky, recording happens from the local machine via the app's live feed — not from Databricks.

The app already has full replay infrastructure:
- `GET /api/opensky/recordings` lists sessions from Delta tables
- `GET /api/opensky/recordings/{airport}/{date}` loads a session for replay
- `useSimulationReplay.ts` → `loadRecording()` plays them back frame-by-frame
- `scripts/opensky_collector.py` shows the JSONL format per frame

## Goal

Add an in-app record button that saves live snapshots to local JSONL files (same format as `opensky_collector.py`), one file per session, replayable via the existing Recorded mode.

## Filename Convention

```
data/opensky_raw/KSFO_2026-05-03T20-05-30Z.jsonl
```

Pattern: `{ICAO}_{ISO-timestamp-start}.jsonl` (matching existing collector convention at `scripts/opensky_collector.py:367`). Each line is one aircraft state dict at one collection time.

## Plan

### 1. Backend: Add `_LiveRecorder` + 3 endpoints (`app/backend/api/opensky.py`)

Add a singleton `_LiveRecorder` class that manages recording state:
- `start(airport_icao, lat, lon)` — creates output file, starts asyncio background task polling every 10s via `opensky_service.fetch_flights()`
- `stop()` — cancels task, returns stats (filename, frames, duration)
- `status()` — returns current recording state

Each poll appends all visible aircraft as JSONL lines using the same field schema as `scripts/opensky_collector.py:state_to_record` (`icao24`, `callsign`, `lat`, `lon`, `baro_altitude`, `velocity`, etc + `collection_time` + `airport_icao`).

Three new routes:
- `POST /api/opensky/record/start` — starts recording for current airport
- `POST /api/opensky/record/stop` — stops and returns stats
- `GET /api/opensky/record/status` — poll-friendly status check

### 2. Backend: Local JSONL replay (`app/backend/api/opensky.py`)

Add local file support so recordings can be replayed without uploading to Databricks:

- Extend `GET /api/opensky/recordings` — also scan `data/opensky_raw/*.jsonl`, parse filename for airport/date, count lines, include with `data_source: "local"`
- Add `GET /api/opensky/recordings/local/{filename}` — reads JSONL, groups by `collection_time` into frames, applies `determine_flight_phase()`, returns the same response shape as the Delta-based `_build_recording_response_from_enriched()` (frames, frame_timestamps, summary, schedule, etc.)

### 3. Frontend: Record button in LiveBar (`SimulationControls.tsx`)

Add to `LiveBar` component:
- Red circle record button, positioned between the Live indicator and flight count
- When recording: pulsing red dot + elapsed time counter + frame count
- Click toggles start/stop via fetch to the new endpoints
- On stop: brief inline confirmation showing filename + frame count

State managed locally in `LiveBar` (no context needed — recording is a transient action).

### 4. Frontend: Show local recordings in picker

The recording picker in `SimulationControls.tsx` (Recorded mode) currently shows Delta-based recordings. The extended `/api/opensky/recordings` response will include local files automatically — they'll appear in the list with a "Local" badge vs "Cloud" badge.

In `useSimulationReplay.ts` → `loadRecording()`: detect `data_source: "local"` and call the new `/api/opensky/recordings/local/{filename}` endpoint instead of the Delta path.

## Files to Modify

| File | Change |
|------|--------|
| `app/backend/api/opensky.py` | Add `_LiveRecorder` class, 3 record endpoints, local JSONL list + replay endpoint |
| `app/frontend/src/components/SimulationControls/SimulationControls.tsx` | Add record button + state to LiveBar |
| `app/frontend/src/hooks/useSimulationReplay.ts` | Handle local recordings in `loadRecording()` |

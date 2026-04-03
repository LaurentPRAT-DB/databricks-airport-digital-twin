# Plan: OpenSky Recorded Data Replay — Backend API + Frontend UI

**Status:** Backlog
**Date added:** 2026-04-03
**Depends on:** OpenSky Local Collector + Lakehouse Ingestion Pipeline
**Scope:** Backend replay API + Frontend "Recorded" data mode + recording picker UI

---

## Context

We collected real OpenSky ADS-B data locally (JSONL files) and need to:

1. Upload it to a UC Volume and load into the `opensky_states_raw` Delta table
2. Add a backend API that reads recorded data from the Delta table and serves it as time-grouped frames (same format as simulation replay)
3. Add a "Recorded" data mode in the UI with a picker showing available recordings (airport, date range, aircraft count) and playback using the existing simulation replay engine

The existing simulation replay infrastructure (`useSimulationReplay` hook, `PlaybackBar`, `FilePicker`) does most of the heavy lifting. The recorded OpenSky data just needs to be served in the same frame-based format.

## Architecture

```
Delta: opensky_states_raw  →  /api/opensky/recordings (list)
                           →  /api/opensky/recordings/{airport}/{date} (frame data)
                           ↓
                    Frontend: "Recorded" data mode
                    (reuses simulation replay engine)
```

## Step 1: Upload Collected Data to Databricks

Before code changes — verify pipeline works:

```bash
# Deploy volume
databricks bundle deploy --target dev

# Upload collected JSONL files
databricks fs cp data/opensky_raw/ dbfs:/Volumes/serverless_stable_3n0ihb_catalog/airport_digital_twin/opensky_raw/ --recursive

# Run ingestion job
databricks bundle run opensky_ingestion --target dev
```

## Step 2: Backend — Recorded Data API

### File: `app/backend/api/opensky.py` (modify existing)

Add two new endpoints:

#### `GET /api/opensky/recordings`

Lists available recordings from `opensky_states_raw` Delta table, grouped by airport + date.

```json
{
  "recordings": [
    {
      "airport_icao": "LSGG",
      "date": "2026-04-03",
      "aircraft_count": 45,
      "state_count": 1260,
      "first_seen": "2026-04-03T10:29:15Z",
      "last_seen": "2026-04-03T10:45:30Z",
      "duration_minutes": 16,
      "data_source": "opensky_live"
    }
  ]
}
```

Query:

```sql
SELECT airport_icao, collection_date, COUNT(DISTINCT icao24), COUNT(*),
       MIN(collection_time), MAX(collection_time)
FROM opensky_states_raw
GROUP BY 1, 2
ORDER BY 2 DESC
```

Uses `DeltaService._get_connection()` for SQL access (existing pattern from `data_ops.py`).

#### `GET /api/opensky/recordings/{airport_icao}/{date}`

Returns frame-based data in the same format as `/api/simulation/data/` so the frontend replay engine works unchanged:

```json
{
  "config": {"airport": "LSGG", "source": "opensky_recorded"},
  "summary": {"total_flights": 45, "data_source": "opensky_live"},
  "schedule": [],
  "frames": {"2026-04-03T10:29:15Z": ["...flight_dicts..."], "...": "..."},
  "frame_timestamps": ["2026-04-03T10:29:15Z", "..."],
  "frame_count": 42,
  "phase_transitions": [],
  "gate_events": [],
  "scenario_events": []
}
```

Query:

```sql
SELECT * FROM opensky_states_raw
WHERE airport_icao = ? AND collection_date = ?
ORDER BY collection_time, icao24
```

Each row gets converted to the PositionSnapshot format (same as simulation):

- `baro_altitude` meters → feet, `velocity` m/s → knots (same conversion as `opensky_service.py`)
- `_determine_flight_phase()` reused from `opensky_service.py`
- Grouped by `collection_time` into frames

## Step 3: Frontend — "Recorded" Data Mode

### `app/frontend/src/context/FlightContext.tsx`

- Add `'recorded'` to DataMode: `type DataMode = 'simulation' | 'live' | 'recorded'`
- Add `'opensky_recorded'` to dataSource union

### `app/frontend/src/hooks/useSimulationReplay.ts`

- Add `loadRecording(airport: string, date: string)` method that fetches from `/api/opensky/recordings/{airport}/{date}` — the response is already in simulation frame format, so it feeds directly into the existing `simData` state
- Add `RecordingFile` type similar to `SimulationFile`
- Add `availableRecordings` state + `fetchRecordings()` method

### `app/frontend/src/components/SimulationControls/SimulationControls.tsx`

- Extend `DataModeToggle` with a third "Recorded" button (amber/orange color to distinguish from Simulation=indigo and Live=emerald)
- Add `RecordingPicker` component (similar to `FilePicker`) that shows recordings with:
  - Airport name, date, duration
  - Number of unique aircraft tracked
  - Clear description: "Real ADS-B data recorded from OpenSky Network"
  - Each row shows: `LSGG — Apr 3, 2026 · 16 min · 45 aircraft · OpenSky ADS-B`
- In recorded mode: auto-fetch recordings list, show picker, load selected recording, use existing PlaybackBar

### `app/frontend/src/types/flight.ts`

- Add `'opensky_recorded'` to `FlightsResponse.data_source` union

## Step 4: Recorded-Mode Status Bar

Add a `RecordedBar` (similar to `LiveBar`) shown during recorded playback:

- Amber/orange theme (distinct from live=green, simulation=dark)
- Shows: "RECORDED" badge, aircraft count, recording date, "OpenSky ADS-B" source tag
- Shows that this is real historical data being replayed

## Files to Modify

| File | Change |
|------|--------|
| `app/backend/api/opensky.py` | Add `/recordings` and `/recordings/{airport}/{date}` endpoints |
| `app/backend/services/opensky_service.py` | Export `_determine_flight_phase` + unit constants for reuse |
| `app/frontend/src/types/flight.ts` | Add `'opensky_recorded'` to data source union |
| `app/frontend/src/context/FlightContext.tsx` | Add `'recorded'` DataMode |
| `app/frontend/src/hooks/useSimulationReplay.ts` | Add `loadRecording`, `fetchRecordings`, `availableRecordings` |
| `app/frontend/src/components/SimulationControls/SimulationControls.tsx` | Add RecordingPicker, extend DataModeToggle, add RecordedBar |

## Verification

1. Backend: `curl /api/opensky/recordings` returns listing after data upload
2. Backend: `curl /api/opensky/recordings/LSGG/2026-04-03` returns frame data
3. Frontend: Build succeeds: `cd app/frontend && npm run build`
4. Frontend tests: `cd app/frontend && npm test -- --run`
5. UI: Switch to "Recorded" mode, picker shows recordings, select one, playback works with PlaybackBar
6. Python tests: `uv run pytest tests/ -v -k opensky`

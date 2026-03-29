# Problem: Long Simulation Persistence + Navigation

## Current State of Simulation Persistence

### Two persistence paths

**1. JSON files (offline batch simulations)**
- `SimulationRecorder` writes a single monolithic JSON file per simulation run
- Contains: position_snapshots, phase_transitions, gate_events, baggage_events, weather_snapshots, schedule, scenario_events, passenger_events
- Stored locally or in UC Volumes (`/Volumes/.../simulation_data/`)
- Listed via `simulation_runs` UC table (metadata catalog)
- Sizes: 27 MB to 152 MB for 1000-flight 24h sims. Multi-day sims would be 500MB+.

**2. Lakebase (real-time live sim)**
- `DataGeneratorService._persist_flight_data()` persists every 15s to Lakebase tables:
  - `flight_position_snapshots` (session_id, airport_icao, icao24, lat/lng/alt/vel, phase, time)
  - `flight_phase_transitions`
  - `gate_assignment_events`
  - `ml_predictions`
  - `turnaround_events`
- All keyed by session_id + airport_icao + event_time

### Frontend loading

- Entire file loaded at once — `loadFile()` fetches the full JSON, groups snapshots into frames in-memory
- Has `start_hour`/`end_hour` query params for server-side time slicing, but the UI doesn't expose this
- 1 GB hard cap (`_MAX_LOADABLE_BYTES`) in the API
- No pagination, no day-level navigation, no date picker
- Video renderer exists (Playwright + ffmpeg) for headless capture, but no in-browser scene capture

---

## Problems for Long Simulations

| Issue | Impact |
|---|---|
| Monolithic JSON file | 152 MB for 24h/1000 flights. A 7-day sim = ~1 GB, browser chokes |
| All frames in browser memory | frames dict + frame_timestamps array all held in state |
| No day/time navigation | Operator can't jump to "day 3" or "March 15, 14:00-18:00" |
| No scene capture for reporting | Can't save a 2D/3D screenshot as evidence |

---

## Proposed Solution

Break into 3 layers (needs detailed planning):

1. **Storage layer** — Chunked persistence (hourly or daily segments) instead of monolithic JSON. Could use Parquet in UC Volumes or Delta tables for position data.
2. **API layer** — Time-windowed loading with the existing `start_hour`/`end_hour` params exposed properly. Add day-level pagination for multi-day sims.
3. **Frontend layer** — Day/time picker in the playback UI. Lazy loading of time windows. In-browser scene capture for reporting.

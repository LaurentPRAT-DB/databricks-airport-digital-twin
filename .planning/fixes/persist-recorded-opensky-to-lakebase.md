# Plan: Persist Recorded OpenSky Data to Lakebase for ML Training

**Status:** Fix
**Date added:** 2026-04-06
**Depends on:** OpenSky Recorded Data Replay, OpenSky Event Inference Pipeline
**Scope:** Single file change — add persistence + schedule derivation to recording playback API

---

## Context

When playing back recorded ADS-B data (e.g. KSFO Apr 3), the `get_recording_data()` endpoint infers gate assignments, phase transitions, and origin/destination from raw positions — but never persists any of it. The enriched data only exists in the API response and is lost. This means recorded data is unusable for ML model training, which needs `flight_position_snapshots`, `gate_assignment_events`, `flight_phase_transitions`, and `flight_schedule` in Lakebase.

Meanwhile, simulation mode (`data_generator_service.py`) persists all of these every 15s. Live OpenSky collection (`opensky_collector.py`) also persists snapshots. Recorded playback should do the same.

**User's key insight:** If the recording is long enough, we can observe full turnarounds (plane arrives, parks, leaves). So we should derive the schedule from observed data first (arrival time = first seen, departure = last seen leaving gate, gate = inferred gate), and only infer/fill gaps when the recording doesn't capture the full lifecycle.

## Changes

### 1. Add Persistence to `get_recording_data()` — `app/backend/api/opensky.py`

After the existing inference + enrichment logic (lines 373-448), add a background persistence step:

- Generate a `session_id` from `f"recorded-{airport}-{date}"` (deterministic, so replaying the same recording upserts rather than duplicates)
- Persist to Lakebase using existing methods:
  - `insert_flight_snapshots()` — enriched snapshots from `inferrer.get_enriched_snapshots()`, with `data_source="opensky_recorded"`
  - `insert_gate_events()` — from `enrichment["gate_events"]`, adding `event_time` from the event's `time` field
  - `insert_phase_transitions()` — from `enrichment["phase_transitions"]`, adding `event_time` from `time`
- Build a derived schedule from observed aircraft lifecycles and persist via `upsert_schedule()`

### 2. Build Schedule from Observed Data — New Function

New function `_derive_schedule_from_recording()`:

For each unique aircraft tracked by the inferrer:

1. **Extract observed facts** from gate_events + phase_transitions + frame data:
   - `callsign` → use as `flight_number` (ADS-B callsign is typically the flight number)
   - `gate` → from gate assign/occupy events (if observed)
   - `arrival_time` → from first landing or taxi_to_gate phase transition, or first frame if already on ground
   - `departure_time` → from gate release event followed by takeoff transition, or last frame if still present
   - `origin` / `destination` → from `enrich_origins_opensky` results (already computed)
   - `status` → derive from lifecycle: "Landed" if we see landing, "Departed" if we see takeoff, "On Time" if parked
   - `flight_type` → "arrival" if first seen airborne/landing, "departure" if first seen at gate and later takes off

2. **Determine direction** from the aircraft tracker's `was_airborne` flag and first/last phase:
   - First seen airborne → arriving flight
   - First seen parked, later takes off → departing flight
   - Both observed (long recording) → create TWO schedule entries (arrival + departure)

3. **Fill gaps with inference only when data is missing:**
   - No origin from OpenSky API → use heading-based heuristic (already computed)
   - No gate observed → leave as `None`
   - No departure seen → leave departure fields as `None` (recording too short)

### 3. Adapt Event Dicts for Lakebase Insert Methods

The inferrer outputs events with `time` field, but Lakebase insert methods expect `event_time`. Map:

- **Gate events:** `{"time": ..., "icao24": ..., "gate": ..., "event_type": ...}` → add `event_time = parse time to datetime`
- **Phase transitions:** same — add `event_time` from `time`
- **Enriched snapshots:** map to `insert_flight_snapshots` format (`flight_phase` instead of `phase`, `snapshot_time` from `time`)

### 4. Run Persistence in Background Thread

The Lakebase insert is sync (psycopg2). Wrap in `threading.Thread` like the existing query pattern in the same file, so it doesn't block the API response. Fire-and-forget — the frontend gets its data immediately, persistence happens async.

## Files to Modify

| File | Change |
|------|--------|
| `app/backend/api/opensky.py` | Add persistence after inference in `get_recording_data()`, add `_derive_schedule_from_recording()`, add `_persist_recording_to_lakebase()` |

No other files need changes — all Lakebase insert methods already exist and the inferrer already produces the right data structures.

## Key Functions to Reuse

- `lakebase_service.insert_flight_snapshots()` — already handles `data_source` field
- `lakebase_service.insert_gate_events()`
- `lakebase_service.insert_phase_transitions()`
- `lakebase_service.upsert_schedule()` — upserts by `(airport_icao, flight_number, scheduled_time)`
- `OpenSkyEventInferrer.get_enriched_snapshots()` — returns snapshots with inferred phase + gate
- `OpenSkyEventInferrer.get_results()` → `gate_events`, `phase_transitions`
- `inferrer._trackers` — per-aircraft state with `was_airborne`, `assigned_gate`, `parked_since`

## Verification

1. **Unit test:** Add test in `tests/test_opensky_recording_persistence.py` for `_derive_schedule_from_recording()` with mock gate events + trackers
2. **Integration:** Load KSFO Apr 3 recording via API, then query Lakebase tables to verify data landed:
   - `flight_position_snapshots` has rows with `data_source='opensky_recorded'`
   - `gate_assignment_events` has inferred gate assignments
   - `flight_schedule` has derived schedule entries
3. **Existing tests:** `uv run pytest tests/ -v -k opensky` still pass
4. **Frontend:** no changes needed — the API response format is unchanged

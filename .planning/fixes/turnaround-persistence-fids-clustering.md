# Fix: Turnaround Event Persistence + FIDS Time Clustering

## Context

Two issues found during deployed app investigation:

1. **Turnaround events drained but never persisted** — `data_generator_service.py:458` says "Lakebase table pending". Events are cleared from the buffer every 15s but discarded. We need historical turnaround data for ML model training.
2. **FIDS time clustering** — Live sim flights from `get_flights_as_schedule()` cluster at similar `scheduled_time`s. The `spread_minutes` variable (line 600) is computed with a 240-min window but never used. Enroute flights use a narrow 60-min modulo causing visible clustering on FIDS.

---

## Fix 1: Persist Turnaround Events to Lakebase

### What exists already

- `emit_turnaround_event()` in `fallback.py:344` emits events with: icao24, callsign, gate, turnaround_phase, event_type (phase_start|phase_complete), aircraft_type, event_time
- `drain_turnaround_events()` in `fallback.py:368` drains the buffer (standard pattern)
- `_persist_flight_data()` in `data_generator_service.py:424` already drains the buffer but only logs
- `_ensure_ml_tables()` in `lakebase_service.py:1319` creates tables on first use
- Existing batch insert pattern: `insert_phase_transitions`, `insert_gate_events` use `execute_values`

### Changes

**File: `app/backend/services/lakebase_service.py`**

1. Add `CREATE TABLE IF NOT EXISTS turnaround_events` to `_ensure_ml_tables()` (after the `ml_predictions` table):
   - Columns: `id BIGSERIAL`, `session_id VARCHAR(36)`, `airport_icao VARCHAR(4)`, `icao24 VARCHAR(10)`, `callsign VARCHAR(10)`, `gate VARCHAR(10)`, `turnaround_phase VARCHAR(20)`, `event_type VARCHAR(15)`, `aircraft_type VARCHAR(10)`, `event_time TIMESTAMPTZ DEFAULT NOW()`
   - Add index on `(session_id, airport_icao, event_time)`
2. Add `insert_turnaround_events()` method (after `insert_gate_events`), following the same `execute_values` batch pattern:
   - Maps each event dict to tuple: `(session_id, airport_icao, icao24, callsign, gate, turnaround_phase, event_type, aircraft_type, event_time)`

**File: `app/backend/services/data_generator_service.py`**

3. Replace the log-only code at line 458-461 with actual persistence:
   ```python
   ta_count = lakebase.insert_turnaround_events(turnaround_events, session_id, airport_icao)
   ```
4. The return dict key `"turnaround_events": ta_count` already exists — no change needed there.

---

## Fix 2: FIDS Time Clustering

### Root cause

In `get_flights_as_schedule()` (`fallback.py:540-660`), the `spread_minutes` variable (line 600, 240-min range) is computed but never used. Each phase branch independently computes `scheduled_time` with narrow modulo ranges that cause clustering.

### Changes

**File: `src/ingestion/fallback.py`**

Remove the unused `spread_minutes` variable (line 600). Widen the per-phase time ranges to reduce clustering:

- Enroute arrivals (line 626): `30 + _h % 60` → `15 + _h % 120` (15-135 min ahead, was 30-90)
- Enroute departures catch-all (line 641): `_h % 30` → `_h % 90` (0-90 min, was 0-30)
- Parked arrivals (line 611): `5 + _h % 55` → `5 + _h % 115` (5-120 min ago, was 5-60)
- Parked departures (line 633): `10 + _h % 80` → `10 + _h % 110` (10-120 min ahead, was 10-90)

---

## Files to Modify

1. `app/backend/services/lakebase_service.py` — add table DDL + `insert_turnaround_events` method
2. `app/backend/services/data_generator_service.py` — wire the persistence call (1 line change)
3. `src/ingestion/fallback.py` — widen FIDS time spread ranges, remove dead `spread_minutes` code

## Verification

1. Run Python tests: `uv run pytest tests/test_lakebase_service.py tests/test_services.py tests/test_fids_accuracy.py -v -x`
2. Start local dev: `./dev.sh`, open FIDS, verify times are spread across a wider window (not all same minute)
3. Build + deploy: `cd app/frontend && npm run build && databricks bundle deploy --target dev`
4. On deployed app: check `/api/schedule/arrivals` for diverse `scheduled_time` values

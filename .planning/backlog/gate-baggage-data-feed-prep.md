---
title: "Gate & Baggage Data Feed Prep Work"
status: active
area: ingestion
priority: high
related:
  - .planning/backlog/flifo-api-live-flight-data.md
---

# Gate & Baggage Data Feed Prep Work

## Context

FLIFO API integration (`.planning/backlog/flifo-api-live-flight-data.md`) adds real gate/stand/belt/terminal data. Most infrastructure exists (gate ML model, baggage DLT pipeline, Lakebase tables). This prep work adds the missing fields so when FLIFO credentials arrive, only the client + mapper need implementation.

## Steps

### 1. Add fields to ScheduledFlight model

**File:** `app/backend/models/schedule.py`

Add 5 optional fields after `icao24`:
- `terminal: Optional[str]` — Terminal assignment
- `stand: Optional[str]` — Physical stand/parking position
- `belt: Optional[str]` — Baggage carousel number (arrivals)
- `registration: Optional[str]` — Aircraft registration
- `codeshares: Optional[list[str]]` — Codeshare flight numbers

→ verify: existing tests still pass (no required field change)

### 2. Add fields to frontend ScheduledFlight interface

**File:** `app/frontend/src/components/FIDS/FIDS.tsx`

Add matching optional fields to the TS interface. Display terminal and belt in FIDS table — terminal for all flights, belt for arrivals only.

→ verify: `cd app/frontend && npm test -- --run`

### 3. Wire terminal from gate lookup in schedule generator

**File:** `src/ingestion/schedule_generator.py`

When `_assign_gate_with_occupancy()` assigns a gate, look up terminal from OSM gate data (already available in gate model's `Gate.terminal` field). Set it on the flight dict.

→ verify: `uv run pytest tests/ -k "schedule" -v`

### 4. Wire carousel → belt in schedule service

**File:** `app/backend/services/schedule_service.py`

When building schedule from synthetic data, if baggage data exists for a flight, copy carousel to belt field.

→ verify: `uv run pytest tests/ -k "schedule_service" -v`

### 5. Add columns to Lakebase flight_schedule table

**File:** `app/backend/services/lakebase_service.py`

In `_ensure_airport_columns()`, add ALTER TABLE for new columns on `flight_schedule`:
- `terminal VARCHAR(20)`
- `stand VARCHAR(20)`
- `belt VARCHAR(10)`
- `registration VARCHAR(10)`
- `data_source VARCHAR(20) DEFAULT 'synthetic'`

Update `upsert_flight_schedule()` to include new columns.

→ verify: `uv run pytest tests/test_lakebase_service.py -v`

### 6. Run full test suite

```bash
uv run pytest tests/ -v
cd app/frontend && npm test -- --run
```

## Files Touched

- `app/backend/models/schedule.py` — add 5 fields
- `app/frontend/src/components/FIDS/FIDS.tsx` — add fields + display
- `src/ingestion/schedule_generator.py` — wire terminal from gate
- `app/backend/services/schedule_service.py` — wire belt from baggage
- `app/backend/services/lakebase_service.py` — new columns + upsert

## Verification

1. Python tests pass: `uv run pytest tests/ -v`
2. Frontend tests pass: `cd app/frontend && npm test -- --run`
3. Existing FIDS behavior unchanged (no required fields added)
4. New fields appear as null/empty until data source provides them

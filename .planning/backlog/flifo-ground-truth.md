---
status: backlog
area: flifo
related:
  - .planning/fixes/flifo-data-usage-gaps.md
  - src/ingestion/flifo_mapper.py
  - src/ingestion/_generation.py
  - src/ingestion/_flight_lifecycle.py
  - src/ingestion/_state.py
  - app/backend/services/schedule_service.py
---

# Plan: FLIFO as Ground Truth

## Context

FLIFO (SITA FlightInfo API) provides real-time ground-truth data: aircraft type, delay minutes, delay codes, estimated/actual times, terminal, baggage belt, registration, and codeshares. Currently this rich metadata is discarded when flights are spawned into the simulation. The spawner only passes callsign, origin, destination, gate, and phase — then `get_flights_as_schedule()` re-invents all other fields synthetically (random aircraft type, hash-derived delays/belts, no terminal). The original FLIFO record gets deduped OUT because live sim data always wins.

**Goal:** When FLIFO data is available for a flight, use it as ground truth throughout the system — aircraft type, delays, times, terminal, belt, registration should flow through to the FIDS and map display.

---

## Approach: Store FLIFO Metadata on FlightState

Rather than maintaining a parallel lookup table, attach FLIFO ground-truth fields directly to FlightState. This keeps the data co-located with the flight and automatically flows through all existing code paths.

---

## Changes

### 1. Add FLIFO metadata fields to FlightState (`src/ingestion/_state.py`)

Add optional fields:

```python
registration: Optional[str] = None
terminal: Optional[str] = None
belt: Optional[str] = None
scheduled_time_iso: Optional[str] = None
estimated_time_iso: Optional[str] = None
actual_time_iso: Optional[str] = None
delay_minutes: int = 0
delay_reason: Optional[str] = None
codeshares: Optional[List[str]] = None
data_source: str = "synthetic"  # "flifo" when seeded from FLIFO
```

### 2. Extend `_create_new_flight` signature (`src/ingestion/_flight_lifecycle.py:390`)

Add kwargs:

```python
def _create_new_flight(
    icao24, callsign, phase,
    origin=None, destination=None, preferred_gate=None,
    aircraft_type_override=None,
    registration=None, terminal=None, belt=None,
    scheduled_time_iso=None, estimated_time_iso=None, actual_time_iso=None,
    delay_minutes=0, delay_reason=None, codeshares=None,
    data_source="synthetic",
) -> FlightState:
```

- When `aircraft_type_override` is set, use it directly instead of calling `_get_aircraft_type_for_airline()`
- Pass all new fields into the `FlightState(...)` constructor at each return site within the function

### 3. Pass FLIFO metadata through spawner (`src/ingestion/_generation.py:374-413`)

In `_try_spawn_from_queue`, extract all available FLIFO fields from the queue item and pass to `_create_new_flight`:

```python
aircraft_type_override = flight.get("aircraft_type")  # ICAO type from FLIFO
registration = flight.get("registration")
terminal = flight.get("terminal")
belt = flight.get("belt")
scheduled_time_iso = flight.get("scheduled_time")
estimated_time_iso = flight.get("estimated_time")
actual_time_iso = flight.get("actual_time")
delay_minutes = flight.get("delay_minutes", 0)
delay_reason = flight.get("delay_reason")
codeshares = flight.get("codeshares")
```

### 4. Prefer FLIFO metadata in schedule derivation (`src/ingestion/_generation.py:259-324`)

In `get_flights_as_schedule`, when building the schedule dict for a flight:

- If `state.data_source == "flifo"`, use stored metadata instead of deriving:
  - `aircraft_type` → already correct (was overridden at spawn)
  - `delay_minutes` → use `state.delay_minutes` (don't re-invent from hash)
  - `estimated_time` → use `state.estimated_time_iso` if set
  - `actual_time` → use `state.actual_time_iso` OR derive from phase (arrived = now)
  - `belt` → use `state.belt` if set
  - `terminal` → use `state.terminal` if set
  - `registration` → use `state.registration`
  - `codeshares` → use `state.codeshares`
  - `data_source` → `"flifo"`
- If `state.data_source == "synthetic"`, keep current logic unchanged.

### 5. Enrich merge logic in schedule_service (`app/backend/services/schedule_service.py:234-270`)

When deduplicating live vs background FLIFO flights:
- If a live flight has `data_source == "flifo"`, it already carries ground truth — no change needed.
- If a live flight has `data_source == "synthetic"` but a matching FLIFO background record exists, merge FLIFO metadata onto the live entry (overlay terminal, belt, registration, codeshares, delay_reason from FLIFO).

This handles the edge case where a flight was spawned before FLIFO data arrived (started synthetic, FLIFO caught up).

### 6. Pass terminal, registration, belt to frontend (already works)

`ScheduledFlight` model already has these fields. `_dict_to_scheduled_flight` already maps them. Frontend `FIDS.tsx` already renders them. No frontend changes needed.

---

## Files Modified

| File | Change |
|------|--------|
| `src/ingestion/_state.py` | Add 10 optional fields to FlightState |
| `src/ingestion/_flight_lifecycle.py` | Extend `_create_new_flight` signature + pass fields to FlightState |
| `src/ingestion/_generation.py` | Pass FLIFO metadata in spawner; prefer stored metadata in schedule derivation |
| `app/backend/services/schedule_service.py` | Merge FLIFO metadata onto synthetic live flights during dedup |

---

## What Does NOT Change

- `flifo_mapper.py` — already produces all needed fields
- `flifo_client.py` — already fetches all data
- `_schedule_queue.py` — already passes full flight dicts through
- `flifo_service.py` — already caches and serves data
- `app/backend/models/schedule.py` — already has all fields
- `app/frontend/` — already renders terminal/belt/registration
- All other callers of `_create_new_flight` — new kwargs have defaults, zero breakage

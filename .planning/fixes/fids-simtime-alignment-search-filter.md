# Plan: FIDS Sim-Time Alignment + Search Filter

## Context

The simulation replays pre-recorded data. The frontend advances through recorded timestamps via `currentSimTime` (e.g. "2026-03-22T08:26:00Z"). But the FIDS backend API uses `datetime.now(timezone.utc)` for all time calculations — filtering the schedule window, computing arrival offsets, etc. This means FIDS times don't match the sim clock.

Additionally, there's no search/filter on the FIDS, making it hard to find a specific flight.

---

## Fix 1: Pass sim_time to FIDS backend

### Frontend -> Backend: Add sim_time query parameter

**`app/frontend/src/components/FIDS/FIDS.tsx`**:
- Accept `simTime?: string | null` prop
- Pass it as query param: `/api/schedule/arrivals?sim_time=2026-03-22T08:26:00Z`
- If `simTime` is null/undefined, omit the param (backend falls back to `datetime.now()`)

**`app/frontend/src/App.tsx`**:
- The sim hook lives inside `SimulationControls`. Need to lift `currentSimTime` up or use a context.
- Simplest approach: FIDS already has access to `FlightContext` — add `simTime` to that context, or pass as prop from App.
- Looking at the code: `SimulationControls` is rendered in App and has access to `sim.currentSimTime`. App can pass it as a prop to FIDS.
- Add state `simTime` in App, updated by `SimulationControls` via a callback prop, passed to `<FIDS simTime={simTime}>`.

### Backend: Use sim_time instead of datetime.now()

**`app/backend/api/routes.py`** — `/api/schedule/arrivals` and `/api/schedule/departures`:
- Add optional `sim_time: str | None` query parameter
- Pass it through to `schedule_service.get_arrivals(sim_time=...)`

**`app/backend/services/schedule_service.py`** — `get_arrivals()` / `get_departures()` / `_get_merged_schedule()`:
- Accept optional `sim_time: datetime | None` parameter
- Pass to `get_flights_as_schedule(sim_time=...)` and time-window calculations

**`src/ingestion/fallback.py`** — `get_flights_as_schedule()`:
- Accept optional `sim_time: datetime | None` parameter
- Use `sim_time or datetime.now(timezone.utc)` as `now` throughout the function
- This affects: arrival offsets (parked_since relative calc), departure offsets, status mapping

**`src/ingestion/schedule_generator.py`** — `get_arrivals()`, `get_departures()`, `get_future_schedule()`:
- Accept optional `sim_time: datetime | None` parameter
- Use `sim_time or datetime.now(timezone.utc)` as `now` for time window filtering

---

## Fix 2: Add search/filter to FIDS

**`app/frontend/src/components/FIDS/FIDS.tsx`**:
- Add search input above the flight table
- Filter flights by `flight_number`, `airline`, `origin`, `destination`, `gate` (case-insensitive substring match)
- Simple `useState` + `.filter()` — no backend changes needed

---

## Files to modify

| File | Change |
|------|--------|
| `app/frontend/src/components/FIDS/FIDS.tsx` | Add simTime prop, search filter, pass sim_time to API |
| `app/frontend/src/App.tsx` | Lift simTime state, pass to FIDS |
| `app/backend/api/routes.py` | Add sim_time query param to schedule endpoints |
| `app/backend/services/schedule_service.py` | Thread sim_time through to data sources |
| `src/ingestion/fallback.py` | `get_flights_as_schedule(sim_time=...)` uses sim_time as now |
| `src/ingestion/schedule_generator.py` | `get_arrivals`/`get_departures`/`get_future_schedule` accept sim_time |

## Verification

1. `uv run pytest tests/ -k "schedule or fids or arrival" -v` — existing tests pass
2. `cd app/frontend && npm test -- --run` — frontend tests pass
3. Build + deploy, verify FIDS times align with sim clock in playback bar
4. Verify search filter works to find a specific flight by callsign

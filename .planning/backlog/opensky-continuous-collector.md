# Plan: Continuous OpenSky ADS-B Data Collector for ML Training

**Status:** Backlog
**Date added:** 2026-04-02
**Depends on:** OpenSky Live Data Integration
**Scope:** Background collector service + Lakebase schema update + REST API + Frontend indicator

---

## Context

Live OpenSky integration is working (commit 77e81d4). The user wants a continuous background collector that records real ADS-B data from multiple airports into the Lakehouse. This data will be used to train ML models with real-world flight patterns. The collector should run independently of the UI, covering multiple airports simultaneously, and track which airports have historical data available for replay.

### Target airports

- **US:** KJFK, KLAX, KATL, KORD, KDEN, KSFO
- **Abu Dhabi:** OMAA (AUH)
- **Athens:** LGAV (ATH)
- **Geneva:** LSGG (GVA)

## Architecture

### New: `app/backend/services/opensky_collector.py`

A background service that continuously polls OpenSky for each configured airport and writes snapshots to Lakebase.

```
OpenSkyCollector
├── _airports: dict[str, AirportTarget]   # ICAO → (lat, lon, iata)
├── _session_id: str                       # "collector-{uuid}"
├── _running: bool
├── _stats: dict[str, CollectorStats]      # Per-airport: snapshots_saved, last_fetch, errors
│
├── start() → asyncio.Task                 # Launches the polling loop
├── stop()                                 # Graceful shutdown
├── get_status() → dict                    # Per-airport stats + collection summary
├── _collect_loop()                        # Main loop: iterates airports, fetches, persists
└── _persist_snapshots(airport_icao, flights) → int
```

### Polling strategy

- OpenSky anonymous rate limit: ~10 requests per 10 seconds
- With 9 airports: cycle through all airports every ~10s (1 req/airport/cycle)
- Each airport gets fresh data every ~10s — well within rate limits
- Sleep 1s between airports to stay under rate limits

### Data flow

1. `_collect_loop()` iterates through airports
2. For each: calls `opensky_service.fetch_flights(lat, lon)` (existing code, reused)
3. Converts flights to snapshot dicts (add `snapshot_time`, already has all required fields)
4. Calls `lakebase_service.insert_flight_snapshots(snapshots, session_id, airport_icao)`
5. Updates per-airport stats

## Backend Changes

### Modify: `app/backend/services/lakebase_service.py`

Add `data_source` column to `flight_position_snapshots`:

- In `_ensure_ml_tables()`: add `data_source VARCHAR(20) DEFAULT 'simulation'` to CREATE TABLE
- Add migration: `ALTER TABLE flight_position_snapshots ADD COLUMN IF NOT EXISTS data_source VARCHAR(20) DEFAULT 'simulation'`
- Update `insert_flight_snapshots()`: include `data_source` in INSERT values (read from snapshot dict, default `'simulation'`)

### New: `app/backend/api/collector.py`

REST endpoints for the collector:

- `GET /api/collector/status` — per-airport stats, overall running state
- `POST /api/collector/start` — start collecting (idempotent)
- `POST /api/collector/stop` — stop collecting
- `GET /api/collector/airports` — list of airports with data availability (snapshot counts, date ranges)

### Modify: `app/backend/main.py`

- Register `collector_router`
- Auto-start the collector on app startup (in the existing lifespan or startup event)

## Frontend Changes

### Modify: `app/frontend/src/components/SimulationControls/SimulationControls.tsx`

In the LiveBar component, add a collector status indicator:

- Small badge showing "Collecting: 9 airports" or "Collector: Off"
- Links to a detailed status (or tooltip with per-airport info)

## Key Implementation Details

### Airport coordinate resolution

Use `src/ingestion/airport_table.py:AIRPORTS` dict (IATA→lat,lon,ICAO,country). Build an ICAO→(lat,lon) reverse lookup for the 9 target airports:

```python
_COLLECTOR_AIRPORTS = {
    "KJFK": (40.6413, -73.7781),
    "KLAX": (33.9425, -118.4081),
    "KATL": (33.6407, -84.4277),
    "KORD": (41.9742, -87.9073),
    "KDEN": (39.8561, -104.6737),
    "KSFO": (37.6213, -122.3790),
    "OMAA": (24.4431, 54.6511),
    "LGAV": (37.9364, 23.9445),
    "LSGG": (46.2381, 6.1090),
}
```

### Snapshot dict shape

OpenSky `_state_to_flight()` already returns all fields needed by `insert_flight_snapshots()`. Just add `snapshot_time` and `data_source`:

```python
for flight in flights:
    flight["snapshot_time"] = datetime.now(timezone.utc).isoformat()
    flight["data_source"] = "opensky"
```

### Reuse existing code

- `opensky_service.fetch_flights(lat, lon)` — already handles rate limiting, 429s, error recovery
- `lakebase_service.insert_flight_snapshots()` — already handles batch inserts, connection pooling
- `_ensure_ml_tables()` — already creates the `flight_position_snapshots` table

## Files to Create/Modify

| Action | File | What |
|--------|------|------|
| Create | `app/backend/services/opensky_collector.py` | Background collector service |
| Create | `app/backend/api/collector.py` | REST endpoints for collector control |
| Modify | `app/backend/services/lakebase_service.py` | Add `data_source` column to snapshots table |
| Modify | `app/backend/main.py` | Register collector router, auto-start |
| Modify | `app/frontend/src/components/SimulationControls/SimulationControls.tsx` | Collector status in LiveBar |
| Create | `tests/test_opensky_collector.py` | Collector unit tests |
| Modify | `tests/test_lakebase_service.py` | Test `data_source` column |

## Verification

1. `uv run pytest tests/test_opensky_collector.py tests/test_lakebase_service.py -v` — new tests pass
2. `uv run pytest tests/ -v` — full backend suite, no regressions
3. `cd app/frontend && npm test -- --run` — frontend tests pass
4. Manual: start app → `GET /api/collector/status` shows 9 airports collecting
5. Manual: wait 30s → `GET /api/collector/airports` shows snapshot counts increasing
6. Manual: query Lakebase `SELECT airport_icao, COUNT(*) FROM flight_position_snapshots WHERE data_source='opensky' GROUP BY airport_icao` — all 9 airports have data

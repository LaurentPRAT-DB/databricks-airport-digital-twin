# Plan: OpenSky Live Data Integration

**Status:** Backlog
**Date added:** 2026-04-02
**Scope:** Backend service + API + WebSocket mode switching + Frontend toggle

---

## Context

The app currently only displays synthetic simulation data. The user wants real ADS-B flight data from the OpenSky Network API alongside the existing simulation mode, with a UI toggle to switch between them. In live mode, simulation-specific controls (sim time, playback speed, scrubber, frame counter) should be hidden since data is real-time.

## Architecture

Two data modes managed at the FlightProvider level:

1. **Simulation** (existing) — frame-based replay with time controls
2. **Live** (new) — OpenSky REST API polled every ~10s, streamed via the existing WebSocket

## Backend

### New file: `app/backend/services/opensky_service.py`

- `OpenSkyService` class with `async fetch_flights(lat, lon, radius_nm=30) -> list[dict]`
- Calls `https://opensky-network.org/api/states/all?lamin=...&lamax=...&lomin=...&lomax=...`
- Computes bounding box from airport center + radius (~30nm ≈ 0.5 degrees)
- Maps OpenSky state vector fields to our FlightPosition schema
- Handles rate limiting (10 req/10s anonymous, backoff on 429)
- Returns empty list on errors (graceful degradation)

### New file: `app/backend/api/opensky.py`

- `opensky_router` with:
  - `GET /api/opensky/flights` — returns live flights for current airport
  - `GET /api/opensky/status` — returns API health, last fetch time, aircraft count

### Modify: `app/backend/api/websocket.py`

- Add a `mode` field to the broadcaster
- When mode is `"live"`, the broadcast loop calls OpenSkyService instead of FlightService
- Accept a `{"command": "set_mode", "mode": "live"|"simulation"}` message from clients
- Broadcast `{"type": "mode_change", "data": {"mode": "live"|"simulation"}}` to all clients on switch

### Modify: `app/backend/main.py`

- Register `opensky_router`

## Frontend

### New file: `app/frontend/src/hooks/useOpenSky.ts`

- Polls `GET /api/opensky/flights` every 10s
- Maps response to `Flight[]`
- Returns `{ flights, isLoading, error, lastUpdated, isActive }`

### Modify: `app/frontend/src/types/flight.ts`

- Add `'opensky'` to `data_source` union in `FlightsResponse`

### Modify: `app/frontend/src/context/FlightContext.tsx`

- Add `dataMode: 'simulation' | 'live'` to context
- Add `setDataMode` action
- When `dataMode === 'live'`, use OpenSky flights instead of simulation/synthetic

### Modify: `app/frontend/src/components/SimulationControls/SimulationControls.tsx`

- Add a toggle button in the header area: "Simulation" / "Live" mode switch
- When in Live mode: hide the PlaybackBar entirely (no sim time, no scrubber, no speed controls)
- Show a minimal "Live" indicator with flight count and last-updated timestamp instead

### Modify: `app/frontend/src/App.tsx`

- Pass `dataMode` / `setDataMode` through to components
- When live mode is active, `simulationFlights` is null (simulation controls hidden)

## Data Mapping (OpenSky → FlightPosition)

OpenSky state vector indices:

```
[0] icao24, [1] callsign, [2] origin_country, [3] time_position,
[4] last_contact, [5] longitude, [6] latitude, [7] baro_altitude (m),
[8] on_ground, [9] velocity (m/s), [10] true_track (degrees),
[11] vertical_rate (m/s), [12] sensors, [13] geo_altitude (m),
[14] squawk, [15] spi, [16] position_source
```

Conversion:

- `altitude`: `baro_altitude * 3.28084` (m → ft)
- `velocity`: `velocity * 1.94384` (m/s → knots)
- `vertical_rate`: `vertical_rate * 196.85` (m/s → ft/min)
- `flight_phase`: derive from altitude + vertical_rate + on_ground (reuse `_determine_flight_phase`)

## Files to Create/Modify

| Action | File |
|--------|------|
| Create | `app/backend/services/opensky_service.py` |
| Create | `app/backend/api/opensky.py` |
| Modify | `app/backend/main.py` (register router) |
| Modify | `app/backend/api/websocket.py` (mode switching) |
| Create | `app/frontend/src/hooks/useOpenSky.ts` |
| Modify | `app/frontend/src/context/FlightContext.tsx` (add dataMode) |
| Modify | `app/frontend/src/components/SimulationControls/SimulationControls.tsx` (mode toggle + hide controls) |
| Modify | `app/frontend/src/App.tsx` (wire mode state) |
| Create | `tests/test_opensky_service.py` |

## Verification

1. `uv run pytest tests/test_opensky_service.py -v` — unit tests with mocked HTTP
2. `cd app/frontend && npm test -- --run` — ensure existing tests still pass
3. Manual: start `./dev.sh`, switch to Live mode, verify flights appear on map with real positions
4. Manual: switch back to Simulation mode, verify sim controls reappear and playback works
5. Verify no sim time / scrubber / speed controls shown in Live mode

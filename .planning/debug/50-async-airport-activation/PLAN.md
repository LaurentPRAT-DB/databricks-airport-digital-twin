# Fix: Async airport activation to survive proxy timeout

## Context

When switching to an uncached airport (e.g., OMAA), the Overpass API (OSM) fetch can take 30-60+ seconds. The Databricks Apps reverse proxy has a ~30s request timeout, which kills the HTTP connection before the FastAPI handler completes. The user sees a generic "Internal Server Error" and the switch fails.

The current `POST /api/airports/{icao}/activate` is synchronous — it does all work (OSM fetch, center set, gate reload, ML retrain, state reset) before returning the HTTP response. The fix: return 202 immediately and run the heavy work in the background, with progress updates via the existing WebSocket infrastructure.

### Existing infrastructure we reuse:
- `broadcaster.broadcast_progress()` in `websocket.py:101` — sends `airport_switch_progress` WS messages
- Frontend WS listener in `useAirportConfig.ts:167-200` — already handles progress and error via WS
- `useFlights.ts:75-82` — clears stale flights on `airport_switch_progress` with `done=true`
- `AirportSwitchProgress.tsx` — progress overlay UI already exists

---

## Changes

### 1. `app/backend/api/routes.py` — Make activation fire-and-forget

**Current flow** (synchronous, blocks HTTP response ~10-60s):
```
POST /activate → acquire lock → OSM fetch (SLOW) → center → gates/ML → return 200 + config
```

**New flow** (returns 202 in <100ms):
```
POST /activate → acquire lock → return 202 {"status": "activating"}
                              → launch background task:
                                  Step 1: OSM fetch → Step 2: center → Step 3: gates/ML
                                  → broadcast "airport_switch_complete" with config via WS
                                  → release lock
```

Specific changes to `activate_airport` (~line 865):
- Keep the 409 check if lock is held
- Don't use `async with _activation_lock` — instead manually `await _activation_lock.acquire()`
- `asyncio.create_task(_activate_airport_inner(...))` — fire-and-forget
- Return `JSONResponse(status_code=202, content={"status": "activating", "icaoCode": icao_code})` immediately

Refactor `_activate_airport_inner` (~line 892):
- Wrap entire body in `try/finally` that calls `_activation_lock.release()` in `finally`
- On success: broadcast a new message `airport_switch_complete` with the config payload (same dict previously returned in HTTP response)
- On error: broadcast `airport_switch_progress` with `error=True`, rollback as before

Add broadcast_complete helper to broadcaster (or inline in routes):
```python
await broadcaster.broadcast({
    "type": "airport_switch_complete",
    "data": { "config": config, "source": source, "icaoCode": icao_code, ... }
})
```

### 2. `app/frontend/src/hooks/useAirportConfig.ts` — Handle 202 + WS completion

Update `loadAirport` (~line 275):
- On 202: set `isLoading=true`, set `currentAirport` to new ICAO code, but don't update config yet. Return without error.
- On 200 (backward compat): keep existing behavior (update config from response body)
- On error: keep existing error handling

Update WS listener (~line 167):
- Add handler for `airport_switch_complete` message:
  - Update config state from `msg.data.config`
  - Set `currentAirport` from `msg.data.icaoCode`
  - Set `isLoading = false`
  - Cache the config
- Update existing `airport_switch_progress` handler:
  - When `done=true` (success or error): set `isLoading = false`

### 3. Frontend error recovery

When WS reports error (`airport_switch_progress` with `error=true`, `done=true`):
- Set `isLoading = false`
- Set error from the message
- Revert `currentAirport` to previous value (the backend rolls back too)

---

## Files to modify

| File | Changes |
|------|---------|
| `app/backend/api/routes.py` (~865-1050) | Refactor activate to return 202, run work in background task, broadcast completion via WS |
| `app/backend/api/websocket.py` | No changes needed — existing `broadcast()` method handles any message type |
| `app/frontend/src/hooks/useAirportConfig.ts` (~275-317, ~167-200) | Handle 202 response, add `airport_switch_complete` WS handler, clear loading on WS done |

---

## Verification

1. `uv run pytest tests/test_airport_config_routes.py -v` — activation route tests (update expectations for 202)
2. `cd app/frontend && npm test -- --run` — frontend tests
3. Deploy and test manually:
   - Switch to cached airport → should return 202, complete via WS quickly
   - Switch to uncached airport → should return 202 instantly, WS progress shows loading, completes when OSM fetch finishes
   - Verify no proxy timeout (HTTP returns in <100ms regardless of OSM fetch time)

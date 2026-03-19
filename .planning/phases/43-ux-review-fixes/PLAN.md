# Plan: Fix Phase 42 UX Review Issues

## Context

Phase 42 deployed UX review found 17 issues across 4 severity levels. The most critical is airport switching permanently corrupting backend state. This plan fixes issues in priority order across 4 waves. Full review: `.planning/phases/42-ux-review-deployed/PLAN.md`.

---

## Wave 1: Physics & Display Fixes

### 1a. Velocity safety guard at end of `_update_flight_state()`

**File:** `src/ingestion/fallback.py` (~line 3185, after existing altitude/heading guards)

Add velocity guards for ground phases. PARKED already sets 0 (line 2781), but as a safety net:

```python
# After line 3185 (heading normalization)
if state.phase in (FlightPhase.TAXI_TO_GATE, FlightPhase.TAXI_TO_RUNWAY):
    state.velocity = min(state.velocity, TAXI_SPEED_STRAIGHT_KTS)
elif state.phase == FlightPhase.PARKED:
    state.velocity = 0.0
    state.vertical_rate = 0.0
```

### 1b. Gate recommendations — only for descending flights

**File:** `app/frontend/src/components/FlightDetail/FlightDetail.tsx:78-80`

Replace:
```tsx
const needsGateAssignment =
  selectedFlight?.flight_phase === 'descending' ||
  (selectedFlight?.flight_phase === 'ground' && !selectedFlight?.assigned_gate);
```

With:
```tsx
const needsGateAssignment =
  selectedFlight?.flight_phase === 'descending';
```

Ground flights either have a gate (PARKED/TAXI_TO_GATE) or are departing. Recs only make sense for incoming flights pre-arrival.

### 1c. Last Seen timestamp — fix Unix seconds vs milliseconds

**File:** `app/frontend/src/components/FlightDetail/FlightDetail.tsx:353`

Backend sends `last_seen` as Unix seconds (`fallback.py:3353`). Frontend does `new Date(last_seen)` expecting milliseconds -> shows 1970 dates.

Replace:
```tsx
<DetailRow label="Last Seen" value={new Date(last_seen).toLocaleTimeString()} />
```

With:
```tsx
<DetailRow label="Last Seen" value={
  typeof last_seen === 'number'
    ? new Date(last_seen * 1000).toLocaleTimeString()
    : new Date(last_seen).toLocaleTimeString()
} />
```

---

## Wave 2: Airport Switch Atomicity

### 2a. Make `activate_airport` transactional with rollback

**File:** `app/backend/api/routes.py:821-922`

**Problem:** If any step fails after state modification begins, the backend stays in a corrupted half-switched state. Page reload doesn't fix it — the singleton holds the bad state until app restart.

**Changes:**
1. Import `_airport_center` and `get_current_airport_iata` from fallback
2. Save pre-switch state (config, center, iata) before modifying anything
3. Wrap steps 1-3 in try/except
4. On failure: restore previous airport center, re-initialize previous config, reload previous gates
5. For airports not in `AIRPORT_COORDINATES`: compute center from OSM config `center` field as fallback
6. Clear `_prev_flights` on broadcaster after reset to force full update (not deltas from old airport)

```python
async def activate_airport(icao_code: str, ...) -> dict:
    service = get_airport_config_service()

    # Save rollback state
    prev_iata = get_current_airport_iata()
    prev_center = get_airport_center()  # Need to expose this getter
    prev_icao = f"K{prev_iata}" if len(prev_iata) == 3 else prev_iata

    try:
        # Step 1: Load config (may fail on OSM timeout)
        await broadcaster.broadcast_progress(1, total_steps, "Loading...", icao_code)
        loaded = await asyncio.to_thread(service.initialize_from_lakehouse, ...)
        if not loaded:
            raise HTTPException(404, ...)

        config = service.get_config()

        # Step 2: Reload gates + ML
        await broadcaster.broadcast_progress(2, total_steps, "Reloading gates...", icao_code)
        gates = reload_gates()
        registry.retrain(icao_code)
        prediction_service.set_airport(icao_code)

        # Step 3: Set center — with fallback to OSM config center
        await broadcaster.broadcast_progress(3, total_steps, "Resetting...", icao_code)
        iata_code = _icao_to_iata(icao_code)
        if iata_code in AIRPORT_COORDINATES:
            lat, lon = AIRPORT_COORDINATES[iata_code]
        elif config.get("center"):
            lat = config["center"]["latitude"]
            lon = config["center"]["longitude"]
        else:
            raise ValueError(f"No coordinates available for {icao_code}")

        set_airport_center(lat, lon, iata_code)
        reset_result = reset_synthetic_state()

        # Force full WS update (clear delta cache)
        broadcaster._prev_flights.clear()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Airport switch to {icao_code} failed, rolling back: {e}")
        # Rollback
        try:
            await asyncio.to_thread(
                service.initialize_from_lakehouse,
                icao_code=prev_icao, fallback_to_osm=True,
            )
            reload_gates()
            set_airport_center(prev_center[0], prev_center[1], prev_iata)
            reset_synthetic_state()
            broadcaster._prev_flights.clear()
        except Exception as rb_err:
            logger.error(f"Rollback failed: {rb_err}")
        raise HTTPException(500, detail=f"Airport switch failed: {e}")

    # ... rest unchanged (background data gen, return config)
```

Also add `get_airport_center()` getter in `fallback.py`:
```python
def get_airport_center() -> tuple[float, float]:
    return _airport_center
```

### 2b. Frontend: handle switch error in useFlights WebSocket

**File:** `app/frontend/src/hooks/useFlights.ts` (~line 48, in `ws.onmessage`)

When receiving `airport_switch_progress` with `error: true`, clear the flights map so stale data from the old airport doesn't show:

```typescript
if (msg.type === 'airport_switch_progress') {
  const progress = (msg as any).data;
  if (progress.error) {
    // Switch failed — don't keep stale flights from partial switch
    flightsMapRef.current = new Map();
    setWsData({ flights: [], count: 0, timestamp: new Date().toISOString(), data_source: 'synthetic' });
  }
  return;
}
```

---

## Wave 3: Data Quality

### 3a. Console duplicate keys in AirportOverlay

**File:** `app/frontend/src/components/Map/AirportOverlay.tsx:254`

The hardcoded gates section uses `key={${label}-${showGateLabels}}` which can collide if multiple gates share the same label.

Fix:
```tsx
key={`hardcoded-${index}-${label}-${showGateLabels}`}
```

(Line 223 OSM gates already use index — no change needed there.)

### 3b. NaN flight filtering

**File:** `app/frontend/src/hooks/useFlights.ts` (in WebSocket full update handler, ~line 77)

Filter flights with invalid data before adding to map:

```typescript
for (const f of fullMsg.data.flights) {
  // Skip flights with no callsign (raw ICAO hex) or NaN values
  if (!f.callsign?.trim() || f.callsign === f.icao24) continue;
  if (f.altitude !== null && f.altitude !== undefined && isNaN(Number(f.altitude))) continue;
  map.set(f.icao24, f);
}
```

---

## Wave 4: Polish

### 4a. Airline name lookup expansion

**File:** `src/ingestion/fallback.py` (in `_AIRLINE_NAMES` dict, search for it)

Add missing entries:
```python
"CSN": "China Southern",
"CZ": "China Southern",   # IATA prefix
"HAL": "Hawaiian Airlines",
"MXA": "Mexicana",
"ACA": "Air Canada",
```

### 4b. Invalid gate name filtering

**File:** `src/formats/osm/converter.py`

During gate extraction, filter out gates where the ref/name is purely numeric and > 999 (likely OSM way/node IDs). Real gate numbers are typically < 200 or have letter prefixes.

### 4c. Flight count env var

**File:** Check `app.yaml` — if `DEMO_FLIGHT_COUNT` is set to 50, remove it or update to 100. The code default in `demo_config.py:17` should already be 100 from Phase 21.

---

## Files Modified

| File | Wave | Changes |
|------|------|---------|
| `src/ingestion/fallback.py` | 1a, 2a, 4a | Velocity guard, `get_airport_center()`, airline names |
| `app/frontend/src/components/FlightDetail/FlightDetail.tsx` | 1b, 1c | Gate rec simplification, Last Seen fix |
| `app/backend/api/routes.py` | 2a | Transactional airport switch with rollback |
| `app/frontend/src/hooks/useFlights.ts` | 2b, 3b | Switch error handling, NaN filter |
| `app/frontend/src/components/Map/AirportOverlay.tsx` | 3a | Unique hardcoded gate keys |
| `src/formats/osm/converter.py` | 4b | Filter invalid gate names |

---

## Verification

1. `uv run pytest tests/ -v -x --ignore=tests/test_airport_persistence.py` — all pass
2. `cd app/frontend && npm test -- --run` — all pass
3. `./dev.sh` locally:
   - Ground flights at gate: velocity = 0, no gate recommendations
   - Last Seen shows current time (not 1970)
   - Flight list: no NaN entries or raw ICAO hex
   - Console: no duplicate key warnings
4. Deploy + test airport switch:
   - SFO -> LAX: succeeds cleanly or rolls back with error, no corrupted state
   - Reload page after failed switch: should show correct airport
   - FIDS: shows reasonable ETAs for approaching flights

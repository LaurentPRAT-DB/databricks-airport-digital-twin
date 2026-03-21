# Plan: Performance Optimization (Priority 1 + 2)

**Phase:** 17 — Post-v1
**Date:** 2026-03-12
**Status:** Not yet implemented

---

## Context

Performance audit identified 6 improvements across two priority tiers. GZip middleware is already enabled (`app/backend/main.py:174`), so task 1 shifts to server-side field trimming and client-side caching. The other 5 items are straightforward.

---

## Priority 1 — High Impact, Easy Fix

### 1. Trim + cache `/api/airport/config` response (~668KB → much smaller)

GZip already compresses the response (`GZipMiddleware` at `main.py:174`). Focus on:

**A. Server-side:** trim unused OSM fields in `app/backend/api/routes.py` `get_airport_config()` (line 434)
- The endpoint returns `service.get_config()` raw — the entire internal dict including verbose fields the frontend never uses (e.g. full OSM metadata, raw tags, source provenance).
- Add a `_slim_config()` helper that strips heavy fields:
  - Remove `osmTaxiways[].tags`, `osmAprons[].tags`, `osmRunways[].tags`, `terminals[].tags`
  - Remove `gates[].tags` (keep only `id`, `ref`, `name`, `geo`)
  - Remove `geoPolygon` coordinate precision beyond 6 decimals
  - Remove `source`, `osmId`, and any other metadata fields not used by frontend

**B. Client-side:** cache config per airport in `app/frontend/src/hooks/useAirportConfig.ts`
- In `refresh()` (line 200): after a successful fetch, store result in a `Map<string, ConfigResponse>` keyed by `currentAirport`.
- Before fetching, check the cache. If the airport is already cached, use it (skip the network call).
- In `loadAirport()`: invalidate the cache entry for that airport on activation (since activation resets state).

### 2. Merge congestion + bottleneck into one endpoint

**Backend:** `app/backend/api/predictions.py`
- Add new endpoint `GET /api/predictions/congestion-summary` that returns both areas (all congestion) and bottlenecks (high+critical subset) in a single response.
- Keep existing separate endpoints for backward compat but the frontend will use the merged one.

Response model:
```python
class CongestionSummaryResponse(BaseModel):
    areas: List[CongestionResponse]
    bottlenecks: List[CongestionResponse]
    areas_count: int
    bottlenecks_count: int
```

Implementation: call `get_congestion()` once, then filter for bottlenecks from the same result (avoid calling `get_bottlenecks()` separately since it re-fetches flights).

**Frontend:** `app/frontend/src/hooks/usePredictions.ts`
- Replace `useCongestion()` hook (line 163) to use the single `/api/predictions/congestion-summary` endpoint.
- One `useQuery` call instead of two, returning both congestion and bottlenecks.

### 3. Increase prediction polling intervals

**Frontend:** `app/frontend/src/hooks/usePredictions.ts`
- `usePredictions` (line 70): change `refetchInterval: 10000` → `30000`
- `useDelayPrediction` (line 106): change `refetchInterval: 10000` → `30000`
- `useCongestion` (after merge): set `refetchInterval: 30000`
- Adjust `staleTime` proportionally (e.g. 25000)

---

## Priority 2 — Medium Impact

### 4. Prefetch Three.js bundle

**File:** `app/frontend/src/App.tsx`

Trigger a dynamic `import()` of the Map3D chunk after the 2D view renders (preload on idle):

```tsx
useEffect(() => {
  // Prefetch 3D bundle after initial render
  const timer = setTimeout(() => {
    import('./components/Map3D').catch(() => {});
  }, 3000);
  return () => clearTimeout(timer);
}, []);
```

This is simpler than a Vite plugin and doesn't depend on knowing the chunk hash.

### 5. Guard against Invalid LatLng on cold start

**File:** `app/frontend/src/components/Map/AirportMap.tsx` (line 126)
- Filter flights with undefined/NaN coordinates before rendering markers:
```tsx
{flights
  .filter((f) => f.latitude != null && f.longitude != null && !isNaN(f.latitude) && !isNaN(f.longitude))
  .map((flight) => (
    <FlightMarker key={flight.icao24} flight={flight} />
  ))}
```

**File:** `app/frontend/src/components/Map/FlightMarker.tsx` (line 81)
- Add an early return if coordinates are invalid (defense in depth):
```tsx
if (flight.latitude == null || flight.longitude == null || isNaN(flight.latitude) || isNaN(flight.longitude)) {
  return null;
}
```

### 6. Add ARIA labels to map markers

**File:** `app/frontend/src/components/Map/FlightMarker.tsx`
- Modify `createAirplaneIcon()` to include `role="img"` and `aria-label="..."` on the SVG element itself:

```tsx
const svgIcon = `
  <svg xmlns="..." viewBox="..." fill="${color}" width="24" height="24"
       style="transform: rotate(${rotation}deg);"
       role="img" aria-label="Flight ${callsign || icao24}">
    <path d="M12 2L4 14h3l1 8h8l1-8h3L12 2z"/>
  </svg>
  ${gateLabel}
`;
```

Pass `callsign` and `icao24` to `createAirplaneIcon()`.

**File:** `app/frontend/src/components/Map/AirportOverlay.tsx`
- Focus on `FlightMarker` which uses `L.divIcon` that generates `<div>` elements acting as buttons. Gate `CircleMarker` renders SVG paths and already has Tooltip providing accessible text.

---

## Files Modified

| File | Changes |
|---|---|
| `app/backend/api/predictions.py` | Add `CongestionSummaryResponse` model + `/congestion-summary` endpoint |
| `app/backend/api/routes.py` | Add `_slim_config()` to trim OSM metadata from config response |
| `app/frontend/src/hooks/usePredictions.ts` | Merge congestion+bottleneck fetch, increase polling to 30s |
| `app/frontend/src/hooks/useAirportConfig.ts` | Add per-airport config cache |
| `app/frontend/src/App.tsx` | Add idle prefetch of 3D bundle |
| `app/frontend/src/components/Map/AirportMap.tsx` | Filter invalid LatLng flights |
| `app/frontend/src/components/Map/FlightMarker.tsx` | Guard invalid coords + add ARIA labels to SVG |
| `app/frontend/src/components/Map/AirportOverlay.tsx` | Add ARIA labels to gate markers |

---

## Verification

1. Backend tests: `uv run pytest tests/test_airport_config_routes.py tests/ -k prediction -v`
2. Frontend tests: `cd app/frontend && npm test -- --run`
3. Manual check: `./dev.sh`, open `http://localhost:3000`
   - Network tab: verify `/api/airport/config` response is smaller
   - Network tab: verify single `/api/predictions/congestion-summary` call every 30s (not 2 calls every 10s)
   - Console: no `Invalid LatLng` errors on cold start
   - Switch to 3D and back: verify 3D loads faster (chunk was prefetched)
   - Lighthouse accessibility: verify flight markers have accessible names

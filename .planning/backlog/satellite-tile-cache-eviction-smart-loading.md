# Satellite Tile Cache Eviction — Smart Cache-First Loading + Staleness Notification

## Context

When the user enables satellite view with Clean Tiles (inpainting), every tile request goes through the full pipeline: HEAD for ETag -> check Lakebase cache -> on miss, fetch tile + call serving endpoint + cache result. This means:

1. If the serving endpoint is cold/down, tiles fail even when cached versions exist in Lakebase
2. No distinction between "no cache" and "stale cache" (ETag mismatch) — both trigger full inpainting
3. No user notification when satellite imagery has been updated but cached tiles are from older imagery

**Goal:** Add cache-first tile loading. When inpainting is enabled, prefer cached tiles from Lakebase. Only trigger the full inpainting pipeline on true cache misses. Detect and notify when cached tiles are stale (satellite imagery updated by Esri). This avoids redundant inpainting work and makes the feature usable even when the serving endpoint is unavailable.

## Files to modify

1. `app/backend/api/inpainting.py` — Add `cache_only` query param to clean-tile
2. `app/frontend/src/components/Map/AirportMap.tsx` — Two-phase tile loading + stale tracking
3. `app/frontend/src/components/Map3D/SatelliteGround.tsx` — Same two-phase logic for 3D
4. `app/frontend/src/App.tsx` — Stale tile notification in ViewToggle area

## Backend: `cache_only` parameter on clean-tile

**File:** `app/backend/api/inpainting.py`, clean-tile endpoint (~line 206)

Add `cache_only: bool = Query(False)` parameter. When `cache_only=True`:
- Still do HEAD for ETag (freshness check)
- Check Lakebase cache with ETag -> if HIT, return as usual (`X-Cache: HIT`)
- If ETag mismatch (stale): call `get_cached_tile(z, tx, ty, source_etag=None)` to get the stale version. Return it with `X-Cache: STALE` header
- If no cache at all: return 204 No Content with `X-Cache: MISS` header
- Never call the serving endpoint

This is a ~15-line change in the existing endpoint, gated behind the `cache_only` flag. No changes to `lakebase_service.py` needed — we just call `get_cached_tile` twice: once with ETag (fresh check), once without (get stale version).

```python
@inpainting_router.post("/clean-tile")
async def clean_tile(
    request: Request,
    url: Optional[str] = Query(None),
    airport_icao: Optional[str] = Query(None),
    cache_only: bool = Query(False, description="Only check cache, never call inpainting"),
    file: Optional[UploadFile] = File(None),
):
    # ... existing HEAD + cache check ...

    # After fresh cache check fails:
    if cache_only and tile_coords:
        z, tx, ty = tile_coords
        # Try returning stale cached tile
        stale = lakebase.get_cached_tile(z, tx, ty, source_etag=None)
        if stale:
            return Response(
                content=stale["image_bytes"],
                media_type="image/png",
                headers={"X-Cache": "STALE", "X-Aircraft-Count": str(stale["aircraft_count"])},
            )
        return Response(status_code=204, headers={"X-Cache": "MISS"})

    # ... existing full inpainting flow unchanged ...
```

## Frontend 2D: Two-phase tile loading

**File:** `app/frontend/src/components/Map/AirportMap.tsx`, InpaintingGridLayer (~line 178)

Change `createTile` to do two-phase loading:
1. **Phase 1 (fast):** POST with `cache_only=true`. If 200 -> use tile. Read `X-Cache` header.
2. **Phase 2 (on miss):** If 204 -> POST without `cache_only` (full inpaint, current behavior)
3. **Stale tracking:** Pass `onStaleDetected` callback via layer options. Increment counter when `X-Cache: STALE`.

```typescript
const InpaintingGridLayer = L.GridLayer.extend({
  createTile(coords, done) {
    const tile = document.createElement('img');
    // ... setup tile, build URL ...

    // Phase 1: cache-only
    const cacheParams = new URLSearchParams(params);
    cacheParams.set('cache_only', 'true');

    fetch(`/api/inpainting/clean-tile?${cacheParams}`, { method: 'POST' })
      .then(resp => {
        const cacheStatus = resp.headers.get('X-Cache');
        if (resp.ok) {
          // HIT or STALE — use the tile
          if (cacheStatus === 'STALE') {
            (this.options as any).onStaleDetected?.();
          }
          return resp.blob().then(blob => { /* set tile.src */ });
        }
        if (resp.status === 204) {
          // No cache — Phase 2: full inpaint
          return fetch(`/api/inpainting/clean-tile?${params}`, { method: 'POST' })
            .then(r => r.ok ? r.blob() : Promise.reject())
            .then(blob => { /* set tile.src */ });
        }
        throw new Error('Unexpected');
      })
      .catch(() => done(null, tile)); // fallback to raw Esri
  },
});
```

Update `InpaintingTileLayer` React wrapper to accept and forward `onStaleDetected` callback:

```typescript
function InpaintingTileLayer({ airportIcao, onStaleDetected }: {
  airportIcao?: string;
  onStaleDetected?: () => void;
}) {
  // ... pass onStaleDetected through layer options ...
}
```

## Frontend 3D: Same two-phase logic

**File:** `app/frontend/src/components/Map3D/SatelliteGround.tsx`, `loadTileImage` (~line 104)

Same pattern: add `cache_only=true` first request, fallback to full inpaint on 204. Pass stale count up via `onLoadingProgress` (extend `TileLoadingProgress` to include `staleCount`).

## Frontend: Stale notification

**File:** `app/frontend/src/App.tsx`, ViewToggle component (~line 429)

Track stale tile count in state. Show a small amber warning banner below the existing cache stats:

```
[Refresh Tiles]
```

Uses the same styling pattern as the existing endpoint status banner and cache stats display. The "Refresh Tiles" button triggers the existing `handleRefreshTiles()` which clears cache and toggles inpainting.

State:
```typescript
const [staleTileCount, setStaleTileCount] = useState(0);
// Reset on inpainting toggle, airport switch
// Increment via onStaleDetected callback from InpaintingGridLayer
```

The stale notification is only shown when `staleTileCount > 0 && inpainting && satellite`.

## Verification

```bash
# 1. Python tests (ensure backend changes don't break existing flow)
uv run pytest tests/ -x -q -k "not test_live"

# 2. Frontend tests
cd app/frontend && npm test -- --run

# 3. Manual test — cache_only endpoint
# Start local server, then:
curl -X POST "http://localhost:8000/api/inpainting/clean-tile?url=https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/17/52486/21218&cache_only=true" -v
# Should return X-Cache: HIT/STALE/MISS

# 4. Build + deploy
cd app/frontend && npm run build && cd ../..
databricks bundle deploy --target dev

# 5. Visual test
# - Enable Satellite + Clean Tiles
# - Note tiles load from cache (fast) — check X-Cache headers in Network tab
# - If stale tiles exist, amber notification should appear
# - Click "Refresh Tiles" → full re-inpaint
```

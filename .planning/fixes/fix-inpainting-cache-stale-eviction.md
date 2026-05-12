---
status: planned
area: inpainting
related:
  - app/frontend/src/components/Map/AirportMap.tsx
  - app/frontend/src/components/Map3D/SatelliteGround.tsx
  - app/backend/services/lakebase_service.py
  - app/backend/api/inpainting.py
  - app/frontend/src/App.tsx
---

# Fix Inpainting Cache: Stale Tile Re-processing & Eviction

## Context

The inpainting pipeline (YOLO aircraft detection + LaMa removal) has a working serving endpoint
(airport-dt-aircraft-inpainting-dev, READY but scaled-to-zero) and a Lakebase cache
(satellite_tile_cache table). The cache uses Esri ETag headers to detect when satellite imagery
has been updated.

**Problem:** When satellite imagery updates (ETag mismatch), the frontend detects the stale tile but
never triggers re-processing. Both the 2D (Leaflet InpaintingGridLayer) and 3D
(SatelliteGround.tsx) two-phase loading:
1. Phase 1 (cache_only=true): Returns stale cached tile if ETag mismatches → displays it, fires
   onStaleDetected
2. Phase 2: Only triggers on 204 MISS (no cached version at all)

**Result:** stale tiles stay stale forever until the user manually clicks "Refresh" in the UI.

**Secondary issue:** No cache eviction — tiles accumulate unbounded in Lakebase with no TTL or size
limit.

## Plan

### 1. Frontend: Background re-inpaint on STALE (both 2D and 3D)

When Phase 1 returns STALE, show it immediately (good UX — fast load), then fire a background
Phase 2 request to re-inpaint and update the cache. When the background request returns, swap in
the fresh tile.

Files:
- `app/frontend/src/components/Map/AirportMap.tsx` (~line 225-250)
- `app/frontend/src/components/Map3D/SatelliteGround.tsx` (~line 139-172)

2D (Leaflet) change — in InpaintingGridLayer.createTile:
```typescript
if (resp.headers.get('X-Cache') === 'STALE') {
  opts.onStaleDetected?.();
  // Show stale tile immediately
  resp.blob().then(loadBlob);
  // Background re-inpaint — fire and replace when ready
  fetch(`/api/inpainting/clean-tile?${params.toString()}`, { method: 'POST' })
    .then(r => r.ok ? r.blob() : null)
    .then(blob => { if (blob) loadBlob(blob); });
  return;
}
```

3D (SatelliteGround) change — in loadTileImage:
When isStale is true, resolve with the stale image but also kick off a non-blocking re-inpaint
fetch. On success, update the canvas tile in-place and flag the texture as needsUpdate.

### 2. Backend: Add TTL-based eviction

Add a periodic cleanup that removes tiles older than a configurable max age (default 30 days). Run
on cache access (probabilistic, ~1% of reads trigger cleanup — similar to PHP session GC).

File: `app/backend/services/lakebase_service.py` (after get_tile_cache_stats)

Add method:
```python
def _maybe_evict_stale_tiles(self, max_age_days: int = 30, probability: float = 0.01):
    """Probabilistic eviction of tiles older than max_age_days."""
    import random
    if random.random() > probability:
        return
    # DELETE FROM satellite_tile_cache WHERE updated_at < NOW() - INTERVAL '{max_age_days} days'
```

Call from get_cached_tile at the end (after the cache check, regardless of hit/miss).

### 3. Backend: Force-reprocess endpoint

Add a POST `/api/inpainting/reprocess` endpoint that:
- Queries all tiles for a given airport (or all) where current Esri ETag doesn't match
  original_etag
- Queues them for re-inpainting (or immediately processes in batch if endpoint is warm)

This gives the frontend "Refresh" button a way to force full reprocessing, not just cache
clearing.

File: `app/backend/api/inpainting.py`

New endpoint:
```python
@inpainting_router.post("/reprocess")
async def reprocess_stale_tiles(request, airport_icao=None):
    # 1. Get all cached tile URLs for the airport
    # 2. HEAD each to get current ETag
    # 3. Compare with stored ETag
    # 4. For mismatches: re-fetch, re-inpaint, update cache
```

### 4. Frontend: Wire "Refresh" to reprocess instead of clear+toggle

Currently handleRefreshTiles deletes the cache then toggles inpainting off/on. Instead, call
`/api/inpainting/reprocess` which preserves valid cached tiles and only re-processes stale ones.

File: `app/frontend/src/App.tsx` (~line 369-381)

## Files to Modify

| File | Change |
|------|--------|
| `app/frontend/src/components/Map/AirportMap.tsx` | Background re-inpaint on STALE in 2D tile layer |
| `app/frontend/src/components/Map3D/SatelliteGround.tsx` | Background re-inpaint on STALE in 3D tile loader |
| `app/backend/services/lakebase_service.py` | Add `_maybe_evict_stale_tiles()` method |
| `app/backend/api/inpainting.py` | Add POST `/reprocess` endpoint + wire eviction |
| `app/frontend/src/App.tsx` | Wire refresh button to `/reprocess` |

## Verification

1. **Unit tests:** Run `uv run pytest tests/test_inpainting_pipeline.py -v` (existing tests still pass)
2. **Frontend tests:** `cd app/frontend && npm test -- --run` (no regressions)
3. **Manual check:** With endpoint scaled-to-zero, verify:
   - `/api/inpainting/status` shows READY + scaled-to-zero
   - Cache_only requests return STALE when ETags differ
   - Background re-inpaint fires after stale tile is shown
4. **Eviction:** Insert a tile with old `updated_at`, verify it gets cleaned up

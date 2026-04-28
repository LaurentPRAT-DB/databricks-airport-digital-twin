---
status: backlog
area: frontend
related: []
---

# Plan: Improve Clean Tiles UX: Background Processing + Cache Status

**Status:** Backlog
**Date added:** 2026-04-06
**Scope:** Frontend progress indicator + cache status display + refresh option + backend cache clear endpoint

---

## Context

When the user clicks "Clean Tiles" in satellite view and the inpainting endpoint is ready (green), nothing visible happens — no progress indication, no feedback. The tiles are cleaned one-by-one as Leaflet requests them via the `InpaintingGridLayer`, but the user has no way to know processing is happening or when it's done.

The user wants:

1. Visual feedback when tile cleaning is in progress (processing indicator)
2. Background processing — clean visible tiles proactively so subsequent views show cached results
3. Cache status info — show when tiles were last cached in Lakebase, small text for context
4. Pull latest — option to refresh/re-fetch satellite tiles (invalidate cache)

## Current Architecture

- **Frontend button:** `handleCleanTilesClick()` in ViewToggle (`App.tsx:181`) toggles the inpainting state
- **Frontend tile layer:** `InpaintingGridLayer` (`AirportMap.tsx:178`) fetches tiles through `/api/inpainting/clean-tile` per tile, with Lakebase cache
- **Backend endpoint:** `/api/inpainting/clean-tile` (`inpainting.py:196`) — checks cache, fetches tile, calls serving endpoint, caches result
- **Backend cache stats:** `/api/inpainting/cache-stats` (`inpainting.py:186`) — returns tile count, airports, size, dates
- **Backend status:** `/api/inpainting/status` (`inpainting.py:79`) — endpoint health + cache stats

## Plan

### 1. Add Processing Progress Indicator to Clean Tiles Button Area

**File:** `app/frontend/src/App.tsx` — ViewToggle component

When inpainting is enabled, show a small progress/status line below the buttons:

- Poll `/api/inpainting/cache-stats` every 5s while inpainting is active
- Show: "Cleaning tiles... {total_tiles} cached" with a spinner while new tiles are being added
- When tiles stop increasing: "Cleaned — {total_tiles} tiles cached ({cache_size})"
- Show last cached date in small text: "Last cached: {newest_tile}"
- Stop polling when inpainting is turned off

### 2. Add "Refresh Tiles" Option

**File:** `app/frontend/src/App.tsx` — ViewToggle component

When inpainting is active and tiles are cached, show a small "Refresh" button that:

- Calls a new backend endpoint to invalidate cache for current airport
- Toggles inpainting off then on to force re-fetch

**File:** `app/backend/api/inpainting.py` — new endpoint

Add `DELETE /api/inpainting/cache?airport_icao={icao}` to clear cached tiles for an airport.

**File:** `app/backend/services/lakebase_service.py` — new method

Add `clear_tile_cache(airport_icao: Optional[str])` method to delete rows from `satellite_tile_cache`.

### 3. Show Cache Metadata in the Status Area

When inpainting is active, display below the buttons:

- **Line 1** (during processing): spinner + "Processing tiles..." or check + "{N} tiles cleaned"
- **Line 2** (always when cached): small grey text "Cached {date} · {cache_size}"
- **Line 3** (when cached): small "Refresh" link

## Files Modified

| File | Change |
|------|--------|
| `app/frontend/src/App.tsx` | ViewToggle: add cache stats polling, progress indicator, refresh button |
| `app/backend/api/inpainting.py` | Add `DELETE /api/inpainting/cache` endpoint |
| `app/backend/services/lakebase_service.py` | Add `clear_tile_cache()` method |

## Verification

1. `cd app/frontend && npx tsc --noEmit` — no type errors
2. `cd app/frontend && npm test -- --run` — all tests pass
3. `uv run pytest tests/ -v -k inpainting` — backend tests pass
4. Manual: enable satellite + clean tiles, observe progress indicator, verify cache stats display, test refresh

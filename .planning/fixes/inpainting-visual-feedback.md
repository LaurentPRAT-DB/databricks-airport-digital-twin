---
status: done
area: frontend
related: [inpainting, satellite, leaflet, ux]
---

# Inpainting Visual Feedback — Processing Pipeline Visibility

## Context

The inpainting feature removes aircraft from satellite tiles using YOLO detection + LaMa inpainting on a Databricks serving endpoint. Currently when active, the only feedback is a static text "Inpainting active — pan or zoom to process tiles". Users can't see:
- Which tile is currently being processed
- What aircraft were detected (bounding boxes)
- The before/after transition when inpainting completes
- Cache hit/miss details per tile (coordinates, zoom, timestamp)

The backend already returns rich metadata in response headers (`X-Detections`, `X-Aircraft-Count`, `X-Cache`, `X-Processing-Ms`) but the frontend discards all of it. This change surfaces that data as visual overlays on the 2D Leaflet map.

## Scope

2D map only (`AirportMap.tsx` + new overlay component). No changes to 3D view or backend.

## Plan

### 1. Create `InpaintingOverlay` component
**New file:** `app/frontend/src/components/Map/InpaintingOverlay.tsx`

A Leaflet overlay that renders visual feedback for inpainting activity. Uses `useMap()` to draw on the map. Manages a list of `TileEvent` objects that represent the lifecycle of each tile:

```ts
interface TileEvent {
  id: string;           // "z/x/y"
  bounds: L.LatLngBounds;  // tile geo bounds
  phase: 'loading' | 'detecting' | 'detected' | 'inpainting' | 'done' | 'cached';
  detections: Detection[];  // bounding boxes [{x1,y1,x2,y2,confidence}]
  aircraftCount: number;
  cacheStatus: 'HIT' | 'STALE' | 'MISS';
  processingMs?: number;
  zoom: number;
  tileX: number;
  tileY: number;
  timestamp: number;
}
```

Visual stages per tile:
1. **Loading** — pulsing blue border on the tile bounds ("processing frame")
2. **Detected** — red/orange bounding boxes drawn at detection coordinates within the tile, with confidence labels. Brief flash (~2s) so user sees what was found
3. **Done/Cached** — brief green border flash + small info badge (coordinates, cache status, time). Fades after 3s
4. **Cache HIT** — instant subtle green flash, no detection boxes (already processed), badge shows "CACHE HIT z/x/y"

### 2. Modify `InpaintingGridLayer` in `AirportMap.tsx`

Currently the `createTile` method ignores response headers. Changes:
- Parse `X-Detections`, `X-Aircraft-Count`, `X-Cache`, `X-Processing-Ms` from both the cache-only and full inpaint responses
- Call a new `onTileEvent` callback (passed via layer options) with tile coords + parsed metadata at each phase transition
- Convert tile pixel coordinates (x,y) to tile-relative positions for overlay rendering

The Esri tile coordinate `{z}/{y}/{x}` maps to geo bounds via standard slippy map math. We'll compute `L.LatLngBounds` from tile coords for the overlay rectangles.

### 3. Wire callbacks through `InpaintingTileLayer` → `AirportMap`

- `InpaintingTileLayer` React wrapper gets a new `onTileEvent` prop
- Pass it through to the GridLayer options
- `AirportMap` manages `tileEvents` state array
- Auto-expire old events (remove after 5s for "done", keep "cached" entries for the session in a log panel)

### 4. Add tile activity log to the cache status panel in `ViewToggle` (App.tsx)

Extend the existing cache status panel with a scrollable mini-log showing recent tile events:
```
✓ 17/23451/34212 — CACHE HIT — 0 aircraft — 12ms
⚡ 17/23452/34212 — MISS — 2 aircraft detected — 1,847ms  
⚡ 17/23453/34212 — MISS — 0 aircraft — 923ms
```

Each line shows: zoom/x/y, cache status, aircraft count, processing time. New entries animate in. This gives the user concrete evidence that caching works and lets them verify by coordinates + zoom level.

### 5. Helper: tile coords ↔ lat/lon conversion

Add utility functions (in `InpaintingOverlay.tsx` or a small utils file) for:
- `tileToLatLngBounds(x, y, z)` — convert tile indices to Leaflet bounds
- `detectionToLatLng(det, tileBounds, tileSize)` — convert pixel-space detection box to map coordinates

These exist in `SatelliteGround.tsx` for the 3D view but not for Leaflet. We'll adapt the same math.

## Files to modify

| File | Change |
|------|--------|
| `app/frontend/src/components/Map/InpaintingOverlay.tsx` | **NEW** — Leaflet overlay for tile borders + detection boxes + cache badges |
| `app/frontend/src/components/Map/AirportMap.tsx` | Parse response headers in `InpaintingGridLayer`, add `onTileEvent` callback, render `InpaintingOverlay`, wire state |
| `app/frontend/src/App.tsx` | Pass `onTileActivity` up from AirportMap, show tile log in cache status panel |

## Verification

1. `cd app/frontend && npm run build` — type-check + build passes
2. `cd app/frontend && npm test -- --run` — existing tests pass
3. Manual test on deployed dev app:
   - Enable satellite + clean tiles
   - Pan to a new area → see blue pulsing border on tiles being processed
   - After detection → see red boxes on aircraft for ~2s
   - After inpainting → green flash, then badge with "MISS z/x/y 1847ms"
   - Pan back to cached area → instant green flash with "HIT z/x/y"
   - Check tile activity log shows coordinates, zoom, cache status, timing

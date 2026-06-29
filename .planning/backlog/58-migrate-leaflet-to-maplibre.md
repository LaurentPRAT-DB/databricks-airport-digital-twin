# Plan: Migrate react-leaflet → react-map-gl + MapLibre GL JS

## Context

react-leaflet@4.2.1 and @react-leaflet/core@2.1.0 use Hippocratic 2.1 license (not OSI-approved) — blocks commercial deployment. Must replace with react-map-gl (MIT) + maplibre-gl (BSD-3-Clause). All their transitive deps are permissive.

Baseline: 1002 frontend tests pass, Map/ coverage 61% statements. Zero regressions allowed.

## Scope

6 files to rewrite (1486 LOC + 4 test files + 1 utility):
- `src/components/Map/AirportMap.tsx` (523 LOC) — map container, tile layers, camera control, zoom tracking
- `src/components/Map/AirportOverlay.tsx` (245 LOC) — airport geometry (polygons, polylines, circles)
- `src/components/Map/FlightMarker.tsx` (210 LOC) — aircraft markers with rotated SVG icons
- `src/components/Map/TrajectoryLine.tsx` (300 LOC) — trajectory polylines with color coding
- `src/components/Map/InpaintingOverlay.tsx` (208 LOC) — detection bounding boxes + status badges
- `src/utils/sceneCapture.ts` — 2D screenshot (queries .leaflet-container DOM)

Test files:
- AirportMap.test.tsx, AirportOverlay.test.tsx, FlightMarker.test.tsx, FlightMarkerHeading.test.tsx, TrajectoryLine.test.ts

Not changed: `useViewportState.ts` (no Leaflet imports — pure state hook).

## Key Migration Decisions

1. **Coordinate order:** MapLibre uses [lng, lat] (GeoJSON standard). Leaflet uses [lat, lng]. Create adapter to avoid pervasive errors.
2. **Markers:** Use MapLibre `<Marker>` component (renders arbitrary React children as HTML overlay). Keeps current SVG icon approach. No Symbol layer conversion needed — <200 markers.
3. **Geometries (polygons, polylines, circles):** Use `<Source type="geojson">` + `<Layer>` pairs. Convert existing [lat, lng][] data to GeoJSON [lng, lat][] at the boundary.
4. **InpaintingGridLayer (custom tile layer):** Use MapLibre's `addProtocol()` to intercept tile requests and route through inpainting API. The existing logic fetches tiles via fetch() and returns images — maps directly to protocol handler.
5. **Tooltips:** Use MapLibre `<Popup>` with hover state management. For permanent labels (gate names), use Symbol layer with text.
6. **Tile URL:** MapLibre doesn't support {s} subdomain placeholder. Use explicit URL array: `['https://a.tile.openstreetmap.org/{z}/{x}/{y}.png', 'https://b.tile...', 'https://c.tile...']`.
7. **Scene capture:** Replace `.leaflet-container` queries with `map.getCanvas()` for direct WebGL canvas export.

## Implementation Steps

### Step 1: Install deps, remove leaflet

```bash
npm install react-map-gl maplibre-gl --legacy-peer-deps
npm uninstall leaflet react-leaflet @react-leaflet/core @types/leaflet --legacy-peer-deps
```

→ verify: no leaflet in package.json deps

### Step 2: Create coordinate adapter utility

New file: `src/utils/mapCoords.ts`
- `toLngLat(lat, lng)` → `[lng, lat]` (for MapLibre)
- `toGeoJSON(positions: [lat, lng][])` → GeoJSON LineString/Polygon
- `boundsFromLatLngs(points)` → LngLatBoundsLike

→ verify: unit tests for adapter

### Step 3: Rewrite AirportMap.tsx

- `MapContainer` → `<Map>` from react-map-gl with controlled viewState
- `TileLayer` → `<Source type="raster" tiles={[...]}><Layer type="raster" /></Source>`
- `useMap()` → `useMap()` from react-map-gl (returns MapRef)
- `map.flyTo([lat, lng], zoom)` → `mapRef.flyTo({center: [lng, lat], zoom})`
- `map.flyToBounds(bounds)` → `mapRef.fitBounds([[swLng, swLat], [neLng, neLat]])`
- `map.getCenter()` → controlled viewState
- `map.on('moveend')` → `onMoveEnd` prop
- `useMapEvents({zoomend})` → `onZoomEnd` prop
- MapRecenter, MapViewportSaver, ZoomTracker, FlightFollower, MapControlExposer — refactor as effects within main component or small sub-components using mapRef

→ verify: map renders, flyTo works, zoom tracking works

### Step 4: Rewrite FlightMarker.tsx

- `<Marker position={[lat, lng]} icon={divIcon}>` → `<Marker longitude={lng} latitude={lat}><div>...</div></Marker>`
- Remove `L.divIcon` — render SVG HTML directly as Marker children
- Keep `createAirplaneIcon` logic but return JSX instead of DivIcon
- Click handler: `onClick` prop on Marker
- Tooltip: render on hover state

→ verify: aircraft render with rotation, click selects flight

### Step 5: Rewrite AirportOverlay.tsx

- `Polygon` → `<Source type="geojson" data={featureCollection}><Layer type="fill" .../><Layer type="line" .../></Source>`
- `Polyline` (runways, taxiways) → `<Source type="geojson"><Layer type="line" /></Source>`
- `CircleMarker` (gates) → `<Source type="geojson"><Layer type="circle" /></Source>`
- `useMapEvents({zoomend})` → get zoom from parent's viewState

→ verify: airport geometry renders correctly

### Step 6: Rewrite TrajectoryLine.tsx

- `Polyline` → `<Source type="geojson"><Layer type="line" /></Source>`
- Color coding via `paint: { 'line-color': ['match', ...] }` or multiple sources
- Coordinate flip: `[lat, lng][]` → `[lng, lat][]`

→ verify: trajectory lines render with correct colors

### Step 7: Rewrite InpaintingOverlay.tsx

- Custom tile layer → `addProtocol('inpainting', handler)` + `<Source type="raster" tiles={['inpainting://...']}>` 
- Detection bounding boxes → GeoJSON source with fill/line layers
- Status badges → Marker overlays

→ verify: inpainting tiles load, bounding boxes render

### Step 8: Update sceneCapture.ts

- Replace `.leaflet-container` DOM query with `mapRef.getMap().getCanvas()`
- Export canvas directly (WebGL → toDataURL)

→ verify: screenshot capture works

### Step 9: Update all test files

- Replace `vi.mock('react-leaflet', ...)` with `vi.mock('react-map-gl', ...)`
- Replace `vi.mock('leaflet', ...)` with `vi.mock('maplibre-gl', ...)`
- Update mock shapes (MapRef vs L.Map, controlled viewState vs imperative)
- Keep all existing test assertions — same behavior, different implementation

→ verify: `npm test -- --run` — all 1002 tests pass

### Step 10: Remove leaflet CSS and verify clean removal

- Remove `import 'leaflet/dist/leaflet.css'`
- Add `import 'maplibre-gl/dist/maplibre-gl.css'`
- Run: `grep -r "leaflet" src/ --include="*.ts" --include="*.tsx"` — must return empty
- Run license-checker — no Hippocratic licenses

→ verify: license audit clean, zero leaflet references

## Verification

1. `npm test -- --run` → 1002 tests pass (zero regression)
2. `npx vitest run --coverage` → Map/ coverage ≥ 60% (no degradation)
3. `npx license-checker --json | grep -i hippocratic` → empty
4. `grep -r "leaflet\|react-leaflet" src/ package.json` → empty (only in test mocks if any)
5. Visual: `./dev.sh` → http://localhost:3000 — map renders, aircraft visible, trajectory works, airport switch animates, inpainting overlay functions
6. Build: `npm run build` → succeeds without errors

# Plan: Remove Hardcoded SFO Coordinates, Use Dynamic Airport Center Everywhere

**Status:** Fix
**Date added:** 2026-04-06
**Scope:** Frontend constants refactor — replace SFO defaults with generic fallbacks

---

## Context

When switching to GVA, the 2D map briefly renders at SFO coordinates before flying to the correct location. Root cause: `AIRPORT_CENTER` (SFO) is used as `MapContainer`'s initial center. The broader problem is that SFO geo data is hardcoded across multiple files as "defaults" — this breaks the multi-airport design.

## Scope

Three categories of hardcoded SFO data:

| What | Where | Used by |
|------|-------|---------|
| `AIRPORT_CENTER` (SFO lat/lon) | `constants/airportLayout.ts:4` | ~~`AirportMap.tsx`~~ (already fixed) |
| `DEFAULT_CENTER_LAT/LON` | `utils/map3d-calculations.ts:13-14` | `useAirportConfig.ts` fallback, 3D coord conversion default params |
| `GATE_POSITIONS`, `airportLayout` GeoJSON | `constants/airportLayout.ts` | `AirportOverlay.tsx` (fallback when no OSM), separation tests |
| `AIRPORT_3D_CONFIG` (SFO runways/taxiways/buildings) | `constants/airport3D.ts` | `AirportScene.tsx`, `Map3D.tsx` (fallback when no OSM) |

Test files using SFO coords as fixtures are fine — they're test data, not config.

## Changes

### 1. Create `app/frontend/src/constants/defaults.ts` — single source of truth for fallback defaults

```typescript
/** Fallback center when no airport config is loaded (geographic center, zoom shows world) */
export const DEFAULT_CENTER_LAT = 0;
export const DEFAULT_CENTER_LON = 0;
export const DEFAULT_ZOOM = 14;
```

Use `[0, 0]` (null island) as fallback — makes it obvious when the real center hasn't loaded yet, rather than silently showing SFO. The `MapRecenter` component will immediately `flyToBounds` to the correct airport.

### 2. Update `utils/map3d-calculations.ts`

- Remove `DEFAULT_CENTER_LAT/LON` exports (lines 13-14)
- Import from `constants/defaults.ts` instead (only used as default params)

### 3. Update `hooks/useAirportConfig.ts`

- Import `DEFAULT_CENTER_LAT/LON` from `constants/defaults.ts`

### 4. Update `components/Map/AirportMap.tsx`

- Import `DEFAULT_ZOOM` from `constants/defaults.ts` instead of `airportLayout.ts` (already done: `AIRPORT_CENTER` removed)

### 5. Clean up `constants/airportLayout.ts`

- Remove `AIRPORT_CENTER` (no longer imported anywhere)
- Keep `DEFAULT_ZOOM` → move to `defaults.ts`, remove from here
- Keep separation utilities (`WAKE_CATEGORIES`, `getRequiredSeparationNM`, etc.) — these are generic, not SFO-specific
- Keep `GATE_POSITIONS` + `airportLayout` GeoJSON — still used as SFO fallback in `AirportOverlay.tsx` when no OSM data. Rename to `SFO_FALLBACK_LAYOUT` and `SFO_GATE_POSITIONS` to make clear this is a legacy SFO fallback, not a generic default.

### 6. `constants/airport3D.ts` — no change needed

- Already only used as fallback when no OSM data; all values are in 3D scene coordinates (not lat/lon), and `airportCenter` is always passed from `getAirportCenter()`.

## Files Modified

| File | Action |
|------|--------|
| `app/frontend/src/constants/defaults.ts` | Create — new single source of truth |
| `app/frontend/src/constants/airportLayout.ts` | Remove `AIRPORT_CENTER`, move `DEFAULT_ZOOM`, rename SFO-specific exports |
| `app/frontend/src/utils/map3d-calculations.ts` | Update imports |
| `app/frontend/src/hooks/useAirportConfig.ts` | Update imports |
| `app/frontend/src/components/Map/AirportMap.tsx` | Update imports (already partially done) |
| `app/frontend/src/components/Map/AirportOverlay.tsx` | Rename imports |
| Test files importing from `airportLayout.ts` or `map3d-calculations.ts` | Update import paths |

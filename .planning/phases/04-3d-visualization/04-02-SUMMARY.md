---
phase: 04-3d-visualization
plan: 02
subsystem: frontend-3d
tags: [three.js, react-three-fiber, 3d-visualization, aircraft, animation]
dependency-graph:
  requires: [04-01]
  provides: [Aircraft3D, latLonTo3D, ViewToggle]
  affects: [04-03]
tech-stack:
  added: []
  patterns: [useFrame-animation, lerp-interpolation, lat-lon-to-3d]
key-files:
  created:
    - app/frontend/src/components/Map3D/Aircraft3D.tsx
  modified:
    - app/frontend/src/components/Map3D/AirportScene.tsx
    - app/frontend/src/components/Map3D/Map3D.tsx
    - app/frontend/src/components/Map3D/index.ts
    - app/frontend/src/App.tsx
decisions:
  - "Use center coordinates 37.62/-122.38 (SFO area) for lat/lon to 3D conversion"
  - "Delta-time based lerp factor for frame-rate independent animation"
  - "Cone+box geometry for simplified aircraft shape (performance)"
metrics:
  duration: 3 minutes
  completed: 2026-03-05T16:52:00Z
---

# Phase 4 Plan 02: Aircraft 3D & Integration Summary

3D aircraft rendering with lat/lon coordinate conversion, smooth position animation, and 2D/3D view toggle for seamless switching between map visualization modes.

## Commits

| Task | Name | Commit | Key Changes |
|------|------|--------|-------------|
| 1 | Create Aircraft3D component | 405e0a7 | latLonTo3D, Aircraft3D with hover labels |
| 2 | Integrate aircraft into AirportScene | ea6530b | flights prop, Aircraft3D mapping |
| 3 | Add 2D/3D view toggle in App | 40e2880 | ViewToggle, viewMode state |
| 4 | Add smooth position updates | d91ca2b | Delta-time lerp, improved animation |

## Implementation Details

### Aircraft3D Component

Created `/app/frontend/src/components/Map3D/Aircraft3D.tsx` with:

**latLonTo3D Function:**
- Converts lat/lon/altitude to 3D scene coordinates
- Uses meters per degree (111000) with cosine correction for longitude
- Altitude converted from feet to meters then scaled
- Configurable center point (default: SFO area 37.62/-122.38)

**Aircraft3D Component:**
- Simple geometry: cone body, box wings, box tail fin
- Position from lat/lon coordinates
- Rotation from heading (degrees clockwise from north)
- Color coding: orange (default), green (selected), blue (arriving), red (departing)
- Hover label with Html component showing callsign and altitude
- Click handler for selection

### Smooth Animation

Uses useFrame hook with lerp interpolation:
- Stores current interpolated position/rotation in refs
- Each frame moves 10% toward target (scaled by delta time)
- Handles rotation angle wrapping (-PI to +PI boundary)
- Creates fluid motion rather than jumping on data updates

### 2D/3D View Toggle

Added to App.tsx:
- `viewMode` state with '2d' | '3d' options
- `ViewToggle` component with styled button pair
- Conditional rendering of AirportMap or Map3D
- Flight selection syncs between both views

### AirportScene Integration

Updated AirportScene with:
- New props: flights[], selectedFlight, onSelectFlight
- Maps flights array to Aircraft3D components
- Passes selection state and click handlers

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

- [x] Aircraft3D renders at correct lat/lon positions
- [x] Aircraft heading shown via rotation
- [x] 2D/3D toggle switches views
- [x] Positions update smoothly with new data
- [x] Selection syncs between views
- [x] TypeScript compiles without errors

## Self-Check: PASSED

All files exist:
- FOUND: app/frontend/src/components/Map3D/Aircraft3D.tsx
- FOUND: app/frontend/src/components/Map3D/AirportScene.tsx
- FOUND: app/frontend/src/components/Map3D/Map3D.tsx
- FOUND: app/frontend/src/components/Map3D/index.ts
- FOUND: app/frontend/src/App.tsx

All commits exist:
- FOUND: 405e0a7
- FOUND: ea6530b
- FOUND: 40e2880
- FOUND: d91ca2b

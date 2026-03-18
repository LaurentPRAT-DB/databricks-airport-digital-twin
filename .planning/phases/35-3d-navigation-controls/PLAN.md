# Plan: 3D Navigation Controls

## Context

The 3D view (`Map3D.tsx`) currently only has a text hint ("Left-click drag: Rotate | Right-click drag: Pan | Scroll: Zoom") that auto-hides. The user wants visual navigation buttons similar to the CesiumJS-style controls — a toolbar of icon buttons to help end users navigate the 3D view intuitively.

## Approach

Add a `NavigationControls3D` component as an overlay on the 3D Canvas with the following buttons:

| Button   | Icon            | Action                                    |
|----------|-----------------|-------------------------------------------|
| Home     | House icon      | Reset camera to default airport overview  |
| North Up | Compass/N arrow | Reset bearing so north is up              |
| Top Down | Eye/down-arrow  | Bird's eye view looking straight down     |
| Zoom In  | +               | Zoom in (reduce camera distance)          |
| Zoom Out | -               | Zoom out (increase camera distance)       |

## Style

- Vertical button strip in the bottom-right corner (similar to the screenshot's horizontal strip, but vertical fits better with existing UI)
- White/light background buttons with subtle shadow, matching the screenshot's style
- Inline SVG icons (no icon library — matches existing codebase pattern)
- Tailwind CSS classes

## Camera Control Mechanism

1. Add a ref to OrbitControls inside the Canvas
2. Store the controls ref in a mutable ref (`useRef`) accessible from the parent component
3. Navigation buttons call methods on the OrbitControls ref to animate camera transitions
4. Use `controls.object` (the camera) and `controls.target` to read/set positions
5. Smooth animation via `controls.update()` after setting positions

## Files to Modify

### 1. `app/frontend/src/components/Map3D/NavigationControls3D.tsx` (NEW)
- Standalone overlay component with 5 navigation buttons
- Accepts `controlsRef` prop to access OrbitControls
- Smooth camera transitions using `requestAnimationFrame`

### 2. `app/frontend/src/components/Map3D/Map3D.tsx` (EDIT)
- Add ref to `<OrbitControls ref={controlsRef}>`
- Store ref via a bridge pattern (`useRef` in parent, set from inner Canvas component)
- Import and render `<NavigationControls3D>` alongside the existing loading overlay
- Remove or keep the text hint (it complements the buttons)

## Verification

1. `cd app/frontend && npm test -- --run` — ensure existing tests pass
2. `./dev.sh` — visual check that buttons appear and work in 3D view
3. Test each button: home resets view, north-up resets bearing, top-down looks straight down, zoom +/- work

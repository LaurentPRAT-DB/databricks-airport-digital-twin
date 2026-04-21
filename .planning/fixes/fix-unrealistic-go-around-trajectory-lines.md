# Plan: Fix Unrealistic Go-Around Trajectory Lines

## Context

When viewing a go-around flight's trajectory on the 2D map, the polyline shows unrealistic straight lines cutting across the airport. This happens because:

1. Go-around transitions the flight from approaching -> enroute (missed approach) -> approaching (re-approach)
2. The trajectory builder (`useSimulationReplay.ts:583`) defines `ARRIVAL_AIRBORNE = Set(['approaching', 'landing'])` — no enroute
3. During playback, the enroute frames (go-around flyout) are skipped
4. The polyline connects the last pre-go-around approaching point directly to the first post-go-around approaching point — a straight line through the terminal

## Fix: Two-Part

### 1. Include go-around segments in arrival trajectory (`useSimulationReplay.ts:583`)

Add enroute to ARRIVAL_AIRBORNE:
```
ARRIVAL_AIRBORNE = Set(['approaching', 'landing', 'enroute'])
```

This captures the missed approach flyout (climb on runway heading + turn back). It also captures the initial cruise enroute frames far from the airport, but Part 2 handles that.

**Phase-matching impact:** When the current phase is enroute, the first if check (`ARRIVAL_AIRBORNE.has(currentPhase)`) now matches for both arriving and departing flights. But we already filter enroute flights from playback display (`useSimulationReplay.ts:454`), so this only affects trajectory building for a selected flight. If the user selects a flight while it's in enroute phase, it would show the arrival trajectory — acceptable since departing enroute flights are far from the airport and unlikely to be selected.

### 2. Gap detection in trajectory polyline (`TrajectoryLine.tsx`)

Split the polyline into disconnected segments when consecutive points are more than ~0.04° apart (~2.5 NM). This:
- Prevents far-away initial cruise points from being connected to approach points via a long straight line
- Handles any other edge-case trajectory discontinuities

Normal approach point spacing at 180 kts x 30s snapshots = ~0.025°, well under the threshold.
Go-around gap (last approach point -> first re-approach point without enroute) = 0.08-0.25°, well above.

In `TrajectoryLine.tsx`, change the polyline rendering to detect gaps and render multi-segment:
- Scan consecutive `validPoints`, split into segments at gaps > 0.04°
- Apply to both `traveledPositions` and `remainingPositions`
- Render multiple `<Polyline>` components for each group of segments

## Files to Modify

| File | Change |
|------|--------|
| `app/frontend/src/hooks/useSimulationReplay.ts:583` | Add `'enroute'` to ARRIVAL_AIRBORNE set |
| `app/frontend/src/components/Map/TrajectoryLine.tsx` | Add `splitAtGaps()` helper; apply to traveled + remaining positions before rendering |

## Verification

1. `cd app/frontend && npm test -- --run` — all 834+ tests pass
2. `cd app/frontend && npm run build` — clean build
3. Deploy + restart, select a go-around flight, verify trajectory shows complete missed approach path without unrealistic straight lines

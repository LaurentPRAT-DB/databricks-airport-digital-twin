---
status: complete
area: simulation
related:
  - .planning/fixes/taxi-route-building-penalty.md
  - src/ingestion/_flight_lifecycle.py
  - src/routing/taxiway_graph.py
---

# Fix: High-Speed Turnoff — Taxi Routes Crossing Buildings

## Problem

After landing, aircraft taxi routes still crossed terminal buildings despite the building penalty (1000x) in the taxiway graph. Root cause: aircraft brakes to 30kt on the runway itself (~820m rollout), then `snap_to_nearest_node` picks a graph node on the wrong side of the terminal.

## Root Cause Analysis

1. **Deceleration too aggressive**: 5 kts/s constant from 130kt touchdown → 30kt exit = only 820m rollout
2. **Exit speed too low**: 30kt means aircraft stops mid-runway, far from any high-speed taxiway exit
3. **Snap position**: `rollout_pos` captured at 30kt is before terminal buildings in many airport layouts
4. **Building penalty insufficient when ALL paths cross**: if snap point is deep inside terminal area, every Dijkstra path crosses a building — penalty just picks the least-bad one

## Real-World Procedure

Pilots use **high-speed turnoffs (HSTs)** — angled exits (30°) allowing runway vacation at 60-80kt:
- Shorter runway occupancy time (increases capacity)
- Exit point further down runway, past terminal complex
- Less taxi fuel (shorter distance to gate)

## Fix (Implemented)

**Two-phase deceleration:**
- >60kt: 3.5 kts/s (reverse thrust dominant)
- <60kt: 5.0 kts/s (wheel brakes dominant)

**Exit threshold raised:** 30kt → 55kt (simulates HST exit)

**Floor velocity lowered:** 25kt → 15kt (allows continued decel on taxiway)

**Result:** Rollout extends from ~820m to ~1000-1100m. Aircraft snaps to graph nodes past the terminal, where paths around buildings exist.

## Metrics

| Metric | Before | After |
|--------|--------|-------|
| Exit speed | 30kt | ~55kt |
| Rollout distance | ~820m | ~1000-1100m |
| Decel rate (high) | 5.0 kts/s | 3.5 kts/s |
| Decel rate (low) | 5.0 kts/s | 5.0 kts/s |

## Verification

- `test_pilot_landing_rollout.py`: 6/6 pass (decel ≤7kt/s, exit ≤65kt, no negative speed)
- `test_hst_taxi_route_quality.py`: 7 new tests — HST exit range, rollout distance, two-phase decel, route quality, no teleport, reasonable distances
- Full regression: 258 tests across routing/taxi/lifecycle/ops — all green
- Pre-existing flaky test (`test_taxi_to_runway_enters_runway_when_clear`) passes in isolation, fails only due to global state contamination from preceding sim — not a regression

## Commit

`ca53664` on branch `fix/hst-landing-rollout`

---
status: backlog
area: simulation
related: []
---

# Plan: Improve SFO Fallback Taxi Waypoints

**Status:** Backlog
**Date added:** 2026-04-07
**Scope:** Gate-zone-aware taxi routing for CLI simulation fallback (no OSM)

---

## Context

A pilot reviewed CLI-rendered KSFO simulation video and flagged that taxi paths (green dots) appear to cut through grass/apron areas instead of following actual taxiway centerlines. This happens because the CLI simulation (no OSM data) uses 5 hardcoded waypoints per direction that create straight-line interpolations, regardless of gate location.

Currently:

- `TAXI_WAYPOINTS_ARRIVAL` (line 1112): 4 points from high-speed exit to terminal apron
- `TAXI_WAYPOINTS_DEPARTURE` (line 1121): 5 points from terminal apron to runway 28R entry
- Both `_get_taxi_waypoints_arrival` and `_get_taxi_waypoints_departure` return these same generic waypoints for ALL SFO gates (line 1822-1823, 1867-1868)
- No gate-specific routing in CLI mode

## SFO Taxiway Layout (Reference)

- **Taxiway A** (~37.613): Runs parallel to 28L/10R on north side — primary arrival taxi route
- **Taxiway B** (~37.616-617): Through the terminal ramp area
- **Taxiway C** (~37.620): Runs parallel to 28R/10L on south side — primary departure taxi route
- Gates span from G (west, lon ~-122.395) to F (east, lon ~-122.370)

## Changes

**File:** `src/ingestion/fallback.py`

### 1. Replace generic waypoints with taxiway-following routes

Replace `TAXI_WAYPOINTS_ARRIVAL` and `TAXI_WAYPOINTS_DEPARTURE` with richer default routes (~8-10 points each) that follow Taxiway A (arrivals) and Taxiway C (departures) centerlines.

### 2. Make `_get_taxi_waypoints_arrival` gate-aware for SFO

Instead of returning the same generic waypoints, build a route that:

- Starts from the high-speed exit on Taxiway A
- Follows Taxiway A westbound to the turn nearest the gate's boarding area
- Turns north through the ramp to the gate
- Western gates (G, A) turn earlier; eastern gates (E, F) turn later

### 3. Make `_get_taxi_waypoints_departure` gate-aware for SFO

Build a route that:

- Exits the gate area southward onto the nearest taxiway
- Joins Taxiway C (or B) eastbound toward runway 28R
- Reaches the 28R hold line

### 4. Helper function `_sfo_taxi_route_for_gate`

Maps gate ref prefix (G/A/B/C/E/F) to the appropriate taxiway intersection point, keeping the logic DRY between arrival and departure.

## What Stays the Same

- The `apply_airport_offset` mechanism for non-SFO CLI sims (just offsets better base waypoints)
- The OSM taxiway graph path (already works correctly)
- The apron-aware fallback for non-SFO airports
- All phase transition logic, separation logic, speed logic

## Verification

1. Run existing tests: `uv run pytest tests/ -k taxi -v` to ensure no regressions
2. Run a short CLI simulation for KSFO and check the output positions to verify taxi paths follow Taxiway A/C
3. Frontend tests: `cd app/frontend && npm test -- --run` (shouldn't be affected)

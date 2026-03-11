# Plan: Origin-Aware Trajectory Generation

**Phase:** 12 — Post-v1
**Date:** 2026-03-11
**Status:** Not yet implemented

---

## Context

Currently, trajectory start points and approach/departure paths are generated with a fixed east-side offset regardless of the flight's origin or destination airport. This produces visually unrealistic trajectories — e.g., a flight from SEA (north of SFO) appears to approach from the east. Goals:

1. **Start point from origin direction** — Arriving flights should appear from the bearing of their origin airport
2. **Distance proportional to remaining points** — The number of trajectory points left determines how far the aircraft is from the destination
3. **All constraints still applied** — Separation, approach path, taxi routing, etc.
4. **Works for every airport** — No hardcoded values (currently SFO has hardcoded approach waypoints)

---

## Files to Modify

- `src/ingestion/fallback.py` — Main file; trajectory generation, approach/departure waypoints, flight spawning

## Key Existing Functions to Reuse

- `_bearing_from_airport(origin_iata)` (line 971) — Bearing FROM origin TO current airport
- `_bearing_to_airport(dest_iata)` (line 991) — Bearing FROM current airport TO destination
- `_point_on_circle(lat, lon, bearing, radius)` (line 1011) — Project point at bearing+distance
- `_calculate_heading(from_pos, to_pos)` (line 892) — Heading between two points
- `_get_airport_coordinates()` (line 965) — Lookup table for airport lat/lon
- `get_airport_center()` (line 249) — Current airport center

---

## Changes

### 1. Make `_get_approach_waypoints()` origin-aware

Replace the current function (lines 481-504) that generates a fixed east-side approach. New signature:

```python
def _get_approach_waypoints(origin_iata: Optional[str] = None) -> list:
```

Logic:
- Compute the inbound bearing using `_bearing_from_airport(origin_iata)` if origin is known, otherwise use a random or default bearing
- Generate waypoints along a curved path: start far out on the origin bearing, then curve onto a final approach aligned with the runway
- The approach entry point distance is proportional to the number of waypoints (farther out = more waypoints to cover)
- Final 3-4 waypoints always align with the runway centerline (standard ILS capture)
- For SFO, keep using the static `APPROACH_WAYPOINTS` only when no origin is specified (backward compat for tests)

**Waypoint generation algorithm:**
1. Compute `entry_bearing` = reciprocal of `_bearing_from_airport(origin)` (direction the aircraft comes FROM)
2. Compute `runway_bearing` = heading derived from runway threshold alignment (use last 2 approach waypoints or computed from OSM)
3. Generate ~11 waypoints:
   - First 5-6 waypoints: straight-line from entry point toward airport, descending from cruise altitude
   - Last 5-6 waypoints: curve onto final approach course, following standard 3-degree glideslope
4. Entry point radius: 0.25 degrees (~15 NM) from airport center — this gives a visible trajectory line

### 2. Make `_get_departure_waypoints()` destination-aware

Replace the current function (lines 522-543). New signature:

```python
def _get_departure_waypoints(destination_iata: Optional[str] = None) -> list:
```

Logic:
- Initial climb follows runway heading (first 2-3 waypoints)
- Then curve toward the destination bearing using `_bearing_to_airport(destination_iata)`
- Final waypoints project outward at the destination bearing
- Exit point distance matches the entry point (~0.25 degrees)

### 3. Update `_create_new_flight()` APPROACHING phase (line 1086)

Pass origin to `_get_approach_waypoints(origin)` so the base waypoint (spawn location) is on the correct bearing. Currently uses:
```python
base_wp = _get_approach_waypoints()[0]  # Always east
```
Change to:
```python
base_wp = _get_approach_waypoints(origin)[0]  # From origin direction
```

### 4. Update `generate_synthetic_trajectory()` (line 1919)

This is the main trajectory visualization function. Three cases to update:

**a) Ground trajectory (line 2000-2167):**
- Pass origin to `_get_approach_waypoints(origin)` in the approach phase
- The approach phase (`progress < 0.55`) already interpolates along waypoints — just needs origin-aware waypoints

**b) Departure trajectory (line 2169-2248):**
- Pass destination to `_get_departure_waypoints(destination)`
- The turn-toward-destination segment (`progress > 0.50`) already uses `dest_bearing` — just needs consistent waypoints

**c) Approach trajectory (line 2250-2324):**
- Already partially origin-aware (uses `_bearing_from_airport`)
- Update to use origin-aware approach waypoints instead of straight-line interpolation
- Replace the simple start → mid → end interpolation with proper waypoint following (same pattern as ground trajectory's approach phase)

### 5. Update `_find_aircraft_ahead_on_approach()` and `_find_last_aircraft_on_approach()`

These functions (lines 752-796) currently use longitude comparison to determine who is ahead (`other.longitude < state.longitude` = closer to runway). This breaks when approaches come from directions other than east.

Fix: Compare by distance to airport center instead of raw longitude:
```python
# Instead of: other.longitude < state.longitude
state_dist = _distance_between((state.latitude, state.longitude), get_airport_center())
other_dist = _distance_between((other.latitude, other.longitude), get_airport_center())
if other_dist < state_dist:  # Closer to airport = ahead
```

### 6. Update `_get_approach_queue_position()` (line 878)

Same fix — sort by distance to airport center, not by longitude.

### 7. Keep SFO backward compatibility

The static `APPROACH_WAYPOINTS` and `DEPARTURE_WAYPOINTS` constants remain for tests that reference them directly. The `_get_approach_waypoints(None)` with SFO center still returns those static values.

---

## What NOT to Change

- Taxi routing (already uses OSM graph, works per-airport)
- Gate assignment logic
- Separation standards (wake turbulence, runway occupancy)
- Frontend code (trajectory rendering already handles arbitrary lat/lon points)
- The hardcoded SFO waypoints as constants (keep for backward compat)

---

## Verification

1. `uv run pytest tests/ -v` — all Python tests pass
2. `cd app/frontend && npm test -- --run` — all frontend tests pass
3. Deploy and visually verify:
   - Select arriving flights from different origins (SEA, LAX, DEN, etc.) — trajectory should come from the correct compass direction
   - Select departing flights to different destinations — trajectory should exit toward the correct direction
   - Approach queue ordering still works correctly (no collisions or queue-jumping)
   - SFO default behavior unchanged when no origin specified

# Plan: Fix Approach Trajectory: Smoother Landing Path with More Points

**Phase:** 11 — Post-v1
**Date:** 2026-03-10
**Status:** Not yet implemented

---

## Context

The trajectory line for arriving flights shows two problems visible in the screenshot:
1. **Landing appears off-runway:** The landing roll uses hardcoded offsets (+0.004 lat, -0.012 lon) that produce a heading of ~293° instead of the actual runway 28L heading of 284°
2. **Jagged approach path:** Only 6 approach waypoints + 40 total points (24 for approach) create a visibly angular trajectory line, especially on the final approach turn

---

## Root Cause Analysis

**Landing roll direction (line 2012-2013):**
```python
lat = runway_28l_lat + roll_progress * 0.004  # produces ~293° heading
lon = runway_28l_lon - roll_progress * 0.012
```
Should use actual runway heading (284°) to compute roll direction.

**Approach smoothness:**
- `APPROACH_WAYPOINTS` has only 6 points with ~1-5 NM spacing
- The final approach segment (short final to threshold) has the sharpest geometry but only 1 waypoint
- Total trajectory capped at 40 points; 60% = 24 points for approach is sparse

---

## Changes

Single file: `src/ingestion/fallback.py`

### 1. Add more approach waypoints for smoother final approach (line 438)

Add intermediate waypoints between the existing ones, especially in the final 5 NM:

```python
APPROACH_WAYPOINTS = [
    (-122.10, 37.58, 6000),      # Initial approach fix - 15 NM
    (-122.15, 37.588, 5000),     # NEW: intermediate
    (-122.20, 37.595, 4000),     # Intermediate fix - 10 NM
    (-122.24, 37.600, 3200),     # NEW: intermediate
    (-122.28, 37.605, 2500),     # Final approach fix - 5 NM
    (-122.30, 37.607, 1800),     # NEW: intermediate
    (-122.32, 37.608, 1000),     # Glideslope intercept - 3 NM
    (-122.333, 37.609, 650),     # NEW: intermediate
    (-122.345, 37.610, 300),     # Short final - 1 NM
    (-122.352, 37.6109, 150),    # NEW: very short final
    (_RWY_28L_LON, _RWY_28L_LAT, 15),  # Threshold
]
```

This doubles the waypoints from 6 to 11, adding density especially in the final 3 NM.

### 2. Fix landing roll to follow actual runway heading (line ~2012-2013)

Replace hardcoded offsets with heading-based computation:

```python
# Landing roll along actual runway heading (284°)
_rwy_heading_rad = math.radians(284)
_roll_distance = 0.012  # ~1.3 km roll in degrees
roll_dlat = _roll_distance * math.cos(_rwy_heading_rad)  # ~0.0029
roll_dlon = _roll_distance * math.sin(_rwy_heading_rad) / math.cos(math.radians(runway_28l_lat))  # ~-0.0147
lat = runway_28l_lat + roll_progress * roll_dlat
lon = runway_28l_lon + roll_progress * roll_dlon
```

Also update the roll endpoint calculation in the taxi phase (line ~2026-2027) to use the same formula so the taxi phase connects smoothly.

### 3. Increase total trajectory points from 40 to 80 (line 1959)

Change `num_points = min(limit, 40)` to `num_points = min(limit, 80)`. This doubles point density across all phases, making the trajectory line significantly smoother.

### 4. Adjust phase proportions for more approach detail

Change from 60/10/30 to 55/10/35:
- Approach: 55% (was 60%) — now 44 points (was 24)
- Landing roll: 10% — now 8 points (was 4)
- Taxi: 35% (was 30%) — now 28 points (was 12)

Update the `if progress < 0.60` / `elif progress < 0.70` thresholds to `0.55` / `0.65`.

---

## Verification

1. `uv run pytest tests/ -v` — all Python tests pass
2. `cd app/frontend && npm test -- --run` — all frontend tests pass
3. Deploy and visually verify: select an arriving ground flight, enable trajectory, zoom to runway area — trajectory should:
   - Follow a smooth curve on approach (no jagged angles)
   - Touch down on the runway threshold (not off to the side)
   - Roll along the runway heading (284°)
   - Transition smoothly to taxiway route

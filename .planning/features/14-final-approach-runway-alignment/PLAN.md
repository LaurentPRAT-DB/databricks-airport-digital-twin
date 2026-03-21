# Plan: Realistic Final Approach with Runway Alignment

**Phase:** 14 — Post-v1
**Date:** 2026-03-11
**Status:** Not yet implemented
**Depends on:** Phase 12 (origin-aware trajectories)

---

## Context

Aircraft approaching the airport fly in a straight line from the origin direction all the way to the airport center. Per ICAO Doc 8168 (PANS-OPS) and FAA Order 8260.3, aircraft must intercept the final approach course (aligned with the runway centerline) at 5-10 NM from the threshold. Currently trajectories arrive from the side of the runway rather than aligning with it.

**Root cause:** `_get_approach_waypoints(origin_iata)` generates all 11 waypoints along a single straight bearing from origin → airport center. No turn, no runway alignment.

---

## Changes — 1 File Modified

**File:** `src/ingestion/fallback.py`

### 1. Rewrite `_get_approach_waypoints`

Split approach into two phases that match real IFR procedures:

- **Phase 1 — Downwind/base leg (outer waypoints):** From entry bearing, gradually turning toward the localizer intercept point.
- **Phase 2 — Final approach (inner waypoints):** Aligned with the runway heading, from ~0.10 deg (~6 NM) to the threshold.

```python
def _get_approach_waypoints(origin_iata: Optional[str] = None) -> list:
    center = get_airport_center()
    lat, lon = center

    # SFO backward-compat: no origin → static waypoints
    if origin_iata is None:
        if abs(lat - AIRPORT_CENTER[0]) < 0.01 and abs(lon - AIRPORT_CENTER[1]) < 0.01:
            return APPROACH_WAYPOINTS
        entry_dir = 90.0
    else:
        bearing_to_apt = _bearing_from_airport(origin_iata)
        entry_dir = (bearing_to_apt + 180) % 360

    # Runway approach course (reciprocal of runway heading)
    rwy_heading = _get_runway_heading()
    approach_course = (rwy_heading + 180) % 360

    # Phase 2: Final approach — along runway centerline
    final_distances = [0.10, 0.075, 0.05, 0.035, 0.02, 0.01, 0.0]
    final_altitudes = [2500, 1800, 1000, 650, 300, 150, 15]
    final_wps = []
    for dist, alt in zip(final_distances, final_altitudes):
        if dist == 0.0:
            final_wps.append((lon, lat, alt))
        else:
            pt = _point_on_circle(lat, lon, approach_course, dist)
            final_wps.append((pt[1], pt[0], alt))

    # Phase 1: Base leg — blend from entry_dir to approach_course
    base_distances = [0.25, 0.21, 0.17, 0.135]
    base_altitudes = [6000, 5000, 4000, 3200]
    base_wps = []
    for i, (dist, alt) in enumerate(zip(base_distances, base_altitudes)):
        blend = i / len(base_distances)  # 0→0.75
        bearing = entry_dir + _shortest_angle_diff(entry_dir, approach_course) * blend
        pt = _point_on_circle(lat, lon, bearing, dist)
        base_wps.append((pt[1], pt[0], alt))

    return base_wps + final_wps
```

Key: `_shortest_angle_diff` already exists. Departures already use this blend pattern.

### 2. Fix `_update_flight_state` APPROACHING phase

Currently uses `_get_approach_waypoints()` with no origin — must pass the flight's origin so it follows the same curved path:

```python
# Change:
approach_wps = _get_approach_waypoints()
# To:
approach_wps = _get_approach_waypoints(state.origin_airport)
```

### 3. No other changes needed

- `_get_runway_heading()` derives from default waypoints — unaffected
- Trajectory generation already calls `_get_approach_waypoints(origin_airport)` — will automatically follow the new curved path
- Departure waypoints already use the same blend pattern — consistent

---

## IFR Reference (ICAO Doc 8168 / FAA 8260.3)

| Parameter | Standard | Our Implementation |
|---|---|---|
| Final approach fix (FAF) | 5-7 NM from threshold | ~6 NM (0.10 deg) |
| Glideslope | 3° (300 ft/NM) | ~300 ft/NM (2500ft at 6NM) |
| Localizer intercept angle | 30-45° max | Blended over 4 waypoints |
| Final approach aligned with runway | Required | Yes (approach_course = rwy_heading + 180°) |

---

## Verification

1. `uv run pytest tests/ -v` — all Python tests pass
2. `cd app/frontend && npm test -- --run` — all frontend tests pass
3. Visual: arriving flights should curve from their origin direction onto the runway centerline for the last ~6 NM, not fly straight from the side

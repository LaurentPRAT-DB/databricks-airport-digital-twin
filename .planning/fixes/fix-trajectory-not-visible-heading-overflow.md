# Fix: Trajectory Not Visible + Heading >360

## Context

Flight UAL2953 approaching SFO from SNA shows:
1. No trajectory line despite "Show Trajectory" being ON
2. Heading 383 deg displayed in Flight Details (should be 0-360)

## Root Causes

### Issue 1: Heading not normalized in state vector output

- `src/ingestion/fallback.py:5168` — `_hdg = _sanitize_float(state.heading, 0.0)` passes heading through without `% 360`
- `_update_flight_state` normalizes heading at the end (line 4882), BUT several early-return paths skip it (lines 3966, 4142, 4150, 4164, 4221, 4446)
- The state vector at line 5184 sends `_hdg` raw to the WebSocket via `flight_service.py:168`

### Issue 2: Trajectory returns 0 renderable segments

- For non-simulation `dataSource='synthetic'`, the frontend calls `/api/flights/{icao24}/trajectory` (REST API)
- `generate_synthetic_trajectory` has an `aircraft_past_threshold` guard (line 5786) that reduces the trajectory to 1 point when the aircraft position is past the runway threshold
- The frontend's `splitAtGaps()` drops segments with <2 points, so a single-point trajectory renders nothing

## Fix Plan

### Fix 1: Normalize heading in state vector output (1 line)

**File:** `src/ingestion/fallback.py:5168`

```python
# Before
_hdg = _sanitize_float(state.heading, 0.0)
# After
_hdg = _sanitize_float(state.heading, 0.0) % 360
```

This is the single chokepoint where all heading values flow to the API and WebSocket. Also normalizes headings from any early-return path that skipped line 4882.

### Fix 2: Generate at least 2 trajectory points when `aircraft_past_threshold` (approach trajectory)

**File:** `src/ingestion/fallback.py:5786-5794`

When `aircraft_past_threshold` is True, instead of emitting 1 point (which gets dropped by `splitAtGaps`), generate a short 2-point segment: one slightly behind the aircraft's direction, one at the aircraft position. This ensures the trajectory renderer has enough points to draw a line.

```python
# When aircraft is past threshold, create a short trailing segment
# instead of a single point (which splitAtGaps drops)
if aircraft_past_threshold:
    # Short back-projection along the aircraft's heading
    back_dist = 0.02  # ~2.2 km behind
    back_bearing = (current_heading + 180) % 360
    back_lat = clamped_lat + back_dist * math.cos(math.radians(back_bearing))
    back_lon = clamped_lon + back_dist * math.sin(math.radians(back_bearing)) / math.cos(math.radians(clamped_lat))
    path_wps = [
        (back_lon, back_lat, final_alt + 300),
        (clamped_lon, clamped_lat, final_alt),
    ]
    path_count = 2
```

## Files Modified

1. `src/ingestion/fallback.py` — heading normalization (line 5168) + approach trajectory guard (lines 5786-5794)

## Verification

1. Run backend tests: `uv run pytest tests/ -x -q -k "trajectory or heading or synthetic"`
2. Deploy and check:
   - Heading should show 0-360 for all flights
   - Approaching flights should show trajectory lines
   - Select various approaching flights and verify trajectory visibility

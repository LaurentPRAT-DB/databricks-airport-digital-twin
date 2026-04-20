# Fix Zigzag Trajectory in Holding Pattern

## Context

GMMN (Casablanca) simulation shows bizarre rectangular zigzag flight paths covering ~50km. The trajectory has sharp ~90° turns instead of smooth racetrack holding patterns. Root cause is in the ENROUTE holding pattern logic in `src/ingestion/fallback.py`.

## Root Cause Analysis

### Primary: Broken holding pattern geometry (lines 4720-4745)

The ENROUTE holding pattern has two critical bugs:

1. **Outbound turn is 90° instead of 180°** — The code turns for 30 seconds at 3°/s = 90°. A standard holding pattern needs 180° (60 seconds at 3°/s). The comment on line 4737 says "30s for 180°" but the math is wrong.
2. **Inbound heading is instant-snapped** — When transitioning from outbound back to inbound (line 4744->4728), the heading snaps instantly to point at the airport center. No gradual turn. This creates a sharp direction change every cycle.

**Combined effect:** 60s inbound -> 90° turn -> 60s perpendicular flight -> instant snap back -> repeat = rectangular zigzag pattern.

### Secondary: ENROUTE->APPROACHING always resets waypoint_index to 0 (lines 4696, 4712)

When a holding flight finally enters APPROACHING, it starts at waypoint 0 (the farthest waypoint, ~15-22 km from airport). The flight must fly AWAY from the airport to reach wp 0, then follow waypoints back. After a go-around, this repeats, adding more zigzag.

### Tertiary: ENROUTE movement ignores velocity and latitude (lines 4806-4807)

Hardcoded 0.001 deg/s instead of using `state.velocity * _KTS_TO_DEG_PER_SEC`. No longitude correction for latitude (compare with the go-around climb code at 4643-4645 which does it correctly).

## Fixes

### Fix 1: Holding pattern turn duration and structure

**File:** `src/ingestion/fallback.py` lines 4720-4745

- Change outbound turn from 30s to 60s -> proper 180° at 3°/s
- Replace instant heading snap on inbound with `_smooth_heading()` (already exists at line 2818) for gradual turns
- Adjust timing constants: outbound total from 90s to 120s

```python
# Before (broken):
if state.holding_phase_time < 30.0:                    # 90° turn
    state.heading = (state.heading + STANDARD_RATE_DEG_S * dt) % 360
elif state.holding_phase_time < 30.0 + HOLDING_LEG_SECONDS:  # 90s total

# After (fixed):
HOLDING_TURN_SECONDS = 60.0  # 180° at standard rate
if state.holding_phase_time < HOLDING_TURN_SECONDS:    # 180° turn
    state.heading = (state.heading + STANDARD_RATE_DEG_S * dt) % 360
elif state.holding_phase_time < HOLDING_TURN_SECONDS + HOLDING_LEG_SECONDS:  # 120s total
```

For the inbound leg, replace the instant snap:
```python
# Before:
state.heading = _calculate_heading(...)  # Instant snap every tick

# After:
target_heading = _calculate_heading(...)
state.heading = _smooth_heading(state.heading, target_heading, 3.0, dt)
```

### Fix 2: Waypoint snapping on ENROUTE->APPROACHING transition

**File:** `src/ingestion/fallback.py` lines 4696, 4712

When entering APPROACHING from ENROUTE, snap `waypoint_index` to the nearest approach waypoint (same logic already used in `_create_new_flight` at line 3459-3467) instead of hardcoding 0.

Both transition points (lines 4696 and 4712) need this fix.

### Fix 3: ENROUTE movement velocity and latitude correction

**File:** `src/ingestion/fallback.py` lines 4806-4807

Replace hardcoded movement with velocity-based, latitude-corrected movement (matching the go-around climb pattern at lines 4643-4645):

```python
# Before:
state.latitude += math.cos(math.radians(state.heading)) * 0.001 * dt
state.longitude += math.sin(math.radians(state.heading)) * 0.001 * dt

# After:
speed_deg = state.velocity * _KTS_TO_DEG_PER_SEC * dt
state.latitude += math.cos(math.radians(state.heading)) * speed_deg
state.longitude += math.sin(math.radians(state.heading)) * speed_deg / max(0.01, math.cos(math.radians(state.latitude)))
```

## Files Modified

- `src/ingestion/fallback.py` — all 3 fixes in one file

## Verification

1. Run existing tests: `uv run pytest tests/ -v -k "holding or enroute or approach" --tb=short`
2. Run full test suite to check for regressions: `uv run pytest tests/ -x --tb=short`
3. Run a GMMN simulation and visually verify the trajectory is smooth

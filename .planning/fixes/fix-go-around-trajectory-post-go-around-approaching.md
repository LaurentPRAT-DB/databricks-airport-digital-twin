---
status: done
area: simulation
related:
  - fix-go-around-display-clustered-markers-grouped-table.md
  - fix-go-around-trajectory-heading-overflow.md
  - fix-unrealistic-go-around-trajectory-lines.md
---

# Plan: Fix go-around trajectory display for post-go-around flights

## Context

UAL732 (LAS->SFO) had a go-around at 3800ft. When the user clicks the flight to see its trajectory, the displayed line looks like erratic zigzags instead of a smooth go-around pattern (approach -> climb-out -> holding -> re-approach).

**Root cause:** `generate_synthetic_trajectory()` in `src/ingestion/fallback.py` has a go-around trajectory handler (`is_go_around` block, line 5302) but it only triggers when `current_phase == "enroute"` — i.e., during the brief holding period. Once the flight re-enters approaching after the go-around, `is_go_around` is false and the code falls to the regular approach trajectory (line 5737 else block). The regular approach trajectory reconstructs a straight approach from origin waypoints, which doesn't match where the aircraft actually is after a go-around, creating the zigzag appearance.

## Fix

### 1. Extend `is_go_around` detection to include post-go-around approaching flights

**File:** `src/ingestion/fallback.py` lines 5270-5280

Current code:
```python
is_go_around = (
    current_state
    and current_state.go_around_count > 0
    and current_phase == "enroute"
    and (...)
)
```

Change to also match approaching phase when `go_around_count > 0`:
```python
is_go_around = (
    current_state
    and current_state.go_around_count > 0
    and current_phase in ("enroute", "approaching")
    and (current_state.origin_airport and (
        not current_state.destination_airport
        or current_state.destination_airport == _local_iata
    ))
)
```

### 2. Extend the go-around trajectory to include re-approach segment

**File:** `src/ingestion/fallback.py` lines 5302-5423

When `current_phase == "approaching"`, the flight has already left holding and is on its second approach. The trajectory should show:
1. Initial approach (40% of points) — waypoints from origin direction to threshold
2. Climb-out (15% of points) — threshold -> climb-out on runway heading to 1500ft
3. Return to holding / re-approach entry (15% of points) — curve from climb-out to approach re-entry
4. Second approach (30% of points) — from re-entry point to aircraft's current position

For `current_phase == "enroute"` (aircraft still in holding), keep the existing 60/25/15 budget.

The key change: when the flight is in approaching phase, add a 4th segment that interpolates along approach waypoints from the re-entry point to the aircraft's current position (using `waypoint_index` from `current_state` to know how far along the approach the aircraft has progressed).

### 3. Rebalance point budget for 4-phase trajectory

```python
if current_phase == "approaching":
    # Full go-around + second approach
    _GA_APP_PTS = 30    # initial approach (shorter, less detail needed)
    _GA_CLIMB_PTS = 12  # climb-out
    _GA_RETURN_PTS = 10 # return/curve
    _GA_REAPP_PTS = 28  # second approach (to current position)
else:
    # During holding (enroute) — keep existing budget
    _GA_APP_PTS = 48
    _GA_CLIMB_PTS = 20
    _GA_RETURN_PTS = 12
```

For the 4th phase (re-approach), interpolate along approach waypoints from `wp[0]` to the aircraft's current waypoint index, ending at the aircraft's current lat/lon. Use the same descent profile interpolation as the initial approach.

## Files to Modify

| File | Change |
|------|--------|
| `src/ingestion/fallback.py` (lines 5270-5280) | Extend `is_go_around` to include approaching phase |
| `src/ingestion/fallback.py` (lines 5302-5423) | Add 4th re-approach segment for post-go-around approaching flights |

## Verification

1. `uv run pytest tests/test_trajectory_coherence.py -v` — all 96 tests pass
2. `uv run pytest tests/test_ingestion.py -v -k trajectory` — trajectory tests
3. Visual: run local sim at SFO, trigger a go-around scenario, click the go-around flight and verify the trajectory shows: approach -> climb-out -> curve -> second approach
4. Deploy and verify on the live app

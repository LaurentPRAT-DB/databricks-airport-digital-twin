---
status: done
area: simulation
related:
  - fix-go-around-display-clustered-markers-grouped-table.md
  - fix-go-around-trajectory-post-go-around-approaching.md
  - fix-unrealistic-go-around-trajectory-lines.md
---

# Fix Go-Around Trajectory + Heading >360° Bug

## Context

Two issues with go-around flights:

1. **Trajectory appears directly above the runway** — when a go-around flight is selected, the trajectory generator doesn't know about go-arounds. It falls into the else branch (approach trajectory, line 5560) which draws an approach trail ending at the aircraft's current position. During a go-around, the aircraft is climbing directly above/past the runway threshold, so the trail endpoint sits right on top of the airport — looking like the aircraft flew through the airport.
2. **Heading >360°** — the go-around climb path at `fallback.py:4666-4676` does `return state` early, skipping the heading normalization at line 4840 (`state.heading = state.heading % 360`). This allows heading values like 385° to persist in snapshots.

## Files to modify

`src/ingestion/fallback.py` only.

## Fix 1: Go-around trajectory — missed approach path

**Where:** `generate_synthetic_trajectory()` at line 5166

**Problem:** A go-around flight has `current_state.phase == FlightPhase.ENROUTE` and `current_state.go_around_count > 0`. It currently falls into the departure branch (`elif current_phase in ["climbing", "cruising", "departing", "takeoff", "enroute"]` at line 5456) which draws a departure trajectory — completely wrong for an arriving aircraft doing a missed approach.

**Fix:** Before the existing branch logic (before `if is_on_ground:` at line 5248), detect go-around state and generate a missed approach trajectory:

```python
# Detect go-around: aircraft is ENROUTE but arriving (has origin, no destination or destination==local)
is_go_around = (
    current_state
    and current_state.go_around_count > 0
    and current_phase == "enroute"
    and (current_state.origin_airport and not current_state.destination_airport)
)
```

If `is_go_around`, generate a trajectory that shows:
1. First 60% of points: approach trail — same as the normal approach trajectory, from origin-aware waypoints down to near the runway threshold
2. Last 40% of points: missed approach climb — from near the threshold, climbing on runway heading, then curving back toward the holding pattern area

The missed approach segment:
- Start at the last approach waypoint (near threshold) at ~200ft (decision height)
- Climb at 1500 fpm on runway heading for ~30% of points
- Turn toward airport center (holding) for last ~10% of points
- End at aircraft's current position/altitude

This replaces the entire `if is_on_ground:` / `elif departure:` / `else approach:` block for go-around flights — it's a separate `if is_go_around:` branch at the top.

### Implementation detail

```python
if is_go_around:
    # Missed approach trajectory: approach + climb-out + return
    origin_airport = current_state.origin_airport
    _traj_app_wps_ga = _get_approach_waypoints(origin_airport)

    _rwy_heading_ga = _get_runway_heading()
    if _rwy_heading_ga is None or len(_traj_app_wps_ga) < 2:
        return []

    # Phase budget: 60% approach, 25% climb-out, 15% return turn
    _GA_APP_PTS = 48
    _GA_CLIMB_PTS = 20
    _GA_RETURN_PTS = 12
    # total = 80

    # Approach phase: interpolate along approach waypoints (same as normal)
    # Climb-out phase: project forward on runway heading, climbing
    # Return phase: curve from climb-out end toward current position

    _running_hdg = current_heading
    for i in range(num_points):
        progress = i / (num_points - 1) if num_points > 1 else 0

        if i < _GA_APP_PTS:
            # Approach portion — interpolate along waypoints
            app_progress = i / max(_GA_APP_PTS - 1, 1)
            # ... interpolate waypoints, descent profile (reuse existing approach code)

        elif i < _GA_APP_PTS + _GA_CLIMB_PTS:
            # Climb-out on runway heading from threshold
            climb_progress = (i - _GA_APP_PTS) / max(_GA_CLIMB_PTS - 1, 1)
            # Start at threshold, fly runway heading, climb from 200ft to ~1500ft
            rwy_rad = math.radians(_rwy_heading_ga)
            climb_dist = climb_progress * 0.03  # ~3km climb-out
            lat = rwy_threshold_lat + climb_dist * math.cos(rwy_rad)
            lon = rwy_threshold_lon + climb_dist * math.sin(rwy_rad) / math.cos(math.radians(rwy_threshold_lat))
            alt = 200 + climb_progress * 1300  # 200ft -> 1500ft
            heading = _rwy_heading_ga

        else:
            # Return turn toward current position
            return_progress = (i - _GA_APP_PTS - _GA_CLIMB_PTS) / max(_GA_RETURN_PTS - 1, 1)
            # Interpolate from climb-out end to aircraft's current position
            # ... smooth curve using lat/lon interpolation
```

Key reuse: The approach portion reuses the same waypoint interpolation + descent profile logic from the existing approach branch (lines 5299-5337).

## Fix 2: Heading normalization on go-around early return

**Where:** `_update_flight_state()`, line 4676

**Problem:** The go-around climb block at lines 4666-4676 does `return state` before the heading normalization at line 4840. This lets heading values >360° or <0° leak out.

**Fix:** Add heading normalization before the early return:

```python
# Line 4675-4676, change from:
                    state.go_around_target_alt = 0.0
                return state

# To:
                    state.go_around_target_alt = 0.0
                state.heading = state.heading % 360
                return state
```

One line added.

## Changes Summary

1. Add `is_go_around` detection before the main trajectory branch (after `is_on_ground` detection, ~line 5227)
2. Add go-around trajectory branch as a new `if is_go_around:` block before `if is_on_ground:` — generates approach + missed-approach-climb + return trajectory
3. Add heading normalization before early return at line 4676

## Verification

```bash
# Run trajectory coherence tests
uv run pytest tests/test_trajectory_coherence.py -v

# Run MCP tests (trajectory tool)
uv run pytest tests/test_mcp.py::TestMCPToolGetFlightTrajectory -v

# Run full test suite
uv run pytest tests/ -x -q --timeout=120
```

Visual: deploy, wait for a go-around event, select the flight — trajectory should show approach trail curving up and away from the runway, not sitting on top of it.

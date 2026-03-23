# ATC Sky Controller Trajectory Review Report

**Airport:** KSFO (San Francisco International)
**Date:** 2026-03-23
**Simulation Time:** ~02:00 local (100 flights active)
**Reviewer:** Sky Controller / OpenAP Integration Audit

---

## 1. Executive Summary

The OpenAP-based trajectory improvements have **significantly improved approach trajectory smoothness** — mean altitude jumps dropped to ~30ft (from ~200ft with the old noise injection), and approach speed profiles now follow realistic deceleration curves. However, the audit uncovered **5 regulatory and procedural concerns** in the departure/enroute phases and **separation management** that need attention.

| Category | Grade | Notes |
|----------|-------|-------|
| Approach trajectory smoothness | **A** | Noise removed, smooth altitude/speed profiles |
| Approach speed envelope | **B+** | Correct Vref deceleration, but some aircraft too slow at altitude |
| Departure climb profile | **C** | Large altitude jumps (~500ft) in trajectory recorder |
| Enroute trajectory realism | **C-** | Heading reversals >90deg, altitude jumps ~500ft |
| Separation standards | **D** | 7 out of 28 approach pairs violate 3NM minimum |
| 14 CFR 91.117 compliance | **A** | Zero current-state violations (250kt below FL100) |
| Glideslope accuracy | **B-** | Range 0.1-3.2deg, only 1 of 6 in ideal 2.5-3.5 band |

---

## 2. Visual Assessment

### 2.1 Ground Operations (Screenshots 01, 03, 50-51)

![Default View](30_default.png)
![Selected Flight with Trajectory](51_trajectory_enabled.png)

**Observations:**
- Taxi paths rendered as clean blue polylines — no jitter or zig-zagging
- Gate assignments visible in flight detail panel (B12, D11, D14)
- Turnaround progress bars and baggage status correctly displayed
- Aircraft positions on taxiways and gates appear realistic
- **Good**: Ground trajectory lines are smooth and follow taxiway geometry

### 2.2 Approach Corridors (Screenshots 31, 38)

![Bay Area Overview](31_zoomed_out_4x.png)
![Final Overview](38_final_overview.png)

**Observations:**
- Gray curved lines radiating from SFO visible at Bay Area zoom level — these are approach/departure corridors
- Airport cluster well-defined with golden runway outlines visible
- Approach paths converge from multiple directions (N, W, S) reflecting origin-aware waypoints
- **Good**: No visible zig-zagging in approach corridor lines at this scale

### 2.3 Airport Detail (Screenshots 33, 04)

![Medium Zoom](33_medium_zoom.png)

**Observations:**
- Runway geometry (28L/28R) clearly rendered in gold/yellow overlay
- Terminal buildings and aprons visible with blue outlines
- Aircraft markers clustered at gates and on taxiways
- Only 1 airborne flight marker visible at this zoom (most are zoomed out of view)

---

## 3. Trajectory Data Analysis

### 3.1 Approach Phase (8 flights) — GOOD

| Callsign | Type | Alt Range | Max Alt Jump | Mean Alt Jump | Max Hdg Jump | GS Angle |
|----------|------|-----------|-------------|--------------|-------------|----------|
| JAL8114  | B738 | 4913ft    | -           | -            | -           | -        |
| UAL1362  | B738 | 2558-4802 | 89ft        | 30.4ft       | 81.0deg     | 3.2deg   |
| UAL9455  | B738 | 2327-4819 | 97ft        | 35.1ft       | 179.6deg    | 2.8deg   |
| UAL866   | B738 | 3181-4790 | 82ft        | 33.2ft       | 178.2deg    | 1.4deg   |
| UAL5239  | B739 | 2400-4791 | 88ft        | 32.8ft       | 151.5deg    | 2.1deg   |
| SKW261   | E175 | 3783-4811 | 75ft        | 26.5ft       | 69.5deg     | 1.0deg   |
| UAL4716  | B738 | 4758-4825 | 58ft        | 23.2ft       | 75.6deg     | 0.1deg   |

**What's Good:**
- **Altitude smoothness is excellent**: Mean altitude jumps of 23-35ft are realistic for ADS-B data (old system had ±200ft random noise)
- **Max altitude jumps < 100ft**: Well within realistic bounds (previously could spike 400ft+)
- **Speed deceleration working**: Flights at lower altitude correctly at Vref range (138-144kts)

**What's Bad:**
- **Heading jumps up to 179.6deg**: UAL9455 and UAL866 show near-reversal heading changes in their trajectory history. This suggests the trajectory recorder is capturing a waypoint turn that happens too abruptly, or the approach path geometry has a sharp turn that the `_smooth_heading` in the live simulation doesn't affect (the recorder generates points from waypoints independently)
- **Glideslope angles too shallow**: UAL4716 at 0.1deg, SKW261 at 1.0deg — far from the standard 3deg ILS glideslope. This means aircraft are flying nearly level while supposedly on approach
- **Many approaches at ~140kts regardless of altitude**: SKW261 (E175) at 4138ft showing 140kts — should be ~210kts at that altitude; speed should only be Vref on short final below ~1500ft

### 3.2 Enroute/Departure Phase (7 flights) — NEEDS WORK

| Callsign | Type | Alt Range | Max Alt Jump | Max Hdg Jump | Speed Violations |
|----------|------|-----------|-------------|-------------|-----------------|
| UAL7567  | B738 | 0-15015   | 487ft       | 57.3deg     | 22              |
| SWA3107  | B737 | 0-14990   | 497ft       | 86.9deg     | 23              |
| UAL7903  | B738 | 2-14985   | 511ft       | 57.1deg     | 23              |
| DAL6184  | B738 | 0-15019   | 493ft       | 9.2deg      | 22              |
| SWA8380  | B737 | 0-14988   | 450ft       | 162.7deg    | 21              |
| UAL9830  | B787 | 5-14998   | 500ft       | 122.9deg    | 22              |
| FFT1981  | A320 | 0-14986   | 486ft       | 58.6deg     | 21              |

**What's Bad:**
- **~500ft altitude jumps**: The trajectory recorder for departures still uses ad-hoc altitude interpolation between waypoints, producing 450-511ft altitude steps. This makes departure trajectory lines look like stair-steps rather than smooth climbs
- **Heading jumps 57-163deg**: The departure trajectory recorder computes heading to next waypoint at each point — when waypoints are spread apart, heading snaps 90+ degrees at the turn point instead of showing a gradual arc
- **Speed violations in trajectory history (14 CFR 91.117)**: 20-23 points per departure trajectory show speeds >250kts below FL100. These are in the trajectory recorder's generated history, not the live simulation state. The recorder formula `velocity = 200 + climb_progress * 100` pushes to 300kts early in climb while still below 10,000ft
- **Current enroute state is fine**: Live flight states show correct speeds (421-491kts at FL350+) and proper vertical rates

### 3.3 Separation Standards — CRITICAL

**Approach separation check (8 flights, 28 pairs):**

| Pair | Distance | Status | Required |
|------|----------|--------|----------|
| JAL8114 ↔ UAL9455 | 2.7 NM | **VIOLATION** | 3.0 NM min |
| UAL1362 ↔ UAL866 | 2.9 NM | **VIOLATION** | 3.0 NM min |
| UAL1362 ↔ UAL5239 | 2.8 NM | **VIOLATION** | 3.0 NM min |
| UAL1362 ↔ UAL185 | 3.0 NM | **VIOLATION** | 3.0 NM min |
| UAL9455 ↔ UAL5239 | 3.0 NM | **VIOLATION** | 3.0 NM min |
| UAL866 ↔ SKW261 | 3.0 NM | **VIOLATION** | 3.0 NM min |
| SKW261 ↔ UAL4716 | 3.0 NM | **VIOLATION** | 3.0 NM min |

7 out of 28 pairs (25%) violate the FAA 3NM minimum approach separation. This suggests the separation checking logic works for sequential (ahead/behind) pairs but not for flights that are laterally spaced on different approach paths coming from different directions. Two aircraft can be at 2.7NM apart laterally while both being "on approach" from different compass quadrants.

**Note**: Some of these may be acceptable if the flights are at different altitudes (vertical separation of 1000ft is an alternative standard), but the simulation doesn't currently check vertical separation as an alternative to lateral.

---

## 4. Detailed Findings

### 4.1 GOOD: Approach Altitude Profile (OpenAP Working)

The approach phase in `_update_flight_state()` now correctly uses OpenAP descent profiles:
- Progress mapped to 60-100% of descent profile (last 40% = final approach segment)
- Altitude interpolated smoothly toward waypoint targets
- Vertical rates from profile instead of ad-hoc brackets
- **Result**: 30ft mean altitude jumps vs 200ft+ previously

### 4.2 GOOD: Turn Rate Limiting Active

The `_smooth_heading()` function at 3deg/s is active on approach and departure:
- Live simulation heading changes are clamped to standard rate turns
- Mean heading jump 2.0-5.6deg per point — consistent with 3deg/s at ~1-2s tick intervals

### 4.3 GOOD: No Noise in Live State

Position noise (`random.uniform(-pos_noise, pos_noise)`) successfully removed from:
- Approach trajectory recorder
- Departure trajectory recorder
- Third approach recorder section

### 4.4 BAD: Trajectory Recorder Not Using OpenAP Profiles

The trajectory recorder functions (`_generate_trajectory_points`) generate historical trajectory lines independently from the live simulation. They still use:
- Ad-hoc altitude interpolation between waypoints (line ~4210-4260)
- `velocity = 200 + climb_progress * 100` for departures (unrealistic step function)
- `velocity = 350 - progress * 210` for approaches (linear, not physics-based)

These are different code paths from the live `_update_flight_state()` that was updated with OpenAP.

### 4.5 BAD: Approach Speed Clamping to Vref Too Early

Multiple flights showing 140kts (Vref) at 4000-5000ft altitude. An aircraft at 4000ft on approach should be ~180-210kts (see FAA 7110.65Y 5-7-1). The live simulation's approach logic clamps to Vref because the OpenAP profile maps to `profile_progress = 0.6 + 0.4 * progress` — at early waypoints (progress=0), it reads the profile at 60%, which may already be at approach speed.

### 4.6 BAD: Glideslope Angle Inconsistency

Computed glideslope angles range from 0.1deg to 3.2deg. Standard ILS glideslope is 3.0deg ±0.5deg. The 0.1deg for UAL4716 means the aircraft traversed almost zero altitude change over its approach path — likely because it just entered the approach and its trajectory is mostly level.

---

## 5. Recommended Improvements (Priority Order)

### P0 — Critical

1. **Fix separation for multi-directional approaches**: Current separation logic only checks sequential "ahead/behind" aircraft on the same approach path. Need to enforce 3NM minimum between ALL approaching aircraft, not just those in sequence. Consider adding altitude-based vertical separation as an alternative (1000ft below FL290).

### P1 — High

2. **Update trajectory recorder to use OpenAP profiles**: The `_generate_trajectory_points()` function for departures and approaches should interpolate from the same OpenAP profiles used in live simulation. This will fix:
   - 500ft altitude stair-steps in departure trajectory lines
   - Linear speed ramps that violate 250kt below FL100
   - Sharp heading jumps at waypoint transitions

3. **Fix approach speed profile**: Don't clamp to Vref until final approach (progress > 0.8 or altitude < 2000ft). At 4000-5000ft, aircraft should be at 180-210kts, decelerating through the speed envelope.

### P2 — Medium

4. **Smooth heading in trajectory recorder**: Apply the same turn-rate interpolation to the trajectory point generator. Instead of snapping heading to the next waypoint at each point, compute a smooth arc through waypoint turns.

5. **Fix glideslope consistency**: Ensure approach altitude decreases at approximately 3deg angle relative to distance. The current mapping of `0.6 + 0.4 * progress` may not correctly model the descent profile for short approach segments.

### P3 — Low

6. **Add vertical separation check**: When lateral separation < 3NM, check if vertical separation >= 1000ft before flagging a violation. This is standard ATC practice for TRACON operations.

7. **Type-specific approach speeds**: Different aircraft types should show different approach speed schedules (e.g., B787 approaches faster than E175). The OpenAP profiles already have this data — ensure the speed from the profile is used rather than a generic Vref clamp.

---

## 6. Screenshot Reference

| File | Description |
|------|-------------|
| `30_default.png` | Default airport view — ground operations, gate positions |
| `31_zoomed_out_4x.png` | Bay Area view — approach corridors visible as gray curves |
| `33_medium_zoom.png` | Medium zoom — runway/taxiway geometry, airport cluster |
| `38_final_overview.png` | Final overview — Bay Area with approach paths |
| `50_marker_selected.png` | Selected OTH1379 — flight detail panel with gate predictions |
| `51_trajectory_enabled.png` | Trajectory toggle ON — blue taxi path rendered on ground |
| `52_trajectory_zoomed_out.png` | Zoomed out with selected flight — regional context |

---

## 7. Conclusion

The OpenAP integration has achieved its primary goal: **approach trajectory lines are now smooth and physics-based**. The 30ft mean altitude jump (down from 200ft+) and realistic speed deceleration profiles represent a major quality improvement.

However, the benefits are **only partially deployed** — the trajectory recorder (which generates the visible trajectory polylines on the map) still uses the old ad-hoc formulas for departures. Applying OpenAP profiles to the recorder is the single highest-impact remaining improvement.

The separation violations at 25% of approach pairs are a functional concern that should be addressed before the simulation can be considered procedurally accurate for ATC training or demonstration purposes.

# Plan: Synthetic Flight Data Audit — Current Rules & Issues

**Phase:** 18 — Post-v1
**Date:** 2026-03-12
**Status:** Not yet implemented

---

## Context

Full audit of the 9 flight phases in `src/ingestion/fallback.py`, documenting current rules (altitude, speed, heading, ground state, gate display, origin/dest) and identifying 10 bugs that affect realism.

---

## Flight Phases — Current Rules

### 1. PARKED (line ~1180)
- **Altitude:** Ground (0 or airport elevation)
- **Speed:** 0
- **Heading:** 180° (hardcoded south-facing)
- **on_ground:** True
- **Gate display:** Shows assigned gate
- **Origin/dest:** Set at creation; origin = random IATA, destination = random IATA

### 2. PUSHBACK (line ~1365)
- **Altitude:** Ground
- **Speed:** ~5 knots (slow reverse)
- **Heading:** 180° (no change — should rotate away from terminal)
- **on_ground:** True
- **Gate display:** Shows assigned gate during pushback
- **Movement:** `latitude -= 0.00002` per tick (always moves south regardless of terminal orientation)

### 3. TAXI_TO_RUNWAY (line ~1391)
- **Altitude:** Ground
- **Speed:** ~15-20 knots
- **Heading:** Follows waypoint-to-waypoint bearing
- **on_ground:** True
- **Gate display:** Hidden
- **Movement:** Follows `TAXI_WAYPOINTS_DEPARTURE` (hardcoded SFO coords)

### 4. TAKEOFF (line ~1408)
- **Altitude:** Ground → ~1000 ft (rapid climb)
- **Speed:** ~150 knots (accelerates on runway)
- **Heading:** Runway heading
- **on_ground:** True → False (transition at rotation)
- **Gate display:** Hidden

### 5. DEPARTING (line ~1430)
- **Altitude:** 1000 → 10000+ ft (climbing)
- **Speed:** ~250 knots (below 10k ft)
- **Heading:** Follows `_get_departure_waypoints(destination)` bearing
- **on_ground:** False
- **Gate display:** Hidden
- **Transition:** Becomes ENROUTE when altitude > threshold or distance from airport > threshold

### 6. ENROUTE (line ~1455)
- **Altitude:** Cruise (~35000 ft)
- **Speed:** ~450 knots
- **Heading:** Varies (simulated cruise path)
- **on_ground:** False
- **Gate display:** Hidden
- **Duration:** Random time before transitioning to APPROACHING

### 7. APPROACHING (line ~1240)
- **Altitude:** Descending from ~10000 to ~3000 ft
- **Speed:** ~180-220 knots (decelerating)
- **Heading:** Follows `_get_approach_waypoints(origin)` bearing toward airport
- **on_ground:** False
- **Gate display:** Hidden
- **Transition:** Follows waypoint sequence toward runway threshold

### 8. LANDING (line ~1340)
- **Altitude:** ~3000 → 0 ft (final descent)
- **Speed:** ~140 knots → ~60 knots (deceleration on runway)
- **Heading:** Runway heading
- **on_ground:** False → True (on touchdown)
- **Gate display:** Hidden

### 9. TAXI_TO_GATE (line ~1277)
- **Altitude:** Ground
- **Speed:** ~15-20 knots
- **Heading:** Follows waypoint-to-waypoint bearing
- **on_ground:** True
- **Gate display:** Shows assigned gate
- **Movement:** Follows `TAXI_WAYPOINTS_ARRIVAL` (hardcoded SFO coords) then straight line to gate

---

## Identified Bugs

### BUG 1: Origin/destination partial for parked aircraft
**Location:** `_create_parked_aircraft()` (~line 800)
**Issue:** Parked aircraft get random `origin` and `destination` IATA codes, but only from a small hardcoded list. Some aircraft end up with `origin == destination` or codes that don't correspond to realistic routes for the airport.
**Impact:** Unrealistic route data; origin-aware approach bearings may point wrong direction.
**Fix:** Use airport-specific route tables (top routes by frequency from BTS/OAG data). Ensure origin ≠ destination.

### BUG 2: Approaching aircraft heading issues from waypoint_index=0
**Location:** `_update_approaching()` (~line 1240)
**Issue:** When `waypoint_index == 0`, the aircraft heading is computed from its current position to waypoint[0], but the initial position may already be past waypoint[0], causing a 180° heading flip or erratic initial movement.
**Impact:** Aircraft appear to briefly face away from the airport on first approaching tick.
**Fix:** Initialize approaching aircraft position at or before waypoint[0], or skip to the nearest upcoming waypoint.

### BUG 3: Same-direction runway operations
**Location:** `_get_approach_waypoints()` / `_get_departure_waypoints()`
**Issue:** Arrivals and departures may use the same runway direction simultaneously. In reality, a runway operates in one direction at a time (determined by wind). Currently, an arrival from the north and a departure to the north could be on a collision course on the same runway.
**Impact:** Unrealistic and potentially confusing visualization — head-on traffic on the same runway.
**Fix:** Establish a single active runway direction per runway (based on wind or random seed). All arrivals land in that direction; all departures take off in that direction.

### BUG 4: Head-on arrival-departure paths
**Location:** Flight path generation
**Issue:** Related to BUG 3 — even on different runways, arrival and departure paths can cross or overlap unrealistically because approach/departure waypoints don't account for standard traffic patterns (downwind, base, final for arrivals; SID routes for departures).
**Impact:** Visual clutter and unrealistic air traffic patterns.
**Fix:** Implement basic traffic pattern separation — arrivals approach from one side, departures climb out the other side.

### BUG 5: _get_departure_waypoints() called without destination during updates
**Location:** `_update_departing()` / general update loop
**Issue:** When `_get_departure_waypoints(destination_iata)` is called during periodic updates, some flights may have `None` destination (e.g., if state was partially initialized), causing a fallback to generic waypoints or an error.
**Impact:** Inconsistent departure paths; some aircraft ignore their destination bearing.
**Fix:** Ensure `destination` is always set before entering DEPARTING phase. Add a guard in `_get_departure_waypoints()` to handle `None` gracefully.

### BUG 6: Parked heading always 180°
**Location:** `_create_parked_aircraft()` (~line 800)
**Issue:** All parked aircraft face south (heading = 180°). In reality, parked aircraft face the terminal (nose-in) or away from it (nose-out), depending on gate configuration. The heading should be perpendicular to the terminal face.
**Impact:** Unrealistic parking visualization — all aircraft point the same direction regardless of terminal orientation.
**Fix:** Compute parked heading from gate position relative to terminal polygon centroid. Nose-in = heading from gate toward terminal center. Nose-out = opposite.

### BUG 7: Gate label only shown for PARKED and TAXI_TO_GATE
**Location:** Frontend `FlightMarker.tsx` / `AirportOverlay.tsx`
**Issue:** The gate label (e.g., "G4") is only displayed when a flight is in PARKED or TAXI_TO_GATE phase. During PUSHBACK and TAXI_TO_RUNWAY, the gate assignment exists in state but isn't shown to the user.
**Impact:** Gate disappears from view during pushback/taxi-out, making it harder to track turnaround operations.
**Fix:** Show gate label for PARKED, PUSHBACK, TAXI_TO_GATE, and optionally TAXI_TO_RUNWAY (with a dimmer style for taxi-out).

### BUG 8: Enroute→Approaching ignores approach queue capacity
**Location:** `_update_enroute()` (~line 1455)
**Issue:** When an ENROUTE flight transitions to APPROACHING, there's no check for how many aircraft are already approaching. This can lead to unrealistic bunching — 10+ aircraft all on final approach simultaneously.
**Impact:** Congestion spikes that wouldn't occur in real ATC-managed traffic. Separation constraints are applied but late, causing jerky speed adjustments.
**Fix:** Check current APPROACHING count before transitioning. If at capacity (e.g., max 4-6 on approach per runway), keep the flight ENROUTE (holding pattern) until a slot opens.

### BUG 9: Parked aircraft origin/destination not swapped on pushback
**Location:** `_update_pushback()` / `_transition_to_pushback()`
**Issue:** When a parked aircraft pushes back to depart, it should conceptually swap origin/destination (this airport becomes the origin, previous origin becomes destination). Currently, the fields are left unchanged, so a "departing" flight still shows its original arrival origin.
**Impact:** Origin-aware departure waypoints may point toward the arrival origin instead of the departure destination. Flight info panel shows stale route data.
**Fix:** On pushback initiation: `state.origin, state.destination = current_airport_iata, state.origin` (swap). This makes the departure heading point toward the original origin airport (now the destination).

### BUG 10: No wind-based runway direction
**Location:** Runway selection logic (implicit)
**Issue:** Runway active direction is not modeled. Real airports switch runway direction based on prevailing wind (aircraft always land/take off into the wind). Currently, runway usage is random or fixed.
**Impact:** Related to BUG 3 — without a consistent runway direction, arrival and departure paths conflict. Also affects realism of noise abatement and traffic flow patterns.
**Fix:** Model a simple wind direction (random per session or configurable). Set runway active direction based on wind. All operations use the into-wind direction. Could later integrate real METAR data.

---

## Priority Order for Fixes

| Priority | Bug | Impact | Effort |
|----------|-----|--------|--------|
| P0 | BUG 3+10 | Runway direction consistency | Medium — needs wind model + runway direction state |
| P0 | BUG 9 | Origin/dest swap on pushback | Low — simple field swap |
| P1 | BUG 5 | Missing destination guard | Low — add null check |
| P1 | BUG 6 | Parked heading from terminal | Medium — needs terminal geometry lookup |
| P1 | BUG 2 | Approaching initial heading | Low — position initialization fix |
| P2 | BUG 8 | Approach queue capacity | Medium — needs counter + holding state |
| P2 | BUG 1 | Realistic origin/dest routes | Medium — needs route frequency data |
| P2 | BUG 7 | Gate label visibility | Low — frontend display logic |
| P3 | BUG 4 | Traffic pattern separation | High — needs SID/STAR-like patterns |

---

## Files Affected

| File | Changes |
|------|---------|
| `src/ingestion/fallback.py` | BUG 1-6, 8-9: Core flight state machine fixes |
| `app/frontend/src/components/Map/FlightMarker.tsx` | BUG 7: Gate label visibility rules |
| `app/frontend/src/components/Map/AirportOverlay.tsx` | BUG 7: Gate label rendering |
| `src/routing/taxiway_graph.py` (Phase 14) | Dependency for BUG 3+10 runway direction |
| `tests/ingestion/test_fallback.py` | Updated tests for all bug fixes |

---

## Verification

1. `uv run pytest tests/ -v` — all backend tests pass
2. `cd app/frontend && npm test -- --run` — all frontend tests pass
3. Visual: `./dev.sh` → observe:
   - All aircraft on a runway land/depart in the same direction
   - Parked aircraft face toward terminals (not all south)
   - Pushback moves away from terminal (not always south)
   - Approaching aircraft don't briefly face away from airport
   - Gate label visible during pushback
   - No more than ~6 aircraft on approach simultaneously
   - Departing aircraft head toward their destination

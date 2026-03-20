# Phase 41: UX Design Review — 2D View Simulation Realism

## Review Method

Systematic observation of the Airport Digital Twin 2D view (KSFO) over ~5 minutes of simulation time. Observed approach, landing, taxi, turnaround, departure, and takeoff phases. Compared aircraft behavior against real aviation physics and airport operations. Captured 8 screenshots.

---

## Critical Issues (Physics Bugs)

### 1. Negative Altitude — Aircraft Descend Below Ground Level
**Severity: Critical**
**Observed:** UAL123 descended to -206ft, then -990ft, before bouncing back to 50ft. UAL4983 descended to -735ft. CZ7666 showed CLB ALT: -261ft during initial climb.

**Root Cause:** The approach path altitude calculation allows negative values. When the sim interpolates between approach waypoints, it can overshoot below 0ft without a floor clamp. For departures, the altitude starts at 0 but the interpolation may briefly go negative.

**Fix:** Clamp altitude to `max(0, computed_altitude)` in `_update_flight_state()` for all phases. Specifically:
- In the approach/landing altitude interpolation logic
- In the departure/climbing altitude calculation
- As a final safety net: `state.altitude = max(0.0, state.altitude)` after any altitude update

### 2. Taxi Speed While At Gate (Turnaround Active)
**Severity: High**
**Observed:** UAL123 at gate A12, turnaround phase "Unloading 54%", but speed shows 25kts. OTH9005 at gate B3, turnaround "Deboarding", speed 25kts with heading actively changing. CZ7666 showed turnaround "Deboarding 28%" while speed was 25kts.

**Root Cause:** The `velocity` field is not reset to 0 when aircraft enters the PARKED phase / begins turnaround. The sim keeps the last taxi speed. Ground aircraft at a gate should have 0 speed.

**Fix:** In `_update_flight_state()`, when phase transitions to PARKED or turnaround begins:
```python
if state.phase == FlightPhase.PARKED:
    state.velocity = 0.0
    state.vertical_rate = 0.0
```

### 3. Gate Recommendations Shown for Aircraft Already at Gate
**Severity: Medium**
**Observed:** CZ7666 at gate B3 (turnaround active) still showing "Gate Recommendations" panel with A1, B1, G1 suggestions. This happens when `assigned_gate` is not set in the flight data even though turnaround panel knows the gate.

**Root Cause:** Inconsistency between `assigned_gate` field (used by FlightDetail gate recommendation logic) and turnaround component (which gets gate from a different source). The `needsGateAssignment` check passes because `assigned_gate` is null even though the aircraft is at a gate.

**Fix:** Ensure `assigned_gate` is populated in the flight state when turnaround begins. The turnaround component already knows the gate — the flight data should too.

---

## High Priority Issues (Data Integrity)

### 4. FIDS ETA Times Wildly Inaccurate
**Severity: High**
**Observed:** Approaching aircraft at 2500-4800ft altitude (minutes from landing) show ETAs hours in the future:
- UAL4983 at 763ft → ETA 21:57 (2+ hours away)
- ASA4638 at 1116ft → ETA 01:25 (6+ hours away)
- UAL1419 at 3800ft → ETA 02:52 (7+ hours away)
- UAL5568 at 2500ft → ETA 04:31 (9+ hours away)
- UAL1624 at 4800ft → ETA 09:51 (14+ hours away)

**Root Cause:** The scheduled arrival time is computed from cruise distance/speed rather than actual current position and approach progress. Once in approach, ETA should be recalculated based on current altitude/distance from airport.

**Fix:** In `get_flights_as_schedule()`, for descending flights, compute ETA from current position:
```python
if phase == FlightPhase.APPROACHING or phase == FlightPhase.LANDING:
    # ETA based on current altitude and descent rate
    remaining_minutes = state.altitude / abs(descent_rate_fpm) if descent_rate_fpm else 5
    eta = now + timedelta(minutes=remaining_minutes + taxi_buffer)
```

### 5. Gate "G869" — Invalid Gate Name from OSM
**Severity: Medium**
**Observed:** CZ7666 departure assigned to gate "G869" in FIDS. This is not a real SFO gate — likely an OSM artifact (a way/node ID leaking through as a gate name).

**Fix:** Filter or rename gates with numeric-only or obviously invalid names during OSM import. Add validation in `converter.py` to skip gates without recognizable terminal-letter + number format.

### 6. Airline Name Resolution Incomplete
**Severity: Low**
**Observed:** FIDS shows raw ICAO codes instead of airline names for some carriers:
- "CZ7" for CZ7666 (should be "China Southern Airlines")
- "HAL" for HAL2980 (should be "Hawaiian Airlines" — but HAL2782 shows correctly)
- "OTH" for OTH carriers (placeholder — expected for synthetic)
- "MXA" for MXA8198, "ACA" for ACA195

**Root Cause:** The airline lookup table is incomplete or the ICAO prefix extraction is wrong for some callsigns.

**Fix:** Expand airline lookup in the schedule/FIDS code. For "CZ7666", the ICAO code should be "CSN" (China Southern), but the callsign format "CZ7666" uses IATA code. Need to handle both ICAO and IATA code lookups.

---

## Medium Priority Issues (UX Polish)

### 7. Heading Shows 0 for Parked/Stationary Aircraft
**Severity: Low**
**Observed:** UAL123 at gate A12 shows heading "0 deg". While not wrong per se, real parked aircraft face the gate (or away from it). The heading should reflect the aircraft's parking orientation.

**Note:** Earlier observation showed heading >360 (383 deg) for ACA195 — this seems to have been fixed or was transient. Worth adding normalization guard: `heading = heading % 360`.

### 8. Console Errors — 2015 Duplicate Key Warnings
**Severity: Medium (Performance)**
**Observed:** Over 2000 React console warnings about duplicate keys in `AirportOverlay.tsx`:
```
Warning: Encountered two children with the same key `G1-false`
Warning: Encountered two children with the same key `G2-false`
```

**Root Cause:** Gate IDs from two different OSM sources (terminal gates and standalone gates) have overlapping names (G1, G2, etc.). The key generation `${gate.id}-${occupied}` produces duplicates.

**Fix:** Use a composite key that includes the gate's source or a unique index:
```tsx
key={`${gate.source || 'default'}-${gate.id}-${index}`}
```

### 9. "Last Seen" Timestamp Stuck
**Severity: Low**
**Observed:** All flights show "Last Seen: 13:45:45" regardless of current time (19:42). This static timestamp doesn't provide useful information.

**Fix:** Update `last_seen` on each simulation tick, or hide it for synthetic data.

### 10. Departure Climb Delay — Altitude Stays at 0 After Takeoff
**Severity: Medium**
**Observed:** CZ7666 transitioned to "climbing" phase with speed 137kts but altitude remained at 0ft for several seconds before climbing. A real aircraft at 137kts on takeoff roll should be lifting off or already airborne.

**Fix:** Accelerate the altitude ramp-up during initial climb. Once speed exceeds rotation speed (~130kts for most jets), altitude should start increasing immediately.

---

## Low Priority Issues (Nice to Have)

### 11. All Delay Predictions Show "Severe Delay"
**Observed:** Every flight checked shows "Severe Delay +53-58m, 70% confidence". The ML model appears to produce the same prediction regardless of flight characteristics.

**Fix:** This is a known limitation of the synthetic ML model. Low priority but worth noting for demo credibility.

### 12. Simulation Timeline Playback Bar Partially Obscured
**Observed:** The simulation timeline at the bottom has a "Start" label but the timeline itself is small and hard to interact with.

### 13. Phase Distribution Imbalance
**Observed:** Of 50 flights: 18 ground, 23 cruising, 8 descending, 1 climbing. Only 1 departure/climbing aircraft visible at a time. For a realistic airport view, there should be more taxi/departure activity.

**Note:** Phase 21 partially addresses this with rebalanced weights. May need further tuning after scaling to 100 flights.

---

## Summary: Prioritized Fix Plan

| Priority | Issue | Effort | Impact |
|----------|-------|--------|--------|
| P0 | Negative altitude clamp | Small | Breaks immersion, physics violation |
| P0 | Taxi speed at gate = 0 | Small | Contradicts turnaround panel |
| P1 | FIDS ETA for approaching flights | Medium | FIDS useless for approaching flights |
| P1 | Console duplicate keys (perf) | Small | 2000+ errors, React perf degradation |
| P1 | Gate data inconsistency | Medium | Turnaround vs flight detail mismatch |
| P2 | Invalid gate names (G869) | Small | Confusing gate assignments |
| P2 | Departure climb delay | Medium | Unrealistic takeoff sequence |
| P2 | Airline name resolution | Small | Incomplete FIDS display |
| P3 | Last Seen timestamp | Small | Static, unhelpful |
| P3 | Heading normalization guard | Small | Prevent >360 edge case |
| P3 | Uniform delay predictions | Large | ML model limitation |

---

## Evidence

Screenshots saved in `.planning/phases/41-ux-review/`:
- `screenshot_t0_overview.png` — Airport overview
- `screenshot_t10_movement.png` — UAL123 descent progress
- `screenshot_taxi_aca195.png` — ACA195 taxi with heading 383
- `screenshot_t25_aca195.png` — ACA195 15s later
- `screenshot_cz7666_taxi.png` — CZ7666 taxi/turnaround inconsistency
- `screenshot_ual123_lowalt.png` — UAL123 low altitude approach
- `screenshot_fids.png` — FIDS arrivals with wild ETAs
- `screenshot_fids_departures.png` — FIDS departures with G869 gate

## What Works Well

- **Approach trajectories**: Descent from 5000ft+ with decreasing altitude looks natural
- **Airport overlay**: OSM gates, terminals, taxiways render correctly on the map
- **Flight list**: Sortable, searchable, real-time updates via WebSocket
- **Turnaround timeline**: Visual progress through turnaround phases with equipment tracking
- **Baggage status**: Counts and progress integrated per-flight
- **Gate status panel**: Terminal breakdown with occupancy counts
- **FIDS departures**: Delayed flights shown with delay amounts and estimated times
- **Weather display**: METAR-style weather in header bar

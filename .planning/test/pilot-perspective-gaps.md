---
title: "Gap Analysis — Civil Airline Pilot Perspective"
status: backlog
area: simulation
priority: medium
related:
  - operator-validation-gaps.md
  - operator-focused-tests-plan.md
---

# Gap Analysis — Civil Airline Pilot Perspective

## What's Already Tested (strong coverage)

| Area | Existing Tests |
|------|---------------|
| Approach speed near Vref | `test_approach_speed_near_vref` |
| 250kt below FL100 | `test_below_fl100_speed_limit` |
| Descent rate limits | `test_descent_rate_reasonable` |
| Decision height compliance | `test_decision_height_compliance` |
| Takeoff acceleration | `test_takeoff_acceleration` |
| Go-around climb rate | `test_go_around_climb_rate` |
| Runway single occupancy | `test_runway_single_occupancy` |
| Approach separation | `test_approach_separation_minimum` |
| Landing altitude (low) | `test_landing_altitude_low` |
| Taxi speed < limit | `test_taxi_speed_below_limit` |
| No teleportation | `test_no_teleportation` |
| Departure altitude increases | `test_departure_altitude_increases` |
| Phase transitions valid | `test_no_invalid_transitions` |

## What's MISSING (pilot blind spots)

### 1. Stabilized Approach Criteria (ICAO/airline SOPs)

No test that below 1000ft AGL: speed ∈ [Vref, Vref+20], descent rate < 1000 fpm, on glideslope (3° ± 0.5°), configured (speed not fluctuating wildly). This is the #1 cause of go-arounds IRL.

### 2. Takeoff V-speeds / rotation / liftoff sequence

Code has `takeoff_subphase`: lineup/roll/rotate/liftoff/initial_climb but NO test validates:
- V1 ≤ Vr ≤ V2 ordering
- Rotation happens at Vr (130-160kt depending on type)
- Liftoff altitude = field elevation + 35ft (screen height)
- Initial climb rate ≥ 500 fpm (Part 25 min gradient)

### 3. Climb performance (SID compliance)

No test validates:
- Initial climb speed: V2+10 to V2+20 (before acceleration altitude)
- Acceleration altitude (~1500ft AGL): speed increases from V2 to clean speed (220-250kt)
- Below FL100: speed never exceeds 250kt (tested for approach but NOT departure)
- Climb gradient ≥ 3.3% (200ft/NM) for obstacle clearance

### 4. Missed approach procedure fidelity

Go-around climb to missed approach altitude is tested, but:
- No test validates the aircraft climbs straight ahead to missed approach point before turning
- No test validates the standard rate turn (3°/s) in the missed approach pattern
- No test validates the missed approach altitude (minimum 1500ft AGL per ICAO)
- No test validates speed management (TOGA thrust → Vref+20 → clean speed)

### 5. Holding pattern geometry

Aircraft enter holding after go-around, but no test checks:
- Standard racetrack pattern (1-min legs)
- Right-hand turns (standard) at standard rate (3°/s)
- Holding speed limits (230kt below FL140, 265kt FL140-FL200)
- Entry type based on inbound heading (direct/parallel/teardrop)

### 6. Landing rollout / deceleration physics

No test checks:
- Touchdown speed ≈ Vref - 5 to Vref + 5
- Deceleration from touchdown to taxi speed (braking ~3-5 kt/s)
- Landing distance proportional to aircraft weight category
- Runway exit speed ≈ 60kt (high-speed exit) or 30kt (90° exit)

### 7. Energy management — speed/altitude coupling

No test checks the fundamental pilot constraint: you can't be fast AND low
- At 10 DME (final approach fix): ~3000ft, ~180kt (clean)
- At 5 DME: ~1500ft, ~160kt (configured)
- At 1 DME: ~300ft, Vref+5 (stable)
- Validates glideslope = 3° (altitude should be ≈ distance_nm × 318ft)

### 8. Fuel / weight-related performance bounds

No test that heavy aircraft (B777, A350) approach faster than light ones (A320, B737):
- `Vref_heavy > Vref_light` should hold in the sim output

### 9. Departure turn restrictions

No test validates that departing aircraft:
- Don't turn below 400ft AGL (straight-out departure minimum)
- Reach acceleration altitude before first SID turn
- Maintain positive climb through the turn

### 10. Wind correction / crosswind limits

The sim has wind in scenarios, but no test validates:
- Aircraft heading ≠ track when wind is present (crab angle)
- Approach speed increases with headwind (Vref + ½ headwind component)
- Crosswind component doesn't exceed aircraft limits (~33kt for A320)

## Priority Recommendation

1. **Stabilized approach** — safety-critical, directly maps to sim logic
2. **Takeoff V-speeds / rotation** — code has subphases but no validation
3. **Energy management on approach** — 3° glideslope = altitude/distance coupling
4. **Landing rollout deceleration** — touchdown → taxi speed physics

---
title: "Pilot-Focused Aviation Tests — Regulations, Physics, Procedures"
status: backlog
area: simulation
priority: medium
related:
  - pilot-perspective-gaps.md
  - operator-focused-tests-plan.md
---

# Plan: Pilot-Focused Aviation Tests — Regulations, Physics, Procedures

## Context

From a civil airline pilot's perspective, the existing tests cover basic speed limits and separation but miss critical procedural and physics validations. The simulation models V-speeds, stabilized approach criteria, missed approach patterns, holding patterns, and multi-subphase takeoffs — but many of these are untested. Adding these tests ensures the sim produces outputs a type-rated pilot would accept as realistic.

## Sim Capabilities Already Modeled (code references)

| Feature | Implementation | Constants |
|---------|---------------|-----------|
| V1/Vr/V2 per type | `_flight_lifecycle.py:1480-1589` | `_constants.py:250-270 TAKEOFF_PERFORMANCE` |
| Takeoff subphases | lineup→roll→rotate→liftoff→initial_climb | `FlightState.takeoff_subphase` |
| Stabilized approach | Vref+30 cap below 1000ft, 1500 fpm max | `_constants.py:195-198` |
| Decision height | 200ft Cat I ILS trigger | `_constants.py:194 DECISION_HEIGHT_FT` |
| Landing rollout | 5 kt/s braking, exit at ≤30kt, release at ≤80kt | `_flight_lifecycle.py:1057-1071` |
| Go-around procedure | Climb 1500ft, straight 60s, standard rate turn | `_flight_lifecycle.py:785-820, 1699-1825` |
| Holding pattern | 1-min legs, 3°/s, right-hand turns | `_flight_lifecycle.py:1801-1825` |
| Departure speed cap | 250kt below FL100, 2 kt/s accel | `_flight_lifecycle.py:1610` |
| No turn below 400ft | initial_climb on runway heading until 500ft | `_flight_lifecycle.py:1574` |
| Vref by type | 18 aircraft types, 125-155kt range | `_constants.py:201-211` |

---

## Test Files to Create

### 1. `tests/test_pilot_stabilized_approach.py` — Stabilized Approach Criteria

**Regulatory basis:** ICAO Doc 9869 (stabilized approach), airline SOPs.
**Fixture:** Module-scoped, SFO, 15+15 flights, 6h, seed=42, diagnostics=True.

**Tests (~6):**
- `test_speed_within_vref_band_below_1000ft` — all approach snapshots below 1000ft have speed ∈ [Vref-10, Vref+30]
- `test_descent_rate_below_1000ft` — no snapshot below 1000ft AGL with >1500 fpm descent
- `test_speed_decreasing_on_final` — speed trend from 3000ft→touchdown is monotonically decreasing (allow 5% exceedances)
- `test_altitude_distance_coupling` — at each waypoint, altitude ≈ distance_to_threshold × 318ft (3° glideslope ± 30%)
- `test_no_level_off_below_500ft` — below 500ft, altitude never increases (no level-offs during final)
- `test_configured_speed_below_2000ft` — below 2000ft, speed ≤ Vref+30 (not racing in at 250kt)

### 2. `tests/test_pilot_takeoff_vspeeds.py` — Takeoff V-Speed Sequence & Physics

**Regulatory basis:** 14 CFR 25.107/111, FCOM performance tables.
**Fixture:** Module-scoped, SFO, 8+15 departures, 4h, seed=42, diagnostics=True.

**Tests (~7):**
- `test_v1_leq_vr_leq_v2` — V-speed ordering verified in TAKEOFF_PERFORMANCE dict
- `test_rotation_speed_at_vr` — takeoff→rotate transition happens near Vr (±10kt)
- `test_liftoff_positive_climb` — altitude > 0 within 5s after rotate subphase
- `test_initial_climb_gradient` — from liftoff to 500ft: climb rate ≥ 500 fpm (Part 25 minimum)
- `test_no_turn_below_400ft` — during takeoff phase, heading stays within ±5° of runway heading
- `test_speed_increases_during_roll` — velocity monotonically increases during "roll" subphase
- `test_heavy_aircraft_higher_vspeeds` — B777/A380 V-speeds > A320/B737 V-speeds (type comparison)

### 3. `tests/test_pilot_landing_rollout.py` — Landing Deceleration & Runway Exit

**Regulatory basis:** 14 CFR 25.125, airline FCOM (landing distance).
**Fixture:** Module-scoped, SFO, 15+8 flights, 6h, seed=42, diagnostics=True.

**Tests (~6):**
- `test_touchdown_speed_near_vref` — first on-ground snapshot speed ∈ [Vref-10, Vref+15]
- `test_deceleration_rate_realistic` — braking decel ≤ 6 kt/s (realistic for commercial)
- `test_runway_exit_speed_below_60kt` — landing→taxi transition speed ≤ 60kt
- `test_rollout_distance_proportional` — heavy aircraft (B777) rollout further than light (A320)
- `test_no_negative_speed_during_rollout` — velocity never goes below 0
- `test_vertical_rate_zero_on_ground` — after touchdown, vertical_rate = 0

### 4. `tests/test_pilot_missed_approach.py` — Go-Around / Missed Approach Procedure

**Regulatory basis:** ICAO Doc 8168 (PANS-OPS), FAA AIM 5-4-21.
**Fixture:** Module-scoped, SFO, 20+20, 6h, seed=42, scenario: `sfo_summer_thunderstorm.yaml` (induces go-arounds).

**Tests (~6):**
- `test_go_around_climbs_immediately` — vertical_rate > 0 within first 2 snapshots after go-around
- `test_missed_approach_altitude_minimum` — go-around climb target ≥ 1500ft AGL
- `test_straight_ahead_before_turn` — after go-around, heading unchanged for ≥30s (fly runway heading)
- `test_standard_rate_turn_in_pattern` — turn rate during missed approach ≤ 3.5°/s
- `test_speed_increases_after_go_around` — speed trend from go-around initiation is increasing (TOGA)
- `test_go_around_speed_above_vref` — during entire missed approach, speed ≥ Vref

### 5. `tests/test_pilot_holding_pattern.py` — Holding Pattern Geometry

**Regulatory basis:** FAA 7110.65 6-5-1, ICAO Doc 4444 §6.5.
**Fixture:** Module-scoped, SFO, 25+25, 6h, seed=42, scenario: `sfo_summer_thunderstorm.yaml` (forces holds when approach is full).

**Tests (~5):**
- `test_holding_speed_limits` — speed ≤ 230kt below FL140 (10000ft in sim context → ≤250kt)
- `test_holding_right_hand_turns` — heading changes during holding are predominantly clockwise (right turns)
- `test_holding_leg_duration` — inbound and outbound legs approximately 60s (±30s tolerance)
- `test_holding_altitude_stable` — altitude does not change significantly during holding (±200ft)
- `test_holding_exits_to_approach` — aircraft in holding eventually transition to APPROACHING

### 6. `tests/test_pilot_energy_management.py` — Speed/Altitude Coupling & Departure Profile

**Regulatory basis:** ICAO Doc 8168, 14 CFR 91.117, SID design criteria.
**Fixture:** Module-scoped, SFO, 12+12, 6h, seed=42, diagnostics=True.

**Tests (~6):**
- `test_250kt_below_fl100_departures` — departing aircraft below 10000ft never exceed 260kt
- `test_departure_altitude_monotonic` — altitude never decreases during DEPARTING phase
- `test_departure_climb_rate_minimum` — average climb ≥ 500 fpm during departure (3.3% gradient at 150kt)
- `test_speed_altitude_inverse_on_approach` — higher altitude correlates with higher speed (at >3000ft)
- `test_heavy_approach_faster_than_light` — average approach speed for B777 > average for A320
- `test_enroute_speed_below_mmo` — enroute aircraft below 600kt (MAX_VELOCITY_KTS)

---

## Key Implementation Patterns

**Reuse from existing tests:**
- `tests/sim_helpers.py`: `extract_flight_traces()`, `phase_positions()`, `phase_sequence()`, `haversine_nm()`
- Module-scoped fixtures: `SimulationConfig` → `SimulationEngine` → `recorder`
- Phase transition scanning: `recorder.phase_transitions` for timing
- Snapshot scanning: traces from `extract_flight_traces()` for per-tick validation

**New helper needed (add to `tests/sim_helpers.py`):**
- `approach_final_snapshots(trace, below_ft=1000)` — filter approach-phase snapshots below given altitude

**Constants to reference (from `src/ingestion/_constants.py`):**
- `VREF_SPEEDS`, `_DEFAULT_VREF`, `TAKEOFF_PERFORMANCE`, `_DEFAULT_TAKEOFF_PERF`
- `DECISION_HEIGHT_FT = 200`, `MAX_SPEED_BELOW_FL100_KTS = 250`

## Files to Create/Modify

| File | Action |
|------|--------|
| `tests/test_pilot_stabilized_approach.py` | Create |
| `tests/test_pilot_takeoff_vspeeds.py` | Create |
| `tests/test_pilot_landing_rollout.py` | Create |
| `tests/test_pilot_missed_approach.py` | Create |
| `tests/test_pilot_holding_pattern.py` | Create |
| `tests/test_pilot_energy_management.py` | Create |

No production code changes needed — these are pure validation tests against existing sim output.

## Implementation Order

1. `test_pilot_takeoff_vspeeds.py` — validates V-speed constants + subphase transitions
2. `test_pilot_stabilized_approach.py` — validates final approach physics
3. `test_pilot_landing_rollout.py` — validates touchdown→taxi deceleration
4. `test_pilot_missed_approach.py` — requires scenario (go-arounds)
5. `test_pilot_holding_pattern.py` — requires scenario (approach capacity)
6. `test_pilot_energy_management.py` — cross-cutting speed/altitude validation

## Verification

```bash
uv run pytest tests/test_pilot_stabilized_approach.py tests/test_pilot_takeoff_vspeeds.py \
  tests/test_pilot_landing_rollout.py tests/test_pilot_missed_approach.py \
  tests/test_pilot_holding_pattern.py tests/test_pilot_energy_management.py -v
```

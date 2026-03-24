# Simulation Defect Report: ASA448 Full Lifecycle Analysis

**Flight:** ASA448 (sim00056) | **Aircraft:** A319
**Airport:** SFO | **Simulation:** `simulation_output_sfo_100.json`
**Video:** `video_output/asa448_full_lifecycle.mp4` (16s, 127 frames at 8fps)
**Time window:** 14:35 UTC — 15:32 UTC (57.5 min total)
**Analysis date:** 2026-03-24

---

## Executive Summary

12 defects identified across physics, data integrity, and operations modeling.
**3 Critical (P0)**, **5 High (P1)**, **4 Medium (P2)**.

The simulation produces visually plausible flight movement but fails physics validation on takeoff speeds, climb rates, descent profiles, and heading continuity. The baggage subsystem is broken for 78% of flights. Every phase transition is recorded twice.

---

## Flight Timeline

| Time (UTC) | Phase | Duration | Notes |
|------------|-------|----------|-------|
| 14:35:00 | Approaching | 4.5 min | Initial alt 4,800ft, hdg 0° |
| 14:39:30 | Landing | 2 sec | Touch-and-go instant |
| 14:39:32 | Taxi to gate | 31.4 min | Gate B3 assigned |
| ~15:11:00 | Parked | 0 min | Missing transition record |
| 15:11:26 | Pushback | 4.0 min | 3 kts pushback speed |
| 15:15:28 | Taxi to runway | 5.9 min | Gate B3 released |
| 15:21:20 | Takeoff | 1.2 min | Roll speed 17 kts |
| 15:22:30 | Departing | 4.5 min | Climb to 8,000ft |
| 15:27:00 | Enroute | 5.5 min | Climb to FL350 |

---

## Defects

### D01 — Takeoff at 17 kts (should be ≥130 kts) [P0 CRITICAL]

**Evidence:** Snapshot [93] at takeoff phase start shows `vel=17 kts`.
**Video frame:** ~frame 93 of 127 (11.6s into video).

**What's wrong:** The A319 V1 (decision speed) is ~130 kts, Vr (rotation) ~135 kts. The simulation starts the takeoff phase at 17 kts with no acceleration roll — it's still at taxi speed. The next frame [94] jumps to 101 kts instantly (+84 kts in 30 seconds).

**Root cause:** `_force_advance()` in `engine.py:900-906` jumps a stuck taxi_to_runway flight directly into takeoff phase without setting proper initial velocity. The takeoff subphase starts at whatever the taxi speed was.

**Fix:** In `_force_advance()` for TAXI_TO_RUNWAY→TAKEOFF, set `state.velocity = 0` and ensure the takeoff subphase starts from `lineup` with proper acceleration model. Better yet, the takeoff phase handler in `fallback.py` should model the acceleration roll: 0 → Vr over ~35-45 seconds.

---

### D02 — Impossible climb rates: 6,000 and 30,000 fpm [P0 CRITICAL]

**Evidence:**
- Snapshot [98]: alt jumps 2,000→5,000ft in 30s = **6,000 fpm** (departing phase)
- Snapshot [101]: alt jumps 5,000→8,000ft in 30s = **6,000 fpm** (departing phase)
- Snapshot [105]: alt jumps 8,000→23,000ft in 30s = **30,000 fpm** (enroute phase)
- Snapshot [106]: alt jumps 23,000→35,000ft in 30s = **24,000 fpm** (enroute phase)

**What's wrong:** A319 maximum climb rate is ~3,500-4,000 fpm at low altitude, decreasing to ~1,500-2,000 fpm above FL200. The simulation produces climb rates 2-10x higher than physically possible. A military fighter jet tops out at ~30,000 fpm.

**Root cause:** The departure/enroute altitude stepping in `fallback.py` uses large altitude increments (3,000-15,000 ft) that exceed what's physically achievable in a 30-second frame interval. The OpenAP vertical rate profile is either not being used or is overridden.

**Fix:** Cap altitude change per tick to `max_climb_rate * dt_seconds / 60`. For A319: max 4,000 fpm at low altitude, 2,000 fpm above FL200. With 30s ticks: max +2,000 ft/tick at low altitude, +1,000 ft/tick at high altitude.

---

### D03 — Baggage generation broken for 78% of parked flights [P0 CRITICAL]

**Evidence:** 59 flights reached PARKED state. Only 13 baggage events generated. sim00056 (ASA448) has **zero** baggage events despite completing a full arrival→parked cycle.

**What's wrong:** Flights that reach PARKED via `_force_advance()` (engine.py:881-898) are not added to `_completed_flights` list. Only flights whose `taxi_to_gate→parked` transition is detected in the normal `_update_all_flights()` loop (line 812-813) get baggage generated.

**Root cause:** `_force_advance()` sets `state.phase = FlightPhase.PARKED` directly (line 895) but never appends to `self._completed_flights`. The baggage generator at line 1147-1164 only processes `_completed_flights`.

**Fix:** Add to `_force_advance()` TAXI_TO_GATE handler:
```python
sched = self._find_schedule_entry(icao24)
if sched:
    self._completed_flights.append({
        "icao24": icao24,
        "callsign": state.callsign,
        "schedule": sched,
        "parked_time": self.sim_time,
    })
```

---

### D04 — Vertical rate field always 0.0 despite clear altitude changes [P1 HIGH]

**Evidence:** All 116 snapshots for ASA448 have `vertical_rate=0.0`, despite altitude changing by 600-15,000 ft between consecutive frames.

**What's wrong:** The simulation computes vertical rate internally (line 840, 924, 972 set it to 1500) but the value recorded in position snapshots is always 0. The `vertical_rate` field is either not being written from the flight state to the snapshot, or is being reset before capture.

**Root cause:** The `vertical_rate` is set on the FlightState during specific phase transitions (go-around, certain departures) but not continuously updated during normal flight. The approach phase, which should have ~-700 fpm, never sets it. The snapshot capture reads whatever value the state has, which defaults to 0.

**Fix:** Compute `vertical_rate` from altitude delta each tick: `vr = (current_alt - prev_alt) / (dt_seconds / 60)` and store it on the flight state before snapshot capture.

---

### D05 — Duplicate phase transitions (every transition recorded twice) [P1 HIGH]

**Evidence:** ASA448 has 15 phase transitions but only 8 unique ones. Every transition from `approaching→landing` onwards is duplicated with identical timestamps.

**What's wrong:** Two recording paths fire for the same transition:
1. `engine.py:805` — `self.recorder.record_phase_transition()` when detecting `new_phase != old_phase`
2. `fallback.py:emit_phase_transition()` — called inside the fallback movement functions

Both execute for the same state change. The engine's `_capture_phase_transitions()` (line 1093-1100) correctly drains without re-recording, but the fallback module's `emit_phase_transition` calls inside movement functions are the second source.

**Fix:** Remove `emit_phase_transition()` calls from `fallback.py` movement functions, since the engine already records transitions. Or, remove the engine's direct recording and use only the buffer. One path, not two.

---

### D06 — Missing taxi_to_gate → parked transition [P1 HIGH]

**Evidence:** Phase transitions show: `landing → taxi_to_gate` (14:39:32) then `parked → pushback` (15:11:26). No `taxi_to_gate → parked` recorded.

**What's wrong:** The transition happens inside `_force_advance()` which directly mutates `state.phase` without going through the normal phase-change detection or recording a transition.

**Root cause:** Same as D03 — `_force_advance()` bypasses the phase transition recording at engine.py:805.

**Fix:** Add `self.recorder.record_phase_transition()` call in `_force_advance()` when changing phases.

---

### D07 — Approach starts at heading 0° (due north) [P1 HIGH]

**Evidence:** Snapshot [0] at 14:35:00: `hdg=0.0°`, then jumps to 279.1° in the next frame. SFO RWY 28R has heading ~281°.

**What's wrong:** The initial spawn heading is 0° (default) instead of being set to the inbound approach heading. This creates a 279° heading discontinuity in the first 30 seconds — the aircraft appears to be coming from due north then instantly rotates westward.

**Root cause:** Flight spawn in engine.py sets initial heading to 0 (default). The approach trajectory waypoints correct this on the second tick.

**Fix:** Set initial heading to the bearing from spawn point toward the airport or the first waypoint when spawning approach flights.

---

### D08 — Constant -1,200 fpm descent (steeper than 3° glideslope) [P1 HIGH]

**Evidence:** Frames [0]-[7]: altitude drops exactly 600ft every 30 seconds = constant -1,200 fpm. Standard 3° glideslope at 150 kts ≈ -700 fpm.

**What's wrong:** The approach descent rate is 1.7x steeper than a standard ILS approach. At -1,200 fpm the approach angle is ~5.1°, which would trigger GPWS "GLIDESLOPE" warnings.

**Root cause:** The approach phase in fallback.py appears to use a linear altitude step of 600ft/tick regardless of speed and distance. It should compute descent rate from target altitude, distance to threshold, and 3° glideslope geometry.

**Fix:** Compute descent rate as: `vr = groundspeed * tan(3°) * 60` → at 160 kts: ~800 fpm. Or use OpenAP's approach profile which was recently integrated (commit 18dbc12).

---

### D09 — Instant speed jumps between frames [P2 MEDIUM]

**Evidence:**
- [93]→[94]: 17→101 kts (+84 kts in 30s = 2.8 kts/s acceleration)
- [94]→[95]: 101→148 kts (+47 kts in 30s)
- [95]→[96]: 148→250 kts (+102 kts in 30s = 3.4 kts/s — unrealistic for A319)

**What's wrong:** A319 max acceleration ~1.5-2 kts/s during takeoff roll. The 101→250 kts jump in 60 seconds is too aggressive. Speed should ramp up following a realistic takeoff acceleration profile.

**Fix:** Apply per-tick speed limiting: `max_delta_v = max_accel * dt_seconds`. For A319 takeoff: ~1.5 kts/s → max +45 kts per 30s tick.

---

### D10 — Heading discontinuities at phase boundaries [P2 MEDIUM]

**Evidence:**
- [29]→[30] taxi_to_gate→parked: 259.7°→34.6° (**+135°** instant rotation)
- [92]→[93] taxi_to_runway→takeoff: 127.5°→284.0° (**+156°** instant rotation)
- [95]→[96] departing frame: 284.0°→104.3° (**+180°** instant rotation)

**What's wrong:** Aircraft heading jumps by up to 180° between consecutive frames. Real aircraft can yaw at ~3°/second max. A 156° change requires ~52 seconds minimum.

**Root cause:** Phase transitions reset heading to target values (runway heading, gate heading, departure heading) without interpolation.

**Fix:** Clamp heading change per tick: `max_hdg_delta = max_yaw_rate * dt_seconds`. For taxi: ~3°/s → max 90° per 30s tick. For airborne: ~3°/s standard rate turn. Interpolate heading toward target rather than snapping.

---

### D11 — Altitude anomaly during approach: 600→630ft climb [P2 MEDIUM]

**Evidence:** Snapshot [7]→[8]: altitude goes from 600ft to 630ft (+30ft) during approach — aircraft climbs while supposedly descending.

**What's wrong:** A momentary altitude increase during final approach violates the continuous descent profile. This could indicate a position interpolation glitch or a waypoint transition artifact.

**Fix:** Enforce monotonic descent during approach: `new_alt = min(current_alt, target_alt_for_distance)`.

---

### D12 — Turnaround time 21.5 min (too short for A319) [P2 MEDIUM]

**Evidence:** Parked at ~14:50 UTC, pushback at 15:11:26 UTC ≈ 21.4 minutes. Missing the exact park time due to D06 (missing transition), but taxi_to_gate last moving frame is [19] at ~14:49:30.

**What's wrong:** Minimum turnaround for an A319 is 25-35 minutes (deboarding, cleaning, catering, refueling, boarding). 21.5 min is unrealistically fast for a 134-seat aircraft.

**Root cause:** The calibrated turnaround function may be using a too-aggressive median or the GSE critical path model underestimates for narrow-body jets.

**Fix:** Floor turnaround time at aircraft-type minimums: A319/A320: 30 min, A321/B737-900: 35 min, widebody: 60+ min. Cross-reference with calibration profile medians.

---

## Summary Table

| ID | Severity | Category | Defect | Video Evidence |
|----|----------|----------|--------|----------------|
| D01 | P0 | Physics | Takeoff at 17 kts | Frame 93 |
| D02 | P0 | Physics | Climb rates up to 30,000 fpm | Frames 98-106 |
| D03 | P0 | Data | Baggage missing for 78% of flights | N/A (data) |
| D04 | P1 | Data | vertical_rate always 0 | All frames |
| D05 | P1 | Data | Duplicate phase transitions | All transitions |
| D06 | P1 | Data | Missing taxi→parked transition | Gap at 14:50-15:11 |
| D07 | P1 | Physics | Approach heading 0° at spawn | Frame 0 |
| D08 | P1 | Physics | Descent rate -1200 fpm (too steep) | Frames 0-7 |
| D09 | P2 | Physics | Speed jumps +84/+102 kts in 30s | Frames 93-96 |
| D10 | P2 | Physics | Heading jumps up to 156° | Frames 30, 93, 96 |
| D11 | P2 | Physics | Approach altitude climbs 30ft | Frame 8 |
| D12 | P2 | Operations | Turnaround 21.5 min (too short) | Timeline |

---

## Recommendations

### Immediate (P0 fixes)

1. **Fix `_force_advance()` in engine.py** to:
   - Record phase transitions when changing phase
   - Add flights to `_completed_flights` when forcing to PARKED
   - Set proper initial velocity when forcing to TAKEOFF

2. **Cap climb/descent rates per tick** using aircraft performance data:
   ```
   max_alt_change = max_vertical_rate * dt_seconds / 60
   new_alt = clamp(target_alt, current_alt - max_alt_change, current_alt + max_alt_change)
   ```

### Short-term (P1 fixes)

3. **Set initial spawn heading** to bearing toward airport for approach flights
4. **Use 3° glideslope geometry** for approach descent rate
5. **Remove duplicate phase transition recording** — pick one path (engine or fallback buffer)
6. **Compute vertical_rate from altitude deltas** each tick

### Medium-term (P2 improvements)

7. **Add per-tick rate limiters** for velocity and heading changes
8. **Enforce monotonic descent** during approach phase
9. **Floor turnaround times** by aircraft type category

### Architecture note

Many of these defects share a root cause: the `_force_advance()` function bypasses all the physics modeling and event recording that the normal state machine provides. Consider refactoring `_force_advance()` to call the same phase-transition logic rather than directly mutating state.

# Global Issues and Improvements — Cross-Airport Simulation Analysis

**Source:** 7 airport simulation reports (SFO, LHR, NRT, DXB, GRU, JFK, SYD)
**Date:** 2026-03-14
**Total flights simulated:** ~7,173 across all scenarios

---

## Executive Summary

Seven regional airport simulations were run with 1,000-flight scenarios under severe weather disruptions. While the simulation engine successfully models capacity constraints, weather-driven holdings, and cascading disruptions, the analysis revealed systemic issues that appear across all airports. The most critical findings are that key metrics (avg delay, on-time %) are disconnected from scenario impact, flight dynamics like go-arounds and diversions are absent, and gate utilization is not recorded. These issues affect the validity of cross-scenario comparisons and the realism of the simulation output.

---

## 1. Critical Issues

### 1.1 Avg Delay Metric Disconnected from Scenario Impact

- **Observed in:** All 7 airports
- **Evidence:** Avg delay is 26.6 min across all simulations regardless of scenario severity -- from SYD's gradual smoke (206 holdings) to JFK's nor'easter (451 holdings, 41% flights never spawned)
- **Root cause:** The delay metric reflects pre-generated schedule delay assigned at flight creation time, not scenario-caused delay. The capacity system holds flights pre-spawn, making weather/capacity delay invisible in this metric.
- **Impact:** The primary delay KPI is meaningless for comparing scenario severity. A typhoon that shuts down NRT for 7 hours reports the same avg delay as SYD's gradual smoke event.
- **Proposed fix:** Track scenario-caused delay separately as `capacity_hold_time` -- the time between a flight's scheduled spawn and actual spawn. For non-spawned flights (JFK), record delay as `sim_end_time - scheduled_spawn_time`.
- **Effort:** Medium (2-3 days). Requires changes to `engine.py` to track scheduled vs actual spawn times, and `recorder.py` to compute and output the new metric.

### 1.2 On-Time Performance Metric Disconnected from Scenario Impact

- **Observed in:** All 7 airports
- **Evidence:** On-time % ranges only 84.4-84.6% across all simulations, regardless of scenario severity
- **Root cause:** Same as avg delay -- on-time is calculated from pre-generated schedule data, not actual scenario-impacted operations. At JFK, on-time is 84.4% but only measures the 597 flights that spawned, ignoring the 423 that effectively were cancelled.
- **Impact:** Cannot compare scenario disruption severity using on-time performance.
- **Proposed fix:** Calculate on-time from actual vs scheduled spawn times. Include non-spawned flights as "not on time" by definition. Add a `cancellation_rate = (total - spawned) / total` metric.
- **Effort:** Medium (2-3 days). Same implementation scope as the delay fix; should be done together.

### 1.3 Zero Go-Arounds Across All Simulations

- **Observed in:** All 7 airports (0 go-arounds total across ~7,173 flights)
- **Evidence:** No go-arounds despite LIFR conditions (0.12nm vis at LHR, 0.25nm at JFK/DXB), 65kt gusts (NRT), microbursts (GRU), and sea breeze windshear (SYD). Real-world go-around rates in these conditions range from 3-5% (LHR fog) to >10% (microbursts).
- **Root cause:** The capacity system prevents flights from spawning rather than modeling airborne approach failures. There is no go-around code path in the flight state machine.
- **Impact:** Simulation does not model one of the most critical safety-related flight dynamics. Go-arounds cause cascading delays, fuel emergencies, and diversions that are absent from results.
- **Proposed fix:** Add go-around probability based on weather conditions (flight category, wind gusts, windshear reports). When triggered, the flight re-enters the approach sequence or diverts. Probability table: LIFR fog 3-5%, LIFR with gusts 5-10%, microburst 10-15%, windshear alert 8-12%.
- **Effort:** High (1-2 weeks). Requires new state machine transition in `fallback.py`, approach re-sequencing logic, and optional diversion routing.

### 1.4 Zero Gates Used Across All Simulations

- **Observed in:** All 7 airports (0 gates_used metric despite hundreds of gate events)
- **Evidence:** SFO reports only 2 gate occupy events for 1,030 flights. LHR has 229 gate events but 0 gates used. GRU has 358 gate events (highest) but still 0 gates used.
- **Root cause:** `emit_gate_event("occupy")` is not called in most code paths within `fallback.py`. Gates are assigned correctly (flights do park), but the occupy event is not recorded.
- **Impact:** Gate utilization metrics are completely broken. Cannot analyze gate management, turnaround efficiency, or gate conflict resolution.
- **Proposed fix:** Add `emit_gate_event("occupy")` calls in `_create_new_flight()` and `_find_available_gate()` code paths in `src/ingestion/fallback.py`.
- **Effort:** Low (1-2 hours). Straightforward code fix -- the gate assignment logic exists, just needs the event emission.

---

## 2. High-Severity Issues

### 2.1 JFK: 41% of Flights Never Spawned

- **Observed in:** JFK only (597/1,020 spawned = 58.5%)
- **Evidence:** The 7+ hour near-total shutdown (08:00-15:00) with 12-hour de-icing (1.8x turnaround) created a backlog that could not clear in the remaining 7 hours. 423 flights were permanently queued.
- **Root cause:** The capacity system correctly prevents overloading but has no mechanism for proactive cancellation. The 24-hour simulation window is insufficient for severe nor'easter recovery.
- **Impact:** Results represent only partial operations. All metrics (delay, on-time, turnaround) are biased toward the flights that did operate (pre/post storm).
- **Proposed fixes:**
  1. Add `cancellation_rate` metric to the results summary (Low effort, 1 hour)
  2. Add `effective_delay` metric for non-spawned flights: `sim_end_time - scheduled_spawn_time` (Low effort, 1 hour)
  3. Extend simulation to 36h for severe scenarios, or run until all flights complete (Medium effort, 1-2 days)
  4. Add proactive cancellation policy -- cancel flights scheduled during storm window (High effort, 1 week)

### 2.2 SFO: 191 Flights Stuck in Approaching Phase

- **Observed in:** SFO (18% of arrivals never completed their flight path)
- **Evidence:** 191 flights spawned into `approaching` phase but never progressed to `landing`. 75 had no position snapshots; 116 had brief data (5-15 min) before vanishing. Concentrated during high-load periods (morning surge, thunderstorm, fog, recovery surge).
- **Root cause:** The flight state machine in `fallback.py` may remove approaching flights from `_flight_states` under certain conditions. The 15-minute force-advance timer appears to not fire for these flights.
- **Impact:** Over-counts active flights during congested periods. ~18% of arrivals are phantom flights.
- **Proposed fix:** Investigate the `APPROACHING` phase handler in `_update_flight_state()`. Ensure flights either progress to landing or are explicitly cancelled/diverted. Add logging for flights removed from the state map.
- **Effort:** Medium (2-3 days). Requires debugging the state machine under load conditions.

### 2.3 No Airborne Diversions During Airport Closures

- **Observed in:** NRT, DXB, GRU, JFK (all airports with total shutdowns)
- **Evidence:** When both runways close (NRT 12:30-15:00, DXB 05:00-08:00, JFK 09:00-12:00), flights already airborne should divert. Instead they either freeze or vanish. NRT had only 2 active flights during a 3-hour closure of a major international airport.
- **Root cause:** The capacity system prevents new flights from spawning but does not manage already-airborne flights. No diversion routing exists.
- **Impact:** Missing realistic diversion statistics, fuel emergency scenarios, and alternate airport load. Airborne flight management during closures is absent.
- **Proposed fix:** When both runways close, airborne flights within X nm should be diverted to the nearest alternate (NRT->HND/KIX, DXB->AUH/SHJ, JFK->EWR/LGA). Track diversion counts and destination airports.
- **Effort:** High (1-2 weeks). Requires alternate airport database, routing logic, and coordination with capacity system.

### 2.4 Capacity Model Uses Spawn-Gating Instead of Realistic Delay Propagation

- **Observed in:** All 7 airports
- **Evidence:** The capacity system holds flights in a pre-spawn queue rather than modeling delay propagation through the system (approach delays, taxiway delays, gate delays, departure queue delays). This means flights either spawn "on time" or never spawn -- there is no intermediate delay state.
- **Root cause:** Architectural decision to manage capacity at the spawn boundary rather than within the flight lifecycle.
- **Impact:** The simulation cannot model cascading delays (a late arrival causing a late departure causing a missed slot). All delay is binary (spawned/not spawned) rather than continuous.
- **Proposed fix:** Implement multi-stage capacity model: arrival queue (holding/approach), runway occupancy, taxiway flow, gate occupancy, departure queue. Each stage can add delay that propagates forward.
- **Effort:** Very High (2-4 weeks). Major architectural change to the simulation engine.

---

## 3. Medium-Severity Issues

### 3.1 Missing Weather Types: Sandstorm, Smoke, Haze

- **Observed in:** DXB (sandstorm mapped to `type: snow`), SYD (smoke/haze mapped to `type: fog`)
- **Evidence:** DXB's severe sandstorm displays as "snow" in the UI replay. SYD's bushfire smoke displays as "fog." The capacity and visibility effects are approximately correct but the presentation is misleading.
- **Root cause:** The engine only supports a limited set of weather types. Non-standard types are mapped to the closest available.
- **Impact:** Confusing UI labels. Also, sand/smoke have different capacity characteristics than snow/fog (e.g., sand affects engines requiring post-storm inspection; smoke reduces horizontal vis more than slant range).
- **Proposed fix:** Add `sandstorm`, `dust`, `smoke`, `haze` weather types to the engine's weather model. Each with appropriate capacity penalties and UI markers.
- **Effort:** Medium (2-3 days). Requires changes to scenario parser, capacity model weather multipliers, and frontend weather display.

### 3.2 Airport Geometry: All Airports Rendering at SFO Coordinates

- **Observed in:** All 6 non-SFO airports (LHR, NRT, DXB, GRU, JFK, SYD)
- **Evidence:** The simulation replay renders all airports at SFO's geographic coordinates because the simulation engine generates positions relative to SFO's reference point. The per-airport OSM map data is not used during simulation.
- **Root cause:** The simulation engine uses hardcoded SFO coordinates as the reference point for all generated flight positions.
- **Impact:** The 2D/3D visualization shows incorrect geography for non-SFO airports. Approach paths, gate locations, and taxiway routing do not match the actual airport layout.
- **Proposed fix:** Use per-airport reference coordinates from the config YAML. Load airport-specific OSM data to position gates, taxiways, and approach paths correctly.
- **Effort:** High (1-2 weeks). Requires passing airport coordinates through the simulation pipeline and updating position generation in `fallback.py`.

### 3.3 Wind Direction Reversals Not Triggering Runway Config Changes

- **Observed in:** NRT (090 to 270 during typhoon eye), SYD (310 to 180 during sea breeze)
- **Evidence:** NRT's 180-degree wind shift during eye passage and SYD's 130-degree sea breeze shift should trigger runway configuration changes. Neither scenario includes explicit config_change events for these shifts.
- **Root cause:** Wind shifts are defined as part of weather events but the engine does not automatically evaluate whether a new wind direction requires a runway config change.
- **Impact:** The simulation may operate on the wrong runway configuration after a wind shift, underestimating disruption (wrong-direction approaches are unsafe and would be refused in reality).
- **Proposed fix:** Add automatic runway configuration evaluation when wind direction changes by more than 90 degrees. Alternatively, scenario authors should manually add config_change events for major wind shifts.
- **Effort:** Low-Medium (1-2 days). Can be done either in the engine (automatic) or in scenario YAMLs (manual).

### 3.4 Channel Squall Impact Appears Muted at LHR

- **Observed in:** LHR
- **Evidence:** The afternoon Channel squall (42kt gusts, MVFR) generated only ~18 holdings (8% of total) despite being a significant weather event. The LIFR fog dominated with 92% of holdings.
- **Root cause:** Likely a combination of lower traffic in the 16:00-18:00 window and the MVFR flight category not reducing capacity as severely. May also indicate the gust penalty is not being applied correctly.
- **Proposed fix:** Verify gust penalty calculation in the capacity model. Check that the wind gust multiplier (42kt gusts should reduce capacity ~25-35%) is applied on top of the MVFR visibility penalty.
- **Effort:** Low (1 day). Diagnostic investigation + potential capacity model tuning.

### 3.5 Sydney Curfew Not Modeled

- **Observed in:** SYD
- **Evidence:** The scenario description explicitly mentions Sydney's 23:00-06:00 noise curfew but no curfew event exists in the YAML or engine. The curfew would prevent recovery operations between 23:00 and 06:00.
- **Root cause:** No curfew event type exists in the engine.
- **Impact:** SYD results overstate recovery capacity. With the curfew, only 5 hours (18:00-23:00) of VFR recovery are available, not 6 hours (18:00-00:00).
- **Proposed fix:** Add `curfew` event type that halts all operations during specified hours. Apply to SYD (23:00-06:00), and make available for other curfew airports (FRA 23:00-05:00, LHR partial).
- **Effort:** Medium (2-3 days). New event type in scenario model + capacity system integration.

### 3.6 Duplicate Phase Transition Recording (Fixed)

- **Observed in:** SFO (discovered and fixed during analysis)
- **Evidence:** Every phase transition was recorded twice -- once by `_update_all_flights()` and once by `_capture_phase_transitions()`. Phase transition count was inflated 2x (7,207 instead of 4,107).
- **Status:** FIXED in `src/simulation/engine.py:685-693`.
- **Effort:** Done.

---

## 4. Low-Severity Issues

### 4.1 24-Hour Simulation Window Insufficient for Severe Scenarios

- **Observed in:** SFO (206 flights incomplete), JFK (423 flights never spawned), NRT (compressed recovery)
- **Evidence:** JFK had only 7 hours for recovery after the storm cleared. SFO left 206 flights incomplete at sim end. NRT's recovery was compressed into 4 hours.
- **Proposed fix:** Allow simulation to extend to 36h or run until all flights complete/are cancelled. Add a `--max-duration` CLI flag.
- **Effort:** Low (1 day). Mostly a configuration change.

### 4.2 Narita Curfew Not Modeled

- **Observed in:** NRT
- **Evidence:** NRT has a strict 23:00-06:00 curfew that limits recovery window. Combined with typhoon shutdown, effective operating hours are extremely compressed.
- **Proposed fix:** Same curfew implementation as SYD (issue 3.5).
- **Effort:** Included in 3.5 scope.

### 4.3 DXB Traffic Profile Does Not Reflect 3-Bank Hub Structure

- **Observed in:** DXB
- **Evidence:** DXB's peak simultaneous (89) is the lowest of all airports. In reality, DXB handles 45+ movements/hr at peak with three daily banks (overnight long-haul, morning regional, afternoon long-haul). The uniform traffic distribution underestimates overnight bank intensity.
- **Proposed fix:** Add per-airport traffic distribution profiles in the config YAML. DXB should have distinct peaks at 01:00-04:00, 08:00-12:00, and 16:00-20:00.
- **Effort:** Medium (2-3 days). Requires changes to the flight scheduler in `engine.py`.

### 4.4 GRU Turnaround Time Needs Validation

- **Observed in:** GRU
- **Evidence:** GRU's 89.7 min avg turnaround is the highest of all airports. The 1.4x taxiway multiplier during peak hours is the primary driver. Verify the multiplier is applied correctly and only during the specified window.
- **Proposed fix:** Add logging/audit for turnaround multiplier application. Verify window boundaries.
- **Effort:** Low (few hours). Diagnostic check.

### 4.5 Rapid-Onset Events May Not Be Captured Accurately

- **Observed in:** GRU
- **Evidence:** The 90-minute MVFR-to-LIFR transition at GRU should cause a spike in holdings at 13:30. If the capacity system evaluates at regular intervals, the rapid onset may not be captured accurately.
- **Proposed fix:** Increase capacity evaluation frequency during active weather transitions, or use event-driven evaluation when weather conditions change.
- **Effort:** Low-Medium (1-2 days).

### 4.6 FAA Ground Stop Event Type Unverified

- **Observed in:** JFK
- **Evidence:** The ground stop at 11:00 is the only scenario to use the `ground_stop` event type. Not verified whether it is processed correctly by the capacity system or logged as a no-op.
- **Proposed fix:** Add unit test for ground_stop event processing. Verify in capacity system logs that departures are halted.
- **Effort:** Low (few hours).

### 4.7 No Heat De-Rating Effects for DXB

- **Observed in:** DXB
- **Evidence:** The scenario description mentions 48C temperatures but no temperature-based capacity penalty exists. High temperatures reduce takeoff performance, requiring longer runway rolls and sometimes payload restrictions.
- **Proposed fix:** Add temperature-based departure capacity modifier. At >40C, apply a de-rating penalty reducing departure throughput by 10-20%.
- **Effort:** Medium (2-3 days). New penalty type in capacity model.

---

## 5. Improvement Roadmap (Priority Order)

### Phase 1 -- Metrics Accuracy (1-2 weeks)

These fixes are prerequisites for meaningful cross-scenario comparison.

| # | Improvement | Effort | Impact |
|---|-----------|--------|--------|
| 1 | Fix gate occupy event recording (`fallback.py`) | 1-2 hours | Unblocks gate utilization analysis |
| 2 | Add `capacity_hold_time` metric (scenario-caused delay) | 2-3 days | Primary delay KPI becomes meaningful |
| 3 | Add `cancellation_rate` metric | 1 hour | Surfaces JFK's 41% non-spawn |
| 4 | Fix on-time % to use actual vs scheduled spawn times | 2-3 days | On-time KPI becomes meaningful |
| 5 | Add `effective_delay` for non-spawned flights | 1 hour | Full delay picture including "cancelled" flights |

### Phase 2 -- Flight Dynamics (2-4 weeks)

These add critical missing realism to the simulation.

| # | Improvement | Effort | Impact |
|---|-----------|--------|--------|
| 6 | Implement go-around logic (weather-dependent) | 1-2 weeks | Adds safety-critical flight dynamic |
| 7 | Implement airborne diversions during closures | 1-2 weeks | Realistic response to airport shutdowns |
| 8 | Fix stuck-approaching flights (SFO state machine bug) | 2-3 days | 18% of arrivals currently phantom |

### Phase 3 -- Scenario Realism (1-2 weeks)

These improve the fidelity of individual scenarios.

| # | Improvement | Effort | Impact |
|---|-----------|--------|--------|
| 9 | Add sandstorm/dust/smoke/haze weather types | 2-3 days | Correct labels and capacity penalties |
| 10 | Add curfew event type (SYD, NRT, FRA) | 2-3 days | Realistic recovery window constraints |
| 11 | Add automatic runway config for wind reversals | 1-2 days | Correct runway usage after wind shifts |
| 12 | Extend simulation to 36h for severe scenarios | 1 day | Allow full recovery assessment |
| 13 | Verify gust penalty and ground stop processing | 1 day | Ensure existing mechanisms work correctly |

### Phase 4 -- Capacity Model Evolution (2-4 weeks)

Major architectural improvement for long-term simulation quality.

| # | Improvement | Effort | Impact |
|---|-----------|--------|--------|
| 14 | Per-airport geometry (not all at SFO coords) | 1-2 weeks | Correct visualization for all airports |
| 15 | Per-airport traffic profiles (DXB 3-bank, LHR slot-constrained) | 2-3 days | Realistic demand patterns |
| 16 | Multi-stage capacity model (replace spawn-gating) | 2-4 weeks | Cascading delay propagation |
| 17 | Temperature-based de-rating (DXB heat) | 2-3 days | Performance-based capacity model |
| 18 | Proactive cancellation policy (JFK nor'easter) | 1 week | Realistic airline response to storms |

---

## 6. Cross-Airport Comparison Summary

| Airport | Scenario | Holdings | Spawned % | Peak Sim | Turnaround | Unique Issue |
|---------|----------|----------|-----------|----------|------------|-------------|
| **SFO** | Thunderstorm + Fog | 315 | ~100% | 141 | 122.9 min | 191 stuck approaching flights |
| **LHR** | Radiation Fog | 218 | 99.9% | 94 | 66.8 min | Channel squall impact muted |
| **NRT** | Typhoon | 359 | 99.9% | 114 | 80.5 min | Double-LIFR, wind reversal |
| **DXB** | Sandstorm | 241 | 99.9% | 89 | 61.9 min | Sandstorm as "snow", low peak |
| **GRU** | Tropical Storm | 216 | 99.9% | 115 | 89.7 min | Highest turnaround, double-disruption |
| **JFK** | Nor'easter | 451 | **58.5%** | 59 | 37.4 min | **41% never spawned**, 910 capacity events |
| **SYD** | Bushfire Smoke | 206 | 99.9% | 111 | 81.4 min | Lowest holdings, gradual onset baseline |

**Key insight:** The dominant differentiator across scenarios is not storm severity but whether the storm causes a total airport shutdown. JFK (3h shutdown + 12h degradation) and NRT (6h effective shutdown) generated far more holdings than DXB (3h shutdown but overnight) or SYD (no shutdown). Storm timing relative to traffic demand is as important as storm intensity.

---

## 7. Methodology Notes

- Issues were extracted from the "Issues Identified" section of each of the 7 simulation reports
- Cross-airport anomalies (identical avg delay, zero go-arounds, zero gates used, identical on-time %) were identified independently in each report and deduplicated here
- Effort estimates are approximate and assume familiarity with the codebase
- Priority ordering reflects impact on simulation validity (metrics accuracy first, then missing dynamics, then realism refinements)

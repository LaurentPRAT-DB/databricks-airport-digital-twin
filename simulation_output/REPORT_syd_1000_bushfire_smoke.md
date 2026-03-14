# SYD Bushfire Smoke + Sea Breeze Simulation Report

**Simulation file:** `simulation_output/simulation_syd_1000_bushfire_smoke.json`
**Scenario file:** `scenarios/syd_bushfire_smoke.yaml`
**Config file:** `configs/simulation_syd_1000.yaml`
**Run date:** 2026-03-14
**Duration:** 24h simulated

---

## 1. Simulation Setup

| Parameter | Value |
|-----------|-------|
| Airport | SYD (Kingsford Smith International, Sydney) |
| Scheduled flights | 500 arrivals + 500 departures |
| Scenario-injected | +19 (surges + MEL diversions) |
| **Total flights** | **1,019** |
| Spawned | 1,018/1,019 |
| Time step | 2.0s |
| Seed | 42 (reproducible) |
| Runways | 28L, 28R (dual parallel) |

### Scenario Definition

```yaml
name: SYD Bushfire Smoke + Sea Breeze Convergence
description: >
  Western Sydney bushfire sends dense smoke plume over the airport.
  Visibility degrades through the morning as smoke accumulates under
  a temperature inversion. Afternoon sea breeze convergence triggers
  thunderstorm activity embedded in the smoke layer. Sydney's curfew
  (23:00-06:00) adds pressure to clear the backlog before shutdown.
  Realistic for Nov-Feb bushfire season.
```

### Reproduction Command

```bash
python -m src.simulation.cli \
  --config configs/simulation_syd_1000.yaml \
  --scenario scenarios/syd_bushfire_smoke.yaml
```

---

## 2. Scenario Definition

This scenario tests SYD's resilience under a gradual smoke degradation followed by sea breeze thunderstorms -- a compound hazard unique to Sydney's geography. The gradual MVFR-to-IFR-to-LIFR progression is the opposite of the sudden-onset storms at GRU and NRT, testing whether the capacity system handles slow degradation differently from rapid onset.

### 2.1 Weather Events

| Time | Type | Severity | Visibility | Ceiling | Wind | Gusts | Flight Cat | Duration |
|------|------|----------|-----------|---------|------|-------|-----------|----------|
| 07:00 | Smoke haze | Light | 3.0nm | 2000ft | 8kt / 270 | - | MVFR | 2.0h |
| 09:00 | Smoke haze | Moderate | 1.0nm | 800ft | 10kt / 290 | - | **IFR** | 3.0h |
| 12:00 | Dense smoke | Severe | 0.5nm | 300ft | 12kt / 310 | - | **LIFR** | 2.0h |
| 14:00 | Thunderstorm | Moderate | 1.5nm | 1000ft | 22kt / 180 | 38kt | **IFR** | 2.0h |
| 16:00 | Clear | Light | 4.0nm | 2500ft | 15kt / 160 | - | MVFR | 2.0h |
| 18:00 | Clear | Light | 8.0nm | 5000ft | 10kt / 200 | - | VFR | 5.0h |

**Effect:** Gradual visibility degradation over 5 hours: MVFR (07:00) to IFR (09:00) to LIFR (12:00). The sea breeze at 14:00 brings a 90-degree wind shift (310 to 180) and thunderstorms but actually improves visibility slightly (0.5nm to 1.5nm) by dispersing the smoke. Note: YAML uses `type: fog` for smoke haze events due to engine limitations.

### 2.2 Runway Events

| Time | Event | Target | Duration | Reason |
|------|-------|--------|----------|--------|
| 12:00 | Closure | 28R | 120 min | Visibility below CAT I minimums in smoke |
| 14:30 | Closure | 28L | 45 min | Windshear on final from sea breeze front |

**Effect:** 28R closed 12:00-14:00 during LIFR smoke (2 hours, single-runway ops). 28L closed 14:30-15:15 for sea breeze windshear (45 min). These do not overlap, so there is no total airport shutdown -- but back-to-back single-runway periods reduce capacity for 3+ hours.

### 2.3 Ground Events

| Time | Type | Target | Duration | Impact |
|------|------|--------|----------|--------|
| 10:00 | Gate failure | T1-D8 | 3.0h | Gate unavailable until 13:00 |
| 11:00 | Taxiway closure | Taxiway B (smoke visibility) | 4.0h | Turnaround 1.3x until 15:00 |
| 15:00 | Fuel shortage | Airport-wide | 2.0h | Turnaround 1.2x until 17:00 |

**Effect:** Gate T1-D8 lost during IFR-to-LIFR transition. Taxiway B closure due to smoke (1.3x turnaround) is the mildest taxiway penalty of all scenarios. Fuel shortage during clearing adds minor compound delay.

### 2.4 Traffic Modifiers

| Time | Type | Extra Arrivals | Extra Departures | Origin |
|------|------|---------------|-----------------|--------|
| 06:00 | Surge | +8 | +6 | Various |
| 13:00 | Diversion | +5 | - | MEL |

**Effect:** Early morning surge of 14 flights at 06:00, before smoke arrives. Melbourne diversions at 13:00 add 5 arrivals during the LIFR-to-thunderstorm transition.

---

## 3. Results Summary

| Metric | Value | Notes |
|--------|-------|-------|
| Total flights processed | 1,019 | 1,000 scheduled + 19 injected |
| Spawned | 1,018/1,019 | |
| On-time performance | 84.4% | |
| Avg delay (delayed flights) | 26.6 min | See Issue 7.4 |
| Avg turnaround time | 81.4 min | Moderate -- 1.3x taxiway multiplier |
| Peak simultaneous | 111 flights | |
| Capacity hold events | 486 (capacity) | + 6 weather + 3 ground + 2 runway = 497 total |
| Holdings | **206** | **Lowest of all 6 airports** |
| Go-arounds | 0 | See Issue 7.5 |
| Gates used | 0 | See Issue 7.6 |
| Position snapshots | **135,244** | **Highest of all 6 airports** |
| Phase transitions | 3,882 | |
| Gate events | 278 | |

---

## 4. Visual — Peak Disruption

![SYD — Bushfire Smoke at peak disruption](screenshots/syd_smoke_peak.png)

*Screenshot: Simulation UI at peak disruption showing ~111 active flights during dense LIFR smoke at 12:00, RWY 28R closed below CAT I minimums, gradual visibility degradation from MVFR to LIFR visible on timeline, and sea breeze thunderstorm markers at 14:00.*

---

## 5. Scenario Impact Analysis

### Disruption Cascade Timeline

```
06:00  +14 surge flights (pre-smoke) ───
07:00  ▓▓▓ SMOKE HAZE (MVFR, vis 3.0nm) ▓▓▓ 09:00
09:00  ████████ THICKENING SMOKE (IFR, vis 1.0nm) ████████ 12:00
10:00  Gate T1-D8 failed ──────────── 13:00
11:00  Taxiway B smoke closure 1.3x ──────────────────── 15:00
12:00  ██████ DENSE SMOKE (LIFR, vis 0.5nm) ██████ 14:00
12:00  RWY 28R closed (below CAT I) ──────────── 14:00
13:00  MEL diversions (+5) ───
14:00  ████ SEA BREEZE THUNDERSTORM (IFR, gusts 38kt) ████ 16:00
14:30  RWY 28L windshear ── 15:15
15:00  Fuel shortage 1.2x ─────── 17:00
16:00  ▓▓▓ CLEARING (MVFR) ▓▓▓ 18:00
18:00  ─── VFR CLEAR (full operations) ─────────── 00:00
```

### Key Observations

1. **07:00-12:00 -- Gradual Smoke Degradation:** The 5-hour progression from MVFR to LIFR is the most gradual onset of any scenario. This allows the capacity system to incrementally reduce throughput rather than facing a sudden cliff. This explains why SYD has the lowest holdings (206) despite reaching LIFR conditions.

2. **Most Position Snapshots (135,244):** SYD generates the most position data of any scenario. Because the disruption is gradual and there is no total airport shutdown, flights continue to operate (at reduced rates) throughout the degradation. This maintains a steady flow of active flights generating position snapshots -- the opposite of JFK where the blizzard suppressed all activity.

3. **Sea Breeze Wind Shift (310 to 180):** The 130-degree wind direction change at 14:00 is highly realistic for Sydney. The afternoon sea breeze from the Tasman Sea clashes with the westerly wind driving the smoke plume, creating convergence thunderstorms. Importantly, the sea breeze actually helps by dispersing the smoke -- visibility improves from 0.5nm (LIFR) to 1.5nm (IFR).

4. **No Total Airport Shutdown:** Unlike JFK, NRT, DXB, and GRU, SYD never has both runways closed simultaneously. The 28R closure (12:00-14:00) and 28L closure (14:30-15:15) are sequential, not overlapping. Single-runway operations are maintained throughout. This is the key reason for the lowest holdings count.

5. **206 Holdings -- Lowest of All Scenarios:** The gradual nature of smoke degradation, lack of total shutdown, and relatively mild ground penalties (1.3x taxiway, 1.2x fuel) result in the fewest holdings. This demonstrates that gradual-onset events are much less disruptive than sudden-onset events (even when reaching the same LIFR severity).

6. **Sydney Curfew Not Modeled:** The scenario description mentions Sydney's 23:00-06:00 curfew, but no curfew event is defined in the YAML. The curfew would prevent any recovery operations between 23:00 and 06:00, potentially creating a backlog if the evening clearing (18:00-23:00) doesn't fully recover.

### Holdings Distribution

- **07:00-09:00:** ~15 holdings -- MVFR smoke, mild constraint
- **09:00-12:00:** ~50 holdings -- IFR smoke, increasing constraint
- **12:00-14:00:** ~80 holdings -- LIFR dense smoke, single-runway ops
- **14:00-16:00:** ~45 holdings -- sea breeze thunderstorm, 28L windshear
- **16:00-18:00:** ~16 holdings -- clearing, residual backlog

### Comparison: Gradual vs Sudden Onset

| Aspect | SYD (Gradual) | NRT (Sudden) | JFK (Extended) |
|--------|--------------|-------------|----------------|
| Onset speed | 5h (MVFR to LIFR) | <1h (VFR to IFR) | 3h (MVFR to LIFR) |
| Total shutdown | None | 2.5h (both runways) | 3h (both runways) |
| Holdings | 206 (lowest) | 359 | 451 (highest) |
| Position snapshots | 135,244 (highest) | 90,052 | 30,126 (lowest) |
| Flights spawned | 1,018/1,019 | 1,029/1,030 | 597/1,020 |

The gradual degradation pattern lets the capacity system adapt smoothly, maintaining flow throughout. Sudden shutdowns create binary states (full capacity to zero to full) that generate massive backlogs.

---

## 6. UI Replay Navigation Guide

To view these events in the simulation replay UI:

1. Load `simulation_syd_1000_bushfire_smoke.json` from the Simulation file picker
2. Use the timeline progress bar to navigate to key moments
3. Colored markers on the timeline indicate scenario events (amber=weather, red=runway, orange=ground, blue=traffic)

### Bookmarks

| Event | Sim Time | Timeline % | What to Look For |
|-------|----------|-----------|------------------|
| Morning surge | 06:00 | 25% | +14 flights before smoke |
| Smoke haze onset | 07:00 | 29% | MVFR, visibility dropping gradually |
| IFR smoke thickening | 09:00 | 38% | Visibility 1.0nm, ops degrading |
| Gate T1-D8 failure | 10:00 | 42% | Gate lost |
| Taxiway B closure | 11:00 | 46% | 1.3x turnaround penalty |
| **Dense smoke (LIFR)** | **12:00** | **50%** | **0.5nm vis, RWY 28R closes** |
| MEL diversions | 13:00 | 54% | 5 extra arrivals |
| **Sea breeze thunderstorm** | **14:00** | **58%** | **Wind shifts 310 to 180, gusts 38kt** |
| RWY 28L windshear | 14:30 | 60% | Brief closure, sea breeze front |
| Fuel shortage | 15:00 | 63% | 1.2x turnaround |
| **Clearing begins** | **16:00** | **67%** | **MVFR, smoke dispersing** |
| **VFR recovery** | **18:00** | **75%** | **Full operations restored** |
| Curfew (not modeled) | 23:00 | 96% | Would halt ops in reality |
| Simulation end | 00:00 | 100% | Check remaining flights |

---

## 7. Issues Identified

### 7.1 Smoke Modeled as "Fog" Type

All three smoke events (07:00, 09:00, 12:00) use `type: fog` in the YAML because the engine has no smoke/haze weather type. While the visibility reduction is similar, smoke has different characteristics: it doesn't typically reduce ceiling as dramatically as fog, and it can persist longer. The capacity penalties for smoke vs fog may differ in practice.

### 7.2 Sydney Curfew Not Modeled

The scenario description explicitly mentions Sydney's 23:00-06:00 noise curfew but no curfew event exists in the YAML or engine. This is a significant gap -- the curfew would prevent recovery operations between 23:00 and 06:00. For SYD specifically, this adds urgency to clear backlogs before 23:00.

### 7.3 Sea Breeze Wind Shift Should Trigger Config Change

The 130-degree wind shift (310 to 180) at 14:00 is dramatic enough to require a runway configuration change. The YAML only has a windshear closure (28L, 45 min) but not a config change event. In reality, the shift to a southerly wind would move SYD from runway 28 operations to runway 16 operations.

### 7.4 Cross-Airport Anomaly: Identical Avg Delay (26.6 min)

Identical across all 6 simulations. Reflects pre-generated schedule delay, not scenario impact.

### 7.5 Cross-Airport Anomaly: Zero Go-Arounds

No go-arounds despite sea breeze windshear and LIFR smoke conditions. The 28L windshear closure is realistic but flights attempting approach during the sea breeze transition should face elevated go-around risk.

### 7.6 Cross-Airport Anomaly: Zero Gates Used

Gate occupy events not recorded. Pre-existing engine issue.

---

## 8. Recommendations

1. **Add smoke/haze weather type** to the engine. Smoke behaves differently from fog: it reduces horizontal visibility more than slant range, has a different spectral signature (relevant for ILS vs visual approaches), and can persist for days. A dedicated type with appropriate capacity penalties would improve realism.

2. **Implement Sydney curfew.** The 23:00-06:00 curfew is a hard constraint that fundamentally changes the recovery calculus. With only 5 hours (18:00-23:00) of VFR operations before curfew, the pressure to clear backlogs is intense. This should be a new event type applicable to any curfew airport (SYD, FRA, LHR partial).

3. **Add runway config change for sea breeze.** The 310-to-180 wind shift should trigger a transition from runway 28 to runway 16 operations. This is a standard daily event at SYD and changes approach/departure paths significantly.

4. **Consider temperature inversion modeling.** The scenario describes smoke accumulating under a temperature inversion. Inversions also affect aircraft performance and could be modeled as a separate atmospheric condition that traps pollutants and reduces visibility.

5. **Use SYD's gradual onset as a baseline.** With the lowest holdings (206) and highest position snapshots (135,244), SYD represents the "best case" for a LIFR event. This makes it an ideal baseline for comparing sudden-onset scenarios and for calibrating capacity model sensitivity.

6. **Track scenario-caused delay separately.** Even with only 206 holdings, the actual capacity-driven delay is invisible in the 26.6 min metric.

7. **Fix gate occupy event recording** in `fallback.py`.

---

## 9. Reproduction

```bash
# Re-run this exact simulation
python -m src.simulation.cli \
  --config configs/simulation_syd_1000.yaml \
  --scenario scenarios/syd_bushfire_smoke.yaml

# Replay in UI
# 1. Start dev server: ./dev.sh
# 2. Click "Simulation" button in header
# 3. Select "simulation_syd_1000_bushfire_smoke.json"
# 4. Use timeline bookmarks from Section 5 to navigate
```

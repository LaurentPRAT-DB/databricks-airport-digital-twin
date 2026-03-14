# NRT Typhoon Approach Simulation Report

**Simulation file:** `simulation_output/simulation_nrt_1000_typhoon.json`
**Scenario file:** `scenarios/nrt_typhoon.yaml`
**Config file:** `configs/simulation_nrt_1000.yaml`
**Run date:** 2026-03-14
**Duration:** 24h simulated

---

## 1. Simulation Setup

| Parameter | Value |
|-----------|-------|
| Airport | NRT (Narita International, Tokyo) |
| Scheduled flights | 500 arrivals + 500 departures |
| Scenario-injected | +30 (surges + HND diversions) |
| **Total flights** | **1,030** |
| Spawned | 1,029/1,030 |
| Time step | 2.0s |
| Seed | 42 (reproducible) |
| Runways | 28L, 28R (dual parallel) |

### Scenario Definition

```yaml
name: NRT Typhoon Approach — Western Pacific
description: >
  Typhoon making landfall near Tokyo. Outer bands arrive mid-morning with
  heavy rain and gusts to 55kt. Eye passes closest at 15:00 with brief
  calm before rear-wall winds hit. Classic Kanto plain typhoon track
  affecting Narita. JCAB issues ground stop during peak winds.
  Realistic for Jul-Oct typhoon season.
```

### Reproduction Command

```bash
python -m src.simulation.cli \
  --config configs/simulation_nrt_1000.yaml \
  --scenario scenarios/nrt_typhoon.yaml
```

---

## 2. Scenario Definition

This scenario tests NRT's resilience under a direct typhoon approach -- the most severe weather event in East Asian aviation. The double-LIFR structure (pre-eye and post-eye) with only a brief 30-minute calm window makes this one of the most challenging scenarios in the regional set.

### 2.1 Weather Events

| Time | Type | Severity | Visibility | Ceiling | Wind | Gusts | Flight Cat | Duration |
|------|------|----------|-----------|---------|------|-------|-----------|----------|
| 09:00 | Thunderstorm | Moderate | 2.0nm | 1200ft | 30kt / 120 | 45kt | **IFR** | 3.0h |
| 12:00 | Thunderstorm | Severe | 0.5nm | 300ft | 45kt / 090 | 65kt | **LIFR** | 3.0h |
| 15:00 | Clear | Light | 5.0nm | 3000ft | 10kt / 180 | - | VFR | 0.5h |
| 15:30 | Thunderstorm | Severe | 0.75nm | 400ft | 40kt / 270 | 55kt | **LIFR** | 2.5h |
| 18:00 | Thunderstorm | Moderate | 2.0nm | 1500ft | 25kt / 300 | 38kt | IFR | 2.0h |
| 20:00 | Clear | Light | 8.0nm | 5000ft | 15kt / 320 | - | VFR | 4.0h |

**Effect:** Double LIFR phase: pre-eye (12:00-15:00) and rear-wall (15:30-18:00) with only a 30-minute eye calm between. 65kt gusts during peak are well beyond all crosswind limits. Effective airport shutdown 12:00-18:00.

### 2.2 Runway Events

| Time | Event | Target | Duration | Reason |
|------|-------|--------|----------|--------|
| 12:00 | Closure | 28L | 180 min | Crosswind exceeds 35kt limit |
| 12:30 | Closure | 28R | 150 min | Typhoon wind shear -- all runways closed |

**Effect:** Both runways closed simultaneously 12:30-15:00 (2.5 hours). 28L closed for full 3 hours (12:00-15:00). Total airport shutdown during peak typhoon.

### 2.3 Ground Events

| Time | Type | Target | Duration | Impact |
|------|------|--------|----------|--------|
| 11:00 | Gate failure | T1-N5 | 6.0h | Gate unavailable until 17:00 |
| 12:00 | Gate failure | T2-S3 | 5.0h | Gate unavailable until 17:00 |
| 13:00 | Taxiway closure | Taxiway W (flood) | 8.0h | Turnaround 1.5x until 21:00 |

**Effect:** Two gates lost for 5-6 hours during and after the typhoon. Taxiway W flooding persists 8 hours -- the longest ground event -- causing 1.5x turnaround penalty well into the recovery phase.

### 2.4 Traffic Modifiers

| Time | Type | Extra Arrivals | Extra Departures | Origin |
|------|------|---------------|-----------------|--------|
| 08:00 | Surge | +12 | +10 | Various |
| 11:00 | Diversion | +8 | - | HND |

**Effect:** Major surge of 22 flights at 08:00 -- operators trying to move flights before the typhoon hits. HND diversions at 11:00 add 8 arrivals as Haneda closes ahead of the storm.

---

## 3. Results Summary

| Metric | Value | Notes |
|--------|-------|-------|
| Total flights processed | 1,030 | 1,000 scheduled + 30 injected |
| Spawned | 1,029/1,030 | |
| On-time performance | 84.6% | |
| Avg delay (delayed flights) | 26.6 min | See Issue 7.3 |
| Avg turnaround time | 80.5 min | Elevated by 1.5x taxiway multiplier |
| Peak simultaneous | 114 flights | |
| Capacity hold events | 720 (capacity) | + 6 weather + 3 ground + 2 runway = 731 total |
| Holdings | 359 | Second-highest after JFK (451) |
| Go-arounds | 0 | See Issue 7.4 |
| Gates used | 0 | See Issue 7.5 |
| Position snapshots | 90,052 | Low due to extended shutdown period |
| Phase transitions | 2,718 | |
| Gate events | 244 | |

---

## 4. Visual — Peak Disruption

![NRT — Typhoon Approach at peak disruption](screenshots/nrt_typhoon_peak.png)

*Screenshot: Simulation UI at peak disruption showing total airport shutdown at 12:30 with both runways closed, LIFR conditions with 65kt gusts, typhoon event markers on the timeline, and only 2 active flights during 13:00-16:00.*

---

## 5. Scenario Impact Analysis

### Disruption Cascade Timeline

```
08:00  +22 surge flights (pre-typhoon rush) ───
09:00  ████████ OUTER BANDS (IFR, gusts 45kt) ████████████ 12:00
11:00  HND diversions (+8) ───
11:00  Gate T1-N5 failed ──────────────────────────────── 17:00
12:00  ██████████████ PEAK TYPHOON (LIFR, gusts 65kt) ██ 15:00
12:00  RWY 28L closed ────────────────────────── 15:00
12:00  Gate T2-S3 failed ──────────────────────────── 17:00
12:30  RWY 28R closed ─────────────────────── 15:00
       ═══════ TOTAL AIRPORT SHUTDOWN 12:30-15:00 ═══════
13:00  Taxiway W flood ────────────────────────────────────── 21:00
15:00  ▓▓ EYE (VFR, 30 min) ▓▓ 15:30
15:30  ██████████ REAR WALL (LIFR, gusts 55kt) ████████ 18:00
18:00  ████ MODERATE (IFR, gusts 38kt) ████ 20:00
20:00  ─── VFR CLEAR (recovery begins) ─────────── 00:00
```

### Key Observations

1. **08:00 -- Pre-Typhoon Rush:** The 22-flight surge represents operators trying to complete flights before the typhoon hits. This frontloads traffic into the system before capacity degrades.

2. **09:00-12:00 -- Outer Bands (IFR):** Moderate thunderstorms with 45kt gusts reduce capacity. Holdings begin accumulating. The HND diversions at 11:00 add 8 more arrivals into an already-constrained system.

3. **12:00-15:00 -- Peak Typhoon (LIFR, Total Shutdown):** Both runways closed by 12:30. 65kt gusts exceed all aircraft operating limits. Only 2 flights were reported active during 13:00-16:00. This is a realistic total airport closure -- Narita routinely closes for 4-6 hours during typhoon landfall.

4. **15:00-15:30 -- Eye Passage (30 min VFR):** A brief window of calm as the eye passes. In reality, Narita would not resume full operations in only 30 minutes -- the eye window is too short for safe restart. The simulator correctly does not release many flights.

5. **15:30-18:00 -- Rear Wall (LIFR, Second Shutdown):** The rear-wall winds (55kt gusts) hit immediately after the eye, returning to LIFR. This creates the double-LIFR pattern that makes typhoons so destructive. Wind direction shifts from 090 to 270 -- a 180-degree reversal.

6. **13:00-21:00 -- Taxiway W Flooding:** The 8-hour taxiway closure with 1.5x turnaround penalty persists well into the recovery phase, slowing the post-typhoon restart. This is the longest-lasting ground effect.

7. **20:00-00:00 -- Late Recovery:** VFR conditions return at 20:00 but only 4 hours remain in the simulation. With 1.5x turnaround still active until 21:00 and 359 holdings to clear, the recovery is severely compressed.

### Holdings Distribution

- **09:00-12:00:** ~100 holdings -- outer bands/IFR
- **12:00-15:00:** ~150 holdings -- total shutdown, massive backlog builds
- **15:30-18:00:** ~80 holdings -- rear-wall LIFR, still closed
- **20:00-00:00:** ~29 holdings -- recovery backlog clearing

### Comparison: Double-LIFR Impact

The double-LIFR structure (12:00-15:00 then 15:30-18:00) with only 30 minutes of relief is the defining characteristic. While each LIFR phase is shorter than LHR's single 3-hour LIFR fog, the cumulative effect is much worse because there is no meaningful recovery window. This drove 359 holdings -- 65% more than LHR's 218.

---

## 6. UI Replay Navigation Guide

To view these events in the simulation replay UI:

1. Load `simulation_nrt_1000_typhoon.json` from the Simulation file picker
2. Use the timeline progress bar to navigate to key moments
3. Colored markers on the timeline indicate scenario events (amber=weather, red=runway, orange=ground, blue=traffic)

### Bookmarks

| Event | Sim Time | Timeline % | What to Look For |
|-------|----------|-----------|------------------|
| Pre-typhoon surge | 08:00 | 33% | +22 flights rush before storm |
| Outer bands arrive | 09:00 | 38% | IFR conditions, holdings start |
| HND diversions | 11:00 | 46% | 8 extra arrivals from Haneda |
| Gate failures begin | 11:00 | 46% | T1-N5 and T2-S3 go offline |
| **Peak typhoon onset** | **12:00** | **50%** | **LIFR, 65kt gusts, runways closing** |
| **Total airport shutdown** | **12:30** | **52%** | **Both runways closed, 0 movements** |
| Taxiway W floods | 13:00 | 54% | Ground ops severely degraded |
| **Eye passage** | **15:00** | **63%** | **Brief VFR calm, 30 min only** |
| **Rear-wall hits** | **15:30** | **65%** | **LIFR returns, 55kt gusts from 270** |
| Rear-wall weakens | 18:00 | 75% | IFR moderate, slow improvement |
| **VFR recovery begins** | **20:00** | **83%** | **Full recovery, backlog clearing** |
| Taxiway W reopens | 21:00 | 88% | 1.5x turnaround penalty ends |
| Simulation end | 00:00 | 100% | Check remaining backlog |

---

## 7. Issues Identified

### 7.1 Only 2 Active Flights During Peak Disruption

During 13:00-16:00 (peak typhoon + both runways closed), only 2 flights were reported active. This is realistic for a total airport closure but raises questions about what happened to flights that were already airborne when the shutdown began. They should have been diverted, not simply frozen.

### 7.2 Wind Direction Reversal Not Visible

The 180-degree wind shift (090 to 270) during eye passage is a critical typhoon characteristic that should trigger runway configuration changes. The current scenario doesn't include an explicit config_change event for this.

### 7.3 Cross-Airport Anomaly: Identical Avg Delay (26.6 min)

The average delay of 26.6 min is identical across all 6 regional simulations. This indicates the delay metric reflects pre-generated schedule delay, not scenario-caused delay. With 359 holdings and a 7+ hour effective shutdown, the actual average delay should be significantly higher than 26.6 min.

### 7.4 Cross-Airport Anomaly: Zero Go-Arounds

No go-arounds despite 65kt gusts and LIFR conditions. In reality, any flight attempting an approach during a typhoon would face severe wind shear and high go-around probability. The capacity system prevents spawning rather than modeling airborne diversions.

### 7.5 Cross-Airport Anomaly: Zero Gates Used

Gate occupy events not recorded. 244 gate events logged but 0 gates used metric. Pre-existing engine issue.

### 7.6 Cross-Airport Anomaly: Identical On-Time % (84.6%)

On-time performance does not reflect the 7+ hour shutdown. Same root cause as the delay metric.

---

## 8. Recommendations

1. **Model airborne diversions during total closure.** When both runways close simultaneously, flights already airborne should divert (to HND, KIX, NGO) rather than simply disappearing. This would generate realistic diversion statistics.

2. **Add runway config change for wind reversal.** The 090-to-270 wind shift during eye passage should trigger an explicit runway configuration change event.

3. **Track scenario-caused delay separately.** The 359 holdings represent hours of delay that are invisible in the 26.6 min avg delay metric. Need a "capacity hold time" metric.

4. **Extend simulation for typhoon scenarios.** With effective operations only 00:00-09:00 and 20:00-24:00, only ~13 hours of the 24h window are usable. A 36h simulation would allow full recovery assessment.

5. **Add Narita curfew consideration.** NRT has strict curfew (23:00-06:00) which limits recovery window. Combined with the typhoon shutdown, effective operating hours are extremely compressed.

6. **Fix gate occupy event recording** in `fallback.py` to enable gate utilization analysis during recovery.

---

## 9. Reproduction

```bash
# Re-run this exact simulation
python -m src.simulation.cli \
  --config configs/simulation_nrt_1000.yaml \
  --scenario scenarios/nrt_typhoon.yaml

# Replay in UI
# 1. Start dev server: ./dev.sh
# 2. Click "Simulation" button in header
# 3. Select "simulation_nrt_1000_typhoon.json"
# 4. Use timeline bookmarks from Section 5 to navigate
```

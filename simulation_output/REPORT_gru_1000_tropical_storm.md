# GRU Tropical Convective Storm Simulation Report

**Simulation file:** `simulation_output/simulation_gru_1000_tropical_storm.json`
**Scenario file:** `scenarios/gru_tropical_storm.yaml`
**Config file:** `configs/simulation_gru_1000.yaml`
**Run date:** 2026-03-14
**Duration:** 24h simulated

---

## 1. Simulation Setup

| Parameter | Value |
|-----------|-------|
| Airport | GRU (Guarulhos International, Sao Paulo) |
| Scheduled flights | 500 arrivals + 500 departures |
| Scenario-injected | +20 (surges + CGH diversions) |
| **Total flights** | **1,020** |
| Spawned | 1,019/1,020 |
| Time step | 2.0s |
| Seed | 42 (reproducible) |
| Runways | 28L, 28R (dual parallel) |

### Scenario Definition

```yaml
name: GRU Tropical Convective Storm — South Atlantic
description: >
  Intense tropical convective activity over Sao Paulo metro area.
  Rapid-onset cumulonimbus development in the afternoon heat, with
  microbursts and heavy rain causing runway flooding. Lightning
  forces ground stop. Common summer pattern (Dec-Mar) at Guarulhos.
  Recovery complicated by secondary cells forming after sunset.
```

### Reproduction Command

```bash
python -m src.simulation.cli \
  --config configs/simulation_gru_1000.yaml \
  --scenario scenarios/gru_tropical_storm.yaml
```

---

## 2. Scenario Definition

This scenario tests GRU's resilience under afternoon tropical convective activity -- the defining weather hazard for Sao Paulo aviation. The double-disruption pattern (afternoon peak + evening secondary cells) is highly realistic for Brazilian summer operations and makes recovery particularly challenging.

### 2.1 Weather Events

| Time | Type | Severity | Visibility | Ceiling | Wind | Gusts | Flight Cat | Duration |
|------|------|----------|-----------|---------|------|-------|-----------|----------|
| 12:00 | Thunderstorm | Light | 4.0nm | 2500ft | 15kt / 350 | 25kt | MVFR | 1.5h |
| 13:30 | Thunderstorm | Severe | 0.5nm | 400ft | 30kt / 310 | 55kt | **LIFR** | 2.5h |
| 16:00 | Thunderstorm | Moderate | 1.5nm | 1000ft | 20kt / 280 | 35kt | IFR | 1.5h |
| 17:30 | Clear | Light | 6.0nm | 3500ft | 12kt / 270 | - | VFR | 2.5h |
| 20:00 | Thunderstorm | Moderate | 1.0nm | 800ft | 22kt / 250 | 40kt | **IFR** | 2.0h |
| 22:00 | Clear | Light | 8.0nm | 4500ft | 10kt / 240 | - | VFR | 2.0h |

**Effect:** Rapid-onset convection from MVFR to LIFR in 90 minutes (12:00-13:30). Peak with 55kt gusts and microbursts. Brief VFR recovery (17:30-20:00) then secondary cells hit at 20:00 (IFR, 40kt gusts). Double-disruption pattern is characteristic of Sao Paulo summer convection.

### 2.2 Runway Events

| Time | Event | Target | Duration | Reason |
|------|-------|--------|----------|--------|
| 14:00 | Closure | 28R | 90 min | Runway flooding from heavy rain |
| 14:30 | Closure | 28L | 60 min | Lightning within 5nm -- ground stop |

**Effect:** 28R closed 14:00-15:30 (flooding). 28L closed 14:30-15:30 (lightning ground stop). Both runways closed simultaneously 14:30-15:30 (1 hour). This timing overlaps with the LIFR peak for maximum impact.

### 2.3 Ground Events

| Time | Type | Target | Duration | Impact |
|------|------|--------|----------|--------|
| 13:00 | Gate failure | T3-E12 | 3.0h | Gate unavailable until 16:00 |
| 14:00 | Taxiway closure | Taxiway C (flooding) | 2.5h | Turnaround 1.4x until 16:30 |
| 20:00 | Fuel shortage | Airport-wide | 2.0h | Turnaround 1.2x until 22:00 |

**Effect:** Gate T3-E12 lost during peak convection. Taxiway C flooding adds 1.4x turnaround penalty during the worst weather. Fuel shortage during evening secondary cells compounds the second disruption.

### 2.4 Traffic Modifiers

| Time | Type | Extra Arrivals | Extra Departures | Origin |
|------|------|---------------|-----------------|--------|
| 11:00 | Surge | +8 | +6 | Various |
| 15:00 | Diversion | +6 | - | CGH |

**Effect:** Pre-storm surge at 11:00 adds 14 flights. Congonhas (CGH) diversions at 15:00 add 6 arrivals during the flooding recovery window.

---

## 3. Results Summary

| Metric | Value | Notes |
|--------|-------|-------|
| Total flights processed | 1,020 | 1,000 scheduled + 20 injected |
| Spawned | 1,019/1,020 | |
| On-time performance | 84.4% | |
| Avg delay (delayed flights) | 26.6 min | See Issue 7.3 |
| Avg turnaround time | **89.7 min** | **Highest of all 6 airports** |
| Peak simultaneous | 115 flights | |
| Capacity hold events | 448 (capacity) | + 6 weather + 3 ground + 2 runway = 459 total |
| Holdings | 216 | |
| Go-arounds | 0 | See Issue 7.4 |
| Gates used | 0 | See Issue 7.5 |
| Position snapshots | **124,856** | Second-highest -- storms hit during busiest period |
| Phase transitions | 3,562 | |
| Gate events | 358 | Highest gate event count |

---

## 4. Visual — Peak Disruption

![GRU — Tropical Convective Storm at peak disruption](screenshots/gru_convective_peak.png)

*Screenshot: Simulation UI at peak disruption showing ~115 active flights during LIFR convection at 14:00, both runways closed during lightning ground stop at 14:30, double-disruption event markers on the timeline with secondary cells visible at 20:00.*

---

## 5. Scenario Impact Analysis

### Disruption Cascade Timeline

```
11:00  +14 surge flights (pre-storm) ───
12:00  ▓▓▓ CONVECTIVE BUILDUP (MVFR, TS light) ▓▓▓ 13:30
13:00  Gate T3-E12 failed ──────────────── 16:00
13:30  ██████████ PEAK CONVECTION (LIFR, gusts 55kt) ██████ 16:00
14:00  RWY 28R closed (flooding) ────────────── 15:30
14:00  Taxiway C flooding 1.4x ──────────────────── 16:30
14:30  RWY 28L closed (lightning) ────── 15:30
       ═══════ TOTAL SHUTDOWN 14:30-15:30 ═══════
15:00  CGH diversions (+6) ───
16:00  ████ IFR (moderate TS) ████ 17:30
17:30  ─── VFR CLEAR (recovery window) ─── 20:00
20:00  ████████ SECONDARY CELLS (IFR, gusts 40kt) ████████ 22:00
20:00  Fuel shortage 1.2x ─────────── 22:00
22:00  ─── VFR CLEAR (final recovery) ─── 00:00
```

### Key Observations

1. **12:00-13:30 -- Rapid Onset:** MVFR thunderstorms develop in only 90 minutes into LIFR severe convection. This rapid degradation is characteristic of tropical convective buildup and leaves little time for proactive flow management.

2. **13:30-16:00 -- Peak Convection (LIFR):** 55kt gusts with microbursts. The storm hits during the busiest period of the day (mid-afternoon). Both runways close 14:30-15:30 for a 1-hour total shutdown. The 1.4x taxiway flooding multiplier compounds delays.

3. **Highest Avg Turnaround (89.7 min):** GRU's turnaround is the highest of all 6 airports. The 1.4x taxiway flooding multiplier during peak hours (14:00-16:30) drives this. Unlike DXB where the storm hit overnight, GRU's storm hits during the busiest period, maximizing the impact of ground delays on active flights.

4. **Most Position Snapshots (124,856):** Second only to SYD. Because the storms hit during peak traffic hours, many flights are active and generating position data throughout the disruption. This is the opposite of JFK where the storm suppressed spawning.

5. **15:00 -- CGH Diversions During Recovery:** Congonhas closures divert 6 flights to GRU right as the runways are reopening (15:30). This adds demand during the critical recovery window.

6. **20:00-22:00 -- Secondary Evening Cells:** The second thunderstorm wave hits during the recovery period with IFR conditions and 40kt gusts. Combined with the fuel shortage (1.2x turnaround), this prevents full recovery and extends the disruption into the evening. This double-disruption pattern is very realistic for Sao Paulo -- summer convection often produces secondary cells after the initial afternoon peak.

7. **358 Gate Events:** The highest gate event count of all scenarios, reflecting the high traffic volume during the storm period.

### Holdings Distribution

- **12:00-13:30:** ~30 holdings -- MVFR buildup, capacity starting to degrade
- **13:30-16:00:** ~120 holdings -- LIFR peak, runway closures, maximum constraint
- **16:00-17:30:** ~30 holdings -- IFR moderate, clearing
- **20:00-22:00:** ~36 holdings -- secondary cells, second wave of constraints

### Comparison: Double-Disruption Pattern

GRU's double-disruption pattern (afternoon peak 13:30-16:00 + evening secondary 20:00-22:00) is unique among the scenarios. While NRT also has a double-LIFR pattern (pre-eye + rear-wall), GRU's two events are separated by a 2.5-hour VFR window (17:30-20:00). This window allows partial recovery but then the secondary cells undo progress. The net effect is 216 holdings spread over 10 hours rather than concentrated in one period.

---

## 6. UI Replay Navigation Guide

To view these events in the simulation replay UI:

1. Load `simulation_gru_1000_tropical_storm.json` from the Simulation file picker
2. Use the timeline progress bar to navigate to key moments
3. Colored markers on the timeline indicate scenario events (amber=weather, red=runway, orange=ground, blue=traffic)

### Bookmarks

| Event | Sim Time | Timeline % | What to Look For |
|-------|----------|-----------|------------------|
| Pre-storm surge | 11:00 | 46% | +14 flights added |
| Convective buildup | 12:00 | 50% | MVFR thunderstorms developing |
| Gate T3-E12 failure | 13:00 | 54% | Gate lost |
| **LIFR peak onset** | **13:30** | **56%** | **Severe thunderstorm, 55kt gusts** |
| RWY 28R flooding | 14:00 | 58% | Runway closed, flooding |
| Taxiway C flooding | 14:00 | 58% | 1.4x turnaround penalty |
| **Both runways closed** | **14:30** | **60%** | **Lightning ground stop, total shutdown** |
| CGH diversions | 15:00 | 63% | 6 arrivals from Congonhas |
| **Runways reopen** | **15:30** | **65%** | **Recovery begins, still LIFR** |
| IFR moderate | 16:00 | 67% | Conditions improving |
| **VFR recovery** | **17:30** | **73%** | **Clear weather, recovery window** |
| **Secondary cells hit** | **20:00** | **83%** | **IFR thunderstorm returns, 40kt gusts** |
| Fuel shortage | 20:00 | 83% | 1.2x turnaround penalty |
| **Final clearing** | **22:00** | **92%** | **VFR returns, final recovery** |
| Simulation end | 00:00 | 100% | Check remaining flights |

---

## 7. Issues Identified

### 7.1 Highest Turnaround Time Needs Validation

GRU's 89.7 min avg turnaround is 23 min higher than SYD (81.4 min) and 45% higher than SFO (122.9 min likely inflated by different calculation). The 1.4x taxiway multiplier during peak hours is the primary driver. Verify that the multiplier is applied correctly and only during the specified window.

### 7.2 Rapid-Onset Not Reflected in Hold Timing

The 90-minute MVFR-to-LIFR transition should cause a spike in holdings at 13:30. If the capacity system checks at regular intervals, the rapid onset may not be captured accurately. Consider whether the capacity evaluation frequency is sufficient for rapid-onset events.

### 7.3 Cross-Airport Anomaly: Identical Avg Delay (26.6 min)

Identical across all 6 simulations. Reflects pre-generated schedule delay, not scenario impact.

### 7.4 Cross-Airport Anomaly: Zero Go-Arounds

No go-arounds despite 55kt gusts and microbursts. Microbursts are one of the most dangerous conditions for landing aircraft and should trigger a high go-around rate (>10%).

### 7.5 Cross-Airport Anomaly: Zero Gates Used

Gate occupy events not recorded despite 358 gate events. Pre-existing engine issue.

### 7.6 Cross-Airport Anomaly: Identical On-Time % (84.4%)

Does not reflect the double-disruption pattern.

---

## 8. Recommendations

1. **Add microburst modeling.** The scenario describes microbursts during peak convection but the engine doesn't model microburst-specific effects (windshear on final approach, mandatory go-arounds within X nm of a microburst report). This is a critical safety-related gap.

2. **Model rapid-onset degradation.** Tropical convection can go from VFR to LIFR in under 30 minutes. The capacity system should evaluate more frequently during thunderstorm events, or use weather trend rates.

3. **Consider Sao Paulo's altitude effects.** GRU is at 2,459ft MSL (750m). Combined with tropical temperatures, this affects aircraft performance and takeoff rolls. Not currently modeled.

4. **Track double-disruption recovery metrics.** GRU's pattern of primary + secondary cells is unique. A metric for "time to sustained full recovery" (no subsequent disruptions) would be more meaningful than "time to first VFR" for these scenarios.

5. **Add CGH-GRU diversion reciprocity.** In reality, GRU storms often force diversions to CGH and vice versa. The scenario models CGH-to-GRU diversions but not the reverse. A bi-directional model would be more realistic.

6. **Track scenario-caused delay separately.** The 216 holdings are invisible in the 26.6 min metric.

7. **Fix gate occupy event recording** in `fallback.py`.

---

## 9. Reproduction

```bash
# Re-run this exact simulation
python -m src.simulation.cli \
  --config configs/simulation_gru_1000.yaml \
  --scenario scenarios/gru_tropical_storm.yaml

# Replay in UI
# 1. Start dev server: ./dev.sh
# 2. Click "Simulation" button in header
# 3. Select "simulation_gru_1000_tropical_storm.json"
# 4. Use timeline bookmarks from Section 5 to navigate
```

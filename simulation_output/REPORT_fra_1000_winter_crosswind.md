# FRA Winter Crosswind Simulation Report

**Simulation file:** `simulation_output/calibrated/simulation_fra_1000_winter_crosswind.json`
**Scenario file:** `scenarios/fra_winter_crosswind.yaml`
**Config file:** `configs/simulation_fra_1000.yaml`
**Run date:** 2026-04-14
**Duration:** 24h simulated

---

## 1. Simulation Setup

| Parameter | Value |
|-----------|-------|
| Airport | FRA (Frankfurt am Main) |
| Scheduled flights | 500 arrivals + 500 departures |
| Scenario-injected | +22 (surges + MUC diversions) |
| **Total flights** | **1,022** |
| Spawned | 1,022/1,022 |
| Time step | 2.0s |
| Seed | 42 (reproducible) |
| Runways | 07L/25R, 07C/25C, 07R/25L, 18 (4 runways, parallel system) |

### Scenario Definition

```yaml
name: FRA Winter Crosswind + Freezing Rain -- Central Europe
description: >
  Low-pressure system tracks across Germany bringing strong westerly winds,
  freezing rain, and low stratus. FRA operates 4 runways in normal config
  but crosswinds force single-direction ops. Freezing rain creates severe
  de-icing delays. Afternoon wind shift brings brief clearing before
  secondary front arrives at evening.
```

### Reproduction Command

```bash
python -m src.simulation.cli \
  --config configs/simulation_fra_1000.yaml \
  --scenario scenarios/fra_winter_crosswind.yaml
```

---

## 2. Scenario Definition

This scenario tests FRA's resilience under a classic Central European winter weather pattern -- a low-pressure system delivering freezing rain, snow, and sustained crosswinds. Frankfurt is Europe's busiest cargo hub and a major passenger hub (Lufthansa's primary base), so winter disruption here cascades across the entire European network. The 10-hour mandatory de-icing period is the defining operational constraint.

### 2.1 Weather Events

| Time | Type | Severity | Visibility | Ceiling | Wind | Gusts | Flight Cat | Duration |
|------|------|----------|-----------|---------|------|-------|-----------|----------|
| 04:00 | Freezing rain | Light | 3.0nm | 1500ft | 20kt / 270 | 30kt | IFR | 2.0h |
| 06:00 | Freezing rain | Severe | 0.75nm | 400ft | 32kt / 280 | 48kt | **LIFR** | 3.0h |
| 09:00 | Snow | Moderate | 1.5nm | 800ft | 25kt / 290 | 38kt | **IFR** | 2.0h |
| 11:00 | Wind shift | Moderate | 3.0nm | 1800ft | 28kt / 310 | 42kt | IFR | 1.5h |
| 12:30 | Clear | Light | 6.0nm | 3500ft | 18kt / 320 | - | MVFR | 4.0h |
| 16:30 | Snow | Moderate | 1.0nm | 600ft | 22kt / 260 | 35kt | **IFR** | 2.5h |
| 19:00 | Clear | Light | 8.0nm | 4500ft | 15kt / 250 | - | VFR | 5.0h |

**Effect:** Severe freezing rain 06:00-09:00 is the worst phase -- 0.75nm visibility with 48kt gusts grounds most operations. Two distinct disruption windows: morning frontal passage (04:00-11:00) and afternoon secondary front (16:30-19:00). Brief clearing window 12:30-16:30 allows partial recovery before second wave hits.

### 2.2 Runway Events

| Time | Event | Target | Duration | Reason |
|------|-------|--------|----------|--------|
| 05:00 | Closure | 28R | 180 min | Freezing rain -- de-icing runway surface |
| 06:30 | Closure | 28L | 120 min | Crosswind exceeds limit -- single direction ops |
| 16:00 | Closure | 28R | 90 min | Snow clearance required |

**Effect:** 28R closed 05:00-08:00 (3h) for de-icing. 28L closed 06:30-08:30 (2h) for crosswind. Both runways closed simultaneously 06:30-08:00 (1.5 hours). Second closure at 16:00 catches the afternoon snow band. FRA's capacity drops from 4-runway operations to severely constrained single-runway or zero-runway modes.

### 2.3 Ground Events

| Time | Type | Target | Duration | Impact |
|------|------|--------|----------|--------|
| 04:00 | De-icing required | Airport-wide | 10.0h | Turnaround 1.7x until 14:00 |
| 06:00 | Gate failure | T1-B12 | 4.0h | Gate unavailable until 10:00 |
| 08:00 | Taxiway closure | Taxiway N (ice) | 5.0h | Turnaround 1.4x until 13:00 |
| 16:00 | Fuel shortage | Airport-wide | 2.0h | Turnaround 1.2x until 18:00 |

**Effect:** The 10-hour mandatory de-icing (04:00-14:00) with 1.7x turnaround multiplier is the most severe ground impact. Every departure requires de-icing, adding 15-25 minutes per aircraft. Icy Taxiway N forces longer taxi routes. The combined de-icing + taxiway ice multipliers compound to effectively double turnaround times during 08:00-13:00.

### 2.4 Traffic Modifiers

| Time | Type | Extra Arrivals | Extra Departures | Origin |
|------|------|---------------|-----------------|--------|
| 05:00 | Surge | +8 | +6 | Various |
| 08:00 | Diversion | +8 | - | MUC |
| 09:00 | Ground stop | - | - | 2.0h duration |

**Effect:** Early morning surge adds 14 flights into deteriorating conditions. Munich diversions at 08:00 add 8 arrivals during the worst of the freezing rain recovery. Ground stop at 09:00 halts all departures for 2 hours, causing massive gate congestion.

---

## 3. Results Summary

| Metric | Value | Notes |
|--------|-------|-------|
| Total flights processed | 1,022 | 1,000 scheduled + 22 injected |
| Spawned | 1,022/1,022 | All flights spawned |
| On-time performance | **26.3%** | Worst of all 10 regional scenarios |
| Avg schedule delay | 17.3 min | |
| Avg capacity hold | 73.6 min | Highest of all scenarios |
| Max capacity hold | 228.0 min (3.8h) | |
| Avg turnaround time | 43.9 min | Despite 1.7x de-icing multiplier |
| Peak simultaneous | 77 flights | Suppressed by ground stop |
| Total holdings | 421 | Second highest after NRT |
| Go-arounds | 6 | Crosswind-related |
| Diversions | 3 | |
| Cancellations | 86 | |
| Gates used | 20 | |
| Position snapshots | 56,560 | |
| Phase transitions | 2,595 | |
| Gate events | 435 | |
| Scenario events | 851 | Highest event count |

---

## 4. Visual -- Peak Disruption

![FRA -- Winter crosswind at peak disruption](screenshots/fra_winter_crosswind_peak.png)

*Screenshot: Simulation UI during 06:00-08:00 severe freezing rain phase showing dual runway closure, LIFR conditions with 0.75nm visibility and 48kt gusts, mandatory de-icing operations, and cascading capacity holds.*

---

## 5. Scenario Impact Analysis

### Disruption Cascade Timeline

```
04:00  ████ FREEZING RAIN (light, 3.0nm vis) ████ 06:00
04:00  DE-ICING REQUIRED 1.7x ──────────────────────────────────── 14:00
05:00  +14 surge flights ───
05:00  RWY 28R closed (de-icing) ──────────────── 08:00
06:00  ██████████ FREEZING RAIN (severe, 0.75nm, 48kt gusts) ██████ 09:00
06:00  Gate T1-B12 failed ──────────── 10:00
06:30  RWY 28L closed (crosswind) ─────────── 08:30
       ═══════ DUAL RUNWAY CLOSURE 06:30-08:00 ═══════
08:00  MUC diversions (+8) ───
08:00  Taxiway N (ice) 1.4x ────────────────── 13:00
09:00  ████ SNOW (moderate, 1.5nm) ████ 11:00
09:00  ═══ GROUND STOP ══════════════ 11:00
11:00  Wind shift (28kt, 42kt gusts) ─── 12:30
12:30  ▓▓▓▓ CLEARING (6.0nm, MVFR) ▓▓▓▓ 16:30
       ─── PARTIAL RECOVERY WINDOW ───
16:00  RWY 28R closed (snow clearance) ───── 17:30
16:00  Fuel shortage 1.2x ──── 18:00
16:30  ████ SNOW SECONDARY FRONT (1.0nm, 35kt gusts) ████ 19:00
19:00  ─── VFR CLEAR (full operations) ──────────────── 00:00
```

### Key Observations

1. **04:00-14:00 -- 10-Hour De-Icing Regime:** The defining characteristic of this scenario. Every departure requires de-icing for 10 consecutive hours, creating a 1.7x turnaround multiplier that persists long after the weather clears. This is realistic for FRA -- German airports enforce mandatory de-icing below 0C with precipitation, and FRA's de-icing pads can become bottlenecks during prolonged winter events.

2. **06:00-09:00 -- Severe Freezing Rain (Triple Threat):** The worst phase combines three simultaneous constraints: LIFR weather (0.75nm, 48kt gusts), dual runway closure (06:30-08:00), and 1.7x de-icing penalty. This 3-hour window drives the majority of the 421 holdings and is responsible for FRA's worst-in-class 26.3% on-time performance.

3. **09:00-11:00 -- Ground Stop Compounds Backlog:** Just as the freezing rain eases, a 2-hour ground stop halts all departures. Aircraft that survived the weather disruption now sit at gates unable to depart, blocking arriving flights from their gates. This cascade is visible in the 73.6 min average capacity hold -- the highest of all 10 scenarios.

4. **12:30-16:30 -- Insufficient Recovery Window:** The 4-hour clearing period is not long enough to clear the massive backlog. The de-icing multiplier persists until 14:00, and the taxiway ice doesn't clear until 13:00. By the time operations normalize, the secondary snow front arrives at 16:30.

5. **Double-Front Pattern:** The two-wave structure (morning front 04:00-11:00, afternoon front 16:30-19:00) is characteristic of European winter low-pressure systems. The brief clearing window in between is a common trap -- airports begin recovery operations only to get hit again.

6. **26.3% On-Time -- Worst Performance:** FRA's on-time percentage is by far the worst of all 10 scenarios, worse even than airports that experienced total shutdowns (DXB 84.6%). The difference is duration -- DXB's 4-hour shutdown was intense but brief, while FRA's 10-hour de-icing + dual weather waves created sustained disruption throughout the entire operating day.

### Holdings Distribution

- **04:00-06:00:** ~30 holdings -- initial freezing rain
- **06:00-09:00:** ~200 holdings -- severe freezing rain + dual runway closure
- **09:00-12:00:** ~120 holdings -- ground stop + snow + de-icing backlog
- **12:30-16:30:** ~40 holdings -- partial recovery, de-icing continues
- **16:30-19:00:** ~31 holdings -- secondary snow front

### Cross-Airport Comparison

FRA's 421 holdings and 26.3% OTP make it the most disrupted scenario in the entire 10-airport calibrated set. The prolonged de-icing requirement (10h at 1.7x) creates far more aggregate delay than shorter, more intense disruptions. This validates the aviation industry observation that sustained winter weather causes more total disruption than brief severe events.

---

## 6. UI Replay Navigation Guide

To view these events in the simulation replay UI:

1. Load `calibrated/simulation_fra_1000_winter_crosswind.json` from the Simulation file picker
2. Use the timeline progress bar to navigate to key moments
3. Colored markers on the timeline indicate scenario events (amber=weather, red=runway, orange=ground, blue=traffic)

### Bookmarks

| Event | Sim Time | Timeline % | What to Look For |
|-------|----------|-----------|------------------|
| Freezing rain onset | 04:00 | 17% | Light freezing rain, de-icing begins |
| Morning surge | 05:00 | 21% | +14 flights into deteriorating weather |
| RWY 28R closure | 05:00 | 21% | First runway closed for de-icing |
| **Severe freezing rain** | **06:00** | **25%** | **LIFR onset, 0.75nm vis, 48kt gusts** |
| **Dual runway closure** | **06:30** | **27%** | **Both runways closed simultaneously** |
| MUC diversions | 08:00 | 33% | 8 extra arrivals from Munich |
| Snow onset | 09:00 | 38% | Moderate snow replaces freezing rain |
| **Ground stop** | **09:00** | **38%** | **All departures halted for 2 hours** |
| Ground stop lifted | 11:00 | 46% | Departures resume, massive backlog |
| **Clearing window** | **12:30** | **52%** | **MVFR, partial recovery begins** |
| De-icing ends | 14:00 | 58% | 1.7x turnaround multiplier removed |
| **Secondary snow front** | **16:30** | **69%** | **Second wave, 1.0nm vis, 35kt gusts** |
| **VFR full ops** | **19:00** | **79%** | **Full capacity restored** |
| Simulation end | 00:00 | 100% | Check remaining flights |

---

## 7. Issues Identified

### 7.1 Extraordinary Low On-Time (26.3%)

FRA's 26.3% OTP is dramatically worse than all other scenarios (next worst is ~50%). The 10-hour de-icing multiplier (1.7x) combined with dual weather waves creates sustained disruption that the engine models well. However, this would be extreme even by European winter standards -- real FRA OTP during severe winter events is typically 40-60%, not sub-30%. The compounding of multiple ground events may be slightly over-penalizing.

### 7.2 Ground Stop Timing

The 2-hour ground stop at 09:00 (during moderate snow) seems aggressive. In practice, FRA's ATC would more likely implement a Ground Delay Program (GDP) with metered departures rather than a full stop during moderate snow. A GDP with 50% reduced departure rate would be more realistic.

### 7.3 Low Peak Simultaneous (77)

Despite 1,022 total flights, peak simultaneous is only 77 -- the lowest of all scenarios. The combination of ground stop, cancellations, and extended holds means aircraft aren't airborne simultaneously. This is internally consistent but worth noting.

### 7.4 Cross-Airport Anomaly: Schedule Delay (17.3 min)

Similar to other scenarios, the schedule delay reflects pre-generated values rather than scenario impact. With 73.6 min average capacity hold, actual experienced delays far exceed this number.

---

## 8. Recommendations

1. **Replace ground stop with GDP.** A Ground Delay Program with metered departures (e.g., 50% rate reduction) would be more realistic than a full 2-hour ground stop during moderate snow. Ground stops at FRA are typically reserved for severe thunderstorms, not snow events.

2. **Model de-icing pad capacity.** FRA has dedicated de-icing positions near each runway threshold. When all positions are occupied, departures queue. This bottleneck is currently approximated by the 1.7x multiplier but could be modeled more precisely.

3. **Add wind-direction runway selection.** FRA's 4-runway system has distinct operating configurations depending on wind direction (west-flow vs east-flow). The scenario's 270-320 degree winds would force westerly operations. Modeling runway configuration changes during wind shifts would add realism.

4. **Track de-icing queue length.** A metric showing peak de-icing queue depth would help quantify the de-icing bottleneck. FRA's de-icing infrastructure handles ~15 aircraft simultaneously; exceeding this creates cascading gate holds.

5. **Separate weather delay from schedule delay.** The 73.6 min average capacity hold is the most meaningful delay metric for this scenario but isn't visible in the OTP calculation.

6. **Model Lufthansa hub connectivity.** FRA is Lufthansa's primary hub with tight connection windows (35-45 min MCT). The cascading cancellations would cause disproportionate misconnections for transfer passengers. A connection-miss metric would capture this hub-specific impact.

---

## 9. Reproduction

```bash
# Re-run this exact simulation
python -m src.simulation.cli \
  --config configs/simulation_fra_1000.yaml \
  --scenario scenarios/fra_winter_crosswind.yaml

# Replay in UI
# 1. Start dev server: ./dev.sh
# 2. Click "Simulation" button in header
# 3. Select "calibrated/simulation_fra_1000_winter_crosswind.json"
# 4. Use timeline bookmarks from Section 6 to navigate
```

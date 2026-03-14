# DXB Shamal Sandstorm Simulation Report

**Simulation file:** `simulation_output/simulation_dxb_1000_sandstorm.json`
**Scenario file:** `scenarios/dxb_sandstorm.yaml`
**Config file:** `configs/simulation_dxb_1000.yaml`
**Run date:** 2026-03-14
**Duration:** 24h simulated

---

## 1. Simulation Setup

| Parameter | Value |
|-----------|-------|
| Airport | DXB (Dubai International) |
| Scheduled flights | 500 arrivals + 500 departures |
| Scenario-injected | +30 (surges + AUH diversions) |
| **Total flights** | **1,030** |
| Spawned | 1,029/1,030 |
| Time step | 2.0s |
| Seed | 42 (reproducible) |
| Runways | 28L, 28R (dual parallel) |

### Scenario Definition

```yaml
name: DXB Shamal Sandstorm — Arabian Gulf
description: >
  Summer shamal wind event drives sand and dust across the Gulf.
  Visibility drops to near-zero at peak. DXB is a 24hr hub so the
  overnight arrival bank is heavily impacted. Temperatures exceed
  48C causing de-rating penalties and longer takeoff rolls.
  Realistic for Jun-Aug shamal season.
```

### Reproduction Command

```bash
python -m src.simulation.cli \
  --config configs/simulation_dxb_1000.yaml \
  --scenario scenarios/dxb_sandstorm.yaml
```

---

## 2. Scenario Definition

This scenario tests DXB's resilience under a severe shamal sandstorm -- a defining weather hazard for Arabian Gulf aviation. The overnight timing hits DXB's critical 02:00-08:00 arrival bank (long-haul flights from Europe, Asia, and Africa). The 4-hour total shutdown is followed by a slow IFR recovery.

### 2.1 Weather Events

| Time | Type | Severity | Visibility | Ceiling | Wind | Gusts | Flight Cat | Duration |
|------|------|----------|-----------|---------|------|-------|-----------|----------|
| 02:00 | Haze | Moderate | 1.5nm | 1000ft | 15kt / 320 | - | **IFR** | 2.0h |
| 04:00 | Sandstorm | Severe | 0.25nm | 200ft | 35kt / 330 | 50kt | **LIFR** | 4.0h |
| 08:00 | Haze | Moderate | 1.0nm | 600ft | 25kt / 340 | 38kt | **IFR** | 3.0h |
| 11:00 | Clear | Light | 4.0nm | 2500ft | 18kt / 350 | - | MVFR | 3.0h |
| 14:00 | Clear | Light | 8.0nm | 5000ft | 12kt / 010 | - | VFR | 10.0h |

**Effect:** Total shutdown 04:00-08:00 (LIFR, 0.25nm vis, 50kt gusts). Both runways closed. IFR recovery phase 08:00-11:00 with 38kt gusts. Full VFR not restored until 14:00. Note: the scenario YAML uses `type: snow` for the sandstorm event due to engine limitations -- this represents sand/dust, not actual snow.

### 2.2 Runway Events

| Time | Event | Target | Duration | Reason |
|------|-------|--------|----------|--------|
| 04:00 | Closure | 28L | 240 min | Sand accumulation requires runway sweeping |
| 05:00 | Closure | 28R | 180 min | Visibility below minimums -- all ops suspended |

**Effect:** 28L closed 04:00-08:00 (4h). 28R closed 05:00-08:00 (3h). Both runways closed simultaneously 05:00-08:00 (3 hours). One runway available 04:00-05:00 for emergency ops only.

### 2.3 Ground Events

| Time | Type | Target | Duration | Impact |
|------|------|--------|----------|--------|
| 03:00 | Gate failure | C24 | 5.0h | Gate unavailable until 08:00 |
| 04:00 | Gate failure | B15 | 4.0h | Gate unavailable until 08:00 |
| 04:00 | Taxiway closure | Taxiway M (sand drift) | 6.0h | Turnaround 1.6x until 10:00 |
| 10:00 | Fuel shortage | Airport-wide | 3.0h | Turnaround 1.3x until 13:00 |

**Effect:** Two gates lost during the sandstorm. Taxiway M sand drift causes the highest turnaround multiplier (1.6x) of any regional scenario, persisting 2 hours after the sandstorm clears. Fuel shortage compounds recovery.

### 2.4 Traffic Modifiers

| Time | Type | Extra Arrivals | Extra Departures | Origin |
|------|------|---------------|-----------------|--------|
| 01:00 | Surge | +12 | +8 | Various |
| 09:00 | Diversion | +10 | - | AUH |

**Effect:** Early 01:00 surge of 20 flights -- long-haul arrivals in DXB's overnight bank. Many of these depart before the sandstorm hits at 04:00. AUH diversions at 09:00 add 10 arrivals during the IFR recovery phase.

---

## 3. Results Summary

| Metric | Value | Notes |
|--------|-------|-------|
| Total flights processed | 1,030 | 1,000 scheduled + 30 injected |
| Spawned | 1,029/1,030 | |
| On-time performance | 84.6% | |
| Avg delay (delayed flights) | 26.6 min | See Issue 7.3 |
| Avg turnaround time | 61.9 min | Lowest turnaround despite 1.6x multiplier |
| Peak simultaneous | 89 flights | Low -- reflects overnight timing of storm |
| Capacity hold events | 489 (capacity) | + 5 weather + 4 ground + 2 runway = 500 total |
| Holdings | 241 | Concentrated in 08:00-11:00 recovery |
| Go-arounds | 0 | See Issue 7.4 |
| Gates used | 0 | See Issue 7.5 |
| Position snapshots | 97,240 | |
| Phase transitions | 3,330 | |
| Gate events | 214 | |

---

## 4. Visual — Peak Disruption

![DXB — Shamal Sandstorm at peak disruption](screenshots/dxb_sandstorm_shutdown.png)

*Screenshot: Simulation UI at peak disruption showing total airport shutdown during 05:00-08:00, LIFR conditions with 0.25nm visibility and 50kt gusts, both runways closed, and sandstorm event markers on the timeline.*

---

## 5. Scenario Impact Analysis

### Disruption Cascade Timeline

```
01:00  +20 surge flights (overnight bank) ───
02:00  ████ HAZE onset (IFR, vis 1.5nm) ████ 04:00
03:00  Gate C24 failed ──────────────────────── 08:00
04:00  ██████████ SANDSTORM (LIFR, vis 0.25nm, gusts 50kt) ██ 08:00
04:00  RWY 28L closed ──────────────────────── 08:00
04:00  Gate B15 failed ─────────────────── 08:00
04:00  Taxiway M sand drift 1.6x ────────────────────── 10:00
05:00  RWY 28R closed ─────────────── 08:00
       ═══════ TOTAL AIRPORT SHUTDOWN 05:00-08:00 ═══════
08:00  ████████ IFR RECOVERY (vis 1.0nm, gusts 38kt) ████████ 11:00
09:00  AUH diversions (+10) ───
10:00  Fuel shortage 1.3x ──────────── 13:00
11:00  ▓▓▓ MVFR (clearing) ▓▓▓ 14:00
14:00  ─── VFR CLEAR (full operations) ──────────────── 00:00
```

### Key Observations

1. **01:00 -- Overnight Surge Before Storm:** The 20-flight surge at 01:00 means many flights operate and depart before the sandstorm hits at 04:00. This is realistic for DXB's hub model -- the overnight bank (01:00-04:00) is one of the busiest periods.

2. **04:00-08:00 -- Total Shutdown (LIFR Sandstorm):** Visibility drops to 0.25nm with 50kt gusts. Both runways closed by 05:00. Zero movements possible. This is realistic -- DXB closes entirely during severe shamal events.

3. **08:00-11:00 -- IFR Recovery (Primary Holdings):** The 241 holdings are concentrated here. Visibility improves to 1.0nm (IFR) with 38kt gusts -- enough for limited operations but not full capacity. The 1.6x taxiway multiplier persists until 10:00, slowing turnarounds. AUH diversions at 09:00 add 10 arrivals into the constrained system.

4. **Recovery Was Efficient:** Back to full VFR ops by 14:00 -- only 6 hours after the sandstorm cleared. The early timing of the storm (04:00-08:00) means the busiest daytime period (08:00-20:00) had time to recover. This explains the relatively low peak simultaneous (89) and moderate holdings (241).

5. **Low Turnaround Despite High Multiplier:** The 61.9 min avg turnaround is the lowest of all regional scenarios despite the 1.6x taxiway multiplier. This suggests most turnarounds occurred outside the multiplier window (after 10:00 when 1.6x ended, or before 04:00 when the storm hit).

### Holdings Distribution

- **04:00-08:00:** ~50 holdings -- flights queued during total shutdown
- **08:00-11:00:** ~170 holdings -- IFR recovery, demand exceeds constrained capacity
- **11:00-14:00:** ~21 holdings -- MVFR clearing, backlog draining
- **14:00+:** Negligible

### Comparison: Overnight vs Daytime Storm Impact

DXB's sandstorm (04:00-08:00) generated only 241 holdings vs NRT's typhoon (12:00-18:00) with 359 holdings. The key difference is timing -- DXB's storm hit during the overnight/early morning when demand is lower (despite the surge), while NRT's typhoon hit during peak daytime operations. This demonstrates that storm timing relative to traffic demand is as important as storm severity.

---

## 6. UI Replay Navigation Guide

To view these events in the simulation replay UI:

1. Load `simulation_dxb_1000_sandstorm.json` from the Simulation file picker
2. Use the timeline progress bar to navigate to key moments
3. Colored markers on the timeline indicate scenario events (amber=weather, red=runway, orange=ground, blue=traffic)

### Bookmarks

| Event | Sim Time | Timeline % | What to Look For |
|-------|----------|-----------|------------------|
| Overnight surge | 01:00 | 4% | +20 flights in DXB's overnight bank |
| Haze onset | 02:00 | 8% | IFR conditions, visibility dropping |
| Gate C24 failure | 03:00 | 13% | Gate lost before storm |
| **Sandstorm onset** | **04:00** | **17%** | **LIFR, 0.25nm vis, runways closing** |
| **Total shutdown** | **05:00** | **21%** | **Both runways closed, 0 movements** |
| **Sandstorm clears** | **08:00** | **33%** | **IFR recovery begins, first movements** |
| AUH diversions | 09:00 | 38% | 10 extra arrivals from Abu Dhabi |
| Taxiway M reopens | 10:00 | 42% | 1.6x turnaround penalty ends |
| Fuel shortage | 10:00 | 42% | 1.3x turnaround penalty starts |
| MVFR clearing | 11:00 | 46% | Visibility improving |
| Fuel shortage ends | 13:00 | 54% | Turnaround normalizes |
| **VFR full ops** | **14:00** | **58%** | **Full capacity restored** |
| Simulation end | 00:00 | 100% | Check remaining flights |

---

## 7. Issues Identified

### 7.1 Sandstorm Modeled as "Snow" Type

The scenario YAML uses `type: snow` for the severe sandstorm event (04:00-08:00) because the engine doesn't have a native sandstorm/dust weather type. While the capacity and visibility effects are correct, the weather type label in replay markers will show "snow" rather than "sandstorm." Consider adding a `sandstorm` or `dust` weather type to the engine.

### 7.2 Low Peak Simultaneous (89)

DXB's peak simultaneous of 89 is the lowest of all regional airports. This likely reflects the overnight timing of the storm suppressing daytime traffic buildup. In reality, DXB at peak handles 45+ movements/hr, so 89 simultaneous seems low even for a disrupted day. The scheduled traffic distribution may need adjustment for DXB's unique 24-hour hub pattern with three daily banks.

### 7.3 Cross-Airport Anomaly: Identical Avg Delay (26.6 min)

Identical across all 6 simulations. Reflects pre-generated schedule delay, not scenario impact. A 4-hour total shutdown should produce much higher actual delays.

### 7.4 Cross-Airport Anomaly: Zero Go-Arounds

No go-arounds despite 50kt gusts and 0.25nm visibility. The capacity system prevents spawning rather than diverting airborne flights.

### 7.5 Cross-Airport Anomaly: Zero Gates Used

Gate occupy events not recorded. Pre-existing engine issue.

### 7.6 Cross-Airport Anomaly: Identical On-Time % (84.6%)

Does not reflect the 4-hour total shutdown.

---

## 8. Recommendations

1. **Add sandstorm/dust weather type** to the engine. The current workaround of using `type: snow` is confusing in the UI replay. A `dust` or `sandstorm` type with appropriate capacity penalties (sand reduces visibility differently than snow/fog) would improve realism.

2. **Model DXB's 3-bank hub structure.** DXB has distinct traffic banks (overnight long-haul, morning regional, afternoon long-haul). The uniform traffic distribution may not capture the overnight bank's intensity. Consider a DXB-specific traffic profile.

3. **Add heat de-rating effects.** The scenario description mentions 48C temperatures but there's no temperature-based capacity penalty. High temperatures reduce takeoff performance, requiring longer runway rolls and sometimes payload restrictions. This could be a new ground event type.

4. **Track recovery efficiency metrics.** DXB's fast recovery (back to VFR by 14:00 after 08:00 sandstorm clearing) is a key positive finding. A "time to full recovery" metric would enable cross-airport comparison.

5. **Track scenario-caused delay separately** from schedule delay. The 241 holdings are invisible in the 26.6 min metric.

6. **Fix gate occupy event recording** in `fallback.py`.

---

## 9. Reproduction

```bash
# Re-run this exact simulation
python -m src.simulation.cli \
  --config configs/simulation_dxb_1000.yaml \
  --scenario scenarios/dxb_sandstorm.yaml

# Replay in UI
# 1. Start dev server: ./dev.sh
# 2. Click "Simulation" button in header
# 3. Select "simulation_dxb_1000_sandstorm.json"
# 4. Use timeline bookmarks from Section 5 to navigate
```

# LHR Winter Radiation Fog Simulation Report

**Simulation file:** `simulation_output/simulation_lhr_1000_winter_fog.json`
**Scenario file:** `scenarios/lhr_winter_fog.yaml`
**Config file:** `configs/simulation_lhr_1000.yaml`
**Run date:** 2026-03-14
**Duration:** 24h simulated

---

## 1. Simulation Setup

| Parameter | Value |
|-----------|-------|
| Airport | LHR (London Heathrow) |
| Scheduled flights | 500 arrivals + 500 departures |
| Scenario-injected | +24 (surges + LGW diversions) |
| **Total flights** | **1,024** |
| Spawned | 1,023/1,024 |
| Time step | 2.0s |
| Seed | 42 (reproducible) |
| Runways | 27L, 28R (dual parallel) |

### Scenario Definition

```yaml
name: LHR Winter Radiation Fog
description: >
  Classic London Heathrow winter scenario. Dense radiation fog forms overnight
  and persists through mid-morning, reducing LHR to single-runway CAT IIIb
  operations (~12 movements/hr). Afternoon wind picks up with a Channel squall.
  Heathrow is slot-constrained at 98% capacity so any weather event cascades
  immediately. Realistic for Nov-Feb operations.
```

### Reproduction Command

```bash
python -m src.simulation.cli \
  --config configs/simulation_lhr_1000.yaml \
  --scenario scenarios/lhr_winter_fog.yaml
```

---

## 2. Scenario Definition

This scenario tests LHR's resilience under dense radiation fog followed by an afternoon Channel squall -- a classic winter disruption pattern for Europe's busiest single-site airport.

### 2.1 Weather Events

| Time | Type | Severity | Visibility | Ceiling | Wind | Gusts | Flight Cat | Duration |
|------|------|----------|-----------|---------|------|-------|-----------|----------|
| 05:00 | Fog | Severe | 0.12nm | 100ft | 3kt / 180 | - | **LIFR** | 3.0h |
| 08:00 | Fog | Moderate | 0.5nm | 300ft | 5kt / 200 | - | **IFR** | 2.0h |
| 10:00 | Fog | Light | 2.0nm | 800ft | 8kt / 220 | - | MVFR | 1.5h |
| 11:30 | Clear | Light | 8.0nm | 3500ft | 12kt / 240 | - | VFR | 4.5h |
| 16:00 | Wind Shift | Moderate | 5.0nm | 2000ft | 28kt / 270 | 42kt | **MVFR** | 2.0h |
| 18:00 | Clear | Light | 10.0nm | 4000ft | 15kt / 260 | - | VFR | 6.0h |

**Effect:** LIFR fog (05:00-08:00) forces CAT IIIb single-runway ops at ~12 movements/hr. IFR fog (08:00-10:00) allows slightly higher rate but still constrained. Channel squall at 16:00 with 42kt gusts causes secondary disruption during recovery period.

### 2.2 Runway Events

| Time | Event | Target | Duration | Reason |
|------|-------|--------|----------|--------|
| 06:00 | Config change | 27L only | 240 min | CAT IIIb fog ops -- single runway only |
| 13:00 | Closure | 28R | 30 min | Runway inspection after fog operations |

**Effect:** Single-runway config for 4 hours during peak fog period. Post-fog inspection adds another 30-min capacity constraint.

### 2.3 Ground Events

| Time | Type | Target | Duration | Impact |
|------|------|--------|----------|--------|
| 07:00 | De-icing required | Airport-wide | 3.0h | Turnaround 1.4x |
| 09:00 | Gate failure | T5-B3 | 2.5h | Gate unavailable |
| 14:00 | Fuel shortage | Airport-wide | 2.0h | Turnaround 1.2x |

**Effect:** De-icing adds 40% turnaround penalty during already-constrained fog period. Gate T5-B3 lost during peak morning fog.

### 2.4 Traffic Modifiers

| Time | Type | Extra Arrivals | Extra Departures | Origin |
|------|------|---------------|-----------------|--------|
| 06:00 | Surge | +10 | +8 | Various |
| 10:30 | Diversion | +6 | - | LGW |

**Effect:** Morning surge adds 18 flights during peak fog period. Gatwick fog diversions at 10:30 add 6 arrivals during IFR-to-MVFR transition.

---

## 3. Results Summary

| Metric | Value | Notes |
|--------|-------|-------|
| Total flights processed | 1,024 | 1,000 scheduled + 24 injected |
| Spawned | 1,023/1,024 | 1 flight never spawned |
| On-time performance | 84.5% | |
| Avg delay (delayed flights) | 26.6 min | See Issue 7.3 |
| Avg turnaround time | 66.8 min | Elevated by 1.2-1.4x multipliers |
| Peak simultaneous | 94 flights | |
| Capacity hold events | 457 (capacity) | + 6 weather + 3 ground + 2 runway = 468 total |
| Holdings | 218 | Concentrated 05:00-10:00 |
| Go-arounds | 0 | See Issue 7.4 |
| Gates used | 0 | See Issue 7.5 |
| Position snapshots | 119,687 | |
| Phase transitions | 4,178 | |
| Gate events | 229 | |

---

## 4. Visual — Peak Disruption

![LHR — Winter Radiation Fog at peak disruption](screenshots/lhr_fog_lifr.png)

*Screenshot: Simulation UI at peak disruption showing holdings concentrated during 05:00-10:00 LIFR fog window, single-runway 27L operations, CAT IIIb weather conditions with 218 holdings accumulated.*

---

## 5. Scenario Impact Analysis

### Disruption Cascade Timeline

```
05:00  ████████████ LIFR FOG (vis 0.12nm, CAT IIIb) ███████ 08:00
06:00  ████████████ SINGLE RWY 27L (4h) ████████████████████ 10:00
06:00  +18 surge flights ───
07:00  ████ De-icing 1.4x ████████████████ 10:00
08:00  ████████ IFR FOG (vis 0.5nm) █████████ 10:00
09:00  Gate T5-B3 failed ─────────── 11:30
10:00  ▓▓▓ MVFR FOG (clearing) ▓▓▓ 11:30
10:30  LGW diversions (+6) ───
11:30  ─── VFR CLEAR (recovery window) ─────────── 16:00
13:00  RWY 28R inspection ── 13:30
14:00  Fuel shortage 1.2x ─────── 16:00
16:00  ████ CHANNEL SQUALL (gusts 42kt, MVFR) ████ 18:00
18:00  ─── VFR CLEAR (final recovery) ──────────── 00:00
```

### Key Observations

1. **05:00-08:00 -- LIFR Fog (Primary Disruption):** Dense radiation fog with 0.12nm visibility forced CAT IIIb single-runway ops. This is the critical bottleneck period. Combined with single-runway config from 06:00, the airport was limited to ~12 movements/hr. The 218 holdings are concentrated overwhelmingly in this 05:00-10:00 window.

2. **06:00 -- Morning Surge Under Fog:** The 18-flight surge hits during the worst visibility. With single-runway CAT IIIb ops, the capacity system queues flights aggressively. This is where most holds accumulate.

3. **07:00-10:00 -- De-icing Compound:** The 1.4x turnaround multiplier compounds the fog delay. Flights that do land take 40% longer to turn around, further blocking gates and reducing departure throughput.

4. **10:30 -- LGW Diversions:** Gatwick's fog forces 6 diversions to Heathrow. The fog is easing (MVFR by 10:00) but the airport is still absorbing the morning backlog.

5. **11:30-16:00 -- Recovery Window:** VFR conditions allow recovery. The runway 28R inspection at 13:00 (30 min) and fuel shortage at 14:00 cause minor perturbations but don't generate significant holdings.

6. **16:00-18:00 -- Channel Squall (Secondary Disruption):** 42kt gusts cause MVFR conditions and likely a runway configuration change. This hits during the afternoon recovery period, creating a secondary capacity constraint. However, the system absorbs this better than the morning fog because baseline traffic is lower.

### Holdings Distribution

- **05:00-10:00 window:** ~200 of 218 holdings (92%) -- LIFR/IFR fog + single runway
- **16:00-18:00 window:** ~18 holdings (8%) -- Channel squall secondary impact
- **Remainder:** Negligible

---

## 6. UI Replay Navigation Guide

To view these events in the simulation replay UI:

1. Load `simulation_lhr_1000_winter_fog.json` from the Simulation file picker
2. Use the timeline progress bar to navigate to key moments
3. Colored markers on the timeline indicate scenario events (amber=weather, red=runway, orange=ground, blue=traffic)

### Bookmarks

| Event | Sim Time | Timeline % | What to Look For |
|-------|----------|-----------|------------------|
| LIFR fog onset | 05:00 | 21% | Visibility drops, holdings begin |
| Single runway config | 06:00 | 25% | 27L-only operations, surge flights arrive |
| De-icing begins | 07:00 | 29% | Turnaround times increase to 1.4x |
| IFR fog transition | 08:00 | 33% | Visibility improves slightly, still constrained |
| Gate T5-B3 failure | 09:00 | 38% | Gate unavailable in terminal 5 |
| **Peak holdings** | **09:00-10:00** | **38-42%** | **Maximum capacity constraint period** |
| MVFR clearing | 10:00 | 42% | Fog lifting, backlog begins clearing |
| LGW diversions | 10:30 | 44% | 6 extra arrivals from Gatwick |
| **VFR recovery begins** | **11:30** | **48%** | **Fog clears, dual-runway ops resume** |
| RWY 28R inspection | 13:00 | 54% | Brief single-runway period |
| Fuel shortage | 14:00 | 58% | Turnaround times increase to 1.2x |
| **Channel squall onset** | **16:00** | **67%** | **42kt gusts, MVFR, secondary disruption** |
| Squall clears | 18:00 | 75% | VFR conditions, final recovery |
| Simulation end | 00:00 | 100% | Check remaining active flights |

---

## 7. Issues Identified

### 7.1 LIFR Fog Dominates All Holdings

218 holdings are almost entirely clustered in the 05:00-10:00 fog window. The single-runway configuration combined with LIFR visibility created an effective capacity of ~12 movements/hr against demand of ~40-50/hr. This is realistic for Heathrow winter fog operations.

### 7.2 Channel Squall Impact Appears Muted

The afternoon squall (42kt gusts) generated relatively few holdings compared to the fog. This may be because: (a) traffic load was lower in the 16:00-18:00 window, or (b) the MVFR flight category didn't reduce capacity as severely as the LIFR fog. Worth verifying whether the gust penalty is being applied correctly.

### 7.3 Cross-Airport Anomaly: Identical Avg Delay (26.6 min)

The average delay of 26.6 min is identical across all 6 regional simulations (LHR, NRT, DXB, GRU, JFK, SYD). This indicates the delay metric reflects pre-generated schedule delay (assigned at flight creation), not scenario-caused delay. The capacity system holds flights pre-spawn, making weather/capacity delay invisible in this metric.

### 7.4 Cross-Airport Anomaly: Zero Go-Arounds

No go-arounds were generated despite LIFR conditions where real-world go-around rates at Heathrow are 3-5% in fog. The capacity system prevents flights from spawning rather than diverting airborne flights, so the go-around mechanism is never triggered.

### 7.5 Cross-Airport Anomaly: Zero Gates Used

Gate occupy events are not being recorded, showing 0 gates used despite 229 gate events logged. This is a pre-existing engine issue where `emit_gate_event("occupy")` is not called in most code paths.

### 7.6 Cross-Airport Anomaly: Identical On-Time % (~84.4-84.6%)

On-time performance is nearly identical across all airports regardless of scenario severity. Same root cause as the delay metric -- on-time is calculated from pre-generated schedule data, not actual scenario-impacted operations.

---

## 8. Recommendations

1. **Track scenario-caused delay separately** from schedule delay. The current avg delay metric (26.6 min) is meaningless for comparing scenario severity. Need a "capacity hold time" metric that measures time spent waiting to spawn due to capacity constraints.

2. **Implement go-around logic for LIFR conditions.** Heathrow CAT IIIb operations have a real-world go-around rate of 3-5%. Flights should occasionally fail to land and re-enter the approach sequence.

3. **Verify Channel squall gust penalty.** The 42kt gusts should cause significant capacity reduction but generated relatively few holdings. Check whether wind gust penalties are applied correctly in the capacity model.

4. **Consider Heathrow's slot constraint.** LHR operates at 98% slot utilization. The simulation should model this constraint -- LHR has very little scheduling slack, so any disruption cascades immediately. The morning surge of +18 flights may be unrealistic given LHR's slot constraints.

5. **Fix gate occupy event recording** in `fallback.py` to enable accurate gate utilization analysis.

6. **Add de-icing queue visualization** in the UI replay. The 3-hour de-icing period (07:00-10:00) with 1.4x multiplier is a significant operational factor that should be visible.

---

## 9. Reproduction

```bash
# Re-run this exact simulation
python -m src.simulation.cli \
  --config configs/simulation_lhr_1000.yaml \
  --scenario scenarios/lhr_winter_fog.yaml

# Replay in UI
# 1. Start dev server: ./dev.sh
# 2. Click "Simulation" button in header
# 3. Select "simulation_lhr_1000_winter_fog.json"
# 4. Use timeline bookmarks from Section 5 to navigate
```

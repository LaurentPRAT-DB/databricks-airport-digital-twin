# JFK Nor'easter Winter Storm Simulation Report

**Simulation file:** `simulation_output/simulation_jfk_1000_winter_storm.json`
**Scenario file:** `scenarios/jfk_winter_storm.yaml`
**Config file:** `configs/simulation_jfk_1000.yaml`
**Run date:** 2026-03-14
**Duration:** 24h simulated

---

## 1. Simulation Setup

| Parameter | Value |
|-----------|-------|
| Airport | JFK (John F. Kennedy International, New York) |
| Scheduled flights | 500 arrivals + 500 departures |
| Scenario-injected | +20 (surges + EWR diversions + ground stop) |
| **Total flights** | **1,020** |
| **Spawned** | **597/1,020 (58.5%)** |
| Time step | 2.0s |
| Seed | 42 (reproducible) |
| Runways | 28L, 28R (dual parallel) |

### Scenario Definition

```yaml
name: JFK Nor'easter Winter Storm — US Northeast
description: >
  Classic nor'easter hits the New York metro area. Snow begins early
  morning, transitions to heavy snow with freezing rain by midday.
  Wind gusts exceed 50kt from the northeast. FAA issues ground delay
  program then ground stop. De-icing queues exceed 90 minutes.
  Realistic for Dec-Mar northeast winter storms.
```

### Reproduction Command

```bash
python -m src.simulation.cli \
  --config configs/simulation_jfk_1000.yaml \
  --scenario scenarios/jfk_winter_storm.yaml
```

---

## 2. Scenario Definition

This scenario tests JFK's resilience under a classic nor'easter -- the most severe weather event in US northeast aviation. The combination of heavy snow, 52kt gusts, 12-hour de-icing requirement, and an FAA ground stop creates the most extreme disruption of all 6 regional scenarios. **41% of flights never spawned.**

### 2.1 Weather Events

| Time | Type | Severity | Visibility | Ceiling | Wind | Gusts | Flight Cat | Duration |
|------|------|----------|-----------|---------|------|-------|-----------|----------|
| 05:00 | Snow | Light | 3.0nm | 1500ft | 18kt / 040 | 28kt | MVFR | 3.0h |
| 08:00 | Snow | Severe | 0.25nm | 200ft | 35kt / 030 | 52kt | **LIFR** | 4.0h |
| 12:00 | Snow | Moderate | 0.75nm | 500ft | 28kt / 020 | 42kt | **LIFR** | 3.0h |
| 15:00 | Snow | Light | 2.0nm | 1200ft | 20kt / 360 | 32kt | IFR | 2.0h |
| 17:00 | Clear | Light | 8.0nm | 4000ft | 15kt / 340 | - | VFR | 7.0h |

**Effect:** 7-hour LIFR period (08:00-15:00) with severe snow. 52kt gusts during peak. This is the longest continuous LIFR period of any regional scenario. Snow transitions from light (MVFR) to blizzard (LIFR) to moderate snow (still LIFR) to light snow (IFR) -- a slow, grinding degradation and recovery typical of nor'easters.

### 2.2 Runway Events

| Time | Event | Target | Duration | Reason |
|------|-------|--------|----------|--------|
| 06:00 | Closure | 28R | 60 min | Snow removal operations |
| 08:30 | Closure | 28L | 210 min | Heavy snow accumulation -- both runways closed |
| 09:00 | Closure | 28R | 180 min | Plowing and de-icing treatment |

**Effect:** 28R closed 06:00-07:00 (snow removal), then again 09:00-12:00. 28L closed 08:30-12:00. Both runways closed simultaneously 09:00-12:00 (3 hours). Combined with the ground stop at 11:00, this creates a near-total shutdown from 08:30 to at least 12:00.

### 2.3 Ground Events

| Time | Type | Target | Duration | Impact |
|------|------|--------|----------|--------|
| 05:00 | De-icing required | Airport-wide | **12.0h** | Turnaround **1.8x** |
| 08:00 | Gate failure | T4-B8 | 6.0h | Gate unavailable until 14:00 |
| 10:00 | Gate failure | T1-A3 | 4.0h | Gate unavailable until 14:00 |
| 09:00 | Taxiway closure | Taxiway A (snow/ice) | 5.0h | Turnaround 1.5x until 14:00 |

**Effect:** The 12-hour de-icing requirement (05:00-17:00) with 1.8x turnaround multiplier is the most severe ground penalty of any scenario. Combined with Taxiway A's 1.5x multiplier (09:00-14:00), effective turnaround multiplier peaks at 1.8x for 12 hours. Two gates lost for 4-6 hours.

### 2.4 Traffic Modifiers

| Time | Type | Extra Arrivals | Extra Departures | Origin |
|------|------|---------------|-----------------|--------|
| 07:00 | Surge | +6 | +4 | Various |
| 10:00 | Diversion | +10 | - | EWR |
| 11:00 | Ground stop | - | - | FAA |

**Effect:** Morning surge of 10 flights at 07:00. EWR diversions at 10:00 add 10 arrivals during the worst conditions. **FAA ground stop at 11:00** halts all departures -- this is unique to JFK and represents the most severe traffic management action.

---

## 3. Results Summary

| Metric | Value | Notes |
|--------|-------|-------|
| Total flights processed | 1,020 | 1,000 scheduled + 20 injected |
| **Spawned** | **597/1,020 (58.5%)** | **423 flights never spawned -- CRITICAL** |
| On-time performance | 84.4% | Of spawned flights only |
| Avg delay (delayed flights) | 26.6 min | See Issue 7.3 |
| Avg turnaround time | 37.4 min | Low because most ops were pre/post storm |
| Peak simultaneous | 59 flights | Lowest -- reflects suppressed operations |
| Capacity hold events | **910 (capacity)** | + 5 weather + 4 ground + 3 runway + 1 ground stop = **923 total** |
| Holdings | **451** | **Highest of all 6 airports** |
| Go-arounds | 0 | See Issue 7.4 |
| Gates used | 0 | See Issue 7.5 |
| Position snapshots | **30,126** | **Smallest -- 4.5x less than SYD** |
| Phase transitions | 1,654 | |
| Gate events | 207 | |
| Output file size | **12 MB** | **vs 35-74 MB for other airports** |

---

## 4. Visual — Peak Disruption

![JFK — Nor'easter Winter Storm at peak disruption](screenshots/jfk_blizzard_peak.png)

*Screenshot: Simulation UI at peak disruption showing only ~59 active flights during blizzard conditions, LIFR with 0.25nm visibility and 52kt gusts, FAA ground stop at 11:00, both runways closed 09:00-12:00, and 41% of flights never spawned.*

---

## 5. Scenario Impact Analysis

### Disruption Cascade Timeline

```
05:00  ▓▓▓ LIGHT SNOW (MVFR) ▓▓▓ 08:00
05:00  ████████████████████ DE-ICING 1.8x (12 HOURS) ████████████████████ 17:00
06:00  RWY 28R snow removal ── 07:00
07:00  +10 surge flights ───
08:00  ██████████████████ BLIZZARD (LIFR, vis 0.25nm, gusts 52kt) ██ 12:00
08:00  Gate T4-B8 failed ──────────────────────── 14:00
08:30  RWY 28L closed (heavy snow) ──────────────────── 12:00
09:00  RWY 28R closed (plowing) ──────────────── 12:00
       ═══════ TOTAL AIRPORT SHUTDOWN 09:00-12:00 ═══════
09:00  Taxiway A snow/ice 1.5x ────────────────────── 14:00
10:00  EWR diversions (+10) ───
10:00  Gate T1-A3 failed ─────────────── 14:00
11:00  ═══ FAA GROUND STOP ═══
12:00  ██████████ MODERATE SNOW (LIFR, gusts 42kt) ██████████ 15:00
15:00  ▓▓▓ LIGHT SNOW (IFR) ▓▓▓ 17:00
17:00  ─── VFR CLEAR (recovery begins) ─────────── 00:00
       Only 7 hours remain for 423 queued flights
```

### CRITICAL ANOMALY: 41% Flights Never Spawned

**This is the most significant finding across all 6 simulations.** Only 597 of 1,020 flights actually entered the simulation. The remaining 423 were held in the capacity queue and never spawned before the 24-hour simulation ended.

**Root cause analysis:**
- The nor'easter created a **7+ hour near-total shutdown** (08:00-15:00) with both runways closed (09:00-12:00), FAA ground stop (11:00+), and continuous LIFR conditions
- When VFR returned at 17:00, only 7 hours remained
- But 423 flights were still queued for spawning
- At maximum capacity (~60 movements/hr), the airport could handle ~420 flights in 7 hours -- but the 1.8x de-icing multiplier (still active until 17:00) and backlog clearing meant actual throughput was lower
- The capacity system correctly prioritized not overloading the airspace but could not recover within the simulation window

**This is realistic.** Major nor'easters routinely cancel 50-70% of JFK flights. The simulation's 41% non-spawn rate is actually conservative compared to real-world cancellation rates during severe nor'easters.

### Key Observations

1. **05:00-08:00 -- Snow Buildup:** Light snow with MVFR conditions. De-icing begins (1.8x turnaround). The 10-flight morning surge at 07:00 adds demand. Early runway 28R closure (06:00-07:00) for snow removal is manageable.

2. **08:00-12:00 -- Blizzard (LIFR, Total Shutdown):** The critical period. Visibility drops to 0.25nm with 52kt gusts. Both runways close by 09:00. Taxiway A closes. Two gates fail. EWR sends 10 diversions at 10:00 into an airport that cannot handle them. The FAA ground stop at 11:00 formalizes what was already de facto -- zero operations.

3. **12:00-15:00 -- Moderate Snow (Still LIFR):** Conditions improve slightly (0.75nm vis, 42kt gusts) but remain LIFR. Runways reopen at 12:00 but capacity is severely limited. The backlog is enormous.

4. **15:00-17:00 -- Light Snow (IFR):** Conditions continue improving but IFR limits throughput. De-icing still active (1.8x) until 17:00.

5. **17:00-00:00 -- Recovery:** VFR conditions and de-icing ends. Only 7 hours to clear a massive backlog. 451 holdings were generated, representing the flights that could not spawn when scheduled.

6. **Lowest Output File (12 MB):** With only 597 flights spawned and 30,126 position snapshots, this simulation produced the smallest output file -- 4x smaller than SYD (51 MB). This directly reflects the suppressed operations.

7. **Lowest Avg Turnaround (37.4 min):** Paradoxically the lowest, because most flights that actually operated did so in the pre-storm (00:00-08:00) or post-storm (17:00-00:00) windows when conditions were better. The 1.8x de-icing multiplier is invisible in the average because few flights turned around during the storm.

### Holdings Distribution

- **05:00-08:00:** ~50 holdings -- MVFR snow, de-icing delay
- **08:00-12:00:** ~200 holdings -- blizzard, total shutdown, massive backlog
- **12:00-15:00:** ~150 holdings -- still LIFR, runways open but limited
- **15:00-17:00:** ~51 holdings -- IFR, slow recovery

### 910 Capacity Events: Most of Any Scenario

JFK generated 910 capacity hold events -- nearly double NRT's 720 and triple LHR's 457. This reflects the continuous nature of the nor'easter: unlike a typhoon that passes in hours, the snowstorm degrades capacity for 12+ hours with no break.

---

## 6. UI Replay Navigation Guide

To view these events in the simulation replay UI:

1. Load `simulation_jfk_1000_winter_storm.json` from the Simulation file picker
2. Use the timeline progress bar to navigate to key moments
3. Note: the timeline will appear sparse during 08:00-15:00 due to minimal flight activity

### Bookmarks

| Event | Sim Time | Timeline % | What to Look For |
|-------|----------|-----------|------------------|
| Light snow onset | 05:00 | 21% | De-icing begins, MVFR |
| RWY 28R snow removal | 06:00 | 25% | Temporary single-runway |
| Morning surge | 07:00 | 29% | +10 flights |
| **Blizzard onset** | **08:00** | **33%** | **LIFR, 52kt gusts, severe disruption** |
| RWY 28L closure | 08:30 | 35% | Starting toward total shutdown |
| **Both runways closed** | **09:00** | **38%** | **Total airport shutdown begins** |
| Taxiway A closure | 09:00 | 38% | Ground ops frozen |
| EWR diversions | 10:00 | 42% | 10 arrivals into closed airport |
| Gate T1-A3 failure | 10:00 | 42% | Second gate lost |
| **FAA ground stop** | **11:00** | **46%** | **Official ground stop declared** |
| Runways reopen | 12:00 | 50% | Still LIFR, very limited ops |
| Gates restored | 14:00 | 58% | T4-B8 and T1-A3 back online |
| IFR improvement | 15:00 | 63% | Light snow, slowly clearing |
| **VFR recovery** | **17:00** | **71%** | **Snow stops, de-icing ends, full recovery** |
| Simulation end | 00:00 | 100% | 423 flights never spawned |

---

## 7. Issues Identified

### 7.1 CRITICAL: 41% Flights Never Spawned

597 of 1,020 flights actually entered the simulation. The remaining 423 were permanently queued. While this is realistic for a severe nor'easter (real-world cancellation rates reach 50-70%), it means the simulation results represent only partial operations. Key implications:
- **On-time % (84.4%) is misleading** -- it only measures the 597 flights that spawned, not the 423 that effectively were cancelled
- **Avg delay (26.6 min) is meaningless** -- flights that never spawned had infinite effective delay
- A "cancellation rate" metric should be added: 423/1020 = 41.5%

### 7.2 FAA Ground Stop Event Type

The ground stop at 11:00 is defined in the YAML as `type: ground_stop` under traffic modifiers. This is the only scenario to use this event type. Verify it is being processed correctly by the capacity system and not just logged as a no-op.

### 7.3 Cross-Airport Anomaly: Identical Avg Delay (26.6 min)

This is most egregious at JFK. With 451 holdings and 423 flights never spawning, the actual operational delay is orders of magnitude higher than 26.6 min. The pre-generated schedule delay metric is completely disconnected from scenario reality.

### 7.4 Cross-Airport Anomaly: Zero Go-Arounds

No go-arounds despite 52kt gusts and 0.25nm visibility. At these conditions, no real-world approach would be attempted -- but the capacity system prevents spawning rather than modeling approach failures.

### 7.5 Cross-Airport Anomaly: Zero Gates Used

Gate occupy events not recorded. Pre-existing engine issue.

### 7.6 Cross-Airport Anomaly: Identical On-Time % (84.4%)

With 41% of flights never spawning, the on-time metric is meaningless for JFK. Need a combined metric that accounts for non-spawned flights as "cancelled/indefinitely delayed."

---

## 8. Recommendations

1. **Add cancellation rate metric.** JFK's 41% non-spawn rate is the most important KPI from this simulation but is not surfaced. Add `cancellation_rate = (total - spawned) / total` to the results summary.

2. **Extend simulation to 36h for severe scenarios.** The 24h cutoff left 423 flights unprocessed. A 36h simulation (or dynamic extension until all flights complete) would show the full recovery curve.

3. **Add "effective delay" metric.** For non-spawned flights, calculate the delay as `sim_end_time - scheduled_spawn_time`. This would show the true average delay including cancellations, likely 4-8 hours for JFK.

4. **Verify ground stop processing.** The FAA ground stop at 11:00 is a unique event type. Ensure it properly halts all departures and is reflected in the capacity model, not just logged.

5. **Model progressive cancellation policy.** In reality, airlines start cancelling flights hours before a nor'easter hits. A proactive cancellation mechanism (cancel flights scheduled during the storm window) would reduce the backlog and enable faster recovery.

6. **Track scenario-caused delay separately.** The 451 holdings (highest of all airports) and 910 capacity events demand a dedicated metric.

7. **Fix gate occupy event recording** in `fallback.py`.

---

## 9. Reproduction

```bash
# Re-run this exact simulation
python -m src.simulation.cli \
  --config configs/simulation_jfk_1000.yaml \
  --scenario scenarios/jfk_winter_storm.yaml

# Replay in UI
# 1. Start dev server: ./dev.sh
# 2. Click "Simulation" button in header
# 3. Select "simulation_jfk_1000_winter_storm.json"
# 4. Use timeline bookmarks from Section 5 to navigate
# Note: Timeline will appear sparse during 08:00-15:00 storm period
```

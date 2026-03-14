# SFO Summer Thunderstorm Simulation Report

**Simulation file:** `simulation_output/simulation_sfo_1000_thunderstorm.json`
**Scenario file:** `scenarios/sfo_summer_thunderstorm.yaml`
**Config file:** `configs/simulation_sfo_1000.yaml`
**Run date:** 2026-03-14
**Duration:** 24h simulated in 31s wall time (2837x real-time)

---

## 1. Simulation Setup

| Parameter | Value |
|-----------|-------|
| Airport | SFO (San Francisco International) |
| Scheduled flights | 500 arrivals + 500 departures |
| Scenario-injected | +30 (surges + OAK diversions) |
| **Total flights** | **1,030** |
| Time step | 2.0s |
| Seed | 42 (reproducible) |
| Runways | 28L, 28R (dual parallel) |

## 2. Scenario Definition

This scenario tests SFO's resilience under cascading disruptions across a full operational day:

### 2.1 Weather Events

| Time | Type | Severity | Visibility | Ceiling | Gusts | Flight Cat | Duration |
|------|------|----------|-----------|---------|-------|-----------|----------|
| 14:00 | Thunderstorm | Moderate | 1.5nm | 800ft | 35kt | **IFR** | 2.5h |
| 18:00 | Fog | Severe | 0.5nm | 200ft | - | **LIFR** | 3.0h |
| 21:00 | Clear | Light | 10.0nm | 5000ft | - | VFR | 3.0h |

**Effect:** Thunderstorm reduces capacity to 45% (IFR + gusts penalty). Fog drops capacity to 30% (LIFR, CAT III single-stream approaches only ~18 arrivals/hour).

### 2.2 Runway Events

| Time | Event | Target | Duration | Reason |
|------|-------|--------|----------|--------|
| 10:30 | Closure | 28R | 45 min | FOD on runway |
| 16:00 | Config change | 28L,28R | 60 min | Wind shift |

**Effect:** 28R closure halves capacity to ~30 arr/hr for 45 minutes during mid-morning.

### 2.3 Ground Events

| Time | Type | Target | Duration | Impact |
|------|------|--------|----------|--------|
| 09:00 | Gate failure | A7 | 4h | Turnaround 1.1x |
| 12:00 | Taxiway closure | Taxiway A (A1-A5) | 2h | Turnaround 1.2x |
| 15:00 | Fuel shortage | Airport-wide | 3h | Turnaround 1.3x |

**Effect:** Progressive turnaround degradation from 1.1x to 1.3x across the day, gate A7 unavailable 09:00-13:00.

### 2.4 Traffic Modifiers

| Time | Type | Extra Arrivals | Extra Departures | Origin |
|------|------|---------------|-----------------|--------|
| 06:00 | Surge | +8 | +7 | Various |
| 08:00 | Surge | +7 | - | Various |
| 11:00 | Diversion | +8 | - | OAK |

**Effect:** Morning surge adds 22 extra flights during peak build. OAK closure diverts 8 flights to SFO at 11:00.

---

## 3. Results Summary

| Metric | Value | Notes |
|--------|-------|-------|
| Total flights processed | 1,030 | 1,000 scheduled + 30 injected |
| On-time performance | 84.6% | |
| Avg delay (delayed flights) | 26.6 min | Max: 113 min |
| Avg turnaround time | 122.9 min | Elevated by 1.1-1.3x multipliers |
| Peak simultaneous | 141 flights | At 16:00 during thunderstorm recovery |
| Capacity hold events | 315 total | 137 arrivals, 178 departures |
| Flights incomplete at sim end | 206 | 191 in approach, 15 in ground phases |
| Position snapshots | 197,620 | |
| Phase transitions | 4,107 | |

---

## 4. Visual — Peak Disruption

![SFO — Summer Thunderstorm at peak disruption](screenshots/sfo_thunderstorm_peak.png)

*Screenshot: Simulation UI at peak disruption showing ~172 active flights at 16:00, thunderstorm and fog event markers on the timeline, IFR weather conditions with arrival and departure holds accumulating.*

---

## 5. Hourly Operations Breakdown

```
Hour  Active  Arr  Dep  Holds(A/D)  Weather     Scenario Event
----  ------  ---  ---  ----------  ----------  -------------------------
00      4      2    2      -/-      VFR
01      7      2    2      -/-      VFR
02     11      3    4      -/-      VFR
03     13      3    2      -/-      VFR
04      9      2    1      -/-      VFR
05     26     11   11      -/-      VFR
06     95     41   40      -/-      VFR         +15 surge flights
07    119     34   35      -/-      VFR
08    148     48   44      -/-      VFR         +7 surge arrivals
09    158     33   32      -/-      VFR         Gate A7 failure (4h)
10    133     17   18      -/-      VFR         RWY 28R closed (45min)
11    138     27   17      -/-      VFR         +8 OAK diversions
12    143     22   20      -/-      VFR         Taxiway A closed (2h)
13    142     19   20      -/-      VFR         Gate A7 restored
14    149     24   24     0/10      IFR TS      THUNDERSTORM onset
15    153     26   24     0/25      IFR TS      Fuel shortage (3h)
16    172     29   34    13/15      IFR TS      RWY config change
17    177     38   33      -/-      VFR         Storm clears, recovery
18    151     18   16    45/46      LIFR FOG    FOG onset (CAT III)
19    140     18   16    36/36      LIFR FOG    Peak congestion
20    126     18   16    22/23      LIFR FOG    Backlog clearing
21    173     60   55    21/23      VFR CLEAR   Fog lifts, surge release
22    130     25   40      -/-      VFR CLEAR   Recovery
23     67      2    1      -/-      VFR CLEAR   Wind down
```

### Key Observations

1. **06:00-09:00 — Morning Build:** Traffic surges add 22 extra flights. Active count ramps from 26 to 158. No capacity issues.

2. **10:30 — Runway 28R FOD Closure:** Capacity halved for 45 minutes. Absorbed without visible holds because traffic is moderate at this hour.

3. **14:00-16:30 — Thunderstorm (IFR):** Capacity drops to 45%. Departure holds appear immediately (10 at hour 14, 25 at hour 15). By 16:00 both arrival and departure holds accumulate (28 total). Active flights peak at 172.

4. **18:00-21:00 — Evening Fog (LIFR):** The worst period. Capacity drops to 30% (~18 arr/hr). **91 holds at 18:00 alone** (45 arrival + 46 departure). Holds remain elevated through 20:00. This is the critical bottleneck.

5. **21:00 — Recovery Surge:** Weather clears to VFR. 60 arrivals and 55 departures released in one hour as the backlog clears. Active count spikes to 173 (near peak). 44 residual holds from the backlog.

---

## 6. UI Replay Navigation Guide

To view these events in the simulation replay UI:

1. Load `simulation_sfo_1000_thunderstorm.json` from the Simulation file picker
2. Use the timeline progress bar to navigate to key moments
3. Colored markers on the timeline indicate scenario events (amber=weather, red=runway, orange=ground, blue=traffic)

### Bookmarks

| Event | Sim Time | Timeline % | What to Look For |
|-------|----------|-----------|------------------|
| Morning surge start | 06:00 | 25% | Rapid increase in active flights |
| Gate A7 failure | 09:00 | 37% | Gate A7 unavailable in gate panel |
| RWY 28R FOD closure | 10:30 | 44% | Single-runway operations |
| OAK diversions arrive | 11:00 | 46% | 8 extra arrivals from OAK |
| Taxiway A closure | 12:00 | 50% | Ground congestion increase |
| **Thunderstorm onset** | **14:00** | **58%** | **Departure holds begin, IFR weather** |
| Fuel shortage | 15:00 | 63% | Turnaround times increase |
| Peak storm impact | 16:00 | 67% | Arrival + departure holds, max congestion |
| **Fog onset (LIFR)** | **18:00** | **75%** | **Worst period: 91 holds, LIFR ops** |
| Peak fog backlog | 19:00 | 79% | 72 holds, constrained operations |
| **Weather clears** | **21:00** | **88%** | **Recovery surge: 115 flights released** |
| Simulation end | 00:00 | 100% | 32 flights still active |

---

## 7. Issues Identified

### 7.1 Scenario System Issues

#### FIXED: Duplicate Phase Transition Recording
- **Severity:** Data quality
- **Description:** Every phase transition was recorded twice — once by the engine's direct detection in `_update_all_flights()` and once by draining the global buffer in `_capture_phase_transitions()`.
- **Impact:** Phase transition count was inflated 2x (7,207 instead of 4,107). Turnaround time calculations and phase analysis were skewed.
- **Fix:** Modified `_capture_phase_transitions()` to only drain the global buffer without re-recording events.
- **File:** `src/simulation/engine.py:685-693`

### 7.2 Pre-existing Engine Issues

#### LOW: Gate Occupy Events Not Recorded
- **Severity:** Data gap
- **Description:** Only 2 gate occupy events recorded for 1,030 flights. Gates are assigned correctly (flights do park at gates), but `emit_gate_event("occupy")` is not called in most code paths within `fallback.py`.
- **Impact:** Gate utilization metrics report only 2 gates used. Actual gate usage is much higher but unrecorded.
- **Where to investigate:** `src/ingestion/fallback.py` — `_create_new_flight()` and `_find_available_gate()` code paths.

#### MEDIUM: 191 Flights Stuck in Approaching Phase
- **Severity:** Simulation accuracy
- **Description:** 191 flights were spawned into `approaching` phase but never progressed to `landing`. 75 of these have no position snapshots at all (disappeared immediately). 116 have brief position data (5-15 minutes) before vanishing from the flight state.
- **Breakdown by spawn hour:**
  - 06:00-09:00: 60 flights (during morning surge — high load)
  - 14:00-16:00: 23 flights (during thunderstorm — capacity constrained)
  - 18:00-20:00: 20 flights (during fog — LIFR)
  - 21:00: 53 flights (recovery surge — sudden release after fog)
- **Root cause hypothesis:** The flight state machine in `fallback.py` may remove approaching flights from `_flight_states` under certain conditions (e.g., no valid waypoints, immediate phase completion). The 15-minute force-advance timer should catch stuck flights but appears to not fire for these.
- **Impact:** ~18% of arrivals never complete their flight path. Over-counts active flights during congested periods.
- **Where to investigate:** `src/ingestion/fallback.py` — `_update_flight_state()` for the `APPROACHING` phase handler.

---

## 8. Capacity Impact Analysis

### Thunderstorm (14:00-16:30) vs Fog (18:00-21:00)

| Metric | Thunderstorm | Fog | Notes |
|--------|-------------|-----|-------|
| Flight category | IFR | LIFR | Fog is more severe |
| Capacity multiplier | 0.45x | 0.30x | |
| Effective arrival rate | ~27/hr | ~18/hr | vs 60/hr VMC |
| Total holds | 63 | 252 | Fog causes **4x more holds** |
| Duration | 2.5h | 3.0h | |
| Recovery time | ~30min | ~1h+ | Fog backlog takes longer to clear |

The fog event at 18:00 is clearly the dominant disruption — it generates 80% of all capacity holds despite being a "simpler" weather event than the thunderstorm, because the LIFR capacity reduction (0.30x) is much more severe than IFR (0.45x), and it hits during the evening push when traffic is still elevated.

### Cascading Effect Timeline

```
09:00  Gate A7 fails ─────────────────────────────────── 13:00 restored
10:30  RWY 28R closed ──── 11:15 reopened
11:00  OAK diversions (+8) ───
12:00  Taxiway A closed ─────────── 14:00 restored
14:00  ████████████████ THUNDERSTORM (IFR, 0.45x) ██████ 16:30
15:00  Fuel shortage ───────────────────── 18:00
16:00  RWY config change ─── 17:00
18:00  ████████████████████ FOG (LIFR, 0.30x) █████████████ 21:00
21:00  RECOVERY ──────────────────────────────────────── 00:00
```

---

## 9. Recommendations for Future Scenarios

1. **Extend simulation to 26-28h** for severe disruption scenarios to allow full recovery. The 24h cutoff left 206 flights incomplete.
2. **Fix gate occupy event recording** in `fallback.py` to enable accurate gate utilization analysis.
3. **Investigate stuck-approaching flights** — the 191 flights that never progressed represent a gap in the flight state machine.
4. **Add go-around logic** — currently no go-arounds are generated even during LIFR conditions where real-world go-around rates would be 5-10%.
5. **Consider delay-by-cause tracking** — separate weather delays from capacity delays from ground delays for more granular analysis.

---

## 10. Reproduction

```bash
# Re-run this exact simulation
python -m src.simulation.cli \
  --config configs/simulation_sfo_1000.yaml \
  --scenario scenarios/sfo_summer_thunderstorm.yaml

# Replay in UI
# 1. Start dev server: ./dev.sh
# 2. Click "Simulation" button in header
# 3. Select "simulation_sfo_1000_thunderstorm.json"
# 4. Use timeline bookmarks from Section 5 to navigate
```

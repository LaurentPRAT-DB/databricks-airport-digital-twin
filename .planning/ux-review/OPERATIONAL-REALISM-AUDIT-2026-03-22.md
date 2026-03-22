# Airport Digital Twin — Operational Realism Audit

**Date:** 2026-03-22
**Airport:** KSFO (San Francisco International)
**Build:** #310
**Method:** API-based systematic testing (~90 seconds of simulation state progression)

---

## Executive Summary

The simulation produces 100 concurrent flights with realistic airline mix (UAL 28%, VRD 11%, SWA 7%) and aircraft types (A320, B738, B777 dominant). Approach speeds and altitudes are realistic (149-183 kts, 240-4882 ft). However, **6 critical gaps** undermine operational credibility:

| # | Gap | Severity | Impact |
|---|-----|----------|--------|
| 1 | All taxi aircraft stationary (0 kts) | **P0** | Taxi movement is visually frozen — no animation |
| 2 | No landing/takeoff/departing phases observed | **P0** | Aircraft teleport between approach→taxi and taxi→enroute |
| 3 | Gate double-booking (10 gates) | **P1** | Multiple aircraft assigned to same gate simultaneously |
| 4 | Turnaround API returns empty for parked flights | **P1** | GSE vehicles never shown, no turnaround progress |
| 5 | Flights with origin = local airport (SFO→SFO) | **P1** | Approaching aircraft can't originate from same airport |
| 6 | Weather data unavailable | **P2** | Weather widget shows "unavailable" |

---

## Detailed Findings

### 1. FLIGHT PHASES & STATE MACHINE

**Phase Distribution (snapshot after 90s of polling):**
```
enroute         40  ████████████████████████████████████████
taxi_in         24  ████████████████████████
taxi_out        20  ████████████████████
parked           8  ████████
approaching      8  ████████
pushback         3  ███
landing          0  (NEVER OBSERVED)
takeoff          0  (NEVER OBSERVED)
departing        0  (NEVER OBSERVED)
```

**Finding 1.1 — Missing transition phases (P0):**
- `landing`, `takeoff`, and `departing` phases were NEVER observed across 40+ polls
- Aircraft appear to teleport: approaching → taxi_in (skipping landing/rollout)
- And: taxi_out → enroute (skipping takeoff roll and initial climb)
- **Real-world:** Landing rollout ~30s, takeoff roll ~20-30s, initial climb visible for ~2-3 min
- **Fix needed:** These phases may exist in code but transition too fast for 2s poll interval, OR they're being skipped entirely

**Finding 1.2 — All taxi aircraft stationary (P0):**
- 44 aircraft in taxi_in/taxi_out phase, ALL showing velocity = 0 kts
- **Real-world:** Taxi speed is 10-25 kts on straights, 5-10 kts on turns
- **Root cause likely:** `_update_flight_state()` not advancing taxi position between polls, or taxi waypoint following is broken
- **Impact:** No visible ground movement — simulation appears frozen to users

**Finding 1.3 — Approach parameters (PASS):**
- Altitude range: 240 - 4,882 ft (realistic for final approach to visual)
- Speed range: 149 - 183 kts (Vref + margin, correct for category C/D)
- Vertical rates: -100 to -800 fpm (realistic for 3-degree glideslope)
- All approaching aircraft correctly airborne (on_ground = false)

**Finding 1.4 — Enroute parameters (PASS):**
- Altitude: 33,554 - 41,876 ft (realistic cruise altitudes)
- Speed: 400 - 499 kts (realistic TAS at cruise, may exceed 250 KIAS below FL100 but these are all high)
- No anomalous vertical rates

### 2. FIDS (Flight Information Display System)

**Finding 2.1 — FIDS populated (PASS with notes):**
- 100 arrivals + 100 departures displayed
- Flight numbers, times, gates, and status all present
- Entries sorted by time

**Finding 2.2 — Parked flights missing from FIDS (P2):**
- 6 parked flights not appearing in FIDS: UAL955, USA8525, UAL7278, EVA472, UAL2484
- These may have arrived before the FIDS window or have different callsign formatting

**Finding 2.3 — Origin airport = local airport (P1):**
- Multiple approaching flights show `origin_airport: "SFO"` — an aircraft approaching SFO cannot have originated from SFO (unless it's a missed approach/go-around, which isn't modeled)
- Example: USA2263 approaching at 3,912ft from SFO, UAL4314 at 3,021ft from SFO
- **Fix:** Arriving flights should always have a different origin than the active airport

**Finding 2.4 — Unfamiliar airport codes (MINOR):**
- Some codes like AGU, AMD, ANF, BJX, BTH are real but uncommon airports
- These are valid IATA codes but unusual for SFO routes (e.g., AGU is Aguascalientes, Mexico)
- Not a bug but affects realism — SFO route network should be weighted toward major hubs

### 3. GATE ALLOCATION

**Finding 3.1 — Double-booked gates (P1):**
- 10 gate conflicts detected:
  - A1: AAL8259 + ANA5955
  - B1: VRD2733 + UAL4742
  - B2: UAL2484 + UAL5856
  - C1: SWA2853 + VRD1327
  - E1: SQC2528 + CCA867 + SWA3292 (TRIPLE!)
  - E3: UAL955 + CCA7311
  - G3: EVA472 + JBU7752
- **Real-world:** Each gate serves exactly one aircraft at a time
- **Root cause:** Gate state tracking not properly preventing assignment when occupied

**Finding 3.2 — Gate API returns empty (P2):**
- `/api/gates` endpoint returns 0 gates (API structure issue — data exists in flights but gate status endpoint is empty)

### 4. TURNAROUND OPERATIONS

**Finding 4.1 — Turnaround API returns empty data (P1):**
- Parked flights queried via `/api/gse/turnaround/{icao24}` return:
  - phase: empty/unknown
  - progress: 0%
  - GSE units: 0
- **Real-world:** A parked aircraft should show its current turnaround phase (deboarding, refueling, catering, boarding, etc.) with active GSE vehicles
- **Impact:** No turnaround animation or progress visible to users

**Finding 4.2 — GSE fleet status endpoint fails (P2):**
- `/api/gse/fleet` returns error or empty data
- Should show equipment inventory: fuel trucks, tugs, belt loaders, etc.

### 5. BAGGAGE SYSTEM

**Finding 5.1 — Baggage stats (PASS):**
- Total bags: 8,750/day — realistic for SFO (~40M pax/year ÷ 365 × 0.8 bags/pax)
- Misconnect rate: 1.9% — within industry range (0.5-3%)
- Avg processing time: 23 min — realistic
- Connecting bags tracked separately

### 6. WEATHER

**Finding 6.1 — Weather unavailable (P2):**
- Weather endpoint returns no data (temp, wind, visibility all N/A)
- Header shows "Weather unavailable"
- **Impact:** No weather-based delay modeling, no METAR data for realism

---

## Gaps Ranked by Impact on Realism

### P0 — Critical (Breaks Illusion)

| # | Gap | Root Cause | Proposed Fix |
|---|-----|-----------|-------------|
| 1 | **Taxi aircraft frozen at 0 kts** | `_update_flight_state()` taxi logic not advancing position per tick | Fix taxi waypoint following to move aircraft along taxiway paths at 10-25 kts each dt tick |
| 2 | **No landing/takeoff/departing visible** | Transitions happen in single tick (too fast for 2s poll) or skipped | Add minimum phase duration: landing ≥ 20s, takeoff ≥ 15s, departing visible for ≥ 60s |

### P1 — Major (Undermines Credibility)

| # | Gap | Root Cause | Proposed Fix |
|---|-----|-----------|-------------|
| 3 | **Gate double-booking** | Gate state not properly checked before assignment | Add gate lock: check `_gate_states` occupancy before assigning, queue if full |
| 4 | **Turnaround returns empty** | Turnaround service not finding flight in `_active_turnarounds` cache | Wire turnaround data from `_flight_states` directly when aircraft is parked |
| 5 | **Origin = local airport** | Route generation assigns SFO as origin for arriving flights | Filter: arriving flight origin must ≠ active airport IATA |

### P2 — Moderate (Reduces Polish)

| # | Gap | Root Cause | Proposed Fix |
|---|-----|-----------|-------------|
| 6 | **Weather unavailable** | Weather service failing (API key? network?) | Check METAR/weather service config, add fallback synthetic weather |
| 7 | **Gate status API empty** | Endpoint may not aggregate from flight states | Populate from `_gate_states` dict in fallback.py |
| 8 | **Parked flights not in FIDS** | FIDS built from schedule generator, not from live state | Cross-reference `_flight_states` parked aircraft into FIDS |
| 9 | **GSE fleet endpoint empty** | Same issue as turnaround — service not wired to live state | Generate fleet from `gse_model.get_fleet_status()` |

### P3 — Minor (Nice to Have)

| # | Gap | Proposed Fix |
|---|-----|-------------|
| 10 | Unfamiliar route codes (AGU, ANF, BTH) | Weight route selection toward top-50 SFO routes from calibration profile |
| 11 | No pushback animation variety | Vary pushback heading (straight-back vs turn-and-push) |
| 12 | Enroute dominates (40/100 = 40%) | Reduce enroute ceiling count or increase local traffic |

---

## What's Working Well

- **Approach realism:** Speeds, altitudes, and descent rates match real ILS approach profiles
- **Airline mix:** Top airlines (UAL, VRD, SWA, AAL, DAL) match SFO's actual carrier distribution
- **Aircraft types:** Narrow/wide body mix reasonable for SFO
- **Pushback:** 3 flights at 0-3 kts with on_ground=true — correct behavior
- **Parked:** All parked aircraft stationary, on_ground=true, altitude 0 — correct
- **Baggage:** Statistics are realistic (8,750 bags, 1.9% misconnect, 23 min processing)
- **FIDS:** 200 entries, sorted by time, with gates, origins/destinations
- **Phase filter (Legend):** New feature working — allows toggling flight phases

---

## Recommended Implementation Order

1. **Fix taxi movement** (P0) — Highest visual impact, aircraft should move along taxiways
2. **Add landing/takeoff minimum duration** (P0) — These phases must be visible
3. **Fix gate double-booking** (P1) — Fundamental data integrity
4. **Fix origin ≠ local airport** (P1) — Easy filter, high credibility impact
5. **Wire turnaround to live state** (P1) — Enables GSE visualization
6. **Fix weather service** (P2) — Check METAR config
7. **Gate status API** (P2) — Wire to flight states
8. **Tune route weighting** (P3) — Use calibration profile top routes

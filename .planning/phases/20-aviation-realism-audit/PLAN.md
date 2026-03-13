# Phase 20: Airplane Rules Validation — Aviation Realism Audit

## Overview

Full review of all movement rules in `src/ingestion/fallback.py` and `src/ingestion/schedule_generator.py` against real aviation regulations (FAA Order 7110.65, ICAO Doc 4444, 14 CFR Part 25, ICAO Annex 14, airline operating manuals).

## Status: Audit Complete — Fixes Pending

---

## 1. Wake Turbulence Categories (Lines 171-192)

| Category | Aircraft |
|----------|----------|
| SUPER | A380 |
| HEAVY | B747, B777, B787, A330, A340, A350 |
| LARGE | A320, A321, A319, A318, B737, B738, B739 |
| SMALL | CRJ9, E175, E190 |

**Verdict: MOSTLY CORRECT, with bugs**

Correct:
- A380 = SUPER (FAA/ICAO special category)
- B747, B777, A330, A340, A350 = HEAVY (MTOW > 300,000 lbs / 136t)
- B787 = HEAVY — correct
- A320 family, B737 family = LARGE — correct

**Bugs:**
- **E190 should be LARGE, not SMALL** — MTOW 51,800 kg (114,200 lbs), well above SMALL threshold of 41,000 lbs. FAA classifies as LARGE.
- **E175 should be LARGE, not SMALL** — MTOW 38,790 kg (85,500 lbs), classified as LARGE by FAA (>41,000 lbs).
- **CRJ9 (CRJ-900) should be LARGE** — MTOW 38,330 kg (84,500 lbs), above SMALL threshold.
- Missing ICAO RECAT-EU categories (FAA uses RECAT A-F at many airports). Legacy 4-category system is older standard — acceptable for simulation.
- Missing "LIGHT" category — ICAO uses LIGHT (not SMALL) for aircraft < 7,000 kg. "SMALL" label doesn't match any standard exactly.

### Separation Matrix

| Your values | FAA 7110.65 (real) | Assessment |
|-------------|-------------------|------------|
| SUPER→SUPER: 4 NM | No published minimum (rare) | Reasonable |
| SUPER→HEAVY: 6 NM | 6 NM | Correct |
| SUPER→LARGE: 7 NM | 7 NM | Correct |
| SUPER→SMALL: 8 NM | 8 NM | Correct |
| HEAVY→HEAVY: 4 NM | 4 NM | Correct |
| HEAVY→LARGE: 5 NM | 5 NM | Correct |
| HEAVY→SMALL: 6 NM | 6 NM | Correct |
| LARGE→LARGE: 3 NM | 2.5 NM (radar minimum) | Slightly conservative |
| LARGE→SMALL: 4 NM | 4 NM | Correct |
| SMALL→SMALL: 3 NM | 2.5 NM (radar minimum) | Slightly conservative |

Overall: Good. Separation values are accurate or conservatively correct.

---

## 2. Taxi Speeds (Lines 199-202)

| Your value | Real standard | Reference | Verdict |
|-----------|--------------|-----------|---------|
| Straight: 25 kts | 20-30 kts typical | ICAO Annex 14 design speed | Correct |
| Turn: 15 kts | 10-15 kts | Operator SOPs | Correct |
| Ramp: 8 kts | 5-10 kts | Ground handling manuals | Correct |
| Pushback: 3 kts | 2-5 kts | Tug speed limitations | Correct |

No gaps. Excellent.

---

## 3. Takeoff Performance (Lines 218-237)

### V-speeds comparison

| Type | Your V1/VR/V2 | Real typical V1/VR/V2 | Verdict |
|------|--------------|----------------------|---------|
| A320 | 130/135/140 | 128-145/130-148/133-150 | Correct range |
| A321 | 135/140/145 | 133-150/138-155/140-158 | Slightly low |
| B737 | 128/133/138 | 126-140/130-145/133-148 | Correct |
| B738 | 132/137/142 | 130-148/135-152/138-155 | Correct |
| B777 | 142/147/152 | 140-160/145-165/148-168 | Low for heavy config |
| B787 | 138/143/148 | 135-155/140-160/143-163 | Low end, acceptable |
| A380 | 150/155/165 | 145-165/150-170/155-175 | Correct |
| E175 | 118/123/128 | 115-130/120-135/123-138 | Correct |

**Gap:** V-speeds are FIXED, but in reality they vary with weight, flap setting, temperature, and altitude. For a simulation this is acceptable. Speeds represent light/medium weight configurations. Heavy international departures (B777 at MTOW) would have V speeds 10-20 kts higher.

### Acceleration rates

| Type | Your accel (kts/s) | Real typical | Verdict |
|------|-------------------|-------------|---------|
| A320 | 2.7 | 2.5-3.5 | Correct |
| A380 | 1.5 | 1.0-2.0 | Correct |
| E175 | 3.3 | 3.0-4.0 | Correct |

### Initial climb rates

| Type | Your rate (fpm) | Real typical | Verdict |
|------|----------------|-------------|---------|
| A320 | 2300 | 2000-3000 | Correct |
| B777 | 1900 | 1500-2500 | Correct |
| A380 | 1400 | 1000-2000 | Correct |
| E175 | 3000 | 2500-4000 | Correct |

---

## 4. Departure Wake Separation (Lines 240-248)

| Your values (seconds) | FAA 7110.65 5-8-1 | Verdict |
|----------------------|-------------------|---------|
| SUPER→any: 180s | 3 min (180s) | Correct |
| HEAVY→HEAVY: 120s | 2 min (120s) | Correct |
| HEAVY→LARGE: 120s | 2 min (120s) | Correct |
| HEAVY→SMALL: 120s | 2 min (120s) | Correct |
| LARGE→SMALL: 120s | 2 min (120s) | Correct |
| Default: 60s | 1 min typical same-category | Correct |

**Perfect match to FAA 7110.65.**

---

## 5. Approach Path / ILS (Lines 457-493)

| Fix | Distance from threshold | Your altitude | Standard 3deg glideslope | Verdict |
|-----|------------------------|--------------|-------------------------|---------|
| IAF | ~15 NM | 6000 ft | 4500-6000 ft | Correct |
| | ~12 NM | 5000 ft | ~3800 ft at 3deg | High by ~1200 ft |
| IF | ~10 NM | 4000 ft | ~3200 ft at 3deg | High by ~800 ft |
| | ~8 NM | 3200 ft | ~2500 ft at 3deg | High by ~700 ft |
| FAF | ~5 NM | 2500 ft | ~1600 ft at 3deg | HIGH by ~900 ft |
| | ~4 NM | 1800 ft | ~1300 ft at 3deg | High by ~500 ft |
| GS intercept | ~3 NM | 1000 ft | ~950 ft at 3deg | Close |
| | ~2.5 NM | 650 ft | ~790 ft at 3deg | Close |
| Short final | ~1 NM | 300 ft | ~318 ft at 3deg | Correct |
| | ~0.5 NM | 150 ft | ~159 ft at 3deg | Correct |
| Threshold | 0 | 15 ft | 50 ft (TCH) | Low — should be 50 ft |

**Gaps:**
- Altitudes are too high early in the approach — doesn't follow standard 3deg glideslope. Uses steeper step-down approach initially, then flattens to approximately correct on short final. Semi-realistic (step-down approaches exist) but doesn't match a standard ILS precision approach.
- **Threshold crossing height should be 50 ft, not 15 ft** — 14 CFR 97.3 and ICAO define TCH as 50 ft (15m) for ILS CAT I. 15 ft is touchdown zone altitude, which should be 0 ft.
- **Missing standard approach speeds** — No Vref/Vapp speeds used. Approach speed is `180 - (waypoint_index * 20)` (line 1652), giving 180→100 kts. Real Vref speeds:
  - A320: 130-140 kts
  - B777: 145-155 kts
  - A380: 140-150 kts
  - E175: 125-135 kts
  - Formula gives incorrect speeds: too fast initially (180 kts at waypoint 0 is correct for initial approach) but potentially too slow at final (100 kts for 4+ waypoints is below stall speed for most types).

---

## 6. Departure Path (Lines 504-515)

| Point | Your altitude | Typical SID | Verdict |
|-------|--------------|------------|---------|
| Rotation | 500 ft | ~35 ft (screen height) | Way too high |
| 2 NM out | 2000 ft | 800-1200 ft | High |
| 4 NM out | 4000 ft | 1500-2500 ft | High |
| 10 NM out | 8000 ft | 4000-6000 ft | High |
| 15 NM out | 12000 ft | 8000-10000 ft | Reasonable |

**Gap:** Initial departure altitudes are too high. At 500 ft the aircraft has barely lifted off. First waypoint should be ~200-400 ft. Aggressive climb profile doesn't account for noise abatement procedures that require reduced climb rates in many SIDs.

---

## 7. Flight Phase Model (Lines 821-831)

| Your phase | Real equivalent | Verdict |
|-----------|----------------|---------|
| APPROACHING | Approach (vectors/IAP) | Correct |
| LANDING | Final approach + touchdown | Correct |
| TAXI_TO_GATE | Taxi-in | Correct |
| PARKED | Gate/stand operations | Correct |
| PUSHBACK | Pushback | Correct |
| TAXI_TO_RUNWAY | Taxi-out | Correct |
| TAKEOFF | Takeoff roll + initial climb | Correct |
| DEPARTING | Departure climb | Correct |
| ENROUTE | Cruise/enroute | Correct |

**Missing phases:**
- **HOLDING** — No holding pattern phase. When approach is full, aircraft do lazy orbit (`heading += 2 * dt`) instead of proper racetrack holding pattern at a published fix. Real holding uses 1-minute legs with standard turns.
- **GO-AROUND / MISSED APPROACH** — No mechanism for landing abort. Real ops have ~1-3% go-around rate.
- **DE-ICING** — In winter ops, de-icing adds 5-20 minutes before departure.
- **RUNWAY CROSSING** — At airports with crossing runways (like SFO), aircraft must stop and receive clearance to cross active runways during taxi.

---

## 8. Ground Operations (Lines 1816-1871)

### Gate turnaround time

| Your value | Real typical | Reference | Verdict |
|-----------|-------------|-----------|---------|
| 300-600s (5-10 min) | 25-90 min (narrow: 25-45, wide: 60-90) | Airline ground handling manuals | **WAY TOO SHORT** |

**Major gap:** 5-10 minutes at gate is unrealistic. Even a quick turnaround (Southwest-style) takes 25-35 minutes. International wide-body flights take 60-120 minutes. **This is the most significant realism gap.**

### Gate cooldown

| Your value | Real typical | Verdict |
|-----------|-------------|---------|
| 60s | 5-10 min | Too short (but functional) |

### Pushback

- Pushback heading logic (toward nearest taxiway node): correct
- Nose facing opposite of movement direction: correct (tail-first)
- Pushback speed 3 kts: correct
- Pushback duration: `phase_progress += dt * 0.1`, completes at 1.0, so ~10 seconds. Real pushback takes 3-5 minutes. **TOO SHORT.**

---

## 9. Enroute Behavior (Lines 2057-2141)

| Parameter | Your value | Real typical | Verdict |
|-----------|-----------|-------------|---------|
| Cruise speed | 400-500 kts | 440-490 kts (M0.78-M0.85) | Correct |
| Cruise altitude | 8,000-25,000 ft | 28,000-43,000 ft | **WAY TOO LOW** |
| Climb rate enroute | 500 ft/min | 500-2000 ft/min | Low end, OK |
| Turn rate | 3deg/s max | Standard rate = 3deg/s | Correct |
| Exit radius | 0.5deg (~30 NM) | N/A (sim boundary) | Reasonable |

**Major gap:** Cruise altitudes are dramatically too low. International flights cruise at FL350-FL430 (35,000-43,000 ft). Domestic flights at FL280-FL390. The 8,000-15,000 ft domestic / 15,000-25,000 ft international altitudes are climb-phase altitudes, not cruise.

---

## 10. Schedule Generator (schedule_generator.py)

### Delay rate

| Your value | Real BTS data | Verdict |
|-----------|--------------|---------|
| 15% delayed | 20-25% (BTS: ~21% > 15 min) | Slightly low |

### Peak hour patterns

| Period | Your flights/hr | SFO real (~450k ops/yr) | Verdict |
|--------|----------------|------------------------|---------|
| Peak (6-10, 16-20) | 18-25 | 25-35 | Low |
| Midday | 10-15 | 15-25 | Low |
| Night (23-5) | 0-3 | 0-5 (SFO curfew) | Correct |

### Airline weights

United at 35% for SFO hub: Correct (United has ~46% of SFO operations, so 35% is reasonable).

---

## 11. Missing Physics / Regulations

### Critical omissions

| Missing rule | Reference | Impact |
|-------------|-----------|--------|
| Wind effects on approach/departure | FAA 7110.65 3-1-4 | No crosswind, headwind, or tailwind affecting speeds/headings. Runway selection depends on wind. |
| Stabilized approach criteria | Airline SOPs, FAA AC 120-71A | No check for stabilized approach (on speed, on glidepath, configured by 1000 ft AGL) |
| Landing rollout distance | 14 CFR 25.125 | Landing just zeroes altitude — no deceleration on runway. Real aircraft need 2000-5000 ft to stop. |
| Flap/gear configuration | 14 CFR 25.107 | No flap settings affecting approach/departure speeds |
| Speed restrictions below 10,000 ft | 14 CFR 91.117 | 250 knots maximum below 10,000 ft MSL — not enforced |
| Noise abatement procedures | SFO TRACON | SFO has specific noise abatement departure procedures (e.g., QUIET BRIDGE) — not modeled |
| RNAV/GPS approaches | FAA 8260.58A | Only ILS approach modeled. Modern airports use RNAV extensively. |
| Simultaneous parallel approaches | FAA 7110.65 5-9 | SFO 28L/28R closely spaced parallels requiring special procedures — not modeled |

---

## Summary Scorecard

| Category | Score | Notes |
|----------|-------|-------|
| Wake turbulence categories | 7/10 | E175, E190, CRJ9 misclassified as SMALL |
| Approach separation distances | 9/10 | Accurate to FAA 7110.65 |
| Departure separation timing | 10/10 | Perfect match |
| Taxi speeds | 10/10 | Spot on |
| Takeoff V-speeds | 8/10 | Reasonable but fixed (no weight variation) |
| Takeoff performance | 8/10 | Good sub-phase model |
| Approach profile geometry | 6/10 | Too high early, TCH wrong, no Vref |
| Departure profile | 6/10 | Initial altitudes too high |
| Ground ops timing | 3/10 | Turnaround 5-10 min vs real 25-90 min |
| Cruise altitudes | 3/10 | 8-25K ft vs real 28-43K ft |
| Flight phases | 7/10 | Missing holding, go-around, de-icing |
| Wind/weather integration | 2/10 | Weather generated but not affecting operations |
| Speed restrictions | 4/10 | 250 kts below FL100 not enforced |

---

## Prioritized Fix List

### P0 — Quick Wins (high impact, low effort)
1. **Fix wake turbulence categories** — Move E175, E190, CRJ9 from SMALL to LARGE
2. **Fix cruise altitudes** — Domestic: 28,000-39,000 ft, International: 35,000-43,000 ft
3. **Fix threshold crossing height** — Change 15 ft to 50 ft
4. **Enforce 250 kts below FL100** — Add speed cap in approach/departure logic

### P1 — Medium Effort (significant realism improvement)
5. **Fix ground ops timing** — Turnaround: 25-45 min narrow-body, 60-90 min wide-body. Pushback: 3-5 min.
6. **Fix departure profile altitudes** — Lower initial waypoints to match realistic climb gradients
7. **Fix approach profile** — Align early waypoints to 3deg glideslope
8. **Add type-specific Vref speeds** — Replace linear formula with per-type approach speed tables

### P2 — Larger Features (future phases)
9. Add proper racetrack holding patterns
10. Add go-around / missed approach logic
11. Add wind effects on operations
12. Add landing rollout deceleration
13. Add stabilized approach criteria

# Operational Review: Simulation vs Reality Gap Analysis

**Date:** 2026-03-22
**Airport tested:** KSFO (SFO) sim replay + KDFW live feed
**Reviewer:** Claude Code (airport ops perspective)

---

## Executive Summary

The simulation demonstrates solid fundamentals: realistic Vref/V-speeds per aircraft type, FAA-compliant speed restrictions (250kts < FL100), proper wake turbulence separation, and BTS-calibrated turnaround/taxi times. However, several gaps would be immediately obvious to an airport operator. The most critical are: (1) taxi routing uses fallback waypoints instead of real taxiway paths, (2) gate status panel doesn't sync during simulation replay, (3) all departures use hardcoded runway "28R" regardless of wind/traffic, and (4) turnaround sub-phase timing isn't validated against actual aircraft position.

---

## Phase-by-Phase Assessment

### 1. APPROACH (Arriving Traffic)

**What's realistic:**
- Vref speeds per aircraft type from manufacturer data (A320: 133kts, B777: 149kts, A380: 145kts)
- Smooth deceleration from 180kts to Vref across waypoints
- 3 NM minimum approach separation (FAA 7110.65 standard)
- Wake turbulence category-based separation (HEAVY behind SUPER = larger gap)
- Speed reduction when closing on aircraft ahead (realistic sequencing behavior)
- Max 8 aircraft on approach simultaneously (realistic for single-direction ops)
- Vertical rates: -800 fpm > 500ft above target, -400 fpm > 100ft, -200 fpm close — reasonable stepped profile
- Holding pattern when runway busy: FAA standard racetrack (1-min legs, 3 deg/s standard rate turns)
- Origin-aware approach: approach bearing starts from the direction of the origin airport

**Gaps found:**

| # | Gap | Severity | Real-World Behavior |
|---|-----|----------|-------------------|
| A1 | **No ILS/visual approach procedure** — aircraft follow generic waypoints, not published approach plates (ILS 28L/28R at SFO = 3-degree glideslope from FAF at ~5.5 NM) | HIGH | Real aircraft intercept localizer at 3000ft, follow 3-degree glidepath. Sim uses `_move_toward()` with fixed speed_factor |
| A2 | **Approach waypoints are origin-rotated copies of the same template** — not actual STAR routes (SERFR, BDEGA, DYAMD for SFO) | MEDIUM | Real SFO has distinct STARs from different directions with specific altitude/speed constraints |
| A3 | **No go-around execution** — event label "go_around" appears in sim events but aircraft don't actually fly a missed approach procedure | MEDIUM | Real go-around: full thrust, pitch up, climb to missed approach altitude, follow published procedure |
| A4 | **Altitude noise ±200ft on approach** — `random.uniform(-200, 200)` on each tick is excessive, creates jittery altitude not seen in real ILS | LOW | Real ILS approach: altitude deviation < ±50ft on stable approach |
| A5 | **No wind correction** — aircraft heading = direct bearing to waypoint, no crab angle for crosswind | LOW | Real aircraft crab into wind, de-crab on short final |

### 2. LANDING (Touchdown & Rollout)

**What's realistic:**
- Deceleration from approach speed to 30kts on rollout (realistic braking)
- Altitude descends to 0 (ground level)
- Runway occupancy tracking (single-aircraft exclusion)
- Staggered runway exit positions to prevent gridlock

**Gaps found:**

| # | Gap | Severity | Real-World Behavior |
|---|-----|----------|-------------------|
| L1 | **No flare model** — aircraft descend at 500 ft/min constant rate until alt=0, then instantly on ground | MEDIUM | Real: flare at ~30ft, rate reduces to ~100-200 fpm at touchdown, nose pitch up |
| L2 | **No touchdown zone** — landing anywhere along runway, no aim point | LOW | Real: touchdown zone markings 1000ft from threshold, pilots aim for 1000-1500ft mark |
| L3 | **Instant transition from LANDING to TAXI_TO_GATE** — no rollout/deceleration on runway | HIGH | Real: ~30-45 second rollout on runway before reaching exit speed (60kts for high-speed exit) |
| L4 | **Landing velocity can go to 30kts in air** — deceleration starts before touchdown | MEDIUM | Real: deceleration only begins after touchdown + spoiler deployment + reverse thrust |

### 3. TAXI-IN (Runway to Gate)

**What's realistic:**
- 30 kts taxi speed (25 base + 5 arrival priority) — realistic for inbound taxi
- Taxi separation checks between aircraft (~60m minimum)
- OSM taxiway graph attempted first, with apron-aware fallback
- Deferred gate assignment when all gates full (realistic — aircraft hold on taxiway)

**Gaps found:**

| # | Gap | Severity | Real-World Behavior |
|---|-----|----------|-------------------|
| T1 | **Fallback taxi routes are 3-5 straight-line waypoints** — not actual taxiway paths | HIGH | Real: aircraft follow named taxiway segments (Alpha, Bravo, Charlie) with turns at intersections. SFO has complex taxiway network. |
| T2 | **No runway crossing clearance** — taxi routes may cross active runways without stopping | HIGH | Real: ATC gives explicit runway crossing clearance, aircraft hold short at hold lines |
| T3 | **Ramp speed same as taxiway speed** — `TAXI_SPEED_RAMP_KTS` used for final approach to gate | LOW | Real: ramp area speed limit typically 10-15 kts, with ground marshaller guidance |
| T4 | **No gate turn-in animation** — aircraft teleports to final parked position/heading | MEDIUM | Real: aircraft makes a 90-degree turn into the gate, follows centerline markings, marshaller signals |

### 4. PARKED (Gate Operations & Turnaround)

**What's realistic:**
- Critical-path turnaround scheduling with proper dependencies (e.g., boarding after cleaning+catering)
- Per-aircraft-type timing (narrow body ~45 min, wide body ~90 min)
- Airline-specific turnaround factors
- Weather and congestion multipliers
- Jitter (±10%) on each sub-phase
- Gate standoff positioning (aircraft nose offset from terminal)
- Parked heading computed from terminal geometry

**Gaps found:**

| # | Gap | Severity | Real-World Behavior |
|---|-----|----------|-------------------|
| G1 | **Turnaround sub-phase visible even when aircraft hasn't arrived** — FIDS/API shows "unloading 90%" for aircraft that was still on approach (observed: OTH1379 approaching showed baggage "100% delivered") | CRITICAL | Real: turnaround phases only start after aircraft is chocked at gate |
| G2 | **Gate Status panel shows 0 occupied during simulation replay** — despite 8-13 parked flights visible in flight list | HIGH | Real: AODB gate status always reflects actual occupancy |
| G3 | **No jetbridge/ground power connection animation** — parked aircraft just sit static | LOW | Real: visible jetbridge movement, GPU connection, belt loaders approaching |
| G4 | **GSE fleet status not linked to turnaround** — `/api/gse/status` shows zero `assigned_flight` at fleet level even when turnarounds are active | MEDIUM | Real: GSE dispatch system tracks every vehicle assignment |

### 5. PUSHBACK

**What's realistic:**
- Pushback speed 3 kts (realistic tug speed)
- Phase transition from PARKED to PUSHBACK after turnaround complete
- Gate release event emitted

**Gaps found:**

| # | Gap | Severity | Real-World Behavior |
|---|-----|----------|-------------------|
| P1 | **No pushback direction model** — aircraft doesn't push back on a specific path | MEDIUM | Real: pushback onto specific taxiway, nose pointed toward departure direction |
| P2 | **No engine start sequence** — instant transition to taxi after pushback | LOW | Real: engines started during pushback, idle check ~30 seconds |

### 6. TAXI-OUT (Gate to Runway)

**What's realistic:**
- 25 kts straight taxi speed (FAA standard)
- Calibrated departure queue hold at runway (BTS taxi-out mean match)
- Wake turbulence departure separation (FAA 7110.65 5-8-1)
- Runway occupancy check before entering

**Gaps found:**

| # | Gap | Severity | Real-World Behavior |
|---|-----|----------|-------------------|
| D1 | **Hardcoded departure runway "28R"** — ignoring wind direction and traffic | CRITICAL | Real: runway assignment based on wind (ATIS), noise abatement, traffic flow. SFO uses 28L/28R for arrivals and 01L/01R for departures in some configs |
| D2 | **No runway selection model** — all aircraft depart from same runway regardless of gate location | HIGH | Real: gate in Terminal 3 → likely 28R; Terminal 1 → might get 01L. Intersection departures for short-haul |
| D3 | **Same fallback waypoints for all departure gates** — all departures follow identical taxi path | HIGH | Real: taxi route depends on gate position. A gate at Terminal A follows different taxiways than Terminal G |
| D4 | **Departure queue is a timer, not spatial** — aircraft holds in place rather than queuing behind others | MEDIUM | Real: visible queue at runway hold point, aircraft lined up sequentially |

### 7. TAKEOFF

**What's realistic:**
- Aircraft-specific V1/Vr/V2 speeds from 14 CFR 25.107 (A320: 130/135/140, B777: 142/147/152)
- Aircraft-specific acceleration rates and climb rates
- Sub-phase model: lineup (3s) → roll → rotate → liftoff → initial climb
- Runway centerline tracking during roll
- Runway length constraint (position interpolated along runway geometry)
- Noise abatement: no turns below 400ft
- Runway released at 500ft AGL

**Gaps found:**

| # | Gap | Severity | Real-World Behavior |
|---|-----|----------|-------------------|
| TO1 | **Aircraft snaps to runway start** — teleports from hold line to runway threshold | MEDIUM | Real: aircraft taxies onto runway, lines up with centerline (takes ~15-20 seconds) |
| TO2 | **No reduced thrust / flex takeoff** — always uses max performance data | LOW | Real: airlines use reduced thrust ~80% of the time to save engine life |

### 8. DEPARTURE (Climb-Out)

**What's realistic:**
- 250 kts below 10,000ft (14 CFR 91.117 compliant)
- Acceleration above 10,000ft (350 kts initially)
- Destination-aware departure heading/waypoints
- Climb to FL180 before ENROUTE transition
- 1500 fpm initial climb rate, 2000 fpm above waypoints

**Gaps found:**

| # | Gap | Severity | Real-World Behavior |
|---|-----|----------|-------------------|
| DEP1 | **No SID (Standard Instrument Departure)** — generic waypoints instead of published procedures (SFO: SSTIK, SAHEY, TRUKN departures) | MEDIUM | Real: ATC assigns specific SID based on destination and traffic. SIDs have mandatory altitude/speed constraints |
| DEP2 | **Flat speed profile** — 200 + waypoint_index * 50, not realistic acceleration curve | LOW | Real: climb schedule varies by airline/aircraft, typical: 250kts to FL100, 280-300kts to FL250, then Mach |
| DEP3 | **All departures at same speed regardless of altitude** — no Mach transition | LOW | Real: aircraft switch from IAS to Mach number around FL250-FL280 |

### 9. ENROUTE (Cruise)

**What's realistic:**
- Cruise altitudes 34,000-39,000 ft (realistic FL range)
- Cruise speeds 400-500 kts (realistic TAS range)
- Progressive descent starting ~30 NM from airport
- Speed envelope: 250kts < FL100, 210kts < 5000ft, 180kts < 3000ft

**Gaps found:**

| # | Gap | Severity | Real-World Behavior |
|---|-----|----------|-------------------|
| E1 | **76% of flights are enroute** — overwhelming the view with cruise traffic that an airport operator wouldn't see | HIGH | Real: AODB/tower only tracks aircraft within ~50NM. Enroute traffic managed by ARTCC, not airport |
| E2 | **No step climbs** — aircraft maintain constant altitude during cruise | LOW | Real: airlines request step climbs as fuel burns off |
| E3 | **Random altitude assignment** — not based on direction-of-travel (odd/even FL rule) | LOW | Real: eastbound = odd FL (350, 370, 390), westbound = even FL (340, 360, 380) |

### 10. FIDS (Flight Information Display)

**What's realistic:**
- Shows flight number, airline, origin/destination, gate, scheduled/estimated times
- Delay reasons (weather, ATC, late inbound, aircraft defect)
- Status categories (on_time, delayed, arrived, departed)

**Gaps found:**

| # | Gap | Severity | Real-World Behavior |
|---|-----|----------|-------------------|
| F1 | **No carousel assignment for arrivals** — FIDS should show baggage carousel number | MEDIUM | Real: "Flight UAL1520 from LAX — Baggage at Carousel 4" |
| F2 | **No boarding status progression** — no "Boarding", "Final Call", "Gate Closed" status | MEDIUM | Real: FIDS shows boarding progress for departures |
| F3 | **Delay minutes shown but no updated ETA/ETD** — estimated times don't always reflect delay | LOW | Real: estimated time = scheduled + delay |

### 11. BAGGAGE

**What's realistic:**
- Per-flight bag count, processing time, connecting bags
- Misconnect rate tracking (1.93%)
- Delivery percentage

**Gaps found:**

| # | Gap | Severity | Real-World Behavior |
|---|-----|----------|-------------------|
| B1 | **Baggage "100% delivered" for approaching aircraft** — observed on OTH1379 while still airborne | CRITICAL | Real: baggage delivery only possible after aircraft arrives, unloads, and bags reach carousel |
| B2 | **Misconnect rate 1.93% is high** — industry standard is <1% for major US carriers | LOW | Real: SFO targets <0.5% misconnect rate |
| B3 | **No BHS routing visualization** — bags are statistical only, no physical path through conveyor system | LOW | Real: BHS has specific routing through sorters, EBS, belt systems |

### 12. PERFORMANCE / UX

| # | Gap | Severity | Notes |
|---|-----|----------|-------|
| UX1 | **FCP 19.7s, LCP 27.8s** — very slow initial load | HIGH | Target: FCP < 2s, LCP < 4s |
| UX2 | **Simulation replay auto-starts on page load** — overrides live feed | MEDIUM | User didn't request sim; should stay on live data |
| UX3 | **Flight list clicks unresponsive during sim replay at 60x** — can't interact with UI | MEDIUM | Should remain interactive regardless of playback speed |

---

## Severity Summary

| Severity | Count | Examples |
|----------|-------|---------|
| CRITICAL | 3 | G1 (turnaround before arrival), D1 (hardcoded runway), B1 (baggage before landing) |
| HIGH | 7 | T1 (taxi routes), L3 (no rollout), G2 (gate panel desync), D2/D3 (runway/route selection), E1 (enroute clutter), UX1 (load time) |
| MEDIUM | 11 | A1, A2, L2, L4, T4, G4, P1, D4, TO1, F1, F2 |
| LOW | 11 | A4, A5, T3, G3, P2, TO2, DEP2, DEP3, E2, E3, B2 |

---

## Improvement Plan

### Phase 1 — Critical Fixes (1-2 weeks)

**1.1 Fix turnaround/baggage temporal coherence (G1, B1)**
- Turnaround sub-phases must NOT start until aircraft phase == PARKED
- Baggage status must be "Pending" or "Not arrived" until aircraft is TAXI_TO_GATE or PARKED
- The API endpoint that generates turnaround status should check `flight_phase` before returning phase progress
- **Files:** `app/backend/routes/flights.py` (turnaround endpoint), `app/backend/routes/baggage.py`

**1.2 Multi-runway operations (D1, D2)**
- Use OSM runway data (already fetched) to select departure runway based on:
  - Wind direction from METAR (already available in header)
  - Gate proximity (minimize taxi distance)
  - Current runway assignment config (28L/28R arr, 28R/01L dep for SFO)
- Remove hardcoded "28R" references in fallback.py
- **Files:** `src/ingestion/fallback.py` (runway selection functions), `src/simulation/capacity.py`

**1.3 Gate status sync in simulation replay (G2)**
- The sim replay mode sends position snapshots but doesn't update gate occupancy
- `useSimulationReplay.ts` should track parked flights and update gate context
- **Files:** `app/frontend/src/hooks/useSimulationReplay.ts`, `app/frontend/src/context/FlightContext.tsx`

### Phase 2 — High-Impact Improvements (2-4 weeks)

**2.1 OSM taxiway graph routing for all airports (T1, D3)**
- The `TaxiwayGraph` exists in `src/routing/taxiway_graph.py` but falls back to straight-line waypoints frequently
- Improve graph construction to handle more OSM taxiway topologies
- Add runway crossing hold points (T2) where taxi routes cross active runways
- **Files:** `src/routing/taxiway_graph.py`, `src/ingestion/fallback.py` (taxi functions)

**2.2 Landing rollout phase (L3)**
- Add intermediate phase between LANDING and TAXI_TO_GATE: deceleration on runway from touchdown to 60kts exit speed
- Aircraft should visibly roll down runway before turning onto taxiway exit
- Integrate with staggered exit position system already in place
- **Files:** `src/ingestion/fallback.py` (LANDING phase handler)

**2.3 Reduce enroute clutter (E1)**
- Airport operators only see traffic within ~50NM. Options:
  - Filter enroute flights beyond 30NM from display
  - Reduce enroute spawn ratio (currently 50% of flights are enroute)
  - Add a "local traffic only" filter toggle
- **Files:** `src/ingestion/fallback.py` (spawn weights), frontend filtering

**2.4 Frontend performance (UX1)**
- Profile the 19.7s FCP — likely caused by loading 3D assets (Three.js 916KB) + Leaflet (297KB) on initial render
- Lazy-load 3D view, code-split map components
- **Files:** `app/frontend/src/App.tsx`, Vite config

### Phase 3 — Realism Enhancements (4-8 weeks)

**3.1 Published approach/departure procedures (A1, A2, DEP1)**
- Replace generic waypoints with real SFO procedures:
  - ILS 28L/28R: 3-degree glide slope, localizer intercept at ~3000ft, FAF at 5.5 DME
  - STARs: SERFR (from south), BDEGA (from north), DYAMD (from east)
  - SIDs: SSTIK (south), SAHEY (north), TRUKN (east)
- Store procedures as JSON per airport, load alongside OSM data
- **Files:** new `data/procedures/` directory, `src/ingestion/fallback.py`

**3.2 Pushback and gate movement realism (P1, T4, TO1)**
- Pushback: compute pushback direction based on gate orientation and nearest taxiway
- Gate turn-in: animate the 90-degree turn from taxiway to gate parking position
- Takeoff lineup: taxi onto runway from hold line instead of teleporting
- **Files:** `src/ingestion/fallback.py` (PUSHBACK, TAXI_TO_GATE, TAKEOFF handlers)

**3.3 FIDS boarding progression (F1, F2)**
- Add status: "Boarding" (30 min before departure) → "Final Call" (10 min) → "Gate Closed" (5 min)
- Add carousel assignment for arrivals
- **Files:** `src/ingestion/schedule_generator.py`, frontend FIDS components

**3.4 Altitude rule compliance (E3)**
- Implement hemispheric rule: eastbound flights (000-179 heading) → odd FL, westbound → even FL
- Apply during ENROUTE altitude assignment
- **Files:** `src/ingestion/fallback.py` (ENROUTE phase)

### Phase 4 — Advanced Features (8+ weeks)

**4.1 Flare model and touchdown physics (L1)**
- Implement flare at 30ft RA: reduce descent rate from -700 fpm to -100 fpm
- Add spoiler deployment, reverse thrust, autobrake modeling
- Visual: nose pitch up during flare, main gear touchdown first

**4.2 Wind-based operations (A5)**
- Use METAR wind direction/speed to compute crab angles on approach
- Dynamic runway configuration changes (e.g., SFO switches 28→01 in strong south wind)

**4.3 Real-time ATC sequencing**
- Implement TRACON-like approach sequencing: miles-in-trail, merge point, speed control
- Departure sequencing: EDCT compliance, ground stop events

---

## Quick Wins (can implement today)

1. **B1/G1 fix:** Add a guard in the turnaround/baggage API: if flight is not PARKED, return "Not at gate" instead of turnaround progress
2. **E3 fix:** `cruise_alt = random.choice([350, 370, 390]) if heading < 180 else random.choice([340, 360, 380])` — one line
3. **F2 fix:** Add boarding status to departure schedule based on time-to-departure
4. **A4 fix:** Reduce altitude noise from ±200ft to ±30ft on approach: `random.uniform(-30, 30)`

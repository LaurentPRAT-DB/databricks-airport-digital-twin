# Phase 47: UX Review V4 — Comprehensive Live Testing Report

**Date:** 2026-03-20
**Tester:** Claude (AI UX designer)
**App URL:** https://airport-digital-twin-dev-7474645572615955.aws.databricksapps.com
**Build:** v0.1.0, #254
**Airports tested:** KSFO, KJFK
**Views tested:** 2D map, 3D view, FIDS, Flight Detail, Gate Status, Turnaround Timeline, Baggage Status

---

## Executive Summary

The Airport Digital Twin demo delivers an impressive, visually rich experience across 2D/3D views with 27 airports, dynamic OSM data, and rich flight detail panels. The core architecture is solid. However, **12 UX issues** were identified during live testing that reduce credibility when scrutinized by aviation-knowledgeable viewers. Most are data realism and edge-case bugs, not architectural problems.

**Severity breakdown:**
- **Critical (3):** Baggage % wrong, FIDS times identical, gate recommendations identical
- **High (5):** G869 fake gate, self-referencing origins, numbered terminal gates unused, WebSocket spam, unrealistic airlines
- **Medium (3):** "OTH" airline prefix, easyJet/Ryanair at JFK, vertical rate sometimes 0
- **Low (1):** Airport switch latency (14s)

---

## Test Session Log

### 1. Initial Load — KSFO (2D View)

**Result:** Good. 100 flights loaded, map centered on SFO, OSM overlay showing terminals/runways/taxiways.
- Flight list shows callsigns with phase badges (GND, CRZ, DSC, CLB)
- Gate Status panel: 72 available, 48 occupied across terminals A-G
- Weather widget showing "15C 262@8kt 10SM"
- WebSocket connected indicator green

### 2. Flight Detail — Descending Flight (UAL1185)

**Observed:**
- Callsign: UAL1185, Phase: Descending, Alt: 4800ft, Speed: 140kts
- Origin: EWR, Destination: SFO, Aircraft: B738
- Heading: 274 deg
- **Vertical Rate: -200 ft/min** (correct this time; earlier session showed 0)

**Issues found:**
- **[ISSUE-1] Gate recommendations all identical:** A1=96%/4min, B1=96%/4min, G1=96%/4min
  - All three gates have same score and same taxi time
  - Reasons identical: "Gate is currently available", "Optimal size for B738"
  - No differentiation by terminal proximity, operator preference, or actual taxi distance
  - **Root cause:** `_estimate_taxi_time()` in gate_model.py uses haversine from primary runway but all gates compute similar distances. The 5-factor scoring collapses because availability (40%) and size (15%) are the same for all empty gates.

- **[ISSUE-2] Baggage shows "Delivered 100%" with 0 bags delivered**
  - 74 Total, 0 Delivered, 10 Connecting — but progress bar says 100% Delivered
  - Aircraft is still at 4800ft descending — no bags should be delivered yet
  - **Root cause:** `_determine_bag_status()` in baggage_generator.py calculates percentage incorrectly for pre-arrival flights. The `processed = unloaded + on_carousel + claimed` formula likely yields 0/0 which defaults to 100%.

### 3. Flight Detail — Ground Flight (AAL100 at Gate D15)

**Observed:**
- Callsign: AAL100, Phase: Ground, Aircraft: A321
- Origin: JFK ("Arrived from"), Destination: DEN ("Departing to") — correct labels
- Turnaround Progress: Gate D15, Refueling phase, 22%
  - 4 checkmarks (deboarding, unloading, cleaning, catering done)
  - Steps 5-7 remaining
  - Est. Departure: 12:57 PM (later showed 10:30 AM — time changed between reads)
  - Active Equipment: fuel truck, ground power
- Baggage: 216 total, 216 delivered (later 215), 20 connecting — realistic for ground phase
- Delay Prediction: Severe Delay +64m, 70% confidence

**Good:** Turnaround lifecycle working correctly with progressive phases.

### 4. Flight Detail — Climbing Flight (OTH8467)

**Issues found:**
- **[ISSUE-3] "OTH" airline prefix unrealistic:** No major airline uses "OTH" ICAO code. Appears to be a catch-all "other" bucket. Should use realistic lesser-known carriers (e.g., SKW for SkyWest, ENY for Envoy).

- **[ISSUE-4] "Arrived from: SFO" for flights AT SFO:** Some ground-phase flights show origin_airport = SFO while they are parked at SFO. The label says "Arrived from: SFO" which is a self-referencing origin.

### 5. 3D View — Ground Aircraft (AAL100)

**Observed:**
- Camera auto-positioned behind aircraft at gate D15 (ramp view)
- Green selection ring visible around aircraft
- Label: "AAL100 | 0 ft | 0 kts"
- Aircraft models rendered at gates with correct orientation
- Trajectory line (dashed cyan) visible
- Terminal buildings as 3D blocks
- Navigation controls: Reset view, North up, Top-down, Zoom in/out
- Hint bar: "Left-click drag: Rotate | Right-click drag: Pan | Scroll: Zoom"

**Good:** Aircraft on ground (not floating), proper scale, 3D models look correct.
**Screenshot:** screenshot_08_3d_view_aal100.png

### 6. 3D View — Descending Flight (UAL1185)

**Observed:**
- Aircraft visible elevated above airport (4800ft)
- Label: "UAL1185 | 4800 ft | 140 kts"
- Camera positioned to show approach trajectory
- Trajectory path visible from cruise altitude down to approach

**Good:** 3D altitude rendering is correct and visually clear.
**Screenshot:** screenshot_09_3d_descending_ual1185.png

### 7. 2D/3D Coherence

**Observed:**
- Flight selection persists when switching 2D→3D and 3D→2D
- Flight detail panel preserved across view switches
- Map recenters appropriately

**Good:** View synchronization works correctly.
**Screenshot:** screenshot_10_2d_after_3d_ual1185.png

### 8. Airport Switch — KSFO → KJFK

**Timing:** ~14 seconds (click to full render)
- Header updated to "KJFK (JFK)"
- Flight selection correctly cleared
- New gates loaded: Terminals 1-9 (numbered) + A-G (lettered)
- OSM overlay updated with JFK layout

**Issues found:**
- **[ISSUE-5] Numbered terminal gates all show 0 used:** JFK Terminals 1-9 (87 gates total) have 0 occupancy while letter terminals A-G have all occupancy. JFK actually uses numbered terminals (T1-T8). The gate assignment logic only generates letter-prefix gate IDs (A1, B5, C9...), never numeric-prefix ones (1-1, 2-3, etc.).

- **[ISSUE-6] Airport switch latency:** 14 seconds is acceptable for a demo but could frustrate users switching between airports. The known issue is that 3-tier loading always falls to OSM (10-16s).

**Screenshot:** screenshot_11_kjfk_loaded.png

### 9. FIDS at KJFK

**Observed:**
- 100 arrivals displayed with airline names, origins, gates, statuses
- Delay statuses working: "Delayed +13 min", "+16 min", "+23 min", etc.
- Arrived flights shown with actual arrival time
- International airlines present: BAW, KLM, UAE, CPA, ANA, DLH, TAM, QFA, KAL, THY, ETD, SAA
- Good diversity of origins: LHR, AMS, NRT, ICN, HKG, SIN, SYD, MEL, DXB, AUH, SCL, DUB, MUC, CDG

**Issues found:**
- **[ISSUE-7] ALL FIDS scheduled times are "08:47":** Every single arrival shows 08:47 as scheduled time. Real FIDS boards have flights spread across hours. This is the most visible realism issue — any viewer immediately notices.
  - **Root cause:** `get_flights_as_schedule()` in fallback.py generates all flights at the same base time. The jitter hash spreads estimated times but not scheduled times.

- **[ISSUE-8] Self-referencing origins in FIDS:** SWA2685 "from JFK" arriving at JFK, DAL2436 "from JFK", UAL2332 "from JFK", UAL1324 "from JFK". Multiple flights show the current airport as their origin.
  - Same as ISSUE-4 but visible in FIDS as well.

- **[ISSUE-9] easyJet (EZY) and Ryanair (RYR) at JFK:** European budget carriers that don't fly transatlantic. EZY946 from LTN (London Luton) and RYR644 from DUB. The airline scope validation should prevent this.
  - **Root cause:** `_is_destination_compatible()` may not be filtering correctly for `regional_eu` scope airlines at US airports.

- **[ISSUE-10] G869 gate still appearing:** BAW2380 assigned to gate G869 in FIDS. This is a known fake gate from a previous OSM data issue that should have been filtered.

**Screenshot:** screenshot_12_kjfk_fids.png

### 10. Console Logs

**Observed:** 6,152 error messages accumulated during session.
- **[ISSUE-11] WebSocket 403 spam:** Continuous reconnection attempts to `wss://...aws.databricksapps.com/ws/flights` fail with 403. Each retry generates 2-4 error messages. Over a session, this fills the console with thousands of errors.
  - **Root cause:** Databricks App proxy doesn't support WebSocket upgrade. The client has exponential backoff but the base interval is too short and max retries too high.

---

## Issue Summary Table

| # | Severity | Category | Issue | Impact |
|---|----------|----------|-------|--------|
| 1 | Critical | Data Realism | Gate recommendations all identical (same score, same taxi time) | Makes ML predictions look broken |
| 2 | Critical | Data Bug | Baggage shows 100% delivered for airborne flights (0/74 = 100%) | Obvious logical error |
| 3 | High | Data Realism | "OTH" airline prefix not a real ICAO code | Breaks immersion for aviation viewers |
| 4 | High | Data Bug | Self-referencing origin ("Arrived from: SFO" at SFO) | Logically impossible |
| 5 | High | Data Realism | JFK numbered terminal gates (T1-T9) all empty, only letter gates used | JFK doesn't have letter terminals |
| 6 | Low | Performance | Airport switch takes ~14 seconds | Acceptable for demo, annoying for repeated use |
| 7 | Critical | Data Realism | FIDS all scheduled times identical (08:47) | Most visible realism issue |
| 8 | High | Data Bug | Self-referencing origins in FIDS (flights "from JFK" at JFK) | Same as #4, visible in FIDS |
| 9 | Medium | Data Realism | easyJet/Ryanair at JFK — budget EU carriers don't fly transatlantic | Unrealistic airline mix |
| 10 | High | Data Bug | G869 fake gate still appearing in assignments | Known issue, not yet filtered |
| 11 | High | Console | WebSocket 403 reconnection spam (6000+ errors) | Fills console, masks real errors |
| 12 | Medium | Data Realism | Vertical rate sometimes 0 for descending flights | Intermittent, may be timing-dependent |

---

## Improvement Plan

### Sub-phase A: Critical Data Fixes (Priority 1)

**A1. Fix baggage percentage for pre-arrival flights**
- File: `src/ingestion/baggage_generator.py`
- Fix: When flight_phase is "descending" or "cruising", set delivered=0, progress=0%
- Guard against 0/0 division returning 100%

**A2. Spread FIDS scheduled times across realistic window**
- File: `src/ingestion/fallback.py` → `get_flights_as_schedule()`
- Fix: Distribute scheduled times across a 2-hour window around current time instead of all at same base time
- Use consistent hash per callsign for deterministic spread

**A3. Differentiate gate recommendation scores**
- File: `src/ml/gate_model.py` → `_score_gate()`, `_estimate_taxi_time()`
- Fix: Use actual gate geo-coordinates (from OSM data) for taxi distance calculation instead of generic haversine
- Add operator preference weighting (UAL → Terminal C at SFO, AAL → Terminal B at JFK)
- Vary availability scores by recency of last use

### Sub-phase B: Data Realism Fixes (Priority 2)

**B1. Eliminate self-referencing origins**
- File: `src/ingestion/schedule_generator.py` or `src/ingestion/fallback.py`
- Fix: When generating flights, ensure origin_airport != current airport for arriving flights
- For ground-phase flights, origin should be the airport they flew FROM, not the current airport

**B2. Filter G869 and other invalid gate IDs**
- File: `src/ingestion/fallback.py` → gate assignment logic
- Fix: Validate gate IDs against OSM-loaded gates, reject any not in the gate list
- Add gate ID format validation (letter + 1-2 digits, or number + letter for numbered terminals)

**B3. Replace "OTH" with real minor carriers**
- File: `src/ingestion/schedule_generator.py` → AIRLINES dict
- Fix: Replace "OTH" entry with real regional carriers (SKW/SkyWest, ENY/Envoy, RPA/Republic, etc.)

**B4. Fix airline scope filtering for non-US airports**
- File: `src/ingestion/schedule_generator.py` → `_is_destination_compatible()`
- Fix: Ensure `regional_eu` scope airlines (EZY, RYR) cannot be assigned to US airports
- Verify scope logic works both directions (EU carriers at US airports, US regionals at EU airports)

**B5. Support numbered terminal gate assignment**
- File: `src/ingestion/fallback.py` → gate assignment
- Fix: When OSM gates have numeric prefixes (JFK: "1-1", "2-3", etc.), include them in the assignment pool
- Gate format detection should handle both "A1" (letter prefix) and "1-1" (number prefix) styles

### Sub-phase C: Infrastructure Fixes (Priority 3)

**C1. Reduce WebSocket reconnection spam**
- File: `app/frontend/src/hooks/useFlightData.ts` (or wherever WS connection lives)
- Fix: Increase backoff interval (min 5s, max 60s), add max retry limit (10), then fall back to polling-only
- When WS returns 403, stop retrying (it's an auth/proxy issue, not transient)

**C2. Improve airport switch performance**
- Already tracked as known issue (Lakebase/UC cache broken)
- Short-term: Pre-cache popular airports on backend startup
- Long-term: Fix Lakebase OAuth for 3-tier loading

### Sub-phase D: Polish (Priority 4)

**D1. Vertical rate consistency for descending flights**
- File: `src/ingestion/fallback.py` → vertical rate logic
- Investigate: VR=0 was seen for some descending flights at 3012ft, but -200 was seen at 4800ft
- May be threshold-based logic where `alt_diff <= 0` returns 0. Check if altitude convergence causes VR to drop to 0 too early

---

## What's Working Well

1. **Multi-airport support:** 27 airports load correctly with OSM data
2. **3D visualization:** Aircraft at correct altitudes, ground aircraft on ground, selection rings, labels
3. **2D/3D coherence:** Flight selection and viewport preserved across view switches
4. **Turnaround lifecycle:** Progressive phases (deboarding → cleaning → catering → refueling → boarding), equipment tracking, estimated departure
5. **FIDS variety:** International airlines (Emirates, Cathay Pacific, ANA, Lufthansa, Korean Air, Qantas, LATAM, Turkish), diverse origins
6. **Gate status panel:** Terminal breakdown, occupancy tracking, congestion indicators
7. **Flight phase visualization:** Color-coded badges, trajectory rendering, altitude-based label positioning
8. **Airport selector:** Clean dropdown with regional grouping (Americas, Europe, Middle East, Asia-Pacific, Africa)
9. **Delay predictions:** Working with severity categories and confidence scores
10. **Navigation controls (3D):** Reset view, North up, Top-down, zoom — all functional

---

## Test Evidence

| Screenshot | Description |
|-----------|-------------|
| screenshot_08_3d_view_aal100.png | 3D view with AAL100 selected at gate D15 |
| screenshot_09_3d_descending_ual1185.png | 3D view of UAL1185 descending at 4800ft |
| screenshot_10_2d_after_3d_ual1185.png | 2D view after switching back from 3D (selection preserved) |
| screenshot_11_kjfk_loaded.png | KJFK airport loaded, gate status showing numbered terminals |
| screenshot_12_kjfk_fids.png | FIDS at KJFK showing all-same scheduled times |

*Note: Screenshots 01-07 from earlier session (pre-context-reset) are in the same directory.*

# UX Review v3 — Airport Digital Twin
**Date:** 2026-03-19
**Reviewer:** Claude (acting as UX designer)
**App URL:** https://airport-digital-twin-dev-7474645572615955.aws.databricksapps.com
**Build:** v0.1.0, deployment #252
**Airport tested:** KSFO (default), KJFK (switch test)

---

## Executive Summary

The application delivers a compelling real-time airport digital twin experience. The core simulation engine works well — flights progress through realistic lifecycle phases (approach, landing, taxi, gate, turnaround, departure), the 2D map with OSM overlay is informative, and the multi-airport switching works. However, several data realism, UX polish, and 3D quality issues reduce the demo impact for aviation-knowledgeable audiences.

**Strengths:**
- Flight lifecycle working end-to-end (watched UAL123 descend from 3200ft → 694ft → landed → taxi at 25kts)
- Turnaround progression realistic (OTH4891: Chocks On → Cleaning at 63%, steps progressing)
- Gate occupancy dynamically updating (93→87→83 available over observation period)
- New flights appearing as others complete lifecycle — continuous simulation
- Airport selector well-organized by region (Americas, Europe, Middle East, Asia-Pacific, Africa)
- Weather data displayed in header (15°C 266@12kt 10SM)
- Baggage tracking with "at risk" warnings adds depth

**Critical Issues (demo-breaking for aviation audience):**
16 issues identified, categorized below.

---

## Issues Found

### P0 — Data Realism (highest impact on credibility)

| # | Issue | Details | Screenshot |
|---|-------|---------|------------|
| 6 | **FIDS: Impossible gate numbers** | Gates like "17B", "52B", "69B", "77", "82", "210B", "48C", "52I", "72B" don't exist at SFO. SFO gates: A1-A15, B1-B27, C1-C11, D1-D16, E1-E13, F1-F22, G1-G23. | screenshot_08_fids.png |
| 7 | **FIDS: Unrealistic airline routes** | Southwest (SWA) to DXB/FRA/LHR/NRT — SWA is domestic only. easyJet from MCO — doesn't fly US. Allegiant from SYD/HKG — domestic only. Hawaiian from FRA/SIN — not realistic. | screenshot_08_fids.png |
| 9 | **JFK terminal naming wrong** | JFK shows terminals A-G (SFO naming). JFK has Terminals 1, 2, 4, 5, 7, 8. 87 gates dumped into "Other" because they don't match A-G naming. | screenshot_09_kjfk_loaded.png |

### P1 — Physics & Simulation Bugs

| # | Issue | Details | Screenshot |
|---|-------|---------|------------|
| 1 | **Vertical rate 0 for descending flights** | UAL123 at 3200ft descending shows 0 ft/min vertical rate. Should be ~-700 to -1000 ft/min on approach. Same for DAL2287 at 2500ft. | screenshot_03_ual123_approach.png |
| 2 | **Gate recommendations all identical** | UAL123: gates A1, B1, G1 all show 96% score and 7 min taxi time. Different terminals should have significantly different taxi times. | screenshot_03_ual123_approach.png |
| 4 | **Baggage progress bar always 0%** | Bar shows "0% Delivered" but text says 170/171 delivered (UAL123) or 216/216 (AAL100). Progress bar calculation is broken — likely dividing wrong values or not updating. | screenshot_03_ual123_approach.png, screenshot_04_aal100_parked.png |
| 8 | **FIDS arrival times too clustered** | All arrivals at 20:48-20:51 — unrealistically bunched. Real FIDS would show spread over 30-60 min window. | screenshot_08_fids.png |

### P2 — UX Polish & State Management

| # | Issue | Details | Screenshot |
|---|-------|---------|------------|
| 5 | **Ambiguous origin/destination for turnaround flights** | AAL100 at SFO gate shows "JFK Origin, DEN Destination" — confusing. Should clarify: "Arrived from JFK → Departing to DEN". | screenshot_04_aal100_parked.png |
| 10 | **Flight details persist across airport switch** | OTH4891 (SFO flight) detail panel still showing after switching to JFK. Should auto-close or update context. | screenshot_10_3d_view.png |
| 16 | **Trajectory points differ between 2D and 3D** | DAL2287: 7 pts in 2D vs 1 pt in 3D. 3D trajectory display is sparse/incomplete. | screenshot_11_3d_flight_selected.png, screenshot_12_2d_after_3d.png |

### P3 — 3D View Quality

| # | Issue | Details | Screenshot |
|---|-------|---------|------------|
| 11 | **Aircraft models are dark silhouettes** | All aircraft render as uniform dark shapes. Hard to distinguish types, ground vs airborne. No color coding by phase. | screenshot_10_3d_view.png |
| 12 | **Stale context in 3D after airport switch** | Same as #10 but specifically in 3D context. | screenshot_10_3d_view.png |
| 13 | **Trajectory "0 pts" for some flights in 3D** | OTH4891 showed 0 trajectory points in 3D despite having 80 pts in 2D. | screenshot_10_3d_view.png |
| 14 | **Delay prediction missing in 3D for some flights** | OTH4891: "No prediction available" in 3D, but prediction was shown in 2D. | screenshot_10_3d_view.png |
| 15 | **Aircraft visual clustering** | Dense airport areas show many overlapping 3D models with no depth separation — visually chaotic. | screenshot_10_3d_view.png |

### Performance

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Initial page load (KSFO) | ~31s (map loading) | <10s | Slow |
| Airport switch (KSFO→KJFK) | ~17s | <5s | Slow (known: OSM fallback) |
| 2D→3D toggle | <1s | <1s | OK |
| 3D→2D toggle | <1s | <1s | OK |
| WebSocket updates | Every ~5s | Continuous | OK |

---

## Positive Observations (keep these)

1. **Flight lifecycle is compelling** — Watching UAL123 descend, land, taxi, and get assigned a gate (B17) over a few minutes is the core demo value
2. **Turnaround progression** — Steps with checkmarks, active equipment display, estimated departure time
3. **Gate occupancy dynamics** — Live updating gate counts per terminal
4. **Multi-airline diversity** — UAL, DAL, AAL, JBU, ASA, BAW, DLH, JAL, ANA, CZ all present
5. **Calibrated flight counts** — KSFO=100, KJFK=195 matches relative airport sizes
6. **Airport selector UX** — Clean regional grouping, custom ICAO input, "All 27 airports cached" indicator
7. **Weather integration** — METAR-style display (15°C 266@12kt 10SM)
8. **Baggage "at risk" warnings** — Adds operational realism
9. **Simulation panel** — Pre-built calibrated scenarios (CDG, BOS, ATL, AMS) with size warnings

---

## Improvement Plan (prioritized)

### Phase A: Data Realism Fixes (P0 — highest demo impact)

**Goal:** Eliminate credibility-breaking data issues for aviation audiences.

1. **Fix FIDS gate generation** — Gate names must come from the active airport's OSM gate list. Currently FIDS generates random gate identifiers that don't match any real airport layout. Map FIDS schedule to available gates from `airport_config_service`.

2. **Fix FIDS airline-route pairing** — Create an airline route plausibility matrix. Southwest, Allegiant, Frontier = domestic US only. easyJet = Europe only. Use calibration profiles to restrict airlines to routes they actually fly. At minimum, filter by domestic/international capability.

3. **Airport-specific terminal naming** — Terminal tab names must come from OSM data, not hardcoded A-G. JFK should show "Terminal 1, 2, 4, 5, 7, 8". SFO is correctly A-G. Parse terminal names from OSM `aeroway=terminal` features.

### Phase B: Physics & Simulation Fixes (P1)

4. **Fix vertical rate for descending/climbing flights** — Compute vertical rate from altitude delta between updates: `vrate = (alt_current - alt_previous) / time_delta`. A descending flight at 3200ft should show approximately -700 to -1000 ft/min.

5. **Differentiate gate recommendations** — Gate scoring should factor in actual taxi distance from runway. Terminal A is closer to runway 28L/R than Terminal G at SFO. Score differential should be 5-15% between near/far terminals, and taxi times should range from 3-12 min.

6. **Fix baggage progress bar** — The progress bar always shows 0%. The percentage calculation likely has a division issue or is reading the wrong field. Should be: `(delivered / total) * 100`.

7. **Spread FIDS arrival times** — Generate arrival times over a realistic window (30-60 min ahead). Currently all arrivals cluster at the same minute. Add time offsets based on the schedule generation logic.

### Phase C: UX State Management (P2)

8. **Auto-close flight details on airport switch** — When airport changes, clear `selectedFlight` state and close the detail panel. Simple state reset in the airport switch handler.

9. **Clarify turnaround flight labels** — For ground flights in turnaround, show "Arrived from {origin}" and "Departing to {destination}" instead of just "Origin" / "Destination" which is ambiguous.

10. **Sync trajectory count between 2D/3D** — Ensure both views request the same trajectory data. The 3D view appears to receive fewer points, possibly due to a different API call or filtering.

### Phase D: 3D Quality (P3)

11. **Color-code 3D aircraft by flight phase** — Ground=green, Climbing=blue, Descending=orange, Cruising=white. Match the legend in the header bar.

12. **Improve 3D aircraft model lighting** — Add ambient/directional light so aircraft models are visible and not flat dark silhouettes. Consider adding subtle glow for airborne aircraft.

13. **Altitude-based visual separation in 3D** — Scale or offset aircraft labels vertically based on altitude to reduce visual overlap in dense areas.

14. **Ensure prediction data available in 3D** — Delay prediction and trajectory data should be identical between 2D and 3D views. May be a data-passing issue in the view switch.

### Phase E: Performance (ongoing, known issues)

15. **Fix Lakebase/UC cache** — Currently falls to OSM for every airport load (10-17s). Restoring the 3-tier cache (Lakebase → UC → OSM) would reduce switch time to <2s.

16. **Pre-load popular airports** — The "All 27 airports cached" indicates backend caching works. Ensure this cache persists across app restarts.

---

## Test Script for Future Reviews

```
1. Load app → verify KSFO loads < 10s, 100 flights, map renders
2. Select descending flight → check vertical rate is negative
3. Check gate recommendations → verify different taxi times per terminal
4. Check baggage progress bar → verify percentage matches count
5. Open FIDS → verify gate names match airport, airline routes plausible
6. Switch to KJFK → measure load time, verify terminal names match JFK
7. Verify flight details auto-close on switch
8. Switch to 3D → verify aircraft colored by phase, trajectories visible
9. Compare same flight in 2D and 3D → verify same trajectory point count
10. Switch back to 2D → verify map renders correctly
```

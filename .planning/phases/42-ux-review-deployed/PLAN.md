# Phase 42: Deployed App UX Review — Airport Digital Twin

## Review Method

Systematic UX review of the deployed Databricks App at `https://airport-digital-twin-dev-7474645572615955.aws.databricksapps.com/`. Tested: initial load, 2D flight tracking, 3D view, airport switching (SFO→LAX→SFO), FIDS, turnaround lifecycle, gate status panel. Captured 16 screenshots. Cross-referenced with Phase 41 local UX review findings.

**Date:** 2026-03-19
**Build:** v0.1.0, commit #249
**App URL:** https://airport-digital-twin-dev-7474645572615955.aws.databricksapps.com/

---

## CRITICAL: Airport Switch State Corruption (New Finding)

### Bug: Switching airports leaves backend in permanently corrupted state
**Severity: CRITICAL — Blocks all multi-airport demo use**

**Steps to reproduce:**
1. Load app (defaults to KSFO/SFO) — works fine
2. Click airport selector → choose KLAX (LAX)
3. Observe "Resetting flight state... 0%" progress bar
4. Error toast: "Failed to activate airport"
5. Partial state: flight data switches to LAX coordinates + gate numbers, but header stays "KSFO (SFO)"
6. Switch back to SFO → header shows KSFO but all flight positions remain at LAX coordinates (33.94°N, -118.40°W)
7. **Full page reload does NOT fix it** — backend singleton is permanently corrupted
8. FIDS shows "Failed to fetch schedule" after switch

**What breaks:**
- Flight positions at LAX coordinates (~33.94, -118.40) while header says KSFO
- Gate numbers are LAX-style (84, 48C, 52B, 407, 209B, 416) instead of SFO (A1, B3, G2)
- Only "Other" terminal tab visible — SFO's A-G terminal tabs gone
- FIDS schedule fetch fails completely
- Map shows LAX airport layout but header claims KSFO
- State persists across page reloads — requires app restart

**Root cause hypothesis:** The `airport_config_service` singleton partially updates during the switch. If the OSM fetch for the new airport fails or times out, the singleton is left in an inconsistent state where some components (gates, flight generator) have switched but others (ICAO code, schedule) have not. The singleton never rolls back on failure.

**Fix approach:**
1. Atomic airport switch: snapshot current state before switching, rollback on any failure
2. Add a health check after switch completes — verify ICAO code, gate data, and flight positions are all consistent
3. Frontend: if switch fails, show clear error and stay on previous airport (don't show partial state)
4. Backend: `airport_config_service.activate_airport()` should be transactional

---

## Confirmed Issues from Phase 41 (Local Review)

All issues documented in Phase 41 were confirmed on the deployed app:

### P0 — Physics Bugs (Confirmed on Deploy)

| # | Issue | Deployed Evidence |
|---|-------|-------------------|
| 1 | **Taxi speed at gate = 25kts** | UAL669 at gate B10, turnaround "Unloading 48%", speed 25kts. UAL1840 at gate, speed 96kts (!). Multiple ground flights show non-zero speed while parked. |
| 2 | **Negative altitude** | Not directly observed this session (would need longer observation), but the code path is unchanged — confirmed in local Phase 41 |

### P1 — Data Integrity (Confirmed on Deploy)

| # | Issue | Deployed Evidence |
|---|-------|-------------------|
| 3 | **FIDS broken after airport switch** | "Failed to fetch schedule" — 0 arrivals displayed. Even before switch, ETAs were wildly inaccurate (confirmed Phase 41) |
| 4 | **Gate recommendations for parked aircraft** | UAL669 at gate B10 with active turnaround still shows "Gate Recommendations" panel with gates 9, 11B, 11A. The `needsGateAssignment` check fails because `assigned_gate` is null despite turnaround knowing the gate. |
| 5 | **Last Seen timestamp frozen** | UAL669 shows "Last Seen: 13:45:47" while current time is 20:17. Every flight shows the same static timestamp. |

### P2 — UX Polish (Confirmed on Deploy)

| # | Issue | Deployed Evidence |
|---|-------|-------------------|
| 6 | **Uniform delay predictions** | Every flight: "Severe Delay +53-59m, 70% confidence". No variation regardless of phase, airline, or route. |
| 7 | **Invalid gate names** | LAX gates showing numeric-only names (84, 157, 416, 407) without terminal prefix — OSM artifacts |
| 8 | **Only "Other" terminal tab** | After corrupted switch, all gates fall under "Other" — no terminal organization |

---

## New Findings (Deployed Only)

### 9. Flight Count Stuck at 50 (Not 100)
**Severity: Medium**
**Observed:** Header shows "Flights: 50" despite Phase 21 changing default to 100.
**Possible cause:** Either the deploy didn't include the demo_config.py change, or the environment variable `DEMO_FLIGHT_COUNT` is set to 50 in the app config, overriding the code default.
**Fix:** Check `app.yaml` for `DEMO_FLIGHT_COUNT` env var. If set, update to 100.

### 10. NaN Values for Some Flights
**Severity: Medium**
**Observed (earlier in session):** Flights like "14F47A" and "CEECD2" showed "ALT: NaNft SPD: NaNkts" — raw hex ICAO addresses with missing data fields.
**Root cause:** These appear to be real ADS-B artifacts that slip through without proper callsign or telemetry data. The frontend displays NaN instead of filtering or showing "--".
**Fix:** Filter flights without valid callsigns from the display, or show "--" for NaN values.

### 11. UAL1840 Taxi Speed 96kts
**Severity: High**
**Observed:** UAL1840 at gate (ALT: 0ft) showing 96kts ground speed. This is far above normal taxi speed (~15-25kts) and approaching takeoff speed. A parked aircraft at 96kts is physically impossible.
**Root cause:** Same as taxi-speed-at-gate bug but worse — the velocity from the previous phase (approach/landing at ~130-180kts) wasn't properly clamped during phase transition.
**Fix:** Clamp velocity during phase transitions: `if transitioning to PARKED: velocity = 0`, `if TAXI: velocity = min(velocity, 25)`.

### 12. Map Auto-Center Not Working After Switch
**Severity: Medium**
**Observed:** After switching airports (LAX→SFO), the map didn't auto-center on the new airport's coordinates. The Leaflet view stayed at the old viewport, requiring manual pan/zoom.
**Fix:** After airport switch completes, call `map.flyTo([newLat, newLng], defaultZoom)`.

---

## What Works Well

- **Approach trajectories**: UAL123 descended 4215→3813→2608→1600ft over ~60s — smooth, realistic descent rate
- **3D view**: Terminal buildings as gray blocks, aircraft models visible, info tags with callsign/altitude/speed. Functionally coherent with 2D view.
- **Flight list**: Real-time updates via WebSocket, searchable, sortable by callsign or altitude
- **Turnaround timeline**: Phase progress (Unloading 48%), equipment tracking (belt loader, ground power), estimated departure time
- **Baggage status**: Per-flight counts (171 total, 169 delivered, 31 connecting, 2 at risk)
- **Weather display**: METAR-style "20°C 297@5kt 10SM" in header
- **WebSocket connection**: "Connected" indicator, 2-second update cycle working reliably
- **Gate status panel**: Occupied/available counts updating in real-time
- **2D/3D toggle**: Instant switch between views, map position preserved

---

## Prioritized Fix Plan (Combined Phase 41 + 42)

| Priority | Issue | Effort | Impact | Source |
|----------|-------|--------|--------|--------|
| **P0** | Airport switch state corruption | Large | **Blocks multi-airport demo entirely** | Phase 42 |
| **P0** | Taxi speed at gate (25-96kts) | Small | Physics violation, contradicts turnaround | Phase 41+42 |
| **P0** | Negative altitude clamp | Small | Physics violation (-990ft underground) | Phase 41 |
| **P1** | FIDS ETA wildly inaccurate | Medium | FIDS useless for approaching flights | Phase 41 |
| **P1** | FIDS broken after airport switch | Medium | Coupled to P0 airport switch fix | Phase 42 |
| **P1** | Gate recommendations for parked flights | Small | Contradicts turnaround panel | Phase 41+42 |
| **P1** | Velocity clamp on phase transition | Small | 96kts while parked | Phase 42 |
| **P1** | Console duplicate keys (2000+) | Small | React perf degradation | Phase 41 |
| **P2** | Flight count 50 vs 100 | Small | Check env var config | Phase 42 |
| **P2** | NaN display for incomplete flights | Small | Unprofessional display | Phase 42 |
| **P2** | Invalid gate names (OSM artifacts) | Small | Confusing gate assignments | Phase 41 |
| **P2** | Departure climb delay at altitude 0 | Medium | Unrealistic takeoff | Phase 41 |
| **P2** | Map auto-center after switch | Small | UX inconvenience | Phase 42 |
| **P2** | Airline name resolution | Small | Incomplete FIDS display | Phase 41 |
| **P3** | Last Seen timestamp frozen | Small | Static, unhelpful | Phase 41+42 |
| **P3** | Heading normalization (>360) | Small | Edge case cosmetic | Phase 41 |
| **P3** | Uniform delay predictions | Large | ML model limitation | Phase 41+42 |

---

## Recommended Implementation Order

### Wave 1: Critical Physics & State Fixes (4 items, ~2 hours)
1. **Altitude clamp**: `max(0, altitude)` in `_update_flight_state()`
2. **Velocity clamp**: Set to 0 on PARKED, max 25 on TAXI
3. **Heading normalization**: `heading % 360`
4. **Gate recommendations guard**: Don't show if turnaround is active

### Wave 2: Airport Switch Fix (1 large item, ~3 hours)
5. **Transactional airport switch**: Atomic state update with rollback on failure, frontend error recovery, map re-center

### Wave 3: Data Quality (3 items, ~2 hours)
6. **FIDS ETA from current position**: Recalculate for approaching/landing flights
7. **NaN/invalid flight filter**: Hide or sanitize flights with missing data
8. **Console duplicate key fix**: Unique composite keys in AirportOverlay

### Wave 4: Polish (remaining items, ~2 hours)
9. Flight count env var check
10. Last Seen timestamp update
11. Invalid gate name filtering
12. Airline name lookup expansion

---

## Evidence

Screenshots saved in `.planning/phases/42-ux-review-deployed/`:

| File | Description |
|------|-------------|
| `screenshot_01_initial_load.png` | First load — "Loading Map..." screen |
| `screenshot_02_map_loading.png` | Map loading with flight list visible |
| `screenshot_03_ual123_approach.png` | UAL123 at 4215ft descending |
| `screenshot_04_ual123_10s_later.png` | UAL123 at 3813ft, 10s later — descent working |
| `screenshot_05_fresh_load.png` | "App Not Available" during deploy restart |
| `screenshot_06_reloaded.png` | Loading screen after deploy completes |
| `screenshot_07_map_loaded.png` | Full map with 52 flights at SFO |
| `screenshot_08_aal100_ground.png` | AAL100 ground, turnaround at gate B23 |
| `screenshot_09_aal100_30s.png` | AAL100 30s later, turnaround progress |
| `screenshot_10_3d_view.png` | 3D view — terminal buildings, aircraft models |
| `screenshot_11_lax_switching.png` | Airport switch in progress — error toast |
| `screenshot_12_lax_result.png` | Post-switch: LAX data, SFO header — corrupted |
| `screenshot_13_lax_final.png` | LAX gates (84, 48C) under "Other" tab |
| `screenshot_14_back_to_sfo.png` | Switch back to SFO — still showing LAX coords |
| `screenshot_15_post_reload_state.png` | Full reload — corruption persists, LAX runway layout visible |
| `screenshot_16_fids_post_switch.png` | FIDS "Failed to fetch schedule" after switch |

---

## Overall UX Assessment

**Score: 6/10 for single-airport demo, 2/10 for multi-airport demo**

**Strengths:**
- Core simulation loop works: approach → landing → taxi → gate → turnaround is visually convincing
- Real-time WebSocket updates provide a live, dynamic feel
- 3D view adds significant wow-factor for demos
- Turnaround + baggage detail panels show depth of the digital twin concept

**Weaknesses:**
- Airport switching is completely broken — the #1 feature for demos ("let me show you LAX now") fails catastrophically
- Physics violations (negative altitude, 96kts at gate) undermine credibility with aviation-aware audiences
- FIDS ETAs being hours off makes the schedule display useless
- Uniform "Severe Delay" predictions feel like placeholder data (which they are)
- Static "Last Seen" timestamp suggests stale data to anyone who notices

**Recommendation:** Fix Wave 1 (physics) and Wave 2 (airport switch) before any customer-facing demo. These are the two things most likely to break trust in the digital twin concept. Waves 3-4 improve polish but aren't demo-blockers for single-airport scenarios.

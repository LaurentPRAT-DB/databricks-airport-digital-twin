# Phase 44: UX Design Review v2 — Comprehensive Findings

## Review Method

Systematic UX review of the deployed Airport Digital Twin app (build #251, KSFO).
Tested on Chrome (macOS) via Chrome DevTools MCP automation. Captured 15 screenshots.
Covered: 2D flight trajectories, gate operations, turnaround lifecycle, FIDS panels,
airport switching, 3D view, and 2D/3D coherence.

**App URL:** https://airport-digital-twin-dev-7474645572615955.aws.databricksapps.com/
**Date:** 2026-03-19
**Review Duration:** ~45 minutes of live observation

---

## Critical Bugs Found & Fixed During Review

### Bug 1: Airport Switch Broken — ImportError (FIXED)
**Severity: Critical (P0)**
**Endpoint:** `POST /api/airports/KJFK/activate` → 500
**Error:** `cannot import name '_icao_to_iata' from 'app.backend.services.data_generator_service'`
**Root Cause:** `routes.py:878` imported `_icao_to_iata` from `data_generator_service` but the function lives in `src.calibration.profile`.
**Fix:** Changed import to `from src.calibration.profile import _icao_to_iata`
**File:** `app/backend/api/routes.py:878`

### Bug 2: FIDS Schedule API Returns 500 (FIXED)
**Severity: Critical (P0)**
**Endpoints:** `GET /api/schedule/arrivals` and `GET /api/schedule/departures` → 500
**Root Cause:** Lakebase returns PostgreSQL `datetime` objects via `RealDictCursor`, but `_dict_to_scheduled_flight()` calls `datetime.fromisoformat()` which expects strings. The Pydantic conversion crashes silently (no try/except).
**Fix:** Added `_parse_datetime()` helper that handles both string and datetime inputs.
**File:** `app/backend/services/schedule_service.py:30-34`

---

## Issues Found (Not Yet Fixed)

### P0 — Showstoppers

#### 3. Airport Switch Side Effects — Flight Count Doubles
**Observed:** After failed KJFK switch (which rolled back), flight count jumped from 100 to 195. JFK-calibrated flights (ANA125, KLM516, CZ8805, AMX415, WS2118, WS2900) were added alongside existing SFO flights. The rollback restored the airport label but not the flight list.
**Root Cause:** The activate endpoint partially succeeds (generates new flights) before hitting the import error. The rollback doesn't undo flight generation.
**Fix:** Either make the switch fully atomic (all-or-nothing), or ensure rollback clears newly generated flights.
**Evidence:** screenshot_12_kjfk_switch_attempt.png — shows 195 flights with mixed SFO+JFK carriers

### P1 — High Priority

#### 4. Ghost Flights with NaN Values
**Observed:** Flights "C5D5FA" and "E76DCF" appeared with hex-like callsigns and all NaN values (altitude, speed, heading, position). E76DCF detail showed all fields as `---`. Flights disappeared after ~15 minutes.
**Root Cause:** Likely flights spawned but never properly initialized, or recycled flight slots with stale hex IDs.
**Fix:** Validate flight state on creation — reject flights with NaN positions. Add guard in WebSocket broadcast to skip flights with invalid data.
**Evidence:** screenshot_05_nan_flight.png

#### 5. DAL1619, JBU6046, UAL1550, UAL4163, UAL6675 — Taxi Speed at Gate
**Observed:** Multiple ground flights show "SPD: 25kts" while parked (turnaround active). Some have heading actively changing.
**Root Cause:** Same as Phase 41 finding #2 — velocity not reset to 0 on PARKED transition. The Phase 41 fix may not have been deployed, or new flights bypass the fix.
**Fix:** Ensure `state.velocity = 0.0` in PARKED phase, not just on turnaround start.

#### 6. "Other" Terminal Category — 0 free | 21 used / 21
**Observed:** After the failed KJFK switch, Gate Status shows "Other" terminal with 21 occupied gates and 0 available. These are JFK gate numbers (1A, 2A, 521, 529, A19, etc.) that don't match SFO terminal prefixes.
**Root Cause:** JFK flights have gate assignments that use JFK gate naming (numeric, e.g. "3", "10", "42"). Since these don't start with SFO terminal letters (A-G), they fall into "Other".
**Fix:** Part of the atomicity fix (#3). Also: gate status should filter by active airport.

#### 7. UAL2945 Assigned to Gate G869
**Observed:** Flight UAL2945 shown at gate "G869" in the map button tooltip. G869 is an invalid OSM artifact.
**Root Cause:** The `_is_valid_gate_ref()` filter skips numeric refs > 999, but "G869" starts with "G" so it passes the filter. Need stricter validation: gate refs should match `^[A-G]\d{1,2}(-[A-G]?\d{1,2})?$` for SFO-style airports.
**Fix:** Update `_is_valid_gate_ref()` with regex validation, or per-airport gate format rules.
**Evidence:** G869 visible in map labels (uid=3_119, 3_273 in snapshots)

#### 8. Duplicate UAL6675 in Flight List
**Observed:** Two entries for "UAL6675" — one GND at 0ft/25kts, one CRZ at 35,290ft/407kts. Same callsign, different states.
**Root Cause:** Either a callsign collision in generation, or the partial KJFK switch created a duplicate.
**Fix:** Enforce unique callsigns in the flight state. If a callsign already exists, skip or reassign.

### P2 — Medium Priority

#### 9. Vertical Rate Shows 0 ft/min During Active Descent
**Observed:** UAL123 at 1151ft, descending at 158kts, but vertical rate shows "0 ft/min". Same for other descending flights in 3D view.
**Root Cause:** The vertical_rate field may only update during specific simulation ticks, or the WebSocket snapshot captures it between updates.
**Fix:** Compute vertical_rate from altitude delta between consecutive updates, or ensure the sim state always reflects current descent rate.

#### 10. 3D Aircraft Too Small / Hard to See
**Observed:** Aircraft models in 3D view are tiny dark shapes, barely visible against the green ground. At default zoom, you can only identify flights by their text labels.
**Fix:** Increase aircraft model scale, add contrasting colors (airline livery or bright generic), and consider adding shadow/highlight effects.

#### 11. Console 500 Errors Accumulate
**Observed:** 25+ console error entries for "Failed to load resource: 500" — all from the FIDS schedule endpoints polling every ~60 seconds.
**Impact:** Console fills with errors, makes debugging other issues harder. Performance: failed requests still consume network bandwidth.
**Fix:** Add error handling to FIDS fetch — after 3 consecutive failures, back off to 5-minute intervals. Show "FIDS unavailable" in UI instead of silently failing.

### P3 — Low Priority / Polish

#### 12. WebSocket DNS Resolution Error
**Observed:** `WebSocket connection to 'wss://...databricksapps.com/ws/flights' failed: ERR_NAME_NOT_RESOLVED` (msgid=19)
**Root Cause:** Transient DNS issue or the WebSocket path is wrong during startup. Only happened once.
**Fix:** Add WebSocket reconnection with exponential backoff (may already exist — verify).

#### 13. Weather Display Changes
**Observed:** Weather shows "14°C 275@6kt 10SM" — seems reasonable for SFO. But weather updates are infrequent.
**Note:** Low priority — weather data is informational only.

---

## What Works Well

1. **Flight approach physics** — UAL123 smooth descent from approach to landing: 602ft → 58ft → 0ft with speed decreasing from 140 → 135 → 25kts. Very realistic.
2. **Turnaround lifecycle** — FFT1470 progressed through Chocks On → Deboarding → Unloading → Cleaning with accurate timing and equipment tracking (ground power visible).
3. **Gate assignments** — UAL123 correctly assigned to gate G10 after landing. Gate status panel shows accurate terminal occupancy.
4. **2D/3D coherence** — Same flight (UAL123) shows consistent position in both views. Lat/lon, altitude, and heading match between views with expected interpolation differences.
5. **Zero console warnings** — No React duplicate key warnings (Phase 41 fix confirmed working).
6. **3D view rendering** — Terminal buildings, runways, taxiways render correctly. Camera controls (rotate, pan, zoom) work smoothly.
7. **OSM gate labels** — Full SFO gate overlay (A1-A15, B1-B27, C1-C11, D1-D16, E2-E13, F5-F22, G1-G14) with correct positions.
8. **Flight detail panel** — Works in both 2D and 3D modes with trajectory, baggage, turnaround, delay prediction.
9. **Delay predictions varied** — FFT1470 showed "Moderate Delay +17m 80%" (not the uniform "Severe Delay" from Phase 41). ML model improvements working.
10. **Lakebase connectivity** — Schedule upserts working, schedule reads succeeding from Lakebase at 100 flights per query.

---

## Prioritized Fix Plan

| # | Priority | Issue | Effort | Impact | Status |
|---|----------|-------|--------|--------|--------|
| 1 | P0 | Airport switch ImportError | Small | All airport switching broken | **FIXED** |
| 2 | P0 | FIDS 500 (datetime parsing) | Small | FIDS completely non-functional | **FIXED** |
| 3 | P0 | Switch atomicity (flight doubling) | Medium | Corrupts flight state on failed switch | TODO |
| 4 | P1 | Ghost NaN flights | Medium | Breaks immersion, confusing entries | TODO |
| 5 | P1 | Taxi speed at gate = 0 | Small | Contradicts turnaround state | TODO |
| 6 | P1 | "Other" terminal from stale state | Small | Confusing gate status after switch | TODO |
| 7 | P1 | G869 invalid gate filter | Small | Fake gate assigned to real flights | TODO |
| 8 | P1 | Duplicate callsigns | Medium | Same callsign, different states | TODO |
| 9 | P2 | Vertical rate 0 during descent | Medium | Incorrect instrument reading | TODO |
| 10 | P2 | 3D aircraft visibility | Medium | Hard to see aircraft models | TODO |
| 11 | P2 | Console error accumulation | Small | DevX + bandwidth waste | TODO |
| 12 | P3 | WebSocket DNS transient | Small | One-time error, auto-recovers | TODO |

---

## Phase 41 → Phase 44 Progress Comparison

| Phase 41 Issue | Status in Phase 44 |
|----------------|-------------------|
| Negative altitude | Not observed — may be fixed |
| Taxi speed at gate | **Still present** (DAL1619 at 25kts) |
| Gate recommendations for parked | Not checked this session |
| FIDS ETA wildly inaccurate | FIDS completely broken (500) — **fixed** |
| G869 invalid gate | **Still present** |
| Airline name resolution | Not checked (FIDS broken) |
| Console duplicate keys | **FIXED** — zero warnings |
| Last Seen timestamp stuck | Not checked |
| Departure climb delay | Not observed |
| Uniform delay predictions | **Improved** — FFT1470 shows varied prediction |

---

## Evidence

Screenshots saved in `.planning/phases/44-ux-review-v2/`:
- `screenshot_01-04` — Initial load and UAL123 approach sequence
- `screenshot_05` — Ghost NaN flight (E76DCF)
- `screenshot_06-08` — Parked flights, turnaround lifecycle (FFT1470)
- `screenshot_09-11` — FIDS 500 error (schedule API broken)
- `screenshot_12` — KJFK switch attempt (failed, flights doubled to 195)
- `screenshot_13-14` — 3D view with flight selected
- `screenshot_15` — 2D view after 3D (coherence check)

---

## Recommended Next Steps

1. **Deploy fixes** — Build frontend, redeploy with the 2 bug fixes (import + datetime parsing)
2. **Retest airport switching** — After fix #1, verify KJFK switch works end-to-end
3. **Retest FIDS** — After fix #2, verify arrivals/departures display correctly
4. **Fix switch atomicity** — Highest priority remaining: prevent flight doubling on failed switch
5. **Filter G869** — Tighten `_is_valid_gate_ref()` with per-airport gate format regex
6. **Fix taxi speed** — Ensure PARKED phase sets velocity to 0

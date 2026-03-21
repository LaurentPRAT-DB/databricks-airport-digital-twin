# P0+P1 UX Fixes — Implementation Plan

## Context

UX review found 5 issues that undermine the demo's credibility. The backend already implements all 9 flight phases (APPROACHING through ENROUTE) — the problem is NOT missing code but timing and configuration. User warning: "make sure not to undo — A1 seems to be a loop."

---

## Fix 1: P0-1 — Flights never depart (turnaround too slow)

**Root cause**: `fallback.py:3063-3079` — turnaround uses real-time seconds. Narrow-body = ~2100s gate time (35 min). Demo viewers see 0 departures in 5 min.

**Fix**: Add a `DEMO_TURNAROUND_SPEEDUP` multiplier that divides target gate time. Factor of 8x → turnaround in ~4 min instead of 35.

**File**: `src/ingestion/fallback.py`
- Line ~3079: After computing `target = gate_seconds * combined_factor * random.uniform(0.9, 1.1)`, divide by speedup factor
- Add constant near top of file: `DEMO_TURNAROUND_SPEEDUP = 8.0`
- Change: `target = target / DEMO_TURNAROUND_SPEEDUP`

**Why this is safe**: Only changes the duration threshold, doesn't touch phase transitions, state machine, or any other logic. All downstream phases (pushback → taxi → takeoff → departing → enroute) remain untouched.

---

## Fix 2: P0-2 — FIDS shows wrong airport data

**Root cause investigation**: The code path works correctly in theory:
- `ScheduleService.set_airport("HND", "RJTT")` is called during airport switch (`routes.py:1099`)
- `_merge_live_and_future()` calls `get_flights_as_schedule()` (returns correct Japanese airlines from live sim)
- `get_future_schedule(airport="HND")` → `get_cached_schedule("HND")` → `_get_profile_loader().get_profile("HND")` → finds RJTT profile with ANA/JAL/SKY airline shares
- `_select_airline(profile=rjtt_profile)` correctly samples from Japanese airlines

**Likely actual issue**: The `_schedule_cache` is keyed by IATA code. On first load (before airport switch), "SFO" gets cached. After switching to "HND", the HND schedule gets generated correctly BUT the stale SFO cache persists. If there's a timing issue where FIDS fetches before the switch fully completes, or the cache TTL hasn't expired from a previous SFO load, SFO data could leak through. Also: `_AIRLINE_NAMES` in `fallback.py` is missing "SKY" (Skymark), "ADO" (Air Do), "SFJ" (StarFlyer), and "CES" (China Eastern) — these would show as raw ICAO codes in FIDS.

**Fix approach**:
1. Clear schedule cache on airport switch: Add `clear_schedule_cache()` call in the airport switch path
2. Add missing airline names to `_AIRLINE_NAMES` in `fallback.py`: SKY, ADO, SFJ, CES, and other common international airlines
3. Force cache invalidation in `get_cached_schedule()` when `set_airport()` is called on `ScheduleService`

**Files**:
- `src/ingestion/schedule_generator.py` — add `clear_schedule_cache()` function that clears `_schedule_cache` and `_schedule_cache_timestamps`
- `app/backend/services/schedule_service.py:65-68` — call `clear_schedule_cache()` in `set_airport()`
- `src/ingestion/fallback.py:350-447` — add missing airline names (SKY→Skymark Airlines, ADO→Air Do, SFJ→StarFlyer, CES→China Eastern)

---

## Fix 3: P1-3 — 3D aircraft too dark

**Root cause**: Lighting is actually decent (ambient=0.8, directional=0.9, hemisphere light present) in `Map3D.tsx:322-343`. The problem is in `GLTFAircraft.tsx:84-125` — the `clone.traverse()` applies airline colors by mesh name matching. If GLTF mesh names don't match expected patterns (fuselage, tail, engine, window), all meshes fall through to the `else` branch at line 108 which sets `material.color.setHex(airline.primaryColor)`. Dark airline primary colors + low emissive = nearly black aircraft.

**Fix**:
1. Increase ambient light intensity from 0.8 → 1.2
2. Increase directional light intensity from 0.9 → 1.5
3. In `GLTFAircraft.tsx`, ensure `MeshStandardMaterial` has reasonable `roughness` (0.5) and `metalness` (0.2) defaults for all branches, not just engine/window
4. Add a minimum brightness floor: if computed color luminance is too low, brighten it

**Files**:
- `app/frontend/src/constants/airport3D.ts:234-240` — increase light intensities
- `app/frontend/src/components/Map3D/GLTFAircraft.tsx:84-125` — add roughness/metalness defaults, minimum brightness

---

## Fix 4: P1-4 — No taxi animation visible

**Root cause**: The backend implements `TAXI_TO_GATE` (line 2921) and `TAXI_TO_RUNWAY` (line 3132) phases with waypoint-following and 15-25kt speed. But because turnaround never completes (Fix 1), flights accumulate at PARKED and never reach PUSHBACK → TAXI_TO_RUNWAY → TAKEOFF.

For arrivals: LANDING → TAXI_TO_GATE does exist but transitions happen fast (touchdown → taxi in seconds). The 2 taxiing flights briefly observed (JAL8794, ANA6936 at 25kts) confirm the code works.

**Fix**: Fix 1 (turnaround speedup) will naturally cause departures to flow through PUSHBACK → TAXI_TO_RUNWAY → TAKEOFF, making taxi visible. Additionally, ensure the taxi phase duration is reasonable (not too fast to see).

**Verification**: After Fix 1 is deployed, observe that:
- Departing flights show taxi_out phase for 30-60 seconds
- Arriving flights show taxi_in phase briefly after landing

**No code changes needed beyond Fix 1** — the taxi code already works.

---

## Fix 5: P1-5 — No runway activity

**Root cause**: Same as Fix 4. The LANDING phase (line 2860) includes touchdown sequence, and TAKEOFF (line 3185) has 5 sub-phases (lineup → roll → rotate → liftoff → initial_climb). But without departures, only half the lifecycle is visible, and landing is very brief.

**Fix**: Fix 1 enables the full cycle. To make runway activity MORE visible:
1. Verify that the frontend renders flights during LANDING/TAKEOFF phases on the runway (they should appear at low altitude near the runway)
2. The `isGroundPhase()` in `phaseUtils.ts` already includes 'landing' and 'takeoff' — these flights will render at ground level in 3D

**No additional code changes needed** — Fix 1 unlocks the complete lifecycle.

---

## Implementation Order

1. **Fix 3** (3D lighting) — isolated frontend change, no risk
2. **Fix 1** (turnaround speedup) — single constant + one line change in backend
3. **Fix 2** (FIDS airport) — backend schedule service wiring
4. **Verify Fix 4 & 5** — should work automatically once Fix 1 is active

## Verification

1. Run existing tests: `uv run pytest tests/ -v` and `cd app/frontend && npm test -- --run`
2. Start local dev: `./dev.sh`
3. Open browser, switch to RJTT (Haneda)
4. Verify within 5 minutes:
   - Ground flights begin pushing back and taxiing
   - Takeoffs visible on runway
   - Climbing/departing flights appear
   - Gate count stabilizes (not just filling up)
5. Open FIDS at RJTT — verify ANA/JAL airlines, Japanese routes, correct gates
6. Switch to 3D view — verify aircraft are clearly visible (not dark silhouettes)
7. Deploy: `cd app/frontend && npm run build && databricks bundle deploy --target dev`
8. Verify on deployed URL

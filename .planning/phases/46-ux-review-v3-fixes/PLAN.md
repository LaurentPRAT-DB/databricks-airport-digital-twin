# Phase 46: Fix 16 UX Issues from Review v3

## Context

Comprehensive UX review on 2026-03-19 found 16 issues ranging from demo-breaking data realism problems (FIDS impossible gates, wrong airline routes, wrong terminal names) to physics bugs (vertical rate=0, baggage bar stuck at 0%), state management issues, and 3D quality problems. Fixing these makes the app credible for aviation-knowledgeable demo audiences.

---

## Sub-phase A: Data Realism (Issues #6, #7, #9) — P0

### Issue #6: FIDS impossible gate numbers

**Root cause:** `schedule_generator.py:_assign_gate_with_occupancy()` (line 451) takes a gates list from `get_gates()` in `fallback.py:758`. The `get_gates()` function correctly loads OSM gates — the gate names ARE real airport gates. However, the FIDS schedule generator calls `_assign_gate_with_occupancy()` with its own gate list from `get_gates()` keys, so gates should be correct. The issue may be that `get_gates()` returns default SFO gates before OSM loads, and the schedule is generated before OSM data is ready. Need to ensure schedule regeneration after OSM load.

**Fix:** In `schedule_generator.py:generate_daily_schedule()`, call `get_gates()` from fallback at generation time (it already does via `_assign_gate_with_occupancy`). The real fix: add a `regenerate_schedule()` call after airport switch completes in `fallback.py:reload_gates()`, so the cached schedule is invalidated. Also, in `get_future_schedule()`, pass the current airport's gate list.

**Files:** `src/ingestion/schedule_generator.py`, `src/ingestion/fallback.py`

### Issue #7: Unrealistic airline routes (SWA to DXB, easyJet from MCO)

**Root cause:** `schedule_generator.py` AIRLINES dict (line 24-60) has no `domestic_only` or region flag. `_select_destination()` (line 205) uses calibrated profile routes if available, but the airline selected by `_select_airline()` has no restriction — a domestic-only carrier can get paired with any international route.

**Fix:** Add a `scope` field to AIRLINES: `"domestic"`, `"regional"`, `"international"`, or `"full"`. In `_select_destination()`, after selecting a route, validate against airline scope. If mismatched, re-pick. Key mappings:
- domestic: SWA, AAY, FFT, NKS, SPR
- regional_eu: EZY, RYR, WZZ
- full: all others

**Files:** `src/ingestion/schedule_generator.py`

### Issue #9: JFK terminal naming shows A-G instead of Terminal 1,2,4,5,7,8

**Root cause:** `GateStatus.tsx:inferTerminal()` (line 62-69) extracts the letter prefix from gate refs (`/^([A-Za-z]+)/`). JFK gates from OSM have numeric refs like `1`, `17B`. The regex fails → falls to "Other". The OSM terminal field on gates should have the correct terminal name.

**Fix:** In `GateStatus.tsx:inferTerminal()`, handle numeric-prefix gates: if the ref starts with a digit, extract the first digit(s) as terminal number → "Terminal N". Also, prioritize the `g.terminal` field from OSM data (already done at line 114: `g.terminal || inferTerminal(...)`). The real issue may be that OSM gates for JFK don't have the terminal field populated. Check and fix in `src/formats/osm/converter.py` if needed — ensure terminal association is computed from spatial containment.

**Files:** `app/frontend/src/components/GateStatus/GateStatus.tsx`, possibly `src/formats/osm/converter.py`

---

## Sub-phase B: Physics Fixes (Issues #1, #2, #4, #8) — P1

### Issue #1: Vertical rate = 0 for descending flights

**Root cause:** The state vector round-trip is correct: `fallback.py:3367` converts ft/min→m/s, `flight_service.py:143` converts m/s→ft/min. The simulation init sets `vertical_rate=-800` (line 2300) and the approach update sets it (line 2579). BUT the update code at line 2579 has: `state.vertical_rate = -800 if state.altitude > target_alt else 0` — if the target waypoint altitude is >= current altitude, `vertical_rate` becomes 0 even during descent. Also, enroute flights (line 2427) get `vertical_rate=random.uniform(-200, 200)` which averages near 0.

**Fix:** In the approach update, compute `vertical_rate` from actual altitude change: `state.vertical_rate = (state.altitude - prev_altitude) / dt * 60` (where dt is in minutes). If no previous altitude is stored, use the descent rate based on distance to target: -800 for high altitude, -400 below 1000ft. For enroute/descending flights, ensure a consistent negative rate. Also store `prev_altitude` on the state for delta computation.

**Files:** `src/ingestion/fallback.py`

### Issue #2: Gate recommendations all identical (96%, 7 min taxi)

**Root cause:** `gate_model.py:_score_gate()` (line 294) scores based on availability (40%), operator match (25%), size compatibility (15%), terminal affinity (10%), proximity bonus (10%). Taxi time is `estimated_taxi_time` field on `GateRecommendation`. Currently a flat value, not computed from actual distance.

**Fix:** In `gate_model.py`, compute `estimated_taxi_time` based on gate terminal distance from active runway. Use gate lat/lon from OSM data to compute haversine distance to runway threshold, then convert to taxi time (assume 15 kts average taxi speed).

**Files:** `src/ml/gate_model.py`

### Issue #4: Baggage progress bar always 0%

**Root cause:** `baggage_generator.py:236` — for arrivals: `loading_progress = 100 if status_counts.get("claimed", 0) > 0 else 0`. If bags are "unloaded" or "on_carousel" but not "claimed", progress is 0. The status flow is: checked_in → loaded → in_transit → unloaded → on_carousel → claimed. For arrived flights, bags are "unloaded"/"on_carousel" but may never reach "claimed" in the simulation.

**Fix:** For arrivals, compute progress as: `(unloaded + on_carousel + claimed) / total * 100`. For departures, the logic is already correct.

**Files:** `src/ingestion/baggage_generator.py`

### Issue #8: FIDS arrival times all clustered at same minute

**Root cause:** Live flights from `get_flights_as_schedule()` (line 389) use deterministic jitter based on `hash(icao24)` with narrow ranges (2-14 min offsets). Future flights from `get_future_schedule()` should have better spread. But the live flights dominate the FIDS display and their scheduled times cluster around now.

**Fix:** In `get_flights_as_schedule()`, widen the jitter ranges for approaching/enroute flights. For approaching flights, use altitude-based ETA (already partially done at line 449-452). For enroute, spread over 20-60 min range (already done at line 454). The main issue is arriving flights at similar phases get similar offsets. Add airline-code hash to diversify timestamps.

**Files:** `src/ingestion/fallback.py`

---

## Sub-phase C: State Management (Issues #5, #10, #16) — P2

### Issue #10: Flight details persist across airport switch

**Root cause:** `loadAirport` in `useAirportConfig.ts` resets config state but doesn't clear `selectedFlightId` in `FlightContext.tsx`. When airport changes, old flight icao24 no longer matches any new flights, so `selectedFlight` becomes null via useMemo (line 38-41). BUT the flight panel may still show stale data if there's a timing issue.

**Fix:** In `App.tsx`, wrap the `loadAirport` call to also call `setSelectedFlight(null)` before loading. Or in `Header.tsx` where `onAirportChange={loadAirport}`, create a wrapper that clears selection first.

**Files:** `app/frontend/src/App.tsx` or `app/frontend/src/components/Header/Header.tsx`

### Issue #5: Ambiguous origin/destination for turnaround flights

**Root cause:** `FlightDetail.tsx:152-153` shows "Origin" and "Destination" labels unconditionally. For a turnaround flight at SFO that arrived from JFK and will depart to DEN, it shows "JFK Origin" and "DEN Destination" — unclear that it's two legs.

**Fix:** For ground-phase flights, change labels to "Arrived from" and "Departing to" instead of "Origin" and "Destination".

**Files:** `app/frontend/src/components/FlightDetail/FlightDetail.tsx`

### Issue #16: Trajectory points differ between 2D and 3D

**Root cause:** Both 2D and 3D views use the same `useTrajectory` hook. The 3D `Trajectory3D` component gets trajectory data from `FlightContext`. If the 3D view doesn't have access to the same trajectory data, it may be a prop-passing issue.

**Fix:** Verify that `Trajectory3D` receives the same trajectory data. Check if the 3D view passes `showTrajectory` and `selectedFlight` context properly. This may already work if FlightContext is shared — investigate and fix if there's a disconnect.

**Files:** `app/frontend/src/components/Map3D/Trajectory3D.tsx`, `app/frontend/src/components/Map3D/Map3D.tsx`

---

## Sub-phase D: 3D Quality (Issues #11, #12, #13, #14) — P3

### Issue #11: Aircraft models are dark silhouettes — no color by phase

**Root cause:** `GLTFAircraft.tsx` applies airline colors to meshes but doesn't color-code by flight phase. The GLTF models apply `MeshStandardMaterial` which responds to lighting. The lighting (ambient=0.6, directional=0.8) should be sufficient. The "dark silhouettes" issue may be because models don't have proper normals or the material properties aren't set well.

**Fix:** Add flight-phase color coding: pass `flight_phase` to `Aircraft3D` → `GLTFAircraft`. Apply a phase-based emissive color or tint: ground=green tint, descending=orange, climbing=blue, cruising=white. Also increase ambient light from 0.6 to 0.8 and add a hemisphere light for better base illumination.

**Files:** `app/frontend/src/components/Map3D/Aircraft3D.tsx`, `app/frontend/src/components/Map3D/GLTFAircraft.tsx`, `app/frontend/src/constants/airport3D.ts`

### Issue #12: Stale context in 3D after airport switch

Same fix as Issue #10 — clearing `selectedFlight` on airport switch handles this.

### Issue #13 & #14: 0 trajectory pts and missing prediction in 3D

**Root cause:** Same as Issue #16 — data passing issue between 2D/3D context.

**Fix:** Ensure `Map3D` passes trajectory/prediction data from the shared `FlightContext`. The 3D view needs to receive and render the same trajectory data the 2D view gets.

**Files:** `app/frontend/src/components/Map3D/Map3D.tsx`

### Issue #15: Aircraft visual clustering

**Fix:** Add altitude-based Y-offset to labels in `Aircraft3D.tsx`. Position `Html` labels at `[0, 2 + altitude_factor, 0]` where `altitude_factor` scales with flight altitude. This provides vertical separation for overlapping aircraft.

**Files:** `app/frontend/src/components/Map3D/Aircraft3D.tsx`

---

## Sub-phase E: Performance (Issues #15cache, #16cache) — Skip

Issues #15 and #16 from the performance section (Lakebase/UC cache) are known infrastructure issues tracked separately. Not fixing in this phase.

---

## Implementation Order

1. **Sub-phase A** (data realism) — highest demo impact
2. **Sub-phase B** (physics) — second highest
3. **Sub-phase C** (state management) — straightforward React fixes
4. **Sub-phase D** (3D quality) — visual polish

## Key Files to Modify

| File | Changes |
|------|---------|
| `src/ingestion/schedule_generator.py` | Add airline scope, validate routes |
| `src/ingestion/fallback.py` | Fix vertical_rate serialization, widen FIDS time jitter |
| `src/ingestion/baggage_generator.py` | Fix arrival progress calculation |
| `src/ml/gate_model.py` | Distance-based taxi time |
| `app/frontend/src/components/GateStatus/GateStatus.tsx` | Fix terminal naming for numeric gates |
| `app/frontend/src/components/FlightDetail/FlightDetail.tsx` | Phase-aware origin/dest labels |
| `app/frontend/src/components/Map3D/Aircraft3D.tsx` | Phase color coding, altitude label offset |
| `app/frontend/src/components/Map3D/GLTFAircraft.tsx` | Phase-based emissive colors |
| `app/frontend/src/components/Map3D/Map3D.tsx` | Better lighting, trajectory data passing |
| `app/frontend/src/constants/airport3D.ts` | Increase lighting intensity |
| `app/frontend/src/App.tsx` or `Header.tsx` | Clear selection on airport switch |

## Verification

1. `uv run pytest tests/ -v` — all existing tests pass
2. `cd app/frontend && npm test -- --run` — all frontend tests pass
3. Deploy and verify:
   - FIDS gates match OSM gate names for KSFO
   - No SWA to DXB or easyJet from MCO
   - KJFK shows "Terminal 1, 2, 4, 5, 7, 8" not A-G
   - Descending flight shows negative vertical rate
   - Baggage bar shows percentage > 0 for arrived flights
   - Flight details close on airport switch
   - Ground flights show "Arrived from / Departing to"
   - 3D aircraft colored by phase, not all dark

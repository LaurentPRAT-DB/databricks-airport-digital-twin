# Performance Optimization Report

**Date:** 2026-06-07
**Scope:** Full codebase (simulation core, support modules, backend API, calibration)
**Status:** Documentation only — no changes implemented

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 0 |
| High | 9 |
| Medium | 11 |
| Low | 8 |
| **Total** | **28** |

---

## High Severity (9 findings)

### H1. Dead code: `_get_approach_queue_position` called but result never used
- **Location:** `src/ingestion/_flight_lifecycle.py:1295`
- **Impact:** O(n² log n) per tick where n = approaching flights (8-12). Completely wasted work — `queue_pos` assigned but never read.
- **Fix:** Delete the line. Effort: **trivial**.

### H2. Approach waypoints recomputed from scratch every tick per approaching flight
- **Location:** `src/ingestion/_approach_departure.py:417` (called from `_flight_lifecycle.py:1280`)
- **Impact:** 5-12 redundant trajectory computations/sec, each with ~14 trig operations. Result is pure (deterministic for given origin_iata + runway).
- **Fix:** Cache by `origin_iata` in module-level dict, clear on airport switch. Effort: **trivial**.

### H3. `_get_osm_primary_runway()` re-fetches config + runs `max()` on every call
- **Location:** `src/ingestion/_approach_departure.py:90-111`
- **Impact:** Called 500+ times/minute across all callers. Data is static per airport session.
- **Fix:** Cache result in module-level variable, invalidate on airport switch. Effort: **trivial**.

### H4. Turnaround target recomputed with `random.uniform` every tick (correctness + perf issue)
- **Location:** `src/ingestion/_flight_lifecycle.py:1049`
- **Impact:** 20-35 multi-function computations per tick, producing non-deterministic departure timing (random jitter each tick). Should be computed once at PARKED entry.
- **Fix:** Add `turnaround_target_s` field to FlightState, compute once. Effort: **small**.

### H5. `_icao_to_iata_map` dict rebuilt from 1180-entry table on every spawn iteration
- **Location:** `src/ingestion/_generation.py:515`
- **Impact:** At startup: 50 × 1180 = 59,000 dict insertions. All to check one conditional.
- **Fix:** Build once at module level or lazily cache. Effort: **trivial**.

### H6. Set union of 5 phase sets created on every `_taxi_speed_factor` call
- **Location:** `src/ingestion/_runway_ops.py:543-549`
- **Impact:** 15-25 ground flights × per tick = 15-25 new set allocations/sec (each copying ~25 icao24 strings). Causes GC pressure over long runs.
- **Fix:** Pre-compute `_ground_movers` set once per tick, or use `itertools.chain` to iterate without allocation. Effort: **small**.

### H7. `_get_approach_queue_position` sorts all approaching aircraft per calling flight per tick
- **Location:** `src/ingestion/_runway_ops.py:635-647`
- **Impact:** O(n² log n) for approach sequencing (called n times, each sorts n items). Combined with `_find_aircraft_ahead_on_approach` = 2× redundant distance computations.
- **Fix:** Compute sorted queue once per tick, share across callers. Effort: **small**. (Note: H1 makes this moot if the call site is dead code — verify before fixing.)

### H8. Synchronous DB calls block asyncio event loop in production mode
- **Location:** `app/backend/services/flight_service.py:108`
- **Impact:** 5-100ms Lakebase + 100-500ms Delta queries block all coroutines (WebSocket, HTTP) while executing. Causes jitter for concurrent requests.
- **Fix:** Wrap with `await asyncio.to_thread(...)`. Pattern already used elsewhere in codebase. Effort: **trivial**.

### H9. Redundant Pydantic round-trip in WebSocket broadcast hot path
- **Location:** `app/backend/api/websocket.py:171-172`
- **Impact:** Every 2s broadcast: 50 Pydantic instantiations + 50 `model_dump()` calls. ~3-5ms wasted per tick.
- **Fix:** Add `get_flights_raw()` to FlightService that returns plain dicts for WS path. Effort: **small**.

---

## Medium Severity (11 findings)

### M1. `_update_parked` computes all turnaround factors every tick unconditionally
- **Location:** `src/ingestion/_flight_lifecycle.py:988-1049`
- **Impact:** 20-35 × 5 function calls per tick, even when flight is 30s into a 45-min turnaround.
- **Fix:** Subsumed by H4 (compute target once). If H4 not done: add early exit when `time_at_gate < 80%` of minimum turnaround.

### M2. `_get_flight_phase_name` creates new 9-entry dict on every call
- **Location:** `src/ingestion/_flight_lifecycle.py:2082`
- **Impact:** 50-80 dict allocations per tick (one per flight in response builder).
- **Fix:** Move dict to module-level constant. Effort: **trivial**.

### M3. `_get_origin_country` called per flight per tick with import + double-lookup
- **Location:** `src/ingestion/_generation.py:645-688`
- **Impact:** 50-80 lookups/tick for a value that never changes per flight.
- **Fix:** Cache `origin_country` on FlightState at creation time. Effort: **trivial**.

### M4. `_get_all_arrival_runway_names` re-parses OSM data per arriving flight
- **Location:** `src/ingestion/_approach_departure.py:261-304`
- **Impact:** 30-60 redundant parses per hour. Result is constant per airport.
- **Fix:** Cache result alongside `_override_arrival_runways`. Effort: **trivial**.

### M5. `_find_aircraft_ahead_on_approach` duplicates distance computations from queue position
- **Location:** `src/ingestion/_runway_ops.py:200-239`
- **Impact:** Combined with H7: 2 × n × n distance calculations per tick for approach sequencing.
- **Fix:** Share sorted queue from H7 fix. Effort: included in H7.

### M6. `_get_parked_heading` iterates all terminal polygon edges per gate operation
- **Location:** `src/ingestion/_taxi_routing.py:536-628`
- **Impact:** Result per gate is constant. Currently computed 2× per flight arrival.
- **Fix:** Precompute at airport-load time, store in dict. Effort: **small**.

### M7. `_gate_to_terminal_edge_distance_m` duplicates polygon iteration done by M6
- **Location:** `src/ingestion/_taxi_routing.py:454-485`
- **Impact:** Same polygon scan done twice per parking operation.
- **Fix:** Combine into single `_compute_gate_orientation()` returning heading + standoff. Effort: **small**.

### M8. Sequential WebSocket sends to all clients
- **Location:** `app/backend/api/websocket.py:91-100`
- **Impact:** Slow client delays all subsequent clients. Linear degradation with client count.
- **Fix:** Replace for-loop with `asyncio.gather()`. Effort: **trivial**.

### M9. Broadcast loop skips no-change optimization in simulation mode
- **Location:** `app/backend/api/websocket.py:139-197`
- **Impact:** Delta computation adds overhead but provides no bandwidth savings (all flights move every tick in sim mode).
- **Fix:** Send full state directly in simulation mode; keep deltas for live mode. Effort: **small**.

### M10. `get_nearby_airports` full O(n) haversine scan on every call (uncalibrated airports)
- **Location:** `src/ingestion/schedule_generator.py:423`
- **Impact:** 300 × 1,180 = ~354K haversine calls per schedule cycle for uncalibrated airports.
- **Fix:** Cache results by `(iata, max_distance_km)`. Effort: **trivial**.

### M11. Gate assignment overlap-check grows quadratically with flight count
- **Location:** `src/ingestion/schedule_generator.py:679-688`
- **Impact:** O(G × F) per assignment. With 50 gates × 300 flights = 15K overlap checks per cycle.
- **Fix:** Exploit chronological insertion order for early-exit. Effort: **small**.

---

## Low Severity (8 findings)

| # | Location | Issue | Fix |
|---|----------|-------|-----|
| L1 | `_generation.py:527-535` | Constant sets recreated inside loop body | Move to module-level `frozenset` |
| L2 | `_generation.py:104` | Faker used only for `hexify` (6-char hex) | Replace with `secrets.token_hex(3)` |
| L3 | `_runway_ops.py:154-168` | `_init_gate_states` creates set comparison on every gate op | Add initialized flag |
| L4 | `websocket.py:91` | stdlib `json.dumps` instead of `orjson` | Add `orjson` for 3-10× faster serialization |
| L5 | `routes.py:127-128` | List slice for web vitals buffer overflow | Use `deque(maxlen=1000)` |
| L6 | `websocket.py:149-163` | Imports inside broadcast loop | Cached by Python, negligible |
| L7 | `schedule_generator.py:329-332` | Airline list/weight rebuild per call | Pool size 7-13, not worth fixing |
| L8 | `auto_calibrate.py:207-243` | Sequential OpenSky API with 24s sleep total | Parallelize with ThreadPoolExecutor (batch/offline only) |

---

## Top 5 Recommended Fixes (effort/reward ranked)

| Rank | Fix | Effort | Reward |
|------|-----|--------|--------|
| 1 | **H1** — Delete dead `queue_pos` line | 1 line delete | Eliminates O(n² log n) wasted computation per tick |
| 2 | **H2+H3** — Cache approach waypoints + primary runway | ~15 lines + invalidation | Eliminates 100+ redundant trig computations/sec |
| 3 | **H8** — `asyncio.to_thread` for DB calls | 2-line change | Unblocks event loop in production mode |
| 4 | **H4** — Compute turnaround target once | Add field + move calc | Fixes correctness bug + eliminates 20-35 useless computations/tick |
| 5 | **H5** — Cache `_icao_to_iata_map` | Move to module level | Eliminates 59K dict insertions at startup |

---

## Implementation Notes

- H1, H2, H3, H5 are independent — can be done in any order
- H4 requires adding a field to `FlightState` dataclass (`src/ingestion/_state.py`)
- H6 benefits from a per-tick pre-computation pattern (compute set at tick start, pass to callees)
- H7 may be dead code if H1 removes the only call site — verify first
- H8 is production-only (demo mode uses mock backend, no DB calls)
- Most caching fixes require invalidation on airport switch via `reset_synthetic_state()`

# Backend Deep Engineering Review — Airport Digital Twin
**Date:** 2026-03-20
**Author:** Claude (Backend Engineer review)
**Scope:** Full backend review — Lakehouse↔Lakebase transitions, caching strategies, sync patterns, pipelines, scheduling, monitoring, live testing

---

## 1. Executive Summary

The backend is well-architected with a solid 3-tier loading pattern (Lakebase → UC → OSM). The recent P0 fixes (connection pooling, RJTT centers, health endpoint, migration retry) resolved the most critical issues. However, significant gaps remain in **cache stampeding**, **first-visit reliability**, **pipeline activation**, **error logging**, and **test execution on Databricks**.

**Key findings:**
- 9 distinct caching mechanisms, 3 with stampede or race condition risks
- First-visit airport activation can **500/502** on uncached airports (VHHH, WSSS observed)
- DLT pipeline has **never been started** — the sync job runs but may sync stale data
- All 3 Databricks test jobs (unit, e2e, integration) have **zero runs recorded**
- Multi-airport simulation batch has a **71% failure rate**
- Zero WARNING/ERROR log entries for airport switch failures — **silent errors**

---

## 2. Data Architecture & Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FastAPI Backend                              │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │ WeatherSvc   │  │ ScheduleSvc  │  │ DataGeneratorSvc         │  │
│  │ (Lakebase→   │  │ (Lakebase→   │  │ (periodic refresh loops) │  │
│  │  Generator)  │  │  Live+Future)│  │ weather/schedule/baggage │  │
│  └──────┬───────┘  └──────┬───────┘  │ /GSE/snapshots → Lakebase│  │
│         │                  │          └──────────┬───────────────┘  │
│         ▼                  ▼                     ▼                  │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │              LakebaseService (PostgreSQL)                    │   │
│  │  ThreadedConnectionPool(2-10) — OAuth + direct modes        │   │
│  │  Tables: flight_status, flight_schedule, weather, baggage,  │   │
│  │          gse_fleet, turnaround, airport_config_cache,        │   │
│  │          user_airport_usage, ML tables (4)                   │   │
│  └──────────────────────────────────────────────────────────────┘   │
│         ▲                                                           │
│         │ write-through on Tier 2/3 loads                          │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │           AirportConfigService (3-Tier Loading)              │   │
│  │  Tier 1: Lakebase cache (JSONB, <1s)                        │   │
│  │  Tier 2: Unity Catalog (SQL Warehouse, 3-9s)                │   │
│  │  Tier 3: OSM Overpass API (external, 10-25s)                │   │
│  └──────────────────────────────────────────────────────────────┘   │
│         ▲                                                           │
│         │ SQL Warehouse queries                                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │           DeltaService (Unity Catalog)                       │   │
│  │  Tables: flight_status_gold, flight_positions_history        │   │
│  │  + AirportRepository (10 config tables)                     │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │           WebSocket Broadcaster                              │   │
│  │  _prev_flights: dict — delta compression per 2s cycle       │   │
│  │  Cleared on airport switch (full refresh to clients)         │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘

External:
┌────────────────────────────────────────────────────────┐
│ Databricks Jobs                                         │
│  - Delta→Lakebase Sync: every 1 min (RUNNING, SUCCESS) │
│  - DLT Pipeline: 6 libraries (IDLE, never started)     │
│  - Realism Scorecard: weekly (PAUSED)                   │
│  - 5 on-demand jobs: sim batch, calibration, tests...  │
└────────────────────────────────────────────────────────┘
```

---

## 3. All Caching Mechanisms (9 found)

| # | Cache | Location | Key | TTL / Invalidation | Thread-Safe? | Issue |
|---|-------|----------|-----|--------------------|-------------|-------|
| 1 | **Airport Config** | `AirportConfigService._current_config` | singleton | Replaced on switch | No lock | Single airport at a time |
| 2 | **Lakebase Config Cache** | `airport_config_cache` table (JSONB) | `icao_code` | **Never expires** | DB-level | No TTL, no staleness check |
| 3 | **Schedule Cache** | `schedule_generator._schedule_cache` | airport IATA | **1-minute window** (`datetime.now().minute`) | **NOT safe** — global dict | **STAMPEDE**: at minute rollover ALL cached airports regenerate simultaneously |
| 4 | **Weather Cache** | `weather_generator._weather_cache` | station | **10-min slots** (`hour*6 + minute//10`) | **NOT safe** — global dict | Same stampede risk at slot boundary |
| 5 | **OAuth Credentials** | `LakebaseService._cached_credentials` | singleton | SDK `expire_time` or 45min fallback, 5-min refresh window | No lock on cache read | OK — single-threaded async |
| 6 | **Connection Pool** | `LakebaseService._pool` | singleton | Invalidated on auth error | `_pool_lock` ✓ | Good |
| 7 | **ML Model Cache** | `AirportModelRegistry._models` | airport ICAO | Retrained on switch | No lock | OK — async single-thread |
| 8 | **Calibration Profile** | `AirportProfileLoader` | lazy singleton | Never expires (static data) | No lock | OK — immutable data |
| 9 | **WS Delta Cache** | `FlightBroadcaster._prev_flights` | `icao24` | Cleared on airport switch | No lock | OK — single event loop |

### Critical Cache Issues

**3A. Schedule Cache Stampede (schedule_generator.py:754-770)**
```python
current_minute = datetime.now(timezone.utc).minute
if _cache_minute != current_minute or airport not in _schedule_cache:
    _schedule_cache[airport] = generate_daily_schedule(...)
    _cache_minute = current_minute
```
When `_cache_minute` changes (every 60s), ALL airports in the cache are invalidated simultaneously because the `_cache_minute != current_minute` check triggers before the `airport not in _schedule_cache` check. This means if 5 airports are cached, the first request after minute rollover regenerates all 5 at once.

**3B. No Lakebase Config TTL**
`airport_config_cache` has an `updated_at` column but it's never checked. Configs cached months ago are served as-is. If OSM data changes (new gates, terminal changes), the stale cache is served indefinitely.

**3C. `_initialized_airports` Set in DataGeneratorService (data_generator_service.py:58)**
```python
self._initialized_airports: set[str] = set()
```
This set tracks which airports have had synthetic data generated. But when Lakebase `has_synthetic_data()` returns True, the airport is added to the set WITHOUT verifying data freshness. Old schedule data from a previous session is treated as current.

---

## 4. Connection Management Assessment

### Lakebase (PostgreSQL)
- **Pool:** `ThreadedConnectionPool(minconn=2, maxconn=10)` — recently added ✓
- **Connection string mode:** Bypasses pool (used in tests/local dev)
- **OAuth mode:** Pool shares credentials; invalidated on auth error ✓
- **Error handling:** Bad connections discarded via `putconn(conn, close=True)` ✓

### Unity Catalog (SQL Warehouse)
- **No pooling:** `DeltaService._get_connection()` creates a new `databricks-sql-connector` connection per query (delta_service.py:42-74)
- **Socket timeout:** 10s — prevents indefinite hangs ✓
- **Auth:** Uses SDK `Config` with ambient M2M credentials — good for Apps context
- **Impact:** UC queries are infrequent (only on cache miss), so pooling is lower priority

### DeltaService vs LakebaseService Pattern Mismatch
Both services are singletons with `_get_connection()`, but DeltaService lacks pooling. Since UC queries happen only on Tier 2 cache miss (rare), this is acceptable. But the `AirportRepository` (in `src/persistence/`) also creates connections per query, and it's called during airport preloading which can be 27 airports in sequence.

---

## 5. Synchronization & Race Conditions

### 5A. Airport Switch Race (routes.py, activate_airport)
The activation endpoint performs multiple sequential steps:
1. Load config (Tier 1→2→3)
2. Reload gates
3. Retrain ML models
4. Set airport center
5. Reset synthetic state
6. Generate synthetic data

If a second activation request arrives while the first is still running, both will mutate shared global state (`_flight_states`, `AIRPORT_CENTER`, `_schedule_cache`). No locking exists on the `activate_airport` endpoint.

**Impact:** Concurrent airport switches from multiple browser tabs could corrupt flight state.

### 5B. Global Mutable State in `fallback.py`
```python
_flight_states: Dict[str, FlightState] = _FlightStateDict()  # line 1599
AIRPORT_CENTER = (37.6213, -122.379)                          # line 695
_loaded_gates: Dict[str, Any] = {}                            # implicit
```
These module-level globals are mutated by both the periodic update loop (every 2s via WebSocket) and the airport switch endpoint. No synchronization primitives protect them.

### 5C. DataGeneratorService Refresh Loops vs Airport Switch
The 5 background tasks (`_weather_refresh_loop`, `_schedule_refresh_loop`, etc.) run continuously with their own airport context (`self._current_airport_icao`). When `switch_airport()` changes the context, the next loop iteration uses the new airport — but any in-flight loop iteration may still be writing data for the old airport.

---

## 6. Pipeline & Job Status

### 6.1 DLT Pipeline
| Property | Value |
|----------|-------|
| Pipeline ID | `ac51a583-2243-4ea5-a638-18d4d748b9f4` |
| State | **IDLE** |
| Mode | Triggered (not continuous), 5-min interval |
| Libraries | 6 (flights bronze/silver/gold + baggage bronze/silver/gold) |
| Ever started? | **No** — no update history found |

**Impact:** The entire DLT medallion architecture exists in code but is dormant. The sync job reads from `flight_status_gold` which may be empty or stale.

### 6.2 Delta-to-Lakebase Sync Job
| Property | Value |
|----------|-------|
| Job ID | `105544756996268` |
| Schedule | Every minute (cron `0 * * * * ?`) |
| Status | **UNPAUSED, RUNNING** |
| Recent runs | All SUCCESS (~52-58s each) |
| Auth | REST API credential generation + notebook token fallback |
| Data flow | `flight_status_gold` → row-by-row UPSERT → `flight_status` |

**Issue:** Row-by-row upserts (one `cur.execute()` per flight) — should use `executemany()` or `execute_values()` for batch performance.

### 6.3 Simulation Batch Job
| Property | Value |
|----------|-------|
| Job ID | `752170313800967` |
| Recent runs | **4 FAILED / 2 SUCCESS / 1 FAILED (71% failure rate)** |
| Timeout | 12 hours |

### 6.4 Test Jobs
| Job | Runs | Status |
|-----|------|--------|
| Python Unit Tests | **0** | Never executed |
| E2E Smoke Tests | **0** | Never executed |
| Baggage Integration Test | **0** | Never executed |

---

## 7. Live Testing Results

### 7.1 Airport Switch Latencies

| Airport | HTTP | Total Time | Server Time | Source | Gates | Finding |
|---------|------|-----------|-------------|--------|-------|---------|
| KSFO | 200 | 1.62s | 1.00s | Tier 1 (Lakebase) | 120 | Baseline |
| KJFK | 200 | 1.54s | 0.91s | Tier 1 (Lakebase) | 137 | Fast |
| EGLL | 200 | 2.00s | 1.14s | Tier 1 (Lakebase) | 142 | Good |
| LFPG | 200 | 2.54s | 1.76s | Tier 1 (Lakebase) | 297 | Slow (most gates) |
| RJTT | 200 | 3.89s | 3.15s | Tier 1 (Lakebase) | 87 | **Anomaly** — slow despite few gates |
| VHHH (1st) | **500** | 9.50s | — | Tier 2 miss→crash | — | **BUG: first-visit crash** |
| VHHH (2nd) | 200 | 2.21s | — | Tier 1 (now cached) | 90 | Works after cache populated |
| WSSS (1st) | **502** | 1.19s | — | — | — | **BUG: server crash from VHHH** |
| WSSS (2nd) | 200 | 4.84s | 2.61s | Tier 2→Tier 1 | 133 | Works on retry |
| KSFO (return) | 200 | 1.51s | 0.77s | Tier 1 (Lakebase) | 120 | 7% faster on return |

### 7.2 Health Endpoint (Post-Fix)
```json
{
    "status": "healthy",
    "lakebase": true,
    "airport": "RJTT",
    "airport_source": "LAKEHOUSE"
}
```
Latency: 0.53-0.57s (median), 1.24s outlier (10 rapid requests).

### 7.3 Error Logs
**Zero WARNING or ERROR entries** found in the log buffer after 500/502 failures. The airport switch failure path either swallows exceptions or logs at DEBUG level.

---

## 8. Bugs Found (New, beyond P0 fixes)

### BUG-5: First-Visit Airport Activation Crashes (500/502)
- **Symptom:** VHHH returned HTTP 500 after 9.5s; WSSS returned 502 after 1.2s
- **Root cause:** When Tier 1 misses and Tier 2 loads, the combined time of UC fetch + config processing + gate reload + ML retrain + schedule generation exceeds some timeout or causes an OOM
- **Impact:** Any airport not in Lakebase cache will fail on first visit
- **Workaround:** Second attempt succeeds (Tier 2 populates Lakebase cache)

### BUG-6: Silent Error Logging on Switch Failure
- **Symptom:** Zero WARNING/ERROR log entries for 500/502 responses
- **Root cause:** The `activate_airport` exception handler logs at `logger.error()` but the error may be caught by middleware before it reaches the handler, or the ring buffer is flushed
- **Impact:** Cannot diagnose production failures

### BUG-7: RJTT Anomalously Slow (3.15s server time for 87 gates)
- **Symptom:** RJTT takes 3x longer than KJFK despite having fewer gates
- **Possible cause:** Lakebase config for RJTT may be larger (more taxiways/aprons), or ML retrain for RJTT takes longer due to missing calibration profile

### BUG-8: Schedule Cache Stampede
- **Symptom:** At minute rollover, all cached airport schedules regenerate simultaneously
- **Impact:** 200-500ms stall for the first request after minute boundary
- **Location:** `schedule_generator.py:754-770`

### BUG-9: Stale DLT Pipeline Config
- `databricks/dlt_pipeline_config.json` references `/mnt/` storage and Photon clusters
- Actual deployed pipeline uses serverless via `resources/pipeline.yml`
- Risk: Someone using the stale config would create a wrong pipeline

---

## 9. Improvement Plan

### P0: Critical (Fix Now)

| # | Issue | Fix | Effort |
|---|-------|-----|--------|
| P0-1 | First-visit crash (BUG-5) | Add timeout + error recovery to `activate_airport`; pre-validate config size before full processing | 2-3h |
| P0-2 | Silent errors (BUG-6) | Add `logger.error()` with traceback in the outer try/except of `activate_airport`; ensure ring buffer captures it | 30min |

### P1: High Priority (This Week)

| # | Issue | Fix | Effort |
|---|-------|-----|--------|
| P1-1 | Schedule cache stampede (BUG-8) | Replace `_cache_minute` with per-airport TTL (`last_generated` timestamp + 60s max age) | 1h |
| P1-2 | Activation race condition (5A) | Add `asyncio.Lock` to `activate_airport` to serialize concurrent switches | 30min |
| P1-3 | Run Databricks test jobs | Execute unit, e2e, integration test jobs at least once to validate | 1h |
| P1-4 | Delete stale DLT config (BUG-9) | Remove `databricks/dlt_pipeline_config.json` | 5min |
| P1-5 | Sync job batch upserts | Replace row-by-row `cur.execute()` with `execute_values()` in sync notebook | 1h |

### P2: Medium Priority (Next Sprint)

| # | Issue | Fix | Effort |
|---|-------|-----|--------|
| P2-1 | Lakebase config TTL | Check `updated_at` on load; if > 24h, background-refresh from UC | 2h |
| P2-2 | DataGenerator airport race (5C) | Snapshot `airport_icao` at start of each refresh loop iteration | 1h |
| P2-3 | DLT pipeline activation | Either start the pipeline or remove the code if not needed | 2h |
| P2-4 | RJTT slowness investigation (BUG-7) | Profile the activation path; check config size, ML retrain timing | 1h |
| P2-5 | Weather cache stampede | Use per-station `last_generated` timestamp like schedule fix | 1h |
| P2-6 | Parallel activation steps | Run gate reload + ML retrain concurrently (they're independent) | 2h |

### P3: Low Priority (Backlog)

| # | Issue | Fix | Effort |
|---|-------|-----|--------|
| P3-1 | UC connection pooling | Add pooling to `DeltaService._get_connection()` (low frequency) | 2h |
| P3-2 | Structured metrics | Add Prometheus `/metrics` endpoint: request durations, tier hit rates, pool utilization | 4h |
| P3-3 | Pre-warm strategy | On startup, pre-warm top-N user airports from Lakebase | 2h |
| P3-4 | Config as code for sync | Replace hardcoded values in sync notebook with bundle variables | 1h |
| P3-5 | Fix simulation batch | Investigate 71% failure rate in multi-airport sim job | 4h |
| P3-6 | Unpause realism scorecard | Re-enable weekly quality monitoring | 5min |

---

## 10. Summary Metrics

| Metric | Value | Status |
|--------|-------|--------|
| Active P0 bugs | 2 (first-visit crash, silent errors) | Needs fix |
| Connection pooling | ThreadedConnectionPool(2-10) | ✅ Good |
| Tier 1 switch time | 0.77-1.76s | ✅ Good |
| Tier 2 switch time | 2.6-9.5s | ⚠️ Can crash |
| Tier 3 switch time | 10-25s | ⚠️ Untested live |
| Caching strategies | 9 mechanisms | ⚠️ 3 have issues |
| DLT Pipeline | IDLE (never started) | ❌ Needs attention |
| Sync Job | Running, 100% success | ✅ Good |
| Test Jobs | 0 runs recorded | ❌ Never executed |
| Simulation Batch | 71% failure rate | ❌ Needs investigation |
| Error observability | Silent on 500/502 | ❌ Needs fix |
| Total tests | 1753 Python + 721 frontend = 2474 | ✅ Good coverage |

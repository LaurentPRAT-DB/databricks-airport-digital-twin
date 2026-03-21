# Backend Engineering Review — Airport Digital Twin
**Date:** 2026-03-20
**Author:** Claude (Backend Engineer review)
**Scope:** Lakehouse↔Lakebase sync, caching, pipelines, scheduling, monitoring, airport switching

---

## 1. Deployment Status

- **Bundle deployed:** `databricks bundle deploy --target dev` ✅
- **App deployed:** `airport-digital-twin-dev` on FEVM Serverless Stable ✅
- **Last deployment:** 2026-03-20T10:47:28Z (SUCCEEDED, SNAPSHOT mode)
- **App URL:** https://airport-digital-twin-dev-7474645572615955.aws.databricksapps.com

---

## 2. Data Architecture & 3-Tier Loading

### Architecture Overview
```
Frontend (React) ←→ FastAPI Backend ←→ 3-Tier Data Sources
                                        ├── Tier 1: Lakebase Autoscaling (Postgres, <1s)
                                        ├── Tier 2: Unity Catalog (Delta via SQL Warehouse, 4-8s)
                                        └── Tier 3: OSM Overpass API (external, 10-25s)
```

### Loading Flow (`AirportConfigService.initialize_from_lakehouse`)
- **Tier 1 → Tier 2 write-through**: When UC loads succeed, config is auto-cached to Lakebase
- **Tier 3 → Both write-through**: OSM loads persist to both UC and Lakebase
- **No TTL/invalidation**: Cached configs are never expired or invalidated automatically

### Measured Latencies (from live app)

| Airport | Tier | Source | Load Time | Notes |
|---------|------|--------|-----------|-------|
| KSFO | 1 | Lakebase | 1.82s | Including gate reload + ML retrain |
| KJFK | 1 | Lakebase | 1.95s | |
| EGLL | 1 | Lakebase | 2.33s | Large config (417 taxiways) |
| LFPG | 1 | Lakebase | 2.84s | |
| EGLL | 2 | Unity Catalog | ~8.6s | First load (before Lakebase cache) |
| LFPG | 2 | Unity Catalog | ~4.0s | First load |
| RJTT | 2 | Unity Catalog | ~3.3s | **Fails after load** (see bug below) |
| KLHR | 3 | OSM API | ~16s | Not in UC, fetched from Overpass |

**Finding:** Tier 1 (Lakebase) adds ~0.5-1.2s for the Postgres query itself. Total switch time is 1.8-2.8s including gate reload, ML model retrain, schedule regeneration, and WebSocket broadcast. This is excellent for cached airports.

---

## 3. Caching Strategies

### 3.1 Airport Config Cache (Lakebase `airport_config_cache` table)
- **Type:** JSONB column, keyed by `icao_code`
- **Write-through:** Populated on UC or OSM load
- **Invalidation:** None (stale forever unless manually refreshed via `/airports/{icao}/reload`)
- **Coverage:** 27 well-known airports all cached (confirmed via preload status)

### 3.2 OAuth Credential Cache (`LakebaseService._cached_credentials`)
- **Type:** In-memory tuple (token, user)
- **TTL:** Uses `expire_time` from SDK response, fallback to 45 minutes
- **Refresh window:** 5 minutes before expiry
- **Auth error handling:** Credentials cleared on auth-related psycopg2 errors (not SQL errors)

### 3.3 Schedule Cache (`_schedule_cache` in `schedule_generator.py`)
- **Type:** In-memory dict keyed by airport IATA code
- **TTL:** Regenerated every minute (keyed on `datetime.now().minute`)
- **Invalidation:** `invalidate_schedule_cache()` called on airport switch
- **Issue:** Uses `datetime.now().minute` — at minute rollover, ALL cached airports regenerate simultaneously

### 3.4 Weather Cache (`_weather_cache` in `weather_generator.py`)
- **Type:** In-memory dict keyed by station
- **TTL:** Regenerated every 10 minutes (using `hour * 6 + minute // 10` slots)

### 3.5 ML Model Cache (`AirportModelRegistry`)
- **Type:** In-memory dict per airport ICAO
- **TTL:** None — trained on first access, retrained on airport switch

### 3.6 Calibration Profile Cache (`AirportProfileLoader`)
- **Type:** Lazy singleton, loads known profiles from `known_profiles.py`

### 3.7 Schema Migration Flags
- `_airport_columns_ensured`, `_ml_tables_ensured`: One-time per service lifetime
- Run `ALTER TABLE ADD COLUMN IF NOT EXISTS` and `CREATE TABLE IF NOT EXISTS`
- Good: Prevents repeated DDL on every request. Bad: If migration fails, silently marks as done.

---

## 4. Connection Management

### ~~Critical Issue: No Connection Pooling~~ — RESOLVED

**Before:** `LakebaseService._get_connection()` created a new psycopg2 connection per query, adding 50-100ms TCP+TLS overhead per call.

**After:** `ThreadedConnectionPool(minconn=2, maxconn=10)` reuses connections. Pool is lazily created on first use, invalidated on auth errors, and falls back to direct connect if pool creation fails. Connection string mode still bypasses the pool.

### Unity Catalog Connection
- `AirportRepository` uses `databricks-sql-connector` or `WorkspaceClient` statement execution
- SQL connector creates a new connection per `_execute_via_connector` call (same pattern)
- UC loads use `ThreadPoolExecutor(max_workers=10)` for parallel table queries (good)

---

## 5. Pipelines & Scheduling

### 5.1 DLT Pipeline (`airport_dlt_pipeline`)
- **Libraries:** 6 (flights bronze/silver/gold, baggage bronze/silver/gold)
- **Trigger interval:** Every 5 minutes
- **Mode:** Not continuous (`continuous: false`), serverless
- **Channel:** CURRENT
- **Status:** Defined but likely idle (no recent data to process — synthetic data is generated in-app, not ingested through DLT)

### 5.2 Delta-to-Lakebase Sync Job (ID: 105544756996268)
- **Schedule:** Every minute (`0 * * * * ?`)
- **What it does:** Reads `flight_status_gold` from UC, upserts to Lakebase `flight_status` table
- **Known issue:** Uses REST API for Lakebase credential generation (`/api/2.0/lakebase/postgres/credentials/generate`) — this may fail in notebook context without proper OAuth setup
- **Timeout:** 5 minutes
- **Status:** No recent successful runs visible (likely failing or paused)

### 5.3 Other Jobs
| Job | Schedule | Status |
|-----|----------|--------|
| OSM Pre-load | Manual (no schedule) | Available |
| Calibration Batch (132 sims) | Manual | Available |
| Multi-Airport Simulation Batch | Manual | Available |
| OBT Model Training | Manual | Available |
| Realism Scorecard | Manual | Available |
| Python Unit Tests | Manual | Available |
| E2E Smoke Tests | Manual | Available |
| Baggage Integration Test | Manual | Available |

**Finding:** Only the sync job has a schedule. The DLT pipeline has a trigger interval but `continuous: false` means it only runs when manually started. All other jobs are on-demand.

---

## 6. Monitoring & Observability

### Current
- **RingBufferHandler:** In-memory ring buffer (2000 lines), queryable via `/api/logs`
- **Log filtering:** Supports `level`, `search`, and `n` parameters
- **Data Ops dashboard:** Frontend component for pipeline health monitoring

### Missing
- **No structured metrics** (Prometheus, StatsD, etc.)
- **No alerting** on sync failures, tier fallback frequency, or Lakebase connection issues
- **No performance tracing** (no request duration histograms)
- ~~**No health check for Lakebase**~~ — RESOLVED: `/health` now returns lakebase status, airport, and source
- **Log rotation:** Ring buffer only keeps 2000 lines — a busy session can flush history in minutes

---

## 7. Bugs Found

### ~~BUG-1: RJTT (Tokyo Haneda) Switch Fails~~ — RESOLVED (P0 Fix #2)
- **Root cause:** `AIRPORT_COORDINATES` dict in `schedule_generator.py` has NRT (Narita) but **not HND (Haneda)**. RJTT maps to IATA "HND" via `_icao_to_iata()`, and "HND" isn't in the dict.
- **The config loaded from UC doesn't have a `center` key** (the OSM-to-config converter doesn't compute center from gate/terminal centroids).
- **Impact:** Any airport whose IATA code isn't in `AIRPORT_COORDINATES` AND whose UC/Lakebase config doesn't have `center` will fail.
- **Fix:** Either add HND to `AIRPORT_COORDINATES`, or compute center from the loaded config's gate/terminal coordinates as a fallback.

### ~~BUG-2: Health Endpoint Returns Empty `{}`~~ — RESOLVED (P0 Fix #3)
- **Location:** The `/api/health` endpoint returns `{}` without auth, `{"error": "Not found"}` with auth.
- **Impact:** No way to monitor app health from external systems.

### ~~BUG-3: Sync Job~~ — RESOLVED (Running Successfully)
- **Initial assessment:** Suspected sync job was failing due to OAuth issues in notebook context.
- **Actual status:** Job runs every minute and completes successfully in ~52-58 seconds. Verified via `databricks jobs list-runs` — last 5 runs all SUCCESS.
- **Conclusion:** The Lakebase credential generation via REST API is working correctly in the notebook context. No fix needed.

### ~~BUG-4: Schema Migration Silently Marks as Done on Failure~~ — RESOLVED (P0 Fix #4)
- `_ensure_airport_columns()` catches ALL exceptions and sets `_airport_columns_ensured = True` regardless.
- If the first call fails due to a transient network error, the columns are never added but the flag prevents retrying.

---

## 8. Improvement Plan

### Priority 1: Critical Fixes (P0)

#### ~~1.1 Add Connection Pooling for Lakebase~~ — DONE
- ThreadedConnectionPool (2-10) added, ~15-20% improvement in switch times

#### ~~1.2 Fix RJTT and All Missing Airport Centers~~ — DONE
- Center computed from OSM centroid + fallback from gate/terminal geo coordinates

#### ~~1.3 Fix Sync Job Authentication~~ — NOT NEEDED
- Sync job is running successfully (every minute, ~52-58s, SUCCESS status)
- REST API credential generation works correctly in notebook context

#### ~~1.4 Fix Health Endpoint~~ — DONE
- Returns lakebase status, airport code, source tier

### Priority 2: Performance (P1)

#### 2.1 Schedule Cache Stampede Prevention
- Current: ALL airport schedules regenerate simultaneously at minute rollover
- Fix: Use per-airport TTL with staggered expiry, or lazy regeneration with `max_age` check

#### 2.2 Lakebase Config Cache with TTL
- Current: No TTL, configs cached forever
- Add `updated_at` check: if older than 24h, refresh from UC in background
- Add cache warming on app startup for recently-used airports

#### 2.3 Parallel Airport Switch Steps
- Currently sequential: load config → reload gates → retrain ML → set center → reset state
- ML retrain and gate reload can run in parallel since they're independent

### Priority 3: Reliability (P2)

#### ~~3.1 Schema Migration Retry Logic~~ — DONE
- Flag only set after commit, max 3 retries before giving up

#### 3.2 DLT Pipeline Activation
- The DLT pipeline is defined but `continuous: false` and no schedule
- Either set `continuous: true` for real-time processing, or add a schedule
- Currently unused because all data is synthetic (generated in-app)

#### 3.3 Structured Logging & Metrics
- Add request duration logging for all API endpoints
- Track tier hit rates (Lakebase vs UC vs OSM)
- Track Lakebase connection pool utilization
- Add Prometheus-compatible `/metrics` endpoint

### Priority 4: Architecture (P3)

#### 4.1 Eliminate Per-Connection Auth for Lakebase
- Each connection does a full OAuth token generation (even with caching)
- With connection pooling, connections can reuse the same auth session

#### 4.2 Pre-warm Strategy
- Current: 27 airports cached in UC, write-through to Lakebase on first access
- After app restart, Lakebase cache may be warm but app startup only loads one airport
- Add startup phase that pre-warms top-N user airports from Lakebase

#### 4.3 Configuration as Code for Sync
- Sync notebook has hardcoded catalog/host/endpoint values
- Should use `dbutils.widgets` or bundle variables

---

## 9. P0 Fixes Applied (2026-03-20)

### Fix 1: Connection Pooling for Lakebase — RESOLVED
- Added `psycopg2.pool.ThreadedConnectionPool` (min=2, max=10)
- `_get_connection()` now uses pool for credential-based connections
- Connection string mode bypasses pool (unchanged behavior)
- Pool invalidated automatically on auth errors
- `close_pool()` method for clean shutdown

### Fix 2: RJTT / Missing Airport Centers — RESOLVED
- **OSM converter** (`converter.py`): Now includes `center` key in output from centroid computation
- **Routes.py**: Added `_compute_center_from_config()` as final fallback — computes center from gate/terminal geo coordinates
- **Result:** RJTT now loads successfully (10.5s from OSM, first time)

### Fix 3: Health Endpoint — RESOLVED
- Now returns: `{"status": "healthy", "lakebase": true/false, "airport": "KSFO", "airport_source": "LAKEHOUSE"}`
- Uses existing `lakebase.health_check()` method
- Graceful degradation when Lakebase unavailable

### Fix 4: Schema Migration Silent Failure — RESOLVED
- `_ensure_airport_columns()` and `_ensure_ml_tables()` no longer mark as "ensured" on failure
- Added retry counter (max 3 attempts before giving up)
- Flag only set after successful `conn.commit()`

### Post-Fix Measurements

| Airport | Source | Switch Time | Notes |
|---------|--------|------------|-------|
| KSFO | Lakebase (cached) | 1.62s | Improved from 1.82s |
| KJFK | Lakebase (cached) | 1.47s | Improved from 1.95s |
| EGLL | Lakebase (cached) | 1.95s | Improved from 2.33s |
| LFPG | Lakebase (cached) | 2.47s | Improved from 2.84s |
| RJTT | Lakebase (cached) | 10.47s | **Previously FAILED**, now works (OSM load) |

Health endpoint latency: ~0.55s (consistent across 5 rapid requests, includes network RTT)

---

## 10. Summary Metrics

| Metric | Value |
|--------|-------|
| App deployment | SUCCEEDED |
| Tier 1 (Lakebase) switch time | 1.5-2.5s (improved ~15-20%) |
| Tier 2 (UC) switch time | 3-9s |
| Tier 3 (OSM) switch time | 10-25s |
| Lakebase Postgres query time | ~0.5-1.0s (with pooling) |
| Cached airports in lakehouse | 27/27 (100%) |
| Sync job status | Running (every ~55s, SUCCESS) |
| DLT pipeline status | Defined, not scheduled |
| Connection pooling | **ThreadedConnectionPool (2-10)** |
| Active bugs | **0 P0 bugs** (all 3 resolved) |
| Scheduled jobs | 1 (sync) |
| Manual jobs | 8 |
| Tests | 1753 Python passed + 721 frontend passed = 2474 total |

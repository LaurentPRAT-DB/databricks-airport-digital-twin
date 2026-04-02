# Plan: Lakebase Read Replica Auto-Discovery

**Status:** Backlog
**Date added:** 2026-04-02
**Files:** `app/backend/services/lakebase_service.py`

---

## Context

The user added a read replica to their Lakebase Autoscaling instance. The LakebaseService currently uses a single connection pool pointing to the primary (read-write) host. By routing SELECT queries to the read replica, we reduce load on the primary and improve read latency.

The Databricks SDK exposes the replica host via `endpoint.status.hosts.read_only_host` — no new env vars needed; the service can auto-discover it at startup.

## Approach

Add a second connection pool (`_read_pool`) for read-only queries. On init, call `w.postgres.get_endpoint(...)` to discover `read_only_host`. If found, create a dedicated read pool; if not, fall back to the primary pool for everything.

## Changes

### 1. Auto-discover read replica host at init

In `__init__`, add `self._read_host: Optional[str] = None`. Add a `_discover_read_replica()` method that:

```python
def _discover_read_replica(self) -> Optional[str]:
    """Auto-discover Lakebase read replica host via SDK."""
    if not self._use_oauth or not self._endpoint_name:
        return None
    try:
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient()
        ep = w.postgres.get_endpoint(name=self._endpoint_name)
        ro_host = ep.status.hosts.read_only_host
        if ro_host:
            logger.info("Lakebase read replica discovered: %s", ro_host)
            return ro_host
    except Exception as e:
        logger.debug("Read replica discovery failed: %s", e)
    return None
```

Call this lazily on first read connection request (not in `__init__` to avoid blocking startup).

### 2. Add a read-only connection pool

- `self._read_pool: Optional[ThreadedConnectionPool] = None`
- `_get_or_create_read_pool()` — same as `_get_or_create_pool()` but uses `self._read_host`
- `_invalidate_pool()` also tears down `_read_pool`

### 3. Add `_get_read_connection()` context manager

```python
@contextmanager
def _get_read_connection(self):
    """Get a connection for read-only queries. Uses read replica if available."""
    # Try read pool first, fall back to primary
    ...
```

### 4. Route read methods to replica

Replace `self._get_connection()` with `self._get_read_connection()` in these read-only methods:

- `get_flights()`
- `get_flight_by_icao24()`
- `get_weather()`
- `get_schedule()`
- `get_baggage_stats()`
- `get_gse_fleet()`
- `get_airport_config()`
- `get_user_top_airports()`
- `get_cached_airport_codes()`
- `get_turnaround()`
- `get_cached_tile()`
- `get_tile_cache_stats()`

Write methods (`upsert_*`, `insert_*`, `delete_*`, `_ensure_*`) stay on primary.

## What NOT to change

- No new env vars — auto-discovered from SDK
- No changes to `app.yaml` or `resources/`
- No changes to routes or other services — the split is internal to LakebaseService

## Verification

1. Run existing lakebase tests: `uv run pytest tests/test_lakebase_service.py tests/test_lakebase_sync.py -v`
2. Check logs for "read replica discovered" message on startup
3. Verify read methods work when replica is unavailable (graceful fallback to primary)

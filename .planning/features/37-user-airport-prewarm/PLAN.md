# Plan: Per-User Airport Usage Tracking & Lakebase Pre-warming

## Context

The 3-tier airport loading is: Lakebase (<10ms) → UC (30-60s) → OSM (external). All 27 airports are now in UC thanks to the preload job, but Lakebase cache may not have them all (e.g., after redeployment or first-time access). Currently there's no user awareness — when a user opens the app, there's no way to know which airports to prioritize for Lakebase pre-warming.

## Goal

Track which airports each user accesses, then on session start, proactively pre-warm their most-used airports from UC → Lakebase so they load in <10ms instead of 30-60s.

## Architecture

```
User opens app → frontend calls POST /api/user/prewarm
  → backend looks up user's top-N airports from user_airport_usage table
  → for each: checks if already in airport_config_cache (Lakebase)
  → if missing: loads from UC → writes to Lakebase (background)

User switches airport → POST /api/airports/{icao}/activate
  → loads config via 3-tier (now likely Lakebase hit)
  → records usage: UPSERT into user_airport_usage
```

## Plan

### 1. Extract user identity from Databricks App headers

**File:** `app/backend/api/deps.py` (new)

Databricks Apps inject `X-Forwarded-Email` and `X-Forwarded-User` headers via their proxy. Create a FastAPI dependency:

```python
def get_current_user(request: Request) -> str:
    """Extract user email from Databricks App proxy headers."""
    email = request.headers.get("X-Forwarded-Email")
    if email:
        return email
    user = request.headers.get("X-Forwarded-User")
    if user:
        return user
    return "anonymous"
```

### 2. Add user_airport_usage table + methods to Lakebase

**File:** `app/backend/services/lakebase_service.py`

Add table creation + CRUD methods to `LakebaseService`:

```sql
CREATE TABLE IF NOT EXISTS user_airport_usage (
    user_email VARCHAR(255),
    icao_code VARCHAR(10),
    access_count INT DEFAULT 1,
    last_accessed_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_email, icao_code)
)
```

New methods:
- `record_airport_usage(user_email, icao_code)` — UPSERT: increment access_count, update last_accessed_at
- `get_user_top_airports(user_email, limit=5)` — SELECT top N by access_count DESC
- `get_cached_airport_codes()` — SELECT all icao_code from airport_config_cache (what's already warm)

### 3. Record usage on airport activation

**File:** `app/backend/api/routes.py` — `activate_airport` endpoint (line 818)

After successful config load, record usage in background (non-blocking):

```python
async def activate_airport(icao_code: str, user: str = Depends(get_current_user)):
    # ... existing load logic ...
    # Record usage (fire-and-forget)
    lakebase = get_lakebase_service()
    if lakebase.is_available:
        asyncio.create_task(asyncio.to_thread(
            lakebase.record_airport_usage, user, icao_code
        ))
```

### 4. Add pre-warm endpoint

**File:** `app/backend/api/routes.py`

`POST /api/user/prewarm`

Logic:
1. Get user email from request headers
2. Query `user_airport_usage` for user's top 5 airports
3. If no usage history (new user), use default airport from `DEMO_DEFAULT_AIRPORT` env var
4. Check which are already in `airport_config_cache` (Lakebase)
5. For any missing: load from UC → Lakebase via `AirportConfigService.load_from_lakehouse()` + `save_to_lakebase_cache()` in background
6. Return immediately with pre-warm status

### 5. Frontend: fire prewarm on app mount

**File:** `app/frontend/src/hooks/useAirportConfig.ts`

In the `useEffect` on mount (line 661), also fire `POST /api/user/prewarm`. Fire-and-forget — doesn't block the UI.

```typescript
useEffect(() => {
    refresh();
    fetch(`${API_BASE}/api/user/prewarm`, { method: 'POST' }).catch(() => {});
}, [refresh]);
```

## Files to Create/Modify

| Action | File | Purpose |
|--------|------|---------|
| Create | `app/backend/api/deps.py` | `get_current_user()` dependency |
| Modify | `app/backend/services/lakebase_service.py` | `user_airport_usage` table + 3 new methods |
| Modify | `app/backend/api/routes.py` | Record usage in `activate_airport` + add `/api/user/prewarm` |
| Modify | `app/frontend/src/hooks/useAirportConfig.ts` | Fire prewarm on mount |

## Verification

1. `uv run pytest tests/ -v -x -k "lakebase or airport_config"` — no regressions
2. `cd app/frontend && npm test -- --run` — frontend tests pass
3. Deploy, switch airports → verify `user_airport_usage` table populates in Lakebase
4. Restart app → verify prewarm fires and loads user's airports from Lakebase (<10ms)

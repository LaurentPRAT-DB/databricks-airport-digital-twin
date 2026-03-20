# Plan: Fix Lakebase Auth for Service Principal

## Context

The deployed Databricks App's service principal (79ea25c2-52d3-462e-b03c-357c14daaa00) gets "password authentication failed" when connecting to Lakebase Postgres. This causes every Lakebase operation to fail — airport config cache, flight snapshots, schedule persistence, etc. All falls through to UC (Tier 2) or OSM (Tier 3).

**Root cause (DB-level):** The service principal had no Postgres role in the Lakebase database. Already fixed — role created and permissions granted via SQL:
```sql
CREATE ROLE "79ea25c2-..." LOGIN;
GRANT ALL ON DATABASE databricks_postgres TO "79ea25c2-...";
GRANT ALL ON SCHEMA public TO "79ea25c2-...";
GRANT ALL ON ALL TABLES IN SCHEMA public TO "79ea25c2-...";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO "79ea25c2-...";
```

**Remaining code issue:** OAuth credentials are cached forever in `_cached_credentials` but expire after 1 hour. After 1 hour, the app silently fails on every Lakebase connection until restart.

---

## Changes

### 1. Add credential expiry tracking (`lakebase_service.py`)

Store the credential expiry time alongside the cached credentials. Refresh when within 5 minutes of expiry.

```python
# In _get_oauth_token: also return expire_time
def _get_oauth_token(endpoint_name: str) -> Optional[tuple[str, str, str]]:
    # Returns (token, user, expire_time) instead of (token, user)
    cred = w.postgres.generate_database_credential(endpoint=endpoint_name)
    me = w.current_user.me()
    return (cred.token, me.user_name, cred.expire_time)

# In LakebaseService.__init__:
self._cached_credentials: Optional[tuple[str, str]] = None
self._credential_expiry: Optional[datetime] = None

# In _get_credentials:
def _get_credentials(self) -> Optional[tuple[str, str]]:
    if self._use_oauth and self._endpoint_name:
        now = datetime.now(timezone.utc)
        # Refresh if no cached creds or within 5 min of expiry
        if (self._cached_credentials is None or
                self._credential_expiry is None or
                now >= self._credential_expiry - timedelta(minutes=5)):
            result = _get_oauth_token(self._endpoint_name)
            if result:
                token, user, expire_time = result
                self._cached_credentials = (token, user)
                self._credential_expiry = _parse_expiry(expire_time)
            else:
                self._cached_credentials = None
                self._credential_expiry = None
        return self._cached_credentials
    ...
```

### 2. Update memory file

Update `project_lakebase_cache_broken.md` to reflect that the issue is now fixed.

---

## Files to Modify

| File | Change |
|------|--------|
| `app/backend/services/lakebase_service.py` | Add credential expiry tracking, refresh before expiry |
| `memory/project_lakebase_cache_broken.md` | Mark as resolved |

---

## Verification

1. Redeploy: `databricks bundle deploy --target dev && databricks apps deploy ...`
2. Check logs: `/api/logs?search=Lakebase` — should show successful connections instead of auth failures
3. Switch airports in UI — Tier 1 (Lakebase) should now serve cached airports
4. Wait 1+ hour and verify credentials auto-refresh (or check logs for refresh messages)

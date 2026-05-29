# OpenSky Network API Integration

## Overview

The Airport Digital Twin integrates with the [OpenSky Network](https://opensky-network.org/) REST API to fetch real-time ADS-B flight position data. This document focuses on the **authentication path** — how credentials are resolved, stored, and used at runtime.

---

## Authentication Architecture

```
┌─────────────────────────────────────────────────────────────-┐
│                  Credential Resolution Chain                 │
│                                                              │
│  1. Databricks Secrets (preferred, secure)                   │
│     scope: airport-digital-twin                              │
│     keys:  opensky-client-id / opensky-client-secret         │
│            ↓ (if found → OAuth2 client_credentials flow)     │
│                                                              │
│  2. Environment Variables — OAuth2                           │
│     OPENSKY_CLIENT_ID + OPENSKY_CLIENT_SECRET                │
│            ↓ (if found → OAuth2 client_credentials flow)     │
│                                                              │
│  3. Environment Variables — Basic Auth                       │
│     OPENSKY_USERNAME + OPENSKY_PASSWORD                      │
│            ↓ (if found → HTTP Basic Auth)                    │
│                                                              │
│  4. Anonymous (no credentials)                               │
│     Lower rate limits: 10 req / 10 sec                       │
└────────────────────────────────────────────────────────────-─┘
```

The resolution happens once at service initialization (singleton pattern) in `_resolve_opensky_credentials()` at `app/backend/services/opensky_service.py:452`.

---

## Authentication Methods

### Method 1: OAuth2 Client Credentials (Preferred)

Used when `client_id` and `client_secret` are available.

**Token endpoint:**
```
https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token
```

**Flow:**
1. POST to token endpoint with `grant_type=client_credentials`
2. Receive `access_token` in response
3. Attach as `Authorization: Bearer <token>` header on API calls

**Code path:** `OpenSkyService._get_token()` → line 250

The token is cached in-memory (`self._token`) for the lifetime of the service. No refresh logic — if the token expires, the next request will fail and the service logs a warning.

### Method 2: HTTP Basic Auth (Legacy/Free Tier)

Used when only `OPENSKY_USERNAME` and `OPENSKY_PASSWORD` are set (no OAuth2 credentials).

Passed as `auth=(username, password)` tuple to httpx. OpenSky's free tier accounts use this method.

### Method 3: Anonymous

No credentials. Subject to the strictest rate limits (10 requests per 10 seconds). The service logs a warning at startup.

---

## Credential Storage

### Production (Databricks App)

Credentials are stored in **Databricks Secrets**:

| Scope | Key | Purpose |
|-------|-----|---------|
| `airport-digital-twin` | `opensky-client-id` | OAuth2 client ID |
| `airport-digital-twin` | `opensky-client-secret` | OAuth2 client secret |

Referenced in `app.yaml` (line 80-82) as a comment — no plaintext values in config. The app resolves them at runtime using the Databricks SDK:

```python
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
client_id = w.dbutils.secrets.get(scope="airport-digital-twin", key="opensky-client-id")
```

The service principal running the app needs `READ` permission on the `airport-digital-twin` secret scope. This is granted by `scripts/grant_sp_permissions.sh`.

### Local Development

Credentials in `.env` file (loaded via `python-dotenv`):

```bash
OPENSKY_USERNAME=<your-username>
OPENSKY_PASSWORD=<your-password>
# Or for OAuth2:
# OPENSKY_CLIENT_ID=<client-id>
# OPENSKY_CLIENT_SECRET=<client-secret>
```

---

## How the Token is Used

Once resolved, the token (or basic auth) is applied in `fetch_flights()` at line 296:

```python
headers = {}
auth = None
token = await self._get_token()
if token:
    headers["Authorization"] = f"Bearer {token}"
elif self._username and self._password:
    auth = (self._username, self._password)

response = await self._client.get(OPENSKY_API_URL, params=params, headers=headers, auth=auth)
```

The same pattern is reused in `enrich_origins_opensky()` (line 559) for the flights/aircraft lookup endpoint.

---

## Rate Limiting & Backoff

| Auth Level | Rate Limit |
|-----------|-----------|
| Anonymous | 10 req / 10 sec |
| Basic Auth (free account) | Higher (undocumented) |
| OAuth2 (registered app) | Best available |

When a **429** response is received:
- `fetch_flights()` returns empty list, sets `_last_error = "Rate limited"`
- `OpenSkyCollector` implements exponential backoff: 10s base, 2x multiplier, 300s cap
- Backoff resets on successful fetch

---

## Service Lifecycle

```
App startup
    └─ get_opensky_service() called (first request or collector start)
        └─ _resolve_opensky_credentials()
            └─ Try Databricks secrets → env OAuth2 → env basic → anonymous
        └─ OpenSkyService(client_id, client_secret, username, password)
            └─ httpx.AsyncClient created (reused for all requests)
```

The service is a **module-level singleton** (`_opensky_service`). It persists for the lifetime of the FastAPI process.

---

## Diagnostic Endpoint

`GET /api/opensky/diag` tests connectivity end-to-end:
1. DNS resolution of `opensky-network.org`
2. General egress test (httpbin.org)
3. OpenSky API call with bounding box
4. Reports `authenticated: true/false` in service status

Use this to debug auth issues on deployed environments.

---

## Status Endpoint

`GET /api/opensky/status` returns:

```json
{
  "available": true,
  "reachable": true,
  "last_fetch_time": "2026-05-29T10:00:00Z",
  "last_flight_count": 42,
  "last_error": null,
  "authenticated": true
}
```

The `authenticated` field indicates whether OAuth2 credentials were loaded (not whether the token is valid).

---

## Key Files

| File | Role |
|------|------|
| `app/backend/services/opensky_service.py` | Service class, auth resolution, API calls |
| `app/backend/services/opensky_collector.py` | Background multi-airport poller |
| `app/backend/api/opensky.py` | FastAPI router (endpoints) |
| `app.yaml:80-82` | Secret scope reference (comment) |
| `scripts/grant_sp_permissions.sh` | Grants SP access to secret scope |
| `.env` | Local dev credentials |

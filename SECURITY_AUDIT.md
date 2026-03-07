# Security Audit Report

**Project:** Airport Digital Twin
**Date:** 2026-03-07
**Auditor:** Automated Security Review

---

## Executive Summary

| Severity | Count | Status |
|----------|-------|--------|
| CRITICAL | 0 | **FIXED** |
| HIGH | 3 | Needs Fix |
| MEDIUM | 4 | Review |
| LOW | 3 | Advisory |
| INFO | 4 | Informational |

---

## CRITICAL Vulnerabilities

### CRIT-01: SQL Injection in Delta Service - **FIXED** (2026-03-07)

**File:** `app/backend/services/delta_service.py`
**Lines:** 131-148, 185-205

**Status:** **RESOLVED** - All queries now use parameterized queries.

**Previous Vulnerable Code:**
```python
safe_icao24 = icao24.replace("'", "''")  # Insufficient!
query = f"""
    SELECT ... FROM {self._catalog}.{self._schema}.flight_status_gold
    WHERE icao24 = '{safe_icao24}'
"""
```

**Fixed Code:**
```python
query = f"""
    SELECT ... FROM {self._catalog}.{self._schema}.flight_status_gold
    WHERE icao24 = :icao24
"""
cursor.execute(query, {"icao24": icao24})
```

**Methods Fixed:**
- `get_flights()` - limit parameter now uses `:limit`
- `get_flight_by_icao24()` - icao24 parameter now uses `:icao24`
- `get_trajectory()` - icao24 and limit parameters now parameterized, minutes validated as int

---

## HIGH Vulnerabilities

### HIGH-01: Overly Permissive CORS Policy

**File:** `app/backend/main.py`
**Lines:** 29-35

**Description:**
CORS is configured to allow ALL origins with credentials:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,  # DANGEROUS with wildcard!
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Impact:** Any website can make authenticated requests to the API, enabling CSRF attacks.

**Recommendation:**
Restrict origins to specific allowed domains:
```python
allow_origins=["https://airport-digital-twin-dev-xxx.aws.databricksapps.com"]
```

---

### HIGH-02: Vulnerable esbuild/Vite (CVE-2024-xxxx)

**Package:** `esbuild <=0.24.2`, `vite 0.11.0-6.1.6`
**Severity:** Moderate (CVSS 6.1)

**Description:**
Development server vulnerability allows any website to send requests and read responses.

**npm audit output:**
```
esbuild enables any website to send any requests to the development
server and read the response
GHSA-67mh-4wv8-2f99
```

**Impact:** In development mode, local files can be exfiltrated.

**Recommendation:**
```bash
cd app/frontend && npm audit fix --force
# Or manually: npm install vite@^7.0.0
```

---

### HIGH-03: Missing Authentication on API Endpoints

**Files:** All routes in `app/backend/api/`

**Description:**
All API endpoints are publicly accessible without authentication:
- `/api/flights` - Flight data
- `/api/flights/{icao24}/trajectory` - Trajectory history
- `/api/predictions/*` - ML predictions
- `/ws/flights` - Real-time WebSocket
- `/api/debug/paths` - Debug endpoint exposing file paths

**Impact:** Unauthorized access to flight data and system information.

**Recommendation:**
Implement authentication middleware (OAuth2, API keys, or Databricks Apps auth):
```python
from fastapi.security import HTTPBearer
security = HTTPBearer()

@router.get("/flights")
async def get_flights(token: str = Depends(security)):
    # Validate token
```

---

## MEDIUM Vulnerabilities

### MED-01: Debug Endpoint Exposes File Paths

**File:** `app/backend/main.py`
**Lines:** 49-65

**Description:**
The `/api/debug/paths` endpoint exposes internal file system paths:
```python
@app.get("/api/debug/paths")
async def debug_paths():
    return {
        "frontend_dist": str(FRONTEND_DIST),
        "cwd": os.getcwd(),
        "__file__": __file__,
    }
```

**Impact:** Information disclosure aids attackers in path traversal attacks.

**Recommendation:**
Remove in production or protect with authentication:
```python
if os.getenv("DEBUG", "false").lower() == "true":
    @app.get("/api/debug/paths")
    ...
```

---

### MED-02: WebSocket No Rate Limiting

**File:** `app/backend/api/websocket.py`

**Description:**
The WebSocket endpoint accepts unlimited connections without rate limiting:
```python
async def connect(self, websocket: WebSocket) -> None:
    await websocket.accept()
    self._connections.add(websocket)  # No limit!
```

**Impact:** Denial of Service through connection exhaustion.

**Recommendation:**
Add connection limits per IP and total:
```python
MAX_CONNECTIONS = 1000
MAX_PER_IP = 10

if len(self._connections) >= MAX_CONNECTIONS:
    await websocket.close(code=1008, reason="Too many connections")
```

---

### MED-03: Metrics Endpoint Unbounded Memory

**File:** `app/backend/api/routes.py`
**Lines:** 137-172

**Description:**
Web Vitals metrics are stored in unbounded in-memory buffer:
```python
_web_vitals_buffer: list = []
_MAX_BUFFER_SIZE = 1000

_web_vitals_buffer.append(metric)  # Grows until truncation
```

**Impact:** Memory exhaustion if buffer manipulation is exploited.

**Recommendation:**
Use a fixed-size deque or external storage:
```python
from collections import deque
_web_vitals_buffer = deque(maxlen=1000)
```

---

### MED-04: Missing Input Validation on Query Parameters

**File:** `app/backend/api/routes.py`

**Description:**
While Pydantic validates types, the `icao24` parameter lacks format validation:
```python
@router.get("/flights/{icao24}")
async def get_flight(icao24: str):  # No hex validation
```

**Recommendation:**
Add regex validation:
```python
from fastapi import Path
icao24: str = Path(..., regex="^[a-f0-9]{6}$")
```

---

## LOW Vulnerabilities

### LOW-01: Outdated Major Dependencies

| Package | Current | Latest | Breaking Changes |
|---------|---------|--------|------------------|
| react | 18.3.1 | 19.2.4 | Yes |
| react-leaflet | 4.2.1 | 5.0.0 | Yes |
| tailwindcss | 3.4.19 | 4.2.1 | Yes |
| vite | 5.4.21 | 7.3.1 | Yes |
| @react-three/fiber | 8.15.19 | 9.5.0 | Yes |

**Recommendation:** Plan migration to latest majors; security patches come to latest versions first.

---

### LOW-02: Credentials in Environment Variables

**Files:** Multiple services

**Description:**
Secrets are loaded from environment variables without validation:
```python
self._token = os.getenv("DATABRICKS_TOKEN")
self._password = os.getenv("LAKEBASE_PASSWORD")
```

**Recommendation:**
Use Databricks Secrets or a vault:
```python
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
token = w.dbutils.secrets.get("scope", "databricks-token")
```

---

### LOW-03: No Content Security Policy

**Description:**
The application doesn't set CSP headers, allowing inline scripts and external resources.

**Recommendation:**
Add CSP middleware:
```python
from fastapi.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = "default-src 'self'"
    return response
```

---

## INFORMATIONAL

### INFO-01: No HTTPS Enforcement
The app relies on Databricks Apps for HTTPS. Local development uses HTTP.

### INFO-02: Service Worker Present
`sw.js` is served but not audited for security.

### INFO-03: No Rate Limiting on REST APIs
All REST endpoints can be called without limits.

### INFO-04: Logging Without Sanitization
User input may be logged without sanitization, risking log injection.

---

## Secure Coding Findings

### Positive Findings (No Issues)

| Check | Status |
|-------|--------|
| No `eval()` or `exec()` | PASS |
| No `subprocess` shell injection | PASS |
| No hardcoded secrets in code | PASS |
| No `.env` files committed | PASS |
| No `dangerouslySetInnerHTML` | PASS |
| PostgreSQL uses parameterized queries | PASS |
| Pydantic input validation | PASS |
| No `pickle` deserialization | PASS |

---

## Recommended Fixes Priority

| Priority | Issue | Effort |
|----------|-------|--------|
| 1 | CRIT-01: SQL Injection | Low |
| 2 | HIGH-01: CORS Policy | Low |
| 3 | HIGH-02: Update Vite | Low |
| 4 | HIGH-03: Add Authentication | Medium |
| 5 | MED-01: Remove Debug Endpoint | Low |
| 6 | MED-02: WebSocket Rate Limit | Medium |

---

## Commands to Fix Critical Issues

```bash
# Fix npm vulnerabilities
cd app/frontend && npm audit fix --force

# Or selective update
npm install vite@^7.0.0 esbuild@latest
```

---

## Next Steps

1. **Immediate:** Fix SQL injection in delta_service.py
2. **Short-term:** Restrict CORS, add authentication
3. **Medium-term:** Update dependencies, add rate limiting
4. **Long-term:** Implement CSP, security monitoring

---

*Report generated automatically. Manual review recommended for production deployment.*

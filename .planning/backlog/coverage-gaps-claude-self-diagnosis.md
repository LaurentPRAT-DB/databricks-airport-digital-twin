# Plan: Coverage Gaps Analysis + Claude Code Self-Diagnosis Infrastructure

## Context

**Problem**: Claude Code can fix bugs and add features, but when something breaks in the deployed app or tests fail, it lacks a tight feedback loop to:
1. See backend logs from the running app
2. Correlate frontend errors with backend failures
3. Run targeted tests fast (full suite = 3826 tests, >10 min)
4. Know which untested code paths are causing issues

**Current state**:
- Python coverage: **72%** (19,844 stmts, 5,468 missed) — 41 files >=85%, 30 files 50-84%, 21 files <50%
- Frontend coverage: **59%** (statements)
- UI E2E: **22/22 pass**
- Debug infra: ring-buffer `/api/debug/logs` (gated by `DEBUG_MODE=true`), frontend `debugLogger.ts`, Chrome DevTools MCP

**Goal**: Close the feedback loop so Claude Code can autonomously test → diagnose → fix → verify without human intervention.

---

## Gap Analysis

### Backend: Lowest Coverage Files

| File | Cov% | Missed | Testable locally? |
|------|------|--------|-------------------|
| `api/simulation.py` | 8% | 337 | Yes — TestClient |
| `api/inpainting.py` | 17% | 147 | Yes — TestClient + mock ML |
| `api/genie.py` | 19% | 166 | Partial — needs Databricks SQL mock |
| `api/opensky.py` | 36% | 310 | Yes — TestClient + mock OpenSky |
| `api/routes.py` | 41% | 367 | Yes — TestClient |
| `main.py` | 33% | 249 | Partial — startup hooks |
| `services/lakebase_service.py` | 41% | 543 | Partial — needs PG mock |
| `services/airport_config_service.py` | 31% | 198 | Yes — mock OSM responses |
| `services/demo_simulation_service.py` | 0% | 58 | Yes — pure Python |
| `services/mcp_connection_service.py` | 0% | 57 | No — needs Databricks SP creds |
| `src/persistence/airport_repository.py` | 47% | 235 | Partial — needs Delta/Spark |

### Frontend: Lowest Coverage Files

| File | Cov% | Impact |
|------|------|--------|
| `SimulationReport.tsx` | 1% | **High** — report modal used every session |
| `FIDS.tsx` | 43% | **High** — flight info display |
| `GLTFAircraft.tsx` | 6% | Medium — 3D model loading |
| `Terminal3D.tsx` | 9% | Low — 3D decoration |
| `NavigationControls3D.tsx` | 13% | Medium — 3D camera |
| `MobileHeader.tsx` | 0% | Low — mobile-only |
| `SceneCapture.tsx` | 27% | Low — screenshot feature |
| `sceneCapture.ts` (util) | 0% | Low — canvas export |
| `debugLogger.ts` | 19% | Low — debug infra |

### Claude Code Devloop Gaps

| Gap | Impact | Fix |
|-----|--------|-----|
| No fast API test subset | Every backend change → 10min wait | pytest markers |
| No backend log access from deployed app | Can't diagnose runtime errors after deploy | Log reader endpoint + script |
| No network error details in E2E failures | "S5 failed" but why? | Capture 4xx/5xx in E2E |
| No local smoke test | Can't verify locally before deploy | TestClient-based smoke script |

---

## Implementation Plan

### Phase 1: pytest markers for fast subsets

**Modify: `pyproject.toml`** — add:
```ini
[tool.pytest.ini_options]
markers = [
    "api: API integration tests using TestClient",
    "ml: ML model tests",
    "simulation: simulation engine tests",
]
```

**Modify 12 existing test files** — add `@pytest.mark.api` class-level decorator:
- `tests/test_backend.py` (22 tests)
- `tests/test_v2_api.py` (59 tests)
- `tests/test_data_ops_api.py` (22 tests)
- `tests/test_security.py` (31 tests)
- `tests/test_mcp.py` (48 tests)
- `tests/test_opensky_router.py` (17 tests)
- `tests/test_airport_config_routes.py` (13 tests)
- `tests/test_data_sync.py` (27 tests)
- `tests/test_assistant.py` (14 tests)
- `tests/test_websocket.py`
- `tests/test_opensky_collector.py` (22 tests)
- `tests/test_services.py` (50 tests)

**Usage**: `uv run pytest -m api -q` → ~341 tests in ~30s

### Phase 2: Local API smoke test script

**Create: `scripts/test_api_local.py`** (~100 lines)

Uses `fastapi.testclient.TestClient` against `app.backend.main:app`. Tests:
1. `GET /health` → 200 + required fields
2. `GET /api/ready` → 200 + `flights_active` present
3. `GET /api/flights` → 200 + non-empty `flights` array
4. `GET /api/weather` → 200 + weather fields
5. `GET /api/schedule?direction=departures` → 200 + flights
6. `GET /api/predictions` → 200
7. `GET /api/gates` → 200
8. `GET /api/simulation/list` → 200

Outputs `test-results/api_local_report.json` with per-endpoint status, latency, and response sample.

### Phase 3: Deployed app log reader

**Modify: `app/backend/api/routes.py`** — Add endpoint:

```python
@router.get("/debug/recent-errors", tags=["debug"])
async def get_recent_errors(
    limit: int = Query(default=50, ge=1, le=200),
    authorization: str = Header(default=""),
):
    """Return recent ERROR/WARNING lines from ring buffer.
    
    Lighter than /debug/logs — doesn't require DEBUG_MODE.
    Requires valid Databricks token in Authorization header.
    """
```

This endpoint:
- Returns only ERROR + WARNING level lines (no debug/info noise)
- Requires Bearer token auth (validates against Databricks host)
- Always available (not gated by DEBUG_MODE)
- Returns JSON: `{"errors": [...], "warnings": [...], "count": N}`

**Create: `scripts/fetch_app_logs.py`** (~50 lines)
- Gets Databricks token via CLI (same pattern as `test_ui_e2e.py`)
- Fetches `/api/debug/recent-errors`
- Prints formatted output Claude can read

### Phase 4: Enhanced E2E network logging

**Modify: `scripts/test_ui_e2e.py`**

Add `page.on("response", ...)` handler that captures:
- Any response with status >= 400
- URL, status code, response body (truncated to 500 chars)
- Stores in `failed_requests` array per scenario

Add to JSON report:
```json
{
  "scenarios": [...],
  "failed_api_requests": [
    {"url": "/api/flights", "status": 500, "body": "{\"detail\":\"...\"}"}
  ]
}
```

### Phase 5: Highest-impact coverage tests

**Create: `tests/test_simulation_api.py`** (~150 lines)
- Target: `app/backend/api/simulation.py` (8% → ~60%)
- Tests: `/api/simulation/list`, `/api/simulation/{id}/load`, `/api/simulation/{id}/events`
- Uses TestClient + temp simulation JSON files
- Mark: `@pytest.mark.api`

**Create: `tests/test_routes_coverage.py`** (~200 lines)
- Target: `app/backend/api/routes.py` (41% → ~65%)
- Tests: `/api/gates`, `/api/turnaround/{icao24}`, `/api/debug/logs` (mocked DEBUG_MODE), `/api/gse/fleet`, error handling paths
- Mark: `@pytest.mark.api`

**Create: `app/frontend/src/components/SimulationControls/SimulationReport.test.tsx`** (~120 lines)
- Target: `SimulationReport.tsx` (1% → ~70%)
- Tests: renders KPI cards, displays events, download button, close callback

---

## Files Summary

| Action | File | Phase |
|--------|------|-------|
| MODIFY | `pyproject.toml` | 1 |
| MODIFY | 12 test files (add `@pytest.mark.api`) | 1 |
| CREATE | `scripts/test_api_local.py` | 2 |
| MODIFY | `app/backend/api/routes.py` (add `/debug/recent-errors`) | 3 |
| CREATE | `scripts/fetch_app_logs.py` | 3 |
| MODIFY | `scripts/test_ui_e2e.py` (add network logging) | 4 |
| CREATE | `tests/test_simulation_api.py` | 5 |
| CREATE | `tests/test_routes_coverage.py` | 5 |
| CREATE | `SimulationReport.test.tsx` | 5 |

---

## Verification

```bash
# Phase 1: Fast subset works
uv run pytest -m api -q  # ~341 tests in <30s

# Phase 2: Local smoke
uv run python scripts/test_api_local.py && cat test-results/api_local_report.json

# Phase 3: Log reader (after deploy)
uv run python scripts/fetch_app_logs.py --limit 10

# Phase 4: Enhanced E2E
uv run python scripts/test_ui_e2e.py
python3 -c "import json; d=json.load(open('test-results/ui_e2e_report.json')); print('Failed requests:', d.get('failed_api_requests', []))"

# Phase 5: Coverage bump
uv run pytest tests/test_simulation_api.py tests/test_routes_coverage.py -v
cd app/frontend && npx vitest run src/components/SimulationControls/SimulationReport.test.tsx

# Overall target: 72% → 76%+ backend, 59% → 62%+ frontend
```

## Claude Code Devloop After Implementation

```
1. Make change
2. uv run python scripts/test_api_local.py     # 10s — API sanity
3. uv run pytest -m api -q                      # 30s — API regression
4. databricks bundle deploy --target dev         # deploy
5. uv run python scripts/fetch_app_logs.py      # read runtime errors
6. uv run python scripts/test_ui_e2e.py          # E2E with network logs
7. If failure → read report → fix → goto 1
```

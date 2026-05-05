---
title: "CI/CD Pipeline — GitHub Actions for Airport Digital Twin"
status: active
area: deployment, infrastructure
priority: high
related:
  - per-target-lakebase-config.md
  - full-environment-isolation.md
  - ../backlog/v1-readiness-checklist.md
---

# CI/CD Pipeline — GitHub Actions for Airport Digital Twin

## Current Status (2026-05-05)

**CI:** Passing on every push. 2 parallel jobs (Python tests, Frontend tests + TypeScript).
**CD:** Deploy to prod on merge to main. Actively stabilizing clean-slate deploys.
**Alerting:** Workflow failure status only (auto-issue creation removed — enterprise token restriction).

---

## Architecture (As-Built)

```
Push/PR to any branch              Merge to main (or workflow_dispatch)
        │                                    │
        ▼                                    ▼
┌──────────────────────┐     ┌──────────────────────────────────┐
│  CI (.github/        │     │  CD (.github/workflows/cd.yml)   │
│  workflows/ci.yml)   │     │                                  │
│                      │     │  Job 1: deploy                   │
│  Job 1: python-tests │     │    0. Patch app.yaml per target  │
│    - uv sync         │     │    1. Create UC schema           │
│    - pytest (skip    │     │    1b. Bundle deploy             │
│      network tests)  │     │    2. Detect app SP              │
│                      │     │    3. Create UC tables            │
│  Job 2: frontend     │     │    3b. Seed data (if --seed)     │
│    - npm ci          │     │    4. Deploy source + start app  │
│    - vitest          │     │    5. Grant SP permissions       │
│    - tsc --noEmit    │     │    6. Output app URL             │
│                      │     │                                  │
│  → Blocks merge on   │     │  Job 2: post-deploy-tests        │
│    failure           │     │    - Wait for /api/ready          │
└──────────────────────┘     │    - verify-prod.sh (11 checks)  │
                             │    - Fail workflow on error       │
                             └──────────────────────────────────┘
```

---

## Files

| File | Purpose |
|------|---------|
| `.github/workflows/ci.yml` | CI: Python + frontend tests on every push |
| `.github/workflows/cd.yml` | CD: deploy + post-deploy verification |
| `.github/actions/connect-vpn/action.yml` | Composite action: GlobalProtect VPN via openconnect |
| `scripts/ci-deploy.sh` | Main CD orchestrator (Steps 0-6) |
| `scripts/verify-prod.sh` | Post-deploy endpoint checker (11 endpoints) |
| `scripts/grant_sp_permissions.sh` | SP grants: UC, workspace ACLs, Lakebase roles, secrets, Genie |

---

## CI Workflow Detail (`.github/workflows/ci.yml`)

**Triggers:** `push` to any branch, `pull_request` to main
**Concurrency:** Cancel-in-progress per branch (`ci-${{ github.ref }}`)

### Job: `python-tests` (ubuntu-latest, 15min timeout)

```
uv sync --all-extras
uv run pytest tests/ \
  --ignore=tests/test_live_trajectory_quality.py \    # Needs OpenSky API
  --ignore=tests/test_airport_activation.py \         # Calls OSM Overpass
  --ignore=tests/test_aviation_procedures.py \        # Network-dependent
  --ignore=tests/test_flight_ops_validation.py \      # Network-dependent
  --ignore=tests/test_expert_reviews.py \             # Network-dependent
  --ignore=tests/test_multi_airport_ux.py \           # Network-dependent
  -q --tb=short --override-ini="asyncio_mode=auto"
```

### Job: `frontend-tests` (ubuntu-latest, 10min timeout)

```
cd app/frontend && npm ci
npm run test:run
npx tsc --noEmit
```

### CI Debugging

| Symptom | Cause | Fix |
|---------|-------|-----|
| Tests timeout at 15min | Heavy deps (catboost, openap) slow to install | Increase timeout or cache `.venv` |
| `asyncio_mode` errors | Some tests need `auto` mode | Already handled via `--override-ini` |
| Network test failures | OSM/OpenSky calls | Already `--ignore`'d — check if new network tests were added |
| Performance test flakiness | CI runners are slower | Relaxed thresholds via `98c3f59` |

---

## CD Workflow Detail (`.github/workflows/cd.yml`)

**Triggers:** `push` to main, `workflow_dispatch` (manual with target + seed inputs)
**Concurrency:** Non-cancelling group (`cd-deploy`) — never cancel in-flight deploys

### Required Secrets

| Secret | Purpose | Required? |
|--------|---------|-----------|
| `DATABRICKS_HOST` | Workspace URL | Yes |
| `DATABRICKS_CLIENT_ID` | SP OAuth client ID | Yes (or TOKEN) |
| `DATABRICKS_CLIENT_SECRET` | SP OAuth client secret | Yes (or TOKEN) |
| `DATABRICKS_TOKEN` | PAT for post-deploy verification | Yes |
| `DATABRICKS_WAREHOUSE_ID` | SQL warehouse for DDL | Optional |
| `LAKEBASE_HOST` | Override Lakebase host | Optional |
| `LAKEBASE_ENDPOINT_NAME` | Override Lakebase endpoint | Optional |
| `GENIE_SPACE_ID` | Genie space to grant access | Optional |
| `SECRET_SCOPE` | Databricks secret scope name | Optional |

### Required Variables (Repository Settings → Variables)

| Variable | Purpose | When needed |
|----------|---------|-------------|
| `RUNNER_LABEL` | Custom runner label (e.g., `self-hosted`) | Self-hosted only |
| `REQUIRES_VPN` | Set to `"true"` to enable VPN connection | When workspace behind VPN |
| `VPN_PORTAL` | GlobalProtect portal address | When VPN required |
| `VPN_GATEWAY` | Specific VPN gateway | Optional |
| `VPN_AUTH_METHOD` | `password`, `totp`, or `saml-cookie` | When VPN required |

### CD Deploy Steps (scripts/ci-deploy.sh)

```
Step 0: Patch app.yaml
  - Rewrites env vars for target (Lakebase endpoint, host, catalog, schema)
  - Uses Python regex replacement — safe because app.yaml format is predictable
  - Ephemeral checkout — no git state affected

Step 1: Create UC catalog/schema
  - Must exist BEFORE bundle deploy (volumes reference the schema)
  - CREATE CATALOG IF NOT EXISTS + CREATE SCHEMA IF NOT EXISTS
  - Uses SQL Statements API (/api/2.0/sql/statements)

Step 1b: DABs bundle deploy
  - `databricks bundle deploy --target $TARGET --force-lock`
  - --force-lock prevents stale lock from blocking (safe in single-deployer CI)

Step 2: Detect app SP and bundle path
  - `databricks apps get $APP_NAME` → reads service_principal_client_id + default_source_code_path
  - Bundle path fallback: derives from current-user + DABs convention

Step 3: Create UC tables
  - Loads DDL from src/persistence/airport_tables.py (Python import)
  - Executes each CREATE TABLE IF NOT EXISTS via SQL API
  - Shows per-table success/failure with error details

Step 3b: Seed data (only with --seed flag)
  - Creates Lakebase branch if needed (for env isolation)
  - Uploads calibration profiles (1,183 JSON files → UC Volume)
  - Uploads 3D aircraft models (GLB files → UC Volume)
  - Applies Lakebase schema via Databricks SDK + psycopg2

Step 4: Deploy source + start app
  - CRITICAL ORDER: compute must be ACTIVE before `apps deploy`
  - Fresh app: `apps start` → wait for compute ACTIVE → `apps deploy`
  - Running app: wait for any active deployment to finish → `apps deploy`
  - `apps deploy $APP_NAME --source-code-path "/Workspace$BUNDLE_DIR"`
  - Wait for app_status.state == "RUNNING" (up to 10min)

Step 5: Grant SP permissions
  - Delegates to scripts/grant_sp_permissions.sh
  - UC GRANT on catalog/schema/tables/volumes
  - Workspace ACLs on bundle dir
  - Lakebase role creation + SQL grants (via SDK)
  - Secret scope ACLs
  - Genie space access

Step 6: Output app URL
  - Writes to $GITHUB_OUTPUT for post-deploy-tests job
```

### Post-Deploy Tests (scripts/verify-prod.sh)

Runs 11 endpoint checks against the deployed app:

| Check | Endpoint | Assertion |
|-------|----------|-----------|
| Health | `/health` | `.status == "healthy"` |
| Ready | `/api/ready` | `.ready == true` |
| Flights | `/api/flights` | `.flights | length > 0` |
| Airport config | `/api/airport/config` | `.config | keys | length > 0` |
| Arrivals | `/api/schedule/arrivals` | array or has `flights` |
| Departures | `/api/schedule/departures` | array or has `flights` |
| Weather | `/api/weather/current` | has `temperature` or `station` |
| GSE | `/api/gse/status` | non-null |
| Baggage | `/api/baggage/stats` | non-null |
| Frontend | `/` | HTTP 200 |
| Version | `/api/version` | has `version` or `commit` |

**OAuth handling:** If all endpoints return 401/302 (OAuth-protected), that's a PASS — it means the app is running but requires browser auth.

---

## Environment Isolation

| Resource | Dev | Prod |
|----------|-----|------|
| App name | `airport-digital-twin-dev` | `airport-digital-twin-prod` |
| UC Schema | `airport_digital_twin` | `airport_digital_twin_prod` |
| Lakebase branch | `dev` | `production` |
| Lakebase endpoint | `branches/dev/endpoints/primary` | `branches/production/endpoints/primary` |
| App URL | `airport-digital-twin-dev-7474645572615955.aws.databricksapps.com` | `airport-digital-twin-prod-7474645572615955.aws.databricksapps.com` |
| Bundle dir | `.bundle/.../dev/files` | `.bundle/.../prod/files` |

Isolation is achieved via:
1. `databricks.yml` per-target variables (`lakebase_branch`, `catalog`, `schema`)
2. `ci-deploy.sh` Step 0 patches `app.yaml` in the ephemeral checkout
3. `grant_sp_permissions.sh` uses resolved env vars for grants

---

## Debugging Guide

### How to check CD status

```bash
# See recent workflow runs
gh run list --workflow=cd.yml --limit=5

# View specific run logs
gh run view <run-id> --log

# Re-trigger manually
gh workflow run cd.yml -f target=prod
gh workflow run cd.yml -f target=prod -f seed=true  # first-time deploy
```

### Common CD Failure Modes

| Step | Symptom | Likely Cause | How to Debug | Fix |
|------|---------|--------------|-------------|-----|
| 0 | `patch_env_var` silently does nothing | app.yaml format changed (name/value not on consecutive lines) | `cat app.yaml` in workflow, check patched values | Update regex in `ci-deploy.sh:patch_env_var()` |
| 1 | "Cannot create schema" | SP lacks `CREATE SCHEMA` on catalog | `databricks permissions get catalog <catalog>` | Grant `ALL PRIVILEGES` on catalog to deployer SP |
| 1b | "Lock held by another" | Previous deploy crashed, lock not released | Visible in error output — `--force-lock` should handle it | Already uses `--force-lock`; if persists, `bundle validate` |
| 2 | "Could not detect app SP" | App doesn't exist yet (first deploy) | `databricks apps get $APP_NAME` | Run with `--seed` (creates app via bundle deploy first) |
| 3 | "Table creation failed" | SQL warehouse not available | Check WAREHOUSE_ID secret, warehouse state in UI | Start warehouse manually or use serverless |
| 3b | "Lakebase schema skipped" | SDK auth fails or psycopg2 not installed | Check `uv run` output, verify psycopg2 in deps | Ensure `psycopg2-binary` in pyproject.toml extras |
| 4 | "App did not reach RUNNING" | Source code error, missing env var, dependency crash | `databricks apps get $APP_NAME --output json` (check message field) | Check app logs: `databricks apps get-logs $APP_NAME` |
| 4 | Deploy hangs waiting for compute | Fresh app, compute never starts | `databricks apps get $APP_NAME` — check compute_status | Manually `databricks apps start`, may need workspace admin |
| 4 | "Active deployment in progress" | Previous deploy didn't finish | Wait loop handles this (5min max) | If stuck >5min, cancel via UI then retry |
| 5 | Permission errors in grants script | SP lacks admin-level permissions | Check script output for specific GRANT failure | Add missing grants in workspace admin console |
| post | All endpoints return 401 | App requires OAuth, token expired/invalid | Expected if no DATABRICKS_TOKEN or token is wrong | Set `DATABRICKS_TOKEN` secret (PAT with workspace access) |
| post | Specific endpoints fail | Backend error for that route | Check app logs | Fix backend code, re-deploy |

### How to check app state

```bash
# App status
databricks apps get airport-digital-twin-prod --output json | python3 -c "
import sys,json
app = json.load(sys.stdin)
print(f\"App state: {app.get('app_status',{}).get('state')}\")
print(f\"Compute:   {app.get('compute_status',{}).get('state')}\")
print(f\"SP:        {app.get('service_principal_client_id')}\")
print(f\"URL:       {app.get('url')}\")
"

# Recent deployments
databricks apps list-deployments airport-digital-twin-prod --output json | python3 -c "
import sys,json
data = json.load(sys.stdin)
deploys = data if isinstance(data, list) else data.get('deployments', [])
for d in deploys[:3]:
    print(f\"{d.get('deployment_id','?')[:8]} | {d.get('status',{}).get('state','?')} | {d.get('create_time','?')}\")
"

# App logs (if app crashes)
databricks apps get-logs airport-digital-twin-prod
```

### How to do a clean-slate deploy

```bash
# 1. Destroy existing bundle resources
databricks bundle destroy --target prod --auto-approve --force-lock

# 2. Drop schema (removes all tables/volumes)
databricks api post /api/2.0/sql/statements --json '{
  "statement": "DROP SCHEMA IF EXISTS serverless_stable_3n0ihb_catalog.airport_digital_twin_prod CASCADE",
  "wait_timeout": "30s"
}'

# 3. Deploy fresh with seed
gh workflow run cd.yml -f target=prod -f seed=true

# 4. Monitor
gh run list --workflow=cd.yml --limit=1
gh run watch <run-id>
```

### VPN Issues (Self-Hosted Runner Behind Firewall)

The `connect-vpn` composite action uses openconnect for GlobalProtect:

| Symptom | Cause | Fix |
|---------|-------|-----|
| "VPN tunnel not established after 60s" | Wrong portal/gateway, expired credentials | Check VPN_PORTAL, VPN_USERNAME, VPN_PASSWORD secrets |
| "TOTP code rejected" | Clock drift or wrong secret | Verify VPN_TOTP_SECRET, check server time |
| "tun0 up" but API calls fail | Split tunneling excludes Databricks | Add `VPN_GATEWAY` variable to force full tunnel gateway |
| VPN works but npm install hangs | npm registry blocked by VPN | Set `NODE_EXTRA_CA_CERTS` or use company npm mirror |

### Self-Hosted Runner Notes

When using `RUNNER_LABEL` for a self-hosted runner:
- Tool setup steps (`setup-python`, `setup-uv`, `setup-cli`) are skipped (`if: runner.environment == 'github-hosted'`)
- Node.js setup uses `RUNNER_TOOL_CACHE: /tmp/runner-tool-cache` to avoid permission issues
- `uv`, `databricks`, `python3`, `node`, `jq` must be pre-installed
- Auth is via env vars (never profiles): `DATABRICKS_HOST` + `DATABRICKS_TOKEN` (or CLIENT_ID/SECRET)

---

## Lessons Learned (from 34 fix commits)

| # | Issue | Root Cause | Fix Applied |
|---|-------|-----------|-------------|
| 1 | Bundle deploy fails with locked state | Previous deploy crashed | Added `--force-lock` (`d5c4ab5`) |
| 2 | UC Volume creation fails | Schema must exist before bundle deploy creates volumes | Create catalog+schema in Step 1 BEFORE bundle deploy (`182b38e`) |
| 3 | Fresh app deploy hangs | `apps deploy` requires compute ACTIVE first | Call `apps start`, wait for compute ACTIVE, then deploy (`6663bfe`) |
| 4 | `uv run python3 - <<HEREDOC` fails | Doesn't resolve venv on self-hosted | Write to temp file, then `uv run python3 /tmp/file.py` (`e4961eb`) |
| 5 | App yaml patching doesn't work | sed doesn't handle multiline properly | Use Python regex replacement (`dadcbd6`) |
| 6 | npm install fails on self-hosted | `~/.npmrc` points to `/tmp` cache with bad perms | Set `RUNNER_TOOL_CACHE` + skip npm cache on self-hosted (`231dad0`) |
| 7 | Post-deploy tests fail with 401 | App is OAuth-protected | Treat all-401 as PASS (app is running), pass Bearer token (`56223b2`) |
| 8 | GitHub issue creation blocked | Enterprise policy blocks personal repo contributions | Removed — rely on workflow failure status (`d644ad3`) |
| 9 | Concurrent deploys race | New push triggers CD while previous deploy is in-flight | Added deployment-in-progress wait loop (`af9b991`) |
| 10 | CI tests fail after refactor | Imports changed, performance thresholds too tight | Skip sim tests in CI, relax perf thresholds (`98c3f59`, `9b74529`) |

---

## Known Limitations

1. **No auto-issue on failure** — Enterprise `GITHUB_TOKEN` policy blocks it. TODO: use PAT or move repo to org.
2. **Post-deploy verification is shallow** — Only checks HTTP 200 + basic JSON assertions. Doesn't test simulation, assistant, or WebSocket.
3. **No rollback** — Failed deploy leaves broken prod. Manual intervention: redeploy last good commit.
4. **Single workspace** — Dev and prod share `fevm-serverless-stable`. True isolation requires separate workspace (PROD not provisioned yet).
5. **Lakebase schema on seed only** — If schema changes, must re-run with `--seed` or apply manually.

---

## Triggering Deploys

```bash
# Normal deploy (on merge to main — automatic)
git push origin main

# Manual deploy to specific target
gh workflow run cd.yml -f target=prod
gh workflow run cd.yml -f target=dev

# First-time deploy (seeds calibration profiles, 3D models, Lakebase schema)
gh workflow run cd.yml -f target=prod -f seed=true

# Check run status
gh run list --workflow=cd.yml --limit=5
gh run view <run-id> --log-failed
```

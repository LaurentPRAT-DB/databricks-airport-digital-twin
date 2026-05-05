---
title: "CI/CD Pipeline — GitHub Actions for Airport Digital Twin"
status: backlog
area: deployment, infrastructure
priority: high
related:
  - ../backlog/v1-readiness-checklist.md
---

# CI/CD Pipeline — GitHub Actions for Airport Digital Twin

## Context

The repo is public on GitHub with branch protection (ruleset) on main. Currently deployment is manual via `./deploy.sh`. The goal is:
- **CI (on every push/PR):** Run unit tests (Python + frontend) directly in GitHub Actions runners
- **CD (on merge to main):** Deploy to Databricks workspace via DABs
- **Post-CD validation:** Run Databricks smoke tests (e2e_smoke_test, integration tests) as workspace jobs — if they fail, alert (deployment not considered successful)

A PROD workspace will be provided later to complete the CD target.

## Gap Analysis

| Area | Status | Gap |
|------|--------|-----|
| Unit tests (Python) | All 3,695 collect without Databricks | None — can run in GHA |
| Unit tests (Frontend) | Vitest, no backend needed | None — can run in GHA |
| Network-dependent tests | `test_live_trajectory_quality` (auto-skips), `test_airport_activation::TestCachedAirportConfig` (calls OSM) | Need to mark/skip OSM-calling tests or mock Overpass in CI |
| Heavy deps (catboost, openap, scikit-learn) | Required for simulation tests | GHA runner needs them — install via `uv sync` |
| `databricks.yml` targets | Only `dev` target exists | Need `prod` target with workspace URL + SP auth |
| Auth for CD | Currently uses databricks-cli local browser auth | Need M2M OAuth (service principal client_id/secret) stored in GH Secrets |
| `deploy.sh` | Assumes interactive environment | Need to parameterize or create a CI-specific deploy script |
| Post-deploy tests | `e2e_smoke_test` requires running app + notebook token auth | App proxy may block SP tokens — documented issue in test notebook itself |
| Alerting | None | Need GitHub Actions notification on post-CD test failure |

## Architecture

```
Push/PR to any branch          Merge to main
        │                            │
        ▼                            ▼
┌─────────────────┐      ┌────────────────────────┐
│  CI Workflow     │      │  CD Workflow            │
│                 │      │                        │
│ 1. Python tests │      │ 1. Build frontend      │
│ 2. Frontend     │      │ 2. DABs bundle deploy  │
│    tests        │      │ 3. Create UC tables    │
│ 3. Lint/type    │      │ 4. Restart app         │
│    checks       │      │ 5. Grant SP perms      │
│                 │      │ 6. Run smoke tests     │
│ → Block merge   │      │    (Databricks job)    │
│   on failure    │      │ 7. Alert on failure    │
└─────────────────┘      └────────────────────────┘
```

## Implementation Plan

### Step 1: Create GitHub Secrets (manual — in GitHub UI)

Required secrets for Databricks M2M auth:
- `DATABRICKS_HOST` — workspace URL (e.g., `https://fevm-serverless-stable-3n0ihb.cloud.databricks.com`)
- `DATABRICKS_CLIENT_ID` — service principal OAuth client ID
- `DATABRICKS_CLIENT_SECRET` — service principal OAuth client secret
- `DATABRICKS_WAREHOUSE_ID` — SQL warehouse for table DDL
- `UC_CATALOG` — Unity Catalog name
- `UC_SCHEMA` — schema name

For PROD (when ready):
- `PROD_DATABRICKS_HOST`
- `PROD_DATABRICKS_CLIENT_ID`
- `PROD_DATABRICKS_CLIENT_SECRET`
- etc.

### Step 2: CI Workflow — `.github/workflows/ci.yml`

Triggers: `push` to any branch, `pull_request` to main

Jobs:

1. **python-tests** (ubuntu-latest, Python 3.10)
   - `uv sync --all-extras`
   - `uv run pytest tests/ -x --ignore=tests/test_live_trajectory_quality.py -q`
   - Skip network-dependent tests via marker or `--ignore`
2. **frontend-tests** (ubuntu-latest, Node 20)
   - `cd app/frontend && npm ci && npm run test:run`
3. **typecheck** (optional, good practice)
   - `cd app/frontend && npx tsc --noEmit`

### Step 3: CD Workflow — `.github/workflows/cd.yml`

Triggers: `push` to main (only after merge)

Jobs:

1. **deploy** (ubuntu-latest)
   - Checkout code
   - Install Databricks CLI (`curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh`)
   - Set env vars from secrets (`DATABRICKS_HOST`, `CLIENT_ID`, `CLIENT_SECRET`)
   - Build frontend: `cd app/frontend && npm ci && npm run build`
   - Deploy: `databricks bundle deploy --target prod`
   - Create tables: SQL API calls via `databricks api post`
   - Restart app: stop + start + wait for RUNNING
   - Grant SP permissions: `./scripts/grant_sp_permissions.sh`
2. **post-deploy-tests** (needs: deploy)
   - Trigger smoke test job: `databricks bundle run e2e_smoke_test --target prod`
   - Trigger integration test: `databricks bundle run baggage_pipeline_integration_test --target prod`
   - Poll job status until completion
   - If FAILED → create GitHub issue or send Slack/email alert
   - Mark deployment as failed in GitHub deployment status

### Step 4: Add `prod` target to `databricks.yml`

```yaml
targets:
  dev:
    default: true
    mode: development
    workspace:
      profile: FEVM_SERVERLESS_STABLE
    variables:
      catalog: "serverless_stable_3n0ihb_catalog"
      schema: "airport_digital_twin"

  prod:
    workspace:
      host: ${var.prod_host}  # From env/secrets
    variables:
      catalog: "${var.prod_catalog}"
      schema: "${var.prod_schema}"
```

### Step 5: Alerting mechanism

On post-CD test failure:
- Create a GitHub Issue with test results and link to job run
- Set GitHub deployment status to "failure"
- Optional: Slack webhook notification (if configured)

## Files to Create/Modify

| File | Action |
|------|--------|
| `.github/workflows/ci.yml` | Create — CI pipeline |
| `.github/workflows/cd.yml` | Create — CD pipeline (placeholder for PROD) |
| `databricks.yml` | Modify — add `prod` target |
| `scripts/ci-deploy.sh` | Create — CI-friendly deploy (non-interactive) |

## What Can Be Done Now vs What Needs Manual Setup

**Can do now:**
1. Create `.github/workflows/ci.yml` (unit tests on push/PR)
2. Create `.github/workflows/cd.yml` (skeleton with deploy steps, using secrets)
3. Add `prod` target placeholder in `databricks.yml`
4. Create `scripts/ci-deploy.sh` (non-interactive version of `deploy.sh`)

**Needs manual setup (later):**
1. PROD workspace URL
2. Service principal credentials (client_id + client_secret)
3. Add secrets in GitHub UI (Settings → Secrets → Actions)

Alert mechanism: GitHub Issue auto-created on post-CD test failure (tagged `deploy-failure`)

## Verification

After implementation:
1. Push to a feature branch → CI runs, tests pass
2. Merge to main → CD triggers (will fail gracefully until secrets are configured)
3. Once secrets are set + PROD workspace ready → full deploy + smoke tests run
4. Simulate smoke test failure → verify alert is created

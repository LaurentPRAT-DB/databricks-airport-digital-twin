# Production Deployment Guide

## Overview

This guide covers deploying the Airport Digital Twin to a production Databricks workspace. The deployment is automated via GitHub Actions CD, but requires one-time manual setup of secrets and a first-time `--seed` run.

---

## Pre-requisites Checklist

### Workspace Requirements

- [ ] Databricks workspace with Unity Catalog enabled
- [ ] Serverless SQL warehouse available (or a Pro/Classic warehouse ID)
- [ ] Service Principal created with workspace admin permissions
- [ ] OAuth M2M credentials (client_id + client_secret) for the Service Principal
- [ ] Lakebase Autoscaling project created (`databricks postgres create-project airport-digital-twin`)

### GitHub Repository Secrets

Configure in **Settings > Secrets and variables > Actions**:

| Secret | Required | Description |
|--------|----------|-------------|
| `DATABRICKS_HOST` | Yes | Workspace URL (e.g., `https://my-workspace.cloud.databricks.com`) |
| `DATABRICKS_CLIENT_ID` | Yes | Service Principal OAuth client ID |
| `DATABRICKS_CLIENT_SECRET` | Yes | Service Principal OAuth client secret |
| `DATABRICKS_WAREHOUSE_ID` | No | SQL warehouse ID (blank = serverless) |
| `LAKEBASE_HOST` | No | Lakebase PostgreSQL host (blank = dev instance) |
| `LAKEBASE_ENDPOINT_NAME` | No | Lakebase endpoint path (blank = dev endpoint) |
| `GENIE_SPACE_ID` | No | Genie Space ID for AI assistant |
| `SECRET_SCOPE` | No | Databricks secret scope name (default: `airport-digital-twin`) |

### Local Verification Before First Deploy

```bash
# Verify CLI auth works with the prod workspace
export DATABRICKS_HOST="https://your-workspace.cloud.databricks.com"
export DATABRICKS_CLIENT_ID="your-sp-client-id"
export DATABRICKS_CLIENT_SECRET="your-sp-secret"
databricks auth env    # Should show token info
databricks workspace ls /  # Should list workspace root
```

---

## First-Time Deployment (with --seed)

### Option A: Via GitHub Actions (recommended)

1. Go to **Actions > CD > Run workflow**
2. Check **"Seed data"** checkbox
3. Click **Run workflow**

### Option B: Manual from local machine

```bash
export DATABRICKS_HOST="https://your-workspace.cloud.databricks.com"
export DATABRICKS_CLIENT_ID="..."
export DATABRICKS_CLIENT_SECRET="..."
export LAKEBASE_HOST="your-lakebase-host.database.us-east-1.cloud.databricks.com"
export LAKEBASE_ENDPOINT_NAME="projects/airport-digital-twin/branches/production/endpoints/primary"

# Build frontend first
cd app/frontend && npm ci && npm run build && cd ../..

# Deploy with seed
./scripts/ci-deploy.sh --target prod --seed
```

### What --seed does

| Step | Data | Source | Destination |
|------|------|--------|-------------|
| Calibration profiles | 1,183 airport JSON files | `data/calibration/profiles/` | UC Volume `calibration_profiles` |
| 3D aircraft models | 17 GLB files | `app/frontend/dist/models/aircraft/` | UC Volume `static_assets/models/aircraft` |
| Lakebase schema | DDL + indexes + triggers | `scripts/lakebase_schema.sql` | Lakebase PostgreSQL |

---

## Subsequent Deployments

Automatic on every merge to `main`. No `--seed` needed.

The CD workflow:
1. Builds frontend
2. Patches `app.yaml` with target-specific env vars
3. Runs `databricks bundle deploy --target prod`
4. Creates UC schema + Delta tables (idempotent)
5. Restarts app (stop + start)
6. Grants SP permissions (UC, Volumes, Secrets)
7. Runs post-deploy smoke tests
8. Creates GitHub Issue on test failure

---

## Post-Deployment Verification

### Automated Checks (run by CD pipeline)

The E2E smoke test job verifies 11 endpoints:

| # | Test | Endpoint | Validates |
|---|------|----------|-----------|
| 1 | Health check | `GET /health` | App process is running |
| 2 | Readiness | `GET /api/ready` | Demo data loaded, simulation active |
| 3 | Flights list | `GET /api/flights` | Returns flights with required fields |
| 4 | Flight detail | `GET /api/flights/{id}/trajectory` | Single flight + trajectory points |
| 5 | Airport config | `GET /api/airport/config` | OSM geometry loaded (runways, gates) |
| 6 | Schedule | `GET /api/schedule/arrivals` | FIDS data available |
| 7 | Weather | `GET /api/weather/current` | Weather widget data |
| 8 | GSE status | `GET /api/gse/status` | Ground support equipment |
| 9 | Baggage stats | `GET /api/baggage/stats` | Baggage handling system |
| 10 | Airport switch | `POST /api/airport/switch` | Multi-airport works (KJFK + back) |
| 11 | Frontend | `GET /` | index.html serves correctly |

### Manual Verification Checklist

After the first deployment, verify these manually:

- [ ] App URL loads in browser (OAuth login works)
- [ ] 2D map shows aircraft moving
- [ ] 3D view renders aircraft models (not fallback geometry)
- [ ] Airport selector works — switch to a non-default airport
- [ ] FIDS panel shows arrivals/departures
- [ ] Weather widget shows current METAR
- [ ] Flight detail panel opens on aircraft click
- [ ] Simulation controls (speed, pause) work
- [ ] Calibration profiles load (check: accurate traffic counts for KSFO/KJFK/KATL)

### Data Verification

```bash
# Check UC tables exist
databricks api post /api/2.0/sql/statements --json '{
  "statement": "SHOW TABLES IN airport_digital_twin.airport_digital_twin",
  "wait_timeout": "30s"
}'

# Check calibration profiles in Volume
databricks fs ls "dbfs:/Volumes/airport_digital_twin/airport_digital_twin/calibration_profiles" | wc -l
# Expected: 1183+

# Check 3D models in Volume
databricks fs ls "dbfs:/Volumes/airport_digital_twin/airport_digital_twin/static_assets/models/aircraft"
# Expected: 17 GLB files

# Check Lakebase connectivity (from app logs)
curl -s "https://<APP_URL>/health" | jq '.services.lakebase'
# Expected: "connected" or similar

# Check app readiness
curl -s "https://<APP_URL>/api/ready" | jq '.'
# Expected: {"ready": true, "demo_ready": true, ...}
```

---

## Automated Post-Deploy Script

Save as `scripts/verify-prod.sh` and run after deployment:

```bash
#!/usr/bin/env bash
# Post-deploy production verification script
# Usage: ./scripts/verify-prod.sh <APP_URL>
#
# Runs the same checks as the E2E smoke test but from your local machine.
# Requires: curl, jq, valid Databricks OAuth session (browser cookie or token)

set -euo pipefail

APP_URL="${1:?Usage: $0 <APP_URL>}"
APP_URL="${APP_URL%/}"  # Remove trailing slash

PASS=0
FAIL=0

check() {
  local name="$1" url="$2" jq_test="${3:-}"
  local response status

  response=$(curl -s -w "\n%{http_code}" "$url" 2>/dev/null)
  status=$(echo "$response" | tail -1)
  body=$(echo "$response" | sed '$d')

  if [[ "$status" != "200" ]]; then
    echo "  FAIL  $name (HTTP $status)"
    FAIL=$((FAIL + 1))
    return
  fi

  if [[ -n "$jq_test" ]]; then
    if echo "$body" | jq -e "$jq_test" > /dev/null 2>&1; then
      echo "  OK    $name"
      PASS=$((PASS + 1))
    else
      echo "  FAIL  $name (assertion failed: $jq_test)"
      FAIL=$((FAIL + 1))
    fi
  else
    echo "  OK    $name"
    PASS=$((PASS + 1))
  fi
}

echo "Verifying deployment: $APP_URL"
echo ""

check "Health"          "$APP_URL/health"                '.status == "healthy"'
check "Ready"           "$APP_URL/api/ready"             '.ready == true'
check "Flights"         "$APP_URL/api/flights"           '.flights | length > 0'
check "Airport config"  "$APP_URL/api/airport/config"    '.config | keys | length > 0'
check "Arrivals"        "$APP_URL/api/schedule/arrivals" '. | type == "array" or has("flights")'
check "Departures"      "$APP_URL/api/schedule/departures" '. | type == "array" or has("flights")'
check "Weather"         "$APP_URL/api/weather/current"   'has("temperature") or has("station")'
check "GSE"             "$APP_URL/api/gse/status"        '. != null'
check "Baggage"         "$APP_URL/api/baggage/stats"     '. != null'
check "Frontend"        "$APP_URL/"                      ''
check "Version"         "$APP_URL/api/version"           'has("version") or has("commit")'

echo ""
echo "Results: $PASS passed, $FAIL failed ($(( PASS + FAIL )) total)"

if [[ $FAIL -gt 0 ]]; then
  echo "DEPLOYMENT VERIFICATION FAILED"
  exit 1
fi
echo "DEPLOYMENT VERIFIED"
```

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| App stuck in STARTING | Missing permissions or env var | Check `databricks apps get <name>` for error message |
| No flights displayed | Demo simulation not started | Check `/api/ready` — wait for `demo_ready: true` |
| 3D models missing | Seed not run | Run CD with `--seed` or `databricks fs cp` models manually |
| "Catalog not found" | UC_CATALOG doesn't exist | Create catalog: `CREATE CATALOG IF NOT EXISTS airport_digital_twin` |
| Lakebase timeout | Wrong host or endpoint name | Verify `LAKEBASE_HOST` secret matches actual Lakebase endpoint |
| Permission denied | SP grants not applied | Re-run `scripts/grant_sp_permissions.sh` |
| Airport switch fails | OSM/Overpass API blocked | Check if workspace has outbound internet access |

---

## Architecture Reference

```
GitHub Actions (CD)
    │
    ├── databricks bundle deploy ──► Databricks App + Jobs + Pipelines
    │
    ├── UC Table DDLs ─────────────► Delta tables (21 tables)
    │
    ├── --seed (first time only):
    │   ├── calibration profiles ──► UC Volume: calibration_profiles
    │   ├── 3D models ────────────► UC Volume: static_assets
    │   └── lakebase_schema.sql ──► Lakebase PostgreSQL (6 tables)
    │
    ├── Stop + Start app ─────────► App picks up new code + env
    │
    ├── Grant SP permissions ─────► UC grants, Volume access, Secrets
    │
    └── E2E smoke tests ──────────► 11 endpoint checks
```

#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Full automated deployment: build → DABs deploy → create tables → start → grant
#
# DABs manages: app, volumes, jobs, pipelines, serving endpoints, SQL warehouse.
# This script handles what DABs cannot: schema/table DDL, app restart, UC grants,
# workspace ACLs, secret scope ACLs, Genie space access.
#
# Usage:
#   ./deploy.sh                    # default target: dev
#   ./deploy.sh --target prod      # specify target
#   SKIP_BUILD=1 ./deploy.sh       # skip frontend build
#
# All env vars are configurable for different workspaces:
#   UC_CATALOG, UC_SCHEMA, WAREHOUSE_ID, GENIE_SPACE_ID, SECRET_SCOPE,
#   DATABRICKS_PROFILE, APP_NAME
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"

TARGET="${1:-dev}"
[[ "${1:-}" == "--target" ]] && TARGET="${2:-dev}"

PROFILE="${DATABRICKS_PROFILE:-FEVM_SERVERLESS_STABLE}"
UC_CATALOG="${UC_CATALOG:-serverless_stable_3n0ihb_catalog}"
UC_SCHEMA="${UC_SCHEMA:-airport_digital_twin}"
WAREHOUSE_ID="${WAREHOUSE_ID:-b868e84cedeb4262}"
GENIE_SPACE_ID="${GENIE_SPACE_ID:-01f12612fa6314ae943d0526f5ae3a00}"
SECRET_SCOPE="${SECRET_SCOPE:-airport-digital-twin}"
APP_NAME="${APP_NAME:-airport-digital-twin-$TARGET}"
SKIP_BUILD="${SKIP_BUILD:-}"

ok()   { echo "  ✓ $1"; }
fail() { echo "  ✗ $1"; }
info() { echo "  → $1"; }

run_sql() {
  local stmt="$1"
  databricks api post /api/2.0/sql/statements \
    --profile "$PROFILE" \
    --json "{\"warehouse_id\":\"$WAREHOUSE_ID\",\"statement\":\"$stmt\",\"wait_timeout\":\"30s\"}" \
    2>/dev/null | grep -q '"SUCCEEDED"'
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo "═══ Airport Digital Twin — Full Deploy (target: $TARGET) ═══"
echo ""

# ── Step 1: Build frontend ───────────────────────────────────────────
echo "Step 1: Build frontend"
if [[ -n "$SKIP_BUILD" ]]; then
  info "Skipped (SKIP_BUILD=1)"
else
  (cd app/frontend && npm run build) > /dev/null 2>&1 \
    && ok "Frontend built" \
    || { fail "Frontend build failed"; exit 1; }
fi

# ── Step 2: DABs bundle deploy ───────────────────────────────────────
# Creates: app, volumes (simulation_data, static_assets, calibration_profiles,
#          demo_simulations, opensky_raw), jobs, pipelines, serving endpoints.
# Grants: SQL warehouse CAN_USE, serving endpoint CAN_QUERY (via app resources).
echo "Step 2: DABs bundle deploy"
databricks bundle deploy --target "$TARGET" 2>&1 | grep -v "^Warning:" \
  && ok "Bundle deployed (app + volumes + jobs + endpoints)" \
  || { fail "Bundle deploy failed"; exit 1; }

# ── Step 3: Detect app SP and bundle path ────────────────────────────
echo "Step 3: Detect app configuration"
APP_JSON=$(databricks apps get "$APP_NAME" --output json 2>/dev/null || echo "{}")
APP_SP=$(echo "$APP_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('service_principal_client_id',''))" 2>/dev/null || true)
BUNDLE_DIR=$(echo "$APP_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('default_source_code_path',''))" 2>/dev/null || true)
BUNDLE_DIR="${BUNDLE_DIR#/Workspace}"

if [[ -z "$APP_SP" || -z "$BUNDLE_DIR" ]]; then
  fail "Could not detect app SP or bundle dir — is the app registered?"
  exit 1
fi
ok "SP: $APP_SP"
ok "Bundle: $BUNDLE_DIR"

# ── Step 4: Create UC schema + tables (DABs can't manage these) ──────
echo "Step 4: Create UC schema + tables"

# Schema
if run_sql "CREATE SCHEMA IF NOT EXISTS \`$UC_CATALOG\`.\`$UC_SCHEMA\`"; then
  ok "Schema $UC_CATALOG.$UC_SCHEMA"
else
  fail "Could not create schema"; exit 1
fi

# Tables from airport_tables.py (single source of truth for all DDL)
TABLES_SQL=$(python3 -c "
import sys; sys.path.insert(0, '.')
from src.persistence.airport_tables import ALL_TABLES
for name, ddl in ALL_TABLES:
    sql = ddl.format(catalog='$UC_CATALOG', schema='$UC_SCHEMA')
    print(name + '|||' + ' '.join(sql.split()))
" 2>/dev/null || true)

if [[ -n "$TABLES_SQL" ]]; then
  while IFS='|||' read -r tname tsql; do
    run_sql "$tsql" && ok "Table $tname" || fail "Table $tname"
  done <<< "$TABLES_SQL"
else
  fail "Could not load table DDLs from airport_tables.py"
  exit 1
fi

# flight_status_gold — created by DLT pipeline, just verify
if run_sql "DESCRIBE TABLE \`$UC_CATALOG\`.\`$UC_SCHEMA\`.flight_status_gold"; then
  ok "Table flight_status_gold (exists via DLT)"
else
  info "Table flight_status_gold not yet created — will appear after first DLT pipeline run"
fi

# ── Step 5: Stop + start app ─────────────────────────────────────────
echo "Step 5: Restart app"
databricks apps stop "$APP_NAME" > /dev/null 2>&1 || true
ok "App stopped"
databricks apps start "$APP_NAME" > /dev/null 2>&1 &
info "App starting..."

# Wait for RUNNING state (up to 10 minutes)
TIMEOUT=600
ELAPSED=0
while [[ $ELAPSED -lt $TIMEOUT ]]; do
  STATE=$(databricks apps get "$APP_NAME" --output json 2>/dev/null \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('app_status',{}).get('state',''))" 2>/dev/null || true)
  if [[ "$STATE" == "RUNNING" ]]; then
    break
  fi
  sleep 30
  ELAPSED=$((ELAPSED + 30))
  info "Waiting for app... (${ELAPSED}s, state: ${STATE:-unknown})"
done

if [[ "$STATE" == "RUNNING" ]]; then
  ok "App is RUNNING"
else
  fail "App did not reach RUNNING state within ${TIMEOUT}s (state: ${STATE:-unknown})"
  info "Continuing with grants — some may fail if app hasn't finished initializing"
fi

# ── Step 6: Grant SP permissions (everything DABs can't manage) ──────
echo "Step 6: Grant SP permissions"
export APP_SP BUNDLE_DIR APP_NAME UC_CATALOG UC_SCHEMA WAREHOUSE_ID GENIE_SPACE_ID SECRET_SCOPE DATABRICKS_PROFILE="$PROFILE"
./scripts/grant_sp_permissions.sh

# ── Done ──────────────────────────────────────────────────────────────
echo ""
echo "═══ Deployment complete ═══"
APP_URL=$(echo "$APP_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('url',''))" 2>/dev/null || true)
echo "App URL: ${APP_URL:-https://${APP_NAME}-7474645572615955.aws.databricksapps.com}"

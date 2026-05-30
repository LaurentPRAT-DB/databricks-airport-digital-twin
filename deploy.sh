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

# Parse arguments
TARGET="dev"
BRAND="${BRAND:-databricks}"
for arg in "$@"; do
  case "$arg" in
    --seed) SEED=true ;;
    --target) :;; # next arg is the target value
    --brand) :;;  # next arg is the brand value
    *) [[ "${_prev_arg:-}" == "--target" ]] && TARGET="$arg"
       [[ "${_prev_arg:-}" == "--brand" ]] && BRAND="$arg" ;;
  esac
  _prev_arg="$arg"
done
unset _prev_arg

# Per-target defaults (catalog, schema, profile, warehouse)
_default_for_target() {
  local key="$1"
  case "$TARGET" in
    free) case "$key" in
            catalog) echo "main" ;;
            schema)  echo "airport_digital_twin" ;;
            profile) echo "LPT_FREE_EDITION" ;;
            warehouse) echo "58d41113cb262dce" ;;
            inpainting_endpoint) echo "" ;;
          esac ;;
    prod) case "$key" in
            catalog) echo "serverless_stable_3n0ihb_catalog" ;;
            schema)  echo "airport_digital_twin_prod" ;;
            profile) echo "FEVM_SERVERLESS_STABLE" ;;
            warehouse) echo "b868e84cedeb4262" ;;
            inpainting_endpoint) echo "airport-dt-aircraft-inpainting-prod" ;;
          esac ;;
    *)    case "$key" in
            catalog) echo "serverless_stable_3n0ihb_catalog" ;;
            schema)  echo "airport_digital_twin" ;;
            profile) echo "FEVM_SERVERLESS_STABLE" ;;
            warehouse) echo "b868e84cedeb4262" ;;
            inpainting_endpoint) echo "airport-dt-aircraft-inpainting-dev" ;;
          esac ;;
  esac
}

PROFILE="${DATABRICKS_PROFILE:-$(_default_for_target profile)}"
UC_CATALOG="${UC_CATALOG:-$(_default_for_target catalog)}"
UC_SCHEMA="${UC_SCHEMA:-$(_default_for_target schema)}"
WAREHOUSE_ID="${WAREHOUSE_ID:-$(_default_for_target warehouse)}"
GENIE_SPACE_ID="${GENIE_SPACE_ID:-01f12612fa6314ae943d0526f5ae3a00}"
SECRET_SCOPE="${SECRET_SCOPE:-airport-digital-twin}"
APP_NAME="${APP_NAME:-airport-digital-twin-$TARGET}"
LAKEBASE_PROJECT="${LAKEBASE_PROJECT:-airport-digital-twin}"
LAKEBASE_BRANCH="${LAKEBASE_BRANCH:-production}"
LAKEBASE_HOST="${LAKEBASE_HOST:-}"
SKIP_BUILD="${SKIP_BUILD:-}"
SEED="${SEED:-}"

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

# ── Step 0: Write build metadata for /api/version ───────────────────
git rev-parse --short HEAD > GIT_COMMIT 2>/dev/null || true
git rev-list --count HEAD > BUILD_NUMBER 2>/dev/null || true

# ── Step 1: Build frontend ───────────────────────────────────────────
echo "Step 1: Build frontend (brand: $BRAND)"
# Copy brand logo to public/ for the build
BRAND_DIR="app/frontend/brands/$BRAND"
if [[ -d "$BRAND_DIR" ]]; then
  cp "$BRAND_DIR/logo.svg" app/frontend/public/company-logo.svg
  ok "Brand logo copied from $BRAND_DIR/logo.svg"
else
  fail "Brand directory not found: $BRAND_DIR"; exit 1
fi
if [[ -n "$SKIP_BUILD" ]]; then
  info "Skipped build (SKIP_BUILD=1)"
else
  (cd app/frontend && VITE_BRAND="$BRAND" npm run build) > /dev/null 2>&1 \
    && ok "Frontend built (VITE_BRAND=$BRAND)" \
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

# ── Step 2a: Patch app.yaml on workspace with target-specific env vars ──
# DABs terraform provider doesn't apply config.env to app definitions,
# so we patch the workspace app.yaml directly after bundle deploy.
echo "Step 2a: Patch app.yaml with target-specific env vars"
BUNDLE_DIR_PATH=$(databricks bundle summary --target "$TARGET" 2>/dev/null \
  | grep "Root Path:" | sed 's/.*Root Path: *//' || true)
if [[ -z "$BUNDLE_DIR_PATH" ]]; then
  # Fallback: derive from profile user
  DEPLOY_USER=$(databricks current-user me --profile "$PROFILE" -o json 2>/dev/null \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('userName',''))" 2>/dev/null || true)
  BUNDLE_DIR_PATH="/Workspace/Users/$DEPLOY_USER/.bundle/airport-digital-twin/$TARGET/files"
fi

# Resolve LAKEBASE_HOST from databricks.yml if not set
if [[ -z "$LAKEBASE_HOST" ]]; then
  LAKEBASE_HOST=$(uv run python3 -c "
import yaml
with open('databricks.yml') as f:
    cfg = yaml.safe_load(f)
target = cfg.get('targets', {}).get('$TARGET', {})
tvars = target.get('variables', {})
print(tvars.get('lakebase_host', cfg.get('variables', {}).get('lakebase_host', {}).get('default', '')))
" 2>/dev/null || true)
fi

if [[ -n "$BUNDLE_DIR_PATH" && -n "$LAKEBASE_HOST" ]]; then
  # Download, patch, re-upload app.yaml
  TMP_YAML=$(mktemp /tmp/app_yaml_XXXXX.yaml)
  databricks workspace export "$BUNDLE_DIR_PATH/app.yaml" --profile "$PROFILE" > "$TMP_YAML" 2>/dev/null
  LAKEBASE_EP="projects/$LAKEBASE_PROJECT/branches/$LAKEBASE_BRANCH/endpoints/primary"
  uv run python3 -c "
import yaml, sys
with open('$TMP_YAML') as f:
    cfg = yaml.safe_load(f)
overrides = {
    'LAKEBASE_HOST': '$LAKEBASE_HOST',
    'LAKEBASE_ENDPOINT_NAME': '$LAKEBASE_EP',
    'DATABRICKS_HTTP_PATH': '/sql/1.0/warehouses/$WAREHOUSE_ID',
    'DATABRICKS_CATALOG': '$UC_CATALOG',
    'DATABRICKS_SCHEMA': '$UC_SCHEMA',
    'DATABRICKS_WAREHOUSE_ID': '$WAREHOUSE_ID',
}
for env in cfg.get('env', []):
    if env.get('name') in overrides:
        env['value'] = overrides[env['name']]
with open('$TMP_YAML', 'w') as f:
    yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
" 2>/dev/null
  databricks workspace delete "$BUNDLE_DIR_PATH/app.yaml" --profile "$PROFILE" 2>/dev/null || true
  databricks workspace import "$BUNDLE_DIR_PATH/app.yaml" --file "$TMP_YAML" --format AUTO --profile "$PROFILE" 2>/dev/null \
    && ok "Patched app.yaml (LAKEBASE_HOST=$LAKEBASE_HOST)" \
    || fail "Could not patch app.yaml"
  rm -f "$TMP_YAML"
else
  info "Skipped app.yaml patch (bundle dir or lakebase host not resolved)"
fi

# ── Step 2b: Upload airport configs to UC Volume ───────────────────
# Seed script reads from static_assets/airport_cache/ — upload there.
echo "Step 2b: Upload airport configs to UC Volume"
VOLUME_PATH="/Volumes/$UC_CATALOG/$UC_SCHEMA/static_assets/airport_cache"
UPLOAD_COUNT=0
for f in data/cache/airport_*.json; do
  FNAME=$(basename "$f")
  databricks fs cp "$f" "dbfs:$VOLUME_PATH/$FNAME" --overwrite --profile "$PROFILE" 2>/dev/null \
    && UPLOAD_COUNT=$((UPLOAD_COUNT + 1))
done
ok "Uploaded $UPLOAD_COUNT airport configs to $VOLUME_PATH"

# ── Step 3: Detect app SP and bundle path ────────────────────────────
echo "Step 3: Detect app configuration"
APP_JSON=$(databricks apps get "$APP_NAME" --profile "$PROFILE" --output json 2>/dev/null || echo "{}")
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

# ── Step 4b: Lakebase Autoscaling setup ──────────────────────────────
echo "Step 4b: Lakebase Autoscaling setup"
if [[ -n "$LAKEBASE_PROJECT" ]]; then
  LAKEBASE_HOST=$(uv run python3 scripts/setup_lakebase_autoscaling.py \
    --profile "$PROFILE" \
    --project-id "$LAKEBASE_PROJECT" \
    --branch "$LAKEBASE_BRANCH") \
    && ok "Lakebase ready (host: $LAKEBASE_HOST)" \
    || { fail "Lakebase setup failed (non-fatal, app will run without caching)"; LAKEBASE_HOST=""; }
else
  info "No LAKEBASE_PROJECT configured — skipping Lakebase"
fi

# ── Step 5: Stop + start app ─────────────────────────────────────────
echo "Step 5: Restart app"
databricks apps stop "$APP_NAME" --profile "$PROFILE" > /dev/null 2>&1 || true
ok "App stopped"
databricks apps start "$APP_NAME" --profile "$PROFILE" > /dev/null 2>&1 &
info "App starting..."

# Wait for RUNNING state (up to 10 minutes)
TIMEOUT=600
ELAPSED=0
while [[ $ELAPSED -lt $TIMEOUT ]]; do
  STATE=$(databricks apps get "$APP_NAME" --profile "$PROFILE" --output json 2>/dev/null \
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

# ── Step 5b: Seed Lakebase airport cache (optional) ──────────────────
if [[ -n "$SEED" ]]; then
  echo "Step 5b: Seed Lakebase airport cache from UC Volume"
  LAKEBASE_BRANCH="$TARGET"
  [[ "$TARGET" == "prod" ]] && LAKEBASE_BRANCH="production"
  uv run python3 scripts/seed_airport_cache.py \
    --profile "$PROFILE" --branch "$LAKEBASE_BRANCH" \
    --catalog "$UC_CATALOG" --schema "$UC_SCHEMA" \
    && ok "Airport cache seeded ($LAKEBASE_BRANCH)" \
    || fail "Airport cache seed failed (non-fatal, app will self-heal on startup)"
fi

# ── Step 6: Grant SP permissions (everything DABs can't manage) ──────
echo "Step 6: Grant SP permissions"
INPAINTING_ENDPOINT="${INPAINTING_ENDPOINT:-$(_default_for_target inpainting_endpoint)}"
export APP_SP BUNDLE_DIR APP_NAME UC_CATALOG UC_SCHEMA WAREHOUSE_ID GENIE_SPACE_ID SECRET_SCOPE INPAINTING_ENDPOINT DATABRICKS_PROFILE="$PROFILE"
./scripts/grant_sp_permissions.sh

# ── Done ──────────────────────────────────────────────────────────────
echo ""
echo "═══ Deployment complete ═══"
APP_URL=$(echo "$APP_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('url',''))" 2>/dev/null || true)
echo "App URL: ${APP_URL:-https://${APP_NAME}-7474645572615955.aws.databricksapps.com}"

#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# CI/CD deployment script — non-interactive version of deploy.sh
#
# Designed for GitHub Actions. Uses environment variables for auth
# (DATABRICKS_HOST, DATABRICKS_CLIENT_ID, DATABRICKS_CLIENT_SECRET)
# instead of a local CLI profile.
#
# Usage:
#   scripts/ci-deploy.sh --target prod
#
# Required env vars:
#   DATABRICKS_HOST, DATABRICKS_CLIENT_ID, DATABRICKS_CLIENT_SECRET
#
# Optional env vars (override app.yaml defaults when set):
#   DATABRICKS_WAREHOUSE_ID — SQL warehouse (blank = serverless)
#   UC_CATALOG, UC_SCHEMA — Unity Catalog target (default: airport_digital_twin)
#   LAKEBASE_HOST — Lakebase PostgreSQL host (default: dev instance)
#   LAKEBASE_ENDPOINT_NAME — Lakebase endpoint path (default: dev endpoint)
#   GENIE_SPACE_ID, SECRET_SCOPE, SKIP_BUILD
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."

TARGET="${1:-prod}"
[[ "${1:-}" == "--target" ]] && TARGET="${2:-prod}"

# Validate required env vars
for var in DATABRICKS_HOST DATABRICKS_CLIENT_ID DATABRICKS_CLIENT_SECRET; do
  if [[ -z "${!var:-}" ]]; then
    echo "ERROR: $var is not set"
    exit 1
  fi
done

UC_CATALOG="${UC_CATALOG:-airport_digital_twin}"
UC_SCHEMA="${UC_SCHEMA:-airport_digital_twin}"
WAREHOUSE_ID="${DATABRICKS_WAREHOUSE_ID:-}"
GENIE_SPACE_ID="${GENIE_SPACE_ID:-}"
SECRET_SCOPE="${SECRET_SCOPE:-airport-digital-twin}"
APP_NAME="${APP_NAME:-airport-digital-twin-$TARGET}"

ok()   { echo "  [OK] $1"; }
fail() { echo "  [FAIL] $1"; }
info() { echo "  [INFO] $1"; }

run_sql() {
  local stmt="$1"
  local json
  if [[ -n "$WAREHOUSE_ID" ]]; then
    json="{\"warehouse_id\":\"$WAREHOUSE_ID\",\"statement\":\"$stmt\",\"wait_timeout\":\"30s\"}"
  else
    json="{\"statement\":\"$stmt\",\"wait_timeout\":\"30s\"}"
  fi
  databricks api post /api/2.0/sql/statements \
    --json "$json" \
    2>/dev/null | grep -q '"SUCCEEDED"'
}

echo "═══ Airport Digital Twin — CI Deploy (target: $TARGET) ═══"
echo ""

# ── Step 0: Patch app.yaml with target-specific config ──────────────
echo "Step 0: Patch app.yaml for target '$TARGET'"
patch_env_var() {
  local varname="$1" newval="$2"
  python3 - "$varname" "$newval" <<'PYEOF'
import re, sys, pathlib
varname, newval = sys.argv[1], sys.argv[2]
p = pathlib.Path("app.yaml")
text = p.read_text()
pattern = rf'(- name: {re.escape(varname)}\n\s+value: )"[^"]*"'
text = re.sub(pattern, rf'\g<1>"{newval}"', text)
p.write_text(text)
PYEOF
}

PATCHED=0
[[ -n "${LAKEBASE_HOST:-}" ]] && patch_env_var "LAKEBASE_HOST" "$LAKEBASE_HOST" && PATCHED=1
[[ -n "${LAKEBASE_ENDPOINT_NAME:-}" ]] && patch_env_var "LAKEBASE_ENDPOINT_NAME" "$LAKEBASE_ENDPOINT_NAME" && PATCHED=1
[[ -n "${DATABRICKS_HOST:-}" ]] && patch_env_var "DATABRICKS_HOST" "${DATABRICKS_HOST#https://}" && PATCHED=1
[[ -n "${UC_CATALOG:-}" ]] && patch_env_var "DATABRICKS_CATALOG" "$UC_CATALOG" && PATCHED=1
[[ -n "${UC_SCHEMA:-}" ]] && patch_env_var "DATABRICKS_SCHEMA" "$UC_SCHEMA" && PATCHED=1
[[ -n "${DATABRICKS_WAREHOUSE_ID:-}" ]] && patch_env_var "DATABRICKS_WAREHOUSE_ID" "$DATABRICKS_WAREHOUSE_ID" && PATCHED=1
[[ -n "${DATABRICKS_WAREHOUSE_ID:-}" ]] && patch_env_var "DATABRICKS_HTTP_PATH" "/sql/1.0/warehouses/$DATABRICKS_WAREHOUSE_ID" && PATCHED=1

if [[ $PATCHED -eq 1 ]]; then
  ok "app.yaml patched for target"
else
  info "No overrides — using app.yaml defaults (dev)"
fi

# ── Step 1: DABs bundle deploy ───────────────────────────────────────
echo "Step 1: DABs bundle deploy"
databricks bundle deploy --target "$TARGET" 2>&1 | grep -v "^Warning:" \
  && ok "Bundle deployed" \
  || { fail "Bundle deploy failed"; exit 1; }

# ── Step 2: Detect app SP and bundle path ────────────────────────────
echo "Step 2: Detect app configuration"
APP_JSON=$(databricks apps get "$APP_NAME" --output json 2>/dev/null || echo "{}")
APP_SP=$(echo "$APP_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('service_principal_client_id',''))" 2>/dev/null || true)
BUNDLE_DIR=$(echo "$APP_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('default_source_code_path',''))" 2>/dev/null || true)
BUNDLE_DIR="${BUNDLE_DIR#/Workspace}"

if [[ -z "$APP_SP" || -z "$BUNDLE_DIR" ]]; then
  fail "Could not detect app SP or bundle dir"
  exit 1
fi
ok "SP: $APP_SP | Bundle: $BUNDLE_DIR"

# ── Step 3: Create UC schema + tables ────────────────────────────────
echo "Step 3: Create UC schema + tables"
if [[ -n "$UC_CATALOG" && -n "$UC_SCHEMA" ]]; then
  run_sql "CREATE SCHEMA IF NOT EXISTS \`$UC_CATALOG\`.\`$UC_SCHEMA\`" \
    && ok "Schema $UC_CATALOG.$UC_SCHEMA" \
    || fail "Could not create schema"

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
    info "Could not load table DDLs — skipping table creation"
  fi
else
  info "Skipping table creation (UC_CATALOG/UC_SCHEMA not set)"
fi

# ── Step 4: Stop + start app ─────────────────────────────────────────
echo "Step 4: Restart app"
databricks apps stop "$APP_NAME" > /dev/null 2>&1 || true
ok "App stopped"
databricks apps start "$APP_NAME" > /dev/null 2>&1 || true
info "App starting..."

TIMEOUT=600
ELAPSED=0
STATE=""
while [[ $ELAPSED -lt $TIMEOUT ]]; do
  STATE=$(databricks apps get "$APP_NAME" --output json 2>/dev/null \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('app_status',{}).get('state',''))" 2>/dev/null || true)
  if [[ "$STATE" == "RUNNING" ]]; then
    break
  fi
  sleep 30
  ELAPSED=$((ELAPSED + 30))
  info "Waiting... (${ELAPSED}s, state: ${STATE:-unknown})"
done

if [[ "$STATE" == "RUNNING" ]]; then
  ok "App is RUNNING"
else
  fail "App did not reach RUNNING state within ${TIMEOUT}s (state: ${STATE:-unknown})"
  exit 1
fi

# ── Step 5: Grant SP permissions ─────────────────────────────────────
echo "Step 5: Grant SP permissions"
export APP_SP BUNDLE_DIR APP_NAME UC_CATALOG UC_SCHEMA WAREHOUSE_ID GENIE_SPACE_ID SECRET_SCOPE
# Unset profile — CI uses env var auth
unset DATABRICKS_PROFILE 2>/dev/null || true
export DATABRICKS_PROFILE=""
./scripts/grant_sp_permissions.sh

# ── Step 6: Output app URL ───────────────────────────────────────────
APP_URL=$(echo "$APP_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('url',''))" 2>/dev/null || true)
echo ""
echo "═══ Deployment complete ═══"
echo "App URL: ${APP_URL:-unknown}"
echo "app_url=${APP_URL}" >> "${GITHUB_OUTPUT:-/dev/null}"

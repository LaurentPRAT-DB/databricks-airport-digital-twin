#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# CI/CD deployment script — non-interactive version of deploy.sh
#
# Designed for GitHub Actions. Uses environment variables for auth
# (DATABRICKS_HOST, DATABRICKS_CLIENT_ID, DATABRICKS_CLIENT_SECRET)
# instead of a local CLI profile.
#
# Usage:
#   scripts/ci-deploy.sh --target prod          # incremental deploy
#   scripts/ci-deploy.sh --target prod --seed   # first-time deploy (seeds data)
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
#
# Flags:
#   --seed  Upload calibration profiles, 3D models, and apply Lakebase schema.
#           Required on first deploy to a fresh workspace. Skip on subsequent deploys.
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"

# Parse flags
TARGET="prod"
SEED=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target) TARGET="${2:-prod}"; shift 2 ;;
    --seed)   SEED=true; shift ;;
    *)        TARGET="$1"; shift ;;
  esac
done

# Validate required env vars
if [[ -z "${DATABRICKS_HOST:-}" ]]; then
  echo "ERROR: DATABRICKS_HOST is not set"
  exit 1
fi
if [[ -z "${DATABRICKS_TOKEN:-}" && ( -z "${DATABRICKS_CLIENT_ID:-}" || -z "${DATABRICKS_CLIENT_SECRET:-}" ) ]]; then
  echo "ERROR: Set DATABRICKS_TOKEN or both DATABRICKS_CLIENT_ID + DATABRICKS_CLIENT_SECRET"
  exit 1
fi

# Resolve catalog/schema from DABs bundle variables (unless overridden via env)
# Known target → catalog/schema mappings (fallback when bundle validate unavailable in CI)
declare -A _TARGET_CATALOG
_TARGET_CATALOG[dev]="serverless_stable_3n0ihb_catalog"
_TARGET_CATALOG[prod]="serverless_stable_3n0ihb_catalog"
_TARGET_CATALOG[free]="main"
declare -A _TARGET_SCHEMA
_TARGET_SCHEMA[dev]="airport_digital_twin"
_TARGET_SCHEMA[prod]="airport_digital_twin_prod"
_TARGET_SCHEMA[free]="airport_digital_twin"

if [[ -z "${UC_CATALOG:-}" || -z "${UC_SCHEMA:-}" ]]; then
  BUNDLE_VARS=$(databricks bundle validate --target "$TARGET" --output json 2>/dev/null \
    | python3 -c "import sys,json; b=json.load(sys.stdin); v=b.get('variables',{}); print(v.get('catalog',{}).get('value',''), v.get('schema',{}).get('value',''))" 2>/dev/null) || true
  if [[ -n "$BUNDLE_VARS" && "$(echo "$BUNDLE_VARS" | cut -d' ' -f1)" != "" ]]; then
    UC_CATALOG="${UC_CATALOG:-$(echo "$BUNDLE_VARS" | cut -d' ' -f1)}"
    UC_SCHEMA="${UC_SCHEMA:-$(echo "$BUNDLE_VARS" | cut -d' ' -f2)}"
  fi
fi
UC_CATALOG="${UC_CATALOG:-${_TARGET_CATALOG[$TARGET]:-serverless_stable_3n0ihb_catalog}}"
UC_SCHEMA="${UC_SCHEMA:-${_TARGET_SCHEMA[$TARGET]:-airport_digital_twin}}"
WAREHOUSE_ID="${DATABRICKS_WAREHOUSE_ID:-}"
GENIE_SPACE_ID="${GENIE_SPACE_ID:-}"
SECRET_SCOPE="${SECRET_SCOPE:-airport-digital-twin}"
APP_NAME="${APP_NAME:-airport-digital-twin-$TARGET}"

# Resolve Lakebase branch from bundle variables (for environment isolation)
LAKEBASE_BRANCH="${LAKEBASE_BRANCH:-}"
if [[ -z "$LAKEBASE_BRANCH" ]]; then
  LAKEBASE_BRANCH=$(databricks bundle validate --target "$TARGET" --output json 2>/dev/null \
    | python3 -c "import sys,json; b=json.load(sys.stdin); print(b.get('variables',{}).get('lakebase_branch',{}).get('value','dev'))" 2>/dev/null) || true
fi
LAKEBASE_BRANCH="${LAKEBASE_BRANCH:-$TARGET}"
LAKEBASE_ENDPOINT="projects/airport-digital-twin/branches/$LAKEBASE_BRANCH/endpoints/primary"
LAKEBASE_HOST="${LAKEBASE_HOST:-ep-summer-scene-d2ew95fl.database.us-east-1.cloud.databricks.com}"
INPAINTING_ENDPOINT="${INPAINTING_ENDPOINT:-airport-dt-aircraft-inpainting-$TARGET}"

ok()   { echo "  [OK] $1"; }
fail() { echo "  [FAIL] $1"; }
info() { echo "  [INFO] $1"; }

run_sql() {
  local stmt="$1"
  local json result
  if [[ -n "$WAREHOUSE_ID" ]]; then
    json=$(jq -n --arg s "$stmt" --arg w "$WAREHOUSE_ID" \
      '{warehouse_id: $w, statement: $s, wait_timeout: "30s"}')
  else
    json=$(jq -n --arg s "$stmt" '{statement: $s, wait_timeout: "30s"}')
  fi
  result=$(databricks api post /api/2.0/sql/statements --json "$json" 2>&1)
  if echo "$result" | grep -q '"SUCCEEDED"'; then
    return 0
  else
    local err_msg
    err_msg=$(echo "$result" | python3 -c "import sys,json; r=json.load(sys.stdin); print(r.get('status',{}).get('error',{}).get('message','')[:200])" 2>/dev/null || echo "$result" | tail -1)
    [[ -n "$err_msg" ]] && echo "    SQL error: $err_msg" >&2
    return 1
  fi
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
[[ -n "${DATABRICKS_HOST:-}" ]] && patch_env_var "DATABRICKS_HOST" "${DATABRICKS_HOST#https://}" && PATCHED=1
[[ -n "${UC_CATALOG:-}" ]] && patch_env_var "DATABRICKS_CATALOG" "$UC_CATALOG" && PATCHED=1
[[ -n "${UC_SCHEMA:-}" ]] && patch_env_var "DATABRICKS_SCHEMA" "$UC_SCHEMA" && PATCHED=1
[[ -n "${DATABRICKS_WAREHOUSE_ID:-}" ]] && patch_env_var "DATABRICKS_WAREHOUSE_ID" "$DATABRICKS_WAREHOUSE_ID" && PATCHED=1
[[ -n "${DATABRICKS_WAREHOUSE_ID:-}" ]] && patch_env_var "DATABRICKS_HTTP_PATH" "/sql/1.0/warehouses/$DATABRICKS_WAREHOUSE_ID" && PATCHED=1

# Always patch target-specific Lakebase endpoint and app metadata
patch_env_var "LAKEBASE_ENDPOINT_NAME" "$LAKEBASE_ENDPOINT" && PATCHED=1
patch_env_var "DATABRICKS_APP_URL" "https://$APP_NAME-7474645572615955.aws.databricksapps.com" && PATCHED=1
patch_env_var "BUNDLE_WORKSPACE_ROOT" "/Workspace/Users/laurent.prat@databricks.com/.bundle/airport-digital-twin/$TARGET/files" && PATCHED=1

if [[ $PATCHED -eq 1 ]]; then
  ok "app.yaml patched for target (Lakebase branch: $LAKEBASE_BRANCH)"
else
  info "No overrides — using app.yaml defaults (dev)"
fi

# ── Step 1a: Create UC catalog + schema (must exist before bundle deploy creates volumes) ──
echo "Step 1: Create UC catalog/schema + deploy bundle"
if [[ -n "$UC_CATALOG" ]]; then
  run_sql "CREATE CATALOG IF NOT EXISTS \`$UC_CATALOG\`" \
    && ok "Catalog $UC_CATALOG exists" \
    || info "Could not create catalog (may already exist or insufficient perms)"
fi
if [[ -n "$UC_CATALOG" && -n "$UC_SCHEMA" ]]; then
  if run_sql "CREATE SCHEMA IF NOT EXISTS \`$UC_CATALOG\`.\`$UC_SCHEMA\`"; then
    ok "Schema $UC_CATALOG.$UC_SCHEMA exists"
  else
    if run_sql "DESCRIBE SCHEMA \`$UC_CATALOG\`.\`$UC_SCHEMA\`"; then
      ok "Schema $UC_CATALOG.$UC_SCHEMA already exists"
    else
      info "Could not verify schema via SQL API (IP ACL?) — proceeding with bundle deploy"
    fi
  fi
fi

# Write current git SHA and build number so /api/version shows the deployed commit
git rev-parse --short HEAD > GIT_COMMIT 2>/dev/null || true
git rev-list --count HEAD > BUILD_NUMBER 2>/dev/null || true

# ── Step 1b: Clean stale frontend assets + DABs bundle deploy ────────
# DABs doesn't delete old hashed asset files when new ones replace them,
# causing index.html to reference files that don't exist on the workspace.
BUNDLE_ASSETS="/Workspace/Users/laurent.prat@databricks.com/.bundle/airport-digital-twin/$TARGET/files/app/frontend/dist/assets"
databricks workspace delete "$BUNDLE_ASSETS" --recursive 2>/dev/null \
  && info "Cleaned stale frontend assets" \
  || info "No existing assets to clean (first deploy)"

databricks bundle deploy --target "$TARGET" --force-lock 2>&1 | grep -v "^Warning:" \
  && ok "Bundle deployed" \
  || { fail "Bundle deploy failed"; exit 1; }

# ── Step 2: Detect app SP and bundle path ────────────────────────────
echo "Step 2: Detect app configuration"
APP_JSON=$(databricks apps get "$APP_NAME" --output json 2>/dev/null || echo "{}")
APP_SP=$(echo "$APP_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('service_principal_client_id',''))" 2>/dev/null || true)
BUNDLE_DIR=$(echo "$APP_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('default_source_code_path',''))" 2>/dev/null || true)
BUNDLE_DIR="${BUNDLE_DIR#/Workspace}"

# Fallback: derive bundle dir from DABs convention if not in app metadata
if [[ -z "$BUNDLE_DIR" ]]; then
  DEPLOYER=$(databricks current-user me --output json 2>/dev/null \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('userName',''))" 2>/dev/null || true)
  if [[ -n "$DEPLOYER" ]]; then
    BUNDLE_DIR="/Users/$DEPLOYER/.bundle/airport-digital-twin/$TARGET/files"
  fi
fi

if [[ -z "$APP_SP" ]]; then
  fail "Could not detect app SP (app may not exist yet)"
  exit 1
fi
if [[ -z "$BUNDLE_DIR" ]]; then
  info "Could not determine bundle dir — skipping workspace permissions"
fi
ok "SP: $APP_SP | Bundle: ${BUNDLE_DIR:-<unknown>}"

# ── Step 3: Create UC tables ─────────────────────────────────────────
echo "Step 3: Create UC tables"
if [[ -n "$UC_CATALOG" && -n "$UC_SCHEMA" ]]; then
  TABLES_SQL=$(python3 -c "
import sys; sys.path.insert(0, '.')
from src.persistence.airport_tables import ALL_TABLES
for name, ddl in ALL_TABLES:
    sql = ddl.format(catalog='$UC_CATALOG', schema='$UC_SCHEMA')
    print(name + '\t' + ' '.join(sql.split()))
" 2>/dev/null || true)

  if [[ -n "$TABLES_SQL" ]]; then
    while IFS=$'\t' read -r tname tsql; do
      if [[ -z "$tsql" ]]; then continue; fi
      RESULT=$(databricks api post /api/2.0/sql/statements \
        --json "$(jq -n --arg s "$tsql" --arg w "$WAREHOUSE_ID" '{warehouse_id: $w, statement: $s, wait_timeout: "30s"}')" \
        2>&1)
      if echo "$RESULT" | grep -q '"SUCCEEDED"'; then
        ok "Table $tname"
      else
        ERR=$(echo "$RESULT" | python3 -c "import sys,json; r=json.load(sys.stdin); print(r.get('status',{}).get('error',{}).get('message','unknown')[:150])" 2>/dev/null || echo "$RESULT" | tail -3)
        fail "Table $tname: $ERR"
      fi
    done <<< "$TABLES_SQL"
  else
    info "Could not load table DDLs — skipping table creation"
  fi
else
  info "Skipping table creation (UC_CATALOG/UC_SCHEMA not set)"
fi

# ── Step 3b: Seed data (--seed flag) ────────────────────────────────
if $SEED; then
  # Ensure Lakebase branch exists (required for env isolation)
  echo "Step 3b-0: Ensure Lakebase branch '$LAKEBASE_BRANCH' exists"
  if databricks api get "/api/2.0/postgres/projects/airport-digital-twin/branches/$LAKEBASE_BRANCH" 2>/dev/null | grep -q "name"; then
    ok "Lakebase branch '$LAKEBASE_BRANCH' exists"
  else
    databricks api post "/api/2.0/postgres/projects/airport-digital-twin/branches" \
      --json "$(jq -n --arg n "$LAKEBASE_BRANCH" --arg p "production" '{name: $n, parent_branch: $p}')" 2>/dev/null \
      && ok "Created Lakebase branch '$LAKEBASE_BRANCH'" \
      || info "Could not create branch (may already exist or need manual setup)"
  fi

  echo "Step 3b: Seed data to UC Volumes"

  VOLUME_BASE="dbfs:/Volumes/$UC_CATALOG/$UC_SCHEMA"

  # Upload calibration profiles (1,183 JSON files)
  PROFILES_DIR="data/calibration/profiles"
  if [[ -d "$PROFILES_DIR" ]]; then
    PROFILE_COUNT=$(find "$PROFILES_DIR" -name "*.json" -type f | wc -l | tr -d ' ')
    echo "  Uploading $PROFILE_COUNT calibration profiles..."
    databricks fs cp "$PROFILES_DIR" "$VOLUME_BASE/calibration_profiles" \
      --recursive --overwrite 2>/dev/null \
      && ok "Calibration profiles ($PROFILE_COUNT files)" \
      || fail "Calibration profile upload"
  else
    info "No calibration profiles found at $PROFILES_DIR"
  fi

  # Upload 3D aircraft models (GLB files)
  MODELS_DIR="app/frontend/dist/models/aircraft"
  if [[ -d "$MODELS_DIR" ]]; then
    MODEL_COUNT=$(find "$MODELS_DIR" -name "*.glb" -type f | wc -l | tr -d ' ')
    echo "  Uploading $MODEL_COUNT 3D models..."
    databricks fs mkdir "$VOLUME_BASE/static_assets/models/aircraft" 2>/dev/null || true
    databricks fs cp "$MODELS_DIR" "$VOLUME_BASE/static_assets/models/aircraft" \
      --recursive --overwrite 2>/dev/null \
      && ok "3D models ($MODEL_COUNT files)" \
      || fail "3D model upload"
  else
    info "No 3D models found at $MODELS_DIR (run npm build first)"
  fi

  # Apply Lakebase schema (if Lakebase is configured)
  if [[ -n "${LAKEBASE_HOST:-}" ]]; then
    echo "  Applying Lakebase schema (branch: $LAKEBASE_BRANCH)..."
    LB_HOST="${LAKEBASE_HOST:-}"
    LB_EP="$LAKEBASE_ENDPOINT"
    # Use project venv python for SDK access (.venv created by uv sync)
    VENV_PY="$PROJECT_ROOT/.venv/bin/python"
    if [[ ! -x "$VENV_PY" ]]; then
      info "Venv not found at $VENV_PY — falling back to uv run"
      VENV_PY="uv run python3"
    fi
    _LB_SCRIPT=$(mktemp /tmp/lb_schema_XXXXXX.py)
    trap "rm -f $_LB_SCRIPT" EXIT
    cat > "$_LB_SCRIPT" <<'PYEOF'
import sys, os

lb_host, endpoint = sys.argv[1], sys.argv[2]
try:
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient()
    cred = w.postgres.generate_database_credential(endpoint=endpoint)
    me = w.current_user.me()
    token = cred.token
    user = me.user_name

    if not token:
        print("  [INFO] Could not get Lakebase credential — schema not applied")
        sys.exit(0)

    import psycopg2

    with open("scripts/lakebase_schema.sql") as f:
        schema_sql = f.read()

    conn = psycopg2.connect(
        host=lb_host, port=5432, dbname="databricks_postgres",
        user=user, password=token, sslmode="require"
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(schema_sql)
    conn.close()
    print("  [OK] Lakebase schema applied")
except Exception as e:
    print(f"  [INFO] Lakebase schema skipped: {e}")
PYEOF
    $VENV_PY "$_LB_SCRIPT" "$LB_HOST" "$LB_EP"
    rm -f "$_LB_SCRIPT"
  else
    info "Lakebase not configured — skipping schema setup"
  fi

  ok "Seed complete"
else
  info "Skipping data seed (use --seed for first-time deploy)"
fi

# ── Step 4: Stop → Deploy → Start app ────────────────────────────────
echo "Step 4: Deploy app (stop → deploy → start)"

if [[ -z "$BUNDLE_DIR" ]]; then
  fail "BUNDLE_DIR not set — cannot deploy source"
  exit 1
fi

# Check current app state and compute state
APP_STATE=$(databricks apps get "$APP_NAME" --output json 2>/dev/null \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('app_status',{}).get('state',''), d.get('compute_status',{}).get('state',''))" 2>/dev/null || true)
info "Current state: ${APP_STATE:-unknown}"

# Step 4a: Stop the app first so the deploy isn't racing with a running instance
if ! echo "$APP_STATE" | grep -q "UNAVAILABLE\|STOPPED"; then
  info "Stopping app before deploy..."
  databricks apps stop "$APP_NAME" 2>&1 | tail -3 || true
  STOP_WAIT=0
  while [[ $STOP_WAIT -lt 90 ]]; do
    STOP_STATE=$(databricks apps get "$APP_NAME" --output json 2>/dev/null \
      | python3 -c "import sys,json; print(json.load(sys.stdin).get('app_status',{}).get('state',''))" 2>/dev/null || true)
    if [[ "$STOP_STATE" == "UNAVAILABLE" || "$STOP_STATE" == "STOPPED" ]]; then break; fi
    sleep 5
    STOP_WAIT=$((STOP_WAIT + 5))
  done
  ok "App stopped (state: ${STOP_STATE:-unknown})"
fi

# Step 4b: Deploy source code (blocking — wait for deployment to complete)
info "Deploying source to /Workspace$BUNDLE_DIR..."
databricks apps deploy "$APP_NAME" --source-code-path "/Workspace$BUNDLE_DIR" 2>&1 | tail -10 || true
ok "Source deployed"

# Step 4c: Start the app with fresh code
info "Starting app..."
databricks apps start "$APP_NAME" 2>&1 | tail -3 || true

# Wait for app to reach RUNNING state
info "Waiting for app to reach RUNNING..."
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
export APP_SP BUNDLE_DIR APP_NAME UC_CATALOG UC_SCHEMA WAREHOUSE_ID GENIE_SPACE_ID SECRET_SCOPE LAKEBASE_ENDPOINT LAKEBASE_HOST INPAINTING_ENDPOINT
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

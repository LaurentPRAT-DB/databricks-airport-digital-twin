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
if [[ -z "${UC_CATALOG:-}" || -z "${UC_SCHEMA:-}" ]]; then
  BUNDLE_VARS=$(databricks bundle validate --target "$TARGET" --output json 2>/dev/null \
    | python3 -c "import sys,json; b=json.load(sys.stdin); v=b.get('variables',{}); print(v.get('catalog',{}).get('value','airport_digital_twin'), v.get('schema',{}).get('value','airport_digital_twin'))" 2>/dev/null) || true
  if [[ -n "$BUNDLE_VARS" ]]; then
    UC_CATALOG="${UC_CATALOG:-$(echo "$BUNDLE_VARS" | cut -d' ' -f1)}"
    UC_SCHEMA="${UC_SCHEMA:-$(echo "$BUNDLE_VARS" | cut -d' ' -f2)}"
  fi
fi
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

# ── Step 1a: Create UC schema (must exist before bundle deploy creates volumes) ──
echo "Step 1: Create UC schema + deploy bundle"
if [[ -n "$UC_CATALOG" && -n "$UC_SCHEMA" ]]; then
  run_sql "CREATE SCHEMA IF NOT EXISTS \`$UC_CATALOG\`.\`$UC_SCHEMA\`" \
    && ok "Schema $UC_CATALOG.$UC_SCHEMA exists" \
    || info "Could not create schema (may already exist or insufficient perms)"
fi

# ── Step 1b: DABs bundle deploy ──────────────────────────────────────
databricks bundle deploy --target "$TARGET" 2>&1 | grep -v "^Warning:" \
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

# ── Step 3b: Seed data (--seed flag) ────────────────────────────────
if $SEED; then
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
    echo "  Applying Lakebase schema..."
    LB_HOST="${LAKEBASE_HOST:-}"
    LB_EP="${LAKEBASE_ENDPOINT_NAME:-projects/airport-digital-twin/branches/production/endpoints/primary}"
    python3 - "$LB_HOST" "$LB_EP" <<'PYEOF'
import sys, subprocess, json

lb_host, endpoint = sys.argv[1], sys.argv[2]
try:
    result = subprocess.run(
        ["databricks", "api", "post", "/api/2.0/postgres/generate-database-credential",
         "--json", json.dumps({"endpoint": endpoint})],
        capture_output=True, text=True
    )
    cred = json.loads(result.stdout)
    token = cred.get("token", "")
    user = cred.get("username", "")

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
  else
    info "Lakebase not configured — skipping schema setup"
  fi

  ok "Seed complete"
else
  info "Skipping data seed (use --seed for first-time deploy)"
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

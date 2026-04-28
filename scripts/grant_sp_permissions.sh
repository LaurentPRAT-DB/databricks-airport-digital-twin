#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Grant all required permissions to the Databricks App service principal.
#
# Prerequisites — run these FIRST:
#   1. databricks bundle deploy --target dev   (creates workspace objects, volumes)
#   2. App must have been started at least once (creates UC tables via lazy DDL,
#      Lakebase tables, and registers the app SP)
#   3. DLT pipeline must have run once         (creates flight_status_gold, etc.)
#
# DABs manages: SQL warehouse (CAN_USE), serving endpoint (CAN_QUERY)
#   via resources.apps.airport_digital_twin.resources in app.yml.
# DABs also manages: all 5 volumes (calibration_profiles, demo_simulations,
#   opensky_raw, simulation_data, static_assets) via resources/*.yml.
# DABs does NOT manage: workspace object permissions, UC grants, secrets,
#   Lakebase, Genie — those are handled here.
#
# Usage:
#   ./scripts/grant_sp_permissions.sh              # uses defaults
#   APP_SP=<sp-uuid> BUNDLE_DIR=<path> ./scripts/grant_sp_permissions.sh
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Configuration (override via env vars for different workspaces) ───
APP_SP="${APP_SP:-}"
BUNDLE_DIR="${BUNDLE_DIR:-}"
APP_NAME="${APP_NAME:-airport-digital-twin-dev}"
UC_CATALOG="${UC_CATALOG:-serverless_stable_3n0ihb_catalog}"
UC_SCHEMA="${UC_SCHEMA:-airport_digital_twin}"
WAREHOUSE_ID="${WAREHOUSE_ID:-b868e84cedeb4262}"
GENIE_SPACE_ID="${GENIE_SPACE_ID:-01f12612fa6314ae943d0526f5ae3a00}"
SECRET_SCOPE="${SECRET_SCOPE:-airport-digital-twin}"
PROFILE="${DATABRICKS_PROFILE:-FEVM_SERVERLESS_STABLE}"

# ── Auto-detect SP and bundle dir from DABs if not set ──────────────
if [[ -z "$APP_SP" ]]; then
  echo "Auto-detecting app service principal..."
  APP_SP=$(databricks apps get "$APP_NAME" --output json 2>/dev/null \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('service_principal_client_id',''))" 2>/dev/null || true)
  if [[ -z "$APP_SP" ]]; then
    echo "ERROR: Could not detect APP_SP. Set APP_SP env var or pass it explicitly."
    exit 1
  fi
  echo "  Detected SP: $APP_SP"
fi

if [[ -z "$BUNDLE_DIR" ]]; then
  echo "Auto-detecting bundle workspace directory..."
  BUNDLE_DIR=$(databricks apps get "$APP_NAME" --output json 2>/dev/null \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('default_source_code_path',''))" 2>/dev/null || true)
  if [[ -z "$BUNDLE_DIR" ]]; then
    echo "ERROR: Could not detect BUNDLE_DIR. Set BUNDLE_DIR env var."
    exit 1
  fi
  BUNDLE_DIR="${BUNDLE_DIR#/Workspace}"
  echo "  Detected bundle dir: $BUNDLE_DIR"
fi

ERRORS=0
ok()   { echo "  [OK] $1"; }
skip() { echo "  [SKIP] $1"; }
fail() { echo "  [FAIL] $1"; ERRORS=$((ERRORS + 1)); }

# ── Helper: run SQL via Statements API ───────────────────────────────
run_sql() {
  local stmt="$1"
  databricks api post /api/2.0/sql/statements \
    --profile "$PROFILE" \
    --json "{\"warehouse_id\":\"$WAREHOUSE_ID\",\"statement\":\"$stmt\",\"wait_timeout\":\"30s\"}" \
    2>/dev/null | grep -q '"SUCCEEDED"'
}

# ── Helper: check if UC object exists ────────────────────────────────
object_exists() {
  local kind="$1" fqn="$2"
  run_sql "DESCRIBE $kind \`${fqn//./\`.\`}\`"
}

# ── 1. Workspace: CAN_READ on bundle directory ──────────────────────
echo ""
echo "1. Workspace directory permissions..."
DIR_ID=$(databricks workspace get-status "$BUNDLE_DIR" --output json 2>/dev/null \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['object_id'])" 2>/dev/null || echo "")
if [[ -n "$DIR_ID" ]]; then
  databricks workspace update-permissions directories "$DIR_ID" --json "{
    \"access_control_list\": [
      {\"service_principal_name\": \"$APP_SP\", \"permission_level\": \"CAN_READ\"}
    ]
  }" > /dev/null 2>&1 && ok "CAN_READ on bundle directory" || fail "Could not set CAN_READ on bundle directory"
else
  fail "Bundle directory not found at $BUNDLE_DIR — run 'databricks bundle deploy' first"
fi

# ── 2. Workspace: CAN_RUN on simulation notebook ────────────────────
echo "2. Simulation notebook permissions..."
NB_ID=$(databricks workspace get-status "$BUNDLE_DIR/databricks/notebooks/run_simulation_airport" --output json 2>/dev/null \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['object_id'])" 2>/dev/null || echo "")
if [[ -n "$NB_ID" ]]; then
  databricks workspace update-permissions notebooks "$NB_ID" --json "{
    \"access_control_list\": [
      {\"service_principal_name\": \"$APP_SP\", \"permission_level\": \"CAN_RUN\"}
    ]
  }" > /dev/null 2>&1 && ok "CAN_RUN on run_simulation_airport" || fail "Could not set CAN_RUN on notebook"
else
  fail "Notebook not found — run 'databricks bundle deploy' first"
fi

# ── 3. Unity Catalog: schema-level privileges ────────────────────────
echo "3. Unity Catalog grants..."

# Catalog + schema access (must exist from DABs deploy)
if run_sql "GRANT USE CATALOG ON CATALOG \`$UC_CATALOG\` TO \`$APP_SP\`"; then
  ok "USE CATALOG on $UC_CATALOG"
else
  fail "USE CATALOG — catalog '$UC_CATALOG' may not exist"
fi

if run_sql "GRANT USE SCHEMA ON SCHEMA \`$UC_CATALOG\`.\`$UC_SCHEMA\` TO \`$APP_SP\`"; then
  ok "USE SCHEMA on $UC_CATALOG.$UC_SCHEMA"
else
  fail "USE SCHEMA — schema '$UC_SCHEMA' may not exist"
fi

# Tables: check existence, then grant (all tables from airport_tables.py + DLT)
TABLES=(
  airport_metadata gates terminals runways taxiways aprons buildings hangars
  helipads parking_positions osm_runways flight_positions_history
  flight_phase_transition_history gate_assignment_history ml_prediction_history
  airport_profiles opensky_phase_transitions opensky_gate_events
  opensky_enriched_snapshots simulation_runs simulation_drafts
  flight_status_gold
)
for table in "${TABLES[@]}"; do
  fqn="$UC_CATALOG.$UC_SCHEMA.$table"
  if object_exists TABLE "$fqn"; then
    if run_sql "GRANT SELECT, MODIFY ON TABLE \`$UC_CATALOG\`.\`$UC_SCHEMA\`.\`$table\` TO \`$APP_SP\`"; then
      ok "SELECT, MODIFY on $table"
    else
      fail "Could not grant on $table"
    fi
  else
    skip "$table — table does not exist yet (created by DLT pipeline or app startup)"
  fi
done

# Volumes: check existence, then grant (all DABs-managed volumes)
VOLUMES=(simulation_data demo_simulations calibration_profiles static_assets opensky_raw)
for volume in "${VOLUMES[@]}"; do
  fqn="$UC_CATALOG.$UC_SCHEMA.$volume"
  if object_exists VOLUME "$fqn"; then
    if run_sql "GRANT READ VOLUME, WRITE VOLUME ON VOLUME \`$UC_CATALOG\`.\`$UC_SCHEMA\`.\`$volume\` TO \`$APP_SP\`"; then
      ok "READ/WRITE VOLUME on $volume"
    else
      fail "Could not grant on volume $volume"
    fi
  else
    skip "$volume — volume does not exist yet (created by DABs deploy or manually)"
  fi
done

# ── 4. Secret scope: READ ────────────────────────────────────────────
echo "4. Secret scope permissions..."
if databricks secrets list-scopes --profile "$PROFILE" 2>/dev/null | grep -q "$SECRET_SCOPE"; then
  databricks secrets put-acl "$SECRET_SCOPE" "$APP_SP" READ --profile "$PROFILE" \
    > /dev/null 2>&1 && ok "READ on secret scope '$SECRET_SCOPE'" || fail "Could not set ACL on secret scope"
else
  skip "Secret scope '$SECRET_SCOPE' does not exist — create it if OpenSky credentials are needed"
fi

# ── 5. Genie space: access ───────────────────────────────────────────
echo "5. Genie space permissions..."
if [[ -n "$GENIE_SPACE_ID" ]]; then
  databricks api patch "/api/2.0/genie/spaces/$GENIE_SPACE_ID" \
    --profile "$PROFILE" \
    --json "{\"acl\":{\"principal_type\":\"SERVICE_PRINCIPAL\",\"principal_id\":\"$APP_SP\",\"permission\":\"CAN_USE\"}}" \
    > /dev/null 2>&1 && ok "CAN_USE on Genie space" || skip "Genie space grant (may need manual setup via UI)"
else
  skip "No GENIE_SPACE_ID configured"
fi

# ── 6. Lakebase ──────────────────────────────────────────────────────
echo "6. Lakebase permissions..."
ok "Handled by Databricks Apps platform (OAuth via WorkspaceClient)"

# ── 7. DABs-managed (informational) ─────────────────────────────────
echo "7. DABs-managed resources (informational)..."
ok "SQL Warehouse CAN_USE ($WAREHOUSE_ID) — via resources/app.yml"
ok "Serving endpoint CAN_QUERY — via resources/app.yml"
ok "Volumes (calibration_profiles, demo_simulations, opensky_raw, simulation_data, static_assets) — via resources/*.yml"

# ── Summary ──────────────────────────────────────────────────────────
echo ""
if [[ $ERRORS -gt 0 ]]; then
  echo "=== $ERRORS error(s) — fix the above and re-run ==="
  exit 1
else
  echo "=== All permissions configured successfully ==="
fi

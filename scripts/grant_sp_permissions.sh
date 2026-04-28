#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Grant all required permissions to the Databricks App service principal.
# Run after `databricks bundle deploy --target <target>`.
#
# DABs manages: SQL warehouse (CAN_USE), serving endpoint (CAN_QUERY)
#   via resources.apps.airport_digital_twin.resources in app.yml.
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
UC_CATALOG="${UC_CATALOG:-serverless_stable_3n0ihb_catalog}"
UC_SCHEMA="${UC_SCHEMA:-airport_digital_twin}"
WAREHOUSE_ID="${WAREHOUSE_ID:-b868e84cedeb4262}"
GENIE_SPACE_ID="${GENIE_SPACE_ID:-01f12612fa6314ae943d0526f5ae3a00}"
SECRET_SCOPE="${SECRET_SCOPE:-airport-digital-twin}"

# ── Auto-detect SP and bundle dir from DABs if not set ──────────────
if [[ -z "$APP_SP" ]]; then
  echo "Auto-detecting app service principal..."
  APP_SP=$(databricks apps get airport-digital-twin-dev --output json 2>/dev/null \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('service_principal_client_id',''))" 2>/dev/null || true)
  if [[ -z "$APP_SP" ]]; then
    echo "ERROR: Could not detect APP_SP. Set APP_SP env var or pass it explicitly."
    exit 1
  fi
  echo "  Detected SP: $APP_SP"
fi

if [[ -z "$BUNDLE_DIR" ]]; then
  echo "Auto-detecting bundle workspace directory..."
  BUNDLE_DIR=$(databricks apps get airport-digital-twin-dev --output json 2>/dev/null \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('default_source_code_path',''))" 2>/dev/null || true)
  if [[ -z "$BUNDLE_DIR" ]]; then
    echo "ERROR: Could not detect BUNDLE_DIR. Set BUNDLE_DIR env var."
    exit 1
  fi
  # Strip /Workspace prefix if present
  BUNDLE_DIR="${BUNDLE_DIR#/Workspace}"
  echo "  Detected bundle dir: $BUNDLE_DIR"
fi

ok() { echo "  [OK] $1"; }
skip() { echo "  [SKIP] $1"; }
fail() { echo "  [WARN] $1"; }

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
  }" > /dev/null 2>&1 && ok "CAN_READ on bundle directory ($DIR_ID)" || fail "Could not set CAN_READ on bundle directory"
else
  fail "Bundle directory not found at $BUNDLE_DIR"
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
  }" > /dev/null 2>&1 && ok "CAN_RUN on run_simulation_airport ($NB_ID)" || fail "Could not set CAN_RUN on notebook"
else
  fail "Notebook not found — deploy first"
fi

# ── 3. Unity Catalog: schema-level privileges ────────────────────────
# The SP needs USE CATALOG, USE SCHEMA, SELECT/MODIFY on tables, READ/WRITE VOLUME
echo "3. Unity Catalog grants..."

PROFILE="${DATABRICKS_PROFILE:-FEVM_SERVERLESS_STABLE}"

run_sql() {
  local stmt="$1"
  databricks api post /api/2.0/sql/statements \
    --profile "$PROFILE" \
    --json "{\"warehouse_id\":\"$WAREHOUSE_ID\",\"statement\":\"$stmt\",\"wait_timeout\":\"30s\"}" \
    > /dev/null 2>&1
}

run_sql "GRANT USE CATALOG ON CATALOG \`$UC_CATALOG\` TO \`$APP_SP\`" \
  && ok "USE CATALOG on $UC_CATALOG" || fail "USE CATALOG grant"
run_sql "GRANT USE SCHEMA ON SCHEMA \`$UC_CATALOG\`.\`$UC_SCHEMA\` TO \`$APP_SP\`" \
  && ok "USE SCHEMA on $UC_CATALOG.$UC_SCHEMA" || fail "USE SCHEMA grant"

# Tables the app reads/writes
for table in flight_status_gold flight_positions_history simulation_runs simulation_drafts; do
  run_sql "GRANT SELECT, MODIFY ON TABLE \`$UC_CATALOG\`.\`$UC_SCHEMA\`.\`$table\` TO \`$APP_SP\`" \
    && ok "SELECT, MODIFY on $table" || fail "Grant on $table (may not exist yet)"
done

# UC Volumes the app reads/writes
for volume in simulation_data demo_simulations calibration_profiles static_assets; do
  run_sql "GRANT READ VOLUME, WRITE VOLUME ON VOLUME \`$UC_CATALOG\`.\`$UC_SCHEMA\`.\`$volume\` TO \`$APP_SP\`" \
    && ok "READ/WRITE VOLUME on $volume" || fail "Grant on volume $volume (may not exist yet)"
done

# ── 4. Secret scope: READ on airport-digital-twin ────────────────────
echo "4. Secret scope permissions..."
databricks secrets put-acl "$SECRET_SCOPE" "$APP_SP" READ --profile "$PROFILE" \
  > /dev/null 2>&1 && ok "READ on secret scope '$SECRET_SCOPE'" || fail "Secret scope grant (scope may not exist)"

# ── 5. Genie space: access ───────────────────────────────────────────
echo "5. Genie space permissions..."
if [[ -n "$GENIE_SPACE_ID" ]]; then
  # Genie space permissions are managed via the Genie UI or API
  # The SP needs to be added as a user of the space
  databricks api patch "/api/2.0/genie/spaces/$GENIE_SPACE_ID" \
    --profile "$PROFILE" \
    --json "{\"acl\":{\"principal_type\":\"SERVICE_PRINCIPAL\",\"principal_id\":\"$APP_SP\",\"permission\":\"CAN_USE\"}}" \
    > /dev/null 2>&1 && ok "CAN_USE on Genie space $GENIE_SPACE_ID" || skip "Genie space grant (may need manual setup via UI)"
else
  skip "No GENIE_SPACE_ID configured"
fi

# ── 6. Lakebase: endpoint access ─────────────────────────────────────
echo "6. Lakebase permissions..."
echo "  [INFO] Lakebase uses OAuth credentials from WorkspaceClient."
echo "  [INFO] The SP needs workspace-level access to call postgres.generate_database_credential."
echo "  [INFO] This is granted automatically when the app is registered."
ok "Lakebase — handled by Databricks Apps platform"

# ── 7. SQL Warehouse + Serving Endpoint (already in app.yml) ─────────
echo "7. DABs-managed resources (informational)..."
ok "SQL Warehouse CAN_USE ($WAREHOUSE_ID) — managed by resources/app.yml"
ok "Serving endpoint CAN_QUERY — managed by resources/app.yml"

echo ""
echo "=== Permission setup complete ==="
echo "Resources managed by DABs (app.yml): SQL warehouse, serving endpoints"
echo "Resources managed by this script: workspace objects, UC grants, secrets, Genie"

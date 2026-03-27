#!/usr/bin/env bash
# =============================================================================
# bootstrap.sh — Deploy Airport Digital Twin to a fresh Databricks workspace
#
# Takes a backup tarball (from backup.sh) or the live repo and sets up all
# workspace resources from scratch:
#   1. Create UC catalog + schema (or use existing)
#   2. Create UC Volume and upload 3D models
#   3. Create Lakebase project + apply schema
#   4. Create Genie Space (optional, can be skipped)
#   5. Patch app.yaml + databricks.yml with target workspace values
#   6. Build frontend (if needed)
#   7. Run databricks bundle deploy
#   8. Start the app
#
# Usage:
#   # From a backup tarball
#   tar xzf airport-digital-twin-backup-*.tar.gz
#   cd airport-digital-twin-backup-*/repo
#   ./scripts/bootstrap.sh --profile TARGET --warehouse-id abc123
#
#   # From the live repo (deploy to a different workspace)
#   ./scripts/bootstrap.sh --profile OTHER_WS --catalog my_catalog \
#       --warehouse-id abc123
#
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Defaults ----------------------------------------------------------------
PROFILE=""
CATALOG=""
SCHEMA="airport_digital_twin"
WAREHOUSE_ID=""
BACKUP_DIR=""  # Parent of repo/ if restoring from backup
LAKEBASE_PROJECT="airport-digital-twin"
SKIP_LAKEBASE=false
SKIP_GENIE=false
SKIP_BUILD=false
TARGET_NAME="dev"
DRY_RUN=false

# --- Parse args --------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)        PROFILE="$2"; shift 2 ;;
    --catalog)        CATALOG="$2"; shift 2 ;;
    --schema)         SCHEMA="$2"; shift 2 ;;
    --warehouse-id)   WAREHOUSE_ID="$2"; shift 2 ;;
    --backup-dir)     BACKUP_DIR="$2"; shift 2 ;;
    --lakebase-project) LAKEBASE_PROJECT="$2"; shift 2 ;;
    --target)         TARGET_NAME="$2"; shift 2 ;;
    --skip-lakebase)  SKIP_LAKEBASE=true; shift ;;
    --skip-genie)     SKIP_GENIE=true; shift ;;
    --skip-build)     SKIP_BUILD=true; shift ;;
    --dry-run)        DRY_RUN=true; shift ;;
    -h|--help)
      cat << 'HELP'
Usage: bootstrap.sh --profile PROFILE --warehouse-id ID [OPTIONS]

Required:
  --profile PROFILE       Databricks CLI profile for the target workspace
  --warehouse-id ID       SQL Warehouse ID to use

Options:
  --catalog CATALOG       UC catalog name (default: auto-detect from profile)
  --schema SCHEMA         UC schema name (default: airport_digital_twin)
  --backup-dir DIR        Path to backup directory (contains uc_volumes/, etc.)
  --lakebase-project NAME Lakebase project name (default: airport-digital-twin)
  --target TARGET         Bundle target name (default: dev)
  --skip-lakebase         Skip Lakebase setup (app runs in demo mode without it)
  --skip-genie            Skip Genie Space setup
  --skip-build            Skip frontend build (use existing dist/)
  --dry-run               Show what would be done without executing
HELP
      exit 0 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

# --- Validation --------------------------------------------------------------
if [[ -z "$PROFILE" ]]; then
  echo "ERROR: --profile is required"
  echo "Run: $0 --help"
  exit 1
fi

if [[ -z "$WAREHOUSE_ID" ]]; then
  echo "ERROR: --warehouse-id is required"
  echo "Run: $0 --help"
  exit 1
fi

# Resolve workspace host
WS_HOST=$(databricks auth describe --profile "$PROFILE" 2>/dev/null \
  | grep -oP 'Host:\s*\K\S+' || true)
if [[ -z "$WS_HOST" ]]; then
  # Try from config
  WS_HOST=$(grep -A5 "\[$PROFILE\]" ~/.databrickscfg 2>/dev/null \
    | grep host | head -1 | awk '{print $3}' | sed 's|https://||' || true)
fi

if [[ -z "$WS_HOST" ]]; then
  echo "ERROR: Could not determine workspace host for profile '$PROFILE'"
  echo "Run: databricks configure --profile $PROFILE"
  exit 1
fi

# Auto-detect catalog if not provided
if [[ -z "$CATALOG" ]]; then
  echo "Detecting default catalog for workspace..."
  CATALOG=$(databricks api get /api/2.1/unity-catalog/current-metastore-assignment \
    --profile "$PROFILE" 2>/dev/null \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('default_catalog_name','main'))" \
    2>/dev/null || echo "main")
  echo "  Using catalog: $CATALOG"
fi

echo "============================================="
echo "  Airport Digital Twin — Bootstrap"
echo "============================================="
echo "Target workspace: $WS_HOST"
echo "Profile:          $PROFILE"
echo "Catalog:          $CATALOG.$SCHEMA"
echo "Warehouse:        $WAREHOUSE_ID"
echo "Bundle target:    $TARGET_NAME"
echo "Backup dir:       ${BACKUP_DIR:-<none — using repo assets>}"
echo "Skip Lakebase:    $SKIP_LAKEBASE"
echo "Skip Genie:       $SKIP_GENIE"
echo ""

if $DRY_RUN; then
  echo "[DRY RUN] Would execute the steps below. Exiting."
  exit 0
fi

# --- Helper: resolve model assets directory ----------------------------------
get_models_dir() {
  # Prefer backup dir, then local dist/models, then public/models
  if [[ -n "$BACKUP_DIR" && -d "$BACKUP_DIR/uc_volumes/models/aircraft" ]]; then
    echo "$BACKUP_DIR/uc_volumes/models/aircraft"
  elif [[ -d "$REPO_ROOT/app/frontend/dist/models/aircraft" ]]; then
    echo "$REPO_ROOT/app/frontend/dist/models/aircraft"
  elif [[ -d "$REPO_ROOT/app/frontend/public/models/aircraft" ]]; then
    echo "$REPO_ROOT/app/frontend/public/models/aircraft"
  else
    echo ""
  fi
}

# =============================================================================
# Step 1: UC Catalog + Schema
# =============================================================================
echo "[1/7] Setting up Unity Catalog..."

# Create schema (catalog should already exist in most workspaces)
databricks api post /api/2.1/unity-catalog/schemas \
  --profile "$PROFILE" \
  --json "{\"name\":\"$SCHEMA\",\"catalog_name\":\"$CATALOG\",\"comment\":\"Airport Digital Twin\"}" \
  2>/dev/null || echo "  Schema $CATALOG.$SCHEMA already exists (OK)"

echo "  ✓ $CATALOG.$SCHEMA ready"

# =============================================================================
# Step 2: UC Volume + 3D Models
# =============================================================================
echo "[2/7] Creating UC Volume and uploading 3D models..."

databricks volumes create "$CATALOG" "$SCHEMA" static_assets MANAGED \
  --comment "3D model assets for Airport Digital Twin frontend" \
  --profile "$PROFILE" 2>/dev/null || echo "  Volume already exists (OK)"

MODELS_SRC=$(get_models_dir)
if [[ -n "$MODELS_SRC" ]]; then
  VOLUME_PATH="dbfs:/Volumes/$CATALOG/$SCHEMA/static_assets/models/aircraft"
  databricks fs mkdir "$VOLUME_PATH" --profile "$PROFILE" 2>/dev/null || true

  COUNT=0
  for f in "$MODELS_SRC"/*.glb; do
    [[ -f "$f" ]] || continue
    NAME=$(basename "$f")
    echo "  Uploading $NAME..."
    databricks fs cp "$f" "$VOLUME_PATH/$NAME" --profile "$PROFILE" --overwrite
    COUNT=$((COUNT + 1))
  done
  echo "  ✓ Uploaded $COUNT model files"
else
  echo "  WARNING: No model files found. 3D view will use fallback geometry."
fi

# =============================================================================
# Step 3: Lakebase (optional)
# =============================================================================
LAKEBASE_HOST=""
LAKEBASE_ENDPOINT=""

if $SKIP_LAKEBASE; then
  echo "[3/7] Skipping Lakebase setup (--skip-lakebase)"
else
  echo "[3/7] Setting up Lakebase Autoscaling..."

  # Create project
  databricks postgres create-project "$LAKEBASE_PROJECT" \
    --profile "$PROFILE" 2>/dev/null || echo "  Project already exists (OK)"

  # Get endpoint info
  ENDPOINT_JSON=$(databricks postgres get-endpoint \
    "projects/$LAKEBASE_PROJECT/branches/production/endpoints/primary" \
    --profile "$PROFILE" 2>/dev/null || echo "{}")

  LAKEBASE_HOST=$(echo "$ENDPOINT_JSON" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('hostname',''))
except: pass
" 2>/dev/null || true)

  LAKEBASE_ENDPOINT="projects/$LAKEBASE_PROJECT/branches/production/endpoints/primary"

  if [[ -n "$LAKEBASE_HOST" ]]; then
    echo "  ✓ Lakebase endpoint: $LAKEBASE_HOST"
    echo "  Applying schema (run setup_lakebase.py manually for full setup)"
  else
    echo "  WARNING: Could not detect Lakebase endpoint. Configure manually in app.yaml."
  fi
fi

# =============================================================================
# Step 4: Genie Space (optional)
# =============================================================================
GENIE_SPACE_ID=""

if $SKIP_GENIE; then
  echo "[4/7] Skipping Genie Space setup (--skip-genie)"
else
  echo "[4/7] Genie Space setup..."
  echo "  NOTE: Genie Spaces must be created manually via the UI."
  echo "  After creation, update GENIE_SPACE_ID in app.yaml."
  echo "  The app works without it (chat feature will be disabled)."
fi

# =============================================================================
# Step 5: Patch configs
# =============================================================================
echo "[5/7] Patching app.yaml and databricks.yml for target workspace..."

# Compute HTTP path
HTTP_PATH="/sql/1.0/warehouses/$WAREHOUSE_ID"

# Patch app.yaml
cd "$REPO_ROOT"
cp app.yaml app.yaml.bak

# Replace workspace-specific values
sed -i.tmp \
  -e "s|fevm-serverless-stable-3n0ihb\.cloud\.databricks\.com|$WS_HOST|g" \
  -e "s|/sql/1.0/warehouses/b868e84cedeb4262|$HTTP_PATH|g" \
  -e "s|b868e84cedeb4262|$WAREHOUSE_ID|g" \
  -e "s|serverless_stable_3n0ihb_catalog|$CATALOG|g" \
  app.yaml

# Patch Lakebase if available
if [[ -n "$LAKEBASE_HOST" ]]; then
  sed -i.tmp \
    -e "s|ep-summer-scene-d2ew95fl\.database\.us-east-1\.cloud\.databricks\.com|$LAKEBASE_HOST|g" \
    -e "s|projects/airport-digital-twin/branches/production/endpoints/primary|$LAKEBASE_ENDPOINT|g" \
    app.yaml
fi

# Patch Genie Space ID if available
if [[ -n "$GENIE_SPACE_ID" ]]; then
  sed -i.tmp \
    -e "s|01f12612fa6314ae943d0526f5ae3a00|$GENIE_SPACE_ID|g" \
    app.yaml
fi

rm -f app.yaml.tmp

# Patch databricks.yml — add/update target
# Create a new target block if not already matching
if ! grep -q "profile: $PROFILE" databricks.yml; then
  cat >> databricks.yml << TARGET

  $TARGET_NAME:
    mode: development
    workspace:
      profile: $PROFILE
    variables:
      catalog: "$CATALOG"
      schema: "$SCHEMA"
TARGET
  echo "  Added target '$TARGET_NAME' to databricks.yml"
fi

# Patch resources/app.yml warehouse ID
sed -i.tmp \
  -e "s|b868e84cedeb4262|$WAREHOUSE_ID|g" \
  resources/app.yml
rm -f resources/app.yml.tmp

echo "  ✓ Configs patched (backup saved as app.yaml.bak)"

# =============================================================================
# Step 6: Build frontend
# =============================================================================
if $SKIP_BUILD; then
  echo "[6/7] Skipping frontend build (--skip-build)"
else
  echo "[6/7] Building frontend..."
  cd "$REPO_ROOT/app/frontend"
  if [[ -f package.json ]]; then
    npm install --silent 2>/dev/null
    npm run build 2>&1 | tail -3
    echo "  ✓ Frontend built"
  else
    echo "  WARNING: No package.json found, skipping build"
  fi
fi

# =============================================================================
# Step 7: Deploy
# =============================================================================
echo "[7/7] Deploying to Databricks..."
cd "$REPO_ROOT"
databricks bundle deploy --target "$TARGET_NAME" 2>&1

echo ""
echo "Starting the app..."
APP_NAME="airport-digital-twin-$TARGET_NAME"
databricks apps start "$APP_NAME" --no-wait --profile "$PROFILE" 2>&1 | \
  python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(f\"  App URL: {d.get('url','unknown')}\")
    print(f\"  Status:  {d.get('compute_status',{}).get('state','unknown')}\")
except: print(sys.stdin.read())
" 2>/dev/null || true

echo ""
echo "============================================="
echo "  Bootstrap complete!"
echo "============================================="
echo ""
echo "Next steps:"
echo "  1. Wait ~2 min for the app to start"
echo "  2. Visit the app URL above"
if ! $SKIP_LAKEBASE && [[ -z "$LAKEBASE_HOST" ]]; then
  echo "  3. Set up Lakebase manually: python scripts/setup_lakebase.py"
fi
if $SKIP_GENIE || [[ -z "$GENIE_SPACE_ID" ]]; then
  echo "  3. (Optional) Create a Genie Space and update GENIE_SPACE_ID in app.yaml"
fi
echo ""
echo "To run DLT pipeline:  databricks bundle run airport_dlt_pipeline --target $TARGET_NAME"
echo "To run tests:         databricks bundle run unit_test --target $TARGET_NAME"

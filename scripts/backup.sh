#!/usr/bin/env bash
# =============================================================================
# backup.sh — Package the Airport Digital Twin for offline / cross-workspace use
#
# Creates a self-contained tarball with:
#   - Git repo snapshot (working tree, not .git history)
#   - 3D model assets from UC Volumes
#   - Calibration profiles (already in repo)
#   - Lakebase schema DDL
#   - UC table DDL (tables are recreated by DLT / sync scripts, not exported)
#   - Workspace-portable app.yaml template
#
# Usage:
#   ./scripts/backup.sh                          # uses default profile
#   ./scripts/backup.sh --profile MY_PROFILE     # custom Databricks profile
#   ./scripts/backup.sh --output /tmp/backup.tar.gz
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Defaults ----------------------------------------------------------------
PROFILE="FEVM_SERVERLESS_STABLE"
CATALOG="serverless_stable_3n0ihb_catalog"
SCHEMA="airport_digital_twin"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
OUTPUT=""

# --- Parse args --------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)  PROFILE="$2"; shift 2 ;;
    --catalog)  CATALOG="$2"; shift 2 ;;
    --schema)   SCHEMA="$2"; shift 2 ;;
    --output)   OUTPUT="$2"; shift 2 ;;
    -h|--help)
      echo "Usage: $0 [--profile PROFILE] [--catalog CATALOG] [--schema SCHEMA] [--output FILE]"
      exit 0 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

BACKUP_DIR="$(mktemp -d)/airport-digital-twin-backup-${TIMESTAMP}"
OUTPUT="${OUTPUT:-${REPO_ROOT}/airport-digital-twin-backup-${TIMESTAMP}.tar.gz}"

mkdir -p "$BACKUP_DIR"
echo "=== Airport Digital Twin Backup ==="
echo "Profile:  $PROFILE"
echo "Catalog:  $CATALOG.$SCHEMA"
echo "Output:   $OUTPUT"
echo "Staging:  $BACKUP_DIR"
echo ""

# --- 1. Repo snapshot (working tree, no .git) --------------------------------
echo "[1/5] Packaging repo snapshot..."
cd "$REPO_ROOT"
# Use git archive for tracked files, then overlay untracked dist/
git archive HEAD --prefix=repo/ | tar -x -C "$BACKUP_DIR"

# Include the built frontend dist (not in git but needed for deployment)
if [[ -d app/frontend/dist ]]; then
  echo "  Including frontend dist/ build..."
  mkdir -p "$BACKUP_DIR/repo/app/frontend/dist"
  rsync -a --exclude='models/' app/frontend/dist/ "$BACKUP_DIR/repo/app/frontend/dist/"
fi

echo "  Repo snapshot: $(du -sh "$BACKUP_DIR/repo" | cut -f1)"

# --- 2. UC Volumes assets (3D models) ---------------------------------------
echo "[2/5] Downloading 3D models from UC Volumes..."
MODELS_DIR="$BACKUP_DIR/uc_volumes/models/aircraft"
mkdir -p "$MODELS_DIR"

VOLUMES_PATH="dbfs:/Volumes/$CATALOG/$SCHEMA/static_assets/models/aircraft"
if databricks fs ls "$VOLUMES_PATH" --profile "$PROFILE" &>/dev/null; then
  databricks fs cp -r "$VOLUMES_PATH" "$MODELS_DIR" --profile "$PROFILE" --overwrite
  echo "  Downloaded: $(ls "$MODELS_DIR" | wc -l | tr -d ' ') model files ($(du -sh "$MODELS_DIR" | cut -f1))"
else
  echo "  WARNING: UC Volumes path not found, copying from local dist/models/ instead"
  if [[ -d "$REPO_ROOT/app/frontend/dist/models/aircraft" ]]; then
    cp "$REPO_ROOT/app/frontend/dist/models/aircraft/"*.glb "$MODELS_DIR/" 2>/dev/null || true
    echo "  Copied from local: $(ls "$MODELS_DIR" | wc -l | tr -d ' ') files"
  fi
fi

# --- 3. Lakebase schema DDL -------------------------------------------------
echo "[3/5] Including Lakebase schema..."
mkdir -p "$BACKUP_DIR/lakebase"
cp "$REPO_ROOT/scripts/lakebase_schema.sql" "$BACKUP_DIR/lakebase/"
cp "$REPO_ROOT/scripts/setup_lakebase.py" "$BACKUP_DIR/lakebase/"
echo "  Included lakebase_schema.sql + setup_lakebase.py"

# --- 4. UC table DDL (tables are created by DLT / sync scripts) -------------
echo "[4/5] Including UC table setup scripts..."
mkdir -p "$BACKUP_DIR/uc_tables"
cp "$REPO_ROOT/scripts/setup_trajectory_tables.py" "$BACKUP_DIR/uc_tables/"
# Export DLT pipeline config
cp "$REPO_ROOT/databricks/dlt_pipeline_config.json" "$BACKUP_DIR/uc_tables/" 2>/dev/null || true
# Export table DDL via Databricks SQL (informational, not required for restore)
if command -v databricks &>/dev/null; then
  echo "  Exporting table DDL from $CATALOG.$SCHEMA..."
  for TABLE in flight_status_gold flight_positions_history airport_profiles; do
    DDL=$(databricks api post /api/2.0/sql/statements \
      --profile "$PROFILE" \
      --json "{\"warehouse_id\":\"b868e84cedeb4262\",\"statement\":\"SHOW CREATE TABLE $CATALOG.$SCHEMA.$TABLE\",\"wait_timeout\":\"30s\"}" \
      2>/dev/null | python3 -c "
import sys, json
try:
    r = json.load(sys.stdin)
    chunks = r.get('result',{}).get('data_array',[])
    print(chunks[0][0] if chunks else '-- Table not found')
except: print('-- Could not export DDL')
" 2>/dev/null || echo "-- Could not export DDL for $TABLE")
    echo "$DDL" > "$BACKUP_DIR/uc_tables/${TABLE}.sql"
  done
  echo "  Exported DDL for 3 tables"
fi

# --- 5. Workspace-portable config template -----------------------------------
echo "[5/5] Creating portable config template..."
mkdir -p "$BACKUP_DIR/config"

# Create app.yaml.template with placeholder variables
sed \
  -e 's|fevm-serverless-stable-3n0ihb\.cloud\.databricks\.com|${DATABRICKS_HOST}|g' \
  -e 's|b868e84cedeb4262|${WAREHOUSE_ID}|g' \
  -e 's|serverless_stable_3n0ihb_catalog|${UC_CATALOG}|g' \
  -e 's|ep-summer-scene-d2ew95fl\.database\.us-east-1\.cloud\.databricks\.com|${LAKEBASE_HOST}|g' \
  -e 's|projects/airport-digital-twin/branches/production/endpoints/primary|${LAKEBASE_ENDPOINT}|g' \
  -e 's|01f12612fa6314ae943d0526f5ae3a00|${GENIE_SPACE_ID}|g' \
  "$REPO_ROOT/app.yaml" > "$BACKUP_DIR/config/app.yaml.template"

# Create databricks.yml.template
sed \
  -e 's|FEVM_SERVERLESS_STABLE|${WORKSPACE_PROFILE}|g' \
  -e 's|serverless_stable_3n0ihb_catalog|${UC_CATALOG}|g' \
  "$REPO_ROOT/databricks.yml" > "$BACKUP_DIR/config/databricks.yml.template"

# Write a manifest
cat > "$BACKUP_DIR/MANIFEST.md" << 'MANIFEST'
# Airport Digital Twin — Backup Manifest

## Contents

| Directory | Description |
|-----------|-------------|
| `repo/` | Full source code snapshot (git working tree) |
| `uc_volumes/models/aircraft/` | 3D GLB model files (served via UC Volumes at runtime) |
| `lakebase/` | PostgreSQL schema DDL + setup script |
| `uc_tables/` | Unity Catalog table DDL + DLT pipeline config |
| `config/` | Workspace-portable templates (app.yaml, databricks.yml) |

## Restore

Run `scripts/bootstrap.sh` from the `repo/` directory:

```bash
cd repo
./scripts/bootstrap.sh \
  --profile TARGET_PROFILE \
  --catalog my_catalog \
  --schema airport_digital_twin \
  --warehouse-id abc123 \
  --backup-dir ..
```

See `scripts/bootstrap.sh --help` for all options.
MANIFEST

echo "  Created app.yaml.template, databricks.yml.template, MANIFEST.md"

# --- Package -----------------------------------------------------------------
echo ""
echo "Packaging tarball..."
cd "$(dirname "$BACKUP_DIR")"
tar -czf "$OUTPUT" "$(basename "$BACKUP_DIR")"
rm -rf "$BACKUP_DIR"

SIZE=$(du -sh "$OUTPUT" | cut -f1)
echo ""
echo "=== Backup complete ==="
echo "File: $OUTPUT"
echo "Size: $SIZE"
echo ""
echo "To restore to a new workspace, extract and run:"
echo "  tar xzf $(basename "$OUTPUT")"
echo "  cd $(basename "$BACKUP_DIR")/repo"
echo "  ./scripts/bootstrap.sh --profile TARGET_PROFILE --backup-dir .."

---
status: complete
area: deployment
related:
  - .planning/backlog/lakebase-delta-sync.md
  - scripts/lakebase_schema.sql
  - scripts/grant_sp_permissions.sh
  - deploy.sh
---

# Plan: Automate Lakebase provisioning in deploy.sh

## Context

Lakebase Autoscaling setup is currently manual — you have to create the project, run schema SQL, and grant permissions by hand. The goal is to fully automate this as part of deploy.sh, handling both first-time setup and upgrades without overwriting data.

The existing `scripts/lakebase_schema.sql` already uses `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, and `ALTER TABLE ADD COLUMN IF NOT EXISTS` — so it's inherently idempotent and safe for upgrades. The SP grants in `scripts/grant_sp_permissions.sh` already handle Lakebase role creation and SQL grants (step 6).

What's missing: a script that creates the Lakebase project+branch if they don't exist, runs the schema migration, and integrates into the deploy flow.

## Changes

### 1. New script: `scripts/setup_lakebase_autoscaling.py`

Replaces the manual steps. Called from deploy.sh. Idempotent — safe to run on every deploy.

**Args:** `--profile`, `--project-id`, `--branch` (default: `production`), `--schema-sql` (default: `scripts/lakebase_schema.sql`)
**Output:** prints endpoint host on last line (captured by deploy.sh)

**Steps:**
1. Check if project exists (`databricks postgres list-projects` → filter by name) — create if missing via `databricks postgres create-project`
2. Check if branch exists — production branch is auto-created with project. If `--branch` is not production, check and create it.
3. Wait for endpoint ACTIVE — poll `databricks postgres list-endpoints` every 5s until `current_state: ACTIVE` (timeout 120s)
4. Get endpoint host from endpoint details
5. Generate OAuth credential (`databricks postgres generate-database-credential`)
6. Run schema SQL — execute the contents of `--schema-sql` via psycopg2. All statements use `IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`, so this is safe on upgrades — no data is overwritten, no tables dropped.
7. Print endpoint host on stdout for deploy.sh to capture

**Key design:** the schema SQL file (`lakebase_schema.sql`) IS the migration. Adding a new table or column means editing this file with `CREATE TABLE IF NOT EXISTS` or `ALTER TABLE ADD COLUMN IF NOT EXISTS`. This is the "upgrade smartly" approach — additive-only, never destructive.

### 2. Update `deploy.sh` — add Step 4b: Lakebase provisioning

Insert after step 4 (UC tables), before step 5 (app restart):

```bash
# ── Step 4b: Lakebase Autoscaling setup ─────────────────────────────
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
```

Add new env vars to deploy.sh defaults:
```bash
LAKEBASE_PROJECT="${LAKEBASE_PROJECT:-airport-digital-twin}"
LAKEBASE_BRANCH="${LAKEBASE_BRANCH:-production}"
```

For free target auto-detection, deploy.sh can read from the target's variables in databricks.yml or use per-target env overrides.

### 3. Commit Lakebase config for free target (already done)

`databricks.yml` free target already has:
```yaml
lakebase_branch: "production"
lakebase_host: "ep-patient-fire-d38b447d.database.eu-west-1.cloud.databricks.com"
```

### 4. Upgrade safety (by design)

The schema SQL is inherently safe for upgrades:
- `CREATE TABLE IF NOT EXISTS` — won't drop/recreate existing tables
- `CREATE INDEX IF NOT EXISTS` — won't touch existing indexes
- `CREATE OR REPLACE FUNCTION` — updates trigger functions safely
- `DROP TRIGGER IF EXISTS` + `CREATE TRIGGER` — recreates triggers idempotently
- `ALTER TABLE ADD COLUMN IF NOT EXISTS` — adds new columns without touching existing data
- Migration block at bottom handles adding `airport_icao` to existing tables

No data is ever deleted or overwritten. New columns get defaults. New tables start empty until populated by the app.

## Files to modify

| File | Action |
|------|--------|
| `scripts/setup_lakebase_autoscaling.py` | Create — idempotent provisioning script |
| `deploy.sh` | Add Step 4b: Lakebase provisioning + env vars |
| `databricks.yml` | Already updated (free target has lakebase vars) |

## Verification

1. Run on fresh workspace: script creates project, waits for endpoint, runs schema → 7 tables created
2. Run again: no-op (project exists, schema unchanged)
3. Add a new table to `lakebase_schema.sql` and re-run: only the new table is created
4. App connects: `LAKEBASE_HOST` env var is set, `is_available()` returns True
5. Existing data preserved: any existing rows in tables remain unchanged

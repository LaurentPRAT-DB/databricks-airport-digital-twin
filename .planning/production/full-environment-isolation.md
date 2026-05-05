---
title: "Full Environment Isolation: Dev/Prod with Separate Lakebase Instances"
status: backlog
area: deployment, infrastructure
priority: high
related:
  - ci-cd-github-actions.md
  - per-target-lakebase-config.md
---

# Full Environment Isolation: Dev/Prod with Separate Lakebase Instances

## Context

The CD pipeline deploys to a single workspace (fevm-serverless-stable) with two DABs targets: `dev` and `prod`. Currently, both targets share the same Lakebase project/branch/endpoint, meaning dev writes pollute prod data. The user explicitly requires: "two separate deployments dev and prod with suffix _dev/_prod to segregate them, and 2 instances of Lakebase."

**Goal:** Complete environment isolation — dev and prod must never share mutable state.

**Current state (what's shared):**
- Lakebase: same project `airport-digital-twin`, same branch `production`, same endpoint `primary`
- UC Schema: already separated (`airport_digital_twin` vs `airport_digital_twin_prod`)
- App name: already separated (`airport-digital-twin-dev` vs `airport-digital-twin-prod`)

## Isolation Matrix

| Resource | Dev | Prod |
|----------|-----|------|
| App name | `airport-digital-twin-dev` | `airport-digital-twin-prod` |
| UC Schema | `airport_digital_twin` | `airport_digital_twin_prod` |
| Lakebase branch | `dev` | `production` |
| Lakebase endpoint | `projects/airport-digital-twin/branches/dev/endpoints/primary` | `projects/airport-digital-twin/branches/production/endpoints/primary` |
| App URL env var | dev app URL | prod app URL |
| Bundle workspace root | `.bundle/.../dev/files` | `.bundle/.../prod/files` |

**Lakebase approach:** Use Lakebase branching (same project, different branches). Each branch has its own endpoint, its own data, and complete schema isolation — functionally equivalent to two separate projects.

## Files to Modify

| File | Change |
|------|--------|
| `databricks.yml` | Add `lakebase_branch` variable per target |
| `scripts/ci-deploy.sh` | Resolve `lakebase_branch` from bundle vars, patch `LAKEBASE_ENDPOINT_NAME` + `DATABRICKS_APP_URL` + `BUNDLE_WORKSPACE_ROOT`; create Lakebase branch if `--seed` |
| `databricks/notebooks/sync_from_lakebase.py` | Read endpoint from job param instead of hardcode |
| `resources/lakebase_sync_job.yml` | Pass `lakebase_endpoint` and `target_schema` as notebook params |
| `resources/lakebase.yml` | Document both branches |

`app.yaml` stays as-is — it keeps dev defaults for local development; `ci-deploy.sh` patches values at deploy time via `patch_env_var`.

## Implementation Steps

### 1. `databricks.yml` — Add `lakebase_branch` variable

Add to variables block:
```yaml
lakebase_branch:
  description: "Lakebase branch name for environment isolation"
  default: "dev"
```

Add to `targets.dev.variables`:
```yaml
lakebase_branch: "dev"
```

Add to `targets.prod.variables`:
```yaml
lakebase_branch: "production"
```

### 2. `scripts/ci-deploy.sh` — Resolve and patch Lakebase per target

After existing bundle variable resolution block (line ~60), add:

```bash
# Resolve Lakebase branch from bundle variables
LAKEBASE_BRANCH="${LAKEBASE_BRANCH:-}"
if [[ -z "$LAKEBASE_BRANCH" ]]; then
  LAKEBASE_BRANCH=$(databricks bundle validate --target "$TARGET" --output json 2>/dev/null \
    | python3 -c "import sys,json; b=json.load(sys.stdin); print(b.get('variables',{}).get('lakebase_branch',{}).get('value','dev'))" 2>/dev/null) || true
fi
LAKEBASE_BRANCH="${LAKEBASE_BRANCH:-$TARGET}"
LAKEBASE_ENDPOINT="projects/airport-digital-twin/branches/$LAKEBASE_BRANCH/endpoints/primary"
```

In Step 0 patching (after existing `patch_env_var` calls), add:

```bash
patch_env_var "LAKEBASE_ENDPOINT_NAME" "$LAKEBASE_ENDPOINT"
patch_env_var "DATABRICKS_APP_URL" "https://$APP_NAME-7474645572615955.aws.databricksapps.com"
patch_env_var "BUNDLE_WORKSPACE_ROOT" "/Workspace/Users/laurent.prat@databricks.com/.bundle/airport-digital-twin/$TARGET/files"
PATCHED=1
```

In `--seed` block (existing Step 3b, after Lakebase schema section), replace the hardcoded endpoint with `$LAKEBASE_ENDPOINT`:

```bash
LB_EP="$LAKEBASE_ENDPOINT"
```

Add Step 1c (after Step 1b bundle deploy, inside `--seed` only):

```bash
if $SEED; then
  echo "Step 1c: Ensure Lakebase branch '$LAKEBASE_BRANCH' exists"
  if databricks api get "/api/2.0/postgres/projects/airport-digital-twin/branches/$LAKEBASE_BRANCH" 2>/dev/null | grep -q "name"; then
    ok "Lakebase branch '$LAKEBASE_BRANCH' exists"
  else
    databricks api post "/api/2.0/postgres/projects/airport-digital-twin/branches" \
      --json "$(jq -n --arg n "$LAKEBASE_BRANCH" --arg p "production" '{name: $n, parent_branch: $p}')" 2>/dev/null \
      && ok "Created Lakebase branch '$LAKEBASE_BRANCH'" \
      || info "Could not create branch (may already exist or need manual setup)"
  fi
fi
```

### 3. `resources/lakebase_sync_job.yml` — Parameterize notebook

Change the notebook task to pass env-specific parameters:

```yaml
tasks:
  - task_key: sync_lakebase_to_delta
    notebook_task:
      notebook_path: ../databricks/notebooks/sync_from_lakebase.py
      base_parameters:
        lakebase_endpoint: "projects/airport-digital-twin/branches/${var.lakebase_branch}/endpoints/primary"
        target_catalog: "${var.catalog}"
        target_schema: "${var.schema}"
    environment_key: sync_env
```

### 4. `databricks/notebooks/sync_from_lakebase.py` — Read params

Replace hardcoded constants at top:

```python
# Read from job parameters (set by DABs), with fallback for interactive use
try:
    LAKEBASE_ENDPOINT_NAME = dbutils.widgets.get("lakebase_endpoint")
except:
    LAKEBASE_ENDPOINT_NAME = "projects/airport-digital-twin/branches/production/endpoints/primary"

try:
    TARGET_CATALOG = dbutils.widgets.get("target_catalog")
    TARGET_SCHEMA = dbutils.widgets.get("target_schema")
except:
    TARGET_CATALOG = "serverless_stable_3n0ihb_catalog"
    TARGET_SCHEMA = "airport_digital_twin"
```

### 5. `resources/lakebase.yml` — Update documentation

Add to the comment block:

```yaml
# Branches:
#   - production: Production data (used by airport-digital-twin-prod app)
#   - dev: Development data (used by airport-digital-twin-dev app)
#
# Each branch has its own endpoint: projects/airport-digital-twin/branches/<branch>/endpoints/primary
# Create a new branch: databricks postgres create-branch --project airport-digital-twin --name <branch> --parent production
```

## One-Time Setup (Manual or via `--seed`)

1. Create the `dev` Lakebase branch (if it doesn't already exist):
```bash
databricks api post "/api/2.0/postgres/projects/airport-digital-twin/branches" \
  --profile FEVM_SERVERLESS_STABLE \
  --json '{"name": "dev", "parent_branch": "production"}'
```

2. Apply schema to dev branch:
```bash
scripts/ci-deploy.sh --target dev --seed
```

3. Verify isolation:
```bash
# Dev app should connect to dev branch
databricks apps get airport-digital-twin-dev --output json | grep LAKEBASE_ENDPOINT
# Prod app should connect to production branch
databricks apps get airport-digital-twin-prod --output json | grep LAKEBASE_ENDPOINT
```

## Verification

1. `databricks bundle validate --target dev --output json` → `lakebase_branch: "dev"`
2. `databricks bundle validate --target prod --output json` → `lakebase_branch: "production"`
3. Deploy dev: app uses `branches/dev/endpoints/primary` (check in app logs)
4. Deploy prod: app uses `branches/production/endpoints/primary`
5. Write flight data via dev app → confirm it does NOT appear in prod Lakebase
6. Run `scripts/verify-prod.sh` against both app URLs independently

---
title: "Per-Target Lakebase Configuration via CI Deploy Script"
status: backlog
area: deployment, infrastructure
priority: medium
related:
  - ci-cd-github-actions.md
---

# Per-Target Lakebase Configuration via CI Deploy Script

## Context

The CD pipeline deploys to a `prod` target that may share the same Databricks workspace as `dev`. The Lakebase connection (PostgreSQL host, endpoint name) is currently hardcoded in `app.yaml`. Since `app.yaml` doesn't support DABs variable interpolation, both targets would connect to the same Lakebase instance — causing data conflicts if both apps run simultaneously.

**Goal:** Make Lakebase connection configurable per target so prod and dev can use separate Lakebase instances (or branches).

**Approach:** `ci-deploy.sh` patches `app.yaml` env vars in-place before `databricks bundle deploy`. Since CI runs in an ephemeral checkout, modifying the file is safe — no git state to worry about.

## Implementation

### Files to Modify

| File | Change |
|------|--------|
| `scripts/ci-deploy.sh` | Add Step 1.5: patch `app.yaml` with target-specific env vars from env |
| `.github/workflows/cd.yml` | Pass new optional secrets: `LAKEBASE_HOST`, `LAKEBASE_ENDPOINT_NAME` |
| `databricks.yml` | No change needed (already has per-target variables) |
| `app.yaml` | No change — stays as dev default |

### 1. `scripts/ci-deploy.sh` — Add env var patching step

After parsing args but before `databricks bundle deploy`, add a step that uses `sed` to replace Lakebase values in `app.yaml` when corresponding env vars are set:

```bash
# ── Step 0: Patch app.yaml with target-specific config ───────────────
echo "Step 0: Patch app.yaml for target '$TARGET'"

patch_env_var() {
  local varname="$1" newval="$2"
  # Match the line after "- name: VARNAME" and replace the value
  sed -i "/$varname/{n;s|value: .*|value: \"$newval\"|}" app.yaml
}

# Patch Lakebase config if env vars provided
[[ -n "${LAKEBASE_HOST:-}" ]] && patch_env_var "LAKEBASE_HOST" "$LAKEBASE_HOST"
[[ -n "${LAKEBASE_ENDPOINT_NAME:-}" ]] && patch_env_var "LAKEBASE_ENDPOINT_NAME" "$LAKEBASE_ENDPOINT_NAME"
# Also patch Databricks SQL config to match target
[[ -n "${DATABRICKS_HOST:-}" ]] && patch_env_var "DATABRICKS_HOST" "${DATABRICKS_HOST#https://}"
[[ -n "${UC_CATALOG:-}" ]] && patch_env_var "DATABRICKS_CATALOG" "$UC_CATALOG"
[[ -n "${UC_SCHEMA:-}" ]] && patch_env_var "DATABRICKS_SCHEMA" "$UC_SCHEMA"
ok "app.yaml patched for target"
```

**Decision:** Use `sed` — simpler, no extra dependency. The `app.yaml` format is predictable (each env var is `- name: X` followed by `  value: "Y"`).

### 2. `.github/workflows/cd.yml` — Add optional secrets to env

```yaml
env:
  LAKEBASE_HOST: ${{ secrets.LAKEBASE_HOST }}
  LAKEBASE_ENDPOINT_NAME: ${{ secrets.LAKEBASE_ENDPOINT_NAME }}
  DATABRICKS_WAREHOUSE_ID: ${{ secrets.DATABRICKS_WAREHOUSE_ID }}
  GENIE_SPACE_ID: ${{ secrets.GENIE_SPACE_ID }}
  SECRET_SCOPE: ${{ secrets.SECRET_SCOPE }}
```

All optional — when blank, `app.yaml` stays unchanged (keeps dev defaults).

### 3. Variables summary

| Secret | Required? | Default (if blank) |
|--------|-----------|-------------------|
| `DATABRICKS_HOST` | Yes | — |
| `DATABRICKS_CLIENT_ID` | Yes | — |
| `DATABRICKS_CLIENT_SECRET` | Yes | — |
| `DATABRICKS_WAREHOUSE_ID` | No | serverless (omitted from SQL API) |
| `LAKEBASE_HOST` | No | `ep-summer-scene-d2ew95fl.database.us-east-1.cloud.databricks.com` (dev) |
| `LAKEBASE_ENDPOINT_NAME` | No | `projects/airport-digital-twin/branches/production/endpoints/primary` (dev) |
| `GENIE_SPACE_ID` | No | blank |
| `SECRET_SCOPE` | No | `airport-digital-twin` |

## Verification

1. Deploy with no Lakebase secrets → app uses dev Lakebase (current `app.yaml` values unchanged)
2. Deploy with `LAKEBASE_HOST=new-host.databricks.com` → patched in `app.yaml` before bundle deploy
3. Check deployed app's env: `databricks apps get airport-digital-twin-prod` → verify `source_code_path`, then `databricks workspace cat <path>/app.yaml` to confirm patched values
4. Both dev and prod apps can run simultaneously on the same workspace without data conflicts

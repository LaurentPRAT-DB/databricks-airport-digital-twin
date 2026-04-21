# Smart Deploy

Fast-path deployment to Databricks. Detects what changed and picks the minimal deployment strategy.

## Trigger

User says "deploy", "push", "ship it", or `/deploy`

## Decision Tree

Run `git diff --name-only HEAD` (unstaged) and `git diff --name-only --cached` (staged) to classify changes.

### Classification Rules

| Pattern | Category |
|---|---|
| `app/frontend/src/**`, `app/frontend/dist/**` | `frontend` |
| `app/backend/**`, `src/**` | `backend` |
| `app.yaml` | `app_config` |
| `resources/*.yml`, `databricks.yml` | `bundle_config` |
| `tests/**`, `scripts/**`, `*.md`, `.claude/**` | `non_deployed` (skip deploy) |
| `data/**`, `configs/**` | `data` |

### Deployment Paths

**Path A: No deploy needed** (`non_deployed` only)
- Changes are tests, docs, scripts, or tooling
- Say: "No deployment needed - changes are local-only (tests/docs/scripts)."
- Offer to commit only

**Path B: Frontend hot deploy** (`frontend` only, no `backend`/`app_config`)
1. `cd app/frontend && npm run build`
2. Commit with built dist: `git add <changed files> app/frontend/dist/ -f`
3. `databricks bundle deploy --target dev`
4. Done. No stop/start. App picks up new static files on next deployment snapshot (~2-3 min).
5. Say: "Frontend deployed via hot path. New assets will be live in ~2-3 min. Hard-refresh browser (Cmd+Shift+R) to bypass cache."

**Path C: Backend deploy** (`backend` with or without `frontend`, no `app_config`)
1. If frontend changed: `cd app/frontend && npm run build`
2. Commit changes
3. `databricks bundle deploy --target dev`
4. Done. The deployment creates a new snapshot and restarts the uvicorn process (~3-5 min). No stop/start needed.
5. Say: "Backend deployed. New code will be live in ~3-5 min after process restart."

**Path D: Full restart required** (`app_config` changed — app.yaml env vars)
1. If frontend changed: `cd app/frontend && npm run build`
2. Commit changes
3. `databricks bundle deploy --target dev`
4. `databricks apps stop airport-digital-twin-dev --profile FEVM_SERVERLESS_STABLE`
5. `databricks apps start airport-digital-twin-dev --profile FEVM_SERVERLESS_STABLE`
6. Say: "Full restart triggered (app.yaml changed). This takes ~15-18 min for compute cold boot."

**Path E: Bundle config only** (`bundle_config` — resources/*.yml, databricks.yml)
1. `databricks bundle deploy --target dev`
2. Done. No app restart needed — this only updates jobs, pipelines, permissions.
3. Say: "Bundle resources updated. No app restart needed."

### Pre-deploy Checks

Before deploying, always:
1. Run relevant tests based on what changed:
   - Frontend: `cd app/frontend && npm test -- --run`
   - Backend: `uv run pytest tests/ -x -q` (quick fail-fast)
   - Both: run both
   - Skip tests for docs/config-only changes
2. Check for uncommitted changes and prompt for commit message
3. Verify current branch — if not `main`, ask whether to merge first

### Post-deploy Verification

- For Path B/C: poll `curl -s https://airport-digital-twin-dev-7474645572615955.aws.databricksapps.com/api/health` until 200
- For Path D: monitor deployment state via `databricks apps list-deployments`
- Report when app is live

### Key Rules

- **Never** use `databricks apps deploy` directly — always `databricks bundle deploy`
- **Never** stop/start unless app.yaml changed or app is hung/crashing
- Default target is `dev` when not specified
- Always force-add `app/frontend/dist/` since it's in `.gitignore`
- Profile is `FEVM_SERVERLESS_STABLE`
- App URL: `https://airport-digital-twin-dev-7474645572615955.aws.databricksapps.com`

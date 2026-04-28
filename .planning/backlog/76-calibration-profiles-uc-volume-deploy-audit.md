---
status: backlog
area: infrastructure
related: []
---

# Plan: Move calibration profiles to UC Volume + deployment audit

## Context

Databricks Apps deployments take 30+ minutes stuck at "Downloading source code" because the bundle contains 1,183 calibration profile JSON files (5.8 MB total). Each file is downloaded individually by the platform. Moving these to a UC Volume — same pattern as the demo simulation file — will dramatically speed up deploys.

The user also wants a full dependency audit to ensure a fresh `databricks bundle deploy` works without manual setup.

---

## Part 1: Calibration Profiles → UC Volume

### Current architecture

- `src/calibration/profile.py` — `AirportProfileLoader.get_profile()` is the central method
- Fallback chain on Databricks: cache → UC Delta table (`airport_profiles`) → local JSON → `known_profiles` → OpenFlights → hardcoded
- Fallback chain locally: cache → local JSON → `known_profiles` → OpenFlights → hardcoded
- Local files: `data/calibration/profiles/{ICAO}.json` (1,183 files, 5.8 MB)
- UC Delta table: `{catalog}.{schema}.airport_profiles` — already populated via `profile_sync` job
- Bundle sync: `data/calibration/profiles/**` is in `databricks.yml` sync includes

### Approach

Add a UC Volume fallback between the UC Delta table and local JSON, following the demo pattern:

1. Create `calibration_profiles` Volume via DABs (`resources/calibration_profiles_volume.yml`)
2. Upload all 1,183 profiles to the Volume (one-time, via `databricks fs cp`)
3. Add Volume fallback to `AirportProfileLoader` — between UC table and local JSON
4. Auto-seed: when loading from local JSON on Databricks, upload to Volume for next time
5. Remove `data/calibration/profiles/**` from bundle sync in `databricks.yml`

### Files to modify

| File | Change |
|------|--------|
| `resources/calibration_profiles_volume.yml` | NEW — Volume resource |
| `src/calibration/profile.py` | Add `_load_from_volume()` + `_seed_volume()` to `AirportProfileLoader` |
| `databricks.yml` | Remove `data/calibration/profiles/**` from sync includes |

### Loading flow after change (on Databricks)

1. In-memory cache → instant
2. UC Delta table (`airport_profiles`) → SQL query (~200ms) — already works, already populated
3. UC Volume (`/Volumes/.../calibration_profiles/{ICAO}.json`) → SDK download (~100ms) — NEW
4. Local JSON (`data/calibration/profiles/`) → disk read — only for local dev now
5. `known_profiles.py` / OpenFlights / hardcoded fallback

### Key detail: UC table already populated

The `profile_sync` job has already been run — the `airport_profiles` Delta table has all 1,183 profiles. So on Databricks, the app reads from the UC table (step 2) and never reaches the local JSON fallback. The Volume serves as a secondary fallback if the UC table is unavailable, and for use cases that need raw JSON files (notebooks, scripts).

---

## Part 2: Deployment Dependency Audit

### Resources created by DABs (all automated)

| Resource | YAML | Purpose |
|----------|------|---------|
| App | `app.yml` | `airport-digital-twin-${bundle.target}` |
| DLT Pipeline | `pipeline.yml` | Bronze/silver/gold flight + baggage |
| Demo Volume | `demo_volume.yml` | Pre-generated demo simulations |
| OpenSky Volume | `opensky_volume.yml` | Raw ADS-B data |
| Calibration Volume | `calibration_profiles_volume.yml` | NEW — profile JSONs |
| 14 Jobs | various `*_job.yml` | Tests, sync, training, batch sims |
| Serving Endpoint | `inpainting_serving.yml` | Aircraft inpainting ML model |

### App env vars (`app.yaml`) — status check

| Env Var | Source | Fresh Install Status |
|---------|--------|---------------------|
| `DATABRICKS_HOST` | Hardcoded | Works |
| `DATABRICKS_HTTP_PATH` | Hardcoded warehouse | Works (if warehouse exists) |
| `DATABRICKS_CATALOG/SCHEMA` | Hardcoded | Works |
| `DATABRICKS_WAREHOUSE_ID` | Hardcoded | Works |
| `DATABRICKS_USE_OAUTH` | Hardcoded | Works (DABs App OAuth) |
| `LAKEBASE_*` | Hardcoded endpoint | Requires Lakebase project to exist |
| `ASSISTANT_MODEL_ENDPOINT` | Hardcoded | Works (Foundation Model) |
| `INPAINTING_ENDPOINT_NAME` | Hardcoded | Requires model registration job |
| `GENIE_SPACE_ID` | Hardcoded | Requires Genie space to exist |
| `DASHBOARD_ID` | Hardcoded | Requires dashboard to exist |
| `DEMO_MODE=true` | Hardcoded | Works |
| OpenSky secrets | Databricks secret scope | Optional — falls back to anonymous |

### Fresh install graceful degradation

The app is designed to degrade gracefully — all external dependencies have fallbacks:

- **Lakebase unavailable:** uses synthetic data only (`DEMO_MODE`)
- **UC tables empty:** falls back to local files / hardcoded
- **Inpainting endpoint missing:** returns original tiles
- **Genie space missing:** assistant routes to MCP only
- **OpenSky secrets missing:** anonymous access (rate-limited)
- **Weather API down:** returns empty weather

### Required pre-deploy steps (not automated by DABs)

1. `npm run build` in `app/frontend/` — `dist/` must exist before deploy
2. SQL Warehouse must exist (hardcoded ID `b868e84cedeb4262`)
3. Lakebase project must exist (manual creation via `databricks postgres`)

### One-time post-deploy steps (optional, for full functionality)

1. Run `profile_sync` job — populates `airport_profiles` UC table
2. Run `inpainting_registration` job — registers ML model for serving
3. Create Genie space — manual, requires AI/BI setup
4. Create dashboard — manual, requires SQL dashboard setup
5. Create secret scope — `databricks secrets create-scope airport-digital-twin`

---

## Implementation Steps

1. Create `resources/calibration_profiles_volume.yml`
2. Add `_load_from_volume()` and `_seed_volume()` to `AirportProfileLoader` in `src/calibration/profile.py`
3. Remove `data/calibration/profiles/**` from `databricks.yml` sync includes
4. Upload profiles to Volume: `databricks fs cp -r data/calibration/profiles/ dbfs:/Volumes/.../calibration_profiles/`
5. Deploy and verify

## Verification

1. `uv run pytest tests/ -k "calibration or profile" -v` — ensure tests pass
2. `databricks bundle deploy --target dev` — verify faster deploy (no profile files in source)
3. Check `/api/version` — app starts and loads profiles from UC table
4. Verify `AirportProfileLoader` fallback: UC table → Volume → local → hardcoded

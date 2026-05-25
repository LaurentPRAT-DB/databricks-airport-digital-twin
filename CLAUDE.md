# CLAUDE.md — Airport Digital Twin

## Project Overview

Interactive airport digital twin demo on Databricks. APX stack: FastAPI backend + React frontend, deployed as a Databricks App. Real-time synthetic flight data, 2D/3D visualization, ML predictions, DLT pipelines.

---

## Python

- Use `uv` for all Python operations (install, run, lock). Never use `pip` directly.
- Python 3.10+. Dependencies in `pyproject.toml`.
- Pydantic v2 for data models. FastAPI for the API layer.
- `asyncio_mode = "auto"` in pytest — async tests don't need `@pytest.mark.asyncio`.

## Frontend

- React + TypeScript + Vite. Located in `app/frontend/`.
- Tailwind CSS for styling. Leaflet for 2D maps, Three.js/react-three-fiber for 3D.
- Test runner: Vitest (`cd app/frontend && npm test -- --run`).
- Build: `cd app/frontend && npm run build` (outputs to `app/frontend/dist/`).

## API (FastAPI Backend)

- Entry point: `app/backend/main.py` (uvicorn serves `app.backend.main:app`).
- Backend source logic lives in `src/` (simulation, ML, calibration, formats).
- WebSocket at `/ws` for real-time flight position updates.
- All airport geometry comes from OSM via Overpass API — see "Airport Data" rule below.

## Testing

### Local tests (run frequently)

```bash
# Python (~3089 tests, 69% code coverage)
uv run pytest tests/ -v

# Frontend (~810 tests, 34 test files)
cd app/frontend && npm test -- --run
```

### Databricks workspace tests (on-demand, after deploy)

```bash
databricks bundle run unit_test --target dev          # Full pytest on serverless
databricks bundle run e2e_smoke_test --target dev     # 11 live API endpoints
databricks bundle run baggage_pipeline_integration_test --target dev  # DLT pipeline
```

- Workspace test notebooks are in `databricks/notebooks/test_*.py`.
- Job configs are in `resources/*_job.yml`.
- Integration tests create temp schema `_test_baggage_{timestamp}` and drop with CASCADE on teardown.

### Known test issues

- 3 pre-existing approach quality failures: `test_approach_no_large_altitude_jumps`, `test_approach_no_velocity_jitter`, `test_approach_mean_alt_change_smooth` (need altitude/velocity smoothing — tracked in plan).
- KORD tests deselected (OSM data incomplete for O'Hare).

## Deployment

**Always use DABs. Never use `databricks apps deploy` directly.**

```bash
# Full automated deploy (build + DABs + tables + app restart + SP grants)
./deploy.sh                    # default target: dev
./deploy.sh --target prod      # specify target
SKIP_BUILD=1 ./deploy.sh       # skip frontend build
```

`deploy.sh` runs these steps in order:
1. Build frontend (`npm run build`)
2. `databricks bundle deploy` — creates app, volumes, jobs, pipelines, endpoints
3. Create UC schema + tables via SQL API (from `airport_tables.py`)
4. Stop/start app, wait for RUNNING
5. `scripts/grant_sp_permissions.sh` — UC grants, workspace ACLs, secrets, Genie

**DABs manages:** app, 5 volumes (calibration_profiles, demo_simulations, opensky_raw, simulation_data, static_assets), jobs, pipelines, serving endpoints, SQL warehouse permissions.
**Post-deploy script manages:** workspace object ACLs, UC GRANT statements, secret scope ACLs, Genie space access.

- Bundle config: `databricks.yml` (profile: `FEVM_SERVERLESS_STABLE`).
- App config: `app.yaml` (uvicorn, env vars for Databricks SQL + Lakebase).
- Resource configs: `resources/*.yml` (app, jobs, pipelines, volumes, Lakebase).
- Target: `dev` (default). Catalog: `serverless_stable_3n0ihb_catalog`, schema: `airport_digital_twin`.

## Databricks App (APX)

- FastAPI backend serves both API and static frontend from `app/frontend/dist/`.
- Runs on Databricks Apps platform with OAuth for Databricks SQL and Lakebase.
- Lakebase Autoscaling (PostgreSQL) for low-latency flight status serving.
- Unity Catalog Delta tables for historical data + DLT Gold layer.
- Demo mode: `DEMO_MODE=true`, synthetic data via `src/simulation/`.

## Data Architecture

- **Unity Catalog:** `serverless_stable_3n0ihb_catalog.airport_digital_twin` — `flight_status_gold`, `flight_positions_history`.
- **UC Volumes:** Managed volumes for file-based assets — `calibration_profiles` (1,183 airport JSON files), `demo_simulations` (pre-generated demo data). Declared in `resources/calibration_profiles_volume.yml`.
- **Lakebase:** PostgreSQL endpoint for <10ms reads — `flight_status` table.
- **OSM data:** Fetched per airport from Overpass API, cached in `airport_config_service` singleton.
- **DLT pipeline:** Bronze/silver/gold layers for flights + baggage (`databricks/dlt_pipeline_config.json`).
- **Calibration profiles:** Loaded from UC Volume on Databricks (fallback: local `data/calibration/profiles/`). Loading chain: UC table → UC Volume → local JSON → known profiles → OpenFlights → hardcoded.

## Airport Data — No Hardcoding

All airport geometry (runways, gates, taxiways, aprons, terminal buildings) must be derived from OSM data via Overpass API. Never hardcode per-airport dictionaries.

When adding airport-specific behavior:
- Derive runway names/headings from OSM `ref` tags and geometry.
- Compute base AAR/ADR from runway count (formula, not lookup).
- Get gate count from OSM gate/parking_position nodes.
- Use airport characteristics (runway count, region) for traffic profiles — not IATA/ICAO codes.

Exception: `src/calibration/known_profiles.py` contains hand-researched statistics (passenger counts, operation counts) — this is calibration data, not geometry.

## ML Models

- Per-airport model registry: `src/ml/registry.py` (`AirportModelRegistry`).
- Models: delay prediction, gate assignment, congestion — `src/ml/{delay,gate,congestion}_model.py`.
- Training: `src/ml/training.py`.
- CatBoost + scikit-learn.

## Local Development

```bash
./dev.sh  # Starts backend + frontend, open http://localhost:3000
```

## Key Directories

```
app/backend/       # FastAPI app (main.py, routes, middleware)
app/frontend/      # React app (src/, tests/, dist/)
src/               # Core logic (simulation, ml, calibration, formats)
tests/             # Python test suite
databricks/        # Notebooks (DLT, test runners)
resources/         # DABs job/pipeline/app YAML configs
data/              # Local calibration profiles (dev fallback; production uses UC Volume)
scripts/           # CLI tools (build profiles, batch sims)
configs/           # Simulation scenario configs
```

## Project Knowledge

Before implementing a fix or feature, search `.planning/` for existing analysis — most problems have prior context documented.

```bash
grep -rl "<keyword>" .planning/
```

All planning files have YAML frontmatter with `status`, `area`, and `related` fields for targeted lookups:

```bash
grep -rl "area: simulation" .planning/    # all simulation-related docs
grep -rl "area: ml" .planning/            # all ML-related docs
grep -rl "status: active" .planning/      # currently in-progress work
```

### Planning directories

| Directory | Files | Contents |
|-----------|-------|---------|
| `.planning/research/` | 6 | Architecture decisions, tech stack rationale, domain pitfalls |
| `.planning/milestones/` | 29 | Original 5-phase build plans with validation reports |
| `.planning/features/` | 30 | Feature implementation plans (numbered 06-37) |
| `.planning/fixes/` | 27 | Bug investigations with root cause analysis |
| `.planning/backlog/` | 59 | Proposed but not yet planned features |
| `.planning/test/` | 8 | Test plans and validation strategies |
| `.planning/audits/` | 30 | Code review and UX audit reports |
| `.planning/reference/` | 4 | ML model registry, calibration status, airport onboarding |
| `.planning/validation-gaps/` | 3 | Known gaps in validation coverage |

### Technical documentation

| File | When to consult |
|------|----------------|
| `docs/SPECIFICATION.md` | Full as-built technical spec (20 sections) |
| `docs/DATA_DICTIONARY.md` | Table schemas, field definitions |
| `docs/ML_MODELS.md` | ML model documentation |
| `docs/PIPELINE.md` | End-to-end data pipeline |
| `docs/SECURITY_AUDIT.md` | Known vulnerabilities (3 high, 4 medium) |
| `docs/USER_GUIDE.md` | End-user feature guide |
| `docs/SYNTHETIC_DATA_GENERATION.md` | How synthetic flight data is generated |
| `docs/OBT_PIPELINE.md` | Off-Block Time model training pipeline |

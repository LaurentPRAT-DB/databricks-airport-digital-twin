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

- 4 known backend failures: approach speed (DEN), taxi-out median vs BTS, origin/destination generation, diversion after go-arounds.
- 1 flaky frontend timing test (`switch to 3D and back to 2D`, 750ms threshold).

## Deployment

**Always use DABs. Never use `databricks apps deploy` directly.**

```bash
# Full deploy sequence
cd app/frontend && npm run build
databricks bundle deploy --target dev
```

- Bundle config: `databricks.yml` (profile: `FEVM_SERVERLESS_STABLE`).
- App config: `app.yaml` (uvicorn, env vars for Databricks SQL + Lakebase).
- Resource configs: `resources/*.yml` (app, jobs, pipelines, Lakebase).
- Target: `dev` (default). Catalog: `serverless_stable_3n0ihb_catalog`, schema: `airport_digital_twin`.

## Databricks App (APX)

- FastAPI backend serves both API and static frontend from `app/frontend/dist/`.
- Runs on Databricks Apps platform with OAuth for Databricks SQL and Lakebase.
- Lakebase Autoscaling (PostgreSQL) for low-latency flight status serving.
- Unity Catalog Delta tables for historical data + DLT Gold layer.
- Demo mode: `DEMO_MODE=true`, synthetic data via `src/simulation/`.

## Data Architecture

- **Unity Catalog:** `serverless_stable_3n0ihb_catalog.airport_digital_twin` — `flight_status_gold`, `flight_positions_history`.
- **Lakebase:** PostgreSQL endpoint for <10ms reads — `flight_status` table.
- **OSM data:** Fetched per airport from Overpass API, cached in `airport_config_service` singleton.
- **DLT pipeline:** Bronze/silver/gold layers for flights + baggage (`databricks/dlt_pipeline_config.json`).
- **Calibration profiles:** `data/calibration/profiles/` — real-data-driven airport stats from BTS, OpenSky, OurAirports.

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
data/              # Calibration profiles, airport data
scripts/           # CLI tools (build profiles, batch sims)
configs/           # Simulation scenario configs
```

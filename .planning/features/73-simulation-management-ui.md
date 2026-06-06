---
status: done
area: frontend
related: []
---

# Simulation Management UI — Create, Load, Running

## Context

The simulation button previously only opened a file picker to load pre-generated simulation JSON files. Users couldn't create new simulations from the UI.

## What was built

Three-tab modal ("Simulation Manager") replacing the old file picker button:

1. **Create** — form to configure and launch a Databricks job:
   - Airport, arrivals/departures, duration
   - Scenario: None / Built-in (38 scenarios) / Custom (inline event builder)
   - Custom event builder: weather, runway, ground, traffic events as composable cards
   - Advanced options: seed, time_step, skip_positions
   - Submits via `POST /api/simulation/jobs` → `jobs.submit()` on Databricks

2. **Load** — existing file picker, now as a tab within the manager

3. **Running** — active/recent job monitoring:
   - Auto-refresh every 10s while jobs are active
   - Status badges, elapsed time, links to Databricks workspace
   - "Load Result" button on completed jobs

## Files

| File | Change |
|------|--------|
| `app/backend/api/simulation_jobs.py` | New — 4 endpoints (POST job, GET jobs, GET job/{id}, GET scenarios) |
| `app/backend/main.py` | Register simulation_jobs_router |
| `app/frontend/src/hooks/useSimulationJobs.ts` | New — react-query hooks for jobs + scenarios |
| `app/frontend/src/components/SimulationControls/SimulationManager.tsx` | New — three-tab modal with event builder |
| `app/frontend/src/components/SimulationControls/SimulationControls.tsx` | Wire SimulationManager, replace old button |
| `app/frontend/src/components/SimulationControls/SimulationControls.test.tsx` | Update tests for new UI |

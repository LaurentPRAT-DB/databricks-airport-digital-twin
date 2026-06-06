---
status: active
area: frontend
related: [73-simulation-management-ui.md]
---

# Simulation Drafts — Save, Edit, Reuse Configs

## Context

Users want to decouple simulation creation from execution. Currently "Create Simulation" immediately submits a Databricks job. This adds a drafts system: save configs as named YAML in UC Volume, edit/reuse them, then run when ready.

Also fixes built-in scenarios not appearing in the Create tab dropdown (path resolution bug on Databricks Apps).

## Design

- **Saved tab** in SimulationManager (between Create and Load)
- Drafts stored at `/Volumes/{catalog}/{schema}/simulation_data/drafts/{name}.yaml`
- CRUD: POST/GET/PUT/DELETE `/api/simulation/drafts`
- Create tab gets "Save Draft" button alongside "Run Now"
- Edit flow: Saved → Edit → Create tab pre-filled → Save/Run

## Files

- `app/backend/api/simulation_jobs.py` — fix scenarios path + add draft endpoints
- `app/frontend/src/hooks/useSimulationDrafts.ts` — new hook
- `app/frontend/src/components/SimulationControls/SimulationManager.tsx` — Saved tab + Save Draft

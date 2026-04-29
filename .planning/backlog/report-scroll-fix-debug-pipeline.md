---
status: active
area: frontend
related: [SimulationReport.tsx, routes.py]
---

# Report Scroll Fix + UC Volume Debug Pipeline

## Problem
Report modal event table doesn't scroll. Root cause: `max-h-[45vh]` (448px) exceeds table content (384px for 12 events), so `overflow-y: auto` never triggers.

## Fix
- Inline style `maxHeight: calc(92vh - 350px)` — subtracts fixed chrome from modal height
- On small viewports (~650px): `92vh - 350px ≈ 248px < 384px` → scroll triggers

## Debug Pipeline (new)
- Frontend POSTs diagnostics to `/api/debug/client-logs`
- Backend appends to UC Volume: `/Volumes/.../simulation_data/debug/client_debug.log`
- CLI reads: `databricks fs cat "dbfs:/Volumes/serverless_stable_3n0ihb_catalog/airport_digital_twin/simulation_data/debug/client_debug.log"`

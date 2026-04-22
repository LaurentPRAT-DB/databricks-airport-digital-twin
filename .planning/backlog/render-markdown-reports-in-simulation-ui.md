# Plan: Render markdown reports in the simulation report UI

## Context

When a simulation runs, it produces `REPORT_*.md` files in `simulation_output/` (e.g., `REPORT_jfk_1000_winter_storm.md`). These are rich narrative reports with scenario analysis, cascade timelines, recommendations, and KPI tables. Currently they sit on disk unused — the in-app SimulationReport component only shows KPIs and event tables computed from the JSON data. The user wants to see the markdown reports rendered inside the app when a simulation is loaded.

**Naming convention:** `simulation_{airport}_{count}_{scenario}.json` maps to `REPORT_{airport}_{count}_{scenario}.md`. Reports live at the top level of `simulation_output/` even when the JSON is in a subdirectory (e.g., `calibrated/`).

## Changes

### 1. Backend — New endpoint to serve markdown content

**File:** `app/backend/api/simulation.py`

Add `GET /api/simulation/report/{filename:path}` endpoint:
- Takes the simulation JSON filename (e.g., `calibrated/simulation_jfk_1000_winter_storm.json`)
- Derives the report path: strip directory prefix, replace `simulation_` with `REPORT_`, change `.json` to `.md`
- Looks in `PROJECT_ROOT / "simulation_output" / report_filename`
- Returns `{"content": "<markdown string>", "filename": "REPORT_jfk_1000_winter_storm.md"}` or 404

### 2. Frontend — Install react-markdown + remark-gfm

```bash
cd app/frontend && npm install react-markdown remark-gfm
```

`react-markdown` renders markdown as React components. `remark-gfm` adds GitHub-Flavored Markdown support (tables, strikethrough, task lists) which the reports use heavily.

### 3. Frontend — Add report tab to SimulationReport modal

**File:** `app/frontend/src/components/SimulationControls/SimulationReport.tsx`

Add a two-tab layout inside the existing modal body:
- Tab 1: "Dashboard" (default) — the existing KPI cards + event table (current content)
- Tab 2: "Analysis Report" — renders the markdown report if available

Tab bar goes right below the header, above the scrollable body. Simple underline-style tabs matching the existing Tailwind design.

### 4. Frontend — Fetch markdown report on load

**File:** `app/frontend/src/hooks/useSimulationReplay.ts`

Add to the hook:
- New state: `markdownReport: string | null`
- After a simulation file loads successfully, fire a fetch to `GET /api/simulation/report/{loadedFile}`
- Store the markdown content (or null if 404)
- Expose `markdownReport` in the return type `UseSimulationReplayResult`

### 5. Frontend — MarkdownReport sub-component

**File:** `app/frontend/src/components/SimulationControls/SimulationReport.tsx` (inline, not a new file)

Add a `MarkdownReportTab` component inside the same file:
- Uses `react-markdown` with `remarkGfm` plugin
- Applies Tailwind prose styling (`prose prose-sm max-w-none`) for clean typography
- Shows "No analysis report available for this simulation" if `sim.markdownReport` is null

## Files to Modify

| File | Change |
|------|--------|
| `app/backend/api/simulation.py` | Add `GET /api/simulation/report/{filename}` endpoint |
| `app/frontend/package.json` | Add react-markdown + remark-gfm dependencies |
| `app/frontend/src/hooks/useSimulationReplay.ts` | Fetch markdown report content, expose in hook result |
| `app/frontend/src/components/SimulationControls/SimulationReport.tsx` | Add tab bar (Dashboard / Analysis Report), render markdown in tab 2 |

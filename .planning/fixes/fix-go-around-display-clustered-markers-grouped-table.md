---
status: done
area: frontend
related:
  - fix-go-around-trajectory-heading-overflow.md
  - fix-go-around-trajectory-post-go-around-approaching.md
  - fix-unrealistic-go-around-trajectory-lines.md
---

# Fix Go-Around Display: Clustered Markers + Grouped Report Table

## Context

The simulation report KPI shows `total_go_arounds: 9` (from summary), but the timeline only shows 3 visible orange markers and the report table shows 3 entries. This is because 3 flights each did 3 go-arounds in rapid succession — the markers overlap at the timeline's scale (each is 1.5px wide), and the events table shows each attempt individually but they're hard to distinguish.

## Changes

### 1. Cluster overlapping timeline markers with count badge

**File:** `app/frontend/src/components/SimulationControls/SimulationControls.tsx`

Replace the flat `.map()` of events (lines 302-322) with a clustering approach:
- Group events that are within 1.5% of each other on the timeline into clusters
- Single events render as before (1 marker)
- Clustered events render as a single marker with a count badge (small number overlay)
- Tooltip on clustered markers shows all event descriptions
- Clicking a cluster seeks to the first event in that cluster

Add a helper function `clusterEvents()` that:
1. Computes position for each event via existing `getEventPosition()`
2. Groups events whose positions are within 1.5% of each other
3. Returns `{ events: ScenarioEvent[], position: number }[]`

### 2. Add "Group by Flight" option in report table

**File:** `app/frontend/src/components/SimulationControls/SimulationReport.tsx`

Add a third `groupBy` mode: `'flight'` alongside existing `'time'` and `'category'`:
- When `groupBy === 'flight'`, group events by callsign (extracted from description via existing `extractCallsign()`)
- Render grouped rows: "DAL123 — 3 go-arounds (IMC)" with expandable sub-rows or inline summary
- For events without a callsign (weather, capacity), show them ungrouped as before
- Keep existing `'time'` and `'category'` modes unchanged

Update the group-by toggle (lines 379-394) to include the new "Flight" option.

Update `filteredEvents` memo (lines 113-126) to support flight grouping — when `groupBy === 'flight'`, sort by callsign first, then by time within each callsign group.

Render the table with collapsible flight groups: show the flight callsign as a header row with the count, and sub-rows for each attempt.

### 3. Offset overlapping markers on timeline

**File:** `app/frontend/src/components/SimulationControls/SimulationControls.tsx`

Within the clustering logic from step 1, when a cluster has 2-4 events, spread them vertically instead of stacking:
- First marker at normal position (top: 0)
- Subsequent markers offset downward by 4px each
- This makes individual markers visible within a cluster while keeping the count badge

## Verification

1. `cd app/frontend && npm test -- --run` — all existing tests pass
2. `cd app/frontend && npm run build` — no build errors
3. Visual check: run `./dev.sh`, load a simulation with go-arounds, verify:
   - Timeline shows clustered markers with count badge
   - Clicking a cluster seeks to first event
   - Report table "Flight" grouping shows grouped go-arounds per callsign
   - Existing "Time" and "Category" grouping modes still work

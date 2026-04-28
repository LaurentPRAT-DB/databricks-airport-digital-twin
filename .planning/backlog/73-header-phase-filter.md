---
status: backlog
area: frontend
related: []
---

# Header Redesign: Compact Legend with Phase Filtering

**Status:** NOT YET IMPLEMENTED (backlog)

## Context

The header bar is overflowing — it crams the app title, airport selector, flight count, demo badge, speed chip, weather, simulation button, FIDS, a full 8-item phase legend, connection status, and platform links all into a single row. On most screens the legend gets cut off. We need to:
1. Make the legend compact and non-intrusive
2. Add phase filtering — clicking a legend item toggles visibility of those flights on the map

## Approach

### 1. Extract legend into a collapsible dropdown (PhaseFilter component)

Replace the inline legend (Header.tsx lines 152-191) with a single "Phases" dropdown button that opens a popover. Each phase is a toggle chip — click to show/hide flights of that phase.

New file: `app/frontend/src/components/Header/PhaseFilter.tsx`

Structure of the dropdown:
```
[Phases ▾]  ← button in the header (same style as other chips)

┌─────────────────────────────────┐
│ Ground                          │
│  [● Parked] [● Pushback] [● Taxi] │
│ Departure                       │
│  [● Takeoff] [● Departing]      │
│ Arrival                         │
│  [● Approaching] [● Landing]    │
│ Cruise                          │
│  [● Enroute]                    │
│                                 │
│ [Show All]  [Hide All]          │
└─────────────────────────────────┘
```

Each chip uses the existing color from `PHASE_BG_CLASSES` in `phaseUtils.ts`. When toggled off → dimmed/strikethrough. The button shows a count badge when some phases are hidden (e.g. "Phases 6/8").

### 2. Add phase filter state to FlightContext

Add to `FlightContext.tsx`:
- `hiddenPhases: Set<string>` — phases currently hidden
- `togglePhase(phase: string): void` — toggle a phase's visibility
- `setHiddenPhases(phases: Set<string>): void` — bulk set
- `filteredFlights: Flight[]` — flights filtered by visible phases (memoized)

Consumers that render flights will use `filteredFlights` instead of `flights`:
- `AirportScene.tsx` (3D) — already receives flights as prop from App.tsx
- `AirportMap` (2D) — uses FlightContext internally
- `FlightList` — uses FlightContext internally
- Header flight count — show `filteredFlights.length / flights.length`

The 3D map gets flights via props from App.tsx, so App.tsx will pass `filteredFlights` instead of `flights`.

### 3. Update Header layout

Reuse existing data from `phaseUtils.ts` (`PHASE_LABELS`, `PHASE_BG_CLASSES`) — single source of truth for colors/labels.

Also: move the connection status indicator into a smaller inline dot (remove the text "Connected"/"Updating") to save space.

## Files to modify

| File | Change |
|------|--------|
| `app/frontend/src/components/Header/PhaseFilter.tsx` | NEW — dropdown with toggle chips |
| `app/frontend/src/components/Header/Header.tsx` | Replace inline legend with `<PhaseFilter />`, compact connection status |
| `app/frontend/src/context/FlightContext.tsx` | Add hiddenPhases, togglePhase, filteredFlights |
| `app/frontend/src/App.tsx` | Pass filteredFlights to Map3D instead of flights |
| `app/frontend/src/components/Header/Header.test.tsx` | Update tests for new legend structure |

## Reuse

- `PHASE_BG_CLASSES`, `PHASE_LABELS` from `utils/phaseUtils.ts` — single source of truth for colors/labels
- Same dropdown pattern as `PlatformLinks.tsx` (backdrop click-away, absolute positioning, z-50)
- Same chip styling as SpeedChip (rounded-full, bg-slate-700)

## Verification

1. `cd app/frontend && npm test -- --run` — all tests pass
2. `./dev.sh` → header shows compact "Phases" button
3. Click Phases → dropdown with grouped toggle chips
4. Toggle off "Parked" → parked aircraft disappear from 2D map, 3D scene, and flight list
5. Flight count in header updates to show filtered/total (e.g. "42/50")
6. "Show All" / "Hide All" buttons work
7. No horizontal overflow on header at 1440px width

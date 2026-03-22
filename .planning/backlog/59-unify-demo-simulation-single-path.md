# Unify Demo and Simulation: Single Synthetic Data Path

## Context

The app currently has two separate synthetic data systems:

1. **fallback.py (real-time):** `generate_synthetic_flights()` → `FlightService.get_flights()` → WebSocket broadcast every 2s → `useFlights` hook → `FlightContext.liveFlights`
2. **SimulationEngine (frame-based):** Pre-generates 24h of frames → served via `/api/simulation/demo/` → `useSimulationReplay` hook → `SimulationControls` → `FlightContext.simulationFlights`

The frontend currently differentiates between "demo" (auto-started simulation) and "simulation" (manually loaded file) with separate UI: `DEMO:` vs `SIM:` header badges, a separate `DemoPausedBar`, different button labels. The user wants these unified: demo IS a simulation with default parameters (current airport, 24h). The UI should be identical regardless of how the simulation was loaded.

**Note:** `fallback.py` cannot be removed entirely — the `SimulationEngine` itself imports and reuses `fallback.py`'s flight state machine (`FlightState`, `FlightPhase`, `_create_new_flight`, `_update_flight_state`, etc.). The change is to stop using `fallback.py` as a frontend data source and unify the UI.

---

## Changes

### 1. Frontend: `useSimulationReplay.ts`

Remove the `isDemoMode` state variable. Both `loadDemo()` and `loadFile()` produce identical state — no special flag.

- Delete `isDemoMode` state and its setter
- Remove `setIsDemoMode(true)` from `loadDemo()`
- Remove `setIsDemoMode(false)` from `stop()`
- Keep `demoPaused` but rename to `switchPaused` (paused for airport switch — applies to any simulation, not just demo)
- Rename `pauseDemo()` → `pauseForSwitch()`
- Update the return type interface: remove `isDemoMode`, rename `demoPaused` → `switchPaused`, rename `pauseDemo` → `pauseForSwitch`

### 2. Frontend: `SimulationControls.tsx`

Unify all UI text and behavior:

| Current | New |
|---------|-----|
| `DEMO: 12:00:00` | `SIM: 12:00:00` |
| `SIM: 12:00:00` | `SIM: 12:00:00` (unchanged) |
| `Demo Paused` (header badge) | `Simulation Paused` |
| `DemoPausedBar` (amber bottom bar) | `PausedBar` — same visual style but says "Simulation Paused" |
| `Start Demo for KSFO` (in paused bar) | `Start Simulation for KSFO` |
| `Exit Demo` (in paused bar) | `Exit` |
| `Preparing Demo...` | `Preparing Simulation...` |
| `Start Demo` (idle button) | `Start Simulation` |
| `sim.isDemoMode ? 'DEMO' : 'SIM'` | Always `'SIM'` |

Update all references: `sim.isDemoMode` → removed, `sim.demoPaused` → `sim.switchPaused`, `sim.pauseDemo()` → `sim.pauseForSwitch()`.

The airport-switch pause logic stays the same but no longer checks `isDemoMode` — any active simulation pauses on airport switch:
```typescript
// Before: if (sim.isActive && sim.isDemoMode && currentAirport !== pendingAirport)
// After:  if (sim.isActive && currentAirport !== pendingAirport)
```

### 3. Frontend: `SimulationControls.test.tsx`

Update test expectations:
- `DEMO:` → `SIM:` (all occurrences)
- `Demo Paused` → `Simulation Paused`
- `Exit Demo` → `Exit`
- `isDemoMode` → removed from mock
- `demoPaused` → `switchPaused`
- `pauseDemo` → `pauseForSwitch`
- `Start Demo` → `Start Simulation`

### 4. Frontend: `useSimulationReplay.test.ts`

Update test references:
- `isDemoMode` → removed from assertions
- `demoPaused` → `switchPaused`
- `pauseDemo` → `pauseForSwitch`
- Remove tests that assert `isDemoMode === true` after `loadDemo` (no longer a concept)

### 5. Backend: No changes

The backend stays as-is:
- `DemoSimulationService` keeps generating default simulations (it's an internal service name)
- `/api/simulation/demo/{icao}` endpoint stays (the URL is an implementation detail)
- `fallback.py` stays as the flight state machine library used by `SimulationEngine`
- WebSocket/live flight path remains for real Lakebase/Delta data (just not used for synthetic)

---

## Files to Modify

| File | Change |
|------|--------|
| `app/frontend/src/hooks/useSimulationReplay.ts` | Remove `isDemoMode`, rename `demoPaused`→`switchPaused`, `pauseDemo`→`pauseForSwitch` |
| `app/frontend/src/components/SimulationControls/SimulationControls.tsx` | Unify all UI text, remove demo/sim branching, rename references |
| `app/frontend/src/hooks/useSimulationReplay.test.ts` | Update to match new interface |
| `app/frontend/src/components/SimulationControls/SimulationControls.test.tsx` | Update test expectations |

---

## Verification

1. `cd app/frontend && npm test -- --run` — all tests pass
2. `./dev.sh` → app loads → PlaybackBar shows `SIM: HH:MM:SS` (not `DEMO:`)
3. Switch airport → bottom bar shows "Simulation Paused" (not "Demo Paused")
4. Click "Start Simulation for XXXX" → new simulation loads with same PlaybackBar UI
5. Manually load a simulation file → identical UI to auto-started simulation
6. Exit simulation → button shows "Start Simulation" (not "Start Demo")

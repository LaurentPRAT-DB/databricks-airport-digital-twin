# 78 — Fix: SimulationEngine corrupts live broadcast state during airport switch

- **area:** simulation, backend, frontend
- **priority:** P0
- **status:** planned
- **effort:** medium
- **depends_on:** none

## Problem

When switching to an airport without a pre-generated demo file (e.g., ATH/LGAV in prod), `_generate_demo_background()` runs `SimulationEngine.run()` via `asyncio.to_thread`. The engine mutates 30+ module-level globals shared with the live broadcast loop (`_flight_states`, `_gate_states`, `_clock_fn`, `_osm_primary_runway_resolved`, airport offsets, calibration state, etc.). This corrupts the live synthetic generator, causing 0 flights to broadcast. Meanwhile, `demo_ready` never fires (engine either crashes or takes too long), so the frontend shows "Preparing Simulation..." forever.

**Works for SFO:** has a pre-generated demo file → engine never runs.
**Fails for ATH/LGAV** (and any airport without `demo_<ICAO>.json` in Volume or local): engine runs in-process, corrupts shared state.

## Fix Strategy

Two-part fix: prevent the engine from corrupting live state + handle missing demo gracefully.

### Part 1: Backend — always broadcast demo_ready, defer engine to subprocess

**File:** `app/backend/api/routes_airport.py` (lines 719-728)

Change `_generate_demo_background()`:
1. Broadcast `demo_ready` immediately (before trying to generate)
2. If no static demo exists, run the engine in a subprocess (`multiprocessing.Process`) instead of `asyncio.to_thread` so it gets isolated memory
3. If subprocess isn't available (fallback), skip engine generation entirely — log a warning

```python
async def _generate_demo_background():
    from app.backend.services.demo_simulation_service import get_demo_simulation_service
    try:
        demo_svc = get_demo_simulation_service()
        # Always signal demo_ready — live synthetic generator handles flights
        await broadcaster.broadcast({"type": "demo_ready", "data": {"icao": icao_code}})

        # Generate demo file in background (subprocess isolation)
        if not demo_svc.has_demo(icao_code):
            await asyncio.to_thread(demo_svc.generate_demo_isolated, icao_code)
            logger.info(f"[DIAG] Background demo generation for {icao_code} complete")
    except Exception as e:
        logger.error(f"Background demo generation failed for {icao_code}: {e}")
```

### Part 2: Demo service — isolated generation via subprocess

**File:** `app/backend/services/demo_simulation_service.py`

Add `generate_demo_isolated()` method that:
1. Tries `_load_static_demo()` first (no engine needed)
2. If no static file, spawns a subprocess with its own copy of all module globals — no shared state with parent

```python
def generate_demo_isolated(self, icao_code: str):
    """Generate demo in subprocess to avoid corrupting live broadcast state."""
    from src.simulation.config import SimulationConfig
    from src.simulation.engine import SimulationEngine
    # ... initialize and run in isolated process
```

### Part 3: Frontend — graceful fallback when demo not available

**File:** `app/frontend/src/hooks/useSimulationReplay.ts` (lines 380-384)

When `loadDemo` gets 404, silent return (no throw) — let live WS flights render:

```typescript
if (!res.ok) {
  if (res.status === 404) {
    console.info(`No demo file for ${airportIcao}, using live synthetic mode`);
    return; // Don't throw — let live synthetic generator handle flights
  }
  throw new Error(`Failed to load demo: ${res.statusText}`);
}
```

**Key insight:** flights are ALWAYS streaming via WebSocket (`useFlights` hook). The simulation replay (`useSimulationReplay`) is an OVERLAY — when active it replaces WS flights. When NOT active (or failed), WS flights show naturally. So if `loadDemo` fails with 404, `sim.isActive` stays false → live WS flights render normally.

## Files to Modify

1. `app/backend/api/routes_airport.py` — move `demo_ready` broadcast before generation, use `generate_demo_isolated`
2. `app/backend/services/demo_simulation_service.py` — add `generate_demo_isolated()` with subprocess isolation
3. `app/frontend/src/hooks/useSimulationReplay.ts` — 404 on `loadDemo` = silent return (no throw)

## Verification

1. `cd app/frontend && npm test -- --run` — frontend tests pass
2. `uv run pytest tests/ -k "demo" -v` — demo-related tests pass
3. `uv run pytest tests/ -k "airport_switch or activate" -v` — switch tests pass
4. Manual test on dev: switch to ATH, verify flights appear within 2-3 seconds
5. Deploy to prod, switch to ATH, verify simulation starts

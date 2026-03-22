# Demo as 24h Simulation Replay

## Context

The current "demo" mode uses a real-time synthetic flight generator (fallback.py) that advances flight states based on wall-clock time. Even with a 16x gate-time multiplier, turnarounds feel sluggish for live demos. The simulation engine (`src/simulation/engine.py`) already generates high-quality 24h datasets with calibrated flight counts, but it requires pre-running a CLI command and loading files manually.

**Goal:** Make the default app experience a pre-generated 24h simulation replay that auto-starts on load. This gives users timeline control (seek, speed 1x-60x), consistent behavior, and immediate visual activity. When switching airports, pause the demo and wait for the user to reset it.

## Architecture

### Current flow (live synthetic)

```
App init -> fallback.py generates flights in real-time -> WebSocket pushes every 2s -> frontend renders
```

### New flow (simulation replay)

```
App init -> SimulationEngine.run() generates 24h in-memory -> saved to /tmp/
         -> frontend auto-loads simulation file -> useSimulationReplay plays frames
         -> user controls speed (1x-60x), seek, pause
```

The existing simulation infrastructure (`SimulationEngine`, `SimulationRecorder`, `useSimulationReplay`, `SimulationControls`, `PlaybackBar`) is reused wholesale. The only new pieces are:

1. Backend generates a demo simulation at startup (per airport)
2. Frontend auto-starts the demo instead of waiting for user to click "Simulation"
3. Airport switch pauses demo, visual state shows "paused"

## Implementation

### 1. Backend: Generate demo simulation at startup

**File:** `app/backend/services/demo_simulation_service.py` (NEW)

Singleton service that generates a 24h simulation for the current airport during `initialize_all_data()`.

```python
class DemoSimulationService:
    _instance = None

    def __init__(self):
        self._demo_files: dict[str, Path] = {}  # icao -> path
        self._generating: set[str] = set()

    def generate_demo(self, airport_icao: str, progress_callback=None) -> Path:
        """Generate a 24h demo simulation for the airport. Returns path to JSON file."""
        iata = icao_to_iata(airport_icao)

        # Use calibrated flight counts from AirportProfileLoader
        profile = AirportProfileLoader.load(iata)
        daily_flights = profile.daily_departures + profile.daily_arrivals if profile else 100
        arrivals = daily_flights // 2
        departures = daily_flights - arrivals

        config = SimulationConfig(
            airport=iata,
            arrivals=arrivals,
            departures=departures,
            duration_hours=24.0,
            time_step_seconds=2.0,
            seed=42,  # deterministic for consistency
            start_time=<midnight UTC today>,
        )

        engine = SimulationEngine(config)
        recorder = engine.run()

        # Write to temp directory
        output_path = Path(tempfile.gettempdir()) / f"demo_{airport_icao}.json"
        recorder.write_output(str(output_path), config.model_dump())
        self._demo_files[airport_icao] = output_path
        return output_path

    def get_demo_file(self, airport_icao: str) -> Path | None:
        return self._demo_files.get(airport_icao)

    def has_demo(self, airport_icao: str) -> bool:
        return airport_icao in self._demo_files
```

**Integration point:** `data_generator_service.py:initialize_all_data()` -- add a new step (step 8) that calls `demo_simulation_service.generate_demo()`. This runs after flight/weather/schedule generation.

**File:** `app/backend/api/simulation.py` -- add endpoint:

```
GET /api/simulation/demo/{airport_icao}
```

Returns the demo simulation data (same format as existing `/api/simulation/data/{filename}`). If not yet generated, returns 404. The frontend polls or uses `isReady` flag from `/api/ready`.

### 2. Backend: Weather stability

**File:** `src/ingestion/weather_generator.py`

The weather generator is purely synthetic -- it generates METAR based on time-of-day patterns. For the demo simulation, the engine already calls `generate_metar()` at each snapshot, so weather naturally varies over the 24h period. No change needed for weather within the simulation -- it's baked into the frames.

For the WeatherWidget in the header during demo playback: it currently fetches `/api/weather/current` which returns synthetic weather for "now". During demo mode the frontend should either:
- Keep showing current weather (simplest -- weather widget is informational, not tied to simulation time)
- This is acceptable since the user said "otherwise use the current weather and make it stable for the previous 24h"

**Decision:** Leave WeatherWidget as-is. It shows current synthetic weather. No changes needed.

### 3. Frontend: Auto-start demo on load

**File:** `app/frontend/src/components/SimulationControls/SimulationControls.tsx`

Add auto-start logic:

```tsx
// On mount + backend ready, auto-load demo for current airport
useEffect(() => {
  if (!sim.isActive && !sim.isLoading && currentAirport) {
    sim.loadDemo(currentAirport);  // new method
  }
}, [backendReady, currentAirport]);
```

**File:** `app/frontend/src/hooks/useSimulationReplay.ts`

Add `loadDemo(airportIcao: string)` method that fetches from `/api/simulation/demo/{icao}` instead of `/api/simulation/data/{filename}`. Same frame parsing logic.

### 4. Frontend: Pause on airport switch

**File:** `app/frontend/src/components/SimulationControls/SimulationControls.tsx`

When `currentAirport` changes while a demo is active:
1. Call `sim.pause()` -- stops frame advancement
2. Set a `demoPaused` state
3. Show "Demo paused -- click to start demo for {newAirport}" message in the PlaybackBar
4. When user clicks the restart button, call `sim.loadDemo(newAirport)` which fetches the new demo

This is the "pause the animation, wait for the user to reset the demo" behavior requested.

### 5. Frontend: Demo button visual state

**File:** `app/frontend/src/components/SimulationControls/SimulationControls.tsx`

Current state:
- Active: `bg-indigo-600/80` pill with pulsing dot + sim time
- Inactive (not running): `bg-indigo-600` "Simulation" button

New states:
- **Demo active & playing:** `bg-indigo-600/80` pill with pulsing dot + sim time (unchanged)
- **Demo paused (airport switched):** `bg-amber-600` pill with "Demo Paused" text, no pulse
- **Demo not started / generating:** `bg-slate-600` (dimmed) "Preparing Demo..." with spinner
- **Demo stopped (user exited):** `bg-slate-600` "Start Demo" button (dimmed, clearly inactive)

The key visual distinction: when demo is not running, the button is gray/dimmed (`bg-slate-600`) instead of the vibrant indigo, making it obvious it's inactive.

### 6. Backend: Expose demo readiness in /api/ready

**File:** `app/backend/api/routes.py`

Extend the `/api/ready` response with a `demo_ready` boolean field. The frontend uses this to know when to auto-start the demo. During startup, the status messages already show progress -- add "Generating demo simulation..." as a step.

## Files to modify

| File | Change |
|------|--------|
| `app/backend/services/demo_simulation_service.py` | NEW -- singleton that generates & caches demo simulations per airport |
| `app/backend/services/data_generator_service.py` | Add step 8: generate demo simulation during `initialize_all_data()` |
| `app/backend/api/simulation.py` | Add `GET /api/simulation/demo/{airport_icao}` endpoint |
| `app/backend/api/routes.py` | Add `demo_ready` to `/api/ready` response |
| `app/frontend/src/hooks/useSimulationReplay.ts` | Add `loadDemo(icao)` method, `demoPaused` state |
| `app/frontend/src/components/SimulationControls/SimulationControls.tsx` | Auto-start demo, pause on airport switch, dimmed button states |
| `app/frontend/src/App.tsx` | Pass `backendReady` + `currentAirport` to SimulationControls for auto-start |

## Reuse

- `SimulationEngine` + `SimulationConfig` from `src/simulation/` -- unchanged
- `SimulationRecorder.write_output()` -- writes the JSON the frontend already knows how to parse
- `useSimulationReplay` -- existing hook handles frame parsing, playback, seek, speed
- `PlaybackBar` -- existing bottom bar with timeline, speed controls, events
- `AirportProfileLoader` from `src/calibration/profile.py` -- calibrated flight counts per airport
- `icao_to_iata()` from `app/backend/demo_config.py` -- ICAO/IATA conversion

## Cleanup: Remove legacy real-time demo mode

Once the 24h simulation replay is the default, the real-time synthetic "demo" path and its gate-time multiplier become dead code. Remove them to reduce complexity.

### Code to remove

| File | What to remove |
|------|----------------|
| `src/ingestion/fallback.py` | `_DEFAULT_GATE_TIME_MULTIPLIER`, `_gate_time_multiplier`, `get_gate_time_multiplier()`, `set_gate_time_multiplier()`, `DEMO_GATE_TIME_MULTIPLIER` constant. Remove all `/get_gate_time_multiplier()` divisors in `_build_turnaround_schedule()` (lines 2474-2475), `_create_new_flight()` PARKED branch (line 2590), `_update_flight_state()` PARKED branch (line 3144), and gate cooldown (line 1884). |
| `src/ml/gse_model.py` | `calculate_turnaround_status()` -- remove `get_gate_time_multiplier()` import and scaling at lines 225-226, 251. Use real-time values directly (simulation replay provides its own time scale). |
| `app/backend/services/gse_service.py` | Lines 162-163, 171 -- remove `get_gate_time_multiplier()` import and divisors for estimated departure and remaining minutes. |
| `app/backend/api/routes.py` | Remove `GET /api/settings/gate-time-multiplier` and `PUT /api/settings/gate-time-multiplier` endpoints (lines ~1549-1570). Remove `get_gate_time_multiplier`, `set_gate_time_multiplier` from the fallback import. |
| `tests/test_flight_realism.py` | `test_wide_body_stays_parked_longer` -- rewrite to use real-world timing (no speedup). |
| `tests/test_synthetic_data_requirements.py` | `TestTurnaroundStatus` -- rewrite all 4 tests to use real-world timing. |

### What stays

- `fallback.py` itself stays -- it's still needed as a data source fallback when no simulation file is loaded (e.g., fresh airport with no pre-generated demo yet)
- `generate_synthetic_flights()` stays but turnarounds run at real-world pace (1x) -- acceptable since it's only a brief fallback before the demo file loads
- `SimulationEngine` calls `_update_flight_state()` from `fallback.py` which uses the multiplier internally. As of 2026-03-22, `engine.py:run()` forces multiplier to 1.0 during simulation and restores it after. When the multiplier is removed, this save/restore can be deleted too.
- `TURNAROUND_TIMING` dict in `gse_model.py` stays (used by simulation engine and GSE display)

### Migration notes

- The multiplier was 8x from initial implementation, bumped to 16x on 2026-03-22 as a short-term fix
- The `PUT /api/settings/gate-time-multiplier` endpoint was added for runtime tuning during demos -- no longer needed with playback speed controls (1x-60x in PlaybackBar)
- Frontend `SimulationControls` already has speed controls that replace the multiplier's purpose

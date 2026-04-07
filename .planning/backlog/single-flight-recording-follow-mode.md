# Plan: Single-Flight Recording & Follow Mode

**Status:** Done (verified 2026-04-06 — all 4 features already implemented)
**Date added:** 2026-04-06
**Scope:** Backend origin/dest in snapshots + Frontend camera follow + flight isolation + CSV export

---

## Context

The simulation replay system has all the data to track individual flights, but lacks:

- Camera following a selected flight
- Origin/destination in position snapshots
- Export of a single flight's lifecycle data
- Visual isolation of the tracked flight

## Changes

### 1. Add Origin/Destination to Position Snapshots (Backend)

**`src/simulation/recorder.py`** — Add `origin_airport` and `destination_airport` params to `record_position()`, include them in the snapshot dict.

**`src/simulation/engine.py:1283`** — Pass `state.origin_airport` and `state.destination_airport` to the `record_position()` call.

**`app/frontend/src/hooks/useSimulationReplay.ts:46-60`** — Add `origin_airport` and `destination_airport` to `PositionSnapshot` interface, propagate them in `snapshotToFlight()` (lines 108-128).

### 2. Camera Follow Mode (Frontend — 2D Map)

**`app/frontend/src/components/Map/AirportMap.tsx`** — Add a `FlightFollower` component (inside `<MapContainer>`) that:

- Reads `selectedFlight` from FlightContext
- When a flight is selected during replay, calls `map.panTo([lat, lon])` on each position update
- Uses `useRef` to debounce (only pan when flight moves > threshold pixels)
- Respects user interaction: if user manually pans, disable follow until re-selection

### 3. Flight Isolation / Dim Mode (Frontend)

**`app/frontend/src/context/FlightContext.tsx`** — Add `isolateSelected: boolean` and `setIsolateSelected` to context.

**`app/frontend/src/components/Map/FlightMarker.tsx`** — When `isolateSelected` is true and the flight is NOT selected, reduce opacity to 0.15 via the SVG opacity style.

**`app/frontend/src/components/FlightDetail/FlightDetail.tsx`** — Add an "Isolate" toggle button next to the existing "Show Trajectory" toggle.

### 4. Single-Flight Data Export (Frontend)

**`app/frontend/src/components/FlightDetail/FlightDetail.tsx`** — Add a "Download Flight Log" button that:

- Iterates all frames in `simData` for the selected `icao24`
- Builds a CSV with columns: `time, callsign, latitude, longitude, altitude_ft, speed_kts, heading_deg, vertical_rate_ftmin, phase, on_ground, aircraft_type, assigned_gate, origin, destination`
- Triggers browser download as `{callsign}_{icao24}_flight_log.csv`

The data extraction needs access to the replay hook. Two options:

- **Option A:** Pass `getFlightTrajectory` from the replay hook (already in context as `simTrajectoryProvider`) — but it only returns trajectory points, not full snapshots.
- **Option B:** Add a new `getFlightLog(icao24): PositionSnapshot[]` function to `useSimulationReplay` that returns ALL frames (not phase-segmented), and expose it via a new `simFlightLogProvider` in FlightContext.

Going with **Option B** — cleaner separation, returns full lifecycle data including origin/destination.

**`app/frontend/src/hooks/useSimulationReplay.ts`** — Add `getFlightLog(icao24)` that iterates all frames and collects every snapshot for that icao24.

**`app/frontend/src/context/FlightContext.tsx`** — Add `simFlightLogProvider` type and pass it through context.

## Files to Modify

| File | Change |
|------|--------|
| `src/simulation/recorder.py` | Add origin/dest params to `record_position()` |
| `src/simulation/engine.py` | Pass origin/dest to recorder |
| `app/frontend/src/hooks/useSimulationReplay.ts` | Add origin/dest to PositionSnapshot, add `getFlightLog()` |
| `app/frontend/src/context/FlightContext.tsx` | Add `isolateSelected`, `simFlightLogProvider` |
| `app/frontend/src/components/Map/AirportMap.tsx` | Add `FlightFollower` component |
| `app/frontend/src/components/Map/FlightMarker.tsx` | Dim non-selected flights when isolated |
| `app/frontend/src/components/FlightDetail/FlightDetail.tsx` | Add Isolate toggle + Download Flight Log button |
| `app/frontend/src/types/flight.ts` | No changes needed (already has origin/dest fields) |

## Verification

1. Backend: `uv run pytest tests/ -k "simulation" -v` — recorder changes don't break tests
2. Frontend: `cd app/frontend && npm test -- --run` — component tests pass
3. Manual: Load a simulation, select a flight, verify:
   - Map follows the flight as replay progresses
   - Isolate toggle dims other aircraft
   - Download button produces CSV with complete flight lifecycle
   - Origin/destination appear in FlightDetail panel during replay

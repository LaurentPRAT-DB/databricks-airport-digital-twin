---
status: planned
area: simulation
related:
  - src/simulation/engine.py
  - app/frontend/src/hooks/useSimulationReplay.ts
---

# Fix: Diverted Flights Disappearing from Map

## Context

When a Go-Around leads to a Diversion, the flight immediately disappears from the map. This is wrong for an airport operator — they need to see the aircraft departing their airspace. The flight should remain visible until it physically exits the simulation radius (~30 NM).

## Root Cause (two issues)

1. **Backend** (`_divert_flight`) at `src/simulation/engine.py:1229`: sets `origin_airport = None`, which loses the knowledge that this flight was related to the local airport. The flight was arriving here — the diversion changes where it's going, not where it came from.

2. **Frontend** (`isLocalEnroute`) at `app/frontend/src/hooks/useSimulationReplay.ts:72`: filters enroute flights by checking if `origin_airport` or `destination_airport` matches the local airport. Since `origin_airport` was cleared and `destination_airport` is now an alternate, the flight fails the filter and vanishes.

## Fix

**Approach:** Simplify the rule.

The backend already removes flights at `EXIT_RADIUS_DEG` (0.5°, ~30 NM). Any flight still present in the simulation data is by definition close enough to display. The `isLocalEnroute` filter is over-aggressive.

**Simplified rule:** If a flight is in the simulation frame data, show it. The backend handles the distance-based removal. The frontend doesn't need to second-guess it.

## Changes

### 1. Backend: Preserve `origin_airport` on diversion

**File:** `src/simulation/engine.py` (line 1229)

Currently:
```python
state.origin_airport = None
```

Change to: Keep `origin_airport` as-is. If the flight was arriving (origin set, no destination), it should retain that origin. The diversion just sets a new destination.

```python
# Don't clear origin_airport — flight still originated from there.
# Only set destination to the alternate airport.
```

This also fixes the right panel (FIDS) display — the flight retains its route context (e.g., "DAL456 from ATL, diverted to JFK").

### 2. Frontend: Remove the `isLocalEnroute` filter

**File:** `app/frontend/src/hooks/useSimulationReplay.ts`

The `isLocalEnroute` function (lines 72-78) is no longer needed. The backend's `EXIT_RADIUS_DEG` already ensures only relevant flights are in the simulation data. Remove the filter and show all enroute flights present in frames.

- **Line 538:** `if (s.phase === 'enroute') return isLocalEnroute(s, localAirport);` → `if (s.phase === 'enroute') return true;`
- **Line 680:** `(s.phase !== 'enroute' || isLocalEnroute(s, localAirport))` → remove the enroute condition entirely
- **Line 751:** `(currentPhase === 'enroute' && currentSnap && isLocalEnroute(currentSnap, localAirportCfg))` → `(currentPhase === 'enroute' && currentSnap)`

Then remove the `isLocalEnroute` function (dead code).

### 3. Update tests

Any test asserting the old filtering behavior needs updating.

## Verification

1. Run Python tests: `uv run pytest tests/ -k "divert or go_around or enroute" -v`
2. Run frontend tests: `cd app/frontend && npm test -- --run`
3. Manual: run a simulation with weather that triggers go-arounds → diversions, confirm the diverted flight remains visible on the map as it flies away until it exits the 30 NM radius.

## Files to Modify

- `src/simulation/engine.py` — remove `state.origin_airport = None` from `_divert_flight`
- `app/frontend/src/hooks/useSimulationReplay.ts` — remove `isLocalEnroute` function and its 3 call sites
- Related test files if they assert on the old filtering

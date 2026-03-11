# Plan: Gate Detail on Click with Flight Info

## Context

Gate occupancy in the GateStatus panel is currently random (`Math.random() > 0.6`) and clicking a gate does nothing. The user wants clicking a gate to show the flight currently at the gate or any incoming flight, using proper airport terminology.

## Changes

### 1. Use real flight data for gate occupancy

**File:** `app/frontend/src/components/GateStatus/GateStatus.tsx`

- Import `useFlightContext` to access `flights[]`
- Build a lookup map: `Map<gateRef, Flight>` from flights with `assigned_gate`
- Replace random `isOccupied` with actual occupancy from flight data
- Classify flights at each gate:
  - **"ON STAND"** — flight is ground phase with velocity === 0 at this gate
  - **"TAXI IN"** — flight is ground phase with velocity > 0 heading to this gate
  - **"INBOUND"** — flight is descending phase assigned to this gate
  - Gate is **"VACANT"** if no flight is assigned

### 2. Add gate click → popover with flight info

**File:** `app/frontend/src/components/GateStatus/GateStatus.tsx`

- Add `selectedGate` state
- On gate cell click, set `selectedGate`
- Render a compact detail card below the gate grid showing:
  - Gate ref + status badge (ON STAND / TAXI IN / INBOUND / VACANT)
  - If flight present: callsign, aircraft type, origin→destination, phase
  - Clicking the flight callsign selects it in FlightContext (highlights on map)
- Click outside or click same gate again to dismiss

### 3. Gate cell color update

- **Red:** ON STAND (occupied)
- **Amber:** TAXI IN or INBOUND (arriving)
- **Green:** VACANT

## Files to Modify

- `app/frontend/src/components/GateStatus/GateStatus.tsx` — all changes in this single file

## Verification

1. `cd app/frontend && npm test -- --run` — existing tests pass
2. Open app locally (`./dev.sh`), click Terminal A tab, verify gate colors match actual flights
3. Click an occupied gate (red) → should show flight callsign, "ON STAND", origin/destination
4. Click an amber gate → should show "INBOUND" or "TAXI IN" with flight info
5. Click a green gate → should show "VACANT"
6. Click the callsign link → flight should be selected on the map

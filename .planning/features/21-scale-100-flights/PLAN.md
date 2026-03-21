# Phase 21: Scale to 100 Flights

## Goal

Scale the simulation from 50 to 100 concurrent flights with no performance degradation. Requires fixing infrastructure bottlenecks (gates, runways, WebSocket efficiency) and rebalancing the flight lifecycle.

## Status: Plan — Not Started

---

## Problem Analysis

At 50 flights the simulation works but has hidden constraints that break at 100:

| Constraint | Current | Needed for 100 | Impact |
|-----------|---------|----------------|--------|
| Gates | 9 default / ~80 OSM | 30+ available | Flights queue indefinitely for gates |
| Runways | 1 (28R for both arr/dep) | 2 (28L arr, 28R dep) | Throughput ~20-30 mvmt/hr with wake sep |
| Approach cap | 4 aircraft max | 6-8 | Holding patterns back up enroute |
| Delta removal scan | O(n*m) `any()` | O(1) set lookup | 10K checks per broadcast at 100 flights |
| Phase counting | O(n) full scan per call | O(1) indexed | Called 5+ times per tick per flight |

---

## Tasks

### Task 1: Fix `_compute_deltas` removal scan (websocket.py)

**File:** `app/backend/api/websocket.py` line 34

**Current (O(n*m)):**
```python
removed = [k for k in prev_flights if not any(f["icao24"] == k for f in current_flights)]
```

**Fix (O(n)):**
```python
current_ids = {f["icao24"] for f in current_flights}
removed = [k for k in prev_flights if k not in current_ids]
```

**Impact:** At 100 flights, avoids 10,000 comparisons every 2s broadcast.

---

### Task 2: Add phase index for O(1) phase counts (fallback.py)

**File:** `src/ingestion/fallback.py`

Add a `_flights_by_phase` index maintained alongside `_flight_states`:

```python
_flights_by_phase: Dict[FlightPhase, Set[str]] = {phase: set() for phase in FlightPhase}
```

**Update points:**
- `_create_new_flight()` — add to index
- `_update_flight_state()` — on every `state.phase = X` transition, move icao24 between sets
- Flight removal (line 2265) — remove from index
- `_count_aircraft_in_phase()` — replace `sum()` scan with `len(_flights_by_phase[phase])`

**Helper:**
```python
def _set_phase(state: FlightState, new_phase: FlightPhase):
    """Transition flight to new phase, maintaining index."""
    old_phase = state.phase
    if old_phase != new_phase:
        _flights_by_phase[old_phase].discard(state.icao24)
        _flights_by_phase[new_phase].add(state.icao24)
        state.phase = new_phase
```

**Impact:** `_count_aircraft_in_phase()` drops from O(n) to O(1). Called ~5 times per flight per tick × 100 flights = 500 scans eliminated per tick.

---

### Task 3: Dual runway operations (fallback.py)

**File:** `src/ingestion/fallback.py`

**Current:** All arrivals and departures use runway `28R`.

**Change:**
- Arrivals land on `28L` (the left/south runway — used for arrivals at SFO)
- Departures take off from `28R` (the right/north runway — used for departures at SFO)
- This matches SFO's standard West Plan configuration

**Implementation:**
1. Define `28L` runway geometry (already have `RUNWAY_28L_EAST` constant)
2. In APPROACHING → LANDING transition (line 1694): check `_is_runway_clear("28L")` instead of `"28R"`
3. In LANDING phase (line 1710-1734): use 28L touchdown point, occupy/release 28L
4. In TAXI_TO_RUNWAY → TAKEOFF transition (line 1931-1955): keep 28R for departures
5. Update `_get_takeoff_runway_geometry()` to use 28R (already does)
6. Add arrival runway geometry function `_get_landing_runway_geometry()` for 28L

**Throughput gain:** Doubles capacity from ~25 to ~50 movements/hour since arrivals and departures no longer compete for the same runway.

---

### Task 4: Raise approach capacity (fallback.py)

**File:** `src/ingestion/fallback.py` line 2118

**Current:**
```python
can_start_approach = approach_count < 4
```

**Change:**
```python
# Scale approach capacity: allow more simultaneous approaches with dual runway ops
# 28L can handle 6-8 aircraft in sequence with 3-5 NM spacing over ~15 NM approach
MAX_APPROACH_AIRCRAFT = 8
can_start_approach = approach_count < MAX_APPROACH_AIRCRAFT
```

**Also update `_find_aircraft_ahead_on_approach()`** to only scan approaching aircraft (use phase index from Task 2):
```python
approaching_ids = _flights_by_phase[FlightPhase.APPROACHING] | _flights_by_phase[FlightPhase.LANDING]
for icao24 in approaching_ids:
    other = _flight_states[icao24]
    ...
```

---

### Task 5: Ensure OSM gates load reliably (fallback.py)

**File:** `src/ingestion/fallback.py` lines 377-422

**Problem:** If OSM gates haven't loaded yet when flights spawn, only 9 default gates are available. With 100 flights and 35-45 min turnarounds, ~30-40 aircraft are parked at any time — far exceeding 9 gates.

**Fix:**
1. Expand `_DEFAULT_GATES` from 9 to ~30 gates covering all SFO terminals (A, B, C, D, E, F, G) as a better fallback
2. In `generate_synthetic_flights()`, dynamically cap parked aircraft at 80% of available gates (not 100%) to leave buffer for arriving flights
3. Add gate overflow logic: if all gates occupied and aircraft needs to park, create a remote stand position near the terminal

**Default gate expansion (real SFO gate refs):**
```python
_DEFAULT_GATES = {
    # International Terminal G
    "G1": ..., "G2": ..., "G3": ..., "G4": ...,
    # International Terminal A
    "A1": ..., "A2": ..., "A3": ..., "A4": ...,
    # Terminal 1 - B
    "B1": ..., "B2": ..., "B3": ..., "B4": ..., "B5": ...,
    # Terminal 1 - C
    "C1": ..., "C2": ..., "C3": ..., "C4": ...,
    # Terminal 2 - D
    "D1": ..., "D2": ..., "D3": ..., "D4": ..., "D5": ...,
    # Terminal 3 - E
    "E1": ..., "E2": ..., "E3": ..., "E4": ...,
    # Terminal 3 - F
    "F1": ..., "F2": ..., "F3": ..., "F4": ...,
}
```

---

### Task 6: Rebalance phase distribution for 100 flights (fallback.py)

**File:** `src/ingestion/fallback.py` lines 2293-2315

**Current distribution logic** fills ENROUTE for most new flights. At 100 flights with realistic turnarounds:
- ~35-40 parked (35-45 min turnaround)
- ~8 approaching/landing
- ~6-8 taxiing (arrival + departure)
- ~6-8 pushback/takeoff/departing
- ~40-45 enroute (buffer, holding, in/outbound)

**Changes:**
1. Scale `max_parked` to 80% of gate count (not 100%)
2. Increase taxi weights: `taxi_in_weight = 0.08`, `taxi_out_weight = 0.08`
3. Allow more approach: `approach_weight = 0.15 if approach_count < 8 else 0.0`
4. Add departing weight: `departing_weight = 0.08`

---

### Task 7: Update API default and frontend (routes.py, FlightContext)

**File:** `app/backend/api/routes.py` line 90

**Change default from 50 to 100:**
```python
count: int = Query(default=100, ge=1, le=500, description="Number of flights"),
```

**File:** `app/backend/services/flight_service.py` line 74
```python
async def get_flights(self, count: int = 100) -> FlightListResponse:
```

**Frontend:** Check if any hardcoded `count=50` exists in fetch calls or WebSocket.

---

### Task 8: Gate cooldown realism (fallback.py)

**File:** `src/ingestion/fallback.py` line 1058

**Current:** 60s cooldown after gate release.

**Change:** 300s (5 min) — time for ground crew to reset jetbridge, clean FOD, reposition equipment.
```python
_gate_states[gate].available_at = time.time() + 300  # 5 min cooldown
```

---

## Verification

1. Run `uv run pytest tests/ -v` — all existing tests pass
2. Start local dev server (`./dev.sh`) with `count=100`
3. Verify:
   - 100 flights visible in 2D and 3D views
   - No flights stuck waiting for gates indefinitely
   - Arrivals use 28L, departures use 28R
   - Smooth 2s WebSocket updates (no lag)
   - Approach queue doesn't back up excessively
   - Phase distribution looks balanced (not all ENROUTE)
4. Monitor browser DevTools: WebSocket message size < 50KB per delta, < 150KB initial

## Estimated Scope

- **Files modified:** 4 (`fallback.py`, `websocket.py`, `routes.py`, `flight_service.py`)
- **Lines changed:** ~200-300
- **Risk:** Low — all changes are backward-compatible, simulation logic unchanged

# Fix 4 P1 UX Issues — Implementation Plan

## Context

Post-deployment UX re-audit at LSGG/EGLL/KJFK found 4 high-priority issues. All stem from bugs in `src/ingestion/fallback.py` (flight spawning/phase logic) and `src/ingestion/schedule_generator.py` (airline scope filtering). The previous plan (Improvements 1–5) has been implemented and deployed.

---

## Fix 1: Rebalance arrival/departure ratio (P1)

**Problem:** 4:1 arrival/departure bias. Phase spawn weights in `fallback.py:3495-3510` give arrivals ~59% vs departures ~16%.

**Root cause:** `fallback.py:3495-3502` — spawn weights:
- ENROUTE: ~0.36 (arriving)
- APPROACHING: 0.15 (arriving)
- TAXI_TO_GATE: 0.08 (arriving)
- TAXI_TO_RUNWAY: 0.08 (departing)
- DEPARTING: 0.08 (departing)
- PARKED: 0.25 (neutral)

Arriving total = 0.59, departing total = 0.16 → 3.7:1 ratio.

**File:** `src/ingestion/fallback.py` (~line 3495-3510)

**Fix:** Rebalance weights to ~45/45/10 (arrival/departure/parked):

```python
approach_weight = 0.10 if approach_count < MAX_APPROACH_AIRCRAFT else 0.0
parked_weight = 0.12 if parked_count < max_parked else 0.0
taxi_in_weight = 0.05 if taxi_count < 6 else 0.0
taxi_out_weight = 0.08 if taxi_count < 6 else 0.0
departing_weight = 0.15

total_assigned = approach_weight + parked_weight + taxi_in_weight + taxi_out_weight + departing_weight
enroute_weight = max(0.0, 1.0 - total_assigned)
```

The real issue is ENROUTE is classified as "arriving" but should be split. Better approach:

1. Split ENROUTE into arriving-enroute and departing-enroute. At spawn, some ENROUTE flights are heading toward the airport (arriving) and some are heading away (departing). Currently ALL ENROUTE spawns are classified as arriving (line 3525).
2. New spawn weights as above.
3. In `_create_new_flight` for ENROUTE: When spawning an ENROUTE flight, decide if it's arriving or departing with 50/50 probability. Arriving ENROUTE flights get positioned inbound; departing ENROUTE flights get positioned outbound (already climbing/cruising away from airport). This is already partially handled by origin/dest assignment at line 3522-3548, but all ENROUTE are marked as `is_arriving=True` which sets `dest = local_iata`.
4. Specific code change at line 3504-3510: Add DEPARTING weight increase and split ENROUTE spawns:

```python
phase_weights = [
    (FlightPhase.ENROUTE, enroute_weight * 0.5),       # arriving enroute
    (FlightPhase.APPROACHING, approach_weight),
    (FlightPhase.PARKED, parked_weight),
    (FlightPhase.TAXI_TO_GATE, taxi_in_weight),
    (FlightPhase.TAXI_TO_RUNWAY, taxi_out_weight),
    (FlightPhase.DEPARTING, departing_weight),
    ("ENROUTE_DEPARTING", enroute_weight * 0.5),  # departing enroute (pseudo-phase)
]
```

Then handle the pseudo-phase: if selected is `"ENROUTE_DEPARTING"`, create as `FlightPhase.ENROUTE` but set `origin=local, dest=random`, and position the flight outbound (already climbing, altitude 15000-35000, heading away).

---

## Fix 2: No climbing phase visible (P1)

**Problem:** Departures jump from ground to cruising. No green "climbing" dots visible.

**Root cause:** Two compounding issues:
1. Low departure spawn rate (Fix 1 above) — only 16% of flights start as departures
2. Short phase duration — TAKEOFF lasts ~60s (lineup 3s + roll ~15s + rotate 3s + liftoff 5s + initial_climb ~10s), DEPARTING follows ~4 waypoints then transitions to ENROUTE. Total "climbing" window is ~90-120s.
3. No ENROUTE flights spawned as departing — they all start as arrivals (Fix 1 addresses this too)

**File:** `src/ingestion/fallback.py`

**Fix:** Two changes beyond Fix 1's spawn rebalancing:

**a.** Extend DEPARTING phase duration (~line 3195-3218): Add more departure waypoints or extend the climb-out altitude ceiling. Currently DEPARTING transitions to ENROUTE after following `_get_departure_waypoints()` (~4 waypoints). Extend by raising the altitude threshold before ENROUTE transition. After the waypoints are exhausted, continue climbing to FL180 (18,000ft) before transitioning:

```python
# After line 3213 (waypoints exhausted):
else:
    # Continue climbing toward cruise altitude before switching to ENROUTE
    if state.altitude < 18000:
        state.velocity = min(state.velocity + 2 * dt, 350)
        state.vertical_rate = 2000
        state.altitude += 2000 / 60.0 * dt
        # Continue on departure heading
        speed_deg = state.velocity * _KTS_TO_DEG_PER_SEC * dt
        state.latitude += math.cos(math.radians(state.heading)) * speed_deg
        state.longitude += math.sin(math.radians(state.heading)) * speed_deg / math.cos(math.radians(state.latitude))
    else:
        # NOW switch to ENROUTE
        emit_phase_transition(...)
        _set_phase(state, FlightPhase.ENROUTE)
```

**b.** Spawn departing ENROUTE flights at mid-climb altitude (from Fix 1): These flights appear at 10,000-25,000ft heading away from airport with positive vertical rate, mapped to "climbing" phase name until they reach cruise altitude.

---

## Fix 3: EZY (EasyJet) filtered out at Geneva (P1)

**Problem:** EZY is 20% in GVA profile but 0% in actual flights.

**Root cause:** `fallback.py:3472-3481` — After selecting airline from profile (line 3440-3443), the code validates scope via `schedule_generator.AIRLINES` dict. EZY has `scope: "regional_eu"`. Line 3477 checks:

```python
if _scope == "regional_eu" and not _is_international_airport(local_iata):
    prefix = random.choice(["UAL", "DAL", "AAL", "UAE", "AFR", "CPA"])
```

`_is_international_airport()` (line 2200) checks `iata in INTERNATIONAL_AIRPORTS` which is only 10 airports: `["LHR", "CDG", "FRA", "AMS", "HKG", "NRT", "SIN", "SYD", "DXB", "ICN"]`. GVA is not in this list, so EZY gets replaced with US carriers.

**File:** `src/ingestion/fallback.py` (~line 3464-3481)

**Fix:** The scope validation is wrong — it should not override profile-selected airlines. If the profile explicitly includes EZY for GVA, the profile is authoritative.

**Option A (recommended):** Skip scope validation entirely when airline came from a calibrated profile. The profile IS the source of truth for which airlines operate at that airport.

```python
# Line 3440-3443: track whether airline came from profile
_from_profile = False
if _profile and _profile.airline_shares:
    _codes = list(_profile.airline_shares.keys())
    _weights = list(_profile.airline_shares.values())
    prefix = random.choices(_codes, weights=_weights, k=1)[0]
    _from_profile = True
else:
    prefix = random.choice(CALLSIGN_PREFIXES)

# ... OTH replacement ...

# Only validate scope for non-profile airlines
if not _from_profile:
    # existing scope validation at lines 3452-3481
    ...
```

**Option B:** Expand `INTERNATIONAL_AIRPORTS` to include all non-US airports. Less clean — the real fix is Option A.

---

## Fix 4: Expose 9 flight phases to frontend (P1)

**Problem:** Frontend only sees 4 phases (ground/climbing/descending/cruising). Can't distinguish taxi from parked, landing from descending enroute.

**Root cause:** `_get_flight_phase_name()` at `fallback.py:3375` collapses 9 phases to 4.

**Files:**
- `src/ingestion/fallback.py` — expose raw phase names
- `app/frontend/src/types/flight.ts` — expand `flight_phase` union type
- `app/frontend/src/components/Map/FlightMarker.tsx` — add colors for new phases
- `app/frontend/src/components/FlightDetail/FlightDetail.tsx` — add labels/colors
- `app/frontend/src/components/Header/Header.tsx` — update legend
- `app/frontend/src/hooks/useSimulationReplay.ts` — update `mapPhase()`

**Fix:**

### a. Backend: Change `_get_flight_phase_name()` to return fine-grained names:

```python
def _get_flight_phase_name(phase: FlightPhase) -> str:
    phase_map = {
        FlightPhase.APPROACHING: "approaching",
        FlightPhase.LANDING: "landing",
        FlightPhase.TAXI_TO_GATE: "taxi_in",
        FlightPhase.PARKED: "parked",
        FlightPhase.PUSHBACK: "pushback",
        FlightPhase.TAXI_TO_RUNWAY: "taxi_out",
        FlightPhase.TAKEOFF: "takeoff",
        FlightPhase.DEPARTING: "departing",
        FlightPhase.ENROUTE: "enroute",
    }
    return phase_map.get(phase, "parked")
```

### b. Frontend type (`flight.ts:13`):

```typescript
flight_phase: "parked" | "pushback" | "taxi_out" | "takeoff" | "departing" | "enroute" | "approaching" | "landing" | "taxi_in"
  // Backward compat aliases handled in parsing
  | "ground" | "climbing" | "descending" | "cruising";
```

### c. Phase colors — 9 distinct colors grouped by category:

```typescript
const phaseColors = {
  // Ground (gray family)
  parked: '#6b7280',      // gray-500
  pushback: '#9ca3af',    // gray-400
  taxi_out: '#a8a29e',    // stone-400
  taxi_in: '#a8a29e',     // stone-400
  // Climbing (green family)
  takeoff: '#16a34a',     // green-600
  departing: '#22c55e',   // green-500
  // Descending (orange family)
  approaching: '#f97316', // orange-500
  landing: '#ea580c',     // orange-600
  // Cruise
  enroute: '#3b82f6',     // blue-500
  // Legacy aliases
  ground: '#6b7280',
  climbing: '#22c55e',
  descending: '#f97316',
  cruising: '#3b82f6',
};
```

### d. Header legend — show 9 phases grouped:

```
Ground: Parked | Pushback | Taxi
Departure: Takeoff | Departing
Arrival: Approaching | Landing
Cruise: Enroute
```

### e. Update all test mocks referencing old 4-phase names to use new names or add legacy mapping in the flight data parser.

### f. Backward compatibility:

Add a normalizer in the flight data parsing layer that maps old 4-phase names to new names for any cached/in-flight data:

```typescript
function normalizePhase(phase: string): Flight['flight_phase'] {
  const legacy: Record<string, Flight['flight_phase']> = {
    ground: 'parked', climbing: 'departing', descending: 'approaching', cruising: 'enroute'
  };
  return legacy[phase] ?? phase as Flight['flight_phase'];
}
```

---

## Files Summary

| File | Fixes |
|------|-------|
| `src/ingestion/fallback.py` | #1 (spawn weights), #2 (extend departing), #3 (skip scope validation for profile airlines), #4 (expose 9 phases) |
| `app/frontend/src/types/flight.ts` | #4 (expand phase type) |
| `app/frontend/src/components/Map/FlightMarker.tsx` | #4 (9 phase colors) |
| `app/frontend/src/components/FlightDetail/FlightDetail.tsx` | #4 (phase labels/colors) |
| `app/frontend/src/components/Header/Header.tsx` | #4 (legend update) |
| `app/frontend/src/hooks/useSimulationReplay.ts` | #4 (mapPhase update) |
| Multiple test files | #4 (update phase string references) |

---

## Verification

1. `uv run pytest tests/ -v --ignore=tests/test_dlt.py` — full Python test suite
2. `cd app/frontend && npm test -- --run` — full frontend test suite
3. Deploy: `cd app/frontend && npm run build && databricks bundle deploy --target dev`
4. Manual UX re-audit:
   - At any airport: count arrivals vs departures → should be ~50/50
   - Watch departing flights → should see green "takeoff"/"departing" dots climbing
   - Switch to LSGG → verify EZY flights appear (~20% of traffic)
   - Click flights → verify 9 distinct phase labels (parked, pushback, taxi_out, takeoff, departing, enroute, approaching, landing, taxi_in)

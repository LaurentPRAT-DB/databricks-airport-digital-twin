# Phase 26: Flight Dynamics — Go-Arounds, Diversions, and Stuck-Flight Fixes

## Goal

Fix three critical flight dynamics issues that prevent realistic simulation behavior: zero go-arounds despite severe weather, no airborne diversions when runways close, and 18% phantom flights stuck in APPROACHING phase forever.

## Status: Plan — Not Started

## Prerequisites: Phase 25 (Metrics Accuracy) must be complete.

---

## Context

Post-Phase 25 metrics accuracy, three flight dynamics issues remain:

1. **Zero go-arounds** across all 7 simulations despite LIFR/microbursts (real-world: 3-15%)
2. **No airborne diversions** when both runways close — airborne flights freeze/vanish
3. **18% of SFO arrivals phantom** — stuck in APPROACHING phase forever, never land or get cleaned up

### Root Causes from Code Analysis

- **No go-around code path** exists in the state machine (`fallback.py`)
- **No diversion routing** or alternate airport logic exists
- The APPROACHING → LANDING transition at line 1894 requires `_is_runway_clear("28R")`. When runway is blocked, flights orbit (`heading += 5*dt`) but their position keeps drifting. The 900s force-advance timer in `engine.py:628` sets phase to LANDING without calling `_occupy_runway()`, causing malformed state
- Engine only removes flights via `phase_progress == -1.0` (ENROUTE exit). No cleanup path for perpetually-stuck approaching flights

---

## Tasks

### Task 1: Fix Stuck-Approaching Flights — Do First

#### A. Fix orbit drift in `fallback.py` line 1904-1908

**Current:** When runway is busy after all waypoints exhausted, flights orbit with `heading += 5*dt` but the position update from the waypoint-following code above still moves them. They drift away.

**Fix:** Replace the simple orbit with proper FAA racetrack holding pattern (same code already used for ENROUTE holding at lines 2342-2367):

```python
# In the `else` block after line 1893 "Transition to landing only if runway is clear"
else:
    # Runway busy — FAA standard racetrack holding pattern
    HOLDING_LEG_SECONDS = 60.0
    STANDARD_RATE_DEG_S = 3.0
    state.holding_phase_time += dt
    if state.holding_inbound:
        center = get_airport_center()
        state.heading = _calculate_heading(
            (state.latitude, state.longitude), center
        )
        if state.holding_phase_time >= HOLDING_LEG_SECONDS:
            state.holding_phase_time = 0.0
            state.holding_inbound = False
    else:
        if state.holding_phase_time < 30.0:
            state.heading = (state.heading + STANDARD_RATE_DEG_S * dt) % 360
        elif state.holding_phase_time < 30.0 + HOLDING_LEG_SECONDS:
            pass  # Straight outbound leg
        else:
            state.holding_phase_time = 0.0
            state.holding_inbound = True
    state.velocity = max(180, state.velocity)  # Maintain approach speed
    # Move along current heading (not toward waypoint)
    speed_deg = 0.001  # ~0.06 NM per tick
    state.latitude += speed_deg * math.cos(math.radians(state.heading))
    state.longitude += speed_deg * math.sin(math.radians(state.heading))
```

#### B. Fix `_force_advance()` for APPROACHING in `engine.py` line 628-632

**Current:** Sets `phase = LANDING` and `waypoint_index = 0` but does NOT call `_occupy_runway()`. Flight enters LANDING without runway lock — can collide with another flight.

**Fix:**
```python
elif state.phase == FlightPhase.APPROACHING:
    if _is_runway_clear("28R"):
        state.phase = FlightPhase.LANDING
        state.waypoint_index = 0
        _occupy_runway(icao24, "28R")
        self._phase_time[icao24] = ("landing", 0.0)
    else:
        # Runway still blocked after 15 min — will be handled by go-around/diversion logic
        # Reset timer to check again in 5 min
        self._phase_time[icao24] = ("approaching", 600.0)
```

---

### Task 2: Go-Around Logic

#### A. New field in `FlightState` (`fallback.py` line 955)

```python
go_around_count: int = 0
```

#### B. Store wind gusts in `CapacityManager` (`capacity.py`)

In `apply_weather()`, add:
```python
self._wind_gusts_kt = wind_gusts_kt
```

New method:
```python
def go_around_probability(self) -> float:
    """Weather-dependent go-around probability per approach attempt."""
    base = {"VFR": 0.005, "MVFR": 0.015, "IFR": 0.03, "LIFR": 0.05}
    prob = base.get(self.current_category, 0.005)
    gusts = getattr(self, '_wind_gusts_kt', None)
    if gusts:
        if gusts > 50:
            prob += 0.05
        elif gusts > 35:
            prob += 0.03
    if not self.active_runways:
        prob = 1.0  # All runways closed = guaranteed go-around
    return min(prob, 1.0)
```

#### C. Go-around check in `engine.py:_update_all_flights()`

After the phase transition detection block (line 558), add:

```python
# Go-around check: APPROACHING → LANDING transition
if (old_phase == FlightPhase.APPROACHING
        and new_phase == FlightPhase.LANDING
        and random.random() < self.capacity.go_around_probability()):
    _release_runway(icao24, "28R")
    new_state.phase = FlightPhase.APPROACHING
    new_state.waypoint_index = 0
    new_state.altitude = 2000
    new_state.velocity = 200
    new_state.vertical_rate = 1500
    new_state.go_around_count += 1
    new_state.holding_phase_time = 0.0
    new_state.holding_inbound = True
    self.recorder.record_scenario_event(
        self.sim_time, "go_around",
        f"{state.callsign} go-around #{new_state.go_around_count} ({self.capacity.current_category})",
        {"callsign": state.callsign, "icao24": icao24,
         "attempt": new_state.go_around_count, "weather": self.capacity.current_category},
    )
    if new_state.go_around_count >= 2:
        self._divert_flight(icao24, new_state)
```

---

### Task 3: Airborne Diversions During Closures

#### A. Alternate airports table in `engine.py`

```python
ALTERNATE_AIRPORTS: dict[str, list[str]] = {
    "SFO": ["OAK", "SJC"],
    "JFK": ["EWR", "LGA"],
    "LHR": ["LGW", "STN"],
    "NRT": ["HND"],
    "DXB": ["AUH"],
    "GRU": ["VCP"],
    "SYD": ["MEL", "BNE"],
}
```

#### B. New method `_divert_flight()` in `SimulationEngine`

```python
def _divert_flight(self, icao24: str, state: FlightState) -> None:
    alternates = ALTERNATE_AIRPORTS.get(self.config.airport, [])
    alt_name = random.choice(alternates) if alternates else "alternate"
    if state.assigned_gate:
        _release_gate(icao24, state.assigned_gate)
        state.assigned_gate = None
    state.phase = FlightPhase.ENROUTE
    state.destination_airport = alt_name
    state.origin_airport = None
    state.altitude = max(state.altitude, 3000)
    state.velocity = 250
    state.vertical_rate = 1500
    state.go_around_count = 0
    if alt_name in AIRPORT_COORDINATES:
        from src.ingestion.fallback import _bearing_to_airport
        state.heading = _bearing_to_airport(alt_name)
    self.recorder.record_scenario_event(
        self.sim_time, "diversion",
        f"{state.callsign} diverted to {alt_name}",
        {"callsign": state.callsign, "icao24": icao24, "alternate": alt_name,
         "reason": "runway_closure" if not self.capacity.active_runways else "go_around_limit"},
    )
```

#### C. Runway-closure diversion sweep in `_update_all_flights()`

After the main flight update loop, before the ENROUTE cleanup:

```python
# Divert airborne flights if all runways closed
if not self.capacity.active_runways:
    for icao24 in list(_flight_states.keys()):
        state = _flight_states[icao24]
        if state.phase == FlightPhase.APPROACHING:
            self._divert_flight(icao24, state)
        elif (state.phase == FlightPhase.ENROUTE
              and state.origin_airport and not state.destination_airport):
            self._divert_flight(icao24, state)
```

---

### Task 4: Update Metrics and CLI

#### `recorder.py` — add to `compute_summary()`:

```python
"total_go_arounds": sum(1 for e in self.scenario_events if e.get("event_type") == "go_around"),
"total_diversions": sum(1 for e in self.scenario_events if e.get("event_type") == "diversion"),
```

#### `cli.py` — add after holdings line:

```python
print(f"  Go-arounds:             {summary.get('total_go_arounds', 0)}")
print(f"  Diversions:             {summary.get('total_diversions', 0)}")
```

---

### Task 5: Tests

**File:** `tests/test_scenario.py` — new `TestFlightDynamics` class

| Test | What it verifies |
|------|------------------|
| `test_go_around_probability_increases_with_weather` | LIFR > IFR > MVFR > VFR |
| `test_go_around_probability_gusts_additive` | Gusts >35kt add to base probability |
| `test_go_around_probability_all_runways_closed` | Returns 1.0 when no active runways |
| `test_go_around_in_bad_weather` | Short LIFR sim → `total_go_arounds > 0` |
| `test_diversion_on_all_runways_closed` | Close both runways → APPROACHING flights diverted |
| `test_diversion_releases_gate` | Diverted flight releases pre-assigned gate |
| `test_diversion_after_two_go_arounds` | Flight with 2 go-arounds becomes diverted |
| `test_force_advance_approaching_checks_runway` | Fixed force-advance respects runway occupancy |

---

## Files Modified

| File | Change |
|------|--------|
| `src/ingestion/fallback.py` | Add `go_around_count` field; replace orbit with holding pattern |
| `src/simulation/engine.py` | Go-around check, `_divert_flight()`, diversion sweep, fix `_force_advance()`, `ALTERNATE_AIRPORTS` |
| `src/simulation/capacity.py` | Store `_wind_gusts_kt`, add `go_around_probability()` |
| `src/simulation/recorder.py` | Add `total_go_arounds`, `total_diversions` to summary |
| `src/simulation/cli.py` | Print go-around and diversion counts |
| `tests/test_scenario.py` | New `TestFlightDynamics` class (~8 tests) |

---

## Execution Order

1. Fix stuck-approaching in `fallback.py` + `engine.py`
2. Add `go_around_count` to `FlightState`
3. Add `go_around_probability()` to `CapacityManager`
4. Add go-around check in engine
5. Add `ALTERNATE_AIRPORTS` + `_divert_flight()` + diversion sweep
6. Update recorder + CLI
7. Add tests
8. Run: `uv run pytest tests/test_scenario.py tests/test_simulation.py -v`

---

## Verification

1. `uv run pytest tests/test_scenario.py tests/test_simulation.py -v` — all pass
2. **Re-run SFO:** expect `total_go_arounds > 0`, zero stuck-approaching phantoms
3. **Re-run JFK:** expect `total_diversions > 0` during 3h runway closure
4. **Compare go-around rates:** LIFR airports > VFR airports

---

## Expected Outcomes

| Metric | Before (broken) | After (fixed) |
|--------|-----------------|---------------|
| Go-arounds (SFO thunderstorm) | 0 | 5-15 |
| Go-arounds (JFK winter storm) | 0 | 20-40 |
| Diversions (JFK 3h closure) | 0 | 10-25 |
| Phantom stuck flights | ~18% of arrivals | 0% |
| Approach holding patterns | Drifting orbits | Proper FAA racetrack |

## Estimated Scope

- **Lines changed:** ~200 new code + ~120 tests
- **Risk:** Medium — go-around probability tuning may need adjustment after observing simulation runs. Diversion logic must not create orphaned flights (ensure diverted flights eventually exit via ENROUTE removal).

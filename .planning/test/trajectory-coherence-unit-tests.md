# Trajectory Coherence Unit Tests

## Context

The simulation generates position-by-position flight trajectories through all ground and air phases (approaching -> landing -> taxi_to_gate -> parked -> pushback -> taxi_to_runway -> takeoff -> departing -> enroute). There are no tests that record the full position trace of individual flights and validate it against aviation procedure rules. The existing `test_flight_ops_validation.py` validates aggregate statistics (turnaround times, throughput) but doesn't check per-flight trajectory coherence — e.g., "did the aircraft actually fly the runway heading during takeoff?" or "did altitude decrease monotonically on approach?".

This adds a new test file that runs small, deterministic simulations (5-10 flights, 2h) for a handful of airports covering edge cases, captures every position snapshot, and runs per-flight trajectory coherence checks against aviation rules.

---

## Airports to Cover

| Airport | IATA | Edge Case |
|---------|------|-----------|
| San Francisco | SFO | Parallel runways, over-water approach, US calibration |
| London Heathrow | LHR | Single-runway ops alternating, dense taxiway network |
| Haneda | HND | Crosswind runways, island airport, tight taxi |
| Denver | DEN | 6 runways, wide-spaced, long taxi distances |

These cover: multi-runway, single-runway, US/Europe/Asia, various taxiway complexity.

---

## Test Structure

**New file:** `tests/test_trajectory_coherence.py`

### Reuse existing infrastructure

- `SimulationConfig` from `src/simulation/config.py`
- `SimulationEngine` from `src/simulation/engine.py` (`.run()` returns `SimulationRecorder`)
- `SimulationRecorder` — has `.position_snapshots` (every position) and `.phase_transitions` (phase changes)
- Pattern from `test_flight_ops_validation.py`: module-scoped fixture runs sim once, all tests share it

### Fixture design

```python
@pytest.fixture(scope="module", params=["SFO", "LHR", "HND", "DEN"])
def sim(request):
    """Run a small 2h sim with 5 arrivals + 5 departures per airport."""
    config = SimulationConfig(
        airport=request.param,
        arrivals=5,
        departures=5,
        duration_hours=2.0,
        time_step_seconds=2.0,
        seed=42,
    )
    engine = SimulationEngine(config)
    recorder = engine.run()
    return recorder, config
```

### Helper: extract per-flight trajectory

```python
def _extract_flight_traces(recorder) -> dict[str, list[dict]]:
    """Group position_snapshots by icao24, sorted by time."""
    traces = defaultdict(list)
    for snap in recorder.position_snapshots:
        traces[snap["icao24"]].append(snap)
    for icao24 in traces:
        traces[icao24].sort(key=lambda p: p["time"])
    return dict(traces)
```

---

## The Coherence Checks (one test class per rule)

### T01 — Phase sequence validity

- For each flight, extract the sequence of phases from position snapshots
- Check that phase transitions follow the valid graph:
  - approaching -> landing -> taxi_to_gate -> parked -> pushback -> taxi_to_runway -> takeoff -> departing -> enroute
  - Arrivals start at approaching, departures start at parked
  - No skipped phases (e.g., approaching -> parked is invalid)
  - No backward transitions (e.g., takeoff -> taxi_to_runway)

### T02 — Approach altitude decreases

- For positions in approaching phase, altitude should generally decrease
- Allow small bumps (turbulence jitter) but overall trend must be downward
- At phase end (transition to landing), altitude should be < 500 ft

### T03 — Landing roll on runway

- Positions in landing phase should be on or very near the runway
- Heading should be within +/-10 deg of a known runway heading for that airport
- Speed should decrease (deceleration)
- Altitude should be ~0

### T04 — Taxi speed limits

- All positions in taxi_to_gate and taxi_to_runway phases: speed < 35 knots
- Altitude = 0 (on ground)
- Aircraft should be moving (not stuck at same position for > 30 consecutive seconds, unless holding)

### T05 — Parked aircraft stationary

- All parked phase positions: speed ~= 0 (< 2 knots)
- Position should not drift (lat/lon delta < 0.0001 deg between consecutive points)
- Must have an assigned gate

### T06 — Takeoff roll acceleration

- Positions in takeoff phase: speed should increase
- Heading should be within +/-10 deg of a runway heading
- Altitude should start at 0 and increase after liftoff

### T07 — Departure climb

- Positions in departing phase: altitude should increase
- Vertical rate should be positive
- Speed should be within realistic range (150-350 knots)

### T08 — No position teleportation

- Between consecutive position snapshots, the distance moved should be physically possible given the speed and time delta
- Max allowed: `speed_knots * dt_seconds * 1.2` (20% tolerance for interpolation)
- No NaN or None in latitude/longitude/altitude

### T09 — Heading consistency

- Heading should change smoothly (< 30 deg per time step during straight segments)
- Exception: taxi turns can be sharper (< 90 deg per step)

### T10 — Complete lifecycle coverage

- At least one flight per sim should complete the full arrival cycle: approaching -> landing -> taxi_to_gate -> parked
- At least one flight should complete the departure cycle: parked -> pushback -> taxi_to_runway -> takeoff -> departing

---

## Files to Create/Modify

| File | Action |
|------|--------|
| `tests/test_trajectory_coherence.py` | New — all 10 test classes + fixtures + helpers |

No existing files need modification.

---

## Verification

```bash
# Run just the new test file
uv run pytest tests/test_trajectory_coherence.py -v

# Run with a single airport to debug
uv run pytest tests/test_trajectory_coherence.py -v -k "SFO"

# Run full suite to confirm no regressions
uv run pytest tests/ -v
```

Expected: 10 test classes x 4 airports = ~40 test cases. Some may skip if the 2h sim doesn't produce enough flights for a particular phase. The sim runs are ~5-10 seconds each (2h sim, 5+5 flights, 2s timestep = 3,600 ticks).

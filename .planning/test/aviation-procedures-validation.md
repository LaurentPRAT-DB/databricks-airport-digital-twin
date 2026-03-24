# Plan: Aviation Procedure Rule Validation Tests

## Context

The simulation implements specific aviation procedure rules (FAA/ICAO standards) as constants in `src/ingestion/fallback.py`. Existing tests validate these rules in isolation (unit tests for constants/functions) or check general trajectory coherence (T01-T10). No test validates that a full multi-airport simulation actually enforces these rules end-to-end — i.e., recording complete flight traces and checking each position against the procedure rules the sim claims to implement.

This new test file runs small sims across multiple airports, records every position snapshot, and validates per-flight traces against the specific aviation constants defined in the codebase.

## What's Already Tested (DO NOT duplicate)

| File | What it tests |
|---|---|
| `test_trajectory_coherence.py` | T01-T10: phase sequence, approach altitude trend, taxi speed < 35kts, parked stationary, heading smoothness, lifecycle coverage |
| `test_aircraft_separation.py` | Wake category mappings, separation NM values, approach/taxi separation functions (unit tests) |
| `test_takeoff_physics.py` | V-speed progression, subphase transitions, runway centerline, altitude transitions, departure separation timing |
| `test_flight_realism.py` | Same-direction ops, departure waypoints, approach glideslope statics, Vref table completeness |
| `test_flight_ops_validation.py` | O01-O04: aggregate turnaround, runway throughput, gate utilization, taxi times vs BTS |

## What This New File Tests (NEW — per-flight trace validation against procedure rules)

New file: `tests/test_aviation_procedures.py`

### Fixture: same pattern as `test_trajectory_coherence.py`

```python
@pytest.fixture(scope="module", params=["SFO", "LHR", "HND", "DEN"])
def sim(request):
    config = SimulationConfig(
        airport=request.param, arrivals=8, departures=8,
        duration_hours=3.0, time_step_seconds=2.0, seed=42,
    )
    engine = SimulationEngine(config)
    recorder = engine.run()
    return recorder, config
```

Reuse same helpers: `_extract_flight_traces`, `_phase_positions`, `_haversine_nm`, `_angle_diff`, `_time_delta_seconds`.

## Test Classes (P01-P10)

### P01 — 250kt Speed Below FL100 (14 CFR 91.117)
- For every position snapshot with altitude < 10,000 ft and airborne: velocity ≤ 260 kts (250 + 10kt tolerance)
- Exception: landing/takeoff phases (speed is transitional)
- Validates: `MAX_SPEED_BELOW_FL100_KTS = 250` from `fallback.py:661`

### P02 — Approach Speed Near Vref (stabilized approach)
- For positions in `approaching` phase with altitude < 3000 ft: speed should be within Vref ± 40 kts
- Import and use `VREF_SPEEDS` and `_DEFAULT_VREF` from `fallback.py:672-680`
- Validates: `STABILIZED_MAX_SPEED_OVER_VREF = 30` from `fallback.py:667`

### P03 — Taxi Speed Compliance (ICAO Doc 9157)
- Taxi phases: speed ≤ 35 kts (straight + margin)
- Pushback phase: speed ≤ 5 kts
- Validates: `TAXI_SPEED_STRAIGHT_KTS=25`, `TAXI_SPEED_PUSHBACK_KTS=3` from `fallback.py:656-659`

### P04 — Wake Turbulence Approach Separation
- For consecutive aircraft on approach (same sim), measure distance between them
- Distance should meet or exceed `WAKE_SEPARATION_NM` for their aircraft type pair
- Uses `WAKE_CATEGORY` and `WAKE_SEPARATION_NM` from `fallback.py:628-650`
- Tolerance: 80% of required (sim may compress slightly due to timing)

### P05 — Departure Wake Separation Timing
- For consecutive takeoff events on the same runway, time gap should meet `DEPARTURE_SEPARATION_S`
- Uses `DEPARTURE_SEPARATION_S` from `fallback.py:745-751`
- Tolerance: 80% of required

### P06 — Takeoff V-Speed Envelope
- From `phase_transitions` (takeoff phase): initial speed should be near 0
- From departing phase positions: speed should be ≥ V2 for the aircraft type
- Uses `TAKEOFF_PERFORMANCE` from `fallback.py:721-740`
- Validates V2 speed is reached before departing phase

### P07 — ILS Decision Height Transition
- Approach → landing transition should occur near `DECISION_HEIGHT_FT = 200` ft
- Check from `phase_transitions` where `to_phase == "landing"`: altitude should be < 1500 ft
- Validates: `DECISION_HEIGHT_FT` from `fallback.py:664`

### P08 — Go-Around Altitude Gain
- If a flight has `go_around_count > 0` (visible as approach→approaching or approach→enroute transitions)
- After go-around, altitude should increase (missed approach climb)
- Validates go-around procedure produces positive climb

### P09 — Ground Speed Zero When Parked
- All parked positions: velocity < 2 kts AND `on_ground == True`
- Validates the sim correctly stops aircraft at gates

### P10 — Departure Climb Gradient
- From departing phase positions: check that altitude gain / distance traveled meets minimum climb gradient
- FAA requires ~200 ft/NM for obstacle clearance
- Check average climb gradient across departure positions exceeds 150 ft/NM (with tolerance)

## Aviation Constants to Import

From `src/ingestion/fallback.py`:
- `VREF_SPEEDS`, `_DEFAULT_VREF` (line 672-680)
- `MAX_SPEED_BELOW_FL100_KTS` (line 661)
- `WAKE_CATEGORY`, `WAKE_SEPARATION_NM`, `DEFAULT_SEPARATION_NM` (lines 628-650)
- `DEPARTURE_SEPARATION_S`, `DEFAULT_DEPARTURE_SEPARATION_S` (lines 745-751)
- `TAKEOFF_PERFORMANCE`, `_DEFAULT_TAKEOFF_PERF` (lines 720-741)
- `TAXI_SPEED_STRAIGHT_KTS`, `TAXI_SPEED_PUSHBACK_KTS` (lines 656-659)
- `DECISION_HEIGHT_FT` (line 664)
- `STABILIZED_MAX_SPEED_OVER_VREF` (line 667)
- `NM_TO_DEG` (line 684)

## Files

| File | Action |
|---|---|
| `tests/test_aviation_procedures.py` | New — P01-P10 test classes + fixtures + helpers |

No existing files modified.

## Verification

```bash
uv run pytest tests/test_aviation_procedures.py -v
uv run pytest tests/test_aviation_procedures.py -v -k "SFO"
uv run pytest tests/ -v  # full suite regression check
```

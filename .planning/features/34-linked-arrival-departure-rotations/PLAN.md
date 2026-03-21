# Plan: Linked Arrival-Departure Rotations in Schedule Generation

## Context

`_generate_schedule()` in `engine.py` creates arrivals and departures as completely independent flights. Departures get random times within hourly slots and spawn directly at gates. There's no aircraft rotation — an arriving plane doesn't become a departing plane.

This causes unrealistic behavior: all departures for an hour cluster at random times unrelated to arrivals. At smaller airports, they may all fire nearly simultaneously. Real airports have departures causally linked to prior arrivals through turnaround time.

**Fix:** Generate departures as linked rotations from arrivals. Aircraft arrives → turnaround (45-90 min) → departs. Only "overnight parked" aircraft get independent departure times.

## File to modify

`src/simulation/engine.py` — `_generate_schedule()` (line 283)

Replace the current dual-loop (arrivals then departures independently) with a three-phase approach:

### Phase 1: Generate arrivals (same as today)

Distribute arrivals across hours using existing hourly weight logic. No change to arrival generation.

### Phase 2: Link departures to arrivals

For each arrival (up to `min(arrivals_count, departures_count)`):
```python
turnaround = get_turnaround_timing(aircraft_type)["total_minutes"]  # 45 or 90
jitter = random.uniform(-0.15, 0.15) * turnaround
dep_time = arrival_time + timedelta(minutes=turnaround + jitter)
```

The linked departure:
- Same `aircraft_type` and same `airline_code` (same physical aircraft, same airline rotation)
- New `flight_number` and new `destination` (return/onward flight)
- `delay_minutes` and `delay_code` generated independently (departure can have its own delay)
- `linked_arrival_idx` field for traceability (optional, informational)
- If `dep_time > end_time`: skip — aircraft stays parked past sim window

### Phase 3: Surplus independent departures

If `config.departures > linked_count`: generate surplus as overnight-parked aircraft.
- Schedule in the first 2 hours of the sim (early morning departures of planes that overnighted)
- Uses current independent generation logic (random airline, aircraft, destination)

## Existing functions reused (all already imported in engine.py)

- `get_turnaround_timing()` from `src/ml/gse_model.py` — turnaround duration by aircraft type
- `get_aircraft_category()` from `src/ml/gse_model.py` — narrow/wide classification
- `_select_destination()`, `_generate_flight_number()`, `_select_airline()`, `_select_aircraft()`, `_generate_delay()` from `schedule_generator.py`

## No changes needed to

- `fallback.py` — PARKED spawn logic unchanged (departures still appear at gate)
- `_spawn_scheduled_flights()` — still spawns by scheduled_time
- `config.py` — arrivals/departures counts stay as user controls
- Turnaround runtime factors (airline, weather, congestion) — applied at runtime in `_update_flight_state`, not at schedule time

## Verification

1. `uv run python -m src.simulation.cli --airport SFO --arrivals 20 --departures 20 --duration 4 --seed 42 --output simulation_output/test_rotation.json`
   - Check departures are staggered ~45-90 min after arrivals (not clustered)
2. Short 2h sim: `--arrivals 10 --departures 10 --duration 2` — most departures should fall in hour 2
3. Surplus test: `--arrivals 5 --departures 15` — 5 linked + 10 overnight-parked in first 2h
4. Run tests: `uv run pytest tests/ -q --ignore=tests/test_airport_persistence.py`

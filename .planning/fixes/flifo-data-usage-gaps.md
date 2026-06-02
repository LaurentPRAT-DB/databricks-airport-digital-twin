---
status: active
area: flifo
related:
  - .planning/features/flifo-integration.md
  - src/ingestion/flifo_mapper.py
  - src/ingestion/_generation.py
  - src/ingestion/_flight_lifecycle.py
---

# FLIFO Data — What It Provides vs What's Actually Used

## Field Usage Matrix

| Field | Source | Used? | Where? |
|-------|--------|-------|--------|
| flightNumber | FLIFO | YES | Callsign for spawning |
| airline (IATA/ICAO/name) | FLIFO | YES | Passed to schedule |
| origin/destination | FLIFO | YES | `_create_new_flight(origin=, destination=)` |
| gate | FLIFO | YES | `preferred_gate` in spawner |
| statusCode | FLIFO | YES | Maps to spawn phase |
| scheduledTime | FLIFO | YES | Spawn window timing |
| estimatedTime | FLIFO | NO | Synthesized from `holding_phase_time` |
| actualTime | FLIFO | NO | Derived from sim phase |
| delayMinutes | FLIFO | NO | Re-invented from hash/holding |
| delayCode | FLIFO | NO | Generic strings used |
| aircraft.icaoType | FLIFO | NO | Random selection by airline (`_get_aircraft_type_for_airline()`) |
| aircraft.registration | FLIFO | NO | Not stored in FlightState |
| terminal | FLIFO | NO | Not stored |
| baggageBelt | FLIFO | NO | Hash-derived (`hash(callsign) % 12 + 1`) |
| codeshares | FLIFO | NO | Not propagated to FlightState |
| data_source tag | mapper sets "flifo" | LOST | Replaced by "synthetic" in `get_flights_as_schedule` |

## Key Gaps (FLIFO data discarded/replaced)

1. **aircraft_type** — FLIFO tells us exact ICAO type (B738, A321, B77W). Instead, `_create_new_flight` calls `_get_aircraft_type_for_airline()` which randomly picks from fleet. Ground truth discarded.

2. **delay_minutes + delay_code** — FLIFO provides real delay info. Instead, `get_flights_as_schedule` re-invents delays from hash-deterministic logic or holding time. Real delay reason (weather, crew, technical) lost.

3. **estimated_time + actual_time** — FLIFO provides real ETAs. Instead, estimated is re-computed from synthetic delay, actual is `now.isoformat()` when status matches.

4. **registration** — tail number available from FLIFO, never stored in FlightState (no field for it).

5. **terminal** — FLIFO assigns terminal. Lost during spawning.

6. **baggageBelt** — FLIFO provides real belt assignment. Replaced by `hash(callsign) % 12 + 1`.

7. **data_source: "flifo"** — The mapper correctly marks records as FLIFO-sourced. But once spawned into sim, `get_flights_as_schedule()` always marks everything `"data_source": "synthetic"`. No way to distinguish ground-truth flights in FIDS.

## Architecture Issue

The merge logic in `schedule_service._get_merged_schedule` does:
1. Get live sim flights (always priority)
2. Get FLIFO background flights
3. Dedup — live sim wins over FLIFO

This means FLIFO ground-truth fields (delay, ETA, belt, terminal) are overwritten by synthetic approximations as soon as a flight spawns into the sim.

## Fix Priority

| Gap | Impact | Difficulty |
|-----|--------|-----------|
| aircraft_type | High (affects 3D model, separation, perf) | Low — pass through `_try_spawn_from_queue` |
| data_source tag | Medium (analytics, FIDS fidelity) | Low — preserve in FlightState |
| delay_minutes/code | Medium (FIDS accuracy) | Medium — store on FlightState, use in schedule export |
| baggageBelt | Low (cosmetic) | Low — pass through and store |
| estimated/actual time | Medium (FIDS accuracy) | Medium — store FLIFO times, prefer over synthetic |
| terminal | Low (display only) | Low — store and export |
| registration | Low (nice-to-have) | Low — add field to FlightState |

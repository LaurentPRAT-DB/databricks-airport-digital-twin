---
title: "FLIFO → Simulation Seeding"
status: complete
area: ingestion
priority: medium
related:
  - .planning/backlog/flifo-api-live-flight-data.md
  - .planning/backlog/flifo-mock-server.md
  - .planning/backlog/gate-baggage-data-feed-prep.md
---

# FLIFO → Simulation Seeding

## Context

Currently FLIFO and simulation are parallel, disconnected systems:
- Simulation spawns flights with random callsigns (UAL4521, DAL8843) and random origins/destinations
- FLIFO provides real schedule data (UA123 from LAX, gate B12, delayed 10min)
- FIDS merges both but they have different flight numbers — user sees "UA123 boarding" on FIDS but no UA123 on the map

**Goal:** When FLIFO is active, the simulation should spawn flights using FLIFO schedule data — real flight numbers, real origins/destinations, real aircraft types. The map and FIDS then show the same flights.

## Current Architecture

```
_spawn_flights_to_target()  ←  random callsigns, random phases
        ↓
_create_new_flight(icao24, callsign, phase, origin, destination)
        ↓
FlightState in _flight_states dict
        ↓
get_flights_as_schedule()  →  FIDS (live flight rows)
```

Key spawn function: `src/ingestion/_generation.py:368` — `_spawn_flights_to_target()`
- Picks airline prefix from profile or random CALLSIGN_PREFIXES
- Picks random flight number (100-9999)
- Picks random phase (weighted by current airport state)
- Picks origin/destination from `_pick_random_origin()`/`_pick_random_destination()`
- Calls `_create_new_flight(icao24, callsign, phase, origin, dest)`

## Design: Schedule Queue

Insert a schedule queue between FLIFO and the spawner. When FLIFO is active, upcoming flights are pre-loaded into a queue. The spawner consumes from this queue instead of generating random callsigns.

```
FLIFO service  →  ScheduleQueue (sorted by scheduled_time)
                        ↓
_spawn_flights_to_target() reads from queue
                        ↓
_create_new_flight(icao24, "UA123", APPROACHING, "LAX", "SFO")
```

## ScheduleQueue Design

```python
# src/ingestion/_schedule_queue.py

class ScheduleQueue:
    """Feeds FLIFO schedule data to the simulation spawner."""

    _arrivals: deque[dict]   # sorted by scheduled_time, upcoming arrivals
    _departures: deque[dict] # sorted by scheduled_time, upcoming departures
    _spawned: set[str]       # flight_numbers already in simulation
    _last_refresh: float     # time.time() of last FLIFO fetch

    def refresh(self, airport_iata: str) -> None:
        """Fetch from FLIFO service, populate queues. Called periodically."""

    def next_arrival(self) -> Optional[dict]:
        """Pop next arrival that's within spawn window and not already spawned."""

    def next_departure(self) -> Optional[dict]:
        """Pop next departure that's within spawn window and not already spawned."""

    def mark_spawned(self, flight_number: str) -> None:
        """Track that a flight has been spawned (avoid duplicates)."""
```

## Spawn Window Logic

Flights spawn when their scheduled_time is within a window relative to now:
- **Arrivals:** spawn when `scheduled_time - now < 45min` (gives time for approach)
- **Departures:** spawn when `scheduled_time - now < 30min` (enough for taxi-out)
- **Already-past flights** with status boarding/gate_closed spawn as PARKED

## Phase Mapping

FLIFO status → simulation spawn phase:

| FLIFO status | Spawn phase | Rationale |
|---|---|---|
| SC/ON/FE (>30min out) | Don't spawn yet | Too early |
| SC/ON (arrival, <45min) | APPROACHING | Start approach from origin direction |
| DL (arrival) | APPROACHING | Still approaching, just late |
| IA/AB | APPROACHING | In air = on approach |
| LN/TX | TAXI_TO_GATE | Already landed |
| AR/BG | PARKED | At gate |
| BD/FC/GC (departure) | PARKED | Still at gate, boarding |
| DP/OB (departure) | TAXI_TO_RUNWAY | Pushing back |
| SC/ON (departure, <20min) | PARKED | Pre-departure gate hold |

## Integration Point

Modify `_spawn_flights_to_target()` to:
1. Check if ScheduleQueue has flights ready
2. If yes: pop from queue, use real callsign + origin + dest + aircraft type
3. If no (queue empty or FLIFO unavailable): fall back to current random logic

This is a soft integration — when FLIFO is off, behavior is identical to today.

## Files to Create

| File | Purpose |
|------|---------|
| `src/ingestion/_schedule_queue.py` | ScheduleQueue class with refresh/pop/mark logic |

## Files to Modify

| File | Change |
|------|--------|
| `src/ingestion/_generation.py` | `_spawn_flights_to_target()` — try queue first, fallback to random |
| `src/ingestion/_generation.py` | `generate_synthetic_flights()` — call `queue.refresh()` periodically |
| `src/ingestion/_flight_lifecycle.py` | `_create_new_flight()` — accept optional aircraft_type override |
| `app/backend/services/flifo_service.py` | Add `get_upcoming()` method returning raw schedule for queue |

## Key Behaviors

1. **Deterministic replay:** Same FLIFO data + same seed = same simulation positions (for demos)
2. **Graceful degradation:** Queue empty → random flights (current behavior)
3. **No duplicates:** `_spawned` set prevents re-spawning a flight that exited and re-entered window
4. **Flight number match:** FIDS and map show same flight numbers when FLIFO active
5. **Phase realism:** Aircraft type from FLIFO used for wake separation, turnaround timing
6. **Refresh rate:** Queue refreshes every 60s from FLIFO cache (already cached in flifo_service)

## What This Does NOT Change

- Trajectory generation (approach paths, taxi routing) — unchanged
- Position updates, physics, separation — unchanged
- FIDS priority chain — unchanged (live sim flights still priority 1)
- Behavior without FLIFO env vars — zero change

## Verification

1. Start mock FLIFO + app with `FLIFO_BASE_URL` set
2. Wait for flights to spawn → check callsigns match FLIFO schedule
3. Open FIDS → same flight numbers appear on map and in schedule table
4. Kill FLIFO server → new spawns fall back to random (graceful degradation)
5. Unit test: ScheduleQueue pop logic, window filtering, duplicate prevention
6. Regression: `uv run pytest tests/ -k "schedule or generation" -v`

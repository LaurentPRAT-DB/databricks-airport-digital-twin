---
title: "Pre-v1.0: Decompose God Objects (fallback.py, routes.py)"
status: backlog
area: infrastructure
priority: high
related:
  - ../backlog/v1-readiness-checklist.md
---

# Pre-v1.0: Decompose God Objects

## Problem

Two oversized files create maintenance risk and onboarding friction:

| Weakness | Impact on v1.0 | Fix? |
|----------|----------------|------|
| `fallback.py` 6,298L god-object | **High** -- 122 functions, 39 test files touch it, 15+ importers reach into private state (`_flight_states`, `_get_osm_primary_runway`). Any bug fix is risky, any new dev is confused. | **Yes** |
| `routes.py` 1,985L | **Medium** -- already sectioned by domain (schedule, weather, GSE, baggage, airport). Natural split points exist. | **Yes, quick** |
| `lakebase_service.py` 2,417L | Low -- one class doing one thing (Lakebase CRUD). Long but cohesive. Each method is independent. | No |
| Scattered `os.getenv()` (91 calls) | Low -- works fine, just ugly. Pydantic BaseSettings is nice-to-have. | No |
| No API versioning | Low -- single consumer (own frontend), deployed as a unit. Versioning adds complexity with zero benefit today. | No |
| Raw dicts in simulation engine | Low -- typed models would help but the engine works. Refactoring changes nothing for users. | No |
| 26 DABs resource configs | Not a weakness -- that's just IaC being explicit. | No |

**Bottom line:** fix `fallback.py` and `routes.py`. Leave the rest alone.

## fallback.py Decomposition -- Natural Modules

The file already has section headers. The decomposition writes itself:

| New Module | ~Lines | Functions | What It Does |
|------------|--------|-----------|-------------|
| `flight_state.py` | ~800 | `FlightPhase`, `FlightState`, `_FlightStateDict`, `_set_phase`, `get_current_flight_states`, `get_flights_as_schedule` | State machine core, phase enum, state container |
| `runway_ops.py` | ~500 | `RunwayState`, `GateState`, separation management, `_check_approach_separation`, `_is_runway_clear`, `_occupy_runway`, `_release_runway` | Runway/gate resource management, wake separation |
| `taxi_routing.py` | ~500 | `_build_arrival_taxi_route`, `_build_departure_taxi_route`, `_compute_taxiway_line`, `_generate_taxi_spine`, `_smooth_sharp_turns`, `_get_taxi_waypoints_*` | Geometry-derived taxi routing |
| `approach_departure.py` | ~600 | `_get_approach_waypoints`, `_get_departure_waypoints`, `_get_star_name`, `_get_sid_name`, runway heading/threshold | ILS approach paths, SID/STAR |
| `airport_geometry.py` | ~500 | `set_airport_center`, `apply_airport_offset`, `get_gates`, `reload_gates`, gate generation, terminal geometry | Airport coordinate system, gates |
| `geo_utils.py` | ~300 | `_distance_nm`, `_distance_meters`, `_bearing_from_airport`, `_point_on_circle`, `_offset_position_by_heading`, `_smooth_heading` | Math/geo helper functions |
| `flight_lifecycle.py` | ~1200 | `_create_new_flight`, `_update_flight_state` (the big state machine) | Flight creation and per-tick update |
| `event_buffers.py` | ~200 | `emit_phase_transition`, `emit_gate_event`, `emit_prediction`, `drain_*` | Thread-safe event collection |
| `fallback.py` (remaining) | ~1500 | `generate_synthetic_flights`, calibration setters, weather state, airline selection, `_get_flight_phase_name` | Orchestrator: ties modules together |

**Key risk:** `fallback.py` uses ~30 module-level globals (`_flight_states`, `AIRPORT_CENTER`, `_gate_states`, `_runway_states`, etc.) that create implicit coupling.

**Approach:** Option (b) -- create a shared `_state.py` module that all sub-modules import. Pragmatic, preserves behavior, minimal risk. Clean explicit state passing (option a) is ideal but too large a refactor for pre-v1.0.

## routes.py Decomposition -- Already Sectioned

The file has clear `# ====` section headers. Split into existing FastAPI sub-routers:

| New Router File | ~Lines | Endpoints |
|----------------|--------|-----------|
| `routes_schedule.py` | ~150 | `/schedule/arrivals`, `/schedule/departures`, `/schedule/audit` |
| `routes_baggage.py` | ~80 | `/baggage/stats`, `/baggage/flight/{fn}`, `/baggage/alerts` |
| `routes_airport.py` | ~500 | `/airport/config`, all import endpoints (OSM, AIXM, IFC, FAA, MSFS) |
| `routes_debug.py` | ~100 | `/debug/*`, `/metrics`, ring buffer |
| `routes.py` (remaining) | ~900 | Core flight endpoints, WebSocket, airport switch, simulation jobs |

## Effort Estimate

| Task | Effort | Risk |
|------|--------|------|
| `routes.py` -> 5 sub-routers | 0.5 day | Low -- `include_router` is trivial, no logic change |
| Create `src/ingestion/_state.py` | 0.5 day | Low -- shared globals module (the glue) |
| Extract `geo_utils.py` | 0.5 day | Low -- pure functions, zero coupling |
| Extract `event_buffers.py` | 0.25 day | Low -- isolated, thread-safe buffers |
| Extract `flight_state.py` | 0.5 day | Medium -- FlightPhase enum used everywhere |
| Extract `runway_ops.py` + `taxi_routing.py` + `approach_departure.py` | 1 day | Medium -- geometry/ops, some cross-references |
| Extract `airport_geometry.py` | 0.5 day | Medium -- gates, coordinate system |
| Extract `flight_lifecycle.py` | 0.5 day | Medium -- the big state machine |
| Re-export from `fallback.py` + update imports | 0.5 day | Low -- backward compat shim |
| Full test suite verification | 0.5 day | 3,089 + 830 tests must pass unchanged |

**Total: ~4-5 days**, dominated by `fallback.py`.

## Recommended Execution Order

1. `routes.py` first (0.5 day) -- low risk, builds confidence
2. Create `src/ingestion/_state.py` -- shared globals module
3. Extract `geo_utils.py` -- pure functions, zero coupling, easy win
4. Extract `event_buffers.py` -- isolated, thread-safe buffers
5. Extract `flight_state.py` -- `FlightPhase`, `FlightState`, state container
6. Extract `runway_ops.py` + `taxi_routing.py` + `approach_departure.py` -- geometry/ops
7. Extract `airport_geometry.py` -- gates, coordinate system
8. Extract `flight_lifecycle.py` -- the big state machine
9. Re-export everything from `fallback.py` -- backward compat, nothing breaks
10. Run full test suite, verify, commit

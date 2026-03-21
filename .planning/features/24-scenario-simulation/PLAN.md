# Phase 24: Scenario-Based Airport Simulation

## Goal

Add scenario injection — composable disruption events defined in YAML — plus a capacity manager that enforces physical throughput limits, so disruptions cause realistic cascading effects (holds, delays, diversions, go-arounds).

## Status: Plan — Not Started

## Prerequisites: Phase 23 (Simulation Mode) must be complete.

---

## Context

The simulation engine (`src/simulation/engine.py`) currently runs a single "fair weather, nominal ops" scenario — flights spawn on schedule, weather is random/benign, all runways and gates are always available. Real airport operations face disruptions: weather degradation reduces runway throughput, runway closures force single-runway ops, gate failures require reassignment, traffic surges overwhelm capacity. Without these, the simulation can't be used for operational planning or stress testing.

This plan adds scenario injection — composable disruption events defined in YAML — plus a capacity manager that enforces physical throughput limits, so disruptions cause realistic cascading effects (holds, delays, diversions, go-arounds).

---

## Architecture

```
scenario.yaml ──► ScenarioManager ──► SimulationEngine main loop
                       │                    │
                       ├─ WeatherEvents ────► CapacityManager (AAR/ADR rates)
                       ├─ RunwayEvents  ────► RunwayManager (closures/config)
                       ├─ GroundEvents  ────► GateManager (failures, turnaround)
                       └─ TrafficEvents ────► Schedule injector (surges/diversions)
                                             │
                                             ▼
                                     SimulationRecorder
                                     (all events + scenario event log)
```

---

## Files to Create

### 1. `src/simulation/scenario.py` — Scenario model + loader

Pydantic models for composable scenario definition:

```python
class WeatherEvent(BaseModel):
    time: str               # "HH:MM" within sim day
    type: str               # "thunderstorm" | "fog" | "snow" | "wind_shift" | "clear"
    severity: str           # "light" | "moderate" | "severe"
    duration_hours: float
    visibility_nm: float | None = None
    ceiling_ft: int | None = None
    wind_speed_kt: int | None = None
    wind_gusts_kt: int | None = None
    wind_direction: int | None = None

class RunwayEvent(BaseModel):
    time: str
    type: str               # "closure" | "config_change" | "reopen"
    runway: str | None = None       # "28R" for closure
    runway_config: str | None = None  # "28L_only" for config change
    duration_minutes: int | None = None
    reason: str | None = None

class GroundEvent(BaseModel):
    time: str
    type: str               # "gate_failure" | "taxiway_closure" | "fuel_shortage" | "deicing_required"
    target: str | None = None  # gate ID or taxiway name
    duration_hours: float = 1.0
    impact: dict | None = None  # e.g. {"turnaround_multiplier": 1.5}

class TrafficModifier(BaseModel):
    time: str | None = None
    time_range: list[str] | None = None  # ["HH:MM", "HH:MM"]
    type: str               # "surge" | "diversion" | "cancellation" | "ground_stop"
    extra_arrivals: int = 0
    extra_departures: int = 0
    diversion_origin: str | None = None

class SimulationScenario(BaseModel):
    name: str
    description: str = ""
    base_config: str | None = None
    weather_events: list[WeatherEvent] = []
    runway_events: list[RunwayEvent] = []
    ground_events: list[GroundEvent] = []
    traffic_modifiers: list[TrafficModifier] = []
```

Functions:
- `load_scenario(path) -> SimulationScenario` — YAML loader
- `resolve_times(scenario, sim_start) -> list[ResolvedEvent]` — converts `"HH:MM"` to absolute datetimes, sorted chronologically

---

### 2. `src/simulation/capacity.py` — Capacity manager

Makes disruptions cause realistic knock-on effects. Key capacity rules based on real SFO ops:

| Condition | Arrivals/hr | Departures/hr | Notes |
|-----------|------------|---------------|-------|
| VMC (VFR, vis >= 5sm, ceiling >= 3000ft) | 60 | 55 | 2 parallel runways |
| IMC (IFR, vis < 5sm or ceiling < 3000ft) | ~30 | ~28 | Increased spacing |
| LIFR (vis < 1sm or ceiling < 500ft) | ~18 | ~15 | CAT III, single approach stream |
| Single runway op | ~50% of 2-runway rates | ~50% | Half throughput |
| Ground stop | N/A | 0 | No departures |

```python
class CapacityManager:
    """Enforces airport throughput limits based on weather, runway config, and disruptions."""

    def __init__(self, airport: str, runways: list[str] = ["28L", "28R"]):
        self.base_aar = 60          # arrivals/hour VMC
        self.base_adr = 55          # departures/hour VMC
        self.all_runways = set(runways)
        self.active_runways = set(runways)
        self.current_category = "VFR"  # VFR/MVFR/IFR/LIFR
        self.failed_gates: dict[str, datetime] = {}  # gate -> expires_at
        self.turnaround_multiplier = 1.0
        self.ground_stop = False
        self._active_events: list = []      # events currently in effect
        self._recent_arrivals: list = []    # timestamps of recent arrivals
        self._recent_departures: list = []

    def get_arrival_rate(self, sim_time) -> int:
        """Current max arrivals/hour."""
        # Base rate adjusted by: weather category, active runways, events

    def get_departure_rate(self, sim_time) -> int:
        """Current max departures/hour."""

    def can_accept_arrival(self, sim_time) -> bool:
        """Has arrival rate capacity for one more in the last hour?"""

    def can_release_departure(self, sim_time) -> bool:
        """Has departure rate capacity for one more?"""

    def should_hold(self, sim_time) -> bool:
        """Approaching flights should enter holding pattern."""

    def is_gate_available(self, gate: str, sim_time) -> bool:
        """Gate not failed/closed."""

    def get_available_runways(self, sim_time) -> set[str]:
        """Runways currently open for operations."""

    def apply_weather(self, visibility_nm, ceiling_ft, wind_gusts_kt):
        """Recalculate category and rates from weather conditions."""

    def close_runway(self, runway: str, until: datetime):
        """Close runway, reduce capacity."""

    def reopen_runway(self, runway: str):
        """Reopen runway, restore capacity."""

    def fail_gate(self, gate: str, until: datetime):
        """Mark gate as unavailable."""

    def set_ground_stop(self, active: bool):
        """Enable/disable ground stop (no departures)."""

    def set_turnaround_multiplier(self, mult: float):
        """Slow down turnarounds (e.g., deicing adds 1.5x)."""

    def record_arrival(self, sim_time):
        """Track arrival for rate limiting."""

    def record_departure(self, sim_time):
        """Track departure for rate limiting."""

    def update(self, sim_time):
        """Expire events whose duration has elapsed, revert to nominal."""
```

---

### 3. Example scenario files

#### `scenarios/sfo_thunderstorm_peak.yaml` — Afternoon storm during evening peak

```yaml
name: SFO Thunderstorm During Evening Peak
description: Severe thunderstorm hits during 16:00-18:00 peak departure window

weather_events:
  - time: "15:30"
    type: thunderstorm
    severity: moderate
    duration_hours: 2.5
    visibility_nm: 2.0
    ceiling_ft: 1500
    wind_gusts_kt: 45
    wind_direction: 210

  - time: "18:00"
    type: clear
    severity: light
    duration_hours: 6.0
    visibility_nm: 10.0
    ceiling_ft: 10000

runway_events:
  - time: "15:45"
    type: closure
    runway: "28R"
    duration_minutes: 90
    reason: "Thunderstorm wind shear on departure end"
```

#### `scenarios/sfo_fog_morning.yaml` — Dense fog 06:00-10:00, CAT III only

```yaml
name: SFO Morning Fog
description: Dense advection fog during morning arrival peak

weather_events:
  - time: "05:30"
    type: fog
    severity: severe
    duration_hours: 4.5
    visibility_nm: 0.25
    ceiling_ft: 100

  - time: "10:00"
    type: clear
    severity: light
    duration_hours: 14.0
    visibility_nm: 10.0
    ceiling_ft: 5000
```

#### `scenarios/sfo_diversions.yaml` — OAK closed, 12 diversions + gate failure

```yaml
name: SFO Diversions from OAK Closure
description: Oakland airport closed, 12 flights divert to SFO; gate G3 fails

traffic_modifiers:
  - time: "14:00"
    type: diversion
    extra_arrivals: 12
    diversion_origin: OAK

ground_events:
  - time: "14:30"
    type: gate_failure
    target: "G3"
    duration_hours: 3.0

  - time: "14:00"
    type: fuel_shortage
    duration_hours: 2.0
    impact:
      turnaround_multiplier: 1.4
```

#### `scenarios/sfo_stress_test.yaml` — Everything fails

```yaml
name: SFO Stress Test
description: Storm + diversions + runway closure + gate failures — worst case

weather_events:
  - time: "08:00"
    type: thunderstorm
    severity: severe
    duration_hours: 4.0
    visibility_nm: 0.5
    ceiling_ft: 200
    wind_gusts_kt: 55
    wind_direction: 240

runway_events:
  - time: "08:15"
    type: closure
    runway: "28R"
    duration_minutes: 180
    reason: "Severe wind shear"

ground_events:
  - time: "09:00"
    type: gate_failure
    target: "A1"
    duration_hours: 4.0
  - time: "09:30"
    type: gate_failure
    target: "B2"
    duration_hours: 3.0
  - time: "08:00"
    type: deicing_required
    duration_hours: 4.0
    impact:
      turnaround_multiplier: 1.8

traffic_modifiers:
  - time: "10:00"
    type: diversion
    extra_arrivals: 15
    diversion_origin: OAK
  - time_range: ["08:00", "12:00"]
    type: ground_stop
```

---

### 4. `tests/test_scenario.py`

- **TestScenarioConfig:** YAML load, model validation, time resolution
- **TestCapacityManager:** VMC rates, weather degradation, runway closure halves rate, gate failure, event expiry
- **TestScenarioEngine:** Run thunderstorm → higher delays; run diversions → extra flights; baseline vs scenario KPI comparison

---

## Modifications to Existing Files

| File | Change |
|------|--------|
| `src/simulation/config.py` | Add `scenario_file: str \| None = None` field |
| `src/simulation/cli.py` | Add `--scenario` CLI argument |
| `src/simulation/engine.py` | Integrate scenario + capacity into main loop (see below) |
| `src/simulation/recorder.py` | Add `scenario_events` list, new summary fields (`total_go_arounds`, `total_holdings`, `delay_by_cause`) |

---

## Engine Integration Detail (`engine.py`)

### `__init__`:
- Load scenario from `config.scenario_file` if provided
- Create `CapacityManager(airport, ["28L", "28R"])`
- Feed scenario events into capacity manager's event timeline
- If scenario has `traffic_modifiers`, inject extra flights into the pre-generated schedule

### New step in `run()` loop (between spawn and update):

```python
# 1b. Process scenario events at current sim_time
self._process_scenario_events()
# Checks if weather/runway/ground/traffic events trigger now
# Updates CapacityManager state accordingly
# Records scenario events to recorder
```

### Modified `_spawn_scheduled_flights()`:
- Before spawning an arrival: check `capacity.can_accept_arrival(sim_time)`
  - If False → delay this flight's spawn by one tick (it'll retry next tick)
  - This naturally creates a queue / holding pattern effect
- Departures: check `capacity.can_release_departure(sim_time)` before allowing pushback

### Modified `_capture_weather()`:
- If a scenario weather event is active, construct METAR from its parameters (visibility, ceiling, wind) instead of random `generate_metar()`
- Pass scripted values to weather generator as overrides

### New `_process_scenario_events()`:
- Iterate scenario events, trigger when `sim_time >= event.resolved_time`
- Weather → `capacity.apply_weather(vis, ceiling, gusts)` + update weather gen
- Runway → `capacity.close_runway("28R", until)` or `capacity.reopen_runway("28R")`
- Ground → `capacity.fail_gate(gate, until)` or `capacity.set_turnaround_multiplier(1.5)`
- Traffic → inject extra flights into schedule (append to `self.flight_schedule`)

---

## Execution Order

1. `src/simulation/scenario.py` — Models + loader
2. `src/simulation/capacity.py` — Capacity manager with rate enforcement
3. `src/simulation/engine.py` — Wire scenario + capacity into main loop
4. `src/simulation/config.py` + `src/simulation/cli.py` — Add `--scenario`
5. `src/simulation/recorder.py` — `scenario_events` + new summary metrics
6. `scenarios/*.yaml` — 4 example scenarios
7. `tests/test_scenario.py` — Unit + integration tests
8. Run & validate — compare baseline vs each scenario

---

## Verification

1. **Baseline:** `python -m src.simulation.cli --config configs/simulation_sfo_50.yaml`
   → ~85% on-time, ~8min avg delay

2. **Thunderstorm:** `... --scenario scenarios/sfo_thunderstorm_peak.yaml`
   → Expect ~50-60% on-time during storm hours, go-arounds, holdings

3. **Fog:** `... --scenario scenarios/sfo_fog_morning.yaml`
   → Expect arrival rate drops to ~18/hr during fog, massive delays 06-10am

4. **Diversions:** `... --scenario scenarios/sfo_diversions.yaml`
   → 12 extra flights appear, gate pressure, higher turnaround times

5. **Stress test:** `... --scenario scenarios/sfo_stress_test.yaml`
   → Severe degradation across all KPIs, some flights never land

6. **Tests:** `uv run pytest tests/test_scenario.py tests/test_simulation.py -v`

---

## Estimated Scope

- **New files:** 7 (`scenario.py`, `capacity.py`, 4 YAML scenarios, tests)
- **Modified files:** 4 (`engine.py`, `config.py`, `cli.py`, `recorder.py`)
- **Lines:** ~800-1000 new code + ~300 tests
- **Risk:** Medium — capacity rate limiting must not deadlock the simulation (flights must eventually land/depart even under severe weather, just slower)

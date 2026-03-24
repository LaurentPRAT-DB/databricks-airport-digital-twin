# Airport Digital Twin — Event Catalog

Complete list of every event recorded during simulation. Use this to understand
what data is available for testing, debugging, and building dashboards.

There are **3 recording systems**. Each captures a different layer:

| System | File | Purpose | Output |
|--------|------|---------|--------|
| **Recorder** | `src/simulation/recorder.py` | Production data — written to simulation JSON | `simulation_output_*.json` |
| **Diagnostics** | `src/simulation/diagnostics.py` | Debug/analysis — optional, machine-readable | `*_diagnostics.json` |
| **Live Buffers** | `src/ingestion/fallback.py` | Real-time WebSocket feed — in-memory ring buffers | `/ws` frames, API drains |

---

## 1. RECORDER EVENTS (Production Output)

These are written to the simulation JSON file and consumed by the frontend replay player.

---

### 1.1 Position Snapshot

**What:** The location, speed, and state of every aircraft at every simulation tick.
This is the primary data stream — it drives the map visualization.

**When:** Every simulation tick (default 2s) for every active flight.

**Source:** `engine.py` → `recorder.record_position()`

| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `time` | ISO datetime | `2026-03-24T08:30:00` | Simulation clock time |
| `icao24` | string | `a1b2c3` | Unique aircraft transponder ID |
| `callsign` | string | `UAL1781` | Flight callsign (e.g., United 1781) |
| `latitude` | float | `37.6213` | WGS84 latitude in degrees |
| `longitude` | float | `-122.3790` | WGS84 longitude in degrees |
| `altitude` | float | `3500.0` | Altitude in feet (0 = on ground) |
| `velocity` | float | `145.0` | Ground speed in knots |
| `heading` | float | `280.0` | Compass heading in degrees (0=N, 90=E) |
| `phase` | string | `approaching` | Current flight phase (see Phase list below) |
| `on_ground` | bool | `false` | Whether the aircraft is on the ground |
| `aircraft_type` | string | `B738` | ICAO aircraft type designator |
| `assigned_gate` | string? | `B22` | Gate assignment, null if none |
| `vertical_rate` | float | `-1200.0` | Climb/descent rate in feet/minute (negative = descending) |

**Flight phases** (the full lifecycle):
```
approaching → landing → taxi_to_gate → parked → pushback → taxi_to_runway → takeoff → departing → enroute
```

---

### 1.2 Phase Transition

**What:** Records every time an aircraft changes flight phase. Essential for
verifying the state machine and measuring phase durations.

**When:** At the exact simulation tick when a flight changes phase.

**Source:** `engine.py` → `recorder.record_phase_transition()`

| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `time` | ISO datetime | `2026-03-24T08:32:15` | When the transition occurred |
| `icao24` | string | `a1b2c3` | Aircraft ID |
| `callsign` | string | `UAL1781` | Flight callsign |
| `from_phase` | string | `approaching` | Phase the aircraft was in |
| `to_phase` | string | `landing` | Phase the aircraft transitioned to |
| `latitude` | float | `37.6100` | Position at transition |
| `longitude` | float | `-122.3750` | Position at transition |
| `altitude` | float | `200.0` | Altitude at transition (feet) |
| `aircraft_type` | string | `B738` | Aircraft type |
| `assigned_gate` | string? | `B22` | Gate assignment at transition time |

**What to check:**
- `approaching → landing` should happen near decision height (~200 ft)
- `landing → taxi_to_gate` should happen at ground level on the runway
- `parked → pushback` indicates turnaround is complete
- `taxi_to_runway → takeoff` should happen at the runway threshold

---

### 1.3 Gate Event

**What:** Records when an aircraft occupies or vacates a gate. Used for gate
utilization analysis, turnaround timing, and conflict detection.

**When:** When a flight arrives at a gate or departs from a gate.

**Source:** `engine.py` → `recorder.record_gate_event()`

| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `time` | ISO datetime | `2026-03-24T08:45:00` | When the event occurred |
| `icao24` | string | `a1b2c3` | Aircraft ID |
| `callsign` | string | `UAL1781` | Flight callsign |
| `gate` | string | `B22` | Gate identifier |
| `event_type` | string | `occupy` | Either `occupy` or `vacate` |
| `aircraft_type` | string | `B738` | Aircraft type |

**What to check:**
- Every `occupy` should eventually have a matching `vacate`
- No two aircraft should `occupy` the same gate simultaneously
- Time between `occupy` and `vacate` = turnaround time

---

### 1.4 Weather Snapshot

**What:** Periodic METAR-style weather conditions at the airport. Affects
runway capacity, approach categories, and delay calculations.

**When:** Periodically during simulation (typically every 30 min sim-time).

**Source:** `engine.py` → `recorder.record_weather()`

| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `time` | ISO datetime | `2026-03-24T09:00:00` | Observation time |
| `wind_speed_kts` | float | `12.0` | Wind speed in knots |
| `wind_direction` | float | `280.0` | Wind from direction (degrees) |
| `visibility_nm` | float | `10.0` | Visibility in nautical miles |
| `ceiling_ft` | float | `5000.0` | Cloud ceiling in feet |
| `temperature_c` | float | `18.0` | Temperature in Celsius |
| `category` | string | `VMC` | VMC (visual) or IMC (instrument) |

---

### 1.5 Baggage Event

**What:** Baggage handling for each parked flight. Tracks bag counts and
individual bag processing.

**When:** When a flight is parked and baggage processing completes.

**Source:** `engine.py` → `recorder.record_baggage()`

| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `time` | ISO datetime | `2026-03-24T09:05:00` | When baggage was processed |
| `flight_number` | string | `UAL1781` | Flight callsign |
| `bag_count` | int | `142` | Total bags processed |
| `bags` | list[dict] | `[{...}]` | Individual bag records (tag, weight, status) |

---

### 1.6 Scenario Event

**What:** High-level operational events — weather changes, runway closures,
go-arounds, diversions, cancellations, capacity holds. This is the "narrative
log" of what happened during the simulation.

**When:** When significant operational events occur.

**Source:** `engine.py` → `recorder.record_scenario_event()`

**Event types and their fields:**

#### `weather` — Weather condition change
| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `time` | ISO datetime | | When weather changed |
| `description` | string | `Thunderstorm approaching` | Human-readable description |
| `severity` | string | `moderate` | Weather severity level |
| `type` | string | `thunderstorm` | Weather type |
| `visibility_nm` | float | `3.0` | New visibility |
| `ceiling_ft` | float | `1500.0` | New ceiling |

#### `runway` — Runway closure, reopening, or configuration change
| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `time` | ISO datetime | | When runway event occurred |
| `description` | string | `Runway 28L closed for maintenance` | Human-readable |
| `runway` | string | `28L` | Affected runway (for close/reopen) |
| `reason` | string | `maintenance` | Why (for closure) |
| `runway_config` | string | `28L/28R` | New config (for config change) |

#### `ground` — Ground infrastructure event
| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `time` | ISO datetime | | When event occurred |
| `description` | string | `Taxiway A closed` | Human-readable |
| `type` | string | `taxiway_closure` | Event type |
| `target` | string | `Taxiway A` | Affected infrastructure |

#### `traffic` — Traffic management event (ground stop, flow control)
| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `time` | ISO datetime | | When event occurred |
| `description` | string | `Ground stop lifted` | Human-readable |

#### `capacity` — Flight held due to rate limit
| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `time` | ISO datetime | | When hold started |
| `description` | string | `Arrival UAL1781 holding — arrival rate at capacity` | Human-readable |
| `callsign` | string | `UAL1781` | Held flight |
| `action` | string | `hold` | Always "hold" |

#### `go_around` — Missed approach executed
| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `time` | ISO datetime | | When go-around initiated |
| `description` | string | `UAL1781 go-around #1 (IMC)` | Human-readable |
| `callsign` | string | `UAL1781` | Flight that went around |
| `icao24` | string | `a1b2c3` | Aircraft ID |
| `count` | int | `1` | Go-around attempt number |
| `weather` | string | `IMC` | Weather category at time |

#### `diversion` — Flight diverted to alternate airport
| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `time` | ISO datetime | | When diversion decided |
| `description` | string | `UAL1781 diverted to OAK` | Human-readable |
| `callsign` | string | `UAL1781` | Diverted flight |
| `icao24` | string | `a1b2c3` | Aircraft ID |
| `alternate` | string | `OAK` | Alternate airport |

#### `cancellation` — Flight cancelled before departure
| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `time` | ISO datetime | | When cancelled |
| `description` | string | `UAL2024 proactively cancelled (severe weather forecast)` | Reason |
| `callsign` | string | `UAL2024` | Cancelled flight |
| `reason` | string | `proactive_severe_weather` | Cancellation reason |

#### `curfew` — Night curfew period active
| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `time` | ISO datetime | | When curfew starts |
| `description` | string | `Curfew active 23:00-06:00 (max 4 arr/hr)` | Details |
| `start` | string | `23:00` | Curfew start time |
| `end` | string | `06:00` | Curfew end time |

---

### 1.7 Passenger Flow Event

**What:** Passenger movement through the terminal — security checkpoints,
dwell time, deboarding, baggage claim. Generated post-simulation by the
passenger flow model.

**When:** After simulation completes, for every scheduled flight.

**Source:** `passenger_flow.py` → stored in `recorder.passenger_events`

#### Departure — Checkpoint stage
| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `time` | ISO datetime | | 5-min time bin when passengers hit security |
| `flight_number` | string | `UAL2024` | Departing flight |
| `flight_type` | string | `departure` | Always "departure" |
| `stage` | string | `checkpoint` | Security checkpoint processing |
| `pax_count` | int | `85` | Passengers processed in this bin |
| `queue_length` | int | `120` | Queue depth at checkpoint |
| `wait_time_min` | float | `12.5` | Estimated wait time (minutes) |
| `throughput_pph` | float | `800.0` | Checkpoint throughput (passengers/hour) |

#### Departure — Dwell stage
| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `time` | ISO datetime | | Scheduled departure time |
| `flight_number` | string | `UAL2024` | Departing flight |
| `flight_type` | string | `departure` | Always "departure" |
| `stage` | string | `dwell` | Post-security terminal dwell |
| `pax_count` | int | `180` | Total passengers for this flight |
| `dwell_time_min` | float | `45.2` | Average dwell time (minutes) |

#### Arrival — Deplane stage
| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `time` | ISO datetime | | Aircraft parked time |
| `flight_number` | string | `UAL1781` | Arriving flight |
| `flight_type` | string | `arrival` | Always "arrival" |
| `stage` | string | `deplane` | Deboarding at gate |
| `pax_count` | int | `165` | Total passengers deboarding |
| `dwell_time_min` | float | `12.0` | Deboarding duration (minutes) |

#### Arrival — Dwell stage
| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `time` | ISO datetime | | Deboarding complete time |
| `flight_number` | string | `UAL1781` | Arriving flight |
| `flight_type` | string | `arrival` | Always "arrival" |
| `stage` | string | `dwell` | Terminal walk + baggage claim |
| `pax_count` | int | `165` | Passengers |
| `dwell_time_min` | float | `28.5` | Total terminal dwell (deplane + walk + claim) |

---

### 1.8 BHS Metrics (Baggage Handling System)

**What:** Aggregated baggage handling system performance. Not per-event —
a single summary object attached to the simulation output.

**Source:** `engine.py` → `recorder.bhs_metrics`

| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `peak_throughput_bpm` | float | `42.5` | Peak throughput in bags/minute |
| `total_injection_capacity_bpm` | float | `60.0` | System injection capacity |
| `jam_count` | int | `3` | Number of conveyor jam events |
| `max_queue_depth` | int | `250` | Maximum queue depth (bags) |
| `p95_processing_time_min` | float | `18.5` | 95th percentile processing time |

---

## 2. DIAGNOSTIC EVENTS (Debug Output)

Written to `*_diagnostics.json` when `config.diagnostics = true`. Machine-readable
events for automated anomaly detection and root-cause analysis. Every event has:

```json
{ "type": "EVENT_TYPE", "sim_time": "2026-03-24T08:30:00", ...fields }
```

---

### 2.1 PHASE_TRANSITION

**What:** Same as recorder phase transition but in the diagnostics stream.
Used for cross-referencing with other diagnostic events.

**When:** Every flight phase change.

**Source:** `fallback.py` → `emit_phase_transition()` → `diag_log()`

| Field | Type | Description |
|-------|------|-------------|
| `icao24` | string | Aircraft ID |
| `callsign` | string | Flight callsign |
| `from_phase` | string | Previous phase |
| `to_phase` | string | New phase |
| `alt` | float | Altitude at transition (feet) |
| `vel` | float | Velocity at transition (knots) |

**Debug use:** Verify `approaching → landing` happens at ~200ft (decision height),
not at 6ft or 3000ft.

---

### 2.2 SEPARATION_LOSS

**What:** Two aircraft are closer than the required wake turbulence separation
minimum. This is a safety violation — the trailing aircraft should slow down
or go around.

**When:** During approach, when separation check fails.

**Source:** `fallback.py` → `_check_approach_separation()` → `diag_log()`

| Field | Type | Description |
|-------|------|-------------|
| `icao24` | string | Trailing aircraft (the one too close) |
| `leader` | string | Leading aircraft (the one being followed) |
| `distance_nm` | float | Actual lateral distance in nautical miles |
| `required_nm` | float | Required separation in nautical miles |
| `vertical_ft` | float | Vertical separation in feet |

**Debug use:** If you see many of these, approach sequencing is broken.
Expected separation by wake category:
- SUPER behind SUPER: 4 NM
- HEAVY behind SUPER: 6 NM
- LARGE behind HEAVY: 5 NM
- SMALL behind HEAVY: 6 NM

---

### 2.3 RUNWAY_CONFLICT

**What:** An aircraft tried to occupy a runway that another aircraft is already
using. The simulation will overwrite the occupant — this event flags the conflict.

**When:** When `_occupy_runway()` is called and the runway is already occupied
by a different aircraft.

**Source:** `fallback.py` → `_occupy_runway()` → `diag_log()`

| Field | Type | Description |
|-------|------|-------------|
| `runway` | string | Runway identifier (e.g., `28L`) |
| `occupant` | string | Aircraft currently on the runway |
| `requester` | string | Aircraft trying to enter the runway |

**Debug use:** This should ideally never happen. If it does, the runway
sequencing logic has a bug — two aircraft on the same runway simultaneously.

---

### 2.4 GATE_CONFLICT

**What:** All gates are occupied and the gate buffer (nearby holding area) is
also full. Aircraft has nowhere to park.

**When:** When `_find_available_gate()` finds no open gate and the buffer is full.

**Source:** `fallback.py` → `_find_available_gate()` → `diag_log()`

| Field | Type | Description |
|-------|------|-------------|
| `gates_in_buffer` | int | Number of gates in the buffer (all occupied) |

**Debug use:** High count means the airport needs more gates or faster turnarounds.

---

### 2.5 GO_AROUND

**What:** An aircraft executed a missed approach — climbed away from the runway
instead of landing. Happens when the runway is occupied, separation is lost,
or weather is below minimums at decision height.

**When:** When `_execute_go_around()` is called.

**Source:** `fallback.py` → `_execute_go_around()` → `diag_log()`

| Field | Type | Description |
|-------|------|-------------|
| `icao24` | string | Aircraft that went around |
| `callsign` | string | Flight callsign |
| `reason` | string | Why: `runway_busy`, `separation_loss`, `runway_busy_at_threshold` |
| `alt` | float | Altitude when go-around initiated (feet) |
| `count` | int | How many times this flight has gone around |

**Debug use:**
- `count > 2` means the same flight keeps going around — likely a sequencing problem
- `reason = runway_busy_at_threshold` means the flight reached the runway end but
  couldn't land — this was previously a bug (holding at ground level)
- Normal rate: <5% of flights should go around

---

### 2.6 DEPARTURE_HOLD

**What:** A flight was held on the ground because the arrival or departure rate
capacity is at maximum. ATC flow control in action.

**When:** When a flight is ready to spawn but the capacity manager says no.

**Source:** `engine.py` → spawn loop → `diag_log()`

| Field | Type | Description |
|-------|------|-------------|
| `icao24` | string | Held aircraft ID |
| `reason` | string | `arrival_rate_capacity` or `departure_rate_capacity` |

**Debug use:** Frequent holds mean the schedule has more flights than the airport
can physically handle at its runway acceptance rate.

---

### 2.7 TICK_STATS

**What:** Per-tick performance metrics. Measures how long each simulation tick
takes to compute, and how many flights are active.

**When:** Every simulation tick.

**Source:** `engine.py` → main loop → `diag_log()`

| Field | Type | Description |
|-------|------|-------------|
| `tick` | int | Tick number (0-indexed) |
| `active_flights` | int | Number of active flights being simulated |
| `elapsed_ms` | float | Wall-clock time to process this tick (milliseconds) |

**Debug use:** If `elapsed_ms` spikes, find the tick number and correlate with
other events (weather change? many go-arounds? gate conflicts?).

---

### 2.8 TAXI_SPEED_VIOLATION (referenced in summary, not yet emitted)

**What:** Aircraft exceeding taxi speed limits on the ground. The diagnostics
summary logic watches for this type but no code currently emits it.

**Future use:** Would fire when ground speed > 30 kts during taxi phases.

---

## 3. LIVE BUFFER EVENTS (Real-Time WebSocket)

These are emitted in real-time by the fallback flight state machine during live
mode (not simulation replay). They're stored in in-memory ring buffers and
drained by API endpoints or the WebSocket.

---

### 3.1 Phase Transition (Live)

**What:** Same data as recorder phase transitions, but emitted in real-time.

**Source:** `fallback.py` → `emit_phase_transition()`
**Drain:** `drain_phase_transitions()` → `/api/events/phase-transitions`

| Field | Type | Description |
|-------|------|-------------|
| `icao24` | string | Aircraft ID |
| `callsign` | string | Flight callsign |
| `from_phase` | string | Previous phase |
| `to_phase` | string | New phase |
| `latitude` | float | Position |
| `longitude` | float | Position |
| `altitude` | float | Altitude (feet) |
| `aircraft_type` | string | ICAO type |
| `assigned_gate` | string? | Gate |
| `event_time` | ISO datetime | Wall-clock time |

---

### 3.2 Gate Event (Live)

**What:** Gate occupy/vacate in real-time.

**Source:** `fallback.py` → `emit_gate_event()`
**Drain:** `drain_gate_events()` → `/api/events/gate-events`

| Field | Type | Description |
|-------|------|-------------|
| `icao24` | string | Aircraft ID |
| `callsign` | string | Flight callsign |
| `gate` | string | Gate ID |
| `event_type` | string | `occupy` or `vacate` |
| `aircraft_type` | string | ICAO type |
| `event_time` | ISO datetime | Wall-clock time |

---

### 3.3 ML Prediction (Live)

**What:** Results from ML model predictions (delay, gate assignment, congestion).

**Source:** `fallback.py` → `emit_prediction()`
**Drain:** `drain_predictions()` → `/api/events/predictions`

| Field | Type | Description |
|-------|------|-------------|
| `prediction_type` | string | `delay`, `congestion`, or `gate_recommendation` |
| `icao24` | string? | Aircraft ID (null for area-level predictions) |
| `result_json` | dict | Model output (varies by type) |
| `event_time` | ISO datetime | Wall-clock time |

**Prediction subtypes:**

**`delay`** result_json:
- `delay_minutes`: predicted delay
- `confidence`: model confidence (0-1)
- `category`: delay category

**`gate_recommendation`** result_json:
- `gate_id`: recommended gate
- `score`: assignment score
- `reasons`: list of reasons
- `taxi_time`: estimated taxi time

**`congestion`** result_json:
- `area_id`: area identifier (e.g., `runway_28L`)
- `area_type`: type of area
- `level`: congestion level (`low`/`medium`/`high`)
- `flight_count`: flights in area
- `wait_minutes`: predicted wait

---

### 3.4 Turnaround Event (Live)

**What:** Sub-phase progress during aircraft turnaround at the gate (deboarding,
cleaning, catering, fueling, boarding).

**Source:** `fallback.py` → `emit_turnaround_event()`
**Drain:** `drain_turnaround_events()` → `/api/events/turnaround-events`

| Field | Type | Description |
|-------|------|-------------|
| `icao24` | string | Aircraft ID |
| `callsign` | string | Flight callsign |
| `gate` | string | Gate where turnaround is happening |
| `turnaround_phase` | string | Sub-phase name (see below) |
| `event_type` | string | `phase_start` or `phase_complete` |
| `aircraft_type` | string | ICAO type |
| `event_time` | ISO datetime | Wall-clock time |

**Turnaround sub-phases** (in order):
1. `deboarding` — passengers exit the aircraft
2. `cleaning` — cabin cleanup
3. `catering` — food/drink restocking
4. `fueling` — refueling the aircraft
5. `boarding` — new passengers board

---

## 4. SUMMARY METRICS (Computed Post-Simulation)

These are computed by `recorder.compute_summary()` and included in the simulation
JSON output. They aggregate all the events above into KPIs.

| Metric | Type | Description |
|--------|------|-------------|
| `total_flights` | int | Total scheduled flights |
| `arrivals` | int | Arrival flights |
| `departures` | int | Departure flights |
| `schedule_delay_min` | float | Average schedule delay (minutes) |
| `avg_capacity_hold_min` | float | Average capacity-induced hold time |
| `max_capacity_hold_min` | float | Maximum capacity hold time |
| `on_time_pct` | float | Percentage of flights on-time (within 15 min) |
| `spawned_count` | int | Flights that actually entered the simulation |
| `not_spawned_count` | int | Flights that never spawned (capacity overflow) |
| `cancellation_rate_pct` | float | Percentage of flights not spawned |
| `avg_effective_delay_not_spawned_min` | float | Average delay for non-spawned flights |
| `gate_utilization_gates_used` | int | Number of distinct gates used |
| `avg_turnaround_min` | float | Average gate turnaround time (minutes) |
| `peak_simultaneous_flights` | int | Maximum concurrent active flights |
| `total_position_snapshots` | int | Total position records generated |
| `total_phase_transitions` | int | Total phase change events |
| `total_gate_events` | int | Total gate occupy/vacate events |
| `total_baggage_events` | int | Total baggage processing events |
| `total_weather_snapshots` | int | Total weather observations |
| `total_scenario_events` | int | Total scenario events |
| `total_go_arounds` | int | Total missed approaches |
| `total_diversions` | int | Total diversions to alternate airports |
| `total_holdings` | int | Total holding pattern entries |
| `total_cancellations` | int | Total proactive cancellations |
| `scenario_name` | string? | Name of the scenario (if any) |
| `total_passenger_events` | int | Total passenger flow events |
| `has_bhs_metrics` | bool | Whether BHS metrics are present |

---

## 5. QUICK REFERENCE — Event by Lifecycle Stage

### Arrival Flight
```
[DEPARTURE_HOLD] ← capacity manager says "wait"
     ↓
PHASE_TRANSITION (scheduled → approaching)
     ↓
Position Snapshots (approaching) ← every tick, altitude decreasing
     ↓
[SEPARATION_LOSS] ← too close to aircraft ahead
     ↓
[GO_AROUND] ← runway busy or separation lost
     ↓
PHASE_TRANSITION (approaching → landing) ← at decision height ~200ft
     ↓
[RUNWAY_CONFLICT] ← runway already occupied
     ↓
Position Snapshots (landing) ← on the runway, decelerating
     ↓
PHASE_TRANSITION (landing → taxi_to_gate)
     ↓
Position Snapshots (taxi_to_gate) ← ground movement to gate
     ↓
PHASE_TRANSITION (taxi_to_gate → parked)
Gate Event (occupy)
     ↓
Turnaround Events (deboarding → cleaning → catering → fueling → boarding)
Passenger Flow Events (deplane → dwell)
Baggage Event
     ↓
[GATE_CONFLICT] ← if no gate available for next aircraft
```

### Departure Flight
```
Gate Event (vacate)
PHASE_TRANSITION (parked → pushback)
     ↓
Position Snapshots (pushback) ← backing away from gate
     ↓
PHASE_TRANSITION (pushback → taxi_to_runway)
     ↓
Position Snapshots (taxi_to_runway) ← ground movement to runway
     ↓
PHASE_TRANSITION (taxi_to_runway → takeoff)
     ↓
Position Snapshots (takeoff) ← accelerating on runway, rotating, climbing
     ↓
PHASE_TRANSITION (takeoff → departing)
     ↓
Position Snapshots (departing) ← initial climb, turning to route
     ↓
PHASE_TRANSITION (departing → enroute)
     ↓
Position Snapshots (enroute) ← climbing to cruise, then removed from sim
```

### Airport-Level Events
```
Weather Snapshot ← periodic conditions update
Scenario Event (weather) ← thunderstorm, fog, wind shift
Scenario Event (runway) ← closure, reopening, config change
Scenario Event (ground) ← taxiway closure, equipment failure
Scenario Event (traffic) ← ground stop, flow control
Scenario Event (curfew) ← night operations restriction
Scenario Event (cancellation) ← proactive flight cancellation
TICK_STATS ← per-tick performance metrics
BHS Metrics ← baggage system throughput (end of sim)
```

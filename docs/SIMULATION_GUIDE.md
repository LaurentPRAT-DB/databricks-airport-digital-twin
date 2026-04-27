# Simulation Guide

Generate airport simulations with configurable weather, traffic, duration, and disruption scenarios.

## Quick Start

```bash
# Simple: 50 flights at SFO, 24 hours, default weather
python -m src.simulation.cli --airport SFO --arrivals 25 --departures 25

# With a weather scenario
python -m src.simulation.cli --airport JFK --arrivals 100 --departures 100 \
  --duration 12 --scenario scenarios/jfk_winter_storm.yaml --output jfk_storm.json

# From a YAML config file
python -m src.simulation.cli --config configs/simulation_sfo_50.yaml

# Debug mode (capped at 4h, verbose logging)
python -m src.simulation.cli --airport FRA --arrivals 30 --departures 30 --debug
```

## CLI Reference

```
python -m src.simulation.cli [OPTIONS]
```

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--config` | path | — | YAML config file (all other flags override it) |
| `--airport` | string | `SFO` | IATA airport code |
| `--arrivals` | int | `25` | Number of arriving flights |
| `--departures` | int | `25` | Number of departing flights |
| `--duration` | float | `24.0` | Simulation duration in hours |
| `--time-step` | float | `2.0` | Simulated seconds per tick |
| `--seed` | int | random | Random seed for reproducibility |
| `--output` | path | `simulation_output.json` | Output file path |
| `--scenario` | path | — | Scenario YAML for weather/disruptions |
| `--debug` | flag | off | Debug mode (4h cap, verbose) |
| `--skip-positions` | flag | off | Skip position snapshots (batch/ML mode) |

## YAML Config File

All CLI flags map to config fields. Create a `.yaml` file:

```yaml
airport: JFK
arrivals: 100
departures: 100
duration_hours: 12
time_step_seconds: 2.0
seed: 42
start_date: "2025-06-16"          # Anchors day-of-week for OBT features
scenario_file: scenarios/jfk_winter_storm.yaml
output_file: simulation_output_jfk.json
```

### Config Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `airport` | string | `SFO` | IATA airport code (any of the 43 calibrated airports) |
| `arrivals` | int | `25` | Number of arriving flights |
| `departures` | int | `25` | Number of departing flights |
| `duration_hours` | float | `24.0` | Duration in hours |
| `time_step_seconds` | float | `2.0` | Seconds per tick (use `10.0` for multi-day sims) |
| `time_acceleration` | float | `3600.0` | Display ratio: 1 real second = N sim seconds |
| `start_time` | datetime | midnight UTC | Simulation start (ISO 8601) |
| `start_date` | string | today | Anchor date `YYYY-MM-DD` for day-of-week features |
| `seed` | int | random | Random seed |
| `debug` | bool | `false` | Debug mode (4h cap) |
| `scenario_file` | path | — | Scenario YAML path |
| `calibration_profile` | path | auto | Calibration JSON (auto-loaded by airport code) |
| `skip_positions` | bool | `false` | Omit position snapshots (saves memory) |
| `output_file` | string | `simulation_output.json` | Output path |
| `diagnostics` | bool | `true` | Enable diagnostic event logging |

## Scenario Files

Scenarios define weather disruptions, runway closures, ground events, curfews, and traffic injections. They are composable — combine any event types in a single file.

### Structure

```yaml
name: "Scenario Name"
description: "What this scenario tests"

weather_events: [...]
runway_events: [...]
ground_events: [...]
curfew_events: [...]
traffic_modifiers: [...]
```

All `time` fields use `"HH:MM"` notation relative to sim start. Hours ≥ 24 wrap to the next day (e.g., `"25:30"` = 01:30 day 2).

### Weather Events

Control visibility, ceiling, wind, and weather type. The simulation engine reduces airport capacity based on flight category (VFR/MVFR/IFR/LIFR) and weather-specific penalties.

```yaml
weather_events:
  - time: "14:00"
    type: thunderstorm
    severity: moderate
    duration_hours: 2.5
    visibility_nm: 1.5
    ceiling_ft: 800
    wind_speed_kt: 22
    wind_gusts_kt: 35
    wind_direction: 240
```

**Weather types:** `thunderstorm`, `fog`, `snow`, `wind_shift`, `clear`, `sandstorm`, `dust`, `smoke`, `haze`, `rain`, `freezing_rain`, `ice_pellets`

**Severity levels:** `light`, `moderate`, `severe`

**Capacity impact by flight category:**

| Visibility | Ceiling | Category | Capacity |
|------------|---------|----------|----------|
| ≥ 5 nm | ≥ 3000 ft | VFR | 100% |
| ≥ 3 nm | ≥ 1000 ft | MVFR | 70% |
| ≥ 1 nm | ≥ 500 ft | IFR | 50% |
| < 1 nm | < 500 ft | LIFR | 30% |

**Weather-type penalties** (stacked on top of category):

| Type | Multiplier | Reason |
|------|-----------|--------|
| `freezing_rain` | 0.60 | Deicing delays, surface contamination |
| `sandstorm` | 0.70 | Engine ingestion risk |
| `snow` | 0.75 | Runway plowing, deicing |
| `smoke` | 0.80 | Crew health, poor vis recovery |
| `dust` | 0.85 | Reduced vis recovery, engine FOD |
| `rain` | 0.90 | Wet runway spacing increase |
| `ice_pellets` | 0.85 | Surface contamination |
| `haze` | 0.95 | Mild vis reduction |

**Wind gusts** further reduce capacity: gusts > 35 kt apply 0.80x, gusts > 25 kt apply 0.90x. Strong gusts also increase go-around probability.

### Runway Events

```yaml
runway_events:
  - time: "10:30"
    type: closure
    runway: "28R"
    duration_minutes: 45
    reason: FOD on runway

  - time: "16:00"
    type: config_change
    runway_config: "28L,28R"
    duration_minutes: 60
    reason: Wind shift requires runway change

  - time: "11:15"
    type: reopen
    runway: "28R"
```

**Types:** `closure`, `config_change`, `reopen`

### Ground Events

```yaml
ground_events:
  - time: "09:00"
    type: gate_failure
    target: "A7"
    duration_hours: 4.0

  - time: "06:00"
    type: deicing_required
    duration_hours: 3.0
    impact:
      turnaround_multiplier: 1.5

  - time: "12:00"
    type: taxiway_closure
    target: "Taxiway A (A1-A5)"
    duration_hours: 2.0
    impact:
      turnaround_multiplier: 1.2
```

**Types:** `gate_failure`, `taxiway_closure`, `fuel_shortage`, `deicing_required`

The `impact.turnaround_multiplier` slows all turnarounds by that factor while active.

### Curfew Events

Model noise curfews (e.g., SYD 23:00-06:00, NRT 23:00-06:00).

```yaml
curfew_events:
  - start: "23:00"
    end: "06:00"
    allow_emergency_arrivals: true
    max_arrivals_per_hour: 2
```

### Traffic Modifiers

Inject extra traffic, diversions, cancellations, or ground stops.

```yaml
traffic_modifiers:
  - time: "06:00"
    type: surge
    extra_arrivals: 8
    extra_departures: 7

  - time: "11:00"
    type: diversion
    extra_arrivals: 8
    diversion_origin: OAK

  - time: "13:30"
    type: ground_stop
    duration_hours: 2.0

  - time_range: ["08:00", "12:00"]
    type: cancellation
    extra_departures: -5
```

**Types:** `surge`, `diversion`, `cancellation`, `ground_stop`

## Available Scenarios

37 pre-built scenario files in `scenarios/`:

| Airport | Scenario | File |
|---------|----------|------|
| SFO | Summer Thunderstorm | `sfo_summer_thunderstorm.yaml` |
| SFO | Dense Morning Fog | `sfo_fog_morning.yaml` |
| SFO | Diversions | `sfo_diversions.yaml` |
| SFO | Maximum Stress Test | `sfo_stress_test.yaml` |
| SFO | Go-Around Test | `sfo_go_around_test.yaml` |
| SFO | Thunderstorm Peak | `sfo_thunderstorm_peak.yaml` |
| JFK | Winter Storm | `jfk_winter_storm.yaml` |
| ATL | Summer Thunderstorm | `atl_summer_thunderstorm.yaml` |
| ORD | Winter Blizzard | `ord_winter_blizzard.yaml` |
| LAX | Santa Ana Winds | `lax_santa_ana_winds.yaml` |
| DFW | Tornado Outbreak | `dfw_tornado_outbreak.yaml` |
| DEN | Spring Blizzard | `den_spring_blizzard.yaml` |
| SEA | Atmospheric River | `sea_atmospheric_river_windstorm.yaml` |
| MIA | Tropical Storm | `mia_tropical_storm.yaml` |
| EWR | Ice Storm | `ewr_ice_storm.yaml` |
| BOS | Nor'easter | `bos_noreaster.yaml` |
| PHX | Extreme Heat & Dust | `phx_extreme_heat_dust.yaml` |
| LAS | Haboob | `las_haboob.yaml` |
| MCO | Thunderstorm Complex | `mco_thunderstorm_complex.yaml` |
| CLT | Derecho | `clt_derecho.yaml` |
| MSP | Arctic Blast | `msp_arctic_blast.yaml` |
| DTW | Lake Effect Blizzard | `dtw_lake_effect_blizzard.yaml` |
| PHL | Summer Thunderstorm | `phl_summer_thunderstorm.yaml` |
| IAH | Hurricane Approach | `iah_hurricane_approach.yaml` |
| SAN | Marine/Santa Ana | `san_marine_santa_ana.yaml` |
| PDX | Atmospheric River | `pdx_atmospheric_river.yaml` |
| LHR | Winter Fog | `lhr_winter_fog.yaml` |
| DXB | Sandstorm | `dxb_sandstorm.yaml` |
| NRT | Typhoon | `nrt_typhoon.yaml` |
| SIN | Monsoon | `sin_monsoon.yaml` |
| HKG | Typhoon Signal 8 | `hkg_typhoon_signal8.yaml` |
| CDG | Winter Fog (Freezing) | `cdg_winter_fog_freezing.yaml` |
| FRA | Winter Crosswind | `fra_winter_crosswind.yaml` |
| AMS | North Sea Storm | `ams_north_sea_storm.yaml` |
| SYD | Bushfire Smoke | `syd_bushfire_smoke.yaml` |
| ICN | Monsoon/Typhoon | `icn_monsoon_typhoon.yaml` |
| GRU | Tropical Storm | `gru_tropical_storm.yaml` |
| JNB | Summer Thunderstorm | `jnb_summer_thunderstorm.yaml` |

## Calibrated Airports

43 airports have hand-researched calibration profiles, with a total of 1,183 auto-generated profiles stored in a UC Volume (real-world traffic stats from BTS, OpenSky, OurAirports). Using calibrated airports produces realistic flight counts, airline mixes, and route distributions. On Databricks, profiles are loaded from the UC Volume; locally, they fall back to `data/calibration/profiles/`.

**US:** SFO, JFK, ATL, ORD, LAX, DFW, DEN, SEA, MIA, EWR, BOS, PHX, LAS, MCO, CLT, MSP, DTW, PHL, IAH, SAN, PDX

**International:** LHR, DXB, NRT, SIN, HKG, CDG, FRA, AMS, SYD, ICN, GRU, JNB

Any IATA code from the OurAirports database works — uncalibrated airports use derived defaults based on runway count and region.

## Batch Generation

Generate configs for all calibrated airports at once:

```bash
# 7-day simulations (1000 flights/day each)
python scripts/generate_sim_configs.py

# 1-day simulations
python scripts/generate_sim_configs.py --days 1
```

Outputs to `configs/simulation_{airport}_{duration}.yaml`. Airports with matching scenario files get them auto-linked.

## Running on Databricks

Simulations can run on Databricks serverless compute via DABs jobs:

```bash
# Run a batch of simulations
databricks bundle run simulation_batch_1 --target dev

# Run ML training on simulation outputs
databricks bundle run simulation_train --target dev
```

Job definitions are in `resources/simulation_batch_job.yml`.

## Output

The simulation writes a JSON file with:

- **config** — simulation parameters
- **summary** — KPIs (on-time %, delays, gate utilization, go-arounds, diversions)
- **schedule** — flight schedule with times and gates
- **frames** — position snapshots per timestamp (unless `skip_positions`)
- **phase_transitions** — flight phase changes (ground → taxi → takeoff → ...)
- **gate_events** — gate assign/occupy/release events
- **weather_snapshots** — weather state over time
- **scenario_events** — disruption events that fired

Load the output in the UI by placing the JSON in the app's simulation output directory or uploading via the simulation file picker.

## Examples

### Minimal: Quick Test

```yaml
airport: SFO
arrivals: 10
departures: 10
duration_hours: 4
debug: true
```

### Realistic: Full Day with Weather

```yaml
airport: LHR
arrivals: 500
departures: 500
duration_hours: 24
time_step_seconds: 2.0
seed: 42
scenario_file: scenarios/lhr_winter_fog.yaml
output_file: simulation_lhr_fog.json
```

### Stress Test: Maximum Disruption

```yaml
airport: SFO
arrivals: 500
departures: 500
duration_hours: 24
seed: 1
scenario_file: scenarios/sfo_stress_test.yaml
output_file: simulation_sfo_stress.json
```

### Custom Scenario from Scratch

Create `scenarios/my_custom_scenario.yaml`:

```yaml
name: Custom Afternoon Thunderstorm
description: Thunderstorm hits during afternoon rush, clears by evening.

weather_events:
  - time: "15:00"
    type: thunderstorm
    severity: severe
    duration_hours: 2.0
    visibility_nm: 0.5
    ceiling_ft: 500
    wind_speed_kt: 30
    wind_gusts_kt: 45
    wind_direction: 220

  - time: "17:00"
    type: clear
    severity: light
    duration_hours: 7.0
    visibility_nm: 10.0
    ceiling_ft: 5000
    wind_speed_kt: 10
    wind_direction: 280

runway_events:
  - time: "15:30"
    type: closure
    runway: "28L"
    duration_minutes: 60
    reason: Lightning within 3nm

traffic_modifiers:
  - time: "16:00"
    type: diversion
    extra_arrivals: 6
    diversion_origin: OAK
```

Then run:

```bash
python -m src.simulation.cli --airport SFO --arrivals 200 --departures 200 \
  --scenario scenarios/my_custom_scenario.yaml --output custom_storm.json
```

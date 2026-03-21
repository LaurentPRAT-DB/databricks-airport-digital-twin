# Phase 30: 132 Calibrated Simulations (33 airports x 4 runs each)

## Goal

Generate a large corpus of simulation data for ML model training/retraining: 132 simulations across 33 airports with calibrated profiles, covering both normal operations and challenging weather.

## Status: Plan — Not Started

## Prerequisites: Phase 28 (Calibrate, Not Fabricate) must be complete — calibrated airport profiles for all 33 airports must exist.

---

## Context

The calibrated airport profiles (33 airports, built from real BTS DB28 data) are deployed. We need a large corpus of simulation data for ML model training/retraining. The previous 10-airport batch only covered extreme weather. This new batch covers normal operations (3 runs per airport) plus challenging weather (1 run per airport), all at 36h duration, producing a diverse training dataset.

Total: 33 airports x 4 runs = 132 simulations
- 99 normal-day runs (3 per airport, seeds 100/200/300, no scenario file)
- 33 weather runs (1 per airport, seed 42, with scenario file)

---

## Step 1: Create a Python generator script

**File:** `scripts/generate_calibration_batch.py`

A single script that generates all configs, scenarios, and the job YAML:

### 1a. Normal-day configs (99 files)

In `configs/calibration_batch/`:
- `simulation_{iata}_normal_d1.yaml` (seed=100)
- `simulation_{iata}_normal_d2.yaml` (seed=200)
- `simulation_{iata}_normal_d3.yaml` (seed=300)

Each config:
```yaml
airport: SFO
arrivals: 500
departures: 500
duration_hours: 36
time_step_seconds: 2.0
seed: 100
output_file: simulation_output/cal_sfo_normal_d1.json
```

No `scenario_file` — pure normal-day operations driven by calibrated profiles.

### 1b. Weather scenarios (23 new files)

10 airports already have scenarios. Create 23 new region-appropriate ones in `scenarios/`:

| Airport | Scenario | Key Weather |
|---------|----------|-------------|
| ATL | Summer severe thunderstorm | Thunderstorm, wind shear, flash flooding |
| BOS | Winter nor'easter | Snow, freezing rain, 40kt+ winds |
| CLT | Summer derecho | Severe thunderstorm, wind damage |
| DEN | Spring blizzard | Heavy snow, whiteout, 50kt gusts |
| DFW | Spring tornado outbreak | Severe thunderstorm, hail, tornado warnings |
| DTW | Lake-effect blizzard | Heavy snow bands, low visibility |
| EWR | Winter ice storm | Freezing rain, ice accumulation |
| IAH | Gulf hurricane approach | Tropical storm bands, flooding |
| LAS | Summer haboob | Dust storm, extreme heat, microbursts |
| LAX | Santa Ana wind event | Extreme dry winds, turbulence, smoke |
| MCO | Afternoon thunderstorm complex | Lightning, heavy rain, wind shear |
| MIA | Tropical storm passage | Heavy rain, gusty winds |
| MSP | Winter arctic blast | Extreme cold, blowing snow |
| ORD | Winter blizzard | Heavy snow, ground stop, de-icing |
| PDX | Atmospheric river | Persistent heavy rain, low ceilings |
| PHL | Summer severe thunderstorm | Thunderstorm, hail, wind gusts |
| PHX | Extreme heat + dust storm | 120F+ heat, haboob, microburst |
| SAN | Marine layer + Santa Ana | Dense fog AM, Santa Ana PM |
| SEA | Atmospheric river + windstorm | Heavy rain, 60kt gusts |
| CDG | Winter fog + freezing rain | Dense fog, freezing drizzle |
| AMS | North Sea winter storm | Gale force winds, heavy rain |
| HKG | Typhoon Signal 8 | Typhoon passage, extreme winds |
| ICN | Summer monsoon + typhoon | Heavy rain, gusty winds |

Each follows the existing YAML structure: `weather_events`, `runway_events`, `ground_events`, `traffic_modifiers`.

### 1c. Weather configs (33 files)

In `configs/calibration_batch/`:
- `simulation_{iata}_weather.yaml` (seed=42, with `scenario_file`)

### 1d. Job YAML

**File:** `resources/calibration_batch_job.yml`

132 parallel notebook tasks, all using existing `run_simulation_airport.py`. No analysis task (analysis done separately for ML).

```yaml
resources:
  jobs:
    calibration_batch:
      name: "[${bundle.target}] Airport DT - Calibration Batch (132 sims)"
      tasks:
        - task_key: cal_sfo_normal_d1
          notebook_task:
            notebook_path: ../databricks/notebooks/run_simulation_airport.py
            base_parameters:
              airport: "SFO"
              config_file: "configs/calibration_batch/simulation_sfo_normal_d1.yaml"
        # ... 131 more tasks
      timeout_seconds: 7200
```

---

## Step 2: Run the generator

```bash
uv run python scripts/generate_calibration_batch.py
```

Creates: 132 config YAMLs + 23 scenario YAMLs + 1 job YAML.

---

## Step 3: Deploy and run

```bash
databricks bundle deploy --target dev
databricks bundle run calibration_batch --target dev
```

Existing `run_simulation_airport.py` handles upload to UC Volume + `simulation_runs` table registration for each of the 132 tasks.

---

## Files Created

| Type | Count | Location |
|------|-------|----------|
| Generator script | 1 | `scripts/generate_calibration_batch.py` |
| Normal-day configs | 99 | `configs/calibration_batch/simulation_{iata}_normal_d{1,2,3}.yaml` |
| Weather configs | 33 | `configs/calibration_batch/simulation_{iata}_weather.yaml` |
| New weather scenarios | 23 | `scenarios/{airport}_{weather_type}.yaml` |
| Job definition | 1 | `resources/calibration_batch_job.yml` |

## Files Reused (no modifications)

- `databricks/notebooks/run_simulation_airport.py` — runs sim, uploads to UC Volume, registers in table
- `data/calibration/profiles/*.json` — automatically loaded by simulation engine per airport code
- `scenarios/{10 existing}.yaml` — reused for the 10 airports that already have weather scenarios

---

## Verification

1. Generator produces 132 configs + 23 new scenarios + job YAML
2. `databricks bundle deploy` succeeds
3. `databricks bundle run calibration_batch` starts 132 parallel tasks
4. All 132 tasks PASS — each uploads JSON to UC Volume and registers in `simulation_runs`
5. `SELECT count(*) FROM ...simulation_runs WHERE filename LIKE 'cal_%'` returns 132
6. UC Volume has 132 files: `cal_{iata}_normal_d{1,2,3}.json` + `cal_{iata}_weather.json`

---

## Estimated Scope

- **New files:** 1 generator script + 132 generated configs + 23 generated scenarios + 1 generated job YAML
- **Modified files:** 0
- **Risk:** Low — all generation is scripted, reuses existing simulation infrastructure. Main risk is Databricks job timeout if 132 parallel tasks exceed cluster availability.

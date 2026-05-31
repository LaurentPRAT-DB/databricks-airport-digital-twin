---
title: "Expand Validation Test Suite (10 Missing Tests)"
status: planned
area: testing
priority: medium
related:
  - .planning/validation-gaps/
  - tests/test_bhs_validation.py
  - tests/test_flight_ops_validation.py
  - tests/test_simulation_validation.py
---

# Plan: Expand Validation Test Suite (10 Missing Tests)

## Context

The /validate skill defines 20 validation tests. Currently 10 are implemented (9 passing, 1 failing). The missing 10 tests fall into three categories:

1. Tests that CAN be written now — the simulation already produces the needed data
2. Tests that need thin wrappers — existing modules produce relevant data but aren't wired into recorder/tests
3. Tests blocked by unbuilt modules — need substantial new simulation capabilities

## Current State (What's Working)

| Test | File | Status |
|------|------|--------|
| F01 Checkpoint throughput | test_passenger_flow_validation.py | PASS (4 tests) |
| F02 Terminal dwell time | test_passenger_flow_validation.py | PASS (3 tests) |
| O01 Turnaround adherence | test_flight_ops_validation.py | PASS (4 tests) |
| O02 Runway sequencing | test_flight_ops_validation.py | PASS (4 tests) |
| O03 Gate utilization | test_flight_ops_validation.py | PASS (3 tests) |
| O04 Taxi times | test_flight_ops_validation.py | 5/6 PASS, 1 FAIL (taxi-in median) |
| B02 BHS throughput | test_bhs_validation.py | PASS (4 tests) |
| Calibration taxi/turnaround | test_calibration_taxi_turnaround.py | PASS (8 tests) |
| FIDS accuracy | test_fids_accuracy.py | PASS (12 tests) |
| Structural/physics (P01 proxy) | test_simulation_validation.py | 35 tests (skip without cached data) |

## The 10 Missing Tests — What Can Be Done

### Category A: Write Now (data already available)

**B01 — Baggage Make Time**
- `generate_bags_for_flight()` already produces `check_in_time` per bag
- `simulate_bhs_throughput()` produces `p95_processing_time_min`
- Recorder already captures `baggage_events` per flight
- Action: Add `TestB01BaggageMakeTime` to `test_bhs_validation.py`. Validate P50/P95 processing time against industry benchmarks (domestic: 15-25 min, international: 20-35 min). Validate misconnect rate is 2-6%.

**B03 — Transfer Baggage Connection**
- `generate_bags_for_flight()` already has `connecting_rate`, `connection_time_min`, MCT logic, `_misconnect_probability()` function
- Bags have `is_connecting`, `connecting_flight`, and `status == "misconnect"` fields
- Action: Add `TestB03TransferBaggage` to `test_bhs_validation.py`. Validate: misconnect rate within ±2% of industry (3-6%), MCT breach rate correlates with tight connections.

**P01 — Live KPI Sync**
- `recorder.compute_summary()` already produces: `on_time_pct`, `avg_turnaround_min`, `peak_simultaneous`, `cancellation_rate`, gate utilization
- These ARE the KPIs that would sync to a dashboard
- Action: Add `TestP01KPIConsistency` — validate KPIs are internally consistent (on_time + delay sum to 100%, turnaround > 0, peak < total flights) and within realistic ranges.

**P02 — Delay Propagation**
- Recorder tracks `actual_spawn_time` vs `scheduled_time` + `delay_minutes`
- Phase transitions show turnaround duration
- Late inbound → long turnaround → late outbound IS tracked via `capacity_delays`
- Scenario events track go-arounds and diversions that cause cascading delays
- Action: Add `TestP02DelayPropagation`. Run a scenario (e.g., `sfo_diversions.yaml`) and verify: (a) capacity hold increases after disruption onset, (b) go-arounds/diversions appear, (c) downstream flights show increased delay. Compare pre/post disruption delay distributions.

**D01 — Weather Event Replay**
- 38 scenario YAML files exist with weather events (visibility, ceiling, wind)
- Engine applies weather → capacity reduction → go-arounds/diversions/cancellations
- Recorder captures `scenario_events` with timestamps
- `compute_summary()` has `go_around` count, `diversion` count, `cancellation` count
- Action: Add `TestD01WeatherReplay`. Load `jfk_winter_storm.yaml`, run sim, validate: (a) capacity drops during storm, (b) recovery begins after weather clears (17:00), (c) scenario events timeline matches weather events, (d) recovery slope is reasonable (not instant).

### Category B: Thin wrapper needed (existing modules, not wired to validation)

**R02 — GSE Positioning**
- `src/ml/gse_model.py` `generate_gse_positions()` produces positions with travel times
- `estimate_gse_travel_time()` gives depot → gate time
- Not currently called during simulation loop, but CAN be validated standalone
- Action: Add `TestR02GSEPositioning` to new `test_resource_validation.py`. Call `generate_gse_positions()` for sample gates/phases, validate: `travel_time_min` is 1-8 min range (realistic ramp distance), correct GSE types active per phase, positions form reasonable spatial layout.

**P03 — Capacity Headroom Prediction**
- Engine tracks `_phase_counts` (how many aircraft in each phase)
- `_max_phase_seconds` defines caps
- Phase transitions record timestamps → can compute runway/gate saturation over time
- Action: Add `TestP03CapacityHeadroom`. After running a high-traffic sim, check: peak gate occupancy approaches gate count, runway movements/hour approaches AAR/ADR, and these peaks occur at expected times (not randomly).

### Category C: Blocked (need new module or major work)

- **F03** — Congestion Hotspots → needs spatial passenger agent model (Gap 5)
- **F04** — Retail/F&B Diversion → needs spatial passenger agent model (Gap 5)
- **R01** — Ground Crew Allocation → needs crew scheduling model (not started)
- **R03** — Check-in Desk Staffing → needs spatial passenger agent model (Gap 5)
- **D02** — Mass Re-accommodation → needs passenger rebooking logic
- **D03** — Evacuation Routing → needs building evacuation model

## Implementation Plan

### Step 1: Expand test_bhs_validation.py — add B01 + B03

- Add `TestB01BaggageMakeTime` (3 tests): `has_timing_data`, `p95_within_industry`, `misconnect_rate_realistic`
- Add `TestB03TransferBaggage` (3 tests): `has_connecting_bags`, `misconnect_rate_bounded`, `tight_connections_higher_miss_rate`

### Step 2: Create test_kpi_validation.py — add P01

- Add `TestP01KPIConsistency` (4 tests): `all_kpis_present`, `on_time_in_range`, `turnaround_positive`, `peak_bounded`

### Step 3: Create test_delay_propagation_validation.py — add P02

- Add `TestP02DelayPropagation` (4 tests): `scenario_increases_delay`, `go_arounds_occur`, `capacity_hold_increases`, `recovery_after_disruption`

### Step 4: Create test_disruption_validation.py — add D01

- Add `TestD01WeatherReplay` (4 tests): `weather_reduces_capacity`, `scenario_events_logged`, `recovery_timeline_reasonable`, `flight_counts_reflect_disruption`

### Step 5: Create test_resource_validation.py — add R02 + P03

- Add `TestR02GSEPositioning` (3 tests): `travel_times_realistic`, `correct_gse_per_phase`, `positions_bounded`
- Add `TestP03CapacityHeadroom` (3 tests): `peak_gate_near_capacity`, `peak_runway_near_aar`, `peaks_at_expected_time`

### Step 6: Document remaining gaps

- Update `.planning/validation-gaps/` with clear blockers for F03, F04, R01, R03, D02, D03

## Key Files to Modify/Create

- `tests/test_bhs_validation.py` — expand (add B01, B03)
- `tests/test_kpi_validation.py` — new
- `tests/test_delay_propagation_validation.py` — new
- `tests/test_disruption_validation.py` — new
- `tests/test_resource_validation.py` — new

## Reusable Existing Code

- `src/ingestion/baggage_generator.py`: `generate_bags_for_flight()`, `_misconnect_probability()`, `simulate_bhs_throughput()`
- `src/ml/gse_model.py`: `generate_gse_positions()`, `estimate_gse_travel_time()`
- `src/simulation/engine.py`: `SimulationEngine`, scenario loading
- `src/simulation/recorder.py`: `compute_summary()`, all event lists
- `src/simulation/scenario.py`: `load_scenario()`
- Fixture pattern from `test_flight_ops_validation.py`: module-scoped `sfo_sim` that runs once

## Verification

1. `uv run pytest tests/test_bhs_validation.py tests/test_kpi_validation.py tests/test_delay_propagation_validation.py tests/test_disruption_validation.py tests/test_resource_validation.py -v`
2. All new tests should PASS (they validate realistic ranges, not exact match to nonexistent ground truth)
3. Scenario tests (P02, D01) will run actual sims with scenario files — verify they complete within ~30s each
4. Total validation coverage moves from 10/20 → 17/20 (85%)

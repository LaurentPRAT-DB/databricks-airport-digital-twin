---
title: "Operator-Focused Tests — Gate Allocation, Routes, KPIs"
status: backlog
area: simulation, frontend
priority: high
related:
  - operator-validation-gaps.md
  - ../backlog/v1-readiness-checklist.md
---

# Plan: Operator-Focused Tests — Gate Allocation, Routes, KPIs

## Context

The previous session added 98 frontend tests for SimulationManager, SimulationReport, TimeWindowPicker, sceneCapture, useSimulationDrafts, and useSimulationJobs. Coverage rose from 55% to 61.5%.

Now we need operator-focused tests — what an airport operator cares about: gate double-booking, flight trajectory geometry, and KPI accuracy/visibility. This spans 3 backend test files and 3 frontend test files.

---

## Backend Tests

### 1. `tests/test_kpi_at_scale.py` — KPI accuracy with realistic traffic

**Why:** Existing tests run only 8+8 flights / 3h. An operator needs confidence that KPIs (OTP, delay, capacity hold, gate utilization) remain accurate at 500-flight / 24h scale.

**Fixture:** Module-scoped, SFO, 250 arrivals + 250 departures, 24h, seed=42, diagnostics=True.
**Pattern:** Same as `test_expert_reviews.py` — `SimulationConfig` → `SimulationEngine` → `recorder.compute_summary()`.

**Tests (~8):**
- `test_total_flights_matches_config` — summary.total_flights == arrivals + departures (±spawning failures)
- `test_on_time_pct_realistic` — 60-98% (BTS average ~80%)
- `test_schedule_delay_within_bounds` — 2-30 min average (FAA historical)
- `test_gate_utilization_positive` — gates_used > 0 and ≤ total gate count
- `test_peak_simultaneous_reasonable` — peak_simultaneous_flights between 10-200
- `test_cancellation_rate_low` — < 5% without scenario events
- `test_turnaround_within_bts_range` — avg_turnaround_min between 25-90 (BTS median ~45 for SFO)
- `test_no_nan_or_none_in_summary` — every field is a finite number

### 2. `tests/test_gate_stress.py` — Gate conflicts under operational stress

**Why:** An operator's worst fear is double-booking a gate. Under diversions + runway closures + high traffic, the gate allocator must never assign two aircraft the same gate simultaneously.

**Fixture:** Module-scoped, SFO, 40 arrivals + 40 departures, 8h, seed=42, scenario_file from `configs/scenarios/` (pick `sfo_fog.yaml` or create inline severe scenario with runway_events).

**Tests (~5):**
- `test_no_gate_double_occupancy_under_stress` — scan gate_events: no overlapping occupy periods per gate
- `test_all_arrivals_get_gate` — every arrival that completed taxi has a gate_assign event
- `test_gate_release_before_departure` — departure flights release gate before takeoff
- `test_diversion_frees_gate_slot` — diverted flights don't occupy gates
- `test_turnaround_time_under_stress` — avg turnaround stays ≤ 120 min even during disruption

### 3. `tests/test_kpi_monotonicity.py` — Worse weather → worse KPIs

**Why:** Operators expect that adding fog or closing a runway degrades performance metrics monotonically. If severe weather shows better OTP than clear weather, the sim is broken.

**Approach:** Run 3 configs (same traffic: SFO, 20+20, 6h, seed=42):
1. No scenario (baseline)
2. `sfo_fog.yaml` (moderate disruption)
3. Inline severe scenario: fog + runway closure + capacity reduction

**Tests (~4):**
- `test_otp_degrades_with_severity` — OTP: baseline ≥ moderate ≥ severe
- `test_delay_increases_with_severity` — schedule_delay: baseline ≤ moderate ≤ severe
- `test_cancellations_increase_with_severity` — total_cancellations: baseline ≤ severe
- `test_capacity_hold_increases_with_severity` — avg_capacity_hold_min: baseline ≤ severe

---

## Frontend Tests

### 4. `src/components/KPIDashboard/KPIDashboard.test.tsx` — ML Predictions Dashboard

**Why:** 19% coverage currently. Operators use this to monitor real-time KPIs, congestion, and delay forecasts.

**Pattern:** Mock `usePredictionDashboard` hook via `vi.mock`. No need for MSW since we mock the hook directly.

**Tests (~12):**
- Renders loading state when `isLoading=true`
- Renders error state with message when error set
- Renders KPI cards grid with correct values/colors
- Tab switching: Overview → Congestion → Delay Forecast
- Overview tab shows both congestion and delay tables (sliced to 10)
- Congestion tab shows full congestion table with all rows
- Delays tab shows full delay table with all rows
- Delay table renders category badges (On Time, Slight, Moderate, Severe)
- Congestion table renders level badges (low, moderate, high, critical)
- Fullscreen toggle changes modal class
- Close button calls `onClose`
- Backdrop click calls `onClose`

### 5. `src/hooks/usePredictionDashboard.test.ts` — Hook test

**Why:** 0% coverage. Simple React Query hook wrapping `/api/predictions/dashboard`.

**Pattern:** `renderHook` + `QueryOnlyProvider` wrapper + `globalThis.fetch = vi.fn()`.

**Tests (~5):**
- Returns `isLoading=true` initially, then resolves with dashboard data
- Returns error when fetch fails (non-ok response)
- Respects `enabled=false` (no fetch triggered)
- Retries on failure (up to 2 times)
- Refetches on 30s interval (advance timers)

### 6. `src/components/Map/TrajectoryLine.test.ts` — Trajectory utility functions

**Why:** 0% coverage on pure geometry functions (`splitAtGaps`, `simplify`, `chaikinSmooth`, `perpendicularDist`, `distSq`). These compute the flight route visualization — wrong output means jumpy or incorrect paths.

**Note:** Test only the exported utility functions, not the React component (requires Leaflet mock infrastructure). Import from the source file — may need to add `export` keyword to the 4 utility functions.

**Tests (~14):**
- `distSq`: same point → 0, known pair → correct squared distance
- `splitAtGaps`: no gaps → single segment, gap in middle → 2 segments, multiple gaps → 3 segments, single point → empty, two points far apart → empty (neither segment has ≥2 points)
- `perpendicularDist`: point on line → 0, point perpendicular → correct distance, degenerate line (zero length) → euclidean distance
- `simplify`: straight line → just endpoints, zigzag → reduced points, < 3 points → returned unchanged
- `chaikinSmooth`: straight line → unchanged shape (no sharp turns), triangle → more points, < 3 points → returned unchanged, iterations=0 → same as input

---

## Files to Create/Modify

| File | Action |
|------|--------|
| `tests/test_kpi_at_scale.py` | Create |
| `tests/test_gate_stress.py` | Create |
| `tests/test_kpi_monotonicity.py` | Create |
| `app/frontend/src/components/KPIDashboard/KPIDashboard.test.tsx` | Create |
| `app/frontend/src/hooks/usePredictionDashboard.test.ts` | Create |
| `app/frontend/src/components/Map/TrajectoryLine.test.ts` | Create |
| `app/frontend/src/components/Map/TrajectoryLine.tsx` | Add `export` to 4 utility functions |

## Key Patterns to Reuse

- `tests/test_expert_reviews.py` — module-scoped sim fixture, `recorder.compute_summary(config.model_dump(mode="json"))` for KPI extraction
- `tests/sim_helpers.py` — `extract_flight_traces`, `haversine_nm`, `phase_positions`
- `src/test/test-utils.tsx` — `renderWithQuery()` wrapper for hook tests
- `vi.mock('../../hooks/usePredictionDashboard')` for KPIDashboard component isolation
- `configs/scenarios/sfo_fog.yaml` — existing scenario file for stress tests

## Implementation Order

1. `TrajectoryLine.test.ts` + export fix — pure math, instant feedback
2. `usePredictionDashboard.test.ts` — simple hook
3. `KPIDashboard.test.tsx` — component with mocked hook
4. `test_kpi_at_scale.py` — backend, long-running fixture
5. `test_gate_stress.py` — backend, requires scenario
6. `test_kpi_monotonicity.py` — backend, 3 fixtures

## Verification

```bash
# Frontend (fast)
cd app/frontend && npm test -- --run --reporter=verbose

# Backend (scale test takes ~60s)
uv run pytest tests/test_kpi_at_scale.py tests/test_gate_stress.py tests/test_kpi_monotonicity.py -v

# Coverage check
cd app/frontend && npm run test:coverage
uv run pytest tests/ --cov=src --cov-report=term-missing
```

**Target:** KPIDashboard > 80% lines, TrajectoryLine utilities 100%, usePredictionDashboard 100%, all backend tests green.

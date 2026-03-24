# Trajectory Validation Test Report

## Context

The airport digital twin simulation has 342 trajectory-related tests across 6 test files validating both airborne and ground flight operations. The user wants a professional test report aimed at airport operators and testers, with matplotlib-generated charts showing trajectory behavior (altitude profiles, speed envelopes, phase transitions, ground tracks) — not just pass/fail counts.

---

## Approach

Create a Python script that:
1. Runs a deterministic simulation (SFO, 8 arrivals + 8 departures, 3h)
2. Extracts per-flight trajectory data from the SimulationRecorder
3. Generates 6 matplotlib figures showing key trajectory properties
4. Runs the 6 trajectory test files and captures results
5. Assembles everything into a Markdown report with embedded images

---

## Output

- `reports/trajectory_validation_report.py` — the generator script
- `reports/trajectory_validation/` — output directory with images + markdown report

---

## Figures to Generate

| # | Chart | What it proves |
|---|-------|----------------|
| 1 | Altitude vs Time (multi-flight overlay) | Approaches descend, departures climb, ground ops at 0 ft |
| 2 | Speed vs Phase (box plot) | Taxi <35 kts, approach 120-250 kts, departure 150-300 kts |
| 3 | Phase Transition Diagram (timeline per flight) | Correct phase sequencing, no illegal transitions |
| 4 | Ground Track Map (lat/lon scatter, colored by phase) | Taxi paths near airport, approach/departure corridors radiate out |
| 5 | Heading Consistency (heading change histogram) | No teleportation, smooth turns |
| 6 | Test Results Summary (bar chart — pass/fail/skip by category) | All 342 tests passing |

---

## Report Structure (Markdown)

```
# Airport Digital Twin — Trajectory Validation Report
## Executive Summary (pass rate, airport, sim config)
## 1. Airborne Operations
  - 1.1 Approach Altitude Profile (Fig 1)
  - 1.2 Departure Climb Profile (Fig 1)
  - 1.3 Speed Envelopes (Fig 2)
  - 1.4 Heading Continuity (Fig 5)
## 2. Ground Operations
  - 2.1 Taxi Speed Compliance (Fig 2)
  - 2.2 Parked Aircraft Stability
  - 2.3 Ground Tracks (Fig 4)
## 3. Flight Lifecycle
  - 3.1 Phase Transition Validity (Fig 3)
  - 3.2 Complete Arrival/Departure Cycles
## 4. Separation & Safety
  - 4.1 Approach Separation (3 NM minimum)
  - 4.2 Wake Turbulence Separation
## 5. Test Results (Fig 6)
  - Full breakdown by test file / category
## Appendix: Simulation Parameters
```

---

## Files to Create

| File | Action |
|------|--------|
| `reports/trajectory_validation_report.py` | New — generator script (~400 lines) |

- Uses `SimulationEngine`, `SimulationRecorder`, `SimulationConfig` from `src/simulation/`
- Uses matplotlib for all charts
- Runs pytest programmatically via subprocess to collect results
- Writes `reports/trajectory_validation/report.md` + PNG figures

---

## Verification

```bash
uv run python reports/trajectory_validation_report.py
# -> generates reports/trajectory_validation/report.md + 6 PNGs
# -> opens or displays the report path
```

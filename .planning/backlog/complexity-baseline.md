---
status: backlog
area: code-quality
priority: low
related:
  - .planning/audits/
---

# Cyclomatic Complexity Baseline

**Captured:** 2026-05-23
**Tool:** radon 6.0.1
**Scope:** `src/` + `app/backend/`

## Summary

| Metric | Value |
|--------|-------|
| Total blocks analyzed | 1,618 |
| Average complexity | **C (19.9)** |
| A+B grade (good) | 1,453 (89.8%) |
| C grade (moderate) | 126 (7.8%) |
| D grade (high) | 20 (1.2%) |
| E grade (very high) | 9 (0.6%) |
| F grade (unmaintainable) | 10 (0.6%) |

## F-Grade Functions (CC > 40)

| Function | CC | File:Line |
|----------|-----|-----------|
| `_update_flight_state` | 219 | `src/ingestion/_flight_lifecycle.py:767` |
| `generate_synthetic_trajectory` | 91 | `src/ingestion/_generation.py:650` |
| `generate_synthetic_flights` | 70 | `src/ingestion/_generation.py:343` |
| `get_flights_as_schedule` | 55 | `src/ingestion/_generation.py:165` |
| `parse_otp_prezip` | 55 | `src/calibration/bts_ingest.py:568` |
| `OpenSkyEventInferrer.process_frame` | 46 | `src/inference/opensky_events.py:190` |
| `_execute_tool` | 44 | `app/backend/api/mcp.py:394` |
| `_create_new_flight` | 42 | `src/ingestion/_flight_lifecycle.py:418` |
| `SimulationRecorder.compute_summary` | 41 | `src/simulation/recorder.py:141` |
| `_load_recording_from_raw` | 41 | `app/backend/api/opensky.py:1041` |

## E-Grade Functions (CC 31-40)

| Function | CC | File:Line |
|----------|-----|-----------|
| `_taxi_speed_factor` | 35 | `src/ingestion/_runway_ops.py:462` |
| `build_profile_from_openflights` | 34 | `src/calibration/openflights_ingest.py:249` |
| `SimulationEngine._update_all_flights` | 34 | `src/simulation/engine.py:666` |
| `get_simulation_data` | 34 | `app/backend/api/simulation.py:746` |
| `clean_tile` | 34 | `app/backend/api/inpainting.py:352` |
| `build_profile_from_bts` | 32 | `src/calibration/bts_ingest.py:188` |
| `_format_run` | 32 | `app/backend/api/simulation_jobs.py:152` |
| `generate_daily_schedule` | 24 | `src/ingestion/schedule_generator.py:702` |
| `auto_calibrate_airport` | 29 | `src/calibration/auto_calibrate.py:140` |

## Maintainability Index (worst files)

| File | MI Grade | Score |
|------|----------|-------|
| `app/backend/api/opensky.py` | C | 0.00 |
| `app/backend/services/lakebase_service.py` | C | 0.00 |
| `app/backend/api/routes_airport.py` | C | 8.12 |
| `app/backend/api/simulation.py` | B | 10.05 |
| `app/backend/api/simulation_jobs.py` | B | 11.64 |

## Refactoring Priority

1. **`_update_flight_state` (CC=219)** — god-function, state machine with 219 decision paths. Split into phase-specific handlers.
2. **`_generation.py` (3 F-grade)** — trajectory/flight generation monoliths. Extract per-phase generators.
3. **`_execute_tool` (CC=44)** — MCP tool dispatcher. Convert to dispatch table pattern.
4. **`_load_recording_from_raw` (CC=41)** — recording parser with many format branches. Strategy pattern.

## Goal

Next capture target (after refactoring top offenders):
- Average: B (< 15)
- F-grade: 0
- E-grade: < 5

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-05)

**Core value:** Demonstrate end-to-end data flow through Databricks (ingest to stream to ML to visualize) with a visually compelling, interactive airport model.
**Current focus:** Phase 4 - 3D Visualization

## Current Position

Phase: 4 of 5 (3D Visualization)
Plan: 2 of 3 in current phase
Status: In Progress
Last activity: 2026-03-05 - Completed 04-02 (Aircraft 3D & Integration)

Progress: [=========.] 92%

## Performance Metrics

**Velocity:**
- Total plans completed: 11
- Average duration: 3.8 minutes
- Total execution time: 0.70 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1 | 3 | 12 min | 4.0 min |
| 2 | 3 | 15 min | 5.0 min |
| 3 | 3 | 11 min | 3.7 min |
| 4 | 2 | 6 min | 3.0 min |

**Recent Trend:**
- Last 5 plans: 04-02 (3 min), 04-01 (3 min), 03-03 (4 min), 03-01 (4 min), 03-02 (3 min)
- Trend: Improving

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

**Phase 1:**
- Use dataclasses for flight schemas (lightweight, stdlib)
- 2-minute watermark for late data handling in Silver layer
- Deduplicate by icao24+position_time to prevent duplicates
- Flight phase computed from on_ground and vertical_rate thresholds
- OAuth2 client credentials flow with token caching in client instance
- Quartz cron for 1-minute polling intervals in Databricks job

**Phase 2:**
- FastAPI for backend with Pydantic V2 models
- React + Vite + TypeScript for frontend
- Leaflet for 2D mapping (lighter than MapLibre)
- TanStack Query for data fetching with 5-second polling
- WebSocket for real-time updates with reconnection logic
- Airport layout as GeoJSON in constants/airportLayout.ts

**Phase 3:**
- Rule-based delay model for demo (avoids sklearn dependency)
- Feature engineering extracts 14 features from flight data
- MLflow optional - works without it for local demo
- Confidence scores based on flight phase and altitude
- Prediction service uses asyncio for parallel model execution
- React Query hooks for predictions with 10-second refetch
- Gate recommendations shown only for arriving flights

**Phase 4:**
- Use React 18 compatible versions (fiber@8.15.19, drei@9.99.0)
- Three.js fiber type declarations for JSX intrinsic elements
- Center coordinates 37.62/-122.38 (SFO area) for lat/lon to 3D conversion
- Delta-time based lerp factor for frame-rate independent animation

### Pending Todos

None yet.

### Blockers/Concerns

None yet.

## Session Continuity

Last session: 2026-03-05
Stopped at: Completed 04-02-PLAN.md (Aircraft 3D & Integration)
Resume file: .planning/phases/04-3d-visualization/04-02-SUMMARY.md

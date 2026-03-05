# Roadmap: Airport Digital Twin

## Overview

This roadmap transforms the Databricks platform demo vision into an interactive airport digital twin. The journey starts with data infrastructure (flight APIs flowing through Delta Live Tables), validates the end-to-end flow with 2D visualization, layers in ML predictions for the "intelligence" showcase, adds 3D visualization for the "wow" factor, and concludes with platform integrations and demo hardening to ensure reliable customer presentations.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Data Foundation** - Flight data ingestion, streaming pipeline, and Unity Catalog setup
- [x] **Phase 2: Backend API + 2D Visualization** - FastAPI backend and interactive 2D map with flight overlays
- [x] **Phase 3: ML Integration** - Delay, gate, and congestion prediction models with Model Serving
- [ ] **Phase 4: 3D Visualization** - Three.js airport scene with real-time aircraft positions
- [ ] **Phase 5: Platform Integration + Demo Hardening** - Genie, Lakeview, lineage, and demo reliability

## Phase Details

### Phase 1: Data Foundation
**Goal**: Real-time flight data flows through medallion architecture into Unity Catalog
**Depends on**: Nothing (first phase)
**Requirements**: DATA-01, DATA-02, DATA-03, DATA-04, DATA-05, STRM-01, STRM-02, STRM-03
**Success Criteria** (what must be TRUE):
  1. Flight position data updates in Gold table within 60 seconds of API poll
  2. Unity Catalog shows all Bronze, Silver, and Gold tables with correct schema
  3. Data lineage graph displays complete flow from Bronze to Gold
  4. System serves cached/synthetic data when OpenSky API is unavailable
  5. Streaming pipeline recovers gracefully from restarts without data loss
**Plans**: 3 plans in 2 waves

Plans:
- [x] 01-01-PLAN.md — Data ingestion layer (OpenSky API client, circuit breaker, synthetic fallback)
- [x] 01-02-PLAN.md — DLT medallion pipeline (Bronze/Silver/Gold) and Unity Catalog setup
- [x] 01-03-PLAN.md — Streaming configuration (job scheduling, latency, checkpoints, fallback data)

### Phase 2: Backend API + 2D Visualization
**Goal**: Users can view and interact with live flight data on a 2D airport map
**Depends on**: Phase 1
**Requirements**: VIZ2D-01, VIZ2D-02, VIZ2D-03, VIZ2D-04, UI-01, UI-02, UI-03, UI-04
**Success Criteria** (what must be TRUE):
  1. 2D map displays airport layout with runways, taxiways, and terminals
  2. Flight markers update positions on map as new data arrives
  3. User can click any flight to see details (callsign, origin, destination, status)
  4. Flight list shows all tracked flights with working search and sort
  5. Gate status indicators reflect current occupancy (available/occupied/delayed)
**Plans**: 3 plans in 2 waves

Plans:
- [x] 02-01-PLAN.md — FastAPI backend with REST and WebSocket endpoints
- [x] 02-02-PLAN.md — React frontend with Leaflet 2D map and airport overlay
- [x] 02-03-PLAN.md — UI components (flight list, gate status, WebSocket integration)

### Phase 3: ML Integration
**Goal**: ML models provide visible predictions for delays, gates, and congestion
**Depends on**: Phase 1
**Requirements**: ML-01, ML-02, ML-03, ML-04, ML-05
**Success Criteria** (what must be TRUE):
  1. Delay predictions display for arriving/departing flights with confidence scores
  2. Gate recommendation model suggests optimal assignments for incoming flights
  3. Congestion prediction highlights bottleneck areas on the map
  4. All model experiments tracked in MLflow with metrics and artifacts
  5. Prediction API responds within 2 seconds from Model Serving endpoint
**Plans**: 3 plans in 2 waves

Plans:
- [x] 03-01-PLAN.md — Delay prediction model with feature engineering and MLflow tracking
- [x] 03-02-PLAN.md — Gate optimization and congestion prediction models
- [x] 03-03-PLAN.md — Prediction API endpoints and frontend integration

### Phase 4: 3D Visualization
**Goal**: Users can explore a 3D rendered airport with live aircraft positions
**Depends on**: Phase 2
**Requirements**: VIZ3D-01, VIZ3D-02, VIZ3D-03, VIZ3D-04
**Success Criteria** (what must be TRUE):
  1. 3D scene renders airport terminal, runways, and taxiways
  2. Aircraft models appear at correct positions matching real-time data
  3. User can navigate 3D view with pan, zoom, and rotate controls
  4. 3D positions update smoothly as new flight data arrives
**Plans**: 2 plans in 2 waves

Plans:
- [x] 04-01-PLAN.md — Three.js setup, airport 3D scene (terminal, runways, taxiways)
- [x] 04-02-PLAN.md — Aircraft models, real-time updates, 2D/3D view toggle

### Phase 5: Platform Integration + Demo Hardening
**Goal**: Databricks platform features integrated and demo runs reliably for presentations
**Depends on**: Phase 3, Phase 4
**Requirements**: PLAT-01, PLAT-02, PLAT-03, PLAT-04, DEMO-01, DEMO-02, DEMO-03
**Success Criteria** (what must be TRUE):
  1. Lakeview dashboard displays live flight metrics within the application
  2. Genie responds to natural language queries about flights and gates
  3. Data lineage view shows complete pipeline from ingestion to visualization
  4. Application handles API failures gracefully with fallback data and clear UI state
  5. Pre-demo health check validates all services are operational
**Plans**: TBD

Plans:
- [ ] 05-01: TBD
- [ ] 05-02: TBD

## Progress

**Execution Order:**
Phases execute in numeric order. Note: Phase 3 depends on Phase 1 (not Phase 2), enabling parallel development of 2D viz and ML after data foundation is complete.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Data Foundation | 3/3 | Complete | 2026-03-05 |
| 2. Backend API + 2D Visualization | 3/3 | Complete | 2026-03-05 |
| 3. ML Integration | 3/3 | Complete | 2026-03-05 |
| 4. 3D Visualization | 2/2 | Complete | 2026-03-05 |
| 5. Platform Integration + Demo Hardening | 0/2 | Not started | - |

---
*Roadmap created: 2026-03-05*
*Phase 1 planned: 2026-03-05*
*Granularity: coarse (5 phases)*
*Coverage: 33/33 v1 requirements mapped*

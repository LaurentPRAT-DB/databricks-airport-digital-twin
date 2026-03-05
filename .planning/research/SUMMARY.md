# Project Research Summary

**Project:** Airport Digital Twin
**Domain:** Real-time 3D visualization / Databricks Platform Demo
**Researched:** 2026-03-05
**Confidence:** MEDIUM

## Executive Summary

The Airport Digital Twin is a Databricks demo application designed to showcase the platform's streaming, ML, Unity Catalog, and AI/BI capabilities through an interactive airport visualization. Experts build similar systems using a layered lakehouse architecture: flight data ingested via APIs into Delta Lake (Bronze/Silver/Gold medallion), processed through Delta Live Tables for data quality, surfaced via FastAPI backends, and rendered with React Three Fiber for 3D visualization. The recommended approach prioritizes data infrastructure first (streaming pipeline must work before anything visual), followed by 2D visualization, ML integration, and finally 3D polish.

The key risks center on demo reliability: flight API rate limits can exhaust during presentations, Three.js memory leaks cause browser crashes during extended sessions, and external service dependencies create single points of failure. Mitigation requires an offline-first architecture with aggressive caching, graceful degradation UI states, and pre-computed fallback data. The 3D visualization layer is the highest complexity component and should be built last after the data foundation is stable.

Overall, this is a well-trodden domain with established patterns. The main challenge is not technical novelty but demo hardening - ensuring the system remains impressive and reliable during customer presentations. Build the "boring" data infrastructure first, validate the demo flow works end-to-end with 2D visualization, then add the "wow" factor with 3D.

## Key Findings

### Recommended Stack

The stack follows Databricks APX (Application Platform) standards: React 18 + TypeScript frontend with Vite build tooling, FastAPI backend for async API handling, and Databricks managed services for data/ML. For 3D, React Three Fiber (R3F) is the clear winner - it bridges Three.js with React's component model and prevents the memory management issues of raw Three.js. MapLibre GL JS handles 2D maps without vendor lock-in.

**Core technologies:**
- **React + TypeScript + Vite**: APX standard, type safety essential for complex 3D logic
- **React Three Fiber + drei**: Declarative 3D scenes, proper React lifecycle integration
- **FastAPI + Pydantic**: APX standard, async-first for concurrent API/WebSocket handling
- **MapLibre GL JS + deck.gl**: Open-source maps with WebGL-accelerated data layers
- **Delta Live Tables**: Declarative ETL with built-in data quality expectations
- **MLflow + Model Serving**: Model tracking and real-time inference endpoints

**Flight Data API:** Start with OpenSky Network (free for development), upgrade to ADS-B Exchange for demos ($10/month, better coverage).

### Expected Features

**Must have (table stakes):**
- 2D airport map with flight position markers and status colors
- Flight list/table (departures/arrivals board pattern)
- Real-time data updates with freshness indicators
- Gate assignment display
- Basic metrics dashboard (flight counts, delay averages)
- Click-to-select with detail panel

**Should have (differentiators):**
- 3D airport visualization (the "wow" factor)
- Delay prediction display with ML confidence
- Genie natural language interface
- Unity Catalog data lineage visualization
- Lakeview dashboard embedding

**Defer (v2+):**
- Passenger-level simulation
- Historical replay mode
- Multi-airport views
- Mobile optimization
- Gate optimization ML model
- What-if scenarios

### Architecture Approach

The system follows a layered lakehouse architecture with five distinct tiers: Ingestion (API polling into Bronze tables), Processing (DLT pipeline to Silver/Gold), ML/Serving (MLflow models via Databricks endpoints), API (FastAPI backend), and Presentation (React + Three.js). Data flows unidirectionally from external flight APIs through the medallion architecture into the visualization layer. Real-time updates use WebSocket from FastAPI to frontend, with 45-95 second end-to-end latency from API poll to UI update.

**Major components:**
1. **Data Ingestion Layer** - Scheduled jobs polling flight APIs, writing raw JSON to Bronze tables
2. **DLT Pipeline** - Bronze to Silver to Gold transformation with data quality expectations
3. **FastAPI Backend** - REST endpoints + WebSocket for real-time position streaming
4. **React Frontend** - 2D map (MapLibre) and 3D scene (R3F) consuming backend APIs
5. **ML Serving** - Delay prediction model served via Databricks Model Serving endpoints
6. **Unity Catalog** - Governance layer organizing all tables (bronze/silver/gold schemas)

### Critical Pitfalls

1. **API Rate Limit Exhaustion** - FlightAware/OpenSky rate limits hit during demo. Prevention: 30-60 second caching, circuit breaker pattern, pre-recorded fallback data.

2. **Three.js Memory Leaks** - Browser crashes after 10-15 minutes due to undisposed geometries/materials. Prevention: Strict disposal protocol, object pooling, React Three Fiber for lifecycle management.

3. **Streaming Checkpoint Corruption** - Structured Streaming fails to restart after schema changes. Prevention: Version checkpoint paths, separate dev/demo checkpoints, never share locations.

4. **External Service Dependency** - Demo fails when FlightAware is down or network is slow. Prevention: Offline-first design, health check dashboard, graceful degradation UI showing "cached data" vs crashing.

5. **Model Serving Cold Start** - First prediction takes 30+ seconds. Prevention: Pre-warm endpoints before demo, provisioned concurrency, cache common predictions.

## Implications for Roadmap

Based on research, suggested phase structure:

### Phase 1: Data Foundation
**Rationale:** Everything depends on data being available. Cannot build visualization without flight data flowing. Validate API access and streaming before investing in UI.
**Delivers:** Unity Catalog setup, Bronze table ingestion, DLT pipeline (Bronze to Silver), scheduled polling job
**Addresses:** Real-time updates (table stakes), data freshness indicators
**Avoids:** Checkpoint corruption (versioned paths from start), API rate limits (caching layer built in)

### Phase 2: Backend API
**Rationale:** Frontend needs an API to develop against. Depends on Gold tables from Phase 1.
**Delivers:** FastAPI scaffold, SQL Warehouse integration, REST endpoints (flights, gates, metrics), health check
**Uses:** FastAPI, Pydantic, Databricks SQL Connector
**Implements:** API/Service Layer from architecture

### Phase 3: 2D Visualization
**Rationale:** 2D is simpler than 3D and validates data flow end-to-end. Proves the demo works before adding complexity.
**Delivers:** React app scaffold, 2D map with flight overlays, flight list, filter controls, detail panel
**Addresses:** All table stakes visualization features
**Avoids:** Over-engineering 3D before data flow validated

### Phase 4: ML Integration
**Rationale:** Can develop in parallel with Phase 3 to some extent. Needs stable Gold tables. Showcases core Databricks ML capabilities.
**Delivers:** Delay prediction model training, MLflow tracking, Model Serving deployment, prediction endpoint in backend, prediction display in UI
**Avoids:** Cold start issues (build pre-warm script), over-complex models (start with one simple model)

### Phase 5: 3D Visualization
**Rationale:** Highest complexity, most impressive. Build only after data pipeline and 2D are stable. The "wow" factor deserves polish time.
**Delivers:** Three.js scene setup, generic airport geometry, aircraft models/positions, real-time position updates, camera controls
**Avoids:** Memory leaks (disposal protocol), hardware performance issues (quality presets, 2D fallback)

### Phase 6: Platform Integration
**Rationale:** Builds on all previous phases. Showcases Databricks-specific capabilities that differentiate from generic digital twins.
**Delivers:** Genie natural language integration, Lakeview dashboard embedding, Unity Catalog lineage visualization, SQL query playground
**Avoids:** Genie query failures (scripted queries, semantic layer config)

### Phase 7: Demo Hardening
**Rationale:** Polish phase to ensure reliability during customer presentations. Address all "moderate" pitfalls.
**Delivers:** Offline mode, pre-demo health checks, fallback scripts, extended run testing, hardware matrix testing
**Addresses:** All external service dependency risks

### Phase Ordering Rationale

- **Data before UI**: Cannot visualize what doesn't exist. Phase 1 must complete before Phase 3-5.
- **2D before 3D**: Validates end-to-end flow with simpler technology. If 2D doesn't work, 3D won't either.
- **ML after data stability**: ML models depend on consistent Gold table features.
- **Platform integration late**: Genie, Lakeview are enhancement features, not core demo flow.
- **Hardening last**: Cannot harden until you know what needs hardening.

### Research Flags

**Phases likely needing deeper research during planning:**
- **Phase 5 (3D Visualization):** Three.js/R3F performance optimization, airport geometry creation, object pooling patterns
- **Phase 6 (Platform Integration):** Genie API specifics, Lakeview embedding authentication, semantic layer configuration

**Phases with standard patterns (skip research-phase):**
- **Phase 1 (Data Foundation):** Well-documented DLT patterns, standard API ingestion
- **Phase 2 (Backend API):** FastAPI is straightforward, many examples available
- **Phase 3 (2D Visualization):** MapLibre + deck.gl well-documented

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM | Versions based on training data, verify current npm/pip versions before starting |
| Features | MEDIUM | Feature landscape well-understood for digital twins, Databricks-specific features should be validated |
| Architecture | MEDIUM | Standard lakehouse patterns, APX framework specifics should be verified against docs |
| Pitfalls | HIGH | Memory leaks, rate limits, checkpoint issues are well-documented failure modes |

**Overall confidence:** MEDIUM

### Gaps to Address

- **Current API pricing/limits**: Verify OpenSky and ADS-B Exchange current terms before committing to data source
- **APX framework current state**: Databricks Apps may have evolved; verify app.yaml format and deployment process
- **Genie API availability**: Confirm Genie can be integrated into custom apps vs Databricks UI only
- **MapLibre + R3F integration**: Research if hybrid 2D/3D views require special handling
- **Model Serving warm-up**: Verify provisioned concurrency availability and pricing

## Sources

### Primary (HIGH confidence)
- Training data on Three.js memory management patterns
- Training data on Databricks Structured Streaming checkpoint behavior
- Training data on React Three Fiber architecture

### Secondary (MEDIUM confidence)
- Training data on Databricks platform services (DLT, MLflow, Unity Catalog)
- Training data on flight data API providers (FlightAware, OpenSky, ADS-B Exchange)
- Training data on FastAPI/React architecture patterns

### Tertiary (LOW confidence - needs validation)
- Current versions of all libraries (verify via npm/pip before development)
- Databricks Apps (APX) current deployment patterns
- Genie integration capabilities for custom apps

---
*Research completed: 2026-03-05*
*Ready for roadmap: yes*

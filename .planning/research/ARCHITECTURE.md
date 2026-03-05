# Architecture Patterns

**Domain:** Airport Digital Twin Demo
**Researched:** 2026-03-05
**Confidence:** MEDIUM (based on established Databricks patterns; web verification unavailable)

## Recommended Architecture

The airport digital twin follows a **layered lakehouse architecture** with real-time streaming capabilities, organized into five major layers.

### High-Level Architecture

```
+------------------------------------------------------------------+
|                     PRESENTATION LAYER                            |
|  +-------------------+  +------------------+  +----------------+  |
|  | Databricks App    |  | AI/BI Dashboard  |  | Genie         |  |
|  | (React + Three.js)|  | (Lakeview)       |  | (NL Queries)  |  |
|  +-------------------+  +------------------+  +----------------+  |
+------------------------------------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                      API/SERVICE LAYER                            |
|  +-----------------------------------------------------------+   |
|  |              FastAPI Backend (APX Framework)              |   |
|  |  - REST endpoints for frontend                            |   |
|  |  - WebSocket for real-time updates                        |   |
|  |  - Authentication via Databricks SDK                      |   |
|  +-----------------------------------------------------------+   |
+------------------------------------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                      ML/SERVING LAYER                             |
|  +------------------+  +------------------+  +----------------+   |
|  | Delay Prediction |  | Gate Assignment  |  | Congestion     |  |
|  | Model (MLflow)   |  | Model (MLflow)   |  | Model (MLflow) |  |
|  +------------------+  +------------------+  +----------------+   |
|  +-----------------------------------------------------------+   |
|  |            Model Serving Endpoints (Databricks)           |   |
|  +-----------------------------------------------------------+   |
+------------------------------------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                    PROCESSING LAYER                               |
|  +-----------------------------------------------------------+   |
|  |              Delta Live Tables Pipeline                    |   |
|  |  Bronze (raw) --> Silver (clean) --> Gold (aggregated)    |   |
|  +-----------------------------------------------------------+   |
|  +-----------------------------------------------------------+   |
|  |              Structured Streaming Jobs                     |   |
|  |  (continuous ingestion from flight APIs)                   |   |
|  +-----------------------------------------------------------+   |
+------------------------------------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                     STORAGE LAYER                                 |
|  +-----------------------------------------------------------+   |
|  |                  Delta Lake Tables                         |   |
|  |  (managed via Unity Catalog)                               |   |
|  |  - flights_raw, flights_clean, flights_agg                 |   |
|  |  - predictions, gate_assignments, alerts                   |   |
|  +-----------------------------------------------------------+   |
+------------------------------------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                    INGESTION LAYER                                |
|  +-----------------------------------------------------------+   |
|  |              Flight Data APIs                              |   |
|  |  - FlightAware API / ADS-B Exchange / OpenSky Network     |   |
|  +-----------------------------------------------------------+   |
+------------------------------------------------------------------+
```

## System Components

### 1. Data Ingestion Layer

**Responsibility:** Pull real-time flight data from external APIs into Databricks.

| Component | Technology | Purpose |
|-----------|------------|---------|
| API Connector | Python (requests/httpx) | Poll external flight APIs |
| Ingestion Job | Databricks Job (scheduled) | Orchestrate API calls every 30-60 seconds |
| Raw Landing | Delta Table (Bronze) | Store raw JSON responses |

**Communicates With:**
- External flight APIs (outbound HTTP)
- Delta Lake storage (write)
- Unity Catalog (metadata registration)

**Notes:**
- Rate limits on flight APIs (typically 500-1000 requests/day on free tiers)
- Consider ADS-B Exchange or OpenSky Network for cost-effective options
- Databricks Secrets for API key management

### 2. Processing Layer (Streaming + DLT)

**Responsibility:** Transform raw flight data into clean, enriched, aggregated forms.

| Component | Technology | Purpose |
|-----------|------------|---------|
| Streaming Ingestion | Structured Streaming | Continuous processing of new data |
| DLT Pipeline | Delta Live Tables | Bronze -> Silver -> Gold transformation |
| Data Quality | DLT Expectations | Validate data quality, track violations |

**Communicates With:**
- Bronze tables (read)
- Silver/Gold tables (write)
- Unity Catalog (lineage tracking)

**Pipeline Stages:**

```
Bronze (Raw)          Silver (Clean)         Gold (Aggregated)
+----------------+    +------------------+   +------------------+
| flights_raw    | -> | flights_clean    | ->| flight_metrics   |
| - raw JSON     |    | - parsed fields  |   | - hourly stats   |
| - ingest_ts    |    | - deduped        |   | - delay averages |
| - source_api   |    | - enriched       |   | - gate util      |
+----------------+    +------------------+   +------------------+
                      | airport_ref      |   | current_state    |
                      | - gate info      |   | - live positions |
                      | - runway info    |   | - active flights |
                      +------------------+   +------------------+
```

### 3. ML/Serving Layer

**Responsibility:** Train, serve, and invoke ML models for predictions.

| Component | Technology | Purpose |
|-----------|------------|---------|
| Model Training | MLflow + Spark ML | Train delay/gate/congestion models |
| Model Registry | MLflow Registry | Version control, stage promotion |
| Model Serving | Databricks Model Serving | REST endpoints for inference |
| Feature Store | Unity Catalog Feature Store | Consistent feature engineering |

**Communicates With:**
- Gold tables (read features)
- Model Serving endpoints (expose)
- FastAPI backend (invoked by)
- Unity Catalog (model governance)

**Models:**

| Model | Input Features | Output | Use Case |
|-------|----------------|--------|----------|
| Delay Predictor | origin, dest, carrier, time, weather | delay_minutes (regression) | Show predicted delays on UI |
| Gate Optimizer | flight_schedule, gate_availability, aircraft_type | optimal_gate_id | Suggest gate assignments |
| Congestion Predictor | current_flights, time_of_day, historical_patterns | congestion_score (0-1) | Color-code terminal areas |

### 4. API/Service Layer (FastAPI Backend)

**Responsibility:** Expose data and predictions to frontend via REST/WebSocket.

| Component | Technology | Purpose |
|-----------|------------|---------|
| REST API | FastAPI | CRUD operations, queries |
| WebSocket | FastAPI WebSocket | Real-time flight position updates |
| Auth | Databricks SDK | Workspace authentication |
| Queries | Databricks SQL Connector | Read from Delta tables |

**Communicates With:**
- Delta Lake (read via SQL Warehouse)
- Model Serving endpoints (invoke)
- React frontend (serve)
- Unity Catalog (permission checks)

**Key Endpoints:**

```
GET  /api/flights              # Current flight list
GET  /api/flights/{id}         # Single flight details
GET  /api/flights/{id}/predict # Delay prediction
GET  /api/gates                # Gate status
GET  /api/metrics              # Aggregated metrics
WS   /ws/positions             # Real-time position stream
GET  /api/health               # Health check
```

### 5. Presentation Layer

**Responsibility:** Render interactive visualizations for users.

| Component | Technology | Purpose |
|-----------|------------|---------|
| 2D Map | React + Leaflet/MapLibre | Interactive airport map |
| 3D View | React + Three.js/R3F | 3D airport visualization |
| Dashboards | AI/BI Lakeview | Business analytics |
| NL Interface | Genie | Natural language queries |

**Communicates With:**
- FastAPI backend (REST/WebSocket)
- Embedded dashboards (iframe)

**React Component Structure:**

```
App
+-- Layout
    +-- Header (flight search, mode toggle)
    +-- MainView
    |   +-- Map2D (Leaflet with flight overlay)
    |   +-- Map3D (Three.js scene)
    |   +-- FlightList (sidebar)
    +-- Dashboard (embedded Lakeview)
    +-- Footer (status, refresh indicator)
```

### 6. Governance Layer (Unity Catalog)

**Responsibility:** Data governance, access control, lineage tracking.

| Component | Purpose |
|-----------|---------|
| Catalog | Organize all tables under single catalog |
| Schema | Separate schemas for bronze/silver/gold |
| Tables | Managed Delta tables with lineage |
| Volumes | Store static assets (airport geometry, etc.) |
| Functions | Registered UDFs for transformations |
| Models | ML models registered for governance |

**Naming Convention:**

```
airport_digital_twin          # Catalog
  +-- bronze                  # Schema
  |   +-- flights_raw
  |   +-- weather_raw
  +-- silver
  |   +-- flights_clean
  |   +-- airport_reference
  +-- gold
  |   +-- flight_metrics
  |   +-- current_state
  +-- ml
      +-- delay_predictor
      +-- gate_optimizer
      +-- congestion_predictor
```

## Data Flow Diagram

```
                              EXTERNAL
                                 |
                    +------------v------------+
                    |     Flight APIs         |
                    | (FlightAware/ADS-B/etc) |
                    +------------+------------+
                                 |
                                 | HTTP/REST (poll every 30-60s)
                                 v
+-------------------------------------------------------------------+
|                         DATABRICKS                                 |
|                                                                    |
|   +-------------------+                                           |
|   | Ingestion Job     |    Write raw JSON                         |
|   | (Scheduled)       |--------------------------------+          |
|   +-------------------+                                |          |
|                                                        v          |
|   +---------------------------------------------------+--+       |
|   |                  DELTA LAKE                          |       |
|   |  +-------------+  +-------------+  +-------------+   |       |
|   |  | Bronze      |->| Silver      |->| Gold        |   |       |
|   |  | flights_raw |  | flights_    |  | flight_     |   |       |
|   |  |             |  | clean       |  | metrics     |   |       |
|   |  +-------------+  +-------------+  +-------------+   |       |
|   |                        |                |            |       |
|   +------------------------|----------------|------------+       |
|                            |                |                    |
|   +-------------------+    |                |                    |
|   | DLT Pipeline      |<---+                |                    |
|   | (continuous)      |                     |                    |
|   +-------------------+                     |                    |
|                                             |                    |
|   +------------------------------------------+---+               |
|   |              ML LAYER                        |               |
|   |  +-------------+  +-------------+            |               |
|   |  | Feature     |<-| Gold tables |            |               |
|   |  | Engineering |  +-------------+            |               |
|   |  +------+------+                             |               |
|   |         |                                    |               |
|   |         v                                    |               |
|   |  +-------------+  +-------------+            |               |
|   |  | MLflow      |->| Model       |            |               |
|   |  | Training    |  | Registry    |            |               |
|   |  +-------------+  +------+------+            |               |
|   |                          |                   |               |
|   |                          v                   |               |
|   |                   +-------------+            |               |
|   |                   | Model       |            |               |
|   |                   | Serving     |            |               |
|   |                   +------+------+            |               |
|   +--------------------------|-------------------+               |
|                              |                                   |
|   +--------------------------|-------------------+               |
|   |              DATABRICKS APP                  |               |
|   |                          |                   |               |
|   |  +-------------+  +------v------+            |               |
|   |  | SQL         |  | FastAPI     |            |               |
|   |  | Warehouse   |<-| Backend     |<--+        |               |
|   |  +-------------+  +------+------+   |        |               |
|   |                          |          |        |               |
|   |                          | REST/WS  | invoke |               |
|   |                          v          |        |               |
|   |                   +-------------+   |        |               |
|   |                   | React       |---+        |               |
|   |                   | Frontend    |            |               |
|   |                   +------+------+            |               |
|   +--------------------------|-------------------+               |
|                              |                                   |
+------------------------------|-----------------------------------+
                               |
                               v
                          USER BROWSER
                    (2D map, 3D view, dashboards)
```

## Component Interactions

### Real-Time Position Updates Flow

```
1. Scheduled Job polls Flight API
2. Raw data written to Bronze table
3. DLT pipeline processes to Silver/Gold
4. FastAPI backend queries SQL Warehouse
5. WebSocket pushes update to React frontend
6. Three.js updates aircraft positions in 3D view
```

**Latency Budget:**
- API poll: 30-60 seconds
- DLT processing: 10-30 seconds
- SQL query: 1-5 seconds
- WebSocket push: <1 second
- Total: ~45-95 seconds end-to-end

### Prediction Request Flow

```
1. User clicks flight in UI
2. React sends GET /api/flights/{id}/predict
3. FastAPI retrieves flight features from SQL Warehouse
4. FastAPI invokes Model Serving endpoint
5. Model returns delay prediction
6. FastAPI formats and returns to UI
7. React displays prediction overlay
```

**Latency Budget:**
- Frontend -> Backend: 50-100ms
- Feature retrieval: 100-500ms
- Model inference: 50-200ms
- Total: ~200-800ms

### Dashboard Integration Flow

```
1. Lakeview dashboard configured to query Gold tables
2. Dashboard embedded in React app via iframe
3. User can interact directly or via Genie
4. Genie queries translated to SQL against Gold tables
```

## Suggested Build Order

Based on dependencies, build in this order:

### Phase 1: Foundation (Data Infrastructure)

**Build:**
1. Unity Catalog setup (catalog, schemas)
2. Bronze table schema definition
3. Basic ingestion job (single API, manual trigger)
4. Simple DLT pipeline (Bronze -> Silver only)

**Why First:** Everything else depends on data being available. Validate API access and basic data flow before building consumers.

**Validates:**
- API connectivity and rate limits
- Data schema understanding
- DLT pipeline mechanics

### Phase 2: Data Maturity (Processing)

**Build:**
1. Complete DLT pipeline (Silver -> Gold)
2. Data quality expectations
3. Scheduled ingestion (continuous)
4. Reference data tables (gates, runways)

**Why Second:** Gold tables needed for ML features and API queries. Reference data needed for enrichment.

**Validates:**
- Data quality assumptions
- Aggregation logic
- End-to-end streaming latency

### Phase 3: Backend API

**Build:**
1. FastAPI project scaffold (APX template)
2. SQL Warehouse connection
3. REST endpoints (read-only first)
4. Health check and basic auth

**Why Third:** Depends on Gold tables existing. Frontend needs API to develop against.

**Validates:**
- APX framework integration
- SQL Warehouse query patterns
- Authentication flow

### Phase 4: Frontend Shell

**Build:**
1. React app scaffold
2. 2D map with mock data
3. Flight list component
4. API integration (replace mock data)

**Why Fourth:** Depends on API. Start with 2D (simpler) before 3D.

**Validates:**
- APX frontend deployment
- API consumption patterns
- Real-time update approach

### Phase 5: ML Models

**Build:**
1. Feature engineering notebooks
2. Delay prediction model (simplest)
3. MLflow tracking integration
4. Model Serving deployment
5. Backend endpoint integration

**Why Fifth:** Needs stable Gold tables. Can develop in parallel with Phase 4 to some extent.

**Validates:**
- Feature availability
- Model accuracy
- Serving latency

### Phase 6: 3D Visualization

**Build:**
1. Three.js scene setup
2. Generic airport geometry
3. Aircraft models/positions
4. Real-time position updates
5. Camera controls and interaction

**Why Sixth:** Highest complexity, needs stable data flow first. Most impressive demo feature, save for polish phase.

**Validates:**
- Performance with many objects
- Real-time update rendering
- User interaction patterns

### Phase 7: Integration & Polish

**Build:**
1. Additional ML models (gate, congestion)
2. WebSocket for real-time updates
3. Lakeview dashboard integration
4. Genie integration
5. Error handling and edge cases

**Why Last:** Polish and integration after core working.

**Validates:**
- Full end-to-end demo flow
- Multi-model orchestration
- Dashboard embedding

## Dependency Graph

```
[Unity Catalog Setup]
         |
         v
[Bronze Tables] --> [DLT Pipeline] --> [Gold Tables]
         |                                   |
         |                                   +--------+
         |                                            |
         v                                            v
[Scheduled Ingestion]                        [ML Feature Engineering]
                                                      |
                                                      v
                                             [ML Model Training]
                                                      |
                                                      v
                                             [Model Serving]
                                                      |
         +---------------------------+                |
         |                           |                |
         v                           v                v
[FastAPI Backend] <----- [SQL Warehouse] -----> [REST Endpoints]
         |                                            |
         v                                            v
[React Frontend] --------------------------------> [2D Map]
         |                                            |
         v                                            v
[Three.js Integration] -----------------------> [3D Visualization]
         |
         v
[Dashboard Embedding] --> [Genie Integration]
```

## Technology Selection Rationale

| Component | Choice | Why |
|-----------|--------|-----|
| Backend | FastAPI | APX standard, async support, OpenAPI docs |
| Frontend | React | APX standard, component ecosystem |
| 3D Engine | Three.js (via R3F) | Industry standard, React integration |
| 2D Map | MapLibre GL JS | Open source, performant, customizable |
| Streaming | Structured Streaming | Native Databricks, exactly-once semantics |
| ETL | Delta Live Tables | Declarative, auto-scaling, quality built-in |
| ML | MLflow + Spark ML | Native Databricks, unified tracking |
| Storage | Delta Lake | ACID, time travel, Unity Catalog integration |
| Governance | Unity Catalog | Required for Databricks, lineage tracking |

## Scalability Considerations

| Concern | Demo Scale (10 flights) | Production Scale (1000+ flights) |
|---------|------------------------|----------------------------------|
| Ingestion | Single job, manual | Parallel jobs, auto-scaling |
| Processing | DLT on-demand | DLT continuous, multiple pipelines |
| Storage | Single cluster | Multiple warehouses, caching |
| Serving | Single endpoint | Load-balanced endpoints |
| Frontend | Client-side filtering | Server-side pagination |

For demo purposes, optimize for visual impact and simplicity over scale.

## Anti-Patterns to Avoid

### 1. Polling from Frontend
**What:** Frontend making direct API calls to flight data sources
**Why Bad:** Rate limits, CORS issues, no data persistence
**Instead:** Backend polls, stores in Delta, frontend reads from backend

### 2. Skipping Bronze Layer
**What:** Transforming data before storage
**Why Bad:** Lose raw data for debugging, can't replay/reprocess
**Instead:** Always land raw first, transform in subsequent layers

### 3. Synchronous ML Inference in DLT
**What:** Calling model serving from DLT pipeline
**Why Bad:** Latency, coupling, harder to debug
**Instead:** Keep DLT for data transformation, call models from API layer

### 4. Embedding Secrets in Code
**What:** API keys in notebooks or app code
**Why Bad:** Security risk, visible in version control
**Instead:** Use Databricks Secrets, reference by scope/key

### 5. Over-Engineering the Airport Model
**What:** Detailed airport geometry before data flow works
**Why Bad:** High effort, low learning, hard to pivot
**Instead:** Start with simple shapes, add detail incrementally

## Sources

- Databricks documentation (established patterns)
- Training data knowledge of Databricks platform architecture
- Standard digital twin architectural patterns

**Note:** Web verification was unavailable during research. Recommend validating APX framework specifics and current API availability against official Databricks documentation.

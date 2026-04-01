# Airport Digital Twin — Complete Technical Specification

**Version:** 1.0
**Date:** 2026-03-10
**Author:** Reverse-engineered from implemented codebase
**Status:** Post-implementation specification (as-built)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Business Context & Objectives](#2-business-context--objectives)
3. [Scope & Boundaries](#3-scope--boundaries)
4. [Stakeholders & Users](#4-stakeholders--users)
5. [System Architecture](#5-system-architecture)
6. [Data Architecture](#6-data-architecture)
7. [Backend Specification](#7-backend-specification)
8. [Frontend Specification](#8-frontend-specification)
9. [Machine Learning Specification](#9-machine-learning-specification)
10. [Data Pipeline Specification](#10-data-pipeline-specification)
11. [Airport Data Import Specification](#11-airport-data-import-specification)
12. [Multi-Airport Support](#12-multi-airport-support)
13. [Synthetic Data Generation](#13-synthetic-data-generation)
14. [Platform Integration](#14-platform-integration)
15. [Deployment & Infrastructure](#15-deployment--infrastructure)
16. [Security Specification](#16-security-specification)
17. [Testing Strategy](#17-testing-strategy)
18. [Non-Functional Requirements](#18-non-functional-requirements)
19. [Data Dictionary](#19-data-dictionary)
20. [API Reference](#20-api-reference)

---

## 1. Executive Summary

### 1.1 Product Vision

An interactive airport digital twin demonstration application showcasing the full Databricks platform stack. The system visualizes real-time airport operations through 2D maps, 3D visualizations, and AI/BI dashboards — all powered by flight data flowing through the Databricks lakehouse architecture.

### 1.2 Core Value Proposition

Demonstrate end-to-end data flow through Databricks (ingest → stream → ML → visualize) with a visually compelling, interactive airport model that customers and prospects can explore during sales presentations and field engineering engagements.

### 1.3 Technology Stack

| Layer | Technology |
|-------|------------|
| **Frontend** | React 18, TypeScript, Three.js, React Three Fiber, Leaflet, Tailwind CSS, Vite |
| **Backend** | Python 3.11+, FastAPI, UV (package manager) |
| **Data Platform** | Databricks (Unity Catalog, Lakebase Autoscaling, DLT, MLflow, Lakeview, Genie) |
| **Data Formats** | AIXM 5.1.1, OpenStreetMap (Overpass API), IFC4, AIDM 12.0, FAA NASR |
| **Deployment** | Databricks Apps (APX framework), Databricks Asset Bundles (DABs) |

---

## 2. Business Context & Objectives

### 2.1 Purpose

This application serves as a customer demonstration tool for Databricks Field Engineering. The goal is to show prospects and customers what is possible with the Databricks platform through an engaging, visually impressive domain (airports).

### 2.2 Demo Objectives

| Capability | What to Demonstrate | Platform Feature |
|------------|---------------------|-----------------|
| **Streaming** | Real-time data from flight APIs flowing through Structured Streaming | Structured Streaming, Auto Loader |
| **Medallion Architecture** | Bronze → Silver → Gold data transformation | Delta Live Tables |
| **ML/AI** | Multiple models making predictions visible in the UI | MLflow, Model Serving |
| **Governance** | Lineage tracking, data discovery, access control | Unity Catalog |
| **Analytics** | Interactive dashboards and natural language queries | Lakeview, Genie |
| **Low-Latency Serving** | Sub-10ms query response for frontend | Lakebase (PostgreSQL) |
| **Application Hosting** | Full-stack web application on Databricks | Databricks Apps (APX) |

### 2.3 Target Audience

- **Primary:** Customer prospects during sales presentations
- **Secondary:** Existing customers exploring Databricks capabilities
- **Tertiary:** Internal Databricks field engineers for training and demos

### 2.4 Success Criteria

1. Application loads and displays flight data within 5 seconds
2. All Databricks platform features visually accessible from the UI
3. Demo runs reliably without external dependencies (synthetic fallback)
4. Supports switching between 43+ known airports worldwide (1183 calibration profiles)
5. 3D visualization provides "wow factor" for presentations

---

## 3. Scope & Boundaries

### 3.1 In Scope (v1 — Implemented)

| Category | Features |
|----------|----------|
| **Data Ingestion** | OpenSky Network API integration, synthetic fallback, circuit breaker |
| **Data Pipeline** | DLT Bronze/Silver/Gold layers, Unity Catalog registration |
| **ML Models** | Delay prediction, gate recommendation, congestion prediction |
| **2D Visualization** | Leaflet map with OSM airport overlay, flight markers, trajectories |
| **3D Visualization** | Three.js airport scene, GLTF aircraft models, real-time positions |
| **UI Components** | Flight list, flight detail, FIDS, weather widget, gate status, data ops dashboard |
| **Multi-Airport** | 43 known airport profiles + 1183 calibration profiles + custom ICAO input, dynamic OSM import |
| **Platform** | Lakeview dashboards, Genie NL queries, data lineage, MLflow tracking |
| **Baggage** | DLT pipeline (bronze/silver/gold), synthetic generation, API endpoints |
| **Weather** | Synthetic METAR/TAF, flight category display, diurnal patterns |
| **GSE** | Turnaround tracking, GSE allocation model, progress visualization |

### 3.2 In Scope (v2 — Implemented)

| Feature | Status |
|---------|--------|
| FIDS (Flight Information Display System) | Implemented (synthetic only) |
| Weather widget | Implemented (synthetic only) |
| GSE/Turnaround model | Implemented (backend + partial frontend) |
| Baggage handling system | Implemented (backend + frontend + DLT pipeline) |
| Multi-airport OSM support | Implemented (43 known airports, 1183 calibration profiles) |
| Per-airport ML model registry | Implemented |
| ML training data persistence | Implemented |
| MCP Server | Implemented (13 tools via JSON-RPC 2.0) |
| Unified LLM Assistant | Implemented (routes to Genie or MCP) |
| Simulation engine | Implemented (calibrated, physics-based, with OpenAP profiles) |
| Satellite inpainting | Implemented (aircraft removal from tiles) |
| MSFS BGL import | Implemented (scenery file parsing) |

### 3.3 Out of Scope

| Feature | Reason |
|---------|--------|
| Real airport-specific fixed layouts | Generic approach more flexible, no licensing concerns |
| Passenger-level simulation | High complexity, does not showcase Databricks well |
| Historical replay mode | Focus on real-time demo |
| Mobile-first UI | Desktop demo presentations are primary use case |
| Multi-language support | English-only for demo purposes |
| Real-time chat/collaboration | Not relevant to digital twin demo |

---

## 4. Stakeholders & Users

### 4.1 User Personas

| Persona | Role | Needs |
|---------|------|-------|
| **Demo Presenter** | Field Engineer conducting customer demo | Reliable, visually impressive, easy to narrate |
| **Customer Viewer** | Prospect watching demo | Understand Databricks capabilities through familiar domain |
| **Technical Evaluator** | Customer's technical staff | See architecture, data flow, code quality |
| **Data Scientist** | Customer data science team | Understand ML model patterns, MLflow integration |
| **Admin** | Person setting up the demo | Easy deployment, health checks, configuration |

### 4.2 User Stories

#### Demo Presenter
- As a presenter, I can switch between airports to show worldwide support
- As a presenter, I can toggle 2D/3D views to demonstrate visualization capabilities
- As a presenter, I can click flights to show ML predictions (delays, gate recommendations)
- As a presenter, I can open FIDS to show a familiar airport display
- As a presenter, I can show platform links (Lakeview, Genie, lineage) directly from the app
- As a presenter, I can rely on synthetic data when live APIs are unavailable

#### Technical Evaluator
- As an evaluator, I can see the data flowing through the medallion architecture
- As an evaluator, I can verify Unity Catalog governance and lineage
- As an evaluator, I can inspect ML model tracking in MLflow
- As an evaluator, I can query data via Genie with natural language

---

## 5. System Architecture

### 5.1 High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                      AIRPORT DIGITAL TWIN                            │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌────────────────── FRONTEND (React + TypeScript) ──────────────┐  │
│  │                                                                │  │
│  │  ┌───────────┐  ┌───────────┐  ┌──────────┐  ┌────────────┐ │  │
│  │  │ Leaflet   │  │ Three.js  │  │  FIDS    │  │  Weather   │ │  │
│  │  │ 2D Map    │  │ 3D Scene  │  │  Modal   │  │  Widget    │ │  │
│  │  └───────────┘  └───────────┘  └──────────┘  └────────────┘ │  │
│  │  ┌───────────┐  ┌───────────┐  ┌──────────┐  ┌────────────┐ │  │
│  │  │ Flight    │  │ Flight    │  │  Gate    │  │  Airport   │ │  │
│  │  │ List      │  │ Detail    │  │  Status  │  │  Selector  │ │  │
│  │  └───────────┘  └───────────┘  └──────────┘  └────────────┘ │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                              │                                       │
│                    REST API + WebSocket                               │
│                              │                                       │
│  ┌────────────────── BACKEND (FastAPI + Python) ─────────────────┐  │
│  │                                                                │  │
│  │  ┌─── API Layer ───┐  ┌─── Service Layer ───┐                │  │
│  │  │ routes.py        │  │ flight_service      │                │  │
│  │  │ websocket.py     │  │ prediction_service  │                │  │
│  │  │ predictions.py   │  │ delta_service       │                │  │
│  │  │ data_ops.py      │  │ lakebase_service    │                │  │
│  │  └──────────────────┘  │ airport_config_svc  │                │  │
│  │                        │ schedule_service    │                │  │
│  │  ┌─── ML Layer ────┐  │ weather_service     │                │  │
│  │  │ delay_model      │  │ gse_service         │                │  │
│  │  │ gate_model       │  │ baggage_service     │                │  │
│  │  │ congestion_model │  │ data_generator_svc  │                │  │
│  │  │ gse_model        │  │ data_ops_service    │                │  │
│  │  │ registry         │  └─────────────────────┘                │  │
│  │  │ features         │                                         │  │
│  │  │ training         │                                         │  │
│  │  └──────────────────┘                                         │  │
│  │                                                                │  │
│  │  ┌─── Data Layer ──┐  ┌─── Format Parsers ──┐                │  │
│  │  │ fallback.py      │  │ OSM (Overpass API)  │                │  │
│  │  │ opensky_client   │  │ AIXM 5.1.1         │                │  │
│  │  │ circuit_breaker  │  │ IFC4               │                │  │
│  │  │ schedule_gen     │  │ AIDM 12.0          │                │  │
│  │  │ weather_gen      │  │ FAA NASR           │                │  │
│  │  │ baggage_gen      │  └────────────────────┘                │  │
│  │  └──────────────────┘                                         │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                              │                                       │
│  ┌────────────────── DATABRICKS PLATFORM ────────────────────────┐  │
│  │                                                                │  │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐ │  │
│  │  │ Unity       │  │ Lakebase     │  │ DLT Pipeline         │ │  │
│  │  │ Catalog     │  │ (PostgreSQL) │  │ Bronze→Silver→Gold   │ │  │
│  │  │ (Governed)  │  │ (<10ms)      │  │                      │ │  │
│  │  └─────────────┘  └──────────────┘  └──────────────────────┘ │  │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐ │  │
│  │  │ MLflow      │  │ Lakeview     │  │ Genie                │ │  │
│  │  │ Experiments │  │ Dashboards   │  │ NL Queries           │ │  │
│  │  └─────────────┘  └──────────────┘  └──────────────────────┘ │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

### 5.2 Data Flow Architecture

```
Data Sources          Ingestion         Processing          Serving           Application
─────────────        ──────────        ───────────         ────────          ────────────

OpenSky API ──┐
              ├─→ Poll Job ──→ Cloud Storage ──→ DLT Bronze ──→ DLT Silver ──→ DLT Gold
Synthetic  ───┘    (1 min)     (JSON files)     (raw ingest)   (cleaned)     (aggregated)
Fallback                                                                          │
                                                                                  │
                                                          Unity Catalog ←─────────┘
                                                               │
                                                    ┌──────────┼──────────┐
                                                    │          │          │
                                              Lakebase    Databricks   Lakeview
                                              (<10ms)     SQL (~100ms) Dashboards
                                                    │                     │
                                                    └─────────┬───────────┘
                                                              │
                                                      FastAPI Backend
                                                              │
                                                    ┌─────────┼─────────┐
                                                    │         │         │
                                               REST API   WebSocket  ML Predictions
                                                    │         │         │
                                                    └─────────┼─────────┘
                                                              │
                                                      React Frontend
```

### 5.3 Fallback Chain

The system uses a cascading data source strategy:

```
1. TRY LAKEBASE (PostgreSQL)     → Latency: <10ms   → data_source="live"
2. FALLBACK TO DELTA TABLES      → Latency: ~100ms  → data_source="live"
3. FALLBACK TO SYNTHETIC DATA    → Latency: <5ms    → data_source="synthetic"
```

---

## 6. Data Architecture

### 6.1 Storage Tiers

| Tier | Technology | Purpose | Latency | Capacity |
|------|------------|---------|---------|----------|
| **Hot Serving** | Lakebase Autoscaling (PostgreSQL) | Real-time frontend queries | <10ms P99 | Current state only |
| **Warm Analytics** | Unity Catalog (Delta Tables) | Analytics, lineage, governance | ~100ms | Full history |
| **Cold Storage** | Cloud Object Storage | Raw ingested files | N/A | Unlimited |

### 6.2 Unity Catalog Structure

```
serverless_stable_3n0ihb_catalog
└── airport_digital_twin
    ├── flight_status_gold            # Current positions (DLT Gold, real-time)
    ├── flight_positions_history      # Trajectory history (append-only)
    ├── flights_bronze                # Raw OpenSky data
    ├── flights_silver                # Cleaned, validated positions
    ├── baggage_bronze                # Raw baggage events
    ├── baggage_silver                # Validated baggage events
    └── baggage_gold                  # Aggregated baggage metrics
```

### 6.3 Lakebase Configuration

```
Host:     ep-summer-scene-d2ew95fl.database.us-east-1.cloud.databricks.com
Endpoint: projects/airport-digital-twin/branches/production/endpoints/primary
Database: databricks_postgres
Schema:   public
Auth:     OAuth (Databricks Apps) / Direct credentials (local dev)
```

### 6.4 DLT Medallion Architecture

| Layer | Table | Source | Transformations | Quality Checks |
|-------|-------|--------|-----------------|----------------|
| **Bronze** | `flights_bronze` | Cloud Storage (Auto Loader) | Add `_ingested_at`, `_source_file` | None (raw) |
| **Silver** | `flights_silver` | `flights_bronze` (streaming) | Explode states array, map columns, trim callsigns, dedup | `valid_position`, `valid_icao24`, `valid_altitude` |
| **Gold** | `flight_status_gold` | `flights_silver` (streaming) | GroupBy `icao24`, last values, compute `flight_phase` | N/A |
| **Baggage Bronze** | `baggage_bronze` | Baggage event stream | Raw event ingestion | None |
| **Baggage Silver** | `baggage_silver` | `baggage_bronze` | Validate bag IDs, status codes | `valid_bag_id`, `valid_status` |
| **Baggage Gold** | `baggage_gold` | `baggage_silver` | Per-flight aggregation (counts, rates) | N/A |

---

## 7. Backend Specification

### 7.1 Application Structure

```
app/backend/
├── main.py                          # FastAPI app setup, lifespan, CORS, static files
├── api/
│   ├── routes.py                    # REST endpoints (flights, schedule, weather, airport, etc.)
│   ├── websocket.py                 # WebSocket for real-time flight updates
│   ├── predictions.py               # ML prediction endpoints
│   ├── data_ops.py                  # Data operations monitoring endpoints
│   ├── simulation.py                # Simulation file management and demo endpoints
│   ├── assistant.py                 # Unified LLM assistant (Genie + MCP routing)
│   ├── genie.py                     # Genie natural language query endpoints
│   ├── mcp.py                       # MCP JSON-RPC 2.0 server (13 tools)
│   └── inpainting.py               # Satellite tile inpainting endpoints
├── models/
│   ├── flight.py                    # FlightPosition, FlightListResponse, TrajectoryPoint
│   ├── airport_config.py            # ImportResponse, AirportConfigResponse
│   ├── schedule.py                  # ScheduledFlight, ScheduleResponse
│   ├── weather.py                   # METAR, TAF, WeatherResponse
│   ├── gse.py                       # GSEUnit, TurnaroundStatus, GSEFleetStatus
│   └── baggage.py                   # Bag, FlightBaggageStats, BaggageAlert
└── services/
    ├── flight_service.py            # Flight data orchestration (Lakebase → Delta → Synthetic)
    ├── prediction_service.py        # ML prediction orchestration (async)
    ├── delta_service.py             # Databricks SQL queries via warehouse
    ├── lakebase_service.py          # PostgreSQL queries via psycopg2
    ├── airport_config_service.py    # Airport config singleton (OSM/AIXM/IFC import)
    ├── data_generator_service.py    # Periodic synthetic data refresh
    ├── schedule_service.py          # FIDS schedule generation
    ├── weather_service.py           # Weather data (synthetic METAR/TAF)
    ├── gse_service.py               # Ground support equipment status
    ├── baggage_service.py           # Baggage handling statistics
    ├── data_ops_service.py          # Pipeline health monitoring
    ├── demo_simulation_service.py   # Demo simulation orchestration
    └── mcp_connection_service.py    # MCP UC connection management
```

### 7.2 Application Lifecycle

1. **FastAPI starts** → Accepts requests immediately (health check available)
2. **Background init kicks off** (async task):
   a. Load airport config from Lakebase cache → Unity Catalog → OSM fallback
   b. Initialize gate positions from OSM data
   c. Initialize ML model registry for default airport (KSFO)
   d. Generate initial synthetic flight data (50 flights)
   e. Start periodic data refresh (every 5 seconds)
3. **`/api/ready` returns `ready: true`** → Frontend shows main UI
4. **Periodic refresh** continues generating updated synthetic positions

### 7.3 Service Layer Design

All services use the **singleton pattern** via factory functions:

```python
_instance = None

def get_flight_service() -> FlightService:
    global _instance
    if _instance is None:
        _instance = FlightService()
    return _instance
```

**FlightService** orchestrates data retrieval with fallback:
1. Try Lakebase (PostgreSQL) → <10ms
2. Try Delta tables (Databricks SQL) → ~100ms
3. Fall back to synthetic data → <5ms

### 7.4 WebSocket Specification

| Endpoint | Purpose | Protocol |
|----------|---------|----------|
| `ws://host/ws/flights` | Real-time flight position updates | JSON messages every 5s |
| Progress broadcasts | Airport switch progress notifications | JSON with `type: "progress"` |

**Flight Update Message:**
```json
{
  "type": "flights",
  "data": {
    "flights": [...],
    "count": 50,
    "timestamp": "2026-03-10T12:00:00Z",
    "data_source": "synthetic"
  }
}
```

**Progress Message:**
```json
{
  "type": "progress",
  "step": 3,
  "totalSteps": 7,
  "message": "Resetting flight state...",
  "icaoCode": "KJFK",
  "done": false
}
```

---

## 8. Frontend Specification

### 8.1 Application Structure

```
app/frontend/src/
├── App.tsx                              # Root: providers, layout, loading screen
├── main.tsx                             # Entry point (React root)
├── components/
│   ├── AirportSelector/
│   │   ├── AirportSelector.tsx          # Dropdown with 43 known airports + custom ICAO
│   │   └── AirportSwitchProgress.tsx    # Progress overlay during airport switch
│   ├── Map/
│   │   ├── AirportMap.tsx               # Leaflet 2D map container
│   │   ├── AirportOverlay.tsx           # OSM polygon/polyline rendering
│   │   ├── FlightMarker.tsx             # Individual flight marker on map
│   │   └── TrajectoryLine.tsx           # Flight path visualization
│   ├── Map3D/
│   │   ├── AirportScene.tsx             # Three.js scene with ground, runways
│   │   ├── Aircraft3D.tsx               # 3D aircraft positioning
│   │   ├── GLTFAircraft.tsx             # GLTF model loader
│   │   ├── ProceduralAircraft.tsx       # Procedural fallback aircraft
│   │   ├── Building3D.tsx               # 3D terminal buildings
│   │   ├── Terminal3D.tsx               # Terminal extrusion from OSM
│   │   ├── Trajectory3D.tsx             # 3D trajectory visualization
│   │   └── Map3D.tsx                    # 3D map container
│   ├── FlightList/
│   │   ├── FlightList.tsx               # Searchable, sortable flight list
│   │   └── FlightRow.tsx                # Individual flight row component
│   ├── FlightDetail/
│   │   ├── FlightDetail.tsx             # Selected flight information panel
│   │   └── TurnaroundTimeline.tsx       # GSE turnaround progress bar
│   ├── FIDS/
│   │   └── FIDS.tsx                     # Flight Information Display modal
│   ├── Header/
│   │   └── Header.tsx                   # Top bar with controls and status
│   ├── Weather/
│   │   └── WeatherWidget.tsx            # METAR/TAF display in header
│   ├── GateStatus/
│   │   └── GateStatus.tsx               # Terminal gate occupancy panel
│   ├── Baggage/
│   │   └── BaggageStatus.tsx            # Baggage statistics widget
│   ├── DataOps/
│   │   └── DataOpsDashboard.tsx         # Pipeline monitoring dashboard
│   └── PlatformLinks/
│       └── PlatformLinks.tsx            # Links to Lakeview, Genie, etc.
├── context/
│   ├── FlightContext.tsx                # Global flight state (selected, list)
│   └── AirportConfigContext.tsx         # Airport config (OSM data, center)
├── hooks/
│   ├── useFlights.ts                    # Flight data fetching + polling
│   ├── useWebSocket.ts                  # WebSocket connection management
│   ├── useAirportConfig.ts              # Airport config data hook
│   ├── usePredictions.ts                # ML prediction fetching
│   ├── useTrajectory.ts                 # Flight trajectory fetching
│   └── useViewportState.ts              # Shared 2D/3D viewport state
├── config/
│   ├── aircraftModels.ts               # GLTF model configuration per airline
│   └── buildingModels.ts               # Building model configuration
├── constants/
│   ├── airport3D.ts                     # 3D scene constants
│   ├── airportLayout.ts                 # 2D layout GeoJSON
│   └── airportSeparation.test.ts        # Separation constant tests
├── types/
│   ├── flight.ts                        # Flight TypeScript interfaces
│   ├── airportFormats.ts                # Airport data format types
│   └── three-fiber.d.ts                 # Three.js type declarations
├── utils/
│   └── map3d-calculations.ts            # Lat/lon to 3D coordinate conversion
└── test/
    ├── setup.ts                         # Test configuration
    ├── test-utils.tsx                   # Custom render with providers
    └── mocks/
        ├── handlers.ts                  # MSW API mock handlers
        └── server.ts                    # MSW server setup
```

### 8.2 Component Hierarchy

```
App
├── AirportConfigProvider (Context)
│   └── FlightProvider (Context)
│       └── AppContent
│           ├── LoadingScreen (shown until backend ready)
│           ├── Header
│           │   ├── AirportSelector
│           │   │   └── AirportSwitchProgress
│           │   ├── WeatherWidget
│           │   ├── FIDS button
│           │   └── PlatformLinks
│           ├── FlightList
│           │   └── FlightRow (×N)
│           ├── Map View (2D or 3D)
│           │   ├── AirportMap (2D)
│           │   │   ├── AirportOverlay (OSM data)
│           │   │   ├── FlightMarker (×N)
│           │   │   └── TrajectoryLine
│           │   └── Map3D (3D, lazy loaded)
│           │       ├── AirportScene
│           │       ├── Aircraft3D (×N)
│           │       │   ├── GLTFAircraft
│           │       │   └── ProceduralAircraft (fallback)
│           │       ├── Building3D / Terminal3D
│           │       └── Trajectory3D
│           ├── FlightDetail
│           │   └── TurnaroundTimeline
│           ├── GateStatus
│           └── FIDS (modal, conditional)
```

### 8.3 State Management

| State | Location | Scope | Update Frequency |
|-------|----------|-------|-----------------|
| Flight positions | `FlightContext` | Global | Every 5s (WebSocket) |
| Selected flight | `FlightContext` | Global | On user click |
| Airport config (OSM) | `AirportConfigContext` | Global | On airport switch |
| Current airport code | `AirportConfigContext` | Global | On airport switch |
| View mode (2D/3D) | `AppContent` local state | Page | On toggle click |
| FIDS visibility | `AppContent` local state | Page | On button click |
| Backend readiness | `AppContent` local state | Page | Polled until ready |
| Shared viewport | `useViewportState` hook | Page | On map interaction |

### 8.4 Data Fetching Strategy

| Data | Method | Frequency | Fallback |
|------|--------|-----------|----------|
| Flight positions | WebSocket (`ws/flights`) | Every 5s push | REST polling `/api/flights` |
| Airport config | REST (`/api/airport/config`) | On airport switch | Cached in context |
| Weather | REST (`/api/weather/current`) | Every 5 min | None (hides widget) |
| Schedule (FIDS) | REST (`/api/schedule/*`) | Every 60s | None |
| Predictions | REST (`/api/predictions/*`) | On flight selection | None |
| Trajectory | REST (`/api/flights/{id}/trajectory`) | On "Show Trajectory" click | Synthetic |
| Backend readiness | REST (`/api/ready`) | Every 1.5s until ready | Loading screen |

### 8.5 3D Visualization Details

| Feature | Implementation |
|---------|---------------|
| **Coordinate System** | Geo coords → 3D via `latLonTo3D()`: `x = (lon - centerLon) × SCALE × cos(centerLat)`, `z = (centerLat - lat) × SCALE` |
| **SCALE factor** | 10,000 (1 degree ≈ 10,000 scene units) |
| **Aircraft models** | GLTF files for major airlines (United, Delta, American, etc.) with procedural box fallback |
| **Aircraft scale** | 0.015 for GLTF models (tuned for visual proportionality) |
| **Camera** | OrbitControls: position [0, 800, 1200], target [0, 0, 0], FOV 45° |
| **Ground plane** | 6000×6000 plane at y=0, color `#2d5016` |
| **Runways** | Box geometry extruded from config coordinates, color `#333333` |
| **Terminals** | Extruded OSM polygons, height 30 units, color `#4a6fa5` |
| **Lighting** | Ambient (0.4) + Directional (0.8) from [500, 1000, 500] |

### 8.6 Preset Airports

| ICAO | IATA | Airport | Location |
|------|------|---------|----------|
| KSFO | SFO | San Francisco International | San Francisco, CA |
| KJFK | JFK | John F. Kennedy International | New York, NY |
| KLAX | LAX | Los Angeles International | Los Angeles, CA |
| KORD | ORD | O'Hare International | Chicago, IL |
| KATL | ATL | Hartsfield-Jackson Atlanta | Atlanta, GA |
| EGLL | LHR | London Heathrow | London, UK |
| LFPG | CDG | Charles de Gaulle | Paris, France |
| OMAA | AUH | Abu Dhabi International | Abu Dhabi, UAE |
| OMDB | DXB | Dubai International | Dubai, UAE |
| RJTT | HND | Tokyo Haneda | Tokyo, Japan |
| VHHH | HKG | Hong Kong International | Hong Kong |
| WSSS | SIN | Singapore Changi | Singapore |

---

## 9. Machine Learning Specification

### 9.1 Model Overview

| Model | Type | Input | Output | Latency |
|-------|------|-------|--------|---------|
| **Delay Prediction** | Rule-based heuristic | FeatureSet (14 features) | delay_minutes, confidence, category | <1ms |
| **Gate Recommendation** | Scoring optimization | Flight + Gate status | gate_id, score, reasons, taxi_time | <5ms |
| **Congestion Prediction** | Capacity thresholds | All flight positions | area congestion levels per zone | <10ms |
| **GSE Allocation** | Phase-dependency model | Aircraft type + gate | turnaround timeline + GSE assignment | <1ms |

### 9.2 Feature Engineering

**Module:** `src/ml/features.py`

14 total features (4 numeric + 3 distance one-hot + 3 altitude one-hot + 4 heading one-hot):

| Feature | Type | Derivation |
|---------|------|------------|
| `hour_of_day` | Normalized float (0-1) | `hour / 23.0` |
| `day_of_week` | Normalized float (0-1) | `weekday / 6.0` |
| `is_weekend` | Binary (0/1) | `weekday >= 5` |
| `velocity_normalized` | Float (0-1) | `velocity_kts / 500` |
| `distance_short` | One-hot | Velocity < 300kts or altitude < 5000m |
| `distance_medium` | One-hot | Velocity 300-400kts and altitude 5000-10000m |
| `distance_long` | One-hot | Velocity > 400kts and altitude > 10000m |
| `altitude_ground` | One-hot | on_ground or altitude < 1000m |
| `altitude_low` | One-hot | 1000m - 5000m |
| `altitude_cruise` | One-hot | > 5000m |
| `heading_N` | One-hot | 315° - 45° |
| `heading_E` | One-hot | 45° - 135° |
| `heading_S` | One-hot | 135° - 225° |
| `heading_W` | One-hot | 225° - 315° |

### 9.3 Delay Prediction Model

**Module:** `src/ml/delay_model.py`

**Algorithm:** Rule-based with additive factors + random noise

| Factor | Condition | Delay Impact | Confidence Impact |
|--------|-----------|-------------|-------------------|
| Peak morning | hour in [7, 8, 9] | +15 min | -0.1 |
| Peak evening | hour in [17, 18, 19] | +12 min | -0.1 |
| Weekend | day_of_week >= 5 | -3 min | +0.05 |
| Ground | altitude_category == "ground" | +8 min | +0.1 |
| Low altitude | altitude_category == "low" | +3 min | 0 |
| Cruising | altitude_category == "cruise" | -2 min | -0.1 |
| Slow speed | velocity < 0.1 (normalized) | +5 min | 0 |
| Random noise | Always | ±5 min | 0 |

**Output Categories:**
- `on_time`: <5 min delay
- `slight`: 5-15 min delay
- `moderate`: 15-30 min delay
- `severe`: >30 min delay

### 9.4 Gate Recommendation Model

**Module:** `src/ml/gate_model.py`

**Scoring (max 1.0):**
- **Availability (50%):** Available=0.5, Delayed=0.2, Occupied/Maintenance=0
- **Terminal Match (25%):** International→Terminal B=0.25, Domestic→Terminal A=0.25, else=0.1
- **Runway Proximity (15%):** Lower gate numbers = higher score
- **Delay Penalty (10%):** >30 min delay = -0.1

**International Detection:** Callsign prefix not in `{AAL, UAL, DAL, SWA, JBU, NKS, ASA, FFT, SKW}`

### 9.5 Congestion Prediction Model

**Module:** `src/ml/congestion_model.py`

**Areas Monitored:** 6 default zones (2 runways, 2 taxiways, 2 aprons) defined by lat/lon bounding boxes

**Congestion Levels:**

| Level | Capacity Ratio | Wait Times (runway / taxiway / apron) |
|-------|---------------|---------------------------------------|
| LOW | <50% | 0 / 0 / 0 min |
| MODERATE | 50-75% | 3 / 2 / 1 min |
| HIGH | 75-90% | 8 / 5 / 3 min |
| CRITICAL | >90% | 15 / 10 / 5 min |

### 9.6 Per-Airport Model Registry

**Module:** `src/ml/registry.py`

The `AirportModelRegistry` maintains per-airport model instances cached by ICAO code. When switching airports:
1. Check cache for existing models
2. If miss, create new model instances configured for the airport
3. Retrain with airport-specific gate layout from OSM data
4. Cache for subsequent requests

### 9.7 MLflow Integration

- **Experiment Tracking:** All model training runs logged to MLflow
- **Metrics:** Category distribution, feature importance, prediction accuracy
- **Artifacts:** Model configuration, training data snapshots
- **Training Data Persistence:** Synthetic training data persisted to Unity Catalog for reproducibility

---

## 10. Data Pipeline Specification

### 10.1 Ingestion Layer

#### OpenSky Network Client (`src/ingestion/opensky_client.py`)

| Parameter | Value |
|-----------|-------|
| **Endpoint** | `https://opensky-network.org/api/states/all` |
| **Bounding Box** | lat: 36.0-39.0, lon: -124.0 to -120.0 (SFO area) |
| **Poll Interval** | Every 1 minute |
| **Timeout** | 10 seconds |
| **Rate Limit** | Anonymous: 10 req/min, Authenticated: 100 req/min |

#### Circuit Breaker (`src/ingestion/circuit_breaker.py`)

| Parameter | Value |
|-----------|-------|
| Failure threshold | 5 consecutive failures |
| Recovery timeout | 60 seconds |
| Half-open requests | 1 |

**States:** CLOSED (normal) → OPEN (bypass API, use fallback) → HALF_OPEN (test recovery)

#### Poll Job (`src/ingestion/poll_job.py`)

**Output Path:** `/mnt/airport_digital_twin/raw/opensky/{date}/{timestamp}.json`
**Schedule:** `*/1 * * * *` (every minute)

### 10.2 DLT Pipeline Libraries

Defined in `databricks/dlt_pipeline_config.json` — 6 libraries:
1. `src/pipelines/bronze.py` — Flight Bronze
2. `src/pipelines/silver.py` — Flight Silver
3. `src/pipelines/gold.py` — Flight Gold
4. `src/pipelines/baggage_bronze.py` — Baggage Bronze
5. `src/pipelines/baggage_silver.py` — Baggage Silver
6. `src/pipelines/baggage_gold.py` — Baggage Gold

### 10.3 Synchronization

**UC → Lakebase Sync:**
- **Frequency:** Every 1 minute
- **Strategy:** Full UPSERT on `icao24` primary key
- **Filter:** Only flights seen within last 5 minutes

---

## 11. Airport Data Import Specification

### 11.1 Supported Formats

| Format | Standard | Parser Module | Data Content |
|--------|----------|---------------|-------------|
| **AIXM 5.1.1** | ICAO/Eurocontrol | `src/formats/aixm/` | Runways, taxiways, aprons, navaids |
| **OSM** | OpenStreetMap | `src/formats/osm/` | Terminals, gates, taxiways, aprons (via Overpass API) |
| **IFC4** | buildingSMART | `src/formats/ifc/` | 3D terminal building geometry |
| **AIDM 12.0** | Eurocontrol | `src/formats/aidm/` | Flight schedules, resource allocations |
| **FAA NASR** | US FAA | `src/formats/faa/` | US runway and facility data |

### 11.2 OSM Import Flow (Primary)

```
1. User selects airport (ICAO code)
2. Backend queries Overpass API for aeroway features within airport boundary
3. Parser extracts: terminals (polygons), gates (points), taxiways (lines), aprons (polygons)
4. Converter transforms to internal format with geo coordinates
5. Airport config service merges into singleton config
6. Frontend receives config via REST API
7. AirportOverlay renders on Leaflet map
8. Terminal3D/Building3D renders in Three.js scene
```

### 11.3 Import API Endpoints

| Endpoint | Method | Input | Purpose |
|----------|--------|-------|---------|
| `/api/airport/import/osm` | POST | `icao_code` query param | Fetch from Overpass API |
| `/api/airport/import/aixm` | POST | XML body | Parse AIXM file |
| `/api/airport/import/ifc` | POST | Binary body | Parse IFC file |
| `/api/airport/import/aidm` | POST | JSON/XML body | Parse AIDM data |
| `/api/airport/import/faa` | POST | `facility_id` query param | Fetch FAA NASR data |

---

## 12. Multi-Airport Support

### 12.1 Airport Switch Sequence

```
User clicks new airport
         │
         ▼
POST /api/airports/{icao}/activate
         │
         ├─ Step 1: Load config (Lakebase cache → UC → OSM fallback)
         ├─ Step 2: Reload gates, swap ML models to airport-specific
         ├─ Step 3: Set airport center, reset synthetic state
         ├─ Step 4: Generate new synthetic flights (background)
         ├─ Steps 5-6: Generate schedule, weather data
         └─ Step 7: Broadcast "Airport ready" via WebSocket
         │
         ▼
Frontend receives config → Updates map center, overlay, flights
```

### 12.2 Per-Airport State

Each airport switch affects:
- Airport config (terminals, gates, taxiways, aprons)
- Airport center coordinates (lat/lon)
- Synthetic flight generator (positions around new airport)
- ML model registry (retrained with new gate layout)
- Weather station (ICAO code)
- Flight schedule (airport-specific airline mix)

### 12.3 Persistence Strategy

```
First visit:  OSM fetch → Cache to Unity Catalog tables → Serve to frontend
Repeat visit: Load from Unity Catalog → Serve to frontend (skip OSM)
Refresh:      Re-fetch from OSM → Update Unity Catalog → Serve to frontend
```

---

## 13. Synthetic Data Generation

### 13.1 Flight Position Generator (`src/ingestion/fallback.py`)

**Generates:** 50 flights with realistic positions, trajectories, and separations

**Flight Phases:**
```
APPROACH → FINAL → LANDING → TAXI_IN → PARKED → PUSHBACK → TAXI_OUT → TAKEOFF → DEPARTURE
```

**Separation Standards (FAA/ICAO):**

| Lead → Follow | SUPER | HEAVY | LARGE | SMALL |
|--------------|-------|-------|-------|-------|
| SUPER | 4 NM | 6 NM | 7 NM | 8 NM |
| HEAVY | — | 4 NM | 5 NM | 6 NM |
| LARGE | — | — | 3 NM | 4 NM |
| SMALL | — | — | — | 3 NM |

**Runway Occupancy:** Single occupancy enforced. Landing/takeoff clearance requires empty runway.

**Gate Management:** 5+ gates (from OSM), single occupancy, 60s cooldown after departure.

### 13.2 Schedule Generator (`src/ingestion/schedule_generator.py`)

- 300-500 flights/day with peak hour distribution
- Airline mix: UAL 35%, DAL 15%, AAL 15%, SWA 10%, international 25%
- 15% delayed (80% minor 5-30 min, 20% major 30-120 min)
- IATA delay codes for realistic delay reasons

### 13.3 Weather Generator (`src/ingestion/weather_generator.py`)

- METAR format with realistic diurnal patterns
- Morning fog (6-9am): 20% probability, visibility 0.5-3 SM
- Afternoon convection: 10% chance gusty winds
- Flight categories: VFR, MVFR, IFR, LIFR
- 10-minute cache intervals for consistency

### 13.4 Baggage Generator (`src/ingestion/baggage_generator.py`)

- 1.2 bags per passenger, 82% load factor
- 15% connecting bags, 2% misconnect rate
- Status progression: checked_in → security → sorted → loaded → in_transit → unloaded → on_carousel → claimed

### 13.5 GSE Model (`src/ml/gse_model.py`)

- Turnaround phases with dependencies (Gantt logic)
- Narrow body: 45 min total, Wide body: 90 min total
- GSE allocation by aircraft type (tugs, fuel trucks, belt loaders, catering)

---

## 14. Platform Integration

### 14.1 Lakeview Dashboard

- **Location:** Embedded link from PlatformLinks component
- **Content:** Real-time flight metrics, delay distribution, gate utilization
- **Config:** `dashboards/flight_metrics.lvdash.json`

### 14.2 Genie Space

- **Purpose:** Natural language queries about flight data
- **Config:** `databricks/genie_space_config.json`
- **Example queries:** "How many flights are delayed?", "Which gates are available?"

### 14.3 Unity Catalog

- **Lineage:** Full data flow from Bronze → Silver → Gold visible in UC graph
- **Governance:** All tables registered with proper schema, comments, tags
- **Discovery:** Tables browsable in Catalog Explorer

### 14.4 MLflow

- **Experiments:** Model training runs tracked with metrics and artifacts
- **UI:** Accessible via Platform links from the application

### 14.5 Delta Sharing

- **Share:** `airport_digital_twin_share` with all managed tables
- **Recipients:** Configurable for cross-workspace sharing
- **Protocol:** Databricks-to-Databricks (internal) or Open Sharing (external)

---

## 15. Deployment & Infrastructure

### 15.1 Databricks Asset Bundles (DABs)

**Bundle name:** `airport-digital-twin`

**Resources defined in `resources/*.yml`:**

| Resource | File | Purpose |
|----------|------|---------|
| App | `resources/app.yml` | Databricks App deployment config |
| DLT Pipeline | `resources/pipeline.yml` | Medallion pipeline definition |
| Sync Job | `resources/sync_job.yml` | UC → Lakebase sync job |
| Integration Tests | `resources/integration_test_job.yml` | Baggage pipeline tests |
| Lakebase | `resources/lakebase.yml` | Lakebase instance config |

### 15.2 App Configuration (`app.yaml`)

```yaml
command: ["uvicorn", "app.backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
env:
  - USE_MOCK_BACKEND: "true"
  - DATABRICKS_HOST, DATABRICKS_HTTP_PATH, DATABRICKS_CATALOG, DATABRICKS_SCHEMA
  - LAKEBASE_HOST, LAKEBASE_PORT, LAKEBASE_DATABASE, LAKEBASE_SCHEMA
  - DATABRICKS_USE_OAUTH: "true"
  - LAKEBASE_USE_OAUTH: "true"
```

### 15.3 Deployment Commands

```bash
# Build frontend
cd app/frontend && npm run build

# Deploy bundle
databricks bundle deploy --target dev

# Deploy app
databricks apps deploy airport-digital-twin-dev \
  --source-code-path /Workspace/Users/<user>/.bundle/airport-digital-twin/dev/files \
  --profile FEVM_SERVERLESS_STABLE
```

### 15.4 Local Development

```bash
./dev.sh  # Starts FastAPI (port 8000) + Vite dev server (port 3000)
```

---

## 16. Security Specification

### 16.1 Current Security Posture

| Check | Status |
|-------|--------|
| SQL Injection prevention | FIXED — Parameterized queries |
| XSS prevention | PASS — React auto-escaping, no `dangerouslySetInnerHTML` |
| No `eval()` or `exec()` | PASS |
| No hardcoded secrets | PASS |
| No `.env` files committed | PASS |
| CORS restriction | TODO — Currently `allow_origins=["*"]` |
| API authentication | TODO — No auth on endpoints |
| WebSocket rate limiting | TODO — No connection limits |
| Debug endpoint protection | TODO — `/api/debug/paths` exposed |
| Content Security Policy | TODO — No CSP headers |
| Input validation (icao24) | TODO — No hex format validation |

### 16.2 Known Vulnerabilities

| ID | Severity | Issue | Recommendation |
|----|----------|-------|---------------|
| HIGH-01 | HIGH | CORS allows all origins with credentials | Restrict to specific domains |
| HIGH-02 | HIGH | Outdated esbuild/Vite (CVE-2024-xxxx) | Update to vite@^7.0.0 |
| HIGH-03 | HIGH | No authentication on API endpoints | Add OAuth2/API key middleware |
| MED-01 | MEDIUM | Debug endpoint exposes file paths | Disable in production |
| MED-02 | MEDIUM | WebSocket no rate limiting | Add connection limits (1000 total, 10/IP) |
| MED-03 | MEDIUM | Metrics endpoint unbounded memory | Use `deque(maxlen=1000)` |
| MED-04 | MEDIUM | No input validation on `icao24` param | Add regex `^[a-f0-9]{6}$` |

---

## 17. Testing Strategy

### 17.1 Test Suite Overview

| Type | Location | Runner | Count | Purpose |
|------|----------|--------|-------|---------|
| **Python Unit** | `tests/` | pytest | ~3089 | Backend logic, services, models, formats (69% code coverage) |
| **Frontend Unit** | `app/frontend/src/**/*.test.*` | Vitest | ~810 | Components, hooks, utilities (34 test files) |
| **Integration** | `databricks/notebooks/test_baggage_pipeline.py` | Databricks | On-demand | DLT Spark transformations |
| **E2E** | `app/frontend/e2e/` | Playwright | 2 specs | Full app interactions, 3D viz |
| **Security** | `tests/test_security.py` | pytest | 31 | SQL injection, XSS, input validation |

**Total:** ~3,900 tests (4 known Python failures, 19 skipped)

### 17.2 Test Categories (Python)

| Test File | Tests | Description |
|-----------|-------|-------------|
| `test_backend.py` | Core API endpoint tests |
| `test_services.py` | Service layer unit tests |
| `test_ml.py` | ML model tests (delay, gate, congestion) |
| `test_multi_airport_models.py` | Per-airport model registry tests |
| `test_ml_persistence.py` | ML training data persistence |
| `test_security.py` | Security vulnerability tests (31) |
| `test_aircraft_separation.py` | FAA/ICAO separation standards |
| `test_synthetic_data_requirements.py` | Synthetic data validation |
| `test_flight_origins_destinations.py` | Origin/destination correctness |
| `test_ingestion.py` | Data ingestion tests |
| `test_dlt.py` | DLT pipeline structure tests |
| `test_websocket.py` | WebSocket connection tests |
| `test_streaming.py` | Streaming pipeline tests |
| `test_lakebase_service.py` | Lakebase connection tests |
| `test_delta_service.py` | Delta table query tests |
| `test_data_sync.py` | UC → Lakebase sync tests |
| `test_airport_config_service.py` | Airport config tests |
| `test_airport_config_routes.py` | Airport API route tests |
| `test_airport_persistence.py` | Lakehouse persistence tests |
| `test_data_ops_api.py` | Data ops endpoint tests |
| `test_data_ops_service.py` | Data ops service tests |
| `test_data_generator_service.py` | Data generator tests |
| `test_unity_catalog.py` | UC integration tests |
| `test_lakebase_sync.py` | Lakebase sync tests |
| `test_v2_api.py` | V2 feature API tests |
| `tests/formats/test_*.py` | Format parser tests (AIXM, IFC, AIDM, OSM, FAA) |

### 17.3 Integration Test Architecture

- Uses temp schema `_test_baggage_{timestamp}` for isolation
- Defined as Databricks job in `resources/integration_test_job.yml`
- No schedule — on-demand execution only
- Tests Spark transformations without DLT decorators
- Temp schema dropped with CASCADE on teardown

### 17.4 Frontend Test Setup

- **Framework:** Vitest with React Testing Library
- **API Mocking:** MSW (Mock Service Worker) for HTTP and WebSocket
- **3D Mocking:** Three.js and React Three Fiber mocked for JSDOM compatibility
- **Custom render:** Wraps components with FlightProvider and AirportConfigProvider

---

## 18. Non-Functional Requirements

### 18.1 Performance

| Metric | Target | Measured |
|--------|--------|----------|
| End-to-end latency (API → Frontend) | <3 min | ~2 min |
| Lakebase query P99 | <20ms | ~10ms |
| Delta table query P99 | <200ms | ~100ms |
| ML prediction (all 3 models) | <50ms | ~20ms |
| Frontend initial load | <5s | ~3s |
| 2D→3D view switch | <750ms | ~500ms |
| Airport switch (cached) | <5s | ~3s |
| Airport switch (OSM fetch) | <15s | ~10s |

### 18.2 Reliability

| Metric | Target |
|--------|--------|
| Application availability | 99.5% (with synthetic fallback) |
| Data freshness | <2 minutes |
| Graceful degradation | Must serve synthetic data when all external sources fail |
| Pre-demo health check | `/health` endpoint validates all services |

### 18.3 Scalability

| Dimension | Current | Notes |
|-----------|---------|-------|
| Simultaneous flights | 50 | Configurable via query param (max 500) |
| Concurrent WebSocket connections | Unlimited | No rate limiting (security issue) |
| Airport data cache | Per-airport in memory | Registry pattern |
| ML model instances | Per-airport cached | `AirportModelRegistry` |

### 18.4 Browser Compatibility

| Browser | Support Level |
|---------|--------------|
| Chrome 90+ | Primary (best WebGL) |
| Firefox 90+ | Full support |
| Safari 15+ | Full support |
| Edge 90+ | Full support |
| Mobile browsers | Not optimized (desktop-first) |

---

## 19. Data Dictionary

### 19.1 Flight Position (API Model)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `icao24` | string | Yes | ICAO 24-bit hex address |
| `callsign` | string | No | Aircraft callsign (e.g., "UAL123") |
| `latitude` | number | No | WGS-84 latitude in degrees |
| `longitude` | number | No | WGS-84 longitude in degrees |
| `altitude` | number | No | Altitude in meters |
| `velocity` | number | No | Ground speed in m/s |
| `heading` | number | No | True track in degrees (0-360) |
| `on_ground` | boolean | Yes | Whether aircraft is on ground |
| `vertical_rate` | number | No | Vertical rate in m/s |
| `last_seen` | integer | No | Unix timestamp of last contact |
| `data_source` | string | Yes | "live", "cached", or "synthetic" |
| `flight_phase` | string | No | "ground", "climbing", "cruising", "descending" |
| `origin` | string | No | Origin airport IATA code |
| `destination` | string | No | Destination airport IATA code |
| `aircraft_type` | string | No | Aircraft type (e.g., "A320", "B777") |

### 19.2 Flight Phase Logic

```sql
CASE
    WHEN on_ground = TRUE THEN 'ground'
    WHEN vertical_rate > 1.0 THEN 'climbing'
    WHEN vertical_rate < -1.0 THEN 'descending'
    WHEN ABS(vertical_rate) <= 1.0 THEN 'cruising'
    ELSE 'unknown'
END
```

### 19.3 Gate Status (Enum)

| Value | Description |
|-------|-------------|
| `AVAILABLE` | Gate is free for assignment |
| `OCCUPIED` | Gate currently in use |
| `DELAYED` | Gate will be available soon |
| `MAINTENANCE` | Gate under maintenance |

### 19.4 Congestion Level (Enum)

| Value | Capacity Ratio | Description |
|-------|---------------|-------------|
| `LOW` | <50% | Normal operations |
| `MODERATE` | 50-75% | Minor delays possible |
| `HIGH` | 75-90% | Significant delays expected |
| `CRITICAL` | >90% | Operations at capacity |

### 19.5 Delay Category

| Category | Range | Color |
|----------|-------|-------|
| `on_time` | <5 min | Green |
| `slight` | 5-15 min | Yellow |
| `moderate` | 15-30 min | Orange |
| `severe` | >30 min | Red |

---

## 20. API Reference

### 20.1 Flight Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /api/flights` | GET | List all current flight positions (default 50) |
| `GET /api/flights/{icao24}` | GET | Get specific flight by ICAO24 |
| `GET /api/flights/{icao24}/trajectory` | GET | Get trajectory history (synthetic or Delta) |
| `GET /api/data-sources` | GET | Data source status and health |
| `GET /health` | GET | Application health check |
| `GET /api/ready` | GET | Backend readiness (for loading screen) |
| `GET /api/version` | GET | Application version info |
| `GET /api/config` | GET | Runtime configuration |
| `GET /api/logs` | GET | Application logs |

### 20.2 Prediction Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /api/predictions/delays` | GET | All flight delay predictions |
| `GET /api/predictions/gates/{icao24}` | GET | Gate recommendations for flight |
| `GET /api/predictions/congestion` | GET | Airport area congestion levels |
| `GET /api/predictions/bottlenecks` | GET | HIGH/CRITICAL congestion only |
| `GET /api/predictions/congestion-summary` | GET | Aggregated congestion summary |

### 20.3 Schedule Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /api/schedule/arrivals` | GET | Scheduled arrivals (FIDS) |
| `GET /api/schedule/departures` | GET | Scheduled departures (FIDS) |
| `GET /api/schedule/audit` | GET | Schedule accuracy audit |

### 20.4 Weather Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /api/weather/current` | GET | Current METAR + TAF |

### 20.5 GSE Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /api/gse/status` | GET | GSE fleet inventory and availability |
| `GET /api/turnaround/{icao24}` | GET | Aircraft turnaround status |

### 20.6 Baggage Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /api/baggage/stats` | GET | Airport-wide baggage statistics |
| `GET /api/baggage/flight/{flight_number}` | GET | Per-flight baggage info |
| `GET /api/baggage/alerts` | GET | Active misconnect alerts |

### 20.7 Airport Configuration Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /api/airport/config` | GET | Current merged airport config |
| `POST /api/airport/import/osm` | POST | Import from OpenStreetMap |
| `POST /api/airport/import/aixm` | POST | Import AIXM XML file |
| `POST /api/airport/import/ifc` | POST | Import IFC building model |
| `POST /api/airport/import/aidm` | POST | Import AIDM operational data |
| `POST /api/airport/import/faa` | POST | Import FAA NASR runway data |
| `POST /api/airport/import/msfs` | POST | Import MSFS BGL scenery data |
| `GET /api/airports` | GET | List all persisted airports |
| `GET /api/airports/{icao}` | GET | Get airport (lakehouse → OSM fallback) |
| `POST /api/airports/{icao}/activate` | POST | Activate airport (full switch) |
| `POST /api/airports/{icao}/reload` | POST | Reload airport from cache |
| `POST /api/airports/{icao}/refresh` | POST | Re-fetch from external sources |
| `DELETE /api/airports/{icao}` | DELETE | Delete persisted airport data |
| `GET /api/airports/preload/status` | GET | Preload cache status for all airports |
| `POST /api/airports/preload` | POST | Preload well-known airports into cache |

### 20.8 Simulation Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /api/simulation/files` | GET | List available simulation data files |
| `GET /api/simulation/data/{filename}` | GET | Retrieve simulation data file |
| `GET /api/simulation/metadata/{filename}` | GET | Simulation file metadata |
| `GET /api/simulation/demo/{airport_icao}` | GET | Run demo simulation for airport |

### 20.9 Assistant & Genie Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `POST /api/assistant/ask` | POST | Unified LLM assistant (routes to Genie or MCP) |
| `POST /api/assistant/followup` | POST | Follow-up question to assistant |
| `POST /api/genie/ask` | POST | Genie natural language query |
| `POST /api/genie/followup` | POST | Genie follow-up query |
| `GET /api/genie/space` | GET | Genie space configuration |

### 20.10 MCP Server Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `POST /api/mcp` | POST | JSON-RPC 2.0 MCP endpoint (13 tools) |
| `GET /api/mcp/tools` | GET | List available MCP tools |
| `GET /api/mcp/health` | GET | MCP server health check |

### 20.11 Inpainting Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /api/inpainting/status` | GET | Inpainting service status |
| `POST /api/inpainting/wake` | POST | Wake up inpainting model endpoint |
| `GET /api/inpainting/cache-stats` | GET | Tile cache statistics |
| `POST /api/inpainting/clean-tile` | POST | Clean a satellite tile |

### 20.12 Data Ops Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /api/data-ops/stats` | GET | Pipeline statistics |
| `GET /api/data-ops/acquisitions` | GET | Data acquisition history |
| `GET /api/data-ops/syncs` | GET | Sync history |
| `GET /api/data-ops/sync-status` | GET | Current sync status |
| `POST /api/data-ops/check-freshness` | POST | Check data freshness |
| `GET /api/data-ops/dashboard` | GET | Full dashboard data |
| `POST /api/data-ops/reset-synthetic` | POST | Reset synthetic data generator |
| `GET /api/data-ops/history-sync-status` | GET | History sync status |

### 20.13 Monitoring Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `POST /api/metrics` | POST | Collect Web Vitals from frontend |
| `GET /api/metrics/summary` | GET | Aggregated Web Vitals summary |
| `GET /api/debug/paths` | GET | Debug: file system paths |
| `GET /api/debug/logs` | GET | Debug: ring-buffer log endpoint |
| `POST /api/user/prewarm` | POST | Prewarm airport data on user arrival |

### 20.14 WebSocket Endpoints

| Endpoint | Protocol | Description |
|----------|----------|-------------|
| `ws://host/ws/flights` | WebSocket | Real-time flight updates (5s interval) |

**Total API endpoints:** 71

---

*End of specification. This document was reverse-engineered from the implemented codebase as of 2026-03-10. Updated 2026-04-01 with current test counts, API endpoints, and airport profile numbers.*

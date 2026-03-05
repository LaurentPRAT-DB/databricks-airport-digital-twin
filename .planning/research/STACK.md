# Technology Stack

**Project:** Airport Digital Twin
**Researched:** 2026-03-05
**Overall Confidence:** MEDIUM (web verification unavailable - versions based on training data)

## Recommended Stack

### Frontend Framework

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| React | ^18.2.0 | UI framework | Databricks APX standard, mature ecosystem, TypeScript support | MEDIUM |
| TypeScript | ^5.3.0 | Type safety | Catches errors at compile time, better IDE support, essential for complex 3D logic | MEDIUM |
| Vite | ^5.0.0 | Build tool | Fast HMR, native ES modules, better DX than CRA (deprecated) | MEDIUM |

**Rationale:** React 18 with concurrent features provides the performance needed for real-time flight updates. TypeScript is non-negotiable for a project with 3D visualization complexity - runtime errors in Three.js code are painful to debug.

### 3D Visualization

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| Three.js | ^0.160.0 | 3D rendering engine | Industry standard, massive community, excellent documentation | MEDIUM |
| @react-three/fiber | ^8.15.0 | React-Three.js bridge | Declarative 3D scenes, React lifecycle integration, official R3F | MEDIUM |
| @react-three/drei | ^9.92.0 | R3F helpers | Pre-built components (OrbitControls, Environment, etc.) | MEDIUM |
| @react-three/postprocessing | ^2.15.0 | Visual effects | Bloom, SSAO for polished demo appearance | MEDIUM |

**Rationale:** React Three Fiber (R3F) is the de facto standard for React + Three.js integration. It provides declarative scene composition and proper React lifecycle management. The drei helpers library saves hundreds of lines of boilerplate for common 3D patterns (camera controls, lighting, loaders).

**AVOID:**
- Raw Three.js without R3F: Imperative code doesn't integrate well with React state, leads to memory leaks and ref management nightmares
- Babylon.js: Less React integration, smaller community for web use cases
- A-Frame: VR-focused, overkill for non-VR visualization

### 2D Mapping

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| MapLibre GL JS | ^4.0.0 | Interactive maps | Open-source fork of Mapbox GL, no API key required for basic use | MEDIUM |
| react-map-gl | ^7.1.0 | React wrapper | Uber's official React binding for MapLibre/Mapbox | MEDIUM |
| deck.gl | ^8.9.0 | Data layers | High-performance WebGL layers for flight paths, excellent with large datasets | MEDIUM |

**Rationale:** MapLibre GL provides Mapbox-quality maps without vendor lock-in or API costs. deck.gl excels at rendering thousands of moving objects (aircraft) with WebGL acceleration.

**AVOID:**
- Google Maps: Expensive API costs, less customizable styling
- Leaflet: Not WebGL-accelerated, struggles with real-time updates of many objects
- Mapbox GL JS v2+: Proprietary license requires API key even for self-hosted tiles

### Backend Framework

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| FastAPI | ^0.109.0 | API framework | Databricks APX standard, async-first, automatic OpenAPI docs | MEDIUM |
| Pydantic | ^2.5.0 | Data validation | Type-safe request/response models, excellent error messages | MEDIUM |
| uvicorn | ^0.27.0 | ASGI server | Production-grade async server for FastAPI | MEDIUM |
| httpx | ^0.26.0 | HTTP client | Async HTTP for flight API calls, connection pooling | MEDIUM |

**Rationale:** FastAPI is the Databricks APX standard - no other choice makes sense here. Its async-first design is perfect for handling multiple concurrent flight API requests and WebSocket connections for real-time updates.

**AVOID:**
- Flask: Sync-only, no native async support, slower for I/O-bound work
- Django: Too heavy for API-only backend, ORM not needed with Databricks
- aiohttp: Lower-level, FastAPI provides better DX

### Real-Time Communication

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| WebSocket (native) | - | Real-time updates | Built into FastAPI, low latency for flight position updates | HIGH |
| Server-Sent Events | - | Alternative fallback | Simpler than WebSocket for one-way data (server to client) | HIGH |

**Rationale:** WebSockets provide bidirectional communication needed for real-time flight tracking. FastAPI has native WebSocket support. SSE is a simpler fallback if WebSocket complexity becomes an issue.

**AVOID:**
- Socket.io: Adds unnecessary complexity, WebSocket alone is sufficient
- Long polling: Inefficient for high-frequency updates like aircraft positions

### Data Layer (Databricks)

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| Databricks SDK | ^0.20.0 | Platform integration | Official SDK for Unity Catalog, SQL Warehouse queries | MEDIUM |
| Databricks SQL Connector | ^3.0.0 | SQL queries | Connect to SQL Warehouses from FastAPI backend | MEDIUM |
| Delta Lake | (managed) | Storage format | ACID transactions, time travel, Databricks native | HIGH |
| Structured Streaming | (managed) | Stream processing | Native Spark streaming, exactly-once semantics | HIGH |
| Delta Live Tables | (managed) | ETL pipelines | Declarative pipelines, automatic data quality | HIGH |

**Rationale:** All data layer components are Databricks managed services - this is the showcase. The SDK provides typed access to Unity Catalog and workspace resources.

### ML/AI Layer (Databricks)

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| MLflow | (managed) | Model tracking | Databricks native, experiment tracking, model registry | HIGH |
| Feature Store | (managed) | Feature engineering | Unity Catalog integrated, point-in-time lookups | HIGH |
| Model Serving | (managed) | Model inference | Real-time endpoints for flight predictions | HIGH |
| Mosaic AI | (managed) | GenAI integration | RAG, agents for Genie-like natural language queries | MEDIUM |

**Rationale:** MLflow is the ML backbone - all models should be tracked and served through it. Feature Store ensures consistent features between training and serving.

### BI/Analytics (Databricks)

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| Lakeview Dashboards | (managed) | Analytics dashboards | Native Databricks BI, auto-updates from tables | HIGH |
| Genie | (managed) | Natural language queries | AI-powered data exploration | HIGH |
| AI/BI | (managed) | Intelligent insights | Automated anomaly detection, recommendations | HIGH |

**Rationale:** These are the Databricks AI/BI products to showcase. Embed Lakeview dashboards directly in the app, provide Genie integration for natural language queries about airport operations.

---

## Flight Data APIs Comparison

### Recommended: Tiered Approach

| API | Tier | Use Case | Cost | Data Quality | Rate Limits | Confidence |
|-----|------|----------|------|--------------|-------------|------------|
| OpenSky Network | Free tier | Development, testing | Free | Good for en-route | 100 req/day anonymous, 1000/day registered | MEDIUM |
| ADS-B Exchange | Primary | Real-time positions | ~$10/month hobby | Excellent global | Generous for paid | MEDIUM |
| FlightAware AeroAPI | Premium | Enriched data | $$$$ (enterprise) | Best in class | Based on plan | MEDIUM |

**Recommended Strategy:**

1. **Development:** OpenSky Network (free, sufficient for testing)
2. **Demo:** ADS-B Exchange (affordable, good coverage, fast updates)
3. **Optional Enhancement:** FlightAware AeroAPI for enriched data (airline info, delay reasons)

### OpenSky Network

**Pros:**
- Free tier available (academic project)
- REST API + historical data access
- Good coverage over North America and Europe
- 5-second position updates

**Cons:**
- Rate limited (100 req/day anonymous)
- Coverage gaps over oceans
- No airline-specific metadata

**API Pattern:**
```python
# State vectors (aircraft positions)
GET https://opensky-network.org/api/states/all?lamin=...&lomin=...&lamax=...&lomax=...

# Returns: icao24, callsign, origin_country, longitude, latitude, altitude, velocity, heading
```

### ADS-B Exchange

**Pros:**
- Affordable paid plans
- Excellent global coverage
- Fast update rates (1-2 seconds)
- Aircraft photos and registration data

**Cons:**
- Requires paid subscription for production
- Less metadata than FlightAware

**API Pattern:**
```python
# Aircraft in bounding box
GET https://adsbexchange.com/api/aircraft/json/lat/{lat}/lon/{lon}/dist/{nm}/

# Returns: hex, flight, lat, lon, alt, track, speed, squawk
```

### FlightAware AeroAPI

**Pros:**
- Richest data (delays, gates, baggage claim)
- Historical data access
- Flight status notifications
- Best data quality

**Cons:**
- Expensive (enterprise pricing)
- Overkill for position-only visualization

**Use when:** Demo needs enriched flight information (why delayed, gate assignments)

### Recommendation

**Start with OpenSky for development, upgrade to ADS-B Exchange for demos.**

OpenSky provides sufficient data quality for the visualization without cost. ADS-B Exchange offers better coverage and faster updates when demoing to customers. FlightAware is only worth the cost if the demo specifically showcases delay prediction accuracy (their data includes delay reason codes).

---

## Supporting Libraries

### State Management

| Library | Version | Purpose | When to Use | Confidence |
|---------|---------|---------|-------------|------------|
| Zustand | ^4.4.0 | Global state | Lightweight, perfect for flight data cache | MEDIUM |
| React Query / TanStack Query | ^5.17.0 | Server state | Flight API data fetching, caching, refetching | MEDIUM |

**Rationale:** Zustand for local state (selected aircraft, UI toggles). TanStack Query for server state (flight data with automatic refetching). This separation keeps concerns clean.

**AVOID:**
- Redux: Overkill boilerplate for this app size
- MobX: Less common in React ecosystem, harder to hire for
- Context alone: Performance issues with frequent updates (flight positions)

### UI Components

| Library | Version | Purpose | When to Use | Confidence |
|---------|---------|---------|-------------|------------|
| Tailwind CSS | ^3.4.0 | Styling | Utility-first, rapid prototyping | MEDIUM |
| shadcn/ui | latest | Components | Copy-paste components, no runtime dependency | MEDIUM |
| Radix UI | ^1.0.0 | Primitives | Accessible, unstyled primitives under shadcn | MEDIUM |

**Rationale:** shadcn/ui provides beautiful, accessible components without vendor lock-in (it's copy-paste, not a dependency). Tailwind enables rapid iteration on demo polish.

**AVOID:**
- Material UI: Heavy bundle, Google aesthetic doesn't match Databricks brand
- Chakra UI: Good but less customizable than shadcn approach
- Ant Design: Enterprise-y feel, large bundle

### Data Visualization (2D Charts)

| Library | Version | Purpose | When to Use | Confidence |
|---------|---------|---------|-------------|------------|
| Recharts | ^2.10.0 | Simple charts | Quick dashboards, flight statistics | MEDIUM |
| Observable Plot | ^0.6.0 | Advanced viz | Complex flight pattern analysis | MEDIUM |

**Rationale:** Recharts for standard bar/line/area charts in the dashboard. Observable Plot if more sophisticated visualization needed.

### Testing

| Library | Version | Purpose | When to Use | Confidence |
|---------|---------|---------|-------------|------------|
| Vitest | ^1.2.0 | Unit testing | Fast, Vite-native testing | MEDIUM |
| Playwright | ^1.41.0 | E2E testing | Browser testing, visual regression | MEDIUM |
| React Testing Library | ^14.1.0 | Component testing | React component behavior testing | MEDIUM |

---

## Databricks-Specific Components

### Databricks Apps (APX Framework)

The APX framework is Databricks' standard for building applications:

```
databricks-app/
├── app.yaml              # App configuration
├── backend/
│   ├── main.py          # FastAPI entry point
│   ├── requirements.txt
│   └── ...
└── frontend/
    ├── package.json
    ├── src/
    └── ...
```

**Key Configuration (app.yaml):**
```yaml
command:
  - uvicorn
  - main:app
  - --host
  - 0.0.0.0
  - --port
  - "8000"
resources:
  memory: 2Gi
  cpu: 1
```

### Unity Catalog Integration

```python
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

# Access tables
tables = w.tables.list(catalog_name="airport_twin", schema_name="flights")

# Query data via SQL Warehouse
with w.statement_execution.execute_statement(
    warehouse_id="...",
    statement="SELECT * FROM airport_twin.flights.positions LIMIT 100"
) as result:
    data = result.result.data_array
```

### Structured Streaming Pipeline

```python
# Ingest from flight API (pseudo-code pattern)
(spark.readStream
    .format("rate")  # Or custom source
    .option("rowsPerSecond", 10)
    .load()
    .writeStream
    .format("delta")
    .outputMode("append")
    .option("checkpointLocation", "/checkpoints/flights")
    .table("airport_twin.flights.raw_positions"))
```

### Delta Live Tables

```python
import dlt

@dlt.table(
    comment="Cleaned flight positions",
    table_properties={"quality": "silver"}
)
@dlt.expect_or_drop("valid_coordinates", "latitude IS NOT NULL AND longitude IS NOT NULL")
def flight_positions_clean():
    return (
        dlt.read_stream("raw_positions")
        .withColumn("ingested_at", current_timestamp())
        .dropDuplicates(["icao24", "timestamp"])
    )
```

### ML Model Serving

```python
import mlflow

# Log model
with mlflow.start_run():
    mlflow.sklearn.log_model(model, "delay_predictor")
    mlflow.log_metrics({"rmse": rmse, "mae": mae})

# Serve via Model Serving endpoint
# Configure in Databricks workspace, call from FastAPI:
# POST https://<workspace>/serving-endpoints/<endpoint>/invocations
```

---

## What to Avoid (and Why)

### Frontend

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Create React App (CRA) | Deprecated, slow builds, no longer maintained | Vite |
| Redux | Boilerplate overkill for this app size | Zustand + TanStack Query |
| Raw Three.js in React | Memory leaks, lifecycle issues | @react-three/fiber |
| CSS-in-JS (Emotion, Styled) | Runtime cost, moving away from industry | Tailwind CSS |
| Next.js | SSR not needed, adds complexity, Databricks Apps are client-side | Vite + React |

### Backend

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Django | Heavy ORM not needed, sync-only | FastAPI |
| Flask | No native async, slower for I/O work | FastAPI |
| SQLAlchemy | Not needed - data lives in Delta Lake | Databricks SQL Connector |
| requests library | Sync HTTP blocks event loop | httpx (async) |

### 3D/Visualization

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Babylon.js | Less React integration, smaller web community | Three.js + R3F |
| Unity WebGL | Heavy, long load times, C# stack | Three.js (native web) |
| Cesium | Overkill for airport scale, complex licensing | Three.js + MapLibre |
| A-Frame | VR-focused, wrong abstraction level | Three.js + R3F |

### Data/APIs

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| FlightAware (initially) | Expensive, not needed for basic demo | OpenSky (free) |
| Synthetic data only | Less impressive than real flights | Real API data |
| Multiple flight APIs simultaneously | Complexity, data reconciliation issues | One primary API |

---

## Installation Commands

### Frontend

```bash
# Initialize Vite + React + TypeScript
npm create vite@latest frontend -- --template react-ts
cd frontend

# Core dependencies
npm install react@^18.2.0 react-dom@^18.2.0

# 3D visualization
npm install three@^0.160.0 @react-three/fiber@^8.15.0 @react-three/drei@^9.92.0 @react-three/postprocessing@^2.15.0

# 2D mapping
npm install maplibre-gl@^4.0.0 react-map-gl@^7.1.0 @deck.gl/core@^8.9.0 @deck.gl/layers@^8.9.0 @deck.gl/react@^8.9.0

# State management
npm install zustand@^4.4.0 @tanstack/react-query@^5.17.0

# UI
npm install tailwindcss@^3.4.0 postcss autoprefixer
npm install @radix-ui/react-dialog @radix-ui/react-dropdown-menu @radix-ui/react-tabs

# Charts
npm install recharts@^2.10.0

# Dev dependencies
npm install -D typescript@^5.3.0 @types/react @types/react-dom @types/three
npm install -D vitest @testing-library/react playwright
```

### Backend

```bash
cd backend

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Core dependencies
pip install fastapi==0.109.0 uvicorn[standard]==0.27.0 pydantic==2.5.0

# HTTP client for flight APIs
pip install httpx==0.26.0

# Databricks integration
pip install databricks-sdk==0.20.0 databricks-sql-connector==3.0.0

# ML
pip install mlflow==2.10.0

# Development
pip install pytest pytest-asyncio httpx
```

---

## Version Pinning Strategy

**Pin major.minor, float patch:** `fastapi==0.109.*`

This allows security patches while preventing breaking changes. For a demo application, stability matters more than bleeding edge.

**Lock file required:** Use `package-lock.json` (npm) and `requirements.txt` with exact versions for reproducible builds.

---

## Confidence Assessment Summary

| Category | Confidence | Reasoning |
|----------|------------|-----------|
| Frontend (React, Vite, TS) | MEDIUM | Training data only, unable to verify current versions |
| 3D (Three.js, R3F) | MEDIUM | Training data only, R3F ecosystem moves fast |
| Backend (FastAPI) | MEDIUM | Training data only, but FastAPI is stable |
| Databricks Services | HIGH | Managed services, less version sensitivity |
| Flight APIs | MEDIUM | Unable to verify current pricing/limits |
| State Management | MEDIUM | Training data only, libraries are stable |

**Recommendation:** Before starting development, verify current stable versions of:
- @react-three/fiber
- three
- maplibre-gl
- fastapi

via `npm info [package] version` and `pip index versions [package]`.

---

## Sources

Unable to verify with live sources due to tool limitations. All recommendations based on training data (cutoff May 2025). Confidence levels adjusted accordingly.

**Verification recommended for:**
- https://docs.databricks.com/en/dev-tools/databricks-apps/
- https://r3f.docs.pmnd.rs/
- https://maplibre.org/maplibre-gl-js/docs/
- https://fastapi.tiangolo.com/
- https://opensky-network.org/apidoc/

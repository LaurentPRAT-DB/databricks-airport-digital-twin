# External API Calls & Data Sources

Inventory of all outbound calls to external services from the Airport Digital Twin application.

---

## 1. Runtime Services (Backend — used during app operation)

### 1.1 OpenSky Network — Live ADS-B Flight Data

| Field | Value |
|-------|-------|
| **Service** | OpenSky Network REST API |
| **File** | `app/backend/services/opensky_service.py` |
| **Library** | `httpx.AsyncClient` |
| **Auth** | 3-tier credential chain (see below) |
| **Rate Limit** | 10 req/10s (anonymous), higher with auth |

**Authentication chain (highest to lowest priority):**
1. **Databricks secrets** (OAuth2): `airport-digital-twin/opensky-client-id` + `airport-digital-twin/opensky-client-secret`
2. **Env vars** (OAuth2): `OPENSKY_CLIENT_ID` / `OPENSKY_CLIENT_SECRET`
3. **Env vars** (basic auth, free tier): `OPENSKY_USERNAME` / `OPENSKY_PASSWORD`
4. **Anonymous** (lowest rate limits)

Local dev uses `.env` file via python-dotenv for credential injection.

**Endpoints called:**

| Method | URL | Purpose | Function |
|--------|-----|---------|----------|
| POST | `https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token` | OAuth2 token exchange | `_authenticate()` |
| GET | `https://opensky-network.org/api/states/all?lamin=..&lamax=..&lomin=..&lomax=..` | Live aircraft positions within bounding box (~30nm radius) | `fetch_live_flights()` |
| GET | `https://opensky-network.org/api/flights/aircraft?icao24=..&begin=..&end=..` | Flight origin/destination enrichment per icao24 | `_enrich_flight_origin()` |

---

### 1.2 OpenStreetMap Overpass API — Airport Geometry

| Field | Value |
|-------|-------|
| **Service** | Overpass API (OSM) |
| **File** | `src/formats/osm/parser.py` |
| **Library** | `httpx.Client` (sync) |
| **Auth** | None (public API) |
| **Rate Limit** | Varies by endpoint; retries with failover between endpoints |

**Endpoints called:**

| Method | URL | Purpose | Function |
|--------|-----|---------|----------|
| POST | `https://overpass-api.de/api/interpreter` | Fetch airport features (runways, gates, taxiways, terminals) via Overpass QL | `fetch_osm_data()` |
| POST | `https://overpass.kumi.systems/api/interpreter` | Failover endpoint | `fetch_osm_data()` |

The query is built per ICAO code and requests `aeroway=*` features within the airport boundary. Results are cached locally at `/tmp/{icao}_osm_cache.json`.

---

### 1.3 Databricks SQL Warehouse — Delta Tables (Unity Catalog)

| Field | Value |
|-------|-------|
| **Service** | Databricks SQL Warehouse |
| **File** | `app/backend/services/delta_service.py` |
| **Library** | `databricks-sql-connector` (`databricks.sql.connect`) |
| **Auth** | OAuth via `databricks.sdk.core.Config` (ambient M2M on Databricks Apps) or `DATABRICKS_TOKEN` env var |
| **Protocol** | Thrift over HTTPS |

**Tables queried:**

| Table | Catalog.Schema | Purpose |
|-------|---------------|---------|
| `flight_status_gold` | `{CATALOG}.airport_digital_twin` | Historical flight status (Gold layer from DLT) |
| `flight_positions_history` | `{CATALOG}.airport_digital_twin` | Historical position snapshots |

**Connection params:** `DATABRICKS_HOST`, `DATABRICKS_HTTP_PATH` (SQL Warehouse), `DATABRICKS_CATALOG`, `DATABRICKS_SCHEMA`.

---

### 1.4 Databricks Lakebase (PostgreSQL) — Low-Latency Cache

| Field | Value |
|-------|-------|
| **Service** | Databricks Lakebase Autoscaling (managed PostgreSQL) |
| **File** | `app/backend/services/lakebase_service.py` |
| **Library** | `psycopg2` (`psycopg2.connect`) |
| **Auth** | OAuth via `WorkspaceClient().postgres.generate_database_credential()` (Databricks Apps) or direct `LAKEBASE_USER`/`LAKEBASE_PASSWORD` (local dev) |
| **Protocol** | PostgreSQL wire protocol (TLS) |

**Tables accessed:**

| Table | Purpose |
|-------|---------|
| `flight_status` | Real-time flight positions (upserted by backend) |
| `satellite_tile_cache` | Cached inpainted satellite tiles |

Lakebase has 14 tables total (not just the two listed above). See `scripts/lakebase_schema.sql` for full schema.

---

### 1.5 Databricks Genie Space API — Natural Language SQL

| Field | Value |
|-------|-------|
| **Service** | Databricks Genie Conversation API |
| **File** | `app/backend/api/genie.py` |
| **Library** | `httpx.AsyncClient` |
| **Auth** | User's forwarded OAuth Bearer token (OBO) or SDK ambient credentials |

**Endpoints called:**

| Method | URL | Purpose | Function |
|--------|-----|---------|----------|
| POST | `https://{DATABRICKS_HOST}/api/2.0/genie/spaces/{SPACE_ID}/start-conversation` | Start new Genie conversation | `ask_genie()` |
| GET | `https://{DATABRICKS_HOST}/api/2.0/genie/spaces/{SPACE_ID}/conversations/{id}/messages/{mid}` | Poll for Genie response | `ask_genie()` |
| GET | `https://{DATABRICKS_HOST}/api/2.0/genie/spaces/{SPACE_ID}/conversations/{id}/messages/{mid}/query-result` | Fetch SQL query result | `ask_genie()` |
| GET | `https://{DATABRICKS_HOST}/api/2.0/genie/spaces/{SPACE_ID}` | Validate Genie config | `validate_genie_config()` |

**Genie Space ID**: `01f12612fa6314ae943d0526f5ae3a00` (configurable via `GENIE_SPACE_ID` env var).

---

### 1.6 Databricks Foundation Model Serving — LLM Assistant

| Field | Value |
|-------|-------|
| **Service** | Databricks Model Serving (OpenAI-compatible chat completions) |
| **File** | `app/backend/api/assistant.py` |
| **Library** | `httpx.AsyncClient` |
| **Auth** | User's forwarded OAuth Bearer token (OBO) or SDK ambient credentials |

**Endpoint called:**

| Method | URL | Purpose | Function |
|--------|-----|---------|----------|
| POST | `https://{DATABRICKS_HOST}/serving-endpoints/{MODEL_ENDPOINT}/invocations` | Chat completions with function calling (routes queries to Genie or MCP tools) | `chat_completions()` |

**Model endpoint**: `databricks-claude-sonnet-4-5` (configurable via `ASSISTANT_MODEL_ENDPOINT` env var).

---

### 1.7 Databricks Model Serving — Aircraft Inpainting

| Field | Value |
|-------|-------|
| **Service** | Databricks Model Serving (custom YOLO + LaMa endpoint) |
| **File** | `app/backend/api/inpainting.py` |
| **Library** | `httpx.AsyncClient` |
| **Auth** | User's Bearer token, `DATABRICKS_TOKEN`, or `WorkspaceClient` M2M OAuth |

**Endpoints called:**

| Method | URL | Purpose | Function |
|--------|-----|---------|----------|
| POST | `https://{DATABRICKS_HOST}/serving-endpoints/{ENDPOINT_NAME}/invocations` | Send satellite tile image, receive inpainted (aircraft-removed) tile | `inpaint_tile()` |
| GET | `https://{DATABRICKS_HOST}/api/2.0/serving-endpoints/{ENDPOINT_NAME}` | Health check (endpoint readiness) | `get_endpoint_status()` |

**Endpoint name**: `airport-dt-aircraft-inpainting-dev` (configurable via `INPAINTING_ENDPOINT_NAME`).

---

### 1.8 Iowa State ASOS Archive — Historical METAR Weather

| Field | Value |
|-------|-------|
| **Service** | Iowa State Mesonet ASOS Archive |
| **File** | `app/backend/services/metar_history.py` |
| **Library** | `httpx.AsyncClient` |
| **Auth** | None (public API) |

**Endpoint called:**

| Method | URL | Purpose | Function |
|--------|-----|---------|----------|
| GET | `https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=..&data=metar&year1=..&...` | Fetch historical METAR observations for a station + date | `fetch_metar_history()` |

---

### 1.9 OpenSky Aircraft Database — Type Code Lookup

| Field | Value |
|-------|-------|
| **Service** | OpenSky Network static datasets |
| **File** | `app/backend/services/aircraft_db.py` |
| **Library** | `httpx.AsyncClient` |
| **Auth** | None (public CSV download) |

**Endpoint called:**

| Method | URL | Purpose | Function |
|--------|-----|---------|----------|
| GET | `https://opensky-network.org/datasets/metadata/aircraftDatabase.csv` | Download ~30MB aircraft type database (icao24 → typecode). Cached locally for 7 days. | `_download_database()` |

---

### 1.10 Databricks SDK — Workspace Operations

| Field | Value |
|-------|-------|
| **Service** | Databricks Workspace REST API (via SDK) |
| **Files** | `app/backend/api/simulation.py`, `app/backend/services/mcp_connection_service.py`, `app/backend/services/lakebase_service.py` |
| **Library** | `databricks.sdk.WorkspaceClient` |
| **Auth** | Ambient M2M OAuth (Databricks Apps injects `DATABRICKS_CLIENT_ID` + `DATABRICKS_CLIENT_SECRET`) |

**SDK operations used:**

| Operation | File | Purpose |
|-----------|------|---------|
| `w.statement_execution.execute_statement()` | `simulation.py`, `mcp_connection_service.py` | Run SQL queries on Databricks SQL Warehouse |
| `w.postgres.generate_database_credential()` | `lakebase_service.py` | Get short-lived PostgreSQL OAuth token for Lakebase |
| `w.current_user.me()` | `lakebase_service.py` | Get current user email for Lakebase auth |
| `w.dbutils.secrets.get()` | `opensky_service.py` | Fetch OpenSky credentials from Databricks secrets |
| `w.connections.get()` / SQL `CREATE CONNECTION` | `mcp_connection_service.py` | Register/verify UC HTTP Connection for MCP |

---

## 2. Frontend — Map Tile Services (loaded by user's browser)

### 2.1 OpenStreetMap Tiles — 2D Street Map

| Field | Value |
|-------|-------|
| **File** | `app/frontend/src/components/Map/AirportMap.tsx` |
| **URL** | `https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png` |
| **Auth** | None (public) |
| **Usage** | Leaflet `TileLayer` for 2D street map base layer |

### 2.2 Esri World Imagery — 2D Satellite Map

| Field | Value |
|-------|-------|
| **File** | `app/frontend/src/components/Map/AirportMap.tsx` |
| **URL** | `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}` |
| **Auth** | None (public) |
| **Usage** | Leaflet `TileLayer` for 2D satellite base layer |

### 2.3 Esri World Imagery — 3D Ground Plane

| Field | Value |
|-------|-------|
| **File** | `app/frontend/src/components/Map3D/SatelliteGround.tsx` |
| **URL** | `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}` |
| **Auth** | None (public) |
| **Usage** | Three.js canvas texture for 3D satellite ground plane |

### 2.4 Google Draco Decoder — 3D Model Decompression

| Field | Value |
|-------|-------|
| **File** | `app/frontend/src/components/Map3D/GLTFAircraft.tsx` |
| **URL** | `https://www.gstatic.com/draco/versioned/decoders/1.5.6/` |
| **Auth** | None (public CDN) |
| **Usage** | WebAssembly decoder for Draco-compressed GLTF 3D models |

---

## 3. Calibration Scripts (offline, run locally or in CI)

These are CLI tools used to build airport calibration profiles. Not called during normal app operation.

### 3.1 OpenSky REST API — Calibration Data

| Field | Value |
|-------|-------|
| **Files** | `src/calibration/opensky_ingest.py`, `src/ingestion/opensky_client.py`, `scripts/opensky_collector.py` |
| **Library** | `urllib.request`, `httpx` |
| **Auth** | OAuth2 client credentials (env vars `OPENSKY_CLIENT_ID` / `OPENSKY_CLIENT_SECRET`) |

| Method | URL | Purpose |
|--------|-----|---------|
| GET | `https://opensky-network.org/api/states/all` | Snapshot aircraft positions for a region |
| GET | `https://opensky-network.org/api/flights/arrival?airport=..&begin=..&end=..` | Arrival flight history for profile building |
| GET | `https://opensky-network.org/api/flights/departure?airport=..&begin=..&end=..` | Departure flight history for profile building |

### 3.2 OpenFlights — Route & Airline Data

| Field | Value |
|-------|-------|
| **File** | `src/calibration/openflights_ingest.py` |
| **Library** | `urllib.request` |
| **Auth** | None (public GitHub raw files) |

| Method | URL | Purpose |
|--------|-----|---------|
| GET | `https://raw.githubusercontent.com/jpatokal/openflights/master/data/routes.dat` | ~67,000 airline route records |
| GET | `https://raw.githubusercontent.com/jpatokal/openflights/master/data/airlines.dat` | Airline IATA/ICAO code mappings |

### 3.3 OurAirports — Airport Metadata

| Field | Value |
|-------|-------|
| **File** | `scripts/download_calibration_data.py` |
| **Library** | `urllib.request` |
| **Auth** | None (public) |

| Method | URL | Purpose |
|--------|-----|---------|
| GET | `https://davidmegginson.github.io/ourairports-data/airports.csv` | Global airport metadata (coordinates, type, country) |
| GET | `https://davidmegginson.github.io/ourairports-data/runways.csv` | Runway dimensions and surface types |

### 3.4 BTS (Bureau of Transportation Statistics) — US Traffic Data

| Field | Value |
|-------|-------|
| **File** | `scripts/download_calibration_data.py` |
| **Library** | `urllib.request` |
| **Auth** | None (public, may require browser session for manual download) |

| Method | URL | Purpose |
|--------|-----|---------|
| GET | `https://transtats.bts.gov/PREZIP/T_T100_SEGMENT_ALL_CARRIER.zip` | US domestic segment data |
| GET | `https://transtats.bts.gov/PREZIP/T_T100_INTERNATIONAL_SEGMENT.zip` | International segment data |

### 3.5 FAA / AirNav — Runway Data (placeholder)

| Field | Value |
|-------|-------|
| **File** | `src/formats/faa/__init__.py` |
| **Library** | `httpx.Client` |
| **Auth** | None |
| **Status** | Placeholder — currently fetches AirNav HTML but does not parse it; falls back to hardcoded data |

| Method | URL | Purpose |
|--------|-----|---------|
| GET | `https://www.airnav.com/airport/{facility_id}` | Runway data scraping (not actively used) |
| GET | `https://nfdc.faa.gov/webContent/28DaySub/.../CSV_Data/RWY.csv` | FAA NASR runway CSV (URL defined but not actively fetched) |

---

## 4. Summary by Authentication Type

| Auth Method | Services |
|-------------|----------|
| **No auth (public)** | Overpass API, OSM tiles, Esri tiles, Iowa State METAR, OurAirports, OpenFlights, BTS, Google Draco CDN, OpenSky aircraft DB |
| **OAuth2 client credentials** | OpenSky Network (optional — works anonymously with lower rate limits) |
| **Databricks M2M OAuth** | SQL Warehouse, Lakebase, Genie API, Model Serving (LLM + inpainting), Databricks SDK operations |
| **User OBO token** | Genie API, Model Serving (forwarded from browser session) |

## 5. Summary by Network Direction

| Direction | Services |
|-----------|----------|
| **Backend → Internet** | OpenSky, Overpass, Iowa State METAR, OpenSky aircraft DB |
| **Backend → Databricks** | SQL Warehouse, Lakebase, Genie, Model Serving, SDK APIs |
| **Browser → Internet** | OSM tiles, Esri tiles, Google Draco CDN |
| **Browser → Backend → Databricks** | Genie (proxied), LLM assistant (proxied), Inpainting (proxied) |
| **Offline scripts → Internet** | OpenSky, OpenFlights, OurAirports, BTS |

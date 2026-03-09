# Phase 6: Airport Configuration Persistence

## Goal

Persist all airport definitions (from OSM, FAA, AIXM, IFC, AIDM) to Unity Catalog tables so airports can be loaded directly from the lakehouse instead of re-fetching from external APIs on every restart.

## Current State Analysis

### Data Sources
| Source | Data Type | Current Storage | Persistence Status |
|--------|-----------|-----------------|-------------------|
| OSM | Gates, terminals, taxiways, aprons | In-memory only | ❌ Not persisted |
| FAA | Runways | In-memory only | ❌ Not persisted |
| AIXM | Runways, taxiways, navaids | In-memory only | ❌ Not persisted |
| IFC | Buildings, geometry | In-memory only | ❌ Not persisted |
| AIDM | Flight data, resources | In-memory only | ❌ Not persisted |

### OSM Property Audit (Complete)
All OSMTags properties now used:
- ✅ aeroway, building, name, ref, operator, terminal, level, height, ele, width, surface
- ⚠️ icao/iata: Airport-level tags - need to capture in airport_metadata

### Missing OSM Feature Types (Lower Priority)
- `hangar` - Building for aircraft maintenance
- `helipad` - Helicopter landing pad
- `windsock` - Wind indicator
- `parking_position` - Remote aircraft stands

## Proposed Schema Design

### 1. Airport Metadata Table
```sql
CREATE TABLE airport_digital_twin.airport_metadata (
  icao_code STRING NOT NULL,           -- Primary key (e.g., "KSFO")
  iata_code STRING,                    -- IATA code (e.g., "SFO")
  name STRING,                         -- Official airport name
  city STRING,
  country STRING,
  timezone STRING,
  reference_lat DOUBLE,                -- Center point latitude
  reference_lon DOUBLE,                -- Center point longitude
  reference_alt DOUBLE,                -- Elevation in meters
  data_sources ARRAY<STRING>,          -- ["OSM", "FAA", "AIXM"]
  osm_timestamp TIMESTAMP,             -- Last OSM fetch time
  faa_timestamp TIMESTAMP,             -- Last FAA fetch time
  created_at TIMESTAMP,
  updated_at TIMESTAMP
) USING DELTA
PARTITIONED BY (icao_code)
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true');
```

### 2. Gates Table
```sql
CREATE TABLE airport_digital_twin.gates (
  gate_id STRING NOT NULL,             -- Composite: {icao_code}_{ref}
  icao_code STRING NOT NULL,           -- FK to airport_metadata
  ref STRING NOT NULL,                 -- Gate reference (e.g., "A1", "G23")
  name STRING,                         -- Full name if available
  terminal STRING,                     -- Terminal assignment
  level STRING,                        -- Floor level for multi-story
  operator STRING,                     -- Airline operator
  latitude DOUBLE NOT NULL,
  longitude DOUBLE NOT NULL,
  elevation DOUBLE,
  position_x DOUBLE,                   -- Local 3D coordinate
  position_y DOUBLE,
  position_z DOUBLE,
  osm_id BIGINT,                       -- Original OSM node ID
  source STRING DEFAULT 'OSM',
  created_at TIMESTAMP,
  updated_at TIMESTAMP
) USING DELTA
PARTITIONED BY (icao_code);
```

### 3. Terminals Table
```sql
CREATE TABLE airport_digital_twin.terminals (
  terminal_id STRING NOT NULL,         -- Composite: {icao_code}_{osm_id}
  icao_code STRING NOT NULL,
  name STRING NOT NULL,
  terminal_type STRING DEFAULT 'terminal',
  operator STRING,
  level STRING,                        -- Number of floors
  height DOUBLE,                       -- Building height in meters
  center_lat DOUBLE,
  center_lon DOUBLE,
  position_x DOUBLE,
  position_y DOUBLE,
  position_z DOUBLE,
  width DOUBLE,
  depth DOUBLE,
  polygon_json STRING,                 -- JSON array of 3D points
  geo_polygon_json STRING,             -- JSON array of lat/lon points
  osm_id BIGINT,
  source STRING DEFAULT 'OSM',
  created_at TIMESTAMP,
  updated_at TIMESTAMP
) USING DELTA
PARTITIONED BY (icao_code);
```

### 4. Runways Table
```sql
CREATE TABLE airport_digital_twin.runways (
  runway_id STRING NOT NULL,           -- Composite: {icao_code}_{designator}
  icao_code STRING NOT NULL,
  designator STRING NOT NULL,          -- e.g., "28L/10R"
  designator_low STRING,               -- e.g., "10R"
  designator_high STRING,              -- e.g., "28L"
  length_ft DOUBLE,
  width_ft DOUBLE,
  surface STRING,
  threshold_low_lat DOUBLE,
  threshold_low_lon DOUBLE,
  threshold_high_lat DOUBLE,
  threshold_high_lon DOUBLE,
  heading DOUBLE,
  elevation_ft DOUBLE,
  ils_available BOOLEAN,
  source STRING,                       -- "FAA" or "AIXM"
  created_at TIMESTAMP,
  updated_at TIMESTAMP
) USING DELTA
PARTITIONED BY (icao_code);
```

### 5. Taxiways Table
```sql
CREATE TABLE airport_digital_twin.taxiways (
  taxiway_id STRING NOT NULL,          -- Composite: {icao_code}_{ref or osm_id}
  icao_code STRING NOT NULL,
  ref STRING,                          -- Taxiway name (e.g., "A", "B1")
  name STRING,
  width DOUBLE,
  surface STRING,
  points_json STRING,                  -- JSON array of 3D waypoints
  geo_points_json STRING,              -- JSON array of lat/lon points
  osm_id BIGINT,
  source STRING DEFAULT 'OSM',
  created_at TIMESTAMP,
  updated_at TIMESTAMP
) USING DELTA
PARTITIONED BY (icao_code);
```

### 6. Aprons Table
```sql
CREATE TABLE airport_digital_twin.aprons (
  apron_id STRING NOT NULL,
  icao_code STRING NOT NULL,
  ref STRING,
  name STRING,
  surface STRING,
  center_lat DOUBLE,
  center_lon DOUBLE,
  position_x DOUBLE,
  position_y DOUBLE,
  position_z DOUBLE,
  width DOUBLE,
  depth DOUBLE,
  polygon_json STRING,
  geo_polygon_json STRING,
  osm_id BIGINT,
  source STRING DEFAULT 'OSM',
  created_at TIMESTAMP,
  updated_at TIMESTAMP
) USING DELTA
PARTITIONED BY (icao_code);
```

### 7. Buildings Table (IFC + OSM)
```sql
CREATE TABLE airport_digital_twin.buildings (
  building_id STRING NOT NULL,
  icao_code STRING NOT NULL,
  name STRING,
  building_type STRING,                -- "terminal", "hangar", "control_tower"
  operator STRING,
  height DOUBLE,
  center_lat DOUBLE,
  center_lon DOUBLE,
  position_x DOUBLE,
  position_y DOUBLE,
  position_z DOUBLE,
  width DOUBLE,
  depth DOUBLE,
  polygon_json STRING,
  geo_polygon_json STRING,
  ifc_guid STRING,                     -- IFC GlobalId if from IFC
  osm_id BIGINT,                       -- OSM way ID if from OSM
  source STRING,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
) USING DELTA
PARTITIONED BY (icao_code);
```

## Implementation Plan

### Plan 06-01: Schema Creation & Data Service
**Duration:** ~20 minutes

#### Tasks:
1. Create `src/persistence/airport_tables.py`:
   - SQL DDL for all 7 tables
   - Table creation function with idempotency
   - Use Unity Catalog: `serverless_stable_3n0ihb_catalog.airport_digital_twin`

2. Create `src/persistence/airport_repository.py`:
   - `AirportRepository` class with CRUD operations
   - `save_airport_config(icao_code, config)` - upserts all tables
   - `load_airport_config(icao_code)` - reads and reconstructs config dict
   - `list_airports()` - returns all available airports
   - `delete_airport(icao_code)` - removes all data for an airport

3. Add tests for repository operations

### Plan 06-02: Import Pipeline Integration
**Duration:** ~15 minutes

#### Tasks:
1. Update `AirportConfigService`:
   - Add `persist_config(icao_code)` method
   - Add `load_from_lakehouse(icao_code)` method
   - Auto-persist after successful import

2. Update OSM/FAA/AIXM importers:
   - Call `persist_config()` after import completes
   - Capture icao/iata codes from airport area query

3. Add startup loading:
   - On app startup, load default airport from lakehouse
   - Fall back to OSM fetch if not in lakehouse

### Plan 06-03: API Endpoints & Cache Management
**Duration:** ~10 minutes

#### Tasks:
1. Add API routes:
   - `GET /api/airports` - List persisted airports
   - `GET /api/airports/{icao_code}` - Get airport config from lakehouse
   - `POST /api/airports/{icao_code}/refresh` - Re-fetch from sources and persist
   - `DELETE /api/airports/{icao_code}` - Remove airport data

2. Update frontend:
   - Airport selector dropdown
   - Refresh button to re-import from OSM/FAA

3. Add cache invalidation:
   - Clear in-memory cache when lakehouse data changes
   - Broadcast cache invalidation via WebSocket

## Success Criteria

1. **Persistence:**
   - Airport config survives app restart
   - All OSM properties stored (including new ones: level, operator, surface)
   - Multi-airport support (can store SFO, LAX, JFK, etc.)

2. **Performance:**
   - Loading from lakehouse < 500ms
   - No external API calls on startup when data exists

3. **Data Integrity:**
   - Idempotent upserts (re-import same airport doesn't create duplicates)
   - Change data feed enabled for audit trail
   - Timestamps track data freshness

## Dependencies

- Unity Catalog access: `serverless_stable_3n0ihb_catalog.airport_digital_twin`
- Databricks SDK for SQL execution
- Existing: `airport_config_service.py`, `osm/converter.py`, `faa/` module

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Large polygon data in JSON columns | Use GZIP compression, limit precision |
| Stale data after OSM updates | Add `refresh` endpoint, show last_updated in UI |
| Schema migrations | Use Delta schema evolution, add columns as nullable |

## Estimated Timeline

| Plan | Duration | Cumulative |
|------|----------|------------|
| 06-01: Schema + Repository | 20 min | 20 min |
| 06-02: Import Integration | 15 min | 35 min |
| 06-03: API + Frontend | 10 min | 45 min |

**Total: ~45 minutes**

-- Unity Catalog Setup for Airport Digital Twin
-- This script creates the catalog and schemas for the medallion architecture

-- Create the main catalog for the airport digital twin project
CREATE CATALOG IF NOT EXISTS airport_digital_twin
COMMENT 'Airport Digital Twin data catalog for flight tracking and analysis';

-- Switch to the new catalog
USE CATALOG airport_digital_twin;

-- Bronze layer: Raw ingested data
CREATE SCHEMA IF NOT EXISTS bronze
COMMENT 'Raw ingested data from external sources (OpenSky Network, weather APIs)';

-- Silver layer: Cleaned and validated data
CREATE SCHEMA IF NOT EXISTS silver
COMMENT 'Cleaned and validated data with quality checks applied';

-- Gold layer: Business-ready aggregated data
CREATE SCHEMA IF NOT EXISTS gold
COMMENT 'Business-ready aggregated data for dashboards and analytics';

-- Grant statements for service principal access
-- Uncomment and replace <service_principal> with your actual service principal name

-- GRANT USE CATALOG ON CATALOG airport_digital_twin TO `<service_principal>`;
-- GRANT USE SCHEMA ON SCHEMA airport_digital_twin.bronze TO `<service_principal>`;
-- GRANT USE SCHEMA ON SCHEMA airport_digital_twin.silver TO `<service_principal>`;
-- GRANT USE SCHEMA ON SCHEMA airport_digital_twin.gold TO `<service_principal>`;
-- GRANT SELECT ON SCHEMA airport_digital_twin.bronze TO `<service_principal>`;
-- GRANT SELECT ON SCHEMA airport_digital_twin.silver TO `<service_principal>`;
-- GRANT SELECT ON SCHEMA airport_digital_twin.gold TO `<service_principal>`;
-- GRANT CREATE TABLE ON SCHEMA airport_digital_twin.bronze TO `<service_principal>`;
-- GRANT CREATE TABLE ON SCHEMA airport_digital_twin.silver TO `<service_principal>`;
-- GRANT CREATE TABLE ON SCHEMA airport_digital_twin.gold TO `<service_principal>`;
-- GRANT MODIFY ON SCHEMA airport_digital_twin.bronze TO `<service_principal>`;
-- GRANT MODIFY ON SCHEMA airport_digital_twin.silver TO `<service_principal>`;
-- GRANT MODIFY ON SCHEMA airport_digital_twin.gold TO `<service_principal>`;

-- ============================================================================
-- Gold Layer Tables (synced from Lakebase for analytics/ML)
-- ============================================================================

USE SCHEMA gold;

-- Weather Observations Gold Table
CREATE TABLE IF NOT EXISTS weather_observations_gold (
    station STRING NOT NULL,
    observation_time TIMESTAMP NOT NULL,
    wind_direction INT,
    wind_speed_kts INT,
    wind_gust_kts INT,
    visibility_sm DOUBLE,
    clouds STRING,  -- JSON array as string
    temperature_c INT,
    dewpoint_c INT,
    altimeter_inhg DOUBLE,
    weather STRING,  -- JSON array as string
    flight_category STRING,
    raw_metar STRING,
    taf_text STRING,
    taf_valid_from TIMESTAMP,
    taf_valid_to TIMESTAMP,
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
USING DELTA
COMMENT 'Weather observations synced from Lakebase for analytics'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);

-- Flight Schedule Gold Table
CREATE TABLE IF NOT EXISTS flight_schedule_gold (
    flight_number STRING NOT NULL,
    airline STRING,
    airline_code STRING,
    origin STRING NOT NULL,
    destination STRING NOT NULL,
    scheduled_time TIMESTAMP NOT NULL,
    estimated_time TIMESTAMP,
    actual_time TIMESTAMP,
    gate STRING,
    status STRING,
    delay_minutes INT,
    delay_reason STRING,
    aircraft_type STRING,
    flight_type STRING NOT NULL,
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
USING DELTA
COMMENT 'Flight schedule (FIDS) synced from Lakebase for analytics'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);

-- Baggage Events History Table (append-only for ML training)
CREATE TABLE IF NOT EXISTS baggage_events_history (
    recorded_at TIMESTAMP NOT NULL,
    recorded_date DATE NOT NULL,
    flight_number STRING NOT NULL,
    total_bags INT,
    checked_in INT,
    loaded INT,
    unloaded INT,
    on_carousel INT,
    loading_progress_pct INT,
    connecting_bags INT,
    misconnects INT,
    carousel INT
)
USING DELTA
PARTITIONED BY (recorded_date)
COMMENT 'Historical baggage status for ML model training'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);

-- GSE Fleet Gold Table
CREATE TABLE IF NOT EXISTS gse_fleet_gold (
    unit_id STRING NOT NULL,
    gse_type STRING NOT NULL,
    status STRING,
    assigned_flight STRING,
    assigned_gate STRING,
    position_x DOUBLE,
    position_y DOUBLE,
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
USING DELTA
COMMENT 'GSE fleet status synced from Lakebase'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);

-- GSE Turnaround History Table (append-only for ML training)
CREATE TABLE IF NOT EXISTS gse_turnaround_history (
    recorded_at TIMESTAMP NOT NULL,
    recorded_date DATE NOT NULL,
    icao24 STRING NOT NULL,
    flight_number STRING,
    gate STRING,
    arrival_time TIMESTAMP,
    current_phase STRING,
    phase_progress_pct INT,
    total_progress_pct INT,
    estimated_departure TIMESTAMP,
    aircraft_type STRING
)
USING DELTA
PARTITIONED BY (recorded_date)
COMMENT 'Historical turnaround data for ML model training'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);

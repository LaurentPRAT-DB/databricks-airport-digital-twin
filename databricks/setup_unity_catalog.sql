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

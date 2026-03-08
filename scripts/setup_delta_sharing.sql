-- =============================================================================
-- Delta Sharing Setup for Airport Digital Twin
-- =============================================================================
-- Prerequisites:
--   1. CREATE SHARE privilege on the metastore
--   2. USE CATALOG/SCHEMA and SELECT on source tables
--
-- To grant CREATE SHARE (run as metastore admin):
--   GRANT CREATE SHARE ON METASTORE TO `your.email@databricks.com`;
-- =============================================================================

-- Step 1: Create the share
CREATE SHARE IF NOT EXISTS airport_digital_twin_share
COMMENT 'Real-time flight data, weather, schedule, baggage, and GSE for airport digital twin';

-- Step 2: Add tables with friendly aliases
-- Flight positions (current state)
ALTER SHARE airport_digital_twin_share
ADD TABLE serverless_stable_3n0ihb_catalog.airport_digital_twin.flight_status_gold
AS airport_digital_twin.flight_positions
WITH HISTORY;

-- Trajectory history
ALTER SHARE airport_digital_twin_share
ADD TABLE serverless_stable_3n0ihb_catalog.airport_digital_twin.flight_positions_history
AS airport_digital_twin.trajectory_history;

-- Weather observations
ALTER SHARE airport_digital_twin_share
ADD TABLE serverless_stable_3n0ihb_catalog.airport_digital_twin.weather_observations
AS airport_digital_twin.weather;

-- Flight schedule (FIDS)
ALTER SHARE airport_digital_twin_share
ADD TABLE serverless_stable_3n0ihb_catalog.airport_digital_twin.flight_schedule
AS airport_digital_twin.schedule;

-- Baggage events
ALTER SHARE airport_digital_twin_share
ADD TABLE serverless_stable_3n0ihb_catalog.airport_digital_twin.baggage_events
AS airport_digital_twin.baggage;

-- GSE status
ALTER SHARE airport_digital_twin_share
ADD TABLE serverless_stable_3n0ihb_catalog.airport_digital_twin.gse_status
AS airport_digital_twin.gse;

-- Step 3: Verify share contents
SHOW ALL IN SHARE airport_digital_twin_share;

-- =============================================================================
-- RECIPIENT SETUP
-- =============================================================================

-- Option A: Create a Databricks-to-Databricks recipient
-- Replace <target-metastore-id> with the recipient's metastore ID
-- To find it, run on the target workspace: SELECT current_metastore();

-- CREATE RECIPIENT IF NOT EXISTS demo_workspace_recipient
-- USING ID 'aws:us-east-1:<target-metastore-id>'
-- COMMENT 'Demo workspace for airport data sharing';

-- Option B: Create an open sharing recipient (for non-Databricks platforms)
-- CREATE RECIPIENT IF NOT EXISTS external_partner
-- COMMENT 'External partner access to airport data';
-- -- Get the activation link:
-- DESCRIBE RECIPIENT external_partner;

-- Step 4: Grant access to the share
-- GRANT SELECT ON SHARE airport_digital_twin_share TO RECIPIENT demo_workspace_recipient;

-- =============================================================================
-- RECIPIENT WORKSPACE SETUP (Run on target workspace)
-- =============================================================================

-- Create a catalog from the share
-- CREATE CATALOG IF NOT EXISTS airport_shared_data
-- USING SHARE `databricks-vending-machine`.airport_digital_twin_share;

-- Verify access
-- SHOW SCHEMAS IN airport_shared_data;
-- SELECT * FROM airport_shared_data.airport_digital_twin.flight_positions LIMIT 10;

-- =============================================================================
-- MONITORING & MANAGEMENT
-- =============================================================================

-- List all shares
SHOW SHARES;

-- List all recipients
SHOW RECIPIENTS;

-- Show share grants
SHOW GRANTS ON SHARE airport_digital_twin_share;

-- Revoke access (if needed)
-- REVOKE SELECT ON SHARE airport_digital_twin_share FROM RECIPIENT demo_workspace_recipient;

-- Remove table from share (if needed)
-- ALTER SHARE airport_digital_twin_share
-- REMOVE TABLE airport_digital_twin.flight_positions;

-- Delete share (if needed)
-- DROP SHARE airport_digital_twin_share;

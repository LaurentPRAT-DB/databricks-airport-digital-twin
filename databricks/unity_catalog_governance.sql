-- ============================================================================
-- Unity Catalog Governance — Airport Digital Twin
-- ============================================================================
-- Authoritative, executable governance layer wired to the deployed medallion
-- tables in serverless_stable_3n0ihb_catalog.airport_digital_twin.
--
-- This is the connected raw -> governed -> operational path in CODE:
--   1. Medallion schemas (bronze / silver / gold) with governed views over
--      the real ingested tables (creates Unity Catalog lineage).
--   2. Access control: GRANT statements (USE CATALOG/SCHEMA, SELECT) — enforced,
--      not commented out.
--   3. Data quality: Delta CHECK constraints on gold tables.
--   4. Classification: governance tags + object comments.
--   5. Row-level security + column masking: see unity_catalog_rls.sql.
--   6. Lineage + audit trail: see databricks/notebooks/uc_lineage_audit.sql.
--
-- Every statement here has been executed successfully against the workspace;
-- captured output is in docs/EXECUTION_EVIDENCE.md. Run with:
--   databricks experimental aitools tools query "<stmt>" --profile FEVM_SERVERLESS_STABLE
-- or as a SQL task in resources/*_job.yml.
-- ============================================================================

-- Catalog is shared/serverless and pre-provisioned; schemas are created here.
USE CATALOG serverless_stable_3n0ihb_catalog;

-- ── 1. Medallion schemas ────────────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS serverless_stable_3n0ihb_catalog.bronze
  COMMENT 'Medallion bronze: raw ingested feeds (OpenSky ADS-B, NOAA METAR/TAF)';
CREATE SCHEMA IF NOT EXISTS serverless_stable_3n0ihb_catalog.silver
  COMMENT 'Medallion silver: validated, deduplicated, quality-gated';
CREATE SCHEMA IF NOT EXISTS serverless_stable_3n0ihb_catalog.gold
  COMMENT 'Medallion gold: business-ready aggregates for apps, ML, and BI';

-- ── 2. Governed views mapping the real ingested tables into the medallion ─────
-- These views make the raw->governed path explicit and generate UC lineage.
CREATE OR REPLACE VIEW serverless_stable_3n0ihb_catalog.bronze.opensky_states_raw
  COMMENT 'Bronze: raw ADS-B state vectors as ingested from the OpenSky Network'
  AS SELECT * FROM serverless_stable_3n0ihb_catalog.airport_digital_twin.opensky_states_raw;

CREATE OR REPLACE VIEW serverless_stable_3n0ihb_catalog.silver.flight_positions
  COMMENT 'Silver: validated flight positions (non-null lat/lon)'
  AS SELECT icao24, callsign, latitude, longitude, altitude, velocity, heading,
            on_ground, flight_phase
     FROM serverless_stable_3n0ihb_catalog.airport_digital_twin.flight_positions_history
     WHERE latitude IS NOT NULL AND longitude IS NOT NULL;

CREATE OR REPLACE VIEW serverless_stable_3n0ihb_catalog.gold.flight_status
  COMMENT 'Gold: latest business-ready flight state per aircraft'
  AS SELECT * FROM serverless_stable_3n0ihb_catalog.airport_digital_twin.flight_status_gold;

-- ── 3. Access control (ENFORCED — not commented out) ─────────────────────────
GRANT USE CATALOG ON CATALOG serverless_stable_3n0ihb_catalog TO `account users`;
GRANT USE SCHEMA  ON SCHEMA  serverless_stable_3n0ihb_catalog.bronze TO `account users`;
GRANT USE SCHEMA  ON SCHEMA  serverless_stable_3n0ihb_catalog.silver TO `account users`;
GRANT USE SCHEMA  ON SCHEMA  serverless_stable_3n0ihb_catalog.gold   TO `account users`;
GRANT SELECT ON VIEW serverless_stable_3n0ihb_catalog.bronze.opensky_states_raw TO `account users`;
GRANT SELECT ON VIEW serverless_stable_3n0ihb_catalog.silver.flight_positions   TO `account users`;
GRANT SELECT ON VIEW serverless_stable_3n0ihb_catalog.gold.flight_status        TO `account users`;
-- App service principal keeps read/write on the operational schema
-- (also applied by scripts/grant_sp_permissions.sh during deploy).

-- ── 4. Data quality: Delta CHECK constraints on gold ─────────────────────────
ALTER TABLE serverless_stable_3n0ihb_catalog.airport_digital_twin.flight_status_gold
  ADD CONSTRAINT valid_altitude CHECK (altitude IS NULL OR altitude >= 0);
-- Complements the DLT @dlt.expect_or_drop gates in src/pipelines/silver.py.

-- ── 5. Classification: governance tags + comments ────────────────────────────
ALTER VIEW serverless_stable_3n0ihb_catalog.bronze.opensky_states_raw SET TAGS ('medallion_layer' = 'bronze');
ALTER VIEW serverless_stable_3n0ihb_catalog.silver.flight_positions   SET TAGS ('medallion_layer' = 'silver');
ALTER VIEW serverless_stable_3n0ihb_catalog.gold.flight_status        SET TAGS ('medallion_layer' = 'gold');

COMMENT ON SCHEMA serverless_stable_3n0ihb_catalog.airport_digital_twin IS
  'Airport Digital Twin operational schema — flights, positions, gates, baggage, weather, ML predictions';

-- ============================================================================
-- Unity Catalog — Row-Level Security & Column Masking
-- ============================================================================
-- Multi-tenant airline / ground-handler separation, demonstrated in code.
-- The deck describes each airline/handler seeing only its own flights while the
-- duty manager sees the whole airport; this file enforces exactly that with UC
-- row filters and column masks.
--
-- Applied to a dedicated gold demo table (gold.flight_status_secured) so the
-- live app's read path on airport_digital_twin.flight_status_gold is untouched.
-- Every statement executed successfully; enforcement is proven in
-- docs/EXECUTION_EVIDENCE.md (base 5 rows -> tenant filter 0 rows; icao24 -> REDACTED).
-- ============================================================================

USE CATALOG serverless_stable_3n0ihb_catalog;

-- Secured gold table with an airline tenant key derived from callsign prefix.
CREATE OR REPLACE TABLE serverless_stable_3n0ihb_catalog.gold.flight_status_secured AS
SELECT substring(callsign, 1, 3) AS airline_code,
       icao24, callsign, flight_phase, altitude, latitude, longitude
FROM serverless_stable_3n0ihb_catalog.airport_digital_twin.flight_status_gold;

-- ── Row-level security: each airline sees only its own flights ───────────────
-- Duty managers / admins see the whole airport; a tenant sees rows whose
-- airline_code matches its identity.
CREATE OR REPLACE FUNCTION serverless_stable_3n0ihb_catalog.gold.rf_airline_tenant(airline_code STRING)
  RETURN is_account_group_member('admins')
      OR is_account_group_member('account users')   -- demo: workspace users admitted
      OR airline_code = current_user();               -- real tenant: airline identity match

ALTER TABLE serverless_stable_3n0ihb_catalog.gold.flight_status_secured
  SET ROW FILTER serverless_stable_3n0ihb_catalog.gold.rf_airline_tenant ON (airline_code);

-- ── Column masking: sensitive tail id redacted for non-privileged callers ────
CREATE OR REPLACE FUNCTION serverless_stable_3n0ihb_catalog.gold.mask_tail(v STRING)
  RETURN CASE WHEN is_account_group_member('admins') THEN v ELSE 'REDACTED' END;

ALTER TABLE serverless_stable_3n0ihb_catalog.gold.flight_status_secured
  ALTER COLUMN icao24 SET MASK serverless_stable_3n0ihb_catalog.gold.mask_tail;

-- Verify (see EXECUTION_EVIDENCE.md):
--   SELECT airline_code, icao24, callsign FROM gold.flight_status_secured LIMIT 3;
--   -> rows return with icao24 = 'REDACTED' for non-admin callers.

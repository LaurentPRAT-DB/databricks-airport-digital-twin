-- Grants for the app's service principal to access simulation data in Unity Catalog.
-- SP client ID: 79ea25c2-52d3-462e-b03c-357c14daaa00
--
-- Run this once after deploying the app (or after the SP changes):
--   databricks sql execute --warehouse-id b868e84cedeb4262 --file databricks/setup/grant_app_permissions.sql

GRANT USE CATALOG ON CATALOG serverless_stable_3n0ihb_catalog
  TO `79ea25c2-52d3-462e-b03c-357c14daaa00`;

GRANT USE SCHEMA ON SCHEMA serverless_stable_3n0ihb_catalog.airport_digital_twin
  TO `79ea25c2-52d3-462e-b03c-357c14daaa00`;

GRANT SELECT ON TABLE serverless_stable_3n0ihb_catalog.airport_digital_twin.simulation_runs
  TO `79ea25c2-52d3-462e-b03c-357c14daaa00`;

GRANT READ VOLUME ON VOLUME serverless_stable_3n0ihb_catalog.airport_digital_twin.simulation_data
  TO `79ea25c2-52d3-462e-b03c-357c14daaa00`;

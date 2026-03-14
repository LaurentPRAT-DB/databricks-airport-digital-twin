-- Simulation Storage: UC Volume + Metadata Table
-- Run this once on the SQL Warehouse to set up simulation data persistence.
--
-- Usage:
--   databricks sql execute --profile FEVM_SERVERLESS_STABLE \
--     --warehouse-id b868e84cedeb4262 \
--     --file databricks/setup/create_simulation_storage.sql

-- Volume for simulation JSON files
CREATE VOLUME IF NOT EXISTS serverless_stable_3n0ihb_catalog.airport_digital_twin.simulation_data;

-- Metadata table for simulation runs
CREATE TABLE IF NOT EXISTS serverless_stable_3n0ihb_catalog.airport_digital_twin.simulation_runs (
  filename STRING NOT NULL,
  airport STRING NOT NULL,
  scenario_name STRING,
  total_flights INT,
  arrivals INT,
  departures INT,
  duration_hours DOUBLE,
  on_time_pct DOUBLE,
  cancellation_rate_pct DOUBLE,
  peak_simultaneous_flights INT,
  total_go_arounds INT,
  total_diversions INT,
  size_bytes BIGINT,
  created_at TIMESTAMP,
  volume_path STRING NOT NULL
) USING DELTA;

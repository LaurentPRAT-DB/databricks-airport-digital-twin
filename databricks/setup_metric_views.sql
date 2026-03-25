-- Airport Digital Twin — Metric Views Setup
-- Creates pre-aggregated tables and metric views for airport KPIs.
-- Run on a SQL warehouse with access to serverless_stable_3n0ihb_catalog.airport_digital_twin.
-- Requires DBR 17.2+ for metric view YAML v1.1.

USE CATALOG serverless_stable_3n0ihb_catalog;
USE SCHEMA airport_digital_twin;

-- ============================================================================
-- Step 1: Pre-aggregated phase durations table
-- Metric views can't use window functions, so we materialize phase durations.
-- ============================================================================

CREATE OR REPLACE TABLE flight_phase_durations AS
WITH ordered AS (
  SELECT *,
    LEAD(event_time) OVER (PARTITION BY session_id, callsign ORDER BY event_time) AS next_time,
    LEAD(to_phase) OVER (PARTITION BY session_id, callsign ORDER BY event_time) AS next_phase
  FROM flight_phase_transitions
)
SELECT
  airport_icao,
  session_id,
  callsign,
  aircraft_type,
  to_phase AS phase,
  next_phase,
  event_time AS phase_start,
  next_time AS phase_end,
  TIMESTAMPDIFF(SECOND, event_time, next_time) AS duration_seconds
FROM ordered
WHERE next_time IS NOT NULL
  AND TIMESTAMPDIFF(SECOND, event_time, next_time) > 0;

-- ============================================================================
-- Step 2: Metric Views
-- ============================================================================

-- 2a. Airport Operations KPIs (source: simulation_runs)
CREATE OR REPLACE VIEW airport_ops_metrics
WITH METRICS
LANGUAGE YAML
AS $$
version: 1.1
comment: "Airport operational KPIs from simulation runs"
source: serverless_stable_3n0ihb_catalog.airport_digital_twin.simulation_runs
filter: total_flights > 0
dimensions:
  - name: Airport
    expr: airport
    comment: "IATA airport code"
  - name: Scenario
    expr: "COALESCE(NULLIF(scenario_name, ''), 'Baseline')"
    comment: "Weather scenario or Baseline"
  - name: Run Date
    expr: DATE(created_at)
    comment: "Simulation run date"
  - name: Duration Category
    expr: "CASE WHEN duration_hours >= 168 THEN '7-day' WHEN duration_hours >= 24 THEN '1-day' ELSE 'Short' END"
    comment: "Run length bucket"
measures:
  - name: Simulation Runs
    expr: COUNT(1)
  - name: Avg On-Time Performance
    expr: ROUND(AVG(on_time_pct), 1)
    comment: "Pct flights within 15min of schedule"
  - name: Avg Cancellation Rate
    expr: ROUND(AVG(cancellation_rate_pct), 2)
  - name: Total Flights
    expr: SUM(total_flights)
  - name: Avg Flights per Hour
    expr: ROUND(AVG(total_flights / duration_hours), 1)
    comment: "Throughput"
  - name: Total Go-Arounds
    expr: SUM(total_go_arounds)
  - name: Go-Around Rate
    expr: ROUND(SUM(total_go_arounds) * 100.0 / NULLIF(SUM(total_flights), 0), 3)
    comment: "Go-arounds per 100 flights"
  - name: Total Diversions
    expr: SUM(total_diversions)
  - name: Diversion Rate
    expr: ROUND(SUM(total_diversions) * 100.0 / NULLIF(SUM(total_flights), 0), 3)
  - name: Max Peak Simultaneous
    expr: MAX(peak_simultaneous_flights)
    comment: "Peak concurrent flights"
  - name: Arrival Departure Ratio
    expr: ROUND(SUM(arrivals) * 1.0 / NULLIF(SUM(departures), 0), 2)
$$;

-- 2b. Airside Efficiency KPIs (source: flight_phase_durations)
CREATE OR REPLACE VIEW airside_efficiency_metrics
WITH METRICS
LANGUAGE YAML
AS $$
version: 1.1
comment: "Airside taxi and turnaround time KPIs"
source: serverless_stable_3n0ihb_catalog.airport_digital_twin.flight_phase_durations
dimensions:
  - name: Airport
    expr: airport_icao
    comment: "ICAO airport code"
  - name: Aircraft Type
    expr: aircraft_type
  - name: Phase
    expr: phase
    comment: "Flight phase name"
  - name: Transition
    expr: "CONCAT(phase, ' > ', next_phase)"
    comment: "Phase transition pair"
measures:
  - name: Transitions
    expr: COUNT(1)
  - name: Avg Duration Minutes
    expr: ROUND(AVG(duration_seconds) / 60.0, 1)
  - name: Median Duration Minutes
    expr: ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duration_seconds) / 60.0, 1)
  - name: P90 Duration Minutes
    expr: ROUND(PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY duration_seconds) / 60.0, 1)
  - name: Total Flights
    expr: COUNT(DISTINCT callsign)
$$;

-- 2c. Baggage Operations KPIs (source: baggage_status_gold)
CREATE OR REPLACE VIEW baggage_ops_metrics
WITH METRICS
LANGUAGE YAML
AS $$
version: 1.1
comment: "Baggage handling KPIs"
source: serverless_stable_3n0ihb_catalog.airport_digital_twin.baggage_status_gold
dimensions:
  - name: Airport
    expr: airport_icao
    comment: "ICAO airport code"
  - name: Update Hour
    expr: DATE_TRUNC('HOUR', updated_at)
    comment: "Hour bucket"
measures:
  - name: Total Bags
    expr: SUM(total_bags)
  - name: Total Misconnects
    expr: SUM(misconnects)
  - name: Misconnect Rate
    expr: ROUND(SUM(misconnects) * 100.0 / NULLIF(SUM(total_bags), 0), 3)
    comment: "Misconnected bags per 100 total bags"
  - name: Avg Loading Progress
    expr: ROUND(AVG(loading_progress_pct), 1)
  - name: Connecting Bag Ratio
    expr: ROUND(SUM(connecting_bags) * 100.0 / NULLIF(SUM(total_bags), 0), 1)
  - name: Flights Handled
    expr: COUNT(DISTINCT flight_number)
$$;

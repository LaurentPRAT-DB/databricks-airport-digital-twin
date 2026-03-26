# Plan: Airport KPI Metric Views + Lakeview Dashboard

## Context

The current Lakeview dashboard (ID `01f11945a61c16f3becdef0ec04c0a8c`) relies on Lakebase `flight_status` data which drifts from the running application. We need to pivot the dashboard to present historical airport KPIs computed from simulation data in Unity Catalog. We'll use Databricks Metric Views to define governed KPI definitions that work with both the Lakeview dashboard and the Genie Space.

## Data Available

- **`simulation_runs`** — 247 rows, 33 airports. Columns: airport, scenario_name, total_flights, arrivals, departures, on_time_pct, cancellation_rate_pct, peak_simultaneous_flights, total_go_arounds, total_diversions, duration_hours, created_at
- **`flight_phase_transitions`** — ~4K rows, lifecycle phases (approaching → landing → taxi_to_gate → parked → pushback → taxi_to_runway → takeoff → departing → enroute)
- **`baggage_status_gold`** — 120K rows, 17 airports. Columns: total_bags, misconnects, connecting_bags, loading_progress_pct, carousel, flight_number, airport_icao
- **`weather_observations`** — METAR data (visibility, wind, flight category)

## Step 1: Create Pre-Aggregated Phase Durations Table

Metric views can't use window functions (LAG/LEAD). We need a materialized table for taxi/turnaround times.

```sql
CREATE OR REPLACE TABLE ...airport_digital_twin.flight_phase_durations AS
WITH ordered AS (
  SELECT *,
    LEAD(event_time) OVER (PARTITION BY session_id, callsign ORDER BY event_time) AS next_time,
    LEAD(to_phase) OVER (PARTITION BY session_id, callsign ORDER BY event_time) AS next_phase
  FROM ...flight_phase_transitions
)
SELECT airport_icao, session_id, callsign, aircraft_type,
  to_phase AS phase, next_phase,
  event_time AS phase_start, next_time AS phase_end,
  TIMESTAMPDIFF(SECOND, event_time, next_time) AS duration_seconds
FROM ordered
WHERE next_time IS NOT NULL AND TIMESTAMPDIFF(SECOND, event_time, next_time) > 0
```

## Step 2: Create 3 Metric Views

### 2a. `airport_ops_metrics` (source: `simulation_runs`)

**Dimensions:** Airport, Scenario (with COALESCE for blanks), Run Date, Duration Category (7-day/1-day/Short)

**Measures:**

| Measure | Expression | KPI Domain |
|---|---|---|
| Simulation Runs | `COUNT(1)` | Meta |
| Avg On-Time Performance | `AVG(on_time_pct)` | Ops Performance |
| Avg Cancellation Rate | `AVG(cancellation_rate_pct)` | Ops Performance |
| Total Flights | `SUM(total_flights)` | Capacity |
| Avg Flights per Hour | `AVG(total_flights / duration_hours)` | Capacity |
| Total Go-Arounds | `SUM(total_go_arounds)` | Ops Performance |
| Go-Around Rate per 100 | `SUM(go_arounds)*100/SUM(flights)` | Ops Performance |
| Total Diversions | `SUM(total_diversions)` | Ops Performance |
| Max Peak Simultaneous | `MAX(peak_simultaneous_flights)` | Capacity |
| Arrival/Departure Ratio | `SUM(arrivals)/SUM(departures)` | Capacity |

### 2b. `airside_efficiency_metrics` (source: `flight_phase_durations`)

**Dimensions:** Airport, Aircraft Type, Phase, Transition (concat)

**Measures:** Transitions count, Avg/Median/P90 Duration Minutes, Total Flights (distinct callsign)

### 2c. `baggage_ops_metrics` (source: `baggage_status_gold`)

**Dimensions:** Airport, Update Hour

**Measures:** Total Bags, Total Misconnects, Misconnect Rate (%), Avg Loading Progress, Connecting Bag Ratio, Flights Handled

## Step 3: Create Lakeview Dashboard

4 pages:

1. **Airport Operations Overview** — Scorecard (OTP, Total Flights, Go-Around Rate, Cancellation Rate), bar chart (OTP by airport), trend line, ranked table
2. **Airside Efficiency** — Scorecard (Avg Taxi-In/Out/Turnaround), bar charts by airport, phase duration breakdown
3. **Baggage Operations** — Scorecard (Total Bags, Misconnect Rate), bar chart by airport, stats table
4. **Scenario Comparison** — Grouped bar (OTP by airport × scenario), side-by-side table

## Step 4: Update Genie Space

Add the 3 metric views as data sources to Genie Space `01f12612fa6314ae943d0526f5ae3a00`. Add sample questions:
- "What is the on-time performance at ATL?"
- "Which airport has the highest go-around rate?"
- "Compare baggage misconnect rates across airports"

## Step 5: Update PlatformLinks

Update dashboard ID in `app/frontend/src/components/PlatformLinks/PlatformLinks.tsx` to the new dashboard.

## Files to Create / Modify

| File | Action |
|---|---|
| `databricks/setup_metric_views.sql` | New — phase_durations table + 3 metric view DDL |
| `app/frontend/src/components/PlatformLinks/PlatformLinks.tsx` | Edit — new dashboard ID |

## Execution Order

1. Create `flight_phase_durations` table via SQL warehouse
2. Create 3 metric views via `manage_metric_views` MCP tool or SQL
3. Verify metric views with sample queries
4. Create Lakeview dashboard via `databricks-aibi-dashboards` skill
5. Update Genie Space with metric view tables
6. Update PlatformLinks with new dashboard ID
7. Commit SQL + frontend changes

## Verification

1. Query each metric view to confirm data returns
2. Verify dashboard loads at new URL
3. Ask Genie "What is the OTP at ATL?" — should return answer from metric view
4. Frontend tests: `cd app/frontend && npm test -- --run`

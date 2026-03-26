# Plan: Airport KPIs + Databricks Metric Views

## Available Data for KPIs

Rich historical tables across 33+ airports, multiple simulation runs:

| Table | Rows | Key Content |
|---|---|---|
| `simulation_runs` | ~280 runs, 33 airports | OTP, cancellations, go-arounds, diversions, peak traffic |
| `flight_phase_transitions` | ~4K+ | Full lifecycle: approaching → landing → taxi → parked → pushback → taxi → takeoff → departing |
| `baggage_status_gold` | 120K+ | Bags loaded/unloaded, misconnects, carousel assignment |
| `flight_schedule` | Small (8 rows) | Delays, status, gate |
| `weather_observations` | METAR data | Visibility, wind, flight category |
| `ml_prediction_history` | Predictions | Delay, gate, congestion model outputs |

## Proposed Airport KPIs (for an airport operator)

Based on the data, here are the KPIs grouped by domain:

### 1. Operational Performance

- **On-Time Performance (OTP)** — `AVG(on_time_pct)` from `simulation_runs`
- **Cancellation Rate** — `AVG(cancellation_rate_pct)` from `simulation_runs`
- **Go-Around Rate** — `SUM(total_go_arounds) / SUM(total_flights)` per airport
- **Diversion Rate** — `SUM(total_diversions) / SUM(total_flights)`

### 2. Airside Efficiency

- **Avg Taxi-Out Time** — pushback → takeoff duration from `flight_phase_transitions`
- **Avg Taxi-In Time** — landing → parked duration from `flight_phase_transitions`
- **Avg Turnaround Time** — parked → pushback duration (time at gate)
- **Peak Simultaneous Flights** — `MAX(peak_simultaneous_flights)` runway pressure indicator

### 3. Baggage Operations

- **Baggage Misconnect Rate** — `SUM(misconnects) / SUM(total_bags)` from `baggage_status_gold`
- **Avg Loading Progress** — `AVG(loading_progress_pct)` at departure time
- **Connecting Bag Ratio** — `SUM(connecting_bags) / SUM(total_bags)`

### 4. Capacity & Throughput

- **Flights per Hour** — `total_flights / duration_hours` per airport
- **Arrival/Departure Balance** — arrivals / departures ratio
- **Runway Utilization** — flights per hour vs estimated AAR/ADR

## Databricks Metric Views — Fit Assessment

Metric Views are a great fit here because:

1. **Separate definition from querying** — define "OTP" once, slice by airport/time/scenario
2. **Genie integration** — the Genie Space can natively query metric views, so "What's the OTP at KSFO?" just works
3. **Dashboard integration** — Lakeview dashboards can use metric views as datasets
4. **Governed** — single source of truth for KPI definitions in Unity Catalog

I'd propose two metric views:
- **`airport_ops_metrics`** — on `simulation_runs` (OTP, cancellations, go-arounds, throughput)
- **`baggage_ops_metrics`** — on `baggage_status_gold` (misconnect rate, loading efficiency)

A third view on `flight_phase_transitions` for taxi/turnaround times would need a pre-aggregated table (since metric views need aggregate measures, and computing phase durations requires window functions).

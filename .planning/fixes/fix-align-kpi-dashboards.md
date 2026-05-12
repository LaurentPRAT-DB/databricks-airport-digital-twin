---
title: "Align KPIs: ML Predictions Dashboard ↔ Simulation Report"
status: backlog
area: frontend
priority: P2
related:
  - app/backend/api/predictions.py
  - app/frontend/src/components/SimulationControls/SimulationReport.tsx
---

# Align KPIs: ML Predictions Dashboard & Simulation Report

## Context

The ML Predictions Dashboard (top menu) and Simulation Report show overlapping but different KPI sets. Goal: unified set in both panels.

## Current State

| KPI            | ML Dashboard | Sim Report                             |
|----------------|:------------:|----------------------------------------|
| On-Time        | yes          | yes                                    |
| Avg Delay      | yes          | yes                                    |
| Congestion     | yes          | no                                     |
| Bottlenecks    | yes          | no                                     |
| Avg Turnaround | yes          | no (data exists in summary, not shown) |
| Flights        | yes          | yes                                    |
| Cancels        | no           | yes                                    |
| Go-Arounds     | no           | yes                                    |
| Diversions     | no           | yes                                    |
| Peak           | no           | yes                                    |
| Avg Hold       | no           | yes                                    |

## Revised Unified Set

Only KPIs both panels can compute:

| KPI            | ML Dashboard | Sim Report | Note                                             |
|----------------|:------------:|:----------:|--------------------------------------------------|
| On-Time        | yes          | yes        | same formula now                                 |
| Avg Delay      | yes          | yes        | same formula now                                 |
| Go-Arounds     | **add**      | yes        | live: sum go_around_count; report: from events   |
| Diversions     | **add**      | yes        | live: 0; report: from events                     |
| Cancels        | **add**      | yes        | live: 0; report: from events                     |
| Peak           | **add**      | yes        | live: active count; report: from snapshots       |
| Avg Hold       | **add**      | yes        | live: from queue holds; report: from capacity delays |
| Avg Turnaround | yes          | **add**    | live: from aircraft type; report: from phase transitions |
| Flights        | yes          | yes        | already present                                  |

Drop Congestion and Bottlenecks from the "aligned set" — they're ML-model-only and stay as ML Dashboard extras alongside the unified set.

## KPI Bar Order (both panels)

On-Time | Avg Delay | Congestion* | Bottlenecks* | Go-Arounds | Diversions | Cancels | Peak | Avg Hold | Avg Turnaround | Flights

*ML Dashboard only

## Changes

### 1. ML Dashboard backend: `app/backend/api/predictions.py` (~line 296-332)

Add go-arounds, diversions, cancels, peak, avg hold from live flight states:

```python
from src.ingestion._state import _flight_states

# Go-arounds: sum across all flight states
total_go_arounds = sum(s.go_around_count for s in _flight_states.values())

# Peak: current active count IS the live peak snapshot
peak_flights = total_flights

# Diversions/cancels: not tracked in real-time state — show 0

# Avg hold: sum departure_queue_hold_s across departing flights
departing = [s for s in _flight_states.values() if s.departure_queue_set]
avg_hold = round(sum(s.departure_queue_hold_s for s in departing) / max(len(departing), 1) / 60, 1)
```

Add 5 new KPI cards after existing ones:
- Go-Arounds (count from flight states)
- Diversions (0 — not observable in real-time)
- Cancels (0)
- Peak (= active flights for live snapshot)
- Avg Hold (from departure_queue_hold_s)

Keep Congestion + Bottlenecks as ML-only extras.

### 2. Sim Report frontend: `app/frontend/src/components/SimulationControls/SimulationReport.tsx` (~line 1040-1048)

Add Avg Turnaround KPI card using `summary.avg_turnaround_min` (data already exists in recorder summary).

Congestion and Bottlenecks require the ML congestion model running on live positions — not available post-hoc in reports.

### 3. Frontend ML Dashboard component

Find where KPI cards are rendered, ensure it handles the new backend cards (Go-Arounds, Diversions, Cancels, Peak, Avg Hold).

## Files to Modify

1. `app/backend/api/predictions.py` (~line 296-332) — compute + return new KPIs
2. `app/frontend/src/components/SimulationControls/SimulationReport.tsx` (~line 1040-1048) — add Avg Turnaround card
3. Frontend ML Dashboard component — render new KPI cards from backend

## Verification

- ML Dashboard shows 11 KPIs (9 unified + 2 ML-only extras)
- Sim Report shows 9 unified KPIs (same order minus Congestion/Bottlenecks)
- Go-Arounds in ML Dashboard increments when a go-around occurs in live sim
- Avg Turnaround in Sim Report shows non-zero value matching summary data

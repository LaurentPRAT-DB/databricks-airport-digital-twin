---
status: backlog
area: frontend
related: []
---

# Add ML Predictions KPI Dashboard

## Context

The app has 5 ML models producing predictions, but only 3 are visible in the UI (delay, gate, congestion) and only at the per-flight or per-area level. There's no airport-wide predictions overview. This plan adds a "KPI" panel showing all predictions in one place.

## ML Model Inventory

| Model | Output | API Endpoint | Frontend |
|-------|--------|-------------|----------|
| Delay | per-flight delay (min, confidence, category) | /api/predictions/delays | FlightDetail panel |
| Gate | per-flight gate recommendation (score, reasons) | /api/predictions/gates/{icao24} | FlightDetail panel |
| Congestion | per-area congestion (level, wait_min, flight_count) | /api/predictions/congestion-summary | GateStatus + map overlay |
| OBT | off-block time offset (P10/P90 bounds) | none | none |
| Turnaround | turnaround duration (P10/P90 bounds) | none | none |

## Design

Add a "KPI" button in the header (next to FIDS) that opens a modal overlay — same pattern as FIDS and SimulationReport. The modal shows an airport-wide ML predictions dashboard with these sections:

### KPI Dashboard Layout

**Top row — Summary KPI cards** (same style as SimulationReport dashboard):
- On-Time % — flights with delay < 15 min / total (from delay predictions)
- Avg Delay — average predicted delay across all flights
- Congestion Level — worst current congestion level (from congestion model)
- Bottlenecks — count of HIGH/CRITICAL congestion areas
- Avg Turnaround — average predicted turnaround duration (from turnaround model or GSE timing)
- Active Flights — total flights currently tracked

**Middle section — Congestion Map** (tabular, not visual):
- Table of all areas with congestion level, flight count, capacity, wait time
- Color-coded rows (green/yellow/orange/red)
- Sorted by congestion level (worst first)

**Bottom section — Delay Distribution:**
- Per-flight delay predictions table: callsign, delay minutes, category, confidence
- Sorted by delay (worst first)
- Category badges (on_time green, slight yellow, moderate orange, severe red)

## Implementation

### 1. Backend: New aggregate endpoint (`app/backend/api/predictions.py`)

Add `GET /api/predictions/dashboard` that calls all models in one shot:
- Delay predictions for all flights
- Congestion summary (areas + bottlenecks)
- Aggregate stats computed server-side (on-time %, avg delay, avg turnaround)

```python
@prediction_router.get("/dashboard")
async def get_predictions_dashboard(...):
    flights = await flight_service.get_flights()
    flight_dicts = [f.model_dump() for f in flights.flights]
    predictions = await prediction_service.get_flight_predictions(flight_dicts)
    congestion = await prediction_service.get_congestion(flight_dicts)

    # Aggregate stats
    delays = predictions["delays"]
    on_time = sum(1 for d in delays.values() if d.delay_minutes < 15)
    avg_delay = mean(d.delay_minutes for d in delays.values()) if delays else 0
    bottlenecks = [c for c in congestion if c.level.value in ("high", "critical")]
    worst_level = max((c.level.value for c in congestion), default="low")

    return { kpi_cards, delay_table, congestion_table }
```

### 2. Frontend: New KPI Dashboard component

- `app/frontend/src/components/KPIDashboard/KPIDashboard.tsx` — modal overlay component
- `app/frontend/src/hooks/usePredictionDashboard.ts` — hook calling `/api/predictions/dashboard`
- Reuse existing styles from SimulationReport.tsx (KPI cards, tables, color coding)

### 3. Frontend: Header button + App wiring

- Add "KPI" button in Header.tsx (next to FIDS button)
- Add `showKPI` state in App.tsx, pass toggle down to Header
- Render `<KPIDashboard>` as modal overlay (same pattern as FIDS)

## Files Modified

| File | Change |
|------|--------|
| `app/backend/api/predictions.py` | new `/dashboard` endpoint (~60 lines) |
| `app/frontend/src/components/KPIDashboard/KPIDashboard.tsx` | new component (~250 lines) |
| `app/frontend/src/hooks/usePredictionDashboard.ts` | new hook (~30 lines) |
| `app/frontend/src/components/Header/Header.tsx` | add KPI button (~5 lines) |
| `app/frontend/src/App.tsx` | add showKPI state + render modal (~10 lines) |

## Verification

1. `uv run pytest tests/ -k prediction -v` — existing prediction tests pass
2. `cd app/frontend && npm test -- --run` — all frontend tests pass
3. Build + deploy + stop/start
4. Click "KPI" in header → modal opens with live predictions
5. KPI cards show realistic values (on-time %, avg delay, congestion level)
6. Congestion table shows all areas sorted by severity
7. Delay table shows per-flight predictions sorted by worst delay
8. Auto-refresh every 30s

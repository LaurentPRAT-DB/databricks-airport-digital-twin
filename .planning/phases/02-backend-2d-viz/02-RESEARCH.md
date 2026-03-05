# Phase 2: Backend API + 2D Visualization - Research

**Researched:** 2026-03-05
**Domain:** FastAPI backend, React frontend, 2D mapping, real-time updates
**Confidence:** HIGH

## Summary

Phase 2 builds the user-facing application layer on top of Phase 1's data foundation. The architecture follows the Databricks APX pattern (FastAPI backend + React frontend) with WebSocket support for real-time flight updates. The 2D map uses Leaflet with a custom airport overlay showing runways, taxiways, and terminals. Flight positions animate smoothly between updates.

**Primary recommendation:** Use Vite + React + TypeScript for the frontend, FastAPI with WebSocket for real-time data push, and Leaflet for mapping (lighter than MapLibre, sufficient for this use case).

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| VIZ2D-01 | Interactive 2D map displays airport layout with runways and terminals | Leaflet with custom SVG/GeoJSON overlay for airport features |
| VIZ2D-02 | Flight positions update on map in real-time | WebSocket push from FastAPI; Leaflet marker updates |
| VIZ2D-03 | User can click flights to see detailed information | Leaflet popup/tooltip + React state for detail panel |
| VIZ2D-04 | Map shows flight paths and predicted trajectories | Leaflet Polyline for tracks; dashed line for predictions |
| UI-01 | Flight list/table displays all tracked flights with search and sort | React table component with client-side filtering |
| UI-02 | Status indicators show gate status | Color-coded gate markers on map |
| UI-03 | Delay alerts highlight flights with predicted delays | Badge/highlight on delayed flights (Phase 3 ML provides data) |
| UI-04 | Prediction displays show ML model outputs | Placeholder UI - actual predictions come in Phase 3 |

## Standard Stack

### Backend
| Library | Version | Purpose |
|---------|---------|---------|
| FastAPI | 0.109+ | REST API + WebSocket server |
| uvicorn | 0.27+ | ASGI server |
| websockets | 12.0+ | WebSocket protocol |
| databricks-sql-connector | 3.0+ | Query Gold table |
| pydantic | 2.5+ | Request/response models |

### Frontend
| Library | Version | Purpose |
|---------|---------|---------|
| React | 18.2+ | UI framework |
| TypeScript | 5.3+ | Type safety |
| Vite | 5.0+ | Build tool |
| Leaflet | 1.9+ | 2D mapping |
| react-leaflet | 4.2+ | React bindings for Leaflet |
| @tanstack/react-query | 5.0+ | Data fetching/caching |
| tailwindcss | 3.4+ | Styling |

## Architecture Patterns

### Pattern 1: APX Project Structure
```
app/
├── backend/
│   ├── __init__.py
│   ├── main.py              # FastAPI app entry
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py        # REST endpoints
│   │   └── websocket.py     # WebSocket handlers
│   ├── services/
│   │   ├── __init__.py
│   │   └── flight_service.py # Business logic
│   └── models/
│       ├── __init__.py
│       └── flight.py        # Pydantic models
├── frontend/
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── Map/
│   │   │   ├── FlightList/
│   │   │   └── FlightDetail/
│   │   ├── hooks/
│   │   └── types/
│   ├── index.html
│   ├── package.json
│   └── vite.config.ts
├── app.yaml                  # Databricks App config
└── requirements.txt
```

### Pattern 2: WebSocket Real-time Updates
```python
# backend/api/websocket.py
from fastapi import WebSocket
import asyncio

class FlightBroadcaster:
    def __init__(self):
        self.connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.connections.append(websocket)

    async def broadcast(self, data: dict):
        for connection in self.connections:
            await connection.send_json(data)

broadcaster = FlightBroadcaster()

# Polling loop (runs in background)
async def poll_flights():
    while True:
        flights = await fetch_from_gold_table()
        await broadcaster.broadcast({"flights": flights})
        await asyncio.sleep(5)
```

### Pattern 3: Leaflet Airport Overlay
```typescript
// Airport layout as GeoJSON
const airportLayout = {
  runways: [
    { type: "Feature", geometry: { type: "Polygon", coordinates: [...] } }
  ],
  terminals: [...],
  taxiways: [...]
};

// Custom flight marker
const FlightMarker = ({ flight }) => (
  <Marker
    position={[flight.latitude, flight.longitude]}
    icon={createFlightIcon(flight.heading)}
  >
    <Popup>{flight.callsign}</Popup>
  </Marker>
);
```

## Common Pitfalls

### Pitfall 1: WebSocket Connection Drops
**What goes wrong:** WebSocket disconnects silently, UI stops updating
**How to avoid:** Implement reconnection logic with exponential backoff in frontend

### Pitfall 2: Map Performance with Many Markers
**What goes wrong:** UI becomes sluggish with 100+ flight markers
**How to avoid:** Use Leaflet.markercluster for clustering; limit visible flights to viewport

### Pitfall 3: CORS Issues in Development
**What goes wrong:** Frontend can't reach backend API
**How to avoid:** Configure FastAPI CORS middleware; use Vite proxy for development

## Airport Layout

For a generic airport, use a fictional layout with:
- 2 parallel runways (10L/28R, 10R/28L)
- 1 crosswind runway (01/19)
- Central terminal with gates A1-A10, B1-B10
- Taxiways connecting runways to terminal

Center coordinates: 37.5°N, -122.0°W (generic Bay Area location)

## Sources

- FastAPI WebSocket documentation
- React-Leaflet documentation
- Databricks APX framework patterns

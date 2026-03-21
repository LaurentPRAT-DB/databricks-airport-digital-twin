# Plan: OSM Taxiway Routing for Realistic Ground Movement

**Phase:** 08 — Post-v1
**Date:** 2026-03-10
**Status:** Not yet implemented

---

## Context

Aircraft ground movement currently uses hardcoded SFO waypoints (`TAXI_WAYPOINTS_ARRIVAL`, `TAXI_WAYPOINTS_DEPARTURE` in `fallback.py:393-408`). This means:
- All airports use SFO's taxi coordinates (broken for non-SFO airports)
- Aircraft fly in straight lines from last waypoint to gate (cutting across buildings/grass)
- Pushback always moves south regardless of terminal orientation
- Taxi time is unrealistic — it doesn't reflect actual taxiway distance

The OSM data already provides 244 taxiway segments for SFO with ordered geoPoints (lat/lon centerlines), plus runway centerlines and gate positions. We need to build a routing graph from this data so aircraft follow real taxiway paths, producing realistic taxi times that affect airport operations (gate turnaround, runway throughput, congestion).

---

## Architecture

New module: `src/routing/taxiway_graph.py` — builds and queries a taxiway routing graph.

```
OSM Taxiways (geoPoints) ──→ TaxiwayGraph ──→ route(gate, runway) ──→ [(lat, lon), ...]
OSM Runways (geoPoints)  ──┘                                              ↓
OSM Gates (geo)          ──┘                              fallback.py uses as waypoints
```

The graph is built once per airport switch (same lifecycle as `airport_config_service` singleton) and cached. It replaces `TAXI_WAYPOINTS_ARRIVAL` / `TAXI_WAYPOINTS_DEPARTURE` with per-gate dynamic routes.

---

## Implementation Steps

### Step 1: TaxiwayGraph class — Build graph from OSM data

**File:** `src/routing/taxiway_graph.py` (new)

```python
class TaxiwayGraph:
    """Builds a navigable graph from OSM taxiway segments."""

    def __init__(self, snap_tolerance: float = 0.0002):
        """snap_tolerance: degrees (~22m) for merging nearby endpoints."""
        self.nodes: dict[int, tuple[float, float]] = {}   # node_id → (lat, lon)
        self.edges: dict[int, list[tuple[int, float]]] = {}  # node_id → [(neighbor_id, distance)]
        self._snap_tolerance = snap_tolerance
        self._node_index: list[tuple[float, float, int]] = []  # for spatial lookup

    def build_from_config(self, config: dict) -> None:
        """Build graph from airport config dict (osmTaxiways, osmRunways, gates)."""
        # 1. Add all taxiway segments as edges
        # 2. Add runway centerlines (aircraft exit/enter runways)
        # 3. Snap nearby endpoints to merge intersections
        # 4. Connect gates to nearest taxiway node

    def find_route(self, start: tuple, end: tuple) -> list[tuple[float, float]]:
        """Dijkstra shortest path. Returns list of (lat, lon) waypoints."""

    def route_length_meters(self, route: list) -> float:
        """Calculate route distance using haversine."""

    def snap_to_nearest_node(self, lat: float, lon: float) -> int:
        """Find closest graph node to a geo position."""
```

**Graph construction algorithm:**
1. For each OSM taxiway, iterate its geoPoints in order. Each consecutive pair (P[i], P[i+1]) becomes an edge.
2. Snap endpoints: if two nodes from different taxiways are within `snap_tolerance` (~22m), merge them into one node. This creates intersections where taxiways cross.
3. For each OSM runway, add its first and last geoPoints as "runway exit" nodes, connected to the nearest taxiway node.
4. For each OSM gate, create a "gate node" connected to the nearest taxiway node.
5. Edge weights = haversine distance between nodes (meters).

**Pathfinding:** Dijkstra with a priority queue (heapq). The graph is small (a few hundred nodes) so this is instant.

### Step 2: Integrate with airport_config_service

**File:** `app/backend/services/airport_config_service.py` (modify)

Add a `TaxiwayGraph` instance to the singleton. Build it whenever airport config loads:

```python
from src.routing.taxiway_graph import TaxiwayGraph

class AirportConfigService:
    def __init__(self):
        ...
        self._taxiway_graph: Optional[TaxiwayGraph] = None

    @property
    def taxiway_graph(self) -> Optional[TaxiwayGraph]:
        return self._taxiway_graph
```

In the existing `import_osm()` or `_process_osm_data()` method, after storing config:
```python
self._taxiway_graph = TaxiwayGraph()
self._taxiway_graph.build_from_config(self._current_config)
```

### Step 3: Dynamic taxi waypoint generation in fallback.py

**File:** `src/ingestion/fallback.py` (modify)

Replace the hardcoded waypoint usage with dynamic routing:

```python
def _get_taxi_waypoints_arrival(gate_ref: str) -> list[tuple[float, float]]:
    """Get taxi route from landing runway exit to assigned gate.

    Uses OSM taxiway graph when available, falls back to hardcoded SFO
    waypoints or generic straight-line path.
    """
    try:
        from app.backend.services.airport_config_service import get_airport_config_service
        service = get_airport_config_service()
        graph = service.taxiway_graph
        if graph:
            runway_exit = _get_runway_threshold()  # (lon, lat)
            gate_pos = get_gates().get(gate_ref)
            if gate_pos:
                route = graph.find_route(
                    (runway_exit[1], runway_exit[0]),  # (lat, lon)
                    gate_pos  # (lat, lon)
                )
                if route:
                    return [(lon, lat) for lat, lon in route]  # convert to (lon, lat)
    except Exception:
        pass

    # Fallback: existing behavior
    center = get_airport_center()
    if abs(center[0] - AIRPORT_CENTER[0]) < 0.01:
        return TAXI_WAYPOINTS_ARRIVAL
    # Generic: straight line from center to gate
    gate_pos = get_gates().get(gate_ref, center)
    return [(center[1], center[0]), (gate_pos[1], gate_pos[0])]


def _get_taxi_waypoints_departure(gate_ref: str) -> list[tuple[float, float]]:
    """Get taxi route from gate to departure runway."""
    # Mirror of arrival, but gate → runway
    ...
```

**Modify TAXI_TO_GATE phase** (line 1277-1347):
- Replace `TAXI_WAYPOINTS_ARRIVAL` with `_get_taxi_waypoints_arrival(state.assigned_gate)`
- Cache the route in FlightState (add `taxi_route: list` field)

**Modify TAXI_TO_RUNWAY phase** (line 1391-1407):
- Replace `TAXI_WAYPOINTS_DEPARTURE` with `_get_taxi_waypoints_departure(state.assigned_gate)`

**Modify PUSHBACK phase** (line 1365-1389):
- Instead of blind `latitude -= 0.00002`, use the first segment of departure route (reversed) to determine pushback direction

### Step 4: Add taxi_route to FlightState

**File:** `src/ingestion/fallback.py` (modify FlightState dataclass)

```python
@dataclass
class FlightState:
    ...
    taxi_route: Optional[list] = None  # Cached taxi waypoints for current phase
```

When entering TAXI_TO_GATE, compute and cache:
```python
state.taxi_route = _get_taxi_waypoints_arrival(state.assigned_gate)
state.waypoint_index = 0
```

When entering TAXI_TO_RUNWAY:
```python
state.taxi_route = _get_taxi_waypoints_departure(state.assigned_gate)
state.waypoint_index = 0
```

### Step 5: Tests

**File:** `tests/routing/test_taxiway_graph.py` (new)

```python
class TestTaxiwayGraph:
    def test_build_empty(self): ...
    def test_build_single_taxiway(self): ...
    def test_snap_nearby_nodes(self): ...
    def test_find_route_simple(self): ...
    def test_find_route_no_path(self): ...
    def test_snap_to_nearest_node(self): ...
    def test_route_length(self): ...
    def test_build_from_real_sfo_config(self): ...  # integration test with SFO OSM data
    def test_gate_to_runway_route(self): ...
```

**File:** `tests/ingestion/test_fallback_routing.py` (new)

```python
class TestDynamicTaxiWaypoints:
    def test_arrival_uses_graph_when_available(self): ...
    def test_arrival_falls_back_to_hardcoded(self): ...
    def test_departure_uses_graph_when_available(self): ...
    def test_pushback_direction_from_route(self): ...
```

---

## Files Modified

| File | Change |
|------|--------|
| `src/routing/__init__.py` | New empty module |
| `src/routing/taxiway_graph.py` | New: TaxiwayGraph class with graph building + Dijkstra |
| `app/backend/services/airport_config_service.py` | Add `_taxiway_graph` field, build on config load |
| `src/ingestion/fallback.py` | Add `taxi_route` to FlightState, new `_get_taxi_waypoints_arrival/departure()`, modify TAXI_TO_GATE/TAXI_TO_RUNWAY/PUSHBACK phases |
| `tests/routing/test_taxiway_graph.py` | New: unit tests for graph building + routing |
| `tests/ingestion/test_fallback_routing.py` | New: integration tests for dynamic waypoints |

---

## Key Design Decisions

1. **Snap tolerance = 0.0002° (~22m):** OSM taxiway segments don't always share exact coordinates at intersections. This tolerance merges nearby endpoints into graph junctions.
2. **Bidirectional edges:** All taxiway segments are traversable in both directions (real taxiways are generally bidirectional except during specific traffic flow configurations).
3. **Graceful fallback:** If graph is unavailable (no OSM data, import failed), existing hardcoded behavior is preserved. No existing functionality breaks.
4. **Per-flight route caching:** Route is computed once when entering a taxi phase and stored in `FlightState.taxi_route`. Not recomputed every tick.
5. **Runway connections:** Only runway endpoints (thresholds) are connected to the taxiway graph, not the full centerline. Aircraft transition from runway to taxiway at these junction points.

---

## Verification

1. `uv run pytest tests/ -v` — all backend tests pass (existing 992 + new routing tests)
2. `cd app/frontend && npm test -- --run` — frontend unchanged, 634 pass
3. Visual verification: start dev server, observe aircraft following taxiway paths instead of straight lines
4. Check different airports: switch to another airport (e.g., KJFK) and verify dynamic routing works there too
5. Measure: taxi times should vary by gate distance (close gates ~3-5 min, far gates ~8-12 min)

# Code Optimization Analysis

## Critical

None found.

---

## High

### #1 — O(n^2) arrival counting in schedule generation

- **Location:** `src/simulation/engine.py:413`
- **Issue:** `sum(1 for f in schedule if f["flight_type"] == "arrival")` is called inside the inner loop for every flight, re-scanning the full schedule list each time. With 200+ arrivals across 24+ hours, this is O(arrivals^2).
- **Fix:** Track count in a variable.

### #2 — snap_to_nearest_node is O(n) linear scan

- **Location:** `src/routing/taxiway_graph.py:286-297`
- **Issue:** Called on every `find_route()` invocation (2 calls per route). With 500-1000 nodes, this is fine for one-off calls, but during simulation it's called for every taxi-to-gate and taxi-to-runway. More critically, `_get_or_create_node` (line 299-309) scans all nodes during graph construction — called once per taxiway point, making construction O(n*m).
- **Fix:** Use a spatial index (grid hash or scipy KDTree).

### #3 — Building penalty checks: O(edges * samples * polygons) with point-in-polygon

- **Location:** `src/routing/taxiway_graph.py:199-218`
- **Issue:** For every edge, 5 sample points are tested against every building polygon via ray-casting. With 500 edges and 10 terminals, that's 25,000 point-in-polygon tests during graph build.
- **Fix:** Pre-compute bounding boxes for fast rejection.

### #4 — model_dump() called per flight every 2s broadcast

- **Location:** `app/backend/api/websocket.py:130`
- **Issue:** `[f.model_dump() for f in flight_data.flights]` serializes all ~100-200 Pydantic models every broadcast tick, even though deltas only send changed fields. The full dict is needed for delta computation but discarded after.
- **Fix:** Cache previous raw dicts in the broadcaster instead of recomputing.

---

## High Priority Fixes (Details)

### Fix for #1 — O(n^2) arrival counting

```python
# Before (engine.py:406-414):
for h_idx, weight in enumerate(hour_weights):
    flights_this_hour = max(1, round(self.config.arrivals * weight / total_weight))
    if h_idx == len(hour_weights) - 1:
        already = sum(1 for f in schedule if f["flight_type"] == "arrival")
        flights_this_hour = max(0, self.config.arrivals - already)
    for _ in range(flights_this_hour):
        if sum(1 for f in schedule if f["flight_type"] == "arrival") >= self.config.arrivals:
            break

# After:
arrival_count = 0
for h_idx, weight in enumerate(hour_weights):
    flights_this_hour = max(1, round(self.config.arrivals * weight / total_weight))
    if h_idx == len(hour_weights) - 1:
        flights_this_hour = max(0, self.config.arrivals - arrival_count)
    for _ in range(flights_this_hour):
        if arrival_count >= self.config.arrivals:
            break
        # ... append to schedule ...
        arrival_count += 1
```

### Fix for #2 — Linear scan in _get_or_create_node

```python
# Add a grid-based spatial index to TaxiwayGraph.__init__:
self._grid: dict[tuple[int, int], list[int]] = {}  # grid cell -> node ids
self._grid_size = snap_tolerance

def _grid_key(self, lat: float, lon: float) -> tuple[int, int]:
    return (int(lat / self._grid_size), int(lon / self._grid_size))

def _get_or_create_node(self, lat: float, lon: float) -> int:
    key = self._grid_key(lat, lon)
    tol = self._snap_tolerance
    # Check 3x3 neighborhood
    for dk in [(-1,-1),(-1,0),(-1,1),(0,-1),(0,0),(0,1),(1,-1),(1,0),(1,1)]:
        nkey = (key[0]+dk[0], key[1]+dk[1])
        for nid in self._grid.get(nkey, []):
            nlat, nlon = self.nodes[nid]
            if abs(nlat - lat) < tol and abs(nlon - lon) < tol:
                return nid
    nid = self._next_id
    self._next_id += 1
    self.nodes[nid] = (lat, lon)
    self.edges.setdefault(nid, [])
    self._grid.setdefault(key, []).append(nid)
    return nid
```

### Fix for #3 — Building penalty with bounding box pre-filter

```python
def _penalize_building_edges(self, polygons):
    # Pre-compute bounding boxes for fast rejection
    poly_bounds = []
    for poly in polygons:
        lats = [p[0] for p in poly]
        lons = [p[1] for p in poly]
        poly_bounds.append((min(lats), max(lats), min(lons), max(lons)))

    # ... in the inner loop:
    for idx, poly in enumerate(polygons):
        min_lat, max_lat, min_lon, max_lon = poly_bounds[idx]
        if s_lat < min_lat or s_lat > max_lat or s_lon < min_lon or s_lon > max_lon:
            continue  # fast reject
        if _point_in_polygon(s_lat, s_lon, poly):
            hits_building = True
            break
```

### Fix for #4 — Avoid redundant model_dump()

```python
# In _broadcast_loop, the broadcaster already caches prev_flights as dicts.
# The fix: skip model_dump() when we already have a valid previous snapshot
# and only need to detect deltas. Use flight_data.flights directly for
# delta fields, and cache the dict form.

# This requires restructuring to avoid double-serialization.
# Simpler: cache the JSON string of the broadcast message and avoid
# re-serializing when nothing changed.
```

---

## Medium

### #5 — ProceduralAircraft creates 10 geometry+material objects inline

- **Location:** `app/frontend/src/components/Map3D/ProceduralAircraft.tsx:17-93`
- **Issue:** Each ProceduralAircraft creates 10 geometry+material objects inline. React-three-fiber re-creates JSX elements on re-render. With 50-200 aircraft using the procedural fallback, that's 500-2000 geometries. The geometries are small but GC pressure adds up.
- **Fix:** Extract shared geometries into module-level constants or use `useMemo`.

### #6 — Array.from(map.values()) on every delta message

- **Location:** `app/frontend/src/hooks/useFlights.ts:131`
- **Issue:** Every 2s WebSocket delta creates a new array from the Map, triggering a full re-render of all FlightMarker components.
- **Fix:** This is inherent to React state updates. Could use a ref + shallow comparison to skip no-op updates.

### #7 — any(s.phase == FlightPhase.LANDING ...) every tick

- **Location:** `src/simulation/engine.py:1228-1231`
- **Issue:** Scans all active flights (~50-200) every simulation tick to check if any is landing. Called thousands of times during a simulation.
- **Fix:** Maintain a counter: increment on LANDING entry, decrement on exit.

### #8 — Departure queue count scans all flights every tick

- **Location:** `src/simulation/engine.py:1180-1183`
- **Issue:** `_update_departure_queue` iterates all flight states to count pushback/taxi flights.
- **Fix:** Same fix: maintain phase counters.

### Fix for #7 and #8 — Phase counters

```python
# In engine.__init__:
self._phase_counts: dict[str, int] = {}

# In _update_all_flights, when phase changes:
if new_phase != old_phase:
    self._phase_counts[old_phase.value] = self._phase_counts.get(old_phase.value, 0) - 1
    self._phase_counts[new_phase.value] = self._phase_counts.get(new_phase.value, 0) + 1

# Then in _update_departure_queue:
queue_size = (self._phase_counts.get("pushback", 0)
              + self._phase_counts.get("taxi_to_runway", 0))

# And in _capture_positions:
has_landing = self._phase_counts.get("landing", 0) > 0
```

---

## Low

### #9 — Icon useMemo has 9 dependencies including flight.latitude

- **Location:** `app/frontend/src/components/Map/FlightMarker.tsx:131-133`
- **Issue:** The icon is regenerated whenever latitude changes (every 2s), even though latitude doesn't affect icon appearance — only `getIconSize` uses it, and size rarely changes between ticks.
- **Fix:** Compute size separately and use it as the dependency instead.

### #10 — _find_nearest_nodes computes haversine for all nodes

- **Location:** `src/routing/taxiway_graph.py:335-349`
- **Issue:** Uses expensive trig functions for all N nodes when only k=5 nearest are needed.
- **Fix:** Pre-filter with squared-degree distance, then haversine only on candidates.

---

## Summary

**Total issues found:** 10 (0 Critical, 4 High, 4 Medium, 2 Low)

### Top 3 highest-impact fixes

| Fix | Impact | Effort |
|-----|--------|--------|
| #1 — O(n^2) arrival counting | Eliminates quadratic scaling in schedule generation (affects every sim run) | ~5 min, trivial |
| #7+#8 — Phase counters | Removes two full-scan loops from every simulation tick (thousands of ticks per run) | ~20 min |
| #2 — Spatial index for node snapping | Reduces graph construction from O(n*m) to O(n), matters for airports with 500+ taxiway nodes | ~30 min |

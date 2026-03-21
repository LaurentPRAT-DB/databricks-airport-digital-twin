# Phase 22: Scale to 500 Flights

## Goal

Scale the simulation from 100 to 500 concurrent flights. Requires architectural changes to the simulation engine, rendering pipeline, and data transport. This phase addresses O(n^2) algorithmic costs, frontend rendering limits, and simulation fidelity at scale.

## Status: Plan — Not Started

## Prerequisites: Phase 21 (Scale to 100) must be complete.

---

## Problem Analysis at 500 Flights

| Bottleneck | At 100 | At 500 | Solution Category |
|-----------|--------|--------|-------------------|
| Taxi separation checks | 10K pair checks/tick | 250K pair checks/tick | Spatial indexing |
| Approach separation | OK with phase index | OK (max 8 approaching) | Already capped |
| State machine update | ~2ms total | ~10ms total | Background thread |
| WebSocket initial payload | ~30KB | ~150KB | Viewport filtering |
| WebSocket delta payload | ~10KB | ~50KB | Compression + filtering |
| 2D Leaflet DOM markers | 100 `<div>` — OK | 500 `<div>` — laggy | Canvas/WebGL rendering |
| 3D React components | 100 `<Aircraft3D>` — OK | 500 — frame drops | Instanced meshes + LOD |
| Gate capacity | 30+ gates OK | Need 80-100+ gates | Dynamic gate generation |
| Runway throughput | ~50 mvmt/hr dual | Need ~80+ mvmt/hr | Multi-config + reduced sep |

---

## Tasks

### Task 1: Spatial Grid for Ground Separation

**File:** `src/ingestion/fallback.py`

Replace the O(n) scan in `_check_taxi_separation()` with a spatial hash grid.

**Design:**
```python
# Grid cell size: ~0.005° ≈ 500m — larger than taxi separation (300m)
_GRID_CELL_SIZE = 0.005

class SpatialGrid:
    """2D spatial hash for O(1) neighbor queries."""

    def __init__(self, cell_size: float = _GRID_CELL_SIZE):
        self.cell_size = cell_size
        self._cells: Dict[tuple[int, int], Set[str]] = defaultdict(set)
        self._positions: Dict[str, tuple[int, int]] = {}

    def _cell_key(self, lat: float, lon: float) -> tuple[int, int]:
        return (int(lat / self.cell_size), int(lon / self.cell_size))

    def update(self, icao24: str, lat: float, lon: float):
        """Update aircraft position in grid."""
        new_key = self._cell_key(lat, lon)
        old_key = self._positions.get(icao24)
        if old_key == new_key:
            return
        if old_key:
            self._cells[old_key].discard(icao24)
        self._cells[new_key].add(icao24)
        self._positions[icao24] = new_key

    def remove(self, icao24: str):
        old_key = self._positions.pop(icao24, None)
        if old_key:
            self._cells[old_key].discard(icao24)

    def nearby(self, lat: float, lon: float, radius_cells: int = 1) -> Set[str]:
        """Return icao24s in adjacent cells."""
        cx, cy = self._cell_key(lat, lon)
        result = set()
        for dx in range(-radius_cells, radius_cells + 1):
            for dy in range(-radius_cells, radius_cells + 1):
                result.update(self._cells.get((cx + dx, cy + dy), set()))
        return result

_ground_grid = SpatialGrid()
```

**Update `_check_taxi_separation()`:**
```python
def _check_taxi_separation(state: FlightState) -> bool:
    if not state.on_ground:
        return True
    nearby = _ground_grid.nearby(state.latitude, state.longitude)
    for icao24 in nearby:
        if icao24 == state.icao24:
            continue
        other = _flight_states.get(icao24)
        if not other or not other.on_ground or other.phase == FlightPhase.PARKED:
            continue
        dist = _distance_between(
            (state.latitude, state.longitude),
            (other.latitude, other.longitude)
        )
        if dist < MIN_TAXI_SEPARATION_DEG:
            return False
    return True
```

**Integration:** Call `_ground_grid.update()` after every position change for ground aircraft. Call `_ground_grid.remove()` on flight removal.

**Impact:** Taxi separation drops from O(n) to O(~5-10 neighbors) per check. At 500 flights with ~200 on ground, this is ~200 × 10 = 2,000 checks vs 200 × 200 = 40,000.

---

### Task 2: Move Simulation to Background Thread

**File:** `src/ingestion/fallback.py`, `app/backend/api/websocket.py`

**Problem:** `generate_synthetic_flights()` runs synchronously inside the async WebSocket broadcast loop. At 500 flights, simulation could take 10-50ms, blocking the event loop.

**Design:**
```python
import threading
import copy

class SimulationEngine:
    """Background thread running the flight state machine."""

    def __init__(self, target_count: int = 500):
        self._target_count = target_count
        self._lock = threading.Lock()
        self._snapshot: List[List[Any]] = []  # Latest OpenSky-format snapshot
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._tick_rate = 0.5  # 500ms tick for smoother animation

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def get_snapshot(self) -> Dict[str, Any]:
        """Thread-safe snapshot read for WebSocket broadcast."""
        with self._lock:
            return {"time": int(time.time()), "states": list(self._snapshot)}

    def _run_loop(self):
        while self._running:
            start = time.monotonic()
            result = generate_synthetic_flights(count=self._target_count)
            with self._lock:
                self._snapshot = result["states"]
            elapsed = time.monotonic() - start
            sleep_time = max(0, self._tick_rate - elapsed)
            time.sleep(sleep_time)
```

**WebSocket change:** `_broadcast_loop()` reads from `engine.get_snapshot()` instead of calling `service.get_flights()`.

**Benefits:**
- Simulation runs at consistent tick rate independent of WebSocket clients
- Event loop never blocked by simulation math
- Can increase tick rate (500ms) for smoother animation without increasing broadcast rate (2s)

---

### Task 3: Instanced Mesh Rendering in 3D

**File:** `app/frontend/src/components/Map3D/AirportScene.tsx`, new file `InstancedAircraft.tsx`

**Current:** 500 × `<Aircraft3D>` = 500 React components, 500 draw calls.

**Design:** Group flights by aircraft model type, render each group as ONE `InstancedMesh`:

```tsx
// InstancedAircraft.tsx
import { useRef, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { useGLTF } from '@react-three/drei';

interface InstancedAircraftProps {
  flights: Flight[];
  modelUrl: string;
  airportCenter: [number, number];
  selectedFlight?: string | null;
  onSelectFlight?: (icao24: string) => void;
}

export function InstancedAircraft({ flights, modelUrl, airportCenter, selectedFlight }: InstancedAircraftProps) {
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const { scene } = useGLTF(modelUrl);

  // Extract geometry from GLTF
  const geometry = useMemo(() => {
    let geo: THREE.BufferGeometry | null = null;
    scene.traverse((child) => {
      if (child instanceof THREE.Mesh && !geo) {
        geo = child.geometry;
      }
    });
    return geo;
  }, [scene]);

  const dummy = useMemo(() => new THREE.Object3D(), []);

  useFrame(() => {
    if (!meshRef.current) return;

    flights.forEach((flight, i) => {
      const [x, z] = geoToLocal(flight.latitude, flight.longitude, airportCenter);
      const y = flight.altitude * ALTITUDE_SCALE;
      dummy.position.set(x, y, z);
      dummy.rotation.set(0, -THREE.MathUtils.degToRad(flight.heading - 90), 0);
      dummy.updateMatrix();
      meshRef.current!.setMatrixAt(i, dummy.matrix);
    });

    meshRef.current.count = flights.length;
    meshRef.current.instanceMatrix.needsUpdate = true;
  });

  if (!geometry) return null;

  return (
    <instancedMesh ref={meshRef} args={[geometry, undefined, flights.length]} frustumCulled>
      <meshStandardMaterial color="#ffffff" />
    </instancedMesh>
  );
}
```

**In AirportScene.tsx:**
```tsx
// Group flights by model type
const flightsByModel = useMemo(() => {
  const groups: Record<string, Flight[]> = {};
  flights.forEach(f => {
    const model = getModelUrl(f.aircraft_type);
    (groups[model] ??= []).push(f);
  });
  return groups;
}, [flights]);

// Render one InstancedMesh per model type (~5-8 types)
{Object.entries(flightsByModel).map(([modelUrl, groupFlights]) => (
  <InstancedAircraft
    key={modelUrl}
    flights={groupFlights}
    modelUrl={modelUrl}
    airportCenter={airportCenter}
    selectedFlight={selectedFlight}
  />
))}
```

**Impact:** 500 flights → ~6 draw calls (one per aircraft type) instead of 500. Frame rate stays at 60fps.

**Selection handling:** Use raycasting on instanced mesh with `instanceId` to identify clicked aircraft.

---

### Task 4: Canvas Rendering for 2D Map

**File:** `app/frontend/src/components/Map/AirportMap.tsx`, `FlightMarker.tsx`

**Current:** 500 Leaflet `divIcon` markers = 500 DOM elements with inline SVG, repositioned every 2s.

**Option A: Leaflet Canvas markers**
Replace `L.divIcon` with `L.CircleMarker` using Canvas renderer — simpler but less visual fidelity.

**Option B: deck.gl IconLayer (recommended)**
```tsx
import { IconLayer } from '@deck.gl/layers';
import { MapboxOverlay } from '@deck.gl/mapbox';

const flightLayer = new IconLayer({
  id: 'flights',
  data: flights,
  getPosition: d => [d.longitude, d.latitude],
  getAngle: d => -(d.heading || 0),
  getIcon: d => ({
    url: '/airplane-icon.png',
    width: 64,
    height: 64,
    anchorY: 32,
  }),
  getSize: 24,
  getColor: d => phaseColor(d.flight_phase),
  pickable: true,
  onClick: info => onSelectFlight(info.object.icao24),
  updateTriggers: {
    getPosition: flights.map(f => `${f.icao24}-${f.latitude}-${f.longitude}`),
    getAngle: flights.map(f => f.heading),
  },
});
```

**Impact:** All 500 flights rendered in a single WebGL draw call. No DOM manipulation. 60fps panning/zooming.

**Trade-off:** Adds deck.gl dependency (~200KB gzipped). Alternative: keep Leaflet but use `L.canvas()` renderer with custom `CircleMarker` — lighter but less visual quality.

**Recommended approach:** Start with Leaflet Canvas renderer (minimal change), migrate to deck.gl if needed.

---

### Task 5: Viewport-Based WebSocket Filtering

**File:** `app/backend/api/websocket.py`, frontend WebSocket hook

**Problem:** At 500 flights, sending all flight data every 2s wastes bandwidth for flights outside the viewport.

**Design:**

Frontend sends viewport bounds with each message:
```typescript
// useFlights.ts
ws.send(JSON.stringify({
  type: 'viewport',
  bounds: map.getBounds().toJSON(),  // {north, south, east, west}
}));
```

Backend filters flights:
```python
async def _broadcast_loop(self, interval: float = 2.0):
    while True:
        flight_data = await service.get_flights()
        for websocket, viewport in self._client_viewports.items():
            if viewport:
                filtered = [f for f in flights_dicts if _in_viewport(f, viewport)]
            else:
                filtered = flights_dicts
            deltas, removed = _compute_deltas(self._prev_per_client[websocket], filtered)
            ...
```

**Impact:** Zoomed-in view showing 50 flights near the airport only receives those 50, not all 500.

**Caveat:** FIDS panel needs all flights regardless of viewport. Send unfiltered data for non-map consumers, or send summary stats + viewport-filtered positions.

---

### Task 6: LOD (Level of Detail) System

**Files:** `Aircraft3D.tsx`, `FlightMarker.tsx`

**3D LOD tiers:**

| Distance from camera | Rendering | Detail |
|---------------------|-----------|--------|
| < 500m | GLTF model with livery colors | Full detail, shadows |
| 500m - 2km | Simple extruded triangle (ProceduralAircraft) | Medium detail, no shadows |
| > 2km | Billboard sprite or colored dot | Minimal, always facing camera |

```tsx
function Aircraft3DWithLOD({ flight, cameraDistance, ... }) {
  if (cameraDistance < 500) {
    return <GLTFAircraft ... />;
  } else if (cameraDistance < 2000) {
    return <ProceduralAircraft ... />;  // Already exists
  } else {
    return <BillboardSprite ... />;  // New: simple point sprite
  }
}
```

**2D LOD:** At low zoom (zoom < 12), cluster nearby flights into a count badge. At medium zoom (12-15), show dots. At high zoom (>15), show full airplane icons.

---

### Task 7: Dynamic Gate Generation for Large Airports

**File:** `src/ingestion/fallback.py`

**Problem:** At 500 flights with 45 min average turnaround, ~180-200 aircraft are parked at any time. Even SFO's ~80 OSM gates aren't enough.

**Design:**
1. If parked count approaches 90% of gate count, dynamically generate overflow remote stands
2. Place overflow stands along terminal geometry at regular intervals
3. Remote stands have longer turnaround (bus transport to terminal)

```python
def _ensure_gate_capacity(target_parked: int):
    """Dynamically add remote stands if gate count is insufficient."""
    current_gates = get_gates()
    if len(current_gates) >= target_parked * 1.2:
        return  # Sufficient capacity

    needed = target_parked * 1.2 - len(current_gates)
    center = get_airport_center()
    # Generate remote stands in a grid pattern near the airport
    for i in range(int(needed)):
        ref = f"R{i+1:03d}"
        angle = (i * 15) % 360
        dist = 0.003 + (i // 24) * 0.001  # Expanding rings
        lat = center[0] + dist * math.cos(math.radians(angle))
        lon = center[1] + dist * math.sin(math.radians(angle))
        current_gates[ref] = (lat, lon)
```

---

### Task 8: Multi-Runway Configuration

**File:** `src/ingestion/fallback.py`

**Current:** Hardcoded 28L/28R. At 500 flights need ~100+ movements/hour.

**Design:** Abstract runway configuration from OSM data:

```python
@dataclass
class RunwayConfig:
    """Active runway configuration."""
    arrival_runways: List[str]     # e.g., ["28L", "28R"] for parallel approaches
    departure_runways: List[str]   # e.g., ["01L", "01R"] or same as arrival

    def get_arrival_runway(self) -> str:
        """Round-robin or load-balanced arrival runway assignment."""
        ...

    def get_departure_runway(self) -> str:
        """Next available departure runway."""
        ...
```

**SFO configurations:**
- West Plan (normal): Arr 28L+28R, Dep 01L+01R — 60+ ops/hr
- Southeast Plan: Arr 19L+19R, Dep 19L+19R — used for south winds
- Reduced: Single runway ops during low traffic

**Impact:** With 4 active runway ends, throughput reaches 80-100+ movements/hour, sufficient for 500 flights.

---

### Task 9: Flight Spawning Scheduler

**File:** `src/ingestion/fallback.py`, `src/ingestion/schedule_generator.py`

**Current:** Fill-to-count approach — when flights exit, new ones spawn instantly to maintain `count`. This creates unrealistic constant density.

**Design:** Time-based arrival/departure waves matching real traffic patterns:

```python
class FlightScheduler:
    """Generates realistic arrival/departure waves."""

    def __init__(self, target_daily_ops: int = 1200):
        # SFO: ~450K ops/year ≈ 1,200/day
        self._hourly_profile = self._build_hourly_profile(target_daily_ops)
        self._next_arrival = 0.0
        self._next_departure = 0.0

    def _build_hourly_profile(self, daily_ops: int) -> List[int]:
        """Build 24-hour ops profile matching real traffic."""
        # Peak: 6-10am, 4-8pm. Quiet: 11pm-5am (SFO curfew)
        weights = [
            0.005, 0.005, 0.003, 0.003, 0.005, 0.015,  # 0-5am
            0.04, 0.07, 0.08, 0.07, 0.06, 0.055,        # 6-11am
            0.05, 0.05, 0.05, 0.055, 0.07, 0.08,        # 12-5pm
            0.07, 0.06, 0.04, 0.03, 0.02, 0.01,         # 6-11pm
        ]
        return [int(w * daily_ops) for w in weights]

    def should_spawn_arrival(self, current_time: float) -> bool:
        """Check if it's time for the next arrival."""
        hour = datetime.fromtimestamp(current_time).hour
        ops_this_hour = self._hourly_profile[hour]
        interval = 3600.0 / max(ops_this_hour, 1) / 2  # Half are arrivals
        if current_time >= self._next_arrival:
            self._next_arrival = current_time + interval * random.uniform(0.7, 1.3)
            return True
        return False
```

**Impact:** Traffic ebbs and flows realistically. Combined with the `count` parameter as a soft cap, this prevents the simulation from maintaining an artificially constant flight count.

---

### Task 10: Optimize ENROUTE flights (skip expensive checks)

**File:** `src/ingestion/fallback.py`

ENROUTE flights don't interact with ground infrastructure. At 500 flights, ~250 may be enroute. Their update is cheap (heading + position) but they still pass through the full `_update_flight_state()` function.

**Optimization:**
```python
def _update_flight_state(state: FlightState, dt: float) -> FlightState:
    # Fast path for enroute — no separation checks needed
    if state.phase == FlightPhase.ENROUTE:
        return _update_enroute_fast(state, dt)
    ...
```

Extract the ENROUTE block (lines 2095-2209) into a separate function with no unnecessary overhead.

---

## Verification

1. **Load test:** Run with `count=500`, measure:
   - Simulation tick time < 50ms (background thread)
   - WebSocket delta size < 100KB
   - Browser frame rate > 30fps (3D), > 45fps (2D)
   - No flights stuck indefinitely in any phase
2. **Phase distribution:** At steady state ~500 flights:
   - ~180-200 parked
   - ~8-10 approaching/landing
   - ~15-20 taxiing
   - ~15-20 pushback/takeoff/departing
   - ~250-280 enroute
3. **Memory:** Python process < 500MB, browser tab < 1GB
4. **All existing tests pass**

## Estimated Scope

- **Files modified:** ~8-10 (fallback.py, websocket.py, AirportScene.tsx, new InstancedAircraft.tsx, FlightMarker.tsx/AirportMap.tsx, routes.py)
- **New files:** 2-3 (SpatialGrid, InstancedAircraft, optional deck.gl layer)
- **Lines changed:** ~800-1200
- **Risk:** Medium — rendering changes require visual QA, background thread needs careful locking
- **Dependencies:** Optional deck.gl for 2D canvas rendering

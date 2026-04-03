# Plan: OpenSky Event Inference Pipeline

**Status:** Backlog
**Date added:** 2026-04-03
**Depends on:** OpenSky Recorded Data Replay
**Scope:** ADS-B event inference engine + recording API enrichment + ML training compatibility

---

## Context

We have 1,425 raw ADS-B state vectors in `opensky_states_raw` (LSGG, 58 aircraft, 81 frames over 20 minutes). The recorded data replay works, but the recordings have empty `gate_events`, `phase_transitions`, and `scenario_events` — fields that the simulation populates and the ML training pipeline (`src/ml/obt_features.py`) requires.

**Goal:** Infer gate assignments, chock-on/chock-off, taxi events, and phase transitions from raw ADS-B positions by matching lat/lon to OSM gate geometry. This enriches recorded data to the same event richness as simulation output, enabling ML model training on real data.

## What the ML Pipeline Needs

`src/ml/obt_features.py:extract_training_data()` joins these data sources:

- **phase_transitions:** `{time, icao24, callsign, from_phase, to_phase, latitude, longitude, altitude, aircraft_type, assigned_gate}` — specifically needs `to_phase="parked"` and `from_phase="parked", to_phase="pushback"` to compute turnaround duration
- **gate_events:** `{time, icao24, callsign, gate, event_type, aircraft_type}` — event_types: `"assign"`, `"occupy"`, `"release"`
- **schedule:** flight metadata (origin, destination, airline, delay)
- **weather_snapshots, scenario_events:** environmental context

## Data Available from ADS-B

Per state vector: `icao24`, `callsign`, `latitude`, `longitude`, `baro_altitude`, `velocity`, `true_track`, `vertical_rate`, `on_ground`, `collection_time`

From OSM (via `airport_config_service`): gate nodes with `{ref, geo: {latitude, longitude}, terminal, operator}` — each gate/parking_position has precise lat/lon.

## Inference Approach

### 1. Gate Assignment — Nearest-Gate Matching

When an aircraft is:

- `on_ground = True`
- `velocity < 2 m/s` (nearly stationary, ~4 kts)
- Position is within 100m of a known gate/parking_position

Match to the nearest gate using haversine distance. The Gate model (`src/ml/gate_model.py:Gate`) already has `latitude`, `longitude` fields loaded from OSM.

### 2. Event Detection — State Machine per Aircraft

Track each `icao24` across time-ordered frames. Detect transitions:

| State change | Emitted events |
|-------------|----------------|
| Airborne → on_ground, decelerating | `phase_transition(to_phase="landing")` |
| On ground, velocity > 5 kts → velocity < 2 kts near gate | `gate_event("occupy")`, `phase_transition(to_phase="parked")` — this is chock-on |
| Parked at gate → velocity > 2 kts | `gate_event("release")`, `phase_transition(from_phase="parked", to_phase="pushback")` — this is chock-off |
| On ground, moving, not near gate | `phase_transition(to_phase="taxi_in")` or `"taxi_out"` based on direction |
| On ground → airborne | `phase_transition(to_phase="takeoff")` |

Velocity thresholds (in m/s, raw OpenSky units before conversion):

- **Stationary:** < 2 m/s (~4 kts)
- **Taxi:** 2–30 m/s (~4–58 kts)
- **Takeoff roll:** > 30 m/s

### 3. Phase Transition Mapping

Map `determine_flight_phase()` (already used in recording API) to simulation phases:

| ADS-B phase | Sim phase |
|------------|-----------|
| ground + near gate + stationary | parked |
| ground + moving | taxi_in / taxi_out |
| takeoff | takeoff |
| landing | landing |
| approaching / descent | approach |
| departing / climb | departure |
| cruise | cruise |

## Implementation

### New file: `src/inference/opensky_events.py`

Core enrichment module — pure Python, no web framework dependencies:

```python
class AircraftTracker:
    """Tracks one aircraft across frames, emitting events on state changes."""
    icao24: str
    callsign: str
    prev_state: dict | None
    assigned_gate: str | None
    parked_since: datetime | None

class OpenSkyEventInferrer:
    """Processes time-ordered ADS-B frames and produces simulation-compatible events."""

    def __init__(self, gates: list[dict]):
        """gates: list of {ref, geo: {latitude, longitude}} from airport config"""
        self._gate_positions: list[tuple[str, float, float]]  # (gate_id, lat, lon)
        self._trackers: dict[str, AircraftTracker]

    def process_frame(self, timestamp: str, states: list[dict]) -> None:
        """Process one time-slice of ADS-B states."""

    def find_nearest_gate(self, lat: float, lon: float, max_dist_m: float = 100) -> str | None:
        """Haversine nearest-gate lookup."""

    def get_results(self) -> dict:
        """Return {phase_transitions, gate_events, schedule} in simulation format."""
```

### Modify: `app/backend/api/opensky.py` — `get_recording_data()`

After building frames from raw rows, run the inferrer:

```python
from src.inference.opensky_events import OpenSkyEventInferrer

# Load gate positions from airport config
config = get_airport_config_service().get_config()
gates = config.get("gates", [])

inferrer = OpenSkyEventInferrer(gates)
for ts in sorted_timestamps:
    inferrer.process_frame(ts, frames[ts])

enrichment = inferrer.get_results()
# Merge into response
response["phase_transitions"] = enrichment["phase_transitions"]
response["gate_events"] = enrichment["gate_events"]
```

### New file: `tests/inference/test_opensky_events.py`

Test the inferrer with synthetic state sequences:

- Aircraft approaches gate → stops → should emit occupy + parked
- Parked aircraft starts moving → should emit release + pushback
- Aircraft airborne → on ground → should emit landing
- Nearest-gate matching at boundary distances

## Key Reuse

| Existing code | Reuse |
|--------------|-------|
| `src/formats/osm/models.py:OSMNode` | Gate lat/lon, `is_gate`, `is_parking_position` |
| `src/formats/osm/converter.py` | Gate geo coords in `config["gates"][*]["geo"]` |
| `src/ml/gate_model.py:Gate.from_osm_gate()` | Pattern for loading gate positions from config |
| `src/simulation/recorder.py` | Event dict formats (13 snapshot fields, gate_event, phase_transition) |
| `app/backend/services/opensky_service.py:determine_flight_phase()` | Base phase from altitude/vrate/on_ground |
| `src/ml/obt_features.py:extract_training_data()` | Consumer of the enriched events — validates format |

## Files to Create/Modify

| File | Action |
|------|--------|
| `src/inference/__init__.py` | Create (empty) |
| `src/inference/opensky_events.py` | Create — core event inference engine |
| `app/backend/api/opensky.py` | Modify — integrate inferrer into `get_recording_data()` |
| `tests/inference/__init__.py` | Create (empty) |
| `tests/inference/test_opensky_events.py` | Create — unit tests for event inference |

## Verification

1. Unit tests: `uv run pytest tests/inference/ -v` — event detection logic
2. Integration: `curl /api/opensky/recordings/LSGG/2026-04-03` — response now has non-empty `phase_transitions` and `gate_events`
3. ML compatibility: Run `extract_training_data()` on the enriched recording data to verify it produces valid `OBTFeatureSet` instances
4. Existing tests pass: `uv run pytest tests/ -v -k opensky`
5. Frontend build: `cd app/frontend && npm run build` (no frontend changes needed)

## Limitations & Future Work

- **20-minute recording window:** May not capture full turnarounds (parked→pushback). Need longer collection sessions (2+ hours) for OBT training data.
- **No schedule data:** OpenSky ADS-B doesn't include origin/destination/airline. Could be enriched later via callsign→flight number lookup (FlightAware, ADS-B Exchange).
- **Gate matching accuracy:** Depends on OSM gate position quality. LSGG has good OSM coverage. Some airports may need manual correction.
- **Aircraft type unknown:** ADS-B doesn't transmit aircraft type. Could infer from icao24→type database or callsign→fleet lookup.

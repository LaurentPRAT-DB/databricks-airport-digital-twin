# Realistic Flight Trajectories with OpenAP

## Context

Flight trajectory lines in the simulation look "fuzzy" and unrealistic — aircraft paths zig-zag with no reasonable aerodynamic basis. This is caused by:

1. Random noise injected every tick: +/-200ft altitude, +/-5kt velocity, +/-0.0003 deg position
2. Fixed `speed_factor = 0.002` for approach movement — not tied to actual airspeed
3. No turn smoothing — instant heading changes at waypoints via `_move_toward()`
4. Departing phase uses same `_move_toward()` with fixed 0.002 speed and ad-hoc altitude/speed formulas

OpenAP (v2.5, GPL-3.0, actively maintained) provides physics-based flight performance profiles per aircraft type via `FlightGenerator`. It generates realistic speed, altitude, and vertical rate curves for climb, cruise, and descent — exactly what we need to replace our ad-hoc formulas.

---

## Changes

### 1. Create OpenAP trajectory profile cache (`src/simulation/openap_profiles.py`)

New module that pre-generates and caches OpenAP profiles per aircraft type:

```python
from openap import FlightGenerator

def get_descent_profile(aircraft_type: str) -> DescentProfile:
    """Return cached OpenAP descent profile (altitude, speed, vrate vs progress)."""

def get_climb_profile(aircraft_type: str) -> ClimbProfile:
    """Return cached OpenAP climb profile (altitude, speed, vrate vs progress)."""
```

- Cache profiles in a dict keyed by aircraft type (A320, B738, B777, etc.)
- Normalize profiles to 0.0-1.0 progress for easy interpolation
- Map OpenAP aircraft types to our types via WRAP performance model
- Fallback to A320 profile for unknown types

### 2. Fix approach phase in `_update_flight_state()` (`src/ingestion/fallback.py:2934`)

Replace ad-hoc approach logic:

**Remove:**
- `speed_factor = 0.002` (fixed, unrealistic)
- `random.uniform(-200, 200)` altitude noise (line 2962)
- `random.uniform(-5, 5)` velocity noise (line 2970)
- Ad-hoc vertical rate brackets (lines 2973-2983)

**Replace with:**
- Speed from OpenAP descent profile interpolated by waypoint progress
- Altitude from OpenAP profile (smooth 3 deg glideslope descent)
- Movement distance derived from actual velocity: `speed_deg = velocity_kts * _KTS_TO_DEG_PER_SEC * dt`
- Smooth heading changes via turn rate limiting (max 3 deg/s standard rate turn)

### 3. Fix departing phase (`src/ingestion/fallback.py:3503`)

Replace ad-hoc departure logic:

**Remove:**
- `_move_toward(..., 0.002)` (fixed speed, line 3511)
- `raw_speed = 200 + state.waypoint_index * 50` (unrealistic step function)
- `_interpolate_altitude(state.altitude, target_alt, 500 * dt)` (ad-hoc)

**Replace with:**
- Speed from OpenAP climb profile
- Altitude from climb profile (realistic V2 -> Vclimb -> cruise acceleration)
- Movement from actual velocity

### 4. Add turn rate limiting to `_calculate_heading()` or call sites

New helper function:

```python
def _smooth_heading(current_heading: float, target_heading: float, max_rate_per_sec: float, dt: float) -> float:
    """Limit heading change to realistic turn rate (standard rate = 3 deg/s)."""
```

Apply at approach (line 2990), departing (line 3517), and enroute heading updates.

### 5. Remove position/altitude noise from simulation recorder (`src/ingestion/fallback.py:4185`)

Remove from the trajectory point generation (lines 4185-4189, 4271-4275, 4415-4419):
- `random.uniform(-pos_noise, pos_noise)` on lat/lon
- `random.uniform(-20, 20)` on altitude
- `random.uniform(-3, 3)` on velocity
- `random.uniform(-1, 1)` on heading

These were simulating "radar scatter" but they make trajectory lines look fuzzy. Real ADS-B data has sub-meter GPS precision.

### 6. Remove enroute heading jitter (`src/ingestion/fallback.py:3664`)

Remove `state.heading += random.uniform(-1, 1) * dt` — makes enroute paths wobbly.

---

## Files Modified

| File | Change |
|------|--------|
| `src/simulation/openap_profiles.py` | NEW — OpenAP profile cache |
| `src/ingestion/fallback.py` | Fix approach, departing, remove noise |
| `pyproject.toml` | Already has openap dependency |

---

## Verification

1. `uv run pytest tests/test_aircraft_separation.py tests/test_flight_realism.py -v` — existing tests pass
2. New test: generate 50-tick approach trajectory, verify altitude monotonically decreasing, speed smoothly decelerating, no +/-200ft jumps
3. New test: generate departure trajectory, verify altitude monotonically increasing
4. Visual check: rebuild frontend, run simulation, verify trajectory lines are smooth curves

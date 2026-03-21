# Plan: Calibrate Taxi Speed to Real-World Aviation Standards

**Phase:** 10 — Post-v1
**Date:** 2026-03-10
**Status:** Not yet implemented

---

## Context

Aircraft taxi movement in the synthetic data generator uses a fixed step size per tick (0.0003°) regardless of elapsed time (dt). This makes movement speed dependent on polling frequency rather than real-world physics. With 5-second polling, the effective speed is ~13 kts — reasonable but not calibrated to industry standards.

Real-world taxi speeds (ICAO Doc 9157, airline SOPs, ICAO Annex 14):
- Straight taxiway: 20-30 kts (design speed 25 kts)
- Taxiway turns: 10-15 kts
- Ramp/near gate: 5-10 kts
- Pushback: 2-5 kts
- High-speed runway exit: 60 kts decelerating

---

## Change

Single file: `src/ingestion/fallback.py`

### 1. Add speed constants (near line 200, after existing separation constants)

```python
# Taxi speed standards (ICAO Doc 9157 / Annex 14 design speeds)
# 1 knot ≈ 0.5144 m/s; 1° latitude ≈ 111,000 m
# So 1 knot = 4.63e-6 °/s
_KTS_TO_DEG_PER_SEC = 0.5144 / 111_000  # ~4.63e-6

TAXI_SPEED_STRAIGHT_KTS = 25    # ICAO standard taxiway design speed
TAXI_SPEED_TURN_KTS = 15        # Reduced speed through turns
TAXI_SPEED_RAMP_KTS = 8         # Near-gate / ramp area
TAXI_SPEED_PUSHBACK_KTS = 3     # Tug-assisted pushback
```

### 2. Make taxi movement dt-dependent in `_update_flight_state`

Replace all hardcoded `_move_toward(..., 0.0003)` calls in taxi phases with dt-scaled movement:

**TAXI_TO_GATE on taxiway (line 1416):**
```python
# Before: _move_toward(..., 0.0003)
# After:
speed_deg = TAXI_SPEED_STRAIGHT_KTS * _KTS_TO_DEG_PER_SEC * dt
new_pos = _move_toward((state.latitude, state.longitude), target, speed_deg)
state.velocity = TAXI_SPEED_STRAIGHT_KTS
```

**TAXI_TO_GATE near gate (line 1447):**
```python
speed_deg = TAXI_SPEED_RAMP_KTS * _KTS_TO_DEG_PER_SEC * dt
new_pos = _move_toward((state.latitude, state.longitude), target, speed_deg)
state.velocity = TAXI_SPEED_RAMP_KTS
```

**TAXI_TO_RUNWAY (line 1523):**
```python
speed_deg = TAXI_SPEED_STRAIGHT_KTS * _KTS_TO_DEG_PER_SEC * dt
new_pos = _move_toward((state.latitude, state.longitude), target, speed_deg)
state.velocity = TAXI_SPEED_STRAIGHT_KTS
```

**PUSHBACK (lines 1493-1494):**
```python
# Before: state.latitude += 0.00002 * dt * math.cos(pb_rad)
# After:
pb_speed_deg = TAXI_SPEED_PUSHBACK_KTS * _KTS_TO_DEG_PER_SEC * dt
state.latitude += pb_speed_deg * math.cos(pb_rad)
state.longitude += pb_speed_deg * math.sin(pb_rad)
state.velocity = TAXI_SPEED_PUSHBACK_KTS
```

### 3. Scale waypoint-reach threshold with dt

Current threshold 0.0005 is fine for fixed step, but with higher speeds at 25 kts we need to ensure aircraft don't overshoot. Use `max(speed_deg, 0.0005)` as threshold:

```python
if _distance_between(..., target) < max(speed_deg, 0.0005):
    state.waypoint_index += 1
```

### 4. Update `_update_flight_state` signature

The function already receives `dt` as a parameter. No signature change needed — just use `dt` in the taxi calculations above.

---

## Verification

1. `uv run pytest tests/ -v` — all Python tests pass
2. `cd app/frontend && npm test -- --run` — all frontend tests pass
3. `cd app/frontend && npm run build` — build succeeds
4. Deploy and visually verify: aircraft taxi at realistic speed on the map, following taxiway paths
5. Check that reported velocity in flight details matches the constants (25 kts on taxiway, 8 kts near gate, 3 kts pushback)

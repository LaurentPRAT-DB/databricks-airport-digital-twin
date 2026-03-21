# Plan: Realistic Takeoff Physics, Regulations & Safety

**Phase:** 16 — Post-v1
**Date:** 2026-03-12
**Status:** Not yet implemented
**Depends on:** Phase 8 (OSM taxiway routing), Phase 12 (origin-aware trajectories)

---

## Context

The current takeoff (lines 1728-1749 of `fallback.py`) is oversimplified:
- Fixed acceleration (`velocity + 30 * dt`), no aircraft-type variation
- Fixed rotation speed (140 kts for all types)
- Moves west by `longitude -= 0.002 * dt` instead of following actual runway geometry
- No sub-phases: jumps from ground roll to airborne instantly
- No V1/VR/V2 speed modeling (14 CFR 25.107)
- No climb gradient enforcement (14 CFR 25.111 requires 2.4% min)
- No departure wake separation timing (FAA 7110.65 5-8-1)
- Runway release at 500 ft — should be based on clearing departure end

---

## Regulatory References

| Regulation | Requirement |
|---|---|
| 14 CFR 25.107 | V1 (decision), VR (rotation), V2 (takeoff safety) speed definitions |
| 14 CFR 25.111 | Takeoff path: min 2.4% net climb gradient, all-engine |
| 14 CFR 25.113 | Takeoff distance: 115% of distance to 35 ft screen height |
| FAA 7110.65 5-8-1 | Departure separation: 2 min behind HEAVY/SUPER on same runway |
| ICAO Doc 4444 6.3.3 | Wake turbulence departure separation (2-3 min by category) |

---

## Changes

### 1. Add takeoff performance constants (~line 210)

**File:** `src/ingestion/fallback.py`

```python
TAKEOFF_PERFORMANCE = {
    # type: (V1, VR, V2, accel_kts/s, initial_climb_fpm)
    "A318": (125, 130, 135, 3.0, 2500),
    "A319": (128, 133, 138, 2.8, 2400),
    "A320": (130, 135, 140, 2.7, 2300),
    "A321": (135, 140, 145, 2.5, 2200),
    "B737": (128, 133, 138, 2.8, 2500),
    "B738": (132, 137, 142, 2.6, 2300),
    "B739": (134, 139, 144, 2.5, 2200),
    "CRJ9": (120, 125, 130, 3.2, 2800),
    "E175": (118, 123, 128, 3.3, 3000),
    "E190": (122, 127, 132, 3.1, 2700),
    "A330": (140, 145, 150, 2.0, 1800),
    "A340": (145, 150, 155, 1.8, 1600),
    "A345": (145, 150, 155, 1.8, 1600),
    "A350": (138, 143, 148, 2.2, 2000),
    "B777": (142, 147, 152, 2.0, 1900),
    "B787": (138, 143, 148, 2.3, 2100),
    "B747": (150, 155, 160, 1.6, 1500),
    "A380": (150, 155, 165, 1.5, 1400),
}

DEPARTURE_SEPARATION_S = {
    ("SUPER", "SUPER"): 180, ("SUPER", "HEAVY"): 180,
    ("SUPER", "LARGE"): 180, ("SUPER", "SMALL"): 180,
    ("HEAVY", "HEAVY"): 120, ("HEAVY", "LARGE"): 120,
    ("HEAVY", "SMALL"): 120, ("LARGE", "SMALL"): 120,
}
DEFAULT_DEPARTURE_SEPARATION_S = 60
```

### 2. Expand FlightState (line 754)

Add: `takeoff_subphase: str = "lineup"`

Sub-phases: `lineup` → `roll` → `rotate` → `liftoff` → `initial_climb`

### 3. Update RunwayState (line 785)

Add: `last_departure_type: str = "LARGE"` — wake category of last departure

### 4. Rewrite TAKEOFF phase handler (replace lines 1728-1749)

**Lineup (~3-5s):**
- Align heading to 280° (runway 28R heading)
- Snap position onto runway centerline (interpolate between thresholds)
- Velocity = 0, transition to `roll` after brief delay

**Roll (brake release → VR):**
- Accelerate at aircraft-specific rate from `TAKEOFF_PERFORMANCE`
- Move along runway centerline: interpolate position between `RUNWAY_28R_WEST` and `RUNWAY_28R_EAST` based on ground roll distance
- Convert speed to distance: `velocity_kts * 1.6878 = ft/s`, accumulate via `phase_progress`
- At VR: transition to `rotate`

**Rotate (~3s):**
- Continue accelerating (80% rate — energy goes to pitch)
- Still on ground, on centerline
- Vertical rate begins ramping: 0 → 500 fpm
- After 3s or velocity ≥ V2: transition to `liftoff`

**Liftoff:**
- `on_ground = False`
- Vertical rate ramps from 500 to `initial_climb_fpm` over ~5s
- Continue along runway heading, gaining altitude
- At 35 ft: transition to `initial_climb`

**Initial climb:**
- Accelerate to V2 + 10
- Climb at full `initial_climb_fpm`
- Maintain heading until 400 ft (noise abatement)
- At 500 ft: release runway, set `last_departure_type`, transition to DEPARTING

### 5. Add departure separation check in TAXI_TO_RUNWAY (line 1712)

Before entering TAKEOFF, check:
```python
elapsed = time.time() - runway_state.last_departure_time
lead_cat = runway_state.last_departure_type
follow_cat = _get_wake_category(state.aircraft_type)
required = DEPARTURE_SEPARATION_S.get((lead_cat, follow_cat), DEFAULT_DEPARTURE_SEPARATION_S)
if elapsed < required:
    state.velocity = 0  # Hold short
    return state
```

### 6. Update runway release in `_release_runway`

Store the departing aircraft's wake category:
```python
runway_state.last_departure_type = _get_wake_category(aircraft_type)
```
(Requires passing `aircraft_type` to `_release_runway` — add parameter.)

### 7. Update existing test constraint

**File:** `tests/test_synthetic_data_requirements.py` line 248
- `"takeoff": (0, 170, 0, 500)` — wider for HEAVY/SUPER V2 speeds

### 8. New test file

**File:** `tests/test_takeoff_physics.py`

- Sub-phase progression: `lineup` → `roll` → `rotate` → `liftoff` → `initial_climb` → DEPARTING
- V-speeds: aircraft reaches VR, V2 at correct sub-phase transitions
- Runway centerline tracking: position stays between runway thresholds
- Altitude at transitions: 0 during roll/rotate, >0 at liftoff, ~35ft screen, ~500ft at DEPARTING
- Departure separation: hold short if < required seconds since last departure
- Aircraft-specific: A380 slower acceleration than CRJ9
- Runway release only after initial climb (not during roll)

---

## Files to Modify

| File | Change |
|---|---|
| `src/ingestion/fallback.py` | Performance data, FlightState, RunwayState, TAKEOFF handler, departure separation |
| `tests/test_synthetic_data_requirements.py` | Update speed constraint range |
| `tests/test_takeoff_physics.py` | New test file |

---

## Verification

1. `uv run pytest tests/ -v -k "takeoff or departure_sep or synthetic_data" --tb=short`
2. `uv run pytest tests/ -v --tb=short` — full regression
3. `./dev.sh` — visual: aircraft accelerates along runway, rotates, climbs

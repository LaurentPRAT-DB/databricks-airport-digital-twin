# ATC Trajectory Review Fixes

## Context

The ATC trajectory review identified 5 issues: separation violations (P0), departure trajectory using ad-hoc physics (P1), approach speed clamped too early (P1), heading reversals in trajectory history (P2), and inconsistent glideslope angles (P2). All fixes target `src/ingestion/fallback.py`.

---

## Fix 1 (P0): Cross-path approach separation

**File:** `src/ingestion/fallback.py` lines 1873-1885

Replace `_check_approach_separation` to check ALL approaching aircraft (not just "ahead"):
- Iterate all APPROACHING/LANDING flights
- If lateral distance < required wake separation AND vertical separation < 1000ft → return False
- This adds ICAO vertical separation (1000ft) as an alternative to lateral
- Keep `_find_aircraft_ahead_on_approach` unchanged (still used for speed-slow-down logic at line 2976)

## Fix 2 (P1): Approach Vref clamping delayed to final

**File:** `src/ingestion/fallback.py` lines 2984-2986

Replace unconditional `max(vref, ...)` with altitude-aware clamping:
- Below 2000ft or progress > 0.85: full Vref floor (current behavior)
- Above 2000ft: soft floor at 90% Vref (prevents pathological drops while allowing 180-210kt at altitude)

## Fix 3 (P1): Departure trajectory recorder -> OpenAP profiles

**File:** `src/ingestion/fallback.py` lines 4238-4310

Replace ad-hoc `velocity = 200 + climb_progress * 100` with `get_climb_profile()` + `interpolate_profile()`:
- Takeoff roll: profile progress 0.0-0.05
- Climb out: profile progress 0.05-0.40, enforce 250kt below FL100
- En-route extension: profile progress 0.40-0.80

## Fix 4 (P2): Smooth heading in trajectory recorder

**File:** `src/ingestion/fallback.py` — all three code paths in `generate_synthetic_trajectory`

Use existing `_smooth_heading(current, target, 3.0, interval_seconds)` to smooth heading across consecutive trajectory points instead of snapping. Track `running_heading` variable through the for-loop.

Apply in 3 places:
- Ground/approach section (line 4104)
- Departure section (line 4272/4290)
- Airborne approach section (line 4426)

## Fix 5 (P2): Glideslope angle consistency

**File:** `src/ingestion/fallback.py`

1. Live sim line 2970: Change mapping from `0.6 + 0.4 * progress` to `0.5 + 0.5 * progress` (widen profile coverage)
2. Trajectory recorder approach sections: Replace linear altitude interpolation with `get_descent_profile()` + `interpolate_profile()`:
   - Ground/approach (lines 4099-4108): profile progress 0.5-1.0
   - Airborne approach (lines 4422-4428): profile progress 0.3-1.0

---

## Implementation Order

1. Fix 1 (separation) → run separation tests
2. Fix 2 (Vref) → quick 3-line change
3. Fix 3 (departure trajectory OpenAP) → import already available
4. Fix 5 (glideslope) → pairs with Fix 3 in same function
5. Fix 4 (heading smoothing) → last, touches all 3 paths

---

## Verification

```bash
uv run pytest tests/test_aircraft_separation.py -v          # Fix 1
uv run pytest tests/test_openap_trajectories.py -v          # Fixes 3-5
uv run pytest tests/test_flight_realism.py -v               # Speed envelope
uv run pytest tests/ -v                                      # Full regression
```

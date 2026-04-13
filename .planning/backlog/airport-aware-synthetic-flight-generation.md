# Plan: Airport-Aware Synthetic Flight Generation

## Context

When switching to an airport like GVA that has no recorded simulation, the synthetic generator already uses some airport context (airport center, loaded gates, airline shares from calibration profiles, origin/destination route shares) but still has several hardcoded/generic behaviors that make the animation feel inconsistent:

1. Flight count is always 100 regardless of airport size (a small regional airport shouldn't have the same traffic as a major hub)
2. Phase distribution weights are hardcoded (same parked/approach/taxi ratios for every airport)
3. Hourly traffic profile is ignored — profiles have hourly_profile data (24-element array of relative weights by hour) but the synthetic generator never uses it
4. Fallback runway heading is always 280 degrees when no OSM data exists

What already works well:
- Airline selection uses calibrated profile airline_shares when available
- Origin/destination picks use domestic_route_shares / international_route_shares
- Aircraft type uses fleet mix from profiles
- Airport center and gate positions come from OSM after activation

## Changes

### 1. Scale flight count to airport size

**File:** `src/ingestion/fallback.py` — `generate_synthetic_flights()` (~line 4836)

Before filling flights up to count, compute an airport-appropriate target:
- Use loaded gate count as the primary signal: `target = max(15, min(count, int(len(get_gates()) * 1.5)))`
- A small airport with 10 gates gets ~15 flights, a hub with 80 gates gets ~100+
- The 1.5x multiplier accounts for airborne + taxiing flights beyond gate capacity
- Still capped by the count parameter (100) so big airports don't explode

### 2. Use hourly traffic profile to modulate flight count

**File:** `src/ingestion/fallback.py` — `generate_synthetic_flights()` (~line 4836)

When the calibration profile has hourly_profile, scale the target count by current hour's weight:
- Get current UTC hour, look up the weight, normalize against peak hour
- At 3 AM (weight ~0.002) -> ~5% of target. At 8 AM peak (weight ~0.078) -> 100% of target
- Minimum floor of 5 flights (airport is never completely empty in a demo)

### 3. Use hourly profile to adjust arrival/departure balance

**File:** `src/ingestion/fallback.py` — phase weight block (~line 4918-4944)

Many airports have morning arrival banks and evening departure banks. With the hourly profile, when current hour is below average weight, bias more toward parked (quieter periods have more idle aircraft); when above, bias toward active phases.

This is a lightweight enhancement: compare current hour weight to the average — if below, increase parked_weight; if above, increase approach/departing weights.

### 4. Derive fallback runway heading from airport latitude

**File:** `src/ingestion/fallback.py` — `_get_fallback_runway()` (line 1889)

Currently hardcoded to 280 degrees. Instead, use prevailing wind patterns:
- Northern hemisphere mid-latitudes (30-60N): ~270 (westerlies) — already close
- Tropics (0-30): ~90 (easterlies / trade winds)
- Southern hemisphere mid-latitudes: ~270
- This only matters when OSM doesn't have runway data (rare after activation)

## Files Modified

| File | Change |
|------|--------|
| `src/ingestion/fallback.py` | Scale flight count by gate count + hourly profile; adjust phase weights; fix fallback runway heading |

## Verification

1. `uv run pytest tests/test_ingestion.py -v` — existing synthetic flight tests pass
2. `uv run pytest tests/test_flight_realism.py -v` — realism checks still pass
3. `uv run pytest tests/test_flight_origins_destinations.py -v` — origin/destination tests pass
4. `uv run pytest tests/test_aircraft_separation.py -v` — separation constraints maintained
5. Manual test: switch to GVA, observe fewer flights than SFO, correct airlines (EZY, SWR)
6. Manual test: switch to a large hub (DFW), observe flight count scales up

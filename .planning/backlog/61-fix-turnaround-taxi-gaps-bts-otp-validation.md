# Fix Turnaround & Taxi Time Gaps + Add BTS OTP Validation Pipeline

## Context

Simulation validation revealed two critical accuracy gaps:

| Metric | Real (BTS OTP Dec 2024) | Simulated | Error |
|--------|------------------------|-----------|-------|
| Turnaround time | median=72 min, P75=96, P95=180 | avg=26.5 min | 2.7x under |
| Taxi-out time | mean=20.4 min, median=19, P95=36 | max 10 min (capped) | 2x under |
| Taxi-in time | mean=8.5 min, median=6, P95=22 | max 10 min (capped) | Roughly OK |

**Root causes:**
1. **Turnaround:** `_critical_path_turnaround()` compresses 12 parallel sub-phases via DAG, yielding ~26 min. Real turnarounds include buffer time, late passengers, baggage reconciliation, airline slack not modeled.
2. **Taxi-out:** `_max_phase_seconds["taxi_to_runway"] = 600` (10 min cap). Real SFO taxi-out averages 20 min due to departure queues at runway holding points.
3. **No taxi/turnaround data in profiles:** `AirportProfile` lacks these fields; BTS OTP has `TaxiOut`/`TaxiIn` columns that `parse_otp_prezip()` ignores.

Additionally, no periodic data refresh pipeline exists to keep calibration current.

---

## Plan

### Step 1: Extract taxi + turnaround stats from BTS OTP data

**File:** `src/calibration/bts_ingest.py`

Modify `parse_otp_prezip()` (line ~559) to also collect:
- `TaxiOut` per-flight → compute mean, median, P95 for departures
- `TaxiIn` per-flight → compute mean, median, P95 for arrivals
- Turnaround proxy: group by `(Tail_Number, FlightDate)`, find arr→dep gaps at the same airport, compute distribution

Add to returned dict:
```python
"taxi_out_stats": {"mean": float, "median": float, "p95": float, "n": int},
"taxi_in_stats": {"mean": float, "median": float, "p95": float, "n": int},
"turnaround_stats": {"mean": float, "median": float, "p25": float, "p75": float, "p95": float, "n": int},
```

### Step 2: Add taxi/turnaround fields to AirportProfile

**File:** `src/calibration/profile.py`

Add to `AirportProfile` dataclass:
```python
taxi_out_mean_min: float = 0.0
taxi_out_p95_min: float = 0.0
taxi_in_mean_min: float = 0.0
taxi_in_p95_min: float = 0.0
turnaround_median_min: float = 0.0
turnaround_p75_min: float = 0.0
turnaround_p95_min: float = 0.0
```

### Step 3: Wire OTP taxi/turnaround data into profile builder

**File:** `src/calibration/profile_builder.py`

In `_enrich_with_otp()` (line ~163), after delay stats, add:
```python
if otp.get("taxi_out_stats") and otp["taxi_out_stats"]["n"] > 100:
    profile.taxi_out_mean_min = otp["taxi_out_stats"]["mean"]
    profile.taxi_out_p95_min = otp["taxi_out_stats"]["p95"]
# ... same for taxi_in and turnaround
```

### Step 4: Use calibrated turnaround time in simulation engine

**File:** `src/simulation/engine.py`

In `_generate_schedule()` (line ~374-380), replace:
```python
turnaround = _critical_path_turnaround(arr["aircraft_type"])
```
with:
```python
turnaround = self._calibrated_turnaround(arr["aircraft_type"], arr["airline_code"])
```

Add new method `_calibrated_turnaround()` that:
1. Checks `self.airport_profile.turnaround_median_min` — if > 0, use it as base
2. Applies aircraft category scaling (wide-body ~1.5x narrow-body)
3. Applies airline turnaround factor from `AIRLINE_TURNAROUND_FACTOR`
4. Adds ±15% jitter (matching real P25-P75 spread)
5. Falls back to `_critical_path_turnaround()` if no calibration data

### Step 5: Use calibrated taxi times in simulation engine

**File:** `src/simulation/engine.py`

Update `_max_phase_seconds` (line ~206-213) to use profile data:
```python
self._max_phase_seconds = {
    "taxi_to_gate": max(600, profile_taxi_in_p95 * 60),
    "taxi_to_runway": max(600, profile_taxi_out_p95 * 60),
    ...
}
```

Also in `_force_advance` timing, add natural taxi duration variance.

**File:** `src/ingestion/fallback.py`

The taxi movement speed is governed by `TAXI_SPEED_STRAIGHT_KTS = 25` and `_move_toward()` speed factor. The `_max_phase_seconds` cap is what cuts taxi short. Increase the default taxi-to-runway cap to match real data, and scale by profile when available.

### Step 6: Add OTP data auto-download to calibration pipeline

**File:** `scripts/download_calibration_data.py`

Add `download_otp_prezip()` function that:
1. Checks `data/calibration/raw/otp/` for existing files
2. Downloads missing months from `https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_(1987_present)_{YEAR}_{MONTH}.zip`
3. Saves as `otp_{YEAR}_{MONTH}.zip`
4. Accepts `--months N` to control how many months back (default 12)

### Step 7: Add periodic data refresh configuration

**File:** `scripts/refresh_calibration_data.py` (new)

Create an orchestrator script:
1. Download latest OTP PREZIP + OurAirports data
2. Rebuild profiles for all airports
3. Log what changed (diff old vs new profile stats)
4. Optionally upload to Unity Catalog

**File:** `resources/calibration_refresh_job.yml` (new)

Add a Databricks workflow job:
- Schedule: weekly (every Monday 06:00 UTC)
- Task 1: Run `refresh_calibration_data.py`
- Task 2: Run `realism_scorecard.py` to verify quality
- Uses serverless compute

**File:** `data/calibration/data_sources.json`

Add `check_update_days` and `last_refreshed` tracking fields per source.

### Step 8: Rebuild all 21 US airport profiles with new data

Run `scripts/build_airport_profiles.py` after changes to regenerate profiles with taxi/turnaround stats from the 12 months of OTP data already downloaded.

### Step 9: Add validation test

**File:** `tests/test_calibration_taxi_turnaround.py` (new)

- Test that KSFO profile has `taxi_out_mean > 15` min (real is 20.4)
- Test that KSFO profile has `turnaround_median > 50` min (real is 72)
- Test that simulation with calibrated profile produces turnaround within 30% of real
- Test that `_calibrated_turnaround()` uses profile data when available, falls back to DAG

### Step 10: Update existing tests

Run full test suite to ensure no regressions:
- `uv run pytest tests/ -v`
- `cd app/frontend && npm test -- --run`

---

## Files to Modify

| File | Change |
|------|--------|
| `src/calibration/bts_ingest.py` | Extract TaxiOut/TaxiIn/turnaround from OTP |
| `src/calibration/profile.py` | Add taxi/turnaround fields to AirportProfile |
| `src/calibration/profile_builder.py` | Wire OTP stats into profile building |
| `src/simulation/engine.py` | Use calibrated turnaround + taxi times |
| `scripts/download_calibration_data.py` | Add OTP PREZIP auto-download |
| `scripts/refresh_calibration_data.py` | New: orchestrator for periodic refresh |
| `resources/calibration_refresh_job.yml` | New: weekly Databricks job |
| `data/calibration/data_sources.json` | Add refresh tracking |
| `tests/test_calibration_taxi_turnaround.py` | New: validation tests |

---

## Verification

1. Run `python scripts/build_airport_profiles.py --airports SFO` and verify `KSFO.json` now contains `taxi_out_mean_min ~20`, `turnaround_median_min ~72`
2. Run simulation: `uv run python -m src.simulation.cli --airport SFO --arrivals 25 --departures 25 --seed 42 --output /tmp/val.json` and verify avg turnaround is 55-90 min range (vs old 26.5)
3. Run `uv run pytest tests/ -v` — no regressions
4. Run `cd app/frontend && npm test -- --run` — no regressions
5. Run `python scripts/realism_scorecard.py --airports SFO` — score should improve

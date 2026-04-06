# Plan: Use Calibration Delay Distributions for Recorded OpenSky Data

**Status:** Backlog
**Date added:** 2026-04-06
**Related:** Calibration-Based Delay Imputation, OpenSky Sim Gap Analysis
**Scope:** OBT feature extraction — replace hardcoded zeros with calibrated delay samples

---

## Context

The OBT model's `extract_training_data_from_recording()` currently sets `arrival_delay_min=0` and `scheduled_buffer_min=0` for all recorded flights because ADS-B has no schedule data. This creates a feature distribution mismatch — the model was trained on simulation data with BTS-calibrated delays (mean ~15-35min, 8-30% delay rate), but sees all-zeros at inference on recorded data.

We already have per-airport delay distributions in calibration profiles (`delay_rate`, `mean_delay_minutes`, `delay_distribution`). We can sample from these to fill delay features, matching the training distribution.

## Changes

### File: `src/ml/obt_features.py`

#### 1. Add delay sampler helper

Add import and module-level helper (~line 17):

```python
import random

_profile_loader: Optional["AirportProfileLoader"] = None

def _sample_calibrated_delay(airport_iata: str) -> tuple[float, float, int]:
    """Sample delay from calibration profile for recorded data.

    Returns (arrival_delay_min, scheduled_buffer_min, scheduled_dep_hour_offset).
    Uses the same distribution the simulation uses for training data.
    """
    global _profile_loader
    if _profile_loader is None:
        from src.calibration.profile import AirportProfileLoader
        _profile_loader = AirportProfileLoader()

    profile = _profile_loader.get_profile(airport_iata) if airport_iata else None
    delay_rate = profile.delay_rate if profile else 0.15
    mean_delay = profile.mean_delay_minutes if profile else 20.0

    if random.random() > delay_rate:
        return 0.0, 0.0, 0

    # Log-normal delay (same formula as _generate_delay_details in schedule_generator.py)
    sigma = 0.8
    mu = math.log(max(mean_delay, 5.0)) - sigma * sigma / 2.0
    delay_minutes = max(5, min(120, round(random.lognormvariate(mu, sigma))))

    # scheduled_buffer: typical buffer is turnaround_nominal minus delay
    # Negative buffer = late, positive = early. Sample centered around -delay.
    scheduled_buffer = -delay_minutes * random.uniform(0.5, 1.0)

    return float(delay_minutes), scheduled_buffer, 0
```

#### 2. Update `extract_training_data_from_recording()` (~lines 614-635)

Replace:

```python
# Recorded data: no real delay info — use 0
arrival_delay = 0.0
scheduled_dep_hour = parked_time.hour
...
scheduled_buffer = 0.0
```

With:

```python
# Sample from calibration profile delay distribution
arrival_delay, scheduled_buffer, dep_hour_offset = _sample_calibrated_delay(airport_code)
# Offset scheduled dep hour backward by delay to approximate real schedule
scheduled_dep_hour = (parked_time.hour - int(arrival_delay / 60)) % 24
```

This replaces the hardcoded zeros at lines 615, 618, and 635.

### File: `tests/test_obt_features_recording.py` (or existing test file)

Add a test that verifies:

- With a known airport code (e.g., "ATL"), the extracted delay features are non-zero for some fraction of flights
- The delay distribution roughly matches the profile's `delay_rate`

## Verification

1. `uv run pytest tests/ -k "obt" -v` — existing OBT tests pass
2. `cd app/frontend && npm test -- --run` — no frontend impact
3. Manual check: run extraction on a recorded dataset, verify `arrival_delay_min` is non-zero ~15-30% of the time with realistic magnitudes

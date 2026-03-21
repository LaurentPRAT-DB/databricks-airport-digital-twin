# Phase 32: OBT Model Improvements — Feature-Dependent Turnarounds + Enhanced Feature Engineering

## Goal

Make the OBT model genuinely learn multi-feature interactions by (1) making simulation turnaround duration depend on weather, airline, congestion, and international status, and (2) adding missing features identified in the data science review. Then re-run the 132 calibrated simulations and retrain.

## Status: Plan — Not Started

## Prerequisites: Phase 31 (Train OBT on 132 Sims) should be complete so we have a baseline to compare against.

---

## Context

The OBT model review (OBT_MODEL_REVIEW.md) identified a fundamental problem: the simulation generates turnaround as `base_time * uniform(0.8, 1.2)` where `base_time` depends **only** on narrow/wide aircraft type. The 11 other features (airline, weather, congestion, etc.) have zero effect on the target variable. The ML model can only learn per-category means.

This phase fixes that by making the simulation generate feature-dependent turnarounds, then adds missing features identified in the literature review.

---

## Data Sufficiency Assessment

### Current Data: 132 simulations, ~41.5GB, ~40K OBT training samples

**Sufficient for:** Single global model with 12-15 features. Rule of thumb: 10-20 samples per feature per tree leaf. With 40K samples, max_depth=6, this supports ~15 features comfortably.

**Insufficient for:**
- Per-airport models (only ~1,200 samples per airport — too few for independent models)
- Rare event detection (ground stops affect <5% of turnarounds, ~2K samples)
- Seasonal patterns (simulation uses fixed date, no multi-month variation)

### After This Phase: Same 132 simulations, re-run with feature-dependent turnarounds

The sample count stays at ~40K but the information content per sample increases dramatically because the target now varies with weather, airline, congestion, and international status.

### Recommended Future Data Improvements

| Improvement | Impact | When |
|-------------|--------|------|
| **Multi-day seeds** (7 days per airport, 33x7=231 normal runs) | Day-of-week patterns | Phase 33+ |
| **Multi-season runs** (4 seasons x 33 airports = 132 more) | Seasonal effects | Phase 33+ |
| **Vary flight counts** (250/500/750 per run) | Congestion range coverage | Phase 33+ |
| **Add OurAirports country data** to schedule | Better international detection now | This phase |

---

## Implementation Plan

### Sub-phase A: Feature-Dependent Turnaround Generation (Simulation Change)

**File:** `src/ingestion/fallback.py` — PARKED phase (lines 2325-2357)

#### A1. Add airline turnaround multiplier table

New constant near the top of fallback.py (after the GSE imports):

```python
# Airline turnaround speed factors (1.0 = standard, <1.0 = faster, >1.0 = slower)
# Based on industry data: LCCs are 15-30% faster, full-service carriers standard,
# Gulf/Asian carriers 5-15% slower (more catering/cleaning for premium service).
AIRLINE_TURNAROUND_FACTOR: dict[str, float] = {
    # US low-cost carriers — fast turns
    "SWA": 0.72,  # Southwest: 25-min target, industry fastest
    "FFT": 0.78,  # Frontier: ULCC, minimal service
    "NK":  0.78,  # Spirit: ULCC
    "JBU": 0.88,  # JetBlue: midway between LCC and legacy
    # US legacy carriers — standard
    "UAL": 1.0, "DAL": 1.0, "AAL": 1.0,
    # US regional — slightly faster (smaller aircraft offset by less crew)
    "ASA": 0.92, "SKW": 0.90, "RPA": 0.90, "ENY": 0.90,
    # European carriers
    "RYR": 0.70,  # Ryanair: 25-min target
    "EZY": 0.75,  # easyJet: 30-min target
    "BAW": 1.05, "DLH": 1.05, "AFR": 1.05, "KLM": 1.0,
    # Gulf carriers — premium service, longer turns
    "UAE": 1.15, "QTR": 1.12, "ETD": 1.10,
    # Asian carriers — premium service
    "SIA": 1.10, "CPA": 1.08, "ANA": 1.05, "JAL": 1.05, "KAL": 1.05,
    "CZ":  1.0,  # China Southern: varies
    # Latin American
    "AMX": 1.0, "MXA": 1.0,
}
DEFAULT_AIRLINE_FACTOR = 1.0
```

#### A2. Add weather-dependent turnaround factor

New helper function:

```python
def _get_weather_turnaround_factor() -> float:
    """Weather impact on ground handling operations.

    High winds slow fueling/cargo; low visibility slows ramp movement;
    precipitation affects loading/unloading.
    """
    factor = 1.0
    # Access current weather from the capacity manager or weather state
    wind = _get_current_wind_speed()  # from weather_generator state
    vis = _get_current_visibility()

    if wind > 50:
        factor += 0.25  # Extreme: possible ramp closure
    elif wind > 35:
        factor += 0.15  # High winds: slow fueling, cargo
    elif wind > 25:
        factor += 0.05  # Moderate: minor delays

    if vis < 0.5:
        factor += 0.15  # Near-zero vis: very slow ramp ops
    elif vis < 1.0:
        factor += 0.10  # Poor: slow vehicle movement
    elif vis < 3.0:
        factor += 0.05  # Reduced: minor impact

    return factor
```

#### A3. Add congestion and international factors

```python
def _get_congestion_turnaround_factor(gate_id: str) -> float:
    """More concurrent gate ops = longer turnaround due to crew contention."""
    concurrent = _count_occupied_gates()  # existing function
    # +1% per extra aircraft above 10 concurrent
    return 1.0 + 0.01 * max(0, concurrent - 10)

def _get_international_turnaround_factor(state: FlightState) -> float:
    """International flights have longer turnarounds (+20-30%)."""
    origin = state.origin_airport or ""
    dest = state.destination_airport or ""
    local = get_current_airport_iata()
    other = dest if origin == local else origin
    if _is_international_airport(other):
        return 1.25  # customs, extra catering, longer cleaning
    return 1.0
```

#### A4. Modify PARKED phase to use all factors

Replace `fallback.py:2339`:

```python
# BEFORE (line 2339):
target = gate_seconds * random.uniform(0.8, 1.2)

# AFTER:
airline_factor = AIRLINE_TURNAROUND_FACTOR.get(
    state.callsign[:3] if state.callsign else "", DEFAULT_AIRLINE_FACTOR
)
weather_factor = _get_weather_turnaround_factor()
congestion_factor = _get_congestion_turnaround_factor(state.assigned_gate or "")
intl_factor = _get_international_turnaround_factor(state)

combined_factor = airline_factor * weather_factor * congestion_factor * intl_factor
# Jitter reduced from +/-20% to +/-10% since factors now explain more variance
target = gate_seconds * combined_factor * random.uniform(0.9, 1.1)
```

**Expected turnaround ranges after this change:**

| Scenario | Narrow-body | Wide-body |
|----------|-------------|-----------|
| SWA, good weather, low congestion | ~23 min | — (SWA doesn't fly widebody) |
| UAL domestic, good weather | ~32 min | ~70 min |
| UAE international, good weather | ~46 min | ~103 min |
| UAL domestic, LIFR + 50kt gusts | ~45 min | ~98 min |
| UAE intl, high congestion, windy | ~55 min | ~120 min |

This produces the spread needed for the ML model to learn meaningful feature interactions.

#### A5. Expose weather state to fallback.py

The PARKED phase in `fallback.py` currently has no access to weather data. The simulation engine passes weather to `CapacityManager` but not to the flight state machine.

**Option:** Add module-level weather state (similar to the existing `_flight_states` dict pattern):

```python
# In fallback.py, near other module-level state:
_current_weather: dict = {"wind_speed_kts": 0, "visibility_sm": 10.0}

def set_current_weather(wind_speed_kts: float, visibility_sm: float) -> None:
    """Called by engine after each weather update."""
    _current_weather["wind_speed_kts"] = wind_speed_kts
    _current_weather["visibility_sm"] = visibility_sm

def _get_current_wind_speed() -> float:
    return _current_weather.get("wind_speed_kts", 0)

def _get_current_visibility() -> float:
    return _current_weather.get("visibility_sm", 10.0)
```

**In engine.py**, after recording weather (line 957):
```python
from src.ingestion.fallback import set_current_weather
set_current_weather(
    metar.get("wind_speed_kts", 0),
    metar.get("visibility_sm", 10.0),
)
```

---

### Sub-phase B: Enhanced Feature Engineering (OBT Features Change)

**File:** `src/ml/obt_features.py`

#### B1. Fix international detection — use country lookup

Replace the broken first-character heuristic with the existing `_AIRPORT_COUNTRY` dict from `fallback.py:1745`:

```python
# In obt_features.py, add a country mapping (reuse from fallback.py)
_AIRPORT_COUNTRY = {
    "SFO": "US", "LAX": "US", "ORD": "US", "DFW": "US", "JFK": "US",
    "ATL": "US", "DEN": "US", "SEA": "US", "BOS": "US", "PHX": "US",
    "LAS": "US", "MCO": "US", "MIA": "US", "CLT": "US", "MSP": "US",
    "DTW": "US", "EWR": "US", "PHL": "US", "IAH": "US", "SAN": "US",
    "PDX": "US",
    "LHR": "GB", "CDG": "FR", "FRA": "DE", "AMS": "NL",
    "HKG": "HK", "NRT": "JP", "HND": "JP", "SIN": "SG", "SYD": "AU",
    "DXB": "AE", "ICN": "KR", "GRU": "BR", "JNB": "ZA",
}

def _is_international_route(origin: str, destination: str, airport_iata: str) -> bool:
    """International = origin and destination in different countries."""
    airport_country = _AIRPORT_COUNTRY.get(airport_iata.upper(), "")
    other = destination if origin.upper() == airport_iata.upper() else origin
    other_country = _AIRPORT_COUNTRY.get(other.upper(), "UNKNOWN")
    if not airport_country or other_country == "UNKNOWN":
        return False  # can't determine, default to domestic
    return airport_country != other_country
```

#### B2. Add day-of-week feature

Add to both `OBTFeatureSet` and `OBTCoarseFeatureSet`:

```python
day_of_week: int  # 0=Monday, 6=Sunday
```

Extract from `parked_time.weekday()` in `extract_training_data()`.

Also add cyclical encoding option:
```python
day_of_week_sin: float  # sin(2*pi*dow/7)
day_of_week_cos: float  # cos(2*pi*dow/7)
```

#### B3. Add scenario type feature

```python
is_weather_scenario: bool  # True if simulation used a scenario file
```

Extract from simulation config: `data.get("config", {}).get("scenario_file") is not None`.

#### B4. Add scheduled buffer time feature (T-park only)

For arrivals that have both `scheduled_time` and a subsequent departure:
```python
scheduled_turnaround_min: float  # scheduled departure - scheduled arrival time
```

This is the airline's planned buffer. When not available (departure flights born as PARKED), use the GSE constant as default.

#### B5. Add airport code as a feature

```python
airport_code: str  # 3-letter IATA, e.g. "SFO"
```

The global model should know which airport it's predicting for. The GBT can learn airport-specific splits naturally.

#### B6. Cyclical hour encoding

Replace integer `hour_of_day` with:
```python
hour_sin: float  # sin(2*pi*hour/24)
hour_cos: float  # cos(2*pi*hour/24)
```

This ensures hour 23 and hour 0 are adjacent.

#### B7. Update feature lists in `obt_model.py`

Update `NUMERIC_FEATURES`, `CATEGORICAL_FEATURES`, `BINARY_FEATURES` and their coarse equivalents to include new features:

**New T-park features:** `day_of_week_sin`, `day_of_week_cos`, `hour_sin`, `hour_cos`, `scheduled_turnaround_min`, `airport_code`, `is_weather_scenario`

**New T-90 features:** `day_of_week_sin`, `day_of_week_cos`, `hour_sin`, `hour_cos`, `airport_code`, `is_weather_scenario`

Remove integer `hour_of_day` and `scheduled_departure_hour` (replaced by cyclical versions).

---

### Sub-phase C: Model Training Improvements

**File:** `src/ml/obt_model.py` and `databricks/notebooks/train_obt_model.py`

#### C1. Add cross-validation

Replace single 80/20 split with 5-fold CV stratified by airport for evaluation, then train final model on all data:

```python
from sklearn.model_selection import StratifiedKFold

# 5-fold CV for evaluation
airports = [d["airport"] for d in all_data]
skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
cv_maes = []
for train_idx, val_idx in skf.split(range(len(all_data)), airports):
    # train on train_idx, evaluate on val_idx
    ...
    cv_maes.append(fold_mae)

print(f"CV MAE: {np.mean(cv_maes):.2f} +/- {np.std(cv_maes):.2f}")

# Final model: train on all data
two_stage.train(all_features, all_targets)
```

#### C2. Add quantile regression for prediction intervals

Train two additional models for P10 and P90:

```python
from sklearn.ensemble import HistGradientBoostingRegressor

# P50 (median) — main model
model_p50 = HistGradientBoostingRegressor(loss="squared_error", ...)

# P10, P90 — for prediction intervals
model_p10 = HistGradientBoostingRegressor(loss="quantile", quantile=0.1, ...)
model_p90 = HistGradientBoostingRegressor(loss="quantile", quantile=0.9, ...)
```

Update `OBTPrediction` to include bounds:
```python
@dataclass
class OBTPrediction:
    turnaround_minutes: float
    lower_bound_minutes: float  # P10
    upper_bound_minutes: float  # P90
    confidence: float  # 1.0 / (P90 - P10), normalized
    is_fallback: bool
    horizon: str = "t_park"
```

#### C3. Feature importance analysis in training notebook

After training, add a cell that:
1. Prints feature importances sorted descending
2. Validates `aircraft_category` is still top-3 (sanity check)
3. Validates new features (airline, weather, congestion) have non-trivial importance
4. Logs a SHAP summary plot to MLflow (optional, requires `shap` dependency)

---

### Sub-phase D: Re-Run Simulations and Retrain

#### D1. Re-run 132 calibrated simulations

The turnaround generation change means all existing simulation data is stale. Must re-run:

```bash
databricks bundle deploy --target dev
databricks bundle run calibration_batch --target dev
```

The existing 132-simulation batch job runs unmodified — it uses `run_simulation_airport.py` which calls the updated `fallback.py`.

**Important:** The old simulation files (cal_*.json with uniform-noise turnarounds) should be archived or deleted before re-running, so the training pipeline doesn't mix old and new data. Add a cleanup step to the batch job or training notebook.

#### D2. Retrain OBT model on new data

```bash
databricks bundle run obt_model_training --target dev
```

#### D3. Compare metrics

Log both old and new metrics to MLflow for side-by-side comparison:

| Metric | Before (uniform noise) | After (feature-dependent) |
|--------|----------------------|--------------------------|
| T-park MAE | ~4-6 min (learns per-category mean) | Target: <5 min (learns multi-feature) |
| T-park R² | ~0.5-0.7 (mostly aircraft_category) | Target: >0.7 (multi-feature) |
| T-90 MAE | ~6-8 min | Target: <8 min |
| Feature importance spread | aircraft_cat ~80%, rest ~0% | aircraft_cat ~30%, airline ~20%, weather ~15%, ... |

---

## Files Modified

| File | Change | Lines |
|------|--------|-------|
| `src/ingestion/fallback.py` | Airline turnaround factors, weather/congestion/intl factors, weather state | ~80 new |
| `src/simulation/engine.py` | Call `set_current_weather()` after weather updates | ~5 |
| `src/ml/obt_features.py` | Fix intl detection, add day_of_week/scenario/buffer/airport/cyclical features | ~60 |
| `src/ml/obt_model.py` | Update feature lists, add quantile models, prediction intervals | ~100 |
| `databricks/notebooks/train_obt_model.py` | Add CV, feature importance analysis, old data cleanup | ~50 |
| `tests/test_obt_model.py` | Update tests for new features, add turnaround factor tests | ~80 |

## Files Created

| File | Purpose |
|------|---------|
| `tests/test_turnaround_factors.py` | Test airline/weather/congestion/intl turnaround multipliers |

---

## Test Plan

### Unit Tests

| Test | Verifies |
|------|----------|
| `test_airline_factor_lcc_faster` | SWA/RYR factor < 0.8 |
| `test_airline_factor_gulf_slower` | UAE/QTR factor > 1.1 |
| `test_weather_factor_high_wind` | Wind >35kt increases factor |
| `test_weather_factor_low_vis` | Vis <1sm increases factor |
| `test_congestion_factor_scales` | Factor increases with concurrent ops |
| `test_intl_factor_applied` | International flights get 1.25x |
| `test_combined_factors_realistic_range` | Turnaround stays in [15, 180] min |
| `test_intl_detection_country_based` | LAX->LHR = international (was broken) |
| `test_intl_detection_domestic` | LAX->SFO = domestic |
| `test_cyclical_hour_encoding` | Hour 23 and 0 are adjacent |
| `test_day_of_week_extracted` | Correct weekday from parked_time |
| `test_feature_set_new_fields` | All new fields present in dataclass |
| `test_prediction_has_bounds` | OBTPrediction includes lower/upper |

### Integration Tests

| Test | Verifies |
|------|----------|
| `test_swa_turnaround_shorter_than_ual` | SWA avg turnaround < UAL avg in simulation output |
| `test_weather_increases_turnaround` | Weather sim avg turnaround > normal sim avg |
| `test_feature_importance_spread` | No single feature >50% importance after training on new data |
| `test_cv_mae_stability` | 5-fold CV std < 1.0 min |

---

## Execution Order

1. **A1-A5:** Simulation turnaround factors (fallback.py + engine.py)
2. **B1-B7:** Feature engineering (obt_features.py + obt_model.py)
3. **C1-C3:** Training pipeline improvements (train_obt_model.py)
4. **Tests:** Unit + integration tests
5. **Local validation:** `uv run pytest tests/test_obt_model.py tests/test_turnaround_factors.py -v`
6. **D1:** Re-run 132 simulations: `databricks bundle run calibration_batch --target dev`
7. **D2:** Retrain: `databricks bundle run obt_model_training --target dev`
8. **D3:** Compare MLflow metrics old vs new

---

## Verification

1. `uv run pytest tests/ -v` — all pass including new tests
2. Local simulation run: SWA flights have shorter turnarounds than UAE flights
3. Local simulation run: Weather scenario produces longer turnarounds than normal-day
4. After Databricks retrain: feature importance shows multi-feature spread (no single feature >50%)
5. After retrain: T-park MAE < 5 min, T-park R² > 0.7
6. MLflow side-by-side: new model clearly beats old on every metric

---

## Estimated Scope

- **New code:** ~280 lines (simulation factors + features + model + training)
- **New tests:** ~150 lines
- **Modified files:** 6
- **Risk:** Medium — changing turnaround generation invalidates all existing simulation data (must re-run 132 sims). Airline factor values are estimates that may need tuning based on simulation output analysis.

---

## Future Data Improvements (Phase 33+)

Once this phase validates that feature-dependent turnarounds produce a better model:

1. **Multi-day batch:** Run 7 days per airport (Mon-Sun) to capture day-of-week patterns. 33 airports x 7 days x 4 runs = 924 simulations.
2. **Seasonal variation:** Add a `season` parameter to simulation config that shifts hourly profile and weather patterns. 4 seasons x 33 airports = 132 additional weather runs.
3. **Variable flight counts:** Run 250/500/750 flights per airport to give the model better congestion range coverage.
4. **Cascading delay seeds:** Run simulations where arrival delays from one airport feed into departure delays at another, creating realistic delay propagation chains.

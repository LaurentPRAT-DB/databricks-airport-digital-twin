# Phase 29: Off-Block Time (OBT) Forecasting Model

## Goal

Train an ML model to predict turnaround duration (and thus pushback time) from simulation data, replacing fixed 45/90 min constants with weather-aware, airline-specific, congestion-sensitive predictions. Target MAE < 5 minutes.

## Status: Plan — Not Started

## Prerequisites: Phase 23 (Simulation Mode) must be complete to generate training data. Phase 28 (Calibrate, Not Fabricate) is recommended for realistic airline/route distributions.

---

## Context

**Problem:** The digital twin currently uses fixed turnaround durations (45min narrow-body, 90min wide-body) from `src/ml/gse_model.py`. Real pushback times vary based on airline operations, time of day, weather, congestion, and delay propagation. An ML model trained on simulation data can predict OBT more accurately, enabling better gate scheduling and delay propagation forecasting.

**OBT definition:** The moment an aircraft pushes back from the gate — the PARKED → PUSHBACK phase transition timestamp in simulation.

**Available data:** 4,031 pushback (OBT) labels across 10 airports × 1 scenario each, from 11 simulation JSON files in `simulation_output/`.

---

## Feature Engineering

### Target Variable

`turnaround_duration_min = (pushback_timestamp - parked_timestamp)` in minutes. This is the actual gate occupancy time. We predict this, then add it to the known parking time to get predicted OBT.

### Features with Rationale

| Feature | Type | Source | Rationale |
|---------|------|--------|-----------|
| `aircraft_category` | categorical | schedule → aircraft_type | Wide-body takes ~2x longer (more pax, cargo, fuel). Maps type to narrow/wide/regional |
| `airline_code` | categorical | schedule → airline | Airlines have different turnaround SOPs. Some are faster (LCCs) vs legacy carriers |
| `hour_of_day` | numeric (0-23) | schedule → scheduled_arrival | Night ops have fewer ground crew, morning banks have pressure for quick turns |
| `is_international` | binary | schedule → origin/destination | International flights need customs, longer deboarding, more catering |
| `arrival_delay_min` | numeric | schedule → delay_minutes | Delayed arrivals often get expedited turnaround OR cause cascading delays |
| `gate_id_prefix` | categorical | gate_events → gate | Terminal area affects ground crew proximity, jetbridge vs stairs |
| `is_remote_stand` | binary | gate_events → gate | Remote stands (R-prefix) need bus ops, adding ~10min |
| `concurrent_gate_ops` | numeric | gate_events | Number of other aircraft at gates when this one parks — proxy for ground crew contention |
| `wind_speed_kt` | numeric | weather_snapshots | High winds slow fueling and cargo loading |
| `visibility_sm` | numeric | weather_snapshots | Low visibility may slow ramp operations |
| `has_active_ground_stop` | binary | scenario_events | Ground stops prevent pushback regardless of turnaround completion |
| `scheduled_departure_hour` | numeric | schedule | Pressure to meet departure slot affects turnaround urgency |

### Feature Extraction Pipeline

**New file:** `src/ml/obt_features.py`

```python
@dataclass
class OBTFeatureSet:
    aircraft_category: str        # "narrow", "wide", "regional"
    airline_code: str
    hour_of_day: int
    is_international: bool
    arrival_delay_min: float
    gate_id_prefix: str
    is_remote_stand: bool
    concurrent_gate_ops: int
    wind_speed_kt: float
    visibility_sm: float
    has_active_ground_stop: bool
    scheduled_departure_hour: int

def extract_obt_features(flight_schedule, gate_event, weather, scenario_events) -> OBTFeatureSet:
    """Extract features from simulation event streams for a single flight."""

def extract_training_data(sim_json_path: Path) -> list[dict]:
    """Parse a simulation JSON file and return (features, target) pairs.

    Joins: schedule + phase_transitions (PARKED→PUSHBACK) + gate_events + weather + scenario_events
    """
```

---

## Data Extraction & Validation

### Extraction from Simulation Files

Each simulation JSON contains:
- `schedule[]` — flight definitions with airline, aircraft, delay, route
- `phase_transitions[]` — `{flight_id, from_phase, to_phase, timestamp}`
- `gate_events[]` — `{flight_id, gate, event_type, timestamp}`
- `weather_snapshots[]` — hourly METAR-style data
- `scenario_events[]` — ground stops, diversions, holdings

**Join logic:**
1. For each flight in schedule, find TAXI_TO_GATE → PARKED transition → `parked_time`
2. Find PARKED → PUSHBACK transition → `pushback_time`
3. `turnaround_duration = pushback_time - parked_time`
4. Match nearest weather snapshot to `parked_time`
5. Check if any ground stop was active during `[parked_time, pushback_time]`
6. Count concurrent gate occupants at `parked_time`

### Data Validation Checks

Before training, validate:
1. **Label sanity:** `turnaround_duration ∈ [10, 180]` minutes (filter outliers)
2. **Feature completeness:** no NaN in critical features (`aircraft_category`, `hour_of_day`)
3. **Class balance:** check distribution of narrow vs wide vs regional
4. **Airport diversity:** confirm all 10 airports contribute training samples
5. **Baseline comparison:** mean turnaround by aircraft category should be ~45min (narrow) / ~90min (wide), matching `gse_model.py` constants

### Existing Data Inventory

| Airport | File | Expected Flights |
|---------|------|------------------|
| KSFO | `simulation_output/sim_KSFO_standard_operations.json` | ~1000 |
| KJFK | `simulation_output/sim_KJFK_standard_operations.json` | ~1000 |
| EGLL | `simulation_output/sim_EGLL_standard_operations.json` | ~1000 |
| RJAA | `simulation_output/sim_RJAA_standard_operations.json` | ~1000 |
| OMDB | `simulation_output/sim_OMDB_standard_operations.json` | ~1000 |
| SBGR | `simulation_output/sim_SBGR_standard_operations.json` | ~1000 |
| YSSY | `simulation_output/sim_YSSY_standard_operations.json` | ~1000 |
| WSSS | `simulation_output/sim_WSSS_standard_operations.json` | ~1000 |
| EDDF | `simulation_output/sim_EDDF_standard_operations.json` | ~1000 |
| FAOR | `simulation_output/sim_FAOR_standard_operations.json` | ~1000 |

~4,031 usable OBT labels (flights that completed full turnaround).

---

## Model Architecture

### Choice: Gradient Boosted Trees (`scikit-learn HistGradientBoostingRegressor`)

**Why not LightGBM/XGBoost:** Adding a C-extension dependency (`lightgbm`) increases deployment complexity. scikit-learn's `HistGradientBoostingRegressor` is equivalent performance for this data size and is a pure Python install.

**Why not neural net:** 4K samples is too small. GBT handles mixed feature types (categorical + numeric) natively and is interpretable.

**Why not the existing rule-based approach:** Fixed durations can't capture airline-specific patterns, weather impacts, or congestion effects. Even simple GBT will capture interaction effects (e.g., wide-body + night + high wind = longer turnaround).

### `src/ml/obt_model.py`

```python
class OBTPredictor:
    """Predicts turnaround duration (minutes) for Off-Block Time forecasting."""

    def __init__(self, airport_code: str, airport_profile=None):
        self.airport_code = airport_code
        self._model = None  # HistGradientBoostingRegressor or fallback
        self._fallback_durations = {"narrow": 45, "wide": 90, "regional": 35}

    def train(self, features: list[OBTFeatureSet], targets: list[float]):
        """Train the GBT model on simulation data."""

    def predict(self, features: OBTFeatureSet) -> OBTPrediction:
        """Predict turnaround duration. Falls back to GSE constants if untrained."""

    def predict_obt(self, parked_time: float, features: OBTFeatureSet) -> float:
        """Predict actual OBT timestamp = parked_time + predicted_turnaround."""
```

**Fallback Behavior:** If no trained model is available (first run, new airport), fall back to `gse_model.py` constants (45/90min). This ensures zero regression from current behavior.

---

## Training Pipeline

**New file:** `scripts/train_obt_model.py`

1. Glob `simulation_output/sim_*.json` files
2. For each file: `extract_training_data()` → list of `(features, target)` dicts
3. Concatenate all airports into one dataset
4. Train/test split: 80/20, stratified by `airport_code`
5. Train `HistGradientBoostingRegressor` with:
   - `max_depth=6, n_estimators=200, learning_rate=0.05`
   - Categorical features handled via `OrdinalEncoder`
6. Evaluate on test set
7. Log to MLflow (if available)
8. Save model pickle to `data/ml_models/obt_model.pkl`
9. Print feature importance ranking

**Train/Validation Split Strategy:**
- 80/20 split, stratified by `airport_code` so each airport is represented in both sets
- No time-based split needed since simulation data is synthetic (no temporal leakage)
- Cross-validation: 5-fold CV for hyperparameter tuning, report mean ± std MAE

---

## Evaluation Metrics & Baselines

### Metrics

| Metric | Purpose |
|--------|---------|
| MAE (Mean Absolute Error) | Primary metric — average prediction error in minutes |
| RMSE | Penalizes large errors (important for gate scheduling) |
| R² | Explained variance vs baseline |
| MAE by `aircraft_category` | Verify narrow/wide predictions are both good |
| MAE by airport | Verify model generalizes across airports |

### Baselines to Beat

| Baseline | Expected MAE | Method |
|----------|-------------|--------|
| GSE constant (45/90min) | ~8-12 min | Current approach — predict 45min for all narrow, 90min for all wide |
| Per-airline mean | ~6-8 min | Mean turnaround per airline from training data |
| **GBT model** | **Target: < 5 min** | Our trained model |

### Success Criteria

- MAE < 5 minutes on held-out test set
- R² > 0.5 (better than mean prediction)
- No airport with MAE > 10 minutes
- Feature importance shows `aircraft_category` as top feature (sanity check)

---

## Integration into Existing ML Infrastructure

### Changes to `src/ml/registry.py`

Add `obt` to the model set:

```python
from src.ml.obt_model import OBTPredictor

# In get_models():
self._instances[airport_code] = {
    "delay": DelayPredictor(...),
    "gate": GateRecommender(...),
    "congestion": CongestionPredictor(...),
    "obt": OBTPredictor(airport_code=airport_code, airport_profile=profile),
}
```

### Changes to `src/ml/training.py`

Add `train_obt_model()` function that:
1. Loads simulation data for the target airport
2. Extracts features + targets
3. Trains `OBTPredictor`
4. Logs to MLflow under `airport_models/{airport}/obt_model`

---

## Dependency Changes

**`pyproject.toml`:** Add `scikit-learn>=1.4` to dependencies. No other new deps needed — scikit-learn pulls in numpy/scipy which are already transitive deps.

---

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `src/ml/obt_features.py` | Create | Feature extraction from simulation data |
| `src/ml/obt_model.py` | Create | `OBTPredictor` with train/predict/fallback |
| `scripts/train_obt_model.py` | Create | Training pipeline script |
| `tests/test_obt_model.py` | Create | Unit + integration tests |
| `src/ml/registry.py` | Modify | Add "obt" to model set |
| `src/ml/training.py` | Modify | Add OBT training function |
| `pyproject.toml` | Modify | Add scikit-learn dependency |

---

## Test Plan

### Unit Tests (`tests/test_obt_model.py`)

```python
class TestOBTFeatureExtraction:
    def test_extract_features_from_simulation_json()   # Parse real sim file
    def test_aircraft_category_mapping()                # B738→narrow, B777→wide
    def test_turnaround_duration_calculation()          # Correct time diff
    def test_handles_missing_weather()                  # Graceful fallback
    def test_concurrent_gate_ops_count()                # Correct counting

class TestOBTPredictor:
    def test_fallback_when_untrained()                  # Returns GSE constants
    def test_train_and_predict()                        # End-to-end on sample data
    def test_prediction_in_reasonable_range()            # 10-180 min
    def test_wide_body_longer_than_narrow()             # Sanity check
    def test_feature_importance_available()              # After training

class TestOBTDataValidation:
    def test_all_airports_have_obt_labels()             # No empty datasets
    def test_turnaround_durations_within_bounds()       # 10-180 min
    def test_no_nan_in_critical_features()              # Completeness
    def test_baseline_mae_calculation()                 # GSE baseline computable

class TestOBTIntegration:
    def test_registry_includes_obt_model()              # After registry change
    def test_training_pipeline_end_to_end()             # Script runs without error
```

### Model Quality Tests (run after training)

```bash
# Train the model
uv run python scripts/train_obt_model.py

# Run tests including model quality assertions
uv run pytest tests/test_obt_model.py -v
```

Quality assertions embedded in test:
- `assert test_mae < 8.0` (must beat GSE baseline)
- `assert test_r2 > 0.3` (must explain some variance)
- Feature importance: `aircraft_category` in top 3

---

## Verification

1. **Install dependency:** `uv add scikit-learn`
2. **Run feature extraction on real sim data:**
   ```bash
   uv run python -c "from src.ml.obt_features import extract_training_data; \
   print(len(extract_training_data('simulation_output/sim_KSFO_standard_operations.json')))"
   ```
3. **Train model:** `uv run python scripts/train_obt_model.py`
4. **Run all tests:**
   ```bash
   uv run pytest tests/test_obt_model.py -v
   uv run pytest tests/ -v  # Full suite, ensure no regressions
   ```
5. **Check MLflow (if available):**
   - Verify experiment `airport_models/KSFO/obt_model` created
   - Verify metrics logged (MAE, RMSE, R², per-airport breakdown)

---

## Estimated Scope

- **New files:** 4 (`obt_features.py`, `obt_model.py`, `train_obt_model.py`, `test_obt_model.py`)
- **Modified files:** 3 (`registry.py`, `training.py`, `pyproject.toml`)
- **Lines:** ~500 new code + ~250 tests
- **Risk:** Low — fallback to GSE constants ensures zero regression. Model quality depends on simulation data diversity (more scenarios = better model).

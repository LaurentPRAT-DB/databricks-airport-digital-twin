# Plan: Rename Turnaround Model + Design True OBT Model

## Context

The current "OBT model" (`src/ml/obt_model.py`) is misnamed. It predicts turnaround duration (minutes from parked -> pushback), not Off-Block Time. In A-CDM terminology:
- Turnaround duration = AOBT - AIBT (what the model actually predicts)
- OBT (Off-Block Time) = the absolute timestamp when the aircraft pushes back from the gate (AOBT)

The `predict_obt()` method at line 607 does `parked_time + turnaround_minutes * 60` — it derives OBT from the duration prediction, but the core ML target is duration, not a timestamp.

## Part 1: Rename Turnaround Model (accurate naming)

Rename all references from `obt_*` / `OBT*` to `turnaround_*` / `Turnaround*` to reflect what the model actually does.

### File renames

| Old | New |
|-----|-----|
| `src/ml/obt_model.py` | `src/ml/turnaround_model.py` |
| `src/ml/obt_features.py` | `src/ml/turnaround_features.py` |
| `tests/test_obt_model.py` | `tests/test_turnaround_model.py` |
| `tests/test_obt_features_recorded.py` | `tests/test_turnaround_features_recorded.py` |
| `scripts/train_obt_model.py` | `scripts/train_turnaround_model.py` |
| `scripts/evaluate_obt_eddf.py` | `scripts/evaluate_turnaround_eddf.py` |
| `databricks/notebooks/train_obt_model.py` | `databricks/notebooks/train_turnaround_model.py` |
| `databricks/notebooks/evaluate_obt_model.py` | `databricks/notebooks/evaluate_turnaround_model.py` |
| `resources/obt_training_job.yml` | `resources/turnaround_training_job.yml` |
| `data/ml_models/obt_model.pkl` | `data/ml_models/turnaround_model.pkl` |
| `data/ml_models/obt_coarse_model.pkl` | `data/ml_models/turnaround_coarse_model.pkl` |

### Class/function renames (inside files)

| Old | New |
|-----|-----|
| `OBTFeatureSet` | `TurnaroundFeatureSet` |
| `OBTCoarseFeatureSet` | `TurnaroundCoarseFeatureSet` |
| `OBTBoardFeatureSet` | `TurnaroundBoardFeatureSet` |
| `OBTPrediction` | `TurnaroundPrediction` |
| `OBTPredictor` | `TurnaroundPredictor` |
| `OBTCoarsePredictor` | `TurnaroundCoarsePredictor` |
| `OBTBoardPredictor` | `TurnaroundBoardPredictor` |
| `OBTMultiHorizonPredictor` | `TurnaroundMultiHorizonPredictor` |
| `train_obt_model()` | `train_turnaround_model()` |
| `predict_obt()` | `predict_pushback_time()` |
| `predict_obt_t90()` | `predict_pushback_time_t90()` |
| `predict_obt_tpark()` | `predict_pushback_time_tpark()` |
| `fine_tune_obt()` | `fine_tune_turnaround()` |

### Files with import updates (no rename, just update imports)

- `src/ml/registry.py` — `from src.ml.turnaround_model import TurnaroundPredictor`
- `src/ml/training.py` — update imports + function name
- `src/ml/transfer_learning.py` — update imports + function name
- `src/ml/acdm_adapter.py` — update imports (feature classes)
- `src/inference/opensky_events.py` — update docstring reference
- `tests/test_ml_training_coverage.py` — update imports + function calls

### Docstring updates

- `turnaround_model.py` line 0: "Turnaround duration forecasting model. Predicts gate occupancy time (minutes from AIBT to AOBT)."
- `turnaround_features.py` line 1: "Feature extraction for turnaround duration prediction."
- `acdm_adapter.py` line 1: "A-CDM data adapter for turnaround duration model."
- `transfer_learning.py` line 0: "Transfer learning pipeline: fine-tune turnaround model on real A-CDM data."

## Part 2: Design True OBT Model (new model)

A true OBT (Off-Block Time) model predicts the absolute timestamp when an aircraft will push back — i.e., AOBT. This is a scheduling/planning model, not a duration model. The key difference:

- **Turnaround model** (existing, renamed): Given features at T-park, predict how long the aircraft will stay at the gate.
- **OBT model** (new): Given schedule + operational context, predict when the aircraft will actually push back (AOBT). Target = AOBT timestamp. Useful for airport CDM and slot management.

### Available data for true OBT

From simulation JSON and recorded data, we already have:

| Field | Source | Description |
|-------|--------|-------------|
| scheduled_time | schedule_generator.py | SOBT for departures |
| parked_time (AIBT) | phase_transitions | When aircraft actually parked |
| pushback_time (AOBT) | phase_transitions | When aircraft actually pushed back — this is the target |
| delay_minutes | schedule_generator.py | Schedule delay |
| estimated_time | schedule_generator.py | Estimated departure with delay |
| aircraft_type | schedule/phase_transitions | Aircraft category |
| airline_code | schedule | Airline |
| gate | gate_events | Gate assignment |
| origin/destination | schedule | Route |
| Weather | weather_snapshots | Wind, visibility at time of prediction |
| scenario_events | simulation | Ground stops, runway closures |
| concurrent_gate_ops | gate_events | Airport congestion |

### OBT model design

**Target:** `pushback_time` as Unix timestamp (AOBT). Or equivalently, `pushback_time - scheduled_departure_time` as departure delay in minutes (easier to learn, more transferable).

**Prediction horizons** (matching A-CDM milestones):
1. **T-schedule** (hours before): Only schedule + historical patterns available. Predict EOBT.
2. **T-arrival** (inbound): Flight is approaching, AIBT is imminent. Can incorporate arrival delay.
3. **T-park** (at gate): Aircraft parked, turnaround started. Can incorporate gate/congestion. Most accurate.

### Feature set (for T-park, the richest horizon)

```python
@dataclass
class OBTFeatureSet:
    # Schedule features
    scheduled_departure_time: float      # SOBT as Unix timestamp
    scheduled_turnaround_min: float      # SOBT - AIBT (buffer scheduled)
    departure_delay_so_far_min: float    # current_time - SOBT (negative = early)

    # Inbound features
    arrival_delay_min: float             # AIBT - SIBT
    aibt: float                          # Actual in-block time (Unix)

    # Aircraft/airline
    aircraft_category: str               # narrow/wide/regional
    airline_code: str                    # ICAO 3-letter
    is_international: bool
    is_hub_connecting: bool

    # Gate/airport
    gate_id_prefix: str
    is_remote_stand: bool
    concurrent_gate_ops: int
    airport_code: str

    # Temporal
    hour_of_day: int
    day_of_week: int
    hour_sin: float
    hour_cos: float

    # Environmental
    wind_speed_kt: float
    visibility_sm: float
    has_active_ground_stop: bool

    # Turnaround progress (when available at T-park+)
    elapsed_gate_time_min: float         # How long at gate so far
    turnaround_predicted_min: float      # From turnaround model
```

**Key insight:** The OBT model can USE the turnaround model's prediction as an input feature. The turnaround model predicts duration; the OBT model predicts the absolute time, incorporating schedule constraints, delay propagation, and operational factors that pure duration doesn't capture.

### New files

| File | Purpose |
|------|---------|
| `src/ml/obt_model.py` | OBTPredictor — true OBT prediction |
| `src/ml/obt_features.py` | OBTFeatureSet — features for OBT model |
| `tests/test_obt_model.py` | Tests for new OBT model |

### Implementation approach

1. First extract training data from existing simulation JSONs — the `pushback_time` from phase_transitions paired with schedule `scheduled_time` gives us (features, AOBT_target) pairs
2. Build a `extract_obt_training_data()` in `obt_features.py` that joins schedule + phase_transitions + gate_events + weather to produce OBT-specific feature vectors
3. The target is `departure_offset_min = (pushback_time - scheduled_departure_time).minutes` — predicting how many minutes early/late the actual pushback is relative to schedule
4. Build OBTPredictor with CatBoost/HGB, same pattern as turnaround model
5. At inference: `predicted_AOBT = SOBT + predicted_offset_minutes`

### Integration with existing turnaround model

The turnaround model's prediction feeds INTO the OBT model as a feature (`turnaround_predicted_min`). This creates a two-stage pipeline:
1. Turnaround model -> predicted duration
2. OBT model -> predicted pushback timestamp, informed by turnaround prediction + schedule + ops context

## Execution Order

1. Rename turnaround model (Part 1) — mechanical refactor, no logic changes
2. Create new OBT model skeleton (Part 2) — new files, feature extraction, predictor class
3. Wire OBT model into registry alongside turnaround model
4. Test both models independently

## Verification

```bash
# After Part 1 rename — all existing tests should pass with new names
uv run pytest tests/test_turnaround_model.py tests/test_turnaround_features_recorded.py tests/test_ml_training_coverage.py -v

# After Part 2 — new OBT model tests
uv run pytest tests/test_obt_model.py -v

# Full suite
uv run pytest tests/ -v -x --timeout=30
cd app/frontend && npm test -- --run
```

# OBT Model: Feature Selection, Training Rationale, and Improvement Plan

**Audience:** Data scientist evaluating/improving the OBT forecasting model
**Date:** 2026-03-16

---

## 1. What the Model Predicts

**Target variable:** `turnaround_duration_min` — elapsed minutes from aircraft parking (chocks on) to pushback (chocks off). This is the gate occupancy time.

**Why it matters:** Accurate turnaround prediction enables:
- Gate scheduling optimization (predict when a gate becomes free)
- Delay propagation forecasting (will the outbound flight depart on time?)
- CDM (Collaborative Decision Making) — providing TOBT (Target Off-Block Time) to ATC

**Current baseline:** Fixed constants from `gse_model.py` — 45 min narrow-body, 90 min wide-body. The model aims to beat this by learning airline-specific, weather-aware, congestion-sensitive patterns.

---

## 2. Two-Stage Architecture

The model uses two prediction horizons, following the A-CDM (Airport Collaborative Decision Making) framework used at 30+ European airports:

### Stage 1: T-90 Coarse Model (`OBTCoarsePredictor`)

- **When:** 90 minutes before scheduled departure (pre-arrival)
- **Available data:** Schedule, weather forecast, airline, aircraft type, inbound delay estimate
- **Not available:** Actual gate, actual parking time, gate congestion
- **Use case:** Early planning — CDM TOBT initial estimate, gate pre-assignment
- **Algorithm:** `HistGradientBoostingRegressor(max_depth=5, max_iter=150, lr=0.05)`
- **Expected MAE:** 8-12 min (literature baseline for pre-arrival prediction)

### Stage 2: T-park Refined Model (`OBTPredictor`)

- **When:** Aircraft has parked at gate (chocks on)
- **Available data:** Everything from T-90 + actual gate, parking hour, concurrent gate ops, remote stand flag
- **Use case:** Operational — refined TOBT for ATC sequencing
- **Algorithm:** `HistGradientBoostingRegressor(max_depth=6, max_iter=200, lr=0.05)`
- **Expected MAE:** 4-7 min (literature baseline for post-arrival prediction)

**Rationale for two stages:** Information availability changes dramatically between pre-arrival and post-parking. A single model either wastes gate-side features at T-90 (when unavailable) or underperforms at T-park by not using them. The A-CDM standard explicitly recommends progressive refinement.

---

## 3. Current Feature Set — Analysis

### T-park (Refined) Features — 12 total

| # | Feature | Type | Source | Rationale | Literature Support |
|---|---------|------|--------|-----------|-------------------|
| 1 | `aircraft_category` | cat: narrow/wide/regional | schedule -> aircraft_type | Wide-body ~2x longer (more pax, cargo, fuel). Maps B738->narrow, B777->wide, E190->regional | **Strong** — universally used, top predictor |
| 2 | `airline_code` | cat: 3-letter ICAO | schedule -> airline | Airlines have different SOPs. LCCs (25-35 min) vs legacy (45-90 min) | **Strong** — captures operational culture |
| 3 | `hour_of_day` | int 0-23 | parked_time.hour | Night ops fewer crew, morning banks have pressure for quick turns | **Strong** — universally included |
| 4 | `is_international` | bool | origin/destination heuristic | International: customs, longer deboarding, more catering (+15-30 min) | **Strong** — well-documented effect |
| 5 | `arrival_delay_min` | float | schedule -> delay_minutes | Delayed arrivals get expedited turnaround OR cause cascading delays | **Strong** — often top-3 predictor |
| 6 | `gate_id_prefix` | cat: first letter(s) | gate_events -> gate | Terminal area affects ground crew proximity, resource availability | **Moderate** — valid but noisy |
| 7 | `is_remote_stand` | bool | gate starts with "R" | Remote stands need bus ops, adding ~10 min | **Strong** — well-documented (+5-15 min) |
| 8 | `concurrent_gate_ops` | int | gate_events at parked_time | Proxy for ground crew contention / apron density | **Moderate-Strong** — congestion proxy |
| 9 | `wind_speed_kt` | float | nearest weather snapshot | High winds slow fueling and cargo loading | **Moderate** — secondary weather effect |
| 10 | `visibility_sm` | float | nearest weather snapshot | Low visibility may slow ramp operations | **Moderate** — indirect effect |
| 11 | `has_active_ground_stop` | bool | scenario_events overlap | Ground stops prevent pushback regardless of turnaround completion | **Moderate** — captures systemic disruption |
| 12 | `scheduled_departure_hour` | int 0-23 | schedule -> scheduled_time | Pressure to meet departure slot affects turnaround urgency | **Moderate** — partly redundant with hour_of_day |

### T-90 (Coarse) Features — 8 total

Subset of T-park features, excluding gate-side information: `aircraft_category`, `airline_code`, `scheduled_departure_hour`, `is_international`, `arrival_delay_min`, `wind_speed_kt`, `visibility_sm`, `has_active_ground_stop`.

---

## 4. Algorithm Choice — Rationale and Alternatives

### Current: `HistGradientBoostingRegressor` (scikit-learn)

**Why chosen:**
- Handles mixed categorical + numeric features natively via histogram binning
- No C-extension dependency (unlike LightGBM/XGBoost) — pure Python install
- Equivalent performance to LightGBM for datasets under 100K samples
- Built-in `OrdinalEncoder` + `ColumnTransformer` pipeline for reproducibility
- `handle_unknown="use_encoded_value"` handles unseen airline codes at inference

**Literature support:** Gradient boosting variants (XGBoost, LightGBM, CatBoost, HistGBR) consistently dominate turnaround prediction benchmarks from 2018 onward. Random Forest is a close second. Neural networks show no consistent advantage for tabular turnaround data at this scale.

### Hyperparameters

| Parameter | T-90 | T-park | Rationale |
|-----------|------|--------|-----------|
| `max_depth` | 5 | 6 | T-park has more features, can support deeper trees |
| `max_iter` | 150 | 200 | More boosting rounds for the richer feature set |
| `learning_rate` | 0.05 | 0.05 | Conservative step size to prevent overfitting |
| `random_state` | 42 | 42 | Reproducibility |

**Assessment:** These are reasonable defaults. The plan calls for 5-fold CV for hyperparameter tuning, which is appropriate for the dataset size (~40K samples from 132 sims).

### Alternatives to Consider

| Algorithm | Pros | Cons | Recommendation |
|-----------|------|------|----------------|
| **CatBoost** | Native categorical handling (no OrdinalEncoder needed), often best on mixed-type data | Extra dependency | **Consider** — eliminates encoding artifacts for `airline_code` (60+ categories) |
| **LightGBM** | Fastest training, DART mode for regularization | C-extension dependency | Optional — HistGBR is equivalent for this data size |
| **XGBoost** | GPU support, wide ecosystem | No advantage over HistGBR here | Skip |
| **Random Forest** | Better uncertainty estimation, simpler | 5-10% worse MAE typically | Skip |
| **Linear/Ridge** | Interpretable baseline | 20-40% worse MAE | Keep as baseline only |

---

## 5. Training Data Pipeline

### Data Flow

```
132 simulation JSONs (UC Volume, ~41.5GB)
  |
  v
extract_training_data() -- src/ml/obt_features.py
  |  Joins: schedule + phase_transitions + gate_events + weather_snapshots + scenario_events
  |  Filters: turnaround in [10, 180] minutes
  |  Links: flight_number (callsign) as join key
  v
~40K (features, target) pairs
  |
  v
80/20 stratified split by airport_code
  |
  v
T-90 coarse: full_features.to_coarse() -> train OBTCoarsePredictor
T-park refined: full_features -> train OBTPredictor
  |
  v
MLflow logging + UC Model Registry
```

### Join Logic (extract_training_data)

1. For each flight in schedule, find `to_phase == "parked"` transition -> `parked_time`
2. Find `from_phase == "parked", to_phase == "pushback"` transition -> `pushback_time`
3. `turnaround_duration = pushback_time - parked_time`
4. Match nearest weather snapshot to `parked_time`
5. Check if any ground stop was active during `[parked_time, pushback_time]`
6. Count concurrent gate occupants at `parked_time`

### Data Validation

- Turnaround bounds: [10, 180] minutes (outlier filter)
- Minimum 10 samples to train (otherwise fallback to GSE constants)
- Airport stratification in train/test split ensures all 33 airports represented

### Known Data Generation Mechanism

The simulation generates turnaround times via `fallback.py:2325-2340`:
```python
timing = get_turnaround_timing(state.aircraft_type)  # 45 or 90 min
gate_seconds = (total_min - non_gate_min) * 60
target = gate_seconds * random.uniform(0.8, 1.2)     # +/- 20% jitter
```

**Critical insight:** The target variable is essentially `{35 or 77} * uniform(0.8, 1.2)` minutes (after subtracting taxi/pushback phases). This means:
- The turnaround distribution is bimodal (narrow-body cluster + wide-body cluster)
- Each cluster has +/-20% uniform noise — no complex interactions actually exist in the data
- Weather, congestion, airline code, etc. do NOT affect the simulated turnaround duration
- The model can only learn `aircraft_category -> duration` plus noise

**This is the fundamental limitation of the current approach.** See Section 7 for improvements.

---

## 6. Challenges to Current Plan and Assumptions

### Challenge 1: The Target Variable Has No Feature Dependence (Beyond Aircraft Type)

**Issue:** The simulation generates turnaround = `base_time * uniform(0.8, 1.2)` where `base_time` depends only on narrow/wide classification. Weather, airline, congestion, gate type — none of these affect the simulated turnaround.

**Impact:** The model will learn that `aircraft_category` explains nearly all variance. All other features will have near-zero importance. The model won't truly beat the baseline of "predict mean turnaround by aircraft type" because there's no signal beyond that in the training data.

**Expected result:** The GBT model will achieve the same MAE as a simple per-category mean (~4-5 min, which is 20% of 35/77 min jitter), but the improvement over GSE constants (45/90 min) will be because it learns the correct post-taxi-subtraction values, not because it captures complex interactions.

### Challenge 2: International Flag Heuristic Is Unreliable

**Issue:** `_is_international_route()` uses `other[0] != airport_iata[0]` (first character comparison) as a proxy. This fails for:
- ORD -> OAK (both start with "O", flagged as domestic — correct for US, but by coincidence)
- LAX -> LHR (both start with "L", flagged as domestic — **wrong**)
- SFO -> SIN (different first letter, flagged as international — correct)

**Impact:** ~15-20% of international flights are mislabeled. The feature adds noise rather than signal.

### Challenge 3: Scheduled Departure Hour vs Hour of Day Redundancy

**Issue:** For departures created as PARKED, `hour_of_day` (parking hour) and `scheduled_departure_hour` are often the same or very close. For arrivals, they differ by roughly the turnaround duration. With 12 features and ~40K samples, this redundancy wastes model capacity.

**Impact:** Low — GBT handles redundant features well, but it slightly inflates feature importance for time-related features.

### Challenge 4: Gate Prefix Cardinality

**Issue:** `gate_id_prefix` extracts the alphabetic prefix (e.g., "A", "B", "T1"). With 33 airports each having different gate naming conventions, this creates a high-cardinality categorical with little consistency across airports.

**Impact:** The `OrdinalEncoder` assigns arbitrary ordinal values. The GBT may overfit to gate prefix ordinals that have no intrinsic ordering. CatBoost or target encoding would handle this better.

### Challenge 5: Confidence Scores Are Hardcoded

**Issue:**
- Fallback confidence: 0.3 (T-park), 0.2 (T-90)
- Trained confidence: 0.75 (T-park), 0.55 (T-90)

These are static values, not computed from prediction uncertainty. A data scientist would expect calibrated prediction intervals.

**Impact:** Downstream consumers of OBT predictions can't distinguish confident predictions from uncertain ones.

### Challenge 6: Synthetic-to-Real Gap

**Issue:** Models trained on synthetic data typically see 2-3x MAE increase on real operational data due to:
- Missing real-world complexity (crew constraints, maintenance surprises, passenger behavior)
- Heavy right-skewed real distributions vs more symmetric synthetic ones
- No regime switching (normal ops vs irregular ops)

**Impact:** The <5 min MAE target is achievable on synthetic test data but would likely be 10-15 min on real A-CDM data. This is acceptable for a demo/digital twin but should be documented.

---

## 7. Improvement Plan

### Tier 1: High Impact, Easy to Implement (Simulation Changes Required)

These require modifying the turnaround generation in `fallback.py` to make the target variable actually depend on features. Without these, the ML model is fundamentally limited to learning per-category means.

#### 1a. Weather-Dependent Turnaround Duration

**Current:** `turnaround = base * uniform(0.8, 1.2)` — weather has zero effect
**Proposed:** Multiply by a weather factor:

```python
# In fallback.py, PARKED phase (line 2339)
weather_factor = 1.0
if current_wind_speed > 35:    # High winds slow ramp ops
    weather_factor += 0.15
if current_visibility < 1.0:   # Low vis slows ground movement
    weather_factor += 0.10
if current_wind_speed > 50:    # Extreme: ramp closure risk
    weather_factor += 0.25
target = gate_seconds * random.uniform(0.8, 1.2) * weather_factor
```

**Expected impact:** Weather features become genuinely predictive. T-park MAE improvement: 0.5-1.5 min.

#### 1b. Airline-Specific Turnaround Multipliers

**Current:** All airlines same turnaround for same aircraft type
**Proposed:** Use calibration profile data to vary by airline:

```python
# LCCs are 15-20% faster, legacy carriers match baseline, some airlines are slower
airline_factor = profile.get_airline_turnaround_factor(airline_code)
# e.g., SWA=0.75, RYR=0.70, UAL=1.0, BAW=1.1, EK=1.15
target = gate_seconds * random.uniform(0.85, 1.15) * airline_factor
```

**Expected impact:** `airline_code` becomes a strong predictor. Estimated MAE improvement: 1-3 min.

#### 1c. Congestion-Dependent Turnaround

**Current:** Gate congestion has zero effect on turnaround
**Proposed:** More concurrent gate ops = longer turnaround (ground crew contention):

```python
congestion_factor = 1.0 + 0.01 * max(0, concurrent_gate_ops - 10)  # +1% per extra aircraft above 10
```

**Expected impact:** `concurrent_gate_ops` becomes predictive. Small but real effect.

#### 1d. International Flight Penalty

**Current:** International flag has zero effect on turnaround
**Proposed:** International flights get longer turnaround:

```python
intl_factor = 1.25 if is_international else 1.0  # +25% for customs, extra catering
```

**Expected impact:** `is_international` becomes genuinely predictive.

### Tier 2: Feature Engineering (No Simulation Changes)

These improve the model's ability to extract signal from existing data.

#### 2a. Add Day-of-Week Feature

**Rationale:** Weekend vs weekday patterns differ — leisure traffic on weekends has different turnaround characteristics. Friday evening and Sunday afternoon are peak connecting passenger times.

**Implementation:** Extract from `parked_time.weekday()` (0=Monday, 6=Sunday). Encode as cyclical: `sin(2*pi*dow/7)`, `cos(2*pi*dow/7)`.

#### 2b. Add Scenario Type Feature

**Rationale:** Weather vs normal-day runs have fundamentally different turnaround distributions. The model should know if it's a disrupted day.

**Implementation:** Extract from simulation config or filename: `scenario_type` = "normal" | "weather".

#### 2c. Fix International Detection

**Rationale:** Current first-character heuristic is unreliable.

**Implementation:** Use a country lookup table (from OurAirports data already available in `src/calibration/ourairports_ingest.py`) to determine if origin/destination countries differ.

#### 2d. Add Scheduled Buffer Time

**Rationale:** The literature identifies `scheduled_turnaround_time` (airline's planned buffer) as one of the strongest predictors. Airlines that schedule generous buffers almost always depart on time.

**Implementation:** `buffer_min = scheduled_departure_time - scheduled_arrival_time`. Available from schedule data for arrivals that have both fields.

#### 2e. Cyclical Time Encoding

**Rationale:** Hour 23 and hour 0 are adjacent but maximally distant in integer encoding.

**Implementation:** Replace `hour_of_day` with:
```python
hour_sin = sin(2 * pi * hour / 24)
hour_cos = cos(2 * pi * hour / 24)
```

### Tier 3: Algorithm and Pipeline Improvements

#### 3a. CatBoost for Native Categorical Handling

**Rationale:** `airline_code` has 60+ unique values, `gate_id_prefix` varies by airport. OrdinalEncoder assigns arbitrary ordinal values that imply a false ordering. CatBoost uses ordered target encoding internally.

**Implementation:** Replace HistGBR pipeline with CatBoost, pass `cat_features` parameter directly.

#### 3b. Quantile Regression for Prediction Intervals

**Rationale:** Current confidence scores are hardcoded (0.75, 0.55). A quantile regression model can output calibrated prediction intervals.

**Implementation:** Train three models: `quantile=0.1`, `quantile=0.5`, `quantile=0.9`. The [P10, P90] interval gives an 80% prediction band. Confidence = `1 / (P90 - P10)` normalized.

#### 3c. Per-Airport Models vs Global Model

**Rationale:** The current approach trains a single global model on all 33 airports. Airport-specific models could capture local patterns better (gate layout, crew practices, climate) but have less data per model (~1200 samples per airport).

**Recommended approach:** Keep global model as primary, but add `airport_code` as a categorical feature. The GBT can learn airport-specific splits naturally. A future enhancement could be hierarchical modeling (global + airport-specific residual model).

#### 3d. Cross-Validation Instead of Single Split

**Rationale:** The current 80/20 single split may produce unstable estimates, especially for airports with few samples.

**Implementation:** 5-fold CV stratified by airport, report mean +/- std MAE. Use the full dataset for final model training after CV evaluation.

### Tier 4: Long-Term / Real-Data Integration

#### 4a. Transfer Learning for Real Data

When real A-CDM data becomes available:
1. Pre-train on synthetic data (current approach)
2. Fine-tune on real data with lower learning rate
3. Track sim-to-real gap (Wasserstein distance between turnaround distributions)

#### 4b. Turnaround Process Milestone Features

The A-CDM framework defines 16 milestones. If the simulation emits sub-phase events (deboarding complete, fueling complete, boarding start), these become the most powerful predictors at T-park+N horizon.

#### 4c. Third Prediction Stage: T-board

Add prediction at boarding start (when boarding begins, turnaround is ~80% complete). Expected MAE: 2-4 min. Requires simulation to emit a boarding-start event.

---

## 8. Priority Recommendation

| Priority | Item | Effort | MAE Impact | Notes |
|----------|------|--------|------------|-------|
| **P0** | 1a-1d: Make turnaround depend on features | Medium | **3-5 min** | Without this, the ML model is fundamentally limited to per-category means. This is the single most important change. |
| **P1** | 2c: Fix international detection | Low | 0.3-0.5 min | Quick fix, improves data quality |
| **P1** | 2a: Add day-of-week | Low | 0.2-0.5 min | Easy feature addition |
| **P1** | 3d: Cross-validation | Low | Stability | Better evaluation, no MAE change |
| **P2** | 2d: Add scheduled buffer time | Low | 0.5-1.0 min | Strong literature support |
| **P2** | 2e: Cyclical time encoding | Low | 0.1-0.3 min | Clean engineering |
| **P2** | 3b: Quantile regression | Medium | Calibrated uncertainty | Important for production use |
| **P3** | 3a: CatBoost | Medium | 0.2-0.5 min | Better categorical handling |
| **P3** | 2b: Scenario type feature | Low | 0.3-0.5 min | Useful for weather runs |
| **P4** | 4a-c: Real data / milestones | High | 2-5 min | Long-term investment |

---

## 9. Expected Model Performance

### Current State (No Simulation Changes)

| Metric | Baseline (GSE) | T-90 Expected | T-park Expected |
|--------|-----------------|---------------|-----------------|
| MAE | ~8-12 min* | ~6-8 min | ~4-6 min |
| R^2 | 0 | 0.3-0.5 | 0.5-0.7 |
| Top feature | — | aircraft_category (~80%) | aircraft_category (~75%) |

*Baseline is high because GSE constants are 45/90 pre-taxi-subtraction, while actual turnaround is ~35/77 post-subtraction.

The model will appear to beat the baseline significantly, but mainly because it learns the correct post-subtraction values, not because it captures complex interactions.

### After Tier 1 Changes (Feature-Dependent Turnarounds)

| Metric | Baseline (GSE) | T-90 Expected | T-park Expected |
|--------|-----------------|---------------|-----------------|
| MAE | ~10-15 min | ~7-10 min | ~3-5 min |
| R^2 | 0 | 0.4-0.6 | 0.6-0.8 |
| Top features | — | aircraft_cat, airline, weather | aircraft_cat, airline, weather, congestion |

The model genuinely captures multi-feature interactions, producing meaningfully better predictions than simple baselines.

---

## 10. References

- **Eurocontrol A-CDM Implementation Manual** — Defines TOBT, TSAT, AOBT milestones and multi-horizon prediction framework
- **Eurocontrol CODA Digest** — Annual delay statistics; ~45% of delays are reactionary (previous-leg propagation)
- **Schultz, M. (2018), DLR** — Turnaround simulation and prediction using aircraft type, airline, stand type
- **Katsigiannis et al. (2021)** — AOBT prediction with milestone data, deep learning comparison with GBT
- **SESAR PJ.04 "Total Airport Management"** — Multi-horizon TOBT prediction with A-CDM data
- **Diana, T. (2014)** — Early ML application for turnaround prediction (Random Forest vs regression)
- **IATA Airport Handling Manual** — Industry standard minimum turnaround times by aircraft category
- **Evler et al. (2021, DLR)** — Turnaround as part of disruption management, buffer time analysis

# Plan: OBT Model — 8 Improvements (P1 to P4)

## Context

The OBT forecasting model is trained and deployed (T-park MAE 4.55 min, R^2 0.91 on calibrated data). The user's improvement roadmap lists 8 enhancements from P1 (quick wins) to P4 (aspirational). Several are already partially implemented; this plan covers what remains and how to execute each.

---

## Status of Each Improvement

| #  | Improvement                    | Status      | What's Done                                           | What's Needed                                              |
|----|--------------------------------|-------------|-------------------------------------------------------|------------------------------------------------------------|
| 1  | Day-of-week variation in sim   | Partial     | day_of_week feature in OBTFeatureSet; cyclical encoding | Simulation runs are 24h single-day -- no day variation in training data |
| 2  | International detection via OurAirports | Partial | _AIRPORT_COUNTRY dict in obt_features.py (34 airports) | Use ourairports_ingest.py for full 60K+ airport coverage |
| 3  | Scheduled buffer time feature  | Not started | --                                                    | Add scheduled_buffer_min = (scheduled_departure - actual_arrival) to features |
| 4  | Switch to CatBoost             | Not started | --                                                    | Replace HistGradientBoostingRegressor with CatBoostRegressor |
| 5  | Conformalized Quantile Regression (CQR) | Partial | P10/P90 quantile models exist                  | Need calibration set + conformal correction for guaranteed coverage |
| 6  | Multi-day simulations (7d x 33 airports) | Not started | 33 known profiles exist; 10 sim configs     | New configs, multi-day support in sim, Databricks job |
| 7  | T-board prediction stage       | Not started | --                                                    | New stage between T-park and pushback |
| 8  | Transfer learning to real A-CDM data | Not started | A-CDM references in 12 files               | Domain adaptation pipeline |

---

## P1 -- Quick Wins (Low effort, immediate value)

### 1. Day-of-Week Variation in Simulation

**Problem:** All simulations are 24-hour single-day runs (duration_hours: 24 in YAML configs). The day_of_week feature exists but always reflects the same day within each sim file. The model can't learn weekend vs weekday patterns.

**Solution:** Modify simulation configs and schedule generator to support multi-day awareness.

**Files to modify:**
- `src/ingestion/schedule_generator.py` -- Add start_date parameter to generate_schedule(). Use it to set day_of_week on each flight. Apply day-of-week modifiers: reduce weekend traffic by ~15-20%, shift peak hours.
- `configs/simulation_*_1000.yaml` -- Add start_date: "2025-06-16" (Monday) so each airport sim starts on a known weekday. For multi-day runs (P3), this becomes the anchor date.
- `src/simulation/engine.py` -- Pass start_date from config to schedule generator.

**Day-of-week effects to inject (in schedule_generator.py):**
- Weekday (Mon-Fri): baseline traffic
- Saturday: -15% departures, -10% arrivals, shift morning peak later by 1h
- Sunday: -10% departures, +5% evening redeye traffic

**Turnaround variation (in fallback.py):**
- Weekend: +5% turnaround time (fewer ground crew), multiply existing combined_factor

**Verification:** Run sim for Monday vs Saturday, confirm different flight counts and mean turnaround.

### 2. Fix International Detection with OurAirports Country Data

**Problem:** `_AIRPORT_COUNTRY` in obt_features.py has only 34 hardcoded airports. Any unknown airport pair returns is_international=False.

**Solution:** Use `src/calibration/ourairports_ingest.py:parse_airports_csv()` which already parses the full OurAirports dataset with country field per airport.

**Files to modify:**
- `src/ml/obt_features.py` -- Replace _AIRPORT_COUNTRY dict with a function that:
  a. Tries the OurAirports CSV lookup (ICAO->country via parse_airports_csv())
  b. Falls back to the existing hardcoded dict for environments without the CSV
  c. Cache the parsed result (module-level singleton, lazy-loaded)
- Need to handle IATA<->ICAO mapping (sim uses IATA like "SFO", OurAirports keys on ICAO like "KSFO"). The CSV includes both ident (ICAO) and iata_code fields -- build a reverse lookup iata -> country.

**OurAirports CSV location:** User needs to download airports.csv from ourairports.com/data/ to data/calibration/airports.csv (or we can auto-download in the loading function).

**Verification:** `_is_international_route("SFO", "NRT", "SFO")` -> True (US->JP). `_is_international_route("SFO", "LAX", "SFO")` -> False.

---

## P2 -- Model Quality Improvements (Medium effort)

### 3. Add Scheduled Buffer Time Feature

**Problem:** Airlines schedule buffer time between arrival and departure (SOBT - SIBT). This "scheduled turnaround" is a strong predictor -- flights with tight buffers get expedited turnaround, while long buffers allow leisurely ops.

**What it is:** `scheduled_buffer_min = scheduled_departure_time - actual_arrival_time` (or scheduled_arrival_time). This is available at T-park (when we know actual arrival time) and partially at T-90 (from schedule alone: SOBT - SIBT).

**Files to modify:**
- `src/ml/obt_features.py`:
  - Add `scheduled_buffer_min: float` to both OBTFeatureSet (T-park: uses actual arrival time) and OBTCoarseFeatureSet (T-90: uses scheduled times only)
  - In `extract_training_data()`: compute from scheduled_time (departure) minus parked_time (actual arrival) for T-park, and from schedule-only times for T-90
- `src/ml/obt_model.py`:
  - Add "scheduled_buffer_min" to ALL_FEATURE_NAMES and ALL_COARSE_FEATURE_NAMES
  - Update `_encode_features()` to include the new numeric feature
- `tests/test_obt_model.py`:
  - Update `_V2_DEFAULTS` and `_make_full_fs()` / `_make_coarse_fs()` helpers
  - Add tests verifying buffer time extraction

**Data source:** The simulation schedule has scheduled_time (departure) per flight. The parked_time comes from phase transitions. Buffer = scheduled_time - parked_time in minutes.

**Expected impact:** +0.5-1.0 min MAE improvement. This feature captures airline scheduling practices directly.

### 4. Switch to CatBoost for Native Categorical Handling

**Problem:** Current pipeline uses OrdinalEncoder + HistGradientBoostingRegressor. The ordinal encoding imposes arbitrary ordering on categoricals (airline_code, airport_code, gate_id_prefix, aircraft_category). CatBoost handles categoricals natively with ordered target statistics.

**Files to modify:**
- `pyproject.toml` -- Add catboost>=1.2 to dependencies
- `src/ml/obt_model.py`:
  - Replace `_build_pipeline()` to use CatBoostRegressor instead of sklearn pipeline
  - CatBoost takes cat_features parameter (indices of categorical columns) -- no encoder needed
  - Keep HistGradientBoostingRegressor as fallback if catboost import fails
  - Update quantile models: CatBoost supports `loss_function='Quantile:alpha=0.1'`
  - Remove OrdinalEncoder from pipeline (or keep for sklearn fallback)
- `databricks/notebooks/train_obt_model.py` -- Update environment deps
- `resources/obt_training_job.yml` -- Add catboost to environment dependencies
- `resources/simulation_batch_job.yml` -- Add catboost to sim_env dependencies
- `tests/test_obt_model.py` -- Add CatBoost-specific tests, verify categorical handling

**CatBoost hyperparameters:**
```python
CatBoostRegressor(
    iterations=500,
    depth=6,
    learning_rate=0.05,
    cat_features=[0, 1, 5, 12],  # aircraft_category, airline_code, gate_id_prefix, airport_code
    verbose=0,
    loss_function='RMSE',
)
```

**Migration strategy:** Train both sklearn and CatBoost, compare MAE. If CatBoost wins, make it primary with sklearn fallback. Log both to MLflow for comparison.

### 5. Conformalized Quantile Regression (CQR)

**Problem:** Current P10/P90 quantile models provide prediction intervals but aren't calibrated -- actual coverage may differ from nominal 80%.

**Solution:** Apply conformal correction using a held-out calibration set.

**Algorithm:**
1. Train quantile models (P10, P90) on training set -- already done
2. Hold out a calibration set (15% of data, separate from test set)
3. Compute nonconformity scores on calibration set: `s_i = max(q_lo - y_i, y_i - q_hi)` for each calibration point
4. Find the `(1-alpha)(1 + 1/n)`-quantile of scores -> Q_hat
5. At prediction time: adjusted interval = `[q_lo - Q_hat, q_hi + Q_hat]`

**Files to modify:**
- `src/ml/obt_model.py`:
  - Add `_calibration_offset` attribute to both predictor classes
  - Add `calibrate(X_cal, y_cal)` method that computes conformal correction
  - Update `predict()` to apply correction: lower -= offset, upper += offset
  - Update `train()` to split off calibration set and auto-calibrate
- `tests/test_obt_model.py`:
  - Test that coverage on test set is >= 80% after calibration
  - Test that calibration offset is non-negative

**Expected impact:** Guaranteed 80% coverage on exchangeable data. Slightly wider intervals but honest uncertainty.

---

## P3 -- Data Scale (High effort, high impact)

### 6. Multi-Day Simulations (7 days x 33 airports)

**Problem:** Current data is 10 airports x 1 day x 1000 flights = ~4K samples. Multi-day runs would capture day-of-week variation, delay propagation across days, and more diverse weather.

**Approach:**
1. Extend simulation engine to support multi-day runs
2. Generate 33 airport configs (all airports with known calibration profiles)
3. Run 7-day simulations on Databricks (33 airports x 7 days x ~1000 flights/day = ~231K samples)

**Files to create/modify:**
- `configs/simulation_*_7day.yaml` -- 33 new configs with duration_hours: 168 (7 days), start_date field
- `scripts/generate_sim_configs.py` -- Script to generate all 33 configs from known profiles
- `src/simulation/engine.py` -- Handle multi-day: advance sim_time across midnight, regenerate daily schedules
- `src/ingestion/schedule_generator.py` -- Support start_date + num_days parameters, generate flights for multiple days with day-of-week variation
- `resources/simulation_batch_job.yml` -- Update to 33 parallel tasks (or batch in groups of 10)
- `resources/obt_training_job.yml` -- Update dependencies for 33-airport runs

**Databricks resource considerations:**
- 33 parallel notebook tasks on serverless compute
- Each 7-day sim produces ~50-100MB JSON -> ~3GB total in UC Volume
- Training on 231K samples still fast with CatBoost (~30s)

**Verification:** After running, verify all 33 airports have 7 days of data, day_of_week distribution is [0-6], total samples ~200K+.

### 7. T-board Prediction Stage (at boarding start)

**Problem:** Current two stages: T-90 (coarse, pre-arrival) and T-park (refined, at gate). Adding a T-board stage when boarding starts would give a more accurate final prediction 15-30 min before pushback.

**What triggers T-board:** The GSE model defines boarding as a distinct turnaround phase (see gse_model.py:TURNAROUND_TIMING["narrow_body"]["phases"]["boarding"] = 15). In simulation, this isn't explicitly tracked as a phase transition -- the sim uses PARKED as a single phase with time-based turnaround.

**Approach:** Since simulation doesn't emit a boarding event, we need to either:
- (A) Infer boarding start from elapsed time at gate: boarding starts after cleaning+catering complete (~60-70% through turnaround for narrow-body)
- (B) Add boarding phase to simulation as an explicit phase transition between PARKED and PUSHBACK

**Recommended: Option A (simpler, no sim changes needed):**
- At inference time, when time_at_gate > 70% of predicted turnaround, switch to T-board model
- T-board features = T-park features + elapsed_gate_time_min + remaining_predicted_min + turnaround_progress_pct

**Files to create/modify:**
- `src/ml/obt_features.py` -- Add OBTBoardFeatureSet dataclass extending OBTFeatureSet with gate elapsed time fields
- `src/ml/obt_model.py` -- Add OBTBoardPredictor class (third model). Train on samples where we know the actual elapsed time at a point ~70% through.
- `src/ml/registry.py` -- Register obt_board model
- `tests/test_obt_model.py` -- Tests for T-board stage

**Expected impact:** MAE 2-4 min (vs 4.5 min for T-park). Most useful for gate scheduling and passenger information displays.

---

## P4 -- Aspirational (Research-grade)

### 8. Transfer Learning to Real A-CDM Data

**Problem:** Model trained on synthetic simulation data. Real A-CDM (Airport Collaborative Decision Making) data has different distributions -- actual airline behaviors, real weather impacts, irregular operations.

**Approach: Domain adaptation in two phases:**

**Phase A -- Feature alignment:**
- Map A-CDM fields to existing OBT feature set (EOBT, TOBT, SOBT timestamps -> features)
- A-CDM data typically has: AIBT (actual in-block), AOBT (actual off-block), SOBT (scheduled off-block), airline, aircraft type, gate, weather
- Create `src/ml/acdm_adapter.py` that converts A-CDM records to OBTFeatureSet

**Phase B -- Fine-tuning:**
- Start from synthetic-trained model weights (CatBoost supports init_model)
- Fine-tune on A-CDM data with lower learning rate
- Use MLflow to compare synthetic-only vs fine-tuned performance
- Apply domain-specific calibration: re-run CQR on real data

**Files to create:**
- `src/ml/acdm_adapter.py` -- A-CDM data -> OBTFeatureSet converter
- `src/ml/transfer_learning.py` -- Fine-tuning pipeline
- `databricks/notebooks/finetune_obt_acdm.py` -- Databricks notebook for fine-tuning with real data

**Data sources:** EUROCONTROL A-CDM data (if available), or airport-specific AODB exports. This improvement depends on access to real operational data.

**Verification:** Compare MAE on real data: synthetic-only model vs fine-tuned model. Target: fine-tuned MAE < 3 min on real data.

---

## Implementation Order

```
P1.1  Day-of-week in simulation  --+
P1.2  OurAirports intl detection --+-- Quick wins (do first)
                                    |
P2.3  Buffer time feature ----------+-- Model improvements (do together)
P2.4  CatBoost switch --------------+
P2.5  CQR calibration -------------+

P3.6  Multi-day sims --------------- Needs P1.1 first (day-of-week variation)
P3.7  T-board stage ---------------- Independent, can start anytime

P4.8  A-CDM transfer learning ----- Future, needs real data access
```

## Files Summary

| File                                      | Action | Improvements                                               |
|-------------------------------------------|--------|------------------------------------------------------------|
| src/ml/obt_features.py                    | Modify | #2 (OurAirports), #3 (buffer), #7 (T-board features)      |
| src/ml/obt_model.py                       | Modify | #3 (buffer feature), #4 (CatBoost), #5 (CQR), #7 (T-board predictor) |
| src/ingestion/schedule_generator.py       | Modify | #1 (day-of-week traffic variation)                         |
| src/ingestion/fallback.py                 | Modify | #1 (weekend turnaround factor)                             |
| src/simulation/engine.py                  | Modify | #1 (pass start_date), #6 (multi-day)                      |
| configs/simulation_*_1000.yaml            | Modify | #1 (add start_date)                                       |
| pyproject.toml                            | Modify | #4 (add catboost)                                         |
| resources/obt_training_job.yml            | Modify | #4 (catboost dep), #6 (33 airports)                       |
| resources/simulation_batch_job.yml        | Modify | #4 (catboost dep), #6 (33 airports)                       |
| databricks/notebooks/train_obt_model.py   | Modify | #4 (CatBoost), #5 (CQR), #7 (T-board)                    |
| tests/test_obt_model.py                   | Modify | All improvements                                          |
| scripts/generate_sim_configs.py           | Create | #6 (generate 33 configs)                                  |
| src/ml/acdm_adapter.py                    | Create | #8 (A-CDM adapter)                                        |
| src/ml/transfer_learning.py               | Create | #8 (fine-tuning)                                          |

## Verification

After each priority tier:

**After P1:**
```bash
# Verify day-of-week variation
uv run python -c "from src.ingestion.schedule_generator import generate_schedule; ..."
# Verify international detection
uv run pytest tests/test_obt_model.py -k "international" -v
```

**After P2:**
```bash
# Retrain with new features + CatBoost
uv run python scripts/train_obt_model.py
# Verify CQR coverage
uv run pytest tests/test_obt_model.py -k "calibrat" -v
# Full test suite
uv run pytest tests/test_obt_model.py -v
```

**After P3:**
```bash
# Deploy 33-airport batch job
databricks bundle deploy --target dev
databricks bundle run simulation_batch --target dev
# Retrain on expanded data
databricks bundle run obt_training --target dev
```

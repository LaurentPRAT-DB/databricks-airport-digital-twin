# ML Models in Airport Digital Twin

## Model Registry (src/ml/registry.py)

All models are managed by `AirportModelRegistry` — a per-airport cache that creates model instances on first access. When a calibrated `AirportProfile` exists (from BTS/OpenSky/OurAirports data), it's passed to model constructors for data-driven priors. Models can optionally be registered to Unity Catalog via MLflow.

---

## 1. Delay Predictor (src/ml/delay_model.py)

| | |
|---|---|
| **Class** | `DelayPredictor` |
| **Predicts** | Flight delay in minutes + confidence + category (on_time/slight/moderate/severe) |
| **Type** | Rule-based heuristic (not trained ML) |
| **Input features** | `FeatureSet`: hour_of_day, day_of_week, is_weekend, altitude_category (ground/low/cruise), velocity_normalized, heading_quadrant, flight_distance_category |
| **Data source** | Live flight state dicts (altitude, velocity, heading, timestamp) |
| **Calibration** | `AirportProfile.delay_rate` and `mean_delay_minutes` scale the base delay magnitude |
| **Logic** | Peak hours (7-9am, 5-7pm) add delay; weekends reduce it; ground aircraft get more delay; slow aircraft penalized; random noise for realism |

---

## 2. Congestion Predictor (src/ml/congestion_model.py)

| | |
|---|---|
| **Class** | `CongestionPredictor` |
| **Predicts** | Per-area congestion level (LOW/MODERATE/HIGH/CRITICAL) + wait time + confidence for each airport zone |
| **Type** | Rule-based (capacity ratio thresholds) |
| **Input** | List of current flight dicts (lat, lon, altitude, velocity, on_ground) |
| **Areas** | Built dynamically from OSM data (runways, taxiways, aprons) with SFO hardcoded fallback |
| **Logic** | Counts flights in each area's bounding box, computes occupancy ratio vs. capacity. Thresholds: <50% LOW, 50-75% MODERATE, 75-90% HIGH, >90% CRITICAL |
| **Calibration** | `AirportProfile.hourly_profile` scales capacity by time of day (peak hours get up to 1.5x) |

---

## 3. Gate Recommender (src/ml/gate_model.py)

| | |
|---|---|
| **Class** | `GateRecommender` |
| **Predicts** | Top-K gate recommendations with score (0-1), reasons, and estimated taxi time |
| **Type** | Multi-factor scoring model (not trained ML) |
| **Input** | Flight dict (callsign, aircraft_type, delay_minutes) |
| **Scoring factors** | Availability (40%), Operator match (20%), Terminal type match (15%), Aircraft size compatibility (15%), Proximity to runway (10%) |
| **Data sources** | OSM gate data (positions, terminals, operators), runway coords, airline-terminal affinity heuristics |
| **Calibration** | `AirportProfile.airline_shares` for operator affinity when no OSM operator data exists |
| **Taxi time** | Haversine distance from gate to runway / 15kts, with per-terminal routing multipliers |

---

## 4. OBT Predictor — T-park (src/ml/obt_model.py:OBTPredictor)

| | |
|---|---|
| **Class** | `OBTPredictor` |
| **Predicts** | Turnaround duration in minutes (time at gate from parking to pushback) with P10/P90 confidence intervals |
| **Type** | Trained ML — CatBoost (preferred) or sklearn HistGradientBoostingRegressor |
| **Target** | turnaround_minutes (parked → pushback) |
| **Features (18)** | **Numeric (10):** hour_of_day, arrival_delay_min, concurrent_gate_ops, wind_speed_kt, visibility_sm, scheduled_departure_hour, day_of_week, hour_sin, hour_cos, scheduled_buffer_min |
| | **Categorical (4):** aircraft_category (narrow/wide/regional), airline_code, gate_id_prefix, airport_code |
| | **Binary (4):** is_international, is_remote_stand, has_active_ground_stop, is_weather_scenario |
| **Training data** | Simulation JSON files containing schedule, phase_transitions, gate_events, weather_snapshots, scenario_events — joined by `obt_features.extract_training_data()` |
| **Quantiles** | Trains P10 and P90 quantile models for prediction intervals, with CQR (Conformalized Quantile Regression) calibration |
| **Fallback** | 45 min (narrow), 90 min (wide), 35 min (regional) — from GSE model constants |
| **Persistence** | Pickle save/load |

---

## 5. OBT Coarse Predictor — T-90 (src/ml/obt_model.py:OBTCoarsePredictor)

| | |
|---|---|
| **Class** | `OBTCoarsePredictor` |
| **Predicts** | Same as OBT T-park but with lower accuracy, available 90 min before departure |
| **Type** | Trained ML — same architecture (CatBoost/sklearn GBT) |
| **Features (14)** | Subset of T-park: drops gate_id_prefix, is_remote_stand, concurrent_gate_ops, hour_of_day (gate-side features not yet known at T-90) |
| **Use case** | Pre-arrival planning estimates when the aircraft hasn't parked yet |

---

## 6. OBT Board Predictor — T-board (src/ml/obt_model.py:OBTBoardPredictor)

| | |
|---|---|
| **Class** | `OBTBoardPredictor` |
| **Predicts** | Remaining turnaround time once ~70% of predicted turnaround has elapsed |
| **Type** | Trained ML — CatBoost/sklearn GBT |
| **Features (21)** | All 18 T-park features + elapsed_gate_time_min, remaining_predicted_min, turnaround_progress_pct |
| **Use case** | Late-stage refinement at boarding start — highest accuracy since actual elapsed time is known |

---

## 7. Two-Stage OBT Predictor (src/ml/obt_model.py:TwoStageOBTPredictor)

Orchestrator that wraps `OBTCoarsePredictor` (T-90) + `OBTPredictor` (T-park). Trains both from the same labeled data, auto-projecting full features down to coarse features.

---

## 8. GSE Model (src/ml/gse_model.py)

| | |
|---|---|
| **Predicts** | GSE (Ground Support Equipment) requirements, turnaround phase timing, fleet status |
| **Type** | Lookup tables + deterministic calculations (not ML) |
| **Data** | Hardcoded per-aircraft-type GSE requirements (pushback tugs, fuel trucks, belt loaders, etc.) and turnaround phase timing (narrow: 45min total, wide: 90min) |
| **Outputs** | Current turnaround phase + progress %, GSE unit positions, fleet inventory scaled by gate count |

---

## 9. Transfer Learning (src/ml/transfer_learning.py)

Fine-tunes a simulation-trained OBT model on real A-CDM (Airport Collaborative Decision Making) operational data using lower learning rate + CatBoost `init_model` warm-starting.

## 10. A-CDM Adapter (src/ml/acdm_adapter.py)

Maps real A-CDM milestones (AIBT, AOBT, SOBT, TOBT, EOBT) to `OBTFeatureSet` for transfer learning. This is the bridge from real operational data to the simulation-trained model.

---

## Summary Table

| Model | Type | Trained? | Training Data | Key Output |
|-------|------|----------|---------------|------------|
| Delay | Rule-based heuristic | No | N/A (calibrated by profile) | delay_minutes, confidence, category |
| Congestion | Capacity-ratio rules | No | N/A (OSM areas + live flights) | per-area congestion level + wait time |
| Gate | Multi-factor scoring | No | N/A (OSM gates + heuristics) | top-K gate recommendations + taxi time |
| OBT T-park | CatBoost/GBT | Yes | Simulation JSONs (phase transitions) | turnaround minutes + P10/P90 |
| OBT T-90 | CatBoost/GBT | Yes | Same sims (coarse feature subset) | early turnaround estimate |
| OBT T-board | CatBoost/GBT | Yes | Same sims (+ elapsed time features) | remaining time at boarding |
| GSE | Lookup tables | No | Hardcoded per aircraft type | turnaround phases, GSE positions |
| Transfer | CatBoost fine-tune | Yes | Real A-CDM records | refined OBT from real ops data |

The only truly trained ML models are the OBT family (T-90, T-park, T-board) using gradient-boosted trees on simulation data, with optional fine-tuning on real A-CDM data. The delay, congestion, and gate models are rule-based/heuristic but calibrated by `AirportProfile` real-data priors.

# Paper Analysis: ML for Predicting Off-Block Delays at CDG

**Source:** Falque, Mazure, Tabia — *Data & Knowledge Engineering* 152 (2024) 102303
**Title:** Machine learning for predicting off-block delays: A case study at Paris -- Charles de Gaulle International Airport

## Paper Summary

Real-world study at Paris-CDG (720K flights/year, Air France hub) predicting off-block delay (AOBT - SOBT) using LightGBM on 1 year of operational data (10.6M rows, 31 columns). Two tasks: day-ahead forecast (static features) and real-time prediction (dynamic features updated every 5 minutes across 60 slots from -2h30 to +2h30 relative to SOBT).

### Their Results

| Task | R^2 | MAE | Notes |
|------|-----|-----|-------|
| Forecast (day-ahead, static only) | ~0.1 | ~16 min | Very poor -- confirms static features alone are insufficient |
| Real-time (all features) | ~0.75 | ~7-8 min | Good -- dynamic features are critical |
| Real-time at 60 min before departure | -- | ~3 min | Excellent -- prediction improves dramatically closer to event |
| Baseline (predict mean delay) | -- | ~17 min | Naive model |

### Their Feature Categories

1. **BFF (Basic Flight Features):** airline, aircraft type, destination, terminal, customs type, season, week index, day-of-week, bus access, same-parking flag, SOBT, rotation duration, pax count, pif passengers, service type
2. **OMF (Off-Block Milestone Features):** arrival delay, TOBT_diff (TOBT - SOBT), TOBT_count (number of TOBT updates), CTOT_diff, TSAT_diff
3. **PCFDF (Previous/Current Flight Delay Features):** mean delay at airport/terminal/airline level, % delayed flights at airport/terminal/airline level -- computed over a sliding time window (10-60 min)
4. **WCF (Weather Condition Features):** low visibility procedures (boolean), humidity %, wind speed, air pressure, temperature
5. **PFF (Passenger Flow Features):** security checkpoint progression %, boarding progression %

### Their Key Findings

- TSAT_diff (time between TSAT and SOBT) is the strongest single feature (Pearson 0.74 at slot 30)
- TOBT_count (number of target off-block time revisions) is 2nd strongest (Pearson 0.33)
- Rolling delay context (PCFDF) adds significant value vs static features alone
- Optimal time window for PCFDF computation: 60 minutes
- 12 months of training history performs best (vs 3/6/9 months)
- LightGBM matches or beats LSTM while being vastly faster to train
- Boarding progression becomes increasingly important at later time slots (SHAP analysis)
- Strike days cause catastrophic prediction failure (Sept 16 MAE jumped to 31 min)

---

## Comparison with Our OBT Model v2

### What they predict vs what we predict

| Aspect | CDG Paper | Our Model v2 |
|--------|-----------|--------------|
| Target variable | Off-block delay (AOBT - SOBT) | Turnaround duration (pushback - parked) |
| Data source | Real CDG operational data (1 year) | Synthetic simulation data (132 calibrated sims) |
| Scale | 10.6M rows, single airport | ~4K samples, 33 airports |
| Algorithm | LightGBM (75 trees, 256 leaves, lr=0.05) | HistGradientBoostingRegressor (200 trees, depth 6, lr=0.05) |
| Architecture | Single model, 60-slot rolling prediction | Two-stage: T-90 (coarse) + T-park (refined) |
| Best MAE | ~7 min (real-time), ~3 min (60 min before) | 4.55 min (T-park on calibrated sim data) |

### Features: Gap Analysis

| Feature Category | CDG Paper | Our Model v2 | Gap |
|-----------------|-----------|--------------|-----|
| Aircraft type/category | Yes | Yes | -- |
| Airline code | Yes | Yes | -- |
| Destination/origin | Yes (destination IATA) | Yes (airport_code, is_international) | -- |
| Terminal/gate | Yes (terminal) | Yes (gate_id_prefix) | -- |
| Day-of-week | Yes (day 1-7) | Yes (day_of_week + cyclical encoding) | We're better (cyclical) |
| Time-of-day | Yes (SOBT as minutes since midnight) | Yes (hour_of_day + hour_sin/cos) | We're better (cyclical) |
| Arrival delay | Yes | Yes (arrival_delay_min) | -- |
| Weather | Yes (wind, visibility, humidity, pressure, temp, LVP flag) | Partial (wind, visibility only) | **Missing: humidity, pressure, temperature** |
| Concurrent ops / congestion | No (indirectly via PCFDF) | Yes (concurrent_gate_ops) | -- |
| **Rolling delay context** | **Yes (PCFDF: 6 features)** | **No** | **MAJOR GAP** |
| **Milestone revision count** | **Yes (TOBT_count)** | **No** | **Gap -- no analog in sim** |
| **Passenger flow** | **Yes (boarding %, security %)** | **No** | **Gap -- sim doesn't model passengers** |
| TOBT/TSAT/CTOT milestones | Yes (strongest features) | No | Gap -- CDM-specific, not in sim |
| Rotation duration | Yes | No | **Valuable -- time between inbound arrival and scheduled departure** |
| Pax count | Yes | No | Gap -- sim doesn't track passenger counts |
| Bus access flag | Yes | No | Minor -- CDG-specific |
| Season (summer/winter) | Yes | Yes (is_weather_scenario) | Different encoding |
| Prediction intervals | No | Yes (P10/P90 quantile regression) | We're better |
| Multi-airport | No (CDG only) | Yes (33 airports) | We're better |
| SHAP explainability | Yes | No | Gap |

### What we do better

1. **Multi-airport generalization** -- they train only on CDG; we generalize across 33 airports
2. **Prediction intervals** -- P10/P90 quantile regression with CQR planned; they only do point predictions
3. **Cyclical time encoding** -- sin/cos for hour and day-of-week; they use raw integers
4. **Feature-dependent simulation** -- airline/weather/congestion/intl turnaround factors give meaningful signal
5. **Two-stage architecture** -- explicit T-90 vs T-park with different feature sets per horizon

### What they do better

1. **Rolling delay context (PCFDF)** -- captures cascading delay effects; our model has no awareness of "how late is the airport running right now"
2. **Real operational data** -- 1 year, 720K flights; our data is synthetic
3. **5-minute rolling re-prediction** -- updates prediction 60 times during turnaround; we predict once at T-90 and once at T-park
4. **SHAP explainability** -- feature importance analysis with SHAP values per sample
5. **Richer weather** -- humidity, pressure, temperature, LVP flag; we only use wind + visibility
6. **Passenger flow tracking** -- boarding and security progression as dynamic features

---

## Concrete Actions for Our Model

### HIGH Priority (directly actionable)

| # | Action | Paper Source | Impact | Implementation |
|---|--------|-------------|--------|----------------|
| 1 | **Add rolling delay context features** | PCFDF (Table 3) | High -- captures cascading delays | Compute mean turnaround deviation and % overrun flights over sliding 60-min window during simulation. Add `mean_recent_delay_min` and `pct_recent_delayed` to both feature sets. |
| 2 | **Add SHAP explainability** | Section 9, Figs 6-7 | Medium -- operational insight | CatBoost (Phase 33 #4) has native SHAP. Add SHAP summary plot to training notebook. |
| 3 | **Add rotation duration / scheduled buffer feature** | BFF "Rotation" feature | High -- already in Phase 33 #3 | `scheduled_buffer_min = scheduled_departure - parked_time`. Paper confirms rotation duration is predictive. |

### MEDIUM Priority (requires simulation changes)

| # | Action | Paper Source | Impact | Implementation |
|---|--------|-------------|--------|----------------|
| 4 | **Track milestone revision count** | TOBT_count (Pearson 0.33) | Medium | Count gate reassignments during turnaround as proxy for operational disruption. |
| 5 | **5-minute rolling re-prediction during turnaround** | Slot-based prediction (Section 8.2) | High -- validates T-board concept | Extends Phase 33 #7. Re-predict at regular intervals with elapsed time as feature. Paper proves MAE drops from 18 to 3 min with rolling updates. |
| 6 | **Expand weather features** | WCF (Table 4) | Low-Medium | Add temperature, humidity, pressure to weather model. Currently only wind + visibility. |

### LOW Priority (future / requires real data)

| # | Action | Paper Source | Impact | Implementation |
|---|--------|-------------|--------|----------------|
| 7 | **Predict delay (vs schedule) as alternate target** | Section 4 problem formulation | Low | Could offer both: turnaround duration AND delay relative to schedule. |
| 8 | **Passenger flow features for A-CDM transfer** | PFF (Table 5) | High (with real data) | Boarding % and security checkpoint % are among top SHAP features. Critical for Phase 33 #8 (real data transfer learning). |

---

## Key Insight

The single highest-value takeaway is **rolling delay context features** (PCFDF). The paper demonstrates that knowing "are other flights at this airport running late right now?" is one of the strongest predictors of individual flight delay. This captures cascading effects, crew/equipment contention, and systemic disruptions that no per-flight feature can model. It is completely absent from our model and directly implementable in simulation.

---

## Honest Performance Comparison: CDG Paper vs Our OBT v2

### Raw Numbers

| Metric | CDG Paper (Real-Time) | CDG Paper (Forecast) | Our Model v2 (T-park) | Our Model v2 (T-90) |
|--------|----------------------|---------------------|----------------------|---------------------|
| MAE | 7-8 min | ~16 min | 4.55 min | ~6-7 min |
| R^2 | ~0.75 | ~0.1 | 0.91 | ~0.7-0.8 |
| RMSE | ~14 min | ~24 min | ~6 min | ~9 min |

### Why Our Metrics Are Artificially Inflated

1. **Predicting on our own synthetic data.** Our model learns patterns we injected (airline factors, weather multipliers in fallback.py). It's essentially learning back the formula we wrote. The CDG paper predicts on chaotic real-world operations -- strikes, equipment failures, passenger no-shows, ATC delays, crew shortages.

2. **Real-world variance is much higher.** CDG off-block delays range 0-280 min (std dev ~25 min). Our turnarounds range 10-180 min with std dev ~15 min. Higher variance = harder prediction = higher MAE even with a good model.

3. **Different targets.** We predict turnaround duration (a somewhat regular process). They predict delay relative to schedule (includes irregular operations, ATC slots, cascading effects -- fundamentally harder).

4. **Their forecast (day-ahead) = R^2 0.1.** This is the fair comparison to our T-90 -- static features, no gate-side info. Our T-90 gets R^2 ~0.75, but on synthetic data where aircraft_category deterministically drives ~80% of variance.

### Honest Assessment

| Question | Answer |
|----------|--------|
| Would our model beat theirs on CDG real data? | **No.** We'd likely get MAE 15-20 min (similar to their baseline) because our features miss TOBT, TSAT, PCFDF, passenger flow. |
| Would their model beat ours on our sim data? | **Yes, probably.** LightGBM with same features would perform similarly to our HistGBT. |
| Are our R^2=0.91 results publishable? | **Not honestly.** Predicting on synthetic data you generated yourself doesn't prove real-world value. |
| Is their MAE 7 min more impressive than our 4.5 min? | **Yes, significantly.** 7 min MAE on 720K real flights with 25-min std dev is a much harder achievement. |

### Where We Genuinely Compete

- **Multi-airport generalization** -- they didn't attempt this
- **Prediction intervals** -- they have none (point predictions only)
- **Architecture** (two-stage) -- cleaner than their single-model approach
- **Sim-to-real pipeline** -- if we execute Phase 33 #8 (A-CDM transfer learning), we'd have a model pre-trained on diverse airports then fine-tuned on real data. They train from scratch on CDG only.

### What Closes the Gap

The gap closes if we: (1) add rolling delay context features (PCFDF), (2) switch to CatBoost/LightGBM, (3) add SHAP explainability, and (4) transfer-learn on real A-CDM data. Until then, our 4.55 min MAE is a best-case ceiling on synthetic data, not a real-world performance claim.

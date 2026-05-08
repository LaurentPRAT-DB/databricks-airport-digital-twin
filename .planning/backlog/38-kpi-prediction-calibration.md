---
title: KPI Prediction Model Calibration
status: backlog
area: ml
priority: P1
related:
  - src/ml/congestion_model.py
  - src/ml/delay_model.py
  - app/backend/api/predictions.py
  - app/backend/services/prediction_service.py
---

# KPI Prediction Model Calibration

## Problem

The ML Predictions Dashboard shows unrealistic KPIs that don't match visual traffic levels:
- **Runway with 1 flight marked "Critical"** — capacity=2, hourly scale drops it to 1, so ratio=1.0 → CRITICAL
- **29% On-Time with only 38 flights** — delay model has aggressive base penalties for ground aircraft (+8min) and peak hours (+15min) that stack
- **19.4m Avg Delay** — every parked/ground aircraft gets high delay predictions regardless of actual congestion
- **Apron with 242 flights at "Low"** — large apron capacity (consolidated) vs tiny runway capacity creates imbalanced severity display

## Root Causes

### 1. Congestion Model: Runway capacity too low
**File:** `src/ml/congestion_model.py:96`

Runway capacity is hardcoded to **2**. Combined with `_get_hourly_capacity_scale()` which can reduce effective capacity to `max(1, int(2 * 0.67)) = 1`, a single aircraft on a runway triggers CRITICAL.

Real-world runway capacity should reflect movements per hour (typically 30-60 ops/hr for major airports), not simultaneous occupants. The model conflates "occupancy" (aircraft physically on the runway) with "demand" (movements/hour).

### 2. Congestion Model: Bounding box overlap
**File:** `src/ml/congestion_model.py:84-99`

Runway bounding boxes are padded by ±0.001° (~111m). For parallel runways (like KSFO 01L/R and 28L/R), these boxes overlap significantly — the same taxiing aircraft can be counted in multiple runway areas simultaneously.

### 3. Delay Model: Ground bias too strong
**File:** `src/ml/delay_model.py:112-117`

Ground aircraft get +8 min base delay regardless of context. Since most parked/taxiing aircraft aren't actually delayed, this inflates average delay.

### 4. Delay Model: Peak hour penalty always applied
**File:** `src/ml/delay_model.py:99-104`

Peak hours (7-9am, 5-7pm) add +15min * delay_scale. The model uses wall-clock time, not simulation time — so predictions don't align with the sim scenario's time.

### 5. Delay Model: Per-flight disposition noise is too high
**File:** `src/ml/delay_model.py:95`

`flight_disposition = flight_rng.gauss(0, 6.0)` — a 6-minute standard deviation means ~16% of flights get >6min base delay just from noise, before any actual delay factors.

### 6. Dashboard: On-Time threshold
**File:** `app/backend/api/predictions.py:302`

On-time threshold is `delay_minutes < 15`. But the delay model categorizes <5min as on_time and 5-15min as "slight". The dashboard counts anything ≥15min as late — the issue is the model predicts >15min for most flights.

## Proposed Fixes

### Phase 1: Quick calibration fixes (low effort, high impact)

1. **Increase runway capacity to movement-based values**
   - Use `capacity = max(4, runway_count * 2)` for dynamic OSM areas
   - Or better: count only aircraft in flight phases relevant to runway use (landing/takeoff/taxi-to-runway), not all ground aircraft in the bounding box

2. **Use flight phase for congestion counting**
   - Runway: only count flights in `landing`, `takeoff`, `taxi_to_runway` phases
   - Taxiway: only count `taxi_to_gate`, `taxi_to_runway`
   - Terminal/Apron: only count `parked`
   - Currently it uses position-only matching which double-counts

3. **Reduce ground aircraft delay bias**
   - Change `+8.0` to `+3.0` for ground category
   - Add phase-aware logic: PARKED flights get 0 delay penalty (they're not waiting, they're servicing)

4. **Use simulation time instead of wall clock**
   - Pass `sim_time` from the simulation clock to `extract_features()`
   - The current `hour_of_day` uses `datetime.now()` which may not match the simulated scenario

### Phase 2: Structural improvements (medium effort)

5. **Phase-based congestion model**
   - Replace bounding-box position matching with flight-phase assignment
   - Runway congestion = count of aircraft in approach/landing/takeoff within last 5 min
   - Use actual arrival/departure rate vs declared capacity (AAR/ADR from calibration)

6. **Trained delay model (CatBoost)**
   - Replace rule-based heuristics with a model trained on simulation history
   - Features: phase, gate, aircraft_type, congestion_level, time_of_day, weather
   - Training data: simulation recordings with known delays (from turnaround overruns)

7. **Remove redundant areas from dashboard**
   - Don't show runway areas that have 0 flights
   - Group runway pairs (28L/10R and 28R/10L are the same physical runway)
   - Only show areas above "low" in the overview tab

### Phase 3: Advanced calibration

8. **Airport-specific capacity from calibration profiles**
   - Use `known_profiles.py` ops/hour data to set realistic capacity thresholds
   - Scale congestion sensitivity inversely with airport size

9. **Historical delay distribution from simulation recordings**
   - After N recorded simulations, compute actual delay distribution
   - Use empirical percentiles instead of hardcoded thresholds

10. **Feedback loop: actual vs predicted**
    - Track predicted delay vs actual turnaround time
    - Surface prediction accuracy as a KPI on the dashboard itself

## Verification

- After Phase 1 fixes: KSFO with 38 flights should show ~80%+ on-time, <10m avg delay, no critical congestion
- Congestion "critical" should only appear when approach queue is genuinely saturated (>30 flights in approach)
- Delay "severe" should be reserved for actual high-congestion scenarios (>100 flights, bad weather)

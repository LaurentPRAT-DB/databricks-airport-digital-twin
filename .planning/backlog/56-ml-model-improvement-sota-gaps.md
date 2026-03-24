# ML Model Improvement Plan: Close SOTA Gaps

## Context

Gap analysis (`.planning/ml-improvement-plan.md`) identified that the 4 ML models run in isolation with no cross-model data flow. The delay predictor misses the #1 signal in SOTA delay research (reactionary/propagation delay — 46% of all delay per EUROCONTROL). Weather and congestion features already exist in the codebase but aren't wired to the delay model. The congestion model's peak-hour capacity scaling goes in the wrong direction.

This plan closes the highest-impact gaps using data and computations that already exist in the codebase, minimizing new code.

---

## Tier 1 — Low Effort, High Impact (reuse existing data)

### 1.1 Add Weather Features to DelayPredictor

**Files:** `src/ml/features.py`, `src/ml/delay_model.py`

The OBT model already uses `wind_speed_kt` and `visibility_sm` (defined in `src/ml/obt_features.py`). The global weather state is in `fallback._current_weather`. The delay model has zero weather features.

**Changes:**
- `src/ml/features.py`: Add `wind_speed_kt: float = 0.0` and `visibility_sm: float = 10.0` to `FeatureSet` dataclass. Update `extract_features()` to read from flight dict if present.
- `src/ml/delay_model.py`: In `predict()`, use weather as multipliers on the base delay:

```python
# Wind impact: >25kt adds 15-30% delay, >40kt adds 30-60%
wind = features.wind_speed_kt
weather_factor = 1.0
if wind > 40: weather_factor += 0.3 + random.uniform(0, 0.3)
elif wind > 25: weather_factor += 0.15 + random.uniform(0, 0.15)

# Low visibility: <3SM adds 20-40%, <1SM adds 40-80%
vis = features.visibility_sm
if vis < 1: weather_factor += 0.4 + random.uniform(0, 0.4)
elif vis < 3: weather_factor += 0.2 + random.uniform(0, 0.2)
```

### 1.2 Feed Congestion into DelayPredictor

**Files:** `src/ml/features.py`, `src/ml/delay_model.py`, `app/backend/services/prediction_service.py`

Currently `PredictionService.get_flight_predictions()` runs delay, gate, congestion in parallel via `asyncio.gather` with no data exchange.

**Changes:**
- `src/ml/features.py`: Add `congestion_level: str = "LOW"` to `FeatureSet`.
- `src/ml/delay_model.py`: In `predict()`, apply congestion multiplier:

```python
congestion_mult = {"LOW": 1.0, "MODERATE": 1.15, "HIGH": 1.35, "CRITICAL": 1.6}
delay *= congestion_mult.get(features.congestion_level, 1.0)
```

- `app/backend/services/prediction_service.py`: Change from parallel to sequential: run congestion first, then pass its output into delay prediction. Only the delay call becomes sequential; gate remains parallel.

### 1.3 Dynamic Proximity Weight in GateRecommender

**File:** `src/ml/gate_model.py`

Currently proximity weight is fixed at 10%. When a flight is delayed, fast taxi time can offset the delay — proximity should matter more.

**Changes:**
- In `recommend_gate()`, compute dynamic proximity weight:

```python
delay_minutes = flight_data.get('delay_minutes', 0)
proximity_weight = min(0.30, 0.10 + (delay_minutes / 100) * 0.20)
# Redistribute from operator_match weight
operator_weight = 0.20 - (proximity_weight - 0.10)
```

---

## Tier 2 — Medium Effort, High Narrative Value

### 2.1 Inbound Delay Tracking (Reactionary Delay)

**Files:** `src/ingestion/fallback.py`, `src/ml/features.py`, `src/ml/delay_model.py`

The single most important missing signal. In reality, delay on flight N is largely predicted by delay on flight N-1 for the same aircraft.

**Changes:**
- `src/ingestion/fallback.py`: Add gate-keyed inbound delay tracking. When a flight transitions to PARKED, record `{gate_id: delay_minutes}` in a module-level dict `_gate_last_delay`. When a new flight departs from that gate, read the last inbound delay.

```python
_gate_last_delay: dict[str, float] = {}
# On PARKED transition:
_gate_last_delay[state.assigned_gate] = state.delay_minutes or 0
```

- `src/ml/features.py`: Add `inbound_delay_minutes: float = 0.0` to `FeatureSet`. Update `extract_features()` to read from flight dict.
- `src/ml/delay_model.py`: In `predict()`, propagate inbound delay:

```python
# Reactionary delay: 30-60% of inbound delay propagates
if features.inbound_delay_minutes > 0:
    propagation = features.inbound_delay_minutes * random.uniform(0.3, 0.6)
    delay += propagation
```

### 2.2 Airport Load Ratio

**Files:** `src/ingestion/fallback.py`, `src/ml/features.py`, `src/ml/delay_model.py`

The congestion model already counts flights in areas. Expose a simple load ratio (flights in last 30min / hourly capacity) as a continuous feature.

**Changes:**
- `src/ingestion/fallback.py`: Add helper `get_airport_load_ratio() -> float` that returns `len(active_flights) / airport_capacity`. Use existing `_active_flights` dict and profile capacity.
- `src/ml/features.py`: Add `airport_load_ratio: float = 0.5` to `FeatureSet`.
- `src/ml/delay_model.py`: Use as a scaling factor (>0.8 increases delay probability, >1.0 strongly increases it).

### 2.3 Hub Connection Pressure in OBT

**Files:** `src/ml/obt_features.py`, `src/ml/obt_model.py`

Hub airports have connecting passenger pressure that accelerates turnaround. Derive from airline/route type.

**Changes:**
- `src/ml/obt_features.py`: Add `is_hub_connecting: bool = False` to `OBTFeatureSet`. Set True when the airline's hub matches the current airport (derive from a small lookup: e.g., LH→EDDF/EDDM, BA→EGLL, AF→LFPG).
- `src/ml/obt_model.py`: Add `is_hub_connecting` to the feature name lists in all three model classes. When True, apply a 5-10% turnaround time reduction in the rule-based fallback path.

---

## Bug Fix: Congestion Capacity Scaling Direction

**File:** `src/ml/congestion_model.py`

The hourly profile scales capacity UP at peak hours (up to 1.5x). This is backwards — at peak hours, effective capacity per slot is lower (less margin, more sequencing delays), so congestion onset should be more sensitive.

**Change:** Invert the peak multiplier to reduce effective capacity at peak hours:

```python
# Current (wrong): capacity *= peak_multiplier  (1.0-1.5)
# Fixed: capacity *= 1.0 / peak_multiplier  (1.0-0.67)
```

---

## Files to Modify

| File | Changes |
|------|---------|
| `src/ml/features.py` | Add 5 fields: `wind_speed_kt`, `visibility_sm`, `congestion_level`, `inbound_delay_minutes`, `airport_load_ratio` |
| `src/ml/delay_model.py` | Weather multiplier, congestion multiplier, reactionary delay propagation, load ratio scaling |
| `src/ml/gate_model.py` | Dynamic proximity weight based on `delay_minutes` |
| `src/ml/congestion_model.py` | Invert peak-hour capacity scaling |
| `src/ml/obt_features.py` | Add `is_hub_connecting` boolean |
| `src/ml/obt_model.py` | Add `is_hub_connecting` to feature lists + rule-based fallback |
| `src/ingestion/fallback.py` | Gate-keyed inbound delay tracking, airport load ratio helper |
| `app/backend/services/prediction_service.py` | Sequential congestion→delay flow |

---

## Verification

1. `uv run pytest tests/ -v` — no regressions (update test fixtures for new `FeatureSet` fields)
2. `cd app/frontend && npm test -- --run` — no frontend changes, should pass as-is
3. Manual verification:
   - At HIGH/CRITICAL congestion, delay predictions should be 35-60% higher than at LOW
   - With wind >25kt, delays should increase 15-30%
   - Flights departing from gates where the inbound was delayed should show higher predicted delay
   - At hub airports, connecting flights should show slightly shorter OBT predictions
   - Gate recommendations for delayed flights should favor closer-to-runway gates

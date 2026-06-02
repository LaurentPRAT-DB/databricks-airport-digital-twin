---
status: backlog
area: ml
related:
  - .planning/backlog/flifo-ground-truth.md
  - .planning/fixes/flifo-data-usage-gaps.md
  - src/ingestion/flifo_mapper.py
  - databricks/dlt_pipeline_config.json
---

# FLIFO Prediction Evaluation & Beat-FLIFO Model

## Context

FLIFO provides three time layers per flight:

| Field | What it is |
|-------|-----------|
| `scheduledTime` | Original plan (published timetable) |
| `estimatedTime` | FLIFO's running prediction (updates as flight progresses) |
| `actualTime` | Ground truth (filled when event happens) |

`estimatedTime` is FLIFO's prediction. Comparing against `actualTime` gives prediction accuracy metrics. By recording FLIFO estimates at multiple checkpoints and correlating with local airport state, we can evaluate FLIFO quality and train a model that beats it.

## Goal

1. Record FLIFO prediction snapshots over time
2. Evaluate FLIFO prediction accuracy (MAE, bias, convergence rate)
3. Train a local model that outperforms FLIFO using features FLIFO lacks
4. Optionally ensemble FLIFO + local model

---

## Phase 1: Data Recording Pipeline

### Bronze — Raw FLIFO Snapshots

Record every FLIFO update as-received. Schema:

```
snapshot_ts: timestamp       -- when we captured this
flight_number: string
direction: string            -- arrival/departure
scheduled_time: timestamp
estimated_time: timestamp    -- FLIFO's current prediction
actual_time: timestamp       -- null until event occurs
status_code: string
delay_minutes: int
delay_code: string
gate: string
terminal: string
airport_iata: string
```

Multiple rows per flight (one per poll cycle). This captures how FLIFO's estimate evolves.

### Silver — Aligned Estimate/Actual Pairs

Join snapshots to final actual time. Compute:

```
flight_number, airport_iata, direction,
snapshot_ts, time_to_event_minutes,       -- how far ahead was this estimate
flifo_estimated, actual_time,
flifo_error_minutes,                      -- estimated - actual
flifo_abs_error_minutes,
scheduled_vs_actual_minutes               -- baseline: schedule accuracy
```

### Gold — Prediction Accuracy Metrics

Aggregated by:
- Time horizon (T-2h, T-1h, T-30min, T-15min, T-5min)
- Airport
- Airline
- Time of day
- Day of week

Metrics: MAE, RMSE, bias, P50/P90 error, convergence curve.

---

## Phase 2: Local Feature Enrichment

At each FLIFO snapshot, also record local airport state:

```
gate_occupancy_pct: float          -- % gates occupied
runway_queue_depth: int            -- aircraft waiting for departure
approach_queue_depth: int          -- aircraft on approach
taxi_congestion: int               -- aircraft taxiing
weather_wind_kts: float
weather_visibility_sm: float
turnaround_state: string           -- phase of inbound aircraft (if arrival)
hour_of_day: int
day_of_week: int
airport_load_ratio: float
```

These are features FLIFO doesn't have (or underweights) — local ground state, real-time congestion.

---

## Phase 3: Beat-FLIFO Model

### Training Data

Silver table with local features joined. Target: `actual_time - scheduled_time` (total delay minutes). Features: FLIFO estimate + local state.

### Model Options

1. **Residual model** — Predict `actual - flifo_estimated` (correct FLIFO's error). Simple, leverages FLIFO as strong baseline.
2. **Direct model** — Predict delay independently, compare accuracy head-to-head.
3. **Ensemble** — Weighted blend of FLIFO + local model. Weight varies by time horizon (FLIFO stronger far out / en-route, local stronger near touchdown / ground ops).

### Where Local Model Wins

- **Ground ops** — taxi delays, gate availability, pushback queue. FLIFO has no visibility into airport ground state.
- **Cascade delays** — late inbound → late turnaround → late outbound. We track turnaround state.
- **Weather at destination** — FLIFO may not weight local weather impact on approach sequencing.
- **Historical route patterns** — specific airline/route/time combinations with systematic biases.

---

## Phase 4: Operational Integration

- Dashboard: FLIFO accuracy by airport/airline, model vs FLIFO comparison
- API endpoint: `/api/predictions/eta?flight=XX123` returns both FLIFO and model estimate with confidence
- FIDS enhancement: show prediction source and confidence indicator
- Alert: flag flights where model disagrees with FLIFO by >15min (early warning)

---

## DLT Pipeline Integration

Fits naturally into existing DLT pipeline:

```
Bronze: raw_flifo_snapshots (append-only, every poll cycle)
Silver: flifo_estimate_pairs (snapshot joined to actual, with local features)
Gold: prediction_accuracy_metrics (aggregated, model training table)
```

---

## Dependencies

- FLIFO ground-truth plan (backlog item) — needed so spawned flights carry FLIFO metadata
- SITA credentials for production FLIFO feed (currently using mock)
- Sufficient data volume — need weeks of snapshots before model training is meaningful

## Files to Create/Modify

| File | Change |
|------|--------|
| `src/ingestion/flifo_snapshot_recorder.py` | New — captures FLIFO state each poll cycle |
| `databricks/notebooks/dlt_flifo_snapshots.py` | New — Bronze/Silver/Gold DLT tables |
| `src/ml/eta_model.py` | New — residual/ensemble ETA prediction model |
| `app/backend/routes/predictions.py` | New — prediction API endpoint |
| `resources/flifo_pipeline_job.yml` | New — DABs job for snapshot recording |

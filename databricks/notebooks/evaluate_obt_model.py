# Databricks notebook source
# MAGIC %md
# MAGIC # Evaluate OBT Model Against Real OpenSky Turnaround Data
# MAGIC
# MAGIC Reads enriched phase transitions from `opensky_phase_transitions` Delta table,
# MAGIC extracts complete turnarounds (parked → pushback), loads the trained OBT model
# MAGIC from Unity Catalog, and compares predictions vs observed durations.
# MAGIC
# MAGIC **Inputs:**
# MAGIC - `opensky_phase_transitions` — enriched by `enrich_opensky_events.py` with gate assignments
# MAGIC - OBT refined model — registered in UC Model Registry or pickle in UC Volume
# MAGIC
# MAGIC **Outputs:**
# MAGIC - Per-turnaround comparison table (observed vs predicted)
# MAGIC - Aggregate metrics: MAE, RMSE, bias
# MAGIC - Per-category breakdown (narrow/wide/regional)

# COMMAND ----------

# MAGIC %pip install scikit-learn catboost>=1.2 pyyaml pydantic --quiet

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import os, sys, json, math
from datetime import datetime

# Bundle root (notebook is at .../files/databricks/notebooks/evaluate_obt_model.py)
nb_path = (
    dbutils.notebook.entry_point.getDbutils()
    .notebook()
    .getContext()
    .notebookPath()
    .get()
)
ws_path = "/Workspace" + nb_path
bundle_root = os.path.dirname(os.path.dirname(os.path.dirname(ws_path)))
print(f"Bundle root: {bundle_root}")

if bundle_root not in sys.path:
    sys.path.insert(0, bundle_root)
os.chdir(bundle_root)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

dbutils.widgets.text("airport_icao", "EDDF", "Airport ICAO code")
dbutils.widgets.text("airport_iata", "FRA", "Airport IATA code (for OBT model)")
dbutils.widgets.text("days", "7", "Days of data to evaluate")

airport_icao = dbutils.widgets.get("airport_icao")
airport_iata = dbutils.widgets.get("airport_iata")
days = int(dbutils.widgets.get("days"))

CATALOG = "serverless_stable_3n0ihb_catalog"
SCHEMA = "airport_digital_twin"
PHASE_TABLE = f"{CATALOG}.{SCHEMA}.opensky_phase_transitions"
MODEL_UC_NAME = f"{CATALOG}.{SCHEMA}.obt_refined_model"
MODEL_PICKLE_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/simulation_data/ml_models/obt_refined.pkl"

# Turnaround duration bounds (same as obt_features.py)
MIN_TURNAROUND_MIN = 10.0
MAX_TURNAROUND_MIN = 180.0

print(f"Airport:     {airport_icao} ({airport_iata})")
print(f"Days:        {days}")
print(f"Phase table: {PHASE_TABLE}")
print(f"Model (UC):  {MODEL_UC_NAME}")
print(f"Model (pkl): {MODEL_PICKLE_PATH}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Load phase transitions from Delta

# COMMAND ----------

phase_rows = spark.sql(f"""
    SELECT time, icao24, callsign, from_phase, to_phase,
           aircraft_type, assigned_gate
    FROM {PHASE_TABLE}
    WHERE airport_icao = '{airport_icao}'
      AND collection_date >= date_sub(current_date(), {days})
    ORDER BY time, icao24
""").collect()

print(f"Phase transitions loaded: {len(phase_rows)}")

if not phase_rows:
    dbutils.notebook.exit(json.dumps({
        "status": "NO_DATA",
        "airport": airport_icao,
        "message": f"No phase transitions found for {airport_icao} in the last {days} days",
    }))

# Show phase distribution
phase_dist = spark.sql(f"""
    SELECT to_phase, count(*) as cnt
    FROM {PHASE_TABLE}
    WHERE airport_icao = '{airport_icao}'
      AND collection_date >= date_sub(current_date(), {days})
    GROUP BY to_phase
    ORDER BY cnt DESC
""")
display(phase_dist)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Extract complete turnarounds

# COMMAND ----------

parked_at = {}   # icao24 → row
turnarounds = []

for row in phase_rows:
    icao24 = row.icao24
    if row.to_phase == "parked":
        parked_at[icao24] = row
    elif row.from_phase == "parked" and icao24 in parked_at:
        park_row = parked_at.pop(icao24)
        park_time = datetime.fromisoformat(park_row.time)
        leave_time = datetime.fromisoformat(row.time)
        duration_min = (leave_time - park_time).total_seconds() / 60.0

        # Filter outliers
        if duration_min < MIN_TURNAROUND_MIN or duration_min > MAX_TURNAROUND_MIN:
            continue

        turnarounds.append({
            "icao24": icao24,
            "callsign": row.callsign or icao24,
            "gate": park_row.assigned_gate or "?",
            "parked_time": park_time,
            "leave_time": leave_time,
            "duration_min": duration_min,
            "aircraft_type": row.aircraft_type or "",
        })

print(f"Complete turnarounds: {len(turnarounds)}")
print(f"Still parked (incomplete): {len(parked_at)}")

if not turnarounds:
    # Show what we have for debugging
    print("\nSample phase transitions:")
    for row in phase_rows[:20]:
        print(f"  {row.time[:19]}  {(row.callsign or '?'):8s}  {row.from_phase:15s} → {row.to_phase}")

    if parked_at:
        print(f"\nAircraft still parked:")
        last_time = phase_rows[-1].time if phase_rows else None
        for icao24, row in list(parked_at.items())[:10]:
            park_time = datetime.fromisoformat(row.time)
            if last_time:
                elapsed = (datetime.fromisoformat(last_time) - park_time).total_seconds() / 60.0
            else:
                elapsed = 0.0
            print(f"  {(row.callsign or icao24):8s}  gate={row.assigned_gate or '?':6s}  "
                  f"parked at {row.time[:19]}  ({elapsed:.0f} min so far)")

    dbutils.notebook.exit(json.dumps({
        "status": "NO_TURNAROUNDS",
        "airport": airport_icao,
        "n_phase_transitions": len(phase_rows),
        "n_still_parked": len(parked_at),
        "message": "No complete turnarounds found. Need 60-90+ min continuous data per aircraft.",
    }))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Load OBT model from Unity Catalog

# COMMAND ----------

from src.ml.obt_model import OBTPredictor
from src.ml.obt_features import OBTFeatureSet, classify_aircraft

predictor = OBTPredictor()
model_source = "fallback"

# Try UC Model Registry first
try:
    import mlflow
    mlflow.set_registry_uri("databricks-uc")
    model_uri = f"models:/{MODEL_UC_NAME}/latest"
    loaded_pipeline = mlflow.sklearn.load_model(model_uri)
    # Inject the loaded pipeline into the predictor
    predictor._pipeline = loaded_pipeline
    model_source = "uc_registry"
    print(f"Model loaded from UC Model Registry: {model_uri}")
except Exception as e:
    print(f"UC Model Registry load failed: {e}")
    # Fallback: pickle from UC Volume
    if os.path.exists(MODEL_PICKLE_PATH):
        loaded = predictor.load(MODEL_PICKLE_PATH)
        if loaded:
            model_source = "uc_volume_pickle"
            print(f"Model loaded from UC Volume pickle: {MODEL_PICKLE_PATH}")
        else:
            print(f"Pickle load failed, using GSE fallback")
    else:
        print(f"No pickle at {MODEL_PICKLE_PATH}, using GSE fallback (45/90 min)")

print(f"Model source: {model_source}")
print(f"Model trained: {predictor.is_trained}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Build features and predict

# COMMAND ----------

def build_feature_set(callsign, gate_id, aircraft_type, parked_hour, parked_weekday, airport_iata):
    """Build an OBTFeatureSet from observed turnaround context."""
    h_sin = round(math.sin(2.0 * math.pi * parked_hour / 24.0), 6)
    h_cos = round(math.cos(2.0 * math.pi * parked_hour / 24.0), 6)

    airline_code = callsign[:3] if len(callsign) >= 3 and callsign[:3].isalpha() else "UNK"
    gate_prefix = ""
    for ch in (gate_id or ""):
        if ch.isalpha():
            gate_prefix += ch
        else:
            break
    gate_prefix = gate_prefix or "UNK"

    return OBTFeatureSet(
        aircraft_category=classify_aircraft(aircraft_type) if aircraft_type else "narrow",
        airline_code=airline_code,
        hour_of_day=parked_hour,
        is_international=False,
        arrival_delay_min=0.0,
        gate_id_prefix=gate_prefix,
        is_remote_stand=(gate_id or "").upper().startswith("R"),
        concurrent_gate_ops=0,
        wind_speed_kt=0.0,
        visibility_sm=10.0,
        has_active_ground_stop=False,
        scheduled_departure_hour=parked_hour,
        airport_code=airport_iata,
        day_of_week=parked_weekday,
        hour_sin=h_sin,
        hour_cos=h_cos,
        is_weather_scenario=False,
        scheduled_buffer_min=0.0,
        is_hub_connecting=False,
    )

# Run predictions
results = []
for ta in sorted(turnarounds, key=lambda x: x["parked_time"]):
    features = build_feature_set(
        callsign=ta["callsign"],
        gate_id=ta["gate"],
        aircraft_type=ta["aircraft_type"],
        parked_hour=ta["parked_time"].hour,
        parked_weekday=ta["parked_time"].weekday(),
        airport_iata=airport_iata,
    )
    prediction = predictor.predict(features)

    results.append({
        "callsign": ta["callsign"],
        "gate": ta["gate"],
        "aircraft_category": features.aircraft_category,
        "parked_at": ta["parked_time"].strftime("%Y-%m-%d %H:%M"),
        "observed_min": round(ta["duration_min"], 1),
        "predicted_min": prediction.turnaround_minutes,
        "error_min": round(ta["duration_min"] - prediction.turnaround_minutes, 1),
        "lower_bound": prediction.lower_bound_minutes,
        "upper_bound": prediction.upper_bound_minutes,
        "is_fallback": prediction.is_fallback,
    })

print(f"Predictions complete: {len(results)} turnarounds")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Results

# COMMAND ----------

from pyspark.sql import Row
from pyspark.sql.types import (
    StructType, StructField, StringType, DoubleType, BooleanType,
)

result_schema = StructType([
    StructField("callsign", StringType(), False),
    StructField("gate", StringType(), True),
    StructField("aircraft_category", StringType(), True),
    StructField("parked_at", StringType(), True),
    StructField("observed_min", DoubleType(), False),
    StructField("predicted_min", DoubleType(), False),
    StructField("error_min", DoubleType(), False),
    StructField("lower_bound", DoubleType(), True),
    StructField("upper_bound", DoubleType(), True),
    StructField("is_fallback", BooleanType(), False),
])

result_rows = [Row(**r) for r in results]
df_results = spark.createDataFrame(result_rows, schema=result_schema)
display(df_results)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Aggregate metrics

# COMMAND ----------

errors = [r["error_min"] for r in results]
abs_errors = [abs(e) for e in errors]

mae = sum(abs_errors) / len(abs_errors)
rmse = math.sqrt(sum(e * e for e in errors) / len(errors))
bias = sum(errors) / len(errors)

# Within-interval coverage (predicted interval contains observed)
in_interval = sum(
    1 for r in results
    if r["lower_bound"] <= r["observed_min"] <= r["upper_bound"]
)
coverage_pct = 100.0 * in_interval / len(results) if results else 0.0

print(f"{'='*60}")
print(f"OBT Model Evaluation — {airport_icao} ({airport_iata})")
print(f"{'='*60}")
print(f"  Turnarounds:    {len(turnarounds)}")
print(f"  Model source:   {model_source}")
print(f"  MAE:            {mae:.1f} min")
print(f"  RMSE:           {rmse:.1f} min")
print(f"  Bias:           {bias:+.1f} min (positive = model under-predicts)")
print(f"  PI coverage:    {coverage_pct:.0f}% (observed within [P10, P90])")

# Per-category breakdown
categories = set(r["aircraft_category"] for r in results)
print(f"\nPer-category MAE:")
for cat in sorted(categories):
    cat_errors = [abs(r["error_min"]) for r in results if r["aircraft_category"] == cat]
    if cat_errors:
        cat_mae = sum(cat_errors) / len(cat_errors)
        print(f"  {cat:10s}  MAE={cat_mae:.1f} min  (n={len(cat_errors)})")

# Fallback stats
n_fallback = sum(1 for r in results if r["is_fallback"])
print(f"\nFallback predictions: {n_fallback}/{len(results)} ({100*n_fallback/len(results):.0f}%)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Exit with summary

# COMMAND ----------

per_category_mae = {}
for cat in sorted(categories):
    cat_errors = [abs(r["error_min"]) for r in results if r["aircraft_category"] == cat]
    if cat_errors:
        per_category_mae[cat] = round(sum(cat_errors) / len(cat_errors), 2)

dbutils.notebook.exit(json.dumps({
    "status": "PASS",
    "airport_icao": airport_icao,
    "airport_iata": airport_iata,
    "days": days,
    "n_phase_transitions": len(phase_rows),
    "n_turnarounds": len(turnarounds),
    "model_source": model_source,
    "model_trained": predictor.is_trained,
    "mae_min": round(mae, 2),
    "rmse_min": round(rmse, 2),
    "bias_min": round(bias, 2),
    "pi_coverage_pct": round(coverage_pct, 1),
    "n_fallback": n_fallback,
    "per_category_mae": per_category_mae,
}))

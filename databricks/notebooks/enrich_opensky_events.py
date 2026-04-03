# Databricks notebook source
# MAGIC %md
# MAGIC # Enrich OpenSky Events — Gate Assignment + Phase Inference
# MAGIC
# MAGIC Reads raw ADS-B states from `opensky_states_raw`, loads OSM gate positions
# MAGIC from the `gates` table, runs `OpenSkyEventInferrer` per airport/date, and
# MAGIC writes results to three Delta tables:
# MAGIC
# MAGIC - **opensky_phase_transitions** — parked, taxi, takeoff, landing, cruise, etc.
# MAGIC - **opensky_gate_events** — assign, occupy, release with gate_distance_m
# MAGIC - **opensky_enriched_snapshots** — every state vector with inferred phase + assigned_gate
# MAGIC
# MAGIC The ML pipeline (`src/ml/obt_features.py`) can read these directly for training.

# COMMAND ----------

import os, sys

# Derive bundle root from notebook path in workspace
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

from datetime import datetime, timezone
from pyspark.sql import Row

CATALOG = "serverless_stable_3n0ihb_catalog"
SCHEMA = "airport_digital_twin"
RAW_TABLE = f"{CATALOG}.{SCHEMA}.opensky_states_raw"
GATES_TABLE = f"{CATALOG}.{SCHEMA}.gates"
PHASE_TABLE = f"{CATALOG}.{SCHEMA}.opensky_phase_transitions"
GATE_EVENTS_TABLE = f"{CATALOG}.{SCHEMA}.opensky_gate_events"
ENRICHED_TABLE = f"{CATALOG}.{SCHEMA}.opensky_enriched_snapshots"

# Unit conversions (same as opensky_service.py)
M_TO_FT = 3.28084
MS_TO_KTS = 1.94384
MS_TO_FTMIN = 196.85

print(f"Raw states:          {RAW_TABLE}")
print(f"Gates:               {GATES_TABLE}")
print(f"Phase transitions:   {PHASE_TABLE}")
print(f"Gate events:         {GATE_EVENTS_TABLE}")
print(f"Enriched snapshots:  {ENRICHED_TABLE}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Find unenriched airport/date combinations

# COMMAND ----------

# Get all (airport_icao, collection_date) pairs in raw data
raw_pairs = spark.sql(f"""
    SELECT DISTINCT airport_icao, collection_date
    FROM {RAW_TABLE}
    ORDER BY collection_date DESC, airport_icao
""").collect()

# Get already-enriched pairs
try:
    enriched_pairs = set(
        (row.airport_icao, str(row.collection_date))
        for row in spark.sql(f"""
            SELECT DISTINCT airport_icao, collection_date
            FROM {ENRICHED_TABLE}
        """).collect()
    )
except Exception:
    enriched_pairs = set()

pending = [
    (row.airport_icao, str(row.collection_date))
    for row in raw_pairs
    if (row.airport_icao, str(row.collection_date)) not in enriched_pairs
]

print(f"Raw airport/date pairs:      {len(raw_pairs)}")
print(f"Already enriched:            {len(enriched_pairs)}")
print(f"Pending enrichment:          {len(pending)}")

if not pending:
    dbutils.notebook.exit("All data already enriched — nothing to do")

for airport, date in pending:
    print(f"  {airport} / {date}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Load gate positions from UC

# COMMAND ----------

def load_gates_for_airport(airport_icao: str) -> list:
    """Load gate geometry from the UC gates table for an airport."""
    rows = spark.sql(f"""
        SELECT ref, latitude, longitude, terminal
        FROM {GATES_TABLE}
        WHERE icao_code = '{airport_icao}'
    """).collect()

    gates = []
    for row in rows:
        if row.latitude is not None and row.longitude is not None:
            gates.append({
                "ref": row.ref,
                "geo": {"latitude": float(row.latitude), "longitude": float(row.longitude)},
                "terminal": row.terminal,
            })
    return gates

# Quick check
sample_airport = pending[0][0]
sample_gates = load_gates_for_airport(sample_airport)
print(f"Gates loaded for {sample_airport}: {len(sample_gates)}")
if sample_gates:
    print(f"  Sample: {sample_gates[0]['ref']} @ ({sample_gates[0]['geo']['latitude']:.4f}, {sample_gates[0]['geo']['longitude']:.4f})")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Run enrichment per airport/date

# COMMAND ----------

from src.inference.opensky_events import OpenSkyEventInferrer

total_phases = 0
total_gate_events = 0
total_snapshots = 0
enriched_at = datetime.now(timezone.utc)

for airport_icao, date in pending:
    print(f"\n{'='*60}")
    print(f"Enriching {airport_icao} / {date}")

    # Load gates
    gates = load_gates_for_airport(airport_icao)
    print(f"  Gates: {len(gates)}")

    # Load raw states
    raw_rows = spark.sql(f"""
        SELECT
            icao24, callsign, origin_country,
            latitude, longitude,
            baro_altitude, geo_altitude,
            velocity, true_track, vertical_rate,
            on_ground, collection_time,
            aircraft_type, airline_icao
        FROM {RAW_TABLE}
        WHERE airport_icao = '{airport_icao}'
          AND collection_date = '{date}'
        ORDER BY collection_time, icao24
    """).collect()

    print(f"  Raw states: {len(raw_rows)}")
    if not raw_rows:
        print("  Skipping — no data")
        continue

    # Group by collection_time into frames
    frames = {}
    for row in raw_rows:
        ts = row.collection_time.isoformat() if isinstance(row.collection_time, datetime) else str(row.collection_time)

        baro_alt_m = row.baro_altitude or 0.0
        velocity_ms = row.velocity or 0.0
        vrate_ms = row.vertical_rate or 0.0
        on_ground = bool(row.on_ground)

        snap = {
            "icao24": row.icao24,
            "callsign": (row.callsign or row.icao24).strip(),
            "latitude": row.latitude,
            "longitude": row.longitude,
            "altitude": baro_alt_m * M_TO_FT,
            "velocity": velocity_ms * MS_TO_KTS,
            "heading": row.true_track,
            "vertical_rate": vrate_ms * MS_TO_FTMIN,
            "on_ground": on_ground,
            "aircraft_type": row.aircraft_type or "",
        }

        if ts not in frames:
            frames[ts] = []
        frames[ts].append(snap)

    sorted_timestamps = sorted(frames.keys())
    print(f"  Frames: {len(sorted_timestamps)}")

    # Run inferrer
    inferrer = OpenSkyEventInferrer(gates)
    for ts in sorted_timestamps:
        inferrer.process_frame(ts, frames[ts])
    results = inferrer.get_results()

    n_phases = len(results["phase_transitions"])
    n_gate_ev = len(results["gate_events"])
    n_snaps = len(results["enriched_snapshots"])
    print(f"  Phase transitions: {n_phases}")
    print(f"  Gate events:       {n_gate_ev}")
    print(f"  Enriched snaps:    {n_snaps}")

    # ── Write phase transitions ──
    if results["phase_transitions"]:
        phase_rows = []
        for pt in results["phase_transitions"]:
            phase_rows.append(Row(
                airport_icao=airport_icao,
                collection_date=date,
                time=pt["time"],
                icao24=pt["icao24"],
                callsign=pt["callsign"],
                from_phase=pt["from_phase"],
                to_phase=pt["to_phase"],
                latitude=pt["latitude"],
                longitude=pt["longitude"],
                altitude=pt["altitude"],
                aircraft_type=pt["aircraft_type"],
                assigned_gate=pt["assigned_gate"],
                _enriched_at=enriched_at,
            ))
        df_phases = spark.createDataFrame(phase_rows)
        df_phases.write.mode("append").partitionBy("collection_date").saveAsTable(PHASE_TABLE)
        total_phases += n_phases

    # ── Write gate events ──
    if results["gate_events"]:
        gate_rows = []
        for ge in results["gate_events"]:
            gate_rows.append(Row(
                airport_icao=airport_icao,
                collection_date=date,
                time=ge["time"],
                icao24=ge["icao24"],
                callsign=ge["callsign"],
                gate=ge["gate"],
                event_type=ge["event_type"],
                aircraft_type=ge["aircraft_type"],
                gate_distance_m=ge["gate_distance_m"],
                _enriched_at=enriched_at,
            ))
        df_gate_ev = spark.createDataFrame(gate_rows)
        df_gate_ev.write.mode("append").partitionBy("collection_date").saveAsTable(GATE_EVENTS_TABLE)
        total_gate_events += n_gate_ev

    # ── Write enriched snapshots ──
    if results["enriched_snapshots"]:
        snap_rows = []
        for s in results["enriched_snapshots"]:
            snap_rows.append(Row(
                airport_icao=airport_icao,
                collection_date=date,
                time=s["time"],
                icao24=s["icao24"],
                callsign=s["callsign"],
                latitude=s["latitude"],
                longitude=s["longitude"],
                altitude=s["altitude"],
                velocity=s["velocity"],
                heading=s["heading"],
                vertical_rate=s["vertical_rate"],
                phase=s["phase"],
                on_ground=s["on_ground"],
                aircraft_type=s["aircraft_type"],
                assigned_gate=s["assigned_gate"],
                _enriched_at=enriched_at,
            ))
        df_snaps = spark.createDataFrame(snap_rows)
        df_snaps.write.mode("append").partitionBy("collection_date").saveAsTable(ENRICHED_TABLE)
        total_snapshots += n_snaps

    print(f"  Written to Delta tables")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Summary

# COMMAND ----------

print(f"\n{'='*60}")
print(f"OpenSky Event Enrichment — Complete")
print(f"{'='*60}")
print(f"  Airport/date pairs processed: {len(pending)}")
print(f"  Phase transitions written:    {total_phases:,}")
print(f"  Gate events written:          {total_gate_events:,}")
print(f"  Enriched snapshots written:   {total_snapshots:,}")
print(f"{'='*60}")

exit_msg = (
    f"SUCCESS: {len(pending)} pairs enriched — "
    f"{total_phases} phases, {total_gate_events} gate events, {total_snapshots} snapshots"
)
dbutils.notebook.exit(exit_msg)

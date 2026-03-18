# Databricks notebook source
# MAGIC %md
# MAGIC # Pre-load OSM Airport Data into Unity Catalog
# MAGIC Fetches airport geometry (gates, terminals, taxiways, aprons) from
# MAGIC OpenStreetMap Overpass API for all well-known airports and persists
# MAGIC to Unity Catalog so the app never hits Overpass at runtime.

# COMMAND ----------

%pip install httpx pydantic --quiet

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import os, sys, time, json
from datetime import datetime

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

# Add bundle root to sys.path so src/ imports work
if bundle_root not in sys.path:
    sys.path.insert(0, bundle_root)

os.chdir(bundle_root)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

UC_CATALOG = "serverless_stable_3n0ihb_catalog"
UC_SCHEMA = "airport_digital_twin"

# Canonical airport list (same as WELL_KNOWN_AIRPORT_INFO in routes.py)
WELL_KNOWN_AIRPORTS = {
    # Americas
    "KSFO": {"iata": "SFO", "name": "San Francisco International"},
    "KJFK": {"iata": "JFK", "name": "John F. Kennedy International"},
    "KLAX": {"iata": "LAX", "name": "Los Angeles International"},
    "KORD": {"iata": "ORD", "name": "O'Hare International"},
    "KATL": {"iata": "ATL", "name": "Hartsfield-Jackson Atlanta"},
    "KDFW": {"iata": "DFW", "name": "Dallas/Fort Worth International"},
    "KDEN": {"iata": "DEN", "name": "Denver International"},
    "KMIA": {"iata": "MIA", "name": "Miami International"},
    "KSEA": {"iata": "SEA", "name": "Seattle-Tacoma International"},
    "SBGR": {"iata": "GRU", "name": "Guarulhos International"},
    "MMMX": {"iata": "MEX", "name": "Mexico City International"},
    # Europe
    "EGLL": {"iata": "LHR", "name": "London Heathrow"},
    "LFPG": {"iata": "CDG", "name": "Charles de Gaulle"},
    "EHAM": {"iata": "AMS", "name": "Amsterdam Schiphol"},
    "EDDF": {"iata": "FRA", "name": "Frankfurt Airport"},
    "LEMD": {"iata": "MAD", "name": "Adolfo Suarez Madrid-Barajas"},
    "LIRF": {"iata": "FCO", "name": "Leonardo da Vinci (Fiumicino)"},
    # Middle East
    "OMAA": {"iata": "AUH", "name": "Abu Dhabi International"},
    "OMDB": {"iata": "DXB", "name": "Dubai International"},
    # Asia-Pacific
    "RJTT": {"iata": "HND", "name": "Tokyo Haneda"},
    "VHHH": {"iata": "HKG", "name": "Hong Kong International"},
    "WSSS": {"iata": "SIN", "name": "Singapore Changi"},
    "ZBAA": {"iata": "PEK", "name": "Beijing Capital International"},
    "RKSI": {"iata": "ICN", "name": "Incheon International"},
    "VTBS": {"iata": "BKK", "name": "Suvarnabhumi Airport"},
    # Africa
    "FAOR": {"iata": "JNB", "name": "O.R. Tambo International"},
    "GMMN": {"iata": "CMN", "name": "Mohammed V International"},
}

DELAY_BETWEEN_AIRPORTS = 10  # seconds, to respect Overpass rate limits

# COMMAND ----------

# MAGIC %md
# MAGIC ## Discover already-persisted airports

# COMMAND ----------

try:
    persisted_df = spark.sql(f"SELECT icao_code FROM {UC_CATALOG}.{UC_SCHEMA}.airport_metadata")
    persisted_codes = {row.icao_code.upper() for row in persisted_df.collect()}
except Exception as e:
    print(f"Could not query airport_metadata (table may not exist yet): {e}")
    persisted_codes = set()

to_load = [icao for icao in WELL_KNOWN_AIRPORTS if icao not in persisted_codes]
already_cached = [icao for icao in WELL_KNOWN_AIRPORTS if icao in persisted_codes]

print(f"Already cached: {len(already_cached)} airports")
print(f"To load: {len(to_load)} airports")
if already_cached:
    print(f"  Cached: {', '.join(sorted(already_cached))}")
if to_load:
    print(f"  Queued: {', '.join(to_load)}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Pre-load missing airports

# COMMAND ----------

from app.backend.services.airport_config_service import AirportConfigService
import src.formats.osm.parser as osm_parser
import traceback

# Override parser defaults for large airports (workspace may not find config file)
osm_parser.OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
osm_parser.DEFAULT_TIMEOUT = 180.0
osm_parser.QUERY_TIMEOUT = 170
osm_parser.RETRY_COUNT = 3
osm_parser.RETRY_DELAY = 15.0

print(f"Overpass config: timeout={osm_parser.DEFAULT_TIMEOUT}s, query_timeout={osm_parser.QUERY_TIMEOUT}s, "
      f"retries={osm_parser.RETRY_COUNT}, retry_delay={osm_parser.RETRY_DELAY}s")
print(f"Endpoints: {osm_parser.OVERPASS_ENDPOINTS}")

loaded = []
failed = []

for i, icao in enumerate(to_load, 1):
    info = WELL_KNOWN_AIRPORTS[icao]
    print(f"\n[{i}/{len(to_load)}] Loading {icao} ({info['iata']}) - {info['name']}...")
    start = time.time()

    try:
        service = AirportConfigService()

        # Import OSM data (gates, terminals, taxiways, aprons)
        config, warnings = service.import_osm(
            icao_code=icao,
            include_gates=True,
            include_terminals=True,
            include_taxiways=True,
            include_aprons=True,
            include_runways=True,
            merge=False,
        )

        gates = len(config.get("gates", []))
        terminals = len(config.get("terminals", []))
        elapsed = time.time() - start

        print(f"  OSM OK: {gates} gates, {terminals} terminals ({elapsed:.1f}s)")
        if warnings:
            print(f"  Warnings: {'; '.join(warnings)}")

        # Import FAA runway data for US airports (ICAO starts with K)
        if icao.startswith("K"):
            try:
                faa_config, faa_warnings = service.import_faa(
                    facility_id=info["iata"],
                    merge=True,
                )
                runways = len(faa_config.get("runways", []))
                print(f"  FAA OK: {runways} runways")
                if faa_warnings:
                    print(f"  FAA warnings: {'; '.join(faa_warnings)}")
            except Exception as e:
                print(f"  FAA skipped: {e}")

        loaded.append({
            "icao": icao,
            "iata": info["iata"],
            "gates": gates,
            "terminals": terminals,
            "elapsed_sec": round(elapsed, 1),
        })

    except Exception as e:
        elapsed = time.time() - start
        print(f"  FAILED ({elapsed:.1f}s): {type(e).__name__}: {e}")
        traceback.print_exc()
        failed.append({
            "icao": icao,
            "iata": info["iata"],
            "error": str(e)[:200],
        })

    # Rate-limit delay (skip after last airport)
    if i < len(to_load):
        print(f"  Waiting {DELAY_BETWEEN_AIRPORTS}s before next airport...")
        time.sleep(DELAY_BETWEEN_AIRPORTS)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary

# COMMAND ----------

print(f"\n{'='*60}")
print(f"OSM PRE-LOAD COMPLETE")
print(f"{'='*60}")
print(f"Already cached: {len(already_cached)}")
print(f"Newly loaded:   {len(loaded)}")
print(f"Failed:         {len(failed)}")
print(f"Total airports: {len(already_cached) + len(loaded)}/{len(WELL_KNOWN_AIRPORTS)}")

if loaded:
    total_gates = sum(r["gates"] for r in loaded)
    total_terminals = sum(r["terminals"] for r in loaded)
    print(f"\nNewly loaded airports:")
    for r in loaded:
        print(f"  {r['icao']} ({r['iata']}): {r['gates']} gates, {r['terminals']} terminals ({r['elapsed_sec']}s)")
    print(f"  Total: {total_gates} gates, {total_terminals} terminals")

if failed:
    print(f"\nFailed airports:")
    for r in failed:
        print(f"  {r['icao']} ({r['iata']}): {r['error']}")

# COMMAND ----------

dbutils.notebook.exit(json.dumps({
    "already_cached": len(already_cached),
    "loaded": len(loaded),
    "failed": len(failed),
    "total": len(WELL_KNOWN_AIRPORTS),
    "failed_details": [{"icao": r["icao"], "error": r["error"]} for r in failed],
    "loaded_details": [{"icao": r["icao"], "gates": r["gates"]} for r in loaded],
}))

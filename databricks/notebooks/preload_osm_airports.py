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
from datetime import datetime, timezone

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
# MAGIC ## Ensure UC tables exist

# COMMAND ----------

from src.persistence.airport_tables import ALL_TABLES

# Only create tables relevant to airport config (skip flight history, ML, profiles)
AIRPORT_CONFIG_TABLES = [
    name for name, _ in ALL_TABLES
    if name in (
        "airport_metadata", "gates", "terminals", "taxiways", "aprons",
        "buildings", "hangars", "helipads", "parking_positions", "osm_runways",
        "runways",
    )
]

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {UC_CATALOG}.{UC_SCHEMA}")

for table_name, ddl in ALL_TABLES:
    if table_name in AIRPORT_CONFIG_TABLES:
        sql = ddl.format(catalog=UC_CATALOG, schema=UC_SCHEMA)
        spark.sql(sql)
        print(f"  Ensured table: {UC_CATALOG}.{UC_SCHEMA}.{table_name}")

print(f"All {len(AIRPORT_CONFIG_TABLES)} airport config tables ready.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Spark SQL persistence helper

# COMMAND ----------

def _sql_str(value):
    """Convert value to SQL string literal or NULL."""
    if value is None:
        return "NULL"
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def _table(name):
    return f"{UC_CATALOG}.{UC_SCHEMA}.{name}"


def _batch_insert(table, columns, rows, batch_size=200):
    """Insert rows in batches to avoid SQL statement size limits."""
    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES {','.join(batch)}"
        spark.sql(sql)


def persist_via_spark(icao_code, config, info):
    """Persist airport config to UC tables using spark.sql().

    Mirrors the logic in AirportRepository.save_airport_config() but
    executes via Spark SQL instead of WorkspaceClient statement execution.
    """
    now = datetime.now(timezone.utc).isoformat()

    # --- airport_metadata (MERGE) ---
    sources = config.get("sources", ["OSM"])
    sources_sql = "ARRAY(" + ", ".join(f"'{s}'" for s in sources) + ")"

    spark.sql(f"""
        MERGE INTO {_table('airport_metadata')} t
        USING (SELECT
            '{icao_code}' as icao_code,
            {_sql_str(config.get('iataCode', info.get('iata')))} as iata_code,
            {_sql_str(config.get('airportName', info.get('name')))} as name,
            {_sql_str(config.get('airportOperator'))} as operator,
            {sources_sql} as data_sources,
            TIMESTAMP'{now}' as osm_timestamp,
            TIMESTAMP'{now}' as updated_at
        ) s
        ON t.icao_code = s.icao_code
        WHEN MATCHED THEN UPDATE SET
            iata_code = s.iata_code,
            name = s.name,
            operator = s.operator,
            data_sources = s.data_sources,
            osm_timestamp = s.osm_timestamp,
            updated_at = s.updated_at
        WHEN NOT MATCHED THEN INSERT (
            icao_code, iata_code, name, operator, data_sources,
            osm_timestamp, created_at, updated_at
        ) VALUES (
            s.icao_code, s.iata_code, s.name, s.operator, s.data_sources,
            s.osm_timestamp, TIMESTAMP'{now}', s.updated_at
        )
    """)

    # --- gates ---
    gates = config.get("gates", [])
    spark.sql(f"DELETE FROM {_table('gates')} WHERE icao_code = '{icao_code}'")
    if gates:
        values = []
        for g in gates:
            ref = g.get("ref") or g.get("id", "")
            gate_id = f"{icao_code}_{ref}"
            geo = g.get("geo", {})
            pos = g.get("position", {})
            values.append(f"""(
                '{gate_id}', '{icao_code}', {_sql_str(ref)}, {_sql_str(g.get('name'))},
                {_sql_str(g.get('terminal'))}, {_sql_str(g.get('level'))},
                {_sql_str(g.get('operator'))},
                {geo.get('latitude', 0)}, {geo.get('longitude', 0)},
                {g.get('elevation') or 'NULL'},
                {pos.get('x', 0)}, {pos.get('y', 0)}, {pos.get('z', 0)},
                {g.get('osmId') or 'NULL'}, 'OSM', TIMESTAMP'{now}', TIMESTAMP'{now}'
            )""")
        _batch_insert(
            _table('gates'),
            ["gate_id", "icao_code", "ref", "name", "terminal", "level", "operator",
             "latitude", "longitude", "elevation",
             "position_x", "position_y", "position_z",
             "osm_id", "source", "created_at", "updated_at"],
            values,
        )

    # --- terminals ---
    terminals = config.get("terminals", [])
    spark.sql(f"DELETE FROM {_table('terminals')} WHERE icao_code = '{icao_code}'")
    if terminals:
        values = []
        for t in terminals:
            terminal_id = f"{icao_code}_{t.get('osmId', t.get('id', ''))}"
            geo = t.get("geo", {})
            pos = t.get("position", {})
            dims = t.get("dimensions", {})
            values.append(f"""(
                '{terminal_id}', '{icao_code}', {_sql_str(t.get('name'))},
                {_sql_str(t.get('type', 'terminal'))}, {_sql_str(t.get('operator'))},
                {_sql_str(t.get('level'))}, {dims.get('height') or 'NULL'},
                {geo.get('latitude', 0)}, {geo.get('longitude', 0)},
                {pos.get('x', 0)}, {pos.get('y', 0)}, {pos.get('z', 0)},
                {dims.get('width') or 'NULL'}, {dims.get('depth') or 'NULL'},
                {_sql_str(json.dumps(t.get('polygon', [])))},
                {_sql_str(json.dumps(t.get('geoPolygon', [])))},
                {t.get('color') or 'NULL'}, {t.get('osmId') or 'NULL'},
                'OSM', TIMESTAMP'{now}', TIMESTAMP'{now}'
            )""")
        _batch_insert(
            _table('terminals'),
            ["terminal_id", "icao_code", "name", "terminal_type", "operator", "level",
             "height", "center_lat", "center_lon",
             "position_x", "position_y", "position_z",
             "width", "depth", "polygon_json", "geo_polygon_json",
             "color", "osm_id", "source", "created_at", "updated_at"],
            values,
        )

    # --- taxiways ---
    taxiways = config.get("osmTaxiways", [])
    spark.sql(f"DELETE FROM {_table('taxiways')} WHERE icao_code = '{icao_code}'")
    if taxiways:
        values = []
        for t in taxiways:
            ref = t.get("id", t.get("ref", ""))
            taxiway_id = f"{icao_code}_{ref}"
            values.append(f"""(
                '{taxiway_id}', '{icao_code}',
                {_sql_str(t.get('ref') or t.get('id'))}, {_sql_str(t.get('name'))},
                {t.get('width') or 'NULL'}, {_sql_str(t.get('surface'))},
                {_sql_str(json.dumps(t.get('points', [])))},
                {_sql_str(json.dumps(t.get('geoPoints', [])))},
                {t.get('color') or 'NULL'}, {t.get('osmId') or 'NULL'},
                'OSM', TIMESTAMP'{now}', TIMESTAMP'{now}'
            )""")
        _batch_insert(
            _table('taxiways'),
            ["taxiway_id", "icao_code", "ref", "name", "width", "surface",
             "points_json", "geo_points_json", "color", "osm_id", "source",
             "created_at", "updated_at"],
            values,
        )

    # --- aprons ---
    aprons = config.get("osmAprons", [])
    spark.sql(f"DELETE FROM {_table('aprons')} WHERE icao_code = '{icao_code}'")
    if aprons:
        values = []
        for a in aprons:
            ref = a.get("id", a.get("ref", ""))
            apron_id = f"{icao_code}_{ref}"
            geo = a.get("geo", {})
            pos = a.get("position", {})
            dims = a.get("dimensions", {})
            values.append(f"""(
                '{apron_id}', '{icao_code}',
                {_sql_str(a.get('ref') or a.get('id'))}, {_sql_str(a.get('name'))},
                {_sql_str(a.get('surface'))},
                {geo.get('latitude', 0)}, {geo.get('longitude', 0)},
                {pos.get('x', 0)}, {pos.get('y', 0)}, {pos.get('z', 0)},
                {dims.get('width') or 'NULL'}, {dims.get('depth') or 'NULL'},
                {_sql_str(json.dumps(a.get('polygon', [])))},
                {_sql_str(json.dumps(a.get('geoPolygon', [])))},
                {a.get('color') or 'NULL'}, {a.get('osmId') or 'NULL'},
                'OSM', TIMESTAMP'{now}', TIMESTAMP'{now}'
            )""")
        _batch_insert(
            _table('aprons'),
            ["apron_id", "icao_code", "ref", "name", "surface",
             "center_lat", "center_lon",
             "position_x", "position_y", "position_z",
             "width", "depth", "polygon_json", "geo_polygon_json",
             "color", "osm_id", "source", "created_at", "updated_at"],
            values,
        )

    # --- buildings ---
    buildings = config.get("buildings", [])
    spark.sql(f"DELETE FROM {_table('buildings')} WHERE icao_code = '{icao_code}'")
    if buildings:
        values = []
        for b in buildings:
            building_id = f"{icao_code}_{b.get('id', b.get('osmId', ''))}"
            geo = b.get("geo", {})
            pos = b.get("position", {})
            dims = b.get("dimensions", {})
            values.append(f"""(
                '{building_id}', '{icao_code}', {_sql_str(b.get('name'))},
                {_sql_str(b.get('type', 'building'))}, {_sql_str(b.get('operator'))},
                {dims.get('height') or 'NULL'},
                {geo.get('latitude', 0)}, {geo.get('longitude', 0)},
                {pos.get('x', 0)}, {pos.get('y', 0)}, {pos.get('z', 0)},
                {dims.get('width') or 'NULL'}, {dims.get('depth') or 'NULL'},
                {_sql_str(json.dumps(b.get('polygon', [])))},
                {_sql_str(json.dumps(b.get('geoPolygon', [])))},
                {b.get('color') or 'NULL'},
                {_sql_str(b.get('ifcGuid'))}, {b.get('osmId') or 'NULL'},
                {_sql_str(b.get('source', 'OSM'))},
                TIMESTAMP'{now}', TIMESTAMP'{now}'
            )""")
        _batch_insert(
            _table('buildings'),
            ["building_id", "icao_code", "name", "building_type", "operator",
             "height", "center_lat", "center_lon",
             "position_x", "position_y", "position_z",
             "width", "depth", "polygon_json", "geo_polygon_json",
             "color", "ifc_guid", "osm_id", "source",
             "created_at", "updated_at"],
            values,
        )

    # --- hangars ---
    hangars = config.get("osmHangars", [])
    spark.sql(f"DELETE FROM {_table('hangars')} WHERE icao_code = '{icao_code}'")
    if hangars:
        values = []
        for h in hangars:
            hangar_id = f"{icao_code}_{h.get('id', h.get('osmId', ''))}"
            geo = h.get("geo", {})
            pos = h.get("position", {})
            dims = h.get("dimensions", {})
            values.append(f"""(
                '{hangar_id}', '{icao_code}', {_sql_str(h.get('name'))},
                {_sql_str(h.get('operator'))}, {dims.get('height') or 'NULL'},
                {geo.get('latitude', 0)}, {geo.get('longitude', 0)},
                {pos.get('x', 0)}, {pos.get('y', 0)}, {pos.get('z', 0)},
                {dims.get('width') or 'NULL'}, {dims.get('depth') or 'NULL'},
                {_sql_str(json.dumps(h.get('polygon', [])))},
                {_sql_str(json.dumps(h.get('geoPolygon', [])))},
                {h.get('color') or 'NULL'}, {h.get('osmId') or 'NULL'},
                'OSM', TIMESTAMP'{now}', TIMESTAMP'{now}'
            )""")
        _batch_insert(
            _table('hangars'),
            ["hangar_id", "icao_code", "name", "operator",
             "height", "center_lat", "center_lon",
             "position_x", "position_y", "position_z",
             "width", "depth", "polygon_json", "geo_polygon_json",
             "color", "osm_id", "source", "created_at", "updated_at"],
            values,
        )

    # --- helipads ---
    helipads = config.get("osmHelipads", [])
    spark.sql(f"DELETE FROM {_table('helipads')} WHERE icao_code = '{icao_code}'")
    if helipads:
        values = []
        for h in helipads:
            ref = h.get("ref") or h.get("id", "")
            helipad_id = f"{icao_code}_{ref}"
            geo = h.get("geo", {})
            pos = h.get("position", {})
            values.append(f"""(
                '{helipad_id}', '{icao_code}', {_sql_str(h.get('ref'))},
                {_sql_str(h.get('name'))},
                {geo.get('latitude', 0)}, {geo.get('longitude', 0)},
                {h.get('elevation') or 'NULL'},
                {pos.get('x', 0)}, {pos.get('y', 0)}, {pos.get('z', 0)},
                {h.get('osmId') or 'NULL'}, 'OSM', TIMESTAMP'{now}', TIMESTAMP'{now}'
            )""")
        _batch_insert(
            _table('helipads'),
            ["helipad_id", "icao_code", "ref", "name",
             "latitude", "longitude", "elevation",
             "position_x", "position_y", "position_z",
             "osm_id", "source", "created_at", "updated_at"],
            values,
        )

    # --- parking_positions ---
    parking = config.get("osmParkingPositions", [])
    spark.sql(f"DELETE FROM {_table('parking_positions')} WHERE icao_code = '{icao_code}'")
    if parking:
        values = []
        for p in parking:
            ref = p.get("ref") or p.get("id", "")
            pp_id = f"{icao_code}_{ref}"
            geo = p.get("geo", {})
            pos = p.get("position", {})
            values.append(f"""(
                '{pp_id}', '{icao_code}', {_sql_str(p.get('ref'))},
                {_sql_str(p.get('name'))},
                {geo.get('latitude', 0)}, {geo.get('longitude', 0)},
                {p.get('elevation') or 'NULL'},
                {pos.get('x', 0)}, {pos.get('y', 0)}, {pos.get('z', 0)},
                {p.get('osmId') or 'NULL'}, 'OSM', TIMESTAMP'{now}', TIMESTAMP'{now}'
            )""")
        _batch_insert(
            _table('parking_positions'),
            ["parking_position_id", "icao_code", "ref", "name",
             "latitude", "longitude", "elevation",
             "position_x", "position_y", "position_z",
             "osm_id", "source", "created_at", "updated_at"],
            values,
        )

    # --- osm_runways ---
    osm_runways = config.get("osmRunways", [])
    spark.sql(f"DELETE FROM {_table('osm_runways')} WHERE icao_code = '{icao_code}'")
    if osm_runways:
        values = []
        for r in osm_runways:
            ref = r.get("id", r.get("ref", ""))
            runway_id = f"{icao_code}_{ref}"
            values.append(f"""(
                '{runway_id}', '{icao_code}',
                {_sql_str(r.get('ref') or r.get('id'))}, {_sql_str(r.get('name'))},
                {r.get('width') or 'NULL'}, {_sql_str(r.get('surface'))},
                {_sql_str(json.dumps(r.get('points', [])))},
                {_sql_str(json.dumps(r.get('geoPoints', [])))},
                {r.get('color') or 'NULL'}, {r.get('osmId') or 'NULL'},
                'OSM', TIMESTAMP'{now}', TIMESTAMP'{now}'
            )""")
        _batch_insert(
            _table('osm_runways'),
            ["osm_runway_id", "icao_code", "ref", "name", "width", "surface",
             "points_json", "geo_points_json", "color", "osm_id", "source",
             "created_at", "updated_at"],
            values,
        )


print("persist_via_spark() defined.")

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

        # Persist to UC tables via Spark SQL
        try:
            # Use full config from service (includes FAA data if merged)
            full_config = service.get_config() or config
            persist_via_spark(icao, full_config, info)
            print(f"  Persisted to UC tables via Spark SQL")
        except Exception as e:
            print(f"  WARNING: Spark SQL persistence failed: {type(e).__name__}: {e}")
            traceback.print_exc()

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

# Verify persistence
try:
    count_df = spark.sql(f"SELECT count(*) as cnt FROM {UC_CATALOG}.{UC_SCHEMA}.airport_metadata")
    total_persisted = count_df.collect()[0].cnt
    print(f"\nVerification: {total_persisted} airports in airport_metadata table")
except Exception as e:
    print(f"\nVerification query failed: {e}")

# COMMAND ----------

dbutils.notebook.exit(json.dumps({
    "already_cached": len(already_cached),
    "loaded": len(loaded),
    "failed": len(failed),
    "total": len(WELL_KNOWN_AIRPORTS),
    "failed_details": [{"icao": r["icao"], "error": r["error"]} for r in failed],
    "loaded_details": [{"icao": r["icao"], "gates": r["gates"]} for r in loaded],
}))

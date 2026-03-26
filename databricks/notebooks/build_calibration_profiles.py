# Databricks notebook source
# MAGIC %md
# MAGIC # Build Airport Calibration Profiles
# MAGIC
# MAGIC Builds per-airport statistical profiles from available data sources
# MAGIC (BTS T-100, OpenSky, OurAirports, or fallback) and persists them to
# MAGIC the Unity Catalog `airport_profiles` table.
# MAGIC
# MAGIC **Parameters:**
# MAGIC - `airports`: Comma-separated IATA codes (default: all known airports)
# MAGIC - `fallback_only`: If "true", build from hardcoded distributions only
# MAGIC - `catalog`: Unity Catalog name
# MAGIC - `schema`: Schema name

# COMMAND ----------

%pip install pyyaml pydantic --quiet

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

dbutils.widgets.text("airports", "", "Airport IATA codes (comma-separated, empty=all)")
dbutils.widgets.text("fallback_only", "false", "Fallback only (true/false)")
dbutils.widgets.text("catalog", "serverless_stable_3n0ihb_catalog", "UC Catalog")
dbutils.widgets.text("schema", "airport_digital_twin", "UC Schema")

airports_raw = dbutils.widgets.get("airports").strip()
fallback_only = dbutils.widgets.get("fallback_only").lower() == "true"
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")

print(f"Airports:      {airports_raw or '(all known)'}")
print(f"Fallback only: {fallback_only}")
print(f"Target:        {catalog}.{schema}.airport_profiles")

# COMMAND ----------

import os, sys

# Add repo root to path (DABs syncs files to CWD)
repo_root = os.getcwd()
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from src.calibration.profile import _build_fallback_profile, AirportProfile, _iata_to_icao
from src.calibration.profile_builder import build_profiles, US_AIRPORTS, INTERNATIONAL_AIRPORTS

if airports_raw:
    airports = [a.strip() for a in airports_raw.split(",")]
else:
    airports = US_AIRPORTS + INTERNATIONAL_AIRPORTS

print(f"Building profiles for {len(airports)} airports")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Build Profiles

# COMMAND ----------

if fallback_only:
    profiles = []
    for iata in airports:
        p = _build_fallback_profile(iata)
        profiles.append(p)
        print(f"  {p.iata_code} ({p.icao_code}): fallback")
else:
    profiles = build_profiles(
        airports=airports,
        raw_data_dir=None,
        output_dir=None,
        use_opensky=False,
    )

print(f"\nBuilt {len(profiles)} profiles")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Persist to Unity Catalog

# COMMAND ----------

from databricks.sdk import WorkspaceClient
from src.calibration.profile import save_batch_to_unity_catalog

# Get warehouse ID from environment (set by app.yaml or job config)
warehouse_id = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
if not warehouse_id:
    # Try spark conf
    try:
        warehouse_id = spark.conf.get("spark.databricks.sql.warehouse.id", "")
    except Exception:
        pass

if not warehouse_id:
    print("WARNING: No warehouse ID found. Set DATABRICKS_WAREHOUSE_ID or pass via job config.")
    print("Skipping UC persistence.")
    dbutils.notebook.exit("no_warehouse_id")

client = WorkspaceClient()
persisted = save_batch_to_unity_catalog(profiles, client, warehouse_id, catalog, schema)

print(f"\nPersisted {persisted}/{len(profiles)} profiles to {catalog}.{schema}.airport_profiles")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary

# COMMAND ----------

summary = []
for p in profiles:
    top_airlines = sorted(p.airline_shares.items(), key=lambda x: -x[1])[:3]
    summary.append({
        "icao": p.icao_code,
        "iata": p.iata_code,
        "source": p.data_source,
        "airlines": len(p.airline_shares),
        "top_airline": top_airlines[0][0] if top_airlines else "?",
        "top_share": f"{top_airlines[0][1]:.0%}" if top_airlines else "?",
        "delay_rate": f"{p.delay_rate:.0%}",
        "domestic_ratio": f"{p.domestic_ratio:.0%}",
        "sample_size": p.sample_size,
    })

df = spark.createDataFrame(summary)
display(df)

# COMMAND ----------

dbutils.notebook.exit(f"success: {len(profiles)} profiles built, {persisted} persisted")

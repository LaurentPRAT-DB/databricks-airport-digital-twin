# Databricks notebook source
# MAGIC %md
# MAGIC # Persist MSFS BGL Airport Data to Lakehouse
# MAGIC
# MAGIC Reads MSFS scenery ZIP files from a UC volume, parses gates/runways via the
# MAGIC BGL parser, and persists the airport config to Unity Catalog tables.
# MAGIC
# MAGIC **Volume path:** `/Volumes/serverless_stable_3n0ihb_catalog/airport_digital_twin/simulation_data/msfs_scenery/`

# COMMAND ----------

import sys
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("persist_msfs")

# Add project root to path so our src modules are importable
# (DABs deploys the full repo to the workspace files path)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(""))))
# In a Databricks notebook __file__ isn't available; use the workspace files path
for candidate in [
    "/Workspace/Users/laurent.prat@databricks.com/.bundle/airport-digital-twin/dev/files",
    project_root,
]:
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

# COMMAND ----------

from src.formats.msfs.parser import MSFSParser
from src.formats.msfs.converter import MSFSConverter
from src.formats.base import CoordinateConverter
from src.persistence.airport_repository import AirportRepository

# COMMAND ----------

VOLUME_BASE = "/Volumes/serverless_stable_3n0ihb_catalog/airport_digital_twin/simulation_data/msfs_scenery"
CATALOG = "serverless_stable_3n0ihb_catalog"
SCHEMA = "airport_digital_twin"
WAREHOUSE_ID = "b868e84cedeb4262"

# Map of filename → ICAO code (BGL files don't always carry the code internally)
SCENERY_FILES = {
    "lsgg.zip": "LSGG",
    "lgav.zip": "LGAV",
}

# COMMAND ----------

# Set up repository (uses WorkspaceClient in notebook context)
repo = AirportRepository(
    catalog=CATALOG,
    schema=SCHEMA,
    warehouse_id=WAREHOUSE_ID,
)

parser = MSFSParser()
results = []

for filename, icao_code in SCENERY_FILES.items():
    filepath = f"{VOLUME_BASE}/{filename}"
    logger.info(f"Processing {icao_code} from {filepath}...")

    try:
        # Read file from volume
        with open(filepath, "rb") as f:
            data = f.read()
        logger.info(f"  Read {len(data)} bytes")

        # Parse BGL/ZIP
        doc = parser.parse(data, source_path=filename)
        if not doc.icao_code:
            doc.icao_code = icao_code

        logger.info(f"  Parsed: {doc.airport_name}, {len(doc.parking_spots)} parking, {len(doc.runways)} runways")

        # Convert to internal config format
        converter = CoordinateConverter(reference_lat=doc.lat, reference_lon=doc.lon)
        msfs_converter = MSFSConverter(converter)
        config = msfs_converter.to_config(doc)
        config["icaoCode"] = icao_code

        gate_count = len(config.get("gates", []))
        runway_count = len(config.get("osmRunways", []))
        logger.info(f"  Config: {gate_count} gates, {runway_count} runways")

        # Persist to Unity Catalog
        logger.info(f"  Persisting {icao_code} to Unity Catalog...")
        repo.save_airport_config(icao_code, config)
        logger.info(f"  {icao_code} persisted successfully!")

        results.append({
            "icao": icao_code,
            "name": doc.airport_name,
            "gates": gate_count,
            "runways": runway_count,
            "status": "OK",
        })

    except Exception as e:
        logger.error(f"  Failed to process {icao_code}: {e}", exc_info=True)
        results.append({
            "icao": icao_code,
            "status": f"FAILED: {e}",
        })

# COMMAND ----------

# Print summary
print("\n=== Persistence Results ===")
for r in results:
    if r["status"] == "OK":
        print(f"  {r['icao']}: {r['name']} — {r['gates']} gates, {r['runways']} runways ✓")
    else:
        print(f"  {r['icao']}: {r['status']}")

# COMMAND ----------

# Verify: list all persisted airports
print("\n=== All Persisted Airports ===")
airports = repo.list_airports()
for a in airports:
    print(f"  {a.get('icao_code')}: {a.get('name')} (sources: {a.get('data_sources')}, updated: {a.get('updated_at')})")

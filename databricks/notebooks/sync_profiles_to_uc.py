# Databricks notebook source
# MAGIC %md
# MAGIC # Sync Calibration Profiles to Unity Catalog
# MAGIC
# MAGIC One-time bulk upload of all local JSON calibration profiles into the
# MAGIC `airport_profiles` Delta table. Safe to re-run — uses MERGE (upsert).
# MAGIC
# MAGIC **Parameters:**
# MAGIC - `catalog`: Unity Catalog name
# MAGIC - `schema`: Schema name

# COMMAND ----------

%pip install pyyaml pydantic --quiet

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

dbutils.widgets.text("catalog", "serverless_stable_3n0ihb_catalog", "UC Catalog")
dbutils.widgets.text("schema", "airport_digital_twin", "UC Schema")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")

print(f"Target: {catalog}.{schema}.airport_profiles")

# COMMAND ----------

import os, sys
from pathlib import Path

repo_root = os.getcwd()
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from src.calibration.profile import AirportProfile, save_to_unity_catalog

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load All Local Profiles

# COMMAND ----------

profiles_dir = Path(repo_root) / "data" / "calibration" / "profiles"
json_files = sorted(profiles_dir.glob("*.json"))
print(f"Found {len(json_files)} profile JSON files in {profiles_dir}")

profiles = []
errors = []
for f in json_files:
    try:
        p = AirportProfile.load(f)
        profiles.append(p)
    except Exception as e:
        errors.append((f.stem, str(e)))

print(f"Loaded {len(profiles)} profiles ({len(errors)} errors)")
if errors:
    for code, err in errors[:10]:
        print(f"  ERROR {code}: {err}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Ensure Table Exists

# COMMAND ----------

from databricks.sdk import WorkspaceClient

warehouse_id = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
if not warehouse_id:
    try:
        warehouse_id = spark.conf.get("spark.databricks.sql.warehouse.id", "")
    except Exception:
        pass

if not warehouse_id:
    print("ERROR: No warehouse ID found.")
    dbutils.notebook.exit("no_warehouse_id")

client = WorkspaceClient()

# Create table if it doesn't exist
from src.persistence.airport_tables import AIRPORT_PROFILES_DDL
ddl = AIRPORT_PROFILES_DDL.format(catalog=catalog, schema=schema)
client.statement_execution.execute_statement(
    warehouse_id=warehouse_id,
    statement=ddl,
    wait_timeout="30s",
)
print(f"Table {catalog}.{schema}.airport_profiles ready")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Bulk Upload

# COMMAND ----------

persisted = 0
failed = 0

for i, p in enumerate(profiles):
    ok = save_to_unity_catalog(p, client, warehouse_id, catalog, schema)
    if ok:
        persisted += 1
    else:
        failed += 1
    if (i + 1) % 100 == 0:
        print(f"  Progress: {i + 1}/{len(profiles)} ({persisted} ok, {failed} failed)")

print(f"\nDone: {persisted}/{len(profiles)} persisted, {failed} failed")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verify

# COMMAND ----------

from databricks.sdk.service.sql import StatementState

response = client.statement_execution.execute_statement(
    warehouse_id=warehouse_id,
    statement=f"SELECT COUNT(*) AS cnt, COUNT(DISTINCT data_source) AS sources FROM {catalog}.{schema}.airport_profiles",
    wait_timeout="30s",
)

if response.status and response.status.state == StatementState.SUCCEEDED and response.result:
    row = response.result.data_array[0]
    print(f"Table has {row[0]} profiles from {row[1]} distinct data sources")

# COMMAND ----------

dbutils.notebook.exit(f"success: {persisted} profiles synced to UC")

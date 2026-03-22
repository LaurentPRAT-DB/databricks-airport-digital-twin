# Databricks notebook source
# MAGIC %md
# MAGIC # Sync Lakebase Data to Delta (Lakehouse)
# MAGIC
# MAGIC This notebook reads operational tables from Lakebase PostgreSQL and writes them
# MAGIC to Delta tables in Unity Catalog. This populates the lakehouse for analytics,
# MAGIC Genie Spaces, and DLT downstream processing.
# MAGIC
# MAGIC **Direction:** Lakebase (PostgreSQL) → Delta (Unity Catalog)

# COMMAND ----------

# MAGIC %pip install psycopg2-binary databricks-sdk

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timezone
from pyspark.sql import Row
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, LongType,
    DoubleType, BooleanType, TimestampType, FloatType,
)

# Configuration
CATALOG = "serverless_stable_3n0ihb_catalog"
SCHEMA = "airport_digital_twin"

# Lakebase Autoscaling configuration
LAKEBASE_HOST = "ep-summer-scene-d2ew95fl.database.us-east-1.cloud.databricks.com"
LAKEBASE_DATABASE = "databricks_postgres"
LAKEBASE_ENDPOINT_NAME = "projects/airport-digital-twin/branches/production/endpoints/primary"

print(f"Syncing from Lakebase to {CATALOG}.{SCHEMA}")
print(f"Lakebase host: {LAKEBASE_HOST}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Get Lakebase Autoscaling credentials

# COMMAND ----------

from databricks.sdk import WorkspaceClient

try:
    w = WorkspaceClient()
    cred = w.postgres.generate_database_credential(endpoint=LAKEBASE_ENDPOINT_NAME)
    me = w.current_user.me()
    db_token = cred.token
    user_email = me.user_name
    print(f"Using Databricks SDK OAuth for Lakebase as: {user_email}")
    print(f"Lakebase token obtained: {'Yes' if db_token else 'No'}")

except Exception as e:
    print(f"SDK approach failed: {e}")
    print("Falling back to REST API credential generation...")
    import requests
    import json
    import traceback
    traceback.print_exc()

    try:
        ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
        api_token = ctx.apiToken().get()
        workspace_host = ctx.apiUrl().get()
        user_email = ctx.userName().get()

        headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
        resp = requests.post(
            f"{workspace_host}/api/2.0/postgres/credentials",
            headers=headers,
            json={"endpoint": LAKEBASE_ENDPOINT_NAME}
        )

        if resp.status_code == 200:
            db_token = resp.json().get("token")
            print(f"REST API credential obtained for: {user_email}")
        else:
            raise RuntimeError(f"Credential generation failed (status {resp.status_code}): {resp.text}")

    except Exception as e2:
        print(f"ERROR: All credential methods failed: {e2}")
        dbutils.notebook.exit(f"ERROR: Cannot authenticate to Lakebase - {e2}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Connect to Lakebase

# COMMAND ----------

def get_lakebase_connection():
    """Create a connection to Lakebase PostgreSQL."""
    return psycopg2.connect(
        host=LAKEBASE_HOST,
        port=5432,
        database=LAKEBASE_DATABASE,
        user=user_email,
        password=db_token,
        sslmode="require"
    )

conn = get_lakebase_connection()
print("Connected to Lakebase successfully!")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Define table sync configurations

# COMMAND ----------

# Snapshot tables: full overwrite each sync
SNAPSHOT_TABLES = {
    "flight_status": {
        "query": "SELECT * FROM flight_status",
        "delta_table": "flight_status_gold",
    },
    "baggage_status": {
        "query": "SELECT * FROM baggage_status",
        "delta_table": "baggage_status_gold",
    },
    "flight_schedule": {
        "query": "SELECT * FROM flight_schedule",
        "delta_table": "flight_schedule",
    },
    "gse_fleet": {
        "query": "SELECT * FROM gse_fleet",
        "delta_table": "gse_fleet",
    },
    "gse_turnaround": {
        "query": "SELECT * FROM gse_turnaround",
        "delta_table": "gse_turnaround",
    },
    "weather_observations": {
        "query": "SELECT * FROM weather_observations",
        "delta_table": "weather_observations",
    },
}

# Append tables: incremental by max id
APPEND_TABLES = {
    "flight_position_snapshots": {
        "query_template": "SELECT * FROM flight_position_snapshots WHERE id > {max_id} ORDER BY id",
        "delta_table": "flight_position_snapshots",
        "id_column": "id",
    },
    "flight_phase_transitions": {
        "query_template": "SELECT * FROM flight_phase_transitions WHERE id > {max_id} ORDER BY id",
        "delta_table": "flight_phase_transitions",
        "id_column": "id",
    },
}

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Sync snapshot tables (overwrite)

# COMMAND ----------

sync_results = {}

for pg_table, config in SNAPSHOT_TABLES.items():
    delta_table = f"{CATALOG}.{SCHEMA}.{config['delta_table']}"
    try:
        conn = get_lakebase_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(config["query"])
            rows = cur.fetchall()
        conn.close()

        if not rows:
            print(f"  {pg_table}: 0 rows (skipping)")
            sync_results[pg_table] = {"status": "empty", "rows": 0}
            continue

        # Convert to Spark DataFrame — let Spark infer schema from dicts
        dict_rows = [dict(row) for row in rows]
        df = spark.createDataFrame(dict_rows)

        df.write.mode("overwrite").option("mergeSchema", "true").saveAsTable(delta_table)

        row_count = df.count()
        print(f"  {pg_table} -> {delta_table}: {row_count} rows (overwrite)")
        sync_results[pg_table] = {"status": "ok", "rows": row_count}

    except Exception as e:
        print(f"  ERROR syncing {pg_table}: {e}")
        sync_results[pg_table] = {"status": "error", "error": str(e)}

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Sync append tables (incremental)

# COMMAND ----------

for pg_table, config in APPEND_TABLES.items():
    delta_table = f"{CATALOG}.{SCHEMA}.{config['delta_table']}"
    id_col = config["id_column"]

    try:
        # Get current max id from Delta table (0 if table doesn't exist)
        max_id = 0
        try:
            result = spark.sql(f"SELECT COALESCE(MAX({id_col}), 0) as max_id FROM {delta_table}")
            max_id = result.collect()[0].max_id
        except Exception:
            print(f"  {pg_table}: Delta table does not exist yet, starting from id=0")

        # Fetch new rows from Lakebase
        query = config["query_template"].format(max_id=max_id)
        conn = get_lakebase_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query)
            rows = cur.fetchall()
        conn.close()

        if not rows:
            print(f"  {pg_table}: 0 new rows since id={max_id}")
            sync_results[pg_table] = {"status": "no_new", "rows": 0, "max_id": max_id}
            continue

        dict_rows = [dict(row) for row in rows]
        df = spark.createDataFrame(dict_rows)

        df.write.mode("append").option("mergeSchema", "true").saveAsTable(delta_table)

        new_count = df.count()
        new_max = df.agg({id_col: "max"}).collect()[0][0]
        print(f"  {pg_table} -> {delta_table}: {new_count} new rows (id {max_id} -> {new_max})")
        sync_results[pg_table] = {"status": "ok", "rows": new_count, "max_id": new_max}

    except Exception as e:
        print(f"  ERROR syncing {pg_table}: {e}")
        sync_results[pg_table] = {"status": "error", "error": str(e)}

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Summary

# COMMAND ----------

print(f"\n{'='*60}")
print(f"Lakebase -> Delta sync completed at {datetime.now(timezone.utc).isoformat()}")
print(f"{'='*60}")

total_rows = 0
errors = 0
for table, result in sync_results.items():
    status = result["status"]
    rows = result.get("rows", 0)
    total_rows += rows
    if status == "error":
        errors += 1
        print(f"  FAIL  {table}: {result['error'][:80]}")
    elif status in ("empty", "no_new"):
        print(f"  SKIP  {table}: no data")
    else:
        print(f"  OK    {table}: {rows} rows")

print(f"\nTotal rows synced: {total_rows}")
print(f"Errors: {errors}")
print(f"{'='*60}")

exit_msg = f"SUCCESS: {total_rows} rows synced across {len(sync_results)} tables, {errors} errors"
dbutils.notebook.exit(exit_msg)

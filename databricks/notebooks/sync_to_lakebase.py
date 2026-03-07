# Databricks notebook source
# MAGIC %md
# MAGIC # Sync Delta Gold Tables to Lakebase
# MAGIC
# MAGIC This notebook syncs flight data from the Delta Gold layer to Lakebase PostgreSQL
# MAGIC for low-latency frontend serving.

# COMMAND ----------

# MAGIC %pip install psycopg2-binary

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import psycopg2
from datetime import datetime, timezone

# Configuration - hardcoded for this workspace
CATALOG = "serverless_stable_3n0ihb_catalog"
SCHEMA = "airport_digital_twin"

# Lakebase Autoscaling configuration
LAKEBASE_HOST = "ep-summer-scene-d2ew95fl.database.us-east-1.cloud.databricks.com"
LAKEBASE_DATABASE = "databricks_postgres"
LAKEBASE_ENDPOINT_NAME = "projects/airport-digital-twin/branches/production/endpoints/primary"

print(f"Syncing from {CATALOG}.{SCHEMA}.flight_status_gold to Lakebase")
print(f"Lakebase host: {LAKEBASE_HOST}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Check if Gold table exists

# COMMAND ----------

# Check if the Gold table exists
table_name = f"{CATALOG}.{SCHEMA}.flight_status_gold"
try:
    result = spark.sql(f"DESCRIBE TABLE {table_name}")
    print(f"Table {table_name} exists")
except Exception as e:
    error_msg = str(e)
    if "TABLE_OR_VIEW_NOT_FOUND" in error_msg or "does not exist" in error_msg.lower():
        print(f"ERROR: Table {table_name} does not exist!")
        print("Please run the DLT pipeline first to create and populate the Gold table.")
        dbutils.notebook.exit("NO_DATA: Gold table does not exist")
    else:
        raise e

# COMMAND ----------

# Get row count
row_count = spark.sql(f"SELECT COUNT(*) as cnt FROM {table_name}").collect()[0].cnt
print(f"Gold table has {row_count} rows")

if row_count == 0:
    print("WARNING: Gold table is empty.")
    dbutils.notebook.exit("NO_DATA: Gold table is empty")

# COMMAND ----------

# Preview data
display(spark.sql(f"SELECT * FROM {table_name} LIMIT 5"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Get Lakebase Autoscaling credentials

# COMMAND ----------

# Get OAuth credentials for Lakebase Autoscaling via REST API
import requests
import json

try:
    # Get the notebook context token and host
    ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
    db_token = ctx.apiToken().get()
    workspace_host = ctx.apiUrl().get()
    user_email = ctx.userName().get()

    # Generate Lakebase credential via REST API
    headers = {"Authorization": f"Bearer {db_token}", "Content-Type": "application/json"}
    resp = requests.post(
        f"{workspace_host}/api/2.0/lakebase/postgres/credentials/generate",
        headers=headers,
        json={"endpoint": LAKEBASE_ENDPOINT_NAME}
    )

    if resp.status_code == 200:
        lakebase_token = resp.json().get("token")
        print(f"Using OAuth for Lakebase Autoscaling as: {user_email}")
        print(f"Lakebase token obtained: {'Yes' if lakebase_token else 'No'}")
        db_token = lakebase_token  # Use Lakebase-specific token
    else:
        print(f"Could not get Lakebase credential (status {resp.status_code}): {resp.text}")
        print("Falling back to notebook API token")

except Exception as e:
    print(f"WARNING: Could not get Lakebase credentials via API: {e}")
    print("Falling back to notebook API token")
    db_token = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get()
    user_email = "laurent.prat@databricks.com"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Sync data to Lakebase

# COMMAND ----------

# Get flight data from Gold table
flights_df = spark.sql(f"""
    SELECT
        icao24,
        callsign,
        origin_country,
        latitude,
        longitude,
        altitude,
        velocity,
        heading,
        on_ground,
        vertical_rate,
        last_seen,
        flight_phase,
        data_source
    FROM {CATALOG}.{SCHEMA}.flight_status_gold
    WHERE last_seen > current_timestamp() - INTERVAL 10 MINUTES
""")

flights = flights_df.collect()
print(f"Found {len(flights)} flights to sync (from last 10 minutes)")

# If no recent flights, get all flights
if len(flights) == 0:
    print("No recent flights. Getting all flights from Gold table...")
    flights_df = spark.sql(f"""
        SELECT
            icao24,
            callsign,
            origin_country,
            latitude,
            longitude,
            altitude,
            velocity,
            heading,
            on_ground,
            vertical_rate,
            last_seen,
            flight_phase,
            data_source
        FROM {CATALOG}.{SCHEMA}.flight_status_gold
        LIMIT 100
    """)
    flights = flights_df.collect()
    print(f"Found {len(flights)} flights total")

# COMMAND ----------

if len(flights) == 0:
    print("No flights to sync")
    dbutils.notebook.exit("NO_DATA: No flights in Gold table")

# Connect to Lakebase using user's OAuth token
print(f"Connecting to Lakebase at {LAKEBASE_HOST}...")
try:
    conn = psycopg2.connect(
        host=LAKEBASE_HOST,
        port=5432,
        database=LAKEBASE_DATABASE,
        user=user_email,
        password=db_token,
        sslmode="require"
    )
    print("Connected to Lakebase successfully!")
except Exception as e:
    print(f"ERROR connecting to Lakebase: {e}")
    dbutils.notebook.exit(f"ERROR: Failed to connect to Lakebase - {e}")

# COMMAND ----------

upsert_sql = """
    INSERT INTO flight_status (
        icao24, callsign, origin_country, latitude, longitude,
        altitude, velocity, heading, on_ground, vertical_rate,
        last_seen, flight_phase, data_source
    ) VALUES (
        %(icao24)s, %(callsign)s, %(origin_country)s, %(latitude)s, %(longitude)s,
        %(altitude)s, %(velocity)s, %(heading)s, %(on_ground)s, %(vertical_rate)s,
        %(last_seen)s, %(flight_phase)s, %(data_source)s
    )
    ON CONFLICT (icao24) DO UPDATE SET
        callsign = EXCLUDED.callsign,
        origin_country = EXCLUDED.origin_country,
        latitude = EXCLUDED.latitude,
        longitude = EXCLUDED.longitude,
        altitude = EXCLUDED.altitude,
        velocity = EXCLUDED.velocity,
        heading = EXCLUDED.heading,
        on_ground = EXCLUDED.on_ground,
        vertical_rate = EXCLUDED.vertical_rate,
        last_seen = EXCLUDED.last_seen,
        flight_phase = EXCLUDED.flight_phase,
        data_source = EXCLUDED.data_source
"""

synced = 0
errors = 0
with conn.cursor() as cur:
    for row in flights:
        try:
            flight_data = {
                "icao24": row.icao24,
                "callsign": row.callsign,
                "origin_country": row.origin_country,
                "latitude": float(row.latitude) if row.latitude else None,
                "longitude": float(row.longitude) if row.longitude else None,
                "altitude": float(row.altitude) if row.altitude else None,
                "velocity": float(row.velocity) if row.velocity else None,
                "heading": float(row.heading) if row.heading else None,
                "on_ground": bool(row.on_ground) if row.on_ground is not None else False,
                "vertical_rate": float(row.vertical_rate) if row.vertical_rate else None,
                "last_seen": row.last_seen,
                "flight_phase": row.flight_phase or "unknown",
                "data_source": row.data_source or "opensky"
            }
            cur.execute(upsert_sql, flight_data)
            synced += 1
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"Error syncing flight {row.icao24}: {e}")

conn.commit()
conn.close()

print(f"Successfully synced {synced} flights to Lakebase ({errors} errors)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Verify sync

# COMMAND ----------

# Reconnect and verify
conn = psycopg2.connect(
    host=LAKEBASE_HOST,
    port=5432,
    database=LAKEBASE_DATABASE,
    user=user_email,
    password=db_token,
    sslmode="require"
)

with conn.cursor() as cur:
    cur.execute("SELECT COUNT(*) FROM flight_status")
    total = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM flight_status WHERE last_seen > NOW() - INTERVAL '10 minutes'")
    recent = cur.fetchone()[0]

    print(f"Lakebase flight_status table:")
    print(f"  Total rows: {total}")
    print(f"  Recent (last 10 min): {recent}")

conn.close()

# COMMAND ----------

print(f"\n{'='*60}")
print(f"Sync completed at {datetime.now(timezone.utc).isoformat()}")
print(f"Flights synced: {synced}")
print(f"Errors: {errors}")
print(f"{'='*60}")

dbutils.notebook.exit(f"SUCCESS: {synced} flights synced, {errors} errors")

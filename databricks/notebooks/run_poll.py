# Databricks notebook source
# MAGIC %md
# MAGIC # OpenSky API Poll Job
# MAGIC This notebook executes a single poll cycle to fetch flight data from OpenSky API.

# COMMAND ----------

import json
import sys

# Add src to path if running from workspace
if "/Workspace/Repos/airport-digital-twin" not in sys.path:
    sys.path.insert(0, "/Workspace/Repos/airport-digital-twin")

# COMMAND ----------

from src.ingestion.databricks_job import run_poll_job

# COMMAND ----------

# Execute poll job
result = run_poll_job()

# Display results
print(f"Poll completed: {result['count']} flights, {result['duration']:.2f}s, status: {result['status']}")

# COMMAND ----------

# Return result as JSON for job output
dbutils.notebook.exit(json.dumps(result))

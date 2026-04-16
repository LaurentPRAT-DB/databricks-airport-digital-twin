# Databricks notebook source
# MAGIC %md
# MAGIC # List Simulation Configs
# MAGIC Returns all 7-day config file paths for the for-each task.

# COMMAND ----------

import os, json

nb_path = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
ws_path = "/Workspace" + nb_path
bundle_root = os.path.dirname(os.path.dirname(os.path.dirname(ws_path)))

configs_dir = os.path.join(bundle_root, "configs")
config_files = sorted(
    f"configs/{f}" for f in os.listdir(configs_dir) if f.endswith("_7day.yaml")
)

print(f"Found {len(config_files)} 7-day configs:")
for f in config_files:
    print(f"  {f}")

# COMMAND ----------

dbutils.jobs.taskValues.set(key="configs", value=config_files)
dbutils.notebook.exit(json.dumps({"count": len(config_files), "configs": config_files}))

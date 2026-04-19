# Databricks notebook source
# MAGIC %md
# MAGIC # List Simulation Configs
# MAGIC Returns 7-day config file paths for the for-each task.
# MAGIC Supports batching: set `batch` and `total_batches` to split configs across parallel jobs.

# COMMAND ----------

import os, json

dbutils.widgets.text("batch", "1")
dbutils.widgets.text("total_batches", "1")

batch = int(dbutils.widgets.get("batch"))
total_batches = int(dbutils.widgets.get("total_batches"))

nb_path = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
ws_path = "/Workspace" + nb_path
bundle_root = os.path.dirname(os.path.dirname(os.path.dirname(ws_path)))

configs_dir = os.path.join(bundle_root, "configs")
all_configs = sorted(
    f"configs/{f}" for f in os.listdir(configs_dir) if f.endswith("_7day.yaml")
)

# Split into batches if requested
if total_batches > 1:
    batch_size = -(-len(all_configs) // total_batches)  # ceiling division
    start = (batch - 1) * batch_size
    config_files = all_configs[start : start + batch_size]
    print(f"Batch {batch}/{total_batches}: {len(config_files)} of {len(all_configs)} configs")
else:
    config_files = all_configs
    print(f"Found {len(config_files)} 7-day configs (no batching)")

for f in config_files:
    print(f"  {f}")

# COMMAND ----------

dbutils.jobs.taskValues.set(key="configs", value=config_files)
dbutils.notebook.exit(json.dumps({"count": len(config_files), "configs": config_files}))

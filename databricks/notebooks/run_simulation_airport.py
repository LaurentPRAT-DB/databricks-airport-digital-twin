# Databricks notebook source
# MAGIC %md
# MAGIC # Single Airport Simulation
# MAGIC Runs one airport simulation based on widget parameters.
# MAGIC Called by the parallel simulation batch job.

# COMMAND ----------

# Only the 3 third-party packages the simulation CLI actually imports
%pip install pyyaml pydantic Faker --quiet

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# Parameters passed from the job
dbutils.widgets.text("airport", "SFO")
dbutils.widgets.text("config_file", "configs/simulation_sfo_1000.yaml")

airport = dbutils.widgets.get("airport")
config_file = dbutils.widgets.get("config_file")

print(f"Airport: {airport}")
print(f"Config:  {config_file}")

# COMMAND ----------

import os, sys, subprocess, json, time

# Derive bundle root from notebook path in workspace
# Notebook is at: .../files/databricks/notebooks/run_simulation_airport.py
# Bundle root is: .../files/
nb_path = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
print(f"Notebook path: {nb_path}")

# Convert workspace path to filesystem path
# /Users/x/.bundle/y/dev/files/databricks/notebooks/run_simulation_airport
# -> /Workspace/Users/x/.bundle/y/dev/files
ws_path = "/Workspace" + nb_path
bundle_root = os.path.dirname(os.path.dirname(os.path.dirname(ws_path)))
print(f"Bundle root: {bundle_root}")
print(f"Contents: {os.listdir(bundle_root)}")

# Verify config exists
config_path = os.path.join(bundle_root, config_file)
assert os.path.isfile(config_path), f"Config not found: {config_path}"

# Verify scenario exists
import yaml
with open(config_path) as f:
    config = yaml.safe_load(f)
scenario_file = config.get("scenario_file")
if scenario_file:
    scenario_path = os.path.join(bundle_root, scenario_file)
    assert os.path.isfile(scenario_path), f"Scenario not found: {scenario_path}"
    print(f"Scenario: {scenario_file}")

# Create output directory
sim_output = os.path.join(bundle_root, "simulation_output")
os.makedirs(sim_output, exist_ok=True)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Run Simulation

# COMMAND ----------

print(f"Starting {airport} simulation...")
start = time.time()

result = subprocess.run(
    [sys.executable, "-m", "src.simulation.cli", "--config", config_file],
    capture_output=True,
    text=True,
    cwd=bundle_root,
)

elapsed = time.time() - start
print(f"Completed in {elapsed:.1f}s (exit code: {result.returncode})")
print()

# Print full output
print(result.stdout)
if result.stderr:
    print(f"STDERR:\n{result.stderr[-2000:]}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verify Output

# COMMAND ----------

output_file = config.get("output_file", "")
output_path = os.path.join(bundle_root, output_file)

summary = {}
if os.path.isfile(output_path):
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"Output file: {output_file} ({size_mb:.1f} MB)")

    with open(output_path) as f:
        data = json.load(f)

    summary = data.get("summary", {})
    print(f"\nSummary for {airport}:")
    print(f"  Total flights:       {summary.get('total_flights', 0)}")
    print(f"  Arrivals:            {summary.get('arrivals', 0)}")
    print(f"  Departures:          {summary.get('departures', 0)}")
    print(f"  Spawned:             {summary.get('spawned_count', 0)}")
    print(f"  On-time %:           {summary.get('on_time_pct', 0):.1f}%")
    print(f"  Cancellation rate:   {summary.get('cancellation_rate_pct', 0):.1f}%")
    print(f"  Avg capacity hold:   {summary.get('avg_capacity_hold_min', 0):.1f} min")
    print(f"  Max capacity hold:   {summary.get('max_capacity_hold_min', 0):.1f} min")
    print(f"  Peak simultaneous:   {summary.get('peak_simultaneous_flights', 0)}")
    print(f"  Gates used:          {summary.get('gate_utilization_gates_used', 0)}")
    print(f"  Position snapshots:  {summary.get('total_position_snapshots', 0):,}")
    print(f"  Go-arounds:          {summary.get('total_go_arounds', 0)}")
    print(f"  Diversions:          {summary.get('total_diversions', 0)}")
    print(f"  Scenario:            {summary.get('scenario_name', 'N/A')}")
else:
    print(f"ERROR: Output file not found at {output_path}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Upload to Unity Catalog Volume

# COMMAND ----------

UC_CATALOG = "serverless_stable_3n0ihb_catalog"
UC_SCHEMA = "airport_digital_twin"
UC_VOLUME = "simulation_data"
VOLUME_PATH = f"/Volumes/{UC_CATALOG}/{UC_SCHEMA}/{UC_VOLUME}"

if os.path.isfile(output_path):
    import shutil
    dest = f"{VOLUME_PATH}/{os.path.basename(output_file)}"
    # UC Volumes are FUSE-mounted on serverless — use shutil directly
    os.makedirs(VOLUME_PATH, exist_ok=True)
    shutil.copy2(output_path, dest)
    print(f"Uploaded to UC Volume: {dest}")

    # Remove the workspace-local JSON to keep bundle dir under app snapshot size limit
    os.remove(output_path)
    print(f"Removed workspace copy: {output_path}")

    # Insert metadata row (MERGE to avoid duplicates on re-runs)
    # Get size from the Volume copy (local was already removed)
    size_bytes = os.path.getsize(dest)
    fname = os.path.basename(output_file)
    scenario_name = summary.get("scenario_name", "").replace("'", "''")

    merge_sql = f"""
    MERGE INTO {UC_CATALOG}.{UC_SCHEMA}.simulation_runs AS target
    USING (SELECT '{fname}' AS filename) AS source
    ON target.filename = source.filename
    WHEN MATCHED THEN UPDATE SET
        airport = '{airport}',
        scenario_name = '{scenario_name}',
        total_flights = {summary.get('total_flights', 0)},
        arrivals = {summary.get('arrivals', 0)},
        departures = {summary.get('departures', 0)},
        duration_hours = {config.get('duration_hours', 0)},
        on_time_pct = {summary.get('on_time_pct', 0)},
        cancellation_rate_pct = {summary.get('cancellation_rate_pct', 0)},
        peak_simultaneous_flights = {summary.get('peak_simultaneous_flights', 0)},
        total_go_arounds = {summary.get('total_go_arounds', 0)},
        total_diversions = {summary.get('total_diversions', 0)},
        size_bytes = {size_bytes},
        created_at = CURRENT_TIMESTAMP(),
        volume_path = '{dest}'
    WHEN NOT MATCHED THEN INSERT (
        filename, airport, scenario_name, total_flights, arrivals, departures,
        duration_hours, on_time_pct, cancellation_rate_pct, peak_simultaneous_flights,
        total_go_arounds, total_diversions, size_bytes, created_at, volume_path
    ) VALUES (
        '{fname}', '{airport}', '{scenario_name}',
        {summary.get('total_flights', 0)}, {summary.get('arrivals', 0)},
        {summary.get('departures', 0)}, {config.get('duration_hours', 0)},
        {summary.get('on_time_pct', 0)}, {summary.get('cancellation_rate_pct', 0)},
        {summary.get('peak_simultaneous_flights', 0)}, {summary.get('total_go_arounds', 0)},
        {summary.get('total_diversions', 0)}, {size_bytes}, CURRENT_TIMESTAMP(), '{dest}'
    )
    """
    spark.sql(merge_sql)
    print(f"Metadata inserted into {UC_CATALOG}.{UC_SCHEMA}.simulation_runs")
else:
    print("Skipping UC upload — no output file")

# COMMAND ----------

# Exit with status
success = result.returncode == 0
dbutils.notebook.exit(json.dumps({
    "status": "PASS" if success else "FAIL",
    "airport": airport,
    "elapsed_sec": round(elapsed, 1),
    "output_file": output_file,
    "total_flights": summary.get("total_flights", 0) if success else 0,
    "on_time_pct": summary.get("on_time_pct", 0) if success else 0,
}))

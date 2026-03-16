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
dbutils.widgets.text("config_file", "")
# Inline parameters (used when config_file is empty)
dbutils.widgets.text("arrivals", "")
dbutils.widgets.text("departures", "")
dbutils.widgets.text("duration_hours", "")
dbutils.widgets.text("time_step_seconds", "")
dbutils.widgets.text("seed", "")
dbutils.widgets.text("output_file", "")
dbutils.widgets.text("scenario_file", "")

airport = dbutils.widgets.get("airport")
config_file = dbutils.widgets.get("config_file")

print(f"Airport: {airport}")
print(f"Config:  {config_file or '(inline parameters)'}")

# COMMAND ----------

import os, sys, subprocess, json, time

# Derive bundle root from notebook path in workspace
nb_path = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
print(f"Notebook path: {nb_path}")

ws_path = "/Workspace" + nb_path
bundle_root = os.path.dirname(os.path.dirname(os.path.dirname(ws_path)))
print(f"Bundle root: {bundle_root}")
print(f"Contents: {os.listdir(bundle_root)}")

# UC Volume for simulation output (FUSE-mounted on serverless)
UC_CATALOG = "serverless_stable_3n0ihb_catalog"
UC_SCHEMA = "airport_digital_twin"
UC_VOLUME = "simulation_data"
VOLUME_PATH = f"/Volumes/{UC_CATALOG}/{UC_SCHEMA}/{UC_VOLUME}"

import yaml

if config_file:
    # ── Mode 1: Config file on workspace ─────────────────────────────
    config_path = os.path.join(bundle_root, config_file)
    assert os.path.isfile(config_path), f"Config not found: {config_path}"
    with open(config_path) as f:
        config = yaml.safe_load(f)
else:
    # ── Mode 2: Inline parameters (no config file needed) ────────────
    config = {
        "airport": airport,
        "arrivals": int(dbutils.widgets.get("arrivals") or "500"),
        "departures": int(dbutils.widgets.get("departures") or "500"),
        "duration_hours": int(dbutils.widgets.get("duration_hours") or "24"),
        "time_step_seconds": float(dbutils.widgets.get("time_step_seconds") or "2.0"),
        "seed": int(dbutils.widgets.get("seed") or "42"),
        "output_file": dbutils.widgets.get("output_file") or f"simulation_output/sim_{airport.lower()}.json",
    }
    sf = dbutils.widgets.get("scenario_file")
    if sf:
        config["scenario_file"] = sf

# Write to local /tmp first (reliable), then copy to UC Volume
# Add timestamp to filename so re-runs don't overwrite previous results
from datetime import datetime
timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
original_output = config.get("output_file", f"simulation_output/sim_{airport.lower()}.json")
base, ext = os.path.splitext(os.path.basename(original_output))
output_basename = f"{base}_{timestamp}{ext}"
local_output = f"/tmp/{output_basename}"
volume_output = f"{VOLUME_PATH}/{output_basename}"
config["output_file"] = local_output
print(f"Local output:  {local_output}")
print(f"Volume target: {volume_output}")

# Write a temporary config file for the CLI to read
config_file = f"configs/_run_{airport.lower()}.yaml"
config_path = os.path.join(bundle_root, config_file)
os.makedirs(os.path.dirname(config_path), exist_ok=True)
with open(config_path, "w") as f:
    yaml.dump(config, f, default_flow_style=False)
print(f"Generated config: {config_path}")

scenario_file = config.get("scenario_file")
if scenario_file:
    scenario_path = os.path.join(bundle_root, scenario_file)
    assert os.path.isfile(scenario_path), f"Scenario not found: {scenario_path}"
    print(f"Scenario: {scenario_file}")

# Ensure local output directory exists
os.makedirs(os.path.dirname(local_output) or "/tmp", exist_ok=True)

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

import re, shutil

def parse_summary_from_stdout(stdout: str) -> dict:
    """Extract summary values from CLI stdout lines like '  Total flights:  123'."""
    mapping = {
        "Total flights": "total_flights",
        "Arrivals": "arrivals",
        "Departures": "departures",
        "On-time": "on_time_pct",
        "Cancellation rate": "cancellation_rate_pct",
        "Capacity hold (avg)": "avg_capacity_hold_min",
        "Capacity hold (max)": "max_capacity_hold_min",
        "Peak simultaneous": "peak_simultaneous_flights",
        "Gates used": "gate_utilization_gates_used",
        "Position snapshots": "total_position_snapshots",
        "Go-arounds": "total_go_arounds",
        "Diversions": "total_diversions",
        "Spawned": "spawned_count",
        "Scenario": "scenario_name",
    }
    result = {}
    for line in stdout.splitlines():
        for label, key in mapping.items():
            if label + ":" in line:
                val = line.split(":", 1)[1].strip().rstrip("%").replace(",", "")
                if key == "scenario_name":
                    result[key] = val
                elif "/" in val:  # "450/500" for spawned
                    result[key] = int(val.split("/")[0])
                else:
                    try:
                        result[key] = int(val) if "." not in val else float(val)
                    except ValueError:
                        result[key] = val
                break
    return result

summary = parse_summary_from_stdout(result.stdout)
print(f"\nParsed summary from CLI stdout: {json.dumps(summary, indent=2)}")

if os.path.isfile(local_output):
    size_mb = os.path.getsize(local_output) / (1024 * 1024)
    print(f"\nLocal output: {local_output} ({size_mb:.1f} MB)")

    # Copy to UC Volume (don't parse the large JSON — use stdout summary)
    os.makedirs(VOLUME_PATH, exist_ok=True)
    shutil.copy2(local_output, volume_output)
    print(f"Copied to UC Volume: {volume_output}")
else:
    print(f"WARNING: Output file not found at {local_output}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Register in Metadata Table

# COMMAND ----------

if os.path.isfile(local_output):
    size_bytes = os.path.getsize(local_output)
    fname = output_basename
    scenario_name = (summary.get("scenario_name") or "").replace("'", "''")

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
        volume_path = '{volume_output}'
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
        {summary.get('total_diversions', 0)}, {size_bytes}, CURRENT_TIMESTAMP(), '{volume_output}'
    )
    """
    spark.sql(merge_sql)
    print(f"Metadata inserted into {UC_CATALOG}.{UC_SCHEMA}.simulation_runs")
else:
    print("Skipping metadata insert — no output file")

# Clean up temporary files
for f in [config_path, local_output]:
    try:
        os.remove(f)
    except OSError:
        pass

# COMMAND ----------

# Exit with status
success = result.returncode == 0
dbutils.notebook.exit(json.dumps({
    "status": "PASS" if success else "FAIL",
    "airport": airport,
    "elapsed_sec": round(elapsed, 1),
    "output_file": volume_output,
    "total_flights": summary.get("total_flights", 0) if success else 0,
    "on_time_pct": summary.get("on_time_pct", 0) if success else 0,
}))

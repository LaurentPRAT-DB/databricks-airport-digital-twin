# Databricks notebook source
# MAGIC %md
# MAGIC # Run All Airport Simulations (Sequential)
# MAGIC Runs all 33 airport simulations sequentially in a single task to avoid
# MAGIC serverless "Futures timed out" errors from launching too many parallel tasks.

# COMMAND ----------

%pip install pyyaml pydantic Faker --quiet

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import os, sys, subprocess, json, time, shutil, re
from datetime import datetime

import yaml

# Derive bundle root from notebook path in workspace
nb_path = (
    dbutils.notebook.entry_point.getDbutils()
    .notebook()
    .getContext()
    .notebookPath()
    .get()
)
ws_path = "/Workspace" + nb_path
bundle_root = os.path.dirname(os.path.dirname(os.path.dirname(ws_path)))
print(f"Bundle root: {bundle_root}")

# UC Volume for simulation output
UC_CATALOG = "serverless_stable_3n0ihb_catalog"
UC_SCHEMA = "airport_digital_twin"
UC_VOLUME = "simulation_data"
VOLUME_PATH = f"/Volumes/{UC_CATALOG}/{UC_SCHEMA}/{UC_VOLUME}"
os.makedirs(VOLUME_PATH, exist_ok=True)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Discover all 7-day configs

# COMMAND ----------

configs_dir = os.path.join(bundle_root, "configs")
config_files = sorted(
    f for f in os.listdir(configs_dir) if f.endswith("_7day.yaml")
)
print(f"Found {len(config_files)} 7-day configs:")
for f in config_files:
    print(f"  {f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Run simulations sequentially

# COMMAND ----------

def parse_summary_from_stdout(stdout: str) -> dict:
    """Extract summary values from the 'Simulation Summary:' block in CLI stdout."""
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
    in_summary = False
    for line in stdout.splitlines():
        if "Simulation Summary:" in line:
            in_summary = True
            continue
        if not in_summary:
            continue
        for label, key in mapping.items():
            if label + ":" in line and line.strip().startswith(label):
                val = line.split(":", 1)[1].strip().rstrip("%").replace(",", "")
                if key == "scenario_name":
                    result[key] = val
                elif "/" in val:
                    result[key] = int(val.split("/")[0])
                else:
                    try:
                        result[key] = int(val) if "." not in val else float(val)
                    except ValueError:
                        result[key] = val
                break
    return result


def run_single_sim(config_filename: str) -> dict:
    """Run one airport simulation and return results dict."""
    config_path = os.path.join(configs_dir, config_filename)
    with open(config_path) as f:
        config = yaml.safe_load(f)

    airport = config["airport"]
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    original_output = config.get(
        "output_file", f"simulation_output/sim_{airport.lower()}.json"
    )
    base, ext = os.path.splitext(os.path.basename(original_output))
    output_basename = f"{base}_{timestamp}{ext}"
    local_output = f"/tmp/{output_basename}"
    volume_output = f"{VOLUME_PATH}/{output_basename}"

    # Write temp config with local output path
    config["output_file"] = local_output
    tmp_config = os.path.join(bundle_root, f"configs/_run_{airport.lower()}.yaml")
    os.makedirs(os.path.dirname(tmp_config), exist_ok=True)
    with open(tmp_config, "w") as f:
        yaml.dump(config, f, default_flow_style=False)

    os.makedirs(os.path.dirname(local_output) or "/tmp", exist_ok=True)

    print(f"\n{'='*60}")
    print(f"Starting {airport} simulation...")
    start = time.time()

    result = subprocess.run(
        [sys.executable, "-m", "src.simulation.cli", "--config", f"configs/_run_{airport.lower()}.yaml"],
        capture_output=True,
        text=True,
        cwd=bundle_root,
    )

    elapsed = time.time() - start
    success = result.returncode == 0
    print(f"  {airport}: {'OK' if success else 'FAIL'} in {elapsed:.1f}s")

    summary = parse_summary_from_stdout(result.stdout)

    if not success:
        print(f"  STDERR (last 500 chars): {result.stderr[-500:]}")
        # Clean up
        for f in [tmp_config, local_output]:
            try:
                os.remove(f)
            except OSError:
                pass
        return {
            "airport": airport,
            "status": "FAIL",
            "elapsed_sec": round(elapsed, 1),
            "error": result.stderr[-200:],
        }

    # Copy to UC Volume
    if os.path.isfile(local_output):
        size_bytes = os.path.getsize(local_output)
        size_mb = size_bytes / (1024 * 1024)
        shutil.copy2(local_output, volume_output)
        print(f"  Output: {volume_output} ({size_mb:.1f} MB)")
        print(f"  Flights: {summary.get('total_flights', '?')}, On-time: {summary.get('on_time_pct', '?')}%")

        # Register in metadata table
        scenario_name = (summary.get("scenario_name") or "").replace("'", "''")
        merge_sql = f"""
        MERGE INTO {UC_CATALOG}.{UC_SCHEMA}.simulation_runs AS target
        USING (SELECT '{output_basename}' AS filename) AS source
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
            '{output_basename}', '{airport}', '{scenario_name}',
            {summary.get('total_flights', 0)}, {summary.get('arrivals', 0)},
            {summary.get('departures', 0)}, {config.get('duration_hours', 0)},
            {summary.get('on_time_pct', 0)}, {summary.get('cancellation_rate_pct', 0)},
            {summary.get('peak_simultaneous_flights', 0)}, {summary.get('total_go_arounds', 0)},
            {summary.get('total_diversions', 0)}, {size_bytes}, CURRENT_TIMESTAMP(), '{volume_output}'
        )
        """
        spark.sql(merge_sql)
    else:
        size_mb = 0
        size_bytes = 0
        print(f"  WARNING: Output file not found at {local_output}")

    # Clean up temp files
    for f in [tmp_config, local_output]:
        try:
            os.remove(f)
        except OSError:
            pass

    return {
        "airport": airport,
        "status": "PASS",
        "elapsed_sec": round(elapsed, 1),
        "total_flights": summary.get("total_flights", 0),
        "on_time_pct": summary.get("on_time_pct", 0),
        "output_file": volume_output,
        "size_mb": round(size_mb, 1),
    }

# COMMAND ----------

# Run all simulations
total_start = time.time()
results = []

for i, config_file in enumerate(config_files):
    print(f"\n[{i+1}/{len(config_files)}] {config_file}")
    res = run_single_sim(config_file)
    results.append(res)

total_elapsed = time.time() - total_start

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary

# COMMAND ----------

passed = [r for r in results if r["status"] == "PASS"]
failed = [r for r in results if r["status"] == "FAIL"]

print(f"\n{'='*60}")
print(f"ALL SIMULATIONS COMPLETE")
print(f"{'='*60}")
print(f"Total time: {total_elapsed/60:.1f} min")
print(f"Passed: {len(passed)}/{len(results)}")

if passed:
    total_flights = sum(r.get("total_flights", 0) for r in passed)
    avg_otp = sum(r.get("on_time_pct", 0) for r in passed) / len(passed)
    total_size = sum(r.get("size_mb", 0) for r in passed)
    print(f"Total flights: {total_flights:,}")
    print(f"Avg on-time: {avg_otp:.1f}%")
    print(f"Total output size: {total_size:.0f} MB")

if failed:
    print(f"\nFailed airports:")
    for r in failed:
        print(f"  {r['airport']}: {r.get('error', 'unknown')}")

print(f"\nPer-airport results:")
for r in results:
    status = "PASS" if r["status"] == "PASS" else "FAIL"
    flights = r.get("total_flights", "?")
    elapsed = r.get("elapsed_sec", "?")
    print(f"  {r['airport']:4s}: {status} | {flights:>6} flights | {elapsed}s")

# COMMAND ----------

# Exit
dbutils.notebook.exit(json.dumps({
    "total_airports": len(results),
    "passed": len(passed),
    "failed": len(failed),
    "total_elapsed_min": round(total_elapsed / 60, 1),
    "total_flights": sum(r.get("total_flights", 0) for r in passed),
}))

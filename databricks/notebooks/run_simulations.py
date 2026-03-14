# Databricks notebook source
# MAGIC %md
# MAGIC # Multi-Airport Simulation Batch
# MAGIC Runs 10 airport simulations (1,000 flights each) with region-appropriate weather scenarios.
# MAGIC Produces JSON outputs for replay and an analysis report with visualizations.

# COMMAND ----------

# Install dependencies not in app requirements.txt
%pip install pyyaml matplotlib --quiet

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import os, sys, subprocess, json, time

# Bundle files root — where DABs syncs the project files
bundle_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
print(f"Bundle root: {bundle_root}")
print(f"Contents: {os.listdir(bundle_root)}")

# Verify required directories exist
for d in ["configs", "scenarios", "src"]:
    path = os.path.join(bundle_root, d)
    assert os.path.isdir(path), f"{d}/ directory not found at {path}"
    print(f"  {d}/: {len(os.listdir(path))} items")

# Create simulation_output directory
sim_output = os.path.join(bundle_root, "simulation_output")
os.makedirs(sim_output, exist_ok=True)
os.makedirs(os.path.join(sim_output, "report"), exist_ok=True)
print(f"Output dir: {sim_output}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Run All 10 Simulations

# COMMAND ----------

# Simulation configs to run (airport, config file, expected scenario)
SIMULATIONS = [
    ("SFO", "configs/simulation_sfo_1000.yaml", "SFO Summer Thunderstorm"),
    ("JFK", "configs/simulation_jfk_1000.yaml", "JFK Nor'easter Winter Storm"),
    ("LHR", "configs/simulation_lhr_1000.yaml", "LHR Winter Radiation Fog"),
    ("FRA", "configs/simulation_fra_1000.yaml", "FRA Winter Crosswind"),
    ("DXB", "configs/simulation_dxb_1000.yaml", "DXB Shamal Sandstorm"),
    ("NRT", "configs/simulation_nrt_1000.yaml", "NRT Typhoon Approach"),
    ("SIN", "configs/simulation_sin_1000.yaml", "SIN Southwest Monsoon"),
    ("GRU", "configs/simulation_gru_1000.yaml", "GRU Tropical Storm"),
    ("SYD", "configs/simulation_syd_1000.yaml", "SYD Bushfire Smoke"),
    ("JNB", "configs/simulation_jnb_1000.yaml", "JNB Highveld Thunderstorm"),
]

results = {}
total_start = time.time()

for airport, config_file, scenario_name in SIMULATIONS:
    config_path = os.path.join(bundle_root, config_file)
    assert os.path.isfile(config_path), f"Config not found: {config_path}"

    print(f"\n{'='*60}")
    print(f"Running {airport} — {scenario_name}")
    print(f"{'='*60}")

    start = time.time()
    result = subprocess.run(
        [sys.executable, "-m", "src.simulation.cli", "--config", config_file],
        capture_output=True,
        text=True,
        cwd=bundle_root,
    )

    elapsed = time.time() - start
    success = result.returncode == 0

    # Extract summary from output
    output_lines = result.stdout.strip().split("\n")
    summary_lines = [l for l in output_lines if l.strip().startswith(("Total flights", "On-time", "Spawned", "Cancellation", "Peak", "Gates", "Output"))]

    results[airport] = {
        "success": success,
        "elapsed_sec": round(elapsed, 1),
        "returncode": result.returncode,
    }

    if success:
        print(f"  OK ({elapsed:.1f}s)")
        for l in summary_lines:
            print(f"  {l.strip()}")
    else:
        print(f"  FAILED (rc={result.returncode}, {elapsed:.1f}s)")
        print(f"  STDOUT: {result.stdout[-1000:]}")
        print(f"  STDERR: {result.stderr[-1000:]}")

total_elapsed = time.time() - total_start
print(f"\n{'='*60}")
print(f"All simulations complete in {total_elapsed:.0f}s")
passed = sum(1 for r in results.values() if r["success"])
print(f"  Passed: {passed}/{len(SIMULATIONS)}")
print(f"{'='*60}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verify Output Files

# COMMAND ----------

import glob

output_files = sorted(glob.glob(os.path.join(sim_output, "simulation_*_1000_*.json")))
print(f"Simulation output files: {len(output_files)}")
for f in output_files:
    size_mb = os.path.getsize(f) / (1024 * 1024)
    print(f"  {os.path.basename(f)}: {size_mb:.1f} MB")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Run Analysis & Generate Report

# COMMAND ----------

print("Running analysis script...")
analysis_result = subprocess.run(
    [sys.executable, "scripts/analyze_simulations.py"],
    capture_output=True,
    text=True,
    cwd=bundle_root,
)

print(analysis_result.stdout[-5000:])
if analysis_result.returncode != 0:
    print(f"Analysis STDERR: {analysis_result.stderr[-2000:]}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Display Report Visuals

# COMMAND ----------

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.image as mpimg

report_dir = os.path.join(sim_output, "report")
report_images = sorted(glob.glob(os.path.join(report_dir, "*.png")))
print(f"Report images: {len(report_images)}")

for img_path in report_images:
    print(f"\n--- {os.path.basename(img_path)} ---")
    img = mpimg.imread(img_path)
    fig, ax = plt.subplots(figsize=(20, 12))
    ax.imshow(img)
    ax.axis("off")
    ax.set_title(os.path.basename(img_path), fontsize=14)
    plt.tight_layout()
    plt.show()

# COMMAND ----------

# Print text report
report_txt = os.path.join(report_dir, "simulation_analysis_report.txt")
if os.path.isfile(report_txt):
    with open(report_txt) as f:
        print(f.read())

# COMMAND ----------

# Final status
failed = [a for a, r in results.items() if not r["success"]]
status = "PASS" if not failed else "FAIL"
dbutils.notebook.exit(json.dumps({
    "status": status,
    "airports_run": len(results),
    "airports_passed": passed,
    "airports_failed": failed,
    "total_elapsed_sec": round(total_elapsed, 0),
    "output_files": len(output_files),
}))

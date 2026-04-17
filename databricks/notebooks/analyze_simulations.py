# Databricks notebook source
# MAGIC %md
# MAGIC # Simulation Analysis & Report
# MAGIC Runs after all 10 airport simulations complete in parallel.
# MAGIC Reads simulation outputs from UC Volume, generates anomaly analysis and visual report.

# COMMAND ----------

# Install all project dependencies + matplotlib/numpy for analysis
%pip install pyyaml pydantic Faker matplotlib numpy --quiet

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import os, sys, subprocess, json, glob, shutil

# Derive bundle root from notebook path
nb_path = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
ws_path = "/Workspace" + nb_path
bundle_root = os.path.dirname(os.path.dirname(os.path.dirname(ws_path)))
print(f"Bundle root: {bundle_root}")

# UC Volume where run_simulation_airport.py uploads outputs
UC_CATALOG = "serverless_stable_3n0ihb_catalog"
UC_SCHEMA = "airport_digital_twin"
UC_VOLUME = "simulation_data"
VOLUME_PATH = f"/Volumes/{UC_CATALOG}/{UC_SCHEMA}/{UC_VOLUME}"

# Local working directory for analysis script
sim_output = os.path.join(bundle_root, "simulation_output")
os.makedirs(os.path.join(sim_output, "report"), exist_ok=True)

# Pick only the latest file per airport (avoid old/duplicate runs)
volume_files_all = sorted(glob.glob(os.path.join(VOLUME_PATH, "simulation_*_7day_*.json")))
print(f"Found {len(volume_files_all)} total simulation files in UC Volume")

latest_by_airport = {}
for f in volume_files_all:
    # Filename: simulation_{airport}_7day_{timestamp}.json
    basename = os.path.basename(f)
    parts = basename.split("_")
    if len(parts) >= 3:
        airport = parts[1]  # e.g. "ams"
        latest_by_airport[airport] = f  # sorted asc, so last wins = newest

volume_files = sorted(latest_by_airport.values())
print(f"Selected {len(volume_files)} latest files (1 per airport):")

for f in volume_files:
    size_mb = os.path.getsize(f) / (1024 * 1024)
    dest = os.path.join(sim_output, os.path.basename(f))
    # Symlink to FUSE-mounted Volume to avoid copying 100+ MB files to local disk
    if os.path.exists(dest):
        os.remove(dest)
    os.symlink(f, dest)
    print(f"  {os.path.basename(f)}: {size_mb:.1f} MB (symlinked)")

output_files = sorted(glob.glob(os.path.join(sim_output, "simulation_*_7day_*.json")))
print(f"\n{len(output_files)} files ready for analysis")
assert len(output_files) >= 3, f"Expected >=3 simulation files in UC Volume, found {len(volume_files)}"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Run Analysis Script

# COMMAND ----------

print("Running analysis...")
result = subprocess.run(
    [sys.executable, os.path.join(bundle_root, "scripts", "analyze_simulations.py")],
    capture_output=True,
    text=True,
    cwd=bundle_root,
)

print(result.stdout[-6000:])
if result.returncode != 0:
    print(f"STDERR: {result.stderr[-2000:]}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Upload Report to UC Volume

# COMMAND ----------

# Copy report artifacts back to UC Volume for persistence
report_dir = os.path.join(sim_output, "report")
volume_report_dir = os.path.join(VOLUME_PATH, "report")
os.makedirs(volume_report_dir, exist_ok=True)

report_files = glob.glob(os.path.join(report_dir, "*"))
for f in report_files:
    dest = os.path.join(volume_report_dir, os.path.basename(f))
    shutil.copy2(f, dest)
    print(f"Uploaded report: {os.path.basename(f)}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Display Report Visuals

# COMMAND ----------

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.image as mpimg

report_images = sorted(glob.glob(os.path.join(report_dir, "*.png")))
print(f"Report images: {len(report_images)}")

for img_path in report_images:
    img = mpimg.imread(img_path)
    fig, ax = plt.subplots(figsize=(20, 12))
    ax.imshow(img)
    ax.axis("off")
    ax.set_title(os.path.basename(img_path), fontsize=14)
    plt.tight_layout()
    plt.show()
    plt.close()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Full Text Report

# COMMAND ----------

report_txt = os.path.join(report_dir, "simulation_analysis_report.txt")
if os.path.isfile(report_txt):
    with open(report_txt) as f:
        print(f.read())

# COMMAND ----------

# Clean up local copies to keep bundle dir small
for f in output_files:
    os.remove(f)
    print(f"Cleaned up: {os.path.basename(f)}")

# COMMAND ----------

dbutils.notebook.exit(json.dumps({
    "status": "PASS" if result.returncode == 0 else "FAIL",
    "report_images": len(report_images),
    "output_files": len(output_files),
}))

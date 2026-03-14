# Databricks notebook source
# MAGIC %md
# MAGIC # Simulation Analysis & Report
# MAGIC Runs after all 10 airport simulations complete in parallel.
# MAGIC Generates anomaly analysis and visual report.

# COMMAND ----------

# Install all project dependencies + matplotlib/numpy for analysis
%pip install pyyaml pydantic Faker matplotlib numpy --quiet

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import os, sys, subprocess, json, glob

# Derive bundle root from notebook path
nb_path = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
ws_path = "/Workspace" + nb_path
bundle_root = os.path.dirname(os.path.dirname(os.path.dirname(ws_path)))
print(f"Bundle root: {bundle_root}")

sim_output = os.path.join(bundle_root, "simulation_output")
os.makedirs(os.path.join(sim_output, "report"), exist_ok=True)

# List available output files
output_files = sorted(glob.glob(os.path.join(sim_output, "simulation_*_1000_*.json")))
print(f"Found {len(output_files)} simulation output files:")
for f in output_files:
    size_mb = os.path.getsize(f) / (1024 * 1024)
    print(f"  {os.path.basename(f)}: {size_mb:.1f} MB")

assert len(output_files) >= 10, f"Expected 10 simulation files, found {len(output_files)}"

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

dbutils.notebook.exit(json.dumps({
    "status": "PASS" if result.returncode == 0 else "FAIL",
    "report_images": len(report_images),
    "output_files": len(output_files),
}))

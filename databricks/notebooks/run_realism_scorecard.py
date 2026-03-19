# Databricks notebook source
# MAGIC %md
# MAGIC # Realism Scorecard
# MAGIC Scores synthetic flight generation against real-world airport profiles across 7 dimensions.
# MAGIC Renders an HTML report in the job run UI and saves artifacts to UC Volume.

# COMMAND ----------

%pip install pyyaml pydantic Faker --quiet

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import json
import os
import sys
import time
from datetime import datetime

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
sys.path.insert(0, bundle_root)

# UC Volume for scorecard artifacts
UC_CATALOG = "serverless_stable_3n0ihb_catalog"
UC_SCHEMA = "airport_digital_twin"
UC_VOLUME = "simulation_data"
VOLUME_PATH = f"/Volumes/{UC_CATALOG}/{UC_SCHEMA}/{UC_VOLUME}"
SCORECARD_DIR = f"{VOLUME_PATH}/scorecard"
os.makedirs(SCORECARD_DIR, exist_ok=True)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

# Read schedules_per_airport from job parameter (default 5)
dbutils.widgets.text("schedules_per_airport", "5", "Schedules per airport")
schedules_per_airport = int(dbutils.widgets.get("schedules_per_airport"))
print(f"Schedules per airport: {schedules_per_airport}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Run Scorecard

# COMMAND ----------

from scripts.realism_scorecard import score_airport, DIMENSION_WEIGHTS
from src.calibration.profile import AirportProfileLoader, _icao_to_iata

loader = AirportProfileLoader()
icao_list = loader.list_available()
print(f"Scoring {len(icao_list)} airports with {schedules_per_airport} schedules each...")

start_time = time.time()
results = []

for i, icao in enumerate(icao_list):
    iata = _icao_to_iata(icao)
    print(f"  [{i+1}/{len(icao_list)}] {iata} ({icao})...", end=" ", flush=True)
    result = score_airport(icao, loader, n_schedules=schedules_per_airport)
    overall = result.get("overall", 0)
    print(f"score={overall:.0f}, flights={result.get('n_flights', 0)}")
    results.append(result)

elapsed = time.time() - start_time
print(f"\nCompleted in {elapsed:.0f}s")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Build HTML Report

# COMMAND ----------

valid = [r for r in results if "error" not in r]
errors = [r for r in results if "error" in r]
avg_overall = sum(r["overall"] for r in valid) / len(valid) if valid else 0

dim_labels = {
    "airline": "Airline Mix",
    "route": "Route Freq",
    "fleet": "Fleet Mix",
    "hourly": "Hourly Pattern",
    "delay_rate": "Delay Rate",
    "delay_codes": "Delay Codes",
    "domestic_ratio": "Dom. Ratio",
}

# Color helper
def _score_color(score: float) -> str:
    if score >= 90:
        return "#22c55e"  # green
    elif score >= 70:
        return "#eab308"  # yellow
    else:
        return "#ef4444"  # red

today = datetime.utcnow().strftime("%Y-%m-%d")

html = f"""
<style>
  .sc-table {{ border-collapse: collapse; font-family: -apple-system, sans-serif; font-size: 13px; width: 100%; }}
  .sc-table th {{ background: #1e293b; color: white; padding: 8px 10px; text-align: right; }}
  .sc-table th:first-child {{ text-align: left; }}
  .sc-table td {{ padding: 6px 10px; border-bottom: 1px solid #e2e8f0; text-align: right; }}
  .sc-table td:first-child {{ text-align: left; font-weight: 600; }}
  .sc-table tr:hover {{ background: #f1f5f9; }}
  .sc-table .avg-row td {{ font-weight: 700; border-top: 2px solid #1e293b; }}
  .sc-badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; color: white; font-weight: 600; }}
</style>

<h2>Realism Scorecard &mdash; {today}</h2>
<p>{len(valid)} airports, {schedules_per_airport} schedules each, completed in {elapsed:.0f}s</p>
<p>Overall average: <span class="sc-badge" style="background:{_score_color(avg_overall)}">{avg_overall:.0f}/100</span></p>

<table class="sc-table">
<tr>
  <th>Airport</th>
"""

for dim in DIMENSION_WEIGHTS:
    html += f"  <th>{dim_labels[dim]}</th>\n"
html += "  <th>Overall</th>\n  <th>Flights</th>\n</tr>\n"

# Airport rows
for r in sorted(valid, key=lambda x: -x["overall"]):
    html += f'<tr><td>{r["iata"]} ({r["icao"]})</td>'
    for dim in DIMENSION_WEIGHTS:
        s = r["scores"][dim]
        html += f'<td style="color:{_score_color(s)}">{s:.0f}</td>'
    html += f'<td><span class="sc-badge" style="background:{_score_color(r["overall"])}">{r["overall"]:.0f}</span></td>'
    html += f'<td>{r["n_flights"]:,}</td></tr>\n'

# Average row
dim_avgs = {}
for dim in DIMENSION_WEIGHTS:
    dim_avgs[dim] = sum(r["scores"][dim] for r in valid) / len(valid) if valid else 0

html += '<tr class="avg-row"><td>AVERAGE</td>'
for dim in DIMENSION_WEIGHTS:
    html += f'<td style="color:{_score_color(dim_avgs[dim])}">{dim_avgs[dim]:.0f}</td>'
html += f'<td><span class="sc-badge" style="background:{_score_color(avg_overall)}">{avg_overall:.0f}</span></td>'
html += f'<td>{sum(r["n_flights"] for r in valid):,}</td></tr>\n'
html += "</table>\n"

# Errors
if errors:
    html += "<h3>Errors</h3><ul>"
    for r in errors:
        html += f'<li>{r["iata"]}: {r["error"]}</li>'
    html += "</ul>"

# Weakest dimensions
ranked = sorted(dim_avgs.items(), key=lambda x: x[1])
html += "<h3>Weakest Dimensions</h3><ol>"
for dim, avg in ranked[:3]:
    html += f"<li>{dim_labels[dim]}: {avg:.0f}/100</li>"
html += "</ol>"

displayHTML(html)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Save Artifacts

# COMMAND ----------

# Save HTML report
html_path = f"{SCORECARD_DIR}/scorecard_{today}.html"
with open(html_path, "w") as f:
    f.write(f"<html><head><title>Realism Scorecard {today}</title></head><body>{html}</body></html>")
print(f"HTML report saved: {html_path}")

# Save JSON (machine-readable for trending)
json_data = {
    "date": today,
    "schedules_per_airport": schedules_per_airport,
    "elapsed_seconds": round(elapsed),
    "n_airports": len(valid),
    "avg_overall": round(avg_overall, 1),
    "dimension_averages": {dim: round(v, 1) for dim, v in dim_avgs.items()},
    "airports": {
        r["iata"]: {
            "icao": r["icao"],
            "overall": round(r["overall"], 1),
            "n_flights": r["n_flights"],
            "scores": {dim: round(r["scores"][dim], 1) for dim in DIMENSION_WEIGHTS},
        }
        for r in valid
    },
}

json_path = f"{SCORECARD_DIR}/scorecard_{today}.json"
with open(json_path, "w") as f:
    json.dump(json_data, f, indent=2)
print(f"JSON data saved: {json_path}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Exit

# COMMAND ----------

summary = json.dumps({
    "date": today,
    "n_airports": len(valid),
    "avg_overall": round(avg_overall, 1),
    "elapsed_seconds": round(elapsed),
    "html_path": html_path,
    "json_path": json_path,
})
print(f"\nSummary: {summary}")
dbutils.notebook.exit(summary)

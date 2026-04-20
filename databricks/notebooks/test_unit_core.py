# Databricks notebook source
# MAGIC %md
# MAGIC # Unit Tests — Core Logic (non-API, non-simulation)
# MAGIC Parsers, ML, calibration, services, DLT tests. Part of the parallel unit test job.

# COMMAND ----------

# Install app dependencies + test dependencies
# Note: psycopg2-binary and openap excluded — not installable on serverless
%pip install fastapi==0.135.2 uvicorn==0.42.0 websockets==16.0 pydantic==2.12.5 starlette==1.0.0 python-dotenv==1.2.2 httpx==0.28.1 requests==2.32.5 tenacity==9.1.4 circuitbreaker==2.1.3 Faker==40.11.1 databricks-sql-connector==4.2.5 databricks-sdk==0.102.0 pyyaml==6.0.2 python-multipart==0.0.20 pytest pytest-mock pytest-asyncio pytest-cov --quiet

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import subprocess, sys, json, os

# Bundle root — where DABs syncs the project files
try:
    _nb_path = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
    bundle_root = os.path.dirname(os.path.dirname(os.path.dirname(f"/Workspace{_nb_path}")))
except Exception:
    bundle_root = "/Workspace/Users/laurent.prat@databricks.com/.bundle/airport-digital-twin/dev/files"

tests_dir = os.path.join(bundle_root, "tests")
assert os.path.isdir(tests_dir), f"tests/ directory not found at {tests_dir}"
print(f"Bundle root: {bundle_root} | Tests: {len(os.listdir(tests_dir))} items")

# COMMAND ----------

# Test files that import simulation engine or are data-heavy (slow — excluded from core)
SIM_HEAVY = [
    # Direct simulation fixture users
    "tests/test_aviation_procedures.py",
    "tests/test_profile_schema_compat.py",
    "tests/test_multi_airport_ux.py",
    "tests/test_ux_multi_airport.py",
    "tests/test_synthetic_data_requirements.py",
    "tests/test_trajectory_coherence.py",
    "tests/test_scenario.py",
    "tests/test_expert_reviews.py",
    "tests/test_flight_origins_destinations.py",
    "tests/test_flight_realism.py",
    "tests/test_aircraft_separation.py",
    "tests/test_takeoff_physics.py",
    "tests/test_calibration.py",
    "tests/test_single_flight_tracker.py",
    "tests/test_ux_video_tester.py",
    "tests/test_engine_coverage.py",
    "tests/test_simulation.py",
    "tests/test_pilot_review.py",
    "tests/test_flight_ops_validation.py",
    "tests/test_engine_phase_counters.py",
    "tests/test_live_trajectory_quality.py",
    "tests/test_go_around_video.py",
    "tests/test_passenger_flow_validation.py",
    "tests/test_bhs_validation.py",
    # Import from simulation/calibration modules
    "tests/test_auto_calibrate.py",
    "tests/test_calibration_taxi_turnaround.py",
    "tests/test_openap_trajectories.py",
    "tests/test_openflights_ingest.py",
    "tests/test_profile_builder_coverage.py",
    "tests/test_realism_scorecard.py",
    # Data-heavy (>50 tests, run full model training)
    "tests/test_turnaround_model.py",
    "tests/test_lakebase_service.py",
]

cmd = [
    sys.executable, "-m", "pytest",
    "tests/", "-m", "not api", "-q", "--tb=short",
    "--override-ini=asyncio_mode=auto",
]
for f in SIM_HEAVY:
    cmd.extend(["--ignore", f])

result = subprocess.run(
    cmd,
    capture_output=True,
    text=True,
    cwd=bundle_root,
    env={**os.environ, "PYTHONPATH": bundle_root, "PYTHONDONTWRITEBYTECODE": "1"},
)

if result.returncode != 0:
    print("=== STDOUT (last 8K) ===")
    print(result.stdout[-8000:])
    print("=== STDERR (last 4K) ===")
    print(result.stderr[-4000:])
else:
    print(result.stdout[-5000:])

# COMMAND ----------

if result.returncode != 0:
    dbutils.notebook.exit(json.dumps({
        "status": "FAIL",
        "returncode": result.returncode,
        "stderr_tail": (result.stderr or "")[-2000:],
        "stdout_tail": (result.stdout or "")[-2000:],
    }))
else:
    dbutils.notebook.exit(json.dumps({"status": "PASS"}))

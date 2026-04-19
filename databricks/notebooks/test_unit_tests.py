# Databricks notebook source
# MAGIC %md
# MAGIC # Unit Tests — Python Backend
# MAGIC Runs the pytest suite on Databricks serverless compute.

# COMMAND ----------

# Install app dependencies + test dependencies
# Note: psycopg2-binary and openap excluded — not installable on serverless
# (psycopg2 guarded by PSYCOPG2_AVAILABLE flag, openap only lazy-imported)
%pip install fastapi==0.135.2 uvicorn==0.42.0 websockets==16.0 pydantic==2.12.5 starlette==1.0.0 python-dotenv==1.2.2 httpx==0.28.1 requests==2.32.5 tenacity==9.1.4 circuitbreaker==2.1.3 Faker==40.11.1 databricks-sql-connector==4.2.5 databricks-sdk==0.102.0 pyyaml==6.0.2 pytest pytest-mock pytest-asyncio pytest-cov --quiet

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import subprocess, sys, json, os

# Bundle files root — where DABs syncs the project files
# After restartPython(), __file__ is not defined; use notebook context path
try:
    _nb_path = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
    # Notebook is at databricks/notebooks/test_unit_tests.py → go up 2 levels
    bundle_root = os.path.dirname(os.path.dirname(os.path.dirname(f"/Workspace{_nb_path}")))
except Exception:
    # Fallback: scan known DABs deploy path
    bundle_root = "/Workspace/Users/laurent.prat@databricks.com/.bundle/airport-digital-twin/dev/files"

print(f"Bundle root: {bundle_root}")
print(f"Contents: {os.listdir(bundle_root)}")

# Verify tests/ directory exists
tests_dir = os.path.join(bundle_root, "tests")
assert os.path.isdir(tests_dir), f"tests/ directory not found at {tests_dir}"
print(f"Tests dir: {tests_dir} ({len(os.listdir(tests_dir))} items)")

# COMMAND ----------

# Run pytest with JUnit XML output
result = subprocess.run(
    [
        sys.executable, "-m", "pytest",
        "tests/", "-v", "--tb=short",
        "--junitxml=/tmp/test-results.xml",
        "-x",  # Stop on first failure for faster feedback
    ],
    capture_output=True,
    text=True,
    cwd=bundle_root,
)

# Print output (last 5K chars to avoid truncation)
print(result.stdout[-5000:])
if result.stderr:
    print("STDERR:", result.stderr[-2000:])

# COMMAND ----------

# Report result
if result.returncode != 0:
    dbutils.notebook.exit(json.dumps({
        "status": "FAIL",
        "returncode": result.returncode,
    }))
else:
    dbutils.notebook.exit(json.dumps({"status": "PASS"}))

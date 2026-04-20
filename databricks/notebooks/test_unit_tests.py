# Databricks notebook source
# MAGIC %md
# MAGIC # Unit Tests — Python Backend
# MAGIC Runs the pytest suite on Databricks serverless compute.

# COMMAND ----------

# Install app dependencies + test dependencies
# Note: psycopg2-binary and openap excluded — not installable on serverless
# (psycopg2 guarded by PSYCOPG2_AVAILABLE flag, openap only lazy-imported)
%pip install fastapi==0.135.2 uvicorn==0.42.0 websockets==16.0 pydantic==2.12.5 starlette==1.0.0 python-dotenv==1.2.2 httpx==0.28.1 requests==2.32.5 tenacity==9.1.4 circuitbreaker==2.1.3 Faker==40.11.1 databricks-sql-connector==4.2.5 databricks-sdk==0.102.0 pyyaml==6.0.2 python-multipart==0.0.20 pytest pytest-mock pytest-asyncio pytest-cov --quiet

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
if not os.path.isdir(tests_dir):
    print(f"ERROR: tests/ not found at {tests_dir}")
    print(f"Bundle root contents: {os.listdir(bundle_root)}")
    # Try alternative paths
    for alt in ["/Workspace/Users/laurent.prat@databricks.com/.bundle/airport-digital-twin/dev/files"]:
        alt_tests = os.path.join(alt, "tests")
        if os.path.isdir(alt_tests):
            bundle_root = alt
            tests_dir = alt_tests
            print(f"Found tests at alternative path: {alt}")
            break
assert os.path.isdir(tests_dir), f"tests/ directory not found at {tests_dir}"
print(f"Tests dir: {tests_dir} ({len(os.listdir(tests_dir))} items)")
print(f"pyproject.toml exists: {os.path.exists(os.path.join(bundle_root, 'pyproject.toml'))}")

# COMMAND ----------

# Run pytest
result = subprocess.run(
    [
        sys.executable, "-m", "pytest",
        "tests/", "-v", "--tb=short",
        "-x",  # Stop on first failure for faster feedback
        "--override-ini=asyncio_mode=auto",
    ],
    capture_output=True,
    text=True,
    cwd=bundle_root,
    env={**os.environ, "PYTHONPATH": bundle_root, "PYTHONDONTWRITEBYTECODE": "1"},
)

# Print output
if result.returncode != 0:
    # On failure, show more context including stderr
    print("=== STDOUT (last 8K) ===")
    print(result.stdout[-8000:])
    print("=== STDERR (last 4K) ===")
    print(result.stderr[-4000:])
else:
    print(result.stdout[-5000:])

# COMMAND ----------

# Report result — include error details in exit message for CLI visibility
if result.returncode != 0:
    # Include last 2K of stderr + stdout in exit value so CLI can see the error
    err_tail = (result.stderr or "")[-2000:]
    out_tail = (result.stdout or "")[-2000:]
    dbutils.notebook.exit(json.dumps({
        "status": "FAIL",
        "returncode": result.returncode,
        "stderr_tail": err_tail,
        "stdout_tail": out_tail,
    }))
else:
    dbutils.notebook.exit(json.dumps({"status": "PASS"}))

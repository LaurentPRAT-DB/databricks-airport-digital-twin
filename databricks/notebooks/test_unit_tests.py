# Databricks notebook source
# MAGIC %md
# MAGIC # Unit Tests — Python Backend
# MAGIC Runs the pytest suite on Databricks serverless compute.

# COMMAND ----------

# Install test dependencies (not in app requirements.txt)
%pip install pytest pytest-mock pytest-asyncio pytest-cov --quiet

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import subprocess, sys, json, os

# Bundle files root — where DABs syncs the project files
bundle_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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

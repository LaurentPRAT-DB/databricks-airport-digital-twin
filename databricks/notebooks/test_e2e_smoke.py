# Databricks notebook source
# MAGIC %md
# MAGIC # E2E Smoke Tests — Deployed App
# MAGIC Validates the live Airport Digital Twin API endpoints.

# COMMAND ----------

import requests, json, time

APP_URL = dbutils.widgets.get("app_url").rstrip("/")
print(f"Testing app at: {APP_URL}")

results = {}

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test 1 — Health check

# COMMAND ----------

try:
    r = requests.get(f"{APP_URL}/health", timeout=10)
    assert r.status_code == 200, f"Status {r.status_code}"
    assert r.json()["status"] == "healthy"
    results["health"] = "PASS"
    print("PASS: health")
except Exception as e:
    results["health"] = f"FAIL: {e}"
    print(f"FAIL: health — {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test 2 — Readiness (wait up to 60s)

# COMMAND ----------

try:
    data = {}
    for _ in range(12):
        r = requests.get(f"{APP_URL}/api/ready", timeout=10)
        data = r.json()
        if data.get("ready"):
            break
        time.sleep(5)
    assert data.get("ready") == True, f"App not ready: {data}"
    results["readiness"] = "PASS"
    print("PASS: readiness")
except Exception as e:
    results["readiness"] = f"FAIL: {e}"
    print(f"FAIL: readiness — {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test 3 — Flights list

# COMMAND ----------

try:
    r = requests.get(f"{APP_URL}/api/flights", timeout=10)
    assert r.status_code == 200, f"Status {r.status_code}"
    data = r.json()
    assert "flights" in data, "Missing 'flights' key"
    assert len(data["flights"]) > 0, "No flights returned"
    flight = data["flights"][0]
    for field in ["icao24", "callsign", "latitude", "longitude"]:
        assert field in flight, f"Missing field: {field}"
    results["flights_list"] = "PASS"
    print(f"PASS: flights_list ({len(data['flights'])} flights)")
except Exception as e:
    results["flights_list"] = f"FAIL: {e}"
    print(f"FAIL: flights_list — {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test 4 — Single flight detail + trajectory

# COMMAND ----------

try:
    r = requests.get(f"{APP_URL}/api/flights", timeout=10)
    flights = r.json()["flights"]
    icao24 = flights[0]["icao24"]

    r2 = requests.get(f"{APP_URL}/api/flights/{icao24}", timeout=10)
    assert r2.status_code == 200, f"Flight detail status {r2.status_code}"

    r3 = requests.get(f"{APP_URL}/api/flights/{icao24}/trajectory", timeout=10)
    assert r3.status_code == 200, f"Trajectory status {r3.status_code}"
    traj = r3.json()
    assert "points" in traj, "Missing 'points' in trajectory"
    results["flight_detail_trajectory"] = "PASS"
    print(f"PASS: flight_detail_trajectory (icao24={icao24})")
except Exception as e:
    results["flight_detail_trajectory"] = f"FAIL: {e}"
    print(f"FAIL: flight_detail_trajectory — {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test 5 — Airport config

# COMMAND ----------

try:
    r = requests.get(f"{APP_URL}/api/airport/config", timeout=10)
    assert r.status_code == 200, f"Status {r.status_code}"
    data = r.json()
    assert "config" in data, "Missing 'config' key"
    results["airport_config"] = "PASS"
    print("PASS: airport_config")
except Exception as e:
    results["airport_config"] = f"FAIL: {e}"
    print(f"FAIL: airport_config — {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test 6 — Schedule endpoints

# COMMAND ----------

try:
    r1 = requests.get(f"{APP_URL}/api/schedule/arrivals", timeout=10)
    assert r1.status_code == 200, f"Arrivals status {r1.status_code}"
    r2 = requests.get(f"{APP_URL}/api/schedule/departures", timeout=10)
    assert r2.status_code == 200, f"Departures status {r2.status_code}"
    results["schedule"] = "PASS"
    print("PASS: schedule")
except Exception as e:
    results["schedule"] = f"FAIL: {e}"
    print(f"FAIL: schedule — {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test 7 — Weather

# COMMAND ----------

try:
    r = requests.get(f"{APP_URL}/api/weather/current", timeout=10)
    assert r.status_code == 200, f"Status {r.status_code}"
    results["weather"] = "PASS"
    print("PASS: weather")
except Exception as e:
    results["weather"] = f"FAIL: {e}"
    print(f"FAIL: weather — {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test 8 — GSE status

# COMMAND ----------

try:
    r = requests.get(f"{APP_URL}/api/gse/status", timeout=10)
    assert r.status_code == 200, f"Status {r.status_code}"
    results["gse_status"] = "PASS"
    print("PASS: gse_status")
except Exception as e:
    results["gse_status"] = f"FAIL: {e}"
    print(f"FAIL: gse_status — {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test 9 — Baggage stats

# COMMAND ----------

try:
    r = requests.get(f"{APP_URL}/api/baggage/stats", timeout=10)
    assert r.status_code == 200, f"Status {r.status_code}"
    results["baggage_stats"] = "PASS"
    print("PASS: baggage_stats")
except Exception as e:
    results["baggage_stats"] = f"FAIL: {e}"
    print(f"FAIL: baggage_stats — {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test 10 — Airport switch (KJFK then back to KSFO)

# COMMAND ----------

try:
    r = requests.post(f"{APP_URL}/api/airports/KJFK/activate", timeout=60)
    assert r.status_code == 200, f"KJFK activate failed: {r.status_code} {r.text[:200]}"
    data = r.json()
    assert "config" in data, "Missing 'config' in activate response"

    # Switch back to KSFO
    r2 = requests.post(f"{APP_URL}/api/airports/KSFO/activate", timeout=60)
    assert r2.status_code == 200, f"KSFO activate failed: {r2.status_code}"
    results["airport_switch"] = "PASS"
    print("PASS: airport_switch")
except Exception as e:
    results["airport_switch"] = f"FAIL: {e}"
    print(f"FAIL: airport_switch — {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test 11 — Frontend serves index.html

# COMMAND ----------

try:
    r = requests.get(f"{APP_URL}/", timeout=10)
    assert r.status_code == 200, f"Status {r.status_code}"
    assert "Airport Digital Twin" in r.text, "Title not found in HTML"
    results["frontend_served"] = "PASS"
    print("PASS: frontend_served")
except Exception as e:
    results["frontend_served"] = f"FAIL: {e}"
    print(f"FAIL: frontend_served — {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Report

# COMMAND ----------

print("\n=== E2E Smoke Test Results ===")
passed = sum(1 for v in results.values() if v == "PASS")
total = len(results)
for name, status in results.items():
    icon = "+" if status == "PASS" else "X"
    print(f"  [{icon}] {name}: {status}")
print(f"\n{passed}/{total} tests passed")

if passed < total:
    dbutils.notebook.exit(json.dumps({"status": "FAIL", "results": results}))
else:
    dbutils.notebook.exit(json.dumps({"status": "PASS", "results": results}))

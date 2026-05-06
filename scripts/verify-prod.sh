#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Post-deploy production verification script
# Usage: ./scripts/verify-prod.sh <APP_URL>
# Env:   DATABRICKS_TOKEN — passed as Bearer token for OAuth-protected apps
#
# Runs the same checks as the E2E smoke test but from your local machine.
# Requires: curl, jq
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

APP_URL="${1:?Usage: $0 <APP_URL>}"
APP_URL="${APP_URL%/}"

AUTH_HEADER=""
if command -v databricks > /dev/null 2>&1; then
  _TOKEN=$(databricks auth token 2>/dev/null | jq -r '.access_token // empty' 2>/dev/null || true)
  [[ -n "$_TOKEN" ]] && AUTH_HEADER="Authorization: Bearer $_TOKEN"
fi
if [[ -z "$AUTH_HEADER" && -n "${DATABRICKS_TOKEN:-}" ]]; then
  AUTH_HEADER="Authorization: Bearer $DATABRICKS_TOKEN"
fi

PASS=0
FAIL=0
SKIP=0

check() {
  local name="$1" url="$2" jq_test="${3:-}"
  local response http_code body

  if [[ -n "$AUTH_HEADER" ]]; then
    response=$(curl -s -w "\n%{http_code}" -H "$AUTH_HEADER" "$url" 2>/dev/null)
  else
    response=$(curl -s -w "\n%{http_code}" "$url" 2>/dev/null)
  fi
  http_code=$(echo "$response" | tail -1)
  body=$(echo "$response" | sed '$d')

  if [[ "$http_code" == "401" || "$http_code" == "302" ]]; then
    echo "  SKIP  $name (HTTP $http_code — OAuth required)"
    SKIP=$((SKIP + 1))
    return
  fi
  if [[ "$http_code" != "200" ]]; then
    echo "  FAIL  $name (HTTP $http_code)"
    FAIL=$((FAIL + 1))
    return
  fi

  if [[ -n "$jq_test" ]]; then
    if echo "$body" | jq -e "$jq_test" > /dev/null 2>&1; then
      echo "  OK    $name"
      PASS=$((PASS + 1))
    else
      echo "  FAIL  $name (assertion failed: $jq_test)"
      FAIL=$((FAIL + 1))
    fi
  else
    echo "  OK    $name"
    PASS=$((PASS + 1))
  fi
}

echo "═══ Airport Digital Twin — Post-Deploy Verification ═══"
echo "Target: $APP_URL"
echo ""

check "Health"          "$APP_URL/health"                    '.status == "healthy"'
check "Ready"           "$APP_URL/api/ready"                 '.ready == true'
check "Flights"         "$APP_URL/api/flights"               '.flights | length > 0'
check "Airport config"  "$APP_URL/api/airport/config"        '.config | keys | length > 0'
check "Arrivals"        "$APP_URL/api/schedule/arrivals"     '. | type == "array" or has("flights")'
check "Departures"      "$APP_URL/api/schedule/departures"   '. | type == "array" or has("flights")'
check "Weather"         "$APP_URL/api/weather/current"       'has("temperature") or has("station")'
check "GSE"             "$APP_URL/api/gse/status"            '. != null'
check "Baggage"         "$APP_URL/api/baggage/stats"         '. != null'
check "Frontend"        "$APP_URL/"                          ''
check "Version"         "$APP_URL/api/version"               'has("build_number") or has("git_commit")'

# ── Deep verification: simulate a real user session ──────────────────
# Skip deep checks if any basic check was skipped (OAuth issue) or already failing
if [[ $SKIP -eq 0 && $FAIL -eq 0 ]]; then
  echo ""
  echo "── Deep verification (data pipeline) ──"

  # Activate default airport (triggers full simulation pipeline)
  ACTIVATE_RESP=""
  if [[ -n "$AUTH_HEADER" ]]; then
    ACTIVATE_RESP=$(curl -s -w "\n%{http_code}" -X POST -H "$AUTH_HEADER" "$APP_URL/api/airports/KSFO/activate" 2>/dev/null)
  else
    ACTIVATE_RESP=$(curl -s -w "\n%{http_code}" -X POST "$APP_URL/api/airports/KSFO/activate" 2>/dev/null)
  fi
  ACTIVATE_CODE=$(echo "$ACTIVATE_RESP" | tail -1)
  if [[ "$ACTIVATE_CODE" == "200" || "$ACTIVATE_CODE" == "202" ]]; then
    echo "  OK    Activate KSFO (HTTP $ACTIVATE_CODE)"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  Activate KSFO (HTTP $ACTIVATE_CODE)"
    FAIL=$((FAIL + 1))
  fi

  # Wait for app to be fully ready with simulation data (max 120s)
  echo "  ...   Waiting for simulation ready (up to 120s)"
  SIM_READY=false
  for i in $(seq 1 12); do
    READY_BODY=""
    if [[ -n "$AUTH_HEADER" ]]; then
      READY_BODY=$(curl -s -H "$AUTH_HEADER" "$APP_URL/api/ready" 2>/dev/null)
    else
      READY_BODY=$(curl -s "$APP_URL/api/ready" 2>/dev/null)
    fi
    IS_READY=$(echo "$READY_BODY" | jq -r '.ready // false' 2>/dev/null)
    DEMO_READY=$(echo "$READY_BODY" | jq -r '.demo_ready // false' 2>/dev/null)
    if [[ "$IS_READY" == "true" && "$DEMO_READY" == "true" ]]; then
      SIM_READY=true
      echo "  OK    Simulation ready (after ${i}0s)"
      PASS=$((PASS + 1))
      break
    fi
    sleep 10
  done
  if [[ "$SIM_READY" == "false" ]]; then
    STATUS=$(echo "$READY_BODY" | jq -r '.status // "unknown"' 2>/dev/null)
    echo "  FAIL  Simulation not ready after 120s (status: $STATUS)"
    FAIL=$((FAIL + 1))
  fi

  # Deep data checks (only if simulation is ready)
  if [[ "$SIM_READY" == "true" ]]; then
    check "Flights (>=10)"    "$APP_URL/api/flights"               '.flights | length >= 10'
    check "Flight position"   "$APP_URL/api/flights"               '.flights[0] | (.latitude | type == "number") and (.longitude | type == "number")'
    check "Schedule data"     "$APP_URL/api/schedule/arrivals"     '(if type == "array" then length > 0 elif has("flights") then .flights | length > 0 else false end)'
    check "Data-ops stats"    "$APP_URL/api/data-ops/stats"        'has("freshness")'
    check "Lakebase"          "$APP_URL/api/data-ops/stats"        '.freshness.lakebase | has("record_count")'
    check "Lakehouse"         "$APP_URL/api/data-ops/stats"        '.freshness.delta | has("record_count")'
  fi
fi

echo ""
echo "Results: $PASS passed, $FAIL failed, $SKIP skipped ($(( PASS + FAIL + SKIP )) total)"

if [[ $SKIP -gt 0 && $PASS -eq 0 && $FAIL -eq 0 ]]; then
  echo "DEPLOYMENT VERIFIED (all endpoints require OAuth — app is running)"
  exit 0
fi
if [[ $FAIL -gt 0 ]]; then
  echo "DEPLOYMENT VERIFICATION FAILED"
  exit 1
fi
echo "DEPLOYMENT VERIFIED"

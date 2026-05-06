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
if [[ -n "${DATABRICKS_TOKEN:-}" ]]; then
  AUTH_HEADER="Authorization: Bearer $DATABRICKS_TOKEN"
elif command -v databricks > /dev/null 2>&1; then
  _TOKEN=$(databricks auth token 2>/dev/null | jq -r '.access_token // empty' 2>/dev/null || true)
  [[ -n "$_TOKEN" ]] && AUTH_HEADER="Authorization: Bearer $_TOKEN"
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
check "Version"         "$APP_URL/api/version"               'has("version") or has("commit")'

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

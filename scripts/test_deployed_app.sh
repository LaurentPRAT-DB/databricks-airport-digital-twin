#!/usr/bin/env bash
# Test script for the deployed Airport Digital Twin app.
# Validates airport switch, flight positions, and API health.
#
# Usage: ./scripts/test_deployed_app.sh [APP_URL]

set -euo pipefail

APP_URL="${1:-https://airport-digital-twin-dev-7474645572615955.aws.databricksapps.com}"
DB_PROFILE="${DB_PROFILE:-FEVM_SERVERLESS_STABLE}"
PASS=0
FAIL=0
SKIP=0

# Get Databricks OAuth token for app authentication
TOKEN=$(databricks auth token --profile "$DB_PROFILE" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null || echo "")
if [ -z "$TOKEN" ]; then
  echo "ERROR: Failed to get Databricks auth token (profile: $DB_PROFILE)"
  exit 1
fi
# Helper to curl with auth
acurl() { curl -s -H "Authorization: Bearer $TOKEN" "$@"; }
acurl_code() { curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$@"; }

green() { printf "\033[32m%s\033[0m\n" "$1"; }
red()   { printf "\033[31m%s\033[0m\n" "$1"; }
yellow(){ printf "\033[33m%s\033[0m\n" "$1"; }

check() {
  local name="$1" ok="$2"
  if [ "$ok" = "true" ]; then
    green "  PASS: $name"
    PASS=$((PASS + 1))
  else
    red "  FAIL: $name"
    FAIL=$((FAIL + 1))
  fi
}

skip() {
  yellow "  SKIP: $1"
  SKIP=$((SKIP + 1))
}

echo "=== Airport Digital Twin — Deployed App Tests ==="
echo "URL: $APP_URL"
echo ""

# ─── T1: Health check ───
echo "T1: Health check"
HTTP_CODE=$(acurl_code "$APP_URL/api/health" 2>/dev/null || echo "000")
check "GET /api/health returns 200" "$([ "$HTTP_CODE" = "200" ] && echo true || echo false)"
if [ "$HTTP_CODE" != "200" ]; then
  red "App not ready (HTTP $HTTP_CODE). Aborting."
  exit 1
fi

# ─── T2: Default airport flights ───
echo ""
echo "T2: Default airport flights"
FLIGHTS_JSON=$(acurl "$APP_URL/api/flights" 2>/dev/null)
FLIGHT_COUNT=$(echo "$FLIGHTS_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('count',0))" 2>/dev/null || echo 0)
check "GET /api/flights returns flights (count=$FLIGHT_COUNT)" "$([ "$FLIGHT_COUNT" -gt 0 ] && echo true || echo false)"

# ─── T3: Airport config ───
echo ""
echo "T3: Airport config loaded"
CONFIG_JSON=$(acurl "$APP_URL/api/airport/config" 2>/dev/null)
HAS_RUNWAYS=$(echo "$CONFIG_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('config',{}).get('osmRunways',[]))>0)" 2>/dev/null || echo False)
check "Airport config has OSM runways" "$([ "$HAS_RUNWAYS" = "True" ] && echo true || echo false)"

# ─── T4: Switch to MMMX (Mexico City) ───
echo ""
echo "T4: Switch to MMMX"
ACTIVATE_RESP=$(acurl -X POST "$APP_URL/api/airports/MMMX/activate" 2>/dev/null)
ACTIVATE_STATUS=$(echo "$ACTIVATE_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
check "POST /api/airports/MMMX/activate accepted" "$([ "$ACTIVATE_STATUS" = "activating" ] && echo true || echo false)"

# Wait for airport switch to complete
echo "  Waiting 20s for airport switch + demo generation..."
sleep 20

# ─── T5: Flights at MMMX coordinates ───
echo ""
echo "T5: Flights at MMMX coordinates (lat ~19.4, lon ~-99.1)"
FLIGHTS_JSON=$(acurl "$APP_URL/api/flights" 2>/dev/null)
POSITION_CHECK=$(echo "$FLIGHTS_JSON" | python3 -c "
import sys, json
d = json.load(sys.stdin)
flights = d.get('flights', [])
if not flights:
    print('NO_FLIGHTS')
    sys.exit()
near_mex = 0
near_sfo = 0
total = 0
for f in flights:
    lat = float(f.get('latitude', 0))
    lon = float(f.get('longitude', 0))
    alt = float(f.get('altitude', 0))
    # Only check ground/low-altitude flights (parked, taxi)
    if alt < 500:
        total += 1
        if abs(lat - 19.43) < 1 and abs(lon - (-99.07)) < 2:
            near_mex += 1
        elif abs(lat - 37.62) < 1 and abs(lon - (-122.38)) < 2:
            near_sfo += 1
print(f'ground_total={total} near_mex={near_mex} near_sfo={near_sfo}')
" 2>/dev/null || echo "ERROR")
echo "  Position check: $POSITION_CHECK"

# Parse results
GROUND_TOTAL=$(echo "$POSITION_CHECK" | sed -n 's/.*ground_total=\([0-9]*\).*/\1/p' || echo 0)
NEAR_SFO=$(echo "$POSITION_CHECK" | sed -n 's/.*near_sfo=\([0-9]*\).*/\1/p' || echo 0)
NEAR_MEX=$(echo "$POSITION_CHECK" | sed -n 's/.*near_mex=\([0-9]*\).*/\1/p' || echo 0)

if [ "$GROUND_TOTAL" -gt 0 ]; then
  check "No ground flights at SFO coordinates (found $NEAR_SFO)" "$([ "$NEAR_SFO" -eq 0 ] && echo true || echo false)"
  check "Ground flights near MMMX ($NEAR_MEX/$GROUND_TOTAL)" "$([ "$NEAR_MEX" -gt 0 ] && echo true || echo false)"
else
  skip "No ground flights yet (demo may still be generating)"
fi

# ─── T6: All flights have valid positions ───
echo ""
echo "T6: Flight data quality"
QUALITY_CHECK=$(echo "$FLIGHTS_JSON" | python3 -c "
import sys, json
d = json.load(sys.stdin)
flights = d.get('flights', [])
nan_count = 0
null_count = 0
valid = 0
for f in flights:
    lat = f.get('latitude')
    lon = f.get('longitude')
    if lat is None or lon is None:
        null_count += 1
    elif str(lat) == 'nan' or str(lon) == 'nan':
        nan_count += 1
    else:
        valid += 1
print(f'valid={valid} null={null_count} nan={nan_count}')
" 2>/dev/null || echo "ERROR")
echo "  Quality: $QUALITY_CHECK"
NAN_COUNT=$(echo "$QUALITY_CHECK" | sed -n 's/.*nan=\([0-9]*\).*/\1/p' || echo 0)
NULL_COUNT=$(echo "$QUALITY_CHECK" | sed -n 's/.*null=\([0-9]*\).*/\1/p' || echo 0)
check "No NaN positions" "$([ "$NAN_COUNT" -eq 0 ] && echo true || echo false)"
check "No null positions" "$([ "$NULL_COUNT" -eq 0 ] && echo true || echo false)"

# ─── T7: Switch back to KSFO ───
echo ""
echo "T7: Switch back to KSFO"
acurl -X POST "$APP_URL/api/airports/KSFO/activate" >/dev/null 2>&1
sleep 15
FLIGHTS_JSON=$(acurl "$APP_URL/api/flights" 2>/dev/null)
SFO_CHECK=$(echo "$FLIGHTS_JSON" | python3 -c "
import sys, json
d = json.load(sys.stdin)
flights = d.get('flights', [])
near_sfo = sum(1 for f in flights
    if float(f.get('altitude',99999)) < 500
    and abs(float(f.get('latitude',0)) - 37.62) < 0.5
    and abs(float(f.get('longitude',0)) - (-122.38)) < 0.5)
print(near_sfo)
" 2>/dev/null || echo 0)
check "Ground flights back at SFO after switch ($SFO_CHECK found)" "$([ "$SFO_CHECK" -gt 0 ] && echo true || echo false)"

# ─── Summary ───
echo ""
echo "════════════════════════════════════"
echo "Results: $(green "$PASS passed"), $([ "$FAIL" -gt 0 ] && red "$FAIL failed" || echo "$FAIL failed"), $SKIP skipped"
echo "════════════════════════════════════"
exit $FAIL

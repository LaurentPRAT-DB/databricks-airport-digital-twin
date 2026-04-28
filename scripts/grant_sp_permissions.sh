#!/usr/bin/env bash
# Grant the app service principal read/run access to the DABs bundle workspace files.
# Run after `databricks bundle deploy --target dev` to ensure the SP can submit notebook jobs.
#
# These permissions are NOT managed by DABs — they must be applied separately.

set -euo pipefail

APP_SP="79ea25c2-52d3-462e-b03c-357c14daaa00"
BUNDLE_DIR="/Users/laurent.prat@databricks.com/.bundle/airport-digital-twin/dev/files"

echo "Getting bundle directory ID..."
DIR_ID=$(databricks workspace get-status "$BUNDLE_DIR" --output json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['object_id'])")
echo "Bundle directory ID: $DIR_ID"

echo "Granting CAN_READ on bundle directory to app SP..."
databricks workspace update-permissions directories "$DIR_ID" --json "{
  \"access_control_list\": [
    {\"service_principal_name\": \"$APP_SP\", \"permission_level\": \"CAN_READ\"}
  ]
}" > /dev/null

echo "Getting simulation notebook ID..."
NB_ID=$(databricks workspace get-status "$BUNDLE_DIR/databricks/notebooks/run_simulation_airport" --output json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['object_id'])")
echo "Notebook ID: $NB_ID"

echo "Granting CAN_RUN on simulation notebook to app SP..."
databricks workspace update-permissions notebooks "$NB_ID" --json "{
  \"access_control_list\": [
    {\"service_principal_name\": \"$APP_SP\", \"permission_level\": \"CAN_RUN\"}
  ]
}" > /dev/null

echo "Done — app SP has CAN_READ on bundle files + CAN_RUN on simulation notebook."

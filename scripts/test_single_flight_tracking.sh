#!/bin/bash
# End-to-end test for single-flight tracking features:
#   1. Install Playwright (if needed)
#   2. Convert EDDF OpenSky JSONL → simulation JSON
#   3. Start dev server (killing stale ones first)
#   4. Render KSFO simulation video with --track-flight
#   5. Render EDDF real-data video with --track-flight
#   6. Cleanup

set -euo pipefail
cd "$(dirname "$0")/.."

# ── Config ──────────────────────────────────────────────────────────
KSFO_SIM="simulation_output_sfo_100.json"
KSFO_FLIGHT="sim00070"    # ASA2319, 199 frames
EDDF_SIM="simulation_output_eddf_opensky.json"
EDDF_FLIGHT="3c4b26"      # DLH572, 64 frames
BACKEND_PORT=8000
VITE_PORT=3000  # vite.config.ts: server.port = 3000, proxies /api to backend
APP_URL="http://localhost:${VITE_PORT}"
OUTPUT_DIR="video_output"
DEV_LOG="/tmp/airport_dt_dev_server.log"
DEV_PID=""

# ── Helpers ─────────────────────────────────────────────────────────
cleanup() {
    echo ""
    echo "=== Cleanup ==="
    if [[ -n "$DEV_PID" ]]; then
        echo "Stopping dev server (PID $DEV_PID)..."
        kill "$DEV_PID" 2>/dev/null || true
        pkill -P "$DEV_PID" 2>/dev/null || true
        wait "$DEV_PID" 2>/dev/null || true
    fi
    echo "Done."
}
trap cleanup EXIT

kill_stale_servers() {
    # Kill any existing uvicorn/vite processes on our ports
    local killed=false
    for port in $BACKEND_PORT $VITE_PORT 5173; do
        local pids
        pids=$(lsof -ti :$port 2>/dev/null || true)
        if [[ -n "$pids" ]]; then
            echo "  Killing stale process(es) on port $port: $pids"
            echo "$pids" | xargs kill 2>/dev/null || true
            killed=true
        fi
    done
    if $killed; then
        sleep 2  # let ports release
    fi
}

wait_for_server() {
    local max_wait="${1:-120}"
    local elapsed=0

    # Wait for backend API
    echo "Waiting for backend (port $BACKEND_PORT, max ${max_wait}s)..."
    while ! curl -sf "http://localhost:${BACKEND_PORT}/api/ready" >/dev/null 2>&1; do
        sleep 2
        elapsed=$((elapsed + 2))
        if [[ $elapsed -ge $max_wait ]]; then
            echo "ERROR: Backend not ready after ${max_wait}s"
            echo "Last 20 lines of dev server log:"
            tail -20 "$DEV_LOG" 2>/dev/null || true
            exit 1
        fi
    done
    echo "  Backend ready (${elapsed}s)."

    # Wait for Vite dev server
    echo "Waiting for Vite (port $VITE_PORT)..."
    while ! curl -sf "http://localhost:${VITE_PORT}/" >/dev/null 2>&1; do
        sleep 1
        elapsed=$((elapsed + 1))
        if [[ $elapsed -ge $max_wait ]]; then
            echo "ERROR: Vite not ready after ${max_wait}s"
            tail -20 "$DEV_LOG" 2>/dev/null || true
            exit 1
        fi
    done
    echo "  Vite ready (${elapsed}s total)."
}

# ── Step 1: Install Playwright ──────────────────────────────────────
echo "=== Step 1: Install Playwright ==="
if uv run python -c "import playwright" 2>/dev/null; then
    echo "Playwright already installed."
else
    echo "Installing playwright..."
    uv pip install playwright pyee greenlet
fi

# Check chromium browser
if ! uv run playwright install --dry-run chromium 2>/dev/null | grep -q "is already installed"; then
    echo "Installing Chromium browser..."
    uv run playwright install chromium
else
    echo "Chromium already installed."
fi

# ── Step 2: Convert EDDF data ──────────────────────────────────────
echo ""
echo "=== Step 2: Convert EDDF OpenSky JSONL → simulation JSON ==="
if [[ -f "$EDDF_SIM" ]]; then
    echo "$EDDF_SIM already exists, skipping conversion."
else
    uv run python scripts/opensky_to_sim_json.py --airport EDDF --output "$EDDF_SIM"
fi

# Verify both simulation files exist
for f in "$KSFO_SIM" "$EDDF_SIM"; do
    if [[ ! -f "$f" ]]; then
        echo "ERROR: Missing simulation file: $f"
        exit 1
    fi
    echo "  OK: $f ($(du -h "$f" | cut -f1))"
done

# ── Step 3: Start dev server ───────────────────────────────────────
echo ""
echo "=== Step 3: Start dev server ==="

# Kill stale servers to avoid port conflicts
kill_stale_servers

if curl -sf "http://localhost:${BACKEND_PORT}/api/ready" >/dev/null 2>&1; then
    echo "Dev server already running on port $BACKEND_PORT"
else
    echo "Starting dev server (logs: $DEV_LOG)..."
    # Start dev server with output redirected to log file to keep console clean
    ./dev.sh > "$DEV_LOG" 2>&1 &
    DEV_PID=$!
    wait_for_server 120
fi

# ── Step 4: Render KSFO video ──────────────────────────────────────
echo ""
echo "=== Step 4: Render KSFO tracked flight video ==="
echo "  Flight: $KSFO_FLIGHT (ASA2319)"
echo "  Window: hour 6-7"
mkdir -p "$OUTPUT_DIR"

uv run python -m src.simulation.video_cli \
    --simulation-file "$KSFO_SIM" \
    --output "$OUTPUT_DIR/ksfo_tracked_ASA2319.mp4" \
    --app-url "$APP_URL" \
    --track-flight "$KSFO_FLIGHT" \
    --start-hour 6 --end-hour 7 \
    --fps 15 --speed 2 -y 2>&1 | grep -v "^$"

# Output filename now includes a timestamp suffix (e.g. _20260407_153012)
KSFO_VIDEO=$(ls -t "$OUTPUT_DIR"/ksfo_tracked_ASA2319_*.mp4 2>/dev/null | head -1)
if [[ -n "$KSFO_VIDEO" ]]; then
    SIZE=$(du -h "$KSFO_VIDEO" | cut -f1)
    echo "  OK: KSFO video rendered ($SIZE) → $KSFO_VIDEO"
else
    echo "  FAIL: KSFO video rendering failed"
    echo "Last 30 lines of dev server log:"
    tail -30 "$DEV_LOG" 2>/dev/null || true
    exit 1
fi

# ── Step 5: Render EDDF video ──────────────────────────────────────
echo ""
echo "=== Step 5: Render EDDF tracked flight video ==="
echo "  Flight: $EDDF_FLIGHT (DLH572)"

uv run python -m src.simulation.video_cli \
    --simulation-file "$EDDF_SIM" \
    --output "$OUTPUT_DIR/eddf_tracked_DLH572.mp4" \
    --app-url "$APP_URL" \
    --track-flight "$EDDF_FLIGHT" \
    --fps 15 --speed 2 -y 2>&1 | grep -v "^$"

EDDF_VIDEO=$(ls -t "$OUTPUT_DIR"/eddf_tracked_DLH572_*.mp4 2>/dev/null | head -1)
if [[ -n "$EDDF_VIDEO" ]]; then
    SIZE=$(du -h "$EDDF_VIDEO" | cut -f1)
    echo "  OK: EDDF video rendered ($SIZE) → $EDDF_VIDEO"
else
    echo "  FAIL: EDDF video rendering failed"
    echo "Last 30 lines of dev server log:"
    tail -30 "$DEV_LOG" 2>/dev/null || true
    exit 1
fi

# ── Summary ─────────────────────────────────────────────────────────
echo ""
echo "=========================================="
echo "  ALL TESTS PASSED"
echo "=========================================="
echo "  KSFO: $KSFO_VIDEO"
echo "  EDDF: $EDDF_VIDEO"
echo ""
echo "  open $OUTPUT_DIR/"
echo "=========================================="

#!/usr/bin/env bash
set -euo pipefail

# 1. Install Playwright
echo "=== Installing Playwright ==="
uv pip install playwright && playwright install chromium

# 2. Start dev server in background
echo "=== Starting dev server ==="
./dev.sh &
DEV_PID=$!

# Wait for frontend to be ready
echo "Waiting for dev server (http://localhost:3000)..."
for i in $(seq 1 60); do
    if curl -s http://localhost:3000 > /dev/null 2>&1; then
        echo "Dev server ready."
        break
    fi
    if [ "$i" -eq 60 ]; then
        echo "ERROR: Dev server did not start within 60s"
        kill $DEV_PID 2>/dev/null || true
        exit 1
    fi
    sleep 1
done

# Ensure dev server is killed on exit
cleanup() {
    echo "=== Shutting down dev server ==="
    kill $DEV_PID 2>/dev/null || true
    wait $DEV_PID 2>/dev/null || true
}
trap cleanup EXIT

# 3. Render KSFO tracked flight video
echo "=== Rendering KSFO tracked flight video ==="
uv run python -m src.simulation.video_cli \
    --simulation-file simulation_output_sfo_100.json \
    --output video_output/ksfo_tracked_flight.mp4 \
    --track-flight sim00070 --start-hour 6 --end-hour 7 --fps 15 -y

# 4. Render EDDF real flight video (DLH572 departure)
echo "=== Rendering EDDF DLH572 video ==="
uv run python -m src.simulation.video_cli \
    --simulation-file simulation_output_eddf_opensky.json \
    --output video_output/eddf_dlh572.mp4 \
    --track-flight 3c4b26 --fps 15 -y

echo "=== Done! Videos in video_output/ ==="

#!/bin/bash
# Local development script - starts backend and frontend

set -e

cleanup() {
    echo "Stopping services..."
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
    exit 0
}

trap cleanup SIGINT SIGTERM

cd "$(dirname "$0")"

echo "Starting backend on http://localhost:8000..."
uv run uvicorn app.backend.main:app --reload --port 8000 &
BACKEND_PID=$!

echo "Starting frontend on http://localhost:5173..."
cd app/frontend
npm install --silent && npm run dev &
FRONTEND_PID=$!

echo ""
echo "Services running:"
echo "  Backend:  http://localhost:8000"
echo "  Frontend: http://localhost:5173"
echo ""
echo "Press Ctrl+C to stop"

wait

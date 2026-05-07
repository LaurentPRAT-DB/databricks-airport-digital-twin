---
status: implemented
area: frontend
related: [deploy.sh, app/frontend/src/hooks/useConnectionHealth.ts, app/frontend/src/components/MaintenanceOverlay/MaintenanceOverlay.tsx]
---

# Maintenance Mode Overlay During Deployments

## Problem

When the app is redeployed (`deploy.sh` stops and restarts the app), users currently on the page see broken behavior — API calls fail, WebSocket disconnects, airport switching breaks. No feedback that a deployment is in progress.

## Solution

Frontend-only maintenance overlay that detects backend downtime and shows a friendly screen.

### Components

1. **`useConnectionHealth` hook** — pings `/health` every 10s, tracks consecutive failures. After 2 failures → `isDown = true`. On recovery → triggers page reload.

2. **`MaintenanceOverlay` component** — full-screen overlay with radar animation and "System update in progress" message. Auto-dismisses when backend returns.

3. **Wiring in `AppContent`** — renders overlay when `isDown`, reloads page on recovery to ensure clean state.

### Key Decisions

- Ping `/health` (lightweight) not `/api/ready` (heavier)
- 2 consecutive failures threshold to avoid single-blip false positives
- Full page reload on recovery — simpler than re-syncing all state
- No backend changes needed

### Files

| File | Action |
|------|--------|
| `app/frontend/src/hooks/useConnectionHealth.ts` | Created |
| `app/frontend/src/components/MaintenanceOverlay/MaintenanceOverlay.tsx` | Created |
| `app/frontend/src/App.tsx` | Modified — added hook + overlay |

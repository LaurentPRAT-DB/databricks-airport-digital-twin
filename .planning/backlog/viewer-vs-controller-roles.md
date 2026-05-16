---
status: proposed
area: architecture
related:
  - app/backend/main.py
  - app/frontend/src/App.tsx
---

# Viewer vs Controller Roles

## Problem

All connected clients share a single simulation engine. When any user switches airports or regenerates the simulation, every viewer sees the change. This is disruptive when multiple people are looking at the app simultaneously.

## Proposed Solution

Introduce two roles:

### Viewer (default)
- Receives real-time flight position broadcasts via WebSocket
- Can pan/zoom map, select flights, view details, use 3D mode
- Can browse gates, view reports, ask the assistant
- **Cannot** switch airports, regenerate simulations, or change scenario parameters

### Controller
- Everything a Viewer can do, plus:
- Switch airports (triggers engine restart for all)
- Start/stop simulations
- Change scenario parameters (weather events, traffic volume)
- Generate new simulation runs
- Access Data Ops dashboard controls

## Implementation Approach

1. **Role assignment** — query parameter (`?role=controller`), or simple token/password, or tied to Databricks user identity (SP = viewer, human = controller)
2. **Frontend** — conditionally render control buttons (airport switcher, sim controls) based on role. Viewer sees a "controlled by [user]" indicator.
3. **Backend** — WebSocket connection carries role metadata. Reject control commands from viewer connections.
4. **Optional: presenter indicator** — show who is currently controlling ("Presented by Laurent") so viewers know changes are intentional.

## Scope

- No per-session simulation (too heavy for now)
- Single shared simulation remains the model
- This is purely about who can trigger state changes

## Future Extension

Per-session simulations (each controller gets their own engine) could be added later by keying the engine on a session ID and routing WebSocket subscriptions accordingly.

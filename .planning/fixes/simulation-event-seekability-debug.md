---
status: backlog
area: frontend
related: [simulation, go-around, debug]
---

# Debug endpoint: simulation event seekability diagnostics

## Context

Go-around "Display on Map" fails to select the flight on prod. Can't access the app API directly (OAuth required). Need a debug endpoint to dump the currently loaded simulation's scenario events and verify whether each event's flight is findable in the frame data — replicating exactly what `seekToFlight` does on the frontend.

## Approach

Add `GET /api/simulation/debug-events` to the simulation router in `app/backend/api/simulation.py`. It reads the currently loaded demo file for a given airport, checks each go-around/diversion event against the frame data using the same ±30 frame search the frontend uses, and returns a diagnostic report.

### Endpoint: `GET /api/simulation/debug-events?airport={ICAO}`

Returns:
```json
{
  "airport": "KSFO",
  "total_frames": 821,
  "total_events": 29,
  "events": [
    {
      "event_type": "go_around",
      "time": "...",
      "icao24": "sim00001",
      "callsign": "UAL123",
      "seekable": true,
      "seek_frame_idx": 27,
      "seek_offset": 0,
      "found_phase": "approaching",
      "found_distance_deg": 0.12,
      "would_be_filtered": false,
      "padding_ms": 120000
    }
  ],
  "failures": 2,
  "failure_reasons": ["sim00005: NOT_IN_FRAMES", "sim00008: DIST_FILTERED"]
}
```

### File to modify: `app/backend/api/simulation.py`

Add endpoint at the bottom of the simulation router. Logic:
1. Get demo file path from `DemoSimulationService.get_demo_path(airport)`
2. Read JSON, group `position_snapshots` by timestamp into frames (same as existing `/demo/{icao}` endpoint)
3. Get `airport_center` from config
4. For each `go_around`/`diversion` event in `scenario_events`:
   - Extract `icao24`, `callsign` from the event
   - Compute seek target = event time - padding (120s for go_around, 60s for diversion)
   - Find nearest frame to seek target
   - Search ±30 frames for matching icao24/callsign
   - If found, check distance from airport center against `MAX_AIRBORNE_DIST_SQ = 0.4²`
   - Report seekable/not-seekable with reason
5. Return JSON diagnostic

### Verification

1. Run local tests: `uv run pytest tests/test_api_simulation*.py -q`
2. Commit + push → CD deploys
3. Open `https://airport-digital-twin-prod-.../api/simulation/debug-events?airport=KSFO` in browser (Databricks auth)
4. Check which events are `seekable: false` and examine `failure_reasons`

# Simulation vs Recorded Data Parity Test

## Context

The Airport Digital Twin has two replay modes: Simulation (synthetic engine-generated data) and Recorded (real ADS-B data from OpenSky). Both use the same PlaybackBar, flight list, detail panel, and map — but the user experience can diverge. The goal is to add E2E test scenarios that load a recording, exercise the same UI interactions as simulation mode, and verify the experience is equivalent.

Key differences found in code exploration:

| Aspect | Simulation | Recorded |
|--------|-----------|----------|
| Data source label | `simulation` | `opensky_recorded` |
| Scenario events | Rich (weather, go-around, diversion, runway, etc.) | Empty `[]` — no events derived yet |
| Weather snapshots | From simulation engine | Empty `[]` |
| Summary KPIs | Full (on_time_pct, delays, go-arounds, etc.) | Minimal (total_flights + scenario_name only) |
| PlaybackBar border | Default slate | Amber border (`border-t-2 border-amber-500/60`) |
| Schedule | Full with origin/destination/phase/gate | Derived from enriched events (41 entries for KSFO) |
| Flight fields | All populated | Same fields, but assigned_gate often null |
| Report modal events table | Full event list with clickable rows | Empty — "No events match filters" |
| Available data | 247 simulation files | 3 recordings (EDDF x2, KSFO x1) |

What should be identical (UX parity):

1. PlaybackBar appears and works (play/pause, speed, seek, time display)
2. Flight list shows flights with callsigns
3. Clicking a flight shows detail panel with position fields
4. Map shows aircraft markers
5. 2D/3D toggle works
6. No console errors

## Approach

Extend `scripts/test_ui_e2e.py` with a recorded data test section that runs after the existing simulation scenarios. The new scenarios:

1. Switch to Recorded mode — Click the "Recorded" button in the DataModeToggle
2. Load a recording — Select KSFO 2026-04-03 from the recording picker
3. Verify PlaybackBar appears — Same controls: play/pause, speed, time display
4. Verify flight list — Flights populate with callsigns
5. Click a flight from list — Detail panel shows position fields
6. Play/pause works — Time advances when playing
7. Compare with simulation baseline — Flight count > 0, all flights have valid positions, detail panel has same fields

## Implementation

Add scenarios S16–S22 to `scripts/test_ui_e2e.py`:

| ID  | Scenario                | What to check                                  | Pass criteria                                       |
|-----|-------------------------|-------------------------------------------------|-----------------------------------------------------|
| S16 | Switch to Recorded mode | Click "Recorded" toggle, recording picker opens | Picker modal visible                                |
| S17 | Load KSFO recording     | Select KSFO 2026-04-03                          | PlaybackBar appears, amber border, flights > 0      |
| S18 | Recorded PlaybackBar    | Play/pause, speed, sim time, flight count       | Same controls as simulation, time changes            |
| S19 | Recorded flight list    | Flight rows with callsigns                      | At least 1 row with mono callsign                   |
| S20 | Recorded flight detail  | Click flight row, check detail panel            | Callsign match, >=3 position fields (Lat/Lon/Alt/Speed/Heading) |
| S21 | Recorded data quality   | All flights have valid lat/lon (no NaN/null)    | 0 invalid positions                                 |
| S22 | Switch back to Simulation | Click "Simulation" toggle                     | Returns to sim mode, PlaybackBar without amber border |

## Key selectors (from code)

- DataModeToggle "Recorded" button: button with text "Recorded" inside `.bg-slate-700.rounded-lg` container
- Recording picker modal: `div.fixed.inset-0` with buttons showing airport/date
- PlaybackBar in recorded mode: has class `border-amber-500/60`
- Recording picker "Load" button: button with airport ICAO + date text
- Flights via API: `fetch('/api/flights')` from page context — works in both modes

## Files to modify

- `scripts/test_ui_e2e.py` — Add S16–S22 scenario functions + update `scenario_def` list

## Verification

Run `uv run python scripts/test_ui_e2e.py` — all 22 scenarios should pass (15 existing + 7 new).

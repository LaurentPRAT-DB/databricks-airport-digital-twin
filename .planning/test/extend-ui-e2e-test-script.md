# Plan: Extend UI E2E Test Script

## Context

The existing `scripts/test_ui_e2e.py` has 10 scenarios (S1-S10) covering page load, flight API, map marker clicks, 2D/3D toggle, airport switching, and console errors. The user wants new scenarios that exercise the flight list selection (left panel), flight detail verification (right panel), PlaybackBar controls, and simulation report modal.

These new scenarios depend on the simulation being active (PlaybackBar and Report only render when `sim.isActive`), so they must run after the existing S1/S2 which confirm page load and flight data.

**File:** `scripts/test_ui_e2e.py`

## New Scenarios (insert between S4 and S5)

### S4b: Flight List Selection

1. Wait for flight list to populate — locate the scrollable container with flight row buttons
2. Locate a flight row button inside the list — identify by font-mono callsign text
3. Click the first flight row
4. Verify the row gets selected state: `border-l-4 border-l-blue-500` or `bg-blue-50`
5. Capture the callsign text from the clicked row for cross-check in S4c

**Selectors:**
- Flight rows: button elements containing a span with class `font-mono`
- Selected state: element has class containing `border-l-blue-500`
- Callsign: `span.font-mono.font-medium` inside the button

### S4c: Flight Detail Panel Verification

1. After S4b selected a flight, check for "Flight Details" header text
2. Verify callsign matches what was clicked in S4b (cross-reference)
3. Check for presence of position data fields: text containing "Latitude", "Longitude", "Altitude"
4. Check for movement data: text containing "Speed", "Heading"
5. Verify at least one numeric value is displayed (not all dashes)

**Selectors:**
- Header: text "Flight Details"
- Callsign: `text-2xl font-bold font-mono` div
- Detail rows: text content "Latitude", "Longitude", "Altitude", "Speed", "Heading"
- Empty state: text "Select a flight to view details" (should NOT be visible after selection)

### S4d: PlaybackBar Controls

1. Wait for PlaybackBar to appear — `div.fixed` with `z-[1500]` at bottom of screen
2. Verify play/pause button exists — `button[title='Play']` or `button[title='Pause']`
3. Click play/pause to toggle — check title attribute changes
4. Verify sim time display — `font-mono.font-bold` element with time text (HH:MM format)
5. Verify "Local Time" label is visible
6. Verify speed buttons exist — at least one button with text matching `1x`
7. Click a speed button (e.g., `2x`) and verify it becomes active (`bg-blue-600`)
8. Verify flight count display — text matching pattern `\d+ flights`

**Selectors:**
- PlaybackBar container: `.fixed` element with PlaybackBar-specific classes at bottom
- Play/Pause: `button[title='Play']` or `button[title='Pause']`
- Sim time: element with classes `font-mono font-bold` inside PlaybackBar
- "Local Time": text "Local Time"
- Speed buttons: buttons with text `1x`, `2x`, `4x`, etc.
- Active speed: button with `bg-blue-600` and `text-white`
- Flight count: text matching `\d+ flights` in PlaybackBar
- Report button: button with text "Report" and `title="Generate simulation report"`

### S4e: Simulation Report Modal

1. Click the "Report" button in PlaybackBar — button with text "Report"
2. Wait for modal overlay — `div.fixed.inset-0` with `z-[2000]`
3. Verify report header contains airport code or "Simulation Report"
4. Check KPI cards exist — look for text: "On-Time %", "Avg Delay", "Total Flights"
5. Check event table has at least one row (if events exist) or table headers ("Time", "Category", "Description")
6. Check "Download Report" button exists
7. Click "Close" button to dismiss
8. Verify modal is gone

**Selectors:**
- Report button: `button:has-text("Report")` inside PlaybackBar
- Modal overlay: `div.fixed.inset-0` (z-index 2000)
- Report title: text containing "Simulation Report"
- KPI labels: "On-Time %", "Avg Delay", "Cancellations", "Go-Arounds", "Diversions", "Peak Flights", "Avg Hold", "Total Flights"
- Event filter buttons: buttons with event type labels
- Download button: `button:has-text("Download Report")`
- Close button: `button:has-text("Close")`

## Implementation Details

- Store shared state between scenarios via module-level dict (e.g., `_shared = {}`) to pass selected callsign from S4b -> S4c
- Each new scenario follows existing `Scenario` class + `run_scenario()` pattern
- PlaybackBar scenarios (S4d, S4e) need the simulation to be active — add a wait/check at start: if PlaybackBar not visible within 5s, `status = "skip"`
- Renumber: keep S1-S4 as is, add S4b/S4c/S4d/S4e (or renumber all to S1-S14), keep S5-S10 (airport switching) after
- Total scenarios: 14

## Ordering

| ID  | Scenario                      | Status   |
|-----|-------------------------------|----------|
| S1  | Initial page load             | existing |
| S2  | Flight list populates         | existing |
| S3  | Click flight marker on map    | existing |
| S4  | Switch 2D/3D view             | existing |
| S5  | Flight list selection         | NEW      |
| S6  | Flight detail panel           | NEW      |
| S7  | PlaybackBar controls          | NEW      |
| S8  | Simulation report             | NEW      |
| S9  | Switch airport MMMX           | existing (was S5) |
| S10 | Verify MMMX positions         | existing (was S6) |
| S11 | Switch airport LSGG           | existing (was S7) |
| S12 | Switch back KSFO              | existing (was S8) |
| S13 | Open simulation report        | existing (was S9 — may now be redundant, keep as post-switch check) |
| S14 | Console error summary         | existing (was S10) |

## Verification

```bash
# Quick syntax check
python -c "import scripts.test_ui_e2e"

# Run against deployed app
uv run python scripts/test_ui_e2e.py

# Check JSON report
cat test-results/ui_e2e_report.json | python -m json.tool
```

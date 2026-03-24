# Airport Digital Twin — Tester's Event Guide

What you can see, where you see it, and what to verify.

---

## A. THE MAP (2D and 3D)

This is the main view. Every aircraft is a marker on the map, moving in real-time
or during simulation replay.

### What you see per aircraft

| What you see | Where | Underlying event | How to verify |
|---|---|---|---|
| Aircraft icon on the map | Map marker | Position Snapshot | Icon should be at lat/lon, rotated to heading |
| Icon color matches flight phase | Marker color | Position Snapshot `.phase` | Approaching=one color, parked=another, etc. |
| Icon rotates as aircraft turns | Marker rotation | Position Snapshot `.heading` | Heading should match flight direction of travel |
| Aircraft moves smoothly between ticks | Marker position | Position Snapshot series | No teleporting, no jitter, no stuck markers |
| Gate label appears when parked | Marker label | Position Snapshot `.assigned_gate` | Label should read "B22" etc. when at gate |
| Hover tooltip shows callsign + phase + altitude | Marker tooltip | Position Snapshot | Tooltip text matches flight detail values |
| Aircraft appears on the map | First Position Snapshot | Flight spawned by engine | Should appear at correct approach/gate position |
| Aircraft disappears from the map | Last Position Snapshot | Flight completed (enroute exit or despawn) | Should not vanish mid-taxi or mid-approach |

### What you see for the airport

| What you see | Where | Underlying data | How to verify |
|---|---|---|---|
| Runway lines with "RWY 28L" labels | Map overlay | OSM geometry | Runways match real airport layout |
| Taxiway lines with "TWY A" labels | Map overlay | OSM geometry | Taxiways connect runways to gates |
| Terminal buildings (blue shapes) | Map overlay | OSM geometry | Buildings are in the right place |
| Gate dots with labels | Map overlay | OSM gate nodes | Gates appear at terminal edges |
| Apron areas (gray) | Map overlay | OSM geometry | Aprons surround terminals |

### What to test on the map

- **Approach path:** Click an approaching flight and enable trajectory. The line should come from outside the airport, descend toward the runway. Not orbit at ground level.
- **Landing:** Aircraft should transition from airborne to ground on the runway, not mid-taxiway.
- **Taxi:** Aircraft should follow taxiway paths, not cut across grass or through buildings.
- **Takeoff:** Aircraft should accelerate on the runway and climb away, not teleport.
- **No pile-ups:** Multiple aircraft should not stack on the same point.
- **Gate parking:** Aircraft should stop at a gate dot, not in the middle of a taxiway.

---

## B. FLIGHT LIST (left panel)

Scrollable list of all active flights.

| What you see | Where | Underlying event | How to verify |
|---|---|---|---|
| Callsign (e.g., UAL1781) | Row text | Position Snapshot `.callsign` | Matches flight detail when clicked |
| Phase badge (colored pill) | Row badge | Position Snapshot `.phase` | Color and label match the lifecycle stage |
| Altitude (e.g., "ALT: 3500ft") | Row text | Position Snapshot `.altitude` | 0 for ground flights, >0 for airborne |
| Speed (e.g., "SPD: 145kts") | Row text | Position Snapshot `.velocity` | 0 for parked, >0 for moving |
| Phase dot color | Row dot | Position Snapshot `.phase` | Consistent with map marker color |
| Flight count in header | Title area | Count of Position Snapshots in current frame | Should match visible markers on map |

### What to test

- **Search:** Type a callsign — only matching flights shown.
- **Sort by altitude:** Highest flight should be at top.
- **Click a flight:** Map should center on it, detail panel should open.
- **Count matches map:** Number in "Flights (N)" header should equal markers on map.

---

## C. FLIGHT DETAIL (right panel — click a flight)

All data for the selected aircraft.

### Position & Movement

| What you see | Label in panel | Underlying event | How to verify |
|---|---|---|---|
| Latitude | "Latitude" | Position Snapshot `.latitude` | Should match marker position on map |
| Longitude | "Longitude" | Position Snapshot `.longitude` | Should match marker position on map |
| Altitude | "Altitude" | Position Snapshot `.altitude` | 0 on ground, increases during climb, decreases during approach |
| Speed | "Speed" | Position Snapshot `.velocity` | ~0 when parked, 10-30 kts taxi, 130-160 kts approach, 250+ kts enroute |
| Heading | "Heading" | Position Snapshot `.heading` | 0-360 degrees, should match marker rotation |
| Vertical Rate | "Vertical Rate" | Position Snapshot `.vertical_rate` | Negative during descent (e.g., -1200 ft/min), positive during climb, 0 on ground |

### Flight Identity

| What you see | Label in panel | Underlying event | How to verify |
|---|---|---|---|
| Callsign | Header title | Position Snapshot `.callsign` | e.g., "UAL1781" |
| ICAO24 | Sub-header | Position Snapshot `.icao24` | 6-char hex ID |
| Aircraft type | Route section badge | Position Snapshot `.aircraft_type` | e.g., "B738", "A320" |
| Flight phase | Phase badge | Position Snapshot `.phase` | Should change as flight progresses through lifecycle |
| Origin → Destination | Route section | Schedule data | Arrow between airport codes |

### Trajectory Line (toggle on)

| What you see | Where | Underlying event | How to verify |
|---|---|---|---|
| Blue dashed line (past path) | On map, behind aircraft | All Position Snapshots for this flight up to now | Should trace the path the aircraft already flew |
| Dark dotted line (future path) | On map, ahead of aircraft | All Position Snapshots for this flight after now | Should show where the aircraft will go |
| Colored dots along the line | Circle markers on trajectory | Position Snapshots at intervals | Color = altitude: green <1000ft, yellow <5000ft, orange <15000ft, red >15000ft |
| Altitude tooltip on dots | Hover a dot | Single Position Snapshot | Shows time, altitude, speed at that point |
| Trajectory scoped to current phase | Line extent | Phase-filtered Position Snapshots | Approaching flights show approach path only, not taxi. Parked flights show no trajectory |

### What to test

- **Vertical rate shows a number:** Should NOT show "--" for airborne flights. Should show e.g., "-1200 ft/min" during descent.
- **Speed varies by aircraft type:** B738 approach ~137 kts, E175 approach ~126 kts. Not all 140 kts.
- **Phase changes at the right place:** Watch "approaching" → "landing" happen near the runway, not miles away.
- **Trajectory toggle:** Click "Show Trajectory" — line should appear on map. Click again — line should disappear.
- **Trajectory is phase-scoped:** An approaching flight's trajectory should only show the approach path. A parked flight should show no trajectory at all.

---

## D. DELAY PREDICTION (in flight detail panel)

Shown for every selected flight.

| What you see | Where | Underlying event | How to verify |
|---|---|---|---|
| Status dot (green/yellow/orange/red) | Delay section | ML Prediction (delay) | Green = On Time, Red = Severe delay |
| Delay minutes (e.g., "+12m") | Delay section | ML Prediction `.delay_minutes` | Positive number = delayed |
| Confidence bar | Delay section | ML Prediction `.confidence` | Percentage fill, higher = more certain |
| Delay category | Status label | ML Prediction `.category` | "On Time", "Slight", "Moderate", "Severe" |

---

## E. GATE RECOMMENDATIONS (in flight detail panel — arrivals only)

Shown when an arriving flight is selected.

| What you see | Where | Underlying event | How to verify |
|---|---|---|---|
| Up to 3 gate suggestions | Gate section | ML Prediction (gate_recommendation) | Gate IDs should exist at this airport |
| Score percentage | Per suggestion | `.score` | Higher = better fit |
| Taxi time estimate | Per suggestion | `.taxi_time` | Minutes from runway to gate |
| Reasons | Per suggestion | `.reasons` | e.g., "Close to terminal", "Compatible aircraft type" |

---

## F. GATE STATUS PANEL (right panel — no flight selected)

Overview of all gates at the airport.

| What you see | Where | Underlying event | How to verify |
|---|---|---|---|
| Available count (green) | Summary | Gates without a Gate Event `occupy` | Count should decrease as flights park |
| Occupied count (red) | Summary | Gates with active Gate Event `occupy` | Count should increase as flights park |
| Terminal filter pills | Header | OSM gate grouping | Click a terminal to filter |
| Gate tiles (colored grid) | Terminal view | Gate Events | Red = occupied, Amber = inbound, Green = vacant |
| Gate detail card | Click a tile | Gate Event + Position Snapshot | Shows callsign, aircraft type, flight phase |
| Congestion badge per terminal | Terminal row | Congestion Prediction | Low/Moderate/High/Critical |

### What to test

- **Gate turns red when flight parks:** Watch a flight taxi to gate — tile should change from green → amber → red.
- **Gate turns green when flight departs:** After pushback, tile should go back to green.
- **No double occupancy:** Two aircraft should never show at the same gate.
- **Click gate → selects flight on map:** Clicking the flight link in gate detail should highlight the aircraft on the map.

---

## G. TURNAROUND TIMELINE (in flight detail — parked flights only)

Shows ground handling progress at the gate.

| What you see | Where | Underlying event | How to verify |
|---|---|---|---|
| 7 phase circles (numbered) | Timeline bar | Turnaround Events | Arrival Taxi → Chocks On → Deboarding → Cleaning → Refueling → Boarding → Pushback |
| Completed phases (green check) | Phase circles | Turnaround Event `phase_complete` | Should progress left to right over time |
| Current phase (blue pulsing) | Phase circle | Turnaround Event `phase_start` (latest) | Only one phase should be "in progress" at a time |
| Pending phases (gray) | Phase circles | No turnaround event yet | Should be to the right of current |
| Overall progress % | Progress bar | Computed from completed sub-phases | Should go 0% → 100% during parked time |
| Gate number | Title | Gate Event `.gate` | Should match the gate shown on map |
| Estimated departure time | Footer | Computed from turnaround duration | Should be in the future |
| Active equipment | Equipment list | Current turnaround phase | e.g., "fuel truck" during refueling |

### What to test

- **Phases progress in order:** You should never see "Boarding" before "Deboarding" completes.
- **Only visible when parked:** If flight is taxi-ing or airborne, turnaround timeline should not appear.
- **Click a phase circle:** Should show detail card (completed/in-progress/pending).

---

## H. BAGGAGE STATUS (in flight detail — flights with callsign)

| What you see | Where | Underlying event | How to verify |
|---|---|---|---|
| Total bags | Stats grid | Baggage Event `.bag_count` | Reasonable number (50-300 for typical flights) |
| Delivered/Loaded count | Stats grid | Baggage Event processing | Should increase over time for parked flights |
| Connecting bags | Stats grid | Baggage Event bag details | Subset of total |
| Progress bar | Top of section | Bags processed / total | Yellow if misconnects detected |
| Misconnect alert | Yellow banner | Baggage Event risk detection | "X bag(s) at risk" |
| Carousel number | Header | Baggage assignment | For arrivals |

---

## I. FIDS — Flight Information Display (full-screen modal)

Airport departure/arrival board, like you see in a real terminal.

| What you see | Where | Underlying event | How to verify |
|---|---|---|---|
| Scheduled time | Time column | Schedule data | In chronological order |
| Flight number + airline | Flight column | Schedule `.callsign` | e.g., "UAL1781 · United Airlines" |
| "Live" badge | Flight column | Position Snapshot exists | Flights currently on the map get "Live" |
| Origin/Destination | From/To column | Schedule data | Airport codes |
| Gate number | Gate column | Gate Event `.gate` | Should match gate status panel |
| Status badge | Status column | Computed from phase + delay | On Time (green), Delayed (yellow), Boarding (blue), Departed/Arrived (gray), Cancelled (red) |
| Delay time | Remarks column | Schedule `.delay_minutes` | e.g., "+15m" with estimated time |

### What to test

- **Arrivals tab vs Departures tab:** Each tab should only show the correct flight type.
- **Click a "Live" flight:** Should select it on the map and close FIDS.
- **Status matches reality:** A flight shown as "Departed" should not still be at the gate on the map.
- **Cancelled flights:** Should show red "Cancelled" status (only in scenario simulations with weather).
- **Time order:** Flights should be sorted by scheduled time.

---

## J. WEATHER WIDGET (header bar)

| What you see | Where | Underlying event | How to verify |
|---|---|---|---|
| Flight category dot | Compact widget | Weather Snapshot `.category` | Green=VFR, Blue=MVFR, Red=IFR, Purple=LIFR |
| Temperature | Compact widget | Weather Snapshot `.temperature_c` | Celsius value |
| Wind | Compact widget | Weather Snapshot | Direction @ speed, with gusts |
| Visibility | Compact widget | Weather Snapshot `.visibility_nm` | Statute miles |
| Expanded METAR details | Click to expand | Full Weather Snapshot | Station, cloud layers, raw METAR text |

### What to test (simulation with weather scenario)

- **Weather changes during simulation:** When a scenario event type `weather` fires, the widget should update.
- **Flight category affects operations:** IFR weather should cause go-arounds and delays visible in FIDS.

---

## K. SIMULATION PLAYBACK BAR (bottom of screen)

Controls for simulation replay mode.

| What you see | Where | Underlying event | How to verify |
|---|---|---|---|
| Play/Pause button | Left of bar | Controls playback | Flights should move when playing, freeze when paused |
| Simulation time | Center | Current frame timestamp | Should advance as simulation plays |
| Progress bar | Center | Frame index / total frames | Clickable to seek to any point |
| **Event markers on progress bar** | Colored pips on the bar | Scenario Events | See below |
| Speed selector | Right | Playback speed | 1/4x to 60x — aircraft should move faster/slower accordingly |
| Flight count | Right | Active flights in current frame | Should go up as flights spawn, down as they complete |
| Scenario name | Header pill | Scenario config | e.g., "Thunderstorm" if using a scenario |

### Event markers on the progress bar

These colored pips appear on the timeline and represent scenario events that happened during the simulation:

| Pip color | Event type | What happened | Example |
|---|---|---|---|
| Amber | `weather` | Weather changed | Thunderstorm started, visibility dropped |
| Red | `runway` | Runway closed/reopened/reconfigured | Runway 28L closed for maintenance |
| Orange | `ground` | Ground infrastructure event | Taxiway closure, equipment failure |
| Blue | `traffic` | Traffic management | Ground stop, flow control change |
| Purple | `capacity` | Flight held at rate limit | Too many arrivals, flight held in air |

### What to test

- **Seek to an event marker:** Click a colored pip on the progress bar. The simulation should jump to that time. Check if the effect is visible (e.g., after a runway closure pip, fewer aircraft should be landing).
- **Speed change:** Switch from 1x to 10x — aircraft should visibly move faster.
- **Pause and resume:** Pause, verify all markers freeze. Resume, verify they start moving again.
- **Reach end:** Simulation should auto-pause at the last frame, not crash.

---

## L. SIMULATION FILE PICKER (modal)

| What you see | Where | Underlying event | How to verify |
|---|---|---|---|
| File name | List row | Simulation output file | e.g., "simulation_output_sfo_100.json" |
| Airport code | Row detail | Config `.airport` | Should match 3-letter airport code |
| Scenario name | Row detail | Summary `.scenario_name` | null for normal, name for scenario runs |
| Flight count (arrivals/departures) | Row detail | Summary `.arrivals` / `.departures` | e.g., "50 arr / 50 dep" |
| Duration | Row detail | Config `.duration_hours` | e.g., "24.0h" |
| File size | Row detail | File size on disk | Large files marked red and disabled |

---

## M. DATA OPS DASHBOARD (full-screen modal)

Backend data pipeline health.

| What you see | Where | Underlying event | How to verify |
|---|---|---|---|
| Acquisition health | Card | Data source polling stats | Green = healthy, Red = errors |
| Sync health | Card | UC ↔ Lakebase sync | Records synced count |
| Data freshness | Card | Staleness check | "In Sync" or lag time |
| Data source table | Table | Per-source stats | Error rate should be low (<5%) |
| Recent acquisitions | Activity log | Last N data fetches | Timestamps, record counts, latency |
| Recent syncs | Activity log | Last N sync operations | Direction (UC→LB or LB→UC), records |

---

## N. GENIE CHAT (floating panel)

Natural language Q&A about airport operations.

| What you see | Where | Underlying event | How to verify |
|---|---|---|---|
| User message | Chat bubble (right) | User typed question | Should appear after pressing send |
| Assistant answer | Chat bubble (left) | Genie API response | Should answer the question |
| SQL query | Expandable block | Generated SQL | Should be valid SQL |
| Data table | Below answer | Query results | Columns and rows from Databricks |
| Error message | Red-bordered bubble | API error | Should show retry button |

---

## O. CONNECTION STATUS (header bar)

| What you see | Where | Underlying event | How to verify |
|---|---|---|---|
| Green dot | Header right | WebSocket connected | Normal state |
| Yellow dot | Header right | WebSocket updating | Brief flash during data refresh |
| Red dot + tooltip | Header right | WebSocket error or disconnected | Tooltip shows last update time |

---

## SUMMARY: What triggers what you see

```
                    ┌─────────────────────────────────────────────────────────┐
                    │                  SIMULATION ENGINE                       │
                    │  (runs the clock, spawns flights, advances physics)      │
                    └──────────┬──────────────────────────────────┬────────────┘
                               │                                  │
                    ┌──────────▼──────────┐          ┌────────────▼────────────┐
                    │  FLIGHT STATE MACHINE│          │   SCENARIO PROCESSOR    │
                    │  (fallback.py)       │          │   (weather, runway,     │
                    │                      │          │    traffic, capacity)   │
                    └──┬───┬───┬───┬───┬──┘          └────────┬───┬───┬───┬───┘
                       │   │   │   │   │                      │   │   │   │
          ┌────────────┘   │   │   │   └──────────┐    ┌──────┘   │   │   └──────┐
          ▼                ▼   ▼   ▼              ▼    ▼          ▼   ▼          ▼
  ┌──────────────┐  ┌────┐ ┌──┐ ┌──────┐  ┌──────────┐ ┌────────┐┌───┐ ┌──────────┐
  │ Position     │  │Gate│ │ML│ │Turn- │  │ Weather  │ │Scenario││Go │ │ Capacity │
  │ Snapshot     │  │Evnt│ │  │ │around│  │ Snapshot │ │ Event  ││Arnd│ │ Hold     │
  └──────┬───────┘  └─┬──┘ └┬─┘ └──┬───┘  └────┬─────┘ └───┬────┘└─┬─┘ └────┬─────┘
         │            │     │      │            │           │       │        │
         ▼            ▼     ▼      ▼            ▼           ▼       ▼        ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           WHAT THE TESTER SEES                                      │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  MAP MARKERS ◄──── Position Snapshot (location, heading, phase → icon color)        │
│  TRAJECTORY  ◄──── Position Snapshot series (filtered by current phase)              │
│  FLIGHT LIST ◄──── Position Snapshot (callsign, altitude, speed, phase badge)       │
│  FLIGHT DETAIL ◄── Position Snapshot (all fields) + ML Prediction + Turnaround      │
│  GATE STATUS ◄──── Gate Event (occupy/vacate) + Congestion Prediction               │
│  TURNAROUND  ◄──── Turnaround Event (sub-phase start/complete)                      │
│  BAGGAGE     ◄──── Baggage Event (bag count, delivery progress)                     │
│  FIDS BOARD  ◄──── Schedule + Phase Transition + Gate Event → status computation    │
│  WEATHER     ◄──── Weather Snapshot (category, wind, visibility, METAR)             │
│  PLAYBACK BAR ◄─── Scenario Events (colored pips) + frame timestamps                │
│  DELAY PRED  ◄──── ML Prediction delay (minutes, confidence, category)              │
│  GATE RECO   ◄──── ML Prediction gate_recommendation (gate, score, taxi time)       │
│  CONNECTION  ◄──── WebSocket health (green/yellow/red dot)                          │
│  DATA OPS    ◄──── Backend pipeline metrics (acquisition, sync, freshness)          │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## EVENTS THE TESTER CANNOT SEE (debug only)

These events are recorded but have **no direct UI representation**. A tester
can only verify them by reading the diagnostics JSON file or checking API responses.

| Event | Why it's hidden | How a tester could indirectly notice |
|---|---|---|
| `SEPARATION_LOSS` | No UI indicator | Two aircraft visually too close on the map during approach |
| `RUNWAY_CONFLICT` | No UI indicator | Two aircraft on the same runway at the same time on the map |
| `GATE_CONFLICT` | No UI indicator | Aircraft stuck taxi-ing with no gate assignment, never reaches "parked" |
| `DEPARTURE_HOLD` | No UI indicator | Flight appears in FIDS as "Scheduled" but never shows up on the map |
| `GO_AROUND` (diag) | Scenario event version IS visible as a pip on playback bar | Aircraft suddenly climbs away from runway instead of landing |
| `TICK_STATS` | Performance metric only | Simulation stutters or slows down at certain points |
| `TAXI_SPEED_VIOLATION` | Not yet implemented | Aircraft moving unnaturally fast on taxiways |
| `Phase Transition` (diag) | Redundant with recorder version | Phase badge changes in flight detail panel |
| `Passenger Flow Events` | No dedicated UI panel | Indirectly feeds terminal congestion calculations |
| `BHS Metrics` | No dedicated UI panel | Could surface in future baggage dashboard |

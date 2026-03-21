# Airport Digital Twin — User Guide

Welcome to the Airport Digital Twin! This guide walks you through every feature with real screenshots so you can get the most out of the platform in minutes.

**Live app**: [airport-digital-twin-dev](https://airport-digital-twin-dev-7474645572615955.aws.databricksapps.com) | **Local**: http://localhost:3000

---

## Table of Contents

- [Your First 60 Seconds](#your-first-60-seconds)
- [The Dashboard at a Glance](#the-dashboard-at-a-glance)
- [Finding and Tracking Flights](#finding-and-tracking-flights)
- [The 2D Map](#the-2d-map)
- [The 3D View](#the-3d-view)
- [Switching Airports](#switching-airports)
- [Flight Details & ML Predictions](#flight-details--ml-predictions)
- [FIDS — The Arrivals & Departures Board](#fids--the-arrivals--departures-board)
- [Weather at a Glance](#weather-at-a-glance)
- [Gate Status & Congestion](#gate-status--congestion)
- [Platform Integration (Databricks)](#platform-integration-databricks)
- [Simulation Mode](#simulation-mode)
- [For Data Scientists: ML Models](#for-data-scientists-ml-models)
- [For IT Ops: Data Architecture](#for-it-ops-data-architecture)
- [Keyboard Shortcuts](#keyboard-shortcuts)
- [Troubleshooting](#troubleshooting)

---

## Your First 60 Seconds

Open the app and you'll see a radar animation while data loads. Within seconds, you're looking at a live airport.

Here's what to try first:

1. **Click any flight** in the left panel to see its details, delay prediction, and gate recommendation
2. **Type a callsign** (like "UAL") in the search box to filter flights instantly
3. **Click "3D"** above the map to enter the immersive 3D view
4. **Click the airport button** (e.g., "KSFO") to switch to another airport — try CDG (Paris) or HND (Tokyo)
5. **Click "FIDS"** in the header to see the familiar arrivals/departures board

That's it — you're already using every major feature. Read on for the details.

---

## The Dashboard at a Glance

![Application Overview](screenshots/01-overview.png)

The dashboard has five main areas that work together:

```
┌──────────────────────────────────────────────────────────────────────┐
│  A: HEADER BAR                                                        │
│  Airport selector | Flight count | Data source | Weather | FIDS |     │
│  Phase legend | Connection | Platform links                          │
├────────────┬──────────────────────────────────────┬──────────────────┤
│            │                                      │                  │
│ B: FLIGHT  │         C: MAP VIEW                  │ D: FLIGHT        │
│    LIST    │    (2D Leaflet or 3D Three.js)       │    DETAILS       │
│            │                                      │                  │
│  Search    │    Real airport infrastructure       │  Position        │
│  Sort      │    from OpenStreetMap:               │  Movement        │
│  Click to  │    - Terminals (blue)                │  Delay predict.  │
│  select    │    - Gates (green dots)              │  Gate recommend.  │
│            │    - Taxiways (yellow lines)         │  Trajectory      │
│            │    - Aprons (gray areas)             │                  │
│            │                                      ├──────────────────┤
│            │    Flight markers color-coded        │ E: GATE STATUS   │
│            │    by phase                          │  Available/       │
│            │                                      │  Occupied         │
│            │                                      │  Congestion       │
├────────────┴──────────────────────────────────────┴──────────────────┤
│  Footer: Flight count, last update time                               │
└──────────────────────────────────────────────────────────────────────┘
```

### Header Bar Components

| Component | What It Shows | Try This |
|---|---|---|
| **Airport button** (e.g., "KSFO (SFO)") | Current airport | Click to switch airports |
| **Flights: 50** | Total tracked flights | — |
| **Data source badge** | `Live` or `Demo Mode (synthetic)` | Live = real data flowing |
| **Weather badge** | Temperature, wind, visibility | Click to expand full METAR |
| **FIDS** | Opens arrivals/departures board | Click to open |
| **Phase legend** | Ground / Climbing / Descending / Cruising | Colors match flight markers |
| **Connected** | WebSocket health | Green = real-time updates active |
| **Platform** | Databricks tools (Lakeview, Genie, etc.) | Click to access |

---

## Finding and Tracking Flights

![Flight Search](screenshots/05-flight-search.png)
*Searching for "UAL" instantly filters to all United Airlines flights*

### Search

The search box at the top of the flight list filters flights as you type. It matches callsign prefixes, so:
- **"UAL"** shows all United flights
- **"AAL"** shows all American Airlines
- **"BAW"** shows British Airways

Search is case-insensitive and instant.

### Sort Options

Use the dropdown below the search box:
- **Callsign (A-Z)** — Alphabetical by callsign
- **Altitude (High-Low)** — Highest aircraft first

### Flight Cards

Each card in the list shows:

| Field | Example | Meaning |
|---|---|---|
| **Callsign** | UAL123 | Flight identifier |
| **Phase badge** | `DSC` | GND=Ground, CLB=Climbing, CRZ=Cruising, DSC=Descending |
| **Route** | SFO → ORD | Origin and destination |
| **Altitude** | 35,000 ft | Current altitude |
| **Speed** | 450 kts | Ground speed |

**Click any card** to select the flight. It highlights on the map and shows full details in the right panel.

---

## The 2D Map

The default view uses Leaflet with OpenStreetMap tiles, overlaid with real airport infrastructure.

### What You See on the Map

| Feature | Visual | Source |
|---|---|---|
| **Terminals** | Blue polygons | OpenStreetMap building footprints |
| **Gates** | Green circle markers with labels | OSM gate positions |
| **Taxiways** | Yellow polylines | OSM taxiway centerlines |
| **Aprons** | Gray polygons | OSM parking/ramp areas |
| **Flights** | Color-coded aircraft icons | Live or synthetic position data |

### Flight Marker Colors

| Color | Phase |
|---|---|
| Yellow | Ground (taxiing or at gate) |
| Green | Climbing (just departed) |
| Red | Descending (on approach) |
| Blue | Cruising (en route) |

### Interacting with the Map

- **Zoom**: `+`/`-` buttons or scroll wheel
- **Pan**: Click and drag
- **Select a flight**: Click its marker — shows a pulsing highlight
- **Hover**: Shows callsign tooltip

---

## The 3D View

![3D Visualization](screenshots/08-3d-view.png)
*The 3D view shows aircraft at actual altitude with realistic GLTF models and extruded terminal buildings*

Click the **3D** button above the map to switch. Click **2D** to go back.

### What Makes the 3D View Special

- **Realistic aircraft models**: GLTF 3D models for major airline liveries (United, Delta, American, British Airways, and more) with procedural geometry fallback
- **True altitude**: Aircraft are positioned at their actual altitude in 3D space — you can see arrivals descending and departures climbing
- **Terminal buildings**: OSM terminal footprints extruded into 3D structures
- **Flight labels**: Hovering tags show callsign, altitude, and speed
- **Origin-aware trajectories**: Approach paths come from the direction of the origin airport; departure paths head toward the destination

### 3D Camera Controls

| Action | Control |
|---|---|
| **Rotate** | Left-click + drag |
| **Pan** | Right-click + drag |
| **Zoom** | Scroll wheel |

### Performance Tip

The 3D view uses WebGL and runs best on Chrome or Firefox with a dedicated GPU. If it feels slow, try reducing the browser window size or switching back to 2D.

---

## Switching Airports

![Airport Selector](screenshots/02-airport-selector.png)
*Click the airport button to reveal the dropdown with 12 presets and a custom ICAO input*

### Preset Airports

| ICAO | IATA | Airport | Region |
|---|---|---|---|
| KSFO | SFO | San Francisco International | US West |
| KJFK | JFK | John F. Kennedy International | US East |
| KLAX | LAX | Los Angeles International | US West |
| KORD | ORD | O'Hare International | US Central |
| KATL | ATL | Hartsfield-Jackson Atlanta | US South |
| EGLL | LHR | London Heathrow | Europe |
| LFPG | CDG | Charles de Gaulle | Europe |
| OMAA | AUH | Abu Dhabi International | Middle East |
| OMDB | DXB | Dubai International | Middle East |
| RJTT | HND | Tokyo Haneda | Asia |
| VHHH | HKG | Hong Kong International | Asia |
| WSSS | SIN | Singapore Changi | Asia |

### Custom Airport

Enter any 4-letter ICAO code in the text field and click **Load**. The system will fetch that airport's real infrastructure from OpenStreetMap.

### What Happens During a Switch

![Airport Switching](screenshots/03-airport-switching.png)
*A progress overlay appears while the airport loads*

When you switch airports, the system:
1. Fetches real infrastructure from OpenStreetMap (terminals, gates, taxiways, aprons)
2. Generates calibrated synthetic flights positioned at the airport
3. Centers the map on the new airport
4. Loads weather data for the location
5. Hot-swaps ML models for the new airport's profile

The progress overlay shows status messages as each step completes. Most airports load in 1-3 seconds.

### See It in Action: Paris CDG

![CDG Airport](screenshots/10-cdg-airport.png)
*Charles de Gaulle (Paris) loaded with real OSM data — every terminal, taxiway, and apron rendered from community-sourced geospatial data*

Notice how different airports have different layouts: CDG has its distinctive circular Terminal 1, while SFO has its compact H-shaped international terminal. All from OpenStreetMap — no manual data entry.

---

## Flight Details & ML Predictions

![Flight Selected](screenshots/04-flight-selected.png)
*Select a flight to see position, movement, delay prediction, and gate recommendations*

Click any flight to open its details panel on the right.

### Position & Movement

| Field | What It Shows |
|---|---|
| **Latitude / Longitude** | Current GPS coordinates |
| **Altitude** | Current altitude in feet |
| **Speed** | Ground speed in knots |
| **Heading** | True heading in degrees |
| **Vertical Rate** | Climb/descent rate (ft/min) |

### Delay Prediction (ML)

The ML model predicts flight delays in real time:

| Field | Example | Meaning |
|---|---|---|
| **Expected Delay** | 13 min | Predicted delay in minutes |
| **Category** | `On Time` / `Slight` / `Moderate` / `Severe` | Color-coded severity |
| **Confidence** | 78% | Model confidence score |

**How delay prediction works**: The model considers time of day (peak hours = more delays), day of week (weekends = fewer delays), altitude category (ground = likely delayed), and velocity (slow = taxi congestion). See [ML Models](ML_MODELS.md) for full details.

### Gate Recommendations (ML)

The top 3 recommended gates, each with:

| Field | Meaning |
|---|---|
| **Gate ID** | Terminal and gate (e.g., A1, B3) |
| **Score** | Quality score (0-100%) — higher is better |
| **Taxi Time** | Estimated minutes to reach the gate |
| **Reasons** | Why this gate was recommended (availability, terminal match, proximity) |

### Show Trajectory

Click **"Show Trajectory"** to display the flight's path on the map. Approach trajectories come from the direction of the origin airport; departure trajectories head toward the destination.

---

## FIDS — The Arrivals & Departures Board

![FIDS Modal](screenshots/06-fids-modal.png)
*The FIDS looks and feels like the departure boards you see in real airport terminals*

Click the **FIDS** button in the header to open the Flight Information Display System.

### Arrivals Tab

Shows all incoming flights with:
- **Time**: Scheduled arrival time
- **Flight**: Callsign and airline
- **From**: Origin airport
- **Gate**: Assigned gate
- **Status**: On Time, Arrived, Delayed (with delay amount)

### Departures Tab

Shows all outbound flights with:
- **Time**: Scheduled departure time
- **Flight**: Callsign and airline
- **To**: Destination airport
- **Gate**: Departure gate
- **Status**: On Time, Boarding, Departed, Delayed

### Status Colors

| Status | Color | Meaning |
|---|---|---|
| **Arrived / On Time** | Green | Normal operations |
| **Delayed** | Red/Orange | Behind schedule (shows delay minutes) |
| **Boarding** | Yellow | Passengers boarding |

---

## Weather at a Glance

![Weather Widget](screenshots/07-weather-widget.png)

The weather badge in the header shows a compact summary. Click it to expand the full panel.

### METAR Data (Current Conditions)

| Field | What It Means |
|---|---|
| **Temperature** | Current temp in Celsius |
| **Wind** | Direction (degrees true) and speed (knots) |
| **Visibility** | Distance in statute miles |
| **Altimeter** | Barometric pressure (inHg) |

### Flight Categories

| Category | Conditions | Impact |
|---|---|---|
| **VFR** | Good visibility, high ceiling | Normal operations |
| **MVFR** | Reduced visibility (3-5 mi) | Caution, slower approaches |
| **IFR** | Low visibility (1-3 mi) | Instrument approaches only |
| **LIFR** | Very low visibility (<1 mi) | Significant delays likely |

Weather updates automatically and affects the operational picture — expect more delays during IFR/LIFR conditions.

---

## Gate Status & Congestion

The Gate Status panel (bottom-right corner) provides terminal-level situational awareness.

### Gate Grid

Each terminal shows its gates in a grid:
- **Green** = Available
- **Red** = Occupied

Numbers at the top show total available vs. occupied.

### Area Congestion

Below the gate grid, congestion indicators show how busy each airport zone is:

| Level | Color | Meaning |
|---|---|---|
| **Low** | Green | Normal operations, no delays |
| **Moderate** | Yellow | Minor delays possible |
| **High** | Orange | Significant congestion |
| **Critical** | Red | Operations at capacity |

This is especially useful for identifying bottlenecks — if a runway shows "Critical" congestion, expect arrival delays.

---

## Platform Integration (Databricks)

![Platform Links](screenshots/09-platform-links.png)
*Click "Platform" in the header to access the full Databricks toolchain*

The Airport Digital Twin is a showcase for the Databricks platform. Click **Platform** to access:

| Tool | What You Can Do |
|---|---|
| **Flight Dashboard** (Lakeview) | View aggregated KPIs: on-time %, delay trends, busiest routes, hourly throughput |
| **Ask Genie** | Query flight data in natural language — "Show me all delayed flights from JFK this week" |
| **Data Lineage** | Trace any data point from source (OpenSky API) through Bronze/Silver/Gold to the frontend |
| **ML Experiments** (MLflow) | Track model training runs, compare metrics, manage model versions |
| **Unity Catalog** | Browse all tables, schemas, and column-level metadata |

### For Executives

The **Flight Dashboard** is your go-to for high-level KPIs. Set up Lakeview alerts to get notified when on-time performance drops below your threshold.

### For Data Scientists

**Ask Genie** lets you explore data conversationally without writing SQL. **ML Experiments** shows model performance over time.

### For IT Ops

**Data Lineage** helps trace data quality issues. **Unity Catalog** provides the full governance view.

---

## Simulation Mode

For demos, testing, or offline analysis, you can run deterministic airport simulations.

### Quick Start

```bash
# Debug mode — fast, 4h simulated, 20 flights
python -m src.simulation.cli --config configs/simulation_sfo_50_debug.yaml

# Full day — 24h simulated, 50 flights each way
python -m src.simulation.cli --airport SFO --arrivals 50 --departures 50 --seed 42
```

### What the Simulation Produces

- **Flight state transitions**: Every flight progresses through realistic phases (taxi-out, takeoff, climb, cruise, descend, approach, land, taxi-in)
- **Gate assignments**: ML-optimized gate allocation
- **Turnaround events**: Pushback, fueling, baggage, catering, cleaning
- **Weather effects**: Conditions affect delay distributions
- **Event log**: Structured JSON output for analysis

### Configuration

Simulations are configured via YAML files or CLI flags. Key parameters:
- `airport`: IATA code
- `arrivals` / `departures`: Number of flights
- `duration_hours`: Simulated time span
- `seed`: Random seed for reproducibility

See the full [Simulation Guide](simulation_user_guide.md) for details.

---

## For Data Scientists: ML Models

Three ML models power the real-time predictions you see in the UI:

### Delay Prediction

**How it works**: Rule-based heuristic considering time of day, day of week, altitude, velocity, and heading. Designed for demo reliability with realistic distributions.

| Factor | Effect |
|---|---|
| Peak morning (7-9am) | +15 min delay |
| Peak evening (5-7pm) | +12 min delay |
| Weekend | -3 min delay |
| Ground aircraft | +8 min delay |
| Cruising | -2 min delay |

**Categories**: On Time (<5 min), Slight (5-15), Moderate (15-30), Severe (>30)

### Gate Recommendation

**How it works**: Scoring algorithm with four weighted factors:
- **Availability** (50%): Available gates score highest
- **Terminal match** (25%): International → Terminal B, Domestic → Terminal A
- **Proximity** (15%): Closer to runway = faster turnaround
- **Delay penalty** (10%): Severely delayed flights get deprioritized

### Congestion Prediction

**How it works**: Counts flights per airport area, compares to capacity thresholds:
- **LOW** (<50% capacity) → 0 min wait
- **MODERATE** (50-75%) → 1-3 min wait
- **HIGH** (75-90%) → 3-8 min wait
- **CRITICAL** (>90%) → 5-15 min wait

### Model Registry

All models are wrapped in `AirportModelRegistry` — when you switch airports, models are hot-swapped with per-ICAO configurations. See [ML Models Documentation](ML_MODELS.md) for code-level details.

---

## For IT Ops: Data Architecture

### Three-Tier Serving

```
Request → Lakebase (PostgreSQL, <10ms)
          ↓ fallback
          Unity Catalog (Delta, ~100ms)
          ↓ fallback
          Synthetic Generator (<5ms)
```

The app never goes dark — if Lakebase is unreachable, it transparently falls back to Delta tables, then to synthetic data.

### Pipeline Health

Check `GET /api/data-ops/dashboard` for:
- **Acquisition stats**: Records ingested, source, timestamps
- **Sync status**: Lakebase sync lag
- **Data freshness**: How stale is the latest data
- **History sync**: Trajectory data pipeline status

### Key Endpoints for Monitoring

| Endpoint | Purpose |
|---|---|
| `GET /health` | Overall health + data source connectivity |
| `GET /api/ready` | Readiness probe for load balancers |
| `GET /api/data-sources` | Current data source and fallback chain |
| `GET /api/debug/logs?pattern=DIAG` | Last 2,000 log entries with filtering |
| `GET /api/data-ops/dashboard` | Full pipeline health dashboard |

### Deploying Updates

```bash
# Build + deploy (always use DABs)
cd app/frontend && npm run build
databricks bundle deploy --target dev
```

Never use `databricks apps deploy` directly — always go through DABs for reproducible, version-controlled deployments.

---

## Keyboard Shortcuts

| Key | Action |
|---|---|
| `2` | Switch to 2D map view |
| `3` | Switch to 3D visualization |
| `Esc` | Deselect current flight |
| `/` | Focus search box |
| `Up` / `Down` | Navigate flight list |
| `Enter` | Select highlighted flight |

---

## Troubleshooting

### "Demo Mode (synthetic data)" showing in header

**What it means**: The backend can't reach live data sources (Lakebase or Delta tables).

**What to check**:
1. Is the Lakebase instance running?
2. Are OAuth credentials valid (for Databricks Apps)?
3. Is the Databricks workspace reachable?
4. Check `GET /health` for source-level status

**Note**: Demo Mode still provides a fully functional experience with realistic synthetic data — great for demos and development.

### Flights aren't updating

1. Check the **"Connected"** indicator in the header — should be green
2. Open browser DevTools console for WebSocket errors
3. Hit `GET /health` to verify backend is running
4. Check if the DLT pipeline is running

### Airport switch fails or hangs

1. The Overpass API (OpenStreetMap) might be rate-limited or down — try again in 30 seconds
2. Try a different airport — some tiny airports have sparse OSM data
3. Check backend logs: `GET /api/debug/logs?pattern=OSM`
4. Refresh the page and retry

### 3D view is slow

1. Use Chrome or Firefox (best WebGL support)
2. Close other GPU-intensive apps
3. Reduce browser window size
4. Switch to 2D view on lower-end hardware

### Delay predictions seem off

The current model is rule-based (not trained on historical data) — it produces realistic distributions for demo purposes. See [ML Models](ML_MODELS.md) for the roadmap to ML-trained models.

### Gate recommendations not showing

1. You need to **click a flight** first to see its recommendations
2. Check the backend logs for prediction service errors
3. The flight needs a valid callsign for domestic/international classification

---

*Documentation updated: 2026-03-21 | Version: 3.0*

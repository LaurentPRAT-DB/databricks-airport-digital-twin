# Airport Digital Twin — End-User UI Test Plan

> **App URL:** https://airport-digital-twin-dev-7474645572615955.aws.databricksapps.com
> **Date:** 2026-03-12
> **Total Tests:** 85

---

## Legend

| Column | Description |
|--------|-------------|
| **ID** | Unique test identifier (area-number) |
| **Priority** | P0 = critical, P1 = high, P2 = medium, P3 = nice-to-have |
| **Action** | Step-by-step user actions |
| **Expected Result** | What the user should observe |
| **Precondition** | Required state before starting |
| **Component** | Source file(s) involved |
| **Auto-testable** | Can be automated with Vitest/Playwright (Y/N) |

---

## 1. Loading Screen & Initialization

| ID | Test Name | Priority | Action | Expected Result | Precondition | Component | Auto-testable |
|----|-----------|----------|--------|-----------------|--------------|-----------|---------------|
| LS-01 | Loading screen displays on cold start | P0 | Open app URL in fresh browser | Radar sweep animation visible, "Airport Digital Twin" title, airport ICAO code, animated dots status text | None | `App.tsx:LoadingScreen` | Y |
| LS-02 | Status message updates during load | P0 | Observe loading screen text | Status text cycles through backend init phases (e.g., "Initializing", "Loading flights...") with animated dots | Cold start | `App.tsx:LoadingScreen` | Y |
| LS-03 | App transitions to main view when ready | P0 | Wait for backend `/api/ready` to return `ready: true` | Loading screen disappears, header + map + panels all visible | Cold start | `App.tsx:AppContent` | Y |
| LS-04 | Loading screen shows current airport code | P1 | Observe loading screen below title | ICAO code (e.g., "KSFO") shown in monospace text below title | Cold start | `App.tsx:LoadingScreen` | Y |

---

## 2. Header

| ID | Test Name | Priority | Action | Expected Result | Precondition | Component | Auto-testable |
|----|-----------|----------|--------|-----------------|--------------|-----------|---------------|
| HD-01 | Header displays title and version | P0 | Observe header bar | "Airport Digital Twin" title, version string `v{X} · #{N}`, build time tooltip on hover | App loaded | `Header.tsx` | Y |
| HD-02 | Flight count badge shows correct number | P0 | Observe header flight counter | "Flights: {N}" matches number of flights in left panel list | App loaded | `Header.tsx` | Y |
| HD-03 | Demo mode banner appears for synthetic data | P1 | Load app with synthetic/fallback data | Orange "Demo Mode (synthetic data)" badge visible in header | Synthetic data active | `Header.tsx` | Y |
| HD-04 | Connection status indicator — connected | P0 | Observe status dot (right side of header) | Green dot, "Connected" text, last-updated timestamp | App loaded, no errors | `Header.tsx` | Y |
| HD-05 | Connection status indicator — error | P1 | Simulate API failure / disconnect network | Red dot, "Error" text | API unreachable | `Header.tsx` | Y |
| HD-06 | Connection status indicator — updating | P2 | Observe during data refresh cycle | Yellow pulsing dot, "Updating" text | Data refresh in progress | `Header.tsx` | Y |
| HD-07 | Flight phase legend colors are correct | P2 | Observe legend in header | Ground=gray, Climbing=green, Descending=orange, Cruising=blue dots with labels | App loaded | `Header.tsx` | Y |

---

## 3. Airport Selector

| ID | Test Name | Priority | Action | Expected Result | Precondition | Component | Auto-testable |
|----|-----------|----------|--------|-----------------|--------------|-----------|---------------|
| AS-01 | Dropdown displays current airport | P0 | Observe selector button | Shows current ICAO + IATA code (e.g., "KSFO (SFO)") | App loaded | `AirportSelector.tsx` | Y |
| AS-02 | Dropdown opens on click | P0 | Click airport selector button | Dropdown appears with custom ICAO input, region-grouped airport list, pre-load button | App loaded | `AirportSelector.tsx` | Y |
| AS-03 | Airports grouped by region | P1 | Open dropdown, scroll through list | Airports grouped under region headers: Americas, Europe, Middle East, Asia-Pacific, Africa | Dropdown open | `AirportSelector.tsx` | Y |
| AS-04 | Cache status indicators | P1 | Open dropdown | Green dot = cached (fast switch), gray dot = not cached (will fetch from OSM) | Dropdown open | `AirportSelector.tsx` | Y |
| AS-05 | Current airport has checkmark | P2 | Open dropdown | Current airport row highlighted blue with checkmark icon | Dropdown open | `AirportSelector.tsx` | Y |
| AS-06 | Switch airport from list | P0 | Open dropdown → Click different airport (e.g., EGLL) | Dropdown closes, progress overlay appears, map recenters on new airport, flights regenerated | Dropdown open | `AirportSelector.tsx` | Y |
| AS-07 | Custom ICAO input | P1 | Open dropdown → Type "RJTT" in input → Press Enter (or click Load) | Airport loads, map recenters on Tokyo Haneda | Dropdown open | `AirportSelector.tsx` | Y |
| AS-08 | Custom ICAO validation | P2 | Type "AB" (< 3 chars) → Click Load | Load button disabled, nothing happens | Dropdown open | `AirportSelector.tsx` | Y |
| AS-09 | Error display on invalid airport | P1 | Enter invalid ICAO "ZZZZ" → Load | Red error banner appears in dropdown with failure message | Dropdown open | `AirportSelector.tsx` | Y |
| AS-10 | Error clears when dropdown reopens | P2 | Trigger error → Close dropdown → Reopen | Error message is gone | Previous error state | `AirportSelector.tsx` | Y |
| AS-11 | Selector disabled during loading | P1 | Click airport while another is loading | Button grayed out with spinner, not clickable | Airport switch in progress | `AirportSelector.tsx` | Y |
| AS-12 | Pre-load all airports | P2 | Open dropdown → Click "Pre-load All" button | Button shows spinner + "Pre-loading...", cache dots turn green progressively | Dropdown open, some uncached | `AirportSelector.tsx` | Y |
| AS-13 | Dropdown closes on outside click | P1 | Open dropdown → Click anywhere outside | Dropdown closes | Dropdown open | `AirportSelector.tsx` | Y |
| AS-14 | Selecting current airport is no-op | P2 | Open dropdown → Click already-selected airport | Dropdown closes, no reload triggered | Dropdown open | `AirportSelector.tsx` | Y |

---

## 4. Airport Switch Progress

| ID | Test Name | Priority | Action | Expected Result | Precondition | Component | Auto-testable |
|----|-----------|----------|--------|-----------------|--------------|-----------|---------------|
| SP-01 | Progress overlay appears during switch | P0 | Switch airport | Semi-transparent overlay covers header area with step message and progress bar | Airport switch triggered | `AirportSwitchProgress.tsx` | Y |
| SP-02 | Progress bar advances with steps | P1 | Observe during airport switch | Progress bar width increases as steps complete (step N/7), message text updates | Airport switch in progress | `AirportSwitchProgress.tsx` | Y |
| SP-03 | 3D loading overlay during switch | P0 | Switch to 3D view → Switch airport | 3D canvas shows semi-transparent black overlay with spinner, progress message, and progress bar | 3D view active, switch triggered | `Map3D.tsx` | Y |

---

## 5. Flight List (Left Panel)

| ID | Test Name | Priority | Action | Expected Result | Precondition | Component | Auto-testable |
|----|-----------|----------|--------|-----------------|--------------|-----------|---------------|
| FL-01 | Flight list populates | P0 | Observe left panel after load | Scrollable list of flights with callsign, altitude, phase color indicator | App loaded | `FlightList.tsx` | Y |
| FL-02 | Flight count shown in header | P0 | Observe "Flights (N)" in panel header | Count matches total visible flights | App loaded | `FlightList.tsx` | Y |
| FL-03 | Search by callsign | P0 | Type "UAL" in search box | List filters to show only flights matching "UAL" in callsign or ICAO24 | App loaded | `FlightList.tsx` | Y |
| FL-04 | Search shows "no results" message | P1 | Type "ZZZZZ" in search box | "No flights match your search" message displayed | App loaded | `FlightList.tsx` | Y |
| FL-05 | Sort by callsign (A-Z) | P1 | Select "Callsign (A-Z)" from sort dropdown | Flights sorted alphabetically by callsign | App loaded | `FlightList.tsx` | Y |
| FL-06 | Sort by altitude (High-Low) | P1 | Select "Altitude (High-Low)" from sort dropdown | Flights sorted by altitude descending | App loaded | `FlightList.tsx` | Y |
| FL-07 | Click flight to select | P0 | Click a flight row in list | Row highlights, right panel shows flight details, map centers/highlights flight | App loaded | `FlightList.tsx` | Y |
| FL-08 | Click selected flight to deselect | P1 | Click already-selected flight row | Selection clears, detail panel returns to "Select a flight" placeholder | Flight selected | `FlightList.tsx` | Y |
| FL-09 | Loading spinner when no flights yet | P2 | Observe during initial data fetch | Spinner with "Loading flights..." message | Data still loading | `FlightList.tsx` | Y |

---

## 6. 2D Map (Leaflet)

| ID | Test Name | Priority | Action | Expected Result | Precondition | Component | Auto-testable |
|----|-----------|----------|--------|-----------------|--------------|-----------|---------------|
| M2-01 | Map renders centered on airport | P0 | Load app | OSM tile map centered on current airport with correct zoom | App loaded | `AirportMap.tsx` | Y |
| M2-02 | Flight markers visible on map | P0 | Observe map | Colored markers for each flight positioned at correct lat/lon | App loaded, flights exist | `FlightMarker.tsx` | Y |
| M2-03 | Airport overlay renders | P0 | Observe map | Terminal polygons, taxiways, aprons, runways drawn as overlay shapes | App loaded | `AirportOverlay.tsx` | Y |
| M2-04 | Click flight marker to select | P0 | Click a flight marker on map | Flight selected, detail panel opens, marker highlighted | App loaded | `FlightMarker.tsx` | Y |
| M2-05 | Map recenters on airport switch | P0 | Switch airport via selector | Map smoothly flies to new airport center with default zoom | Airport switch | `AirportMap.tsx:MapRecenter` | Y |
| M2-06 | Status overlay shows flight count | P2 | Observe bottom-left overlay on map | "Flights: N", "Last updated: HH:MM:SS" displayed | App loaded | `AirportMap.tsx` | Y |
| M2-07 | Trajectory line on map | P1 | Select flight → Enable "Show Trajectory" toggle | Polyline trajectory drawn on map from flight history points | Flight selected, trajectory toggled on | `TrajectoryLine.tsx` | Y |
| M2-08 | Pan and zoom | P1 | Drag map, scroll to zoom | Map pans and zooms smoothly | App loaded | `AirportMap.tsx` | N (manual) |

---

## 7. 3D Map (Three.js)

| ID | Test Name | Priority | Action | Expected Result | Precondition | Component | Auto-testable |
|----|-----------|----------|--------|-----------------|--------------|-----------|---------------|
| M3-01 | 3D view renders airport scene | P0 | Click "3D" toggle button | 3D scene with ground plane, terminal buildings, runways, taxiways visible | App loaded | `Map3D.tsx`, `AirportScene.tsx` | Y |
| M3-02 | 3D aircraft models visible | P0 | Observe 3D scene | Aircraft models at correct positions with proper orientation/heading | 3D view active, flights exist | `Aircraft3D.tsx`, `GLTFAircraft.tsx` | Y |
| M3-03 | Click aircraft in 3D to select | P0 | Click an aircraft model in 3D | Flight selected, detail panel opens | 3D view active | `AirportScene.tsx` | N (manual) |
| M3-04 | Orbit controls (pan/zoom/rotate) | P1 | Drag to rotate, scroll to zoom, right-drag to pan | Camera orbits smoothly, zoom in/out works, pan moves view | 3D view active | `Map3D.tsx` | N (manual) |
| M3-05 | Camera frames selected flight | P1 | Select a flight (from list) while in 3D | Camera moves to frame selected aircraft (close ramp view for ground, farther for airborne) | 3D view active, flight selected | `Map3D.tsx` | Y |
| M3-06 | Terminal buildings render from OSM | P1 | Observe 3D scene at airport with OSM data | 3D terminal buildings with correct footprint and reasonable height | 3D view, OSM data loaded | `Building3D.tsx`, `Terminal3D.tsx` | Y |
| M3-07 | 3D trajectory lines | P1 | Select flight → Enable trajectory → View in 3D | 3D trajectory polyline visible in scene | 3D view, trajectory enabled | `Trajectory3D.tsx` | Y |
| M3-08 | Camera doesn't go below ground | P2 | Rotate camera aggressively downward | Camera stops at near-horizontal angle, never goes underground | 3D view | `Map3D.tsx` (maxPolarAngle) | N (manual) |

---

## 8. View Toggle (2D ↔ 3D)

| ID | Test Name | Priority | Action | Expected Result | Precondition | Component | Auto-testable |
|----|-----------|----------|--------|-----------------|--------------|-----------|---------------|
| VT-01 | Toggle from 2D to 3D | P0 | Click "3D" button in view toggle | 3D scene appears, 2D map hidden, "3D" button highlighted blue | 2D view active | `App.tsx:ViewToggle` | Y |
| VT-02 | Toggle from 3D to 2D | P0 | Click "2D" button in view toggle | 2D map reappears, 3D hidden, "2D" button highlighted blue | 3D view active | `App.tsx:ViewToggle` | Y |
| VT-03 | Viewport preserved 2D→3D | P1 | Zoom into area in 2D → Switch to 3D | 3D camera positioned to show roughly the same area/zoom level | 2D view zoomed in | `useViewportState.ts` | Y |
| VT-04 | Viewport preserved 3D→2D | P1 | Navigate in 3D → Switch to 2D | 2D map shows roughly same center and zoom as 3D camera | 3D view navigated | `useViewportState.ts` | Y |
| VT-05 | Lazy loading fallback | P2 | Switch to 3D for the very first time | Brief "Loading 3D View..." spinner shown before scene renders | First 3D switch, bundle not prefetched | `App.tsx:MapLoadingFallback` | Y |

---

## 9. Flight Detail (Right Panel)

| ID | Test Name | Priority | Action | Expected Result | Precondition | Component | Auto-testable |
|----|-----------|----------|--------|-----------------|--------------|-----------|---------------|
| FD-01 | Placeholder when no flight selected | P0 | Deselect all flights | "Select a flight to view details" placeholder with icon | No flight selected | `FlightDetail.tsx` | Y |
| FD-02 | Callsign and phase badge | P0 | Select a flight | Large callsign text, ICAO24 below, colored phase badge (Ground/Climbing/Descending/Cruising) | Flight selected | `FlightDetail.tsx` | Y |
| FD-03 | Route display (Origin → Destination) | P0 | Select flight with origin/destination | "LAX → SFO" style route display with arrow, aircraft type chip below | Flight with route data selected | `FlightDetail.tsx` | Y |
| FD-04 | Position data (lat/lon/alt) | P0 | Select a flight | Latitude, Longitude (4 decimals), Altitude (rounded, ft) displayed | Flight selected | `FlightDetail.tsx` | Y |
| FD-05 | Movement data (speed/heading/vrate) | P0 | Select a flight | Speed (kts), Heading (deg), Vertical Rate (ft/min) displayed | Flight selected | `FlightDetail.tsx` | Y |
| FD-06 | Close button | P1 | Click X button on flight detail | Selection cleared, returns to placeholder | Flight selected | `FlightDetail.tsx` | Y |
| FD-07 | Trajectory toggle | P1 | Click "Show Trajectory" toggle | Toggle turns blue, point count badge appears, trajectory drawn on map | Flight selected | `FlightDetail.tsx` | Y |
| FD-08 | Trajectory toggle off | P1 | Click toggle again to disable | Toggle returns to gray, trajectory line removed from map | Trajectory enabled | `FlightDetail.tsx` | Y |
| FD-09 | Delay prediction displayed | P1 | Select a flight | "Delay Prediction" section shows expected delay (min), category badge (On Time/Slight/Moderate/Severe), confidence bar | Flight selected | `FlightDetail.tsx` | Y |
| FD-10 | Gate recommendations (arriving flights) | P1 | Select a descending or ground-phase flight | "Gate Recommendations" section with top 3 gates, scores (%), taxi times, reasons | Arriving flight selected | `FlightDetail.tsx` | Y |
| FD-11 | Gate recommendations hidden for departures | P2 | Select a climbing or cruising flight | No "Gate Recommendations" section shown | Departing flight selected | `FlightDetail.tsx` | Y |
| FD-12 | Metadata section | P2 | Select a flight, scroll to bottom | Data Source and Last Seen timestamp displayed | Flight selected | `FlightDetail.tsx` | Y |

---

## 10. Turnaround Timeline

| ID | Test Name | Priority | Action | Expected Result | Precondition | Component | Auto-testable |
|----|-----------|----------|--------|-----------------|--------------|-----------|---------------|
| TT-01 | Timeline appears for ground flights | P1 | Select a ground-phase flight | "Turnaround Progress" section with progress bar, phase circles (1-7), est. departure time | Ground flight selected | `TurnaroundTimeline.tsx` | Y |
| TT-02 | Phase indicators show correct state | P1 | Observe phase circles | Completed phases = green checkmark, current = blue pulse, pending = gray number | Ground flight selected | `TurnaroundTimeline.tsx` | Y |
| TT-03 | Click phase for detail | P2 | Click a phase circle | Detail tooltip shows phase name and status (Completed/In progress X%/Pending), close button | Ground flight selected | `TurnaroundTimeline.tsx` | Y |
| TT-04 | Active GSE equipment shown | P2 | Observe below progress bar | "Active Equipment" section lists currently servicing GSE (fuel truck, catering, etc.) | Ground flight with active GSE | `TurnaroundTimeline.tsx` | Y |
| TT-05 | Timeline hidden for airborne flights | P2 | Select a climbing/cruising flight | No "Turnaround Progress" section visible | Non-ground flight selected | `FlightDetail.tsx` | Y |

---

## 11. Baggage Status

| ID | Test Name | Priority | Action | Expected Result | Precondition | Component | Auto-testable |
|----|-----------|----------|--------|-----------------|--------------|-----------|---------------|
| BG-01 | Baggage status appears for flights with callsign | P1 | Select flight with callsign | "Baggage Status" section with progress bar, total/delivered/connecting stats | Flight with callsign selected | `BaggageStatus.tsx` | Y |
| BG-02 | Progress bar shows loading percentage | P1 | Observe baggage section | Progress bar width matches loading_progress_pct, green for normal, yellow if misconnects | Flight selected | `BaggageStatus.tsx` | Y |
| BG-03 | Carousel number displayed for arrivals | P2 | Select arriving flight | "Carousel {N}" badge shown in header | Arriving flight with carousel data | `BaggageStatus.tsx` | Y |
| BG-04 | Misconnect alert | P1 | Select flight with tight connections | Yellow alert: "{N} bag(s) at risk — Tight connection time" | Flight with misconnects | `BaggageStatus.tsx` | Y |
| BG-05 | Baggage hidden when no callsign | P2 | Select flight without callsign | No baggage section rendered | Flight with empty callsign | `FlightDetail.tsx` | Y |

---

## 12. Gate Status (Right Panel)

| ID | Test Name | Priority | Action | Expected Result | Precondition | Component | Auto-testable |
|----|-----------|----------|--------|-----------------|--------------|-----------|---------------|
| GS-01 | Gate status panel renders | P0 | Observe right panel below flight detail | "Gate Status" header with available/occupied counts | App loaded | `GateStatus.tsx` | Y |
| GS-02 | Terminal filter pills | P0 | Observe pill buttons | "All" pill (blue) + one pill per terminal | App loaded | `GateStatus.tsx` | Y |
| GS-03 | All view — terminal summary | P0 | Ensure "All" pill selected | Each terminal listed as a row with name, congestion badge, free/used/total counts | "All" selected | `GateStatus.tsx` | Y |
| GS-04 | Click terminal row to drill in | P0 | Click a terminal row (or its pill) | Grid of gate squares shown, color-coded by status (red=On Stand, amber=Taxi In/Inbound, green=Vacant) | "All" view | `GateStatus.tsx` | Y |
| GS-05 | Gate square tooltip | P2 | Hover over a gate square | Tooltip: "{ref}: {STATUS} — {callsign}" (if occupied) | Terminal view | `GateStatus.tsx` | N (manual) |
| GS-06 | Click gate for detail card | P1 | Click a gate square | Detail card appears below grid: gate ref, status badge, flight info (callsign, type, route, phase) or "No flight assigned" | Terminal view | `GateStatus.tsx` | Y |
| GS-07 | Detail card — click flight to select | P1 | Click flight callsign link in gate detail card | Flight selected in context, detail panel updates, map highlights flight | Gate detail card with flight | `GateStatus.tsx` | Y |
| GS-08 | Detail card close button | P2 | Click × on gate detail card | Card dismissed | Gate detail visible | `GateStatus.tsx` | Y |
| GS-09 | Congestion indicator per terminal | P1 | Observe terminal rows or header | Colored badge: Low (green), Moderate (yellow), High (orange), Critical (red) with wait time | Congestion data loaded | `GateStatus.tsx` | Y |
| GS-10 | Gate color legend | P2 | Observe bottom of gate status panel | Legend: On Stand (red), Taxi In/Inbound (amber), Vacant (green) | Any view | `GateStatus.tsx` | Y |
| GS-11 | Congestion legend | P2 | Observe bottom of gate status panel | Legend: Low, Moderate, High, Critical with colored badges | Any view | `GateStatus.tsx` | Y |

---

## 13. Weather Widget

| ID | Test Name | Priority | Action | Expected Result | Precondition | Component | Auto-testable |
|----|-----------|----------|--------|-----------------|--------------|-----------|---------------|
| WX-01 | Compact weather shown in header | P1 | Observe header right area | Flight category dot (VFR=green/MVFR=blue/IFR=red/LIFR=purple), temperature °C, wind, visibility | App loaded | `WeatherWidget.tsx` | Y |
| WX-02 | Click to expand weather details | P1 | Click weather pill in header | Dropdown with station name, flight category badge, wind/visibility/temperature/clouds grid, raw METAR text | Weather loaded | `WeatherWidget.tsx` | Y |
| WX-03 | Weather loading state | P2 | Observe during initial fetch | "Loading weather..." pulsing text | Initial load | `WeatherWidget.tsx` | Y |
| WX-04 | Weather error state | P2 | Simulate API failure | Red "Weather unavailable" badge | API error | `WeatherWidget.tsx` | Y |

---

## 14. FIDS (Flight Information Display System)

| ID | Test Name | Priority | Action | Expected Result | Precondition | Component | Auto-testable |
|----|-----------|----------|--------|-----------------|--------------|-----------|---------------|
| FI-01 | FIDS opens as modal | P0 | Click "FIDS" button in header | Full-screen dark modal with table, arrivals/departures tabs, close button | App loaded | `FIDS.tsx` | Y |
| FI-02 | Arrivals tab displays data | P0 | Open FIDS → Click "Arrivals" tab (default) | Table columns: Time, Flight, From, Gate, Status, Remarks. Rows populated. | FIDS open | `FIDS.tsx` | Y |
| FI-03 | Departures tab | P0 | Click "Departures" tab | Table columns change: "From" becomes "To", rows show departure data | FIDS open | `FIDS.tsx` | Y |
| FI-04 | Live flight badge | P1 | Observe FIDS rows | Tracked flights show blue "Live" badge next to flight number | FIDS open, tracked flights exist | `FIDS.tsx` | Y |
| FI-05 | Click live flight selects and closes | P1 | Click a "Live" flight row | FIDS closes, flight selected in main view, detail panel shows info | FIDS open, live flight visible | `FIDS.tsx` | Y |
| FI-06 | Delay info in remarks | P1 | Find a delayed flight | Yellow "+N min" in Remarks column, estimated time shown below scheduled time | Delayed flight exists | `FIDS.tsx` | Y |
| FI-07 | Status color coding | P2 | Observe Status column | On Time=green, Delayed=yellow, Boarding=blue, Cancelled=red, etc. | FIDS open | `FIDS.tsx` | Y |
| FI-08 | Close FIDS | P0 | Click X button in FIDS header | Modal closes, main app visible | FIDS open | `FIDS.tsx` | Y |
| FI-09 | Footer shows count and refresh info | P2 | Observe FIDS footer | "{N} arrivals | Auto-refresh: 1 min | Synthetic data for demo" | FIDS open | `FIDS.tsx` | Y |

---

## 15. Platform Links

| ID | Test Name | Priority | Action | Expected Result | Precondition | Component | Auto-testable |
|----|-----------|----------|--------|-----------------|--------------|-----------|---------------|
| PL-01 | Platform button opens dropdown | P1 | Click "Platform" button in header | Dropdown with 5 links: Flight Dashboard, Ask Genie, Data Lineage, ML Experiments, Unity Catalog | App loaded | `PlatformLinks.tsx` | Y |
| PL-02 | Links open in new tab | P1 | Click any link in dropdown | New browser tab opens with correct Databricks workspace URL | Dropdown open | `PlatformLinks.tsx` | N (manual) |
| PL-03 | Dropdown closes on outside click | P2 | Open dropdown → Click outside | Dropdown closes | Dropdown open | `PlatformLinks.tsx` | Y |
| PL-04 | Dropdown closes after link click | P2 | Click a link | Dropdown closes (link opens in new tab) | Dropdown open | `PlatformLinks.tsx` | Y |

---

## 16. Data Ops Dashboard

| ID | Test Name | Priority | Action | Expected Result | Precondition | Component | Auto-testable |
|----|-----------|----------|--------|-----------------|--------------|-----------|---------------|
| DO-01 | Dashboard opens as modal | P1 | Navigate to Data Ops (if accessible from UI) | Full-screen modal with health summary, sync status, data sources, recent activity | App loaded | `DataOpsDashboard.tsx` | Y |
| DO-02 | Health summary cards | P1 | Observe top row | 4 cards: Acquisition (count + records), Sync (count + synced), Freshness (In Sync/Out of Sync + lag), Last Sync (time + record diff) | Dashboard open | `DataOpsDashboard.tsx` | Y |
| DO-03 | Health badge colors | P1 | Observe health indicators | Green = healthy, Yellow = degraded, Red = unhealthy | Dashboard open | `DataOpsDashboard.tsx` | Y |
| DO-04 | Sync status detail (Delta vs Lakebase) | P2 | Observe "Sync Status" section | Two columns: Unity Catalog (Delta) and Lakebase (PostgreSQL) with record counts and staleness | Dashboard open | `DataOpsDashboard.tsx` | Y |
| DO-05 | Data sources table | P2 | Observe "Data Sources" section | Table: Source, Calls, Records, Errors, Error Rate (red if > 10%) | Dashboard open | `DataOpsDashboard.tsx` | Y |
| DO-06 | Check Freshness button | P2 | Click "Check Freshness" button | Button shows "Checking...", triggers freshness check, data refreshes | Dashboard open | `DataOpsDashboard.tsx` | Y |
| DO-07 | Recent acquisitions list | P2 | Observe "Recent Acquisitions" | List of recent data acquisitions with timestamp, source, record count, latency, success/fail dot | Dashboard open | `DataOpsDashboard.tsx` | Y |
| DO-08 | Recent syncs list | P2 | Observe "Recent Syncs" | List of sync operations with timestamp, direction, records synced/failed, latency | Dashboard open | `DataOpsDashboard.tsx` | Y |
| DO-09 | Auto-refresh indicator | P3 | Observe footer | "Auto-refreshes every 30 seconds" with last updated timestamp | Dashboard open | `DataOpsDashboard.tsx` | Y |
| DO-10 | Error state with retry | P2 | Simulate API failure | "Error loading dashboard" with "Retry" button | API error | `DataOpsDashboard.tsx` | Y |

---

## 17. Cross-Component Integration

| ID | Test Name | Priority | Action | Expected Result | Precondition | Component | Auto-testable |
|----|-----------|----------|--------|-----------------|--------------|-----------|---------------|
| CI-01 | Select flight from list → map highlights | P0 | Click flight in list | 2D: marker highlighted/zoomed. 3D: camera frames aircraft. Detail panel populates. | App loaded | Multiple | Y |
| CI-02 | Select flight from map → list highlights | P0 | Click marker on 2D map | Flight row scrolled into view and highlighted in left panel, detail panel populates | App loaded, 2D view | Multiple | N (manual) |
| CI-03 | Select flight from gate detail → all sync | P1 | Click callsign in gate detail card | Flight selected across all panels: list highlights, map centers, detail shows info | Gate detail open | Multiple | Y |
| CI-04 | Select flight from FIDS → all sync | P1 | Click live flight in FIDS | FIDS closes, flight selected in list + map + detail panel | FIDS open | Multiple | Y |
| CI-05 | Airport switch resets selection | P1 | Select a flight → Switch airport | Selection cleared, detail panel shows placeholder, new flights populate | Flight selected | Multiple | Y |
| CI-06 | Airport switch recenters both views | P0 | In 2D: switch airport → check 2D position. Switch to 3D → check 3D position | Both views centered on new airport | Any view | Multiple | Y |
| CI-07 | Data auto-refreshes in real-time | P1 | Wait 10+ seconds without interaction | Flight positions update, timestamps refresh, no user action needed | App loaded | `FlightContext`, `useFlights` | Y |

---

## Summary by Priority

| Priority | Count | Description |
|----------|-------|-------------|
| **P0** | 24 | Core functionality — app must not ship without these passing |
| **P1** | 33 | Important features — should pass for production quality |
| **P2** | 24 | Secondary features — nice to have, can defer if needed |
| **P3** | 2 | Low priority — cosmetic or minor utility |
| **Total** | **83** | |

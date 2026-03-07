# Airport Digital Twin - UI Test Plan

## Overview

Comprehensive test cases for the Airport Digital Twin application covering all 2D and 3D visualization features.

**App URL:** https://airport-digital-twin-dev-7474645572615955.aws.databricksapps.com

---

## 1. Application Bootstrap

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| 1.1 | App loads successfully | Navigate to app URL | App renders without errors, no console errors |
| 1.2 | Header displays | Check top of page | Header with "Airport Digital Twin" title visible |
| 1.3 | Three-panel layout | Check layout | Left (Flight List), Center (Map), Right (Details) panels visible |
| 1.4 | Default view is 2D | Check map area | 2D map with OpenStreetMap tiles displays by default |
| 1.5 | View toggle visible | Check top-right of map | 2D/3D toggle buttons visible, 2D highlighted |

---

## 2. View Toggle (2D/3D Switch)

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| 2.1 | Switch to 3D view | Click "3D" button | 3D scene renders, button highlights |
| 2.2 | Switch back to 2D | Click "2D" button | 2D map renders, button highlights |
| 2.3 | Selection persists across views | Select flight in 2D, switch to 3D | Same flight remains selected |
| 2.4 | Trajectory persists across views | Enable trajectory in 2D, switch to 3D | Trajectory visible in 3D view |

---

## 3. Flight List Panel

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| 3.1 | Flight count displays | Check header | "Flights (N)" shows correct count |
| 3.2 | Flights render | Check list | All flights display with callsign, altitude, phase |
| 3.3 | Search by callsign | Type "UAL" in search | Only flights matching "UAL" shown |
| 3.4 | Search by ICAO24 | Type "a12" in search | Flights with matching ICAO24 shown |
| 3.5 | Clear search | Clear search field | All flights shown again |
| 3.6 | Sort by callsign | Select "Callsign (A-Z)" | Flights sorted alphabetically |
| 3.7 | Sort by altitude | Select "Altitude (High-Low)" | Flights sorted by altitude descending |
| 3.8 | Select flight | Click on flight row | Row highlights, details panel updates |
| 3.9 | Deselect flight | Click selected flight again | Selection cleared, details show placeholder |
| 3.10 | Loading state | Refresh page, observe | Spinner shows while loading |
| 3.11 | Empty search results | Search for "ZZZZZ" | "No flights match your search" message |

---

## 4. Flight Detail Panel

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| 4.1 | Empty state | No flight selected | "Select a flight to view details" placeholder |
| 4.2 | Flight header | Select a flight | Callsign and ICAO24 display |
| 4.3 | Phase badge - Ground | Select ground flight | Gray "Ground" badge |
| 4.4 | Phase badge - Climbing | Select climbing flight | Green "Climbing" badge |
| 4.5 | Phase badge - Descending | Select descending flight | Orange "Descending" badge |
| 4.6 | Phase badge - Cruising | Select cruising flight | Blue "Cruising" badge |
| 4.7 | Position section | Select flight with position | Lat, Lon, Altitude display |
| 4.8 | Movement section | Select flight | Speed, Heading, Vertical Rate display |
| 4.9 | Close button | Click X button | Flight deselected, returns to placeholder |
| 4.10 | Data source | Check metadata | Data source (live/cached/synthetic) shows |
| 4.11 | Last seen timestamp | Check metadata | Valid timestamp displays |

---

## 5. Trajectory Feature

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| 5.1 | Trajectory toggle visible | Select flight | "Show Trajectory" toggle button visible |
| 5.2 | Enable trajectory | Click toggle ON | Toggle turns blue, loading spinner shows |
| 5.3 | Point count badge | Wait for load | Badge shows "N pts" count |
| 5.4 | Disable trajectory | Click toggle OFF | Toggle turns gray, trajectory hidden |
| 5.5 | Trajectory resets on deselect | Deselect flight | Trajectory auto-disabled |
| 5.6 | Trajectory in 2D | Enable in 2D view | Polyline renders on map |
| 5.7 | Trajectory in 3D | Enable in 3D view | 3D line/tube renders in scene |

---

## 6. Delay Prediction (ML Feature)

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| 6.1 | Prediction section visible | Select flight | "Delay Prediction" section shows |
| 6.2 | Loading state | Select flight | "Loading predictions..." briefly shows |
| 6.3 | Delay minutes | Wait for load | Delay in minutes displays |
| 6.4 | On-time badge | Delay = 0-5 min | Green "On Time" badge |
| 6.5 | Slight delay badge | Delay = 5-15 min | Yellow "Slight Delay" badge |
| 6.6 | Moderate delay badge | Delay = 15-30 min | Orange "Moderate Delay" badge |
| 6.7 | Severe delay badge | Delay > 30 min | Red "Severe Delay" badge |
| 6.8 | Confidence bar | Check confidence | Progress bar + percentage display |

---

## 7. Gate Recommendations (ML Feature)

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| 7.1 | Section shows for arriving | Select descending/ground flight | "Gate Recommendations" section visible |
| 7.2 | Section hidden for departing | Select climbing/cruising flight | Section not visible |
| 7.3 | Top recommendation highlighted | Check first gate | Blue background highlight |
| 7.4 | Gate ID displays | Check recommendations | Gate IDs (A1, B5, etc.) show |
| 7.5 | Score displays | Check recommendations | Score percentage shows |
| 7.6 | Taxi time displays | Check recommendations | Taxi time in minutes shows |
| 7.7 | Reasons list | Check recommendations | Bullet points with reasons |

---

## 8. Gate Status Panel

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| 8.1 | Panel renders | Check right panel | "Gate Status" section visible |
| 8.2 | Summary counts | Check header | "N Available" and "N Occupied" counts |
| 8.3 | Terminal A grid | Check section | 10 gate boxes (1-10) in grid |
| 8.4 | Terminal B grid | Check section | 10 gate boxes (1-10) in grid |
| 8.5 | Available gate color | Check available gates | Green background |
| 8.6 | Occupied gate color | Check occupied gates | Red background |
| 8.7 | Gate tooltip | Hover over gate | Tooltip shows "A1: Available/Occupied" |
| 8.8 | Congestion indicator | Check terminal headers | Congestion badge (Low/Moderate/High/Critical) |
| 8.9 | Wait time in congestion | Check congestion badge | Wait time in minutes if > 0 |
| 8.10 | Congestion legend | Check bottom | Color legend for congestion levels |

---

## 9. 2D Map View

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| 9.1 | Map tiles load | Check map | OpenStreetMap tiles render |
| 9.2 | Airport centered | Check initial view | Map centered on airport coordinates |
| 9.3 | Zoom controls | Use scroll/pinch | Map zooms in/out smoothly |
| 9.4 | Pan controls | Click and drag | Map pans smoothly |
| 9.5 | Flight markers render | Check map | Aircraft icons at flight positions |
| 9.6 | Marker rotation | Check markers | Markers rotated to match heading |
| 9.7 | Marker click selects | Click on marker | Flight selected, details panel updates |
| 9.8 | Selected marker highlight | Select flight | Marker visually highlighted |
| 9.9 | Marker tooltip | Hover marker | Tooltip with callsign/altitude |
| 9.10 | Airport overlay | Check map | Runways/terminals overlay visible |
| 9.11 | Status overlay | Check bottom-left | Flight count, last updated, error status |
| 9.12 | Updating indicator | During refresh | "Updating..." text with animation |
| 9.13 | Trajectory polyline | Enable trajectory | Colored line showing flight path |
| 9.14 | Trajectory follows flight | Check line | Line connects to current position |

---

## 10. 3D Map View

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| 10.1 | Canvas renders | Switch to 3D | WebGL canvas renders without errors |
| 10.2 | Ground plane | Check scene | Green grass ground visible |
| 10.3 | Terminal building | Check scene | Gray terminal building visible |
| 10.4 | Runways | Check scene | Dark gray runways visible |
| 10.5 | Runway markings | Check runways | White center line and threshold markings |
| 10.6 | Taxiways | Check scene | Yellow/tan taxiways connecting to terminal |
| 10.7 | Additional buildings | Check scene | Tower/hangars if configured |
| 10.8 | Aircraft models | Check scene | 3D aircraft at flight positions |
| 10.9 | Aircraft orientation | Check aircraft | Aircraft rotated to match heading |
| 10.10 | Aircraft altitude | Check aircraft | Aircraft height matches altitude |
| 10.11 | Orbit camera - rotate | Click and drag | Camera rotates around scene |
| 10.12 | Orbit camera - zoom | Scroll wheel | Camera zooms in/out |
| 10.13 | Orbit camera - pan | Right-click drag | Camera pans |
| 10.14 | Camera limits | Try to go below ground | Camera stops above ground level |
| 10.15 | Aircraft selection | Click on aircraft | Flight selected, details update |
| 10.16 | Selected aircraft glow | Select aircraft | Aircraft has visual highlight/glow |
| 10.17 | Shadows | Check scene | Aircraft cast shadows on ground |
| 10.18 | Trajectory 3D | Enable trajectory | 3D line/tube showing flight path |
| 10.19 | Airline livery | Check aircraft colors | Colors match airline (if configured) |
| 10.20 | Aircraft scale | Check aircraft vs terminal | Aircraft appropriately sized (smaller than terminal building) |
| 10.21 | Gate spacing | Check aircraft at gates | Aircraft don't overlap, space for ground equipment |

---

## 11. Data Refresh & Persistence

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| 11.1 | Auto-refresh works | Wait 30 seconds | Flight positions update |
| 11.2 | Selection persists | Select flight, wait for refresh | Same flight still selected |
| 11.3 | Trajectory persists | Enable trajectory, wait for refresh | Trajectory still visible |
| 11.4 | New flights appear | Wait for new data | New flights added to list/map |
| 11.5 | Removed flights disappear | Wait for stale data | Old flights removed |
| 11.6 | Last updated timestamp | Check status | Timestamp updates after refresh |

---

## 12. Error Handling

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| 12.1 | API error display | Simulate API failure | Error message in status overlay |
| 12.2 | Graceful degradation | Network offline | App shows cached data or error |
| 12.3 | 3D fallback | GLTF model fails to load | Procedural aircraft renders instead |
| 12.4 | Missing prediction | No ML prediction available | "No prediction available" message |
| 12.5 | Empty recommendations | No gates available | "No recommendations available" message |

---

## 13. Performance

| ID | Test Case | Steps | Expected Result |
|----|-----------|-------|-----------------|
| 13.1 | Initial load time | Measure page load | < 3 seconds to interactive |
| 13.2 | 2D render performance | 50+ flights | Smooth panning/zooming (60 FPS) |
| 13.3 | 3D render performance | 50+ flights | Smooth camera movement (30+ FPS) |
| 13.4 | List scroll performance | Scroll flight list | Smooth scrolling |
| 13.5 | View switch speed | Toggle 2D/3D | < 500ms transition |
| 13.6 | Search responsiveness | Type in search | Instant filtering |

---

## Test Data Requirements

For complete testing, ensure these flights exist:
- At least 1 flight in each phase (ground, climbing, descending, cruising)
- Flights with callsigns: UAL123, DAL456, SWA789, AAL100, JBU555 (have trajectory data)
- Mix of occupied/available gates

---

## Browser Compatibility

Test on:
- [ ] Chrome (latest)
- [ ] Firefox (latest)
- [ ] Safari (latest)
- [ ] Edge (latest)

---

## Automated Test Execution

```bash
# Run with Playwright (if configured)
npx playwright test

# Run with Chrome DevTools MCP
# Use mcp__chrome-devtools__* tools for automated UI testing
```

# UX Fixes: Silhouettes, Turnaround Speed, Loading Indicator, Airline Realism, Terminal Mapping, Baggage Display

## Context

UX audit on 2026-03-20 identified multiple issues across the Airport Digital Twin. The user requests fixes for aircraft silhouette sizing/positioning, P0 bugs (speed during turnaround, loading indicator), and P1 improvements (airline realism, fixed flights, terminal mapping, baggage display).

Full audit: `.planning/ux-audit-2026-03-20.md`

---

## 1. Aircraft Silhouette Sizing (Analysis — No Change Needed)

Current (`FlightMarker.tsx:81-96`): Zoom 18→48px, 17→36px, 16→20px, 14→10px. Multipliers: narrow=1.0, wideTwin=1.1, wideQuad=1.2.

Real scale at zoom 18 (~0.46 m/px): B737=76px, B777=140px — too large for a crowded ramp. Current 48px cap is a deliberate readability compromise. **No changes.**

## 2. Aircraft Gate Positioning / Wall Clipping (Already Handled)

`_compute_gate_standoff()` (`fallback.py:2085-2126`) uses OSM terminal polygons + aircraft half-lengths to offset parked aircraft from terminal walls. `_get_parked_heading()` orients nose perpendicular to nearest terminal edge.

If clipping still occurs, it's due to imprecise OSM gate node positions for specific airports — a data quality issue, not a code bug. **No changes.**

---

## 3. P0-1: Fix Speed During Gate Turnaround

**Bug:** Parked aircraft shows speed=25kts during turnaround phases.

**Root cause:** In `fallback.py:2912-2914`, `state.velocity = 0` IS set for PARKED phase. However, the `get_current_flight_states()` serialization at line 311 reads `state.velocity` directly, which could be transiently non-zero if snapshot is captured between state machine updates, or the WebSocket delta compression omits unchanged velocity when phase transitions from TAXI_TO_GATE (25kts) to PARKED.

**Fix** (`src/ingestion/fallback.py:311`):
Force velocity=0 for PARKED flights in the serialization:
```python
"velocity": 0 if state.phase == FlightPhase.PARKED else state.velocity,
```

---

## 4. P0-2: Loading Indicator During Airport Switch

**Bug:** No visible feedback during 13-21s airport switch.

**Root cause:** `AirportSwitchProgress` renders in `Header.tsx:27-31` with absolute `top-full` positioning — it appears BELOW the header element and gets hidden behind the map container. The `isLoadingAirport` state IS set correctly.

**Fix:**
- `Header.tsx`: Move progress overlay to fixed `inset-0` with semi-transparent backdrop and high z-index
- `AirportSwitchProgress.tsx`: Restyle as a centered card overlay

```tsx
// Header.tsx — replace current progress block
{(isLoadingAirport || switchProgress) && (
  <div className="fixed inset-0 bg-black/50 z-[2000] flex items-center justify-center">
    <AirportSwitchProgress ... />
  </div>
)}
```

---

## 5. P1-3: Unrealistic Airline Mixes at Uncalibrated Airports

**Root cause** (`fallback.py:3405-3433`): Without a calibrated profile, airlines are picked from `CALLSIGN_PREFIXES` (US-centric: UAL, DAL, AAL, SWA, JBU, ASA, UAE, AFR, CPA + regionals). The scope validation only blocks `regional_eu` and `regional_me`, but domestic-scoped carriers (SWA, JBU, ASA, HAL) are NOT blocked at international airports like RJTT/EGLL.

**Fix** (`src/ingestion/fallback.py`, random generation block ~line 3419-3433):
Add domestic scope validation: if current airport is NOT in `DOMESTIC_AIRPORTS` (i.e., it's international), reject domestic-only carriers and re-pick from the pool. Also filter out US regional carriers (SKW, RPA, ENY, PDT, EDV) at non-US airports.

---

## 6. P1-4: Remove Fixed Test Flights

**Root cause** (`fallback.py:3385-3397`): 5 hardcoded flights (UAL123, DAL456, SWA789, AAL100, JBU555) created at every airport regardless of realism. Also `_FIXED_FLIGHT_IDS` at lines 3545-3549.

**Fix** (`src/ingestion/fallback.py`):
- Delete the `test_flights` list and its iteration loop (lines 3385-3397)
- Delete `_FIXED_FLIGHT_IDS` constant (lines 3545-3549)
- Remove any references to `_FIXED_FLIGHT_IDS` elsewhere in the file

---

## 7. P1-5: Terminal Mapping for Well-Known Airports

**Root cause** (`src/formats/osm/converter.py:260`): Terminal names from OSM `tags.name` are used as-is. Some airports have inconsistent/wrong OSM naming.

**Fix** (`src/formats/osm/converter.py`):
Add `TERMINAL_NAME_OVERRIDES` dict keyed by ICAO code, mapping OSM name patterns to corrected names. Apply during terminal conversion.

Known overrides:
- EGLL: Map generic terminal labels to "Terminal 2", "Terminal 3", "Terminal 4", "Terminal 5"
- RJTT: Normalize to "Terminal 1", "Terminal 2", "Terminal 3 (International)"

---

## 8. P1-6: Baggage Display "0 Delivered" at 100%

**Root cause** (`BaggageStatus.tsx:111-112`):
```tsx
{isArrival ? stats.on_carousel || stats.unloaded : stats.loaded}
```
When all bags reach `claimed` status, both `on_carousel` and `unloaded` are 0. The progress bar shows 100% but the count shows 0.

**Fix:**
1. `src/ingestion/baggage_generator.py`: Add `"delivered"` field = `unloaded + on_carousel + claimed` in the stats dict
2. `app/frontend/src/components/Baggage/BaggageStatus.tsx`: Use the new `delivered` field, or fall back to `total_bags` when `loading_progress_pct === 100`

---

## Files to Modify

| File | Fix |
|------|-----|
| `src/ingestion/fallback.py` | P0-1: velocity=0 for PARKED in serialization. P1-3: domestic scope filter. P1-4: remove fixed flights |
| `app/frontend/src/components/Header/Header.tsx` | P0-2: fixed overlay positioning |
| `app/frontend/src/components/AirportSelector/AirportSwitchProgress.tsx` | P0-2: centered card layout |
| `app/frontend/src/components/Baggage/BaggageStatus.tsx` | P1-6: fix delivered count |
| `src/ingestion/baggage_generator.py` | P1-6: add delivered field |
| `src/formats/osm/converter.py` | P1-5: terminal name overrides |

---

## Verification

1. `uv run pytest tests/ -v` — no regressions
2. `cd app/frontend && npm test -- --run` — no regressions
3. Deploy and test visually:
   - Parked aircraft shows 0kts speed
   - Airport switch shows full-screen loading overlay
   - RJTT/EGLL have no SWA/JBU flights
   - No UAL123/SWA789/etc. at any airport
   - EGLL shows T2/T3/T4/T5
   - 100% delivered shows actual bag count

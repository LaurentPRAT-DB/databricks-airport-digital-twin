# Phase 45: UX Review v3 Fixes

## Overview
Address 16 UX issues found during comprehensive review on 2026-03-19.
Organized into 5 sub-phases by priority and blast radius.

## Sub-phase A: Data Realism (P0)
**Files:** `src/api/fids.py`, `src/formats/osm/converter.py`, `app/frontend/src/components/GateStatus/`

1. FIDS gate names from OSM gate list (not random generation)
2. Airline-route plausibility filter (domestic-only airlines restricted)
3. Airport-specific terminal naming from OSM data

## Sub-phase B: Physics Fixes (P1)
**Files:** `src/simulation/`, `src/api/flights.py`, `app/frontend/src/components/FlightDetails/`

4. Compute vertical rate from altitude deltas
5. Gate scoring with actual taxi distance
6. Fix baggage progress bar (percentage calculation)
7. Spread FIDS arrival times over realistic window

## Sub-phase C: State Management (P2)
**Files:** `app/frontend/src/hooks/useAirportConfig.ts`, `app/frontend/src/components/FlightDetails/`

8. Clear selected flight on airport switch
9. Clarify turnaround origin/destination labels
10. Sync trajectory data between 2D/3D views

## Sub-phase D: 3D Quality (P3)
**Files:** `app/frontend/src/components/Map3D/Map3D.tsx`

11. Color-code aircraft by flight phase
12. Improve model lighting
13. Altitude-based label separation
14. Ensure prediction data passes to 3D view

## Sub-phase E: Performance
15. Fix Lakebase/UC cache (separate known issue)
16. Ensure airport cache persistence

## Success Criteria
- No impossible gate numbers in FIDS
- Vertical rate negative for descending flights
- Baggage bar shows correct percentage
- JFK shows "Terminal 1,2,4,5,7,8" not "A-G"
- Flight details auto-close on airport switch
- 3D aircraft colored by phase, not all dark

# UX Review Session 2 — Airport Digital Twin (2026-03-21, Evening)

Deployed build via DABs, reviewed via API on https://airport-digital-twin-dev-7474645572615955.aws.databricksapps.com

## Executive Summary

Backend performance is excellent (0.3–0.5s airport switches), airline mixes are airport-appropriate, and gate stacking P0 bug appears resolved. However, the **simulation state machine is completely frozen** — no flights progress through their lifecycle — making this the top-priority issue. FIDS schedule entries are empty for some airports, and origins remain random.

**Severity levels:** P0 = blocks demo, P1 = noticeable/confusing, P2 = polish

---

## Airport Switch Timing (API-measured)

| Airport | Lakebase Cache | Total Ready Time | Notes |
|---------|---------------|------------------|-------|
| KSFO (initial) | 0.367s | 1.6s (+ data gen) | Cold start |
| KSFO (re-activate) | 0.318s | 0.321s | Warm |
| RJTT | 0.512s | 0.514s | First switch |
| EGLL | 0.452s | 0.454s | Second switch |
| KSFO (return) | 0.313s | 0.315s | Round-trip |

**Verdict:** Airport switching is fast and reliable. Lakebase Tier 1 cache hits consistently. The 35-second switch time reported in Session 1 was likely due to frontend re-rendering and flight data generation, not backend config loading. From the API perspective, switches complete in <1s.

---

## P0 — Critical Bugs

### 1. Simulation State Machine Frozen — Zero Flight Lifecycle Progression
- **What:** Flight phases never change. Over 60 seconds of monitoring, phase distribution was identical:
  - Snapshot 1: `taxi_out:5, enroute:73, parked:13, approaching:8, taxi_in:1`
  - Snapshot 2 (60s later): `taxi_out:5, enroute:73, parked:13, approaching:8, taxi_in:1`
  - Same callsigns at same gates. Zero departures. Zero new arrivals.
- **Impact:** The airport looks static — like a screenshot, not a simulation. This is the single biggest realism issue. In a real airport, over 60 seconds you'd see taxi_out→climbing transitions, approaching→taxi_in transitions, turnaround completions.
- **Prior session data:** In the earlier review, 180 seconds also showed zero progression (9 parked, 6 taxi, 0 climbing/departed across the entire observation window).
- **Root cause hypothesis:** The `DEMO_GATE_TIME_MULTIPLIER` (8x) may only affect turnaround display, not the actual state machine transitions. Or the tick/update loop that advances flight phases is not running.

### 2. FIDS Shows Zero Entries for EGLL and KSFO (Return)
- **What:** `GET /api/schedule/arrivals` returns `entries: 0` for EGLL and KSFO (after round-trip switch).
- **RJTT worked:** RJTT FIDS showed 100 entries with airport="HND" (correct sync).
- **KSFO first activation:** Worked (100 entries, airport="SFO").
- **Impact:** FIDS modal would show empty table — confusing for users.
- **Root cause hypothesis:** Schedule cache invalidation may not trigger re-generation reliably on all switches.

---

## P1 — Noticeable Issues

### 3. Taxi Aircraft Heading Defaults to 0° (North)
- **What:** Multiple taxi_out aircraft have `heading: 0.0` despite being in motion (`velocity: 25.0 kts`).
  - `AAL8896` taxi_out vel=25.0 hdg=0.0°
  - `USA3520` taxi_out vel=25.0 hdg=0.0°
  - `UAL3736` taxi_in heading changed from 295.5° to 0.0° between snapshots
- **Impact:** Aircraft appear to always point north while taxiing — unrealistic.
- **Root cause:** Heading not computed from position deltas during taxi phase; defaults to 0.

### 4. Some Taxi Aircraft Stuck at velocity=0
- **What:** `JBU4953` taxi_out at vel=0.0, `AAL1642` taxi_out at vel=0.0.
- **Impact:** Aircraft frozen mid-taxiway — looks broken.

### 5. FIDS Origins Still Random (Pre-existing)
- **What:** RJTT FIDS origins include SUB (Surabaya), BVA (Beauvais), HTA (Chita), TIQ (Tinian) — not real HND routes.
- **Status:** Known issue from Session 1, fix plan exists at `.planning/ux-review/PLAN-fids-route-realism.md`.

### 6. FIDS Callsigns Missing ("?") at RJTT
- **What:** All 8 sample FIDS arrivals had callsign="?" — empty/null callsigns in schedule entries.
- **Impact:** FIDS shows entries without flight numbers, rendering empty cells.

---

## P2 — Polish

### 7. Response Format Inconsistency
- **What:** `/api/flights` returns different shapes:
  - Sometimes: `[{flight}, {flight}, ...]` (array)
  - Sometimes: `{"flights": [{flight}, ...]}` (wrapped object)
  - During activation: `["activating", "please", "wait", ...]` (string array)
- **Impact:** Frontend likely handles this, but API should be consistent.

### 8. Airport Config Returns Empty During Activation
- **What:** During RJTT/EGLL activation, `/api/airport/config` returns `icao_code: null, gates: 0`.
- **Impact:** Brief flash of empty state in UI during switch.

---

## Positive Observations

1. **Airport switching is fast** — Backend consistently <0.5s via Lakebase cache.
2. **Gate stacking fixed** — KSFO: 13 parked, all unique gates. RJTT: 10 parked, all unique. EGLL: 12 parked, all unique. The gate 56 stacking bug from Session 1 is no longer observed.
3. **Airline mixes are realistic per airport:**
   - KSFO: UAL 33%, VRD 15%, AAL 7%, USA 6%, JBU 5% — realistic SFO carriers
   - RJTT: JAL 35%, ANA 28%, ADO 6%, SKY 6% — realistic HND carriers
   - EGLL: BAW 40%, VIR 6%, FIN 4%, AAL 4%, AFR 3% — realistic LHR carriers
4. **Gate assignments distributed well** — No duplicates observed across 3 airports.
5. **FIDS airport field synced** — Shows correct IATA code after switch (HND, LHR, SFO).
6. **Schedule service switching works** — DIAG logs confirm `schedule_service switched to HND/RJTT`, `LHR/EGLL`, `SFO/KSFO`.

---

## Consolidated Issue Priority (Both Sessions)

| # | Issue | Severity | Status | Notes |
|---|-------|----------|--------|-------|
| **1** | Simulation state machine frozen | **P0** | **NEW** | Top priority — no flight lifecycle |
| **2** | FIDS empty after some switches | **P0** | **NEW** | Schedule cache issue |
| 3 | FIDS random origins | P1 | Open | Plan exists |
| 4 | Taxi heading=0° default | P1 | Open | Multiple aircraft affected |
| 5 | Taxi stuck at vel=0 | P1 | Open | 2 of 5 taxi aircraft |
| 6 | FIDS missing callsigns | P1 | **NEW** | RJTT entries have no callsigns |
| 7 | Identical delay predictions | P1 | Open | From Session 1 |
| 8 | API response format inconsistency | P2 | **NEW** | flights array vs object |
| 9 | Gate 56 stacking | P0 | **FIXED** | No longer observed |
| 10 | FIDS wrong airport | P0 | **FIXED** | Confirmed fixed |

---

## Test Methodology

- **Platform:** Deployed Databricks App via DABs
- **Airports tested:** KSFO, RJTT, EGLL, KSFO (round-trip)
- **Method:** API-based testing via curl with auth tokens
- **Monitoring:** 60-second observation window for state machine progression
- **DIAG logs:** Ring buffer debug logs checked for timing and errors
- **Date:** 2026-03-21, ~19:30–19:55 UTC

---

## Recommended Next Actions

### Immediate (P0)
1. **Debug simulation tick loop** — Determine why flights don't progress. Check if the WebSocket/timer-based update loop is running in the deployed app. The state machine that transitions `parked→taxi_out→climbing→enroute` and `approaching→taxi_in→parked` must be triggered by periodic updates.
2. **Fix FIDS schedule generation** — Ensure schedule entries are regenerated on every airport switch, not just the first one.

### Short-term (P1)
3. **Compute taxi heading from position** — Use position deltas to calculate bearing during taxi phases instead of defaulting to 0°.
4. **Implement route realism** — Use calibration profiles (OpenFlights data) to assign realistic origins/destinations per airline.
5. **Populate FIDS callsigns** — Ensure schedule entries include callsign field from flight data.

### Medium-term (P2)
6. **Standardize API response format** — `/api/flights` should always return same shape.
7. **Add loading skeleton during switch** — Show partial UI during activation instead of empty config.

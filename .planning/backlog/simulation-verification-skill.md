# Plan: Simulation Verification Skill

**Status:** planned
**Priority:** P1
**Area:** simulation, testing, validation

## Context

The simulation produces rich data (position snapshots, phase transitions, gate events) but validation is scattered across:
- `tests/test_simulation_validation.py` — validates pre-downloaded simulation JSON files from UC Volume (offline)
- `tests/test_go_around_landing_validation.py` — live centerline validation (runs sims)
- `tests/test_live_trajectory_quality.py` — validates live API trajectory data
- `scripts/validate_all_airports.py` — realism scorecard (go-around rate, OTP, turnaround)
- `scripts/realism_scorecard.py` — schedule distribution vs ground truth

**Need:** a unified verification module (`src/simulation/verify.py`) that encodes aviation invariants as reusable checker functions, plus a CLI runner (`scripts/verify_simulation.py`) and a pytest integration that runs all checks against live simulation output. This becomes the single source of truth for "is the simulation realistic?"

## Aviation Invariants to Implement

### Tier 1: Safety Critical (hard failures)

1. **Runway single occupancy** — max 1 aircraft on runway at any time
2. **Gate single occupancy** — max 1 aircraft at same gate at any time
3. **Phase ordering** — no illegal state transitions
4. **No terrain penetration** — altitude >= 0 during all ground phases

### Tier 2: Physics (soft failures, threshold-based)

5. **Taxi speed** — ground phases < 30kt
6. **Approach speed envelope** — 120-250kt during approach
7. **Approach altitude monotonic** — no altitude gains > 200ft in last 5nm (except go-around)
8. **Departure climb positive** — no altitude loss in first 60s after takeoff
9. **No teleportation** — position jumps < 0.05° between consecutive ticks (ground phases)
10. **Landing heading aligned** — within ±10° of runway heading at touchdown

### Tier 3: Operational Realism (warnings, not failures)

11. **Go-around rate** — 0-5% (flag if outside)
12. **Turnaround time bounds** — 15-180min
13. **Capacity ceiling** — ops/hr ≤ 2× physical AAR
14. **On-time performance** — 60-100%
15. **Taxi time bounds** — taxi-in 3-15min, taxi-out 5-25min

## Deliverables

- `src/simulation/verify.py` — checker functions, each returns pass/fail + detail
- `scripts/verify_simulation.py` — CLI runner (point at sim output JSON or live API)
- pytest integration — runs all checks against live simulation output

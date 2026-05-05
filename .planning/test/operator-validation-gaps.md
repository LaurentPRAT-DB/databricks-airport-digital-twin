---
title: "Operator-Facing Validation Gaps: Gates, Trajectories, KPIs"
status: backlog
area: simulation, frontend
priority: high
related:
  - ../backlog/v1-readiness-checklist.md
  - ../validation-gaps/
---

# Operator-Facing Validation Gaps

From an airport operator's standpoint, the missing tests across three key areas.

## 1. Gate Allocation — Gaps

**What's covered:** gate occupancy counts, double-occupancy prevention, occupy/release events, overflow stands, basic turnaround ranges.

**What's missing:**

| Gap | Why it matters (operator POV) |
|-----|-------------------------------|
| Gate conflict resolution under surge | When diversions flood the airport, do gates get reassigned correctly? |
| Gate turnaround buffer enforcement | Aircraft can't use a gate for N minutes after departure (cleaning/prep). Is the buffer respected under load? |
| Terminal/concourse balancing | Do international vs. domestic flights get routed to correct terminal areas? |
| Gate reassignment after go-around | If a flight goes around, does its gate stay reserved or get released to another? |
| Gate utilization report accuracy | The GateStatus UI shows counts — do they match actual engine state after 6+ hours of sim? |
| Frontend: KPIDashboard (19% coverage) | The ML predictions dashboard has zero functional tests — operator would rely on it for congestion/delay forecasts |

## 2. Airplane Route (Trajectory) — Gaps

**What's covered:** taxi speed limits, no teleportation, heading smoothness, approach descent, departure climb, pushback direction, waypoint advancement.

**What's missing:**

| Gap | Why it matters (operator POV) |
|-----|-------------------------------|
| Taxi route conflicts (two aircraft same taxiway segment) | Operators care about ground conflicts causing delays |
| Runway crossing authorization | Aircraft taxiing across an active runway — is it prevented? |
| STAR/SID corridor compliance | Do approach/departure paths stay within published corridors? |
| Missed approach procedure fidelity | After go-around, does the aircraft follow the published missed approach? |
| Taxi route efficiency (path length vs. optimal) | Are routes unreasonably long? (e.g., >2x shortest path) |
| Frontend: TrajectoryLine (0 dedicated tests) | The 2D polyline rendering — does it display correct path for approach/taxi/departure? |

## 3. KPIs — Gaps

**What's covered:** on-time %, go-around rate, schedule delay, cancellation rate recorded, capacity hold time recorded, peak gate utilization.

**What's missing:**

| Gap | Why it matters (operator POV) |
|-----|-------------------------------|
| KPI accuracy over full 24h sim | Existing tests run short sims (~50 flights). Do KPIs remain accurate at 500+ flights/24h? |
| KPI correlation with scenario severity | Worse weather should monotonically degrade KPIs. Is this tested? |
| Runway throughput (actual arrivals/departures per hour) vs declared rate | Core operator metric — is AAR/ADR achievable? |
| Taxi-out time vs scheduled push time | OOOI compliance — do departures leave gate within target window? |
| Delay attribution (weather vs capacity vs ground) | Which factor causes what % of delay? Not validated |
| Frontend: SimulationReport KPI cards vs engine | The report UI renders on_time_pct, avg_delay, etc. — do the displayed values match the engine's computed summary? (end-to-end) |
| Frontend: usePredictionDashboard (0% coverage) | Congestion forecasts, delay predictions — entire hook untested |

## Priority Recommendation

For highest operator value, the three biggest gaps are:

1. **KPI accuracy at scale** — a backend integration test running a full 500-flight/24h sim and validating all summary fields against expected ranges
2. **Gate conflict under scenario stress** — diversions + runway closure scenario should not produce gate double-bookings
3. **Frontend KPIDashboard + usePredictionDashboard** — the operator's live ops view has 19% coverage; adding tests would catch rendering bugs for congestion/delay forecasts

# Airport Digital Twin V2 — Roadmap & Status

## Executive Summary

This document tracks the V2 feature roadmap from initial gap analysis through implementation. All originally planned V2 phases (6–12) are **complete**. The roadmap now extends with V3 phases focused on multi-airport portfolio management, cross-airport benchmarking, optimization recommendations, and remaining gaps.

*Last updated: 2026-05-11*

---

## 1. V2 Phases — Complete

All V1 limitations have been resolved. All 7 V2 phases are implemented with backend logic, API routes, frontend UI, and test coverage.

| Phase | Feature | Status | What Was Built |
|-------|---------|--------|----------------|
| **6** | FIDS Display | **Done** | Full arrivals/departures board, schedule vs actual, delay indicators, gate info, status colors, sticky landed-flight retention |
| **7** | Ground Support Equipment | **Done** | GSE allocation model (per aircraft type), turnaround timeline UI, pushback/refueling/catering/boarding phases, API routes + service layer |
| **8** | Weather Integration | **Done** | METAR generation + real METAR parser, weather widget UI (VFR/MVFR/IFR/LIFR), wind/visibility/clouds, weather impact on operations, diurnal patterns |
| **9** | Baggage Handling System | **Done** | Baggage generator (lognormal timing, MCT-based misconnects), DLT pipeline (bronze/silver/gold), per-flight bag tracking UI, carousel assignment, Lakebase writer |
| **10** | Enhanced ML Models | **Done** | CatBoost turnaround model, OBT model (HistGBR + CatBoost), BTS data ingest, transfer learning from A-CDM data, per-airport model registry, realism scorecard |
| **11** | Real Airport Layout | **Done** | OSM/Overpass API integration, 1,183 calibration profiles, multi-airport selector with region grouping, OurAirports + OpenFlights ingest, dynamic geometry |
| **12** | Passenger Flow Simulation | **Done** | Cohort-based passenger flow (departure + arrival pipelines), security checkpoint throughput model, check-in queues, dwell time, connection handling |

### Additional V2-era features (built beyond original plan)

| Feature | Description |
|---------|-------------|
| MCP Server | 13 tools exposed via JSON-RPC 2.0 for AI Playground / Supervisor Agents |
| LLM Assistant | Unified Genie + MCP routing with sonnet-4-5, report chat + what-if simulation |
| A-CDM Adapter | Maps real A-CDM milestones to model features for transfer learning |
| OBT Model | 2-stage prediction pipeline (turnaround duration → absolute pushback time) |
| Video Renderer | Headless Chromium + ffmpeg for simulation MP4 export |
| Format Parsers | AIDM, AIXM, IFC, MSFS BGL, OSM — multi-format airport data ingestion |
| YOLO Inpainting | Aircraft detection + removal from satellite imagery |
| Simulation Replay | Record/replay with time controls, WebSocket streaming |
| KPI Dashboard | ML predictions dashboard + data ops monitoring |

---

## 2. V1 Limitations — Resolution Status

| Original Limitation | Resolution |
|--------------------|-----------|
| "Flight Data Only" | Baggage, GSE, passenger flow all implemented |
| "Generic Airport" | 1,183 real airports via OSM + calibration profiles |
| "Rule-Based ML" | CatBoost/HistGBR models trained on BTS + simulation data |
| "No Historical Analysis" | OpenSky recording persistence, trajectory history, replay |
| "No Scheduling" | Full schedule generator + FIDS display |
| "No Weather" | METAR generation + weather widget + operational impact |
| "No Ground Equipment" | GSE model with turnaround phases and timeline UI |

---

## 3. Remaining Gaps

Features that exist but need validation, polish, or deeper implementation:

| Area | Gap | Current State | Priority |
|------|-----|---------------|----------|
| Passenger flow | No spatial visualization | Backend model only (queuing theory), no frontend particle sim | Medium |
| Baggage | No conveyor/cart 3D | Backend tracking + DLT pipeline work, no 3D ramp visualization | Low |
| GSE | No 3D vehicle models | Turnaround timeline UI exists, no animated GSE in 3D scene | Medium |
| Weather | No real-time API | Synthetic METAR generation + historical parser, no live CheckWX/AWC feed | Medium |
| ML | Models not deployed to serving endpoints | Trained locally / in notebooks, not all registered in MLflow Model Registry | High |
| Simulation | Clock speed issues | Playback timing inconsistent at high speeds | Medium |
| Simulation | Demo ≠ simulation path | Two separate code paths for demo mode vs simulation | Medium |
| OpenSky | Collector fragile | Rate limits, no continuous collection, gaps in recorded data | Medium |
| Report chat | What-if not validated | Code exists but not tested end-to-end on deployed app | Medium |

---

## 4. V3 Roadmap — Airport Network & Intelligence

### Phase 13: Airport Group Management
**Goal**: Manage portfolios of airports as a single operational unit

**Features**:
- Airport group CRUD (create, name, add/remove airports)
- Group presets by region (US hubs, European majors, Middle East mega-hubs)
- Parallel simulation across group — run same scenario on N airports simultaneously
- Group-level health dashboard — one screen showing all airports' status
- Batch operations: import all, calibrate all, run simulation on all

**Data Model**:
```
airport_groups (Lakebase)
├── group_id, name, description, created_at
├── airports: [icao_code, ...]
└── config: {default_scenario, sim_hours, auto_refresh}
```

**Technical Approach**:
- Backend: `AirportGroupService` with CRUD endpoints, parallel sim orchestration
- Frontend: Group manager panel, multi-select airport picker
- Lakebase: `airport_groups` table for persistence
- Databricks Jobs: parameterized job for batch simulation across group

**Effort**: 3-4 days

---

### Phase 14: Global Network View
**Goal**: World map showing all airports in a group with real-time status indicators

**Features**:
- Zoomable world map (Leaflet) with airport markers colored by health/load
- Flight connections drawn between airports (great circle arcs)
- Traffic flow visualization — animated particles along routes
- Aggregate KPI overlay (total flights, avg delay, on-time %)
- Click-to-drill: click any airport → opens single-airport view
- Hub-spoke visualization for airline networks
- Timezone-aware "current hour" heatmap (which airports are in peak vs off-peak)

**Technical Approach**:
- New `/api/groups/{group_id}/overview` endpoint — lightweight KPIs for all airports
- WebSocket channel for group-level updates (status changes, alerts)
- Frontend: new `GlobalView` component with Leaflet + D3 for flow arcs
- Aggregate from per-airport simulation snapshots or Lakebase queries

**Effort**: 4-5 days

---

### Phase 15: Airport Benchmarking & Comparison
**Goal**: Compare airports against each other on standardized KPIs

**Features**:
- Side-by-side comparison (2-4 airports)
- Standardized KPI scorecard:
  - On-time performance (OTP)
  - Average delay (arrival + departure)
  - Turnaround efficiency (actual vs minimum)
  - Gate utilization %
  - Runway throughput (movements/hour vs capacity)
  - Baggage delivery time (P50, P95)
  - Security checkpoint wait time
  - Passenger connection success rate
- Radar chart visualization (spider plot)
- Ranking/leaderboard within a group
- Historical trend comparison (same KPI across airports over time)
- Peer group benchmarks (compare SFO to "US large hubs" average)
- Export comparison as PDF/Slides

**Data Sources**:
- Per-airport simulation KPIs (already computed)
- BTS On-Time Performance (historical ground truth for US)
- Calibration profiles (capacity baselines)

**Technical Approach**:
- Backend: `BenchmarkService` — compute normalized scores, percentile ranks
- Frontend: `AirportComparison` component with radar chart (recharts/d3)
- Lakebase: `airport_kpi_snapshots` table (periodic snapshots per airport)
- Scoring: normalize each KPI to 0-100 scale relative to peer group

**Effort**: 4-5 days

---

### Phase 16: Optimization Recommendations Engine
**Goal**: AI-powered suggestions for operational improvements per airport

**Features**:
- Automated gap detection — identify which KPIs are below peer average
- Root cause analysis — trace poor OTP to specific bottlenecks (taxi, turnaround, weather)
- Actionable recommendations with estimated impact:
  - "Adding 1 runway reduces avg departure delay by 4.2 min" (via what-if sim)
  - "Shifting 15% of departures from 0800-0900 to 0600-0700 reduces congestion 22%"
  - "Adding 2 security lanes increases pax throughput by 360 pph"
- What-if simulation integration — each recommendation backed by sim results
- Priority ranking (impact × feasibility)
- LLM-generated narrative explaining findings (leverage existing report chat)
- Track recommendation adoption and measured improvement over time

**Technical Approach**:
- Backend: `OptimizationEngine` — rule-based heuristics + what-if sim runner
- LLM layer: use existing assistant to generate natural language recommendations
- Pattern library: known operational improvements mapped to simulation parameters
- Frontend: recommendations panel in single-airport view, link to what-if

**Effort**: 5-7 days

---

### Phase 17: Multi-Airport Simulation (Network Effects)
**Goal**: Simulate flights flowing between airports — delays propagate through the network

**Features**:
- Connected airport simulation — a delayed departure at ORD becomes a delayed arrival at SFO
- Delay propagation modeling — aircraft rotation chains (same aircraft flies multiple legs)
- Hub bottleneck detection — when one hub degrades, downstream spoke airports suffer
- Cascade analysis — "if EDDF has fog for 2 hours, which airports are affected and by how much?"
- Network resilience scoring — how well does a group absorb disruptions
- Diversion routing — flights divert to alternates within the network

**Data Model**:
- Route graph: airports as nodes, flight frequency as weighted edges
- Aircraft rotation chains: [flight1 → turnaround → flight2 → ...]
- Propagation rules: arrival_delay(N+1) = f(departure_delay(N), buffer_time, wind)

**Technical Approach**:
- Extend simulation engine with multi-airport coordinator
- New `NetworkSimulation` class orchestrating per-airport engines
- Shared flight objects that move between airport instances
- Databricks Jobs: distributed simulation across workers (one airport per task)

**Effort**: 7-10 days

---

### Phase 18: Real-Time Data Integration
**Goal**: Live operational data replacing synthetic generation

**Features**:
- Live METAR/TAF from Aviation Weather Center or CheckWX API
- Real-time ADS-B from OpenSky (continuous collector, not snapshot)
- Live schedule feed (AviationStack or FlightAware for demo airports)
- Hybrid mode: real positions + synthetic ground ops (where no ground truth)
- Data quality indicators — show which data is live vs synthetic
- Alerting: notify when live data diverges significantly from prediction

**Data Sources**:
- CheckWX API (free tier: 2000 req/day) for METAR/TAF
- OpenSky continuous websocket or polling (authenticated: no rate limit)
- AviationStack (free tier: 100 req/month — limited to 1-2 airports)
- BTS monthly data drops (historical validation, not real-time)

**Technical Approach**:
- Background worker: continuous OpenSky poller → Lakebase
- Weather service: cache + TTL, fall back to synthetic on API failure
- Frontend badge: "LIVE" vs "SIM" indicator per data layer

**Effort**: 4-5 days

---

## 5. Implementation Priority Matrix (V3)

| Phase | Feature | Demo Impact | Effort | Priority Score |
|-------|---------|-------------|--------|----------------|
| 13 | Airport Group Management | High | Low | **9/10** |
| 14 | Global Network View | Very High | Medium | **9/10** |
| 15 | Airport Benchmarking | Very High | Medium | **8/10** |
| 16 | Optimization Recommendations | High | High | **7/10** |
| 18 | Real-Time Data Integration | High | Medium | **7/10** |
| 17 | Multi-Airport Network Sim | Medium | Very High | **6/10** |

---

## 6. Recommended Execution Order

### Immediate (Week 1):
1. **Phase 13: Airport Group Management** — Foundation for everything else. CRUD + parallel sim.
2. **Phase 14: Global Network View** — Highest visual impact for demos. "Here are 20 airports, all running."

### Short-term (Week 2-3):
3. **Phase 15: Benchmarking** — Once groups exist, compare them. Radar charts + leaderboard.
4. **Phase 18: Real-Time Data** — Replace synthetic weather with live METAR (quick win for realism).

### Medium-term (Week 4-6):
5. **Phase 16: Optimization Engine** — The "so what?" layer. Recommendations backed by what-if sims.
6. **Phase 17: Network Simulation** — Most complex. Delay propagation across connected airports.

---

## 7. Data Architecture for V3

```
┌─────────────────────────────────────────────────────────────┐
│                     Unity Catalog                             │
│                                                              │
│  airport_groups          → group definitions                 │
│  airport_kpi_snapshots   → periodic KPI captures per airport │
│  benchmark_results       → comparison outputs                │
│  network_simulations     → multi-airport sim results         │
│  recommendations_log     → generated recommendations + status│
│                                                              │
│  Existing tables:                                            │
│  flight_status_gold, flight_positions_history,               │
│  baggage_events_*, calibration_profiles (Volume)             │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                     Lakebase (PostgreSQL)                     │
│                                                              │
│  airport_groups          → fast CRUD for group management    │
│  kpi_latest              → most recent KPIs per airport      │
│  flight_status           → existing real-time serving        │
│  network_state           → cross-airport flight positions    │
└─────────────────────────────────────────────────────────────┘
```

---

## 8. Still Missing (Beyond V3)

Features not yet planned but would complete a full AOMS:

| Category | Feature | Notes |
|----------|---------|-------|
| **ATC** | Full ATC simulation (sequencing, spacing, vectoring) | Very complex, would need dedicated ATC logic engine |
| **Ground** | 3D GSE vehicle animations in scene | Models on Sketchfab (CC-BY), needs animation system |
| **Ground** | De-icing operations | Winter-only, weather-triggered, low priority |
| **Pax** | Spatial passenger visualization (particle sim in terminal) | Backend model exists, needs WebGL terminal floorplan |
| **Baggage** | 3D conveyor belt visualization | Cool but low operational value |
| **Financials** | Revenue impact modeling (delay cost, missed connections) | Would tie KPIs to $ impact |
| **Staffing** | Crew/ground staff scheduling optimization | Separate optimization problem |
| **Noise** | Noise contour mapping and community impact | Regulatory use case |
| **Sustainability** | Carbon emissions per flight/airport, fuel efficiency KPIs | ESG reporting angle |
| **Security** | Threat detection, perimeter monitoring | Separate security system |
| **Cargo** | Freight handling, warehouse operations | Cargo airports (MEM, LEJ) focus |
| **Airlines** | Airline-specific ops view (fleet utilization, crew planning) | Different persona than airport ops |
| **Regulatory** | Slot compliance, noise quota tracking, curfew management | European airports mainly |
| **Construction** | Airport expansion planning with traffic impact sim | Long-term capital planning |
| **Emergency** | Emergency response simulation (evacuation, runway closure) | Safety/compliance use case |

---

*Document created: 2026-03-08*
*V2 roadmap complete: 2026-05-11*
*V3 phases added: 2026-05-11*

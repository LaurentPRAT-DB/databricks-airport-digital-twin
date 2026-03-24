# Strategic Gap 5: Passenger Flow Module

**Validation tests blocked:** F01 (Checkpoint Throughput), F02 (Terminal Dwell Time), F03 (Congestion Hotspots), F04 (Retail Diversion), D02 (Mass Re-accommodation), D03 (Evacuation), R03 (Check-in Desk)

**Impact:** 7 of 20 validation tests require passenger simulation. This is the single largest missing capability.

---

## Architecture

### Module location
`src/simulation/passenger_flow.py` — new module, imported by `src/simulation/engine.py`

### Core model: Agent-based with fluid fallback

Each flight generates a passenger cohort at check-in (departures) or at gate arrival (arrivals). Passengers move through a terminal graph as discrete agents at low volume (<500 pax), switching to fluid-dynamics (flow rate through nodes) at high volume.

### Terminal graph

Nodes derived from IFC building model or OSM terminal outlines:
- **Entry nodes**: curbside drop-off, parking garage, metro/BART
- **Check-in desks**: per-airline desk clusters with queue model
- **Security checkpoints**: N lanes, M/G/1 queue per lane, processing time ~30s/pax
- **Terminal zones**: airside corridors connecting security to gates
- **Retail/F&B nodes**: shops and restaurants with dwell time distribution
- **Gates**: boarding areas with capacity
- **Transfer corridors**: paths between terminals (with MCT implications)

Edge weights = walking time (distance / walking speed, ~1.3 m/s, elderly 0.8 m/s).

### Passenger types
| Type | Share | Behavior |
|------|-------|----------|
| Business | 25% | Arrives late, skips retail, PreCheck lane |
| Leisure | 55% | Arrives early, 40% retail diversion |
| Transfer | 15% | Enters airside, walks to next gate |
| Crew | 5% | KCM lane, direct to gate |

### Queue model (F01, R03)
Each checkpoint/desk is an M/G/1 queue:
- Arrival rate: λ = passengers/min from upstream node
- Service rate: μ = 1/processing_time (configurable per lane type)
- Wait time: W = ρ / (μ(1-ρ)) where ρ = λ/μ
- When ρ → 1.0, queue grows unbounded → congestion hotspot

### Dwell time model (F02)
Total dwell = walk_time + security_wait + retail_dwell + gate_wait
- Walk segments from terminal graph shortest path
- Security wait from queue model output
- Retail dwell: lognormal(μ=15min, σ=0.5) for diverting passengers
- Gate wait: arrives early → sits; arrives late → runs

### Congestion heatmap (F03)
Terminal zones track density (pax/m²). When density > 0.5 pax/m², zone is congested. Propagate back-pressure: congested zone slows inflow from upstream.

---

## Implementation phases

### Phase 1: Terminal graph + security queue (2 weeks)
- Parse IFC/OSM terminal layout into graph
- Implement M/G/1 checkpoint model
- Generate pax from flight schedule → route through graph
- Output: throughput/hour, wait time P50/P95
- **Validates:** F01

### Phase 2: Dwell time + retail diversion (1 week)
- Add retail/F&B nodes with diversion probability
- Track per-passenger journey time from entry to gate
- Split by pax type
- **Validates:** F02, F04

### Phase 3: Congestion zones + heatmap (1 week)
- Zone density tracking from agent positions
- Back-pressure propagation
- Heatmap export for 2D visualization
- **Validates:** F03

### Phase 4: Check-in desk model (3 days)
- Per-airline desk allocation with staffing schedule
- Queue sensor comparison interface
- **Validates:** R03

### Phase 5: Mass re-accommodation (1 week)
- Cancellation event → pax re-routing to customer service
- Rebooking queue model (service time ~8 min/pax)
- Lounge overflow detection
- **Validates:** D02

---

## Data requirements
- Terminal floor plan (IFC preferred, OSM outline fallback)
- Airline desk allocation schedule
- Security checkpoint lane count + hours
- POS transaction data for retail calibration (optional)
- CCTV people-counter data for validation (F01)

## Estimated effort
Total: ~5-6 weeks for full passenger flow module
Phase 1 alone enables F01 validation.

# Strategic Gap 6: BHS Physics Module

**Validation tests blocked:** B02 (BHS Throughput Under Load), B03 (Transfer Baggage Connection)

**Current state:** Baggage model is statistical (lognormal timing, now improved with B01 fix). No conveyor physics, sort routing, or junction capacity.

---

## Architecture

### Module location
`src/simulation/bhs.py` — new module

### Core model: Discrete-event conveyor network

BHS modeled as a directed graph of conveyor segments:
- **Injection points**: check-in counters → BHS entry
- **Conveyor segments**: belt with capacity (bags/min), length, speed
- **Junctions**: merge/divert decisions (tilt-tray, pusher)
- **Sort machines**: destination-based routing (gate/carousel)
- **Holding areas**: early bag storage
- **Carousel/loader**: final delivery to aircraft or passenger

### Conveyor segment model
```
class ConveyorSegment:
    length_m: float          # Physical length
    speed_mps: float         # Belt speed (typically 2-5 m/s)
    capacity: int            # Max bags on segment simultaneously
    bags: deque[Bag]         # Bags currently on segment
    jam_threshold: float     # Capacity ratio that triggers jam (0.9)
```

### Junction routing
Each junction has a routing table:
- Key: destination (gate, carousel, or terminal)
- Value: next segment ID
Sort decision time: ~50ms per bag (tilt-tray) or ~200ms (pusher divert)

### Jam model
When segment load > jam_threshold:
1. Upstream segments back up (stop accepting)
2. Jam event logged with timestamp and location
3. Recovery: clear jam in 2-5 min (manual intervention)
4. Jam cascades upstream until injection points queue

### Transfer bag routing (B03)
Transfer bags have:
- Arrival flight + terminal
- Departure flight + terminal
- MCT = walking_time(terminal_pair) + sort_time + load_time
- If arrival_time + MCT > departure_time → misconnect prediction

---

## Implementation phases

### Phase 1: Conveyor network model (2 weeks)
- Define segment graph per airport (derive from terminal layout)
- Implement discrete-event bag movement through segments
- Capacity limits and back-pressure
- Output: throughput/hour per segment
- **Validates:** B02

### Phase 2: Sort routing + transfer (1 week)
- Routing table per junction
- Transfer bag path: arrival carousel → sort → departure loader
- MCT computation from path length + segment speeds
- Misconnect prediction from MCT vs connection time
- **Validates:** B03

### Phase 3: Jam simulation + SCADA interface (1 week)
- Jam trigger/cascade/recovery model
- SCADA log format export for validation comparison
- Peak bank stress testing

---

## Airport-specific configuration
BHS topology varies per airport. Approach:
1. **Template topologies**: hub (6+ terminals), spoke (2-3), regional (1)
2. **Scale from gate count**: more gates → more injection/delivery points
3. **Manual override**: YAML config per airport if known layout

## Data requirements
- BHS RFID scan events (for B01 calibration)
- SCADA throughput logs (for B02 validation)
- Terminal-pair MCT tables (for B03)

## Estimated effort
Total: ~4 weeks
Phase 1 alone enables B02 validation.

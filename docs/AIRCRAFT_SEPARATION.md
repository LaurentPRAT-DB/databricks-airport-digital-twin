# Aircraft Separation Standards

This document describes the FAA/ICAO separation standards implemented in the synthetic flight data generator.

## Overview

Real-world air traffic control maintains strict separation between aircraft to prevent collisions. The Airport Digital Twin synthetic data generator now implements these standards for realistic simulation.

## Implemented Standards

### 1. Wake Turbulence Separation (Final Approach)

Aircraft are categorized by weight and generate different levels of wake turbulence:

| Category | Examples | Weight |
|----------|----------|--------|
| **SUPER** | A380 | > 560,000 lbs |
| **HEAVY** | B747, B777, B787, A330, A340, A350 | > 300,000 lbs |
| **LARGE** | A320, A321, B737, B738 | 41,000 - 300,000 lbs |
| **SMALL** | CRJ9, E175, E190 | < 41,000 lbs |

### Minimum Separation (Nautical Miles)

Following aircraft category determines minimum distance from lead aircraft:

| Lead → Follow | Separation |
|---------------|------------|
| SUPER → SUPER | 4 NM |
| SUPER → HEAVY | 6 NM |
| SUPER → LARGE | 7 NM |
| SUPER → SMALL | 8 NM |
| HEAVY → HEAVY | 4 NM |
| HEAVY → LARGE | 5 NM |
| HEAVY → SMALL | 6 NM |
| LARGE → LARGE | 3 NM |
| LARGE → SMALL | 4 NM |
| SMALL → SMALL | 3 NM |

**Default minimum: 3 NM** if category unknown.

### 2. Runway Occupancy

- **Single occupancy**: Only one aircraft on the runway at any time
- **Landing clearance**: Requires runway to be clear before aircraft transitions to landing
- **Takeoff clearance**: Requires runway to be clear before aircraft begins takeoff roll
- **Release**: Runway is released when:
  - Landing aircraft exits to taxiway
  - Departing aircraft is airborne and > 500 ft AGL

### 3. Approach Sequencing

Aircraft on approach are sequenced with proper spacing:

```
┌─────────────────────────────────────────────────────────────────────┐
│  Approach Sequence (from east to west)                              │
│                                                                     │
│  [AC4]──5NM──[AC3]──5NM──[AC2]──5NM──[AC1]──►RUNWAY                │
│  8000ft      7000ft      6000ft      5000ft                         │
│                                                                     │
│  Maximum 4 aircraft on approach at once                             │
└─────────────────────────────────────────────────────────────────────┘
```

- **Maximum simultaneous approaches**: 4 aircraft
- **Stagger altitude**: Each aircraft in queue starts higher
- **Speed adjustment**: Aircraft slow down when closing on aircraft ahead
- **Hold pattern**: If runway occupied, leading aircraft orbits

### 4. Taxi Separation

Ground operations maintain visual separation:

- **Minimum taxi separation**: ~100m (330 ft)
- **Gate area**: ~200m minimum clearance
- **Hold short**: Aircraft hold if blocked by traffic ahead

### 5. Gate Management

- **5 gates available**: A1, A2, A3, B1, B2
- **Single occupancy**: One aircraft per gate
- **Cooldown period**: 60 seconds after departure before gate reuse
- **Queue handling**: Aircraft without available gate hold on taxiway

## Implementation Details

### Key Functions

| Function | Purpose |
|----------|---------|
| `_check_approach_separation()` | Verify >= 3 NM from aircraft ahead |
| `_find_aircraft_ahead_on_approach()` | Find closest aircraft on approach path |
| `_get_required_separation()` | Calculate wake turbulence separation |
| `_is_runway_clear()` | Check runway single occupancy |
| `_occupy_runway()` / `_release_runway()` | Manage runway state |
| `_check_taxi_separation()` | Verify ground traffic clearance |
| `_find_available_gate()` | Find unoccupied gate |
| `_occupy_gate()` / `_release_gate()` | Manage gate assignments |

### State Management

```python
# Runway state
@dataclass
class RunwayState:
    occupied_by: Optional[str]     # icao24 of aircraft on runway
    last_departure_time: float     # Timestamp of last departure
    last_arrival_time: float       # Timestamp of last arrival
    approach_queue: List[str]      # Ordered approach sequence
    departure_queue: List[str]     # Ordered departure sequence

# Gate state
@dataclass
class GateState:
    occupied_by: Optional[str]     # icao24 of aircraft at gate
    available_at: float            # When gate becomes available
```

## Realistic Behaviors

With separation implemented, the simulation now shows:

1. **Approach spacing**: Aircraft visibly spaced on final approach
2. **Speed adjustments**: Faster aircraft slow to maintain separation
3. **Holding patterns**: Aircraft orbit if approach is full
4. **Sequential landings**: Only one touchdown at a time
5. **Orderly taxi**: Ground traffic yields appropriately
6. **Gate scheduling**: No aircraft overlap at gates

## Configuration

The following constants can be adjusted in `src/ingestion/fallback.py`:

```python
# Separation minimums (in degrees, ~60 deg = 1 NM)
MIN_APPROACH_SEPARATION_DEG = 0.05   # 3 NM
MIN_TAXI_SEPARATION_DEG = 0.001      # ~100m
MIN_GATE_SEPARATION_DEG = 0.002      # ~200m

# Capacity limits
MAX_APPROACH_AIRCRAFT = 4
MAX_PARKED_AIRCRAFT = 5  # Number of gates
MAX_TAXI_AIRCRAFT = 2
```

## References

- [FAA JO 7110.65 - Air Traffic Control](https://www.faa.gov/air_traffic/publications/atpubs/atc_html/)
- [FAA Wake Turbulence Categories](https://www.faa.gov/air_traffic/publications/atpubs/atc_html/chap2_section_1.html)
- [ICAO Doc 4444 - Air Traffic Management](https://www.icao.int/publications/Documents/4444_cons_en.pdf)

# Airport Synthetic Data Generation Guide

This document provides a comprehensive reference for generating realistic synthetic airport data for digital twin applications, simulations, training systems, and demos. All constraints are based on real-world aviation regulations and industry standards.

---

## Table of Contents

1. [Overview](#overview)
2. [Flight Movement Data](#flight-movement-data)
3. [Flight Schedule (FIDS)](#flight-schedule-fids)
4. [Weather Data (METAR/TAF)](#weather-data-metartaf)
5. [Baggage Handling](#baggage-handling)
6. [Ground Support Equipment (GSE)](#ground-support-equipment-gse)
7. [Regulatory References](#regulatory-references)
8. [Implementation Examples](#implementation-examples)

---

## Overview

### Data Domains

| Domain | Purpose | Refresh Rate | Key Constraints |
|--------|---------|--------------|-----------------|
| Flight Movements | Real-time aircraft positions | 1-5 seconds | Separation standards |
| Flight Schedule | FIDS arrivals/departures | 1 minute | Peak hour distribution |
| Weather | METAR/TAF observations | 10 minutes | Flight category rules |
| Baggage | BHS tracking | 30 seconds | Processing times |
| GSE | Ground equipment allocation | 10 seconds | Turnaround phases |

### Key Principles

1. **Regulatory Compliance**: All separation, timing, and operational constraints follow FAA/ICAO/IATA standards
2. **Statistical Realism**: Distributions based on industry benchmarks (load factors, delay rates, etc.)
3. **Temporal Consistency**: Data respects time-based dependencies and state machines
4. **Deterministic Reproducibility**: Seeded random generation for consistent test scenarios

---

## Flight Movement Data

### Aircraft Separation Standards

Based on **FAA Order 7110.65** (Air Traffic Control) and **ICAO Doc 4444** (PANS-ATM).

#### Wake Turbulence Categories

```
WAKE_CATEGORY = {
    "A380": "SUPER",
    "B747": "HEAVY", "B777": "HEAVY", "B787": "HEAVY", "A330": "HEAVY",
    "A340": "HEAVY", "A350": "HEAVY", "A345": "HEAVY",
    "A320": "LARGE", "A321": "LARGE", "A319": "LARGE", "A318": "LARGE",
    "B737": "LARGE", "B738": "LARGE", "B739": "LARGE",
    "CRJ9": "SMALL", "E175": "SMALL", "E190": "SMALL",
}
```

#### Minimum Radar Separation (Nautical Miles)

| Lead → Following | SUPER | HEAVY | LARGE | SMALL |
|-----------------|-------|-------|-------|-------|
| **SUPER**       | 4.0   | 6.0   | 7.0   | 8.0   |
| **HEAVY**       | -     | 4.0   | 5.0   | 6.0   |
| **LARGE**       | -     | -     | 3.0   | 4.0   |
| **SMALL**       | -     | -     | -     | 3.0   |

**Reference**: FAA Order 7110.65, Chapter 5-5-4

#### Time-Based Separation (Seconds)

For aircraft departing same runway:

| Lead → Following | SUPER | HEAVY | LARGE | SMALL |
|-----------------|-------|-------|-------|-------|
| **SUPER**       | 120   | 180   | 180   | 180   |
| **HEAVY**       | 120   | 120   | 120   | 120   |
| **LARGE**       | 60    | 60    | 60    | 60    |
| **SMALL**       | 60    | 60    | 60    | 60    |

### Flight Phases State Machine

```
FLIGHT_PHASES = [
    "APPROACH",      # 10+ NM from airport, descending
    "FINAL",         # Within 10 NM, aligned with runway
    "LANDING",       # Touchdown to runway exit
    "TAXI_IN",       # Runway to gate
    "PARKED",        # At gate
    "PUSHBACK",      # Gate to taxiway
    "TAXI_OUT",      # Taxiway to runway hold
    "TAKEOFF",       # Runway to 400ft AGL
    "DEPARTURE",     # Climbing above 400ft
]
```

### Speed Constraints by Phase

| Phase | Speed (knots) | Altitude |
|-------|--------------|----------|
| Approach | 160-200 | 3000-10000 ft |
| Final | 130-160 | 200-3000 ft |
| Landing | 0-140 | 0-200 ft |
| Taxi | 15-25 | Ground |
| Pushback | 3-5 | Ground |
| Takeoff | 0-160 | 0-400 ft |
| Departure | 200-300 | 400-10000 ft |

**Reference**: FAA AC 91-73B (Operations at Non-towered Airports), 14 CFR Part 91.117

### Runway Constraints

- **Single occupancy**: Only one aircraft on runway at a time
- **Crossing restrictions**: No crossings during active operations
- **Hold short**: Aircraft must hold short of runway until cleared
- **Runway change**: Requires ATC coordination and 2-minute gap

### Gate Assignment Constraints

```python
# Gate categories by aircraft capability
GATE_CATEGORIES = {
    "narrow_body": ["A", "B", "C"],      # A319-A321, B737 family
    "wide_body": ["D", "E"],             # A330, A350, B777, B787
    "super_heavy": ["F", "G"],           # A380, B747
}

# Minimum gate separation
GATE_SPACING_METERS = {
    "narrow_body": 50,   # ~164 ft
    "wide_body": 80,     # ~262 ft
    "super_heavy": 100,  # ~328 ft
}
```

### Position Generation Algorithm

```python
def generate_position(aircraft, elapsed_seconds):
    """Generate aircraft position based on flight phase."""
    phase = aircraft.phase

    if phase == "APPROACH":
        # Descend at 3° glide slope
        distance_nm = aircraft.start_distance - (elapsed_seconds * speed_kts / 3600)
        altitude_ft = distance_nm * 318  # 3° = 318 ft/nm

    elif phase == "TAXI_IN":
        # Follow taxi waypoints at constant speed
        progress = elapsed_seconds * TAXI_SPEED_KTS / total_taxi_distance
        position = interpolate_waypoints(taxi_route, progress)

    elif phase == "PARKED":
        # Static at gate position
        position = gate_positions[aircraft.gate]
```

---

## Flight Schedule (FIDS)

### Peak Hour Distribution

Based on typical hub airport operations:

| Time Period | Flights/Hour | % of Daily |
|-------------|-------------|------------|
| 00:00-05:00 | 0-3 | 5% |
| 05:00-06:00 | 5-10 | 3% |
| 06:00-10:00 | 18-25 | 30% |
| 10:00-16:00 | 10-15 | 25% |
| 16:00-20:00 | 18-25 | 30% |
| 20:00-23:00 | 8-12 | 7% |

**Reference**: FAA Airport Capacity and Delay reports

### Airline Mix (Hub Airport Example - SFO)

```python
AIRLINES = {
    "UAL": {"name": "United Airlines", "weight": 0.35},   # Hub carrier
    "DAL": {"name": "Delta Air Lines", "weight": 0.15},
    "AAL": {"name": "American Airlines", "weight": 0.15},
    "SWA": {"name": "Southwest Airlines", "weight": 0.10},
    "ASA": {"name": "Alaska Airlines", "weight": 0.08},
    "JBU": {"name": "JetBlue Airways", "weight": 0.05},
    "UAE": {"name": "Emirates", "weight": 0.04},
    "BAW": {"name": "British Airways", "weight": 0.03},
    "ANA": {"name": "All Nippon Airways", "weight": 0.03},
    "CPA": {"name": "Cathay Pacific", "weight": 0.02},
}
```

### IATA Delay Codes

Standard delay reason codes per **IATA SGHA Annex B**:

```python
DELAY_CODES = {
    # Passenger and Baggage (Code 61-69)
    "61": ("Cargo/Mail", 0.05),
    "62": ("Cleaning/Catering", 0.12),
    "63": ("Baggage handling", 0.10),
    "67": ("Late crew", 0.08),
    "68": ("Late inbound aircraft", 0.15),  # Reactionary

    # Weather (Code 71-79)
    "71": ("Weather at departure", 0.18),
    "72": ("Weather at destination", 0.12),

    # Air Traffic (Code 81-89)
    "81": ("ATC restriction", 0.15),

    # Technical (Code 41-49)
    "41": ("Aircraft defect", 0.05),
}
```

### Delay Distribution

- **15%** of flights experience delays
- **80%** of delays are 5-30 minutes
- **20%** of delays are 30-120 minutes
- Average delay: 18 minutes

**Reference**: Bureau of Transportation Statistics (BTS) On-Time Performance data

### Flight Status State Machine

```
SCHEDULED → ON_TIME → BOARDING → DEPARTED/ARRIVED
                   ↘ DELAYED → BOARDING → DEPARTED/ARRIVED
                            ↘ CANCELLED
```

---

## Weather Data (METAR/TAF)

### Flight Categories (FAA)

| Category | Ceiling | Visibility | Operations |
|----------|---------|------------|------------|
| **VFR** | ≥3000 ft | ≥5 SM | Visual approaches |
| **MVFR** | 1000-2999 ft | 3-4.99 SM | Caution required |
| **IFR** | 500-999 ft | 1-2.99 SM | Instrument required |
| **LIFR** | <500 ft | <1 SM | Low minimums |

**Reference**: 14 CFR Part 91, AIM Chapter 7

### METAR Format

```
KSFO 081756Z 28015G22KT 10SM SCT040 BKN080 18/10 A2992
│    │       │          │    │       │     │
│    │       │          │    │       │     └─ Altimeter (29.92 inHg)
│    │       │          │    │       └─ Temp/Dewpoint (18°C/10°C)
│    │       │          │    └─ Clouds (Scattered 4000, Broken 8000)
│    │       │          └─ Visibility (10 statute miles)
│    │       └─ Wind (280° at 15kt, gusting 22kt)
│    └─ Date/Time (8th day, 17:56 Zulu)
└─ Station (San Francisco International)
```

### Diurnal Patterns

| Time | Wind | Visibility | Temperature |
|------|------|------------|-------------|
| 05:00-09:00 | 2-8 kt, light | 20% chance fog | Base - 3-6°C |
| 09:00-12:00 | 8-15 kt | Clear | Base + 0-4°C |
| 12:00-18:00 | 10-20 kt, gusty | 10% chance rain | Base + 4-8°C |
| 18:00-22:00 | 5-12 kt | Clear | Base + 2-5°C |
| 22:00-05:00 | 0-6 kt | Clear | Base - 0-3°C |

### Cloud Coverage Codes

| Code | Coverage | Sky Percentage |
|------|----------|----------------|
| SKC | Clear | 0% |
| FEW | Few | 1-25% |
| SCT | Scattered | 26-50% |
| BKN | Broken | 51-87% |
| OVC | Overcast | 88-100% |

---

## Baggage Handling

### Industry Benchmarks

| Metric | Value | Source |
|--------|-------|--------|
| Bags per passenger | 1.2 | IATA |
| Load factor | 82% | IATA World Air Transport Statistics |
| Connecting bags | 15% | Industry average |
| Misconnect rate | 2% | SITA Baggage IT Insights |

**Reference**: IATA Resolution 743, SITA Annual Baggage Report

### Aircraft Capacity

```python
AIRCRAFT_CAPACITY = {
    "A319": 140,  "A320": 180,  "A321": 220,
    "A330": 300,  "A350": 350,  "A380": 550,
    "B737": 160,  "B738": 175,
    "B777": 380,  "B787": 300,
    "E175": 76,
}
```

### Baggage Processing Timeline (Departure)

| Phase | Time Before Departure | Status Code |
|-------|----------------------|-------------|
| Check-in | 180-60 min | `checked_in` |
| Security screening | 175-55 min | `security_screening` |
| Sorted | 165-45 min | `sorted` |
| Loading | 45-15 min | `loaded` |
| In transit | After departure | `in_transit` |

### Baggage Processing Timeline (Arrival)

| Phase | Time After Arrival | Status Code |
|-------|-------------------|-------------|
| In transit | Before arrival | `in_transit` |
| Unloaded | 0-10 min | `unloaded` |
| On carousel | 10-25 min | `on_carousel` |
| Claimed | 25+ min | `claimed` |

### Bag ID Format

```
{FLIGHT_NUMBER}-{SEQUENCE:04d}
Example: UA123-0042
```

---

## Ground Support Equipment (GSE)

### GSE Requirements by Aircraft Type

**Reference**: IATA Airport Handling Manual (AHM)

#### Narrow Body (A320, B737)

| Equipment | Quantity |
|-----------|----------|
| Pushback tug | 1 |
| Fuel truck | 1 |
| Belt loader | 2 |
| Catering truck | 1 |
| Lavatory truck | 1 |
| Ground power | 1 |

#### Wide Body (B777, A350)

| Equipment | Quantity |
|-----------|----------|
| Pushback tug | 1 |
| Fuel truck | 2 |
| Belt loader | 3 |
| Catering truck | 2 |
| Lavatory truck | 2 |
| Ground power | 1 |

#### Super Heavy (A380)

| Equipment | Quantity |
|-----------|----------|
| Pushback tug | 1 (special) |
| Fuel truck | 3 |
| Belt loader | 4 |
| Passenger stairs | 2 (upper deck) |
| Catering truck | 4 |
| Lavatory truck | 3 |
| Ground power | 2 |

### Turnaround Timing

#### Narrow Body (45 minutes total)

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| Arrival taxi | 5 min | - |
| Chocks on | 2 min | Arrival taxi |
| Deboarding | 8 min | Chocks on |
| Unloading | 10 min | Chocks on (parallel) |
| Cleaning | 12 min | Deboarding |
| Catering | 15 min | Deboarding (parallel) |
| Refueling | 18 min | Deboarding (parallel) |
| Loading | 12 min | Unloading |
| Boarding | 15 min | Cleaning, Catering |
| Chocks off | 2 min | Boarding, Loading, Refueling |
| Pushback | 5 min | Chocks off |
| Departure taxi | 8 min | Pushback |

#### Wide Body (90 minutes total)

All phases approximately 2x narrow body duration.

### Phase Dependencies (Gantt Logic)

```python
PHASE_DEPENDENCIES = {
    "arrival_taxi": [],
    "chocks_on": ["arrival_taxi"],
    "deboarding": ["chocks_on"],
    "unloading": ["chocks_on"],       # Parallel with deboarding
    "cleaning": ["deboarding"],
    "catering": ["deboarding"],        # Parallel with cleaning
    "refueling": ["deboarding"],       # Parallel with cleaning
    "loading": ["unloading"],
    "boarding": ["cleaning", "catering"],
    "chocks_off": ["boarding", "loading", "refueling"],
    "pushback": ["chocks_off"],
    "departure_taxi": ["pushback"],
}
```

---

## Regulatory References

### FAA Regulations

| Document | Topic | URL |
|----------|-------|-----|
| FAA Order 7110.65 | Air Traffic Control | [FAA](https://www.faa.gov/air_traffic/publications/atpubs/atc_html/) |
| 14 CFR Part 91 | General Operating Rules | [eCFR](https://www.ecfr.gov/current/title-14/chapter-I/subchapter-F/part-91) |
| 14 CFR Part 121 | Operating Requirements | [eCFR](https://www.ecfr.gov/current/title-14/chapter-I/subchapter-G/part-121) |
| AC 150/5300-13B | Airport Design | [FAA](https://www.faa.gov/airports/resources/advisory_circulars/index.cfm/go/document.current/documentNumber/150_5300-13) |

### ICAO Standards

| Document | Topic |
|----------|-------|
| Doc 4444 | PANS-ATM (Air Traffic Management) |
| Doc 9157 | Aerodrome Design Manual |
| Annex 14 | Aerodromes |

### IATA Standards

| Document | Topic |
|----------|-------|
| AHM | Airport Handling Manual |
| SGHA | Standard Ground Handling Agreement |
| Resolution 743 | Baggage Handling |
| SSIM | Standard Schedules Information Manual |

---

## Implementation Examples

### Generating a Complete Flight

```python
from datetime import datetime, timezone
import random

def generate_flight():
    """Generate a complete synthetic flight with all data domains."""

    # 1. Select airline and flight number
    airline_code = random.choices(
        list(AIRLINES.keys()),
        weights=[a["weight"] for a in AIRLINES.values()]
    )[0]
    flight_number = f"{airline_code}{random.randint(100, 2999)}"

    # 2. Select aircraft and route
    is_international = random.random() < 0.3
    aircraft_type = random.choice(WIDE_BODY if is_international else NARROW_BODY)
    destination = random.choice(
        INTERNATIONAL_AIRPORTS if is_international else DOMESTIC_AIRPORTS
    )

    # 3. Generate schedule with delay probability
    scheduled_time = datetime.now(timezone.utc).replace(
        minute=random.randint(0, 59), second=0
    )
    delay_minutes = 0
    if random.random() < 0.15:  # 15% delayed
        delay_minutes = random.randint(5, 30) if random.random() < 0.8 else random.randint(30, 120)

    # 4. Generate baggage
    capacity = AIRCRAFT_CAPACITY.get(aircraft_type, 180)
    passengers = int(capacity * 0.82)  # 82% load factor
    bags = int(passengers * 1.2)       # 1.2 bags per passenger

    # 5. Assign GSE
    gse_requirements = GSE_REQUIREMENTS.get(aircraft_type, GSE_REQUIREMENTS["A320"])

    return {
        "flight_number": flight_number,
        "airline": AIRLINES[airline_code]["name"],
        "aircraft_type": aircraft_type,
        "destination": destination,
        "scheduled_time": scheduled_time.isoformat(),
        "delay_minutes": delay_minutes,
        "passengers": passengers,
        "bags": bags,
        "gse": gse_requirements,
    }
```

### Enforcing Separation Standards

```python
def check_separation(aircraft_list, new_aircraft):
    """Verify minimum separation from all other aircraft."""
    new_wake = WAKE_CATEGORY.get(new_aircraft.type, "LARGE")

    for existing in aircraft_list:
        existing_wake = WAKE_CATEGORY.get(existing.type, "LARGE")
        required_nm = WAKE_SEPARATION_NM.get(
            (existing_wake, new_wake), 3.0
        )

        actual_nm = calculate_distance(existing.position, new_aircraft.position)

        if actual_nm < required_nm:
            return False, f"Separation violation: {actual_nm:.1f} < {required_nm} NM"

    return True, "OK"
```

### Generating Consistent Weather

```python
def generate_weather_for_time(hour: int, base_temp: int = 15):
    """Generate weather appropriate for time of day."""

    # Morning fog probability
    if 6 <= hour < 10 and random.random() < 0.2:
        visibility = round(random.uniform(0.5, 3.0), 1)
        category = "IFR" if visibility < 3 else "MVFR"
    else:
        visibility = 10.0
        category = "VFR"

    # Diurnal wind patterns
    if 12 <= hour < 18:
        wind_speed = random.randint(10, 20)
        gust = wind_speed + random.randint(5, 12) if random.random() < 0.3 else None
    else:
        wind_speed = random.randint(5, 12)
        gust = None

    return {
        "visibility_sm": visibility,
        "flight_category": category,
        "wind_speed_kts": wind_speed,
        "wind_gust_kts": gust,
    }
```

---

## Caching and Performance

### Recommended Cache Intervals

| Data Type | Cache Duration | Reason |
|-----------|---------------|--------|
| Flight schedule | 1 minute | Schedules are semi-static |
| Weather (METAR) | 10 minutes | Standard observation interval |
| Flight positions | 0 (real-time) | Continuous updates |
| Baggage status | 30 seconds | Near real-time tracking |
| GSE positions | 10 seconds | Operational changes |

### Seeding for Reproducibility

```python
import hashlib
import random

def get_seeded_random(flight_number: str, timestamp: datetime):
    """Get reproducible random generator for consistent data."""
    seed_str = f"{flight_number}-{timestamp.strftime('%Y%m%d%H%M')}"
    seed = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
    return random.Random(seed)
```

---

## Validation Checklist

Before deploying synthetic data generation:

- [ ] Wake turbulence separation enforced for all aircraft pairs
- [ ] Runway occupancy prevents conflicts
- [ ] Gate assignments respect aircraft size categories
- [ ] Delay distribution matches BTS statistics (15% delayed)
- [ ] Baggage counts match load factor × capacity × 1.2
- [ ] Weather follows diurnal patterns
- [ ] Turnaround timing respects phase dependencies
- [ ] METAR/TAF format passes validation

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-03-08 | Initial release |

---

*Document generated from Airport Digital Twin project implementation.*

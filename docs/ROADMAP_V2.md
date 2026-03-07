# Airport Digital Twin V2 - Gap Analysis & Feature Roadmap

## Executive Summary

This document analyzes gaps between the current Airport Digital Twin implementation and a comprehensive Airport Operations Management System (AOMS), proposes new features, identifies available data sources, and provides synthetic data generation strategies.

---

## 1. Current Implementation Assessment

### What We Have (V1 Complete)

| Category | Feature | Status |
|----------|---------|--------|
| **Data Ingestion** | OpenSky API integration | Implemented |
| **Data Ingestion** | Synthetic flight generator | Implemented |
| **Data Pipeline** | DLT Bronze/Silver/Gold | Implemented |
| **Serving** | Lakebase (PostgreSQL) | Implemented |
| **Serving** | Delta table fallback | Implemented |
| **ML** | Delay prediction (rule-based) | Implemented |
| **ML** | Gate recommendation | Implemented |
| **ML** | Congestion prediction | Implemented |
| **Visualization** | 2D Leaflet map | Implemented |
| **Visualization** | 3D Three.js scene | Implemented |
| **Visualization** | Aircraft GLB models | Implemented |
| **Platform** | Lakeview dashboard | Implemented |
| **Platform** | Genie integration | Implemented |
| **Platform** | Unity Catalog | Implemented |

### Current Limitations

1. **Flight Data Only** - No ground operations, passengers, or baggage
2. **Generic Airport** - No real airport layouts or configurations
3. **Rule-Based ML** - Demo models, not trained on real data
4. **No Historical Analysis** - Limited trajectory history
5. **No Scheduling** - No arrival/departure schedules
6. **No Weather** - Weather impact not modeled
7. **No Ground Equipment** - Tugs, fuel trucks, stairs not visualized

---

## 2. Gap Analysis: Airport Management System Components

### 2.1 Flight Operations (Current: 60% Complete)

| Component | Current State | Gap | Priority |
|-----------|---------------|-----|----------|
| Real-time flight positions | Implemented | - | - |
| Flight trajectories | Basic | Need smoother interpolation | Medium |
| Arrival/Departure boards | Missing | Full FIDS display | High |
| Flight schedules | Missing | Scheduled vs actual comparison | High |
| Turnaround tracking | Missing | Gate arrival → departure cycle | High |
| Stand/Gate assignment | Basic recommendation | Need operational assignment | Medium |
| Runway operations | Visual only | Sequencing, spacing logic | Low |

### 2.2 Ground Operations (Current: 0% Complete)

| Component | Current State | Gap | Priority |
|-----------|---------------|-----|----------|
| Ground Support Equipment (GSE) | Missing | Tugs, fuel trucks, stairs, belt loaders | High |
| Pushback operations | Missing | Tug allocation, timing | High |
| Refueling operations | Missing | Fuel truck routing, fill time | Medium |
| Catering vehicles | Missing | Meal loading operations | Low |
| De-icing | Missing | Winter operations simulation | Low |
| Ground crew scheduling | Missing | Staff allocation | Medium |

### 2.3 Passenger Operations (Current: 0% Complete)

| Component | Current State | Gap | Priority |
|-----------|---------------|-----|----------|
| Passenger flow simulation | Missing | Terminal movement | Medium |
| Check-in queues | Missing | Counter utilization | Medium |
| Security checkpoint | Missing | Queue times, throughput | Medium |
| Boarding process | Missing | Zone boarding simulation | Low |
| Connection monitoring | Missing | Tight connections alerts | High |

### 2.4 Baggage Operations (Current: 0% Complete)

| Component | Current State | Gap | Priority |
|-----------|---------------|-----|----------|
| Baggage handling system (BHS) | Missing | Conveyor visualization | High |
| Bag tracking | Missing | Individual bag status | High |
| Baggage cart operations | Missing | Ramp handling | Medium |
| Lost baggage tracking | Missing | Misconnect handling | Low |
| Baggage claims | Missing | Carousel assignment | Low |

### 2.5 Weather & Environment (Current: 0% Complete)

| Component | Current State | Gap | Priority |
|-----------|---------------|-----|----------|
| METAR/TAF integration | Missing | Real weather data | High |
| Wind visualization | Missing | Runway selection impact | Medium |
| Visibility conditions | Missing | IFR/VFR operations | Medium |
| Weather delays | Missing | Ground stops, diversions | High |
| Seasonal patterns | Missing | Winter ops, thunderstorms | Low |

### 2.6 Analytics & KPIs (Current: 30% Complete)

| Component | Current State | Gap | Priority |
|-----------|---------------|-----|----------|
| Lakeview dashboard | Basic | Need more KPIs | Medium |
| On-time performance | Missing | OTP metrics | High |
| Turnaround efficiency | Missing | TAT metrics | High |
| Gate utilization | Basic | Detailed analytics | Medium |
| Delay causes analysis | Missing | IATA delay codes | Medium |
| Capacity forecasting | Missing | Demand prediction | Low |

---

## 3. Available Data Sources

### 3.1 Flight Data APIs

| Source | Data Available | Access | Cost |
|--------|----------------|--------|------|
| **OpenSky Network** | Real-time ADS-B positions, trajectory history | Free (rate limited), Auth available | Free |
| **AviationStack** | Flights, schedules, airlines, airports | API Key | Free tier: 100 req/month |
| **FlightAware AeroAPI** | Comprehensive flight data, schedules | API Key | $$$ (enterprise) |
| **ADS-B Exchange** | Raw ADS-B data, no restrictions | API | Free/donations |
| **Flightradar24** | Flight tracking, historical | API | $$$ (enterprise) |

### 3.2 Airport Data (Free)

| Source | Data Available | Format |
|--------|----------------|--------|
| **OurAirports.com** | 70k+ airports, runways, frequencies, navaids | CSV |
| **OpenStreetMap** | Airport layouts, terminals, taxiways | GeoJSON/OSM |
| **FAA NASR** | US airport data, procedures | Various |
| **Eurocontrol DDR** | European traffic data | Research access |

### 3.3 Weather Data

| Source | Data Available | Access |
|--------|----------------|--------|
| **Aviation Weather Center** | METAR, TAF, SIGMET | Free API |
| **OpenWeatherMap** | General weather | Free tier |
| **CheckWX** | Aviation-specific METAR/TAF | Free tier |

### 3.4 Airline Data

| Source | Data Available | Format |
|--------|----------------|--------|
| **OpenFlights** | Airlines, routes, aircraft | CSV |
| **Wikipedia** | Airline fleet data | Scraping |
| **Planespotters.net** | Aircraft registrations, photos | API |

### 3.5 3D Models (Free/CC)

| Source | Models Available | License |
|--------|------------------|---------|
| **Sketchfab** | Aircraft, vehicles, terminals | CC-BY, CC0 |
| **TurboSquid** | Aircraft, ground equipment | Various (check license) |
| **Free3D** | Basic airport assets | Various |
| **Blender Market** | Professional airport kits | Paid |

---

## 4. Recommended V2 Roadmap

### Phase 6: Flight Information Display System (FIDS)
**Goal**: Arrival/departure boards with schedule vs actual comparison

**Features**:
- Scheduled arrivals/departures board UI
- Real-time vs scheduled comparison
- Delay indicators and reasons
- Gate changes and announcements

**Data Sources**:
- AviationStack API (schedules)
- Synthetic schedule generator

**Effort**: 2-3 days

---

### Phase 7: Ground Support Equipment (GSE)
**Goal**: Visualize and simulate ground operations

**Features**:
- GSE 3D models (tugs, fuel trucks, belt loaders, stairs)
- Pushback animation with tug
- Equipment allocation logic
- Turnaround timeline visualization

**Data Sources**:
- Synthetic (realistic timing models)
- Sketchfab GSE models (CC-BY)

**Effort**: 4-5 days

---

### Phase 8: Weather Integration
**Goal**: Real weather affecting operations

**Features**:
- METAR/TAF display in UI
- Wind sock/indicator visualization
- Runway selection based on wind
- Low visibility indicators
- Weather delay predictions

**Data Sources**:
- Aviation Weather Center API (free)
- CheckWX API (backup)

**Effort**: 2-3 days

---

### Phase 9: Baggage Handling System
**Goal**: Baggage flow visualization and tracking

**Features**:
- Baggage cart 3D models on ramp
- Conveyor system visualization (2D diagram)
- Bag tracking status per flight
- Misconnect alerts
- Carousel assignments

**Data Sources**:
- Synthetic bag generation
- Timing models based on aircraft type

**Effort**: 3-4 days

---

### Phase 10: Enhanced ML Models
**Goal**: Train real ML models on historical data

**Features**:
- XGBoost/LightGBM delay model trained on historical data
- Weather feature integration
- Historical OTP analysis
- A/B model comparison in MLflow
- Model serving endpoint upgrade

**Data Sources**:
- BTS On-Time Performance data (free, US flights)
- Synthetic historical generation

**Effort**: 4-5 days

---

### Phase 11: Real Airport Layout
**Goal**: Render actual airport (SFO, JFK, or configurable)

**Features**:
- OurAirports runway data integration
- OSM terminal/taxiway import
- Multiple airport selection
- Accurate gate positions

**Data Sources**:
- OurAirports.com CSV
- OpenStreetMap Overpass API

**Effort**: 3-4 days

---

### Phase 12: Passenger Flow Simulation
**Goal**: Terminal operations visualization

**Features**:
- Passenger particle simulation
- Check-in queue visualization
- Security checkpoint throughput
- Boarding progress indicator
- Connection risk alerts

**Data Sources**:
- Synthetic (passenger counts from aircraft type)
- Queue theory models

**Effort**: 4-5 days

---

## 5. Synthetic Data Generation Strategies

### 5.1 Flight Schedules

```python
# Strategy: Generate realistic schedule based on airport characteristics
def generate_flight_schedule(airport_code: str, date: date) -> List[Flight]:
    """
    Generate synthetic flight schedule.

    Parameters:
    - Peak hours: 6-9am, 4-7pm (60% of flights)
    - Airline mix based on hub status
    - Domestic/international ratio
    - Seasonal variation
    """
    schedule = []

    # Define peaks
    morning_peak = range(6, 10)  # 6am-10am
    evening_peak = range(16, 20)  # 4pm-8pm

    # Airlines weighted by hub status
    airlines = {
        "UAL": 0.35,  # Hub carrier
        "DAL": 0.15,
        "AAL": 0.15,
        "SWA": 0.10,
        "International": 0.25
    }

    # Generate 300-500 movements per day
    for hour in range(5, 24):
        flights_this_hour = 20 if hour in morning_peak or hour in evening_peak else 10
        for _ in range(flights_this_hour):
            schedule.append(generate_flight(hour, airlines))

    return schedule
```

### 5.2 Ground Support Equipment

```python
# Strategy: GSE allocation based on aircraft type and operation
GSE_REQUIREMENTS = {
    "A320": {
        "pushback_tug": 1,
        "fuel_truck": 1,
        "belt_loader": 2,
        "passenger_stairs": 0,  # Jetbridge
        "catering": 1,
    },
    "B777": {
        "pushback_tug": 1,  # Heavy tug
        "fuel_truck": 2,    # More fuel
        "belt_loader": 3,   # More cargo
        "passenger_stairs": 0,
        "catering": 2,
    },
    "A380": {
        "pushback_tug": 1,
        "fuel_truck": 3,
        "belt_loader": 4,
        "passenger_stairs": 2,  # Upper deck
        "catering": 4,
    }
}

TURNAROUND_TIMING = {
    "narrow_body": {
        "total_minutes": 45,
        "phases": {
            "arrival_taxi": 5,
            "deboarding": 10,
            "cleaning": 8,
            "catering": 12,
            "refueling": 15,
            "boarding": 20,
            "pushback": 5,
        }
    },
    "wide_body": {
        "total_minutes": 90,
        "phases": {
            "arrival_taxi": 8,
            "deboarding": 25,
            "cleaning": 15,
            "catering": 30,
            "refueling": 35,
            "boarding": 40,
            "pushback": 8,
        }
    }
}
```

### 5.3 Baggage System

```python
# Strategy: Bag generation based on passenger load
def generate_baggage_for_flight(flight: Flight) -> List[Bag]:
    """
    Generate synthetic baggage.

    Assumptions:
    - 1.2 bags per passenger average
    - 15% connecting bags
    - 2% misconnect rate
    - Processing time: 20-40 minutes from aircraft to carousel
    """
    passenger_count = AIRCRAFT_CAPACITY[flight.aircraft_type] * 0.82  # 82% load factor
    bag_count = int(passenger_count * 1.2)

    bags = []
    for i in range(bag_count):
        is_connecting = random.random() < 0.15
        is_misconnect = is_connecting and random.random() < 0.02

        bags.append(Bag(
            bag_id=f"{flight.flight_number}-{i:04d}",
            flight=flight,
            is_connecting=is_connecting,
            connecting_flight=generate_connection() if is_connecting else None,
            status="checked_in",
            processing_time_minutes=random.randint(20, 40),
        ))

    return bags
```

### 5.4 Weather Data

```python
# Strategy: Generate realistic METAR sequence
def generate_weather_sequence(duration_hours: int = 24) -> List[METAR]:
    """
    Generate synthetic weather progression.

    Patterns:
    - Morning fog clearing by 10am
    - Afternoon thermals/convection
    - Evening calm conditions
    - Occasional frontal passages
    """
    metars = []

    base_conditions = {
        "visibility_sm": 10,
        "ceiling_ft": 25000,
        "wind_direction": 280,
        "wind_speed_kts": 8,
        "temperature_c": 15,
        "dewpoint_c": 8,
    }

    for hour in range(duration_hours):
        conditions = base_conditions.copy()

        # Morning fog (6-9am)
        if 6 <= hour <= 9:
            conditions["visibility_sm"] = random.uniform(0.5, 3)
            conditions["ceiling_ft"] = random.randint(200, 1000)

        # Afternoon convection (14-18)
        if 14 <= hour <= 18 and random.random() < 0.3:
            conditions["wind_speed_kts"] = random.randint(15, 25)
            conditions["ceiling_ft"] = random.randint(3000, 8000)

        metars.append(create_metar(conditions))

    return metars
```

### 5.5 Delay Causes (IATA Codes)

```python
# Strategy: Realistic delay distribution
DELAY_DISTRIBUTION = {
    # Airline delays (40%)
    "61": ("Cargo/Mail", 0.05),
    "62": ("Cleaning/Catering", 0.08),
    "63": ("Baggage handling", 0.07),
    "64": ("Cargo handling", 0.03),
    "65": ("Oversales", 0.02),
    "66": ("Industrial action", 0.01),
    "67": ("Late crew", 0.08),
    "68": ("Late aircraft", 0.06),

    # Weather delays (25%)
    "71": ("Departure weather", 0.10),
    "72": ("Destination weather", 0.08),
    "73": ("En route weather", 0.04),
    "76": ("De-icing", 0.03),

    # ATC delays (20%)
    "81": ("ATC restriction", 0.12),
    "82": ("Airport capacity", 0.05),
    "83": ("Mandatory security", 0.03),

    # Technical (15%)
    "41": ("Aircraft defect", 0.08),
    "42": ("Scheduled maintenance", 0.04),
    "43": ("Unscheduled maintenance", 0.03),
}
```

---

## 6. Implementation Priority Matrix

| Phase | Feature | Demo Impact | Effort | Priority Score |
|-------|---------|-------------|--------|----------------|
| 6 | FIDS Display | High | Low | **9/10** |
| 8 | Weather Integration | High | Low | **9/10** |
| 7 | GSE Visualization | Very High | Medium | **8/10** |
| 10 | Enhanced ML Models | Medium | Medium | **7/10** |
| 9 | Baggage System | High | Medium | **7/10** |
| 11 | Real Airport Layout | Medium | Medium | **6/10** |
| 12 | Passenger Flow | Medium | High | **5/10** |

---

## 7. Recommended First Steps

### Immediate (Week 1):
1. **FIDS Display** - High visual impact, shows schedules
2. **Weather API Integration** - Easy win, adds realism

### Short-term (Week 2-3):
3. **GSE Models** - Download from Sketchfab, integrate in 3D scene
4. **Turnaround Timeline** - Show aircraft ground time progression

### Medium-term (Week 4+):
5. **Baggage System** - Adds operational depth
6. **Enhanced ML** - Train real models on BTS data

---

*Document created: 2026-03-08*
*Version: 2.0 Planning*

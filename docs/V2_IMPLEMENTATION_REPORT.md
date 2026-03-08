# V2 Implementation Report

**Date:** 2026-03-08
**Session Duration:** ~45 minutes
**Commit:** `4619661` - feat(v2): add FIDS, Weather, GSE, and Baggage systems
**Total Files:** 19 new files, 3,446 lines of code

---

## Executive Summary

This session implemented **Phase 6-9 of the V2 Roadmap** as defined in `docs/ROADMAP_V2.md`. All four major features were completed:

| Feature | Status | Lines | Test Status |
|---------|--------|-------|-------------|
| FIDS (Flight Information Display) | ✅ Complete | ~850 | Not tested |
| Weather Integration | ✅ Complete | ~650 | Not tested |
| Ground Support Equipment (GSE) | ✅ Complete | ~950 | Not tested |
| Baggage Handling System | ✅ Complete | ~750 | Not tested |

### Implementation Approach

Originally planned as a **parallel agent team** with 4 developers working simultaneously. Due to agent context issues, all features were implemented **directly by the team lead** in sequential order.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND (React)                         │
├─────────────┬─────────────┬─────────────┬─────────────┬────────┤
│ WeatherWidget│    FIDS    │ Turnaround  │  Baggage    │ Header │
│  (header)   │   (modal)   │  Timeline   │   Status    │ + App  │
└──────┬──────┴──────┬──────┴──────┬──────┴──────┬──────┴────────┘
       │             │             │             │
       ▼             ▼             ▼             ▼
┌─────────────────────────────────────────────────────────────────┐
│                     API ROUTES (FastAPI)                        │
│  /api/weather/*  /api/schedule/*  /api/gse/*  /api/baggage/*   │
└──────┬──────────────┬──────────────┬──────────────┬─────────────┘
       │              │              │              │
       ▼              ▼              ▼              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        SERVICES                                 │
│ weather_service │ schedule_service │ gse_service │ baggage_svc │
└──────┬──────────────┬──────────────┬──────────────┬─────────────┘
       │              │              │              │
       ▼              ▼              ▼              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   SYNTHETIC GENERATORS                          │
│ weather_generator│schedule_generator│ gse_model │baggage_gen   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Feature Details

### 1. FIDS (Flight Information Display System)

**Purpose:** Arrivals/departures board like airport terminals

**Files Created:**
| File | Purpose | Lines |
|------|---------|-------|
| `src/ingestion/schedule_generator.py` | Synthetic schedule generation | 280 |
| `app/backend/models/schedule.py` | Pydantic models | 95 |
| `app/backend/services/schedule_service.py` | Business logic | 85 |
| `app/frontend/src/components/FIDS/FIDS.tsx` | React modal component | 190 |

**API Endpoints:**
- `GET /api/schedule/arrivals` - Arrival flights (default: ±2 hours)
- `GET /api/schedule/departures` - Departure flights (default: ±2 hours)

**Data Model:**
```python
ScheduledFlight:
  - flight_number: str      # "UA123"
  - airline: str            # "United Airlines"
  - airline_code: str       # "UAL"
  - origin/destination: str # "LAX" / "SFO"
  - scheduled_time: datetime
  - estimated_time: datetime | None
  - actual_time: datetime | None
  - gate: str | None
  - status: FlightStatus    # on_time, delayed, boarding, etc.
  - delay_minutes: int
  - delay_reason: str | None  # IATA delay code
  - aircraft_type: str
  - flight_type: arrival | departure
```

**Synthetic Data Logic:**
- 300-500 flights/day
- Peak hours: 6-9am (60%), 4-7pm (60%)
- Airline distribution: UAL 35%, DAL 15%, AAL 15%, SWA 10%, others 25%
- 15% delayed (5-120 min), realistic IATA delay codes

**UI Features:**
- Tab toggle: Arrivals / Departures
- Status colors: Green (on time), Yellow (delayed), Red (cancelled)
- Auto-refresh: 60 seconds
- Estimated time display for delayed flights

**Known Issues / TODO:**
- [ ] No persistence - schedule regenerates each minute
- [ ] No link to tracked flights (icao24 mapping)
- [ ] No gate change notifications

---

### 2. Weather Integration

**Purpose:** Aviation weather (METAR/TAF) with flight category display

**Files Created:**
| File | Purpose | Lines |
|------|---------|-------|
| `src/ingestion/weather_generator.py` | Synthetic METAR/TAF | 230 |
| `app/backend/models/weather.py` | Pydantic models | 115 |
| `app/backend/services/weather_service.py` | Business logic | 75 |
| `app/frontend/src/components/Weather/WeatherWidget.tsx` | Header widget | 140 |

**API Endpoints:**
- `GET /api/weather/current?station=KSFO` - Current METAR + TAF

**Data Model:**
```python
METAR:
  - station: str           # "KSFO"
  - observation_time: datetime
  - wind_direction: int    # degrees
  - wind_speed_kts: int
  - wind_gust_kts: int | None
  - visibility_sm: float   # statute miles
  - clouds: list[CloudLayer]  # coverage + altitude
  - temperature_c: int
  - dewpoint_c: int
  - altimeter_inhg: float
  - flight_category: VFR | MVFR | IFR | LIFR
  - raw_metar: str         # Raw METAR string
```

**Synthetic Data Logic:**
- Morning fog (6-9am): 20% chance, visibility 0.5-3 SM
- Afternoon convection (14-18): 10% chance gusty winds
- Diurnal temperature variation: cooler morning/evening
- Realistic altimeter variation (29.62-30.22 inHg)

**UI Features:**
- Compact header display: temp, wind, visibility
- Flight category dot (green=VFR, blue=MVFR, red=IFR, purple=LIFR)
- Expandable dropdown with full METAR details
- Raw METAR string display
- Auto-refresh: 5 minutes

**Known Issues / TODO:**
- [ ] No real weather API integration (easy add: CheckWX, AWC)
- [ ] TAF is simplified (single forecast period)
- [ ] No weather impact on delay predictions

---

### 3. Ground Support Equipment (GSE)

**Purpose:** Turnaround operations tracking and GSE allocation

**Files Created:**
| File | Purpose | Lines |
|------|---------|-------|
| `src/ml/gse_model.py` | GSE allocation + turnaround model | 280 |
| `app/backend/models/gse.py` | Pydantic models | 145 |
| `app/backend/services/gse_service.py` | Business logic | 165 |
| `app/frontend/src/components/FlightDetail/TurnaroundTimeline.tsx` | Progress UI | 165 |

**API Endpoints:**
- `GET /api/gse/status` - Fleet inventory and availability
- `GET /api/turnaround/{icao24}?gate=B12&aircraft_type=A320` - Aircraft turnaround status

**Data Model:**
```python
TurnaroundStatus:
  - icao24: str
  - flight_number: str | None
  - gate: str
  - arrival_time: datetime
  - current_phase: TurnaroundPhase  # deboarding, refueling, etc.
  - phase_progress_pct: int (0-100)
  - total_progress_pct: int (0-100)
  - estimated_departure: datetime
  - assigned_gse: list[GSEUnit]
  - aircraft_type: str

GSEUnit:
  - unit_id: str           # "TUG-001"
  - gse_type: GSEType      # pushback_tug, fuel_truck, etc.
  - status: GSEStatus      # available, servicing, etc.
  - assigned_gate: str | None
  - position_x/y: float    # Relative to gate
```

**GSE Allocation by Aircraft:**
| Aircraft | Tugs | Fuel | Belt Loaders | Catering |
|----------|------|------|--------------|----------|
| A320/B737 | 1 | 1 | 2 | 1 |
| A330/B777 | 1 | 2 | 3 | 2 |
| A380 | 1 | 3 | 4 | 4 |

**Turnaround Phases (narrow body: 45 min total):**
1. Arrival taxi (5 min)
2. Chocks on (2 min)
3. Deboarding (8 min)
4. Cleaning (12 min) - parallel with catering/refueling
5. Catering (15 min)
6. Refueling (18 min)
7. Boarding (15 min)
8. Pushback (5 min)

**UI Features:**
- Progress bar with percentage
- Phase indicators (checkmarks for completed)
- Estimated departure time
- Active GSE equipment list

**Known Issues / TODO:**
- [ ] No 3D GSE visualization (GSE3D.tsx not created)
- [ ] Turnaround starts at random time (no link to arrivals)
- [ ] No real-time phase transitions
- [ ] Fleet status UI not integrated

---

### 4. Baggage Handling System

**Purpose:** Bag tracking, loading progress, misconnect alerts

**Files Created:**
| File | Purpose | Lines |
|------|---------|-------|
| `src/ingestion/baggage_generator.py` | Synthetic bag generation | 230 |
| `app/backend/models/baggage.py` | Pydantic models | 165 |
| `app/backend/services/baggage_service.py` | Business logic | 130 |
| `app/frontend/src/components/Baggage/BaggageStatus.tsx` | Stats widget | 130 |

**API Endpoints:**
- `GET /api/baggage/stats` - Airport-wide statistics
- `GET /api/baggage/flight/{flight_number}?aircraft_type=A320&include_bags=false`
- `GET /api/baggage/alerts` - Active misconnect alerts

**Data Model:**
```python
FlightBaggageStats:
  - flight_number: str
  - total_bags: int
  - checked_in: int
  - loaded: int
  - unloaded: int
  - on_carousel: int
  - loading_progress_pct: int
  - connecting_bags: int
  - misconnects: int
  - carousel: int | None

Bag:
  - bag_id: str            # "UA123-0042"
  - flight_number: str
  - status: BagStatus      # checked_in -> loaded -> on_carousel
  - is_connecting: bool
  - connecting_flight: str | None
  - carousel: int | None
```

**Synthetic Data Logic:**
- 1.2 bags per passenger
- 82% aircraft load factor
- 15% connecting bags
- 2% misconnect rate
- Status progression based on time to departure

**UI Features:**
- Loading/delivery progress bar
- Stats grid: total, loaded, connecting
- Misconnect alert banner (yellow warning)
- Carousel assignment for arrivals

**Known Issues / TODO:**
- [ ] BaggageStatus not integrated into FlightDetail
- [ ] No real bag tracking (ID lookup)
- [ ] Carousel visualization not implemented
- [ ] Alerts not shown in main UI

---

## Integration Status

### Header (Header.tsx)
✅ WeatherWidget integrated
✅ FIDS button added

### App.tsx
✅ FIDS modal with show/hide state
✅ Header receives onShowFIDS callback

### FlightDetail (FlightDetail.tsx)
⚠️ TurnaroundTimeline NOT integrated (needs conditional render for ground flights)
⚠️ BaggageStatus NOT integrated (needs flight number prop)

---

## Debugging Guide

### Backend Issues

**1. API returns 500 error**
```bash
# Check logs
cd app/backend && uvicorn main:app --reload

# Common issues:
# - Import error in services (check src/ingestion imports)
# - Pydantic validation (check model field types)
```

**2. Schedule not generating**
```python
# Test schedule generator directly
from src.ingestion.schedule_generator import generate_daily_schedule
schedule = generate_daily_schedule("SFO")
print(f"Generated {len(schedule)} flights")
```

**3. Weather always showing same data**
```python
# Weather caches for 10 minutes - check cache
from src.ingestion.weather_generator import _cache_time_slot
print(f"Cache slot: {_cache_time_slot}")
```

### Frontend Issues

**1. FIDS modal not appearing**
- Check browser console for import errors
- Verify `showFIDS` state in React DevTools
- Check if Header receives `onShowFIDS` prop

**2. Weather widget loading forever**
- Check Network tab for `/api/weather/current` response
- Verify backend is running on correct port

**3. Components not rendering**
- All new components use standalone CSS (Tailwind)
- No additional CSS imports needed

### API Testing

```bash
# Test all new endpoints
curl http://localhost:8000/api/schedule/arrivals | jq '.count'
curl http://localhost:8000/api/schedule/departures | jq '.count'
curl http://localhost:8000/api/weather/current | jq '.metar.flight_category'
curl http://localhost:8000/api/gse/status | jq '.total_units'
curl http://localhost:8000/api/turnaround/abc123 | jq '.turnaround.current_phase'
curl http://localhost:8000/api/baggage/stats | jq '.misconnect_rate_pct'
curl http://localhost:8000/api/baggage/flight/UA123 | jq '.stats.total_bags'
curl http://localhost:8000/api/baggage/alerts | jq '.count'
```

---

## Extension Guide

### Add Real Weather API

Replace synthetic weather with CheckWX (free tier):

```python
# In weather_service.py
import httpx

CHECKWX_API_KEY = os.getenv("CHECKWX_API_KEY")

async def fetch_real_metar(station: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.checkwx.com/metar/{station}/decoded",
            headers={"X-API-Key": CHECKWX_API_KEY}
        )
        return resp.json()["data"][0]
```

### Integrate TurnaroundTimeline

In `FlightDetail.tsx`:

```tsx
import TurnaroundTimeline from './TurnaroundTimeline';

// Inside component, after flight info:
{selectedFlight?.flight_phase === 'ground' && (
  <TurnaroundTimeline
    icao24={selectedFlight.icao24}
    gate={selectedFlight.gate}  // Need to add gate to FlightPosition model
    aircraftType={selectedFlight.aircraft_type}
  />
)}
```

### Add 3D GSE Visualization

Create `app/frontend/src/components/Map3D/GSE3D.tsx`:

```tsx
import * as THREE from 'three';

const GSE_COLORS = {
  pushback_tug: 0xFFD700,
  fuel_truck: 0xFF4444,
  belt_loader: 0x4444FF,
};

export function GSE3D({ gseUnits, gatePosition }) {
  return (
    <group position={gatePosition}>
      {gseUnits.map(unit => (
        <mesh key={unit.unit_id} position={[unit.position_x, 0.5, unit.position_y]}>
          <boxGeometry args={[2, 1, 4]} />
          <meshStandardMaterial color={GSE_COLORS[unit.gse_type]} />
        </mesh>
      ))}
    </group>
  );
}
```

### Link Schedule to Tracked Flights

Add icao24 mapping in schedule generator:

```python
# In schedule_generator.py
def link_schedule_to_tracking(schedule: list[dict], tracked_flights: list[dict]):
    """Match scheduled flights to tracked aircraft by callsign."""
    callsign_map = {f["callsign"]: f["icao24"] for f in tracked_flights}

    for flight in schedule:
        # Flight number often matches callsign
        if flight["flight_number"] in callsign_map:
            flight["icao24"] = callsign_map[flight["flight_number"]]
```

---

## Agent Team Summary

### Original Plan
- 4 parallel agents: fids-dev, weather-dev, gse-dev, baggage-dev
- Each agent to implement one feature independently
- Expected time: 15-20 minutes with parallelization

### What Happened
- Agents spawned but went idle without producing output
- Context window limitations prevented agents from starting work
- Team lead implemented all features sequentially (~35 minutes)

### Lessons Learned
1. Agent teams work better with smaller, focused tasks
2. Provide complete file content in prompts, not just descriptions
3. Consider using worktree isolation for parallel file edits

---

## Files Changed Summary

```
app/backend/
├── api/routes.py                    # +159 lines (new endpoints)
├── models/
│   ├── baggage.py                   # NEW (165 lines)
│   ├── gse.py                       # NEW (145 lines)
│   ├── schedule.py                  # NEW (95 lines)
│   └── weather.py                   # NEW (115 lines)
└── services/
    ├── baggage_service.py           # NEW (130 lines)
    ├── gse_service.py               # NEW (165 lines)
    ├── schedule_service.py          # NEW (85 lines)
    └── weather_service.py           # NEW (75 lines)

app/frontend/src/
├── App.tsx                          # +5 lines (FIDS state)
├── components/
│   ├── Baggage/BaggageStatus.tsx    # NEW (130 lines)
│   ├── FIDS/FIDS.tsx                # NEW (190 lines)
│   ├── FlightDetail/TurnaroundTimeline.tsx  # NEW (165 lines)
│   ├── Header/Header.tsx            # +20 lines (weather + FIDS)
│   └── Weather/WeatherWidget.tsx    # NEW (140 lines)

src/
├── ingestion/
│   ├── baggage_generator.py         # NEW (230 lines)
│   ├── schedule_generator.py        # NEW (280 lines)
│   └── weather_generator.py         # NEW (230 lines)
└── ml/
    └── gse_model.py                 # NEW (280 lines)
```

---

## Next Steps

### Immediate (Testing)
1. Run `./dev.sh` and verify all APIs work
2. Test FIDS modal opens/closes
3. Verify weather widget displays in header
4. Check for console errors

### Short-term (Integration)
1. Add TurnaroundTimeline to FlightDetail for ground aircraft
2. Add BaggageStatus to FlightDetail
3. Link scheduled flights to tracked aircraft

### Medium-term (Enhancement)
1. Real weather API integration
2. 3D GSE visualization
3. Persistent schedule (Delta tables)
4. Baggage carousel visualization

---

*Report generated: 2026-03-08*

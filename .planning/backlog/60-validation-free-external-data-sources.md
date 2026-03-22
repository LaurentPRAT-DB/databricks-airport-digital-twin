# Validation Improvement Plan — Free External Data Sources

## Data Already Available (in data/calibration/)

Gold-mine data already downloaded:

| Source | Data | Records | Validation Tests it Unlocks |
|--------|------|---------|----------------------------|
| BTS OTP (12 months, 2024) | Dep/arr delays, taxi-in/out, cancellations, diversions, hourly patterns, delay causes, tail numbers | 24K+ SFO records/month | O01, O02, O04, P01, P02 |
| BTS DB28 T-100 (10 months) | Airline shares, route volumes, fleet mix | All US airports | Calibration accuracy |
| OpenFlights (routes.dat) | 67K worldwide routes | 1,182 airport profiles built | Calibration coverage |
| OurAirports (airports.csv, runways.csv) | 80K airports, 45K runways | All airports | Runway config validation |

## Key Finding: BTS OTP has taxi time and turnaround data you aren't using

The BTS data contains fields the simulation should validate against right now:

| BTS Field | Real SFO Value (Dec 2024) | Sim Value | Gap |
|-----------|--------------------------|-----------|-----|
| TaxiOut | mean=20.4 min, median=19, P95=36 | Modeled as 5-8 min (GSE model) | 12-15 min under-estimate |
| TaxiIn | mean=8.5 min, median=6, P95=22 | Modeled as 5-8 min | Roughly OK for narrow-body |
| DepDelay | 21.6% delayed >15 min, mean=14 min | 0% delayed (no delay at low load) | Need calibrated delay injection |
| Turnaround (tail proxy) | median=72 min, P75=96, P95=180 | avg=26.5 min (critical path) | 2.7x under-estimate |
| Cancellation rate | 0.7% | 0% | Need cancellation model |
| Daily movements | ~390 dep + ~390 arr = ~780 | 50 flights/4h | Load too low to test capacity |

---

## Free External Sources to Add

### 1. OpenSky Network REST API (already integrated, just not used for validation)

- **What:** Real-time and historical ADS-B flight positions
- **Free tier:** 400 req/day anonymous, 4000 with registration (free)
- **Validation tests:** O02 (runway sequencing), O04 (taxi times via ground track)
- **How:** Query `flights/departure` and `flights/arrival` endpoints, compare timestamps against sim
- **License:** CC BY-NC 4.0

### 2. NOAA Aviation Weather Center — METAR/TAF (confirmed working)

- **URL:** `aviationweather.gov/api/data/metar?ids=KSFO&format=raw&hours=N`
- **What:** Real-time and historical METAR observations (wind, visibility, ceiling, wx phenomena)
- **Free:** Unlimited, no auth, US government data
- **Validation tests:** D01 (weather replay), P02 (delay propagation from real weather)
- **How:** Ingest historical METARs for a date, replay visibility/ceiling/wind into scenario system

### 3. FAA ASPM (Aviation System Performance Metrics)

- **URL:** `aspmhelp.faa.gov/index.php`
- **What:** Airport arrival/departure rates (AAR/ADR), actual throughput per hour
- **Free:** Public access, monthly data
- **Validation tests:** O02 (movements/hr), P03 (capacity headroom)
- **How:** Compare simulated throughput at capacity load against FAA published AAR/ADR

### 4. FAA OPSNET (Operations Network)

- **URL:** Available via ATADS (Air Traffic Activity Data System)
- **What:** Tower operations count per airport per day
- **Free:** Public, downloadable CSV
- **Validation tests:** O02 (total movement count calibration)

### 5. Eurocontrol DDR/NM B2B (for European airports)

- **What:** Airport slot allocations, traffic counts, weather disruption logs
- **Free:** Registration required, research/non-commercial use
- **Validation tests:** O01, O02, D01 for LHR, CDG, FRA, AMS

---

## Concrete Improvements (ranked by impact)

### Priority 1: Validate against BTS data you already have

This requires no new data downloads — just write a validation script:

```
tests/validation/
  validate_taxi_times.py      — Compare sim taxi vs BTS TaxiOut/TaxiIn
  validate_delays.py          — Compare sim delay rate vs BTS DepDel15
  validate_turnarounds.py     — Compare sim turnaround vs BTS tail-number proxy
  validate_airline_mix.py     — Compare sim airline shares vs BTS carrier breakdown
  validate_hourly_profile.py  — Compare sim hourly traffic vs BTS CRSDepTime
```

**Biggest fix needed:** Turnaround time. Real SFO median = 72 min vs sim 26.5 min. The critical-path DAG compresses too aggressively. Real turnarounds include buffer/slack time, gate hold, late passenger boarding, baggage reconciliation that aren't in the phase model.

**Second biggest fix:** Taxi-out time. Real mean = 20.4 min vs modeled 5-8 min. The simulation doesn't model taxi queue congestion at runway holding points.

### Priority 2: Add METAR weather ingest for scenario replay

The weather generator currently produces synthetic METARs. Replace with real historical METAR ingest:
- Fetch from `aviationweather.gov/api/data/metar` (confirmed working, free, no auth)
- Parse METAR strings into `WeatherEvent` objects
- Replay actual weather sequences for historical validation

### Priority 3: Add BTS-calibrated delay injection

The KSFO calibration profile from OpenFlights has `delay_rate: 0.0` and `mean_delay: 0.0` — it's missing delay data. The BTS OTP data shows 21.6% delayed, mean 14 min, with cause breakdown (carrier 40 min avg, weather 107 min, NAS 28 min, late aircraft 61 min). Wire this into the profile builder.

### Priority 4: OpenSky live comparison mode

Add a validation mode that:
1. Queries OpenSky for current SFO departures/arrivals
2. Runs the sim with matching flight count and time window
3. Compares movement rates, timing patterns, and airline mix

### Priority 5: Passenger flow model (biggest gap, most work)

No free data source exists for airport passenger flow at the individual level. However:
- TSA checkpoint throughput data is published weekly at `tsa.gov/travel/passenger-volumes` — total daily checkpoint throughput numbers. Free, public.
- Use these as a top-level constraint for passenger generation rate
- Model internal flow using queuing theory (M/M/c queues for checkpoints, check-in desks)

---

## Data Source Summary Table

| Source | Cost | Auth | Tests Unlocked | Already Have? |
|--------|------|------|----------------|---------------|
| BTS OTP | Free | None | O01, O02, O04, P01, P02 | Yes (12 months) |
| BTS T-100 | Free | None | Calibration | Yes (10 months) |
| OpenFlights | Free | None | Route calibration | Yes (downloaded) |
| OurAirports | Free | None | Runway config | Yes (downloaded) |
| OpenSky API | Free | Optional | O02, O04 | Yes (code exists) |
| NOAA METAR | Free | None | D01, P02 | Confirmed working |
| FAA ASPM/ATADS | Free | None | O02, P03 | Not yet |
| TSA volumes | Free | None | F01 (top-level) | Not yet |
| Eurocontrol | Free (reg.) | Required | EU airports | Not yet |

---

## Bottom Line

You already have the data to validate 5 of the 7 PASS tests and fix the 2 biggest numerical gaps (turnaround time 2.7x too fast, taxi-out 2.5x too fast). No new downloads needed — just write the comparison scripts.

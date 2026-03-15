# Calibration System — Status, Quality & Roadmap

**Date:** 2026-03-15
**Scope:** Airport profile calibration for synthetic flight generation

---

## 1. What Was Done

### 1.1 Core Infrastructure

- **`AirportProfile` dataclass** (`src/calibration/profile.py`) — single data object per airport containing:
  - Airline market shares (e.g., UAL: 59% at SFO)
  - Domestic and international route frequency distributions
  - Fleet mix per airline (aircraft type probabilities)
  - Hourly traffic profile (24-element weight vector)
  - Delay rate, delay cause distribution, mean delay minutes
  - Metadata: data source, sample size, profile date

- **`AirportProfileLoader`** — loads profiles with a 4-level fallback chain:
  1. In-memory cache (instant)
  2. Local JSON file (`data/calibration/profiles/{ICAO}.json`)
  3. Unity Catalog table (`airport_profiles`) when running on Databricks
  4. Hardcoded fallback (generic distributions)

- **33 airport profiles built** — 21 US + 12 international airports

### 1.2 Real Data Sources Integrated

| Source | Coverage | What It Provides | Status |
|--------|----------|-------------------|--------|
| **BTS T-100 DB28 Domestic Segment** | 21 US airports | Airline shares, domestic route frequencies, fleet mix, domestic ratio | **Live** — 10 zip files, Feb 2024–Nov 2025, 33k–145k departures per airport |
| **OurAirports CSV** | Global (84,811 airports) | Airport metadata (ICAO/IATA codes, coordinates, elevation, runway data) | **Downloaded** — used in validation script |
| **Known stats (hand-researched)** | 33 airports | Hourly profiles, delay rates, delay distributions, international route shares | **Live** — fills gaps that DB28 doesn't cover |

### 1.3 Data Pipeline

```
BTS DB28 zip files (data/calibration/download_manual/)
    │
    ▼
bts_ingest.py: parse_db28_segment_zips()
    │  - Pipe-delimited .asc format parser
    │  - DOT 2-letter → ICAO 3-letter carrier mapping (40+ carriers)
    │  - Regional carrier → mainline consolidation (SkyWest→United, etc.)
    │  - Service class filtering (scheduled only)
    │
    ▼
profile_builder.py: _build_single_profile()
    │  - Tries DB28 zips first for US airports
    │  - Falls back to BTS CSV, OpenSky, known_stats, generic fallback
    │  - Merges DB28 data with known_stats for hourly/delay fields
    │
    ▼
data/calibration/profiles/{ICAO}.json
    │
    ▼
AirportProfileLoader → consumed by generators + ML models
```

### 1.4 Profile Wiring Into Generators

Both the **live demo** and **batch simulation** use calibrated profiles:

| Component | Generator | Uses Profile? | What's Calibrated |
|-----------|-----------|---------------|-------------------|
| **2D/3D map** (real-time flight dots) | `fallback.py:generate_synthetic_flights()` | **Yes** | Airline selection, route selection (origin/destination), fleet mix (aircraft type) |
| **FIDS board** (flight schedule table) | `schedule_generator.py:generate_daily_schedule()` | **Yes** | Airline, route, aircraft type, delay rate/cause, hourly flight count |
| **Simulation engine** (batch) | `engine.py:SimulationEngine._generate_schedule()` | **Yes** | All of the above, plus scenario modifiers |
| **Data generator service** (Lakebase) | `data_generator_service.py` → `generate_daily_schedule()` | **Yes** | Same as FIDS — populates Lakebase tables |

**Key finding: demo and simulation share the same underlying generator functions** (`_select_airline`, `_select_destination`, `_select_aircraft`, `_generate_delay` from `schedule_generator.py`). The demo (`fallback.py`) also has its own airline selection path that reads the profile directly. Both paths are calibrated.

### 1.5 ML Model Calibration

| Model | File | How Profile Is Used |
|-------|------|---------------------|
| **DelayPredictor** | `src/ml/delay_model.py` | Accepts profile; base delay rate comes from `profile.delay_rate` instead of hardcoded 15% |
| **GateRecommender** | `src/ml/gate_model.py` | Airline affinity scoring — gates with matching airline get priority; international flight detection from profile routes |
| **CongestionPredictor** | `src/ml/congestion_model.py` | Hourly capacity scaling — area capacities adjusted by `profile.hourly_profile` weight for current hour |

### 1.6 Scripts & Tools

| Script | Purpose |
|--------|---------|
| `scripts/build_airport_profiles.py` | CLI to build all profiles, with `--persist-to-uc` for Unity Catalog |
| `scripts/validate_profiles_live.py` | Compare profiles against live OpenSky ADS-B state vectors |
| `scripts/download_calibration_data.py` | Download OurAirports CSVs (BTS requires manual browser download) |
| `databricks/notebooks/build_calibration_profiles.py` | Databricks notebook for profile building/refresh with UC persistence |

### 1.7 Expanded Carrier Database

The `AIRLINES` dict in `schedule_generator.py` now covers 33 airlines (was 10), including:
- US majors: United, Delta, American, Southwest, Alaska, JetBlue
- US ULCCs: Spirit, Frontier, Allegiant, Sun Country, Hawaiian
- European: British Airways, Lufthansa, Air France, KLM, Turkish, Ryanair, easyJet, Virgin Atlantic
- Asian: ANA, JAL, Singapore, Cathay Pacific, Korean Air, EVA Air
- Other: Emirates, Etihad, flydubai, Air Canada, Aeromexico, LATAM, South African, Qantas

---

## 2. Current Quality Assessment

### 2.1 What's Real Data vs Approximated

| Field | US Airports (21) | International (12) |
|-------|-------------------|-------------------|
| Airline market shares | **Real** — BTS T-100 (33k–145k departures) | Approximated — hand-researched from public sources |
| Domestic route shares | **Real** — BTS T-100 route volumes | N/A (no domestic for most) or hand-researched |
| International route shares | Approximated — known_stats | Approximated — known_stats |
| Domestic ratio | **Real** — computed from BTS T-100 | Hand-researched |
| Fleet mix per airline | **Real** — BTS T-100 aircraft type codes | Hand-researched |
| Hourly traffic profile | Approximated — known_stats | Approximated — known_stats |
| Delay rate | Approximated — known_stats | Approximated — known_stats |
| Delay cause distribution | Approximated — known_stats | Approximated — known_stats |
| Mean delay minutes | Approximated — known_stats | Approximated — known_stats |

### 2.2 Validation Results

Live OpenSky validation (7 airports tested against ADS-B state vectors):
- **7.0/8 average carrier matches** within 15 percentage points
- SFO, JFK, ORD, ATL all showed correct dominant carriers matching profiles
- International airports (LHR, EDDF) showed good alignment

### 2.3 Known Accuracy Issues

1. **Regional carrier consolidation may over-concentrate** — SkyWest flies for both United and Delta, but we map all SkyWest → United. SFO shows UAL at 59% vs known_stats 46%. The truth is somewhere in between; SkyWest allocation varies by airport.

2. **DB28 fleet type codes are numeric**, not ICAO type designators. The `BTS_AIRCRAFT_MAP` converts some (612→A319, 625→B738) but coverage is incomplete — many flights get raw numeric codes like "620" that don't map to recognizable types.

3. **Hourly profiles are not from real data** for any airport. The known_stats patterns are reasonable approximations (dual-peak for US hubs, single-peak for international) but not measured.

4. **Delay statistics are approximated** — delay rates (12%–30%) come from public BTS summaries and FAA ATADS, not computed from raw on-time performance data.

5. **International route shares for US airports** come from known_stats, not the BTS T-100 International Segment data. The downloaded DB28IS file was from 2005 (too old).

---

## 3. What Could Be Done to Improve

### 3.1 Near-Term (Data Downloads)

| Action | Impact | Effort |
|--------|--------|--------|
| **Download current BTS T-100 International Segment** (DB28IS 2024–2025) | Real international route shares + carrier data for US airports | Low — same BTS site, manual download |
| **Download BTS On-Time Performance** data | Real hourly patterns, delay rates, delay cause breakdowns per airport | Medium — large files (~500MB/month), different BTS page |
| **Parse DB28 aircraft type codes fully** | Real fleet mix with ICAO type designators instead of numeric codes | Low — extend BTS_AIRCRAFT_MAP with full BTS Aircraft Type Lookup Table |

### 3.2 Medium-Term (Engineering)

| Action | Impact | Effort |
|--------|--------|--------|
| **Fix SkyWest regional allocation** | Correct UAL/DAL split at airports where SkyWest flies for both | Medium — need BTS operating carrier + ticketing carrier cross-reference |
| **OpenSky historical data** for international airports | Real airline/route data for LHR, FRA, SIN, etc. (free API, rate-limited) | Medium — requires authenticated account, rate-limit management |
| **Seasonal profile variants** | Different distributions for summer vs winter (tourism airports like MCO, LAS shift significantly) | Medium — split BTS data by quarter, store seasonal profiles |
| **Profile auto-refresh pipeline** | Databricks job that rebuilds profiles monthly from new BTS releases | Medium — job definition + BTS data fetch automation |
| **Gate-airline affinity from real data** | Map which gates each airline actually uses (not just generic scoring) | High — need airport-specific gate assignment data (not in BTS) |

### 3.3 Long-Term (Architecture)

| Action | Impact | Effort |
|--------|--------|--------|
| **Eurocontrol/ICAO data for international airports** | Real European traffic data (equivalent of BTS for EU) | High — data access agreements required |
| **ASPM/OPSNET integration** | Real airport operational data (runway configs, delay causes, throughput) | High — FAA data access |
| **Profile-driven traffic profiles** | Replace the 4 generic TRAFFIC_PROFILES patterns with per-airport learned curves | Medium — derive from BTS hourly data once available |
| **Demand forecasting** | Predict future traffic mix from trend data (new routes, airline expansions) | High — ML model on historical BTS time series |

---

## 4. Architecture: How Calibration Flows Through the System

```
                    ┌──────────────────────────────────────┐
                    │        AirportProfileLoader          │
                    │  (cache → JSON → UC → fallback)      │
                    └──────────────┬───────────────────────┘
                                   │
                    ┌──────────────▼───────────────────────┐
                    │         AirportProfile (JSON)         │
                    │  airline_shares, route_shares,        │
                    │  fleet_mix, hourly_profile,           │
                    │  delay_rate, delay_distribution       │
                    └──┬────────────┬──────────────┬───────┘
                       │            │              │
          ┌────────────▼──┐  ┌─────▼──────┐  ┌───▼─────────────┐
          │  fallback.py   │  │ schedule_  │  │   ML Models      │
          │  (2D/3D map)   │  │ generator  │  │ (delay, gate,    │
          │                │  │ (FIDS +    │  │  congestion)     │
          │ airline select │  │  sim engine)│  │                  │
          │ route select   │  │            │  │ delay_rate prior │
          │ fleet mix      │  │ _select_*  │  │ gate affinity    │
          │                │  │ _generate_ │  │ hourly scaling   │
          └───────┬────────┘  │ delay      │  └──────────────────┘
                  │           └─────┬──────┘
                  │                 │
       ┌──────────▼─────┐   ┌──────▼──────────┐
       │  flight_service │   │  data_generator  │
       │  (API: /flights)│   │  (Lakebase +     │
       │                 │   │   FIDS schedule)  │
       └─────────────────┘   └──────────────────┘
```

**Both paths converge on the same profile data.** A flight generated for the 2D/3D map at SFO will pick United ~59% of the time, and a flight generated for the FIDS schedule board at SFO will also pick United ~59% of the time. The demo and simulation are statistically consistent.

---

## 5. File Inventory

### Source Code
| File | Lines | Purpose |
|------|-------|---------|
| `src/calibration/profile.py` | ~300 | AirportProfile dataclass, loader, fallback builder, IATA↔ICAO mapping |
| `src/calibration/bts_ingest.py` | ~580 | BTS CSV + DB28 pipe-delimited parsers, carrier code mappings |
| `src/calibration/known_profiles.py` | ~900 | Hand-researched stats for 33 airports |
| `src/calibration/profile_builder.py` | ~170 | Orchestrator: data source priority, enrichment, profile building |
| `src/calibration/ourairports_ingest.py` | ~100 | OurAirports CSV parser (airports + runways) |
| `src/calibration/opensky_ingest.py` | ~80 | OpenSky historical API client (rate-limited) |

### Data Files
| Path | Size | Contents |
|------|------|----------|
| `data/calibration/profiles/` | 33 JSON files | Built profiles for all airports |
| `data/calibration/download_manual/` | ~90MB | 10 BTS DB28 domestic segment zips (2024–2025) |
| `data/calibration/raw/airports.csv` | 12MB | OurAirports: 84,811 airports worldwide |
| `data/calibration/raw/runways.csv` | 3.8MB | OurAirports: runway data for 40,657 airports |

### Tests
| File | Tests | Coverage |
|------|-------|----------|
| `tests/test_calibration.py` | 43 | Profile CRUD, loader fallback chain, BTS parsing, generation integration, builder pipeline |

# Phase 28: Calibrate, Not Fabricate — Real-Data-Driven Synthetic Flight Generation

## Goal

Replace fabricated distributions with airport-specific statistical profiles learned from real data. The synthetic generator still produces fake flights, but their statistical properties (airline shares, route frequencies, hourly patterns, delay rates, fleet mix) match reality.

## Status: Plan — Not Started

---

## Context

Every parameter in the synthetic flight generator (`schedule_generator.py`, `fallback.py`, simulation `engine.py`) is currently hardcoded guesswork:

| Parameter | Current | Reality |
|-----------|---------|---------|
| Airline mix | Fixed weights (UAL 35%, DAL 15%...) regardless of airport | UAL is 46% at SFO, 0% at LHR |
| Traffic profiles | 4 generic patterns chosen by runway count | Each airport has unique hourly shape |
| Routes | 70% domestic / 30% international, uniform random | SFO→LAX is 12% of traffic, SFO→NRT is 0.3% |
| Fleet | airline → aircraft type dict, no route consideration | UAL flies B738 to LAX, B777 to NRT |
| Delays | Flat 15% rate with arbitrary code weights | SFO: 22%, JFK: 28%, DXB: 8% |
| Gate assignments | Random from OSM gates | Airlines have terminal affinity |
| ML models | Rule-based heuristics pretending to be trained models | Should use calibrated priors |

---

## Architecture: Airport Statistical Profile

### Core Concept — `AirportProfile`

A single JSON artifact per airport containing learned distributions:

```python
@dataclass
class AirportProfile:
    icao_code: str           # e.g., "KSFO"
    iata_code: str           # e.g., "SFO"

    # Airline market share: {"UAL": 0.46, "SWA": 0.12, "DAL": 0.08, ...}
    airline_shares: dict[str, float]

    # Route frequencies: {"LAX": 0.12, "ORD": 0.08, "JFK": 0.06, ...}
    domestic_route_shares: dict[str, float]
    international_route_shares: dict[str, float]
    domestic_ratio: float    # e.g., 0.72 for SFO

    # Fleet mix per airline: {"UAL": {"B738": 0.35, "A320": 0.25, ...}, ...}
    fleet_mix: dict[str, dict[str, float]]

    # Hourly traffic profile: 24-element list of relative weights
    hourly_profile: list[float]

    # Delay statistics per airport
    delay_rate: float        # e.g., 0.22 for SFO
    delay_distribution: dict[str, float]  # delay code → weight
    mean_delay_minutes: float

    # Metadata
    data_source: str         # "BTS_T100" / "OpenSky" / "OurAirports" / "fallback"
    profile_date: str        # when profile was built
    sample_size: int         # flights used to build profile
```

---

## Data Sources (priority order)

| Source | Coverage | Data | Access |
|--------|----------|------|--------|
| **BTS T-100 Segment Data** | US airports | Airline share, routes, aircraft types, monthly volumes | Free bulk CSV from transtats.bts.gov (~50MB/year) |
| **BTS On-Time Performance** | US airports | Delay rates, cause breakdown, hourly patterns | Free bulk CSV |
| **OurAirports** | Global | Airport metadata, runways, lat/lon, elevation | Free CSV at ourairports.com/data/ |
| **OpenSky Network** | Global | Actual flight tracks, callsigns, airline mix | Free historical API (rate-limited ~400 calls/day) |
| **Fallback** | All | Current hardcoded distributions | Always works |

---

## Profile Training Pipeline

```
scripts/build_airport_profiles.py

1. Download raw data (BTS CSVs, OurAirports CSVs)
   └─ Cached in data/calibration/raw/

2. For each target airport:
   a. Extract airline market share from T-100 departures
   b. Extract route frequencies from T-100 segments
   c. Extract fleet mix from T-100 aircraft types
   d. Extract delay stats from On-Time Performance
   e. Extract hourly profile from departure/arrival times
   f. For non-US airports: query OpenSky or use fallback

3. Normalize distributions (ensure they sum to 1.0)

4. Save profile to data/calibration/profiles/{ICAO}.json

5. Persist to Unity Catalog table for Databricks access
   (airport_profiles table)
```

Training is **OFFLINE** — run once as a script, produces static profile files. No real-time API calls during simulation or app serving.

---

## How Profiles Are Used (Generation Flow)

**Current flow:**
```
SimulationConfig → engine._generate_schedule()
  → schedule_generator._select_airline() → HARDCODED WEIGHTS
  → schedule_generator._select_destination() → RANDOM CHOICE
  → schedule_generator._select_aircraft() → HARDCODED DICT
```

**New flow:**
```
SimulationConfig → engine._generate_schedule()
  → AirportProfileLoader.get_profile("SFO")
      ↓
  AirportProfile for SFO
  (airline_shares, route_shares, fleet_mix, ...)
      ↓
  schedule_generator._select_airline(profile)
  schedule_generator._select_destination(profile)
  schedule_generator._select_aircraft(profile)
  schedule_generator._generate_delay(profile)
  TRAFFIC_PROFILES dynamically from profile.hourly_profile
```

**Key design principle:** The `AirportProfile` is a pure data object — no API calls, no model inference. The generator functions just sample from its distributions instead of hardcoded dicts.

---

## Files to Create

| File | Purpose |
|------|---------|
| `src/calibration/__init__.py` | Package init |
| `src/calibration/profile.py` | `AirportProfile` dataclass + `AirportProfileLoader` (loads from JSON/Unity Catalog, falls back to hardcoded) |
| `src/calibration/bts_ingest.py` | Parse BTS T-100 and On-Time CSVs into per-airport statistics |
| `src/calibration/opensky_ingest.py` | Query OpenSky API for non-US airports |
| `src/calibration/ourairports_ingest.py` | Parse OurAirports CSV for global airport metadata |
| `src/calibration/profile_builder.py` | Orchestrates ingestion → profile building for a list of airports |
| `scripts/build_airport_profiles.py` | CLI entry point: downloads data, builds profiles, optionally persists to UC |
| `scripts/download_calibration_data.py` | Downloads raw BTS/OurAirports CSVs to `data/calibration/raw/` |
| `data/calibration/profiles/` | Directory for generated profile JSONs |
| `tests/test_calibration.py` | Tests for profile loading, fallback, generation integration |

## Files Modified

| File | Change |
|------|--------|
| `src/ingestion/schedule_generator.py` | Replace hardcoded `AIRLINES`, `DOMESTIC_AIRPORTS`, `INTERNATIONAL_AIRPORTS`, `DELAY_CODES`, `TRAFFIC_PROFILES` with profile-driven sampling. Add profile parameter to all `_select_*` functions. Keep hardcoded values as fallback when no profile loaded. |
| `src/simulation/engine.py` | Load `AirportProfile` in `__init__`, pass to `_generate_schedule()`. Profile replaces `set_traffic_airport()` call. |
| `src/simulation/config.py` | Add optional `calibration_profile` field to `SimulationConfig` |
| `src/ml/delay_model.py` | Accept airport profile for calibrated base delay rates instead of rule-based heuristics |
| `src/ml/training.py` | Train delay model using calibrated distributions as priors |
| `databricks.yml` | Add `data/calibration/profiles/` to sync includes |

---

## Persistence (Unity Catalog)

New table: `airport_profiles`

```sql
CREATE TABLE IF NOT EXISTS {catalog}.{schema}.airport_profiles (
    icao_code STRING NOT NULL,
    iata_code STRING,
    profile_json STRING,        -- Full AirportProfile as JSON
    data_source STRING,
    sample_size INT,
    profile_date TIMESTAMP,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

**`AirportProfileLoader` loading order:**
1. Local JSON file (`data/calibration/profiles/{ICAO}.json`)
2. Unity Catalog table (when running on Databricks)
3. Hardcoded fallback (current distributions, always works)

---

## Implementation Phases

### Sub-phase 1: Profile Data Structure + Fallback Profiles

- Create `src/calibration/profile.py` with `AirportProfile` dataclass
- Create `AirportProfileLoader` with JSON file loading + hardcoded fallback
- Build fallback profiles for all 10 simulation airports from current hardcoded values
- No real data yet — just the infrastructure and identical behavior to today

### Sub-phase 2: Wire Profile into Generator

- Modify `schedule_generator.py` to accept and use `AirportProfile`
- Modify `engine.py` to load profile and pass through
- All `_select_*` functions gain `profile: AirportProfile | None` parameter
- When profile is `None` → existing hardcoded behavior (backward compatible)
- Tests pass with identical behavior using fallback profiles

### Sub-phase 3: BTS Data Ingestion (US airports)

- `scripts/download_calibration_data.py` — download T-100 and On-Time CSVs
- `src/calibration/bts_ingest.py` — parse CSVs, extract per-airport stats
- Build real profiles for SFO, JFK, GRU (US origins/destinations)
- Validate: run simulation, compare summary stats to BTS actuals

### Sub-phase 4: International Airport Profiles

- `src/calibration/opensky_ingest.py` — query OpenSky for LHR, FRA, DXB, NRT, SIN, SYD, JNB
- `src/calibration/ourairports_ingest.py` — supplement with OurAirports metadata
- Build profiles for all 10 airports
- `scripts/build_airport_profiles.py` — full pipeline CLI

### Sub-phase 5: ML Model Calibration

- Update `DelayPredictor` to use profile delay rates as priors
- Update `GateRecommender` to consider airline-gate affinity from profiles
- Update `CongestionPredictor` with calibrated hourly patterns
- Retrain models with calibrated synthetic data (better training signal)

### Sub-phase 6: Unity Catalog Persistence + Databricks Integration

- Add `airport_profiles` table to persistence layer
- Profile loader checks UC table when running on Databricks
- `build_airport_profiles.py` can persist directly to UC
- Add Databricks notebook for profile building/refresh

---

## Verification

1. **Unit tests:** Profile loading, fallback behavior, distribution sampling
2. **Integration test:** Run SFO simulation with BTS-calibrated profile, verify:
   - United Airlines share is ~46% (real) not 35% (hardcoded)
   - Top routes match BTS top-10 for SFO
   - Delay rate matches BTS on-time stats (~22% for SFO)
   - Hourly pattern shows realistic dual-peak for US airports
3. **Comparison report:** Script that runs simulation twice (fallback vs calibrated) and compares summary statistics side by side
4. **Existing tests pass:** All ~1058 Python + 635 frontend tests remain green (backward compatible fallback)

---

## What This Does NOT Change

- Flight state machine (phases, transitions, separation)
- Trajectory generation (waypoints, approach paths)
- Scenario system (weather, disruptions)
- OSM airport geometry
- 3D/2D visualization
- Baggage/GSE models
- API endpoints

---

## Estimated Scope

- **New files:** 10 (calibration package + scripts + tests)
- **Modified files:** 6 (`schedule_generator.py`, `engine.py`, `config.py`, `delay_model.py`, `training.py`, `databricks.yml`)
- **Lines:** ~1500-2000 new code + ~300 tests
- **External data:** BTS CSVs (~100MB download), OurAirports (~5MB), OpenSky API calls (~50 per airport)
- **Risk:** Medium — BTS CSV format may change between years; OpenSky rate limits may slow international profile building. Fallback ensures the system always works even without real data.

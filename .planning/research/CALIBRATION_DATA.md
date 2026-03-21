# Calibration Data Acquisition for Non-US Airports

## Problem Statement

When a user activates a non-US airport that is NOT in `known_profiles.py` (the 33 hand-researched airports), it falls back to `_build_fallback_profile()` which produces a **US-centric generic profile** — UAL/DAL/AAL/SWA airlines, US domestic routes (LAX/ORD/DFW), US dual-peak hourly pattern, uniform fleet mix. This is clearly wrong for airports like Munich (MUC), Istanbul (IST), or Bangkok (BKK — which is now in known_profiles but illustrates the pattern).

**Goal:** Automatically acquire real calibration data when a non-US airport is activated for the first time, so synthetic data generation produces realistic airline mixes, routes, fleet types, and traffic patterns without requiring hand-research.

## Current Calibration Architecture

### AirportProfile Fields (from `src/calibration/profile.py`)

| Field | Type | Description | US Source | Intl Source |
|-------|------|-------------|-----------|-------------|
| `airline_shares` | `dict[str, float]` | Carrier → market share | BTS T-100 | OpenSky (callsigns) |
| `domestic_route_shares` | `dict[str, float]` | Dest IATA → share | BTS T-100 | **MISSING** |
| `international_route_shares` | `dict[str, float]` | Dest IATA → share | BTS T-100 Intl | OpenSky (estArrivalAirport) |
| `domestic_ratio` | `float` | Fraction domestic | BTS T-100 | **MISSING** |
| `fleet_mix` | `dict[str, dict[str, float]]` | Airline → {type: share} | BTS T-100 (aircraft_type) | **MISSING** |
| `hourly_profile` | `list[float]` (24) | Relative traffic by hour | BTS On-Time | OpenSky (firstSeen/lastSeen) |
| `delay_rate` | `float` | Fraction delayed | BTS On-Time | **MISSING** |
| `delay_distribution` | `dict[str, float]` | IATA delay code → weight | BTS On-Time | **MISSING** |
| `mean_delay_minutes` | `float` | Average delay | BTS On-Time | **MISSING** |
| `data_source` | `str` | Provenance tag | "BTS" / "BTS_DB28" | "OpenSky" |
| `sample_size` | `int` | Number of flights | from CSV rows | from API results |

### Profile Loading Chain (`AirportProfileLoader.get_profile()`)

```
1. In-memory cache
2. Local JSON file (data/calibration/profiles/{ICAO}.json)
3. known_profiles.py (33 hand-researched airports)
4. Unity Catalog table (airport_profiles, when on Databricks)
5. Fallback — generic US-centric profile ← THE PROBLEM
```

### What Works Today

| Source | Coverage | Fields Provided | Gaps |
|--------|----------|----------------|------|
| **BTS T-100** | US airports only | airline shares, routes (dom+intl), fleet mix | No hourly, no delays |
| **BTS On-Time** | US airports only | hourly profile, delay rate/distribution/mean | No airline shares, no routes |
| **BTS DB28 PREZIP** | US airports only | Same as T-100 but pipe-delimited ZIP | Same gaps |
| **OpenSky API** | Global (ICAO) | airline shares (callsign), hourly (UTC), routes (dest ICAO) | No fleet mix, no delays, no dom/intl split, UTC not local time |
| **OurAirports** | Global | Metadata only (coords, elevation, type, country, runways) | No traffic data |
| **known_profiles.py** | 33 airports (21 US + 12 intl) | All fields (hand-researched) | Static, doesn't scale |

## Available Free Data Sources for International Airports

### 1. OpenSky Network API (already implemented)

- **URL:** `https://opensky-network.org/api`
- **Coverage:** Global, any ICAO-coded airport
- **Rate limit:** ~400 requests/day (free), higher with auth
- **Data window:** 1-hour chunks, up to 30 days back (free tier)
- **Provides:**
  - Airline shares from callsign prefixes (3-letter ICAO codes)
  - Route frequencies (estArrivalAirport / estDepartureAirport)
  - Hourly traffic pattern (from firstSeen/lastSeen timestamps, **in UTC**)
- **Missing:**
  - Aircraft type (not in free tier; Impala SQL has `typecode` but requires account)
  - Delay data
  - Domestic vs international classification
- **Current implementation:** `src/calibration/opensky_ingest.py` — works but gaps filled with defaults

### 2. AviationStack API

- **URL:** `https://aviationstack.com/`
- **Free tier:** 100 requests/month, real-time + historical flight data
- **Provides:**
  - Airline ICAO/IATA codes
  - Aircraft type (ICAO designator)
  - Scheduled vs actual times → **delay computation possible**
  - Origin/destination with domestic/intl classification
  - Terminal/gate assignments
- **Missing:** Hourly aggregates (need to build from individual flights)
- **Limitation:** 100 req/month free is very limited. 1 request = 1 page of results.

### 3. AeroDataBox (RapidAPI)

- **URL:** `https://rapidapi.com/aedbx-aedbx/api/aerodatabox`
- **Free tier:** 150 requests/month
- **Provides:**
  - Flight schedules for any airport (departures/arrivals by date)
  - Aircraft type code, airline, origin/destination
  - Scheduled/actual times
- **Missing:** Historical aggregates (need to sample across dates)
- **Limitation:** 150 req/month. Each request = 1 airport + 1 time window.

### 4. Eurocontrol STATFOR (European airports)

- **URL:** `https://www.eurocontrol.int/dashboard/rnd-data-archive`
- **Coverage:** European airports
- **Provides:**
  - Monthly/annual traffic by airport
  - Delay statistics (ATFM delays)
  - Airport pair flows
- **Access:** Free download but requires registration. Data is aggregated (not per-flight).

### 5. OAG (Schedules)

- **URL:** `https://www.oag.com/`
- **Coverage:** Global airline schedules
- **Provides:** Most comprehensive airline schedule data
- **Access:** Commercial only. No free tier.

### 6. FlightRadar24 / FlightAware

- **No free API** suitable for bulk airport profiling.

### 7. Wikipedia / Airport Annual Reports

- **Coverage:** Top 200+ airports worldwide
- **Provides:** Annual passenger counts, airline lists, route lists, domestic/intl splits
- **Access:** Free but unstructured. Requires scraping or manual research.
- **This is what `known_profiles.py` uses today** — doesn't scale.

### 8. Airline Route Maps (public)

- Airlines publish route maps showing their destinations from each hub.
- Can derive airline_shares and route_shares for hub airports.
- Unstructured, not automatable.

## Recommended Approach: Multi-Source Auto-Calibration

### Strategy: OpenSky + Heuristic Enrichment + Regional Templates

Since OpenSky is the only free, global, automatable source with sufficient rate limits, use it as the primary data source and **fill gaps with regional heuristics**.

### Architecture

```
User activates uncalibrated airport (e.g., EDDM / MUC)
    │
    ▼
AirportProfileLoader.get_profile("EDDM")
    │
    ├─ Cache? No
    ├─ Local JSON? No
    ├─ known_profiles.py? No
    ├─ Unity Catalog? No
    │
    ▼
NEW: Auto-calibrate pipeline (async, non-blocking)
    │
    ├─ 1. OurAirports metadata → country, continent, airport type
    ├─ 2. OpenSky 7-day query → airline shares, routes, hourly (UTC→local)
    ├─ 3. Regional template → domestic_ratio, delay stats, fleet mix heuristics
    ├─ 4. Fleet mix inference → from airline identity + region
    ├─ 5. Build AirportProfile → save to JSON + cache
    │
    ▼
Profile available for synthetic generation
```

### Step-by-Step

#### Step 1: Airport Metadata (OurAirports)

Already implemented in `ourairports_ingest.py`. Download `airports.csv` once (or bundle a snapshot). Gives:
- Country code → determines region
- Airport type (large_airport, medium_airport) → scale traffic volumes
- Coordinates → timezone inference for UTC→local hourly conversion

#### Step 2: OpenSky Traffic Data

Already implemented in `opensky_ingest.py`. Query 7 days of departures + arrivals. Gives:
- `airline_shares` from callsign prefix extraction
- `international_route_shares` from estArrivalAirport
- `hourly_profile` from firstSeen/lastSeen (needs UTC→local timezone conversion)

**Improvement needed:** Convert hourly timestamps from UTC to airport local time using `timezonefinder` or a lookup table. Currently `hourly_profile` is in UTC, which is wrong for non-UTC airports (e.g., Tokyo hourly pattern would be shifted 9 hours).

#### Step 3: Regional Template

Fill fields that OpenSky cannot provide using **regional templates** derived from the known airports in each region:

```python
REGIONAL_TEMPLATES = {
    "europe_west": {
        "domestic_ratio": 0.15,  # avg of LHR(0.05), CDG(0.15), FRA(0.10), AMS(0.05)
        "delay_rate": 0.18,
        "mean_delay_minutes": 22.0,
        "delay_distribution": {"81": 0.20, "68": 0.18, "71": 0.16, ...},
    },
    "europe_south": {
        "domestic_ratio": 0.35,  # avg of ATH(0.35), FCO(0.35), MAD(0.40)
        "delay_rate": 0.18,
        "mean_delay_minutes": 21.0,
        ...
    },
    "middle_east": {
        "domestic_ratio": 0.02,  # avg of DXB(0.02), AUH(0.02)
        "delay_rate": 0.11,
        "mean_delay_minutes": 17.0,
        ...
    },
    "east_asia": {
        "domestic_ratio": 0.40,  # avg of NRT(0.15), HND(0.70), PEK(0.70), ICN(0.10)
        "delay_rate": 0.13,
        "mean_delay_minutes": 18.0,
        ...
    },
    "southeast_asia": {
        "domestic_ratio": 0.20,  # avg of SIN(0.02), BKK(0.35)
        "delay_rate": 0.12,
        "mean_delay_minutes": 17.0,
        ...
    },
    "south_america": {
        "domestic_ratio": 0.55,  # from GRU(0.60)
        "delay_rate": 0.22,
        "mean_delay_minutes": 28.0,
        ...
    },
    "africa": {
        "domestic_ratio": 0.42,  # avg of JNB(0.50), CMN(0.35)
        "delay_rate": 0.16,
        "mean_delay_minutes": 20.0,
        ...
    },
    "oceania": {
        "domestic_ratio": 0.55,  # from SYD(0.55)
        "delay_rate": 0.14,
        "mean_delay_minutes": 18.0,
        ...
    },
    "us_domestic": {
        "domestic_ratio": 0.82,  # avg of US airports
        "delay_rate": 0.20,
        "mean_delay_minutes": 24.0,
        ...
    },
}
```

**Country → region mapping** using OurAirports `iso_country` + `continent`:
- `continent=EU` + Western Europe countries → `europe_west`
- `continent=EU` + Southern Europe countries → `europe_south`
- Middle East country codes → `middle_east`
- etc.

#### Step 4: Fleet Mix Inference

OpenSky free tier doesn't provide aircraft type. Infer fleet mix from **airline identity + region**:

```python
# Known airline fleet profiles (top 10 aircraft types per carrier)
AIRLINE_FLEET_PROFILES = {
    "DLH": {"A320": 0.25, "A321": 0.20, "A350": 0.15, "B747": 0.10, "A330": 0.15, "B777": 0.15},
    "AFR": {"A320": 0.25, "A321": 0.20, "B777": 0.20, "A350": 0.15, "A330": 0.10, "B787": 0.10},
    "RYR": {"B738": 0.70, "B737": 0.30},
    "EZY": {"A320": 0.60, "A319": 0.25, "A321": 0.15},
    ...
}

# For unknown airlines, use region-based fleet defaults
REGIONAL_FLEET_DEFAULTS = {
    "europe_west": {"A320": 0.30, "A321": 0.20, "B738": 0.15, "B777": 0.10, "A330": 0.10, ...},
    "middle_east": {"B777": 0.30, "A380": 0.15, "B787": 0.20, "A350": 0.15, "A321": 0.10, ...},
    ...
}
```

For each airline in the OpenSky-derived `airline_shares`:
1. Look up in `AIRLINE_FLEET_PROFILES` → use if found
2. Else use the `REGIONAL_FLEET_DEFAULTS` for the airport's region

#### Step 5: Domestic/International Route Classification

OpenSky gives routes as ICAO destination codes. Classify using OurAirports country data:

```python
def classify_routes(airport_country: str, route_destinations: dict[str, float]):
    domestic = {}
    international = {}
    for dest_icao, share in route_destinations.items():
        dest_country = ourairports_lookup[dest_icao].country
        if dest_country == airport_country:
            domestic[dest_icao] = share
        else:
            international[dest_icao] = share
    # Convert ICAO to IATA for profile compatibility
    return iata_domestic, iata_international
```

This fills `domestic_route_shares`, `international_route_shares`, and derives `domestic_ratio`.

### Implementation Plan

#### New Files

| File | Purpose |
|------|---------|
| `src/calibration/regional_templates.py` | Regional delay/fleet/domestic_ratio templates |
| `src/calibration/airline_fleets.py` | Known airline fleet mix profiles (top 50 airlines) |
| `src/calibration/auto_calibrate.py` | Orchestrator: OpenSky + metadata + templates → profile |
| `src/calibration/timezone_util.py` | UTC→local hourly conversion using coordinates |

#### Modified Files

| File | Change |
|------|--------|
| `src/calibration/profile.py` | Add `region` field to AirportProfile |
| `src/calibration/profile_builder.py` | Add auto-calibrate as step between OpenSky and known_profiles |
| `src/calibration/opensky_ingest.py` | Add timezone-aware hourly conversion, add route country classification |
| `src/calibration/ourairports_ingest.py` | Add bundled airports.csv snapshot, add country→region mapping |

#### Integration with Airport Activation

In `routes.py` `_activate_airport_inner()`:

```python
# After airport switch succeeds, if profile was fallback, trigger auto-calibrate
if profile.data_source == "fallback":
    async def _auto_calibrate_background():
        from src.calibration.auto_calibrate import auto_calibrate_airport
        profile = await asyncio.to_thread(auto_calibrate_airport, icao_code)
        if profile:
            loader.update_cache(icao_code, profile)
            logger.info(f"Auto-calibrated {icao_code}: {profile.data_source}")
    asyncio.create_task(_auto_calibrate_background())
```

This is non-blocking — the airport loads immediately with fallback data, then upgrades to calibrated data in the background. Next flight generation cycle picks up the real profile.

### Priority & Effort

| Component | Priority | Effort | Impact |
|-----------|----------|--------|--------|
| Regional templates | P0 | Small | Eliminates US-centric fallback for all regions |
| UTC→local hourly fix | P0 | Small | Fixes shifted traffic patterns for non-UTC airports |
| Route dom/intl classification | P1 | Small | Enables domestic_ratio from OpenSky data |
| Airline fleet profiles | P1 | Medium | Gives realistic fleet mix for top 50 airlines |
| Auto-calibrate orchestrator | P1 | Medium | Ties everything together |
| Background activation hook | P2 | Small | Makes it seamless during airport switch |
| OurAirports bundled snapshot | P2 | Small | Avoids network call for metadata |

### Data Quality Comparison

| Airport | Current Fallback | After Auto-Calibrate |
|---------|-----------------|---------------------|
| MUC (Munich) | UAL 35%, DAL 15%, AAL 15% (wrong) | DLH ~55%, EWG ~8%, others (correct) |
| IST (Istanbul) | US domestic routes (wrong) | THY ~45%, PGT ~15%, European/ME routes (correct) |
| BOM (Mumbai) | US hourly pattern (wrong) | AIC ~25%, 6E ~20%, Indian domestic pattern (correct) |

### Constraints

- **OpenSky rate limit:** 400 req/day free. Each airport needs ~14 requests (7 days × 2 dep+arr). Max ~28 airports/day.
- **No fleet mix from OpenSky free tier.** Must rely on airline identity heuristics.
- **No delay data from any free global API.** Must use regional averages from known airports.
- **Timezone inference** needed for hourly patterns. Use `timezonefinder` library or a lat/lon→timezone lookup table.

### Bundled OurAirports Snapshot

To avoid network dependency, bundle a filtered snapshot of `airports.csv` (~1MB for large+medium airports). Include only fields needed: `ident`, `iata_code`, `name`, `latitude_deg`, `longitude_deg`, `iso_country`, `continent`, `type`. Filter to `type IN ('large_airport', 'medium_airport')` (~2,500 airports).

Store at: `data/calibration/ourairports_snapshot.csv`

### Testing Strategy

1. **Unit tests for regional template selection:** given country code, returns correct region
2. **Unit tests for fleet mix inference:** given airline code, returns known fleet or regional default
3. **Unit tests for route classification:** given routes + country, correctly splits dom/intl
4. **Unit tests for timezone conversion:** given lat/lon + UTC hours, returns local hours
5. **Integration test:** full auto_calibrate_airport() for a known airport (e.g., FRA), compare output against known_profiles.py values — airline shares should be within 20% tolerance
6. **Fallback safety:** if OpenSky is down, auto-calibrate returns None and fallback profile is used unchanged

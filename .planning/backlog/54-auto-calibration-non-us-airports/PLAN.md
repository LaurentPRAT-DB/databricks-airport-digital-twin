# Plan: Auto-Calibration for Non-US Airports

## Context

When a non-US airport not in `known_profiles.py` (33 hand-researched airports) is activated, it gets a US-centric fallback profile — UAL/DAL/AAL airlines, US routes, US traffic patterns. This produces obviously wrong synthetic data for airports like Munich (MUC), Istanbul (IST), or Mumbai (BOM). The goal is to automatically build realistic calibration profiles for any airport in the world using free data sources.

---

## New Files (4)

### 1. `src/calibration/regional_templates.py`

Regional delay/fleet/domestic_ratio templates derived from averaging the 33 known airports grouped by region.

- `REGION_TEMPLATES` dict: region name → `{domestic_ratio, delay_rate, mean_delay_minutes, delay_distribution, hourly_profile}`
- Regions: `europe_west`, `europe_south`, `middle_east`, `east_asia`, `southeast_asia`, `south_america`, `africa`, `oceania`, `north_america`, `central_america`
- `COUNTRY_TO_REGION` dict: ISO country code → region name (covers ~100 countries)
- `get_region(country_code: str) -> str` — lookup with fallback to `"europe_west"` as the most neutral default
- `get_regional_template(country_code: str) -> dict` — returns template for country

### 2. `src/calibration/airline_fleets.py`

Known fleet mix for ~50 major world airlines.

- `AIRLINE_FLEET` dict: 3-letter ICAO carrier code → `{aircraft_type: share}`
- Covers: DLH, AFR, KLM, BAW, RYR, EZY, WZZ, IBE, AZA, SWR, AUA, TAP, SAS, THY, UAE, ETD, QTR, SIA, CPA, QFA, ANA, JAL, KAL, AAR, EVA, THA, CCA, CES, CSN, AIC, IGO, RAM, SAA, TAM, GLO, AMX, VOI, AEE, AEA + US carriers already known
- `REGIONAL_FLEET_DEFAULTS` dict: region → generic fleet mix for unknown airlines in that region
- `get_fleet_mix(carrier_code: str, region: str) -> dict[str, float]` — lookup airline first, fall back to regional default

### 3. `src/calibration/timezone_util.py`

Lightweight UTC→local hour offset using airport coordinates. No new dependency — use a simple longitude-based approximation (1 hour per 15° longitude) refined by a small lookup table for common timezone exceptions (e.g., China is UTC+8 despite spanning 60° longitude, India is UTC+5:30).

- `TIMEZONE_OVERRIDES` dict: ISO country code → UTC offset in hours (for countries with non-standard timezone vs longitude)
- `estimate_utc_offset(lat: float, lon: float, country: str = "") -> float` — returns offset in hours
- `utc_to_local_hourly(hourly_utc: list[float], utc_offset: float) -> list[float]` — rotate the 24-element hourly profile by the offset

This avoids adding `timezonefinder` as a dependency (~50MB). The longitude approximation is accurate within ±1 hour for most airports, and the country override table handles the exceptions.

### 4. `src/calibration/auto_calibrate.py`

Orchestrator that combines OpenSky + OurAirports metadata + regional templates + fleet inference.

```python
def auto_calibrate_airport(icao_code: str, use_opensky: bool = True) -> AirportProfile | None:
```

Steps:
1. Load OurAirports metadata from `data/calibration/raw/airports.csv` — get country, coordinates
2. Determine region from country code via `regional_templates.get_region()`
3. If `use_opensky`: query OpenSky 7-day data → airline shares, routes, hourly (UTC)
4. Convert hourly UTC → local using `timezone_util`
5. Classify routes as domestic/international using OurAirports country data
6. Compute `domestic_ratio` from classified routes
7. Build fleet mix: for each airline in shares, look up `airline_fleets.get_fleet_mix()`
8. Fill delay stats from regional template
9. Merge: OpenSky data (airline shares, routes, hourly) + regional template (delays) + fleet inference
10. Save profile JSON to `data/calibration/profiles/{ICAO}.json`
11. Return the `AirportProfile`

Fallback: if OpenSky fails (rate limit, network), return a region-based profile with regional airline shares and generic routes — still much better than the US fallback.

---

## Modified Files (3)

### 5. `src/calibration/profile.py`

- Add `region: str = ""` field to `AirportProfile` dataclass (after `data_source`)
- Add method `update_cache(self, icao: str, profile: AirportProfile)` to `AirportProfileLoader` — allows background tasks to inject auto-calibrated profiles into the running loader

### 6. `src/calibration/opensky_ingest.py`

- In `build_profile_from_opensky()`: accept optional `utc_offset` param and apply timezone shift to hourly profile
- Export `query_departures` and `query_arrivals` for use by `auto_calibrate` (already exported)

### 7. `app/backend/api/routes.py`

After the existing ML retrain background task, add auto-calibrate background task:

```python
# Auto-calibrate if this airport has no real profile
profile_loader = get_model_registry()._profile_loader
current_profile = profile_loader.get_profile(icao_code)
if current_profile.data_source == "fallback":
    async def _auto_calibrate_background():
        from src.calibration.auto_calibrate import auto_calibrate_airport
        profile = await asyncio.to_thread(auto_calibrate_airport, icao_code, use_opensky=True)
        if profile:
            profile_loader.update_cache(icao_code, profile)
            # Retrain ML with calibrated profile
            registry.retrain(icao_code)
    asyncio.create_task(_auto_calibrate_background())
```

---

## NOT Changed

- `known_profiles.py` — untouched, remains the gold standard for known airports
- `profile_builder.py` — untouched, used for batch offline builds only
- No new pip dependencies

---

## Verification

1. `uv run pytest tests/ -v -k calibrat` — existing calibration tests still pass
2. New unit tests in `tests/test_auto_calibrate.py`:
   - `test_regional_template_selection` — country→region mapping
   - `test_airline_fleet_lookup` — known airline returns correct fleet
   - `test_timezone_offset` — longitude-based offset + country overrides
   - `test_utc_to_local_shift` — hourly profile rotation
   - `test_route_classification` — domestic/intl split from country data
   - `test_auto_calibrate_without_opensky` — region-only fallback produces non-US profile
   - `test_auto_calibrate_known_airport` — FRA auto-calibrate produces DLH-dominant profile
3. `uv run pytest tests/ -q` — full suite, no regressions

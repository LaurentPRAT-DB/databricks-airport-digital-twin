# Adding a New Airport — Configuration Checklist

When adding a new airport to the digital twin, several files need to be updated to ensure the airport gets the same level of configuration and synthetic data quality as existing airports. The system has two tiers of airport support:

- **Well-known airports** (currently 28): Appear in the UI dropdown, have curated profiles, pre-cached in Lakebase
- **Ad-hoc airports**: Any ICAO code typed into the custom input field; loaded on demand from OSM

This document covers what's needed to promote an airport to well-known status.

---

## Required Changes (7 files)

### 1. ICAO↔IATA Mapping — `app/backend/demo_config.py`

Add the airport to the `_ICAO_TO_IATA` dict. This mapping is used by the API layer for display names, schedule generation, and FIDS.

```python
_ICAO_TO_IATA = {
    ...
    "ZSPD": "PVG",  # Shanghai Pudong
}
```

**Without this:** US airports fall back to stripping the `K` prefix (KJFK→JFK), but international airports return the ICAO code as-is (ZSPD instead of PVG), breaking schedule display and route generation.

### 2. ICAO↔IATA Mapping — `src/calibration/profile.py`

Add to both `_IATA_TO_ICAO` (and its inverse `_ICAO_TO_IATA` is auto-generated). This mapping is used by the calibration system and flight origin/destination selection.

```python
_IATA_TO_ICAO: dict[str, str] = {
    ...
    "PVG": "ZSPD",
}
```

**Without this:** The airport falls back to generic calibration profiles with US-centric airline distributions.

### 3. Airport Dropdown — `app/backend/api/routes.py`

Add to `WELL_KNOWN_AIRPORT_INFO` dict (around line 130). This populates the frontend airport selector dropdown.

```python
WELL_KNOWN_AIRPORT_INFO: dict[str, dict] = {
    ...
    "ZSPD": {"iata": "PVG", "name": "Shanghai Pudong International", "city": "Shanghai, CN", "region": "Asia-Pacific"},
}
```

**Fields:** `iata` (3-letter), `name` (display name), `city` (city + country), `region` (one of: Americas, Europe, Middle East, Asia-Pacific, Africa — used for grouping in the dropdown).

**Without this:** The airport won't appear in the dropdown. Users can still activate it via the custom ICAO input field.

### 4. OSM Preload Notebook — `databricks/notebooks/preload_osm_airports.py`

Add to `WELL_KNOWN_AIRPORTS` dict (around line 50). This notebook pre-fetches OSM geometry into Unity Catalog and Lakebase so the airport loads in <3s instead of 10-25s.

```python
WELL_KNOWN_AIRPORTS = {
    ...
    "ZSPD": {"iata": "PVG", "name": "Shanghai Pudong International"},
}
```

**After adding:** Run the preload job once: `databricks bundle run osm_preload --target dev`

**Without this:** The airport loads from OSM Overpass API on first visit (10-25s), then gets cached in Lakebase. Not broken, just slow on first access.

### 5. Weather Parameters — `src/ingestion/weather_generator.py`

Add to `STATION_WEATHER_PARAMS` dict (around line 207). This provides realistic base temperature and prevailing wind direction for synthetic METAR/TAF generation.

```python
STATION_WEATHER_PARAMS: dict[str, dict[str, int]] = {
    ...
    "ZSPD": {"base_temp": 17, "base_wind_dir": 150},  # Shanghai
}
```

**Values:** `base_temp` is annual average temperature in °C, `base_wind_dir` is prevailing wind direction in degrees. Look up from historical METAR data or Wikipedia climate section.

**Without this:** Weather defaults to SFO's parameters (15°C, 280° wind) — wrong but functional.

### 6. Country Domestic Airports — `src/ingestion/schedule_generator.py`

If the airport is in a country not yet represented, add the country's domestic airports to `COUNTRY_DOMESTIC_AIRPORTS` (around line 85). This enables realistic domestic route generation.

```python
COUNTRY_DOMESTIC_AIRPORTS: dict[str, list[str]] = {
    ...
    "CN": ["PEK", "CAN", "CTU", "SHA", "SZX", "KMG", "XIY", "HGH"],
}
```

Also add the airport to `AIRPORT_COUNTRY` (around line 105) if it's an international hub:

```python
AIRPORT_COUNTRY: dict[str, str] = {
    ...
    "PVG": "CN", "PEK": "CN",
}
```

**Without this:** The airport uses the global distance-based algorithm from `airport_table.py` (1,180 airports), which works well. Country-specific domestic routes are a refinement.

---

## Optional but Recommended (2 files)

### 7. Calibration Profile — `src/calibration/known_profiles.py`

Add a hand-researched `AirportProfile` with real airline shares, route distributions, fleet mix, and hourly traffic profile. This is the most impactful single change for data realism.

```python
def _pvg() -> AirportProfile:
    return AirportProfile(
        icao_code="ZSPD", iata_code="PVG",
        airline_shares={
            "CES": 0.35,  # China Eastern (hub)
            "CSN": 0.15,  # China Southern
            "CCA": 0.12,  # Air China
            "CSH": 0.08,  # Shanghai Airlines
            ...
        },
        domestic_route_shares={
            "PEK": 0.12, "CAN": 0.10, "CTU": 0.08, ...
        },
        international_route_shares={
            "NRT": 0.10, "ICN": 0.08, "HKG": 0.07, ...
        },
        domestic_ratio=0.65,
        fleet_mix={
            "CES": {"A320": 0.35, "B738": 0.25, "A321": 0.20, "B789": 0.10, "A359": 0.10},
            ...
        },
        hourly_profile=[...],  # 24 values summing to ~1.0
        avg_daily_movements=1400,
        avg_delay_minutes=22.0,
        on_time_percentage=0.68,
        domestic_delay_minutes=18.0,
        international_delay_minutes=28.0,
    )
```

Then register in `_KNOWN_PROFILES` at the bottom of the file:

```python
_KNOWN_PROFILES: dict[str, callable] = {
    ...
    "PVG": _pvg,
}
```

**Sources for research:** FAA ATADS (US), Eurocontrol (Europe), CAAC statistics (China), Wikipedia airport article "Airlines and destinations" section, airline investor presentations, OAG public summaries.

**Without this:** The airport uses the generic fallback profile — equal airline distribution, US-centric route shares, default hourly curve. Functional but unrealistic.

### 8. Calibration JSON Profile — `data/calibration/profiles/{ICAO}.json`

If you have BTS/OpenSky CSV data, run the profile builder to generate a data-driven profile:

```bash
uv run python scripts/build_airport_profiles.py --airports PVG
```

This creates `data/calibration/profiles/ZSPD.json` with statistically-derived values. The known_profiles.py hand-researched values take precedence if both exist.

---

## What Happens Automatically (No Changes Needed)

These features work for any ICAO code without configuration:

| Feature | Source | How it works |
|---------|--------|-------------|
| **OSM geometry** (gates, terminals, taxiways) | Overpass API | Fetched on first activation, cached in Lakebase |
| **Airport center coordinates** | OSM centroid or gate/terminal geo average | Computed from loaded config |
| **Origin/destination airports** | `airport_table.py` (1,180 airports) | Distance-based selection from OurAirports data |
| **Approach/departure bearings** | `airport_table.py` | Computed from origin/destination coordinates |
| **ML models** (delay, gate, congestion) | `src/ml/` | Retrained per-airport on activation |
| **Baggage simulation** | `data_generator_service.py` | Generated from flight data, airport-agnostic |
| **GSE simulation** | `data_generator_service.py` | Generated from gate positions, airport-agnostic |
| **WebSocket real-time updates** | `websocket.py` | Delta compression, airport-agnostic |
| **3D visualization** | Frontend | Uses gate/terminal geo from config |
| **2D map overlay** | Frontend | Uses OSM polygons/polylines |

---

## Verification After Adding

1. **Run tests:** `uv run pytest tests/ -k "calibration or demo_config or airport" -x`
2. **Deploy:** `cd app/frontend && npm run build && databricks bundle deploy --target dev`
3. **Run preload:** `databricks bundle run osm_preload --target dev` (if added to preload list)
4. **Test activation:** Switch to the new airport in the UI, verify:
   - Loads in <3s (if preloaded) or <30s (first visit from OSM)
   - Gates and terminals render on 2D/3D maps
   - FIDS shows realistic airline names and flight numbers
   - Weather shows reasonable temperature for the region
   - Delays and congestion predictions are generated

---

## Summary Table

| File | Required? | Impact if missing |
|------|-----------|-------------------|
| `demo_config.py` — ICAO↔IATA | **Yes** | Wrong IATA code in schedules/FIDS |
| `profile.py` — IATA↔ICAO | **Yes** | Wrong code in calibration lookups |
| `routes.py` — WELL_KNOWN_AIRPORT_INFO | **Yes** | Not in dropdown (still works via custom input) |
| `preload_osm_airports.py` — WELL_KNOWN_AIRPORTS | **Yes** | Slow first load (10-25s instead of <3s) |
| `weather_generator.py` — STATION_WEATHER_PARAMS | **Yes** | Wrong temperature and wind for region |
| `schedule_generator.py` — COUNTRY/DOMESTIC | Recommended | Less realistic domestic route mix |
| `known_profiles.py` — AirportProfile | Recommended | Generic airline/route distributions |
| `data/calibration/profiles/` — JSON | Optional | Only needed if BTS/OpenSky data available |

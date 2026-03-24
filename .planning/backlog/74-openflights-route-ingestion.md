# OpenFlights Route Data Ingestion for Accurate FIDS

## Context

FIDS (Flight Information Display System) shows origin/destination for each flight. Currently, 42 airports have hand-researched route profiles
in known_profiles.py. The remaining ~1,140 airports in airport_table.py fall back to uniform random selection from nearby/far airports —
producing unrealistic route mixes. OpenFlights provides a free, public routes.dat CSV with ~67,000 real airline routes worldwide, which can
auto-populate domestic_route_shares, international_route_shares, and airline_shares for any airport.

## Approach

### 1. Create `src/calibration/openflights_ingest.py` — OpenFlights route data ingester

Download & parse routes.dat:
- URL: https://raw.githubusercontent.com/jpatokal/openflights/master/data/routes.dat
- Format: CSV (no header), fields: airline, airline_id, src_airport, src_id, dst_airport, dst_id, codeshare, stops, equipment
- Download to data/calibration/raw/openflights_routes.dat (cache locally)
- Parse into list of (airline_icao, src_iata, dst_iata) tuples
- Filter: skip rows with \N (missing data), skip codeshares, keep only IATA-coded airports

Build per-airport route profile:
- For a given IATA code, filter routes where src_airport == iata or dst_airport == iata
- Count destinations by frequency → route_shares dict
- Split into domestic vs international using airport_table.AIRPORTS country codes
- Compute domestic_ratio from the counts
- Count airlines by frequency → airline_shares dict
- Parse equipment field to approximate fleet_mix per airline

Function signature:
```python
def build_profile_from_openflights(
    iata: str,
    routes_path: Path | None = None,  # auto-download if missing
    download: bool = True,
) -> AirportProfile | None
```

Also download airlines.dat:
- URL: https://raw.githubusercontent.com/jpatokal/openflights/master/data/airlines.dat
- Maps airline IDs to ICAO codes and names
- Needed to resolve airline codes in routes.dat (some use IATA 2-letter codes)

### 2. Wire into `profile_builder.py` — add OpenFlights as data source

Insert OpenFlights as priority 2.5 (after BTS/CSV, before known profiles):

1. DB28 pipe-delimited zips (US, real BTS)
2. BTS CSV data (US)
3. **OpenFlights routes.dat** (worldwide, NEW)
4. Known hand-researched profiles (known_profiles.py)
5. Fallback (uniform distribution)

This means:
- US airports still prefer BTS real data when available
- International airports get real route data from OpenFlights instead of uniform fallback
- Known profiles still serve as fallback if OpenFlights has no data for an airport

### 3. Add CLI command to `scripts/build_airport_profiles.py`

Add `--source openflights` flag to force OpenFlights-only profile building. Also add `--all-airports` to process all 1,180 airports from airport_table.py (not just the 33 currently listed).

### 4. Auto-enrich at runtime in `AirportProfileLoader`

In `profile.py:AirportProfileLoader.get_profile()`, after the known-profiles check and before the fallback, try to build from OpenFlights data if available locally:

1. In-memory cache
2. Local JSON file
3. Known hand-researched profiles
4. **OpenFlights auto-build** (if routes.dat exists locally)
5. Unity Catalog
6. Fallback

### 5. Tests

New test file `tests/test_openflights_ingest.py`:
- Test CSV parsing with sample data (mock, no download)
- Test domestic/international split using country codes
- Test airline_shares normalization
- Test integration with profile_builder priority chain
- Test that generated profiles have non-empty route_shares

## Files to Modify

| File | Change |
|---|---|
| `src/calibration/openflights_ingest.py` | NEW — download, parse, build profiles |
| `src/calibration/profile_builder.py` | Add OpenFlights as data source in priority chain |
| `src/calibration/profile.py` | Add OpenFlights auto-build in AirportProfileLoader.get_profile() |
| `scripts/build_airport_profiles.py` | Add --source openflights and --all-airports flags |
| `tests/test_openflights_ingest.py` | NEW — unit tests |

## Key Reuse

- `airport_table.AIRPORTS` — country codes for domestic/international split
- `AirportProfile` dataclass — output format (no changes needed)
- `_iata_to_icao()` / `_icao_to_iata()` — code conversion
- Existing `schedule_generator._select_destination()` already consumes `domestic_route_shares` / `international_route_shares` — no FIDS changes needed

## Verification

1. `python scripts/build_airport_profiles.py --source openflights --airports RJTT,KJFK,KSFO` — builds 3 profiles
2. Check output JSON has realistic route shares (RJTT should show CTS, KIX, FUK as top domestic; KJFK should show LAX, SFO, ORD)
3. `uv run pytest tests/test_openflights_ingest.py -v` — unit tests pass
4. `uv run pytest tests/ -k calibration -v` — existing calibration tests still pass
5. Deploy and verify FIDS shows realistic origins/destinations for RJTT (should show domestic Japanese airports, not random US ones)

## Status: NOT YET IMPLEMENTED

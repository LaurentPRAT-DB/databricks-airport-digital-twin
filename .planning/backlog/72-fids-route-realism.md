# FIDS Route Realism — Implementation Plan

## Problem

The schedule generator (`src/ingestion/schedule_generator.py`) picks random IATA airport codes for origins/destinations, creating absurd combinations visible in the FIDS:
- Turkish Airlines flying domestic US (CVG→SFO)
- Lufthansa on San Antonio→SFO
- easyJet Luton→Heathrow (30-mile bus ride)
- Singapore Airlines from Chicago Midway to Tokyo Haneda
- E175 regional jets on intercontinental routes

This is the most visible data quality issue — anyone familiar with aviation will immediately notice.

## Approach: Airline Route Tables

### Step 1: Create route data structure

File: `src/ingestion/airline_routes.py`

```python
AIRLINE_ROUTES: dict[str, dict] = {
    "UAL": {
        "hubs": ["SFO", "ORD", "EWR", "IAH", "IAD", "DEN", "LAX"],
        "domestic": ["LAX", "SEA", "JFK", "BOS", "DFW", "ATL", "MIA", "PHX", "LAS", ...],
        "international": ["NRT", "HND", "LHR", "FRA", "CDG", "SYD", "PEK", "PVG", ...],
        "aircraft_map": {
            "domestic_short": ["B737", "B738", "A320", "A319"],
            "domestic_long": ["B738", "B739", "A321"],
            "international": ["B777", "B787", "B763"],
            "regional": ["E175", "CRJ9", "CRJ7"],
        },
        "max_regional_nm": 1500,
    },
    "ANA": {
        "hubs": ["HND", "NRT"],
        "domestic": ["CTS", "FUK", "KIX", "ITM", "OKA", "NGO", "HIJ", "KOJ", "SDJ", ...],
        "international": ["LAX", "SFO", "JFK", "ORD", "IAH", "LHR", "FRA", "CDG", ...],
        ...
    },
    # ... 20-30 major airlines
}
```

### Step 2: Modify schedule generator to use route tables

File: `src/ingestion/schedule_generator.py`

In `generate_daily_schedule()`:
1. When picking an origin for an arrival, look up the airline's route table
2. Filter to airports the airline actually serves from/to the current airport
3. Fall back to calibration profile routes if airline not in table
4. Cap regional jets to max 1500nm

### Step 3: Add airport-to-airline constraints

Don't generate easyJet at KSFO, Alaska Airlines at EGLL, etc. The airline selection should be weighted by the calibration profile, but the route selection should use route tables.

### Step 4: Validate with known profiles

Cross-reference `known_profiles.py` airline weights with route tables to ensure consistency.

## Effort Estimate

- Route data: ~2h (manually research top 20 airlines)
- Generator changes: ~1h
- Tests: ~1h
- Total: ~4h

## Files to Modify

1. `src/ingestion/airline_routes.py` (NEW) — Route tables
2. `src/ingestion/schedule_generator.py` — Use route tables
3. `tests/test_fids_accuracy.py` (or new) — Validate route realism

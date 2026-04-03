# Plan: Improve OpenSky Collector Defaults and Enrichment Strategies

**Status:** Backlog
**Date added:** 2026-04-03
**Depends on:** OpenSky Local Collector + Lakehouse Ingestion Pipeline
**Scope:** Collector defaults + aircraft type enrichment + multi-airport + airline extraction

---

## Context

The current `scripts/opensky_collector.py` uses minimal defaults (15s interval, 0=indefinite duration, single airport). For collecting ML-quality training data, we need:

- Longer default sessions (2h+ to capture full turnarounds)
- Aircraft type enrichment via OpenSky's free icao24→type database
- Multi-airport parallel collection support
- Better documentation of recommended collection strategies

## Changes to `scripts/opensky_collector.py`

### 1. Better Defaults for ML Data Collection

| Parameter | Current | New | Rationale |
|-----------|---------|-----|-----------|
| `--duration` | 0 (indefinite) | 7200 (2h) | Captures full turnarounds (30-90 min) |
| `--interval` | 15s | 10s | Higher temporal resolution for event inference |

### 2. Aircraft Type Enrichment from OpenSky Database

OpenSky provides a free CSV database: `https://opensky-network.org/datasets/metadata/aircraftDatabase.csv`

On collector startup:

- Download and cache the CSV locally (`data/opensky_raw/aircraft_db.csv`)
- Build an `icao24 → (typecode, registration)` lookup
- Enrich each state record with `aircraft_type` and `registration` fields before writing JSONL

This fills the currently empty `aircraft_type` field and enables aircraft-size-aware ML features.

### 3. Airline Code Extraction from Callsign

Already partially available (`callsign[:3]` is ICAO airline code). Formalize by adding an `airline_icao` field to each record, extracted from callsign.

### 4. Multi-Airport Collection Mode

Add `--airports` flag accepting comma-separated ICAO codes. The collector round-robins through airports, fetching each in sequence per interval. This builds a diverse training dataset from a single collection session.

When `--airports` is provided, the interval is split across airports (e.g., 3 airports with 10s interval = each airport fetched every 30s).

### 5. Collection Strategy Documentation

Add a header docstring section documenting recommended collection patterns for different use cases.

## Files to Modify

| File | Change |
|------|--------|
| `scripts/opensky_collector.py` | All changes above — defaults, aircraft DB enrichment, multi-airport, airline extraction |
| `databricks/notebooks/load_opensky_from_volume.py` | Add `aircraft_type`, `registration`, `airline_icao` to schema |

## Verification

1. `uv run python scripts/opensky_collector.py --airport LSGG --duration 60` — runs 1-minute test, verify `aircraft_type` populated
2. Check JSONL output has `aircraft_type`, `registration`, `airline_icao` fields
3. Multi-airport: `uv run python scripts/opensky_collector.py --airports LSGG,LFPG --duration 60`

---
phase: 01-data-foundation
plan: 01
subsystem: data-ingestion
tags: [api-client, circuit-breaker, synthetic-data, polling]
dependency-graph:
  requires: []
  provides: [opensky-client, circuit-breaker, fallback-generator, poll-job]
  affects: [landing-zone, dlt-bronze]
tech-stack:
  added: [requests, pydantic, tenacity, circuitbreaker, Faker]
  patterns: [circuit-breaker, retry-with-backoff, oauth2-client-credentials]
key-files:
  created:
    - pyproject.toml
    - src/ingestion/opensky_client.py
    - src/ingestion/circuit_breaker.py
    - src/ingestion/fallback.py
    - src/ingestion/poll_job.py
    - src/schemas/opensky.py
    - src/config/settings.py
    - tests/test_ingestion.py
    - tests/conftest.py
  modified: []
decisions:
  - Used pydantic for API response validation with field validators
  - Implemented custom circuit breaker (not decorator-based) for state visibility
  - OAuth2 client credentials flow with token caching in client instance
metrics:
  duration: 5 minutes
  completed: 2026-03-05
---

# Phase 1 Plan 01: Data Ingestion Layer Summary

OpenSky API client with OAuth2 authentication, retry logic (tenacity), circuit breaker for failover, and synthetic flight data generator for fallback. Polling job writes JSON to landing zone for downstream DLT consumption.

## What Was Built

### Core Components

1. **OpenSkyClient** (`src/ingestion/opensky_client.py`)
   - OAuth2 client credentials flow for authenticated API access
   - Retry decorator with exponential backoff (3 attempts, 2-10s wait)
   - Rate limit handling with RateLimitError exception
   - Bounding box queries to minimize API credit usage

2. **APICircuitBreaker** (`src/ingestion/circuit_breaker.py`)
   - Three states: closed, open, half-open
   - Opens after 5 consecutive failures
   - Transitions to half-open after 60s recovery timeout
   - Module-level singleton for shared state

3. **Synthetic Data Generator** (`src/ingestion/fallback.py`)
   - Generates realistic flight data matching OpenSky API format
   - Uses Faker for ICAO24 hex addresses
   - Callsign prefixes for major US airlines (UAL, DAL, AAL, etc.)
   - Positions constrained to bounding box

4. **Poll Job** (`src/ingestion/poll_job.py`)
   - Checks circuit breaker before API call
   - Falls back to synthetic data when circuit open
   - Writes JSON files with timestamp, source, and states
   - Main entrypoint for Databricks job scheduling

### Data Models

- **StateVector**: Pydantic model for 17-field aircraft state (position, velocity, altitude)
- **OpenSkyResponse**: API response wrapper with time and states list
- **Settings**: Configuration from environment variables (credentials, landing path, bbox)

## Test Coverage

9 tests in `tests/test_ingestion.py`:
- OpenSkyClient: API response parsing, retry behavior
- Fallback: Data structure validation, bbox constraints
- CircuitBreaker: State transitions, timeout recovery
- PollJob: File creation, source metadata

All tests pass with mocked API responses.

## Deviations from Plan

None - plan executed exactly as written.

## Integration Points

- **Output**: JSON files in landing zone (`/mnt/data/landing/*.json`)
- **Downstream**: DLT Bronze pipeline reads from landing zone with Auto Loader
- **Configuration**: Environment variables for credentials and paths

## Task Commits

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Project setup and test scaffolding | 9f21929 | pyproject.toml, tests/conftest.py, tests/test_ingestion.py |
| 2 | OpenSky API client with OAuth2 and retry | ce86dd4 | src/ingestion/opensky_client.py, src/schemas/opensky.py, src/config/settings.py |
| 3 | Circuit breaker and synthetic data fallback | 249cdd5 | src/ingestion/circuit_breaker.py, src/ingestion/fallback.py, src/ingestion/poll_job.py |

## Usage Example

```python
from src.ingestion.poll_job import poll_and_write
from src.config.settings import settings

# Poll API and write to landing zone
count = poll_and_write(
    landing_path=settings.LANDING_PATH,
    bbox=settings.SFO_BBOX,
)
print(f"Wrote {count} flight states")
```

## Self-Check: PASSED

All 9 files exist, all 3 commit hashes verified.

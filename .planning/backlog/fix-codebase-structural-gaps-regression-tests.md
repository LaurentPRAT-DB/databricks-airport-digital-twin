---
status: backlog
area: pipeline
related: []
---

# Fix Codebase Structural Gaps + Regression Tests

## Context

Knowledge graph analysis (`/graphify`) of `src/` + `app/` revealed 6 structural gaps where modules that should be connected share no types, use magic strings, or couple through private imports. These create silent runtime failure modes. This plan adds shared constants/types and regression tests to prevent drift.

## Scope — 6 fixes, priority order

### Fix 1: DLT Pipeline — shared table name constants

**Problem:** Bronze/Silver/Gold layers reference each other via magic table name strings (`dlt.read_stream("flights_bronze")`). Rename a table in one layer → silent runtime break.

**Files to modify:**
- `src/pipelines/__init__.py` — add table name constants
- `src/pipelines/bronze.py` — use constant for `name=`
- `src/pipelines/silver.py` — use constant for `name=` and `read_stream()`
- `src/pipelines/gold.py` — use constant for `name=` and `read_stream()`
- `src/pipelines/baggage_bronze.py` — same
- `src/pipelines/baggage_silver.py` — same
- `src/pipelines/baggage_gold.py` — same

**New test:** `tests/test_dlt_table_names.py`
- Verify every `dlt.read_stream(X)` call references a table name that matches a `dlt.table(name=X)` in another pipeline file
- Verify the constants in `__init__.py` match what's actually used in the pipeline files
- Verify the chain: bronze → silver → gold is intact for both flight and baggage pipelines

**Constants to add to `src/pipelines/__init__.py`:**
```python
# Flight pipeline table names
FLIGHTS_BRONZE = "flights_bronze"
FLIGHTS_SILVER = "flights_silver"
FLIGHT_STATUS_GOLD = "flight_status_gold"

# Baggage pipeline table names
BAGGAGE_EVENTS_BRONZE = "baggage_events_bronze"
BAGGAGE_EVENTS_SILVER = "baggage_events_silver"
BAGGAGE_STATUS_GOLD = "baggage_status_gold"
BAGGAGE_EVENTS_GOLD = "baggage_events_gold"

# Source tables (read by bronze layers from Unity Catalog)
LAKEBASE_FLIGHT_STATUS = "serverless_stable_3n0ihb_catalog.airport_digital_twin.flight_status_gold"
LAKEBASE_BAGGAGE_STATUS = "serverless_stable_3n0ihb_catalog.airport_digital_twin.baggage_status_gold"
```

---

### Fix 2: Weather types — shared Pydantic model

**Problem:** `weather_generator.py` (synthetic) and `metar_history.py` (real) produce similar weather dicts but share no types. Key differences found:
- Generator returns: `station`, `observation_time`, `clouds`, `altimeter_inhg`, `weather`, `raw_metar` (12 keys)
- History returns: `time`, `wind_speed_kts`, `wind_gust_kts`, `wind_direction`, `visibility_sm`, `flight_category`, `temperature_c`, `dewpoint_c`, `raw_metar` (9 keys)
- The history `_to_weather_snapshot()` deliberately produces a subset — but there's no validation they stay compatible

**Files to modify:**
- New: `src/ingestion/weather_types.py` — shared `WeatherSnapshot` Pydantic model (the common subset both must produce)
- `src/ingestion/weather_generator.py` — `generate_metar()` return dict must be a superset of `WeatherSnapshot`
- `app/backend/services/metar_history.py` — `_to_weather_snapshot()` return must match `WeatherSnapshot`

**New test:** `tests/test_weather_schema_compat.py`
- Import both `generate_metar` and the `WeatherSnapshot` model
- Validate that `generate_metar()` output contains all `WeatherSnapshot` fields
- Validate that `_to_weather_snapshot()` output matches `WeatherSnapshot`
- Test `flight_category` values are from the same enum in both paths

**WeatherSnapshot model (common fields both sources must provide):**
```python
from pydantic import BaseModel
from typing import Optional

class WeatherSnapshot(BaseModel):
    wind_speed_kts: int
    wind_gust_kts: Optional[int]
    wind_direction: int
    visibility_sm: float
    temperature_c: Optional[float]
    dewpoint_c: Optional[float]
    flight_category: str  # "VFR" | "MVFR" | "IFR" | "LIFR"
    raw_metar: str
```

---

### Fix 3: Genie/Assistant — extract shared interface

**Problem:** `assistant.py` imports `_genie_api` and `_poll_message` (private functions) from `genie.py`. Brittle coupling — any internal change to genie breaks assistant.

**Files to modify:**
- `app/backend/api/genie.py` — rename `_genie_api` → `genie_api` and `_poll_message` → `poll_genie_message` (make public)
- `app/backend/api/assistant.py` — update import to use public names

**New test:** add to existing `tests/test_assistant.py`
- Test that `genie_api` and `poll_genie_message` are importable from `genie.py`
- Test that `assistant.py` does not import any `_`-prefixed names from `genie.py`

---

### Fix 4: Profile schema validation

**Problem:** `known_profiles.py` hand-creates `AirportProfile` objects, but if `AirportProfile` gains new required fields, known profiles silently get defaults instead of failing.

**Files to modify:** none (test-only fix)

**New test:** `tests/test_profile_schema_compat.py`
- Import `list_known_airports` and `get_known_profile`
- For each known airport, call `get_known_profile()` and verify:
  - All non-default fields are populated (`airline_shares`, `domestic_route_shares`, `fleet_mix`, `hourly_profile` are non-empty)
  - `data_source` is `"known"` (not `"fallback"`)
  - `sample_size > 0`
- Compare field sets: verify `AirportProfile.__dataclass_fields__` matches what known profiles actually populate

---

### Fix 5: WebSocket schema contract test

**Problem:** Backend WebSocket sends `flight_delta` messages with dict fields. Frontend `Flight` interface defines the expected shape. No compile-time or test-time validation they match.

**Files to modify:** none (test-only fix)

**New test:** `tests/test_websocket_schema.py`
- Import `_DELTA_FIELDS` from `websocket.py`
- Parse the frontend `Flight` interface fields from `app/frontend/src/types/flight.ts`
- Verify all `_DELTA_FIELDS` exist in the `Flight` interface
- Verify the WebSocket message types (`flight_delta`, `mode_change`, `airport_switch_progress`, `airport_switch_complete`) match what the frontend expects
- Test that `_compute_deltas()` output keys are a subset of `Flight` interface keys

---

### Fix 6: DLT pipeline chain integrity test

**Problem:** Bronze layers hardcode Unity Catalog source table FQNs. No test that these match the actual catalog/schema from deployment config.

**New test:** added to `tests/test_dlt_table_names.py` (same file as Fix 1)
- Parse `databricks.yml` or `app.yaml` for catalog/schema config
- Verify the FQN strings in `bronze.py` match the configured `catalog.schema`
- Verify the pipeline chain: for each `read_stream(X)`, there exists a `@dlt.table(name=X)` in another file

---

## Verification

```bash
# Run only the new tests
uv run pytest tests/test_dlt_table_names.py tests/test_weather_schema_compat.py tests/test_profile_schema_compat.py tests/test_websocket_schema.py -v

# Run full test suite to check no regressions
uv run pytest tests/ -v --timeout=60
```

## Files created (new)

- `src/ingestion/weather_types.py`
- `tests/test_dlt_table_names.py`
- `tests/test_weather_schema_compat.py`
- `tests/test_profile_schema_compat.py`
- `tests/test_websocket_schema.py`

## Files modified (existing)

- `src/pipelines/__init__.py` — add constants
- `src/pipelines/bronze.py` — use constants
- `src/pipelines/silver.py` — use constants
- `src/pipelines/gold.py` — use constants
- `src/pipelines/baggage_bronze.py` — use constants
- `src/pipelines/baggage_silver.py` — use constants
- `src/pipelines/baggage_gold.py` — use constants
- `src/ingestion/weather_generator.py` — validate against `WeatherSnapshot`
- `app/backend/services/metar_history.py` — validate against `WeatherSnapshot`
- `app/backend/api/genie.py` — make 2 functions public
- `app/backend/api/assistant.py` — update 1 import line
- `tests/test_assistant.py` — add 2 tests for public interface

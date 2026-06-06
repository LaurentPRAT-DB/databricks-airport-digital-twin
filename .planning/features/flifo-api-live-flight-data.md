---
status: complete
area: ingestion
priority: high
related:
  - .planning/backlog/openflights-route-ingestion.md
  - app/backend/services/schedule_service.py
  - src/ingestion/opensky_client.py
---

# SITA FLIFO API Integration for Live Flight Data

## Problem

The SITA-branded deployment needs real flight schedule/status data instead of synthetic generation. FLIFO is SITA's B2B flight information service — the same data airports see in their AMS.

## Architecture

Pluggable data source slotting into existing `ScheduleService` priority chain:

```
Current:  Live sim → Lakebase → Schedule generator
Proposed: Live sim → FLIFO (if configured) → Lakebase → Schedule generator
```

Active only when `FLIFO_API_KEY` env var is set. Zero behavior change without it.

## FLIFO Data Fields

| FLIFO provides | Maps to |
|----------------|---------|
| Schedule (SIFL/SSIM) | `scheduled_time` |
| Estimated milestones (EOBT/ELDT) | `estimated_time` |
| Actual milestones (AOBT/ALDT) | `actual_time` |
| Status updates | `FlightStatus` enum |
| Gate/stand assignments | `gate`, new `stand` field |
| Baggage belt | new `belt` field |
| IATA delay codes | `delay_reason` |
| Codeshares | new `codeshares` field |
| Aircraft registration | new `registration` field |
| Terminal | new `terminal` field |

## New Files

| File | Purpose |
|------|---------|
| `src/ingestion/flifo_client.py` | API client (auth, retry, rate limit) |
| `src/ingestion/flifo_mapper.py` | Response → internal dict transform |
| `app/backend/services/flifo_service.py` | Service layer + polling cache |
| `tests/test_flifo_client.py` | Client unit tests |
| `tests/test_flifo_mapper.py` | Mapper unit tests |
| `tests/test_flifo_service.py` | Service integration tests |

## Modified Files

| File | Change |
|------|--------|
| `app/backend/models/schedule.py` | Add 5 optional fields (belt, stand, terminal, registration, codeshares) |
| `app/backend/services/schedule_service.py` | Insert FLIFO in priority chain |
| `src/config/settings.py` | Add FLIFO env vars |
| `app.yaml` | Add FLIFO env var declarations |

## Key Patterns (reuse from codebase)

- **Client pattern**: `src/ingestion/opensky_client.py` — OAuth2/API key, tenacity retry, RateLimitError
- **Service pattern**: `app/backend/services/lakebase_service.py` — singleton, `is_available` property, graceful degradation
- **Test pattern**: `tests/test_lakebase_service.py` — `unittest.mock.patch` for env vars and availability flags

## Lakebase Persistence

FLIFO data also written to `flight_schedule` table (cache for outages). Add `data_source` column: `"flifo"` / `"synthetic"` / `"opensky"`.

## Blockers

1. **SITA sandbox credentials** — need API key from SITA contract to test against real endpoint
2. **Exact API spec** — response format TBD. Mapper pattern isolates this to one file

## Effort

~2-3 days with mocked API. +1 day for real integration after credentials.

## Verification

1. `uv run pytest tests/test_flifo_*.py -v`
2. Set `FLIFO_API_KEY=test` → schedule service uses FLIFO source
3. Without API key → zero behavior change
4. Deploy dev target with SITA brand → FIDS shows real data
5. `/api/schedule/audit` cross-reference

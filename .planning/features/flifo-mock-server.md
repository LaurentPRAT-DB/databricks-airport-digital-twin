---
title: "Local FLIFO Mock Server"
status: complete
area: ingestion
priority: medium
related:
  - .planning/backlog/flifo-api-live-flight-data.md
  - .planning/backlog/gate-baggage-data-feed-prep.md
---

# Local FLIFO Mock Server

## Context

FLIFO API integration is planned (`.planning/backlog/flifo-api-live-flight-data.md`) but blocked on SITA sandbox credentials. Need a local mock server that mimics FLIFO REST responses so we can build `flifo_client.py` and `flifo_mapper.py` against realistic data without waiting for credentials.

## Architecture

Standalone FastAPI app in `tools/flifo_mock/` — run locally, point future FLIFO client at `http://localhost:8089`. Dynamically generates flights for any requested airport using existing schedule_generator logic for realism.

## FLIFO API Shape (from shared reference)

- **Auth:** OAuth2 client credentials → bearer token (1hr expiry)
- **Endpoints:**
  - `POST /oauth/token` — token endpoint
  - `GET /flightinfo/v2/flights/airport/{iata}` — flights at airport
  - `GET /flightinfo/v2/flights/airline/{iata}` — flights for airline
  - Query params: `direction` (arrival/departure), `status`, `fromDate`, `toDate`
- **Response:** `{ "flightRecords": [...] }` array
- **Status codes:** SC (scheduled), ON (on-time), DL (delayed), BD (boarding), DP (departed), AR (arrived), CX (cancelled), DV (diverted), IA (in-air), plus ~19 more

## Files to Create

| File | Purpose |
|------|---------|
| `tools/flifo_mock/server.py` | FastAPI app with FLIFO-shaped endpoints |
| `tools/flifo_mock/models.py` | Pydantic models for FLIFO response format |
| `tools/flifo_mock/generator.py` | Flight data generator (reuses schedule_generator logic) |
| `tools/flifo_mock/auth.py` | OAuth2 mock (issues/validates tokens) |
| `tools/flifo_mock/__init__.py` | Package marker |
| `tools/flifo_mock/README.md` | Usage instructions |

## Key Design Decisions

1. **Standalone process** — `uvicorn tools.flifo_mock.server:app --port 8089`
2. **OAuth required** — clients must POST to `/oauth/token` with client_id/secret, get back JWT-like token. All flight endpoints require `Authorization: Bearer <token>`.
3. **Dynamic data** — reuse AIRLINES dict and schedule generation patterns from `src/ingestion/schedule_generator.py` (import directly). Generate per-request with seed from airport+date for deterministic replay.
4. **FLIFO-shaped responses** — field names match real FLIFO spec: `flightNumber`, `airline.iataCode`, `departure.iataCode`, `arrival.iataCode`, `statusCode`, `estimatedTime`, `actualTime`, `gate`, `terminal`, `baggageBelt`, `aircraft.registration`, `codeshares[]`.
5. **28 status codes** with realistic distribution weighted by time-to-scheduled.

## Response Schema (single flightRecord)

```json
{
  "flightNumber": "UA123",
  "airline": { "iataCode": "UA", "icaoCode": "UAL", "name": "United Airlines" },
  "departure": { "iataCode": "LAX", "icaoCode": "KLAX", "scheduledTime": "2026-06-01T14:30:00Z" },
  "arrival": {
    "iataCode": "SFO", "icaoCode": "KSFO",
    "scheduledTime": "2026-06-01T15:45:00Z",
    "estimatedTime": "2026-06-01T15:50:00Z",
    "actualTime": null,
    "terminal": "1", "gate": "B12", "baggageBelt": "3"
  },
  "statusCode": "DL",
  "statusDescription": "Delayed",
  "delayMinutes": 5,
  "delayCode": "81",
  "aircraft": { "registration": "N12345", "iataType": "320", "icaoType": "A320" },
  "codeshares": [{ "flightNumber": "LH7234", "airline": { "iataCode": "LH" } }],
  "updatedAt": "2026-06-01T14:00:00Z"
}
```

## Reused Code

- `src/ingestion/schedule_generator.AIRLINES` — airline weights, names, ICAO codes, hubs, scope
- Schedule generation patterns (peak hours, delay distribution, gate assignment) — adapted, not imported directly (mock is standalone-ish)
- `src/ingestion/schedule_generator.DESTINATIONS` concept — route realism

## Implementation Steps

1. Create `tools/flifo_mock/` directory
2. `models.py` — Pydantic models for FLIFO response envelope
3. `auth.py` — token issuing + validation middleware
4. `generator.py` — flight record generator (standalone, copies airline/route data to avoid import coupling)
5. `server.py` — FastAPI app wiring endpoints
6. `README.md` — how to run, env vars, example curl commands

## Verification

1. Start server: `uv run uvicorn tools.flifo_mock.server:app --port 8089`
2. Get token: `curl -X POST localhost:8089/oauth/token -d "client_id=test&client_secret=test&grant_type=client_credentials"`
3. Fetch flights: `curl -H "Authorization: Bearer <token>" "localhost:8089/flightinfo/v2/flights/airport/SFO?direction=arrival"`
4. Verify response has `flightRecords` array with correct field structure
5. Verify auth rejection without token returns 401
6. Verify different airports return different data

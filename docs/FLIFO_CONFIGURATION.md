# FLIFO Configuration Guide

SITA FLIFO (FlightInfo) provides real-time flight schedule data — gate assignments, terminal, baggage belt, delay codes, codeshares, and operational milestones. This document covers setup for development and production.

## Architecture

```
FLIFO API (or embedded mock)
    │
    ▼
flifo_client.py ──→ OAuth2 token ──→ GET /flightinfo/v2/flights/airport/{iata}
    │
    ▼
flifo_mapper.py ──→ 28 FLIFO status codes → internal format
    │
    ▼
flifo_service.py ──→ in-memory cache (60s) + Lakebase persistence
    │
    ├──→ schedule_service ──→ FIDS display (priority: live sim → FLIFO → Lakebase → generator)
    └──→ _schedule_queue ──→ simulation spawner (seeds real callsigns onto map)
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `FLIFO_MOCK_MODE` | No | `""` (off) | `true` = use embedded mock (in-process, no HTTP) |
| `FLIFO_BASE_URL` | No | `""` | API base URL (mock or production) |
| `FLIFO_CLIENT_ID` | No | `""` | OAuth2 client ID |
| `FLIFO_CLIENT_SECRET` | No | `""` | OAuth2 client secret |

When none are set → FLIFO disabled → pure synthetic data → zero behavior change.

## Development Setup (Embedded Mock)

The app includes an embedded FLIFO mock server that generates realistic data in-process. No external service needed.

```yaml
# app.yaml (already configured for dev target)
env:
  - name: FLIFO_MOCK_MODE
    value: "true"
  - name: FLIFO_BASE_URL
    value: "http://localhost:8000/mock/flifo"
  - name: FLIFO_CLIENT_ID
    value: "test"
  - name: FLIFO_CLIENT_SECRET
    value: "test"
```

The mock:
- Generates flights using airport calibration profiles (realistic airline weights per airport)
- Covers all 28 FLIFO status codes with time-relative distribution
- Includes codeshares (20% of flights), IATA delay codes, aircraft registration
- Deterministic per airport+date (same seed = same flights for reproducibility)
- Zero network latency (called directly in-process)

### Standalone Mock Server

For testing the FLIFO client independently:

```bash
uv run uvicorn tools.flifo_mock.server:app --port 8089
```

Test credentials: `test/test`, `flifo_client/flifo_secret`, `sita_demo/demo_secret`

```bash
# Get token
TOKEN=$(curl -s -X POST http://localhost:8089/oauth/token \
  -d "grant_type=client_credentials&client_id=test&client_secret=test" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Fetch flights
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8089/flightinfo/v2/flights/airport/SFO?direction=arrival&limit=5"
```

## Production Setup (Real SITA API)

### 1. Obtain Credentials

Register at [developer.aero](https://developer.aero) for FLIFO API access. You'll receive a `client_id` and `client_secret`.

### 2. Store in Databricks Secret Scope

```bash
databricks secrets put-secret airport-digital-twin FLIFO_CLIENT_ID --string-value "<your-client-id>"
databricks secrets put-secret airport-digital-twin FLIFO_CLIENT_SECRET --string-value "<your-client-secret>"
```

### 3. Update app.yaml

```yaml
env:
  - name: FLIFO_MOCK_MODE
    value: "false"
  - name: FLIFO_BASE_URL
    value: "https://api.developer.aero"
  - name: FLIFO_CLIENT_ID
    value: "${FLIFO_CLIENT_ID}"
  - name: FLIFO_CLIENT_SECRET
    value: "${FLIFO_CLIENT_SECRET}"
```

Or simply remove `FLIFO_MOCK_MODE` entirely (absent = disabled).

### 4. Deploy

```bash
./deploy.sh --target prod
```

No code changes required.

## UI Controls

### Platform Menu Toggle

The Platform dropdown (top-right header) includes a FLIFO toggle switch:
- **Green** = active, data flowing
- **Amber** = enabled but API unreachable (using fallback)
- **Grey** = disabled (pure simulation)

Toggle is instant — no redeploy needed.

### FIDS Footer Badge

When FLIFO data is displayed, a green pulsing "FLIFO" badge appears in the FIDS footer (bottom-right of the panel).

### API Endpoints

```bash
# Check status
GET /api/schedule/flifo/status
# Response: { configured, enabled, active, queued_arrivals, queued_departures, last_error }

# Toggle on/off
POST /api/schedule/flifo/toggle?enabled=true
POST /api/schedule/flifo/toggle?enabled=false
```

## How Data Flows

### FIDS Display

Priority chain (first available wins):
1. **Live sim flights** — always shown (matches map)
2. **FLIFO** — real schedule data (if configured and enabled)
3. **Lakebase** — cached schedule from previous fetches
4. **Schedule generator** — synthetic fallback

### Simulation Seeding

When FLIFO is active, the `ScheduleQueue` feeds real flight data to the simulation spawner:
- Arrivals spawn when `scheduled_time - now` < 45 minutes
- Departures spawn when `scheduled_time - now` < 30 minutes
- FLIFO status maps to simulation phase (SC→APPROACHING, BD→PARKED, DP→TAXI_TO_RUNWAY)
- Duplicate prevention via callsign tracking

Result: FIDS and map show the **same flight numbers**.

### Callsign Reconciliation

OpenSky uses ICAO format (`UAL123`), FLIFO uses IATA format (`UA123`). The callsign reconciler normalizes both for deduplication — same physical flight never appears twice.

### Persistence (Lakebase → Delta)

FLIFO data is written to Lakebase `flight_schedule` table with `data_source='flifo'`. Two sync paths to Unity Catalog:
- `sync_from_lakebase.py` — `SELECT *` + `mergeSchema=true` (auto-evolves schema)
- `sync_all_to_unity_catalog.py` — explicit MERGE with all fields

All 5 FLIFO-specific columns are persisted: `terminal`, `stand`, `belt`, `registration`, `data_source`.

## Graceful Degradation

| Scenario | Behavior |
|----------|----------|
| FLIFO not configured | App works as before — pure synthetic |
| FLIFO configured, API down | Serves stale cache → falls back to generator, logs warning |
| FLIFO configured, toggle off | Pure simulation, queue frozen |
| Lakebase unavailable | FLIFO still works for FIDS (in-memory), just not persisted |
| Network timeout | 3 retries with exponential backoff, then fallback |

## Supported Airports

FLIFO works with **any airport** — the airport selector drives which IATA code is queried. The mock uses calibration profiles for airport-appropriate airline weights (e.g., 54% United at SFO, 15% Lufthansa at FRA).

## FLIFO Status Codes

| Code | Description | Maps to |
|------|-------------|---------|
| SC | Scheduled | scheduled |
| ON | On Time | on_time |
| DL | Delayed | delayed |
| BD | Boarding | boarding |
| FC | Final Call | final_call |
| GC | Gate Closed | gate_closed |
| DP | Departed | departed |
| AR | Arrived | arrived |
| CX | Cancelled | cancelled |
| IA | In Air | departed |
| LN | Landed | arrived |
| TX | Taxiing | arrived |
| BG | Baggage on Belt | arrived |

Full 28-code mapping in `src/ingestion/flifo_mapper.py`.

## Files

| File | Purpose |
|------|---------|
| `tools/flifo_mock/server.py` | Mock server (FastAPI, embeddable) |
| `tools/flifo_mock/generator.py` | Flight data generator (profile-aware) |
| `tools/flifo_mock/auth.py` | OAuth2 mock |
| `tools/flifo_mock/models.py` | Pydantic response models |
| `src/ingestion/flifo_client.py` | API client (OAuth2, retry, rate limit) |
| `src/ingestion/flifo_mapper.py` | Response → internal format |
| `src/ingestion/callsign_reconciler.py` | ICAO↔IATA normalization |
| `src/ingestion/_schedule_queue.py` | Simulation seeding queue |
| `app/backend/services/flifo_service.py` | Service layer (cache, persistence) |

## Tests

```bash
# All FLIFO tests (55 total)
uv run pytest tests/test_flifo_*.py tests/test_callsign_reconciler.py tests/test_schedule_queue.py -v

# Integration test (starts mock server automatically)
uv run pytest tests/test_flifo_integration.py -v
```

# FLIFO Mock Server

Local mock of SITA FlightInfo API v2 for development and testing.

## Quick Start

```bash
uv run uvicorn tools.flifo_mock.server:app --port 8089
```

## Authentication

Get a token first (mimics OAuth2 client credentials):

```bash
TOKEN=$(curl -s -X POST http://localhost:8089/oauth/token \
  -d "grant_type=client_credentials&client_id=test&client_secret=test" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

Valid credentials: `test/test`, `flifo_client/flifo_secret`, `sita_demo/demo_secret`

## Endpoints

### GET /flightinfo/v2/flights/airport/{iata}

Flights at an airport.

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8089/flightinfo/v2/flights/airport/SFO?direction=arrival&limit=10"
```

Query params:
- `direction`: `arrival` or `departure` (omit for both)
- `fromDate`: ISO datetime (default: now - 2h)
- `toDate`: ISO datetime (default: now + 4h)
- `status`: Filter by FLIFO status code (e.g., `DL`, `AR`, `BD`)
- `limit`: Max records (1-200, default 30)

### GET /flightinfo/v2/flights/airline/{iata}

Flights for an airline.

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8089/flightinfo/v2/flights/airline/UA?limit=10"
```

### GET /flightinfo/v2/flights/{flight_number}

Single flight lookup.

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8089/flightinfo/v2/flights/UA1234"
```

## Status Codes

| Code | Description | Typical timing |
|------|-------------|---------------|
| SC | Scheduled | >2h before |
| ON | On Time | 30min-2h before |
| DL | Delayed | Any time |
| BD | Boarding | 10-30min before (dep) |
| FC | Final Call | 10-30min before (dep) |
| GC | Gate Closed | 0-10min before (dep) |
| DP | Departed | After scheduled (dep) |
| IA | In Air | During flight |
| LN | Landed | At arrival time |
| TX | Taxiing | Just after landing |
| AR | Arrived | After arrival |
| BG | Baggage on Belt | After arrival |
| CX | Cancelled | Any time |
| DV | Diverted | During flight |

## Response Shape

```json
{
  "flightRecords": [
    {
      "flightNumber": "UA1234",
      "airline": { "iataCode": "UA", "icaoCode": "UAL", "name": "United Airlines" },
      "departure": { "iataCode": "LAX", "icaoCode": "KLAX", "scheduledTime": "..." },
      "arrival": { "iataCode": "SFO", "icaoCode": "KSFO", "scheduledTime": "...", "estimatedTime": "...", "terminal": "1", "gate": "B12", "baggageBelt": "3" },
      "statusCode": "DL",
      "statusDescription": "Delayed",
      "delayMinutes": 15,
      "delayCode": "81",
      "aircraft": { "registration": "N12345", "iataType": "320", "icaoType": "A320" },
      "codeshares": [{ "flightNumber": "LH7234", "airline": { "iataCode": "LH" } }],
      "updatedAt": "2026-06-01T14:00:00Z"
    }
  ],
  "totalRecords": 1,
  "airport": "SFO",
  "direction": "arrival"
}
```

## Integration with FLIFO Client

Set these env vars when developing `flifo_client.py`:

```bash
FLIFO_BASE_URL=http://localhost:8089
FLIFO_CLIENT_ID=test
FLIFO_CLIENT_SECRET=test
```

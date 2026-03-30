# Plan: Add MCP Server to Airport Digital Twin

## Context

The Airport Digital Twin is a FastAPI + React app deployed on Databricks Apps. We want to expose its core functionality as MCP (Model Context Protocol) tools so AI agents in the Databricks AI Playground and Supervisor Agents can query airport data, flight status, predictions, weather, etc. via natural language.

The app has ~40 REST endpoints across 7 routers. We'll expose the most useful read-only endpoints as MCP tools — the ones an AI agent would realistically call to answer questions about airport operations.

---

## Part 1: MCP Router Implementation

**New file:** `app/backend/api/mcp.py`

Create JSON-RPC 2.0 endpoint at `/api/mcp` with these MCP tools:

| #  | Tool Name                | Maps To                                 | Description                                                    |
|----|--------------------------|------------------------------------------|----------------------------------------------------------------|
| 1  | get_flights              | GET /api/flights                        | List all current flights with position, altitude, speed, phase |
| 2  | get_flight_details       | GET /api/flights/{icao24}               | Get details for a specific flight                              |
| 3  | get_flight_trajectory    | GET /api/flights/{icao24}/trajectory    | Get trajectory points for a flight                             |
| 4  | get_arrivals             | GET /api/schedule/arrivals              | Get scheduled arrivals (FIDS board)                            |
| 5  | get_departures           | GET /api/schedule/departures            | Get scheduled departures (FIDS board)                          |
| 6  | get_weather              | GET /api/weather/current                | Get current METAR weather for the airport                      |
| 7  | get_delay_predictions    | GET /api/predictions/delays             | Get ML delay predictions for flights                           |
| 8  | get_gate_recommendations | GET /api/predictions/gates/{icao24}     | Get ML gate assignment recommendations                         |
| 9  | get_congestion           | GET /api/predictions/congestion-summary | Get runway/taxiway/apron congestion + bottlenecks              |
| 10 | get_airport_info         | GET /api/airport/config                 | Get airport config (runways, gates, terminals, taxiways)       |
| 11 | get_baggage_stats        | GET /api/baggage/stats                  | Get baggage handling statistics                                |
| 12 | get_gse_status           | GET /api/gse/status                     | Get ground support equipment fleet status                      |
| 13 | list_airports            | GET /api/airports                       | List all supported airports                                    |

### Implementation approach

- No new dependencies — pure JSON-RPC 2.0 over HTTP with Pydantic models
- Each tool calls the existing service layer directly (same pattern as existing routers)
- Protocol handlers: `initialize`, `tools/list`, `tools/call`
- Debug endpoints: `GET /api/mcp/tools` and `GET /api/mcp/health`

### Register in `app/backend/main.py`

```python
from app.backend.api.mcp import mcp_router
app.include_router(mcp_router)
```

---

## Part 2: MCP Tool Unit Tests

**New file:** `tests/test_mcp.py`

Test every MCP tool with:

1. **Protocol tests** — initialize, tools/list, invalid method, bad JSON-RPC version
2. **Per-tool tests** — for each of the 13 tools:
   - Call via JSON-RPC `tools/call` with valid params
   - Assert response has `result.content[0].text` with parseable JSON
   - Assert response JSON has expected keys (tool-specific)
   - Measure and assert latency < threshold (e.g., 500ms for most, 2000ms for predictions)
3. **Error handling tests** — unknown tool, missing required params
4. **Latency report** — parametrized test that collects timing for all tools

### Test structure

```python
@pytest.fixture
def client():
    return TestClient(app)

def _mcp_call(client, method, params=None, req_id=1):
    """Helper: send JSON-RPC request, return (response_json, elapsed_ms)."""
    t0 = time.monotonic()
    resp = client.post("/api/mcp", json={...})
    elapsed = (time.monotonic() - t0) * 1000
    return resp.json(), elapsed

class TestMCPProtocol:
    # initialize, tools/list, error cases

class TestMCPTools:
    # Per-tool: response shape + latency assertion

    @pytest.mark.parametrize("tool_name,args,expected_keys,max_ms", [
        ("get_flights", {}, ["flights", "count"], 500),
        ("get_weather", {}, ["metar", "temperature"], 500),
        ("get_delay_predictions", {}, ["delays", "count"], 2000),
        ...
    ])
    def test_tool_response_and_latency(self, client, tool_name, args, expected_keys, max_ms):
        result, elapsed = _mcp_call(client, "tools/call", {"name": tool_name, "arguments": args})
        assert result.get("error") is None
        content = json.loads(result["result"]["content"][0]["text"])
        for key in expected_keys:
            assert key in content
        assert elapsed < max_ms, f"{tool_name} took {elapsed:.0f}ms (max {max_ms}ms)"
```

---

## Files to create/modify

| Action | File                                                          |
|--------|---------------------------------------------------------------|
| Create | `app/backend/api/mcp.py` — MCP JSON-RPC router (13 tools)    |
| Edit   | `app/backend/main.py` — add mcp_router import + include_router |
| Create | `tests/test_mcp.py` — protocol + per-tool + latency tests    |

---

## Verification

1. `uv run pytest tests/test_mcp.py -v` — all MCP tests pass
2. `uv run pytest tests/test_backend.py tests/test_v2_api.py -v` — existing tests still pass
3. Manual curl test:
```bash
curl -X POST http://localhost:8000/api/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

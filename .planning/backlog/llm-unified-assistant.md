# Plan: LLM-Powered Unified Assistant (Genie + MCP Tools)

## Context

The Airport Digital Twin has two AI backends:
1. **Genie Space** (01f12612fa6314ae943d0526f5ae3a00) — SQL analytics on historical Delta tables
2. **MCP Server** (13 tools) — real-time operational data (live flights, weather, predictions, congestion)

Currently the UI chat only calls Genie. We want a unified assistant that uses an LLM to route queries to the right backend — historical SQL via Genie or real-time data via MCP tools — and synthesizes coherent responses.

The Databricks Supervisor Agent API isn't publicly available for programmatic creation, so we build equivalent routing logic in our backend using a Foundation Model endpoint with function calling.

---

## Architecture

```
Frontend (GenieChat → AssistantChat)
    ↓ POST /api/assistant/ask
Backend Assistant Router (app/backend/api/assistant.py)
    ↓ LLM with function calling (databricks-claude-sonnet-4-5)
    ├── Genie Space API (historical SQL queries)
    └── MCP tool functions (real-time operational data)
    ↓ LLM synthesizes final answer
Frontend displays response (text + optional SQL/data tables)
```

---

## Part 1: Backend — `app/backend/api/assistant.py`

**New file:** `app/backend/api/assistant.py`

### Core flow

1. Receive user question + optional conversation_id
2. Call FM endpoint (`databricks-claude-sonnet-4-5`) with:
   - System prompt describing both tools (Genie for historical, MCP for real-time)
   - User's question
   - Function definitions for all 13 MCP tools + a `query_genie` function
3. If LLM requests function calls:
   - MCP tools → call `_execute_tool()` from `app/backend/api/mcp.py` directly
   - `query_genie` → call existing Genie API proxy logic
4. Feed function results back to LLM
5. LLM produces final text response
6. Return to frontend

### Key design decisions

- Reuse `_execute_tool()` from `mcp.py` directly — no duplication
- Reuse `_genie_api()` + `_poll_message()` from `genie.py` for Genie calls
- Use OpenAI-compatible chat completions API (`/serving-endpoints/{endpoint}/invocations`)
- Auth: forward user's OAuth token (same as Genie) + fall back to SDK credentials
- Env var `ASSISTANT_MODEL_ENDPOINT` defaults to `databricks-claude-sonnet-4-5`
- Max 3 tool-call rounds to prevent infinite loops

### Response model

```python
class AssistantResponse(BaseModel):
    conversation_id: str | None = None   # For Genie follow-ups
    answer: str                           # LLM's synthesized answer
    sources: list[str] = []              # ["genie", "mcp:get_flights", ...]
    sql: str | None = None               # If Genie was called
    columns: list[str] | None = None     # If Genie returned data
    data: list[list] | None = None       # If Genie returned data
    row_count: int = 0
    tool_calls: list[dict] | None = None # Debug: which tools were called
```

### Function definitions for the LLM

- All 13 MCP tools (from `MCP_TOOLS` in `mcp.py`) — mapped to OpenAI function calling format
- 1 `query_genie` function for historical SQL queries:

```json
{
    "name": "query_genie",
    "description": "Query historical airport data via SQL. Use for trends, aggregations, time-series, counts over periods. Returns SQL + data tables.",
    "parameters": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "Natural language question about historical data"}
        },
        "required": ["question"]
    }
}
```

### Endpoints

- `POST /api/assistant/ask` — new conversation
- `POST /api/assistant/followup` — continue conversation (maintains Genie conversation_id)

### Edits

- `app/backend/main.py` — add `assistant_router` import + `app.include_router()`
- `app.yaml` — add `ASSISTANT_MODEL_ENDPOINT` env var (default: `databricks-claude-sonnet-4-5`)

---

## Part 2: Frontend — Update GenieChat → AssistantChat

**Edit:** `app/frontend/src/components/GenieChat/GenieChat.tsx`

Minimal changes — keep the same UI, switch the API calls:

1. **API endpoint:** `/api/genie/ask` → `/api/assistant/ask`, `/api/genie/followup` → `/api/assistant/followup`
2. **Response mapping:** Map `AssistantResponse` to existing `GenieMessage` format:
   - `answer` → `content`
   - `sql`, `columns`, `data`, `row_count` → same fields (pass through when Genie was used)
   - `sources` → show as badge/tag (e.g., "Live Data" / "Historical SQL")
3. **Source indicator:** Add a small badge below assistant messages showing the data source
4. **Sample questions:** Update to include both types:
   - Historical: "Average delay by airline last month"
   - Real-time: "What's the current weather at the airport?"
   - Mixed: "Compare current congestion to typical levels"

### Rename component

Keep filename as `GenieChat.tsx` for now (avoid unnecessary churn), but update the header text from "Airport Ops Assistant" to "Airport Operations Assistant" and update the description.

---

## Part 3: Tests

**New file:** `tests/test_assistant.py`

1. **Routing tests** — mock the FM endpoint to return known function calls:
   - Weather question → should call `get_weather` MCP tool
   - Historical count question → should call `query_genie`
   - Verify response includes sources
2. **Error handling** — FM endpoint unreachable, Genie fails, MCP tool fails
3. **Max rounds** — verify loop terminates after 3 rounds

**Edit:** `app/frontend/src/components/GenieChat/GenieChat.test.tsx`

Update API endpoint paths in existing tests.

---

## Files to create/modify

| Action | File                                                                                             |
|--------|--------------------------------------------------------------------------------------------------|
| Create | `app/backend/api/assistant.py` — LLM router with function calling                               |
| Edit   | `app/backend/main.py` — add assistant_router                                                     |
| Edit   | `app.yaml` — add ASSISTANT_MODEL_ENDPOINT env var                                                |
| Edit   | `app/frontend/src/components/GenieChat/GenieChat.tsx` — switch to /api/assistant/ + source badges |
| Edit   | `app/frontend/src/components/GenieChat/GenieChat.test.tsx` — update endpoint paths               |
| Create | `tests/test_assistant.py` — routing + error handling tests                                       |

---

## Verification

1. `uv run pytest tests/test_assistant.py -v` — new tests pass
2. `uv run pytest tests/test_mcp.py -v` — MCP tests still pass
3. `cd app/frontend && npm test -- --run` — frontend tests pass
4. Manual test via curl:
```bash
curl -X POST http://localhost:8000/api/assistant/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the current weather?"}'
```
5. Build + deploy: `cd app/frontend && npm run build && cd ../.. && databricks bundle deploy --target dev`
6. Test on deployed app — verify both historical and real-time queries work

---

## Dependencies

- Requires **MCP Server** (`.planning/backlog/mcp-server.md`) to be implemented first

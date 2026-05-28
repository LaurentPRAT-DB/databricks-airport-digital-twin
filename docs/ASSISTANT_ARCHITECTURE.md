# Airport Operations Assistant — Architecture

The assistant is an LLM-powered conversational interface embedded in the main page. It classifies user questions and routes them to the appropriate backend: **Genie Space** for historical SQL analytics or **MCP tools** for real-time operational data.

---

## High-Level Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│  Frontend: GenieChat component                                       │
│  (floating panel, right-side drawer)                                 │
│                                                                      │
│  POST /api/assistant/ask          → new conversation                 │
│  POST /api/assistant/followup     → continue conversation            │
│  POST /api/assistant/explain      → explain simulation event (no tools)│
│  POST /api/assistant/report-chat  → report analysis + what-if         │
└──────────────┬───────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Backend: assistant_router (app/backend/api/assistant.py)             │
│                                                                      │
│  1. Authenticate (OAuth OBO token or SDK fallback)                   │
│  2. Build tool definitions (MCP tools + query_genie function)        │
│  3. Call Databricks FM Endpoint (OpenAI-compatible API)               │
│  4. If LLM returns tool_calls → execute tools → feed results back    │
│  5. Loop up to MAX_TOOL_ROUNDS (3) until LLM produces final answer   │
│  6. Return structured response with answer, sources, SQL, data        │
└──────────────┬─────────────────────┬─────────────────────────────────┘
               │                     │
    ┌──────────▼──────┐    ┌────────▼──────────────┐
    │  Genie Space    │    │  MCP Tool Layer        │
    │  (Historical)   │    │  (Real-Time)           │
    └─────────────────┘    └───────────────────────┘
```

---

## Components

### 1. Frontend — `GenieChat.tsx`

**Path:** `app/frontend/src/components/GenieChat/GenieChat.tsx`

| Feature | Detail |
|---------|--------|
| UI | Floating action button (bottom-right) opens a slide-in panel (400px wide, right-docked) |
| Modes | Full panel (conversation history + input) or compact (input bar only, mobile) |
| Conversation | Maintains `conversationId` for Genie follow-ups across messages |
| Sample questions | 4 pre-seeded prompts shown on empty state |
| Source badges | "Historical SQL", "Live Data", or "Historical + Live" based on response `sources[]` |
| Data display | Collapsible SQL blocks + paginated data tables (10 rows max, link to full Genie) |
| Error handling | HTTP-status-specific messages (403, 503, 404), retry button on failures |
| Deep link | Header links to Databricks Genie Space web UI |

**API calls:**
- `POST /api/assistant/ask` — first question (no `conversation_id`)
- `POST /api/assistant/followup` — subsequent questions (sends `conversation_id`)

**Configuration fetched from backend:**
- `GET /api/config` → `platform.workspace_url`, `platform.genie_space_id`

---

### 2. Backend — Unified Assistant Router

**Path:** `app/backend/api/assistant.py`

The router implements an **LLM-powered function-calling loop** that classifies questions and executes tools.

#### Endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /api/assistant/ask` | Start new conversation |
| `POST /api/assistant/followup` | Continue existing conversation |
| `POST /api/assistant/explain` | Explain a simulation event (no tools, pure inference) |
| `POST /api/assistant/report-chat` | Analyze simulation report + what-if simulation |

#### Response Schema (`AssistantResponse`)

```json
{
  "conversation_id": "string | null",
  "answer": "string",
  "sources": ["genie", "mcp:get_flights", ...],
  "sql": "SELECT ... | null",
  "columns": ["col1", "col2"] | null,
  "data": [[...], [...]] | null,
  "row_count": 0,
  "tool_calls": [{"name": "...", "arguments": {...}}] | null,
  "error": "string | null"
}
```

---

### 3. LLM Configuration

| Parameter | Value | Source |
|-----------|-------|--------|
| Model endpoint | `databricks-claude-sonnet-4-5` | `ASSISTANT_MODEL_ENDPOINT` env var |
| Fallback endpoints | `databricks-meta-llama-3-3-70b-instruct`, `databricks-llama-4-maverick` | Hardcoded list |
| Max tokens | 2048 | Hardcoded |
| Temperature | 0.1 | Hardcoded |
| Max tool rounds | 3 | `MAX_TOOL_ROUNDS` |
| API format | OpenAI-compatible chat completions | `/serving-endpoints/{endpoint}/invocations` |

**Endpoint resolution:** Tries primary, on 404 falls through fallback list sequentially.

---

### 4. System Prompt

```
You are the Airport Operations Assistant for a digital twin system. You have access to two types of data:

1. **Real-time operational data** (via tools): Current flights, live weather, ML predictions,
   congestion, baggage stats, GSE status. Use these tools for anything about the CURRENT
   state of the airport.

2. **Historical SQL analytics** (via query_genie): Historical trends, aggregations, time-series
   analysis, counts over time periods. Use query_genie for questions about past data, trends,
   comparisons over time, or statistical analysis.

Guidelines:
- For "right now", "current", "live", "at the moment" questions → use the real-time tools
- For "last week", "this month", "trend", "average over", "compare", "history" → use query_genie
- You can call multiple tools in one turn if needed
- Always provide clear, concise answers with key numbers highlighted
- When showing data from query_genie, mention it came from historical SQL analytics
- When showing real-time data, mention it's live operational data
```

---

### 5. Tool Definitions (Function Calling)

The LLM receives 13 tool definitions in OpenAI function-calling format:

#### Real-Time MCP Tools (12)

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `get_flights` | List current flights with positions | `count` (1-500) |
| `get_flight_details` | Single flight by ICAO24 | `icao24` (required) |
| `get_flight_trajectory` | Position history time-series | `icao24`, `minutes` |
| `get_arrivals` | FIDS arrivals board | `hours_ahead`, `hours_behind`, `limit` |
| `get_departures` | FIDS departures board | `hours_ahead`, `hours_behind`, `limit` |
| `get_weather` | Current METAR observation | (none) |
| `get_delay_predictions` | ML delay forecasts | `icao24` (optional) |
| `get_gate_recommendations` | ML gate assignment | `icao24` (required), `top_k` |
| `get_congestion` | Runway/taxiway/apron congestion | (none) |
| `get_airport_info` | Airport configuration from OSM | (none) |
| `get_baggage_stats` | Baggage handling metrics | (none) |
| `get_gse_status` | Ground support equipment fleet | (none) |
| `list_airports` | All supported airports | (none) |

#### Historical SQL Tool (1)

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `query_genie` | Natural-language SQL against Delta tables | `question` (required) |

---

### 6. Genie Space Integration

**Path:** `app/backend/api/genie.py`

| Config | Value |
|--------|-------|
| Space ID | `01f12612fa6314ae943d0526f5ae3a00` (env: `GENIE_SPACE_ID`) |
| API base | `{DATABRICKS_HOST}/api/2.0/genie/spaces/{SPACE_ID}` |
| Poll interval | 1.5s |
| Max poll time | 120s |
| Timeout response | Returns friendly "took too long" message |

**Flow:**
1. `POST /start-conversation` → get `conversation_id` + `message_id`
2. Poll `GET /conversations/{id}/messages/{id}` until terminal state
3. On `COMPLETED` with query attachment → fetch `/query-result/{attachment_id}`
4. Extract columns, data_array, SQL, description → return structured result

**Genie Space tables** (configured in Databricks UI):
- `flight_status_gold` — historical flight status records
- `flight_positions_history` — time-series position data
- `gate_assignment_history` — gate usage history
- `ml_prediction_history` — prediction accuracy tracking
- `simulation_runs` — simulation metadata

---

### 7. MCP Server (Standalone Protocol)

**Path:** `app/backend/api/mcp.py`

Beyond serving as internal tools for the assistant, the same tool layer is exposed as a **JSON-RPC 2.0 MCP endpoint** at `POST /api/mcp` for external AI agents (Databricks AI Playground, Supervisor Agents).

Protocol methods: `initialize`, `tools/list`, `tools/call`

Debug endpoints: `GET /api/mcp/tools`, `GET /api/mcp/health`

---

### 8. Report Chat (What-If Analysis)

**Path:** `app/backend/api/assistant.py` (lines 466–653)

Separate endpoint for post-simulation analysis with domain-expert prompting.

| Config | Value |
|--------|-------|
| Endpoint | `POST /api/assistant/report-chat` |
| System prompt | Aviation benchmarks (FAA AC 150/5060-5, 7110.65) + analysis instructions |
| Tool | `run_what_if_simulation` — re-runs simulation with modified parameters |
| Parameters | `arrivals`, `departures`, `duration_hours`, `scenario_file`, `seed` |

**Flow:** User asks "what if we add 20% more arrivals?" → LLM calls `run_what_if_simulation` → engine runs modified sim → results fed back → LLM produces before/after comparison.

---

### 9. Explain Event (Pure Inference)

**Path:** `app/backend/api/assistant.py` (lines 442–463)

| Config | Value |
|--------|-------|
| Endpoint | `POST /api/assistant/explain` |
| Model | Same as main assistant |
| Tools | None (pure text generation) |
| Prompt | Configurable via `EXPLAIN_PROMPT` env var |

Used by the simulation UI's "Explain" button on events (go-arounds, diversions, delays). Receives event JSON, returns structured analysis.

---

## Authentication

```
Request arrives
    │
    ├─ Has Bearer token in Authorization header? → use it (Databricks App OBO)
    │
    ├─ Databricks SDK Config() produces token? → use it
    │
    └─ Try CLI profiles (DATABRICKS_CONFIG_PROFILE, DEFAULT) → use first valid
    │
    └─ All failed → HTTP 503
```

On Databricks Apps, the user's OAuth token is forwarded automatically (On-Behalf-Of). For local dev, falls back to CLI profile authentication.

---

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `ASSISTANT_MODEL_ENDPOINT` | `databricks-claude-sonnet-4-5` | Primary FM endpoint for routing |
| `EXPLAIN_PROMPT` | (aviation expert prompt) | System prompt for event explanations |
| `GENIE_SPACE_ID` | `01f12612fa6314ae943d0526f5ae3a00` | Databricks Genie Space for SQL |
| `DATABRICKS_HOST` | (from SDK) | Workspace URL |
| `DATABRICKS_APP_URL` | (set in app.yaml) | For MCP connection auto-registration |

---

## Sequence Diagram — Typical Query

```
User types: "How many flights are active right now?"

1. Frontend → POST /api/assistant/ask {"question": "How many flights are active right now?"}
2. Backend builds messages: [system_prompt, user_question]
3. Backend → Databricks FM Endpoint (Claude Sonnet 4.5)
4. LLM returns: tool_calls: [{name: "get_flights", arguments: {count: 50}}]
5. Backend executes get_flights() → flight_service → returns 42 flights
6. Backend appends tool result to messages
7. Backend → Databricks FM Endpoint (second round)
8. LLM returns: "There are currently 42 active flights at the airport..."
9. Backend → Frontend: {answer: "...", sources: ["mcp:get_flights"], ...}
10. Frontend renders response with "Live Data" badge
```

```
User types: "What was the average delay last week?"

1. Frontend → POST /api/assistant/ask {"question": "What was the average delay last week?"}
2. Backend → Databricks FM Endpoint
3. LLM returns: tool_calls: [{name: "query_genie", arguments: {question: "average delay last week"}}]
4. Backend → Genie API: start-conversation → poll → fetch query-result
5. Genie executes SQL: SELECT AVG(delay_minutes) FROM flight_status_gold WHERE ...
6. Backend appends Genie results to messages
7. Backend → Databricks FM Endpoint (second round)
8. LLM returns: "The average delay last week was 12.3 minutes based on 1,847 flights..."
9. Backend → Frontend: {answer: "...", sources: ["genie"], sql: "SELECT...", columns: [...], data: [...]}
10. Frontend renders with "Historical SQL" badge + collapsible SQL + data table
```

---

## File Map

| File | Role |
|------|------|
| `app/frontend/src/components/GenieChat/GenieChat.tsx` | Chat UI component |
| `app/backend/api/assistant.py` | Unified assistant router (LLM + tools) |
| `app/backend/api/genie.py` | Genie Space API proxy |
| `app/backend/api/mcp.py` | MCP tool definitions + JSON-RPC endpoint |
| `app/backend/main.py` | Router registration |
| `app.yaml` | Environment variable configuration |

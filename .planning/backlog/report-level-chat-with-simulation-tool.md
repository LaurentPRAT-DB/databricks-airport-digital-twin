---
status: proposed
area: assistant, simulation, frontend
related:
  - app/frontend/src/components/SimulationControls/SimulationReport.tsx
  - app/backend/api/assistant.py
  - src/simulation/engine.py
---

# Feature: Report-Level Chat with Simulation-as-Tool

## Context

The simulation report has an "Analysis" tab that shows an LLM-generated markdown report. There's already a per-event mini-chat (explain + follow-up). The user wants a report-level chat that:

1. Has the full simulation context (KPIs, weather, events, schedule)
2. Can answer follow-up questions about the overall simulation
3. Can trigger what-if re-runs — "What if we add a 3rd arrival stream?" → run new simulation with modified params, compare KPIs

## Approach

### Frontend: Chat panel below the analysis report

Add a chat component below the markdown report in the Analysis tab. Reuse the same pattern as EventDetailPanel mini-chat (messages state, input box, send handler).

**File:** `app/frontend/src/components/SimulationControls/SimulationReport.tsx`

- New `ReportChat` component (inline, below the report markdown)
- State: `messages: ChatMessage[]`, `input`, `isLoading`, `conversationId`
- Sends to new endpoint `/api/assistant/report-chat` with simulation context
- Displays responses as markdown (reuses existing `<Markdown remarkPlugins={[remarkGfm]}>`)
- When response includes `what_if_result` (KPI comparison), render a before/after table
- Suggestion chips for common questions: "What caused the delays?", "How could we improve on-time?", "What if we reduce separation to 60s?"

### Backend: New endpoint `/api/assistant/report-chat`

**File:** `app/backend/api/assistant.py`

New endpoint that:

1. Accepts simulation context + user question + conversation history
2. Uses a specialized system prompt with aviation benchmarks (FAA/ICAO)
3. Has a `run_what_if_simulation` tool available for the LLM to call
4. Returns answer + optional what-if results (KPI comparison)

Request model:

```python
class ReportChatRequest(BaseModel):
    question: str
    messages: list[dict] = []  # prior conversation for multi-turn
    simulation_context: dict   # {config, summary, scenario_events, weather}
```

System prompt — aviation expert with benchmarks:

- Standard capacity figures (AAR/ADR by airport size)
- IFR/VFR reduction factors
- Separation standards (FAA 7110.65)
- Go-around/diversion acceptable rates
- Delay thresholds (FAA: >15min = delayed)
- Turnaround benchmarks by aircraft type

### Backend: Simulation-as-tool (`run_what_if_simulation`)

**Files:** `app/backend/api/assistant.py` (tool definition) + `src/simulation/engine.py` (execution)

The LLM can call a tool to run a modified simulation:

```json
{
    "name": "run_what_if_simulation",
    "description": "Run a modified simulation to compare KPIs. Modify parameters like arrivals, departures, runway config, or weather to see impact.",
    "parameters": {
        "modifications": {
            "type": "object",
            "properties": {
                "arrivals": {"type": "integer"},
                "departures": {"type": "integer"},
                "duration_hours": {"type": "number"},
                "runway_closures": {"type": "array"},
                "weather_override": {"type": "string"},
                "separation_seconds": {"type": "integer"}
            }
        },
        "comparison_label": {"type": "string"}
    }
}
```

Execution:

1. Take the current simulation's config as baseline
2. Apply modifications from the tool call
3. Run a short headless simulation (same duration, skip position snapshots for speed)
4. Return KPI comparison: baseline vs modified

`src/simulation/engine.py` already has `SimulationEngine(config).run()` that returns a recorder with summary. We just need a lightweight wrapper that:

- Clones the config
- Applies modifications
- Runs with `skip_positions=True` (fast — no position recording, only KPIs)
- Returns `{baseline_kpis, modified_kpis, delta}`

## Files to Modify

| File | Change |
|------|--------|
| `app/frontend/src/components/SimulationControls/SimulationReport.tsx` | Add `ReportChat` component in Analysis tab, below report markdown |
| `app/backend/api/assistant.py` | New `/api/assistant/report-chat` endpoint with aviation system prompt + `run_what_if_simulation` tool |
| `src/simulation/engine.py` | Add `run_what_if(base_config, modifications)` helper for headless comparison runs |

## UI Layout (Analysis tab)

```
+-----------------------------------+
|  [Dashboard] [Analysis]           |
+-----------------------------------+
|                                   |
|  ## Executive Summary             |
|  The simulation showed...         |
|                                   |
|  ## Weather Narrative             |
|  ...                              |
|                                   |
|  (scrollable report content)      |
|                                   |
+-----------------------------------+
|  +- Ask about this simulation --+ |
|  | Suggestions:                  | |
|  | [What caused delays?]        | |
|  | [How to improve on-time?]    | |
|  | [What if 20% more traffic?]  | |
|  |                               | |
|  | Assistant: Based on the KPIs  | |
|  | the main bottleneck was...    | |
|  |                               | |
|  | +--------------------+ [->]   | |
|  | | Type your question |        | |
|  | +--------------------+        | |
|  +-------------------------------+ |
+-----------------------------------+
```

## Implementation Steps

1. **Backend: Add `run_what_if` helper** to `src/simulation/engine.py`
   - Takes `SimulationConfig` + dict of overrides → returns KPI summary
   - Uses `skip_positions=True` for fast execution (~5-10s)

2. **Backend: Add `/api/assistant/report-chat` endpoint**
   - Aviation-expert system prompt with FAA/ICAO benchmarks
   - Tool: `run_what_if_simulation` (calls the engine helper)
   - Multi-turn via messages array (stateless — frontend maintains history)

3. **Frontend: Add `ReportChat` component**
   - Rendered below the markdown report in the Analysis tab
   - Suggestion chips + message list + input
   - Handles what-if results (before/after KPI table)

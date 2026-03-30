# Supervisor Agent: MCP + Genie Combined

**Created:** 2026-03-30
**Status:** Completed (2026-03-30)
**Approach:** LLM-powered backend router (Supervisor Agent API not publicly available)

## Goal

Create a Databricks Supervisor Agent that combines:
1. **Genie Space** (`01f12612fa6314ae943d0526f5ae3a00`) — SQL analytics on historical flight data from Delta tables
2. **MCP Server** (`airport_digital_twin_mcp`) — real-time airport operations (live flights, weather, predictions, congestion)

Then update the UI Assistant (currently Genie-only) to route through this Supervisor Agent, enabling both historical SQL queries and real-time operational queries from the same chat interface.

## Architecture

```
User (UI Chat) → Supervisor Agent → ┬─ Genie Space (historical SQL)
                                     └─ MCP Server (live operations)
```

## Sub-Agents

| Name | Type | ID/Connection | Use Case |
|------|------|---------------|----------|
| `airport_analytics` | Genie Space | `01f12612fa6314ae943d0526f5ae3a00` | Historical trends, aggregations, counts over time |
| `airport_live_ops` | MCP Connection | `airport_digital_twin_mcp` | Current flights, weather, predictions, congestion |

## Routing Instructions

- Historical trends, aggregations, counts over time → `airport_analytics` (Genie)
- Current/live flight positions, weather, predictions → `airport_live_ops` (MCP)
- If unclear, prefer `airport_live_ops` for "now/current" and `airport_analytics` for "last week/month/year"

## Implementation Steps

1. Create Supervisor Agent via `manage_mas` API
2. Wait for endpoint provisioning (2-5 min)
3. Update UI assistant backend to use Supervisor Agent endpoint instead of Genie Conversation API
4. Test both historical and real-time queries through the unified chat
5. Deploy updated app

## UI Changes

The frontend assistant component currently calls the Genie Conversation API directly. It needs to be updated to call the Supervisor Agent's model serving endpoint instead, which will route to either Genie or MCP based on the query.

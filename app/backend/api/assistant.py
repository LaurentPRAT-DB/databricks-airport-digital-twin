"""Unified Assistant — LLM-powered router combining Genie (historical SQL) and MCP tools (real-time ops).

Uses a Databricks Foundation Model endpoint with function calling to classify user queries
and route them to the appropriate backend: Genie Space for historical SQL analytics or
the MCP tool layer for real-time operational data.
"""

import json
import logging
import os
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

assistant_router = APIRouter(prefix="/api/assistant", tags=["assistant"])

# --- Configuration ---

MODEL_ENDPOINT = os.getenv("ASSISTANT_MODEL_ENDPOINT", "databricks-claude-sonnet-4-5")
MAX_TOOL_ROUNDS = 3  # Prevent infinite tool-call loops

SYSTEM_PROMPT = """You are the Airport Operations Assistant for a digital twin system. You have access to two types of data:

1. **Real-time operational data** (via tools): Current flights, live weather, ML predictions, congestion, baggage stats, GSE status. Use these tools for anything about the CURRENT state of the airport.

2. **Historical SQL analytics** (via query_genie): Historical trends, aggregations, time-series analysis, counts over time periods. Use query_genie for questions about past data, trends, comparisons over time, or statistical analysis.

Guidelines:
- For "right now", "current", "live", "at the moment" questions → use the real-time tools
- For "last week", "this month", "trend", "average over", "compare", "history" → use query_genie
- You can call multiple tools in one turn if needed
- Always provide clear, concise answers with key numbers highlighted
- When showing data from query_genie, mention it came from historical SQL analytics
- When showing real-time data, mention it's live operational data"""


# --- Request/Response Models ---


class AskRequest(BaseModel):
    question: str


class FollowupRequest(BaseModel):
    conversation_id: str
    question: str


class AssistantResponse(BaseModel):
    conversation_id: str | None = None
    answer: str
    sources: list[str] = []
    sql: str | None = None
    columns: list[str] | None = None
    data: list[list] | None = None
    row_count: int = 0
    tool_calls: list[dict] | None = None
    error: str | None = None


# --- Tool Definitions for the LLM (OpenAI function-calling format) ---


def _build_function_definitions() -> list[dict]:
    """Convert MCP_TOOLS + query_genie into OpenAI function-calling format."""
    from app.backend.api.mcp import MCP_TOOLS

    functions = []
    for tool in MCP_TOOLS:
        schema = tool.get("inputSchema", {"type": "object", "properties": {}})
        functions.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"][:500],  # Trim verbose MCP descriptions
                "parameters": schema,
            },
        })

    # Add the Genie function for historical SQL
    functions.append({
        "type": "function",
        "function": {
            "name": "query_genie",
            "description": (
                "Query historical airport data via SQL analytics. Use for trends, aggregations, "
                "time-series, counts over periods, statistical analysis, and any question about "
                "past data. Examples: 'average delay last month', 'flights per day this week', "
                "'busiest hour yesterday', 'delay trend over the past 7 days'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Natural language question about historical airport data",
                    },
                },
                "required": ["question"],
            },
        },
    })

    return functions


# --- Auth Helper ---


def _get_databricks_auth(request: Request) -> tuple[str, str]:
    """Extract Databricks host + token (reuses pattern from genie.py)."""
    host = os.getenv("DATABRICKS_HOST", "")
    if host and not host.startswith("http"):
        host = f"https://{host}"

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):]
        if token:
            return host, token

    try:
        from databricks.sdk.core import Config
        cfg = Config()
        host = host or cfg.host
        token = cfg.token
        if token:
            return host, token
        headers = cfg.authenticate()
        auth = headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return host, auth[len("Bearer "):]
    except Exception as e:
        logger.debug(f"SDK auth fallback failed: {e}")

    raise HTTPException(status_code=503, detail="No Databricks authentication available")


# --- LLM Call ---


async def _call_llm(
    host: str,
    token: str,
    messages: list[dict],
    tools: list[dict],
) -> dict:
    """Call the FM endpoint with OpenAI-compatible chat completions API."""
    url = f"{host}/serving-endpoints/{MODEL_ENDPOINT}/invocations"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "messages": messages,
        "tools": tools,
        "max_tokens": 2048,
        "temperature": 0.1,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, headers=headers, json=payload)

    if resp.status_code >= 400:
        detail = resp.text[:500]
        logger.error(f"LLM call failed ({resp.status_code}): {detail}")
        raise HTTPException(status_code=502, detail=f"LLM endpoint error: {resp.status_code}")

    return resp.json()


# --- Tool Execution ---


async def _execute_mcp_tool(tool_name: str, arguments: dict[str, Any]) -> str:
    """Execute an MCP tool and return the result as a string."""
    from app.backend.api.mcp import _execute_tool
    result = await _execute_tool(tool_name, arguments)
    return json.dumps(result, indent=2, default=str)


async def _execute_genie_query(
    question: str,
    host: str,
    token: str,
    conversation_id: str | None = None,
) -> dict:
    """Execute a Genie query and return structured result."""
    from app.backend.api.genie import _genie_api, _poll_message

    if conversation_id:
        resp = await _genie_api(
            "POST",
            f"/conversations/{conversation_id}/messages",
            host, token,
            json_body={"content": question},
        )
        message_id = resp.get("message_id") or resp.get("id")
    else:
        resp = await _genie_api(
            "POST",
            "/start-conversation",
            host, token,
            json_body={"content": question},
        )
        conversation_id = resp.get("conversation_id")
        message_id = resp.get("message_id")

    if not conversation_id or not message_id:
        return {"error": "Genie returned no conversation/message ID", "text": ""}

    genie_result = await _poll_message(host, token, conversation_id, message_id)
    return {
        "conversation_id": conversation_id,
        "text": genie_result.text_response or "",
        "sql": genie_result.sql,
        "columns": genie_result.columns,
        "data": genie_result.data,
        "row_count": genie_result.row_count,
        "status": genie_result.status,
    }


# --- Main Assistant Logic ---


async def _run_assistant(
    question: str,
    request: Request,
    conversation_id: str | None = None,
) -> AssistantResponse:
    """Run the LLM-powered assistant with tool calling loop."""
    t0 = time.monotonic()
    host, token = _get_databricks_auth(request)
    tools = _build_function_definitions()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    sources: list[str] = []
    all_tool_calls: list[dict] = []
    genie_result: dict | None = None

    from app.backend.api.mcp import _TOOL_NAMES

    for round_num in range(MAX_TOOL_ROUNDS):
        logger.info(f"Assistant round {round_num + 1}: calling LLM with {len(messages)} messages")
        llm_response = await _call_llm(host, token, messages, tools)

        choices = llm_response.get("choices", [])
        if not choices:
            return AssistantResponse(
                answer="The assistant could not generate a response. Please try again.",
                error="No choices in LLM response",
            )

        choice = choices[0]
        message = choice.get("message", {})
        finish_reason = choice.get("finish_reason", "")

        # If no tool calls, return the text response
        tool_calls = message.get("tool_calls")
        if not tool_calls or finish_reason == "stop":
            answer = message.get("content", "")
            if not answer:
                answer = "I processed your question but couldn't generate a clear answer. Please try rephrasing."
            elapsed = (time.monotonic() - t0) * 1000
            logger.info(f"Assistant completed in {elapsed:.0f}ms with {len(sources)} sources")
            return AssistantResponse(
                conversation_id=genie_result.get("conversation_id") if genie_result else conversation_id,
                answer=answer,
                sources=sources,
                sql=genie_result.get("sql") if genie_result else None,
                columns=genie_result.get("columns") if genie_result else None,
                data=genie_result.get("data") if genie_result else None,
                row_count=genie_result.get("row_count", 0) if genie_result else 0,
                tool_calls=all_tool_calls if all_tool_calls else None,
            )

        # Process tool calls
        messages.append(message)  # Add assistant message with tool_calls

        for tc in tool_calls:
            func = tc.get("function", {})
            tool_name = func.get("name", "")
            try:
                arguments = json.loads(func.get("arguments", "{}"))
            except json.JSONDecodeError:
                arguments = {}

            tc_record = {"name": tool_name, "arguments": arguments}
            all_tool_calls.append(tc_record)

            try:
                if tool_name == "query_genie":
                    genie_q = arguments.get("question", question)
                    genie_result = await _execute_genie_query(
                        genie_q, host, token, conversation_id,
                    )
                    # Update conversation_id for follow-ups
                    if genie_result.get("conversation_id"):
                        conversation_id = genie_result["conversation_id"]
                    sources.append("genie")

                    # Build a text summary for the LLM
                    genie_text = genie_result.get("text", "")
                    if genie_result.get("data"):
                        cols = genie_result.get("columns", [])
                        rows = genie_result["data"][:20]  # Limit rows for LLM context
                        table_str = " | ".join(cols) + "\n"
                        for row in rows:
                            table_str += " | ".join(str(c) for c in row) + "\n"
                        tool_result = f"{genie_text}\n\nSQL: {genie_result.get('sql', 'N/A')}\n\nResults ({genie_result.get('row_count', 0)} rows):\n{table_str}"
                    else:
                        tool_result = genie_text or "No results from Genie."

                elif tool_name in _TOOL_NAMES:
                    tool_result = await _execute_mcp_tool(tool_name, arguments)
                    sources.append(f"mcp:{tool_name}")

                else:
                    tool_result = json.dumps({"error": f"Unknown tool: {tool_name}"})

            except HTTPException as e:
                tool_result = json.dumps({"error": e.detail})
                logger.warning(f"Tool {tool_name} failed: {e.detail}")
            except Exception as e:
                tool_result = json.dumps({"error": str(e)})
                logger.exception(f"Tool {tool_name} failed")

            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": tool_result,
            })

    # If we exhausted all rounds, take the last LLM response
    return AssistantResponse(
        conversation_id=conversation_id,
        answer="I gathered data but ran out of processing rounds. Here's what I found so far.",
        sources=sources,
        tool_calls=all_tool_calls if all_tool_calls else None,
    )


# --- API Endpoints ---


@assistant_router.post("/ask", response_model=AssistantResponse)
async def ask_assistant(body: AskRequest, request: Request):
    """Start a new assistant conversation."""
    try:
        return await _run_assistant(body.question, request)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Assistant ask failed")
        return AssistantResponse(
            answer="The assistant encountered an error. Please try again.",
            error=str(e),
        )


@assistant_router.post("/followup", response_model=AssistantResponse)
async def followup_assistant(body: FollowupRequest, request: Request):
    """Continue an existing assistant conversation."""
    try:
        return await _run_assistant(body.question, request, conversation_id=body.conversation_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Assistant followup failed")
        return AssistantResponse(
            conversation_id=body.conversation_id,
            answer="The assistant encountered an error. Please try again.",
            error=str(e),
        )

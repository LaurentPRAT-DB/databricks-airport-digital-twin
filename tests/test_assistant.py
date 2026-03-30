"""Tests for the unified assistant (LLM-powered Genie + MCP router)."""

import json
import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.backend.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _make_llm_response(content: str = "", tool_calls: list | None = None) -> dict:
    """Build a mock LLM chat completion response."""
    message: dict = {"role": "assistant"}
    if tool_calls:
        message["tool_calls"] = tool_calls
        message["content"] = None
        finish_reason = "tool_calls"
    else:
        message["content"] = content
        finish_reason = "stop"
    return {"choices": [{"message": message, "finish_reason": finish_reason}]}


def _make_tool_call(name: str, arguments: dict, call_id: str = "tc_1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


class TestAssistantEndpoints:
    """Test the /api/assistant/ask and /followup endpoints exist and respond."""

    def test_ask_endpoint_exists(self, client):
        """POST /api/assistant/ask returns a response (may fail LLM call but endpoint is routed)."""
        # With mocked LLM, should work
        with patch("app.backend.api.assistant._call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = _make_llm_response("The weather is sunny at 22C.")
            resp = client.post("/api/assistant/ask", json={"question": "What is the weather?"})
        assert resp.status_code == 200
        data = resp.json()
        assert "answer" in data
        assert data["answer"] == "The weather is sunny at 22C."

    def test_followup_endpoint_exists(self, client):
        with patch("app.backend.api.assistant._call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = _make_llm_response("Here are the details.")
            resp = client.post("/api/assistant/followup", json={
                "conversation_id": "test-conv-123",
                "question": "Tell me more",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["answer"] == "Here are the details."

    def test_missing_question_returns_422(self, client):
        resp = client.post("/api/assistant/ask", json={})
        assert resp.status_code == 422


class TestAssistantRouting:
    """Test that the LLM routes to the correct tools."""

    def test_mcp_tool_routing(self, client):
        """When LLM calls get_weather, the response includes mcp:get_weather source."""
        call1_resp = _make_llm_response(tool_calls=[
            _make_tool_call("get_weather", {}),
        ])
        call2_resp = _make_llm_response("The current weather is clear skies, 18C.")

        call_count = 0

        async def mock_llm(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return call1_resp if call_count == 1 else call2_resp

        with patch("app.backend.api.assistant._call_llm", side_effect=mock_llm):
            resp = client.post("/api/assistant/ask", json={"question": "What is the weather?"})

        assert resp.status_code == 200
        data = resp.json()
        assert "mcp:get_weather" in data["sources"]
        assert data["answer"] == "The current weather is clear skies, 18C."
        assert data["tool_calls"] is not None
        assert any(tc["name"] == "get_weather" for tc in data["tool_calls"])

    def test_genie_tool_routing(self, client):
        """When LLM calls query_genie, the response includes genie source."""
        call1_resp = _make_llm_response(tool_calls=[
            _make_tool_call("query_genie", {"question": "average delay last week"}),
        ])
        call2_resp = _make_llm_response("The average delay last week was 12 minutes.")

        call_count = 0

        async def mock_llm(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return call1_resp if call_count == 1 else call2_resp

        mock_genie = AsyncMock(return_value={
            "conversation_id": "genie-conv-1",
            "text": "Average delay: 12 minutes",
            "sql": "SELECT AVG(delay) FROM flights WHERE date > ...",
            "columns": ["avg_delay"],
            "data": [["12"]],
            "row_count": 1,
            "status": "COMPLETED",
        })

        with (
            patch("app.backend.api.assistant._call_llm", side_effect=mock_llm),
            patch("app.backend.api.assistant._execute_genie_query", mock_genie),
        ):
            resp = client.post("/api/assistant/ask", json={
                "question": "What was the average delay last week?",
            })

        assert resp.status_code == 200
        data = resp.json()
        assert "genie" in data["sources"]
        assert data["sql"] == "SELECT AVG(delay) FROM flights WHERE date > ..."
        assert data["conversation_id"] == "genie-conv-1"

    def test_no_tool_calls_direct_response(self, client):
        """When LLM responds directly without tools, no sources."""
        with patch("app.backend.api.assistant._call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = _make_llm_response("Hello! I'm the airport assistant.")
            resp = client.post("/api/assistant/ask", json={"question": "Hello"})

        data = resp.json()
        assert data["sources"] == []
        assert data["tool_calls"] is None
        assert "Hello" in data["answer"]


class TestAssistantErrorHandling:
    """Test error handling in the assistant."""

    def test_llm_failure_returns_graceful_error(self, client):
        """If LLM endpoint is unreachable, return a user-friendly error."""
        with patch("app.backend.api.assistant._call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = Exception("Connection refused")
            resp = client.post("/api/assistant/ask", json={"question": "test"})

        assert resp.status_code == 200  # Graceful error, not 500
        data = resp.json()
        assert "error" in data["answer"].lower() or data["error"] is not None

    def test_empty_llm_response(self, client):
        """If LLM returns empty choices, handle gracefully."""
        with patch("app.backend.api.assistant._call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = {"choices": []}
            resp = client.post("/api/assistant/ask", json={"question": "test"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["answer"]  # Should have some fallback text

    def test_max_rounds_limit(self, client):
        """Verify assistant doesn't loop forever with continuous tool calls."""
        # LLM always returns a tool call — should stop after MAX_TOOL_ROUNDS
        tool_resp = _make_llm_response(tool_calls=[
            _make_tool_call("get_weather", {}),
        ])

        with patch("app.backend.api.assistant._call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = tool_resp
            resp = client.post("/api/assistant/ask", json={"question": "weather loop test"})

        assert resp.status_code == 200
        data = resp.json()
        # Should have called the tool MAX_TOOL_ROUNDS times
        assert len(data.get("tool_calls", [])) <= 3 * 1  # max 3 rounds, 1 tool per round


class TestAssistantResponseFormat:
    """Test response format and fields."""

    def test_response_has_all_fields(self, client):
        with patch("app.backend.api.assistant._call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = _make_llm_response("Test answer.")
            resp = client.post("/api/assistant/ask", json={"question": "test"})

        data = resp.json()
        assert "answer" in data
        assert "sources" in data
        assert "sql" in data
        assert "columns" in data
        assert "data" in data
        assert "row_count" in data
        assert "tool_calls" in data
        assert "conversation_id" in data

    def test_function_definitions_include_all_mcp_tools_plus_genie(self, client):
        """Verify _build_function_definitions returns 13 MCP tools + query_genie."""
        from app.backend.api.assistant import _build_function_definitions
        funcs = _build_function_definitions()
        names = [f["function"]["name"] for f in funcs]
        assert "query_genie" in names
        assert "get_flights" in names
        assert "get_weather" in names
        assert "get_delay_predictions" in names
        assert len(funcs) == 14  # 13 MCP + 1 query_genie

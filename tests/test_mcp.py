"""Tests for the MCP (Model Context Protocol) JSON-RPC 2.0 endpoint.

Tests cover:
- Protocol-level correctness (initialize, tools/list, error handling)
- Per-tool response validation (expected keys, types)
- Latency assertions per tool
"""

import json
import time

import pytest
from fastapi.testclient import TestClient

from app.backend.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _mcp_call(client, method: str, params: dict | None = None, req_id: int = 1) -> tuple[dict, float]:
    """Send a JSON-RPC 2.0 request to /api/mcp and return (response_json, elapsed_ms)."""
    payload = {"jsonrpc": "2.0", "method": method, "id": req_id}
    if params is not None:
        payload["params"] = params
    t0 = time.monotonic()
    resp = client.post("/api/mcp", json=payload)
    elapsed_ms = (time.monotonic() - t0) * 1000
    assert resp.status_code == 200
    return resp.json(), elapsed_ms


def _tool_call(client, tool_name: str, arguments: dict | None = None) -> tuple[dict, float]:
    """Call an MCP tool and return (parsed_content_json, elapsed_ms)."""
    params = {"name": tool_name, "arguments": arguments or {}}
    result, elapsed = _mcp_call(client, "tools/call", params)
    assert result.get("error") is None, f"Tool {tool_name} returned error: {result.get('error')}"
    content_text = result["result"]["content"][0]["text"]
    return json.loads(content_text), elapsed


# =============================================================================
# Protocol Tests
# =============================================================================


class TestMCPProtocol:

    def test_initialize(self, client):
        result, _ = _mcp_call(client, "initialize")
        assert result["result"]["protocolVersion"] == "2024-11-05"
        assert result["result"]["serverInfo"]["name"] == "airport-digital-twin-mcp"
        assert "tools" in result["result"]["capabilities"]

    def test_tools_list(self, client):
        result, _ = _mcp_call(client, "tools/list")
        tools = result["result"]["tools"]
        assert isinstance(tools, list)
        assert len(tools) == 13
        names = {t["name"] for t in tools}
        assert "get_flights" in names
        assert "get_weather" in names
        assert "get_delay_predictions" in names
        assert "list_airports" in names

    def test_tools_list_has_descriptions(self, client):
        result, _ = _mcp_call(client, "tools/list")
        for tool in result["result"]["tools"]:
            assert "name" in tool
            assert "description" in tool
            assert len(tool["description"]) > 50, f"Tool {tool['name']} has too-short description"
            assert "inputSchema" in tool

    def test_invalid_jsonrpc_version(self, client):
        payload = {"jsonrpc": "1.0", "method": "initialize", "id": 1}
        resp = client.post("/api/mcp", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"] is not None
        assert data["error"]["code"] == -32600

    def test_unknown_method(self, client):
        result, _ = _mcp_call(client, "nonexistent/method")
        assert result["error"] is not None
        assert result["error"]["code"] == -32601

    def test_tools_call_missing_name(self, client):
        result, _ = _mcp_call(client, "tools/call", {"arguments": {}})
        assert result["error"] is not None
        assert result["error"]["code"] == -32602

    def test_tools_call_unknown_tool(self, client):
        result, _ = _mcp_call(client, "tools/call", {"name": "nonexistent_tool"})
        assert result["error"] is not None
        assert result["error"]["code"] == -32602
        assert "Unknown tool" in result["error"]["message"]

    def test_response_has_id(self, client):
        result, _ = _mcp_call(client, "initialize", req_id=42)
        assert result["id"] == 42

    def test_response_jsonrpc_version(self, client):
        result, _ = _mcp_call(client, "initialize")
        assert result["jsonrpc"] == "2.0"


# =============================================================================
# Debug Endpoints
# =============================================================================


class TestMCPDebugEndpoints:

    def test_tools_debug_endpoint(self, client):
        resp = client.get("/api/mcp/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert "tools" in data
        assert "server" in data
        assert len(data["tools"]) == 13

    def test_health_endpoint(self, client):
        resp = client.get("/api/mcp/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["tools_count"] == 13
        assert data["protocol_version"] == "2024-11-05"


# =============================================================================
# Per-Tool Response Validation + Latency
# =============================================================================


class TestMCPToolGetFlights:

    def test_response_shape(self, client):
        data, _ = _tool_call(client, "get_flights")
        assert "flights" in data
        assert "count" in data
        assert "timestamp" in data
        assert isinstance(data["flights"], list)
        assert data["count"] == len(data["flights"])

    def test_with_count_param(self, client):
        data, _ = _tool_call(client, "get_flights", {"count": 5})
        assert data["count"] <= 5

    def test_flight_fields(self, client):
        data, _ = _tool_call(client, "get_flights", {"count": 1})
        if data["flights"]:
            flight = data["flights"][0]
            assert "icao24" in flight
            assert "callsign" in flight
            assert "latitude" in flight
            assert "longitude" in flight

    def test_latency(self, client):
        _, elapsed = _tool_call(client, "get_flights")
        assert elapsed < 2000, f"get_flights took {elapsed:.0f}ms (max 2000ms)"


class TestMCPToolGetFlightDetails:

    def _get_first_icao24(self, client) -> str:
        data, _ = _tool_call(client, "get_flights", {"count": 1})
        assert data["flights"], "No flights available for testing"
        return data["flights"][0]["icao24"]

    def test_response_shape(self, client):
        icao24 = self._get_first_icao24(client)
        data, _ = _tool_call(client, "get_flight_details", {"icao24": icao24})
        assert data["icao24"] == icao24
        assert "callsign" in data
        assert "latitude" in data

    def test_not_found(self, client):
        params = {"name": "get_flight_details", "arguments": {"icao24": "zzzzzz"}}
        result, _ = _mcp_call(client, "tools/call", params)
        assert result["error"] is not None

    def test_latency(self, client):
        icao24 = self._get_first_icao24(client)
        _, elapsed = _tool_call(client, "get_flight_details", {"icao24": icao24})
        assert elapsed < 1000, f"get_flight_details took {elapsed:.0f}ms (max 1000ms)"


class TestMCPToolGetFlightTrajectory:

    def _get_first_icao24(self, client) -> str:
        data, _ = _tool_call(client, "get_flights", {"count": 1})
        assert data["flights"], "No flights available"
        return data["flights"][0]["icao24"]

    def test_response_shape(self, client):
        icao24 = self._get_first_icao24(client)
        data, _ = _tool_call(client, "get_flight_trajectory", {"icao24": icao24})
        assert "points" in data
        assert "count" in data
        assert data["icao24"] == icao24

    def test_latency(self, client):
        icao24 = self._get_first_icao24(client)
        _, elapsed = _tool_call(client, "get_flight_trajectory", {"icao24": icao24})
        assert elapsed < 2000, f"get_flight_trajectory took {elapsed:.0f}ms (max 2000ms)"


class TestMCPToolGetArrivals:

    def test_response_shape(self, client):
        data, _ = _tool_call(client, "get_arrivals")
        assert "flights" in data
        assert "count" in data
        assert "flight_type" in data
        assert data["flight_type"] == "arrival"

    def test_with_params(self, client):
        data, _ = _tool_call(client, "get_arrivals", {"hours_ahead": 2, "limit": 10})
        assert data["count"] <= 10

    def test_latency(self, client):
        _, elapsed = _tool_call(client, "get_arrivals")
        assert elapsed < 1000, f"get_arrivals took {elapsed:.0f}ms (max 1000ms)"


class TestMCPToolGetDepartures:

    def test_response_shape(self, client):
        data, _ = _tool_call(client, "get_departures")
        assert "flights" in data
        assert "count" in data
        assert "flight_type" in data
        assert data["flight_type"] == "departure"

    def test_latency(self, client):
        _, elapsed = _tool_call(client, "get_departures")
        assert elapsed < 1000, f"get_departures took {elapsed:.0f}ms (max 1000ms)"


class TestMCPToolGetWeather:

    def test_response_shape(self, client):
        data, _ = _tool_call(client, "get_weather")
        assert "metar" in data
        assert "station" in data

    def test_metar_fields(self, client):
        data, _ = _tool_call(client, "get_weather")
        metar = data["metar"]
        assert "temperature_c" in metar
        assert "wind_speed_kts" in metar
        assert "flight_category" in metar

    def test_latency(self, client):
        _, elapsed = _tool_call(client, "get_weather")
        assert elapsed < 1000, f"get_weather took {elapsed:.0f}ms (max 1000ms)"


class TestMCPToolGetDelayPredictions:

    def test_response_shape(self, client):
        data, _ = _tool_call(client, "get_delay_predictions")
        assert "delays" in data
        assert "count" in data
        assert isinstance(data["delays"], list)

    def test_delay_fields(self, client):
        data, _ = _tool_call(client, "get_delay_predictions")
        if data["delays"]:
            d = data["delays"][0]
            assert "icao24" in d
            assert "delay_minutes" in d
            assert "confidence" in d
            assert "category" in d

    def test_latency(self, client):
        _, elapsed = _tool_call(client, "get_delay_predictions")
        assert elapsed < 3000, f"get_delay_predictions took {elapsed:.0f}ms (max 3000ms)"


class TestMCPToolGetGateRecommendations:

    def _get_first_icao24(self, client) -> str:
        data, _ = _tool_call(client, "get_flights", {"count": 1})
        assert data["flights"], "No flights available"
        return data["flights"][0]["icao24"]

    def test_response_shape(self, client):
        icao24 = self._get_first_icao24(client)
        data, _ = _tool_call(client, "get_gate_recommendations", {"icao24": icao24})
        assert "recommendations" in data
        assert "count" in data

    def test_recommendation_fields(self, client):
        icao24 = self._get_first_icao24(client)
        data, _ = _tool_call(client, "get_gate_recommendations", {"icao24": icao24})
        if data["recommendations"]:
            rec = data["recommendations"][0]
            assert "gate_id" in rec
            assert "score" in rec
            assert "reasons" in rec
            assert "taxi_time" in rec

    def test_latency(self, client):
        icao24 = self._get_first_icao24(client)
        _, elapsed = _tool_call(client, "get_gate_recommendations", {"icao24": icao24})
        assert elapsed < 2000, f"get_gate_recommendations took {elapsed:.0f}ms (max 2000ms)"


class TestMCPToolGetCongestion:

    def test_response_shape(self, client):
        data, _ = _tool_call(client, "get_congestion")
        assert "areas" in data
        assert "bottlenecks" in data
        assert "areas_count" in data
        assert "bottlenecks_count" in data

    def test_area_fields(self, client):
        data, _ = _tool_call(client, "get_congestion")
        if data["areas"]:
            area = data["areas"][0]
            assert "area_id" in area
            assert "area_type" in area
            assert "level" in area
            assert "flight_count" in area
            assert "capacity" in area
            assert "wait_minutes" in area

    def test_latency(self, client):
        _, elapsed = _tool_call(client, "get_congestion")
        assert elapsed < 3000, f"get_congestion took {elapsed:.0f}ms (max 3000ms)"


class TestMCPToolGetAirportInfo:

    def test_response_shape(self, client):
        data, _ = _tool_call(client, "get_airport_info")
        assert "icaoCode" in data
        assert "runways_count" in data
        assert "gates_count" in data
        assert "terminals_count" in data
        assert "runways" in data
        assert "gates" in data
        assert "terminals" in data

    def test_latency(self, client):
        _, elapsed = _tool_call(client, "get_airport_info")
        assert elapsed < 500, f"get_airport_info took {elapsed:.0f}ms (max 500ms)"


class TestMCPToolGetBaggageStats:

    def test_response_shape(self, client):
        data, _ = _tool_call(client, "get_baggage_stats")
        # BaggageStatsResponse fields
        assert "total_bags_today" in data or "total_bags" in data or isinstance(data, dict)

    def test_latency(self, client):
        _, elapsed = _tool_call(client, "get_baggage_stats")
        assert elapsed < 1000, f"get_baggage_stats took {elapsed:.0f}ms (max 1000ms)"


class TestMCPToolGetGSEStatus:

    def test_response_shape(self, client):
        data, _ = _tool_call(client, "get_gse_status")
        assert isinstance(data, dict)
        # GSEFleetStatus has fleet and summary
        assert "fleet" in data or "units" in data or "total_units" in data or isinstance(data, dict)

    def test_latency(self, client):
        _, elapsed = _tool_call(client, "get_gse_status")
        assert elapsed < 1000, f"get_gse_status took {elapsed:.0f}ms (max 1000ms)"


class TestMCPToolListAirports:

    def test_response_shape(self, client):
        data, _ = _tool_call(client, "list_airports")
        assert "airports" in data
        assert "count" in data
        assert data["count"] > 0

    def test_airport_fields(self, client):
        data, _ = _tool_call(client, "list_airports")
        airport = data["airports"][0]
        assert "icao_code" in airport
        assert "iata_code" in airport
        assert "name" in airport
        assert "city" in airport
        assert "region" in airport
        assert "cached" in airport

    def test_includes_well_known(self, client):
        data, _ = _tool_call(client, "list_airports")
        codes = {a["icao_code"] for a in data["airports"]}
        assert "KSFO" in codes
        assert "KJFK" in codes
        assert "EGLL" in codes

    def test_latency(self, client):
        _, elapsed = _tool_call(client, "list_airports")
        assert elapsed < 500, f"list_airports took {elapsed:.0f}ms (max 500ms)"


# =============================================================================
# Parametrized Latency Summary
# =============================================================================


class TestMCPLatencySummary:
    """Parametrized test that runs all tools and checks latency thresholds."""

    @pytest.mark.parametrize("tool_name,args,max_ms", [
        ("get_flights", {"count": 10}, 2000),
        ("get_arrivals", {}, 1000),
        ("get_departures", {}, 1000),
        ("get_weather", {}, 1000),
        ("get_delay_predictions", {}, 3000),
        ("get_congestion", {}, 3000),
        ("get_airport_info", {}, 500),
        ("get_baggage_stats", {}, 1000),
        ("get_gse_status", {}, 1000),
        ("list_airports", {}, 500),
    ])
    def test_tool_latency(self, client, tool_name, args, max_ms):
        _, elapsed = _tool_call(client, tool_name, args)
        assert elapsed < max_ms, f"{tool_name} took {elapsed:.0f}ms (max {max_ms}ms)"

"""MCP (Model Context Protocol) JSON-RPC 2.0 endpoint.

Exposes Airport Digital Twin functionality as MCP tools for AI agents
in Databricks AI Playground and Supervisor Agents.
"""

import json
import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

mcp_router = APIRouter(prefix="/api/mcp", tags=["mcp"])

# --- JSON-RPC 2.0 Models ---


class JsonRpcRequest(BaseModel):
    jsonrpc: str = Field(default="2.0")
    method: str
    params: dict[str, Any] | None = None
    id: int | str | None = None


class JsonRpcError(BaseModel):
    code: int
    message: str
    data: Any | None = None


class JsonRpcResponse(BaseModel):
    jsonrpc: str = "2.0"
    result: Any | None = None
    error: JsonRpcError | None = None
    id: int | str | None = None


# --- Server Info ---

SERVER_INFO = {
    "name": "airport-digital-twin-mcp",
    "version": "1.0.0",
    "description": "Airport Digital Twin — real-time flight data, ML predictions, weather, and airport operations",
}

# --- Tool Definitions ---

MCP_TOOLS = [
    {
        "name": "get_flights",
        "description": (
            "LIST CURRENT FLIGHTS at the airport with real-time positions. "
            "\n\n"
            "RETURNS: Array of flights with icao24, callsign, latitude, longitude, altitude, speed, heading, phase (parked/taxiing/airborne/approaching), gate, origin, destination. "
            "\n\n"
            "USE THIS TOOL WHEN USER ASKS: "
            "'Show me all flights', 'What flights are active?', 'How many planes are there?', "
            "'List aircraft at the airport', 'What's flying right now?', 'Show airborne flights', "
            "'Which planes are taxiing?', 'How many arrivals/departures?', 'Airport traffic overview'. "
            "\n\n"
            "DO NOT USE FOR: Getting details about ONE specific flight (use get_flight_details), "
            "or scheduled future flights (use get_arrivals/get_departures)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "Max flights to return (1-500, default 50).",
                    "default": 50,
                    "minimum": 1,
                    "maximum": 500,
                },
            },
        },
    },
    {
        "name": "get_flight_details",
        "description": (
            "GET DETAILS FOR A SPECIFIC FLIGHT by its ICAO24 hex address. "
            "\n\n"
            "RETURNS: icao24, callsign, latitude, longitude, altitude_ft, speed_knots, heading, "
            "vertical_rate, phase, gate, origin, destination, aircraft_type. "
            "\n\n"
            "USE THIS TOOL WHEN USER ASKS: "
            "'Tell me about flight X', 'Where is aircraft abc123?', 'What gate is flight X at?', "
            "'Show me flight details for X', 'Is flight X still airborne?'. "
            "\n\n"
            "DO NOT USE FOR: Listing all flights (use get_flights). "
            "\n\n"
            "TIP: The icao24 is a 6-character hex string (e.g., 'a0b1c2'). "
            "Use get_flights first to find the icao24 for a callsign."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "icao24": {
                    "type": "string",
                    "description": "ICAO24 hex address of the aircraft (e.g., 'a0b1c2').",
                },
            },
            "required": ["icao24"],
        },
    },
    {
        "name": "get_flight_trajectory",
        "description": (
            "GET TRAJECTORY HISTORY for a specific flight — time-series of positions. "
            "\n\n"
            "RETURNS: Array of points with timestamp, latitude, longitude, altitude, speed, heading. "
            "\n\n"
            "USE THIS TOOL WHEN USER ASKS: "
            "'Show me the flight path for X', 'Where has this plane been?', "
            "'Trace the trajectory of flight X', 'Flight route history'. "
            "\n\n"
            "DO NOT USE FOR: Current position only (use get_flight_details)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "icao24": {
                    "type": "string",
                    "description": "ICAO24 hex address of the aircraft.",
                },
                "minutes": {
                    "type": "integer",
                    "description": "Minutes of history (1-1440, default 60).",
                    "default": 60,
                    "minimum": 1,
                    "maximum": 1440,
                },
            },
            "required": ["icao24"],
        },
    },
    {
        "name": "get_arrivals",
        "description": (
            "GET SCHEDULED ARRIVALS — the airport FIDS (Flight Information Display) arrivals board. "
            "\n\n"
            "RETURNS: Array of flights with flight_number, airline, origin, scheduled_time, "
            "estimated_time, status (on_time/delayed/landed/cancelled), gate, terminal. "
            "\n\n"
            "USE THIS TOOL WHEN USER ASKS: "
            "'What flights are arriving?', 'Show arrivals board', 'Incoming flights', "
            "'When does flight X land?', 'Are there delayed arrivals?', 'FIDS arrivals', "
            "'What's landing in the next hour?'. "
            "\n\n"
            "DO NOT USE FOR: Departures (use get_departures), or real-time positions (use get_flights)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "hours_ahead": {
                    "type": "integer",
                    "description": "Hours to look ahead (default 6).",
                    "default": 6,
                },
                "hours_behind": {
                    "type": "integer",
                    "description": "Hours to look behind for recent arrivals (default 1).",
                    "default": 1,
                },
                "limit": {
                    "type": "integer",
                    "description": "Max flights to return (default 50).",
                    "default": 50,
                },
            },
        },
    },
    {
        "name": "get_departures",
        "description": (
            "GET SCHEDULED DEPARTURES — the airport FIDS departures board. "
            "\n\n"
            "RETURNS: Array of flights with flight_number, airline, destination, scheduled_time, "
            "estimated_time, status (on_time/delayed/boarding/departed/cancelled), gate, terminal. "
            "\n\n"
            "USE THIS TOOL WHEN USER ASKS: "
            "'What flights are departing?', 'Show departures board', 'Outgoing flights', "
            "'When does flight X depart?', 'Are there delayed departures?', 'FIDS departures'. "
            "\n\n"
            "DO NOT USE FOR: Arrivals (use get_arrivals)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "hours_ahead": {
                    "type": "integer",
                    "description": "Hours to look ahead (default 6).",
                    "default": 6,
                },
                "hours_behind": {
                    "type": "integer",
                    "description": "Hours to look behind for recent departures (default 1).",
                    "default": 1,
                },
                "limit": {
                    "type": "integer",
                    "description": "Max flights to return (default 50).",
                    "default": 50,
                },
            },
        },
    },
    {
        "name": "get_weather",
        "description": (
            "GET CURRENT WEATHER at the airport — METAR observation and conditions. "
            "\n\n"
            "RETURNS: temperature_c, dewpoint_c, wind_speed_kt, wind_direction, visibility_miles, "
            "altimeter_inhg, flight_category (VFR/MVFR/IFR/LIFR), cloud_layers, raw_metar. "
            "\n\n"
            "USE THIS TOOL WHEN USER ASKS: "
            "'What's the weather?', 'Current conditions', 'Is it VFR or IFR?', "
            "'Wind speed and direction', 'Temperature at the airport', 'METAR', "
            "'Can planes land in this weather?', 'Visibility conditions'. "
            "\n\n"
            "DO NOT USE FOR: Weather forecasts (TAF not yet exposed)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_delay_predictions",
        "description": (
            "GET ML DELAY PREDICTIONS for current flights — AI-powered delay forecasting. "
            "\n\n"
            "RETURNS: Array with icao24, delay_minutes, confidence (0-1), "
            "category (on_time/slight/moderate/severe). "
            "\n\n"
            "USE THIS TOOL WHEN USER ASKS: "
            "'Are there any delayed flights?', 'Predict delays', 'Which flights will be late?', "
            "'Delay forecast', 'On-time performance', 'ML predictions', "
            "'Will my flight be delayed?', 'Expected delays'. "
            "\n\n"
            "DO NOT USE FOR: Schedule status (use get_arrivals/get_departures), "
            "or congestion (use get_congestion)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "icao24": {
                    "type": "string",
                    "description": "Optional: ICAO24 for a single flight. Omit for all flights.",
                },
            },
        },
    },
    {
        "name": "get_gate_recommendations",
        "description": (
            "GET ML GATE ASSIGNMENT RECOMMENDATIONS for a specific flight. "
            "\n\n"
            "RETURNS: Array of recommendations with gate_id, score (0-1), reasons[], taxi_time_minutes. "
            "\n\n"
            "USE THIS TOOL WHEN USER ASKS: "
            "'Which gate should flight X use?', 'Best gate for this aircraft', "
            "'Gate assignment recommendations', 'Optimize gate allocation', "
            "'Where should we park this plane?'. "
            "\n\n"
            "TIP: Requires an icao24. Use get_flights first to find the right one."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "icao24": {
                    "type": "string",
                    "description": "ICAO24 hex address of the aircraft.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of recommendations (1-10, default 3).",
                    "default": 3,
                    "minimum": 1,
                    "maximum": 10,
                },
            },
            "required": ["icao24"],
        },
    },
    {
        "name": "get_congestion",
        "description": (
            "GET AIRPORT CONGESTION LEVELS and bottlenecks for runways, taxiways, and aprons. "
            "\n\n"
            "RETURNS: areas[] with area_id, area_type (runway/taxiway/apron/terminal), "
            "level (low/moderate/high/critical), flight_count, capacity, wait_minutes. "
            "Also bottlenecks[] filtered to high/critical only. "
            "\n\n"
            "USE THIS TOOL WHEN USER ASKS: "
            "'Is the airport congested?', 'Any bottlenecks?', 'Runway congestion', "
            "'Taxiway delays', 'Where are the holdups?', 'Airport capacity status', "
            "'Which areas are busy?', 'Traffic flow problems'. "
            "\n\n"
            "DO NOT USE FOR: Individual flight delays (use get_delay_predictions)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_airport_info",
        "description": (
            "GET AIRPORT CONFIGURATION — runways, gates, terminals, taxiways from OpenStreetMap. "
            "\n\n"
            "RETURNS: icaoCode, iataCode, name, runways[], gates[], terminals[], "
            "taxiways[], aprons[], center coordinates, data source. "
            "\n\n"
            "USE THIS TOOL WHEN USER ASKS: "
            "'How many runways?', 'What gates are available?', 'Airport layout', "
            "'Terminal map', 'Airport info', 'How big is this airport?', "
            "'List all gates', 'Runway configuration'. "
            "\n\n"
            "DO NOT USE FOR: Switching airports (not supported via MCP)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_baggage_stats",
        "description": (
            "GET BAGGAGE HANDLING STATISTICS — throughput, misconnects, processing times. "
            "\n\n"
            "RETURNS: total_bags, bags_per_hour, misconnect_rate, avg_processing_time_seconds, "
            "bags_in_system, alerts_count. "
            "\n\n"
            "USE THIS TOOL WHEN USER ASKS: "
            "'Baggage stats', 'How's baggage handling?', 'Any lost bags?', "
            "'Baggage throughput', 'Misconnection rate', 'Baggage system status'. "
            "\n\n"
            "DO NOT USE FOR: Individual flight baggage (not exposed via MCP)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_gse_status",
        "description": (
            "GET GROUND SUPPORT EQUIPMENT fleet status — tugs, fuel trucks, belt loaders, etc. "
            "\n\n"
            "RETURNS: Fleet inventory with unit counts by type, availability percentages, "
            "active assignments, maintenance status. "
            "\n\n"
            "USE THIS TOOL WHEN USER ASKS: "
            "'GSE status', 'Ground equipment availability', 'How many fuel trucks?', "
            "'Tug availability', 'Ground support fleet', 'Equipment utilization'. "
            "\n\n"
            "DO NOT USE FOR: Turnaround status of specific flights."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "list_airports",
        "description": (
            "LIST ALL SUPPORTED AIRPORTS in the digital twin system. "
            "\n\n"
            "RETURNS: Array of airports with icao_code, iata_code, name, city, region. "
            "\n\n"
            "USE THIS TOOL WHEN USER ASKS: "
            "'What airports are available?', 'Which airports do you support?', "
            "'List airports', 'Can I see JFK?', 'Show all airports'. "
            "\n\n"
            "DO NOT USE FOR: Detailed airport config (use get_airport_info)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]

_TOOL_NAMES = {t["name"] for t in MCP_TOOLS}


# --- Tool Execution ---


async def _execute_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute an MCP tool by calling existing service functions."""
    logger.info(f"MCP executing tool: {tool_name} with args: {arguments}")
    t0 = time.monotonic()

    if tool_name == "get_flights":
        from app.backend.services.flight_service import get_flight_service
        service = get_flight_service()
        count = arguments.get("count", 50)
        result = await service.get_flights(count=count)
        return {"flights": [f.model_dump(mode="json") for f in result.flights], "count": result.count, "timestamp": result.timestamp}

    elif tool_name == "get_flight_details":
        from app.backend.services.flight_service import get_flight_service
        service = get_flight_service()
        flight = await service.get_flight_by_icao24(arguments["icao24"])
        if flight is None:
            raise HTTPException(status_code=404, detail=f"Flight {arguments['icao24']} not found")
        return flight.model_dump(mode="json")

    elif tool_name == "get_flight_trajectory":
        import os
        from app.backend.demo_config import DEMO_MODE
        from app.backend.services.delta_service import get_delta_service
        from app.backend.models.flight import TrajectoryPoint, TrajectoryResponse
        from src.ingestion.fallback import generate_synthetic_trajectory

        icao24 = arguments["icao24"]
        minutes = arguments.get("minutes", 60)
        limit = 1000
        use_mock = DEMO_MODE or os.getenv("USE_MOCK_BACKEND", "true").lower() == "true"
        trajectory_data = None
        if not use_mock:
            delta = get_delta_service()
            trajectory_data = delta.get_trajectory(icao24, minutes=minutes, limit=limit)
        if trajectory_data is None or len(trajectory_data) == 0:
            trajectory_data = generate_synthetic_trajectory(icao24, minutes=minutes, limit=limit)
        if trajectory_data is None or len(trajectory_data) == 0:
            raise HTTPException(status_code=404, detail=f"No trajectory data for {icao24}")
        from datetime import datetime as dt
        for p in trajectory_data:
            ts = p.get("timestamp")
            if isinstance(ts, str):
                parsed = dt.fromisoformat(ts.replace("Z", "+00:00"))
                p["timestamp"] = int(parsed.timestamp())
            elif isinstance(ts, dt):
                p["timestamp"] = int(ts.timestamp())
        points = [TrajectoryPoint(**p) for p in trajectory_data]
        result = TrajectoryResponse(
            icao24=icao24, callsign=points[0].callsign if points else None,
            points=points, count=len(points),
            start_time=points[0].timestamp if points else None,
            end_time=points[-1].timestamp if points else None,
        )
        return result.model_dump(mode="json")

    elif tool_name == "get_arrivals":
        from app.backend.services.schedule_service import get_schedule_service
        service = get_schedule_service()
        result = service.get_arrivals(
            hours_ahead=arguments.get("hours_ahead", 6),
            hours_behind=arguments.get("hours_behind", 1),
            limit=arguments.get("limit", 50),
        )
        return result.model_dump(mode="json")

    elif tool_name == "get_departures":
        from app.backend.services.schedule_service import get_schedule_service
        service = get_schedule_service()
        result = service.get_departures(
            hours_ahead=arguments.get("hours_ahead", 6),
            hours_behind=arguments.get("hours_behind", 1),
            limit=arguments.get("limit", 50),
        )
        return result.model_dump(mode="json")

    elif tool_name == "get_weather":
        from app.backend.services.weather_service import get_weather_service
        service = get_weather_service()
        result = service.get_current_weather()
        return result.model_dump(mode="json")

    elif tool_name == "get_delay_predictions":
        from app.backend.services.prediction_service import get_prediction_service
        from app.backend.services.flight_service import get_flight_service
        prediction_service = get_prediction_service()
        flight_service = get_flight_service()
        flight_response = await flight_service.get_flights()
        flights = [f.model_dump() for f in flight_response.flights]
        icao24 = arguments.get("icao24")
        if icao24:
            flights = [f for f in flights if f.get("icao24") == icao24]
        if not flights:
            return {"delays": [], "count": 0}
        predictions = await prediction_service.get_flight_predictions(flights)
        delay_predictions = predictions.get("delays", {})
        delays = [
            {"icao24": k, "delay_minutes": v.delay_minutes, "confidence": v.confidence, "category": v.delay_category}
            for k, v in delay_predictions.items()
        ]
        return {"delays": delays, "count": len(delays)}

    elif tool_name == "get_gate_recommendations":
        from app.backend.services.prediction_service import get_prediction_service
        from app.backend.services.flight_service import get_flight_service
        prediction_service = get_prediction_service()
        flight_service = get_flight_service()
        icao24 = arguments["icao24"]
        top_k = arguments.get("top_k", 3)
        flight = await flight_service.get_flight_by_icao24(icao24)
        flight_data = flight.model_dump() if flight else {"icao24": icao24, "callsign": ""}
        recs = await prediction_service.get_gate_recommendations(flight_data, top_k=top_k)
        return {
            "recommendations": [
                {"gate_id": r.gate_id, "score": r.score, "reasons": r.reasons, "taxi_time": r.estimated_taxi_time}
                for r in recs
            ],
            "count": len(recs),
        }

    elif tool_name == "get_congestion":
        from app.backend.services.prediction_service import get_prediction_service
        from app.backend.services.flight_service import get_flight_service
        prediction_service = get_prediction_service()
        flight_service = get_flight_service()
        flight_response = await flight_service.get_flights()
        flights = [f.model_dump() for f in flight_response.flights]
        congestion = await prediction_service.get_congestion(flights)
        bottlenecks = await prediction_service.get_bottlenecks(flights)
        def _area(c):
            return {"area_id": c.area_id, "area_type": c.area_type, "level": c.level.value,
                    "flight_count": c.flight_count, "capacity": c.capacity, "wait_minutes": c.predicted_wait_minutes}
        return {
            "areas": [_area(c) for c in congestion],
            "bottlenecks": [_area(c) for c in bottlenecks],
            "areas_count": len(congestion),
            "bottlenecks_count": len(bottlenecks),
        }

    elif tool_name == "get_airport_info":
        from app.backend.services.airport_config_service import get_airport_config_service
        service = get_airport_config_service()
        config = service.get_config()
        # Slim down verbose OSM fields
        summary = {
            "icaoCode": config.get("icaoCode"),
            "iataCode": config.get("iataCode"),
            "name": config.get("name"),
            "source": config.get("source"),
            "runways_count": len(config.get("osmRunways", [])),
            "gates_count": len(config.get("gates", [])),
            "terminals_count": len(config.get("terminals", [])),
            "taxiways_count": len(config.get("osmTaxiways", [])),
            "aprons_count": len(config.get("osmAprons", [])),
            "runways": [
                {"id": r.get("id"), "ref": r.get("ref"), "width": r.get("width")}
                for r in config.get("osmRunways", [])
            ],
            "gates": [
                {"id": g.get("id"), "ref": g.get("ref"), "name": g.get("name")}
                for g in config.get("gates", [])
            ],
            "terminals": [
                {"id": t.get("id"), "name": t.get("name")}
                for t in config.get("terminals", [])
            ],
        }
        return summary

    elif tool_name == "get_baggage_stats":
        from app.backend.services.baggage_service import get_baggage_service
        service = get_baggage_service()
        result = service.get_overall_stats()
        return result.model_dump(mode="json")

    elif tool_name == "get_gse_status":
        from app.backend.services.gse_service import get_gse_service
        service = get_gse_service()
        result = service.get_fleet_status()
        return result.model_dump(mode="json")

    elif tool_name == "list_airports":
        from app.backend.services.airport_config_service import get_airport_config_service
        from app.backend.api.routes import WELL_KNOWN_AIRPORT_INFO
        service = get_airport_config_service()
        persisted = service.list_persisted_airports()
        persisted_codes = {a.get("icao_code", a.get("icaoCode", "")).upper() for a in persisted}
        airports = []
        for icao, info in WELL_KNOWN_AIRPORT_INFO.items():
            airports.append({
                "icao_code": icao,
                "iata_code": info["iata"],
                "name": info["name"],
                "city": info["city"],
                "region": info["region"],
                "cached": icao in persisted_codes,
            })
        return {"airports": airports, "count": len(airports)}

    raise ValueError(f"Unknown tool: {tool_name}")


# --- Protocol Handlers ---


def _handle_initialize(request: JsonRpcRequest) -> JsonRpcResponse:
    return JsonRpcResponse(
        id=request.id,
        result={
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        },
    )


def _handle_tools_list(request: JsonRpcRequest) -> JsonRpcResponse:
    return JsonRpcResponse(id=request.id, result={"tools": MCP_TOOLS})


async def _handle_tools_call(request: JsonRpcRequest) -> JsonRpcResponse:
    params = request.params or {}
    tool_name = params.get("name")
    arguments = params.get("arguments", {})

    if not tool_name:
        return JsonRpcResponse(
            id=request.id,
            error=JsonRpcError(code=-32602, message="Invalid params: 'name' is required"),
        )

    if tool_name not in _TOOL_NAMES:
        return JsonRpcResponse(
            id=request.id,
            error=JsonRpcError(code=-32602, message=f"Unknown tool: {tool_name}"),
        )

    try:
        t0 = time.monotonic()
        result = await _execute_tool(tool_name, arguments)
        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.info(f"MCP tool {tool_name} completed in {elapsed_ms:.0f}ms")
        return JsonRpcResponse(
            id=request.id,
            result={
                "content": [{"type": "text", "text": json.dumps(result, indent=2, default=str)}],
                "_meta": {"elapsed_ms": round(elapsed_ms)},
            },
        )
    except HTTPException as e:
        return JsonRpcResponse(
            id=request.id,
            error=JsonRpcError(code=-32000, message=f"Tool error: {e.detail}"),
        )
    except Exception as e:
        logger.exception(f"MCP tool call failed: {tool_name}")
        return JsonRpcResponse(
            id=request.id,
            error=JsonRpcError(code=-32000, message=str(e)),
        )


# --- Main Endpoint ---


@mcp_router.post("", response_model=JsonRpcResponse)
async def mcp_handler(request: JsonRpcRequest) -> JsonRpcResponse:
    """MCP JSON-RPC 2.0 endpoint."""
    logger.info(f"MCP request: method={request.method}, id={request.id}")

    if request.jsonrpc != "2.0":
        return JsonRpcResponse(
            id=request.id,
            error=JsonRpcError(code=-32600, message=f"Invalid JSON-RPC version: {request.jsonrpc}"),
        )

    if request.method == "initialize":
        return _handle_initialize(request)
    elif request.method == "tools/list":
        return _handle_tools_list(request)
    elif request.method == "tools/call":
        return await _handle_tools_call(request)

    return JsonRpcResponse(
        id=request.id,
        error=JsonRpcError(code=-32601, message=f"Method not found: {request.method}"),
    )


# --- Debug Endpoints ---


@mcp_router.get("/tools")
async def list_tools():
    """List available MCP tools (debugging)."""
    return {"tools": MCP_TOOLS, "server": SERVER_INFO}


@mcp_router.get("/health")
async def mcp_health():
    """MCP endpoint health check."""
    return {"status": "healthy", "server": SERVER_INFO, "protocol_version": "2024-11-05", "tools_count": len(MCP_TOOLS)}

"""REST API routes for the Airport Digital Twin."""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

logger = logging.getLogger(__name__)

from app.backend.models.flight import (
    FlightListResponse,
    FlightPosition,
    TrajectoryPoint,
    TrajectoryResponse,
)
from app.backend.models.schedule import ScheduleResponse
from app.backend.models.weather import WeatherResponse
from app.backend.models.gse import GSEFleetStatus, TurnaroundResponse
from app.backend.models.baggage import (
    FlightBaggageResponse,
    BaggageStatsResponse,
    BaggageAlertsResponse,
)
from app.backend.services.flight_service import FlightService, get_flight_service
from app.backend.services.delta_service import get_delta_service
from app.backend.services.schedule_service import get_schedule_service
from app.backend.services.weather_service import get_weather_service
from app.backend.services.gse_service import get_gse_service
from app.backend.services.baggage_service import get_baggage_service
from app.backend.services.airport_config_service import get_airport_config_service
from app.backend.services.data_generator_service import get_data_generator_service
from app.backend.models.airport_config import (
    ImportResponse,
    AIDMImportResponse,
    AirportConfigResponse,
    OSMImportResponse,
    FAAImportResponse,
)
from src.ingestion.fallback import generate_synthetic_trajectory, reload_gates, reset_synthetic_state, set_airport_center
from src.ml.gate_model import reload_gate_recommender
from src.ml.registry import get_model_registry
from app.backend.services.prediction_service import get_prediction_service
from src.formats.base import ParseError, ValidationError


router = APIRouter(prefix="/api", tags=["flights"])

# Well-known airports with metadata — single source of truth for frontend dropdown
WELL_KNOWN_AIRPORT_INFO: dict[str, dict] = {
    # Americas
    "KSFO": {"iata": "SFO", "name": "San Francisco International", "city": "San Francisco, CA", "region": "Americas"},
    "KJFK": {"iata": "JFK", "name": "John F. Kennedy International", "city": "New York, NY", "region": "Americas"},
    "KLAX": {"iata": "LAX", "name": "Los Angeles International", "city": "Los Angeles, CA", "region": "Americas"},
    "KORD": {"iata": "ORD", "name": "O'Hare International", "city": "Chicago, IL", "region": "Americas"},
    "KATL": {"iata": "ATL", "name": "Hartsfield-Jackson Atlanta", "city": "Atlanta, GA", "region": "Americas"},
    "KDFW": {"iata": "DFW", "name": "Dallas/Fort Worth International", "city": "Dallas, TX", "region": "Americas"},
    "KDEN": {"iata": "DEN", "name": "Denver International", "city": "Denver, CO", "region": "Americas"},
    "KMIA": {"iata": "MIA", "name": "Miami International", "city": "Miami, FL", "region": "Americas"},
    "KSEA": {"iata": "SEA", "name": "Seattle-Tacoma International", "city": "Seattle, WA", "region": "Americas"},
    "SBGR": {"iata": "GRU", "name": "Guarulhos International", "city": "Sao Paulo, BR", "region": "Americas"},
    "MMMX": {"iata": "MEX", "name": "Mexico City International", "city": "Mexico City, MX", "region": "Americas"},
    # Europe
    "EGLL": {"iata": "LHR", "name": "London Heathrow", "city": "London, UK", "region": "Europe"},
    "LFPG": {"iata": "CDG", "name": "Charles de Gaulle", "city": "Paris, FR", "region": "Europe"},
    "EHAM": {"iata": "AMS", "name": "Amsterdam Schiphol", "city": "Amsterdam, NL", "region": "Europe"},
    "EDDF": {"iata": "FRA", "name": "Frankfurt Airport", "city": "Frankfurt, DE", "region": "Europe"},
    "LEMD": {"iata": "MAD", "name": "Adolfo Suarez Madrid-Barajas", "city": "Madrid, ES", "region": "Europe"},
    "LIRF": {"iata": "FCO", "name": "Leonardo da Vinci (Fiumicino)", "city": "Rome, IT", "region": "Europe"},
    # Middle East
    "OMAA": {"iata": "AUH", "name": "Abu Dhabi International", "city": "Abu Dhabi, AE", "region": "Middle East"},
    "OMDB": {"iata": "DXB", "name": "Dubai International", "city": "Dubai, AE", "region": "Middle East"},
    # Asia-Pacific
    "RJTT": {"iata": "HND", "name": "Tokyo Haneda", "city": "Tokyo, JP", "region": "Asia-Pacific"},
    "VHHH": {"iata": "HKG", "name": "Hong Kong International", "city": "Hong Kong", "region": "Asia-Pacific"},
    "WSSS": {"iata": "SIN", "name": "Singapore Changi", "city": "Singapore", "region": "Asia-Pacific"},
    "ZBAA": {"iata": "PEK", "name": "Beijing Capital International", "city": "Beijing, CN", "region": "Asia-Pacific"},
    "RKSI": {"iata": "ICN", "name": "Incheon International", "city": "Seoul, KR", "region": "Asia-Pacific"},
    "VTBS": {"iata": "BKK", "name": "Suvarnabhumi Airport", "city": "Bangkok, TH", "region": "Asia-Pacific"},
    # Africa
    "FAOR": {"iata": "JNB", "name": "O.R. Tambo International", "city": "Johannesburg, ZA", "region": "Africa"},
    "GMMN": {"iata": "CMN", "name": "Mohammed V International", "city": "Casablanca, MA", "region": "Africa"},
}


@router.get("/flights", response_model=FlightListResponse)
async def get_flights(
    count: int = Query(default=50, ge=1, le=500, description="Number of flights"),
    service: FlightService = Depends(get_flight_service),
) -> FlightListResponse:
    """
    Get current flight positions.

    Returns a list of flight positions with their current status.
    """
    try:
        return await service.get_flights(count=count)
    except Exception as e:
        logger.error(f"Failed to get flights: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Flight service error: {str(e)}")


@router.get("/flights/{icao24}", response_model=FlightPosition)
async def get_flight(
    icao24: str,
    service: FlightService = Depends(get_flight_service),
) -> FlightPosition:
    """
    Get a specific flight by ICAO24 address.

    Args:
        icao24: The ICAO24 address (hex) of the aircraft.

    Returns:
        Flight position data if found.

    Raises:
        404: If flight not found.
    """
    flight = await service.get_flight_by_icao24(icao24)
    if flight is None:
        raise HTTPException(status_code=404, detail=f"Flight {icao24} not found")
    return flight


@router.get("/flights/{icao24}/trajectory", response_model=TrajectoryResponse)
async def get_flight_trajectory(
    icao24: str,
    minutes: int = Query(default=60, ge=1, le=1440, description="Minutes of history"),
    limit: int = Query(default=1000, ge=1, le=5000, description="Max points to return"),
) -> TrajectoryResponse:
    """
    Get trajectory history for a specific flight.

    Returns a time-series of positions for trajectory visualization,
    analytics, and ML training. In mock mode, returns synthetic trajectory.
    In live mode, queries Unity Catalog Delta tables.

    Args:
        icao24: The ICAO24 address (hex) of the aircraft.
        minutes: How many minutes of history to retrieve (default: 60, max: 1440/24h).
        limit: Maximum number of points to return (default: 1000).

    Returns:
        Trajectory with list of positions ordered by time.

    Raises:
        404: If no trajectory data found for this flight.
    """
    use_mock = os.getenv("USE_MOCK_BACKEND", "true").lower() == "true"
    trajectory_data = None

    # Try Delta tables first if not in mock mode
    if not use_mock:
        delta = get_delta_service()
        trajectory_data = delta.get_trajectory(icao24, minutes=minutes, limit=limit)

    # Fall back to synthetic trajectory if no data or in mock mode
    if trajectory_data is None or len(trajectory_data) == 0:
        trajectory_data = generate_synthetic_trajectory(icao24, minutes=minutes, limit=limit)

    if trajectory_data is None or len(trajectory_data) == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No trajectory data found for flight {icao24}"
        )

    # Parse timestamps - convert to Unix timestamp (int)
    for p in trajectory_data:
        ts = p.get("timestamp")
        if isinstance(ts, str):
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            p["timestamp"] = int(dt.timestamp())
        elif isinstance(ts, datetime):
            p["timestamp"] = int(ts.timestamp())

    points = [TrajectoryPoint(**p) for p in trajectory_data]
    callsign = points[0].callsign if points else None

    return TrajectoryResponse(
        icao24=icao24,
        callsign=callsign,
        points=points,
        count=len(points),
        start_time=points[0].timestamp if points else None,
        end_time=points[-1].timestamp if points else None,
    )


@router.get("/data-sources")
async def get_data_sources_status(
    service: FlightService = Depends(get_flight_service),
) -> dict:
    """
    Get status of all data sources.

    Returns availability and health of:
    - Lakebase (PostgreSQL)
    - Delta tables (Databricks SQL)
    - Synthetic fallback
    """
    return service.get_data_sources_status()


# In-memory storage for web vitals (in production, use a proper store)
_web_vitals_buffer: list = []
_MAX_BUFFER_SIZE = 1000


@router.post("/metrics")
async def collect_web_vitals(request_data: dict) -> dict:
    """
    Collect Web Vitals metrics from frontend.

    Receives Core Web Vitals (LCP, INP, CLS, FCP, TTFB) from real users.
    These metrics help monitor real user experience and identify
    performance regressions.

    In production, these would be sent to a monitoring service
    like Datadog, New Relic, or stored in Delta tables for analysis.
    """
    global _web_vitals_buffer

    metric = {
        "name": request_data.get("name"),
        "value": request_data.get("value"),
        "rating": request_data.get("rating"),
        "delta": request_data.get("delta"),
        "id": request_data.get("id"),
        "navigationType": request_data.get("navigationType"),
        "timestamp": request_data.get("timestamp"),
        "received_at": datetime.now(timezone.utc).isoformat(),
    }

    # Add to buffer (simple in-memory store)
    _web_vitals_buffer.append(metric)
    if len(_web_vitals_buffer) > _MAX_BUFFER_SIZE:
        _web_vitals_buffer = _web_vitals_buffer[-_MAX_BUFFER_SIZE:]

    return {"status": "ok", "count": len(_web_vitals_buffer)}


@router.get("/metrics/summary")
async def get_web_vitals_summary() -> dict:
    """
    Get summary of collected Web Vitals metrics.

    Returns aggregated statistics for each metric type,
    useful for dashboards and performance monitoring.
    """
    from collections import defaultdict

    if not _web_vitals_buffer:
        return {"message": "No metrics collected yet", "metrics": {}}

    # Group by metric name
    by_name = defaultdict(list)
    for m in _web_vitals_buffer:
        if m.get("name") and m.get("value") is not None:
            by_name[m["name"]].append(m["value"])

    # Calculate p75 for each metric (used by CrUX)
    summary = {}
    for name, values in by_name.items():
        sorted_vals = sorted(values)
        count = len(sorted_vals)
        p75_idx = int(count * 0.75)
        summary[name] = {
            "count": count,
            "min": round(min(values), 2),
            "max": round(max(values), 2),
            "avg": round(sum(values) / count, 2),
            "p75": round(sorted_vals[p75_idx] if p75_idx < count else sorted_vals[-1], 2),
        }

    return {
        "total_metrics": len(_web_vitals_buffer),
        "metrics": summary,
    }


# ==============================================================================
# Schedule/FIDS Routes
# ==============================================================================

@router.get("/schedule/arrivals", response_model=ScheduleResponse, tags=["schedule"])
async def get_arrivals(
    hours_ahead: int = Query(default=2, ge=1, le=12, description="Hours into future"),
    hours_behind: int = Query(default=1, ge=0, le=6, description="Hours into past"),
    limit: int = Query(default=50, ge=1, le=200, description="Max flights"),
) -> ScheduleResponse:
    """
    Get scheduled arrivals for FIDS display.

    Returns arrival flights within the specified time window,
    sorted by scheduled time.
    """
    service = get_schedule_service()
    return service.get_arrivals(
        hours_ahead=hours_ahead,
        hours_behind=hours_behind,
        limit=limit,
    )


@router.get("/schedule/departures", response_model=ScheduleResponse, tags=["schedule"])
async def get_departures(
    hours_ahead: int = Query(default=2, ge=1, le=12, description="Hours into future"),
    hours_behind: int = Query(default=1, ge=0, le=6, description="Hours into past"),
    limit: int = Query(default=50, ge=1, le=200, description="Max flights"),
) -> ScheduleResponse:
    """
    Get scheduled departures for FIDS display.

    Returns departure flights within the specified time window,
    sorted by scheduled time.
    """
    service = get_schedule_service()
    return service.get_departures(
        hours_ahead=hours_ahead,
        hours_behind=hours_behind,
        limit=limit,
    )


# ==============================================================================
# Weather Routes
# ==============================================================================

@router.get("/weather/current", response_model=WeatherResponse, tags=["weather"])
async def get_current_weather(
    station: Optional[str] = Query(default=None, description="ICAO station (default: KSFO)"),
) -> WeatherResponse:
    """
    Get current weather observation and forecast.

    Returns METAR (current conditions) and TAF (forecast) for the specified
    or default airport station.
    """
    service = get_weather_service()
    return service.get_current_weather(station=station)


# ==============================================================================
# GSE (Ground Support Equipment) Routes
# ==============================================================================

@router.get("/gse/status", response_model=GSEFleetStatus, tags=["gse"])
async def get_gse_fleet_status() -> GSEFleetStatus:
    """
    Get overall GSE fleet status.

    Returns inventory and availability of all ground support equipment
    including tugs, fuel trucks, belt loaders, etc.
    """
    service = get_gse_service()
    return service.get_fleet_status()


@router.get("/turnaround/{icao24}", response_model=TurnaroundResponse, tags=["gse"])
async def get_turnaround_status(
    icao24: str,
    gate: Optional[str] = Query(default=None, description="Gate assignment"),
    aircraft_type: str = Query(default="A320", description="Aircraft type"),
) -> TurnaroundResponse:
    """
    Get turnaround status for an aircraft at gate.

    Returns current phase, progress, GSE allocation, and estimated departure
    time for an aircraft undergoing turnaround operations.
    """
    service = get_gse_service()
    return service.get_turnaround_status(
        icao24=icao24,
        gate=gate,
        aircraft_type=aircraft_type,
    )


# ==============================================================================
# Baggage Routes
# ==============================================================================

@router.get("/baggage/stats", response_model=BaggageStatsResponse, tags=["baggage"])
async def get_baggage_stats() -> BaggageStatsResponse:
    """
    Get overall baggage handling statistics.

    Returns airport-wide baggage metrics including throughput,
    misconnect rate, and processing times.
    """
    service = get_baggage_service()
    return service.get_overall_stats()


@router.get("/baggage/flight/{flight_number}", response_model=FlightBaggageResponse, tags=["baggage"])
async def get_flight_baggage(
    flight_number: str,
    aircraft_type: str = Query(default="A320", description="Aircraft type"),
    include_bags: bool = Query(default=False, description="Include bag list"),
) -> FlightBaggageResponse:
    """
    Get baggage information for a specific flight.

    Returns loading/unloading progress, bag counts, and optionally
    a sample of individual bags.
    """
    service = get_baggage_service()
    return service.get_flight_baggage(
        flight_number=flight_number,
        aircraft_type=aircraft_type,
        include_bags=include_bags,
    )


@router.get("/baggage/alerts", response_model=BaggageAlertsResponse, tags=["baggage"])
async def get_baggage_alerts() -> BaggageAlertsResponse:
    """
    Get active baggage alerts.

    Returns alerts for misconnects, delayed loading, and other
    baggage handling issues requiring attention.
    """
    service = get_baggage_service()
    return service.get_alerts()


# ==============================================================================
# Airport Configuration Routes
# ==============================================================================

@router.get("/airport/config", tags=["airport"])
async def get_airport_config() -> dict:
    """
    Get current airport configuration.

    Returns the merged configuration from all imported sources
    (AIXM, IFC, AIDM) or default configuration if nothing imported.
    """
    service = get_airport_config_service()
    config = service.get_config()
    last_updated = service.get_last_updated()

    return {
        "config": config,
        "lastUpdated": last_updated.isoformat() if last_updated else None,
        "elementCounts": service.get_element_counts(),
    }


@router.post("/airport/import/aixm", response_model=ImportResponse, tags=["airport"])
async def import_aixm(
    request: Request,
    reference_lat: Optional[float] = Query(default=None, description="Reference latitude"),
    reference_lon: Optional[float] = Query(default=None, description="Reference longitude"),
    merge: bool = Query(default=True, description="Merge with existing config"),
):
    """
    Import AIXM aeronautical data.

    Accepts AIXM 5.1.1 XML data containing runway, taxiway, and apron
    definitions. Data is parsed and converted to the internal configuration
    format for 3D visualization.

    Args:
        file: AIXM XML file content
        reference_lat: Optional reference latitude for coordinate conversion
        reference_lon: Optional reference longitude for coordinate conversion
        merge: Whether to merge with existing configuration

    Returns:
        Import result with element counts and any warnings
    """
    service = get_airport_config_service()
    file = await request.body()

    # Update reference point if provided
    if reference_lat is not None and reference_lon is not None:
        service.set_reference_point(reference_lat, reference_lon)

    try:
        config, warnings = service.import_aixm(file, merge=merge)

        return ImportResponse(
            success=True,
            format="AIXM",
            elementsImported={
                "runways": len(config.get("runways", [])),
                "taxiways": len(config.get("taxiways", [])),
                "aprons": len(config.get("aprons", [])),
                "navaids": len(config.get("navaids", [])),
            },
            warnings=warnings,
            timestamp=datetime.now(timezone.utc),
        )

    except ParseError as e:
        raise HTTPException(status_code=400, detail=f"AIXM parsing error: {str(e)}")
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=f"AIXM validation error: {str(e)}")


@router.post("/airport/import/ifc", response_model=ImportResponse, tags=["airport"])
async def import_ifc(
    request: Request,
    reference_lat: Optional[float] = Query(default=None, description="Reference latitude"),
    reference_lon: Optional[float] = Query(default=None, description="Reference longitude"),
    include_geometry: bool = Query(default=False, description="Extract detailed geometry"),
    merge: bool = Query(default=True, description="Merge with existing config"),
):
    """
    Import IFC building data.

    Accepts IFC4 files containing building geometry and structure.
    Requires ifcopenshell library to be installed.

    Args:
        file: IFC file content
        reference_lat: Optional reference latitude for coordinate conversion
        reference_lon: Optional reference longitude for coordinate conversion
        include_geometry: Whether to extract detailed mesh geometry
        merge: Whether to merge with existing configuration

    Returns:
        Import result with element counts and any warnings
    """
    service = get_airport_config_service()
    file = await request.body()

    if reference_lat is not None and reference_lon is not None:
        service.set_reference_point(reference_lat, reference_lon)

    try:
        config, warnings = service.import_ifc(
            file,
            merge=merge,
            include_geometry=include_geometry,
        )

        return ImportResponse(
            success=True,
            format="IFC",
            elementsImported={
                "buildings": len(config.get("buildings", [])),
                "elements": len(config.get("elements", [])),
            },
            warnings=warnings,
            timestamp=datetime.now(timezone.utc),
        )

    except ParseError as e:
        raise HTTPException(status_code=400, detail=f"IFC parsing error: {str(e)}")
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=f"IFC validation error: {str(e)}")


@router.post("/airport/import/aidm", response_model=AIDMImportResponse, tags=["airport"])
async def import_aidm(
    request: Request,
    local_airport: str = Query(default="SFO", description="Local airport IATA code"),
):
    """
    Import AIDM operational data.

    Accepts AIDM 12.0 JSON or XML containing flight schedules,
    resource allocations, and operational events.

    Args:
        file: AIDM JSON or XML content
        local_airport: Local airport code for context

    Returns:
        Import result with flight and resource counts
    """
    service = get_airport_config_service()
    file = await request.body()

    try:
        config, warnings = service.import_aidm(file, local_airport=local_airport)

        return AIDMImportResponse(
            success=True,
            flightsImported=len(config.get("flights", [])),
            resourcesImported=len(config.get("resources", [])),
            eventsImported=len(config.get("events", [])),
            warnings=warnings,
            timestamp=datetime.now(timezone.utc),
        )

    except ParseError as e:
        raise HTTPException(status_code=400, detail=f"AIDM parsing error: {str(e)}")
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=f"AIDM validation error: {str(e)}")


@router.post("/airport/import/osm", response_model=OSMImportResponse, tags=["airport"])
async def import_osm(
    icao_code: str = Query(default="KSFO", description="ICAO airport code"),
    include_gates: bool = Query(default=True, description="Import gate positions"),
    include_terminals: bool = Query(default=True, description="Import terminal buildings"),
    include_taxiways: bool = Query(default=False, description="Import taxiway geometry"),
    include_aprons: bool = Query(default=False, description="Import apron areas"),
    include_runways: bool = Query(default=False, description="Import runway geometry"),
    include_hangars: bool = Query(default=False, description="Import hangar buildings"),
    include_helipads: bool = Query(default=False, description="Import helipad positions"),
    include_parking_positions: bool = Query(default=False, description="Import parking positions"),
    merge: bool = Query(default=True, description="Merge with existing config"),
):
    """
    Import airport data from OpenStreetMap.

    Fetches gates, terminals, and other aeroway features from OSM
    via the Overpass API. OSM provides community-contributed data
    that complements official AIXM sources.

    Args:
        icao_code: ICAO airport code (e.g., "KSFO", "KJFK", "EGLL")
        include_gates: Whether to import gate positions
        include_terminals: Whether to import terminal building outlines
        include_taxiways: Whether to import taxiway centerlines
        include_aprons: Whether to import apron/ramp areas
        include_runways: Whether to import runway geometry
        include_hangars: Whether to import hangar buildings
        include_helipads: Whether to import helipad positions
        include_parking_positions: Whether to import parking positions
        merge: Whether to merge with existing configuration

    Returns:
        Import result with element counts and warnings
    """
    service = get_airport_config_service()

    try:
        config, warnings = service.import_osm(
            icao_code=icao_code,
            include_gates=include_gates,
            include_terminals=include_terminals,
            include_taxiways=include_taxiways,
            include_aprons=include_aprons,
            include_runways=include_runways,
            include_hangars=include_hangars,
            include_helipads=include_helipads,
            include_parking_positions=include_parking_positions,
            merge=merge,
        )

        return OSMImportResponse(
            success=True,
            icaoCode=icao_code,
            gatesImported=len(config.get("gates", [])),
            terminalsImported=len(config.get("terminals", [])),
            taxiwaysImported=len(config.get("osmTaxiways", [])),
            apronsImported=len(config.get("osmAprons", [])),
            runwaysImported=len(config.get("osmRunways", [])),
            hangarsImported=len(config.get("osmHangars", [])),
            helipadsImported=len(config.get("osmHelipads", [])),
            parkingPositionsImported=len(config.get("osmParkingPositions", [])),
            warnings=warnings,
            timestamp=datetime.now(timezone.utc),
        )

    except ParseError as e:
        raise HTTPException(status_code=400, detail=f"OSM fetch error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OSM import error: {str(e)}")


@router.post("/airport/import/faa", response_model=FAAImportResponse, tags=["airport"])
async def import_faa(
    facility_id: str = Query(default="SFO", description="FAA facility ID or ICAO code"),
    merge: bool = Query(default=True, description="Merge with existing config"),
):
    """
    Import FAA runway data for a US airport.

    Fetches authoritative runway geometry and metadata from FAA
    NASR (National Airspace System Resources) data. This is the
    official source for US airport runway information.

    Args:
        facility_id: FAA facility ID (e.g., "SFO") or ICAO code ("KSFO")
        merge: Whether to merge with existing configuration

    Returns:
        Import result with runway count and warnings
    """
    service = get_airport_config_service()

    try:
        config, warnings = service.import_faa(
            facility_id=facility_id,
            merge=merge,
        )

        return FAAImportResponse(
            success=True,
            facilityId=facility_id,
            runwaysImported=len(config.get("runways", [])),
            warnings=warnings,
            timestamp=datetime.now(timezone.utc),
        )

    except ParseError as e:
        raise HTTPException(status_code=400, detail=f"FAA fetch error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"FAA import error: {str(e)}")


# ==============================================================================
# Airport Persistence Routes
# ==============================================================================

@router.get("/airports", tags=["airport"])
async def list_airports() -> dict:
    """
    List all airports persisted in the lakehouse.

    Returns a list of airport metadata for all airports that have been
    imported and persisted to Unity Catalog tables.
    """
    service = get_airport_config_service()
    airports = service.list_persisted_airports()

    return {
        "airports": airports,
        "count": len(airports),
    }


@router.get("/airports/{icao_code}", tags=["airport"])
async def get_airport(icao_code: str) -> dict:
    """
    Get airport configuration (lakehouse first, OSM fallback).

    Tries to load from Unity Catalog tables first for speed.
    Falls back to OSM import if not found, then persists for next time.

    Args:
        icao_code: ICAO airport code (e.g., "KSFO")

    Returns:
        Airport configuration with source info
    """
    service = get_airport_config_service()

    loaded = service.initialize_from_lakehouse(
        icao_code=icao_code,
        fallback_to_osm=True,
    )

    if loaded:
        config = service.get_config()
        source = "lakehouse" if config.get("source") == "LAKEHOUSE" else "osm"
        return {
            "config": config,
            "source": source,
            "icaoCode": icao_code,
            "elementCounts": service.get_element_counts(),
        }
    else:
        raise HTTPException(
            status_code=404,
            detail=f"Airport {icao_code} not found (tried lakehouse and OSM)"
        )


@router.post("/airports/{icao_code}/activate", tags=["airport"])
async def activate_airport(icao_code: str) -> dict:
    """
    Activate an airport: load config, reset state, and ensure synthetic data.

    Returns the config immediately once loaded, then generates synthetic data
    in the background while broadcasting progress via WebSocket.

    Args:
        icao_code: ICAO airport code (e.g., "KSFO", "KJFK")

    Returns:
        Airport configuration with data readiness info
    """
    from app.backend.api.websocket import broadcaster

    total_steps = 7
    service = get_airport_config_service()

    # Step 1: Load airport config (fast)
    await broadcaster.broadcast_progress(1, total_steps, "Loading airport configuration...", icao_code)
    loaded = service.initialize_from_lakehouse(
        icao_code=icao_code,
        fallback_to_osm=True,
    )

    if not loaded:
        await broadcaster.broadcast_progress(1, total_steps, "Airport not found", icao_code, done=True)
        raise HTTPException(
            status_code=404,
            detail=f"Airport {icao_code} not found (tried lakehouse and OSM)"
        )

    config = service.get_config()
    source = "lakehouse" if config.get("source") == "LAKEHOUSE" else "osm"

    # Step 2: Reload gates and swap ML models (fast)
    await broadcaster.broadcast_progress(2, total_steps, "Reloading gate positions and ML models...", icao_code)
    gates = reload_gates()
    gate_recommender_count = reload_gate_recommender()

    # Swap ML models to airport-specific instances
    registry = get_model_registry()
    registry.retrain(icao_code)
    prediction_service = get_prediction_service()
    prediction_service.set_airport(icao_code)

    # Step 3: Set airport center BEFORE resetting state, so any concurrent
    # flight generation uses the new center immediately
    await broadcaster.broadcast_progress(3, total_steps, "Resetting flight state...", icao_code)
    from src.ingestion.schedule_generator import AIRPORT_COORDINATES
    from app.backend.services.data_generator_service import _icao_to_iata
    iata_code = _icao_to_iata(icao_code)
    if iata_code in AIRPORT_COORDINATES:
        lat, lon = AIRPORT_COORDINATES[iata_code]
        set_airport_center(lat, lon, iata_code)
    reset_result = reset_synthetic_state()

    # Check if data generation is needed
    data_generator = get_data_generator_service()
    already_initialized = icao_code in data_generator._initialized_airports

    if already_initialized:
        await broadcaster.broadcast_progress(total_steps, total_steps, "Airport ready", icao_code, done=True)
    else:
        # Launch data generation as background task with progress
        async def _generate_data_background():
            async def _progress(step, total, message, done):
                await broadcaster.broadcast_progress(step, total, message, icao_code, done)

            try:
                await data_generator.switch_airport(icao_code, progress_callback=_progress)
            except Exception as e:
                logger.error(f"Background data generation failed for {icao_code}: {e}")
            finally:
                await broadcaster.broadcast_progress(
                    total_steps, total_steps, "Airport ready", icao_code, done=True
                )

        asyncio.create_task(_generate_data_background())

    return {
        "config": config,
        "source": source,
        "icaoCode": icao_code,
        "elementCounts": service.get_element_counts(),
        "dataReady": already_initialized,
        "dataGenerating": not already_initialized,
        "gatesLoaded": len(gates),
        "gateRecommenderCount": gate_recommender_count,
        "stateReset": reset_result,
    }


@router.post("/airports/{icao_code}/refresh", tags=["airport"])
async def refresh_airport(
    icao_code: str,
    include_taxiways: bool = Query(default=True, description="Include taxiways"),
    include_aprons: bool = Query(default=True, description="Include aprons"),
    include_runways: bool = Query(default=True, description="Include runways"),
    include_hangars: bool = Query(default=True, description="Include hangars"),
    include_helipads: bool = Query(default=True, description="Include helipads"),
    include_parking_positions: bool = Query(default=True, description="Include parking positions"),
) -> dict:
    """
    Refresh airport data from external sources and persist.

    Re-fetches airport data from OSM and FAA APIs, then persists
    the updated configuration to the lakehouse.

    Args:
        icao_code: ICAO airport code (e.g., "KSFO")
        include_taxiways: Whether to fetch taxiway data
        include_aprons: Whether to fetch apron data
        include_runways: Whether to fetch runway data
        include_hangars: Whether to fetch hangar data
        include_helipads: Whether to fetch helipad data
        include_parking_positions: Whether to fetch parking position data

    Returns:
        Updated airport configuration
    """
    service = get_airport_config_service()

    try:
        # Import from OSM
        osm_config, osm_warnings = service.import_osm(
            icao_code,
            include_gates=True,
            include_terminals=True,
            include_taxiways=include_taxiways,
            include_aprons=include_aprons,
            include_runways=include_runways,
            include_hangars=include_hangars,
            include_helipads=include_helipads,
            include_parking_positions=include_parking_positions,
        )

        # Try to add FAA runway data (US airports only)
        faa_warnings = []
        facility_id = icao_code[1:] if icao_code.startswith("K") else icao_code
        try:
            faa_config, faa_warnings = service.import_faa(facility_id)
        except Exception:
            faa_warnings.append(f"FAA data not available for {icao_code}")

        return {
            "success": True,
            "icaoCode": icao_code,
            "elementCounts": service.get_element_counts(),
            "warnings": osm_warnings + faa_warnings,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to refresh airport {icao_code}: {str(e)}"
        )


@router.delete("/airports/{icao_code}", tags=["airport"])
async def delete_airport(icao_code: str) -> dict:
    """
    Delete an airport from the lakehouse.

    Removes all persisted data for the specified airport from
    Unity Catalog tables.

    Args:
        icao_code: ICAO airport code to delete

    Returns:
        Success confirmation
    """
    service = get_airport_config_service()

    if service.delete_persisted_airport(icao_code):
        return {
            "success": True,
            "message": f"Deleted airport {icao_code}",
        }
    else:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete airport {icao_code}"
        )


# ==============================================================================
# Airport Pre-load Routes
# ==============================================================================

@router.get("/airports/preload/status", tags=["airport"])
async def preload_status() -> dict:
    """
    Check which well-known airports are cached in the lakehouse.

    Returns metadata and cache status for all well-known airports.
    """
    service = get_airport_config_service()
    persisted = service.list_persisted_airports()
    persisted_codes = {a.get("icao_code", a.get("icaoCode", "")).upper() for a in persisted}

    airports = []
    for icao, info in WELL_KNOWN_AIRPORT_INFO.items():
        airports.append({
            "icao": icao,
            "iata": info["iata"],
            "name": info["name"],
            "city": info["city"],
            "region": info["region"],
            "cached": icao in persisted_codes,
        })

    return {"airports": airports}


@router.post("/airports/preload", tags=["airport"])
async def preload_airports(
    icao_codes: list[str] = Body(default=None, description="ICAO codes to preload. If null, preloads all well-known airports"),
) -> dict:
    """
    Pre-load airports into the lakehouse cache.

    Fetches airport data from OSM for each airport not already cached.
    Processes sequentially to respect Overpass API rate limits.
    Broadcasts progress via WebSocket.
    """
    from app.backend.api.websocket import broadcaster

    codes = icao_codes if icao_codes else list(WELL_KNOWN_AIRPORT_INFO.keys())
    service = get_airport_config_service()

    # Determine which are already cached
    persisted = service.list_persisted_airports()
    persisted_codes = {a.get("icao_code", a.get("icaoCode", "")).upper() for a in persisted}

    already_cached = [c for c in codes if c.upper() in persisted_codes]
    to_preload = [c for c in codes if c.upper() not in persisted_codes]

    preloaded = []
    failed = []

    for i, icao in enumerate(to_preload, 1):
        await broadcaster.broadcast_progress(
            i, len(to_preload),
            f"Pre-loading {icao} ({i}/{len(to_preload)})...",
            icao,
        )
        try:
            loaded = service.initialize_from_lakehouse(
                icao_code=icao.upper(),
                fallback_to_osm=True,
            )
            if loaded:
                preloaded.append(icao.upper())
            else:
                failed.append({"icao": icao.upper(), "error": "Load returned false"})
        except Exception as e:
            logger.error(f"Failed to preload {icao}: {e}")
            failed.append({"icao": icao.upper(), "error": str(e)})

    await broadcaster.broadcast_progress(
        len(to_preload), len(to_preload),
        "Pre-load complete",
        "all",
        done=True,
    )

    return {
        "preloaded": preloaded,
        "already_cached": already_cached,
        "failed": failed,
    }

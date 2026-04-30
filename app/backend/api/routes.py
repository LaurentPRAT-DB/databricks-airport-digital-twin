"""REST API routes for the Airport Digital Twin."""

import asyncio
import logging
import os
import re
import traceback
from collections import deque
from datetime import datetime, timezone
from typing import Optional

# Serialize concurrent airport activations to prevent global state corruption
_activation_lock = asyncio.Lock()
# Timeout for the entire activation flow (config load + gate reload + ML retrain)
_ACTIVATION_TIMEOUT_S = 90

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

_ICAO_RE = re.compile(r"^[A-Z0-9]{3,4}$")


def _validate_icao(icao_code: str) -> str:
    """Validate ICAO code at the API boundary. Returns 400 on invalid input."""
    if not icao_code or not isinstance(icao_code, str):
        raise HTTPException(status_code=400, detail=f"Invalid ICAO code: {icao_code!r}")
    code = icao_code.strip().upper()
    if not _ICAO_RE.match(code):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid ICAO code: {icao_code!r} — must be 3-4 uppercase alphanumeric characters",
        )
    return code


# ── In-memory ring-buffer log handler for /api/debug/logs ──
class _RingBufferHandler(logging.Handler):
    """Keeps the last N log records in memory for diagnostic retrieval."""

    def __init__(self, capacity: int = 500):
        super().__init__()
        self._buffer: deque[str] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord):
        try:
            self._buffer.append(self.format(record))
        except Exception:
            pass

    def get_lines(self, pattern: str | None = None) -> list[str]:
        lines = list(self._buffer)
        if pattern:
            lines = [l for l in lines if pattern in l]
        return lines


_ring_handler = _RingBufferHandler(capacity=1000)
_ring_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
_ring_handler.setLevel(logging.DEBUG)
# Attach to root AND the specific loggers that emit [DIAG] lines
for _logger_name in (
    None,  # root
    "app.backend.services.airport_config_service",
    "app.backend.services.data_generator_service",
    "app.backend.api.routes",
    "src.persistence.airport_repository",
    "app.backend.services.lakebase_service",
    "app.backend.services.opensky_service",
    "app.backend.services.opensky_collector",
    "app.backend.api.opensky",
    "src.ingestion.fallback",
):
    _lg = logging.getLogger(_logger_name)
    _lg.addHandler(_ring_handler)
    if _lg.level > logging.DEBUG:
        _lg.setLevel(logging.DEBUG)

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
from app.backend.demo_config import DEFAULT_FLIGHT_COUNT
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
    MSFSImportResponse,
)
from src.ingestion.fallback import apply_airport_offset, generate_synthetic_trajectory, get_airport_center, get_current_airport_iata, reload_gates, reset_airport_offset, reset_synthetic_state, set_airport_center
from src.ml.gate_model import reload_gate_recommender
from src.ml.registry import get_model_registry
from app.backend.services.prediction_service import get_prediction_service
from app.backend.api.deps import get_current_user
from app.backend.services.lakebase_service import get_lakebase_service
from src.formats.base import ParseError, ValidationError


def _compute_center_from_config(config: dict) -> tuple[float | None, float | None]:
    """Compute airport center from gate/terminal geo coordinates.

    Falls back through gates → terminals → None.
    """
    # Try gates first
    lats, lons = [], []
    for gate in config.get("gates", []):
        geo = gate.get("geo")
        if geo and geo.get("latitude") is not None and geo.get("longitude") is not None:
            lats.append(float(geo["latitude"]))
            lons.append(float(geo["longitude"]))
    if lats and lons:
        return sum(lats) / len(lats), sum(lons) / len(lons)

    # Try terminals
    for terminal in config.get("terminals", []):
        geo = terminal.get("geo")
        if geo and geo.get("latitude") is not None and geo.get("longitude") is not None:
            lats.append(float(geo["latitude"]))
            lons.append(float(geo["longitude"]))
    if lats and lons:
        return sum(lats) / len(lats), sum(lons) / len(lons)

    return None, None


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
    "LSGG": {"iata": "GVA", "name": "Geneva Cointrin", "city": "Geneva, CH", "region": "Europe"},
    "LGAV": {"iata": "ATH", "name": "Eleftherios Venizelos", "city": "Athens, GR", "region": "Europe"},
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


_COUNTRY_TO_REGION: dict[str, str] = {
    # Americas
    **{c: "Americas" for c in [
        "US", "CA", "MX", "BR", "AR", "CL", "CO", "PE", "VE", "EC", "UY", "PY",
        "BO", "CR", "PA", "CU", "DO", "PR", "JM", "TT", "BS", "BB", "HN", "GT",
        "SV", "NI", "BZ", "HT", "AW", "CW", "BM", "KY", "AG", "GY", "SR",
    ]},
    # Europe
    **{c: "Europe" for c in [
        "GB", "FR", "DE", "NL", "ES", "IT", "PT", "CH", "AT", "BE", "SE", "NO",
        "DK", "FI", "IE", "PL", "CZ", "GR", "RO", "HU", "HR", "BG", "RS", "SK",
        "UA", "IS", "LT", "LV", "EE", "SI", "LU", "MT", "CY", "AL", "BA", "ME",
        "MK", "MD", "BY", "XK", "GI", "TR",
    ]},
    # Middle East
    **{c: "Middle East" for c in [
        "AE", "SA", "QA", "KW", "BH", "OM", "JO", "LB", "IQ", "IR", "IL", "YE",
    ]},
    # Asia-Pacific
    **{c: "Asia-Pacific" for c in [
        "JP", "CN", "KR", "IN", "SG", "TH", "MY", "ID", "PH", "VN", "TW", "HK",
        "AU", "NZ", "PK", "BD", "LK", "NP", "MM", "KH", "LA", "BN", "MV", "FJ",
        "PG", "MN", "KZ", "UZ",
    ]},
    # Africa
    **{c: "Africa" for c in [
        "ZA", "MA", "EG", "NG", "KE", "ET", "GH", "TZ", "SN", "CI", "CM", "DZ",
        "TN", "LY", "AO", "MZ", "MG", "MU", "RW", "UG", "ZW", "BW", "NA", "GA",
    ]},
}


def _derive_airport_info(icao: str, name: str | None, iata: str | None) -> dict:
    """Derive full airport metadata from ICAO code and optional name/IATA."""
    from src.ingestion.airport_table import AIRPORTS as _AIRPORT_TABLE

    # Try well-known first (rich, hand-curated metadata)
    if icao in WELL_KNOWN_AIRPORT_INFO:
        info = WELL_KNOWN_AIRPORT_INFO[icao]
        return {
            "icao": icao,
            "iata": info["iata"],
            "name": info["name"],
            "city": info["city"],
            "region": info["region"],
            "cached": True,
        }

    # Try airport_table for IATA/country lookup
    resolved_iata = iata or ""
    country = ""
    if not resolved_iata:
        # Reverse lookup: find IATA from ICAO in airport_table
        for _iata, (_lat, _lon, _icao, _cc) in _AIRPORT_TABLE.items():
            if _icao == icao:
                resolved_iata = _iata
                country = _cc
                break
    else:
        entry = _AIRPORT_TABLE.get(resolved_iata)
        if entry:
            country = entry[3]

    region = _COUNTRY_TO_REGION.get(country, "Other")
    display_name = name or icao
    city = f"{country}" if country else ""

    return {
        "icao": icao,
        "iata": resolved_iata,
        "name": display_name,
        "city": city,
        "region": region,
        "cached": True,
    }


@router.get("/flights", response_model=FlightListResponse)
async def get_flights(
    count: int = Query(default=DEFAULT_FLIGHT_COUNT, ge=1, le=500, description="Number of flights"),
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
    trajectory_data = None

    # Always try Delta tables first — OpenSky/live flights won't exist in the
    # simulation state, so the synthetic fallback would return 0 points for them.
    delta = get_delta_service()
    if delta.is_available:
        trajectory_data = delta.get_trajectory(icao24, minutes=minutes, limit=limit)

    # Fall back to synthetic trajectory (works for simulated flights only)
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
    limit: int = Query(default=100, ge=1, le=200, description="Max flights"),
    sim_time: Optional[str] = Query(default=None, description="Simulation clock ISO timestamp"),
) -> ScheduleResponse:
    """
    Get scheduled arrivals for FIDS display.

    Returns arrival flights within the specified time window,
    sorted by scheduled time.
    """
    parsed_sim_time = None
    if sim_time:
        parsed_sim_time = datetime.fromisoformat(sim_time)
        if parsed_sim_time.tzinfo is None:
            parsed_sim_time = parsed_sim_time.replace(tzinfo=timezone.utc)

    service = get_schedule_service()
    return service.get_arrivals(
        hours_ahead=hours_ahead,
        hours_behind=hours_behind,
        limit=limit,
        sim_time=parsed_sim_time,
    )


@router.get("/schedule/departures", response_model=ScheduleResponse, tags=["schedule"])
async def get_departures(
    hours_ahead: int = Query(default=2, ge=1, le=12, description="Hours into future"),
    hours_behind: int = Query(default=1, ge=0, le=6, description="Hours into past"),
    limit: int = Query(default=100, ge=1, le=200, description="Max flights"),
    sim_time: Optional[str] = Query(default=None, description="Simulation clock ISO timestamp"),
) -> ScheduleResponse:
    """
    Get scheduled departures for FIDS display.

    Returns departure flights within the specified time window,
    sorted by scheduled time.
    """
    parsed_sim_time = None
    if sim_time:
        parsed_sim_time = datetime.fromisoformat(sim_time)
        if parsed_sim_time.tzinfo is None:
            parsed_sim_time = parsed_sim_time.replace(tzinfo=timezone.utc)

    service = get_schedule_service()
    return service.get_departures(
        hours_ahead=hours_ahead,
        hours_behind=hours_behind,
        limit=limit,
        sim_time=parsed_sim_time,
    )


@router.get("/schedule/audit", tags=["schedule"])
async def audit_schedule():
    """
    Cross-reference live simulation flights with FIDS schedule data.

    Returns a detailed ops audit showing:
    - Each sim flight and its matching FIDS entry (or missing)
    - Phase-to-status mapping accuracy
    - Delay consistency
    - Gate assignment alignment
    """
    from src.ingestion.fallback import get_flights_as_schedule, _flight_states, FlightPhase

    service = get_schedule_service()
    arrivals = service.get_arrivals(hours_ahead=4, hours_behind=2, limit=200)
    departures = service.get_departures(hours_ahead=4, hours_behind=2, limit=200)

    # Build FIDS lookup by flight number
    fids_map: dict[str, dict] = {}
    for f in arrivals.flights:
        fids_map[f.flight_number.upper()] = {
            "flight_number": f.flight_number,
            "status": f.status.value,
            "scheduled_time": f.scheduled_time.isoformat(),
            "estimated_time": f.estimated_time.isoformat() if f.estimated_time else None,
            "gate": f.gate,
            "delay_minutes": f.delay_minutes,
            "flight_type": "arrival",
            "origin": f.origin,
            "destination": f.destination,
        }
    for f in departures.flights:
        fids_map[f.flight_number.upper()] = {
            "flight_number": f.flight_number,
            "status": f.status.value,
            "scheduled_time": f.scheduled_time.isoformat(),
            "estimated_time": f.estimated_time.isoformat() if f.estimated_time else None,
            "gate": f.gate,
            "delay_minutes": f.delay_minutes,
            "flight_type": "departure",
            "origin": f.origin,
            "destination": f.destination,
        }

    # Build sim flight audit
    audit_entries = []
    matched = 0
    missing = 0

    for icao24, state in _flight_states.items():
        callsign = (state.callsign or "").strip().upper()
        if not callsign:
            continue

        fids_entry = fids_map.get(callsign)
        is_matched = fids_entry is not None

        if is_matched:
            matched += 1
        else:
            missing += 1

        entry = {
            "callsign": callsign,
            "icao24": icao24,
            "sim": {
                "phase": state.phase.value if hasattr(state.phase, 'value') else str(state.phase),
                "altitude": round(state.altitude, 0),
                "velocity": round(state.velocity, 0),
                "vertical_rate": round(state.vertical_rate, 0),
                "heading": round(state.heading % 360, 1),
                "latitude": round(state.latitude, 4),
                "longitude": round(state.longitude, 4),
                "on_ground": state.on_ground,
                "gate": state.assigned_gate,
                "origin": state.origin_airport,
                "destination": state.destination_airport,
                "aircraft_type": state.aircraft_type,
            },
            "fids": fids_entry,
            "matched": is_matched,
        }

        if is_matched:
            # Check consistency
            issues = []
            if fids_entry["gate"] and state.assigned_gate and fids_entry["gate"] != state.assigned_gate:
                issues.append(f"gate mismatch: sim={state.assigned_gate} fids={fids_entry['gate']}")
            entry["issues"] = issues

        audit_entries.append(entry)

    # Sort: unmatched first, then by callsign
    audit_entries.sort(key=lambda x: (x["matched"], x["callsign"]))

    return {
        "total_sim_flights": len(_flight_states),
        "total_fids_arrivals": len(arrivals.flights),
        "total_fids_departures": len(departures.flights),
        "matched": matched,
        "missing_from_fids": missing,
        "match_rate": f"{matched / max(1, matched + missing) * 100:.1f}%",
        "flights": audit_entries,
    }


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
    # Look up flight phase from synthetic state so airborne flights show 0% baggage
    flight_phase = None
    try:
        from src.ingestion.fallback import _flight_states
        for state in _flight_states.values():
            if state.callsign and state.callsign.strip() == flight_number:
                flight_phase = state.phase.value if state.phase else None
                break
    except Exception:
        pass

    service = get_baggage_service()
    return service.get_flight_baggage(
        flight_number=flight_number,
        aircraft_type=aircraft_type,
        include_bags=include_bags,
        flight_phase=flight_phase,
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

def _slim_config(config: dict) -> dict:
    """Strip verbose OSM metadata fields the frontend doesn't use."""
    if not config:
        return config

    slimmed = dict(config)

    # Strip tags from OSM collections
    for key in ("osmTaxiways", "osmAprons", "osmRunways", "terminals"):
        items = slimmed.get(key)
        if isinstance(items, list):
            slimmed[key] = [
                {k: v for k, v in item.items() if k not in ("tags", "source", "osmId")}
                for item in items
            ]

    # Strip gates to only id, ref, name, geo
    gates = slimmed.get("gates")
    if isinstance(gates, list):
        slimmed["gates"] = [
            {k: v for k, v in gate.items() if k in ("id", "ref", "name", "geo")}
            for gate in gates
        ]

    # Truncate geoPolygon coordinate precision to 6 decimals
    for key in ("osmTaxiways", "osmAprons", "osmRunways", "terminals"):
        items = slimmed.get(key)
        if isinstance(items, list):
            for item in items:
                for geo_key in ("geoPolygon", "geoPoints"):
                    points = item.get(geo_key)
                    if isinstance(points, list):
                        item[geo_key] = [
                            {
                                k: round(float(v), 6) if k in ("latitude", "longitude") and v is not None else v
                                for k, v in pt.items()
                            }
                            for pt in points
                            if isinstance(pt, dict)
                        ]

    return slimmed


@router.get("/airport/config", tags=["airport"])
async def get_airport_config(request: Request) -> dict:
    """
    Get current airport configuration.

    Returns the merged configuration from all imported sources
    (AIXM, IFC, AIDM) or default configuration if nothing imported.
    If the backend hasn't finished initialization, includes a ready flag.
    """
    service = get_airport_config_service()
    config = _slim_config(service.get_config())
    last_updated = service.get_last_updated()
    app_ready = getattr(request.app.state, "ready", False)

    return {
        "config": config,
        "lastUpdated": last_updated.isoformat() if last_updated else None,
        "elementCounts": service.get_element_counts(),
        "ready": app_ready,
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
    icao_code = _validate_icao(icao_code)
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


@router.post("/airport/import/msfs", response_model=MSFSImportResponse, tags=["airport"])
async def import_msfs(
    request: Request,
    merge: bool = Query(default=True, description="Merge with existing config"),
    icao_code: Optional[str] = Query(default=None, description="ICAO airport code (auto-detected from filename if omitted)"),
    filename: Optional[str] = Query(default=None, description="Original filename for ICAO extraction from BGL/ZIP names"),
):
    """
    Import MSFS scenery data.

    Accepts MSFS airport scenery XML, compiled BGL, or ZIP archive
    containing gate positions, taxi paths, runways, and apron areas.
    Community scenery packages from flightsim.to provide detailed
    airport definitions that complement OSM data.

    For BGL files where the ICAO code is embedded in the filename
    (e.g. lgav-airport.zip), pass the original filename or icao_code
    so the config can be persisted correctly.

    Args:
        request: HTTP request with XML, BGL, or ZIP body
        merge: Whether to merge with existing configuration
        icao_code: Explicit ICAO code (overrides filename extraction)
        filename: Original filename hint for ICAO extraction

    Returns:
        Import result with element counts and warnings
    """
    service = get_airport_config_service()
    file = await request.body()

    # Build source_path hint from filename or Content-Disposition header
    source_path = filename or ""
    if not source_path:
        cd = request.headers.get("content-disposition", "")
        if "filename=" in cd:
            # Extract filename from Content-Disposition header
            import re
            match = re.search(r'filename="?([^";]+)"?', cd)
            if match:
                source_path = match.group(1)

    try:
        config, warnings = service.import_msfs(
            file, merge=merge, icao_code=icao_code, source_path=source_path,
        )

        return MSFSImportResponse(
            success=True,
            icaoCode=config.get("icaoCode", ""),
            gatesImported=len(config.get("gates", [])),
            taxiwaysImported=len(config.get("osmTaxiways", [])),
            runwaysImported=len(config.get("osmRunways", [])),
            apronsImported=len(config.get("osmAprons", [])),
            warnings=warnings,
            timestamp=datetime.now(timezone.utc),
        )

    except ParseError as e:
        raise HTTPException(status_code=400, detail=f"MSFS parsing error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"MSFS import error: {str(e)}")


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
    icao_code = _validate_icao(icao_code)
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
async def activate_airport(icao_code: str, user: str = Depends(get_current_user)):
    """
    Activate an airport: load config, reset state, and ensure synthetic data.

    Returns 202 immediately and runs activation in the background.
    Progress and completion are broadcast via WebSocket so the frontend
    can update without waiting for the HTTP response.

    Accepts both IATA (MIA, CDG) and ICAO (KMIA, LFPG) codes — normalized to ICAO.

    Returns:
        202 Accepted with {"status": "activating", "icaoCode": icao_code}
        200 OK with {"status": "already_active"} if the airport is already loaded
    """
    icao_code = _validate_icao(icao_code)

    # Normalize IATA → ICAO so callers can pass either format
    from src.calibration.profile import _iata_to_icao
    icao_code = _iata_to_icao(icao_code)

    # Skip re-activation if this airport is already loaded
    current_iata = get_current_airport_iata()
    current_icao = _iata_to_icao(current_iata)
    if current_icao == icao_code:
        service = get_airport_config_service()
        if service.config_ready:
            return JSONResponse(
                status_code=200,
                content={"status": "already_active", "icaoCode": icao_code},
            )

    from app.backend.api.websocket import broadcaster

    # Serialize concurrent activations (prevents global state corruption from multiple tabs)
    if _activation_lock.locked():
        raise HTTPException(
            status_code=409,
            detail="Another airport activation is in progress. Please wait.",
        )

    # Acquire lock manually so we can hold it across the background task
    await _activation_lock.acquire()

    # Fire-and-forget: background task releases lock when done
    asyncio.create_task(_activate_airport_inner(icao_code, user, broadcaster))

    return JSONResponse(
        status_code=202,
        content={"status": "activating", "icaoCode": icao_code},
    )


async def _activate_airport_inner(icao_code: str, user: str, broadcaster) -> None:
    """Inner activation logic, runs as background task. Releases _activation_lock on exit."""
    import time as _time

    # Normalize IATA → ICAO so callers can pass either format
    from src.calibration.profile import _iata_to_icao
    icao_code = _iata_to_icao(icao_code)

    total_steps = 7
    service = get_airport_config_service()
    _t_activate_start = _time.monotonic()

    # Save rollback state before modifying anything
    prev_iata = get_current_airport_iata()
    prev_center = get_airport_center()
    prev_icao = _iata_to_icao(prev_iata)

    logger.info(f"[DIAG] ===== _activate_airport_inner({icao_code}) START =====")

    try:
        try:
            # Step 1: Load airport config with timeout (prevents Tier 2/3 hangs)
            _t_step = _time.monotonic()
            await broadcaster.broadcast_progress(1, total_steps, "Loading airport configuration...", icao_code)
            try:
                loaded = await asyncio.wait_for(
                    asyncio.to_thread(
                        service.initialize_from_lakehouse,
                        icao_code=icao_code,
                        fallback_to_osm=True,
                    ),
                    timeout=_ACTIVATION_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                logger.error(
                    f"Airport config load for {icao_code} timed out after {_ACTIVATION_TIMEOUT_S}s",
                    exc_info=True,
                )
                await broadcaster.broadcast_progress(
                    1, total_steps,
                    f"Timeout loading config after {_ACTIVATION_TIMEOUT_S}s",
                    icao_code, done=True, error=True,
                )
                return

            if not loaded:
                await broadcaster.broadcast_progress(
                    1, total_steps, "Airport not found", icao_code, done=True, error=True,
                )
                return

            logger.info(f"[DIAG] Step 1 (config load) done in {_time.monotonic() - _t_step:.3f}s — source={loaded}")

            config = service.get_config()
            source = "lakehouse" if config.get("source") == "LAKEHOUSE" else "osm"

            # Step 2: Set airport center FIRST so any concurrent flight generation
            # (e.g. WS broadcast loop) uses the new coordinates immediately
            _t_step = _time.monotonic()
            await broadcaster.broadcast_progress(2, total_steps, "Setting airport center...", icao_code)
            from src.ingestion.schedule_generator import AIRPORT_COORDINATES
            from src.calibration.profile import _icao_to_iata
            iata_code = _icao_to_iata(icao_code)
            if iata_code in AIRPORT_COORDINATES:
                lat, lon = AIRPORT_COORDINATES[iata_code]
            elif config.get("center"):
                lat = config["center"]["latitude"]
                lon = config["center"]["longitude"]
            else:
                # Compute center from gate/terminal geo coordinates as last resort
                lat, lon = _compute_center_from_config(config)
                if lat is None or lon is None:
                    raise ValueError(f"No coordinates available for {icao_code}")

            set_airport_center(lat, lon, iata_code)
            if iata_code != "SFO":
                apply_airport_offset(lat, lon)
            else:
                reset_airport_offset()
            logger.info(f"[DIAG] Step 2 (set center) done in {_time.monotonic() - _t_step:.3f}s")

            # Step 3: Reload gates and reset state (ML retrain deferred to background)
            _t_step = _time.monotonic()
            await broadcaster.broadcast_progress(3, total_steps, "Reloading gate positions...", icao_code)

            _t_sub = _time.monotonic()
            gates = reload_gates()
            logger.info(f"[DIAG]   reload_gates: {_time.monotonic() - _t_sub:.3f}s ({len(gates)} gates)")

            _t_sub = _time.monotonic()
            gate_recommender_count = reload_gate_recommender()
            logger.info(f"[DIAG]   reload_gate_recommender: {_time.monotonic() - _t_sub:.3f}s ({gate_recommender_count} entries)")

            _t_sub = _time.monotonic()
            reset_result = reset_synthetic_state()
            logger.info(f"[DIAG]   reset_synthetic_state: {_time.monotonic() - _t_sub:.3f}s")

            # Update schedule service to use the new airport
            schedule_svc = get_schedule_service()
            schedule_svc.set_airport(iata_code, icao_code)
            logger.info(f"[DIAG]   schedule_service switched to {iata_code}/{icao_code}")

            # Force full WS update (clear delta cache so clients get a full refresh)
            broadcaster._prev_flights.clear()
            logger.info(f"[DIAG] Step 3 (gates+reset) done in {_time.monotonic() - _t_step:.3f}s")

        except Exception as e:
            logger.error(
                f"Airport switch to {icao_code} failed, rolling back:\n"
                f"{traceback.format_exc()}"
            )
            # Rollback to previous airport state (restore ALL components)
            try:
                await asyncio.to_thread(
                    service.initialize_from_lakehouse,
                    icao_code=prev_icao,
                    fallback_to_osm=True,
                )
                reload_gates()
                set_airport_center(prev_center[0], prev_center[1], prev_iata)
                if prev_iata != "SFO":
                    apply_airport_offset(prev_center[0], prev_center[1])
                else:
                    reset_airport_offset()
                # Restore ML models and schedule service to previous airport
                registry = get_model_registry()
                registry.retrain(prev_icao)
                prediction_service = get_prediction_service()
                prediction_service.set_airport(prev_icao)
                schedule_svc = get_schedule_service()
                schedule_svc.set_airport(prev_iata, prev_icao)
                reset_synthetic_state()
                broadcaster._prev_flights.clear()
            except Exception:
                logger.error(
                    f"Rollback to {prev_icao} also failed:\n"
                    f"{traceback.format_exc()}"
                )
            await broadcaster.broadcast_progress(
                total_steps, total_steps,
                f"Airport switch failed: {e}. Rolled back to {prev_iata}.",
                icao_code, done=True, error=True,
            )
            return

        # Build the config payload to send via WS (same shape as old HTTP response)
        data_generator = get_data_generator_service()
        already_initialized = icao_code in data_generator._initialized_airports
        config_payload = {
            "config": config,
            "source": source,
            "icaoCode": icao_code,
            "elementCounts": service.get_element_counts(),
            "dataReady": True,
            "dataGenerating": not already_initialized,
            "gatesLoaded": len(gates),
            "gateRecommenderCount": gate_recommender_count,
            "stateReset": reset_result,
        }

        # Broadcast completion immediately — in-memory sim is ready, Lakebase
        # data gen runs in background and is not needed for the UI to work.
        await broadcaster.broadcast({
            "type": "airport_switch_complete",
            "data": config_payload,
        })

        _t_ready = _time.monotonic() - _t_activate_start
        await broadcaster.broadcast_progress(total_steps, total_steps, "Airport ready", icao_code, done=True)
        logger.info(f"[DIAG] Airport {icao_code} ready in {_t_ready:.3f}s (UI unblocked)")

        # === Everything below is background work — UI is already unblocked ===

        # Retrain ML models in background
        async def _retrain_ml_background():
            try:
                _t0 = _time.monotonic()
                registry = get_model_registry()
                await asyncio.to_thread(registry.retrain, icao_code)
                prediction_service = get_prediction_service()
                prediction_service.set_airport(icao_code)
                logger.info(f"[DIAG] Background ML retrain for {icao_code}: {_time.monotonic() - _t0:.3f}s")
            except Exception:
                logger.error(f"Background ML retrain failed for {icao_code}:\n{traceback.format_exc()}")

        asyncio.create_task(_retrain_ml_background())

        # Auto-calibrate if this airport has no real profile
        registry = get_model_registry()
        profile_loader = registry._profile_loader
        current_profile = profile_loader.get_profile(icao_code)
        if current_profile.data_source == "fallback":
            async def _auto_calibrate_background():
                try:
                    _t0 = _time.monotonic()
                    from src.calibration.auto_calibrate import auto_calibrate_airport
                    profile = await asyncio.to_thread(auto_calibrate_airport, icao_code, True)
                    if profile:
                        profile_loader.update_cache(icao_code, profile)
                        await asyncio.to_thread(registry.retrain, icao_code)
                        logger.info(
                            f"[DIAG] Background auto-calibrate for {icao_code}: "
                            f"{_time.monotonic() - _t0:.1f}s (source={profile.data_source})"
                        )
                except Exception:
                    logger.error(f"Background auto-calibrate failed for {icao_code}:\n{traceback.format_exc()}")

            asyncio.create_task(_auto_calibrate_background())

        # Lakebase data generation (fully background, non-blocking)
        if not already_initialized:
            async def _generate_data_background():
                try:
                    _t0 = _time.monotonic()
                    await data_generator.switch_airport(icao_code)
                    logger.info(f"[DIAG] Background data gen for {icao_code}: {_time.monotonic() - _t0:.3f}s")
                except Exception as e:
                    logger.error(f"Background data generation failed for {icao_code}: {e}")

            asyncio.create_task(_generate_data_background())

        # Generate demo simulation for new airport (background) and auto-start
        async def _generate_demo_background():
            from app.backend.services.demo_simulation_service import get_demo_simulation_service
            try:
                demo_svc = get_demo_simulation_service()
                if not demo_svc.has_demo(icao_code):
                    await asyncio.to_thread(demo_svc.generate_demo, icao_code)
                    logger.info(f"[DIAG] Background demo generation for {icao_code} complete")
                # Signal frontend that demo is ready for auto-start
                await broadcaster.broadcast({
                    "type": "demo_ready",
                    "data": {"icao": icao_code},
                })
            except Exception as e:
                logger.error(f"Background demo generation failed for {icao_code}: {e}")

        asyncio.create_task(_generate_demo_background())

        # Record usage for pre-warming (fire-and-forget, non-blocking)
        lakebase = get_lakebase_service()
        if lakebase.is_available:
            asyncio.create_task(asyncio.to_thread(
                lakebase.record_airport_usage, user, icao_code
            ))

    finally:
        _activation_lock.release()


@router.post("/airports/{icao_code}/reload", tags=["airport"])
async def reload_airport(icao_code: str) -> dict:
    """
    Force-reload airport from OSM and update all caches.

    Clears cached config, re-fetches from OSM Overpass API, then
    persists to UC and caches to Lakebase.

    Args:
        icao_code: ICAO airport code (e.g., "KSFO")

    Returns:
        Updated airport configuration
    """
    service = get_airport_config_service()

    try:
        # Fetch fresh from OSM (full import)
        osm_config, warnings = await asyncio.to_thread(
            service.import_osm,
            icao_code,
            include_gates=True,
            include_terminals=True,
            include_taxiways=True,
            include_aprons=True,
            include_runways=True,
            include_hangars=True,
            include_helipads=True,
            include_parking_positions=True,
            merge=False,
        )

        # For US airports, also import FAA runway data
        faa_warnings = []
        if icao_code.startswith("K"):
            try:
                await asyncio.to_thread(service.import_faa, icao_code, True)
            except Exception:
                faa_warnings.append(f"FAA data not available for {icao_code}")

        # Persist to Unity Catalog
        await asyncio.to_thread(service.persist_config, icao_code)

        # Cache to Lakebase
        await asyncio.to_thread(service.save_to_lakebase_cache, icao_code)

        return {
            "success": True,
            "icaoCode": icao_code,
            "source": "osm_reload",
            "elementCounts": service.get_element_counts(),
            "warnings": warnings + faa_warnings,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reload airport {icao_code}: {str(e)}"
        )


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
    icao_code = _validate_icao(icao_code)
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
    List airports available in the cache (Lakebase).

    Returns only airports that have been loaded and cached.
    The list grows dynamically as new airports are activated via custom ICAO input.
    """
    from app.backend.services.lakebase_service import get_lakebase_service

    lakebase = get_lakebase_service()
    cached_meta = lakebase.get_cached_airport_metadata()

    airports = []
    for row in cached_meta:
        info = _derive_airport_info(
            icao=row["icao_code"],
            name=row.get("name"),
            iata=row.get("iata"),
        )
        airports.append(info)

    # Fallback: if Lakebase is unavailable, fall back to well-known list
    # with cached=false so the UI still shows something.
    if not airports and not lakebase.is_available:
        for icao, info in WELL_KNOWN_AIRPORT_INFO.items():
            airports.append({
                "icao": icao,
                "iata": info["iata"],
                "name": info["name"],
                "city": info["city"],
                "region": info["region"],
                "cached": False,
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


@router.post("/user/prewarm", tags=["user"])
async def prewarm_user_airports(user: str = Depends(get_current_user)) -> dict:
    """Pre-warm user's most-used airports from UC into Lakebase cache.

    Looks up the user's top airports from usage history. For any that
    aren't already in Lakebase cache, loads them from Unity Catalog
    in the background.
    """
    lakebase = get_lakebase_service()
    if not lakebase.is_available:
        return {"status": "skipped", "reason": "lakebase_unavailable"}

    top_airports = lakebase.get_user_top_airports(user, limit=5)

    if not top_airports:
        # New user — pre-warm the default airport
        default = os.getenv("DEMO_DEFAULT_AIRPORT", "KSFO")
        top_airports = [default]

    cached = set(lakebase.get_cached_airport_codes())
    to_warm = [icao for icao in top_airports if icao not in cached]

    if not to_warm:
        return {
            "status": "ok",
            "user": user,
            "airports": top_airports,
            "already_cached": len(top_airports),
            "warming": 0,
        }

    # Warm missing airports in background
    async def _warm_airports():
        service = get_airport_config_service()
        for icao in to_warm:
            try:
                loaded = await asyncio.to_thread(
                    service.initialize_from_lakehouse,
                    icao_code=icao,
                    fallback_to_osm=False,  # UC only, don't hit external OSM
                )
                if loaded:
                    await asyncio.to_thread(service.save_to_lakebase_cache, icao)
                    logger.info(f"Pre-warmed {icao} into Lakebase for {user}")
            except Exception as e:
                logger.warning(f"Failed to pre-warm {icao}: {e}")

    asyncio.create_task(_warm_airports())

    return {
        "status": "warming",
        "user": user,
        "airports": top_airports,
        "already_cached": len(top_airports) - len(to_warm),
        "warming": len(to_warm),
    }


# ==============================================================================
# Debug / Diagnostics
# ==============================================================================

@router.get("/debug/logs", tags=["debug"])
async def get_debug_logs(
    pattern: Optional[str] = Query(default="DIAG", description="Filter pattern (default: DIAG)"),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict:
    """Return recent log lines matching a pattern.

    Only available when DEBUG_MODE=true.
    """
    if os.environ.get("DEBUG_MODE", "false").lower() != "true":
        raise HTTPException(status_code=403, detail="Debug endpoints are disabled in production")

    lines = _ring_handler.get_lines(pattern if pattern else None)
    return {
        "pattern": pattern,
        "total_buffered": len(_ring_handler._buffer),
        "matched": len(lines),
        "lines": lines[-limit:],
    }


_CLIENT_LOG_LEVELS = {"error": logging.ERROR, "warn": logging.WARNING, "info": logging.INFO, "debug": logging.DEBUG}


@router.post("/debug/client-logs", tags=["debug"])
async def post_client_logs(request: Request) -> dict:
    """Receive frontend log entries — persist to ring buffer + Lakebase."""
    body = await request.json()
    entries = body.get("entries", [])
    if not entries:
        return {"accepted": 0}

    # Mirror to ring buffer so GET /debug/logs?pattern=CLIENT sees them
    for entry in entries:
        lvl = _CLIENT_LOG_LEVELS.get(entry.get("level", "info"), logging.INFO)
        logger.log(lvl, "[CLIENT:%s] %s", entry.get("source", "?"), entry.get("message", ""))

    # Persist to Lakebase
    from app.backend.services.lakebase_service import get_lakebase_service
    lakebase = get_lakebase_service()
    if lakebase.is_available:
        lakebase.insert_client_logs(entries)

    # Persist to UC Volume debug log (readable via `databricks fs cat`)
    _uc_catalog = os.getenv("DATABRICKS_CATALOG", "")
    _uc_schema = os.getenv("DATABRICKS_SCHEMA", "")
    if _uc_catalog and _uc_schema:
        try:
            from datetime import datetime as _dt
            debug_dir = f"/Volumes/{_uc_catalog}/{_uc_schema}/simulation_data/debug"
            os.makedirs(debug_dir, exist_ok=True)
            log_path = f"{debug_dir}/client_debug.log"
            with open(log_path, "a") as f:
                ts = _dt.utcnow().isoformat(timespec="seconds")
                import json as _json
                for entry in entries:
                    meta = entry.get("metadata")
                    meta_str = f" | {_json.dumps(meta, default=str)}" if meta else ""
                    f.write(f"[{ts}] [{entry.get('level', 'info')}] [{entry.get('source', '?')}] {entry.get('message', '')}{meta_str}\n")
        except Exception:
            pass

    return {"accepted": len(entries)}


@router.get("/debug/client-logs", tags=["debug"])
async def get_client_logs(
    source: Optional[str] = Query(default=None, description="Filter by source tag"),
    level: Optional[str] = Query(default=None, description="Filter by level (error, warn, info, debug)"),
    limit: int = Query(default=100, ge=1, le=500),
    since_minutes: int = Query(default=60, ge=1, le=1440),
) -> dict:
    """Query persisted client debug logs from Lakebase.

    Only available when DEBUG_MODE=true.
    """
    if os.environ.get("DEBUG_MODE", "false").lower() != "true":
        raise HTTPException(status_code=403, detail="Debug endpoints are disabled in production")

    from app.backend.services.lakebase_service import get_lakebase_service
    lakebase = get_lakebase_service()
    if not lakebase.is_available:
        raise HTTPException(status_code=503, detail="Lakebase not available")

    rows = lakebase.query_client_logs(source=source, level=level, limit=limit, since_minutes=since_minutes)
    # Serialize datetimes
    for row in rows:
        if hasattr(row.get("logged_at"), "isoformat"):
            row["logged_at"] = row["logged_at"].isoformat()
    return {"entries": rows, "count": len(rows)}


@router.get("/debug/recent-errors", tags=["debug"])
async def get_recent_errors(
    limit: int = Query(default=50, ge=1, le=200),
    authorization: str = Header(default="", alias="Authorization"),
) -> dict:
    """Return recent ERROR/WARNING lines from the ring buffer.

    Unlike /debug/logs, this endpoint does NOT require DEBUG_MODE.
    It only returns error/warning-level entries and requires a Bearer token
    for basic auth gating.

    Designed for Claude Code's devloop: after deploy, fetch errors to
    diagnose runtime issues without ssh or log streaming.
    """
    # Require a Bearer token (any valid Databricks token will do)
    if not authorization.startswith("Bearer ") or len(authorization) < 20:
        raise HTTPException(status_code=401, detail="Bearer token required")

    all_lines = list(_ring_handler._buffer)
    errors = [l for l in all_lines if " ERROR " in l]
    warnings = [l for l in all_lines if " WARNING " in l]

    return {
        "errors": errors[-limit:],
        "warnings": warnings[-limit:],
        "error_count": len(errors),
        "warning_count": len(warnings),
        "total_buffered": len(all_lines),
    }


@router.get("/debug/runway-diag", tags=["debug"])
async def get_runway_diagnostics() -> dict:
    """Return runway diagnostic data — what the simulator sees."""
    from app.backend.services.airport_config_service import get_airport_config_service
    config = get_airport_config_service().get_config()
    osm_runways = config.get("osmRunways", [])

    runway_info = []
    for r in osm_runways:
        pts = r.get("geoPoints", [])
        info = {
            "ref": r.get("ref"),
            "name": r.get("name"),
            "geoPoints_count": len(pts),
        }
        if len(pts) >= 2:
            info["first_pt"] = pts[0]
            info["last_pt"] = pts[-1]
        runway_info.append(info)

    from src.ingestion.fallback import _get_osm_primary_runway, _osm_runway_endpoints, _get_runway_heading
    primary = _get_osm_primary_runway()
    heading = _get_runway_heading()
    endpoints = None
    if primary:
        thr, far, hdg = _osm_runway_endpoints(primary)
        endpoints = {
            "threshold": {"lon": thr[0], "lat": thr[1]},
            "far_end": {"lon": far[0], "lat": far[1]},
            "heading": hdg,
            "ref": primary.get("ref"),
        }

    return {
        "config_keys": list(config.keys())[:20],
        "osmRunways_count": len(osm_runways),
        "runways": runway_info,
        "primary_runway": {
            "ref": primary.get("ref") if primary else None,
            "geoPoints_count": len(primary.get("geoPoints", [])) if primary else 0,
        },
        "computed_heading": heading,
        "endpoints": endpoints,
        "config_source": config.get("source"),
        "config_ready": get_airport_config_service().config_ready,
    }

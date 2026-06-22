"""Airport configuration endpoints — imports, CRUD, activation, preloading."""

import asyncio
import logging
import os
import re
import traceback
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.backend.models.airport_config import (
    ImportResponse,
    AIDMImportResponse,
    OSMImportResponse,
    FAAImportResponse,
    MSFSImportResponse,
)
from app.backend.services.airport_config_service import get_airport_config_service
from app.backend.services.schedule_service import get_schedule_service
from app.backend.services.lakebase_service import get_lakebase_service
from app.backend.services.data_generator_service import get_data_generator_service
from app.backend.services.prediction_service import get_prediction_service
from app.backend.api.deps import get_current_user
from src.ingestion.fallback import (
    apply_airport_offset,
    get_airport_center,
    get_current_airport_iata,
    reload_gates,
    reset_airport_offset,
    reset_synthetic_state,
    set_airport_center,
)
from src.ml.gate_model import reload_gate_recommender
from src.ml.registry import get_model_registry
from src.formats.base import ParseError, ValidationError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["airport"])

_ICAO_RE = re.compile(r"^[A-Z0-9]{3,4}$")

_activation_lock = asyncio.Lock()
_ACTIVATION_TIMEOUT_S = 90


def _validate_icao(icao_code: str) -> str:
    """Validate ICAO code at the API boundary."""
    if not icao_code or not isinstance(icao_code, str):
        raise HTTPException(status_code=400, detail=f"Invalid ICAO code: {icao_code!r}")
    code = icao_code.strip().upper()
    if not _ICAO_RE.match(code):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid ICAO code: {icao_code!r} — must be 3-4 uppercase alphanumeric characters",
        )
    return code


def _compute_center_from_config(config: dict) -> tuple[float | None, float | None]:
    """Compute airport center from gate/terminal geo coordinates."""
    lats, lons = [], []
    for gate in config.get("gates", []):
        geo = gate.get("geo")
        if geo and geo.get("latitude") is not None and geo.get("longitude") is not None:
            lats.append(float(geo["latitude"]))
            lons.append(float(geo["longitude"]))
    if lats and lons:
        return sum(lats) / len(lats), sum(lons) / len(lons)

    for terminal in config.get("terminals", []):
        geo = terminal.get("geo")
        if geo and geo.get("latitude") is not None and geo.get("longitude") is not None:
            lats.append(float(geo["latitude"]))
            lons.append(float(geo["longitude"]))
    if lats and lons:
        return sum(lats) / len(lats), sum(lons) / len(lons)

    return None, None


WELL_KNOWN_AIRPORT_INFO: dict[str, dict] = {
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
    "EGLL": {"iata": "LHR", "name": "London Heathrow", "city": "London, UK", "region": "Europe"},
    "LFPG": {"iata": "CDG", "name": "Charles de Gaulle", "city": "Paris, FR", "region": "Europe"},
    "EHAM": {"iata": "AMS", "name": "Amsterdam Schiphol", "city": "Amsterdam, NL", "region": "Europe"},
    "EDDF": {"iata": "FRA", "name": "Frankfurt Airport", "city": "Frankfurt, DE", "region": "Europe"},
    "LEMD": {"iata": "MAD", "name": "Adolfo Suarez Madrid-Barajas", "city": "Madrid, ES", "region": "Europe"},
    "LIRF": {"iata": "FCO", "name": "Leonardo da Vinci (Fiumicino)", "city": "Rome, IT", "region": "Europe"},
    "LSGG": {"iata": "GVA", "name": "Geneva Cointrin", "city": "Geneva, CH", "region": "Europe"},
    "LGAV": {"iata": "ATH", "name": "Eleftherios Venizelos", "city": "Athens, GR", "region": "Europe"},
    "OMAA": {"iata": "AUH", "name": "Abu Dhabi International", "city": "Abu Dhabi, AE", "region": "Middle East"},
    "OMDB": {"iata": "DXB", "name": "Dubai International", "city": "Dubai, AE", "region": "Middle East"},
    "RJTT": {"iata": "HND", "name": "Tokyo Haneda", "city": "Tokyo, JP", "region": "Asia-Pacific"},
    "VHHH": {"iata": "HKG", "name": "Hong Kong International", "city": "Hong Kong", "region": "Asia-Pacific"},
    "WSSS": {"iata": "SIN", "name": "Singapore Changi", "city": "Singapore", "region": "Asia-Pacific"},
    "ZBAA": {"iata": "PEK", "name": "Beijing Capital International", "city": "Beijing, CN", "region": "Asia-Pacific"},
    "RKSI": {"iata": "ICN", "name": "Incheon International", "city": "Seoul, KR", "region": "Asia-Pacific"},
    "VTBS": {"iata": "BKK", "name": "Suvarnabhumi Airport", "city": "Bangkok, TH", "region": "Asia-Pacific"},
    "FAOR": {"iata": "JNB", "name": "O.R. Tambo International", "city": "Johannesburg, ZA", "region": "Africa"},
    "GMMN": {"iata": "CMN", "name": "Mohammed V International", "city": "Casablanca, MA", "region": "Africa"},
}


_COUNTRY_TO_REGION: dict[str, str] = {
    **{c: "Americas" for c in [
        "US", "CA", "MX", "BR", "AR", "CL", "CO", "PE", "VE", "EC", "UY", "PY",
        "BO", "CR", "PA", "CU", "DO", "PR", "JM", "TT", "BS", "BB", "HN", "GT",
        "SV", "NI", "BZ", "HT", "AW", "CW", "BM", "KY", "AG", "GY", "SR",
    ]},
    **{c: "Europe" for c in [
        "GB", "FR", "DE", "NL", "ES", "IT", "PT", "CH", "AT", "BE", "SE", "NO",
        "DK", "FI", "IE", "PL", "CZ", "GR", "RO", "HU", "HR", "BG", "RS", "SK",
        "UA", "IS", "LT", "LV", "EE", "SI", "LU", "MT", "CY", "AL", "BA", "ME",
        "MK", "MD", "BY", "XK", "GI", "TR",
    ]},
    **{c: "Middle East" for c in [
        "AE", "SA", "QA", "KW", "BH", "OM", "JO", "LB", "IQ", "IR", "IL", "YE",
    ]},
    **{c: "Asia-Pacific" for c in [
        "JP", "CN", "KR", "IN", "SG", "TH", "MY", "ID", "PH", "VN", "TW", "HK",
        "AU", "NZ", "PK", "BD", "LK", "NP", "MM", "KH", "LA", "BN", "MV", "FJ",
        "PG", "MN", "KZ", "UZ",
    ]},
    **{c: "Africa" for c in [
        "ZA", "MA", "EG", "NG", "KE", "ET", "GH", "TZ", "SN", "CI", "CM", "DZ",
        "TN", "LY", "AO", "MZ", "MG", "MU", "RW", "UG", "ZW", "BW", "NA", "GA",
    ]},
}


def _derive_airport_info(icao: str, name: str | None, iata: str | None) -> dict:
    """Derive full airport metadata from ICAO code and optional name/IATA."""
    from src.ingestion.airport_table import AIRPORTS as _AIRPORT_TABLE

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

    resolved_iata = iata or ""
    country = ""
    if not resolved_iata:
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


def _slim_config(config: dict) -> dict:
    """Strip verbose OSM metadata fields the frontend doesn't use."""
    if not config:
        return config

    slimmed = dict(config)

    for key in ("osmTaxiways", "osmAprons", "osmRunways", "terminals"):
        items = slimmed.get(key)
        if isinstance(items, list):
            slimmed[key] = [
                {k: v for k, v in item.items() if k not in ("tags", "source", "osmId")}
                for item in items
            ]

    gates = slimmed.get("gates")
    if isinstance(gates, list):
        slimmed["gates"] = [
            {k: v for k, v in gate.items() if k in ("id", "ref", "name", "geo")}
            for gate in gates
        ]

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


# ── Airport Configuration ──

@router.get("/airport/config")
async def get_airport_config(request: Request) -> dict:
    """Get current airport configuration."""
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


@router.post("/airport/import/aixm", response_model=ImportResponse)
async def import_aixm(
    request: Request,
    reference_lat: Optional[float] = Query(default=None),
    reference_lon: Optional[float] = Query(default=None),
    merge: bool = Query(default=True),
):
    """Import AIXM aeronautical data."""
    service = get_airport_config_service()
    file = await request.body()

    if reference_lat is not None and reference_lon is not None:
        service.set_reference_point(reference_lat, reference_lon)

    try:
        config, warnings = service.import_aixm(file, merge=merge)
        return ImportResponse(
            success=True, format="AIXM",
            elementsImported={
                "runways": len(config.get("runways", [])),
                "taxiways": len(config.get("taxiways", [])),
                "aprons": len(config.get("aprons", [])),
                "navaids": len(config.get("navaids", [])),
            },
            warnings=warnings, timestamp=datetime.now(timezone.utc),
        )
    except ParseError as e:
        raise HTTPException(status_code=400, detail=f"AIXM parsing error: {str(e)}")
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=f"AIXM validation error: {str(e)}")


@router.post("/airport/import/ifc", response_model=ImportResponse)
async def import_ifc(
    request: Request,
    reference_lat: Optional[float] = Query(default=None),
    reference_lon: Optional[float] = Query(default=None),
    include_geometry: bool = Query(default=False),
    merge: bool = Query(default=True),
):
    """Import IFC building data."""
    service = get_airport_config_service()
    file = await request.body()

    if reference_lat is not None and reference_lon is not None:
        service.set_reference_point(reference_lat, reference_lon)

    try:
        config, warnings = service.import_ifc(file, merge=merge, include_geometry=include_geometry)
        return ImportResponse(
            success=True, format="IFC",
            elementsImported={
                "buildings": len(config.get("buildings", [])),
                "elements": len(config.get("elements", [])),
            },
            warnings=warnings, timestamp=datetime.now(timezone.utc),
        )
    except ParseError as e:
        raise HTTPException(status_code=400, detail=f"IFC parsing error: {str(e)}")
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=f"IFC validation error: {str(e)}")


@router.post("/airport/import/aidm", response_model=AIDMImportResponse)
async def import_aidm(
    request: Request,
    local_airport: str = Query(default="SFO"),
):
    """Import AIDM operational data."""
    service = get_airport_config_service()
    file = await request.body()

    try:
        config, warnings = service.import_aidm(file, local_airport=local_airport)
        return AIDMImportResponse(
            success=True,
            flightsImported=len(config.get("flights", [])),
            resourcesImported=len(config.get("resources", [])),
            eventsImported=len(config.get("events", [])),
            warnings=warnings, timestamp=datetime.now(timezone.utc),
        )
    except ParseError as e:
        raise HTTPException(status_code=400, detail=f"AIDM parsing error: {str(e)}")
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=f"AIDM validation error: {str(e)}")


@router.post("/airport/import/osm", response_model=OSMImportResponse)
async def import_osm(
    icao_code: str = Query(default="KSFO"),
    include_gates: bool = Query(default=True),
    include_terminals: bool = Query(default=True),
    include_taxiways: bool = Query(default=False),
    include_aprons: bool = Query(default=False),
    include_runways: bool = Query(default=False),
    include_hangars: bool = Query(default=False),
    include_helipads: bool = Query(default=False),
    include_parking_positions: bool = Query(default=False),
    merge: bool = Query(default=True),
):
    """Import airport data from OpenStreetMap."""
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
            success=True, icaoCode=icao_code,
            gatesImported=len(config.get("gates", [])),
            terminalsImported=len(config.get("terminals", [])),
            taxiwaysImported=len(config.get("osmTaxiways", [])),
            apronsImported=len(config.get("osmAprons", [])),
            runwaysImported=len(config.get("osmRunways", [])),
            hangarsImported=len(config.get("osmHangars", [])),
            helipadsImported=len(config.get("osmHelipads", [])),
            parkingPositionsImported=len(config.get("osmParkingPositions", [])),
            warnings=warnings, timestamp=datetime.now(timezone.utc),
        )
    except ParseError as e:
        raise HTTPException(status_code=400, detail=f"OSM fetch error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OSM import error: {str(e)}")


@router.post("/airport/import/faa", response_model=FAAImportResponse)
async def import_faa(
    facility_id: str = Query(default="SFO"),
    merge: bool = Query(default=True),
):
    """Import FAA runway data for a US airport."""
    service = get_airport_config_service()

    try:
        config, warnings = service.import_faa(facility_id=facility_id, merge=merge)
        return FAAImportResponse(
            success=True, facilityId=facility_id,
            runwaysImported=len(config.get("runways", [])),
            warnings=warnings, timestamp=datetime.now(timezone.utc),
        )
    except ParseError as e:
        raise HTTPException(status_code=400, detail=f"FAA fetch error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"FAA import error: {str(e)}")


@router.post("/airport/import/msfs", response_model=MSFSImportResponse)
async def import_msfs(
    request: Request,
    merge: bool = Query(default=True),
    icao_code: Optional[str] = Query(default=None),
    filename: Optional[str] = Query(default=None),
):
    """Import MSFS scenery data."""
    service = get_airport_config_service()
    file = await request.body()

    source_path = filename or ""
    if not source_path:
        cd = request.headers.get("content-disposition", "")
        if "filename=" in cd:
            match = re.search(r'filename="?([^";]+)"?', cd)
            if match:
                source_path = match.group(1)

    try:
        config, warnings = service.import_msfs(
            file, merge=merge, icao_code=icao_code, source_path=source_path,
        )
        return MSFSImportResponse(
            success=True, icaoCode=config.get("icaoCode", ""),
            gatesImported=len(config.get("gates", [])),
            taxiwaysImported=len(config.get("osmTaxiways", [])),
            runwaysImported=len(config.get("osmRunways", [])),
            apronsImported=len(config.get("osmAprons", [])),
            warnings=warnings, timestamp=datetime.now(timezone.utc),
        )
    except ParseError as e:
        raise HTTPException(status_code=400, detail=f"MSFS parsing error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"MSFS import error: {str(e)}")


# ── Airport Persistence ──

@router.get("/airports")
async def list_airports() -> dict:
    """List all airports persisted in the lakehouse."""
    service = get_airport_config_service()
    airports = service.list_persisted_airports()
    return {"airports": airports, "count": len(airports)}


@router.get("/airports/preload/status")
async def preload_status() -> dict:
    """List airports available in the cache (Lakebase)."""
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


@router.get("/airports/{icao_code}")
async def get_airport(icao_code: str) -> dict:
    """Get airport configuration (lakehouse first, OSM fallback)."""
    icao_code = _validate_icao(icao_code)
    service = get_airport_config_service()

    loaded = service.initialize_from_lakehouse(icao_code=icao_code, fallback_to_osm=True)

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
        raise HTTPException(status_code=404, detail=f"Airport {icao_code} not found (tried lakehouse and OSM)")


@router.post("/airports/{icao_code}/activate")
async def activate_airport(icao_code: str, user: str = Depends(get_current_user)):
    """Activate an airport: load config, reset state, and ensure synthetic data."""
    icao_code = _validate_icao(icao_code)

    from src.calibration.profile import _iata_to_icao
    icao_code = _iata_to_icao(icao_code)

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

    if _activation_lock.locked():
        raise HTTPException(
            status_code=409,
            detail="Another airport activation is in progress. Please wait.",
        )

    await _activation_lock.acquire()
    asyncio.create_task(_activate_airport_inner(icao_code, user, broadcaster))

    return JSONResponse(
        status_code=202,
        content={"status": "activating", "icaoCode": icao_code},
    )


async def _activate_airport_inner(icao_code: str, user: str, broadcaster) -> None:
    """Inner activation logic, runs as background task."""
    import time as _time

    from src.calibration.profile import _iata_to_icao, _icao_to_iata
    icao_code = _iata_to_icao(icao_code)

    total_steps = 7
    service = get_airport_config_service()
    _t_activate_start = _time.monotonic()

    prev_iata = get_current_airport_iata()
    prev_center = get_airport_center()
    prev_icao = _iata_to_icao(prev_iata)

    logger.info(f"[DIAG] ===== _activate_airport_inner({icao_code}) START =====")

    try:
        try:
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
                logger.error(f"Airport config load for {icao_code} timed out after {_ACTIVATION_TIMEOUT_S}s", exc_info=True)
                await broadcaster.broadcast_progress(
                    1, total_steps, f"Timeout loading config after {_ACTIVATION_TIMEOUT_S}s",
                    icao_code, done=True, error=True,
                )
                return

            if not loaded:
                await broadcaster.broadcast_progress(1, total_steps, "Airport not found", icao_code, done=True, error=True)
                return

            logger.info(f"[DIAG] Step 1 (config load) done in {_time.monotonic() - _t_step:.3f}s — source={loaded}")

            config = service.get_config()
            source = "lakehouse" if config.get("source") == "LAKEHOUSE" else "osm"

            _t_step = _time.monotonic()
            await broadcaster.broadcast_progress(2, total_steps, "Setting airport center...", icao_code)
            from src.ingestion.schedule_generator import AIRPORT_COORDINATES
            iata_code = _icao_to_iata(icao_code)
            if iata_code in AIRPORT_COORDINATES:
                lat, lon = AIRPORT_COORDINATES[iata_code]
            elif config.get("center"):
                lat = config["center"]["latitude"]
                lon = config["center"]["longitude"]
            else:
                lat, lon = _compute_center_from_config(config)
                if lat is None or lon is None:
                    raise ValueError(f"No coordinates available for {icao_code}")

            set_airport_center(lat, lon, iata_code)
            if iata_code != "SFO":
                apply_airport_offset(lat, lon)
            else:
                reset_airport_offset()
            logger.info(f"[DIAG] Step 2 (set center) done in {_time.monotonic() - _t_step:.3f}s")

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

            schedule_svc = get_schedule_service()
            schedule_svc.set_airport(iata_code, icao_code)
            logger.info(f"[DIAG]   schedule_service switched to {iata_code}/{icao_code}")

            broadcaster._prev_flights.clear()
            logger.info(f"[DIAG] Step 3 (gates+reset) done in {_time.monotonic() - _t_step:.3f}s")

        except Exception as e:
            logger.error(f"Airport switch to {icao_code} failed, rolling back:\n{traceback.format_exc()}")
            try:
                await asyncio.to_thread(service.initialize_from_lakehouse, icao_code=prev_icao, fallback_to_osm=True)
                reload_gates()
                set_airport_center(prev_center[0], prev_center[1], prev_iata)
                if prev_iata != "SFO":
                    apply_airport_offset(prev_center[0], prev_center[1])
                else:
                    reset_airport_offset()
                registry = get_model_registry()
                registry.retrain(prev_icao)
                prediction_service = get_prediction_service()
                prediction_service.set_airport(prev_icao)
                schedule_svc = get_schedule_service()
                schedule_svc.set_airport(prev_iata, prev_icao)
                reset_synthetic_state()
                broadcaster._prev_flights.clear()
            except Exception:
                logger.error(f"Rollback to {prev_icao} also failed:\n{traceback.format_exc()}")
            await broadcaster.broadcast_progress(
                total_steps, total_steps,
                f"Airport switch failed: {e}. Rolled back to {prev_iata}.",
                icao_code, done=True, error=True,
            )
            return

        data_generator = get_data_generator_service()
        already_initialized = icao_code in data_generator._initialized_airports
        config_payload = {
            "config": config, "source": source, "icaoCode": icao_code,
            "elementCounts": service.get_element_counts(),
            "dataReady": True, "dataGenerating": not already_initialized,
            "gatesLoaded": len(gates), "gateRecommenderCount": gate_recommender_count,
            "stateReset": reset_result,
        }

        await broadcaster.broadcast({"type": "airport_switch_complete", "data": config_payload})

        _t_ready = _time.monotonic() - _t_activate_start
        await broadcaster.broadcast_progress(total_steps, total_steps, "Airport ready", icao_code, done=True)
        logger.info(f"[DIAG] Airport {icao_code} ready in {_t_ready:.3f}s (UI unblocked)")

        from app.backend.demo_config import save_last_airport
        save_last_airport(icao_code)

        # Restart OpenSky recording for new airport if active
        from app.backend.api.opensky import _recorder
        await _recorder.switch_airport(icao_code, lat, lon)

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

        if not already_initialized:
            async def _generate_data_background():
                try:
                    _t0 = _time.monotonic()
                    await data_generator.switch_airport(icao_code)
                    logger.info(f"[DIAG] Background data gen for {icao_code}: {_time.monotonic() - _t0:.3f}s")
                except Exception as e:
                    logger.error(f"Background data generation failed for {icao_code}: {e}")

            asyncio.create_task(_generate_data_background())

        async def _generate_demo_background():
            from app.backend.services.demo_simulation_service import get_demo_simulation_service
            try:
                demo_svc = get_demo_simulation_service()
                # Always signal demo_ready immediately — live synthetic generator
                # already produces flights via WS. Demo file is optional (replay mode).
                await broadcaster.broadcast({"type": "demo_ready", "data": {"icao": icao_code}})
                if not demo_svc.has_demo(icao_code):
                    await asyncio.to_thread(demo_svc.generate_demo_isolated, icao_code)
                    logger.info(f"[DIAG] Background demo generation for {icao_code} complete")
            except Exception as e:
                logger.error(f"Background demo generation failed for {icao_code}: {e}")

        asyncio.create_task(_generate_demo_background())

        lakebase = get_lakebase_service()
        if lakebase.is_available:
            asyncio.create_task(asyncio.to_thread(lakebase.record_airport_usage, user, icao_code))

    finally:
        _activation_lock.release()


@router.post("/airports/{icao_code}/reload")
async def reload_airport(icao_code: str) -> dict:
    """Force-reload airport from OSM and update all caches."""
    service = get_airport_config_service()

    try:
        osm_config, warnings = await asyncio.to_thread(
            service.import_osm, icao_code,
            include_gates=True, include_terminals=True,
            include_taxiways=True, include_aprons=True,
            include_runways=True, include_hangars=True,
            include_helipads=True, include_parking_positions=True,
            merge=False,
        )

        faa_warnings = []
        if icao_code.startswith("K"):
            try:
                await asyncio.to_thread(service.import_faa, icao_code, True)
            except Exception:
                faa_warnings.append(f"FAA data not available for {icao_code}")

        await asyncio.to_thread(service.persist_config, icao_code)
        await asyncio.to_thread(service.save_to_lakebase_cache, icao_code)

        return {
            "success": True, "icaoCode": icao_code, "source": "osm_reload",
            "elementCounts": service.get_element_counts(),
            "warnings": warnings + faa_warnings,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reload airport {icao_code}: {str(e)}")


@router.post("/airports/{icao_code}/refresh")
async def refresh_airport(
    icao_code: str,
    include_taxiways: bool = Query(default=True),
    include_aprons: bool = Query(default=True),
    include_runways: bool = Query(default=True),
    include_hangars: bool = Query(default=True),
    include_helipads: bool = Query(default=True),
    include_parking_positions: bool = Query(default=True),
) -> dict:
    """Refresh airport data from external sources and persist."""
    service = get_airport_config_service()

    try:
        osm_config, osm_warnings = service.import_osm(
            icao_code, include_gates=True, include_terminals=True,
            include_taxiways=include_taxiways, include_aprons=include_aprons,
            include_runways=include_runways, include_hangars=include_hangars,
            include_helipads=include_helipads, include_parking_positions=include_parking_positions,
        )

        faa_warnings = []
        facility_id = icao_code[1:] if icao_code.startswith("K") else icao_code
        try:
            faa_config, faa_warnings = service.import_faa(facility_id)
        except Exception:
            faa_warnings.append(f"FAA data not available for {icao_code}")

        return {
            "success": True, "icaoCode": icao_code,
            "elementCounts": service.get_element_counts(),
            "warnings": osm_warnings + faa_warnings,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to refresh airport {icao_code}: {str(e)}")


@router.delete("/airports/{icao_code}")
async def delete_airport(icao_code: str) -> dict:
    """Delete an airport from the lakehouse."""
    icao_code = _validate_icao(icao_code)
    service = get_airport_config_service()

    if service.delete_persisted_airport(icao_code):
        return {"success": True, "message": f"Deleted airport {icao_code}"}
    else:
        raise HTTPException(status_code=500, detail=f"Failed to delete airport {icao_code}")


@router.post("/airports/preload")
async def preload_airports(
    icao_codes: list[str] = Body(default=None),
) -> dict:
    """Pre-load airports into the lakehouse cache."""
    from app.backend.api.websocket import broadcaster

    codes = icao_codes if icao_codes else list(WELL_KNOWN_AIRPORT_INFO.keys())
    service = get_airport_config_service()

    persisted = service.list_persisted_airports()
    persisted_codes = {a.get("icao_code", a.get("icaoCode", "")).upper() for a in persisted}

    already_cached = [c for c in codes if c.upper() in persisted_codes]
    to_preload = [c for c in codes if c.upper() not in persisted_codes]

    preloaded = []
    failed = []

    for i, icao in enumerate(to_preload, 1):
        await broadcaster.broadcast_progress(
            i, len(to_preload), f"Pre-loading {icao} ({i}/{len(to_preload)})...", icao,
        )
        try:
            loaded = service.initialize_from_lakehouse(icao_code=icao.upper(), fallback_to_osm=True)
            if loaded:
                preloaded.append(icao.upper())
            else:
                failed.append({"icao": icao.upper(), "error": "Load returned false"})
        except Exception as e:
            logger.error(f"Failed to preload {icao}: {e}")
            failed.append({"icao": icao.upper(), "error": str(e)})

    await broadcaster.broadcast_progress(len(to_preload), len(to_preload), "Pre-load complete", "all", done=True)

    return {"preloaded": preloaded, "already_cached": already_cached, "failed": failed}

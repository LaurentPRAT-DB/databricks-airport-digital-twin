"""OpenSky Network API endpoints for live ADS-B flight data."""

import logging

from fastapi import APIRouter, HTTPException

from app.backend.services.opensky_service import get_opensky_service
from app.backend.services.airport_config_service import get_airport_config_service

logger = logging.getLogger(__name__)

opensky_router = APIRouter(prefix="/api/opensky", tags=["opensky"])


def _get_airport_center() -> tuple[float, float]:
    """Get the current airport's center coordinates."""
    service = get_airport_config_service()
    config = service.get_config()

    # Try reference point from config
    ref = config.get("reference_point") or config.get("referencePoint")
    if ref and "latitude" in ref and "longitude" in ref:
        return float(ref["latitude"]), float(ref["longitude"])

    # Fall back to converter reference
    converter = getattr(service, "_converter", None)
    if converter:
        return converter.reference_lat, converter.reference_lon

    raise HTTPException(status_code=503, detail="No airport loaded — cannot determine location")


@opensky_router.get("/flights")
async def get_opensky_flights() -> dict:
    """Fetch live flights from OpenSky Network for the current airport.

    Returns flights in the same schema as /api/flights for easy frontend consumption.
    """
    lat, lon = _get_airport_center()
    opensky = get_opensky_service()
    flights = await opensky.fetch_flights(lat, lon)

    return {
        "flights": flights,
        "count": len(flights),
        "data_source": "opensky",
    }


@opensky_router.get("/status")
async def get_opensky_status() -> dict:
    """Return OpenSky service health and last fetch info."""
    opensky = get_opensky_service()
    return opensky.get_status()


@opensky_router.get("/diag")
async def opensky_diagnostic() -> dict:
    """Diagnostic endpoint to test OpenSky API connectivity from this environment.

    Does a single fetch and returns detailed results including raw response info.
    Always available (no DEBUG_MODE requirement) for deployment debugging.
    """
    import httpx
    import time

    lat, lon = _get_airport_center()
    radius = 0.5
    params = {
        "lamin": lat - radius,
        "lamax": lat + radius,
        "lomin": lon - radius,
        "lomax": lon + radius,
    }

    result: dict = {
        "airport_center": {"lat": lat, "lon": lon},
        "bounding_box": params,
        "api_url": "https://opensky-network.org/api/states/all",
    }

    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                "https://opensky-network.org/api/states/all",
                params=params,
            )
        elapsed_ms = (time.monotonic() - t0) * 1000

        result["http_status"] = response.status_code
        result["elapsed_ms"] = round(elapsed_ms, 1)
        result["response_headers"] = dict(response.headers)

        if response.status_code == 200:
            data = response.json()
            states = data.get("states") or []
            result["raw_time"] = data.get("time")
            result["state_count"] = len(states)
            if states:
                result["sample_state"] = states[0]
        else:
            result["response_body"] = response.text[:500]

    except Exception as e:
        elapsed_ms = (time.monotonic() - t0) * 1000
        result["error"] = f"{type(e).__name__}: {e}"
        result["elapsed_ms"] = round(elapsed_ms, 1)

    # Also include service status
    opensky = get_opensky_service()
    result["service_status"] = opensky.get_status()

    logger.info("OpenSky diag: status=%s, states=%s, elapsed=%.0fms",
                result.get("http_status"), result.get("state_count"), result.get("elapsed_ms", 0))

    return result

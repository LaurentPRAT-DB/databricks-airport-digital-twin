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

"""REST API routes for the Airport Digital Twin."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.backend.models.flight import FlightListResponse, FlightPosition
from app.backend.services.flight_service import FlightService, get_flight_service


router = APIRouter(prefix="/api", tags=["flights"])


@router.get("/flights", response_model=FlightListResponse)
async def get_flights(
    count: int = Query(default=50, ge=1, le=500, description="Number of flights"),
    service: FlightService = Depends(get_flight_service),
) -> FlightListResponse:
    """
    Get current flight positions.

    Returns a list of flight positions with their current status.
    """
    return await service.get_flights(count=count)


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

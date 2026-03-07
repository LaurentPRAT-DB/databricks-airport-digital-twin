"""REST API routes for the Airport Digital Twin."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.backend.models.flight import (
    FlightListResponse,
    FlightPosition,
    TrajectoryPoint,
    TrajectoryResponse,
)
from app.backend.services.flight_service import FlightService, get_flight_service
from app.backend.services.delta_service import get_delta_service


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


@router.get("/flights/{icao24}/trajectory", response_model=TrajectoryResponse)
async def get_flight_trajectory(
    icao24: str,
    minutes: int = Query(default=60, ge=1, le=1440, description="Minutes of history"),
    limit: int = Query(default=1000, ge=1, le=5000, description="Max points to return"),
) -> TrajectoryResponse:
    """
    Get trajectory history for a specific flight from Unity Catalog.

    Returns a time-series of positions for trajectory visualization,
    analytics, and ML training. Data is stored in Delta tables for
    full historical analysis.

    Args:
        icao24: The ICAO24 address (hex) of the aircraft.
        minutes: How many minutes of history to retrieve (default: 60, max: 1440/24h).
        limit: Maximum number of points to return (default: 1000).

    Returns:
        Trajectory with list of positions ordered by time.

    Raises:
        404: If no trajectory data found for this flight.
    """
    delta = get_delta_service()
    trajectory_data = delta.get_trajectory(icao24, minutes=minutes, limit=limit)

    if trajectory_data is None or len(trajectory_data) == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No trajectory data found for flight {icao24}"
        )

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

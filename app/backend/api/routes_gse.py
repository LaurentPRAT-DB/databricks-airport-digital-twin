"""GSE (Ground Support Equipment) endpoints — fleet status, turnaround."""

from typing import Optional

from fastapi import APIRouter, Query

from app.backend.models.gse import GSEFleetStatus, TurnaroundResponse
from app.backend.services.gse_service import get_gse_service

router = APIRouter(prefix="/api", tags=["gse"])


@router.get("/gse/status", response_model=GSEFleetStatus)
async def get_gse_fleet_status() -> GSEFleetStatus:
    """Get overall GSE fleet status."""
    service = get_gse_service()
    return service.get_fleet_status()


@router.get("/turnaround/{icao24}", response_model=TurnaroundResponse)
async def get_turnaround_status(
    icao24: str,
    gate: Optional[str] = Query(default=None, description="Gate assignment"),
    aircraft_type: str = Query(default="A320", description="Aircraft type"),
) -> TurnaroundResponse:
    """Get turnaround status for an aircraft at gate."""
    service = get_gse_service()
    return service.get_turnaround_status(
        icao24=icao24,
        gate=gate,
        aircraft_type=aircraft_type,
    )

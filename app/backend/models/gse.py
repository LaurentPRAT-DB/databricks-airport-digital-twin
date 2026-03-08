"""Ground Support Equipment (GSE) models for turnaround operations."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class GSEType(str, Enum):
    """Types of ground support equipment."""
    PUSHBACK_TUG = "pushback_tug"
    FUEL_TRUCK = "fuel_truck"
    BELT_LOADER = "belt_loader"
    PASSENGER_STAIRS = "passenger_stairs"
    CATERING_TRUCK = "catering_truck"
    LAVATORY_TRUCK = "lavatory_truck"
    GROUND_POWER = "ground_power"
    AIR_START = "air_start"


class GSEStatus(str, Enum):
    """Status of GSE unit."""
    AVAILABLE = "available"
    EN_ROUTE = "en_route"
    SERVICING = "servicing"
    RETURNING = "returning"
    MAINTENANCE = "maintenance"


class TurnaroundPhase(str, Enum):
    """Phases of aircraft turnaround."""
    ARRIVAL_TAXI = "arrival_taxi"
    CHOCKS_ON = "chocks_on"
    DEBOARDING = "deboarding"
    UNLOADING = "unloading"
    CLEANING = "cleaning"
    CATERING = "catering"
    REFUELING = "refueling"
    LOADING = "loading"
    BOARDING = "boarding"
    CHOCKS_OFF = "chocks_off"
    PUSHBACK = "pushback"
    DEPARTURE_TAXI = "departure_taxi"
    COMPLETE = "complete"


class GSEUnit(BaseModel):
    """Model representing a ground support equipment unit."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "unit_id": "TUG-001",
                "gse_type": "pushback_tug",
                "status": "servicing",
                "assigned_flight": "UA123",
                "position": {"x": 100.0, "y": 50.0},
            }
        }
    )

    unit_id: str = Field(..., description="Unique GSE unit identifier")
    gse_type: GSEType = Field(..., description="Type of equipment")
    status: GSEStatus = Field(GSEStatus.AVAILABLE, description="Current status")
    assigned_flight: Optional[str] = Field(None, description="Assigned flight number")
    assigned_gate: Optional[str] = Field(None, description="Gate location")
    position_x: float = Field(0.0, description="X position relative to gate")
    position_y: float = Field(0.0, description="Y position relative to gate")


class TurnaroundStatus(BaseModel):
    """Model representing aircraft turnaround status."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "icao24": "a12345",
                "flight_number": "UA123",
                "gate": "B12",
                "current_phase": "refueling",
                "phase_progress_pct": 45,
                "total_progress_pct": 60,
                "estimated_departure": "2026-03-08T15:30:00Z",
            }
        }
    )

    icao24: str = Field(..., description="ICAO24 address of aircraft")
    flight_number: Optional[str] = Field(None, description="Flight number")
    gate: str = Field(..., description="Gate assignment")
    arrival_time: Optional[datetime] = Field(None, description="Actual arrival time")
    current_phase: TurnaroundPhase = Field(..., description="Current turnaround phase")
    phase_start_time: Optional[datetime] = Field(None, description="Phase start time")
    phase_progress_pct: int = Field(0, description="Progress within current phase (0-100)")
    total_progress_pct: int = Field(0, description="Overall turnaround progress (0-100)")
    estimated_departure: Optional[datetime] = Field(None, description="Estimated departure")
    assigned_gse: list[GSEUnit] = Field(default_factory=list, description="Assigned GSE units")
    aircraft_type: Optional[str] = Field(None, description="Aircraft type for timing")


class GSEFleetStatus(BaseModel):
    """Response model for GSE fleet status."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "total_units": 50,
                "available": 20,
                "in_service": 25,
                "maintenance": 5,
                "units": [],
                "timestamp": "2026-03-08T12:00:00Z",
            }
        }
    )

    total_units: int = Field(..., description="Total GSE units in fleet")
    available: int = Field(..., description="Available units")
    in_service: int = Field(..., description="Units currently servicing aircraft")
    maintenance: int = Field(0, description="Units in maintenance")
    units: list[GSEUnit] = Field(..., description="All GSE units")
    timestamp: datetime = Field(default_factory=_utc_now, description="Response timestamp")


class TurnaroundResponse(BaseModel):
    """Response model for turnaround status endpoint."""

    turnaround: TurnaroundStatus = Field(..., description="Turnaround status")
    timestamp: datetime = Field(default_factory=_utc_now, description="Response timestamp")

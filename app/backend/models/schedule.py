"""Flight schedule models for FIDS (Flight Information Display System)."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class FlightStatus(str, Enum):
    """Flight status for schedule display."""
    SCHEDULED = "scheduled"
    ON_TIME = "on_time"
    DELAYED = "delayed"
    BOARDING = "boarding"
    FINAL_CALL = "final_call"
    GATE_CLOSED = "gate_closed"
    DEPARTED = "departed"
    ARRIVED = "arrived"
    CANCELLED = "cancelled"


class FlightType(str, Enum):
    """Type of flight movement."""
    ARRIVAL = "arrival"
    DEPARTURE = "departure"


class ScheduledFlight(BaseModel):
    """Model representing a scheduled flight."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "flight_number": "UA123",
                "airline": "United Airlines",
                "airline_code": "UAL",
                "origin": "LAX",
                "destination": "SFO",
                "scheduled_time": "2026-03-08T14:30:00Z",
                "estimated_time": "2026-03-08T14:45:00Z",
                "actual_time": None,
                "gate": "B12",
                "status": "delayed",
                "delay_minutes": 15,
                "aircraft_type": "A320",
                "flight_type": "arrival",
            }
        }
    )

    flight_number: str = Field(..., description="Flight number (e.g., UA123)")
    airline: str = Field(..., description="Airline name")
    airline_code: str = Field(..., description="ICAO airline code")
    origin: str = Field(..., description="Origin airport IATA code")
    destination: str = Field(..., description="Destination airport IATA code")
    scheduled_time: datetime = Field(..., description="Scheduled arrival/departure time")
    estimated_time: Optional[datetime] = Field(None, description="Estimated time (if delayed)")
    actual_time: Optional[datetime] = Field(None, description="Actual time (if arrived/departed)")
    gate: Optional[str] = Field(None, description="Gate assignment")
    status: FlightStatus = Field(FlightStatus.SCHEDULED, description="Flight status")
    delay_minutes: int = Field(0, description="Delay in minutes")
    delay_reason: Optional[str] = Field(None, description="IATA delay reason code")
    aircraft_type: Optional[str] = Field(None, description="Aircraft type code")
    flight_type: FlightType = Field(..., description="Arrival or departure")
    icao24: Optional[str] = Field(None, description="ICAO24 address if tracked")


class ScheduleResponse(BaseModel):
    """Response model for schedule endpoints."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "flights": [],
                "count": 0,
                "timestamp": "2026-03-08T12:00:00Z",
                "airport": "SFO",
                "flight_type": "arrival",
            }
        }
    )

    flights: list[ScheduledFlight] = Field(..., description="List of scheduled flights")
    count: int = Field(..., description="Number of flights")
    timestamp: datetime = Field(default_factory=_utc_now, description="Response timestamp")
    airport: str = Field("SFO", description="Airport code")
    flight_type: FlightType = Field(..., description="Arrivals or departures")

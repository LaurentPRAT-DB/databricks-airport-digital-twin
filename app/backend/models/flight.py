"""Flight data models for the Airport Digital Twin API."""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class FlightPosition(BaseModel):
    """Model representing a flight's position and status."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "icao24": "a12345",
                "callsign": "UAL123",
                "latitude": 37.6213,
                "longitude": -122.3790,
                "altitude": 5000.0,
                "velocity": 200.0,
                "heading": 270.0,
                "on_ground": False,
                "vertical_rate": 5.0,
                "last_seen": 1709654400,
                "data_source": "synthetic",
                "flight_phase": "cruise",
            }
        }
    )

    icao24: str = Field(..., description="ICAO 24-bit address (hex)")
    callsign: Optional[str] = Field(None, description="Aircraft callsign")
    latitude: Optional[float] = Field(None, description="Latitude in degrees")
    longitude: Optional[float] = Field(None, description="Longitude in degrees")
    altitude: Optional[float] = Field(None, description="Altitude in meters")
    velocity: Optional[float] = Field(None, description="Ground speed in m/s")
    heading: Optional[float] = Field(None, description="True track in degrees")
    on_ground: bool = Field(False, description="Whether aircraft is on ground")
    vertical_rate: Optional[float] = Field(None, description="Vertical rate in m/s")
    last_seen: Optional[int] = Field(None, description="Unix timestamp of last contact")
    data_source: str = Field("synthetic", description="Source of the data")
    flight_phase: Optional[str] = Field(None, description="Current flight phase")


class FlightListResponse(BaseModel):
    """Response model for flight list endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "flights": [],
                "count": 0,
                "timestamp": "2024-03-05T12:00:00Z",
                "data_source": "synthetic",
            }
        }
    )

    flights: list[FlightPosition] = Field(..., description="List of flight positions")
    count: int = Field(..., description="Number of flights in response")
    timestamp: datetime = Field(
        default_factory=_utc_now, description="Response timestamp"
    )
    data_source: str = Field(
        "synthetic", description="Data source: live, cached, or synthetic"
    )


class TrajectoryPoint(BaseModel):
    """A single point in a flight trajectory."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "icao24": "a12345",
                "callsign": "UAL123",
                "latitude": 37.6213,
                "longitude": -122.3790,
                "altitude": 5000.0,
                "velocity": 200.0,
                "heading": 270.0,
                "vertical_rate": 5.0,
                "on_ground": False,
                "flight_phase": "cruise",
                "timestamp": 1709654400,
            }
        }
    )

    icao24: str = Field(..., description="ICAO 24-bit address (hex)")
    callsign: Optional[str] = Field(None, description="Aircraft callsign")
    latitude: Optional[float] = Field(None, description="Latitude in degrees")
    longitude: Optional[float] = Field(None, description="Longitude in degrees")
    altitude: Optional[float] = Field(None, description="Altitude in meters")
    velocity: Optional[float] = Field(None, description="Ground speed in m/s")
    heading: Optional[float] = Field(None, description="True track in degrees")
    vertical_rate: Optional[float] = Field(None, description="Vertical rate in m/s")
    on_ground: bool = Field(False, description="Whether aircraft is on ground")
    flight_phase: Optional[str] = Field(None, description="Flight phase at this point")
    timestamp: int = Field(..., description="Unix timestamp of this position")


class TrajectoryResponse(BaseModel):
    """Response model for trajectory endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "icao24": "a12345",
                "callsign": "UAL123",
                "points": [],
                "count": 0,
                "start_time": 1709650800,
                "end_time": 1709654400,
            }
        }
    )

    icao24: str = Field(..., description="ICAO 24-bit address")
    callsign: Optional[str] = Field(None, description="Aircraft callsign")
    points: list[TrajectoryPoint] = Field(..., description="Trajectory points")
    count: int = Field(..., description="Number of points in trajectory")
    start_time: Optional[int] = Field(None, description="Earliest timestamp")
    end_time: Optional[int] = Field(None, description="Latest timestamp")

"""Baggage handling system models."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class BagStatus(str, Enum):
    """Status of a bag in the handling system."""
    CHECKED_IN = "checked_in"
    SECURITY_SCREENING = "security_screening"
    SORTED = "sorted"
    LOADED = "loaded"
    IN_TRANSIT = "in_transit"
    UNLOADED = "unloaded"
    ON_CAROUSEL = "on_carousel"
    CLAIMED = "claimed"
    MISCONNECT = "misconnect"
    LOST = "lost"


class Bag(BaseModel):
    """Model representing a single bag."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "bag_id": "UA123-0001",
                "flight_number": "UA123",
                "status": "loaded",
                "is_connecting": False,
                "connecting_flight": None,
                "check_in_time": "2026-03-08T12:00:00Z",
            }
        }
    )

    bag_id: str = Field(..., description="Unique bag identifier")
    flight_number: str = Field(..., description="Flight number")
    passenger_name: Optional[str] = Field(None, description="Passenger name (anonymized)")
    status: BagStatus = Field(BagStatus.CHECKED_IN, description="Current bag status")
    is_connecting: bool = Field(False, description="Whether this is a connecting bag")
    connecting_flight: Optional[str] = Field(None, description="Connecting flight number")
    origin: Optional[str] = Field(None, description="Origin airport")
    destination: Optional[str] = Field(None, description="Final destination")
    check_in_time: Optional[datetime] = Field(None, description="Check-in timestamp")
    carousel: Optional[int] = Field(None, description="Assigned carousel number")


class FlightBaggageStats(BaseModel):
    """Baggage statistics for a single flight."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "flight_number": "UA123",
                "total_bags": 180,
                "loaded": 165,
                "loading_progress_pct": 92,
                "connecting_bags": 27,
                "misconnects": 2,
            }
        }
    )

    flight_number: str = Field(..., description="Flight number")
    icao24: Optional[str] = Field(None, description="ICAO24 address if tracked")
    total_bags: int = Field(..., description="Total bags for this flight")
    checked_in: int = Field(0, description="Bags checked in")
    loaded: int = Field(0, description="Bags loaded on aircraft")
    unloaded: int = Field(0, description="Bags unloaded (arrivals)")
    on_carousel: int = Field(0, description="Bags on carousel")
    loading_progress_pct: int = Field(0, description="Loading progress (0-100)")
    connecting_bags: int = Field(0, description="Number of connecting bags")
    misconnects: int = Field(0, description="Number of misconnected bags")
    carousel: Optional[int] = Field(None, description="Assigned carousel (arrivals)")


class BaggageAlert(BaseModel):
    """Alert for baggage issues."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "alert_id": "ALERT-001",
                "alert_type": "misconnect",
                "bag_id": "UA123-0042",
                "flight_number": "UA456",
                "message": "Bag may miss connection - tight transfer time",
            }
        }
    )

    alert_id: str = Field(..., description="Unique alert identifier")
    alert_type: str = Field(..., description="Type of alert")
    bag_id: str = Field(..., description="Related bag ID")
    flight_number: str = Field(..., description="Affected flight")
    connecting_flight: Optional[str] = Field(None, description="Connecting flight if applicable")
    message: str = Field(..., description="Alert message")
    created_at: datetime = Field(default_factory=_utc_now, description="Alert timestamp")
    resolved: bool = Field(False, description="Whether alert is resolved")


class BaggageStatsResponse(BaseModel):
    """Response model for overall baggage statistics."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "total_bags_today": 15000,
                "bags_in_system": 3500,
                "misconnect_rate_pct": 1.8,
                "avg_processing_time_min": 25,
            }
        }
    )

    total_bags_today: int = Field(..., description="Total bags processed today")
    bags_in_system: int = Field(..., description="Bags currently in system")
    loaded_departures: int = Field(0, description="Bags loaded on departures")
    delivered_arrivals: int = Field(0, description="Bags delivered to carousels")
    connecting_bags: int = Field(0, description="Connecting bags in transit")
    misconnects: int = Field(0, description="Misconnected bags today")
    misconnect_rate_pct: float = Field(0.0, description="Misconnect rate percentage")
    avg_processing_time_min: int = Field(0, description="Average processing time")
    timestamp: datetime = Field(default_factory=_utc_now, description="Response timestamp")


class FlightBaggageResponse(BaseModel):
    """Response model for flight baggage endpoint."""

    stats: FlightBaggageStats = Field(..., description="Flight baggage statistics")
    bags: list[Bag] = Field(default_factory=list, description="Individual bags (sample)")
    timestamp: datetime = Field(default_factory=_utc_now, description="Response timestamp")


class BaggageAlertsResponse(BaseModel):
    """Response model for baggage alerts endpoint."""

    alerts: list[BaggageAlert] = Field(..., description="Active alerts")
    count: int = Field(..., description="Number of alerts")
    timestamp: datetime = Field(default_factory=_utc_now, description="Response timestamp")

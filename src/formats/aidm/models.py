"""
AIDM Pydantic Models

Models for IATA Airport Industry Data Model (AIDM) 12.0 data structures.
These models focus on operational data relevant for airport visualization:
- Flights and flight legs
- Resources (gates, carousels, check-in desks)
- Events and notifications

Reference: IATA AIDM 12.0 specification
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class FlightType(str, Enum):
    """Flight type classification."""
    SCHEDULED = "J"
    CHARTER = "C"
    CARGO = "F"
    GENERAL_AVIATION = "G"
    MILITARY = "M"
    POSITIONING = "P"
    TECHNICAL = "T"


class FlightServiceType(str, Enum):
    """Service type of flight."""
    PASSENGER = "J"
    CARGO = "F"
    MAIL = "M"
    MIXED = "X"


class MovementType(str, Enum):
    """Flight movement type."""
    ARRIVAL = "A"
    DEPARTURE = "D"
    DOMESTIC = "D"
    INTERNATIONAL = "I"
    TURNAROUND = "T"


class AIDMResourceType(str, Enum):
    """Types of airport resources."""
    GATE = "GATE"
    STAND = "STAND"
    BAGGAGE_CLAIM = "BAGGAGE_CLAIM"
    CHECK_IN = "CHECK_IN"
    SECURITY = "SECURITY"
    BOARDING = "BOARDING"
    RUNWAY = "RUNWAY"
    TAXIWAY = "TAXIWAY"
    DEICING = "DEICING"


class AIDMEventType(str, Enum):
    """Operational event types."""
    SCHEDULED = "SCHEDULED"
    ESTIMATED = "ESTIMATED"
    ACTUAL = "ACTUAL"
    CANCELLED = "CANCELLED"
    DIVERTED = "DIVERTED"
    DELAYED = "DELAYED"
    BOARDING = "BOARDING"
    FINAL_CALL = "FINAL_CALL"
    GATE_CLOSED = "GATE_CLOSED"
    DEPARTED = "DEPARTED"
    LANDED = "LANDED"
    ON_BLOCK = "ON_BLOCK"
    OFF_BLOCK = "OFF_BLOCK"


class AIDMCodeContext(BaseModel):
    """Code context for airline/airport codes."""
    code: str
    code_context: str = Field(default="IATA", alias="codeContext")

    class Config:
        populate_by_name = True


class AIDMAirport(BaseModel):
    """Airport reference."""
    code: str = Field(..., description="IATA airport code")
    code_context: str = Field(default="IATA", alias="codeContext")
    terminal: Optional[str] = None

    class Config:
        populate_by_name = True


class AIDMAirline(BaseModel):
    """Airline reference."""
    code: str = Field(..., description="IATA airline code")
    code_context: str = Field(default="IATA", alias="codeContext")
    name: Optional[str] = None

    class Config:
        populate_by_name = True


class AIDMAircraft(BaseModel):
    """Aircraft information."""
    registration: Optional[str] = None
    aircraft_type: str = Field(..., alias="aircraftType", description="IATA aircraft type code")
    icao_type: Optional[str] = Field(None, alias="icaoType", description="ICAO aircraft type")
    configuration: Optional[str] = None
    owner: Optional[AIDMAirline] = None

    class Config:
        populate_by_name = True


class AIDMFlightId(BaseModel):
    """Flight identifier."""
    airline: AIDMAirline
    flight_number: str = Field(..., alias="flightNumber")
    suffix: Optional[str] = None
    operational_date: datetime = Field(..., alias="operationalDate")

    @property
    def full_flight_number(self) -> str:
        suffix = self.suffix or ""
        return f"{self.airline.code}{self.flight_number}{suffix}"

    class Config:
        populate_by_name = True


class AIDMTime(BaseModel):
    """Time representation with type qualifier."""
    time: datetime
    time_type: AIDMEventType = Field(..., alias="timeType")

    class Config:
        populate_by_name = True


class AIDMResource(BaseModel):
    """Airport resource allocation."""
    resource_type: AIDMResourceType = Field(..., alias="resourceType")
    resource_id: str = Field(..., alias="resourceId")
    terminal: Optional[str] = None
    area: Optional[str] = None
    start_time: Optional[datetime] = Field(None, alias="startTime")
    end_time: Optional[datetime] = Field(None, alias="endTime")

    class Config:
        populate_by_name = True


class AIDMGate(BaseModel):
    """Gate resource."""
    gate_id: str = Field(..., alias="gateId")
    terminal: Optional[str] = None
    gate_type: Optional[str] = Field(None, alias="gateType")  # Contact, Remote
    position: Optional[dict[str, float]] = None  # lat, lon

    class Config:
        populate_by_name = True


class AIDMBaggageClaim(BaseModel):
    """Baggage claim carousel."""
    carousel_id: str = Field(..., alias="carouselId")
    terminal: Optional[str] = None
    first_bag_time: Optional[datetime] = Field(None, alias="firstBagTime")
    last_bag_time: Optional[datetime] = Field(None, alias="lastBagTime")

    class Config:
        populate_by_name = True


class AIDMCheckIn(BaseModel):
    """Check-in desk allocation."""
    desk_range: str = Field(..., alias="deskRange", description="e.g., '1-5'")
    terminal: Optional[str] = None
    open_time: Optional[datetime] = Field(None, alias="openTime")
    close_time: Optional[datetime] = Field(None, alias="closeTime")

    class Config:
        populate_by_name = True


class AIDMFlightLeg(BaseModel):
    """
    Single flight leg (one takeoff/landing pair).

    A flight may have multiple legs (e.g., SFO-LAX-DFW).
    """
    leg_id: str = Field(..., alias="legId")
    sequence: int = 1

    # Airports
    departure_airport: AIDMAirport = Field(..., alias="departureAirport")
    arrival_airport: AIDMAirport = Field(..., alias="arrivalAirport")

    # Times
    scheduled_departure: Optional[datetime] = Field(None, alias="scheduledDeparture")
    estimated_departure: Optional[datetime] = Field(None, alias="estimatedDeparture")
    actual_departure: Optional[datetime] = Field(None, alias="actualDeparture")
    scheduled_arrival: Optional[datetime] = Field(None, alias="scheduledArrival")
    estimated_arrival: Optional[datetime] = Field(None, alias="estimatedArrival")
    actual_arrival: Optional[datetime] = Field(None, alias="actualArrival")

    # Resources
    departure_gate: Optional[AIDMGate] = Field(None, alias="departureGate")
    arrival_gate: Optional[AIDMGate] = Field(None, alias="arrivalGate")
    runway: Optional[str] = None
    stand: Optional[str] = None

    # Status
    cancelled: bool = False
    diverted: bool = False
    diversion_airport: Optional[AIDMAirport] = Field(None, alias="diversionAirport")

    class Config:
        populate_by_name = True


class AIDMFlight(BaseModel):
    """
    AIDM Flight record.

    Represents a complete flight with all legs and resources.
    """
    flight_id: AIDMFlightId = Field(..., alias="flightId")
    flight_type: FlightType = Field(default=FlightType.SCHEDULED, alias="flightType")
    service_type: FlightServiceType = Field(default=FlightServiceType.PASSENGER, alias="serviceType")

    # Aircraft
    aircraft: Optional[AIDMAircraft] = None

    # Legs
    legs: list[AIDMFlightLeg] = Field(default_factory=list)

    # Code shares
    codeshares: list[AIDMFlightId] = Field(default_factory=list)

    # Resources
    gate: Optional[AIDMGate] = None
    check_in: Optional[AIDMCheckIn] = Field(None, alias="checkIn")
    baggage_claim: Optional[AIDMBaggageClaim] = Field(None, alias="baggageClaim")

    # Status
    status: AIDMEventType = AIDMEventType.SCHEDULED
    remarks: Optional[str] = None

    @property
    def callsign(self) -> str:
        return self.flight_id.full_flight_number

    @property
    def is_arrival(self) -> bool:
        """Check if this is an arrival at the local airport."""
        return len(self.legs) > 0 and self.legs[-1].arrival_airport is not None

    @property
    def is_departure(self) -> bool:
        """Check if this is a departure from the local airport."""
        return len(self.legs) > 0 and self.legs[0].departure_airport is not None

    class Config:
        populate_by_name = True


class AIDMEvent(BaseModel):
    """
    Operational event notification.

    Events track status changes for flights and resources.
    """
    event_id: str = Field(..., alias="eventId")
    event_type: AIDMEventType = Field(..., alias="eventType")
    timestamp: datetime
    flight_id: Optional[AIDMFlightId] = Field(None, alias="flightId")
    resource: Optional[AIDMResource] = None
    description: Optional[str] = None
    source: Optional[str] = None

    class Config:
        populate_by_name = True


class AIDMDocument(BaseModel):
    """
    Parsed AIDM Document.

    Contains flights, resources, and events from an AIDM feed.
    """
    version: str = Field(default="12.0")
    airport: Optional[AIDMAirport] = Field(None, description="Local airport context")
    timestamp: Optional[datetime] = None
    flights: list[AIDMFlight] = Field(default_factory=list)
    resources: list[AIDMResource] = Field(default_factory=list)
    events: list[AIDMEvent] = Field(default_factory=list)
    gates: list[AIDMGate] = Field(default_factory=list)

    class Config:
        populate_by_name = True

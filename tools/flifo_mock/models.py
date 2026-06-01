"""Pydantic models matching SITA FLIFO API response format."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AirlineInfo(BaseModel):
    iataCode: str
    icaoCode: str
    name: str


class AirportPoint(BaseModel):
    iataCode: str
    icaoCode: str
    scheduledTime: str
    estimatedTime: Optional[str] = None
    actualTime: Optional[str] = None
    terminal: Optional[str] = None
    gate: Optional[str] = None
    baggageBelt: Optional[str] = None


class AircraftInfo(BaseModel):
    registration: Optional[str] = None
    iataType: Optional[str] = None
    icaoType: Optional[str] = None


class CodeshareInfo(BaseModel):
    flightNumber: str
    airline: dict


class FlightRecord(BaseModel):
    flightNumber: str
    airline: AirlineInfo
    departure: AirportPoint
    arrival: AirportPoint
    statusCode: str
    statusDescription: str
    delayMinutes: int = 0
    delayCode: Optional[str] = None
    aircraft: AircraftInfo
    codeshares: list[CodeshareInfo] = []
    updatedAt: str


class FlightResponse(BaseModel):
    flightRecords: list[FlightRecord]
    totalRecords: int
    airport: str
    direction: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600

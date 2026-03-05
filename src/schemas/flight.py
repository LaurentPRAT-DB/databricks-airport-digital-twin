"""Flight data models for the Airport Digital Twin.

This module defines the schema structures for flight data at different
layers of the medallion architecture:
- FlightPosition: Silver layer schema for cleaned flight position data
- FlightStatus: Gold layer schema for aggregated flight status
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class FlightPhase(str, Enum):
    """Flight phase classification based on vertical movement."""

    GROUND = "ground"
    CLIMBING = "climbing"
    DESCENDING = "descending"
    CRUISING = "cruising"
    UNKNOWN = "unknown"


@dataclass
class FlightPosition:
    """Silver layer schema for cleaned flight position data.

    Represents a single position report from the OpenSky Network.
    All 17 fields from the OpenSky state vector are mapped here.

    Attributes:
        icao24: ICAO 24-bit address (hex string, 6 characters)
        callsign: Aircraft callsign (8 chars max, may be None)
        origin_country: Country of origin
        position_time: Unix timestamp of position update
        last_contact: Unix timestamp of last contact
        longitude: WGS-84 longitude in degrees
        latitude: WGS-84 latitude in degrees
        baro_altitude: Barometric altitude in meters
        on_ground: Whether aircraft is on ground
        velocity: Ground speed in m/s
        true_track: True track angle in degrees (0=north)
        vertical_rate: Vertical rate in m/s
        geo_altitude: Geometric altitude in meters
        squawk: Transponder code
        position_source: Source of position (0=ADS-B, 1=ASTERIX, 2=MLAT, 3=FLARM)
        category: Aircraft category
    """

    icao24: str
    callsign: Optional[str]
    origin_country: str
    position_time: int
    last_contact: int
    longitude: Optional[float]
    latitude: Optional[float]
    baro_altitude: Optional[float]
    on_ground: bool
    velocity: Optional[float]
    true_track: Optional[float]
    vertical_rate: Optional[float]
    geo_altitude: Optional[float]
    squawk: Optional[str]
    position_source: int
    category: Optional[int]


@dataclass
class FlightStatus:
    """Gold layer schema for aggregated flight status.

    Represents the current state of a flight with computed metrics
    and flight phase classification.

    Attributes:
        icao24: ICAO 24-bit address
        callsign: Aircraft callsign
        origin_country: Country of origin
        last_seen: Unix timestamp of last position update
        longitude: Current longitude
        latitude: Current latitude
        altitude: Current altitude in meters
        velocity: Current ground speed in m/s
        heading: Current heading in degrees
        on_ground: Whether aircraft is on ground
        vertical_rate: Current vertical rate in m/s
        flight_phase: Computed flight phase
        data_source: Source of position data
    """

    icao24: str
    callsign: Optional[str]
    origin_country: str
    last_seen: int
    longitude: Optional[float]
    latitude: Optional[float]
    altitude: Optional[float]
    velocity: Optional[float]
    heading: Optional[float]
    on_ground: bool
    vertical_rate: Optional[float]
    flight_phase: FlightPhase
    data_source: str

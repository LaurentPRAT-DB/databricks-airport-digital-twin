"""Pydantic models for OpenSky Network API responses."""

from pydantic import BaseModel, field_validator
from typing import Optional, List, Any


class StateVector(BaseModel):
    """
    Represents a single aircraft state vector from OpenSky API.

    The OpenSky API returns state vectors as lists, so this model is used
    for parsing and validation after conversion from list format.

    Fields follow OpenSky API documentation:
    https://openskynetwork.github.io/opensky-api/rest.html#response
    """

    icao24: str                              # 0: Unique ICAO 24-bit address (hex)
    callsign: Optional[str] = None           # 1: Callsign (8 chars, may be null)
    origin_country: str                      # 2: Country of origin
    time_position: Optional[int] = None      # 3: Unix timestamp of last position update
    last_contact: int                        # 4: Unix timestamp of last contact
    longitude: Optional[float] = None        # 5: WGS84 longitude
    latitude: Optional[float] = None         # 6: WGS84 latitude
    baro_altitude: Optional[float] = None    # 7: Barometric altitude in meters
    on_ground: bool                          # 8: Whether aircraft is on ground
    velocity: Optional[float] = None         # 9: Ground speed in m/s
    true_track: Optional[float] = None       # 10: Track angle in degrees (0=north)
    vertical_rate: Optional[float] = None    # 11: Vertical rate in m/s
    sensors: Optional[List[int]] = None      # 12: IDs of receivers (usually null)
    geo_altitude: Optional[float] = None     # 13: Geometric altitude in meters
    squawk: Optional[str] = None             # 14: Transponder code
    spi: bool = False                        # 15: Special position indicator
    position_source: int = 0                 # 16: Source of position (0=ADS-B)
    category: Optional[int] = None           # 17: Aircraft category (may be absent)

    @field_validator("icao24")
    @classmethod
    def validate_icao24(cls, v: str) -> str:
        """Validate ICAO24 is a 6-character hex string."""
        if len(v) != 6:
            raise ValueError(f"icao24 must be 6 characters, got {len(v)}")
        if not all(c in "0123456789abcdefABCDEF" for c in v):
            raise ValueError("icao24 must be hexadecimal")
        return v.lower()

    @classmethod
    def from_list(cls, state_list: List[Any]) -> "StateVector":
        """Create StateVector from OpenSky API list format."""
        # Handle variable length (category field may be absent)
        while len(state_list) < 18:
            state_list.append(None)

        return cls(
            icao24=state_list[0],
            callsign=state_list[1].strip() if state_list[1] else None,
            origin_country=state_list[2],
            time_position=state_list[3],
            last_contact=state_list[4],
            longitude=state_list[5],
            latitude=state_list[6],
            baro_altitude=state_list[7],
            on_ground=state_list[8],
            velocity=state_list[9],
            true_track=state_list[10],
            vertical_rate=state_list[11],
            sensors=state_list[12],
            geo_altitude=state_list[13],
            squawk=state_list[14],
            spi=state_list[15] if state_list[15] is not None else False,
            position_source=state_list[16] if state_list[16] is not None else 0,
            category=state_list[17],
        )


class OpenSkyResponse(BaseModel):
    """
    Response from OpenSky Network /states/all endpoint.

    The 'states' field contains raw list-format state vectors as returned
    by the API. Use StateVector.from_list() to parse individual states.
    """

    time: int                                   # Unix timestamp of response
    states: Optional[List[List[Any]]] = None    # List of state vectors (list format)

    def get_state_vectors(self) -> List[StateVector]:
        """Parse raw states into StateVector objects."""
        if not self.states:
            return []
        return [StateVector.from_list(s) for s in self.states]

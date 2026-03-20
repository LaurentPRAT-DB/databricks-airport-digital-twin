"""
Microsoft Flight Simulator Scenery Pydantic Models

Models for MSFS airport scenery XML data structures.
Focuses on elements relevant to airport visualization:
- TaxiwayParking: Gate/ramp positions
- TaxiwayPoint/TaxiwayPath: Taxi route network
- Runway: Runway geometry
- Apron: Apron area polygons
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ParkingType(str, Enum):
    """MSFS parking spot types."""
    GATE = "GATE"
    RAMP = "RAMP"
    DOCK = "DOCK"


class TaxiPointType(str, Enum):
    """MSFS taxi point types."""
    NORMAL = "NORMAL"
    HOLD_SHORT = "HOLD_SHORT"
    ILS_HOLD_SHORT = "ILS_HOLD_SHORT"


class TaxiPathType(str, Enum):
    """MSFS taxi path types."""
    TAXI = "TAXI"
    RUNWAY = "RUNWAY"
    PARKING = "PARKING"
    PATH = "PATH"
    CLOSED = "CLOSED"


class MSFSParkingSpot(BaseModel):
    """
    MSFS TaxiwayParking element.

    Represents a gate, ramp, or dock parking position.
    """
    index: int = Field(..., description="Parking spot index")
    lat: float = Field(..., description="Latitude (WGS84)")
    lon: float = Field(..., description="Longitude (WGS84)")
    heading: float = Field(0.0, description="Heading in degrees true north")
    radius: float = Field(25.0, description="Parking radius in meters")
    type: ParkingType = Field(ParkingType.RAMP, description="Parking type")
    name: str = Field("", description="Name letter (e.g., 'GATE_A')")
    number: int = Field(0, description="Number part of gate name")
    airline_codes: list[str] = Field(default_factory=list, description="Preferred airline ICAO codes")

    @property
    def is_gate(self) -> bool:
        """Check if this is a gate (not a ramp or dock)."""
        return self.type == ParkingType.GATE

    @property
    def display_name(self) -> str:
        """Get human-readable gate/spot name."""
        # MSFS names are like "GATE_A", "RAMP_GA", "DOCK" etc.
        prefix = self.name.replace("GATE_", "").replace("RAMP_", "").replace("DOCK_", "").replace("_", "")
        if self.number > 0:
            return f"{prefix}{self.number}"
        return prefix or f"S{self.index}"


class MSFSTaxiPoint(BaseModel):
    """
    MSFS TaxiwayPoint element.

    A node in the taxi route network.
    """
    index: int = Field(..., description="Point index")
    lat: float = Field(..., description="Latitude (WGS84)")
    lon: float = Field(..., description="Longitude (WGS84)")
    type: TaxiPointType = Field(TaxiPointType.NORMAL, description="Point type")


class MSFSTaxiPath(BaseModel):
    """
    MSFS TaxiwayPath element.

    An edge connecting two TaxiwayPoints in the taxi network.
    """
    start: int = Field(..., description="Start TaxiwayPoint index")
    end: int = Field(..., description="End TaxiwayPoint index")
    width: float = Field(20.0, description="Path width in meters")
    name: str = Field("", description="Taxiway name (e.g., 'A', 'B')")
    type: TaxiPathType = Field(TaxiPathType.TAXI, description="Path type")
    weight_limit: float = Field(0.0, description="Weight limit in lbs")
    surface: str = Field("ASPHALT", description="Surface type")


class MSFSRunwayEnd(BaseModel):
    """One end of an MSFS runway."""
    designator: str = Field("", description="Runway designator (e.g., '28L')")
    lat: float = Field(0.0, description="Latitude")
    lon: float = Field(0.0, description="Longitude")


class MSFSRunway(BaseModel):
    """
    MSFS Runway element.
    """
    lat: float = Field(..., description="Center latitude (WGS84)")
    lon: float = Field(..., description="Center longitude (WGS84)")
    heading: float = Field(0.0, description="Heading in degrees true north")
    length: float = Field(0.0, description="Length in meters")
    width: float = Field(45.0, description="Width in meters")
    surface: str = Field("ASPHALT", description="Surface type")
    designator: str = Field("", description="Primary designator")
    primary_end: Optional[MSFSRunwayEnd] = Field(None, description="Primary runway end")
    secondary_end: Optional[MSFSRunwayEnd] = Field(None, description="Secondary runway end")


class MSFSApronVertex(BaseModel):
    """A vertex in an MSFS apron polygon."""
    lat: float
    lon: float


class MSFSApron(BaseModel):
    """
    MSFS Apron element.

    A polygonal apron area defined by vertices.
    """
    surface: str = Field("ASPHALT", description="Surface type")
    vertices: list[MSFSApronVertex] = Field(default_factory=list, description="Polygon vertices")

    @property
    def center(self) -> tuple[float, float]:
        """Calculate centroid of apron polygon."""
        if not self.vertices:
            return (0.0, 0.0)
        lats = [v.lat for v in self.vertices]
        lons = [v.lon for v in self.vertices]
        return (sum(lats) / len(lats), sum(lons) / len(lons))


class MSFSDocument(BaseModel):
    """
    Parsed MSFS scenery data for an airport.

    Top-level container matching FSData > Airport structure.
    """
    airport_name: str = Field("", description="Airport name")
    icao_code: str = Field("", description="ICAO airport code")
    iata_code: str = Field("", description="IATA airport code")
    lat: float = Field(0.0, description="Airport center latitude")
    lon: float = Field(0.0, description="Airport center longitude")
    alt: float = Field(0.0, description="Airport altitude in meters")
    parking_spots: list[MSFSParkingSpot] = Field(default_factory=list)
    taxi_points: list[MSFSTaxiPoint] = Field(default_factory=list)
    taxi_paths: list[MSFSTaxiPath] = Field(default_factory=list)
    runways: list[MSFSRunway] = Field(default_factory=list)
    aprons: list[MSFSApron] = Field(default_factory=list)

    @property
    def gates(self) -> list[MSFSParkingSpot]:
        """Get all gate-type parking spots."""
        return [p for p in self.parking_spots if p.is_gate]

    @property
    def ramps(self) -> list[MSFSParkingSpot]:
        """Get all ramp-type parking spots."""
        return [p for p in self.parking_spots if p.type == ParkingType.RAMP]

    @property
    def taxi_taxiways(self) -> list[MSFSTaxiPath]:
        """Get taxi paths that are actual taxiways (not runway or parking paths)."""
        return [p for p in self.taxi_paths if p.type == TaxiPathType.TAXI]

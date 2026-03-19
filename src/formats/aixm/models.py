"""
AIXM Pydantic Models

Models for AIXM 5.1.1 data structures representing aeronautical features.
These models focus on the core elements needed for airport visualization:
- Runways and runway directions
- Taxiways
- Aprons (parking areas)
- Navaids (navigation aids)
- Airport/Heliport metadata

Reference: https://www.aixm.aero/page/aixm-511
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SurfaceCondition(str, Enum):
    """Surface condition codes per AIXM."""
    DRY = "DRY"
    WET = "WET"
    ICE = "ICE"
    SNOW = "SNOW"
    SLUSH = "SLUSH"
    FLOODED = "FLOODED"


class RunwaySurfaceType(str, Enum):
    """Runway surface composition."""
    ASPHALT = "ASPH"
    CONCRETE = "CONC"
    GRASS = "GRASS"
    GRAVEL = "GRVL"
    SAND = "SAND"
    WATER = "WATER"
    BITUMINOUS = "BITU"
    COMPOSITE = "COMP"


class NavaidType(str, Enum):
    """Navigation aid types."""
    VOR = "VOR"
    VORDME = "VOR_DME"
    TACAN = "TACAN"
    NDB = "NDB"
    ILS = "ILS"
    ILS_DME = "ILS_DME"
    LOCALIZER = "LOC"
    GLIDESLOPE = "GP"
    MARKER = "MKR"
    DME = "DME"


class GMLPoint(BaseModel):
    """GML Point geometry."""
    srs_name: str = Field(default="EPSG:4326", alias="srsName")
    pos: str = Field(..., description="Space-separated lat lon [alt]")

    @property
    def latitude(self) -> float:
        parts = self.pos.split()
        return float(parts[0])

    @property
    def longitude(self) -> float:
        parts = self.pos.split()
        return float(parts[1])

    @property
    def altitude(self) -> float:
        parts = self.pos.split()
        return float(parts[2]) if len(parts) > 2 else 0.0

    model_config = ConfigDict(populate_by_name=True)


class GMLLineString(BaseModel):
    """GML LineString geometry."""
    srs_name: str = Field(default="EPSG:4326", alias="srsName")
    pos_list: str = Field(..., alias="posList", description="Space-separated coordinates")

    @property
    def points(self) -> list[tuple[float, float, float]]:
        """Parse pos_list into list of (lat, lon, alt) tuples."""
        values = self.pos_list.split()
        result = []
        # Typically 2D (lat lon) or 3D (lat lon alt)
        dim = 2  # Default 2D
        if len(values) >= 6 and len(values) % 3 == 0:
            dim = 3
        for i in range(0, len(values), dim):
            lat = float(values[i])
            lon = float(values[i + 1])
            alt = float(values[i + 2]) if dim == 3 else 0.0
            result.append((lat, lon, alt))
        return result

    model_config = ConfigDict(populate_by_name=True)


class GMLPolygon(BaseModel):
    """GML Polygon geometry."""
    srs_name: str = Field(default="EPSG:4326", alias="srsName")
    exterior: GMLLineString

    model_config = ConfigDict(populate_by_name=True)


class AIXMTimeslice(BaseModel):
    """AIXM time slice for temporal validity."""
    valid_time_begin: Optional[datetime] = Field(None, alias="validTimeBegin")
    valid_time_end: Optional[datetime] = Field(None, alias="validTimeEnd")
    interpretation: str = Field(default="BASELINE")

    model_config = ConfigDict(populate_by_name=True)


class AIXMRunwayDirection(BaseModel):
    """
    AIXM Runway Direction (threshold).

    Each physical runway has two directions (e.g., 28L and 10R).
    """
    gml_id: str = Field(..., alias="gmlId")
    designator: str = Field(..., description="Runway designator (e.g., '28L', '10R')")
    true_bearing: Optional[float] = Field(None, alias="trueBearing", description="True bearing in degrees")
    magnetic_bearing: Optional[float] = Field(None, alias="magneticBearing")
    threshold_location: Optional[GMLPoint] = Field(None, alias="thresholdLocation")
    elevation: Optional[float] = Field(None, description="Threshold elevation in meters")
    displaced_threshold_length: Optional[float] = Field(None, alias="displacedThresholdLength")
    tora: Optional[float] = Field(None, description="Take-off run available (m)")
    toda: Optional[float] = Field(None, description="Take-off distance available (m)")
    asda: Optional[float] = Field(None, description="Accelerate-stop distance available (m)")
    lda: Optional[float] = Field(None, description="Landing distance available (m)")

    model_config = ConfigDict(populate_by_name=True)


class AIXMRunway(BaseModel):
    """
    AIXM Runway Element.

    Represents a physical runway with its geometry and properties.
    """
    gml_id: str = Field(..., alias="gmlId")
    identifier: str = Field(..., description="Unique identifier")
    designator: str = Field(..., description="Runway pair designator (e.g., '10L/28R')")
    type: str = Field(default="RWY", description="Feature type")
    length: float = Field(..., description="Runway length in meters")
    width: float = Field(..., description="Runway width in meters")
    surface_type: Optional[RunwaySurfaceType] = Field(None, alias="surfaceType")
    surface_condition: Optional[SurfaceCondition] = Field(None, alias="surfaceCondition")
    centre_line: Optional[GMLLineString] = Field(None, alias="centreLine")
    directions: list[AIXMRunwayDirection] = Field(default_factory=list)
    time_slice: Optional[AIXMTimeslice] = Field(None, alias="timeSlice")

    model_config = ConfigDict(populate_by_name=True)


class AIXMTaxiway(BaseModel):
    """
    AIXM Taxiway Element.

    Represents a taxiway with its geometry.
    """
    gml_id: str = Field(..., alias="gmlId")
    identifier: str = Field(..., description="Unique identifier")
    designator: str = Field(..., description="Taxiway designator (e.g., 'A', 'B1')")
    type: str = Field(default="TWY", description="Feature type")
    width: Optional[float] = Field(None, description="Taxiway width in meters")
    surface_type: Optional[RunwaySurfaceType] = Field(None, alias="surfaceType")
    centre_line: Optional[GMLLineString] = Field(None, alias="centreLine")
    extent: Optional[GMLPolygon] = Field(None, description="Taxiway polygon extent")

    model_config = ConfigDict(populate_by_name=True)


class AIXMApron(BaseModel):
    """
    AIXM Apron Element.

    Represents an aircraft parking apron/ramp area.
    """
    gml_id: str = Field(..., alias="gmlId")
    identifier: str = Field(..., description="Unique identifier")
    name: Optional[str] = Field(None, description="Apron name")
    type: str = Field(default="APRON", description="Feature type")
    surface_type: Optional[RunwaySurfaceType] = Field(None, alias="surfaceType")
    extent: Optional[GMLPolygon] = Field(None, description="Apron polygon extent")

    model_config = ConfigDict(populate_by_name=True)


class AIXMNavaid(BaseModel):
    """
    AIXM Navigation Aid.

    Represents VOR, NDB, ILS, and other navigation aids.
    """
    gml_id: str = Field(..., alias="gmlId")
    identifier: str = Field(..., description="Unique identifier")
    designator: str = Field(..., description="Navaid identifier (e.g., 'SFO', 'ISFO')")
    name: Optional[str] = Field(None, description="Navaid name")
    type: NavaidType = Field(..., description="Navaid type")
    location: Optional[GMLPoint] = Field(None, description="Navaid location")
    frequency: Optional[float] = Field(None, description="Frequency in MHz/kHz")
    channel: Optional[str] = Field(None, description="TACAN channel")
    magnetic_variation: Optional[float] = Field(None, alias="magneticVariation")

    model_config = ConfigDict(populate_by_name=True)


class AIXMAirportHeliport(BaseModel):
    """
    AIXM Airport/Heliport.

    Contains metadata and reference point for an airport or heliport.
    """
    gml_id: str = Field(..., alias="gmlId")
    identifier: str = Field(..., description="Unique identifier")
    icao_code: Optional[str] = Field(None, alias="icaoCode", description="ICAO code (e.g., 'KSFO')")
    iata_code: Optional[str] = Field(None, alias="iataCode", description="IATA code (e.g., 'SFO')")
    name: str = Field(..., description="Airport name")
    type: str = Field(default="AD", description="Airport type (AD, HP)")
    arp: Optional[GMLPoint] = Field(None, description="Aerodrome Reference Point")
    elevation: Optional[float] = Field(None, description="Field elevation in meters")
    magnetic_variation: Optional[float] = Field(None, alias="magneticVariation")
    transition_altitude: Optional[float] = Field(None, alias="transitionAltitude")

    model_config = ConfigDict(populate_by_name=True)


class AIXMDocument(BaseModel):
    """
    Parsed AIXM Document.

    Contains all aeronautical features extracted from an AIXM file.
    """
    version: str = Field(default="5.1.1", description="AIXM version")
    airport: Optional[AIXMAirportHeliport] = Field(None, description="Airport metadata")
    runways: list[AIXMRunway] = Field(default_factory=list)
    taxiways: list[AIXMTaxiway] = Field(default_factory=list)
    aprons: list[AIXMApron] = Field(default_factory=list)
    navaids: list[AIXMNavaid] = Field(default_factory=list)
    effective_date: Optional[datetime] = Field(None, alias="effectiveDate")

    model_config = ConfigDict(populate_by_name=True)

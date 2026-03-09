"""
OpenStreetMap Pydantic Models

Models for OSM data structures returned by Overpass API.
Focuses on aeroway elements relevant to airport visualization:
- Nodes: Gates, POIs, navigation points
- Ways: Terminal buildings, taxiways, apron areas
- Relations: Multi-polygon terminals (if needed)
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class OSMElementType(str, Enum):
    """OSM element types."""
    NODE = "node"
    WAY = "way"
    RELATION = "relation"


class AerowayType(str, Enum):
    """Aeroway feature types from OSM."""
    GATE = "gate"
    TERMINAL = "terminal"
    TAXIWAY = "taxiway"
    RUNWAY = "runway"
    APRON = "apron"
    HANGAR = "hangar"
    HELIPAD = "helipad"
    WINDSOCK = "windsock"
    PARKING_POSITION = "parking_position"


class OSMTags(BaseModel):
    """Common OSM tags for airport features."""
    model_config = {"extra": "allow"}  # Allow additional tags

    aeroway: Optional[str] = None
    building: Optional[str] = None
    name: Optional[str] = None
    ref: Optional[str] = Field(None, description="Reference number (e.g., gate number)")
    operator: Optional[str] = None
    icao: Optional[str] = None
    iata: Optional[str] = None
    terminal: Optional[str] = Field(None, description="Terminal name/number")
    level: Optional[str] = None
    height: Optional[float] = None
    ele: Optional[float] = Field(None, description="Elevation in meters")
    width: Optional[float] = None
    surface: Optional[str] = None


class OSMNode(BaseModel):
    """
    OSM Node element.

    Represents point features like gates, POIs, and waypoints.
    """
    id: int = Field(..., description="OSM node ID")
    type: str = Field(default="node")
    lat: float = Field(..., description="Latitude (WGS84)")
    lon: float = Field(..., description="Longitude (WGS84)")
    tags: OSMTags = Field(default_factory=OSMTags)

    @property
    def is_gate(self) -> bool:
        """Check if this node is a gate."""
        return self.tags.aeroway == "gate"

    @property
    def is_helipad(self) -> bool:
        """Check if this node is a helipad."""
        return self.tags.aeroway == "helipad"

    @property
    def is_parking_position(self) -> bool:
        """Check if this node is a parking position."""
        return self.tags.aeroway == "parking_position"

    @property
    def gate_ref(self) -> Optional[str]:
        """Get gate reference/number."""
        return self.tags.ref if self.is_gate else None

    @property
    def terminal_name(self) -> Optional[str]:
        """Get associated terminal name."""
        return self.tags.terminal


class OSMWayNode(BaseModel):
    """Node reference within a way, with optional geometry."""
    lat: float
    lon: float


class OSMWay(BaseModel):
    """
    OSM Way element.

    Represents linear or polygon features like terminal buildings,
    taxiways, and apron areas.
    """
    id: int = Field(..., description="OSM way ID")
    type: str = Field(default="way")
    tags: OSMTags = Field(default_factory=OSMTags)
    nodes: list[int] = Field(default_factory=list, description="Node ID references")
    geometry: list[OSMWayNode] = Field(default_factory=list, description="Resolved geometry")
    bounds: Optional[dict] = Field(None, description="Bounding box")

    @property
    def is_terminal(self) -> bool:
        """Check if this way is a terminal building."""
        return (
            self.tags.aeroway == "terminal" or
            self.tags.building == "terminal"
        )

    @property
    def is_taxiway(self) -> bool:
        """Check if this way is a taxiway."""
        return self.tags.aeroway == "taxiway"

    @property
    def is_apron(self) -> bool:
        """Check if this way is an apron."""
        return self.tags.aeroway == "apron"

    @property
    def is_runway(self) -> bool:
        """Check if this way is a runway."""
        return self.tags.aeroway == "runway"

    @property
    def is_hangar(self) -> bool:
        """Check if this way is a hangar."""
        return self.tags.aeroway == "hangar" or self.tags.building == "hangar"

    @property
    def is_closed(self) -> bool:
        """Check if this way forms a closed polygon."""
        return len(self.nodes) >= 3 and self.nodes[0] == self.nodes[-1]

    @property
    def points(self) -> list[tuple[float, float]]:
        """Get list of (lat, lon) coordinate tuples."""
        return [(n.lat, n.lon) for n in self.geometry]

    @property
    def center(self) -> tuple[float, float]:
        """Calculate centroid of the way."""
        if not self.geometry:
            return (0.0, 0.0)
        lats = [n.lat for n in self.geometry]
        lons = [n.lon for n in self.geometry]
        return (sum(lats) / len(lats), sum(lons) / len(lons))


class OSMDocument(BaseModel):
    """
    Parsed OSM data for an airport.

    Contains all aeroway elements fetched from Overpass API.
    """
    version: str = Field(default="0.6", description="OSM API version")
    generator: str = Field(default="Overpass API")
    icao_code: Optional[str] = Field(None, description="Airport ICAO code")
    iata_code: Optional[str] = Field(None, description="Airport IATA code")
    airport_name: Optional[str] = Field(None, description="Official airport name")
    airport_operator: Optional[str] = Field(None, description="Airport operator")
    timestamp: Optional[datetime] = None
    nodes: list[OSMNode] = Field(default_factory=list)
    ways: list[OSMWay] = Field(default_factory=list)

    @property
    def gates(self) -> list[OSMNode]:
        """Get all gate nodes."""
        return [n for n in self.nodes if n.is_gate]

    @property
    def terminals(self) -> list[OSMWay]:
        """Get all terminal building ways."""
        return [w for w in self.ways if w.is_terminal]

    @property
    def taxiways(self) -> list[OSMWay]:
        """Get all taxiway ways."""
        return [w for w in self.ways if w.is_taxiway]

    @property
    def aprons(self) -> list[OSMWay]:
        """Get all apron ways."""
        return [w for w in self.ways if w.is_apron]

    @property
    def runways(self) -> list[OSMWay]:
        """Get all runway ways."""
        return [w for w in self.ways if w.is_runway]

    @property
    def hangars(self) -> list[OSMWay]:
        """Get all hangar ways."""
        return [w for w in self.ways if w.is_hangar]

    @property
    def helipads(self) -> list[OSMNode]:
        """Get all helipad nodes."""
        return [n for n in self.nodes if n.is_helipad]

    @property
    def parking_positions(self) -> list[OSMNode]:
        """Get all parking position nodes."""
        return [n for n in self.nodes if n.is_parking_position]

    def get_gates_by_terminal(self) -> dict[str, list[OSMNode]]:
        """Group gates by terminal name."""
        result: dict[str, list[OSMNode]] = {}
        for gate in self.gates:
            terminal = gate.terminal_name or "Unknown"
            if terminal not in result:
                result[terminal] = []
            result[terminal].append(gate)
        return result

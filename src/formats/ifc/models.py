"""
IFC Pydantic Models

Models for IFC4 data structures representing building elements.
These models focus on elements relevant for airport terminal visualization:
- Buildings and storeys
- Spaces (rooms, areas)
- Structural elements (walls, floors, roofs)
- Materials and geometry

Reference: https://standards.buildingsmart.org/IFC/RELEASE/IFC4/ADD2_TC1/HTML/
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class IFCElementType(str, Enum):
    """IFC element types relevant for visualization."""
    BUILDING = "IfcBuilding"
    BUILDING_STOREY = "IfcBuildingStorey"
    SPACE = "IfcSpace"
    WALL = "IfcWall"
    WALL_STANDARD = "IfcWallStandardCase"
    SLAB = "IfcSlab"
    ROOF = "IfcRoof"
    COLUMN = "IfcColumn"
    BEAM = "IfcBeam"
    DOOR = "IfcDoor"
    WINDOW = "IfcWindow"
    STAIR = "IfcStair"
    RAMP = "IfcRamp"
    CURTAIN_WALL = "IfcCurtainWall"
    COVERING = "IfcCovering"
    FURNITURE = "IfcFurnishingElement"


class IFCSpaceType(str, Enum):
    """Common space types in airports."""
    TERMINAL = "TERMINAL"
    GATE = "GATE"
    LOUNGE = "LOUNGE"
    SECURITY = "SECURITY"
    BAGGAGE = "BAGGAGE"
    RETAIL = "RETAIL"
    OFFICE = "OFFICE"
    CIRCULATION = "CIRCULATION"
    MECHANICAL = "MECHANICAL"
    OTHER = "OTHER"


class IFCVector3(BaseModel):
    """3D vector/point."""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class IFCBoundingBox(BaseModel):
    """Axis-aligned bounding box."""
    min: IFCVector3
    max: IFCVector3

    @property
    def center(self) -> IFCVector3:
        return IFCVector3(
            x=(self.min.x + self.max.x) / 2,
            y=(self.min.y + self.max.y) / 2,
            z=(self.min.z + self.max.z) / 2,
        )

    @property
    def dimensions(self) -> IFCVector3:
        return IFCVector3(
            x=self.max.x - self.min.x,
            y=self.max.y - self.min.y,
            z=self.max.z - self.min.z,
        )


class IFCGeometry(BaseModel):
    """
    Geometry representation for an IFC element.

    Can be simple (bounding box) or detailed (mesh data).
    """
    bounding_box: Optional[IFCBoundingBox] = Field(None, alias="boundingBox")
    vertices: Optional[list[float]] = Field(None, description="Flat array of vertex positions")
    indices: Optional[list[int]] = Field(None, description="Triangle indices")
    normals: Optional[list[float]] = Field(None, description="Vertex normals")

    @property
    def has_mesh(self) -> bool:
        return self.vertices is not None and self.indices is not None

    class Config:
        populate_by_name = True


class IFCMaterial(BaseModel):
    """Material properties."""
    name: str
    color: Optional[tuple[float, float, float]] = Field(None, description="RGB color (0-1)")
    transparency: float = Field(default=0.0, ge=0.0, le=1.0)
    diffuse: Optional[tuple[float, float, float]] = None
    specular: Optional[tuple[float, float, float]] = None
    shininess: float = Field(default=0.0, ge=0.0, le=1.0)


class IFCElement(BaseModel):
    """
    Generic IFC element.

    Base model for building elements with geometry and materials.
    """
    global_id: str = Field(..., alias="globalId", description="IFC GlobalId (GUID)")
    name: Optional[str] = None
    description: Optional[str] = None
    element_type: IFCElementType = Field(..., alias="elementType")
    geometry: Optional[IFCGeometry] = None
    material: Optional[IFCMaterial] = None
    parent_id: Optional[str] = Field(None, alias="parentId")

    # Placement
    location: IFCVector3 = Field(default_factory=IFCVector3)
    rotation: IFCVector3 = Field(default_factory=IFCVector3, description="Euler angles in radians")

    class Config:
        populate_by_name = True


class IFCSpace(BaseModel):
    """
    IFC Space (room/area).

    Represents enclosed volumes within a building.
    """
    global_id: str = Field(..., alias="globalId")
    name: Optional[str] = None
    long_name: Optional[str] = Field(None, alias="longName")
    space_type: IFCSpaceType = Field(default=IFCSpaceType.OTHER, alias="spaceType")
    geometry: Optional[IFCGeometry] = None
    area: Optional[float] = Field(None, description="Floor area in m²")
    volume: Optional[float] = Field(None, description="Volume in m³")
    storey_id: Optional[str] = Field(None, alias="storeyId")

    class Config:
        populate_by_name = True


class IFCBuildingStorey(BaseModel):
    """
    IFC Building Storey (floor level).

    Contains spaces and elements for one floor of a building.
    """
    global_id: str = Field(..., alias="globalId")
    name: Optional[str] = None
    elevation: float = Field(default=0.0, description="Floor elevation in meters")
    height: Optional[float] = Field(None, description="Storey height in meters")
    spaces: list[IFCSpace] = Field(default_factory=list)
    elements: list[IFCElement] = Field(default_factory=list)
    building_id: Optional[str] = Field(None, alias="buildingId")

    class Config:
        populate_by_name = True


class IFCBuilding(BaseModel):
    """
    IFC Building.

    Contains storeys and metadata for a building structure.
    """
    global_id: str = Field(..., alias="globalId")
    name: Optional[str] = None
    description: Optional[str] = None
    address: Optional[str] = None
    elevation: float = Field(default=0.0, description="Building elevation in meters")
    storeys: list[IFCBuildingStorey] = Field(default_factory=list)

    # Geo-reference (if available)
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # Overall geometry
    bounding_box: Optional[IFCBoundingBox] = Field(None, alias="boundingBox")

    class Config:
        populate_by_name = True


class IFCDocument(BaseModel):
    """
    Parsed IFC Document.

    Contains all buildings and elements extracted from an IFC file.
    """
    schema_version: str = Field(default="IFC4", alias="schemaVersion")
    name: Optional[str] = None
    author: Optional[str] = None
    organization: Optional[str] = None
    application: Optional[str] = None
    buildings: list[IFCBuilding] = Field(default_factory=list)

    # All elements (for flat access)
    all_elements: list[IFCElement] = Field(default_factory=list, alias="allElements")

    class Config:
        populate_by_name = True

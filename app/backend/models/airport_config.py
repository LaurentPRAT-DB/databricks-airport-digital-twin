"""
Airport Configuration Models

Pydantic models for airport configuration import/export API.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ImportFormat(str, Enum):
    """Supported import formats."""
    AIXM = "aixm"
    IFC = "ifc"
    AIDM = "aidm"
    OSM = "osm"
    FAA = "faa"


class Position3D(BaseModel):
    """3D position in scene coordinates."""
    x: float
    y: float
    z: float


class Dimensions3D(BaseModel):
    """3D dimensions."""
    width: float
    height: float
    depth: float


class RunwayConfig(BaseModel):
    """Runway configuration."""
    id: str
    start: Position3D
    end: Position3D
    width: float
    color: int = 0x333333
    length: Optional[float] = None
    surface_type: Optional[str] = Field(None, alias="surfaceType")

    model_config = ConfigDict(populate_by_name=True)


class TaxiwayConfig(BaseModel):
    """Taxiway configuration."""
    id: str
    points: list[Position3D]
    width: float
    color: int = 0x555555


class BuildingPlacement(BaseModel):
    """Building placement configuration."""
    id: str
    type: str
    position: Position3D
    rotation: float
    scale: Optional[float] = None
    color: Optional[int] = None
    dimensions: Optional[Dimensions3D] = None
    source: Optional[str] = None
    source_global_id: Optional[str] = Field(None, alias="sourceGlobalId")

    model_config = ConfigDict(populate_by_name=True)


class AirportConfigResponse(BaseModel):
    """Airport configuration response."""
    source: Optional[str] = None
    version: Optional[str] = None
    airport: Optional[dict[str, Any]] = None
    runways: list[RunwayConfig] = Field(default_factory=list)
    taxiways: list[TaxiwayConfig] = Field(default_factory=list)
    buildings: list[BuildingPlacement] = Field(default_factory=list)
    aprons: list[dict[str, Any]] = Field(default_factory=list)
    navaids: list[dict[str, Any]] = Field(default_factory=list)
    timestamp: Optional[datetime] = None


class ImportRequest(BaseModel):
    """Request for importing airport data."""
    format: ImportFormat
    reference_lat: Optional[float] = Field(None, alias="referenceLat")
    reference_lon: Optional[float] = Field(None, alias="referenceLon")
    merge_with_existing: bool = Field(default=True, alias="mergeWithExisting")

    model_config = ConfigDict(populate_by_name=True)


class ImportResponse(BaseModel):
    """Response from import operation."""
    success: bool
    format: str
    elements_imported: dict[str, int] = Field(alias="elementsImported")
    warnings: list[str] = Field(default_factory=list)
    config: Optional[AirportConfigResponse] = None
    timestamp: datetime

    model_config = ConfigDict(populate_by_name=True)


class AIDMImportResponse(BaseModel):
    """Response from AIDM import."""
    success: bool
    flights_imported: int = Field(alias="flightsImported")
    resources_imported: int = Field(alias="resourcesImported")
    events_imported: int = Field(alias="eventsImported")
    warnings: list[str] = Field(default_factory=list)
    timestamp: datetime

    model_config = ConfigDict(populate_by_name=True)


class OSMImportResponse(BaseModel):
    """Response from OSM import."""
    success: bool
    icao_code: str = Field(alias="icaoCode")
    gates_imported: int = Field(alias="gatesImported")
    terminals_imported: int = Field(alias="terminalsImported")
    taxiways_imported: int = Field(alias="taxiwaysImported")
    aprons_imported: int = Field(alias="apronsImported")
    runways_imported: int = Field(0, alias="runwaysImported")
    hangars_imported: int = Field(0, alias="hangarsImported")
    helipads_imported: int = Field(0, alias="helipadsImported")
    parking_positions_imported: int = Field(0, alias="parkingPositionsImported")
    warnings: list[str] = Field(default_factory=list)
    timestamp: datetime

    model_config = ConfigDict(populate_by_name=True)


class FAAImportResponse(BaseModel):
    """Response from FAA import."""
    success: bool
    facility_id: str = Field(alias="facilityId")
    runways_imported: int = Field(alias="runwaysImported")
    warnings: list[str] = Field(default_factory=list)
    timestamp: datetime

    model_config = ConfigDict(populate_by_name=True)

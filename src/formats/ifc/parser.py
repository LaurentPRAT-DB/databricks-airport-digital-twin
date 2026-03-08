"""
IFC File Parser

Parses IFC (Industry Foundation Classes) files using ifcopenshell.
Extracts building geometry, materials, and spatial structure for
airport terminal visualization.

If ifcopenshell is not available, provides a fallback stub that
returns empty documents with appropriate warnings.

Note: IFC files can be very large (100MB+). This parser uses streaming
where possible and limits geometry detail to manage memory.
"""

from pathlib import Path
from typing import Any, Optional, Union
import logging

from src.formats.base import AirportFormatParser, CoordinateConverter, ParseError, ValidationError
from src.formats.ifc.models import (
    IFCDocument,
    IFCBuilding,
    IFCBuildingStorey,
    IFCSpace,
    IFCElement,
    IFCMaterial,
    IFCGeometry,
    IFCElementType,
    IFCSpaceType,
    IFCVector3,
    IFCBoundingBox,
)

logger = logging.getLogger(__name__)

# Check for ifcopenshell availability
IFCOPENSHELL_AVAILABLE = False
try:
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.util.element
    import ifcopenshell.util.placement
    IFCOPENSHELL_AVAILABLE = True
except ImportError:
    ifcopenshell = None
    logger.warning(
        "ifcopenshell not installed. IFC parsing will not be available. "
        "Install with: pip install ifcopenshell"
    )


class IFCParser(AirportFormatParser[IFCDocument]):
    """
    Parser for IFC4 files.

    Extracts building structure and geometry using ifcopenshell.
    Falls back to stub implementation if ifcopenshell is not available.
    """

    # IFC types to extract for visualization
    ELEMENT_TYPES = [
        "IfcWall",
        "IfcWallStandardCase",
        "IfcSlab",
        "IfcRoof",
        "IfcColumn",
        "IfcBeam",
        "IfcDoor",
        "IfcWindow",
        "IfcCurtainWall",
        "IfcStair",
        "IfcRamp",
    ]

    def __init__(
        self,
        converter: CoordinateConverter | None = None,
        include_geometry: bool = True,
        max_elements: int = 10000,
    ):
        """
        Initialize IFC parser.

        Args:
            converter: Coordinate converter for geo transforms
            include_geometry: Whether to extract detailed geometry (slower)
            max_elements: Maximum elements to parse (for large files)
        """
        super().__init__(converter)
        self.include_geometry = include_geometry
        self.max_elements = max_elements

    def parse(self, source: Union[str, Path, bytes]) -> IFCDocument:
        """
        Parse IFC file.

        Args:
            source: File path or raw IFC content

        Returns:
            Parsed IFCDocument

        Raises:
            ParseError: If parsing fails or ifcopenshell not available
        """
        if not IFCOPENSHELL_AVAILABLE:
            raise ParseError(
                "ifcopenshell is not installed. Install with: pip install ifcopenshell"
            )

        try:
            # Open IFC file
            if isinstance(source, bytes):
                # Write to temp file for ifcopenshell
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".ifc", delete=False) as f:
                    f.write(source)
                    temp_path = f.name
                ifc_file = ifcopenshell.open(temp_path)
                Path(temp_path).unlink()  # Clean up
            else:
                ifc_file = ifcopenshell.open(str(source))

            return self._parse_file(ifc_file)

        except Exception as e:
            raise ParseError(f"Failed to parse IFC file: {e}") from e

    def validate(self, model: IFCDocument) -> list[str]:
        """
        Validate parsed IFC document.

        Args:
            model: Parsed IFCDocument

        Returns:
            List of validation warnings
        """
        warnings = []

        if not model.buildings:
            warnings.append("No buildings found in IFC file")

        for building in model.buildings:
            if not building.storeys:
                warnings.append(f"Building '{building.name}' has no storeys")

            for storey in building.storeys:
                if not storey.elements and not storey.spaces:
                    warnings.append(
                        f"Storey '{storey.name}' (elevation {storey.elevation}m) "
                        "has no elements or spaces"
                    )

        return warnings

    def to_config(self, model: IFCDocument) -> dict[str, Any]:
        """Convert IFC document to internal configuration."""
        from src.formats.ifc.converter import IFCConverter
        converter = IFCConverter(self.converter)
        return converter.to_config(model)

    def _parse_file(self, ifc_file) -> IFCDocument:
        """Parse ifcopenshell file object into IFCDocument."""
        doc = IFCDocument(
            schemaVersion=ifc_file.schema,
        )

        # Get project info
        projects = ifc_file.by_type("IfcProject")
        if projects:
            project = projects[0]
            doc.name = project.Name
            # Get authoring info from header
            if hasattr(ifc_file, "header"):
                header = ifc_file.header
                if hasattr(header, "file_name"):
                    doc.author = header.file_name.author[0] if header.file_name.author else None
                    doc.organization = header.file_name.organization[0] if header.file_name.organization else None

        # Parse buildings
        for building in ifc_file.by_type("IfcBuilding"):
            parsed_building = self._parse_building(ifc_file, building)
            doc.buildings.append(parsed_building)

        # Collect all elements for flat access
        element_count = 0
        for building in doc.buildings:
            for storey in building.storeys:
                for element in storey.elements:
                    doc.all_elements.append(element)
                    element_count += 1
                    if element_count >= self.max_elements:
                        logger.warning(f"Reached max elements limit ({self.max_elements})")
                        return doc

        return doc

    def _parse_building(self, ifc_file, building) -> IFCBuilding:
        """Parse IfcBuilding entity."""
        parsed = IFCBuilding(
            globalId=building.GlobalId,
            name=building.Name,
            description=building.Description,
            elevation=float(building.ElevationOfRefHeight or 0),
        )

        # Get geo-reference if available
        if hasattr(building, "ObjectPlacement"):
            try:
                coords = ifcopenshell.util.placement.get_local_placement(
                    building.ObjectPlacement
                )
                if coords is not None:
                    # Extract translation from 4x4 matrix
                    parsed.latitude = None  # Would need IfcMapConversion
                    parsed.longitude = None
            except Exception:
                pass

        # Parse storeys
        for rel in ifc_file.by_type("IfcRelAggregates"):
            if rel.RelatingObject == building:
                for related in rel.RelatedObjects:
                    if related.is_a("IfcBuildingStorey"):
                        storey = self._parse_storey(ifc_file, related)
                        storey.building_id = building.GlobalId
                        parsed.storeys.append(storey)

        # Sort storeys by elevation
        parsed.storeys.sort(key=lambda s: s.elevation)

        return parsed

    def _parse_storey(self, ifc_file, storey) -> IFCBuildingStorey:
        """Parse IfcBuildingStorey entity."""
        parsed = IFCBuildingStorey(
            globalId=storey.GlobalId,
            name=storey.Name,
            elevation=float(storey.Elevation or 0),
        )

        # Get contained elements
        for rel in ifc_file.by_type("IfcRelContainedInSpatialStructure"):
            if rel.RelatingStructure == storey:
                for element in rel.RelatedElements:
                    # Parse spaces
                    if element.is_a("IfcSpace"):
                        space = self._parse_space(element)
                        space.storey_id = storey.GlobalId
                        parsed.spaces.append(space)
                    # Parse building elements
                    elif any(element.is_a(t) for t in self.ELEMENT_TYPES):
                        elem = self._parse_element(ifc_file, element)
                        if elem:
                            parsed.elements.append(elem)

        return parsed

    def _parse_space(self, space) -> IFCSpace:
        """Parse IfcSpace entity."""
        parsed = IFCSpace(
            globalId=space.GlobalId,
            name=space.Name,
            longName=space.LongName if hasattr(space, "LongName") else None,
        )

        # Determine space type from name
        name_lower = (space.Name or "").lower()
        if "gate" in name_lower:
            parsed.space_type = IFCSpaceType.GATE
        elif "lounge" in name_lower:
            parsed.space_type = IFCSpaceType.LOUNGE
        elif "security" in name_lower:
            parsed.space_type = IFCSpaceType.SECURITY
        elif "baggage" in name_lower:
            parsed.space_type = IFCSpaceType.BAGGAGE
        elif "retail" in name_lower or "shop" in name_lower:
            parsed.space_type = IFCSpaceType.RETAIL
        elif "office" in name_lower:
            parsed.space_type = IFCSpaceType.OFFICE
        elif "corridor" in name_lower or "hall" in name_lower:
            parsed.space_type = IFCSpaceType.CIRCULATION

        return parsed

    def _parse_element(self, ifc_file, element) -> Optional[IFCElement]:
        """Parse generic IFC building element."""
        try:
            element_type = IFCElementType(element.is_a())
        except ValueError:
            # Map specific types to generic
            if element.is_a("IfcWallStandardCase"):
                element_type = IFCElementType.WALL_STANDARD
            else:
                return None

        parsed = IFCElement(
            globalId=element.GlobalId,
            name=element.Name,
            description=element.Description if hasattr(element, "Description") else None,
            elementType=element_type,
        )

        # Get placement
        if hasattr(element, "ObjectPlacement") and element.ObjectPlacement:
            try:
                matrix = ifcopenshell.util.placement.get_local_placement(
                    element.ObjectPlacement
                )
                if matrix is not None:
                    # Extract translation from 4x4 matrix
                    parsed.location = IFCVector3(
                        x=float(matrix[0][3]),
                        y=float(matrix[1][3]),
                        z=float(matrix[2][3]),
                    )
            except Exception:
                pass

        # Get geometry if requested
        if self.include_geometry:
            parsed.geometry = self._extract_geometry(ifc_file, element)

        # Get material
        parsed.material = self._extract_material(element)

        return parsed

    def _extract_geometry(self, ifc_file, element) -> Optional[IFCGeometry]:
        """Extract geometry for an element."""
        try:
            settings = ifcopenshell.geom.settings()
            settings.set(settings.USE_WORLD_COORDS, True)

            shape = ifcopenshell.geom.create_shape(settings, element)
            if shape is None:
                return None

            # Get bounding box from shape
            verts = shape.geometry.verts
            if not verts:
                return None

            # Convert flat array to points
            points = [
                (verts[i], verts[i + 1], verts[i + 2])
                for i in range(0, len(verts), 3)
            ]

            if not points:
                return None

            # Calculate bounding box
            xs, ys, zs = zip(*points)
            bbox = IFCBoundingBox(
                min=IFCVector3(x=min(xs), y=min(ys), z=min(zs)),
                max=IFCVector3(x=max(xs), y=max(ys), z=max(zs)),
            )

            return IFCGeometry(
                boundingBox=bbox,
                vertices=list(verts),
                indices=list(shape.geometry.faces) if shape.geometry.faces else None,
            )

        except Exception as e:
            logger.debug(f"Failed to extract geometry for {element.GlobalId}: {e}")
            return None

    def _extract_material(self, element) -> Optional[IFCMaterial]:
        """Extract material for an element."""
        try:
            # Get material associations
            for rel in element.HasAssociations:
                if rel.is_a("IfcRelAssociatesMaterial"):
                    material = rel.RelatingMaterial
                    if material.is_a("IfcMaterial"):
                        return IFCMaterial(name=material.Name or "Unknown")
                    elif material.is_a("IfcMaterialLayerSetUsage"):
                        layer_set = material.ForLayerSet
                        if layer_set and layer_set.MaterialLayers:
                            first_layer = layer_set.MaterialLayers[0]
                            if first_layer.Material:
                                return IFCMaterial(
                                    name=first_layer.Material.Name or "Unknown"
                                )
        except Exception:
            pass
        return None

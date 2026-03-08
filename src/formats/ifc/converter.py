"""
IFC to Internal Format Converter

Converts parsed IFC documents to the internal airport configuration format
and optionally exports to glTF for Three.js visualization.
"""

from typing import Any, Optional
import math

from src.formats.base import CoordinateConverter, GeoPosition
from src.formats.ifc.models import (
    IFCDocument,
    IFCBuilding,
    IFCBuildingStorey,
    IFCElement,
    IFCElementType,
    IFCGeometry,
)


class IFCConverter:
    """
    Converts IFC models to internal airport configuration format.

    Generates BuildingPlacement configurations from IFC buildings
    for use in the 3D visualization.
    """

    # Material colors by element type (hex)
    ELEMENT_COLORS = {
        IFCElementType.WALL: 0xCCCCCC,
        IFCElementType.WALL_STANDARD: 0xCCCCCC,
        IFCElementType.SLAB: 0x888888,
        IFCElementType.ROOF: 0x666666,
        IFCElementType.COLUMN: 0xAAAAAA,
        IFCElementType.BEAM: 0x999999,
        IFCElementType.DOOR: 0x8B4513,
        IFCElementType.WINDOW: 0x87CEEB,
        IFCElementType.CURTAIN_WALL: 0x4682B4,
        IFCElementType.STAIR: 0x808080,
        IFCElementType.RAMP: 0x808080,
    }

    def __init__(self, coord_converter: CoordinateConverter):
        """Initialize converter with coordinate transformer."""
        self.coord_converter = coord_converter

    def to_config(self, doc: IFCDocument) -> dict[str, Any]:
        """
        Convert IFC document to internal configuration.

        Args:
            doc: Parsed IFC document

        Returns:
            Configuration dictionary with buildings array
        """
        config: dict[str, Any] = {
            "source": "IFC",
            "version": doc.schema_version,
            "buildings": [],
            "elements": [],
        }

        for building in doc.buildings:
            building_config = self._convert_building(building)
            config["buildings"].append(building_config)

            # Also collect all elements for detailed rendering
            for storey in building.storeys:
                for element in storey.elements:
                    element_config = self._convert_element(element, storey.elevation)
                    if element_config:
                        config["elements"].append(element_config)

        return config

    def _convert_building(self, building: IFCBuilding) -> dict[str, Any]:
        """Convert IFC building to BuildingPlacement format."""
        # Calculate building dimensions from storeys
        if building.bounding_box:
            dims = building.bounding_box.dimensions
            center = building.bounding_box.center
        elif building.storeys:
            # Estimate from storey data
            total_height = sum(s.height or 4.0 for s in building.storeys)
            dims = {"width": 100, "height": total_height, "depth": 50}
            center = {"x": 0, "y": total_height / 2, "z": 0}
        else:
            dims = {"width": 100, "height": 20, "depth": 50}
            center = {"x": 0, "y": 10, "z": 0}

        return {
            "id": f"ifc-{building.global_id[:8]}",
            "name": building.name,
            "type": "terminal",
            "position": {
                "x": center.get("x", 0) if isinstance(center, dict) else center.x,
                "y": 0,
                "z": center.get("z", 0) if isinstance(center, dict) else center.z,
            },
            "dimensions": {
                "width": dims.get("width", 100) if isinstance(dims, dict) else dims.x,
                "height": dims.get("height", 20) if isinstance(dims, dict) else dims.y,
                "depth": dims.get("depth", 50) if isinstance(dims, dict) else dims.z,
            },
            "rotation": 0,
            "storeys": [
                {
                    "name": s.name,
                    "elevation": s.elevation,
                    "height": s.height,
                    "spaceCount": len(s.spaces),
                    "elementCount": len(s.elements),
                }
                for s in building.storeys
            ],
            "sourceGlobalId": building.global_id,
        }

    def _convert_element(
        self,
        element: IFCElement,
        storey_elevation: float,
    ) -> Optional[dict[str, Any]]:
        """Convert IFC element to simplified representation."""
        if not element.geometry or not element.geometry.bounding_box:
            return None

        bbox = element.geometry.bounding_box
        center = bbox.center
        dims = bbox.dimensions

        return {
            "id": element.global_id,
            "name": element.name,
            "type": element.element_type.value,
            "position": {
                "x": center.x,
                "y": center.y + storey_elevation,
                "z": center.z,
            },
            "dimensions": {
                "width": dims.x,
                "height": dims.y,
                "depth": dims.z,
            },
            "rotation": {
                "x": element.rotation.x,
                "y": element.rotation.y,
                "z": element.rotation.z,
            },
            "color": self.ELEMENT_COLORS.get(element.element_type, 0xCCCCCC),
            "material": element.material.name if element.material else None,
        }

    def to_gltf(self, doc: IFCDocument, output_path: str) -> str:
        """
        Export IFC document to glTF format.

        Args:
            doc: Parsed IFC document
            output_path: Path for output .glb file

        Returns:
            Path to generated glTF file

        Note: Requires trimesh library for glTF export.
        """
        try:
            import trimesh
            from trimesh.exchange.gltf import export_glb
        except ImportError:
            raise ImportError(
                "trimesh is required for glTF export. "
                "Install with: pip install trimesh"
            )

        # Create scene
        scene = trimesh.Scene()

        for building in doc.buildings:
            for storey in building.storeys:
                for element in storey.elements:
                    if not element.geometry or not element.geometry.has_mesh:
                        continue

                    # Create mesh from IFC geometry
                    vertices = element.geometry.vertices
                    faces = element.geometry.indices

                    if vertices and faces:
                        # Reshape vertices
                        verts = [
                            [vertices[i], vertices[i + 1], vertices[i + 2]]
                            for i in range(0, len(vertices), 3)
                        ]
                        # Reshape faces (triangles)
                        tris = [
                            [faces[i], faces[i + 1], faces[i + 2]]
                            for i in range(0, len(faces), 3)
                        ]

                        mesh = trimesh.Trimesh(vertices=verts, faces=tris)

                        # Apply color
                        color = self.ELEMENT_COLORS.get(
                            element.element_type, 0xCCCCCC
                        )
                        r = ((color >> 16) & 0xFF) / 255
                        g = ((color >> 8) & 0xFF) / 255
                        b = (color & 0xFF) / 255
                        mesh.visual.face_colors = [r, g, b, 1.0]

                        scene.add_geometry(
                            mesh,
                            node_name=element.global_id,
                        )

        # Export to glTF
        glb_data = export_glb(scene)
        with open(output_path, "wb") as f:
            f.write(glb_data)

        return output_path


def merge_ifc_config(
    base_config: dict[str, Any],
    ifc_config: dict[str, Any],
) -> dict[str, Any]:
    """
    Merge IFC-derived config into existing airport configuration.

    IFC buildings are added to the existing buildings list.

    Args:
        base_config: Existing Airport3DConfig
        ifc_config: Configuration from IFC parser

    Returns:
        Merged configuration
    """
    result = base_config.copy()

    # Add IFC buildings to existing buildings
    existing_buildings = result.get("buildings", [])
    ifc_buildings = ifc_config.get("buildings", [])

    # Convert IFC buildings to BuildingPlacement format
    for ifc_building in ifc_buildings:
        placement = {
            "id": ifc_building["id"],
            "type": ifc_building.get("type", "terminal"),
            "position": ifc_building["position"],
            "rotation": ifc_building.get("rotation", 0),
            "dimensions": ifc_building.get("dimensions"),
            "source": "IFC",
            "sourceGlobalId": ifc_building.get("sourceGlobalId"),
        }
        existing_buildings.append(placement)

    result["buildings"] = existing_buildings

    return result

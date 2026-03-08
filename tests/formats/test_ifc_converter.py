"""Tests for IFC converter (model-based tests that don't require ifcopenshell)."""

import pytest

from src.formats.base import CoordinateConverter
from src.formats.ifc.converter import IFCConverter, merge_ifc_config
from src.formats.ifc.models import (
    IFCDocument,
    IFCBuilding,
    IFCBuildingStorey,
    IFCSpace,
    IFCElement,
    IFCElementType,
    IFCSpaceType,
    IFCVector3,
    IFCBoundingBox,
    IFCGeometry,
)


class TestIFCConverter:
    """Tests for IFC to internal format converter."""

    @pytest.fixture
    def converter(self):
        """Create converter with SFO reference point."""
        coord_converter = CoordinateConverter(
            reference_lat=37.6213,
            reference_lon=-122.379,
            reference_alt=4.0,
        )
        return IFCConverter(coord_converter)

    @pytest.fixture
    def sample_building(self):
        """Create sample building with storeys."""
        return IFCBuilding(
            globalId="BLDG-001",
            name="Terminal 1",
            description="Main passenger terminal",
            elevation=4.0,
            storeys=[
                IFCBuildingStorey(
                    globalId="STOREY-G",
                    name="Ground Floor",
                    elevation=0.0,
                    height=5.0,
                    spaces=[
                        IFCSpace(
                            globalId="SPACE-1",
                            name="Arrivals Hall",
                            spaceType=IFCSpaceType.CIRCULATION,
                            area=2000.0,
                        ),
                    ],
                    elements=[
                        IFCElement(
                            globalId="WALL-1",
                            name="External Wall",
                            elementType=IFCElementType.WALL,
                            geometry=IFCGeometry(
                                boundingBox=IFCBoundingBox(
                                    min=IFCVector3(x=0, y=0, z=0),
                                    max=IFCVector3(x=100, y=5, z=0.3),
                                )
                            ),
                        ),
                    ],
                ),
                IFCBuildingStorey(
                    globalId="STOREY-1",
                    name="First Floor",
                    elevation=5.0,
                    height=4.0,
                ),
            ],
            boundingBox=IFCBoundingBox(
                min=IFCVector3(x=0, y=0, z=0),
                max=IFCVector3(x=200, y=20, z=80),
            ),
        )

    def test_convert_building(self, converter, sample_building):
        """Test building conversion to internal format."""
        doc = IFCDocument(buildings=[sample_building])
        config = converter.to_config(doc)

        assert "buildings" in config
        assert len(config["buildings"]) == 1

        building = config["buildings"][0]
        assert building["name"] == "Terminal 1"
        assert "position" in building
        assert "dimensions" in building
        assert len(building["storeys"]) == 2

    def test_convert_building_storeys(self, converter, sample_building):
        """Test storey information is preserved."""
        doc = IFCDocument(buildings=[sample_building])
        config = converter.to_config(doc)

        building = config["buildings"][0]
        storeys = building["storeys"]

        assert storeys[0]["name"] == "Ground Floor"
        assert storeys[0]["elevation"] == 0.0
        assert storeys[0]["spaceCount"] == 1
        assert storeys[0]["elementCount"] == 1

    def test_convert_elements(self, converter, sample_building):
        """Test element conversion."""
        doc = IFCDocument(buildings=[sample_building])
        config = converter.to_config(doc)

        assert "elements" in config
        # Should have elements from storeys
        elements = config["elements"]
        wall_elements = [e for e in elements if e["type"] == "IfcWall"]
        assert len(wall_elements) >= 1

    def test_element_colors(self, converter):
        """Test that element colors are assigned."""
        # Check color mapping exists for key types
        assert IFCElementType.WALL in IFCConverter.ELEMENT_COLORS
        assert IFCElementType.WINDOW in IFCConverter.ELEMENT_COLORS
        assert IFCElementType.DOOR in IFCConverter.ELEMENT_COLORS
        assert IFCElementType.SLAB in IFCConverter.ELEMENT_COLORS

    def test_convert_empty_document(self, converter):
        """Test conversion of empty document."""
        doc = IFCDocument()
        config = converter.to_config(doc)

        assert config["source"] == "IFC"
        assert config["buildings"] == []
        assert config["elements"] == []

    def test_convert_building_without_bounding_box(self, converter):
        """Test building conversion when no bounding box available."""
        building = IFCBuilding(
            globalId="BLDG-001",
            name="Simple Building",
            storeys=[
                IFCBuildingStorey(
                    globalId="S1",
                    name="Floor 1",
                    elevation=0.0,
                    height=4.0,
                ),
            ],
        )

        doc = IFCDocument(buildings=[building])
        config = converter.to_config(doc)

        # Should still produce valid output with estimated dimensions
        assert len(config["buildings"]) == 1
        assert "dimensions" in config["buildings"][0]

    def test_convert_building_without_storeys(self, converter):
        """Test building conversion with no storeys."""
        building = IFCBuilding(
            globalId="BLDG-001",
            name="Empty Building",
        )

        doc = IFCDocument(buildings=[building])
        config = converter.to_config(doc)

        assert len(config["buildings"]) == 1
        # Should have default dimensions
        assert config["buildings"][0]["storeys"] == []


class TestMergeIFCConfig:
    """Tests for merge_ifc_config function."""

    def test_merge_adds_buildings(self):
        """Test that IFC buildings are added to existing config."""
        base = {
            "runways": [{"id": "28L"}],
            "buildings": [{"id": "existing", "type": "hangar"}],
        }
        ifc = {
            "buildings": [
                {
                    "id": "ifc-terminal",
                    "type": "terminal",
                    "position": {"x": 0, "y": 0, "z": 0},
                    "rotation": 0,
                }
            ],
        }

        result = merge_ifc_config(base, ifc)

        assert len(result["buildings"]) == 2
        # Original building preserved
        assert any(b["id"] == "existing" for b in result["buildings"])
        # IFC building added
        assert any(b["id"] == "ifc-terminal" for b in result["buildings"])

    def test_merge_preserves_non_ifc_fields(self):
        """Test that non-IFC fields are preserved."""
        base = {
            "runways": [{"id": "28L"}],
            "taxiways": [{"id": "A"}],
            "lighting": {"ambient": 0.6},
        }
        ifc = {
            "buildings": [{"id": "terminal", "position": {"x": 0, "y": 0, "z": 0}}],
        }

        result = merge_ifc_config(base, ifc)

        assert result["runways"] == [{"id": "28L"}]
        assert result["taxiways"] == [{"id": "A"}]
        assert result["lighting"] == {"ambient": 0.6}

    def test_merge_empty_ifc(self):
        """Test merge with empty IFC buildings."""
        base = {
            "buildings": [{"id": "existing"}],
        }
        ifc = {
            "buildings": [],
        }

        result = merge_ifc_config(base, ifc)

        # Existing buildings should be preserved
        assert result["buildings"] == [{"id": "existing"}]

    def test_merge_marks_source(self):
        """Test that merged IFC buildings are marked with source."""
        base = {"buildings": []}
        ifc = {
            "buildings": [
                {
                    "id": "terminal",
                    "type": "terminal",
                    "position": {"x": 0, "y": 0, "z": 0},
                    "rotation": 0,
                    "sourceGlobalId": "ABC123",
                }
            ],
        }

        result = merge_ifc_config(base, ifc)

        added_building = result["buildings"][0]
        assert added_building["source"] == "IFC"
        assert added_building["sourceGlobalId"] == "ABC123"

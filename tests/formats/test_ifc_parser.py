"""Tests for IFC parser."""

import pytest

from src.formats.ifc.parser import IFCParser, IFCOPENSHELL_AVAILABLE
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
    IFCMaterial,
)
from src.formats.base import ParseError


class TestIFCModels:
    """Tests for IFC Pydantic models (always run regardless of ifcopenshell)."""

    def test_vector3(self):
        """Test IFCVector3 model."""
        v = IFCVector3(x=1.0, y=2.0, z=3.0)
        assert v.x == 1.0
        assert v.y == 2.0
        assert v.z == 3.0

    def test_vector3_defaults(self):
        """Test IFCVector3 default values."""
        v = IFCVector3()
        assert v.x == 0.0
        assert v.y == 0.0
        assert v.z == 0.0

    def test_bounding_box(self):
        """Test IFCBoundingBox model."""
        bbox = IFCBoundingBox(
            min=IFCVector3(x=0, y=0, z=0),
            max=IFCVector3(x=10, y=20, z=30),
        )

        assert bbox.center.x == 5
        assert bbox.center.y == 10
        assert bbox.center.z == 15

        assert bbox.dimensions.x == 10
        assert bbox.dimensions.y == 20
        assert bbox.dimensions.z == 30

    def test_geometry_without_mesh(self):
        """Test IFCGeometry without mesh data."""
        geom = IFCGeometry(
            boundingBox=IFCBoundingBox(
                min=IFCVector3(x=0, y=0, z=0),
                max=IFCVector3(x=10, y=10, z=10),
            )
        )
        assert geom.has_mesh is False

    def test_geometry_with_mesh(self):
        """Test IFCGeometry with mesh data."""
        geom = IFCGeometry(
            vertices=[0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
            indices=[0, 1, 2],
        )
        assert geom.has_mesh is True

    def test_material(self):
        """Test IFCMaterial model."""
        material = IFCMaterial(
            name="Concrete",
            color=(0.5, 0.5, 0.5),
            transparency=0.0,
        )
        assert material.name == "Concrete"
        assert material.color == (0.5, 0.5, 0.5)

    def test_element(self):
        """Test IFCElement model."""
        element = IFCElement(
            globalId="ABC123",
            name="Wall 1",
            elementType=IFCElementType.WALL,
        )

        assert element.global_id == "ABC123"
        assert element.name == "Wall 1"
        assert element.element_type == IFCElementType.WALL

    def test_element_with_geometry(self):
        """Test IFCElement with geometry."""
        element = IFCElement(
            globalId="ABC123",
            elementType=IFCElementType.SLAB,
            geometry=IFCGeometry(
                boundingBox=IFCBoundingBox(
                    min=IFCVector3(x=0, y=0, z=0),
                    max=IFCVector3(x=100, y=0.3, z=50),
                )
            ),
        )
        assert element.geometry is not None
        assert element.geometry.bounding_box.dimensions.x == 100

    def test_space(self):
        """Test IFCSpace model."""
        space = IFCSpace(
            globalId="SPACE-1",
            name="Gate A1",
            longName="Gate A1 Waiting Area",
            spaceType=IFCSpaceType.GATE,
            area=500.0,
            volume=1500.0,
        )
        assert space.global_id == "SPACE-1"
        assert space.space_type == IFCSpaceType.GATE

    def test_building_storey(self):
        """Test IFCBuildingStorey model."""
        storey = IFCBuildingStorey(
            globalId="STOREY-1",
            name="Ground Floor",
            elevation=0.0,
            height=4.0,
        )

        assert storey.global_id == "STOREY-1"
        assert storey.elevation == 0.0
        assert storey.height == 4.0
        assert storey.spaces == []
        assert storey.elements == []

    def test_building_storey_with_contents(self):
        """Test IFCBuildingStorey with spaces and elements."""
        storey = IFCBuildingStorey(
            globalId="STOREY-1",
            name="Ground Floor",
            elevation=0.0,
            spaces=[
                IFCSpace(globalId="SP-1", spaceType=IFCSpaceType.LOUNGE),
            ],
            elements=[
                IFCElement(globalId="EL-1", elementType=IFCElementType.WALL),
            ],
        )
        assert len(storey.spaces) == 1
        assert len(storey.elements) == 1

    def test_building(self):
        """Test IFCBuilding model."""
        building = IFCBuilding(
            globalId="BLDG-1",
            name="Terminal 1",
            storeys=[
                IFCBuildingStorey(
                    globalId="S1",
                    name="Ground",
                    elevation=0.0,
                ),
                IFCBuildingStorey(
                    globalId="S2",
                    name="First",
                    elevation=4.0,
                ),
            ],
        )

        assert building.global_id == "BLDG-1"
        assert len(building.storeys) == 2

    def test_building_with_geo_reference(self):
        """Test IFCBuilding with geo-reference."""
        building = IFCBuilding(
            globalId="BLDG-1",
            name="Terminal 1",
            latitude=37.6213,
            longitude=-122.379,
            elevation=4.0,
        )
        assert building.latitude == 37.6213
        assert building.longitude == -122.379

    def test_document(self):
        """Test IFCDocument model."""
        doc = IFCDocument(
            schemaVersion="IFC4",
            name="Airport Terminal",
        )

        assert doc.schema_version == "IFC4"
        assert doc.buildings == []
        assert doc.all_elements == []

    def test_document_with_metadata(self):
        """Test IFCDocument with authoring metadata."""
        doc = IFCDocument(
            schemaVersion="IFC4",
            name="Airport Project",
            author="John Doe",
            organization="Airport Authority",
            application="Revit 2024",
        )
        assert doc.author == "John Doe"
        assert doc.organization == "Airport Authority"

    def test_element_types(self):
        """Test all IFCElementType values."""
        for element_type in IFCElementType:
            element = IFCElement(
                globalId=f"EL-{element_type.value}",
                elementType=element_type,
            )
            assert element.element_type == element_type

    def test_space_types(self):
        """Test all IFCSpaceType values."""
        for space_type in IFCSpaceType:
            space = IFCSpace(
                globalId=f"SP-{space_type.value}",
                spaceType=space_type,
            )
            assert space.space_type == space_type


@pytest.mark.skipif(not IFCOPENSHELL_AVAILABLE, reason="ifcopenshell not installed")
class TestIFCParser:
    """Tests for IFC file parser (requires ifcopenshell)."""

    @pytest.fixture
    def parser(self):
        return IFCParser(include_geometry=False)

    def test_parser_creation(self, parser):
        """Test parser can be created."""
        assert parser is not None
        assert parser.include_geometry is False

    def test_parse_requires_file(self, parser):
        """Test that parse raises error without valid file."""
        with pytest.raises(ParseError):
            parser.parse(b"not an IFC file")


@pytest.mark.skipif(not IFCOPENSHELL_AVAILABLE, reason="ifcopenshell not installed")
class TestIFCConverter:
    """Tests for IFC to internal format converter."""

    def test_converter_import(self):
        """Test that converter can be imported."""
        from src.formats.ifc.converter import IFCConverter
        assert IFCConverter is not None

    def test_element_colors(self):
        """Test that element colors are defined."""
        from src.formats.ifc.converter import IFCConverter
        assert IFCElementType.WALL in IFCConverter.ELEMENT_COLORS
        assert IFCElementType.WINDOW in IFCConverter.ELEMENT_COLORS


class TestIFCAvailability:
    """Tests for graceful handling when ifcopenshell not available."""

    def test_availability_flag(self):
        """Test that IFCOPENSHELL_AVAILABLE is defined."""
        from src.formats.ifc import IFCOPENSHELL_AVAILABLE
        assert isinstance(IFCOPENSHELL_AVAILABLE, bool)

    def test_parser_raises_without_ifcopenshell(self):
        """Test that parser raises error if ifcopenshell not available."""
        if IFCOPENSHELL_AVAILABLE:
            pytest.skip("ifcopenshell is installed")

        parser = IFCParser()
        with pytest.raises(ParseError) as exc_info:
            parser.parse(b"test")

        assert "ifcopenshell" in str(exc_info.value).lower()

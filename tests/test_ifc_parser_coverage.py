"""Tests to improve coverage of src/formats/ifc/parser.py (currently 17%).

Focuses on paths that do NOT require ifcopenshell to be installed:
- parse() raising ParseError when ifcopenshell unavailable
- validate() with various IFCDocument configurations
- to_config() with mock converter
- _parse_space() space type detection from names
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from src.formats.base import ParseError
from src.formats.ifc.models import (
    IFCDocument,
    IFCBuilding,
    IFCBuildingStorey,
    IFCSpace,
    IFCElement,
    IFCElementType,
    IFCSpaceType,
)
from src.formats.ifc.parser import IFCParser


# ---------------------------------------------------------------------------
# parse() — ifcopenshell unavailable
# ---------------------------------------------------------------------------

class TestParseWithoutIfcopenshell:
    """Test that parse() raises ParseError when ifcopenshell is missing."""

    def test_parse_raises_when_no_ifcopenshell(self):
        parser = IFCParser()
        with patch("src.formats.ifc.parser.IFCOPENSHELL_AVAILABLE", False):
            with pytest.raises(ParseError, match="ifcopenshell is not installed"):
                parser.parse("fake_file.ifc")

    def test_parse_raises_for_bytes_input(self):
        parser = IFCParser()
        with patch("src.formats.ifc.parser.IFCOPENSHELL_AVAILABLE", False):
            with pytest.raises(ParseError, match="ifcopenshell is not installed"):
                parser.parse(b"ISO-10303-21;")

    def test_parse_raises_for_path_input(self):
        from pathlib import Path

        parser = IFCParser()
        with patch("src.formats.ifc.parser.IFCOPENSHELL_AVAILABLE", False):
            with pytest.raises(ParseError, match="ifcopenshell is not installed"):
                parser.parse(Path("/tmp/nonexistent.ifc"))


# ---------------------------------------------------------------------------
# validate()
# ---------------------------------------------------------------------------

class TestValidate:
    """Test validate() with various IFCDocument configurations."""

    def test_empty_document_warns_no_buildings(self):
        parser = IFCParser()
        doc = IFCDocument()

        warnings = parser.validate(doc)
        assert any("No buildings found" in w for w in warnings)

    def test_building_without_storeys(self):
        parser = IFCParser()
        doc = IFCDocument(
            buildings=[
                IFCBuilding(globalId="bld-1", name="Terminal 1"),
            ]
        )

        warnings = parser.validate(doc)
        assert any("has no storeys" in w for w in warnings)
        assert "Terminal 1" in warnings[0]

    def test_storey_without_elements_or_spaces(self):
        parser = IFCParser()
        doc = IFCDocument(
            buildings=[
                IFCBuilding(
                    globalId="bld-1",
                    name="Terminal 1",
                    storeys=[
                        IFCBuildingStorey(
                            globalId="storey-1",
                            name="Ground Floor",
                            elevation=0.0,
                        ),
                    ],
                ),
            ]
        )

        warnings = parser.validate(doc)
        assert any("has no elements or spaces" in w for w in warnings)
        assert any("Ground Floor" in w for w in warnings)

    def test_storey_with_elements_no_warning(self):
        parser = IFCParser()
        doc = IFCDocument(
            buildings=[
                IFCBuilding(
                    globalId="bld-1",
                    name="Terminal 1",
                    storeys=[
                        IFCBuildingStorey(
                            globalId="storey-1",
                            name="Level 1",
                            elevation=0.0,
                            elements=[
                                IFCElement(
                                    globalId="wall-1",
                                    elementType=IFCElementType.WALL,
                                ),
                            ],
                        ),
                    ],
                ),
            ]
        )

        warnings = parser.validate(doc)
        # No warnings about missing elements
        assert not any("has no elements or spaces" in w for w in warnings)
        assert not any("has no storeys" in w for w in warnings)

    def test_storey_with_spaces_no_warning(self):
        parser = IFCParser()
        doc = IFCDocument(
            buildings=[
                IFCBuilding(
                    globalId="bld-1",
                    name="Terminal 1",
                    storeys=[
                        IFCBuildingStorey(
                            globalId="storey-1",
                            name="Level 1",
                            elevation=0.0,
                            spaces=[
                                IFCSpace(globalId="sp-1", name="Gate A1"),
                            ],
                        ),
                    ],
                ),
            ]
        )

        warnings = parser.validate(doc)
        assert not any("has no elements or spaces" in w for w in warnings)

    def test_multiple_buildings_mixed_issues(self):
        parser = IFCParser()
        doc = IFCDocument(
            buildings=[
                IFCBuilding(globalId="bld-1", name="Terminal A"),
                IFCBuilding(
                    globalId="bld-2",
                    name="Terminal B",
                    storeys=[
                        IFCBuildingStorey(
                            globalId="s-1",
                            name="Empty Floor",
                            elevation=0.0,
                        ),
                        IFCBuildingStorey(
                            globalId="s-2",
                            name="Occupied Floor",
                            elevation=4.0,
                            elements=[
                                IFCElement(
                                    globalId="w-1",
                                    elementType=IFCElementType.WALL,
                                ),
                            ],
                        ),
                    ],
                ),
            ]
        )

        warnings = parser.validate(doc)
        # Terminal A has no storeys
        assert any("Terminal A" in w and "no storeys" in w for w in warnings)
        # Empty Floor has no elements or spaces
        assert any("Empty Floor" in w for w in warnings)
        # Should NOT warn about Occupied Floor
        assert not any("Occupied Floor" in w for w in warnings)

    def test_valid_document_no_warnings(self):
        parser = IFCParser()
        doc = IFCDocument(
            buildings=[
                IFCBuilding(
                    globalId="bld-1",
                    name="Terminal 1",
                    storeys=[
                        IFCBuildingStorey(
                            globalId="s-1",
                            name="Ground",
                            elevation=0.0,
                            spaces=[
                                IFCSpace(globalId="sp-1", name="Gate B3"),
                            ],
                            elements=[
                                IFCElement(
                                    globalId="w-1",
                                    elementType=IFCElementType.DOOR,
                                ),
                            ],
                        ),
                    ],
                ),
            ]
        )

        warnings = parser.validate(doc)
        assert warnings == []


# ---------------------------------------------------------------------------
# to_config() — mock the converter
# ---------------------------------------------------------------------------

class TestToConfig:
    """Test to_config() delegates to IFCConverter."""

    def test_to_config_calls_converter(self):
        parser = IFCParser()
        doc = IFCDocument()

        mock_converter_instance = MagicMock()
        mock_converter_instance.to_config.return_value = {"gates": [], "terminals": []}

        with patch("src.formats.ifc.converter.IFCConverter", return_value=mock_converter_instance) as mock_cls:
            result = parser.to_config(doc)

        mock_cls.assert_called_once_with(parser.converter)
        mock_converter_instance.to_config.assert_called_once_with(doc)
        assert result == {"gates": [], "terminals": []}

    def test_to_config_passes_converter(self):
        """Ensure the parser's converter is forwarded."""
        mock_coord_conv = MagicMock()
        parser = IFCParser(converter=mock_coord_conv)
        doc = IFCDocument()

        mock_ifc_converter = MagicMock()
        mock_ifc_converter.to_config.return_value = {}

        with patch("src.formats.ifc.converter.IFCConverter", return_value=mock_ifc_converter) as mock_cls:
            parser.to_config(doc)

        mock_cls.assert_called_once_with(mock_coord_conv)


# ---------------------------------------------------------------------------
# _parse_space() — space type detection
# ---------------------------------------------------------------------------

class TestParseSpaceTypeDetection:
    """Test _parse_space() maps names to IFCSpaceType correctly."""

    @pytest.fixture
    def parser(self):
        return IFCParser()

    @staticmethod
    def _mock_space(name: str, long_name: str | None = None) -> MagicMock:
        """Create a mock IfcSpace entity."""
        space = MagicMock()
        space.GlobalId = "test-id"
        space.Name = name
        space.LongName = long_name
        return space

    def test_gate_space(self, parser):
        result = parser._parse_space(self._mock_space("Gate A1"))
        assert result.space_type == IFCSpaceType.GATE

    def test_lounge_space(self, parser):
        result = parser._parse_space(self._mock_space("Business Lounge"))
        assert result.space_type == IFCSpaceType.LOUNGE

    def test_security_space(self, parser):
        result = parser._parse_space(self._mock_space("Security Checkpoint"))
        assert result.space_type == IFCSpaceType.SECURITY

    def test_baggage_space(self, parser):
        result = parser._parse_space(self._mock_space("Baggage Claim"))
        assert result.space_type == IFCSpaceType.BAGGAGE

    def test_retail_space(self, parser):
        result = parser._parse_space(self._mock_space("Retail Area"))
        assert result.space_type == IFCSpaceType.RETAIL

    def test_shop_space(self, parser):
        result = parser._parse_space(self._mock_space("Duty Free Shop"))
        assert result.space_type == IFCSpaceType.RETAIL

    def test_office_space(self, parser):
        result = parser._parse_space(self._mock_space("Airline Office"))
        assert result.space_type == IFCSpaceType.OFFICE

    def test_corridor_space(self, parser):
        result = parser._parse_space(self._mock_space("Main Corridor"))
        assert result.space_type == IFCSpaceType.CIRCULATION

    def test_hall_space(self, parser):
        result = parser._parse_space(self._mock_space("Departure Hall"))
        assert result.space_type == IFCSpaceType.CIRCULATION

    def test_unknown_space_defaults_to_other(self, parser):
        result = parser._parse_space(self._mock_space("Meeting Room"))
        assert result.space_type == IFCSpaceType.OTHER

    def test_none_name_defaults_to_other(self, parser):
        result = parser._parse_space(self._mock_space(None))
        assert result.space_type == IFCSpaceType.OTHER

    def test_case_insensitive(self, parser):
        result = parser._parse_space(self._mock_space("SECURITY ZONE"))
        assert result.space_type == IFCSpaceType.SECURITY

    def test_long_name_preserved(self, parser):
        result = parser._parse_space(
            self._mock_space("Gate B5", long_name="International Gate B5")
        )
        assert result.space_type == IFCSpaceType.GATE
        assert result.long_name == "International Gate B5"

    def test_global_id_preserved(self, parser):
        mock = self._mock_space("Some Room")
        mock.GlobalId = "custom-guid-123"
        result = parser._parse_space(mock)
        assert result.global_id == "custom-guid-123"


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

class TestIFCParserInit:
    """Test parser initialization options."""

    def test_default_init(self):
        parser = IFCParser()
        assert parser.include_geometry is True
        assert parser.max_elements == 10000
        # Base class creates a default CoordinateConverter when None is passed
        assert parser.converter is not None

    def test_custom_init(self):
        parser = IFCParser(include_geometry=False, max_elements=500)
        assert parser.include_geometry is False
        assert parser.max_elements == 500

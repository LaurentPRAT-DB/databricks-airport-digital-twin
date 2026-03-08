"""Tests for AIXM converter."""

import pytest

from src.formats.base import CoordinateConverter, GeoPosition
from src.formats.aixm.converter import AIXMConverter, merge_aixm_config
from src.formats.aixm.models import (
    AIXMDocument,
    AIXMRunway,
    AIXMRunwayDirection,
    AIXMTaxiway,
    AIXMApron,
    AIXMNavaid,
    AIXMAirportHeliport,
    GMLPoint,
    GMLLineString,
    GMLPolygon,
    RunwaySurfaceType,
    NavaidType,
)


class TestAIXMConverter:
    """Tests for AIXM to internal format converter."""

    @pytest.fixture
    def converter(self):
        """Create converter with SFO reference point."""
        coord_converter = CoordinateConverter(
            reference_lat=37.6213,
            reference_lon=-122.379,
            reference_alt=4.0,
        )
        return AIXMConverter(coord_converter)

    @pytest.fixture
    def sample_runway(self):
        """Create sample runway with geometry."""
        return AIXMRunway(
            gmlId="RWY-01",
            identifier="RWY-28L",
            designator="28L/10R",
            length=3048,
            width=45,
            surfaceType=RunwaySurfaceType.ASPHALT,
            centreLine=GMLLineString(
                posList="37.6190 -122.400 4.0 37.6236 -122.358 4.0"
            ),
            directions=[
                AIXMRunwayDirection(
                    gmlId="RWY-28L-DIR",
                    designator="28L",
                    trueBearing=280.0,
                ),
                AIXMRunwayDirection(
                    gmlId="RWY-10R-DIR",
                    designator="10R",
                    trueBearing=100.0,
                ),
            ],
        )

    @pytest.fixture
    def sample_taxiway(self):
        """Create sample taxiway with geometry."""
        return AIXMTaxiway(
            gmlId="TWY-A",
            identifier="TWY-A",
            designator="A",
            width=20,
            centreLine=GMLLineString(
                posList="37.6200 -122.380 4.0 37.6210 -122.380 4.0 37.6220 -122.385 4.0"
            ),
        )

    @pytest.fixture
    def sample_apron(self):
        """Create sample apron with polygon geometry."""
        return AIXMApron(
            gmlId="APRON-1",
            identifier="APRON-1",
            name="Main Apron",
            extent=GMLPolygon(
                exterior=GMLLineString(
                    posList="37.620 -122.380 4.0 37.621 -122.380 4.0 37.621 -122.379 4.0 37.620 -122.379 4.0"
                )
            ),
        )

    @pytest.fixture
    def sample_navaid(self):
        """Create sample navaid."""
        return AIXMNavaid(
            gmlId="NAV-SFO",
            identifier="SFO-VOR",
            designator="SFO",
            name="San Francisco VOR",
            type=NavaidType.VOR,
            location=GMLPoint(pos="37.6213 -122.379"),
            frequency=115.8,
        )

    def test_convert_runway(self, converter, sample_runway):
        """Test runway conversion to internal format."""
        doc = AIXMDocument(runways=[sample_runway])
        config = converter.to_config(doc)

        assert "runways" in config
        assert len(config["runways"]) == 1

        runway = config["runways"][0]
        assert runway["id"] == "28L/10R"
        assert runway["width"] == 45
        assert runway["length"] == 3048
        assert runway["surfaceType"] == "ASPH"
        assert "start" in runway
        assert "end" in runway
        assert runway["start"]["x"] != runway["end"]["x"]  # Different positions

    def test_convert_runway_with_directions(self, converter, sample_runway):
        """Test runway direction data is preserved."""
        doc = AIXMDocument(runways=[sample_runway])
        config = converter.to_config(doc)

        runway = config["runways"][0]
        assert "directions" in runway
        assert len(runway["directions"]) == 2
        assert runway["directions"][0]["designator"] == "28L"
        assert runway["directions"][0]["bearing"] == 280.0

    def test_convert_taxiway(self, converter, sample_taxiway):
        """Test taxiway conversion to internal format."""
        doc = AIXMDocument(taxiways=[sample_taxiway])
        config = converter.to_config(doc)

        assert "taxiways" in config
        assert len(config["taxiways"]) == 1

        taxiway = config["taxiways"][0]
        assert taxiway["id"] == "A"
        assert taxiway["width"] == 20
        assert "points" in taxiway
        assert len(taxiway["points"]) == 3

    def test_convert_apron(self, converter, sample_apron):
        """Test apron conversion to internal format."""
        doc = AIXMDocument(aprons=[sample_apron])
        config = converter.to_config(doc)

        assert "aprons" in config
        assert len(config["aprons"]) == 1

        apron = config["aprons"][0]
        assert apron["id"] == "APRON-1"
        assert apron["name"] == "Main Apron"
        assert "position" in apron
        assert "polygon" in apron

    def test_convert_navaid(self, converter, sample_navaid):
        """Test navaid conversion to internal format."""
        doc = AIXMDocument(navaids=[sample_navaid])
        config = converter.to_config(doc)

        assert "navaids" in config
        assert len(config["navaids"]) == 1

        navaid = config["navaids"][0]
        assert navaid["id"] == "SFO-VOR"
        assert navaid["designator"] == "SFO"
        assert navaid["type"] == "VOR"
        assert navaid["frequency"] == 115.8

    def test_convert_with_airport_metadata(self, converter, sample_runway):
        """Test conversion updates reference point from airport ARP."""
        airport = AIXMAirportHeliport(
            gmlId="AHP-KSFO",
            identifier="KSFO",
            icaoCode="KSFO",
            iataCode="SFO",
            name="San Francisco International",
            arp=GMLPoint(pos="37.6213 -122.379"),
            elevation=4.0,
        )

        doc = AIXMDocument(airport=airport, runways=[sample_runway])
        config = converter.to_config(doc)

        assert "airport" in config
        assert config["airport"]["icaoCode"] == "KSFO"
        assert config["airport"]["iataCode"] == "SFO"
        assert config["airport"]["name"] == "San Francisco International"

    def test_convert_empty_document(self, converter):
        """Test conversion of empty document."""
        doc = AIXMDocument()
        config = converter.to_config(doc)

        assert config["source"] == "AIXM"
        assert config["runways"] == []
        assert config["taxiways"] == []

    def test_runway_without_centerline_uses_directions(self, converter):
        """Test runway conversion falls back to directions when no centerline."""
        runway = AIXMRunway(
            gmlId="RWY-01",
            identifier="RWY-28L",
            designator="28L/10R",
            length=3048,
            width=45,
            directions=[
                AIXMRunwayDirection(
                    gmlId="RWY-28L-DIR",
                    designator="28L",
                    trueBearing=280.0,
                    thresholdLocation=GMLPoint(pos="37.6190 -122.400"),
                ),
                AIXMRunwayDirection(
                    gmlId="RWY-10R-DIR",
                    designator="10R",
                    trueBearing=100.0,
                    thresholdLocation=GMLPoint(pos="37.6236 -122.358"),
                ),
            ],
        )

        doc = AIXMDocument(runways=[runway])
        config = converter.to_config(doc)

        assert len(config["runways"]) == 1
        assert "start" in config["runways"][0]
        assert "end" in config["runways"][0]


class TestMergeAIXMConfig:
    """Tests for merge_aixm_config function."""

    def test_merge_replaces_runways(self):
        """Test that AIXM runways replace existing runways."""
        base = {
            "runways": [{"id": "old", "width": 30}],
            "buildings": [{"id": "terminal"}],
        }
        aixm = {
            "runways": [{"id": "new", "width": 45}],
        }

        result = merge_aixm_config(base, aixm)

        assert len(result["runways"]) == 1
        assert result["runways"][0]["id"] == "new"
        # Buildings should be preserved
        assert result["buildings"] == [{"id": "terminal"}]

    def test_merge_replaces_taxiways(self):
        """Test that AIXM taxiways replace existing taxiways."""
        base = {
            "taxiways": [{"id": "old"}],
        }
        aixm = {
            "taxiways": [{"id": "A"}, {"id": "B"}],
        }

        result = merge_aixm_config(base, aixm)

        assert len(result["taxiways"]) == 2
        assert result["taxiways"][0]["id"] == "A"

    def test_merge_adds_aprons(self):
        """Test that AIXM aprons are added."""
        base = {"runways": []}
        aixm = {"aprons": [{"id": "APRON-1"}]}

        result = merge_aixm_config(base, aixm)

        assert "aprons" in result
        assert result["aprons"][0]["id"] == "APRON-1"

    def test_merge_preserves_non_aixm_fields(self):
        """Test that non-AIXM fields are preserved."""
        base = {
            "lighting": {"ambient": 0.6},
            "ground": {"size": 2000},
            "buildings": [{"id": "tower"}],
        }
        aixm = {
            "runways": [{"id": "28L"}],
        }

        result = merge_aixm_config(base, aixm)

        assert result["lighting"] == {"ambient": 0.6}
        assert result["ground"] == {"size": 2000}
        assert result["buildings"] == [{"id": "tower"}]

    def test_merge_empty_aixm_preserves_base(self):
        """Test that empty AIXM data preserves base config."""
        base = {
            "runways": [{"id": "existing"}],
            "taxiways": [{"id": "A"}],
        }
        aixm = {}

        result = merge_aixm_config(base, aixm)

        # Empty lists in aixm shouldn't replace
        assert result["runways"] == [{"id": "existing"}]
        assert result["taxiways"] == [{"id": "A"}]

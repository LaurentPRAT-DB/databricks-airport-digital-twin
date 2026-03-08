"""Tests for AIXM parser."""

import pytest

from src.formats.aixm.parser import AIXMParser
from src.formats.aixm.models import (
    AIXMDocument,
    AIXMRunway,
    AIXMTaxiway,
    RunwaySurfaceType,
)
from src.formats.base import ParseError


# Sample AIXM XML for testing
SAMPLE_AIXM_RUNWAY = b"""<?xml version="1.0" encoding="UTF-8"?>
<message:AIXMBasicMessage xmlns:message="http://www.aixm.aero/schema/5.1.1/message"
    xmlns:aixm="http://www.aixm.aero/schema/5.1.1"
    xmlns:gml="http://www.opengis.net/gml/3.2">
    <message:hasMember>
        <aixm:Runway gml:id="RWY_28L28R">
            <aixm:timeSlice>
                <aixm:RunwayTimeSlice gml:id="RWY_28L28R_TS1">
                    <aixm:identifier>RWY-28L-28R</aixm:identifier>
                    <aixm:designator>28L/10R</aixm:designator>
                    <aixm:nominalLength>3048</aixm:nominalLength>
                    <aixm:nominalWidth>45</aixm:nominalWidth>
                    <aixm:surfaceComposition>ASPH</aixm:surfaceComposition>
                    <aixm:centreLine>
                        <gml:posList>37.6190 -122.400 4.0 37.6236 -122.358 4.0</gml:posList>
                    </aixm:centreLine>
                </aixm:RunwayTimeSlice>
            </aixm:timeSlice>
        </aixm:Runway>
    </message:hasMember>
</message:AIXMBasicMessage>
"""

SAMPLE_AIXM_TAXIWAY = b"""<?xml version="1.0" encoding="UTF-8"?>
<message:AIXMBasicMessage xmlns:message="http://www.aixm.aero/schema/5.1.1/message"
    xmlns:aixm="http://www.aixm.aero/schema/5.1.1"
    xmlns:gml="http://www.opengis.net/gml/3.2">
    <message:hasMember>
        <aixm:Taxiway gml:id="TWY_A">
            <aixm:timeSlice>
                <aixm:TaxiwayTimeSlice gml:id="TWY_A_TS1">
                    <aixm:identifier>TWY-A</aixm:identifier>
                    <aixm:designator>A</aixm:designator>
                    <aixm:width>20</aixm:width>
                    <aixm:centreLine>
                        <gml:posList>37.6200 -122.380 4.0 37.6210 -122.380 4.0 37.6220 -122.385 4.0</gml:posList>
                    </aixm:centreLine>
                </aixm:TaxiwayTimeSlice>
            </aixm:timeSlice>
        </aixm:Taxiway>
    </message:hasMember>
</message:AIXMBasicMessage>
"""

SAMPLE_AIXM_AIRPORT = b"""<?xml version="1.0" encoding="UTF-8"?>
<message:AIXMBasicMessage xmlns:message="http://www.aixm.aero/schema/5.1.1/message"
    xmlns:aixm="http://www.aixm.aero/schema/5.1.1"
    xmlns:gml="http://www.opengis.net/gml/3.2">
    <message:hasMember>
        <aixm:AirportHeliport gml:id="AHP_KSFO">
            <aixm:timeSlice>
                <aixm:AirportHeliportTimeSlice gml:id="AHP_KSFO_TS1">
                    <aixm:identifier>KSFO</aixm:identifier>
                    <aixm:locationIndicatorICAO>KSFO</aixm:locationIndicatorICAO>
                    <aixm:designatorIATA>SFO</aixm:designatorIATA>
                    <aixm:name>San Francisco International Airport</aixm:name>
                    <aixm:fieldElevation>4.0</aixm:fieldElevation>
                    <aixm:ARP>
                        <gml:pos>37.6213 -122.379</gml:pos>
                    </aixm:ARP>
                </aixm:AirportHeliportTimeSlice>
            </aixm:timeSlice>
        </aixm:AirportHeliport>
    </message:hasMember>
</message:AIXMBasicMessage>
"""


class TestAIXMParser:
    """Tests for AIXM XML parser."""

    @pytest.fixture
    def parser(self):
        return AIXMParser()

    def test_parse_runway(self, parser):
        """Test parsing a runway from AIXM XML."""
        doc = parser.parse(SAMPLE_AIXM_RUNWAY)

        assert isinstance(doc, AIXMDocument)
        assert len(doc.runways) == 1

        runway = doc.runways[0]
        assert runway.designator == "28L/10R"
        assert runway.length == 3048
        assert runway.width == 45
        assert runway.surface_type == RunwaySurfaceType.ASPHALT
        assert runway.centre_line is not None

    def test_parse_taxiway(self, parser):
        """Test parsing a taxiway from AIXM XML."""
        doc = parser.parse(SAMPLE_AIXM_TAXIWAY)

        assert len(doc.taxiways) == 1

        taxiway = doc.taxiways[0]
        assert taxiway.designator == "A"
        assert taxiway.width == 20
        assert taxiway.centre_line is not None
        assert len(taxiway.centre_line.points) == 3

    def test_parse_airport(self, parser):
        """Test parsing airport metadata from AIXM XML."""
        doc = parser.parse(SAMPLE_AIXM_AIRPORT)

        assert doc.airport is not None
        assert doc.airport.icao_code == "KSFO"
        assert doc.airport.iata_code == "SFO"
        assert doc.airport.name == "San Francisco International Airport"
        assert doc.airport.elevation == 4.0
        assert doc.airport.arp is not None
        assert abs(doc.airport.arp.latitude - 37.6213) < 0.001

    def test_parse_invalid_xml(self, parser):
        """Test that invalid XML raises ParseError."""
        with pytest.raises(ParseError):
            parser.parse(b"not valid xml")

    def test_validate_runway(self, parser):
        """Test validation of parsed runway."""
        doc = parser.parse(SAMPLE_AIXM_RUNWAY)
        warnings = parser.validate(doc)

        # Should have no warnings for valid data
        assert not any("Invalid length" in w for w in warnings)
        assert not any("Invalid width" in w for w in warnings)

    def test_to_config_runway(self, parser):
        """Test conversion of runway to internal config."""
        doc = parser.parse(SAMPLE_AIXM_RUNWAY)
        config = parser.to_config(doc)

        assert "runways" in config
        assert len(config["runways"]) == 1

        runway_config = config["runways"][0]
        assert runway_config["id"] == "28L/10R"
        assert "start" in runway_config
        assert "end" in runway_config
        assert runway_config["width"] == 45

    def test_to_config_taxiway(self, parser):
        """Test conversion of taxiway to internal config."""
        doc = parser.parse(SAMPLE_AIXM_TAXIWAY)
        config = parser.to_config(doc)

        assert "taxiways" in config
        assert len(config["taxiways"]) == 1

        taxiway_config = config["taxiways"][0]
        assert taxiway_config["id"] == "A"
        assert "points" in taxiway_config
        assert len(taxiway_config["points"]) == 3

    def test_parse_empty_document(self, parser):
        """Test parsing an empty AIXM document."""
        empty_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <message:AIXMBasicMessage xmlns:message="http://www.aixm.aero/schema/5.1.1/message"
            xmlns:aixm="http://www.aixm.aero/schema/5.1.1"
            xmlns:gml="http://www.opengis.net/gml/3.2">
        </message:AIXMBasicMessage>
        """
        doc = parser.parse(empty_xml)

        assert doc.runways == []
        assert doc.taxiways == []
        assert doc.aprons == []


class TestAIXMModels:
    """Tests for AIXM Pydantic models."""

    def test_runway_model(self):
        """Test AIXMRunway model creation."""
        runway = AIXMRunway(
            gmlId="RWY_01",
            identifier="RWY-28L",
            designator="28L/10R",
            length=3048,
            width=45,
        )

        assert runway.gml_id == "RWY_01"
        assert runway.designator == "28L/10R"
        assert runway.length == 3048
        assert runway.type == "RWY"

    def test_taxiway_model(self):
        """Test AIXMTaxiway model creation."""
        taxiway = AIXMTaxiway(
            gmlId="TWY_A",
            identifier="TWY-A",
            designator="A",
            width=20,
        )

        assert taxiway.gml_id == "TWY_A"
        assert taxiway.designator == "A"
        assert taxiway.type == "TWY"

    def test_document_defaults(self):
        """Test AIXMDocument default values."""
        doc = AIXMDocument()

        assert doc.version == "5.1.1"
        assert doc.runways == []
        assert doc.taxiways == []
        assert doc.aprons == []
        assert doc.navaids == []

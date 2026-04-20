"""
Tests for AIXM parser coverage.

Covers uncovered lines in src/formats/aixm/parser.py including:
- parse() with bytes input, file path input, error handling
- validate() warnings for missing geometry
- _parse_document() for all element types
- _parse_runway() with surface type, centre line, directions
- _parse_runway_direction() with threshold, bearings
- _parse_taxiway() with geometry
- _parse_apron() with polygon
- _parse_navaid() with type parsing, location
- _parse_linestring(), _parse_polygon() GML geometry helpers
- _get_float() with invalid values
"""

import tempfile
from pathlib import Path

import pytest

from src.formats.aixm.parser import AIXMParser, NAMESPACES
from src.formats.aixm.models import (
    AIXMDocument,
    RunwaySurfaceType,
    NavaidType,
)
from src.formats.base import ParseError


# ---------------------------------------------------------------------------
# Helper: build a minimal AIXM XML wrapper
# ---------------------------------------------------------------------------

def _wrap_aixm(*feature_blocks: str) -> str:
    """Wrap AIXM feature XML fragments in the root message element."""
    inner = "\n".join(feature_blocks)
    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<message:AIXMBasicMessage
    xmlns:message="{NAMESPACES['message']}"
    xmlns:aixm="{NAMESPACES['aixm']}"
    xmlns:gml="{NAMESPACES['gml']}"
    xmlns:xlink="{NAMESPACES['xlink']}">
{inner}
</message:AIXMBasicMessage>"""


def _airport_xml(
    gml_id="AH_KSFO",
    icao="KSFO",
    iata="SFO",
    name="San Francisco Intl",
    arp_pos="37.6213 -122.379",
    elevation="4.0",
    mag_var="-14.0",
) -> str:
    arp_block = ""
    if arp_pos:
        arp_block = f"""
        <aixm:ARP>
          <aixm:ElevatedPoint>
            <gml:pos>{arp_pos}</gml:pos>
          </aixm:ElevatedPoint>
        </aixm:ARP>"""
    return f"""\
<aixm:AirportHeliport gml:id="{gml_id}">
  <aixm:timeSlice>
    <aixm:AirportHeliportTimeSlice>
      <aixm:identifier>{gml_id}</aixm:identifier>
      <aixm:locationIndicatorICAO>{icao}</aixm:locationIndicatorICAO>
      <aixm:designatorIATA>{iata}</aixm:designatorIATA>
      <aixm:name>{name}</aixm:name>{arp_block}
      <aixm:fieldElevation>{elevation}</aixm:fieldElevation>
      <aixm:magneticVariation>{mag_var}</aixm:magneticVariation>
    </aixm:AirportHeliportTimeSlice>
  </aixm:timeSlice>
</aixm:AirportHeliport>"""


def _runway_xml(
    gml_id="RWY_01",
    designator="10L/28R",
    length="3048",
    width="45",
    surface="ASPH",
    centre_line_pos="37.6200 -122.380 37.6230 -122.378",
    include_direction=True,
) -> str:
    surface_block = f"<aixm:surfaceComposition>{surface}</aixm:surfaceComposition>" if surface else ""
    centre_line_block = ""
    if centre_line_pos:
        centre_line_block = f"""
      <aixm:centreLine>
        <gml:LineString>
          <gml:posList>{centre_line_pos}</gml:posList>
        </gml:LineString>
      </aixm:centreLine>"""
    direction_block = ""
    if include_direction:
        direction_block = f"""
  <aixm:RunwayDirection gml:id="RWYDIR_10L">
    <aixm:timeSlice>
      <aixm:RunwayDirectionTimeSlice>
        <aixm:designator>10L</aixm:designator>
        <aixm:trueBearing>100.5</aixm:trueBearing>
        <aixm:magneticBearing>114.5</aixm:magneticBearing>
        <aixm:aiming>
          <gml:Point>
            <gml:pos>37.6200 -122.380</gml:pos>
          </gml:Point>
        </aixm:aiming>
        <aixm:elevation>4.0</aixm:elevation>
      </aixm:RunwayDirectionTimeSlice>
    </aixm:timeSlice>
  </aixm:RunwayDirection>"""
    return f"""\
<aixm:Runway gml:id="{gml_id}">
  <aixm:timeSlice>
    <aixm:RunwayTimeSlice>
      <aixm:identifier>{gml_id}</aixm:identifier>
      <aixm:designator>{designator}</aixm:designator>
      <aixm:nominalLength>{length}</aixm:nominalLength>
      <aixm:nominalWidth>{width}</aixm:nominalWidth>
      {surface_block}{centre_line_block}
    </aixm:RunwayTimeSlice>
  </aixm:timeSlice>{direction_block}
</aixm:Runway>"""


def _taxiway_xml(
    gml_id="TWY_A",
    designator="A",
    width="23",
    centre_line_pos="37.620 -122.380 37.621 -122.379",
    extent_pos="37.620 -122.380 37.621 -122.379 37.621 -122.378 37.620 -122.380",
) -> str:
    cl_block = ""
    if centre_line_pos:
        cl_block = f"""
      <aixm:centreLine>
        <gml:LineString>
          <gml:posList>{centre_line_pos}</gml:posList>
        </gml:LineString>
      </aixm:centreLine>"""
    ext_block = ""
    if extent_pos:
        ext_block = f"""
      <aixm:extent>
        <gml:Polygon>
          <gml:posList>{extent_pos}</gml:posList>
        </gml:Polygon>
      </aixm:extent>"""
    return f"""\
<aixm:Taxiway gml:id="{gml_id}">
  <aixm:timeSlice>
    <aixm:TaxiwayTimeSlice>
      <aixm:identifier>{gml_id}</aixm:identifier>
      <aixm:designator>{designator}</aixm:designator>
      <aixm:width>{width}</aixm:width>{cl_block}{ext_block}
    </aixm:TaxiwayTimeSlice>
  </aixm:timeSlice>
</aixm:Taxiway>"""


def _apron_xml(
    gml_id="APRON_01",
    name="Main Apron",
    extent_pos="37.620 -122.380 37.621 -122.379 37.621 -122.378 37.620 -122.380",
) -> str:
    ext_block = ""
    if extent_pos:
        ext_block = f"""
      <aixm:extent>
        <gml:Polygon>
          <gml:posList>{extent_pos}</gml:posList>
        </gml:Polygon>
      </aixm:extent>"""
    return f"""\
<aixm:Apron gml:id="{gml_id}">
  <aixm:timeSlice>
    <aixm:ApronTimeSlice>
      <aixm:identifier>{gml_id}</aixm:identifier>
      <aixm:name>{name}</aixm:name>{ext_block}
    </aixm:ApronTimeSlice>
  </aixm:timeSlice>
</aixm:Apron>"""


def _navaid_xml(
    gml_id="NAV_SFO",
    designator="SFO",
    name="San Francisco VOR",
    navaid_type="VOR",
    location_pos="37.6200 -122.3800",
    frequency="115.8",
) -> str:
    loc_block = ""
    if location_pos:
        loc_block = f"""
      <aixm:location>
        <gml:Point>
          <gml:pos>{location_pos}</gml:pos>
        </gml:Point>
      </aixm:location>"""
    return f"""\
<aixm:Navaid gml:id="{gml_id}">
  <aixm:timeSlice>
    <aixm:NavaidTimeSlice>
      <aixm:identifier>{gml_id}</aixm:identifier>
      <aixm:designator>{designator}</aixm:designator>
      <aixm:name>{name}</aixm:name>
      <aixm:type>{navaid_type}</aixm:type>{loc_block}
      <aixm:frequency>{frequency}</aixm:frequency>
    </aixm:NavaidTimeSlice>
  </aixm:timeSlice>
</aixm:Navaid>"""


# ===========================================================================
# Tests
# ===========================================================================


class TestParseBytes:
    """Tests for parse() with bytes input (lines 84-85)."""

    def test_parse_bytes_input(self):
        xml = _wrap_aixm(_airport_xml())
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert doc.airport is not None
        assert doc.airport.icao_code == "KSFO"

    def test_parse_bytes_with_all_features(self):
        xml = _wrap_aixm(
            _airport_xml(),
            _runway_xml(),
            _taxiway_xml(),
            _apron_xml(),
            _navaid_xml(),
        )
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert doc.airport is not None
        assert len(doc.runways) == 1
        assert len(doc.taxiways) == 1
        assert len(doc.aprons) == 1
        assert len(doc.navaids) == 1


class TestParseFilePath:
    """Tests for parse() with file path input (lines 86-88)."""

    def test_parse_file_path_string(self, tmp_path):
        xml = _wrap_aixm(_airport_xml())
        f = tmp_path / "test.xml"
        f.write_text(xml)
        parser = AIXMParser()
        doc = parser.parse(str(f))
        assert doc.airport is not None
        assert doc.airport.icao_code == "KSFO"

    def test_parse_file_path_object(self, tmp_path):
        xml = _wrap_aixm(_airport_xml())
        f = tmp_path / "test.xml"
        f.write_text(xml)
        parser = AIXMParser()
        doc = parser.parse(f)
        assert doc.airport is not None


class TestParseErrorHandling:
    """Tests for parse() error paths (lines 89-90, 94-97)."""

    def test_parse_unsupported_type_raises(self):
        parser = AIXMParser()
        with pytest.raises(ParseError, match="Unsupported source type"):
            parser.parse(12345)  # type: ignore

    def test_parse_invalid_xml_bytes_raises(self):
        parser = AIXMParser()
        with pytest.raises(ParseError, match="(XML parsing error|Failed to parse AIXM)"):
            parser.parse(b"<not-valid-xml")

    def test_parse_nonexistent_file_raises(self):
        parser = AIXMParser()
        with pytest.raises(ParseError):
            parser.parse("/nonexistent/path/file.xml")


class TestValidate:
    """Tests for validate() (lines 115-130)."""

    def test_validate_empty_document_warns(self):
        parser = AIXMParser()
        doc = AIXMDocument()
        warnings = parser.validate(doc)
        assert any("No runways, taxiways, or aprons" in w for w in warnings)

    def test_validate_runway_invalid_length(self):
        from src.formats.aixm.models import AIXMRunway
        parser = AIXMParser()
        doc = AIXMDocument(
            runways=[
                AIXMRunway(
                    gmlId="R1",
                    identifier="R1",
                    designator="10L/28R",
                    length=-10,
                    width=45,
                )
            ]
        )
        warnings = parser.validate(doc)
        assert any("Invalid length" in w for w in warnings)

    def test_validate_runway_invalid_width(self):
        from src.formats.aixm.models import AIXMRunway
        parser = AIXMParser()
        doc = AIXMDocument(
            runways=[
                AIXMRunway(
                    gmlId="R1",
                    identifier="R1",
                    designator="10L/28R",
                    length=3000,
                    width=-5,
                )
            ]
        )
        warnings = parser.validate(doc)
        assert any("Invalid width" in w for w in warnings)

    def test_validate_runway_missing_centre_line(self):
        from src.formats.aixm.models import AIXMRunway
        parser = AIXMParser()
        doc = AIXMDocument(
            runways=[
                AIXMRunway(
                    gmlId="R1",
                    identifier="R1",
                    designator="10L/28R",
                    length=3000,
                    width=45,
                    centreLine=None,
                )
            ]
        )
        warnings = parser.validate(doc)
        assert any("Missing center line" in w for w in warnings)

    def test_validate_taxiway_missing_geometry(self):
        from src.formats.aixm.models import AIXMTaxiway
        parser = AIXMParser()
        doc = AIXMDocument(
            taxiways=[
                AIXMTaxiway(
                    gmlId="T1",
                    identifier="T1",
                    designator="A",
                    centreLine=None,
                    extent=None,
                )
            ]
        )
        warnings = parser.validate(doc)
        assert any("Missing geometry" in w for w in warnings)

    def test_validate_clean_document(self):
        from src.formats.aixm.models import AIXMRunway, GMLLineString
        parser = AIXMParser()
        doc = AIXMDocument(
            runways=[
                AIXMRunway(
                    gmlId="R1",
                    identifier="R1",
                    designator="10L/28R",
                    length=3000,
                    width=45,
                    centreLine=GMLLineString(posList="37.62 -122.38 37.63 -122.37"),
                )
            ]
        )
        warnings = parser.validate(doc)
        assert len(warnings) == 0


class TestParseRunway:
    """Tests for _parse_runway() (lines 220, 232-234, 242-244)."""

    def test_runway_with_surface_type(self):
        xml = _wrap_aixm(_runway_xml(surface="ASPH"))
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert len(doc.runways) == 1
        assert doc.runways[0].surface_type == RunwaySurfaceType.ASPHALT

    def test_runway_with_concrete_surface(self):
        xml = _wrap_aixm(_runway_xml(surface="CONC"))
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert doc.runways[0].surface_type == RunwaySurfaceType.CONCRETE

    def test_runway_with_unknown_surface_type(self):
        xml = _wrap_aixm(_runway_xml(surface="UNKNOWN_SURFACE"))
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert doc.runways[0].surface_type is None

    def test_runway_without_surface_type(self):
        xml = _wrap_aixm(_runway_xml(surface=None))
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert doc.runways[0].surface_type is None

    def test_runway_centre_line_geometry(self):
        xml = _wrap_aixm(_runway_xml(centre_line_pos="37.6200 -122.380 37.6230 -122.378"))
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert doc.runways[0].centre_line is not None
        assert "37.6200" in doc.runways[0].centre_line.pos_list

    def test_runway_without_centre_line(self):
        xml = _wrap_aixm(_runway_xml(centre_line_pos=None))
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert doc.runways[0].centre_line is None

    def test_runway_with_directions(self):
        xml = _wrap_aixm(_runway_xml(include_direction=True))
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert len(doc.runways[0].directions) == 1
        d = doc.runways[0].directions[0]
        assert d.designator == "10L"
        assert d.true_bearing == 100.5
        assert d.magnetic_bearing == 114.5
        assert d.threshold_location is not None
        assert d.threshold_location.latitude == 37.62
        assert d.elevation == 4.0

    def test_runway_without_directions(self):
        xml = _wrap_aixm(_runway_xml(include_direction=False))
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert len(doc.runways[0].directions) == 0

    def test_runway_no_timeslice_returns_none(self):
        """Runway element without a RunwayTimeSlice is skipped (line 220)."""
        xml = _wrap_aixm(f"""\
<aixm:Runway gml:id="RWY_BAD">
  <aixm:someOtherElement/>
</aixm:Runway>""")
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert len(doc.runways) == 0


class TestParseRunwayDirection:
    """Tests for _parse_runway_direction() (lines 259-277)."""

    def test_direction_no_timeslice_skipped(self):
        """RunwayDirection without RunwayDirectionTimeSlice is skipped."""
        xml = _wrap_aixm(f"""\
<aixm:Runway gml:id="RWY_01">
  <aixm:timeSlice>
    <aixm:RunwayTimeSlice>
      <aixm:identifier>RWY_01</aixm:identifier>
      <aixm:designator>10L/28R</aixm:designator>
      <aixm:nominalLength>3000</aixm:nominalLength>
      <aixm:nominalWidth>45</aixm:nominalWidth>
    </aixm:RunwayTimeSlice>
  </aixm:timeSlice>
  <aixm:RunwayDirection gml:id="RWYDIR_BAD">
    <aixm:otherStuff/>
  </aixm:RunwayDirection>
</aixm:Runway>""")
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert len(doc.runways) == 1
        assert len(doc.runways[0].directions) == 0

    def test_direction_without_threshold(self):
        """Direction with no aiming/gml:pos gets threshold_location=None."""
        xml = _wrap_aixm(f"""\
<aixm:Runway gml:id="RWY_01">
  <aixm:timeSlice>
    <aixm:RunwayTimeSlice>
      <aixm:identifier>RWY_01</aixm:identifier>
      <aixm:designator>10L/28R</aixm:designator>
      <aixm:nominalLength>3000</aixm:nominalLength>
      <aixm:nominalWidth>45</aixm:nominalWidth>
    </aixm:RunwayTimeSlice>
  </aixm:timeSlice>
  <aixm:RunwayDirection gml:id="RWYDIR_10L">
    <aixm:timeSlice>
      <aixm:RunwayDirectionTimeSlice>
        <aixm:designator>10L</aixm:designator>
        <aixm:trueBearing>100.0</aixm:trueBearing>
      </aixm:RunwayDirectionTimeSlice>
    </aixm:timeSlice>
  </aixm:RunwayDirection>
</aixm:Runway>""")
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        d = doc.runways[0].directions[0]
        assert d.threshold_location is None
        assert d.true_bearing == 100.0


class TestParseTaxiway:
    """Tests for _parse_taxiway() (lines 292, 299-309)."""

    def test_taxiway_full(self):
        xml = _wrap_aixm(_taxiway_xml())
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert len(doc.taxiways) == 1
        t = doc.taxiways[0]
        assert t.designator == "A"
        assert t.width == 23.0
        assert t.centre_line is not None
        assert t.extent is not None

    def test_taxiway_no_timeslice_skipped(self):
        xml = _wrap_aixm(f"""\
<aixm:Taxiway gml:id="TWY_BAD">
  <aixm:otherStuff/>
</aixm:Taxiway>""")
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert len(doc.taxiways) == 0

    def test_taxiway_no_geometry(self):
        xml = _wrap_aixm(_taxiway_xml(centre_line_pos=None, extent_pos=None))
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert len(doc.taxiways) == 1
        assert doc.taxiways[0].centre_line is None
        assert doc.taxiways[0].extent is None


class TestParseApron:
    """Tests for _parse_apron() (lines 313-325)."""

    def test_apron_full(self):
        xml = _wrap_aixm(_apron_xml())
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert len(doc.aprons) == 1
        a = doc.aprons[0]
        assert a.name == "Main Apron"
        assert a.extent is not None
        assert a.extent.exterior is not None

    def test_apron_no_timeslice_skipped(self):
        xml = _wrap_aixm(f"""\
<aixm:Apron gml:id="APRON_BAD">
  <aixm:otherStuff/>
</aixm:Apron>""")
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert len(doc.aprons) == 0

    def test_apron_no_extent(self):
        xml = _wrap_aixm(_apron_xml(extent_pos=None))
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert len(doc.aprons) == 1
        assert doc.aprons[0].extent is None


class TestParseNavaid:
    """Tests for _parse_navaid() (lines 334-359)."""

    def test_navaid_vor(self):
        xml = _wrap_aixm(_navaid_xml(navaid_type="VOR"))
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert len(doc.navaids) == 1
        n = doc.navaids[0]
        assert n.type == NavaidType.VOR
        assert n.designator == "SFO"
        assert n.name == "San Francisco VOR"
        assert n.frequency == 115.8
        assert n.location is not None
        assert n.location.latitude == 37.62

    def test_navaid_ils(self):
        xml = _wrap_aixm(_navaid_xml(navaid_type="ILS", designator="ISFO"))
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert doc.navaids[0].type == NavaidType.ILS

    def test_navaid_ndb(self):
        xml = _wrap_aixm(_navaid_xml(navaid_type="NDB"))
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert doc.navaids[0].type == NavaidType.NDB

    def test_navaid_unknown_type_defaults_to_vor(self):
        xml = _wrap_aixm(_navaid_xml(navaid_type="UNKNOWN_TYPE"))
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert doc.navaids[0].type == NavaidType.VOR

    def test_navaid_no_timeslice_skipped(self):
        xml = _wrap_aixm(f"""\
<aixm:Navaid gml:id="NAV_BAD">
  <aixm:otherStuff/>
</aixm:Navaid>""")
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert len(doc.navaids) == 0

    def test_navaid_no_location(self):
        xml = _wrap_aixm(_navaid_xml(location_pos=None))
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert doc.navaids[0].location is None

    def test_navaid_no_type_defaults_to_vor(self):
        """Navaid without <aixm:type> defaults to VOR."""
        xml = _wrap_aixm(f"""\
<aixm:Navaid gml:id="NAV_NOTYPE">
  <aixm:timeSlice>
    <aixm:NavaidTimeSlice>
      <aixm:identifier>NAV_NOTYPE</aixm:identifier>
      <aixm:designator>XYZ</aixm:designator>
      <aixm:name>No Type</aixm:name>
      <aixm:frequency>110.0</aixm:frequency>
    </aixm:NavaidTimeSlice>
  </aixm:timeSlice>
</aixm:Navaid>""")
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert doc.navaids[0].type == NavaidType.VOR


class TestParseAirport:
    """Tests for _parse_airport() (line 186)."""

    def test_airport_no_timeslice_returns_none(self):
        xml = _wrap_aixm(f"""\
<aixm:AirportHeliport gml:id="AH_BAD">
  <aixm:otherElement/>
</aixm:AirportHeliport>""")
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert doc.airport is None

    def test_airport_full(self):
        xml = _wrap_aixm(_airport_xml())
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        a = doc.airport
        assert a is not None
        assert a.icao_code == "KSFO"
        assert a.iata_code == "SFO"
        assert a.name == "San Francisco Intl"
        assert a.arp is not None
        assert a.arp.latitude == 37.6213
        assert a.elevation == 4.0
        assert a.magnetic_variation == -14.0

    def test_airport_no_arp(self):
        xml = _wrap_aixm(_airport_xml(arp_pos=None))
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert doc.airport.arp is None


class TestGetFloat:
    """Tests for _get_float() invalid value path (lines 380-381)."""

    def test_get_float_invalid_value(self):
        """Non-numeric text returns None."""
        xml = _wrap_aixm(f"""\
<aixm:AirportHeliport gml:id="AH_BAD_ELEV">
  <aixm:timeSlice>
    <aixm:AirportHeliportTimeSlice>
      <aixm:identifier>AH_BAD_ELEV</aixm:identifier>
      <aixm:name>Bad Elevation</aixm:name>
      <aixm:fieldElevation>not_a_number</aixm:fieldElevation>
    </aixm:AirportHeliportTimeSlice>
  </aixm:timeSlice>
</aixm:AirportHeliport>""")
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert doc.airport is not None
        assert doc.airport.elevation is None


class TestParseLineStringAndPolygon:
    """Tests for _parse_linestring() and _parse_polygon() (lines 384-396)."""

    def test_linestring_parsed_from_taxiway(self):
        xml = _wrap_aixm(_taxiway_xml(
            centre_line_pos="37.620 -122.380 37.621 -122.379",
            extent_pos=None,
        ))
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        cl = doc.taxiways[0].centre_line
        assert cl is not None
        points = cl.points
        assert len(points) == 2
        assert points[0][0] == pytest.approx(37.620)

    def test_polygon_parsed_from_apron(self):
        xml = _wrap_aixm(_apron_xml(
            extent_pos="37.620 -122.380 37.621 -122.379 37.621 -122.378 37.620 -122.380"
        ))
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        ext = doc.aprons[0].extent
        assert ext is not None
        points = ext.exterior.points
        assert len(points) == 4

    def test_linestring_returns_none_when_missing(self):
        xml = _wrap_aixm(_taxiway_xml(centre_line_pos=None, extent_pos=None))
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert doc.taxiways[0].centre_line is None

    def test_polygon_returns_none_when_missing(self):
        xml = _wrap_aixm(_apron_xml(extent_pos=None))
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))
        assert doc.aprons[0].extent is None


class TestFullDocument:
    """Integration test: parse a complete AIXM document with all features."""

    def test_complete_document(self):
        xml = _wrap_aixm(
            _airport_xml(),
            _runway_xml(),
            _runway_xml(gml_id="RWY_02", designator="01L/19R", length="2500", surface="CONC"),
            _taxiway_xml(),
            _taxiway_xml(gml_id="TWY_B", designator="B"),
            _apron_xml(),
            _navaid_xml(),
            _navaid_xml(gml_id="NAV_ILS", designator="ISFO", navaid_type="ILS", frequency="110.3"),
        )
        parser = AIXMParser()
        doc = parser.parse(xml.encode("utf-8"))

        assert doc.airport is not None
        assert len(doc.runways) == 2
        assert len(doc.taxiways) == 2
        assert len(doc.aprons) == 1
        assert len(doc.navaids) == 2

        # Validate should produce no warnings
        warnings = parser.validate(doc)
        assert len(warnings) == 0

    def test_complete_document_from_file(self, tmp_path):
        xml = _wrap_aixm(
            _airport_xml(),
            _runway_xml(),
            _taxiway_xml(),
            _apron_xml(),
            _navaid_xml(),
        )
        f = tmp_path / "airport.xml"
        f.write_text(xml)
        parser = AIXMParser()
        doc = parser.parse(f)
        assert doc.airport is not None
        assert len(doc.runways) == 1

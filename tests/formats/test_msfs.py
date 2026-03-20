"""
Unit tests for Microsoft Flight Simulator scenery parser.

Tests XML parsing, BGL binary parsing, coordinate conversion,
gate extraction, taxi path building, runway parsing, and converter output.
"""

import math
import os
import struct
import tempfile
import zipfile

import pytest

from src.formats.base import CoordinateConverter, ParseError
from src.formats.msfs.bgl_parser import (
    bgl_lon,
    bgl_lat,
    is_bgl,
    extract_icao_from_path,
    BGL_MAGIC,
    SECTION_AIRPORT,
)
from src.formats.msfs.models import (
    MSFSDocument,
    MSFSParkingSpot,
    MSFSTaxiPoint,
    MSFSTaxiPath,
    MSFSRunway,
    MSFSRunwayEnd,
    MSFSApron,
    MSFSApronVertex,
    ParkingType,
    TaxiPointType,
    TaxiPathType,
)
from src.formats.msfs.parser import MSFSParser
from src.formats.msfs.converter import MSFSConverter, merge_msfs_config


# Sample MSFS airport XML for testing (simplified but realistic structure)
SAMPLE_MSFS_XML = b"""\
<?xml version="1.0" encoding="utf-8"?>
<FSData>
  <Airport ident="KSFO" name="San Francisco International" lat="37.6213" lon="-122.379" alt="4.0">
    <TaxiwayParking index="0" lat="37.6145" lon="-122.3955" heading="270.0" radius="30"
                    type="GATE" name="GATE_A" number="1" airlineCodes="UAL,AAL"/>
    <TaxiwayParking index="1" lat="37.6140" lon="-122.3945" heading="90.0" radius="25"
                    type="GATE" name="GATE_A" number="2" airlineCodes="DAL"/>
    <TaxiwayParking index="2" lat="37.6135" lon="-122.3950" heading="180.0" radius="20"
                    type="RAMP" name="RAMP_GA" number="1"/>
    <TaxiwayParking index="3" lat="37.6130" lon="-122.3940" heading="0.0" radius="15"
                    type="DOCK" name="DOCK_" number="0"/>

    <TaxiwayPoint index="0" lat="37.6150" lon="-122.3970" type="NORMAL"/>
    <TaxiwayPoint index="1" lat="37.6150" lon="-122.3950" type="NORMAL"/>
    <TaxiwayPoint index="2" lat="37.6140" lon="-122.3950" type="HOLD_SHORT"/>
    <TaxiwayPoint index="3" lat="37.6140" lon="-122.3930" type="NORMAL"/>

    <TaxiwayPath start="0" end="1" width="23" name="A" type="TAXI" weightLimit="500000" surface="CONCRETE"/>
    <TaxiwayPath start="1" end="2" width="23" name="A" type="TAXI" weightLimit="500000" surface="CONCRETE"/>
    <TaxiwayPath start="2" end="3" width="20" name="B" type="TAXI" surface="ASPHALT"/>

    <Runway lat="37.6200" lon="-122.3800" heading="280.0" length="3618" width="60"
            surface="ASPHALT" designator="28L">
      <RunwayEnd designator="28L" lat="37.6190" lon="-122.3900"/>
      <RunwayEnd designator="10R" lat="37.6210" lon="-122.3700"/>
    </Runway>

    <Apron surface="CONCRETE">
      <Vertex lat="37.6150" lon="-122.3970"/>
      <Vertex lat="37.6150" lon="-122.3940"/>
      <Vertex lat="37.6130" lon="-122.3940"/>
      <Vertex lat="37.6130" lon="-122.3970"/>
    </Apron>
  </Airport>
</FSData>
"""

# Minimal XML with only required elements
MINIMAL_MSFS_XML = b"""\
<?xml version="1.0" encoding="utf-8"?>
<FSData>
  <Airport ident="KJFK" name="John F Kennedy" lat="40.6413" lon="-73.7781" alt="4.0">
    <TaxiwayParking index="0" lat="40.6420" lon="-73.7790" heading="90" radius="30" type="GATE" name="GATE_A" number="10"/>
  </Airport>
</FSData>
"""

# Invalid XML (no Airport)
NO_AIRPORT_XML = b"""\
<?xml version="1.0" encoding="utf-8"?>
<FSData>
</FSData>
"""

# Wrong root element
WRONG_ROOT_XML = b"""\
<?xml version="1.0" encoding="utf-8"?>
<NotFSData>
  <Airport ident="KSFO"/>
</NotFSData>
"""


class TestMSFSModels:
    """Tests for MSFS Pydantic models."""

    def test_parking_spot_gate(self):
        spot = MSFSParkingSpot(
            index=0, lat=37.6145, lon=-122.3955,
            heading=270.0, radius=30, type=ParkingType.GATE,
            name="GATE_A", number=1,
        )
        assert spot.is_gate
        assert spot.display_name == "A1"

    def test_parking_spot_ramp(self):
        spot = MSFSParkingSpot(
            index=1, lat=37.6135, lon=-122.3950,
            type=ParkingType.RAMP, name="RAMP_GA", number=1,
        )
        assert not spot.is_gate
        assert spot.display_name == "GA1"

    def test_parking_spot_no_number(self):
        spot = MSFSParkingSpot(
            index=5, lat=37.61, lon=-122.39,
            type=ParkingType.DOCK, name="DOCK_", number=0,
        )
        # number=0, name prefix is empty after stripping -> falls back to index
        assert spot.display_name == "S5"

    def test_document_gates_filter(self):
        doc = MSFSDocument(
            parking_spots=[
                MSFSParkingSpot(index=0, lat=37.61, lon=-122.39, type=ParkingType.GATE, name="GATE_A", number=1),
                MSFSParkingSpot(index=1, lat=37.62, lon=-122.38, type=ParkingType.RAMP, name="RAMP_GA", number=1),
                MSFSParkingSpot(index=2, lat=37.63, lon=-122.37, type=ParkingType.GATE, name="GATE_B", number=2),
            ],
        )
        assert len(doc.gates) == 2
        assert len(doc.ramps) == 1

    def test_taxi_path_types(self):
        path = MSFSTaxiPath(start=0, end=1, type=TaxiPathType.TAXI, name="A")
        assert path.type == TaxiPathType.TAXI

        doc = MSFSDocument(
            taxi_paths=[
                MSFSTaxiPath(start=0, end=1, type=TaxiPathType.TAXI, name="A"),
                MSFSTaxiPath(start=1, end=2, type=TaxiPathType.RUNWAY, name="28L"),
                MSFSTaxiPath(start=2, end=3, type=TaxiPathType.TAXI, name="B"),
            ],
        )
        assert len(doc.taxi_taxiways) == 2

    def test_apron_center(self):
        apron = MSFSApron(
            surface="CONCRETE",
            vertices=[
                MSFSApronVertex(lat=37.615, lon=-122.397),
                MSFSApronVertex(lat=37.615, lon=-122.394),
                MSFSApronVertex(lat=37.613, lon=-122.394),
                MSFSApronVertex(lat=37.613, lon=-122.397),
            ],
        )
        center_lat, center_lon = apron.center
        assert abs(center_lat - 37.614) < 0.001
        assert abs(center_lon - (-122.3955)) < 0.001

    def test_runway_with_ends(self):
        runway = MSFSRunway(
            lat=37.62, lon=-122.38, heading=280, length=3618, width=60,
            primary_end=MSFSRunwayEnd(designator="28L", lat=37.619, lon=-122.39),
            secondary_end=MSFSRunwayEnd(designator="10R", lat=37.621, lon=-122.37),
        )
        assert runway.primary_end.designator == "28L"
        assert runway.secondary_end.designator == "10R"


class TestMSFSParser:
    """Tests for MSFS XML parser."""

    def test_parse_xml_bytes(self):
        parser = MSFSParser()
        doc = parser.parse(SAMPLE_MSFS_XML)

        assert isinstance(doc, MSFSDocument)
        assert doc.icao_code == "KSFO"
        assert doc.airport_name == "San Francisco International"
        assert abs(doc.lat - 37.6213) < 0.001

    def test_parse_parking_spots(self):
        parser = MSFSParser()
        doc = parser.parse(SAMPLE_MSFS_XML)

        assert len(doc.parking_spots) == 4
        assert len(doc.gates) == 2

        gate = doc.gates[0]
        assert gate.display_name == "A1"
        assert abs(gate.heading - 270.0) < 0.1
        assert gate.airline_codes == ["UAL", "AAL"]

    def test_parse_taxi_points(self):
        parser = MSFSParser()
        doc = parser.parse(SAMPLE_MSFS_XML)

        assert len(doc.taxi_points) == 4
        assert doc.taxi_points[2].type == TaxiPointType.HOLD_SHORT

    def test_parse_taxi_paths(self):
        parser = MSFSParser()
        doc = parser.parse(SAMPLE_MSFS_XML)

        assert len(doc.taxi_paths) == 3
        assert doc.taxi_paths[0].name == "A"
        assert doc.taxi_paths[0].surface == "CONCRETE"
        assert doc.taxi_paths[0].weight_limit == 500000

    def test_parse_runway(self):
        parser = MSFSParser()
        doc = parser.parse(SAMPLE_MSFS_XML)

        assert len(doc.runways) == 1
        rwy = doc.runways[0]
        assert abs(rwy.heading - 280.0) < 0.1
        assert rwy.length == 3618
        assert rwy.width == 60
        assert rwy.primary_end.designator == "28L"
        assert rwy.secondary_end.designator == "10R"

    def test_parse_apron(self):
        parser = MSFSParser()
        doc = parser.parse(SAMPLE_MSFS_XML)

        assert len(doc.aprons) == 1
        assert len(doc.aprons[0].vertices) == 4
        assert doc.aprons[0].surface == "CONCRETE"

    def test_parse_minimal(self):
        parser = MSFSParser()
        doc = parser.parse(MINIMAL_MSFS_XML)

        assert doc.icao_code == "KJFK"
        assert len(doc.parking_spots) == 1
        assert doc.gates[0].display_name == "A10"

    def test_parse_no_airport_raises(self):
        parser = MSFSParser()
        with pytest.raises(ParseError, match="No Airport elements"):
            parser.parse(NO_AIRPORT_XML)

    def test_parse_wrong_root_raises(self):
        parser = MSFSParser()
        with pytest.raises(ParseError, match="Expected FSData"):
            parser.parse(WRONG_ROOT_XML)

    def test_parse_invalid_xml_raises(self):
        parser = MSFSParser()
        with pytest.raises(ParseError):
            parser.parse(b"<not valid xml")

    def test_parse_xml_file(self):
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
            f.write(SAMPLE_MSFS_XML)
            f.flush()
            try:
                parser = MSFSParser()
                doc = parser.parse(f.name)
                assert doc.icao_code == "KSFO"
                assert len(doc.parking_spots) == 4
            finally:
                os.unlink(f.name)

    def test_parse_zip_archive(self):
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as zf_path:
            with zipfile.ZipFile(zf_path.name, "w") as zf:
                zf.writestr("scenery/airport.xml", SAMPLE_MSFS_XML)
                zf.writestr("readme.txt", b"Not XML")
            try:
                parser = MSFSParser()
                doc = parser.parse(zf_path.name)
                assert doc.icao_code == "KSFO"
            finally:
                os.unlink(zf_path.name)

    def test_parse_zip_no_airport_raises(self):
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as zf_path:
            with zipfile.ZipFile(zf_path.name, "w") as zf:
                zf.writestr("readme.txt", b"No XML here")
            try:
                parser = MSFSParser()
                with pytest.raises(ParseError, match="No valid MSFS airport scenery"):
                    parser.parse(zf_path.name)
            finally:
                os.unlink(zf_path.name)

    def test_parse_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            xml_path = os.path.join(tmpdir, "airport.xml")
            with open(xml_path, "wb") as f:
                f.write(SAMPLE_MSFS_XML)

            parser = MSFSParser()
            doc = parser.parse(tmpdir)
            assert doc.icao_code == "KSFO"

    def test_parse_empty_directory_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            parser = MSFSParser()
            with pytest.raises(ParseError, match="No valid MSFS airport scenery"):
                parser.parse(tmpdir)

    def test_parse_nonexistent_file_raises(self):
        parser = MSFSParser()
        with pytest.raises(ParseError, match="File not found"):
            parser.parse("/nonexistent/file.xml")

    def test_parking_with_zero_coords_skipped(self):
        """Parking spots at (0,0) should be skipped."""
        xml = b"""\
<?xml version="1.0" encoding="utf-8"?>
<FSData>
  <Airport ident="TEST" lat="37.0" lon="-122.0">
    <TaxiwayParking index="0" lat="0" lon="0" type="GATE" name="GATE_A" number="1"/>
    <TaxiwayParking index="1" lat="37.01" lon="-122.01" type="GATE" name="GATE_A" number="2"/>
  </Airport>
</FSData>
"""
        parser = MSFSParser()
        doc = parser.parse(xml)
        assert len(doc.parking_spots) == 1


class TestMSFSValidation:
    """Tests for MSFS validation."""

    def test_validate_empty_document(self):
        parser = MSFSParser()
        doc = MSFSDocument()
        warnings = parser.validate(doc)
        assert any("No parking spots or runways" in w for w in warnings)

    def test_validate_no_gates(self):
        parser = MSFSParser()
        doc = MSFSDocument(
            parking_spots=[
                MSFSParkingSpot(index=0, lat=37.61, lon=-122.39, type=ParkingType.RAMP, name="RAMP_GA", number=1),
            ],
        )
        warnings = parser.validate(doc)
        assert any("No gate-type" in w for w in warnings)

    def test_validate_unreferenced_points(self):
        parser = MSFSParser()
        doc = MSFSDocument(
            taxi_points=[
                MSFSTaxiPoint(index=0, lat=37.61, lon=-122.39),
                MSFSTaxiPoint(index=1, lat=37.62, lon=-122.38),
                MSFSTaxiPoint(index=2, lat=37.63, lon=-122.37),  # Not referenced
            ],
            taxi_paths=[
                MSFSTaxiPath(start=0, end=1, name="A"),
            ],
        )
        warnings = parser.validate(doc)
        assert any("1 taxi points not referenced" in w for w in warnings)

    def test_validate_bad_path_refs(self):
        parser = MSFSParser()
        doc = MSFSDocument(
            taxi_points=[
                MSFSTaxiPoint(index=0, lat=37.61, lon=-122.39),
            ],
            taxi_paths=[
                MSFSTaxiPath(start=0, end=99, name="A"),  # 99 doesn't exist
            ],
        )
        warnings = parser.validate(doc)
        assert any("reference non-existent" in w for w in warnings)

    def test_validate_good_document(self):
        parser = MSFSParser()
        doc = parser.parse(SAMPLE_MSFS_XML)
        warnings = parser.validate(doc)
        # Sample has gates and all points referenced
        assert not any("No parking" in w for w in warnings)
        assert not any("No gate-type" in w for w in warnings)


class TestMSFSConverter:
    """Tests for MSFS to internal format converter."""

    def setup_method(self):
        self.converter = CoordinateConverter(
            reference_lat=37.6213,
            reference_lon=-122.379,
            reference_alt=4.0,
        )
        self.msfs_converter = MSFSConverter(self.converter)

    def test_convert_gates(self):
        parser = MSFSParser()
        doc = parser.parse(SAMPLE_MSFS_XML)
        config = self.msfs_converter.to_config(doc)

        # 4 parking spots total (2 gates, 1 ramp, 1 dock)
        assert len(config["gates"]) == 4  # all parking spots become gate entries
        gate_names = [g["ref"] for g in config["gates"]]
        assert "A1" in gate_names
        assert "A2" in gate_names

    def test_gate_has_geo_and_position(self):
        parser = MSFSParser()
        doc = parser.parse(SAMPLE_MSFS_XML)
        config = self.msfs_converter.to_config(doc)

        gate = next(g for g in config["gates"] if g["ref"] == "A1")
        assert "geo" in gate
        assert "position" in gate
        assert gate["geo"]["latitude"] == 37.6145
        assert gate["geo"]["longitude"] == -122.3955
        assert gate["heading"] == 270.0
        assert gate["airlineCodes"] == ["UAL", "AAL"]

    def test_convert_taxiways(self):
        parser = MSFSParser()
        doc = parser.parse(SAMPLE_MSFS_XML)
        config = self.msfs_converter.to_config(doc)

        taxiways = config["osmTaxiways"]
        assert len(taxiways) >= 1  # At least taxiway A
        names = [t["name"] for t in taxiways]
        assert "A" in names

    def test_taxiway_has_geo_points(self):
        parser = MSFSParser()
        doc = parser.parse(SAMPLE_MSFS_XML)
        config = self.msfs_converter.to_config(doc)

        twy_a = next(t for t in config["osmTaxiways"] if t["name"] == "A")
        assert "geoPoints" in twy_a
        assert len(twy_a["geoPoints"]) >= 2
        assert "latitude" in twy_a["geoPoints"][0]

    def test_convert_runway(self):
        parser = MSFSParser()
        doc = parser.parse(SAMPLE_MSFS_XML)
        config = self.msfs_converter.to_config(doc)

        runways = config["osmRunways"]
        assert len(runways) == 1
        rwy = runways[0]
        assert rwy["name"] == "28L/10R"
        assert rwy["width"] == 60
        assert len(rwy["geoPoints"]) == 2

    def test_convert_apron(self):
        parser = MSFSParser()
        doc = parser.parse(SAMPLE_MSFS_XML)
        config = self.msfs_converter.to_config(doc)

        aprons = config["osmAprons"]
        assert len(aprons) == 1
        assert len(aprons[0]["geoPolygon"]) == 4
        assert aprons[0]["surface"] == "CONCRETE"

    def test_config_has_source_and_icao(self):
        parser = MSFSParser()
        doc = parser.parse(SAMPLE_MSFS_XML)
        config = self.msfs_converter.to_config(doc)

        assert config["source"] == "MSFS"
        assert config["icaoCode"] == "KSFO"

    def test_config_has_center(self):
        parser = MSFSParser()
        doc = parser.parse(SAMPLE_MSFS_XML)
        config = self.msfs_converter.to_config(doc)

        assert "center" in config
        assert abs(config["center"]["latitude"] - 37.6213) < 0.001

    def test_to_gates_dict(self):
        parser = MSFSParser()
        doc = parser.parse(SAMPLE_MSFS_XML)
        gates_dict = self.msfs_converter.to_gates_dict(doc)

        assert "A1" in gates_dict
        assert "A2" in gates_dict
        assert gates_dict["A1"]["latitude"] == 37.6145
        assert gates_dict["A1"]["heading"] == 270.0

    def test_to_config_via_parser(self):
        """Test that parser.to_config delegates to converter."""
        parser = MSFSParser(self.converter)
        doc = parser.parse(SAMPLE_MSFS_XML)
        config = parser.to_config(doc)

        assert config["source"] == "MSFS"
        assert len(config["gates"]) > 0


class TestMergeMSFSConfig:
    """Tests for MSFS config merging."""

    def test_merge_gates_override(self):
        base = {"gates": [{"id": "old_gate"}], "sources": []}
        msfs = {"gates": [{"id": "A1"}, {"id": "A2"}]}

        result = merge_msfs_config(base, msfs)
        assert len(result["gates"]) == 2
        assert result["gates"][0]["id"] == "A1"

    def test_merge_taxiways_no_duplicates(self):
        base = {"osmTaxiways": [{"id": "TWY_A"}], "sources": []}
        msfs = {"osmTaxiways": [{"id": "TWY_A"}, {"id": "TWY_B"}]}

        result = merge_msfs_config(base, msfs)
        assert len(result["osmTaxiways"]) == 2

    def test_merge_tracks_source(self):
        base = {"sources": ["OSM"]}
        msfs = {"gates": [{"id": "A1"}]}

        result = merge_msfs_config(base, msfs)
        assert "MSFS" in result["sources"]
        assert "OSM" in result["sources"]

    def test_merge_preserves_base_fields(self):
        base = {"terminals": [{"id": "T1"}], "runways": [{"id": "28L"}], "sources": []}
        msfs = {"gates": [{"id": "A1"}]}

        result = merge_msfs_config(base, msfs)
        assert result["terminals"] == [{"id": "T1"}]
        assert result["runways"] == [{"id": "28L"}]

    def test_merge_aprons_appended(self):
        base = {"osmAprons": [{"id": "existing"}], "sources": []}
        msfs = {"osmAprons": [{"id": "new_apron"}]}

        result = merge_msfs_config(base, msfs)
        assert len(result["osmAprons"]) == 2

    def test_merge_runways_no_duplicates(self):
        base = {"osmRunways": [{"id": "RWY_28L/10R"}], "sources": []}
        msfs = {"osmRunways": [{"id": "RWY_28L/10R"}, {"id": "RWY_01L/19R"}]}

        result = merge_msfs_config(base, msfs)
        assert len(result["osmRunways"]) == 2


# ---------------------------------------------------------------------------
# BGL coordinate helpers
# ---------------------------------------------------------------------------

def _encode_bgl_lon(lon_deg: float) -> int:
    """Reverse of bgl_lon: encode longitude degrees to BGL raw int32."""
    return int((lon_deg + 180.0) / (360.0 / (3 * 0x10000000)))


def _encode_bgl_lat(lat_deg: float) -> int:
    """Reverse of bgl_lat: encode latitude degrees to BGL raw int32."""
    return int((90.0 - lat_deg) / (180.0 / (2 * 0x10000000)))


def _build_minimal_bgl(
    airport_lat: float = 46.2376,
    airport_lon: float = 6.1083,
    airport_name: str = "Test Airport",
    num_gates: int = 2,
    num_ramps: int = 1,
    include_runway: bool = True,
) -> bytes:
    """
    Build a minimal synthetic BGL binary for testing.

    Creates a valid BGL file with one airport section containing parking spots
    and optionally a runway.
    """
    # --- Build airport sub-records ---
    sub_records = bytearray()

    # NAME sub-record (type=0x0019)
    name_bytes = airport_name.encode("utf-8") + b"\x00"
    name_rec_size = 6 + len(name_bytes)  # type(2)+size(4)+name
    sub_records += struct.pack("<HI", 0x0019, name_rec_size)
    sub_records += name_bytes

    # TAXI_PARKING_MSFS sub-record (type=0x00E7)
    total_spots = num_gates + num_ramps
    parking_entries = bytearray()
    for i in range(total_spots):
        is_gate = i < num_gates
        type_idx = 9 if is_gate else 1  # GATE_MEDIUM or RAMP_GA_SMALL
        name_idx = 12 + i if is_gate else 1  # GA, GB, ... or P
        number = i + 1
        num_airlines = 1 if is_gate else 0

        flags = (name_idx & 0x3F) | ((type_idx & 0xF) << 8) | ((number & 0xFFF) << 12) | ((num_airlines & 0xFF) << 24)
        spot_lat = airport_lat + 0.001 * (i + 1)
        spot_lon = airport_lon + 0.001 * (i + 1)
        heading = 90.0 + i * 30.0
        radius = 25.0

        parking_entries += struct.pack("<I", flags)
        parking_entries += struct.pack("<f", radius)
        parking_entries += struct.pack("<f", heading)
        parking_entries += b"\x00" * 16  # teeOffset
        parking_entries += struct.pack("<i", _encode_bgl_lon(spot_lon))
        parking_entries += struct.pack("<i", _encode_bgl_lat(spot_lat))

        # Airline codes at offset 36 (right after lat), before suffix area
        if num_airlines > 0:
            parking_entries += b"SWR\x00"

        parking_entries += b"\x00" * 20  # suffix area

    parking_rec_size = 6 + 2 + len(parking_entries)  # type(2)+size(4)+count(2)+entries
    sub_records += struct.pack("<HI", 0x00E7, parking_rec_size)
    sub_records += struct.pack("<H", total_spots)
    sub_records += parking_entries

    # RUNWAY_MSFS sub-record (type=0x00CE) - optional
    if include_runway:
        rwy_lat = airport_lat
        rwy_lon = airport_lon + 0.01
        rwy_heading = 230.0
        rwy_length = 3000.0
        rwy_width = 45.0
        surface_idx = 0  # CONCRETE

        runway_data = bytearray()
        runway_data += struct.pack("<H", surface_idx)  # surface
        runway_data += struct.pack("<H", 0)  # flags
        runway_data += struct.pack("<H", 2)  # numEnds
        runway_data += b"\x00" * 8  # unknown
        runway_data += struct.pack("<i", _encode_bgl_lon(rwy_lon))
        runway_data += struct.pack("<i", _encode_bgl_lat(rwy_lat))
        runway_data += struct.pack("<I", 0)  # alt
        runway_data += struct.pack("<f", rwy_length)
        runway_data += struct.pack("<f", rwy_width)
        runway_data += struct.pack("<f", rwy_heading)

        runway_rec_size = 6 + len(runway_data)
        sub_records += struct.pack("<HI", 0x00CE, runway_rec_size)
        sub_records += runway_data

    # --- Build airport record ---
    airport_header = bytearray()
    airport_header += struct.pack("<H", 0x0056)  # rec_id
    airport_rec_size = 0x50 + len(sub_records)
    airport_header += struct.pack("<I", airport_rec_size)  # size

    # Counts (6 bytes)
    airport_header += struct.pack("<B", 1 if include_runway else 0)  # numRunways
    airport_header += b"\x00" * 5  # other counts

    # Coordinates
    airport_header += struct.pack("<i", _encode_bgl_lon(airport_lon))
    airport_header += struct.pack("<i", _encode_bgl_lat(airport_lat))

    # Remaining header: alt(4)+towerLon(4)+towerLat(4)+towerAlt(4)+magVar(4)+ident(4)+extra(36) = 60 bytes
    airport_header += b"\x00" * 60

    assert len(airport_header) == 0x50
    airport_record = bytes(airport_header) + bytes(sub_records)

    # --- Build BGL file ---
    # Header (56 bytes at offset 0x38)
    bgl_header_size = 0x38
    section_table_offset = bgl_header_size
    num_sections = 1

    # Subsection index entry (16 bytes)
    subsection_offset = section_table_offset + 20  # after 1 section entry
    airport_record_offset = subsection_offset + 16  # after 1 subsection entry

    # Section entry: type, unk, count, first_subsection_offset, total_size
    section_entry = struct.pack(
        "<IIIII",
        SECTION_AIRPORT,  # type
        0,  # unknown
        1,  # subsection count
        subsection_offset,  # first subsection offset
        len(airport_record),  # total size
    )

    # Subsection index entry: QMID, num_recs, rec_offset, rec_size
    subsection_entry = struct.pack(
        "<IIII",
        0,  # QMID
        1,  # num_recs
        airport_record_offset,  # rec_offset
        len(airport_record),  # rec_size
    )

    # BGL file header
    file_header = bytearray(bgl_header_size)
    struct.pack_into("<I", file_header, 0, BGL_MAGIC)  # magic
    struct.pack_into("<I", file_header, 4, bgl_header_size)  # header_size
    struct.pack_into("<I", file_header, 0x14, num_sections)  # num_sections

    return bytes(file_header) + section_entry + subsection_entry + airport_record


class TestBGLCoordinates:
    """Tests for BGL coordinate encoding/decoding."""

    def test_bgl_lon_zero(self):
        # lon = 0 when raw = (180/360) * 3 * 0x10000000
        raw = int(180.0 / (360.0 / (3 * 0x10000000)))
        assert abs(bgl_lon(raw)) < 0.001

    def test_bgl_lat_zero(self):
        # lat = 0 when raw = (90/180) * 2 * 0x10000000
        raw = int(90.0 / (180.0 / (2 * 0x10000000)))
        assert abs(bgl_lat(raw)) < 0.001

    def test_bgl_lon_roundtrip(self):
        for lon in [-122.379, 0.0, 6.1083, 139.6917, -73.7781]:
            raw = _encode_bgl_lon(lon)
            decoded = bgl_lon(raw)
            assert abs(decoded - lon) < 0.0001, f"lon {lon} roundtrip failed: {decoded}"

    def test_bgl_lat_roundtrip(self):
        for lat in [37.6213, 0.0, 46.2376, 35.5494, 51.4700]:
            raw = _encode_bgl_lat(lat)
            decoded = bgl_lat(raw)
            assert abs(decoded - lat) < 0.0001, f"lat {lat} roundtrip failed: {decoded}"

    def test_bgl_geneva_coords(self):
        """Verify encoding matches known Geneva airport coordinates."""
        raw_lon = _encode_bgl_lon(6.1083)
        raw_lat = _encode_bgl_lat(46.2376)
        assert abs(bgl_lon(raw_lon) - 6.1083) < 0.001
        assert abs(bgl_lat(raw_lat) - 46.2376) < 0.001


class TestBGLDetection:
    """Tests for BGL format detection."""

    def test_is_bgl_valid(self):
        data = struct.pack("<I", BGL_MAGIC) + b"\x00" * 100
        assert is_bgl(data)

    def test_is_bgl_invalid_magic(self):
        data = struct.pack("<I", 0xDEADBEEF) + b"\x00" * 100
        assert not is_bgl(data)

    def test_is_bgl_too_short(self):
        assert not is_bgl(b"\x01\x02")

    def test_is_bgl_empty(self):
        assert not is_bgl(b"")

    def test_is_bgl_xml(self):
        assert not is_bgl(b"<?xml version")


class TestExtractICAO:
    """Tests for ICAO code extraction from file paths."""

    def test_extract_from_zip_name(self):
        assert extract_icao_from_path("plasmastorm-lsgg-geneva-airport_9OP2u.zip") == "LSGG"

    def test_extract_from_path(self):
        assert extract_icao_from_path("/downloads/msfs-kjfk-addon.zip") == "KJFK"

    def test_extract_rjtt(self):
        assert extract_icao_from_path("airport-rjtt-tokyo-haneda.bgl") == "RJTT"

    def test_no_icao(self):
        assert extract_icao_from_path("random-scenery-pack.zip") == ""

    def test_extract_with_backslash(self):
        assert extract_icao_from_path("C:\\MSFS\\Addons\\lsgg-scenery\\airport.bgl") == "LSGG"


class TestBGLParser:
    """Tests for BGL binary parser."""

    def test_parse_synthetic_bgl(self):
        data = _build_minimal_bgl()
        parser = MSFSParser()
        doc = parser.parse(data)

        assert isinstance(doc, MSFSDocument)
        assert doc.airport_name == "Test Airport"
        assert abs(doc.lat - 46.2376) < 0.001
        assert abs(doc.lon - 6.1083) < 0.001

    def test_parse_bgl_parking_spots(self):
        data = _build_minimal_bgl(num_gates=3, num_ramps=2)
        parser = MSFSParser()
        doc = parser.parse(data)

        assert len(doc.parking_spots) == 5
        assert len(doc.gates) == 3
        assert len(doc.ramps) == 2

    def test_parse_bgl_gate_properties(self):
        data = _build_minimal_bgl(num_gates=1, num_ramps=0, include_runway=False)
        parser = MSFSParser()
        doc = parser.parse(data)

        assert len(doc.gates) == 1
        gate = doc.gates[0]
        assert gate.type == ParkingType.GATE
        assert gate.airline_codes == ["SWR"]
        assert gate.radius == 25.0

    def test_parse_bgl_runway(self):
        data = _build_minimal_bgl(include_runway=True)
        parser = MSFSParser()
        doc = parser.parse(data)

        assert len(doc.runways) == 1
        rwy = doc.runways[0]
        assert abs(rwy.length - 3000.0) < 1.0
        assert abs(rwy.width - 45.0) < 1.0
        assert abs(rwy.heading - 230.0) < 1.0
        assert rwy.surface == "CONCRETE"

    def test_parse_bgl_no_runway(self):
        data = _build_minimal_bgl(include_runway=False)
        parser = MSFSParser()
        doc = parser.parse(data)
        assert len(doc.runways) == 0

    def test_parse_bgl_runway_designator(self):
        data = _build_minimal_bgl(include_runway=True)
        parser = MSFSParser()
        doc = parser.parse(data)

        rwy = doc.runways[0]
        # heading 230 -> rwy_num = round(230/10) % 36 = 23
        assert "23" in rwy.designator
        assert "05" in rwy.designator

    def test_parse_bgl_from_file(self):
        data = _build_minimal_bgl()
        with tempfile.NamedTemporaryFile(suffix=".bgl", delete=False) as f:
            f.write(data)
            f.flush()
            try:
                parser = MSFSParser()
                doc = parser.parse(f.name)
                assert doc.airport_name == "Test Airport"
            finally:
                os.unlink(f.name)

    def test_parse_bgl_from_zip(self):
        bgl_data = _build_minimal_bgl()
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as zf_path:
            with zipfile.ZipFile(zf_path.name, "w") as zf:
                zf.writestr("scenery/airport.bgl", bgl_data)
            try:
                parser = MSFSParser()
                doc = parser.parse(zf_path.name)
                assert doc.airport_name == "Test Airport"
                assert len(doc.parking_spots) > 0
            finally:
                os.unlink(zf_path.name)

    def test_parse_bgl_icao_from_zip_name(self):
        bgl_data = _build_minimal_bgl()
        with tempfile.NamedTemporaryFile(
            suffix=".zip", prefix="addon-lsgg-", delete=False
        ) as zf_path:
            with zipfile.ZipFile(zf_path.name, "w") as zf:
                zf.writestr("scenery/airport.bgl", bgl_data)
            try:
                parser = MSFSParser()
                doc = parser.parse(zf_path.name)
                assert doc.icao_code == "LSGG"
            finally:
                os.unlink(zf_path.name)

    def test_parse_invalid_bgl_raises(self):
        # Valid magic but truncated
        data = struct.pack("<I", BGL_MAGIC) + b"\x00" * 10
        parser = MSFSParser()
        with pytest.raises(Exception):
            parser.parse(data)

    def test_bgl_coordinates_accuracy(self):
        """Verify BGL-decoded coordinates are within 100m of input."""
        lat, lon = 37.6213, -122.379
        data = _build_minimal_bgl(airport_lat=lat, airport_lon=lon, num_gates=1, num_ramps=0)
        parser = MSFSParser()
        doc = parser.parse(data)

        gate = doc.parking_spots[0]
        # Gate is at lat+0.001, lon+0.001
        expected_lat = lat + 0.001
        expected_lon = lon + 0.001
        assert abs(gate.lat - expected_lat) < 0.001
        assert abs(gate.lon - expected_lon) < 0.001

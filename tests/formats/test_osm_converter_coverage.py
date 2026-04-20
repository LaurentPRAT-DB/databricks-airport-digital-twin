"""
Tests to improve coverage of src/formats/osm/converter.py.

Covers:
- _convert_taxiway, _convert_apron, _convert_runway, _convert_hangar, _convert_helipad
- _convert_parking_position and parking position → gate promotion logic
- to_gates_dict (including gate without ref → skip)
- merge_osm_config with all key combinations
- to_config full integration with all element types
"""

import pytest

from src.formats.base import CoordinateConverter
from src.formats.osm.converter import OSMConverter, merge_osm_config
from src.formats.osm.models import OSMDocument, OSMNode, OSMTags, OSMWay, OSMWayNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _converter() -> CoordinateConverter:
    """Reference converter centred on a dummy airport (0,0)."""
    return CoordinateConverter(reference_lat=0.0, reference_lon=0.0)


def _make_way(way_id: int, aeroway: str, geometry: list[tuple[float, float]], **extra_tags) -> OSMWay:
    """Build an OSMWay with minimal geometry."""
    return OSMWay(
        id=way_id,
        tags=OSMTags(aeroway=aeroway, **extra_tags),
        nodes=list(range(len(geometry))),
        geometry=[OSMWayNode(lat=lat, lon=lon) for lat, lon in geometry],
    )


def _make_node(node_id: int, lat: float, lon: float, **tag_kwargs) -> OSMNode:
    """Build an OSMNode with given tags."""
    return OSMNode(id=node_id, lat=lat, lon=lon, tags=OSMTags(**tag_kwargs))


# A simple square polygon for ways that need geometry
SQUARE = [(1.0, 1.0), (1.0, 2.0), (2.0, 2.0), (2.0, 1.0), (1.0, 1.0)]
LINE = [(0.0, 0.0), (0.0, 1.0), (0.0, 2.0)]


# ---------------------------------------------------------------------------
# Individual converter method tests
# ---------------------------------------------------------------------------

class TestConvertTaxiway:
    def test_basic(self):
        conv = OSMConverter(_converter())
        way = _make_way(100, "taxiway", LINE, ref="A", surface="asphalt", width=25.0)
        result = conv._convert_taxiway(way)
        assert result is not None
        assert result["id"] == "A_100"
        assert result["osmId"] == 100
        assert result["name"] == "A"  # falls back to ref
        assert len(result["points"]) == 3
        assert len(result["geoPoints"]) == 3
        assert result["width"] == 25.0
        assert result["surface"] == "asphalt"
        assert result["color"] == OSMConverter.TAXIWAY_COLOR

    def test_no_ref(self):
        conv = OSMConverter(_converter())
        way = _make_way(101, "taxiway", LINE)
        result = conv._convert_taxiway(way)
        assert result["id"] == "TWY_101"

    def test_no_geometry_returns_none(self):
        conv = OSMConverter(_converter())
        way = OSMWay(id=102, tags=OSMTags(aeroway="taxiway"))
        assert conv._convert_taxiway(way) is None

    def test_default_width(self):
        conv = OSMConverter(_converter())
        way = _make_way(103, "taxiway", LINE)
        result = conv._convert_taxiway(way)
        assert result["width"] == 20.0


class TestConvertApron:
    def test_basic(self):
        conv = OSMConverter(_converter())
        way = _make_way(200, "apron", SQUARE, ref="RAMP-A", name="Main Apron", surface="concrete")
        result = conv._convert_apron(way)
        assert result is not None
        assert result["id"] == "RAMP-A_200"
        assert result["name"] == "Main Apron"
        assert result["surface"] == "concrete"
        assert result["osmId"] == 200
        assert "polygon" in result
        assert "geoPolygon" in result
        assert result["dimensions"]["width"] > 0
        assert result["dimensions"]["depth"] > 0
        assert result["color"] == OSMConverter.APRON_COLOR

    def test_no_ref(self):
        conv = OSMConverter(_converter())
        way = _make_way(201, "apron", SQUARE)
        result = conv._convert_apron(way)
        assert result["id"] == "APRON_201"

    def test_no_geometry_returns_none(self):
        conv = OSMConverter(_converter())
        way = OSMWay(id=202, tags=OSMTags(aeroway="apron"))
        assert conv._convert_apron(way) is None


class TestConvertRunway:
    def test_basic(self):
        conv = OSMConverter(_converter())
        way = _make_way(300, "runway", LINE, ref="09L/27R", name="Runway 09L/27R", surface="asphalt", width=60.0)
        result = conv._convert_runway(way)
        assert result is not None
        assert result["id"] == "09L/27R_300"
        assert result["ref"] == "09L/27R"
        assert result["name"] == "Runway 09L/27R"
        assert result["width"] == 60.0
        assert result["surface"] == "asphalt"
        assert result["color"] == OSMConverter.RUNWAY_COLOR
        assert len(result["points"]) == 3
        assert len(result["geoPoints"]) == 3

    def test_no_ref(self):
        conv = OSMConverter(_converter())
        way = _make_way(301, "runway", LINE)
        result = conv._convert_runway(way)
        assert result["id"] == "RWY_301"

    def test_default_width(self):
        conv = OSMConverter(_converter())
        way = _make_way(302, "runway", LINE)
        result = conv._convert_runway(way)
        assert result["width"] == 45.0

    def test_no_geometry_returns_none(self):
        conv = OSMConverter(_converter())
        way = OSMWay(id=303, tags=OSMTags(aeroway="runway"))
        assert conv._convert_runway(way) is None


class TestConvertHangar:
    def test_basic(self):
        conv = OSMConverter(_converter())
        way = _make_way(400, "hangar", SQUARE, name="Hangar B", operator="FBO Inc", height=18.0)
        result = conv._convert_hangar(way)
        assert result is not None
        assert result["id"] == "hangar_400"
        assert result["name"] == "Hangar B"
        assert result["type"] == "hangar"
        assert result["operator"] == "FBO Inc"
        assert result["dimensions"]["height"] == 18.0
        assert result["dimensions"]["width"] > 0
        assert result["dimensions"]["depth"] > 0
        assert result["color"] == OSMConverter.HANGAR_COLOR
        assert "polygon" in result
        assert "geoPolygon" in result

    def test_default_height(self):
        conv = OSMConverter(_converter())
        way = _make_way(401, "hangar", SQUARE)
        result = conv._convert_hangar(way)
        assert result["dimensions"]["height"] == 12.0

    def test_default_name(self):
        conv = OSMConverter(_converter())
        way = _make_way(402, "hangar", SQUARE)
        result = conv._convert_hangar(way)
        assert result["name"] == "Hangar 402"

    def test_no_geometry_returns_none(self):
        conv = OSMConverter(_converter())
        way = OSMWay(id=403, tags=OSMTags(aeroway="hangar"))
        assert conv._convert_hangar(way) is None


class TestConvertHelipad:
    def test_basic(self):
        conv = OSMConverter(_converter())
        node = _make_node(500, 1.5, 1.5, aeroway="helipad", ref="H1", name="Main Helipad", ele=5.0)
        result = conv._convert_helipad(node)
        assert result is not None
        assert result["id"] == "H1_500"
        assert result["osmId"] == 500
        assert result["name"] == "Main Helipad"
        assert result["ref"] == "H1"
        assert result["geo"]["latitude"] == 1.5
        assert result["geo"]["longitude"] == 1.5
        assert "position" in result

    def test_no_ref(self):
        conv = OSMConverter(_converter())
        node = _make_node(501, 1.0, 1.0, aeroway="helipad")
        result = conv._convert_helipad(node)
        assert result["id"] == "HELI_501"

    def test_no_elevation(self):
        conv = OSMConverter(_converter())
        node = _make_node(502, 1.0, 1.0, aeroway="helipad")
        result = conv._convert_helipad(node)
        # Should still produce a valid result (ele defaults to 0)
        assert result["position"]["y"] == 0.0


class TestConvertParkingPosition:
    def test_basic(self):
        conv = OSMConverter(_converter())
        node = _make_node(600, 1.0, 1.0, aeroway="parking_position", ref="S12", name="Stand 12", ele=3.0)
        result = conv._convert_parking_position(node)
        assert result is not None
        assert result["id"] == "S12_600"
        assert result["osmId"] == 600
        assert result["ref"] == "S12"
        assert result["name"] == "Stand 12"
        assert result["geo"]["latitude"] == 1.0
        assert result["geo"]["longitude"] == 1.0

    def test_no_ref(self):
        conv = OSMConverter(_converter())
        node = _make_node(601, 1.0, 1.0, aeroway="parking_position")
        result = conv._convert_parking_position(node)
        assert result["id"] == "PP_601"

    def test_no_elevation(self):
        conv = OSMConverter(_converter())
        node = _make_node(602, 0.5, 0.5, aeroway="parking_position")
        result = conv._convert_parking_position(node)
        assert result["position"]["y"] == 0.0


# ---------------------------------------------------------------------------
# Parking position → gate promotion (lines 114-134)
# ---------------------------------------------------------------------------

class TestParkingPositionGatePromotion:
    def _doc_with_parking(self, pp_ref: str | None, gate_refs: list[str] | None = None):
        """Build an OSMDocument with a parking position and optional gate nodes."""
        nodes = []
        if gate_refs:
            for i, ref in enumerate(gate_refs):
                nodes.append(_make_node(10 + i, 0.5, 0.5, aeroway="gate", ref=ref))
        # Parking position
        pp_tags = {"aeroway": "parking_position"}
        if pp_ref:
            pp_tags["ref"] = pp_ref
        nodes.append(_make_node(900, 1.0, 1.0, **pp_tags))
        return OSMDocument(nodes=nodes, ways=[])

    def test_parking_promoted_to_gate(self):
        doc = self._doc_with_parking("R5")
        conv = OSMConverter(_converter())
        config = conv.to_config(doc)
        gate_ids = [g["id"] for g in config["gates"]]
        assert "R5" in gate_ids
        # Verify remote stand flag
        promoted = [g for g in config["gates"] if g["id"] == "R5"][0]
        assert promoted["is_remote_stand"] is True
        assert promoted["terminal"] is None

    def test_parking_not_promoted_when_gate_exists(self):
        """Parking position with same ref as existing gate should NOT duplicate."""
        doc = self._doc_with_parking("A1", gate_refs=["A1"])
        conv = OSMConverter(_converter())
        config = conv.to_config(doc)
        a1_gates = [g for g in config["gates"] if g.get("ref") == "A1"]
        assert len(a1_gates) == 1  # No duplicate

    def test_parking_without_ref_uses_id_fallback(self):
        """Parking without ref uses its converted id as gate id."""
        doc = self._doc_with_parking(None)
        conv = OSMConverter(_converter())
        config = conv.to_config(doc)
        # The parking position has id=900 and no ref, so converted id is "PP_900"
        promoted_ids = [g["id"] for g in config["gates"] if g.get("is_remote_stand")]
        assert "PP_900" in promoted_ids


# ---------------------------------------------------------------------------
# to_gates_dict (line 421: gate without ref → skip)
# ---------------------------------------------------------------------------

class TestToGatesDict:
    def test_basic(self):
        doc = OSMDocument(
            nodes=[
                _make_node(10, 1.0, 2.0, aeroway="gate", ref="B3", terminal="T1", name="Gate B3"),
            ],
            ways=[],
        )
        conv = OSMConverter(_converter())
        gates_dict = conv.to_gates_dict(doc)
        assert "B3" in gates_dict
        assert gates_dict["B3"]["latitude"] == 1.0
        assert gates_dict["B3"]["longitude"] == 2.0
        assert gates_dict["B3"]["terminal"] == "T1"

    def test_gate_without_ref_skipped(self):
        """Gate node without aeroway=gate ref should be skipped (line 421)."""
        # A node that IS a gate but has no ref tag — gate_ref returns None
        doc = OSMDocument(
            nodes=[
                _make_node(11, 1.0, 2.0, aeroway="gate"),  # no ref
            ],
            ways=[],
        )
        conv = OSMConverter(_converter())
        gates_dict = conv.to_gates_dict(doc)
        assert len(gates_dict) == 0

    def test_multiple_gates(self):
        doc = OSMDocument(
            nodes=[
                _make_node(10, 1.0, 2.0, aeroway="gate", ref="A1"),
                _make_node(11, 1.1, 2.1, aeroway="gate", ref="A2"),
            ],
            ways=[],
        )
        conv = OSMConverter(_converter())
        gates_dict = conv.to_gates_dict(doc)
        assert len(gates_dict) == 2


# ---------------------------------------------------------------------------
# to_config full integration — exercises all element dispatch loops
# ---------------------------------------------------------------------------

class TestToConfigIntegration:
    def _full_doc(self) -> OSMDocument:
        """Create an OSMDocument containing every element type."""
        nodes = [
            _make_node(1, 0.001, 0.001, aeroway="gate", ref="G1"),
            _make_node(2, 0.002, 0.002, aeroway="helipad", ref="H1"),
            _make_node(3, 0.003, 0.003, aeroway="parking_position", ref="S1"),
        ]
        ways = [
            _make_way(10, "terminal", SQUARE, name="Terminal 1"),
            _make_way(11, "taxiway", LINE, ref="A"),
            _make_way(12, "apron", SQUARE, ref="RAMP"),
            _make_way(13, "runway", LINE, ref="09L/27R"),
            _make_way(14, "hangar", SQUARE, name="Hangar X"),
        ]
        return OSMDocument(
            icao_code="KXYZ",
            iata_code="XYZ",
            airport_name="Test Airport",
            airport_operator="Test Ops",
            nodes=nodes,
            ways=ways,
        )

    def test_all_keys_present(self):
        doc = self._full_doc()
        conv = OSMConverter(_converter())
        config = conv.to_config(doc)
        assert config["source"] == "OSM"
        assert config["icaoCode"] == "KXYZ"
        assert len(config["gates"]) >= 1  # G1 + S1 promoted
        assert len(config["terminals"]) == 1
        assert len(config["osmTaxiways"]) == 1
        assert len(config["osmAprons"]) == 1
        assert len(config["osmRunways"]) == 1
        assert len(config["osmHangars"]) == 1
        assert len(config["osmHelipads"]) == 1
        assert len(config["osmParkingPositions"]) == 1

    def test_terminal_with_no_geometry_skipped(self):
        """Terminal way without geometry should be skipped (line 196)."""
        doc = OSMDocument(
            nodes=[],
            ways=[OSMWay(id=10, tags=OSMTags(aeroway="terminal"))],
        )
        conv = OSMConverter(_converter())
        config = conv.to_config(doc)
        assert config["terminals"] == []


# ---------------------------------------------------------------------------
# merge_osm_config (lines 473-493)
# ---------------------------------------------------------------------------

class TestMergeOsmConfig:
    def test_gates_merged(self):
        base = {"gates": [{"id": "old"}]}
        osm = {"gates": [{"id": "new"}]}
        result = merge_osm_config(base, osm)
        assert result["gates"] == [{"id": "new"}]

    def test_terminals_merged_and_added_to_buildings(self):
        base = {"buildings": [{"id": "bldg_1"}]}
        osm = {"terminals": [{"id": "terminal_99", "name": "T1"}]}
        result = merge_osm_config(base, osm)
        assert result["terminals"] == osm["terminals"]
        assert any(b["id"] == "terminal_99" for b in result["buildings"])
        # Original building still present
        assert any(b["id"] == "bldg_1" for b in result["buildings"])

    def test_terminals_no_duplicate_buildings(self):
        base = {"buildings": [{"id": "terminal_99"}]}
        osm = {"terminals": [{"id": "terminal_99", "name": "T1"}]}
        result = merge_osm_config(base, osm)
        count = sum(1 for b in result["buildings"] if b["id"] == "terminal_99")
        assert count == 1

    def test_taxiways_merged(self):
        osm = {"osmTaxiways": [{"id": "twy_1"}]}
        result = merge_osm_config({}, osm)
        assert result["osmTaxiways"] == [{"id": "twy_1"}]

    def test_aprons_merged(self):
        osm = {"osmAprons": [{"id": "apron_1"}]}
        result = merge_osm_config({}, osm)
        assert result["osmAprons"] == [{"id": "apron_1"}]

    def test_runways_merged(self):
        osm = {"osmRunways": [{"id": "rwy_1"}]}
        result = merge_osm_config({}, osm)
        assert result["osmRunways"] == [{"id": "rwy_1"}]

    def test_hangars_merged(self):
        osm = {"osmHangars": [{"id": "hangar_1"}]}
        result = merge_osm_config({}, osm)
        assert result["osmHangars"] == [{"id": "hangar_1"}]

    def test_helipads_merged(self):
        osm = {"osmHelipads": [{"id": "heli_1"}]}
        result = merge_osm_config({}, osm)
        assert result["osmHelipads"] == [{"id": "heli_1"}]

    def test_parking_positions_merged(self):
        osm = {"osmParkingPositions": [{"id": "pp_1"}]}
        result = merge_osm_config({}, osm)
        assert result["osmParkingPositions"] == [{"id": "pp_1"}]

    def test_source_tracking(self):
        result = merge_osm_config({}, {})
        assert "OSM" in result["sources"]

    def test_source_not_duplicated(self):
        result = merge_osm_config({"sources": ["OSM"]}, {})
        assert result["sources"].count("OSM") == 1

    def test_empty_osm_keys_not_overwritten(self):
        """If osm_config has empty lists they should NOT overwrite base."""
        base = {"gates": [{"id": "keep"}]}
        osm = {"gates": []}  # falsy
        result = merge_osm_config(base, osm)
        assert result["gates"] == [{"id": "keep"}]

    def test_all_keys_at_once(self):
        osm = {
            "gates": [{"id": "g"}],
            "terminals": [{"id": "t"}],
            "osmTaxiways": [{"id": "tw"}],
            "osmAprons": [{"id": "ap"}],
            "osmRunways": [{"id": "rw"}],
            "osmHangars": [{"id": "hg"}],
            "osmHelipads": [{"id": "hp"}],
            "osmParkingPositions": [{"id": "pp"}],
        }
        result = merge_osm_config({}, osm)
        assert result["gates"] == [{"id": "g"}]
        assert result["terminals"] == [{"id": "t"}]
        assert result["osmTaxiways"] == [{"id": "tw"}]
        assert result["osmAprons"] == [{"id": "ap"}]
        assert result["osmRunways"] == [{"id": "rw"}]
        assert result["osmHangars"] == [{"id": "hg"}]
        assert result["osmHelipads"] == [{"id": "hp"}]
        assert result["osmParkingPositions"] == [{"id": "pp"}]

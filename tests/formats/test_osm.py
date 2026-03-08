"""
Unit tests for OpenStreetMap airport data parser.

Tests the OSM Overpass API client, models, and converter.
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from src.formats.base import CoordinateConverter, ParseError
from src.formats.osm.models import (
    OSMDocument,
    OSMNode,
    OSMWay,
    OSMWayNode,
    OSMTags,
)
from src.formats.osm.parser import OSMParser
from src.formats.osm.converter import OSMConverter, merge_osm_config


# Sample Overpass API response for testing
SAMPLE_OVERPASS_RESPONSE = {
    "version": 0.6,
    "generator": "Overpass API 0.7.61",
    "elements": [
        {
            "type": "node",
            "id": 123456789,
            "lat": 37.6145,
            "lon": -122.3955,
            "tags": {
                "aeroway": "gate",
                "ref": "G91",
                "terminal": "International Terminal G",
            },
        },
        {
            "type": "node",
            "id": 123456790,
            "lat": 37.6140,
            "lon": -122.3945,
            "tags": {
                "aeroway": "gate",
                "ref": "G92",
                "terminal": "International Terminal G",
            },
        },
        {
            "type": "way",
            "id": 234567890,
            "tags": {
                "aeroway": "terminal",
                "name": "International Terminal G",
                "building": "terminal",
            },
            "nodes": [1, 2, 3, 4, 1],
            "geometry": [
                {"lat": 37.6150, "lon": -122.3970},
                {"lat": 37.6150, "lon": -122.3940},
                {"lat": 37.6130, "lon": -122.3940},
                {"lat": 37.6130, "lon": -122.3970},
                {"lat": 37.6150, "lon": -122.3970},
            ],
        },
    ],
}


class TestOSMModels:
    """Tests for OSM Pydantic models."""

    def test_osm_node_creation(self):
        """Test creating an OSM node."""
        node = OSMNode(
            id=123456789,
            lat=37.6145,
            lon=-122.3955,
            tags=OSMTags(aeroway="gate", ref="G91"),
        )

        assert node.id == 123456789
        assert node.lat == 37.6145
        assert node.lon == -122.3955
        assert node.is_gate
        assert node.gate_ref == "G91"

    def test_osm_node_not_gate(self):
        """Test non-gate node."""
        node = OSMNode(
            id=123456789,
            lat=37.6145,
            lon=-122.3955,
            tags=OSMTags(aeroway="windsock"),
        )

        assert not node.is_gate
        assert node.gate_ref is None

    def test_osm_way_terminal(self):
        """Test terminal way detection."""
        way = OSMWay(
            id=234567890,
            tags=OSMTags(aeroway="terminal", name="Terminal 1"),
            geometry=[
                OSMWayNode(lat=37.615, lon=-122.397),
                OSMWayNode(lat=37.615, lon=-122.394),
                OSMWayNode(lat=37.613, lon=-122.394),
            ],
        )

        assert way.is_terminal
        assert not way.is_taxiway
        assert len(way.points) == 3

    def test_osm_way_center_calculation(self):
        """Test way centroid calculation."""
        way = OSMWay(
            id=234567890,
            geometry=[
                OSMWayNode(lat=37.615, lon=-122.397),
                OSMWayNode(lat=37.615, lon=-122.394),
                OSMWayNode(lat=37.613, lon=-122.394),
                OSMWayNode(lat=37.613, lon=-122.397),
            ],
        )

        center_lat, center_lon = way.center
        assert abs(center_lat - 37.614) < 0.001
        assert abs(center_lon - (-122.3955)) < 0.001

    def test_osm_document_gates_filter(self):
        """Test filtering gates from document."""
        doc = OSMDocument(
            nodes=[
                OSMNode(id=1, lat=37.61, lon=-122.39, tags=OSMTags(aeroway="gate", ref="G1")),
                OSMNode(id=2, lat=37.62, lon=-122.38, tags=OSMTags(aeroway="windsock")),
                OSMNode(id=3, lat=37.63, lon=-122.37, tags=OSMTags(aeroway="gate", ref="G2")),
            ],
        )

        gates = doc.gates
        assert len(gates) == 2
        assert gates[0].gate_ref == "G1"
        assert gates[1].gate_ref == "G2"


class TestOSMParser:
    """Tests for OSM Overpass API parser."""

    def test_build_query_default(self):
        """Test default Overpass query building."""
        parser = OSMParser()
        query = parser.build_query("KSFO")

        assert 'area["icao"="KSFO"]' in query
        assert 'node["aeroway"="gate"]' in query
        assert 'way["aeroway"="terminal"]' in query

    def test_build_query_with_options(self):
        """Test query with all options enabled."""
        parser = OSMParser()
        query = parser.build_query(
            "KSFO",
            include_gates=True,
            include_terminals=True,
            include_taxiways=True,
            include_aprons=True,
        )

        assert 'node["aeroway"="gate"]' in query
        assert 'way["aeroway"="terminal"]' in query
        assert 'way["aeroway"="taxiway"]' in query
        assert 'way["aeroway"="apron"]' in query

    def test_build_query_gates_only(self):
        """Test query with only gates."""
        parser = OSMParser()
        query = parser.build_query(
            "KSFO",
            include_gates=True,
            include_terminals=False,
        )

        assert 'node["aeroway"="gate"]' in query
        assert 'way["aeroway"="terminal"]' not in query

    def test_parse_response(self):
        """Test parsing Overpass API response."""
        parser = OSMParser()
        doc = parser._parse_response(SAMPLE_OVERPASS_RESPONSE)

        assert isinstance(doc, OSMDocument)
        assert len(doc.nodes) == 2
        assert len(doc.ways) == 1

        # Check gate parsing
        gate = doc.nodes[0]
        assert gate.gate_ref == "G91"
        assert gate.terminal_name == "International Terminal G"

        # Check terminal parsing
        terminal = doc.ways[0]
        assert terminal.is_terminal
        assert terminal.tags.name == "International Terminal G"
        assert len(terminal.geometry) == 5

    def test_validate_empty_document(self):
        """Test validation of empty document."""
        parser = OSMParser()
        doc = OSMDocument()

        warnings = parser.validate(doc)
        assert "No OSM elements found" in warnings[0]

    def test_validate_gates_without_refs(self):
        """Test validation warns about gates without refs."""
        parser = OSMParser()
        doc = OSMDocument(
            nodes=[
                OSMNode(id=1, lat=37.61, lon=-122.39, tags=OSMTags(aeroway="gate")),
                OSMNode(id=2, lat=37.62, lon=-122.38, tags=OSMTags(aeroway="gate", ref="G1")),
            ],
        )

        warnings = parser.validate(doc)
        assert any("gates missing ref" in w for w in warnings)

    @patch("httpx.Client")
    def test_fetch_from_api_success(self, mock_client_class):
        """Test successful API fetch."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_OVERPASS_RESPONSE
        mock_response.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_class.return_value = mock_client

        parser = OSMParser()
        data = parser.fetch_from_api("KSFO")

        assert data == SAMPLE_OVERPASS_RESPONSE
        mock_client.post.assert_called_once()

    @patch("httpx.Client")
    def test_fetch_from_api_timeout(self, mock_client_class):
        """Test API timeout handling."""
        import httpx

        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.TimeoutException("Timeout")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_class.return_value = mock_client

        parser = OSMParser()

        with pytest.raises(ParseError, match="Failed to fetch OSM data"):
            parser.fetch_from_api("KSFO")


class TestOSMConverter:
    """Tests for OSM to internal format converter."""

    def setup_method(self):
        """Set up converter for each test."""
        self.converter = CoordinateConverter(
            reference_lat=37.6213,
            reference_lon=-122.379,
            reference_alt=4.0,
        )
        self.osm_converter = OSMConverter(self.converter)

    def test_convert_gate(self):
        """Test gate conversion to internal format."""
        doc = OSMDocument(
            nodes=[
                OSMNode(
                    id=123456789,
                    lat=37.6145,
                    lon=-122.3955,
                    tags=OSMTags(aeroway="gate", ref="G91", terminal="ITG"),
                ),
            ],
        )

        config = self.osm_converter.to_config(doc)

        assert len(config["gates"]) == 1
        gate = config["gates"][0]
        assert gate["ref"] == "G91"
        assert gate["terminal"] == "ITG"
        assert "position" in gate
        assert "geo" in gate
        assert gate["geo"]["latitude"] == 37.6145

    def test_convert_terminal(self):
        """Test terminal conversion to internal format."""
        doc = OSMDocument(
            ways=[
                OSMWay(
                    id=234567890,
                    tags=OSMTags(aeroway="terminal", name="Terminal G"),
                    geometry=[
                        OSMWayNode(lat=37.615, lon=-122.397),
                        OSMWayNode(lat=37.615, lon=-122.394),
                        OSMWayNode(lat=37.613, lon=-122.394),
                        OSMWayNode(lat=37.613, lon=-122.397),
                        OSMWayNode(lat=37.615, lon=-122.397),
                    ],
                ),
            ],
        )

        config = self.osm_converter.to_config(doc)

        assert len(config["terminals"]) == 1
        terminal = config["terminals"][0]
        assert terminal["name"] == "Terminal G"
        assert terminal["type"] == "terminal"
        assert "position" in terminal
        assert "dimensions" in terminal
        assert "polygon" in terminal

    def test_convert_to_gates_dict(self):
        """Test conversion to GATES dict format."""
        doc = OSMDocument(
            nodes=[
                OSMNode(id=1, lat=37.6145, lon=-122.3955, tags=OSMTags(aeroway="gate", ref="G91")),
                OSMNode(id=2, lat=37.6140, lon=-122.3945, tags=OSMTags(aeroway="gate", ref="G92")),
            ],
        )

        gates_dict = self.osm_converter.to_gates_dict(doc)

        assert "G91" in gates_dict
        assert "G92" in gates_dict
        assert gates_dict["G91"]["latitude"] == 37.6145
        assert gates_dict["G92"]["longitude"] == -122.3945


class TestMergeOSMConfig:
    """Tests for OSM config merging."""

    def test_merge_adds_gates(self):
        """Test that merge adds gates to config."""
        base = {"runways": [{"id": "28L"}], "buildings": []}
        osm = {"gates": [{"id": "G1"}], "terminals": []}

        result = merge_osm_config(base, osm)

        assert result["gates"] == [{"id": "G1"}]
        assert result["runways"] == [{"id": "28L"}]

    def test_merge_adds_terminals_to_buildings(self):
        """Test that terminals are merged into buildings."""
        base = {"buildings": [{"id": "existing"}]}
        osm = {"terminals": [{"id": "new_terminal"}]}

        result = merge_osm_config(base, osm)

        assert len(result["buildings"]) == 2
        assert result["buildings"][0]["id"] == "existing"
        assert result["buildings"][1]["id"] == "new_terminal"

    def test_merge_no_duplicate_buildings(self):
        """Test that duplicate buildings are not added."""
        base = {"buildings": [{"id": "terminal_123"}]}
        osm = {"terminals": [{"id": "terminal_123"}, {"id": "terminal_456"}]}

        result = merge_osm_config(base, osm)

        assert len(result["buildings"]) == 2  # Original + one new

    def test_merge_tracks_source(self):
        """Test that OSM source is tracked."""
        base = {"sources": ["AIXM"]}
        osm = {"gates": []}

        result = merge_osm_config(base, osm)

        assert "OSM" in result["sources"]
        assert "AIXM" in result["sources"]

"""Tests for airport persistence module."""

import json
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from src.persistence.airport_tables import (
    DEFAULT_CATALOG,
    DEFAULT_SCHEMA,
    ALL_TABLES,
    AIRPORT_METADATA_DDL,
    GATES_DDL,
    TERMINALS_DDL,
    TAXIWAYS_DDL,
    APRONS_DDL,
    BUILDINGS_DDL,
    HANGARS_DDL,
    HELIPADS_DDL,
    PARKING_POSITIONS_DDL,
)
from src.persistence.airport_repository import AirportRepository


class TestAirportTables:
    """Tests for table schema definitions."""

    def test_default_catalog_and_schema(self):
        """Verify default catalog and schema values."""
        assert DEFAULT_CATALOG == "serverless_stable_3n0ihb_catalog"
        assert DEFAULT_SCHEMA == "airport_digital_twin"

    def test_all_tables_defined(self):
        """Verify all expected tables are defined."""
        table_names = [name for name, _ in ALL_TABLES]
        assert "airport_metadata" in table_names
        assert "gates" in table_names
        assert "terminals" in table_names
        assert "runways" in table_names
        assert "taxiways" in table_names
        assert "aprons" in table_names
        assert "buildings" in table_names
        assert "hangars" in table_names
        assert "helipads" in table_names
        assert "parking_positions" in table_names
        assert "osm_runways" in table_names
        assert len(ALL_TABLES) == 15

    def test_metadata_ddl_has_required_columns(self):
        """Verify airport_metadata DDL has required columns."""
        assert "icao_code STRING NOT NULL" in AIRPORT_METADATA_DDL
        assert "iata_code STRING" in AIRPORT_METADATA_DDL
        assert "name STRING" in AIRPORT_METADATA_DDL
        assert "data_sources ARRAY<STRING>" in AIRPORT_METADATA_DDL
        assert "delta.enableChangeDataFeed" in AIRPORT_METADATA_DDL

    def test_gates_ddl_has_osm_properties(self):
        """Verify gates DDL includes all OSM properties."""
        assert "ref STRING NOT NULL" in GATES_DDL
        assert "terminal STRING" in GATES_DDL
        assert "level STRING" in GATES_DDL
        assert "operator STRING" in GATES_DDL
        assert "elevation DOUBLE" in GATES_DDL
        assert "osm_id BIGINT" in GATES_DDL


class TestAirportRepository:
    """Tests for AirportRepository."""

    @pytest.fixture
    def mock_client(self):
        """Create mock workspace client."""
        client = MagicMock()
        return client

    @pytest.fixture
    def repository(self, mock_client):
        """Create repository with mock client."""
        repo = AirportRepository(
            client=mock_client,
            warehouse_id="test-warehouse",
        )
        repo._tables_initialized = True  # Skip table creation
        return repo

    def test_table_name_generation(self, repository):
        """Test fully qualified table name generation."""
        table = repository._table("gates")
        assert table == f"{DEFAULT_CATALOG}.{DEFAULT_SCHEMA}.gates"

    def test_sql_str_helper(self):
        """Test SQL string literal helper."""
        assert AirportRepository._sql_str(None) == "NULL"
        assert AirportRepository._sql_str("test") == "'test'"
        assert AirportRepository._sql_str("O'Hare") == "'O''Hare'"

    def test_save_gates_empty_list(self, repository):
        """Test saving empty gates list does nothing."""
        repository._execute = MagicMock()
        repository._save_gates("KSFO", [], "2026-01-01T00:00:00")
        repository._execute.assert_not_called()

    def test_list_airports_returns_empty(self, repository):
        """Test list_airports when no airports exist."""
        repository._execute = MagicMock(return_value=None)
        result = repository.list_airports()
        assert result == []

    def test_airport_exists_false(self, repository):
        """Test airport_exists returns False when not found."""
        repository._execute = MagicMock(return_value=None)
        assert repository.airport_exists("XXXX") is False

    def test_airport_exists_true(self, repository):
        """Test airport_exists returns True when found."""
        repository._execute = MagicMock(return_value=[{"1": 1}])
        assert repository.airport_exists("KSFO") is True


class TestAirportRepositoryIntegration:
    """Integration tests for config round-trip (requires mocking)."""

    @pytest.fixture
    def sample_config(self):
        """Sample airport configuration."""
        return {
            "source": "OSM",
            "icaoCode": "KSFO",
            "iataCode": "SFO",
            "airportName": "San Francisco International Airport",
            "airportOperator": "City and County of San Francisco",
            "sources": ["OSM", "FAA"],
            "gates": [
                {
                    "id": "A1",
                    "ref": "A1",
                    "name": "Gate A1",
                    "terminal": "International",
                    "level": "1",
                    "operator": "United Airlines",
                    "osmId": 12345,
                    "elevation": 4.0,
                    "position": {"x": 100.0, "y": 0.0, "z": 50.0},
                    "geo": {"latitude": 37.6155, "longitude": -122.3900},
                }
            ],
            "terminals": [
                {
                    "id": "terminal_1",
                    "osmId": 67890,
                    "name": "International Terminal",
                    "type": "terminal",
                    "operator": "SFO",
                    "level": "3",
                    "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                    "dimensions": {"width": 200.0, "height": 15.0, "depth": 100.0},
                    "polygon": [{"x": 0, "y": 0, "z": 0}],
                    "geoPolygon": [{"latitude": 37.615, "longitude": -122.39}],
                    "geo": {"latitude": 37.615, "longitude": -122.39},
                }
            ],
            "runways": [
                {
                    "id": "28L/10R",
                    "designator": "28L/10R",
                    "designatorLow": "10R",
                    "designatorHigh": "28L",
                    "lengthFt": 11870,
                    "widthFt": 200,
                    "surface": "Asphalt",
                    "heading": 280,
                    "source": "FAA",
                }
            ],
            "osmTaxiways": [
                {
                    "id": "TWY_A",
                    "ref": "A",
                    "name": "Taxiway Alpha",
                    "width": 23.0,
                    "surface": "concrete",
                    "osmId": 11111,
                    "points": [{"x": 0, "y": 0, "z": 0}],
                    "geoPoints": [{"latitude": 37.62, "longitude": -122.38}],
                }
            ],
            "osmAprons": [
                {
                    "id": "APRON_1",
                    "ref": "Main Apron",
                    "name": "Main Apron",
                    "surface": "asphalt",
                    "osmId": 22222,
                    "position": {"x": 0, "y": 0, "z": 0},
                    "dimensions": {"width": 500, "depth": 300},
                    "polygon": [],
                    "geoPolygon": [],
                    "geo": {"latitude": 37.615, "longitude": -122.39},
                }
            ],
            "buildings": [
                {
                    "id": "building_1",
                    "osmId": 33333,
                    "name": "Control Tower",
                    "type": "control_tower",
                    "source": "OSM",
                    "position": {"x": 0, "y": 0, "z": 0},
                    "dimensions": {"width": 20, "height": 60, "depth": 20},
                    "polygon": [],
                    "geoPolygon": [],
                    "geo": {"latitude": 37.618, "longitude": -122.385},
                }
            ],
        }

    def test_sample_config_structure(self, sample_config):
        """Verify sample config has all required fields."""
        assert sample_config["icaoCode"] == "KSFO"
        assert len(sample_config["gates"]) == 1
        assert sample_config["gates"][0]["level"] == "1"
        assert sample_config["gates"][0]["operator"] == "United Airlines"
        assert len(sample_config["terminals"]) == 1
        assert len(sample_config["runways"]) == 1
        assert len(sample_config["osmTaxiways"]) == 1
        assert len(sample_config["osmAprons"]) == 1
        assert len(sample_config["buildings"]) == 1


class TestLoadOperations:
    """Tests for load operations."""

    @pytest.fixture
    def repository(self):
        """Create repository with mock."""
        repo = AirportRepository(
            client=MagicMock(),
            warehouse_id="test",
        )
        repo._tables_initialized = True
        return repo

    def test_load_gates_empty(self, repository):
        """Test loading gates when none exist."""
        repository._execute = MagicMock(return_value=None)
        result = repository._load_gates("KSFO")
        assert result == []

    def test_load_gates_with_data(self, repository):
        """Test loading gates with data."""
        repository._execute = MagicMock(return_value=[
            {
                "ref": "A1",
                "osm_id": 12345,
                "name": "Gate A1",
                "terminal": "International",
                "level": "1",
                "operator": "United",
                "elevation": 4.0,
                "latitude": 37.6155,
                "longitude": -122.39,
                "position_x": 100.0,
                "position_y": 0.0,
                "position_z": 50.0,
            }
        ])

        result = repository._load_gates("KSFO")
        assert len(result) == 1
        assert result[0]["ref"] == "A1"
        assert result[0]["level"] == "1"
        assert result[0]["operator"] == "United"
        assert result[0]["geo"]["latitude"] == 37.6155

    def test_load_airport_config_not_found(self, repository):
        """Test loading config for non-existent airport."""
        repository._execute = MagicMock(return_value=None)
        result = repository.load_airport_config("XXXX")
        assert result is None

    def test_load_terminals_parses_json(self, repository):
        """Test that polygon JSON is parsed correctly."""
        repository._execute = MagicMock(return_value=[
            {
                "terminal_id": "KSFO_123",
                "osm_id": 123,
                "name": "Terminal 1",
                "terminal_type": "terminal",
                "operator": None,
                "level": None,
                "height": 15.0,
                "center_lat": 37.615,
                "center_lon": -122.39,
                "position_x": 0,
                "position_y": 0,
                "position_z": 0,
                "width": 200,
                "depth": 100,
                "polygon_json": '[{"x":0,"y":0,"z":0}]',
                "geo_polygon_json": '[{"latitude":37.615,"longitude":-122.39}]',
            }
        ])

        result = repository._load_terminals("KSFO")
        assert len(result) == 1
        assert result[0]["polygon"] == [{"x": 0, "y": 0, "z": 0}]
        assert result[0]["geoPolygon"] == [{"latitude": 37.615, "longitude": -122.39}]

    def test_load_terminals_with_color(self, repository):
        """Test that color is loaded from terminals."""
        repository._execute = MagicMock(return_value=[
            {
                "terminal_id": "KSFO_123",
                "osm_id": 123,
                "name": "Terminal 1",
                "terminal_type": "terminal",
                "operator": None,
                "level": None,
                "height": 15.0,
                "center_lat": 37.615,
                "center_lon": -122.39,
                "position_x": 0,
                "position_y": 0,
                "position_z": 0,
                "width": 200,
                "depth": 100,
                "polygon_json": "[]",
                "geo_polygon_json": "[]",
                "color": 0x444444,
            }
        ])

        result = repository._load_terminals("KSFO")
        assert len(result) == 1
        assert result[0]["color"] == 0x444444

    def test_load_hangars_empty(self, repository):
        """Test loading hangars when none exist."""
        repository._execute = MagicMock(return_value=None)
        result = repository._load_hangars("KSFO")
        assert result == []

    def test_load_hangars_with_data(self, repository):
        """Test loading hangars with data."""
        repository._execute = MagicMock(return_value=[
            {
                "hangar_id": "KSFO_hangar_1",
                "osm_id": 44444,
                "name": "United Hangar",
                "operator": "United Airlines",
                "height": 12.0,
                "center_lat": 37.617,
                "center_lon": -122.388,
                "position_x": 50.0,
                "position_y": 0.0,
                "position_z": 30.0,
                "width": 80.0,
                "depth": 60.0,
                "polygon_json": "[]",
                "geo_polygon_json": "[]",
                "color": 0x777777,
            }
        ])

        result = repository._load_hangars("KSFO")
        assert len(result) == 1
        assert result[0]["name"] == "United Hangar"
        assert result[0]["type"] == "hangar"
        assert result[0]["color"] == 0x777777

    def test_load_helipads_with_data(self, repository):
        """Test loading helipads with data."""
        repository._execute = MagicMock(return_value=[
            {
                "helipad_id": "KSFO_H1",
                "osm_id": 55555,
                "ref": "H1",
                "name": "Helipad 1",
                "latitude": 37.616,
                "longitude": -122.387,
                "elevation": 4.0,
                "position_x": 20.0,
                "position_y": 0.0,
                "position_z": 10.0,
            }
        ])

        result = repository._load_helipads("KSFO")
        assert len(result) == 1
        assert result[0]["ref"] == "H1"
        assert result[0]["geo"]["latitude"] == 37.616

    def test_load_parking_positions_with_data(self, repository):
        """Test loading parking positions with data."""
        repository._execute = MagicMock(return_value=[
            {
                "parking_position_id": "KSFO_PP1",
                "osm_id": 66666,
                "ref": "PP1",
                "name": "Position 1",
                "latitude": 37.615,
                "longitude": -122.386,
                "elevation": None,
                "position_x": 10.0,
                "position_y": 0.0,
                "position_z": 5.0,
            }
        ])

        result = repository._load_parking_positions("KSFO")
        assert len(result) == 1
        assert result[0]["ref"] == "PP1"
        assert result[0]["geo"]["longitude"] == -122.386

    def test_save_hangars_empty(self, repository):
        """Test saving empty hangars list does nothing."""
        repository._execute = MagicMock()
        repository._save_hangars("KSFO", [], "2026-01-01T00:00:00")
        repository._execute.assert_not_called()

    def test_save_helipads_empty(self, repository):
        """Test saving empty helipads list does nothing."""
        repository._execute = MagicMock()
        repository._save_helipads("KSFO", [], "2026-01-01T00:00:00")
        repository._execute.assert_not_called()

    def test_save_parking_positions_empty(self, repository):
        """Test saving empty parking positions list does nothing."""
        repository._execute = MagicMock()
        repository._save_parking_positions("KSFO", [], "2026-01-01T00:00:00")
        repository._execute.assert_not_called()


class TestColorRoundTrip:
    """Tests for color field persistence."""

    @pytest.fixture
    def repository(self):
        """Create repository with mock."""
        repo = AirportRepository(
            client=MagicMock(),
            warehouse_id="test",
        )
        repo._tables_initialized = True
        return repo

    def test_taxiway_color_round_trip(self, repository):
        """Test that taxiway color survives load."""
        repository._execute = MagicMock(return_value=[
            {
                "taxiway_id": "KSFO_A",
                "ref": "A",
                "osm_id": 111,
                "name": "Alpha",
                "width": 23.0,
                "surface": "concrete",
                "points_json": "[]",
                "geo_points_json": "[]",
                "color": 0x555555,
            }
        ])

        result = repository._load_taxiways("KSFO")
        assert result[0]["color"] == 0x555555

    def test_apron_color_round_trip(self, repository):
        """Test that apron color survives load."""
        repository._execute = MagicMock(return_value=[
            {
                "apron_id": "KSFO_1",
                "ref": "1",
                "osm_id": 222,
                "name": "Main",
                "surface": "asphalt",
                "position_x": 0, "position_y": 0, "position_z": 0,
                "width": 100, "depth": 50,
                "polygon_json": "[]",
                "geo_polygon_json": "[]",
                "center_lat": 37.615, "center_lon": -122.39,
                "color": 0x666666,
            }
        ])

        result = repository._load_aprons("KSFO")
        assert result[0]["color"] == 0x666666

    def test_building_color_round_trip(self, repository):
        """Test that building color survives load."""
        repository._execute = MagicMock(return_value=[
            {
                "building_id": "KSFO_1",
                "osm_id": 333,
                "ifc_guid": None,
                "name": "Tower",
                "building_type": "control_tower",
                "operator": None,
                "position_x": 0, "position_y": 0, "position_z": 0,
                "width": 20, "height": 60, "depth": 20,
                "polygon_json": "[]",
                "geo_polygon_json": "[]",
                "center_lat": 37.618, "center_lon": -122.385,
                "source": "OSM",
                "color": 0x444444,
            }
        ])

        result = repository._load_buildings("KSFO")
        assert result[0]["color"] == 0x444444

    def test_no_color_returns_no_key(self, repository):
        """Test that missing color doesn't add a color key."""
        repository._execute = MagicMock(return_value=[
            {
                "taxiway_id": "KSFO_A",
                "ref": "A",
                "osm_id": 111,
                "name": "Alpha",
                "width": 23.0,
                "surface": "concrete",
                "points_json": "[]",
                "geo_points_json": "[]",
                "color": None,
            }
        ])

        result = repository._load_taxiways("KSFO")
        assert "color" not in result[0]


class TestNewTableDDL:
    """Tests for new table DDL definitions."""

    def test_hangars_ddl_has_required_columns(self):
        """Verify hangars DDL has required columns."""
        assert "hangar_id STRING NOT NULL" in HANGARS_DDL
        assert "icao_code STRING NOT NULL" in HANGARS_DDL
        assert "color INT" in HANGARS_DDL
        assert "osm_id BIGINT" in HANGARS_DDL
        assert "polygon_json STRING" in HANGARS_DDL

    def test_helipads_ddl_has_required_columns(self):
        """Verify helipads DDL has required columns."""
        assert "helipad_id STRING NOT NULL" in HELIPADS_DDL
        assert "icao_code STRING NOT NULL" in HELIPADS_DDL
        assert "latitude DOUBLE NOT NULL" in HELIPADS_DDL
        assert "osm_id BIGINT" in HELIPADS_DDL

    def test_parking_positions_ddl_has_required_columns(self):
        """Verify parking_positions DDL has required columns."""
        assert "parking_position_id STRING NOT NULL" in PARKING_POSITIONS_DDL
        assert "icao_code STRING NOT NULL" in PARKING_POSITIONS_DDL
        assert "latitude DOUBLE NOT NULL" in PARKING_POSITIONS_DDL
        assert "osm_id BIGINT" in PARKING_POSITIONS_DDL

    def test_terminals_ddl_has_color(self):
        """Verify terminals DDL has color column."""
        assert "color INT" in TERMINALS_DDL

    def test_taxiways_ddl_has_color(self):
        """Verify taxiways DDL has color column."""
        assert "color INT" in TAXIWAYS_DDL

    def test_aprons_ddl_has_color(self):
        """Verify aprons DDL has color column."""
        assert "color INT" in APRONS_DDL

    def test_buildings_ddl_has_color(self):
        """Verify buildings DDL has color column."""
        assert "color INT" in BUILDINGS_DDL

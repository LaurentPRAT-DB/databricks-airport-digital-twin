"""Tests for Unity Catalog setup and flight schemas."""

import re
from dataclasses import fields
from pathlib import Path

import pytest

from src.schemas.flight import FlightPhase, FlightPosition, FlightStatus


class TestUnityCatalogSQL:
    """Tests for the Unity Catalog SQL setup script."""

    @pytest.fixture
    def sql_content(self) -> str:
        """Load the Unity Catalog setup SQL file."""
        sql_path = Path(__file__).parent.parent / "databricks" / "setup_unity_catalog.sql"
        return sql_path.read_text()

    def test_catalog_sql_syntax(self, sql_content: str) -> None:
        """Validate SQL file contains required statements and is parseable."""
        # Check for CREATE CATALOG statement
        assert "CREATE CATALOG IF NOT EXISTS airport_digital_twin" in sql_content

        # Check for USE CATALOG statement
        assert "USE CATALOG airport_digital_twin" in sql_content

        # Check for all three schema layers
        assert "CREATE SCHEMA IF NOT EXISTS bronze" in sql_content
        assert "CREATE SCHEMA IF NOT EXISTS silver" in sql_content
        assert "CREATE SCHEMA IF NOT EXISTS gold" in sql_content

        # Check for schema comments
        assert "COMMENT" in sql_content

        # Check for GRANT statements (commented)
        assert "GRANT" in sql_content
        assert "<service_principal>" in sql_content

    def test_sql_has_valid_structure(self, sql_content: str) -> None:
        """Validate SQL statements are properly terminated."""
        # Remove comments and check semicolons
        lines = sql_content.split("\n")
        statements = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("--"):
                statements.append(stripped)

        # Join and split by semicolons to count statements
        full_sql = " ".join(statements)
        # Should have at least 4 statements (1 CREATE CATALOG + 1 USE + 3 CREATE SCHEMA)
        sql_statements = [s.strip() for s in full_sql.split(";") if s.strip()]
        assert len(sql_statements) >= 4


class TestFlightPositionSchema:
    """Tests for the FlightPosition Silver layer schema."""

    def test_flight_position_has_required_fields(self) -> None:
        """Validate FlightPosition has all required fields."""
        field_names = {f.name for f in fields(FlightPosition)}

        required_fields = {
            "icao24",
            "callsign",
            "origin_country",
            "position_time",
            "last_contact",
            "longitude",
            "latitude",
            "baro_altitude",
            "on_ground",
            "velocity",
            "true_track",
            "vertical_rate",
            "geo_altitude",
            "squawk",
            "position_source",
            "category",
        }

        assert required_fields.issubset(field_names), (
            f"Missing fields: {required_fields - field_names}"
        )

    def test_flight_position_field_count(self) -> None:
        """Validate FlightPosition has exactly 16 fields (all OpenSky state fields)."""
        assert len(fields(FlightPosition)) == 16

    def test_flight_position_instantiation(self) -> None:
        """Validate FlightPosition can be instantiated with valid data."""
        position = FlightPosition(
            icao24="abc123",
            callsign="TEST123",
            origin_country="United States",
            position_time=1609459200,
            last_contact=1609459200,
            longitude=-122.4194,
            latitude=37.7749,
            baro_altitude=10000.0,
            on_ground=False,
            velocity=250.0,
            true_track=90.0,
            vertical_rate=5.0,
            geo_altitude=10050.0,
            squawk="1234",
            position_source=0,
            category=1,
        )

        assert position.icao24 == "abc123"
        assert position.on_ground is False
        assert position.baro_altitude == 10000.0


class TestFlightStatusSchema:
    """Tests for the FlightStatus Gold layer schema."""

    def test_flight_status_has_required_fields(self) -> None:
        """Validate FlightStatus has all required fields."""
        field_names = {f.name for f in fields(FlightStatus)}

        required_fields = {
            "icao24",
            "callsign",
            "origin_country",
            "last_seen",
            "longitude",
            "latitude",
            "altitude",
            "velocity",
            "heading",
            "on_ground",
            "vertical_rate",
            "flight_phase",
            "data_source",
        }

        assert required_fields.issubset(field_names), (
            f"Missing fields: {required_fields - field_names}"
        )

    def test_flight_status_has_flight_phase(self) -> None:
        """Validate FlightStatus has flight_phase field."""
        field_names = {f.name for f in fields(FlightStatus)}
        assert "flight_phase" in field_names

    def test_flight_phase_enum_values(self) -> None:
        """Validate FlightPhase enum has correct values."""
        expected_values = {"ground", "climbing", "descending", "cruising", "unknown"}
        actual_values = {phase.value for phase in FlightPhase}

        assert expected_values == actual_values

    def test_flight_status_instantiation(self) -> None:
        """Validate FlightStatus can be instantiated with valid data."""
        status = FlightStatus(
            icao24="abc123",
            callsign="TEST123",
            origin_country="United States",
            last_seen=1609459200,
            longitude=-122.4194,
            latitude=37.7749,
            altitude=10000.0,
            velocity=250.0,
            heading=90.0,
            on_ground=False,
            vertical_rate=5.0,
            flight_phase=FlightPhase.CRUISING,
            data_source="opensky",
        )

        assert status.icao24 == "abc123"
        assert status.flight_phase == FlightPhase.CRUISING
        assert status.data_source == "opensky"

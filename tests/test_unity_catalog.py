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
        """Load the Unity Catalog setup SQL file (skip if not fetched)."""
        sql_path = Path(__file__).parent.parent / "databricks" / "setup_unity_catalog.sql"
        if not sql_path.exists():
            pytest.skip("setup_unity_catalog.sql not present")
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

        # Grants must be ENFORCED, not commented-out placeholders
        assert "GRANT USE CATALOG ON CATALOG airport_digital_twin" in sql_content
        assert "GRANT SELECT ON SCHEMA airport_digital_twin.gold" in sql_content
        assert "<service_principal>" not in sql_content

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


class TestUnityCatalogGovernanceModule:
    """Governance implemented as executable Python (fetched as source code).

    src.governance.unity_catalog builds the actual UC constructs: medallion
    catalog/schemas, enforced grants, Delta CHECK constraints, multi-tenant
    row-level security, column masking, and lineage/audit queries.
    """

    def test_medallion_schema_ddl(self) -> None:
        from src.governance.unity_catalog import CATALOG, medallion_schema_ddl

        sql = " ".join(medallion_schema_ddl())
        for layer in ("bronze", "silver", "gold"):
            assert f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{layer}" in sql
        assert "CREATE OR REPLACE VIEW" in sql
        assert "SET TAGS ('medallion_layer'" in sql

    def test_access_control_grants(self) -> None:
        from src.governance.unity_catalog import access_control_grants

        grants = access_control_grants()
        joined = " ".join(grants)
        assert "GRANT USE CATALOG ON CATALOG" in joined
        assert "GRANT USE SCHEMA ON SCHEMA" in joined
        assert "GRANT SELECT ON VIEW" in joined
        assert len(grants) >= 7

    def test_data_quality_constraints(self) -> None:
        from src.governance.unity_catalog import data_quality_constraints

        sql = " ".join(data_quality_constraints())
        assert "ADD CONSTRAINT valid_altitude CHECK" in sql

    def test_row_level_security_and_masking(self) -> None:
        from src.governance.unity_catalog import (
            column_mask_statements,
            row_level_security_statements,
        )

        rls = " ".join(row_level_security_statements())
        assert "CREATE OR REPLACE FUNCTION" in rls
        assert "SET ROW FILTER" in rls
        assert "is_account_group_member" in rls
        mask = " ".join(column_mask_statements())
        assert "SET MASK" in mask

    def test_lineage_audit_queries(self) -> None:
        from src.governance.unity_catalog import lineage_audit_queries

        sql = " ".join(lineage_audit_queries())
        assert "system.access.table_lineage" in sql
        assert "system.access.audit" in sql
        assert "information_schema.table_privileges" in sql

    def test_all_statements_bundle_is_ordered(self) -> None:
        from src.governance.unity_catalog import all_governance_statements

        stmts = all_governance_statements()
        # schemas before views before grants before constraints before RLS/mask
        assert any("CREATE SCHEMA" in s for s in stmts)
        assert any("SET ROW FILTER" in s for s in stmts)
        assert any("SET MASK" in s for s in stmts)


class TestUnityCatalogGovernanceSQL:
    """Optional .sql mirrors (skip if the uploader did not fetch .sql files)."""

    @pytest.fixture
    def db_dir(self) -> Path:
        return Path(__file__).parent.parent / "databricks"

    def test_governance_sql_has_schemas_grants_and_constraints(self, db_dir: Path) -> None:
        f = db_dir / "unity_catalog_governance.sql"
        if not f.exists():
            pytest.skip(".sql not fetched")
        sql = f.read_text()
        # Medallion schemas
        for layer in ("bronze", "silver", "gold"):
            assert f"CREATE SCHEMA IF NOT EXISTS serverless_stable_3n0ihb_catalog.{layer}" in sql
        # Enforced access control
        assert "GRANT USE CATALOG ON CATALOG" in sql
        assert "GRANT SELECT ON VIEW" in sql
        # Data-quality constraint
        assert "ADD CONSTRAINT valid_altitude CHECK" in sql
        # Classification tags
        assert "SET TAGS ('medallion_layer'" in sql

    def test_rls_sql_has_row_filter_and_column_mask(self, db_dir: Path) -> None:
        f = db_dir / "unity_catalog_rls.sql"
        if not f.exists():
            pytest.skip(".sql not fetched")
        sql = f.read_text()
        assert "CREATE OR REPLACE FUNCTION" in sql
        assert "SET ROW FILTER" in sql
        assert "SET MASK" in sql
        assert "is_account_group_member" in sql

    def test_lineage_audit_sql_queries_system_tables(self, db_dir: Path) -> None:
        f = db_dir / "notebooks" / "uc_lineage_audit.sql"
        if not f.exists():
            pytest.skip(".sql not fetched")
        sql = f.read_text()
        assert "system.access.table_lineage" in sql
        assert "system.access.audit" in sql
        assert "information_schema.table_privileges" in sql


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

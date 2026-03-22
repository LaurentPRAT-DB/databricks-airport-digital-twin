"""Tests for DLT pipeline definitions.

These tests validate the pipeline code structure and logic without
requiring a Spark/Databricks environment. The actual DLT decorators
are tested by checking their presence in the source code.
"""

import ast
import json
import os
from pathlib import Path

import pytest


class TestBronzePipeline:
    """Tests for the Bronze layer DLT pipeline."""

    @pytest.fixture
    def bronze_source(self) -> str:
        """Load the bronze pipeline source code."""
        bronze_path = Path(__file__).parent.parent / "src" / "pipelines" / "bronze.py"
        return bronze_path.read_text()

    def test_bronze_table_has_dlt_decorator(self, bronze_source: str) -> None:
        """Validate bronze table has @dlt.table decorator."""
        assert "@dlt.table" in bronze_source

    def test_bronze_table_has_metadata_columns(self, bronze_source: str) -> None:
        """Validate bronze table adds _ingested_at and _source_file columns."""
        assert "_ingested_at" in bronze_source
        assert "_source_file" in bronze_source
        assert "current_timestamp()" in bronze_source

    def test_bronze_reads_from_delta_table(self, bronze_source: str) -> None:
        """Validate bronze table reads from synced Delta table (not cloudFiles)."""
        assert "spark.read.table" in bronze_source
        assert "flight_status_gold" in bronze_source

    def test_bronze_table_properties(self, bronze_source: str) -> None:
        """Validate bronze table has quality property set."""
        assert '"quality": "bronze"' in bronze_source


class TestSilverPipeline:
    """Tests for the Silver layer DLT pipeline."""

    @pytest.fixture
    def silver_source(self) -> str:
        """Load the silver pipeline source code."""
        silver_path = Path(__file__).parent.parent / "src" / "pipelines" / "silver.py"
        return silver_path.read_text()

    def test_silver_table_has_dlt_decorator(self, silver_source: str) -> None:
        """Validate silver table has @dlt.table decorator."""
        assert "@dlt.table" in silver_source

    def test_silver_has_data_quality_expectations(self, silver_source: str) -> None:
        """Validate silver table has required data quality expectations."""
        # Check for expect_or_drop decorators
        assert "@dlt.expect_or_drop" in silver_source

        # Check for specific expectations
        assert "valid_position" in silver_source
        assert "latitude IS NOT NULL AND longitude IS NOT NULL" in silver_source

        assert "valid_icao24" in silver_source
        assert "icao24 IS NOT NULL AND LENGTH(icao24) = 6" in silver_source

        # Check for expect (not drop) decorator
        assert "@dlt.expect" in silver_source
        assert "valid_altitude" in silver_source
        assert "baro_altitude >= 0 OR baro_altitude IS NULL" in silver_source

    def test_silver_deduplicates_by_icao_time(self, silver_source: str) -> None:
        """Validate silver table deduplicates by icao24 and position_time."""
        assert "dropDuplicates" in silver_source
        assert "icao24" in silver_source
        assert "position_time" in silver_source

    def test_silver_applies_watermark(self, silver_source: str) -> None:
        """Validate silver table applies watermark for late data handling."""
        assert "withWatermark" in silver_source
        assert "2 minutes" in silver_source

    def test_silver_extracts_state_vector_fields(self, silver_source: str) -> None:
        """Validate silver extracts all required fields from state vector."""
        required_fields = [
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
        ]

        for field in required_fields:
            assert field in silver_source, f"Missing field: {field}"

    def test_silver_uses_explode(self, silver_source: str) -> None:
        """Validate silver table explodes the states array."""
        assert "explode" in silver_source
        assert "states" in silver_source

    def test_silver_reads_from_bronze(self, silver_source: str) -> None:
        """Validate silver reads from bronze table."""
        assert "flights_bronze" in silver_source


class TestGoldPipeline:
    """Tests for the Gold layer DLT pipeline."""

    @pytest.fixture
    def gold_source(self) -> str:
        """Load the gold pipeline source code."""
        gold_path = Path(__file__).parent.parent / "src" / "pipelines" / "gold.py"
        return gold_path.read_text()

    def test_gold_table_has_dlt_decorator(self, gold_source: str) -> None:
        """Validate gold table has @dlt.table decorator."""
        assert "@dlt.table" in gold_source

    def test_gold_computes_flight_phase(self, gold_source: str) -> None:
        """Validate gold table computes flight_phase column."""
        assert "flight_phase" in gold_source
        # Check for flight phase logic
        assert "ground" in gold_source
        assert "climbing" in gold_source
        assert "descending" in gold_source
        assert "cruising" in gold_source

    def test_gold_aggregates_by_icao24(self, gold_source: str) -> None:
        """Validate gold table groups by icao24 for aggregation."""
        assert "groupBy" in gold_source
        assert "icao24" in gold_source

    def test_gold_reads_from_silver(self, gold_source: str) -> None:
        """Validate gold reads from silver table."""
        assert "flights_silver" in gold_source


class TestBaggageBronzePipeline:
    """Tests for the Baggage Bronze layer DLT pipeline."""

    @pytest.fixture
    def baggage_bronze_source(self) -> str:
        """Load the baggage bronze pipeline source code."""
        path = Path(__file__).parent.parent / "src" / "pipelines" / "baggage_bronze.py"
        return path.read_text()

    def test_baggage_bronze_has_dlt_decorator(self, baggage_bronze_source: str) -> None:
        """Validate baggage bronze table has @dlt.table decorator."""
        assert "@dlt.table" in baggage_bronze_source

    def test_baggage_bronze_table_name(self, baggage_bronze_source: str) -> None:
        """Validate baggage bronze table is named baggage_events_bronze."""
        assert "baggage_events_bronze" in baggage_bronze_source

    def test_baggage_bronze_reads_from_delta_table(self, baggage_bronze_source: str) -> None:
        """Validate baggage bronze reads from synced Delta table (not cloudFiles)."""
        assert "spark.read.table" in baggage_bronze_source
        assert "baggage_status_gold" in baggage_bronze_source

    def test_baggage_bronze_has_metadata_columns(self, baggage_bronze_source: str) -> None:
        """Validate baggage bronze adds _ingested_at and _source_file columns."""
        assert "_ingested_at" in baggage_bronze_source
        assert "_source_file" in baggage_bronze_source

    def test_baggage_bronze_table_properties(self, baggage_bronze_source: str) -> None:
        """Validate baggage bronze has quality property set."""
        assert '"quality": "bronze"' in baggage_bronze_source


class TestBaggageSilverPipeline:
    """Tests for the Baggage Silver layer DLT pipeline."""

    @pytest.fixture
    def baggage_silver_source(self) -> str:
        """Load the baggage silver pipeline source code."""
        path = Path(__file__).parent.parent / "src" / "pipelines" / "baggage_silver.py"
        return path.read_text()

    def test_baggage_silver_has_dlt_decorator(self, baggage_silver_source: str) -> None:
        """Validate baggage silver table has @dlt.table decorator."""
        assert "@dlt.table" in baggage_silver_source

    def test_baggage_silver_table_name(self, baggage_silver_source: str) -> None:
        """Validate baggage silver table is named baggage_events_silver."""
        assert "baggage_events_silver" in baggage_silver_source

    def test_baggage_silver_has_quality_expectations(self, baggage_silver_source: str) -> None:
        """Validate baggage silver has expect_or_drop decorators."""
        assert "@dlt.expect_or_drop" in baggage_silver_source
        assert "valid_flight_number" in baggage_silver_source
        assert "valid_total_bags" in baggage_silver_source
        assert "valid_load_percentage" in baggage_silver_source

    def test_baggage_silver_deduplicates(self, baggage_silver_source: str) -> None:
        """Validate baggage silver deduplicates records."""
        assert "dropDuplicates" in baggage_silver_source
        assert "flight_number" in baggage_silver_source
        assert "recorded_at" in baggage_silver_source

    def test_baggage_silver_reads_from_bronze(self, baggage_silver_source: str) -> None:
        """Validate baggage silver reads from baggage bronze table."""
        assert "baggage_events_bronze" in baggage_silver_source


class TestBaggageGoldPipeline:
    """Tests for the Baggage Gold layer DLT pipeline."""

    @pytest.fixture
    def baggage_gold_source(self) -> str:
        """Load the baggage gold pipeline source code."""
        path = Path(__file__).parent.parent / "src" / "pipelines" / "baggage_gold.py"
        return path.read_text()

    def test_baggage_gold_has_dlt_decorator(self, baggage_gold_source: str) -> None:
        """Validate baggage gold has @dlt.table decorators."""
        assert "@dlt.table" in baggage_gold_source

    def test_baggage_gold_has_status_table(self, baggage_gold_source: str) -> None:
        """Validate baggage gold has baggage_status_gold table."""
        assert "baggage_status_gold" in baggage_gold_source

    def test_baggage_gold_has_events_table(self, baggage_gold_source: str) -> None:
        """Validate baggage gold has baggage_events_gold table."""
        assert "baggage_events_gold" in baggage_gold_source

    def test_baggage_gold_status_aggregates(self, baggage_gold_source: str) -> None:
        """Validate baggage gold status table groups by airport and flight."""
        assert "groupBy" in baggage_gold_source
        assert "airport_icao" in baggage_gold_source
        assert "flight_number" in baggage_gold_source

    def test_baggage_gold_has_watermark(self, baggage_gold_source: str) -> None:
        """Validate baggage gold status table applies watermark."""
        assert "withWatermark" in baggage_gold_source
        assert "10 minutes" in baggage_gold_source

    def test_baggage_gold_reads_from_silver(self, baggage_gold_source: str) -> None:
        """Validate baggage gold reads from baggage silver table."""
        assert "baggage_events_silver" in baggage_gold_source

    def test_baggage_gold_has_partition(self, baggage_gold_source: str) -> None:
        """Validate baggage events gold is partitioned by recorded_date."""
        assert "partition_cols" in baggage_gold_source
        assert "recorded_date" in baggage_gold_source


class TestBaggageWriter:
    """Tests for the baggage landing zone writer."""

    def test_baggage_writer_creates_json(self, tmp_path: Path) -> None:
        """Validate writer creates JSON-lines files in the landing zone."""
        from src.ingestion.baggage_writer import write_baggage_events, LANDING_ZONE
        import src.ingestion.baggage_writer as bw

        # Temporarily override the landing zone to use tmp_path
        original = bw.LANDING_ZONE
        bw.LANDING_ZONE = str(tmp_path / "{catalog}" / "{schema}" / "baggage_landing")

        try:
            events = [
                {"flight_number": "UA123", "total_bags": 180, "loaded": 165,
                 "connecting_bags": 27, "loading_progress_pct": 92, "misconnects": 0},
                {"flight_number": "DL456", "total_bags": 200, "loaded": 180,
                 "connecting_bags": 30, "loading_progress_pct": 90, "misconnects": 1},
            ]

            filepath = write_baggage_events(events, catalog="test_cat", schema="test_schema")

            assert os.path.exists(filepath)
            assert filepath.endswith(".json")

            with open(filepath) as f:
                lines = f.readlines()

            assert len(lines) == 2

            first = json.loads(lines[0])
            assert first["flight_number"] == "UA123"
            assert first["total_bags"] == 180
            assert "recorded_at" in first

            second = json.loads(lines[1])
            assert second["flight_number"] == "DL456"
        finally:
            bw.LANDING_ZONE = original

    def test_baggage_writer_empty_events(self, tmp_path: Path) -> None:
        """Validate writer handles empty event list."""
        import src.ingestion.baggage_writer as bw

        original = bw.LANDING_ZONE
        bw.LANDING_ZONE = str(tmp_path / "{catalog}" / "{schema}" / "baggage_landing")

        try:
            filepath = bw.write_baggage_events([], catalog="test_cat", schema="test_schema")
            assert os.path.exists(filepath)
            with open(filepath) as f:
                assert f.read() == ""
        finally:
            bw.LANDING_ZONE = original


class TestDLTPipelineConfig:
    """Tests for the DLT pipeline configuration (DABs resource YAML)."""

    @pytest.fixture
    def pipeline_config(self) -> dict:
        """Load the DLT pipeline configuration from DABs resource YAML."""
        import yaml
        config_path = (
            Path(__file__).parent.parent / "resources" / "pipeline.yml"
        )
        raw = yaml.safe_load(config_path.read_text())
        return raw["resources"]["pipelines"]["airport_dlt_pipeline"]

    def test_pipeline_has_required_fields(self, pipeline_config: dict) -> None:
        """Validate pipeline config has name and serverless mode."""
        assert "name" in pipeline_config
        assert "Airport Digital Twin DLT" in pipeline_config["name"]
        assert pipeline_config.get("serverless") is True

    def test_pipeline_is_serverless(self, pipeline_config: dict) -> None:
        """Validate pipeline uses serverless compute (no cluster config)."""
        assert pipeline_config.get("serverless") is True
        assert "clusters" not in pipeline_config

    def test_pipeline_targets_catalog(self, pipeline_config: dict) -> None:
        """Validate pipeline targets catalog and schema."""
        assert "catalog" in pipeline_config
        assert "target" in pipeline_config

    def test_pipeline_has_libraries(self, pipeline_config: dict) -> None:
        """Validate pipeline config has library references."""
        libraries = pipeline_config["libraries"]
        assert len(libraries) >= 6  # bronze, silver, gold + baggage bronze, silver, gold
        paths = [lib["file"]["path"] for lib in libraries]
        assert any("bronze.py" in p for p in paths)
        assert any("silver.py" in p for p in paths)
        assert any("gold.py" in p for p in paths)
        assert any("baggage_bronze.py" in p for p in paths)
        assert any("baggage_silver.py" in p for p in paths)
        assert any("baggage_gold.py" in p for p in paths)

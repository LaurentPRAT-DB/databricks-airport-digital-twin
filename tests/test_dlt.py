"""Tests for DLT pipeline definitions.

These tests validate the pipeline code structure and logic without
requiring a Spark/Databricks environment. The actual DLT decorators
are tested by checking their presence in the source code.
"""

import ast
import json
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
        assert "input_file_name()" in bronze_source

    def test_bronze_uses_cloud_files(self, bronze_source: str) -> None:
        """Validate bronze table uses cloudFiles format for Auto Loader."""
        assert "cloudFiles" in bronze_source

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


class TestDLTPipelineConfig:
    """Tests for the DLT pipeline configuration."""

    @pytest.fixture
    def pipeline_config(self) -> dict:
        """Load the DLT pipeline configuration."""
        config_path = (
            Path(__file__).parent.parent / "databricks" / "dlt_pipeline_config.json"
        )
        return json.loads(config_path.read_text())

    def test_pipeline_has_required_fields(self, pipeline_config: dict) -> None:
        """Validate pipeline config has required fields."""
        assert "name" in pipeline_config
        assert pipeline_config["name"] == "airport_digital_twin_pipeline"

    def test_pipeline_has_cluster_config(self, pipeline_config: dict) -> None:
        """Validate pipeline config has cluster configuration."""
        assert "clusters" in pipeline_config
        clusters = pipeline_config["clusters"]
        assert len(clusters) > 0

        # Check for autoscale
        cluster = clusters[0]
        assert "autoscale" in cluster
        assert "min_workers" in cluster["autoscale"]
        assert "max_workers" in cluster["autoscale"]

    def test_pipeline_targets_catalog(self, pipeline_config: dict) -> None:
        """Validate pipeline targets the correct catalog."""
        assert "target" in pipeline_config
        assert "catalog" in pipeline_config

    def test_pipeline_has_libraries(self, pipeline_config: dict) -> None:
        """Validate pipeline config has library references."""
        assert "libraries" in pipeline_config
        libraries = pipeline_config["libraries"]
        assert len(libraries) >= 3  # bronze, silver, gold

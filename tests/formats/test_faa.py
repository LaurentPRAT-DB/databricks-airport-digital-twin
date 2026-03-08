"""
Unit tests for FAA airport data fetcher.

Tests the FAA NASR data fetcher and runway conversion.
"""

import pytest
from unittest.mock import patch, MagicMock

from src.formats.base import CoordinateConverter
from src.formats.faa import (
    FAADataFetcher,
    FAARunway,
    merge_faa_config,
)


class TestFAARunway:
    """Tests for FAARunway model."""

    def test_runway_creation(self):
        """Test creating a runway."""
        runway = FAARunway(
            facility_id="SFO",
            runway_id="10L/28R",
            length=3618,
            width=61,
            surface="ASPH",
            base_end_id="10L",
            base_lat=37.6288,
            base_lon=-122.3936,
            base_elevation=4.0,
            base_heading=102,
            recip_end_id="28R",
            recip_lat=37.6193,
            recip_lon=-122.3571,
            recip_elevation=4.0,
            recip_heading=282,
        )

        assert runway.facility_id == "SFO"
        assert runway.runway_id == "10L/28R"
        assert runway.length == 3618
        assert runway.designator == "10L/28R"

    def test_runway_designator(self):
        """Test runway designator property."""
        runway = FAARunway(
            facility_id="SFO",
            runway_id="01L/19R",
            length=2286,
            width=46,
            surface="ASPH",
            base_end_id="01L",
            base_lat=37.6073,
            base_lon=-122.3862,
            base_elevation=4.0,
            base_heading=10,
            recip_end_id="19R",
            recip_lat=37.6266,
            recip_lon=-122.3825,
            recip_elevation=4.0,
            recip_heading=190,
        )

        assert runway.designator == "01L/19R"


class TestFAADataFetcher:
    """Tests for FAA data fetcher."""

    def test_fetch_sfo_runways(self):
        """Test fetching SFO runway data (fallback)."""
        fetcher = FAADataFetcher()
        runways = fetcher.fetch_airport_runways("SFO")

        assert len(runways) == 4
        designators = [r.runway_id for r in runways]
        assert "10L/28R" in designators
        assert "10R/28L" in designators
        assert "01L/19R" in designators
        assert "01R/19L" in designators

    def test_fetch_with_k_prefix(self):
        """Test fetching with ICAO K prefix."""
        fetcher = FAADataFetcher()
        runways = fetcher.fetch_airport_runways("KSFO")

        assert len(runways) == 4

    def test_fetch_unknown_airport(self):
        """Test fetching unknown airport returns empty."""
        fetcher = FAADataFetcher()
        runways = fetcher.fetch_airport_runways("ZZZZ")

        assert len(runways) == 0

    def test_runway_caching(self):
        """Test that runways are cached."""
        fetcher = FAADataFetcher()

        # First fetch
        runways1 = fetcher.fetch_airport_runways("SFO")

        # Cached fetch should return same list
        runways2 = fetcher.fetch_airport_runways("SFO")

        assert runways1 is runways2

    def test_convert_to_aixm_config(self):
        """Test converting runways to AIXM-compatible config."""
        fetcher = FAADataFetcher()
        runways = fetcher.fetch_airport_runways("SFO")

        converter = CoordinateConverter(
            reference_lat=37.6213,
            reference_lon=-122.379,
            reference_alt=4.0,
        )

        config = fetcher.runways_to_aixm_config(runways, converter)

        assert config["source"] == "FAA"
        assert len(config["runways"]) == 4

        # Check runway structure
        rwy = config["runways"][0]
        assert "id" in rwy
        assert "start" in rwy
        assert "end" in rwy
        assert "width" in rwy
        assert "directions" in rwy

        # Check directions
        assert len(rwy["directions"]) == 2
        assert "designator" in rwy["directions"][0]
        assert "bearing" in rwy["directions"][0]

    def test_convert_runway_positions(self):
        """Test that runway positions are converted correctly."""
        fetcher = FAADataFetcher()
        runways = fetcher.fetch_airport_runways("SFO")

        converter = CoordinateConverter(
            reference_lat=37.6213,
            reference_lon=-122.379,
            reference_alt=4.0,
        )

        config = fetcher.runways_to_aixm_config(runways, converter)

        # Find 10L/28R runway
        rwy_28r = next(r for r in config["runways"] if r["id"] == "10L/28R")

        # Check position types
        assert isinstance(rwy_28r["start"]["x"], float)
        assert isinstance(rwy_28r["start"]["y"], float)
        assert isinstance(rwy_28r["start"]["z"], float)

        # Y should be at least 0.1 (above ground)
        assert rwy_28r["start"]["y"] >= 0.1
        assert rwy_28r["end"]["y"] >= 0.1


class TestMergeFAAConfig:
    """Tests for FAA config merging."""

    def test_merge_replaces_runways(self):
        """Test that FAA runways replace existing runways."""
        base = {
            "runways": [{"id": "old_runway"}],
            "taxiways": [{"id": "taxiway_a"}],
        }
        faa = {
            "runways": [{"id": "10L/28R"}, {"id": "10R/28L"}],
        }

        result = merge_faa_config(base, faa)

        assert len(result["runways"]) == 2
        assert result["runways"][0]["id"] == "10L/28R"
        # Taxiways should be preserved
        assert result["taxiways"] == [{"id": "taxiway_a"}]

    def test_merge_preserves_other_elements(self):
        """Test that non-runway elements are preserved."""
        base = {
            "runways": [],
            "gates": [{"id": "G1"}],
            "buildings": [{"id": "terminal"}],
        }
        faa = {
            "runways": [{"id": "28L"}],
        }

        result = merge_faa_config(base, faa)

        assert result["gates"] == [{"id": "G1"}]
        assert result["buildings"] == [{"id": "terminal"}]

    def test_merge_tracks_source(self):
        """Test that FAA source is tracked."""
        base = {"sources": ["OSM"]}
        faa = {"runways": []}

        result = merge_faa_config(base, faa)

        assert "FAA" in result["sources"]
        assert "OSM" in result["sources"]

    def test_merge_empty_faa_keeps_existing(self):
        """Test that empty FAA config keeps existing runways."""
        base = {
            "runways": [{"id": "existing"}],
            "sources": [],
        }
        faa = {"runways": []}

        result = merge_faa_config(base, faa)

        # Empty FAA runways should not replace existing
        assert result["runways"] == [{"id": "existing"}]


class TestFAAIntegration:
    """Integration tests for FAA data pipeline."""

    def test_full_sfo_import_pipeline(self):
        """Test full pipeline from fetch to config."""
        fetcher = FAADataFetcher()
        runways = fetcher.fetch_airport_runways("SFO")

        converter = CoordinateConverter(
            reference_lat=37.6213,
            reference_lon=-122.379,
            reference_alt=4.0,
        )

        config = fetcher.runways_to_aixm_config(runways, converter)

        # Validate all SFO runways are present
        assert len(config["runways"]) == 4

        # Validate runway 28R (main landing runway)
        rwy_28r = next((r for r in config["runways"] if "28R" in r["id"]), None)
        assert rwy_28r is not None
        assert rwy_28r["width"] == 61  # meters

        # Validate directions
        directions = rwy_28r["directions"]
        designators = [d["designator"] for d in directions]
        assert "10L" in designators
        assert "28R" in designators

    def test_merge_with_osm_data(self):
        """Test merging FAA runway data with OSM gate data."""
        # Simulate OSM config
        osm_config = {
            "sources": ["OSM"],
            "gates": [{"id": "G91"}, {"id": "G92"}],
            "terminals": [{"id": "ITG"}],
            "runways": [],  # OSM usually doesn't have good runway data
        }

        # Get FAA runway data
        fetcher = FAADataFetcher()
        runways = fetcher.fetch_airport_runways("SFO")

        converter = CoordinateConverter(
            reference_lat=37.6213,
            reference_lon=-122.379,
            reference_alt=4.0,
        )

        faa_config = fetcher.runways_to_aixm_config(runways, converter)

        # Merge
        result = merge_faa_config(osm_config, faa_config)

        # Should have FAA runways and OSM gates
        assert len(result["runways"]) == 4
        assert result["gates"] == [{"id": "G91"}, {"id": "G92"}]
        assert "FAA" in result["sources"]
        assert "OSM" in result["sources"]

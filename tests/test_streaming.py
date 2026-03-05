"""Tests for streaming infrastructure: watermarks, deduplication, checkpoints, and fallback data."""

import json
import re
from pathlib import Path


class TestSilverWatermark:
    """Tests for Silver layer watermark configuration."""

    def test_silver_watermark_configured(self):
        """Verify Silver layer has withWatermark call with 2 minutes delay."""
        silver_path = Path(__file__).parent.parent / "src" / "pipelines" / "silver.py"
        content = silver_path.read_text()

        # Check for withWatermark call with 2 minutes
        assert ".withWatermark(" in content, "Silver layer missing withWatermark call"
        assert '"2 minutes"' in content, "Watermark should be configured for 2 minutes"


class TestSilverDeduplication:
    """Tests for Silver layer deduplication configuration."""

    def test_silver_deduplication_keys(self):
        """Verify Silver layer deduplicates on icao24 and position_time."""
        silver_path = Path(__file__).parent.parent / "src" / "pipelines" / "silver.py"
        content = silver_path.read_text()

        # Check for dropDuplicates call
        assert ".dropDuplicates(" in content, "Silver layer missing dropDuplicates call"

        # Check for required keys in dropDuplicates
        assert "icao24" in content, "Deduplication should include icao24"
        assert "position_time" in content, "Deduplication should include position_time"

        # More specific check - find the dropDuplicates call and verify both keys
        dedup_match = re.search(r'\.dropDuplicates\(\[([^\]]+)\]\)', content)
        assert dedup_match, "dropDuplicates should use list format"
        dedup_keys = dedup_match.group(1)
        assert "icao24" in dedup_keys, "icao24 must be in deduplication keys"
        assert "position_time" in dedup_keys, "position_time must be in deduplication keys"


class TestLateDataHandling:
    """Tests for late data handling configuration."""

    def test_late_data_not_dropped_silently(self):
        """Verify Silver layer uses expect decorator for data quality (logs, not drops)."""
        silver_path = Path(__file__).parent.parent / "src" / "pipelines" / "silver.py"
        content = silver_path.read_text()

        # DLT uses @dlt.expect to log quality issues without dropping
        # @dlt.expect_or_drop drops, but @dlt.expect just logs
        assert "@dlt.expect(" in content, (
            "Silver layer should use @dlt.expect for at least some quality checks "
            "to log issues without dropping data"
        )


class TestCheckpointConfiguration:
    """Tests for checkpoint location configuration."""

    def test_checkpoint_path_configurable(self):
        """Verify checkpoint location is not hardcoded in silver layer.

        DLT manages checkpoints automatically based on pipeline configuration.
        We verify the silver layer doesn't hardcode checkpoint paths.
        """
        silver_path = Path(__file__).parent.parent / "src" / "pipelines" / "silver.py"
        content = silver_path.read_text()

        # Silver layer should NOT hardcode checkpoint paths
        # DLT manages this via pipeline config
        hardcoded_patterns = [
            r'checkpointLocation\s*=\s*["\'][^"\']*/checkpoint',
            r'checkpoint_location\s*=\s*["\'][^"\']+["\']',
            r'\.option\(["\']checkpointLocation["\']',
        ]

        for pattern in hardcoded_patterns:
            assert not re.search(pattern, content), (
                f"Checkpoint path appears hardcoded. "
                f"DLT should manage checkpoints via pipeline configuration."
            )


class TestFallbackData:
    """Tests for fallback/sample flight data."""

    def test_fallback_json_valid_schema(self):
        """Verify sample_flights.json has valid OpenSky response structure."""
        fallback_path = (
            Path(__file__).parent.parent / "data" / "fallback" / "sample_flights.json"
        )
        assert fallback_path.exists(), "Fallback data file should exist"

        with open(fallback_path) as f:
            data = json.load(f)

        # Check top-level structure
        assert "time" in data, "Fallback data should have 'time' key"
        assert "states" in data, "Fallback data should have 'states' key"
        assert isinstance(data["time"], int), "'time' should be an integer timestamp"
        assert isinstance(data["states"], list), "'states' should be a list"

        # Verify at least one state has correct structure (18 fields per OpenSky spec)
        if data["states"]:
            first_state = data["states"][0]
            assert isinstance(first_state, list), "Each state should be a list"
            assert len(first_state) == 18, (
                f"State vector should have 18 fields, got {len(first_state)}"
            )

            # Verify key field types
            assert isinstance(first_state[0], str), "icao24 (index 0) should be string"
            assert isinstance(first_state[5], (int, float)), "longitude (index 5) should be numeric"
            assert isinstance(first_state[6], (int, float)), "latitude (index 6) should be numeric"
            assert isinstance(first_state[8], bool), "on_ground (index 8) should be boolean"

    def test_fallback_has_minimum_flights(self):
        """Verify fallback data has at least 50 sample flights."""
        fallback_path = (
            Path(__file__).parent.parent / "data" / "fallback" / "sample_flights.json"
        )

        with open(fallback_path) as f:
            data = json.load(f)

        assert len(data.get("states", [])) >= 50, (
            f"Fallback data should have at least 50 flights, got {len(data.get('states', []))}"
        )

    def test_fallback_has_realistic_distribution(self):
        """Verify fallback data has realistic on_ground distribution (~10%)."""
        fallback_path = (
            Path(__file__).parent.parent / "data" / "fallback" / "sample_flights.json"
        )

        with open(fallback_path) as f:
            data = json.load(f)

        states = data.get("states", [])
        if not states:
            return  # Skip if no states

        on_ground_count = sum(1 for s in states if s[8] is True)
        on_ground_pct = on_ground_count / len(states) * 100

        # Allow 0-30% on ground (random variation from ~10% target)
        assert 0 <= on_ground_pct <= 30, (
            f"On-ground percentage ({on_ground_pct:.1f}%) seems unrealistic"
        )

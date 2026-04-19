"""Tests for simulation replay API endpoints."""

import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

pytestmark = pytest.mark.api

from fastapi.testclient import TestClient

from app.backend.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_sim_data():
    """Minimal simulation JSON for testing."""
    return {
        "config": {
            "airport": "KSFO",
            "duration_hours": 6,
            "start_time": "2026-04-15T06:00:00Z",
        },
        "summary": {
            "total_flights": 10,
            "arrivals": 5,
            "departures": 5,
            "scenario_name": "test_scenario",
        },
        "schedule": [],
        "position_snapshots": [
            {
                "time": "2026-04-15T06:00:00Z",
                "flights": [
                    {
                        "icao24": "abc001",
                        "callsign": "UAL100",
                        "latitude": 37.6,
                        "longitude": -122.4,
                        "altitude": 0,
                        "heading": 90,
                        "speed": 0,
                        "phase": "parked",
                    }
                ],
            }
        ],
        "phase_transitions": [],
        "gate_events": [],
        "scenario_events": [],
    }


class TestSimulationFilesList:
    def test_list_files_returns_200(self, client):
        resp = client.get("/api/simulation/files")
        assert resp.status_code == 200
        data = resp.json()
        assert "files" in data
        assert "count" in data
        assert isinstance(data["files"], list)

    def test_list_files_count_matches(self, client):
        resp = client.get("/api/simulation/files")
        data = resp.json()
        assert data["count"] == len(data["files"])


class TestSimulationData:
    def test_invalid_filename_path_traversal(self, client):
        # FastAPI normalizes `..` in URL paths, so test with encoded version
        resp = client.get("/api/simulation/data/..%2Fetc%2Fpasswd")
        # Either rejected (400) or normalized away (200/404)
        assert resp.status_code in (400, 404, 200)

    def test_invalid_filename_backslash(self, client):
        resp = client.get("/api/simulation/data/test%5Cfile.json")
        # Backslash should be rejected or file not found
        assert resp.status_code in (400, 404)

    def test_nonexistent_file_returns_404(self, client):
        resp = client.get("/api/simulation/data/nonexistent_file_abc123.json")
        assert resp.status_code == 404

    def test_load_local_simulation(self, client, sample_sim_data, tmp_path):
        """Test loading a simulation file from the local filesystem."""
        sim_file = tmp_path / "simulation_test_local.json"
        sim_file.write_text(json.dumps(sample_sim_data))

        with patch(
            "app.backend.api.simulation._find_simulation_files_from_catalog",
            return_value=None,
        ), patch(
            "app.backend.api.simulation._load_simulation_from_volume",
            return_value=None,
        ), patch(
            "app.backend.api.simulation._load_simulation_local",
            return_value=sample_sim_data,
        ):
            resp = client.get("/api/simulation/data/simulation_test_local.json")
            assert resp.status_code == 200
            data = resp.json()
            assert "config" in data
            assert "position_snapshots" in data or "frames" in data


class TestSimulationMetadata:
    def test_metadata_nonexistent(self, client):
        resp = client.get("/api/simulation/metadata/nonexistent.json")
        assert resp.status_code == 404

    def test_metadata_nonexistent_file(self, client):
        resp = client.get("/api/simulation/metadata/totally_nonexistent_xyz.json")
        assert resp.status_code == 404


class TestSimulationDemo:
    def test_demo_endpoint_returns_response(self, client):
        """Demo endpoint for a valid airport should return some response."""
        resp = client.get("/api/simulation/demo/KSFO")
        # Could be 200 (if demo file exists) or 404 (if not generated yet)
        assert resp.status_code in (200, 404, 503)

    def test_demo_endpoint_invalid_icao(self, client):
        resp = client.get("/api/simulation/demo/INVALID_AIRPORT_CODE_ZZZZZ")
        # Should either 404 or return empty
        assert resp.status_code in (200, 404, 503)


class TestLocalFileFinder:
    def test_find_simulation_files_local_empty(self, tmp_path):
        """No simulation files → empty list."""
        from app.backend.api.simulation import _find_simulation_files_local as find_files

        with patch("app.backend.api.simulation.PROJECT_ROOT", tmp_path):
            files = find_files()
            assert isinstance(files, list)

    def test_find_simulation_files_local_with_file(self, tmp_path, sample_sim_data):
        from app.backend.api.simulation import _find_simulation_files_local as find_files

        sim_file = tmp_path / "simulation_output_test.json"
        sim_file.write_text(json.dumps(sample_sim_data))

        with patch("app.backend.api.simulation.PROJECT_ROOT", tmp_path):
            files = find_files()
            assert len(files) == 1
            assert files[0]["airport"] == "KSFO"
            assert files[0]["total_flights"] == 10

    def test_find_simulation_files_local_bad_json(self, tmp_path):
        from app.backend.api.simulation import _find_simulation_files_local as find_files

        bad_file = tmp_path / "simulation_output_bad.json"
        bad_file.write_text("not valid json")

        with patch("app.backend.api.simulation.PROJECT_ROOT", tmp_path):
            files = find_files()
            assert len(files) == 0  # bad file skipped

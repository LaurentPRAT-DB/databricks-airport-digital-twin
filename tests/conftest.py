"""Pytest fixtures for ingestion tests."""

import pytest
import tempfile
import os
from pathlib import Path


@pytest.fixture
def mock_opensky_response():
    """Return sample OpenSky API response data."""
    return {
        "time": 1709654400,
        "states": [
            [
                "a0b1c2",           # icao24
                "UAL1234 ",         # callsign (8 chars padded)
                "United States",    # origin_country
                1709654395,         # time_position
                1709654398,         # last_contact
                -122.3782,          # longitude
                37.6213,            # latitude
                3048.0,             # baro_altitude (meters)
                False,              # on_ground
                231.5,              # velocity (m/s)
                45.0,               # true_track (degrees)
                2.5,                # vertical_rate (m/s)
                None,               # sensors
                3100.0,             # geo_altitude
                "1234",             # squawk
                False,              # spi
                0,                  # position_source
                3                   # category
            ],
            [
                "d3e4f5",
                "DAL5678 ",
                "United States",
                1709654396,
                1709654399,
                -122.2500,
                37.5000,
                10668.0,
                False,
                257.2,
                180.0,
                -3.2,
                None,
                10700.0,
                "5678",
                False,
                0,
                4
            ]
        ]
    }


@pytest.fixture
def mock_landing_path(tmp_path):
    """Create temporary directory for landing zone tests."""
    landing_dir = tmp_path / "landing"
    landing_dir.mkdir()
    return str(landing_dir)


@pytest.fixture
def sfo_bbox():
    """Return SFO area bounding box."""
    return {
        "lamin": 36.0,
        "lamax": 39.0,
        "lomin": -124.0,
        "lomax": -121.0
    }

"""Pytest fixtures for ingestion tests."""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import patch


# SFO runway 28L geometry as OSM-format geoPoints (threshold → far end)
_SFO_RWY_28L_OSM = {
    "id": "RWY_28L",
    "ref": "28L/10R",
    "geoPoints": [
        {"latitude": 37.611712, "longitude": -122.358349},  # 28L threshold
        {"latitude": 37.626291, "longitude": -122.393105},  # 10R end
    ],
    "width": 60.0,
}


@pytest.fixture(autouse=True)
def _provide_osm_runway_data():
    """Inject SFO runway OSM data for all tests so trajectory functions work.

    Production code reads runway geometry from the OSM config service.  In the
    test environment there is no config service, so we patch the lookup function
    to return SFO's primary runway.  Tests that need a different airport or no
    runway data can override this fixture or re-patch as needed.
    """
    with patch(
        "src.ingestion.fallback._get_osm_primary_runway",
        return_value=_SFO_RWY_28L_OSM,
    ):
        yield


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

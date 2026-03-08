"""Tests for base format parser utilities."""

import pytest
import math

from src.formats.base import (
    Position3D,
    GeoPosition,
    CoordinateConverter,
)


class TestPosition3D:
    """Tests for Position3D dataclass."""

    def test_creation(self):
        pos = Position3D(x=1.0, y=2.0, z=3.0)
        assert pos.x == 1.0
        assert pos.y == 2.0
        assert pos.z == 3.0

    def test_to_dict(self):
        pos = Position3D(x=1.0, y=2.0, z=3.0)
        d = pos.to_dict()
        assert d == {"x": 1.0, "y": 2.0, "z": 3.0}


class TestGeoPosition:
    """Tests for GeoPosition dataclass."""

    def test_creation(self):
        geo = GeoPosition(latitude=37.6213, longitude=-122.379, altitude=4.0)
        assert geo.latitude == 37.6213
        assert geo.longitude == -122.379
        assert geo.altitude == 4.0

    def test_default_altitude(self):
        geo = GeoPosition(latitude=37.6213, longitude=-122.379)
        assert geo.altitude == 0.0

    def test_to_dict(self):
        geo = GeoPosition(latitude=37.6213, longitude=-122.379, altitude=4.0)
        d = geo.to_dict()
        assert d == {"latitude": 37.6213, "longitude": -122.379, "altitude": 4.0}


class TestCoordinateConverter:
    """Tests for CoordinateConverter."""

    @pytest.fixture
    def sfo_converter(self):
        """Converter centered on SFO airport."""
        return CoordinateConverter(
            reference_lat=37.6213,
            reference_lon=-122.379,
            reference_alt=4.0,
        )

    def test_reference_point_at_origin(self, sfo_converter):
        """Reference point should convert to origin."""
        geo = GeoPosition(latitude=37.6213, longitude=-122.379, altitude=4.0)
        local = sfo_converter.geo_to_local(geo)

        assert abs(local.x) < 0.001
        assert abs(local.y) < 0.001
        assert abs(local.z) < 0.001

    def test_east_offset(self, sfo_converter):
        """Point east of reference should have positive X."""
        geo = GeoPosition(latitude=37.6213, longitude=-122.369, altitude=4.0)
        local = sfo_converter.geo_to_local(geo)

        assert local.x > 0  # East is positive X
        assert abs(local.z) < 0.001  # Same latitude

    def test_north_offset(self, sfo_converter):
        """Point north of reference should have positive Z."""
        geo = GeoPosition(latitude=37.6313, longitude=-122.379, altitude=4.0)
        local = sfo_converter.geo_to_local(geo)

        assert abs(local.x) < 0.001  # Same longitude
        assert local.z > 0  # North is positive Z

    def test_altitude_offset(self, sfo_converter):
        """Point above reference should have positive Y."""
        geo = GeoPosition(latitude=37.6213, longitude=-122.379, altitude=104.0)
        local = sfo_converter.geo_to_local(geo)

        assert local.y == 100.0  # 104 - 4 = 100m above reference

    def test_roundtrip(self, sfo_converter):
        """Convert geo -> local -> geo should return original."""
        original = GeoPosition(latitude=37.63, longitude=-122.37, altitude=50.0)
        local = sfo_converter.geo_to_local(original)
        recovered = sfo_converter.local_to_geo(local)

        assert abs(recovered.latitude - original.latitude) < 0.0001
        assert abs(recovered.longitude - original.longitude) < 0.0001
        assert abs(recovered.altitude - original.altitude) < 0.1

    def test_bearing_to_rotation(self, sfo_converter):
        """Test bearing to rotation conversion."""
        # North (0 degrees) should be along +Z axis
        rot_north = sfo_converter.bearing_to_rotation(0)
        assert abs(rot_north - math.pi / 2) < 0.001

        # East (90 degrees) should be along +X axis
        rot_east = sfo_converter.bearing_to_rotation(90)
        assert abs(rot_east) < 0.001

    def test_scale_factor(self):
        """Test that scale factor is applied correctly."""
        converter = CoordinateConverter(
            reference_lat=37.6213,
            reference_lon=-122.379,
            reference_alt=0.0,
            scene_scale=0.001,  # 1m = 0.001 scene units
        )

        # 1 degree latitude ≈ 111km = 111,000m
        geo = GeoPosition(latitude=38.6213, longitude=-122.379, altitude=0.0)
        local = converter.geo_to_local(geo)

        # Should be roughly 111,000 * 0.001 = 111 scene units
        assert 100 < local.z < 120

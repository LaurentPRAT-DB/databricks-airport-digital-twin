"""
Base classes and utilities for airport format parsers.

Provides abstract base class for parsers and coordinate conversion utilities
for transforming between geographic (WGS84) and local 3D scene coordinates.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Generic, TypeVar, Union
import math

from pydantic import BaseModel


class ParseError(Exception):
    """Raised when parsing fails."""
    pass


class ValidationError(Exception):
    """Raised when validation fails."""
    pass


@dataclass
class Position3D:
    """3D position in scene coordinates."""
    x: float
    y: float
    z: float

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z}


@dataclass
class GeoPosition:
    """Geographic position in WGS84 coordinates."""
    latitude: float
    longitude: float
    altitude: float = 0.0  # meters above sea level

    def to_dict(self) -> dict[str, float]:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "altitude": self.altitude,
        }


class CoordinateSystem(str, Enum):
    """Supported coordinate reference systems."""
    WGS84 = "EPSG:4326"  # Geographic (lat/lon)
    UTM = "UTM"  # Universal Transverse Mercator
    LOCAL = "LOCAL"  # Local Cartesian


class CoordinateConverter:
    """
    Convert between geographic (WGS84) and local 3D scene coordinates.

    Uses a simple equirectangular projection centered on a reference point.
    For airport-scale distances (<10km), this provides sufficient accuracy.
    For production use with larger areas, consider using pyproj for proper
    CRS transformations.

    The conversion uses:
    - X axis: East-West (longitude)
    - Y axis: Up (altitude)
    - Z axis: North-South (latitude)
    """

    # Earth radius in meters
    EARTH_RADIUS = 6_371_000

    # Meters per degree at equator
    METERS_PER_DEG_LAT = 111_320
    METERS_PER_DEG_LON_EQUATOR = 111_320

    def __init__(
        self,
        reference_lat: float,
        reference_lon: float,
        reference_alt: float = 0.0,
        scene_scale: float = 1.0,
    ):
        """
        Initialize converter with reference point.

        Args:
            reference_lat: Reference latitude (center of scene)
            reference_lon: Reference longitude (center of scene)
            reference_alt: Reference altitude in meters
            scene_scale: Scale factor for scene units (default: 1 meter = 1 unit)
        """
        self.reference_lat = reference_lat
        self.reference_lon = reference_lon
        self.reference_alt = reference_alt
        self.scene_scale = scene_scale

        # Precompute meters per degree longitude at reference latitude
        self._meters_per_deg_lon = (
            self.METERS_PER_DEG_LON_EQUATOR * math.cos(math.radians(reference_lat))
        )

    def geo_to_local(self, geo: GeoPosition) -> Position3D:
        """
        Convert geographic coordinates to local 3D scene coordinates.

        Args:
            geo: Geographic position (WGS84)

        Returns:
            Local 3D position in scene units
        """
        # Delta from reference
        d_lat = geo.latitude - self.reference_lat
        d_lon = geo.longitude - self.reference_lon
        d_alt = geo.altitude - self.reference_alt

        # Convert to meters
        x_meters = d_lon * self._meters_per_deg_lon
        z_meters = d_lat * self.METERS_PER_DEG_LAT
        y_meters = d_alt

        # Apply scale
        return Position3D(
            x=x_meters * self.scene_scale,
            y=y_meters * self.scene_scale,
            z=z_meters * self.scene_scale,
        )

    def local_to_geo(self, local: Position3D) -> GeoPosition:
        """
        Convert local 3D scene coordinates to geographic coordinates.

        Args:
            local: Local 3D position in scene units

        Returns:
            Geographic position (WGS84)
        """
        # Remove scale
        x_meters = local.x / self.scene_scale
        y_meters = local.y / self.scene_scale
        z_meters = local.z / self.scene_scale

        # Convert to degrees
        d_lon = x_meters / self._meters_per_deg_lon
        d_lat = z_meters / self.METERS_PER_DEG_LAT

        return GeoPosition(
            latitude=self.reference_lat + d_lat,
            longitude=self.reference_lon + d_lon,
            altitude=self.reference_alt + y_meters,
        )

    def bearing_to_rotation(self, bearing_degrees: float) -> float:
        """
        Convert compass bearing to scene rotation.

        Bearing: 0=North, 90=East, 180=South, 270=West (clockwise from North)
        Scene rotation: radians around Y axis (counter-clockwise from +X)

        Args:
            bearing_degrees: Compass bearing in degrees

        Returns:
            Rotation in radians for scene
        """
        # Convert bearing (CW from N) to math angle (CCW from E)
        # bearing 0 (N) = math angle 90 = +Z direction
        # bearing 90 (E) = math angle 0 = +X direction
        return math.radians(90 - bearing_degrees)


# Type variable for parsed model type
T = TypeVar("T", bound=BaseModel)


class AirportFormatParser(ABC, Generic[T]):
    """
    Abstract base class for airport format parsers.

    Subclasses implement parsing for specific formats (AIXM, IFC, AIDM)
    and conversion to internal configuration types.
    """

    def __init__(self, converter: CoordinateConverter | None = None):
        """
        Initialize parser.

        Args:
            converter: Optional coordinate converter. If not provided,
                      a default converter centered on SFO is used.
        """
        if converter is None:
            # Default: SFO airport coordinates
            converter = CoordinateConverter(
                reference_lat=37.6213,
                reference_lon=-122.379,
                reference_alt=4.0,  # SFO elevation in meters
            )
        self.converter = converter

    @abstractmethod
    def parse(self, source: Union[str, Path, bytes]) -> T:
        """
        Parse source data into typed model.

        Args:
            source: File path, URL, or raw bytes to parse

        Returns:
            Parsed model of type T

        Raises:
            ParseError: If parsing fails
        """
        pass

    @abstractmethod
    def validate(self, model: T) -> list[str]:
        """
        Validate parsed model.

        Args:
            model: Parsed model to validate

        Returns:
            List of validation warnings (empty if valid)

        Raises:
            ValidationError: If validation fails with critical errors
        """
        pass

    @abstractmethod
    def to_config(self, model: T) -> dict[str, Any]:
        """
        Convert parsed model to internal configuration format.

        Args:
            model: Parsed and validated model

        Returns:
            Dictionary compatible with Airport3DConfig
        """
        pass

    def parse_and_convert(self, source: Union[str, Path, bytes]) -> dict[str, Any]:
        """
        Parse source and convert to configuration in one step.

        Args:
            source: File path, URL, or raw bytes to parse

        Returns:
            Configuration dictionary

        Raises:
            ParseError: If parsing fails
            ValidationError: If validation fails
        """
        model = self.parse(source)
        warnings = self.validate(model)
        if warnings:
            # Log warnings but don't fail
            for warning in warnings:
                print(f"Warning: {warning}")
        return self.to_config(model)

"""
AIXM to Internal Format Converter

Converts parsed AIXM documents to the internal airport configuration format
used by the Airport Digital Twin visualization.
"""

from typing import Any

from src.formats.base import CoordinateConverter, GeoPosition, Position3D
from src.formats.aixm.models import (
    AIXMDocument,
    AIXMRunway,
    AIXMTaxiway,
    AIXMApron,
    GMLLineString,
)


class AIXMConverter:
    """
    Converts AIXM models to internal airport configuration format.

    The internal format matches the TypeScript interfaces defined in
    airport3D.ts (RunwayConfig, TaxiwayConfig, etc.).
    """

    # Default runway colors
    RUNWAY_COLOR = 0x333333  # Dark gray
    TAXIWAY_COLOR = 0x555555  # Medium gray
    APRON_COLOR = 0x666666  # Light gray

    def __init__(self, coord_converter: CoordinateConverter):
        """
        Initialize converter.

        Args:
            coord_converter: Coordinate converter for geo to local transforms
        """
        self.coord_converter = coord_converter

    def to_config(self, doc: AIXMDocument) -> dict[str, Any]:
        """
        Convert AIXMDocument to internal configuration.

        Args:
            doc: Parsed AIXM document

        Returns:
            Configuration dictionary compatible with Airport3DConfig
        """
        config: dict[str, Any] = {
            "source": "AIXM",
            "version": doc.version,
            "runways": [],
            "taxiways": [],
            "aprons": [],
            "navaids": [],
        }

        # Add airport metadata if available
        if doc.airport:
            config["airport"] = {
                "icaoCode": doc.airport.icao_code,
                "iataCode": doc.airport.iata_code,
                "name": doc.airport.name,
                "elevation": doc.airport.elevation,
            }

            # Update coordinate converter with airport reference point
            if doc.airport.arp:
                self.coord_converter = CoordinateConverter(
                    reference_lat=doc.airport.arp.latitude,
                    reference_lon=doc.airport.arp.longitude,
                    reference_alt=doc.airport.elevation or 0.0,
                )

        # Convert runways
        for runway in doc.runways:
            converted = self._convert_runway(runway)
            if converted:
                config["runways"].append(converted)

        # Convert taxiways
        for taxiway in doc.taxiways:
            converted = self._convert_taxiway(taxiway)
            if converted:
                config["taxiways"].append(converted)

        # Convert aprons
        for apron in doc.aprons:
            converted = self._convert_apron(apron)
            if converted:
                config["aprons"].append(converted)

        # Convert navaids
        for navaid in doc.navaids:
            if navaid.location:
                config["navaids"].append({
                    "id": navaid.identifier,
                    "designator": navaid.designator,
                    "type": navaid.type.value,
                    "position": self._geo_to_position(
                        navaid.location.latitude,
                        navaid.location.longitude,
                        0.0,
                    ),
                    "frequency": navaid.frequency,
                })

        return config

    def _convert_runway(self, runway: AIXMRunway) -> dict[str, Any] | None:
        """Convert AIXM runway to internal RunwayConfig format."""
        # Get start and end positions
        if runway.centre_line:
            points = runway.centre_line.points
            if len(points) >= 2:
                start = self._geo_to_position(*points[0])
                end = self._geo_to_position(*points[-1])
            else:
                return None
        elif runway.directions and len(runway.directions) >= 2:
            # Use runway direction thresholds
            dir1 = runway.directions[0]
            dir2 = runway.directions[1]
            if dir1.threshold_location and dir2.threshold_location:
                start = self._geo_to_position(
                    dir1.threshold_location.latitude,
                    dir1.threshold_location.longitude,
                    dir1.elevation or 0.0,
                )
                end = self._geo_to_position(
                    dir2.threshold_location.latitude,
                    dir2.threshold_location.longitude,
                    dir2.elevation or 0.0,
                )
            else:
                return None
        else:
            return None

        return {
            "id": runway.designator,
            "start": start,
            "end": end,
            "width": runway.width,
            "color": self.RUNWAY_COLOR,
            "length": runway.length,
            "surfaceType": runway.surface_type.value if runway.surface_type else None,
            "directions": [
                {
                    "designator": d.designator,
                    "bearing": d.true_bearing or d.magnetic_bearing,
                }
                for d in runway.directions
            ],
        }

    def _convert_taxiway(self, taxiway: AIXMTaxiway) -> dict[str, Any] | None:
        """Convert AIXM taxiway to internal TaxiwayConfig format."""
        points = []

        if taxiway.centre_line:
            for lat, lon, alt in taxiway.centre_line.points:
                points.append(self._geo_to_position(lat, lon, alt))
        elif taxiway.extent:
            # Use polygon exterior as center line approximation
            for lat, lon, alt in taxiway.extent.exterior.points:
                points.append(self._geo_to_position(lat, lon, alt))

        if not points:
            return None

        return {
            "id": taxiway.designator,
            "points": points,
            "width": taxiway.width or 20,  # Default 20m
            "color": self.TAXIWAY_COLOR,
        }

    def _convert_apron(self, apron: AIXMApron) -> dict[str, Any] | None:
        """Convert AIXM apron to internal format."""
        if not apron.extent:
            return None

        points = []
        for lat, lon, alt in apron.extent.exterior.points:
            points.append(self._geo_to_position(lat, lon, alt))

        if not points:
            return None

        # Calculate center and bounding box
        xs = [p["x"] for p in points]
        zs = [p["z"] for p in points]
        center_x = sum(xs) / len(xs)
        center_z = sum(zs) / len(zs)
        width = max(xs) - min(xs)
        depth = max(zs) - min(zs)

        return {
            "id": apron.identifier,
            "name": apron.name,
            "position": {"x": center_x, "y": 0.02, "z": center_z},
            "dimensions": {"width": width, "height": 0.1, "depth": depth},
            "polygon": points,
            "color": self.APRON_COLOR,
        }

    def _geo_to_position(self, lat: float, lon: float, alt: float) -> dict[str, float]:
        """Convert geographic coordinates to scene position dict."""
        pos = self.coord_converter.geo_to_local(GeoPosition(lat, lon, alt))
        # Ensure runway is slightly above ground
        return {"x": pos.x, "y": max(pos.y, 0.1), "z": pos.z}


def merge_aixm_config(
    base_config: dict[str, Any],
    aixm_config: dict[str, Any],
) -> dict[str, Any]:
    """
    Merge AIXM-derived config into existing airport configuration.

    AIXM data takes precedence for runways and taxiways, while keeping
    existing buildings and other elements.

    Args:
        base_config: Existing Airport3DConfig
        aixm_config: Configuration from AIXM parser

    Returns:
        Merged configuration
    """
    result = base_config.copy()

    # Replace runways if AIXM provides them
    if aixm_config.get("runways"):
        result["runways"] = aixm_config["runways"]

    # Replace taxiways if AIXM provides them
    if aixm_config.get("taxiways"):
        result["taxiways"] = aixm_config["taxiways"]

    # Add aprons (AIXM-specific, not in base config)
    if aixm_config.get("aprons"):
        result["aprons"] = aixm_config["aprons"]

    # Add navaids
    if aixm_config.get("navaids"):
        result["navaids"] = aixm_config["navaids"]

    # Keep existing buildings, terminal, ground, lighting
    # These are typically not in AIXM data

    return result

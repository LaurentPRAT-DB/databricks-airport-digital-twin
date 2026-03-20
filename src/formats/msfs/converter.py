"""
MSFS to Internal Format Converter

Converts parsed MSFS documents to the internal airport configuration format
used by the Airport Digital Twin visualization.
"""

import math
from typing import Any

from src.formats.base import CoordinateConverter, GeoPosition
from src.formats.msfs.models import (
    MSFSDocument,
    MSFSParkingSpot,
    MSFSTaxiPath,
    MSFSTaxiPoint,
    MSFSRunway,
    MSFSApron,
    TaxiPathType,
)


class MSFSConverter:
    """
    Converts MSFS models to internal airport configuration format.

    Produces the same output structure as OSMConverter so both
    can be merged into the same airport config.
    """

    TAXIWAY_COLOR = 0x555555
    APRON_COLOR = 0x666666
    RUNWAY_COLOR = 0x333333

    def __init__(self, coord_converter: CoordinateConverter):
        self.coord_converter = coord_converter

    def to_config(self, doc: MSFSDocument) -> dict[str, Any]:
        """
        Convert MSFSDocument to internal configuration.

        Args:
            doc: Parsed MSFS document

        Returns:
            Configuration dictionary matching OSMConverter output format
        """
        # Update reference point from airport center
        if doc.lat != 0 and doc.lon != 0:
            self.coord_converter = CoordinateConverter(
                reference_lat=doc.lat,
                reference_lon=doc.lon,
                reference_alt=doc.alt,
            )

        config: dict[str, Any] = {
            "source": "MSFS",
            "icaoCode": doc.icao_code,
            "iataCode": doc.iata_code or None,
            "airportName": doc.airport_name or None,
            "gates": [],
            "terminals": [],
            "osmTaxiways": [],
            "osmAprons": [],
            "osmRunways": [],
        }

        if doc.lat != 0 and doc.lon != 0:
            config["center"] = {"latitude": doc.lat, "longitude": doc.lon}

        # Build taxi point index for path resolution
        taxi_point_index = {p.index: p for p in doc.taxi_points}

        # Convert gates from parking spots
        for spot in doc.parking_spots:
            gate = self._convert_parking_to_gate(spot)
            if gate:
                config["gates"].append(gate)

        # Convert taxi paths to taxiway polylines
        taxiway_groups = self._group_taxi_paths_by_name(doc.taxi_paths, taxi_point_index)
        for name, paths_with_points in taxiway_groups.items():
            taxiway = self._convert_taxiway_group(name, paths_with_points)
            if taxiway:
                config["osmTaxiways"].append(taxiway)

        # Convert runways
        for runway in doc.runways:
            converted = self._convert_runway(runway)
            if converted:
                config["osmRunways"].append(converted)

        # Convert aprons
        for apron in doc.aprons:
            converted = self._convert_apron(apron)
            if converted:
                config["osmAprons"].append(converted)

        return config

    def _convert_parking_to_gate(self, spot: MSFSParkingSpot) -> dict[str, Any] | None:
        """Convert a parking spot to the internal gate format."""
        ref = spot.display_name
        if not ref:
            return None

        pos = self.coord_converter.geo_to_local(
            GeoPosition(spot.lat, spot.lon, 0.0)
        )

        return {
            "id": ref,
            "ref": ref,
            "terminal": None,
            "name": ref,
            "type": spot.type.value.lower(),
            "heading": spot.heading,
            "radius": spot.radius,
            "airlineCodes": spot.airline_codes or None,
            "position": {"x": pos.x, "y": pos.y, "z": pos.z},
            "geo": {"latitude": spot.lat, "longitude": spot.lon},
        }

    def _group_taxi_paths_by_name(
        self,
        paths: list[MSFSTaxiPath],
        point_index: dict[int, MSFSTaxiPoint],
    ) -> dict[str, list[tuple[MSFSTaxiPath, MSFSTaxiPoint | None, MSFSTaxiPoint | None]]]:
        """Group taxi paths by taxiway name for polyline construction."""
        groups: dict[str, list[tuple[MSFSTaxiPath, MSFSTaxiPoint | None, MSFSTaxiPoint | None]]] = {}
        for path in paths:
            if path.type == TaxiPathType.RUNWAY:
                continue  # Skip runway paths
            name = path.name or f"unnamed_{path.start}_{path.end}"
            start_pt = point_index.get(path.start)
            end_pt = point_index.get(path.end)
            if start_pt is None and end_pt is None:
                continue
            groups.setdefault(name, []).append((path, start_pt, end_pt))
        return groups

    def _convert_taxiway_group(
        self,
        name: str,
        paths_with_points: list[tuple[MSFSTaxiPath, MSFSTaxiPoint | None, MSFSTaxiPoint | None]],
    ) -> dict[str, Any] | None:
        """Convert a group of taxi paths with the same name to a taxiway polyline."""
        if not paths_with_points:
            return None

        # Collect unique points in order
        seen = set()
        points = []
        geo_points = []
        width = 20.0

        for path, start_pt, end_pt in paths_with_points:
            width = max(width, path.width)
            for pt in [start_pt, end_pt]:
                if pt is None:
                    continue
                if pt.index not in seen:
                    seen.add(pt.index)
                    pos = self.coord_converter.geo_to_local(
                        GeoPosition(pt.lat, pt.lon, 0.0)
                    )
                    points.append({"x": pos.x, "y": 0.1, "z": pos.z})
                    geo_points.append({"latitude": pt.lat, "longitude": pt.lon})

        if len(points) < 2:
            return None

        return {
            "id": f"TWY_{name}",
            "name": name,
            "points": points,
            "geoPoints": geo_points,
            "width": width,
            "surface": paths_with_points[0][0].surface if paths_with_points else "ASPHALT",
            "color": self.TAXIWAY_COLOR,
        }

    def _convert_runway(self, runway: MSFSRunway) -> dict[str, Any] | None:
        """Convert MSFS runway to internal format."""
        # Build a two-point polyline from center + heading + length
        half_len = runway.length / 2.0
        heading_rad = math.radians(runway.heading)

        # Calculate endpoints from center
        d_lat = half_len * math.cos(heading_rad) / 111_320
        d_lon = half_len * math.sin(heading_rad) / (111_320 * math.cos(math.radians(runway.lat)))

        start_lat = runway.lat - d_lat
        start_lon = runway.lon - d_lon
        end_lat = runway.lat + d_lat
        end_lon = runway.lon + d_lon

        # Use runway end positions if available
        if runway.primary_end and runway.secondary_end:
            start_lat, start_lon = runway.primary_end.lat, runway.primary_end.lon
            end_lat, end_lon = runway.secondary_end.lat, runway.secondary_end.lon

        start_pos = self.coord_converter.geo_to_local(GeoPosition(start_lat, start_lon, 0.0))
        end_pos = self.coord_converter.geo_to_local(GeoPosition(end_lat, end_lon, 0.0))

        designator = runway.designator
        if runway.primary_end and runway.secondary_end:
            designator = f"{runway.primary_end.designator}/{runway.secondary_end.designator}"

        return {
            "id": f"RWY_{designator or 'UNK'}",
            "name": designator,
            "ref": designator,
            "points": [
                {"x": start_pos.x, "y": 0.0, "z": start_pos.z},
                {"x": end_pos.x, "y": 0.0, "z": end_pos.z},
            ],
            "geoPoints": [
                {"latitude": start_lat, "longitude": start_lon},
                {"latitude": end_lat, "longitude": end_lon},
            ],
            "width": runway.width,
            "surface": runway.surface,
            "color": self.RUNWAY_COLOR,
        }

    def _convert_apron(self, apron: MSFSApron) -> dict[str, Any] | None:
        """Convert MSFS apron to internal format."""
        if not apron.vertices:
            return None

        center_lat, center_lon = apron.center
        center_pos = self.coord_converter.geo_to_local(
            GeoPosition(center_lat, center_lon, 0.0)
        )

        points = []
        geo_polygon = []
        for v in apron.vertices:
            pos = self.coord_converter.geo_to_local(GeoPosition(v.lat, v.lon, 0.0))
            points.append({"x": pos.x, "y": 0.02, "z": pos.z})
            geo_polygon.append({"latitude": v.lat, "longitude": v.lon})

        xs = [p["x"] for p in points]
        zs = [p["z"] for p in points]
        width = max(xs) - min(xs) if xs else 100
        depth = max(zs) - min(zs) if zs else 100

        return {
            "id": f"APRON_{id(apron)}",
            "name": None,
            "surface": apron.surface,
            "position": {"x": center_pos.x, "y": 0.02, "z": center_pos.z},
            "dimensions": {"width": width, "height": 0.1, "depth": depth},
            "polygon": points,
            "geoPolygon": geo_polygon,
            "geo": {"latitude": center_lat, "longitude": center_lon},
            "color": self.APRON_COLOR,
        }

    def to_gates_dict(self, doc: MSFSDocument) -> dict[str, dict[str, Any]]:
        """
        Convert parking spots to the GATES dict format used in fallback.py.

        Args:
            doc: Parsed MSFS document

        Returns:
            Dictionary mapping gate refs to gate data
        """
        gates_dict = {}
        for spot in doc.parking_spots:
            ref = spot.display_name
            if not ref:
                continue
            gates_dict[ref] = {
                "latitude": spot.lat,
                "longitude": spot.lon,
                "terminal": None,
                "name": ref,
                "type": spot.type.value.lower(),
                "heading": spot.heading,
            }
        return gates_dict


def merge_msfs_config(
    base_config: dict[str, Any],
    msfs_config: dict[str, Any],
) -> dict[str, Any]:
    """
    Merge MSFS-derived config into existing airport configuration.

    MSFS data provides detailed gate positions and taxi networks.
    Gates from MSFS override existing gates (more precise positions).

    Args:
        base_config: Existing airport configuration
        msfs_config: Configuration from MSFS parser

    Returns:
        Merged configuration
    """
    result = base_config.copy()

    # MSFS gates override existing (they have precise positions + headings)
    if msfs_config.get("gates"):
        result["gates"] = msfs_config["gates"]

    # Add MSFS taxiways
    if msfs_config.get("osmTaxiways"):
        existing = result.get("osmTaxiways", [])
        existing_ids = {t.get("id") for t in existing}
        for tw in msfs_config["osmTaxiways"]:
            if tw.get("id") not in existing_ids:
                existing.append(tw)
        result["osmTaxiways"] = existing

    # Add MSFS aprons
    if msfs_config.get("osmAprons"):
        existing = result.get("osmAprons", [])
        existing.extend(msfs_config["osmAprons"])
        result["osmAprons"] = existing

    # Add MSFS runways
    if msfs_config.get("osmRunways"):
        existing = result.get("osmRunways", [])
        existing_ids = {r.get("id") for r in existing}
        for rwy in msfs_config["osmRunways"]:
            if rwy.get("id") not in existing_ids:
                existing.append(rwy)
        result["osmRunways"] = existing

    # Track source
    sources = result.get("sources", [])
    if "MSFS" not in sources:
        sources.append("MSFS")
    result["sources"] = sources

    return result

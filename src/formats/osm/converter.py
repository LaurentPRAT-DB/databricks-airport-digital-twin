"""
OSM to Internal Format Converter

Converts parsed OSM documents to the internal airport configuration format
used by the Airport Digital Twin visualization.
"""

from typing import Any

from src.formats.base import CoordinateConverter, GeoPosition
from src.formats.osm.models import OSMDocument, OSMNode, OSMWay


class OSMConverter:
    """
    Converts OSM models to internal airport configuration format.

    The internal format matches the TypeScript interfaces and the
    fallback.py GATES structure.
    """

    # Default colors
    TERMINAL_COLOR = 0x444444
    TAXIWAY_COLOR = 0x555555
    APRON_COLOR = 0x666666

    def __init__(self, coord_converter: CoordinateConverter):
        """
        Initialize converter.

        Args:
            coord_converter: Coordinate converter for geo to local transforms
        """
        self.coord_converter = coord_converter

    def to_config(self, doc: OSMDocument) -> dict[str, Any]:
        """
        Convert OSMDocument to internal configuration.

        Args:
            doc: Parsed OSM document

        Returns:
            Configuration dictionary
        """
        config: dict[str, Any] = {
            "source": "OSM",
            "icaoCode": doc.icao_code,
            "gates": [],
            "terminals": [],
            "taxiways": [],
            "aprons": [],
        }

        # Update converter reference point from centroid of all elements
        self._update_reference_point(doc)

        # Convert gates
        for gate in doc.gates:
            converted = self._convert_gate(gate)
            if converted:
                config["gates"].append(converted)

        # Convert terminals
        for terminal in doc.terminals:
            converted = self._convert_terminal(terminal)
            if converted:
                config["terminals"].append(converted)

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

        return config

    def _update_reference_point(self, doc: OSMDocument) -> None:
        """Update converter reference point from document centroid."""
        lats = []
        lons = []

        for node in doc.nodes:
            lats.append(node.lat)
            lons.append(node.lon)

        for way in doc.ways:
            if way.geometry:
                center = way.center
                lats.append(center[0])
                lons.append(center[1])

        if lats and lons:
            ref_lat = sum(lats) / len(lats)
            ref_lon = sum(lons) / len(lons)
            self.coord_converter = CoordinateConverter(
                reference_lat=ref_lat,
                reference_lon=ref_lon,
                reference_alt=self.coord_converter.reference_alt,
            )

    def _convert_gate(self, gate: OSMNode) -> dict[str, Any] | None:
        """Convert OSM gate node to internal gate format."""
        ref = gate.gate_ref
        if not ref:
            # Generate ref from OSM ID if missing
            ref = f"G{gate.id % 1000}"

        pos = self.coord_converter.geo_to_local(
            GeoPosition(gate.lat, gate.lon, gate.tags.ele or 0.0)
        )

        return {
            "id": ref,
            "osmId": gate.id,
            "ref": ref,
            "terminal": gate.terminal_name,
            "name": gate.tags.name,
            "position": {
                "x": pos.x,
                "y": pos.y,
                "z": pos.z,
            },
            "geo": {
                "latitude": gate.lat,
                "longitude": gate.lon,
            },
        }

    def _convert_terminal(self, terminal: OSMWay) -> dict[str, Any] | None:
        """Convert OSM terminal way to internal building format."""
        if not terminal.geometry:
            return None

        # Calculate center and bounding box
        center_lat, center_lon = terminal.center
        center_pos = self.coord_converter.geo_to_local(
            GeoPosition(center_lat, center_lon, 0.0)
        )

        # Calculate dimensions from polygon
        points = []
        for pt in terminal.geometry:
            pos = self.coord_converter.geo_to_local(
                GeoPosition(pt.lat, pt.lon, 0.0)
            )
            points.append({"x": pos.x, "y": pos.y, "z": pos.z})

        xs = [p["x"] for p in points]
        zs = [p["z"] for p in points]
        width = max(xs) - min(xs) if xs else 100
        depth = max(zs) - min(zs) if zs else 50
        height = terminal.tags.height or 15.0  # Default terminal height

        return {
            "id": f"terminal_{terminal.id}",
            "osmId": terminal.id,
            "name": terminal.tags.name or f"Terminal {terminal.id}",
            "type": "terminal",
            "position": {
                "x": center_pos.x,
                "y": 0.0,
                "z": center_pos.z,
            },
            "dimensions": {
                "width": width,
                "height": height,
                "depth": depth,
            },
            "polygon": points,
            "color": self.TERMINAL_COLOR,
            "geo": {
                "latitude": center_lat,
                "longitude": center_lon,
            },
        }

    def _convert_taxiway(self, taxiway: OSMWay) -> dict[str, Any] | None:
        """Convert OSM taxiway way to internal taxiway format."""
        if not taxiway.geometry:
            return None

        points = []
        for pt in taxiway.geometry:
            pos = self.coord_converter.geo_to_local(
                GeoPosition(pt.lat, pt.lon, 0.0)
            )
            points.append({"x": pos.x, "y": 0.1, "z": pos.z})

        return {
            "id": taxiway.tags.ref or f"TWY_{taxiway.id}",
            "osmId": taxiway.id,
            "name": taxiway.tags.name or taxiway.tags.ref,
            "points": points,
            "width": taxiway.tags.width or 20.0,
            "color": self.TAXIWAY_COLOR,
        }

    def _convert_apron(self, apron: OSMWay) -> dict[str, Any] | None:
        """Convert OSM apron way to internal apron format."""
        if not apron.geometry:
            return None

        center_lat, center_lon = apron.center
        center_pos = self.coord_converter.geo_to_local(
            GeoPosition(center_lat, center_lon, 0.0)
        )

        points = []
        for pt in apron.geometry:
            pos = self.coord_converter.geo_to_local(
                GeoPosition(pt.lat, pt.lon, 0.0)
            )
            points.append({"x": pos.x, "y": 0.02, "z": pos.z})

        xs = [p["x"] for p in points]
        zs = [p["z"] for p in points]
        width = max(xs) - min(xs) if xs else 100
        depth = max(zs) - min(zs) if zs else 100

        return {
            "id": apron.tags.ref or f"APRON_{apron.id}",
            "osmId": apron.id,
            "name": apron.tags.name,
            "position": {"x": center_pos.x, "y": 0.02, "z": center_pos.z},
            "dimensions": {"width": width, "height": 0.1, "depth": depth},
            "polygon": points,
            "color": self.APRON_COLOR,
        }

    def to_gates_dict(self, doc: OSMDocument) -> dict[str, dict[str, Any]]:
        """
        Convert gates to the GATES dict format used in fallback.py.

        This creates a dictionary keyed by gate reference suitable for
        direct use as the GATES constant or dynamic loading.

        Args:
            doc: Parsed OSM document

        Returns:
            Dictionary mapping gate refs to gate data
        """
        gates_dict = {}

        for gate in doc.gates:
            ref = gate.gate_ref
            if not ref:
                continue

            gates_dict[ref] = {
                "latitude": gate.lat,
                "longitude": gate.lon,
                "terminal": gate.terminal_name,
                "name": gate.tags.name,
            }

        return gates_dict


def merge_osm_config(
    base_config: dict[str, Any],
    osm_config: dict[str, Any],
) -> dict[str, Any]:
    """
    Merge OSM-derived config into existing airport configuration.

    OSM data provides gates and terminals, while keeping existing
    runways from AIXM and other elements.

    Args:
        base_config: Existing airport configuration
        osm_config: Configuration from OSM parser

    Returns:
        Merged configuration
    """
    result = base_config.copy()

    # Add gates from OSM
    if osm_config.get("gates"):
        result["gates"] = osm_config["gates"]

    # Merge terminals (add OSM terminals to existing buildings)
    if osm_config.get("terminals"):
        existing_buildings = result.get("buildings", [])
        osm_buildings = osm_config["terminals"]
        # Don't duplicate - check by name/id
        existing_ids = {b.get("id") for b in existing_buildings}
        for bldg in osm_buildings:
            if bldg.get("id") not in existing_ids:
                existing_buildings.append(bldg)
        result["buildings"] = existing_buildings

    # Add taxiways if not already present
    if osm_config.get("taxiways") and not result.get("taxiways"):
        result["taxiways"] = osm_config["taxiways"]

    # Add aprons if not already present
    if osm_config.get("aprons") and not result.get("aprons"):
        result["aprons"] = osm_config["aprons"]

    # Track source
    sources = result.get("sources", [])
    if "OSM" not in sources:
        sources.append("OSM")
    result["sources"] = sources

    return result

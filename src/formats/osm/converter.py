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
    RUNWAY_COLOR = 0x333333
    HANGAR_COLOR = 0x777777

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
            "iataCode": doc.iata_code,
            "airportName": doc.airport_name,
            "airportOperator": doc.airport_operator,
            "osmTimestamp": doc.timestamp.isoformat() if doc.timestamp else None,
            "gates": [],
            "terminals": [],
            "osmTaxiways": [],
            "osmAprons": [],
            "osmRunways": [],
            "osmHangars": [],
            "osmHelipads": [],
            "osmParkingPositions": [],
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
                config["osmTaxiways"].append(converted)

        # Convert aprons
        for apron in doc.aprons:
            converted = self._convert_apron(apron)
            if converted:
                config["osmAprons"].append(converted)

        # Convert runways
        for runway in doc.runways:
            converted = self._convert_runway(runway)
            if converted:
                config["osmRunways"].append(converted)

        # Convert hangars
        for hangar in doc.hangars:
            converted = self._convert_hangar(hangar)
            if converted:
                config["osmHangars"].append(converted)

        # Convert helipads
        for helipad in doc.helipads:
            converted = self._convert_helipad(helipad)
            if converted:
                config["osmHelipads"].append(converted)

        # Convert parking positions — also add as usable gates (remote stands)
        # Track refs already present from aeroway=gate nodes to avoid duplicates
        gate_refs = {g["ref"] for g in config["gates"] if g.get("ref")}
        for pp in doc.parking_positions:
            converted = self._convert_parking_position(pp)
            if converted:
                config["osmParkingPositions"].append(converted)
                # Parking positions are legitimate aircraft stands
                ref = converted.get("ref") or converted.get("id")
                if ref and converted.get("geo") and ref not in gate_refs and self._is_valid_gate_ref(str(ref)):
                    gate_entry = {
                        "id": ref,
                        "osmId": converted.get("osmId"),
                        "ref": ref,
                        "terminal": None,  # Remote stand — no terminal
                        "name": converted.get("name"),
                        "level": None,
                        "operator": None,
                        "elevation": None,
                        "position": converted.get("position"),
                        "geo": converted["geo"],
                        "is_remote_stand": True,
                    }
                    config["gates"].append(gate_entry)
                    gate_refs.add(ref)

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

    @staticmethod
    def _is_valid_gate_ref(ref: str) -> bool:
        """Check if a gate ref looks like a real gate number, not an OSM ID.

        Real gate numbers are typically < 200 or have letter prefixes (e.g. "A12", "T3").
        Purely numeric values > 999 are likely OSM way/node IDs leaking through.
        """
        if not ref:
            return False
        if ref.isdigit() and int(ref) > 999:
            return False
        return True

    def _convert_gate(self, gate: OSMNode) -> dict[str, Any] | None:
        """Convert OSM gate node to internal gate format."""
        ref = gate.gate_ref
        if not ref:
            # No ref tag — skip this gate rather than generating a fake name
            # (e.g. "G869" from OSM node IDs confuses users)
            return None

        if not self._is_valid_gate_ref(ref):
            return None

        pos = self.coord_converter.geo_to_local(
            GeoPosition(gate.lat, gate.lon, gate.tags.ele or 0.0)
        )

        return {
            "id": ref,
            "osmId": gate.id,
            "ref": ref,
            "terminal": gate.terminal_name,
            "name": gate.tags.name,
            "level": gate.tags.level,  # Floor level for multi-story terminals
            "operator": gate.tags.operator,  # Airline operator (if assigned)
            "elevation": gate.tags.ele,  # Elevation in meters
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

        # Calculate dimensions from polygon (3D coordinates)
        points = []
        geo_polygon = []
        for pt in terminal.geometry:
            pos = self.coord_converter.geo_to_local(
                GeoPosition(pt.lat, pt.lon, 0.0)
            )
            points.append({"x": pos.x, "y": pos.y, "z": pos.z})
            geo_polygon.append({"latitude": pt.lat, "longitude": pt.lon})

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
            "operator": terminal.tags.operator,  # Airport authority or airline operator
            "level": terminal.tags.level,  # Number of levels/floors
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
            "geoPolygon": geo_polygon,  # For 2D map rendering
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
        geo_points = []
        for pt in taxiway.geometry:
            pos = self.coord_converter.geo_to_local(
                GeoPosition(pt.lat, pt.lon, 0.0)
            )
            points.append({"x": pos.x, "y": 0.1, "z": pos.z})
            geo_points.append({"latitude": pt.lat, "longitude": pt.lon})

        return {
            "id": f"{taxiway.tags.ref or 'TWY'}_{taxiway.id}",
            "osmId": taxiway.id,
            "name": taxiway.tags.name or taxiway.tags.ref,
            "points": points,
            "geoPoints": geo_points,  # For 2D map rendering
            "width": taxiway.tags.width or 20.0,
            "surface": taxiway.tags.surface,  # Paving material (asphalt, concrete, etc.)
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
        geo_polygon = []
        for pt in apron.geometry:
            pos = self.coord_converter.geo_to_local(
                GeoPosition(pt.lat, pt.lon, 0.0)
            )
            points.append({"x": pos.x, "y": 0.02, "z": pos.z})
            geo_polygon.append({"latitude": pt.lat, "longitude": pt.lon})

        xs = [p["x"] for p in points]
        zs = [p["z"] for p in points]
        width = max(xs) - min(xs) if xs else 100
        depth = max(zs) - min(zs) if zs else 100

        return {
            "id": f"{apron.tags.ref or 'APRON'}_{apron.id}",
            "osmId": apron.id,
            "name": apron.tags.name,
            "surface": apron.tags.surface,  # Paving material (asphalt, concrete, etc.)
            "position": {"x": center_pos.x, "y": 0.02, "z": center_pos.z},
            "dimensions": {"width": width, "height": 0.1, "depth": depth},
            "polygon": points,
            "geoPolygon": geo_polygon,  # For 2D map rendering
            "geo": {"latitude": center_lat, "longitude": center_lon},
            "color": self.APRON_COLOR,
        }

    def _convert_runway(self, runway: OSMWay) -> dict[str, Any] | None:
        """Convert OSM runway way to internal format."""
        if not runway.geometry:
            return None

        points = []
        geo_points = []
        for pt in runway.geometry:
            pos = self.coord_converter.geo_to_local(
                GeoPosition(pt.lat, pt.lon, 0.0)
            )
            points.append({"x": pos.x, "y": 0.0, "z": pos.z})
            geo_points.append({"latitude": pt.lat, "longitude": pt.lon})

        return {
            "id": f"{runway.tags.ref or 'RWY'}_{runway.id}",
            "osmId": runway.id,
            "name": runway.tags.name or runway.tags.ref,
            "ref": runway.tags.ref,
            "points": points,
            "geoPoints": geo_points,
            "width": runway.tags.width or 45.0,
            "surface": runway.tags.surface,
            "color": self.RUNWAY_COLOR,
        }

    def _convert_hangar(self, hangar: OSMWay) -> dict[str, Any] | None:
        """Convert OSM hangar way to internal building format."""
        if not hangar.geometry:
            return None

        center_lat, center_lon = hangar.center
        center_pos = self.coord_converter.geo_to_local(
            GeoPosition(center_lat, center_lon, 0.0)
        )

        points = []
        geo_polygon = []
        for pt in hangar.geometry:
            pos = self.coord_converter.geo_to_local(
                GeoPosition(pt.lat, pt.lon, 0.0)
            )
            points.append({"x": pos.x, "y": pos.y, "z": pos.z})
            geo_polygon.append({"latitude": pt.lat, "longitude": pt.lon})

        xs = [p["x"] for p in points]
        zs = [p["z"] for p in points]
        width = max(xs) - min(xs) if xs else 50
        depth = max(zs) - min(zs) if zs else 50
        height = hangar.tags.height or 12.0

        return {
            "id": f"hangar_{hangar.id}",
            "osmId": hangar.id,
            "name": hangar.tags.name or f"Hangar {hangar.id}",
            "type": "hangar",
            "operator": hangar.tags.operator,
            "position": {"x": center_pos.x, "y": 0.0, "z": center_pos.z},
            "dimensions": {"width": width, "height": height, "depth": depth},
            "polygon": points,
            "geoPolygon": geo_polygon,
            "color": self.HANGAR_COLOR,
            "geo": {"latitude": center_lat, "longitude": center_lon},
        }

    def _convert_helipad(self, helipad: OSMNode) -> dict[str, Any] | None:
        """Convert OSM helipad node to internal format."""
        pos = self.coord_converter.geo_to_local(
            GeoPosition(helipad.lat, helipad.lon, helipad.tags.ele or 0.0)
        )

        return {
            "id": f"{helipad.tags.ref or 'HELI'}_{helipad.id}",
            "osmId": helipad.id,
            "name": helipad.tags.name,
            "ref": helipad.tags.ref,
            "position": {"x": pos.x, "y": pos.y, "z": pos.z},
            "geo": {"latitude": helipad.lat, "longitude": helipad.lon},
        }

    def _convert_parking_position(self, pp: OSMNode) -> dict[str, Any] | None:
        """Convert OSM parking position node to internal format."""
        pos = self.coord_converter.geo_to_local(
            GeoPosition(pp.lat, pp.lon, pp.tags.ele or 0.0)
        )

        return {
            "id": f"{pp.tags.ref or 'PP'}_{pp.id}",
            "osmId": pp.id,
            "ref": pp.tags.ref,
            "name": pp.tags.name,
            "position": {"x": pos.x, "y": pos.y, "z": pos.z},
            "geo": {"latitude": pp.lat, "longitude": pp.lon},
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
            if not ref or not self._is_valid_gate_ref(ref):
                continue

            gates_dict[ref] = {
                "latitude": gate.lat,
                "longitude": gate.lon,
                "terminal": gate.terminal_name,
                "name": gate.tags.name,
                "level": gate.tags.level,  # Floor level
                "operator": gate.tags.operator,  # Airline operator
                "elevation": gate.tags.ele,  # Elevation in meters
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

    # Merge terminals (add OSM terminals to existing buildings AND set terminals field)
    if osm_config.get("terminals"):
        result["terminals"] = osm_config["terminals"]
        existing_buildings = result.get("buildings", [])
        osm_buildings = osm_config["terminals"]
        # Don't duplicate - check by name/id
        existing_ids = {b.get("id") for b in existing_buildings}
        for bldg in osm_buildings:
            if bldg.get("id") not in existing_ids:
                existing_buildings.append(bldg)
        result["buildings"] = existing_buildings

    # Add OSM taxiways
    if osm_config.get("osmTaxiways"):
        result["osmTaxiways"] = osm_config["osmTaxiways"]

    # Add OSM aprons
    if osm_config.get("osmAprons"):
        result["osmAprons"] = osm_config["osmAprons"]

    # Add OSM runways
    if osm_config.get("osmRunways"):
        result["osmRunways"] = osm_config["osmRunways"]

    # Add OSM hangars
    if osm_config.get("osmHangars"):
        result["osmHangars"] = osm_config["osmHangars"]

    # Add OSM helipads
    if osm_config.get("osmHelipads"):
        result["osmHelipads"] = osm_config["osmHelipads"]

    # Add OSM parking positions
    if osm_config.get("osmParkingPositions"):
        result["osmParkingPositions"] = osm_config["osmParkingPositions"]

    # Track source
    sources = result.get("sources", [])
    if "OSM" not in sources:
        sources.append("OSM")
    result["sources"] = sources

    return result

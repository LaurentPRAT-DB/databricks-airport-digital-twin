"""
OpenStreetMap Overpass API Parser

Fetches and parses airport data from OpenStreetMap via Overpass API.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

import httpx

from src.formats.base import CoordinateConverter, ParseError, AirportFormatParser
from src.formats.osm.models import (
    OSMDocument,
    OSMNode,
    OSMWay,
    OSMWayNode,
    OSMTags,
)

logger = logging.getLogger(__name__)

# Overpass API endpoints (use multiple for redundancy)
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Default timeout for API requests
DEFAULT_TIMEOUT = 30.0


class OSMParser(AirportFormatParser[OSMDocument]):
    """
    Parser for OpenStreetMap airport data via Overpass API.

    Fetches gates, terminals, and other aeroway features for an airport.
    """

    def __init__(
        self,
        converter: CoordinateConverter | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        """
        Initialize OSM parser.

        Args:
            converter: Coordinate converter (auto-created from airport data)
            timeout: API request timeout in seconds
        """
        super().__init__(converter)
        self.timeout = timeout

    def build_query(
        self,
        icao_code: str,
        include_gates: bool = True,
        include_terminals: bool = True,
        include_taxiways: bool = False,
        include_aprons: bool = False,
    ) -> str:
        """
        Build Overpass QL query for airport features.

        Args:
            icao_code: ICAO airport code (e.g., "KSFO")
            include_gates: Fetch gate nodes
            include_terminals: Fetch terminal buildings
            include_taxiways: Fetch taxiway ways
            include_aprons: Fetch apron areas

        Returns:
            Overpass QL query string
        """
        # Build feature selectors
        selectors = []

        if include_gates:
            selectors.append('node["aeroway"="gate"](area.airport);')

        if include_terminals:
            selectors.append('way["aeroway"="terminal"](area.airport);')
            selectors.append('way["building"="terminal"](area.airport);')

        if include_taxiways:
            selectors.append('way["aeroway"="taxiway"](area.airport);')

        if include_aprons:
            selectors.append('way["aeroway"="apron"](area.airport);')

        features = "\n  ".join(selectors)

        query = f"""[out:json][timeout:25];
area["icao"="{icao_code}"]->.airport;
(
  {features}
);
out body geom;
"""
        return query

    def fetch_from_api(
        self,
        icao_code: str,
        include_gates: bool = True,
        include_terminals: bool = True,
        include_taxiways: bool = False,
        include_aprons: bool = False,
    ) -> dict:
        """
        Fetch airport data from Overpass API.

        Args:
            icao_code: ICAO airport code
            include_gates: Fetch gate nodes
            include_terminals: Fetch terminal buildings
            include_taxiways: Fetch taxiway ways
            include_aprons: Fetch apron areas

        Returns:
            Raw JSON response from Overpass API

        Raises:
            ParseError: If API request fails
        """
        query = self.build_query(
            icao_code,
            include_gates=include_gates,
            include_terminals=include_terminals,
            include_taxiways=include_taxiways,
            include_aprons=include_aprons,
        )

        logger.info(f"Fetching OSM data for {icao_code}")
        logger.debug(f"Overpass query:\n{query}")

        last_error = None
        for endpoint in OVERPASS_ENDPOINTS:
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(
                        endpoint,
                        data={"data": query},
                    )
                    response.raise_for_status()
                    return response.json()
            except httpx.TimeoutException:
                last_error = f"Timeout fetching from {endpoint}"
                logger.warning(last_error)
            except httpx.HTTPStatusError as e:
                last_error = f"HTTP {e.response.status_code} from {endpoint}: {e.response.text}"
                logger.warning(last_error)
            except Exception as e:
                last_error = f"Error fetching from {endpoint}: {e}"
                logger.warning(last_error)

        raise ParseError(f"Failed to fetch OSM data: {last_error}")

    def parse(self, source: Union[str, Path, bytes]) -> OSMDocument:
        """
        Parse OSM data from API response or file.

        Args:
            source: ICAO code (str), file path, or raw JSON bytes

        Returns:
            Parsed OSMDocument

        Raises:
            ParseError: If parsing fails
        """
        # If source is a simple ICAO code (4 letters starting with K for US)
        if isinstance(source, str) and len(source) == 4 and source.isupper():
            data = self.fetch_from_api(source)
        elif isinstance(source, str) and Path(source).exists():
            data = json.loads(Path(source).read_text())
        elif isinstance(source, Path):
            data = json.loads(source.read_text())
        elif isinstance(source, bytes):
            data = json.loads(source.decode("utf-8"))
        else:
            # Assume it's raw JSON string
            data = json.loads(source) if isinstance(source, str) else source

        return self._parse_response(data)

    def _parse_response(self, data: dict) -> OSMDocument:
        """Parse raw Overpass API response into OSMDocument."""
        elements = data.get("elements", [])

        nodes: list[OSMNode] = []
        ways: list[OSMWay] = []

        for elem in elements:
            elem_type = elem.get("type")

            if elem_type == "node":
                node = self._parse_node(elem)
                nodes.append(node)
            elif elem_type == "way":
                way = self._parse_way(elem)
                ways.append(way)

        # Extract ICAO from airport area if available
        icao_code = None

        version = data.get("version", "0.6")
        if not isinstance(version, str):
            version = str(version)

        return OSMDocument(
            version=version,
            generator=data.get("generator", "Overpass API"),
            icao_code=icao_code,
            timestamp=datetime.now(timezone.utc),
            nodes=nodes,
            ways=ways,
        )

    def _parse_node(self, elem: dict) -> OSMNode:
        """Parse a node element."""
        tags = OSMTags(**elem.get("tags", {}))
        return OSMNode(
            id=elem["id"],
            type="node",
            lat=elem["lat"],
            lon=elem["lon"],
            tags=tags,
        )

    def _parse_way(self, elem: dict) -> OSMWay:
        """Parse a way element with geometry."""
        tags = OSMTags(**elem.get("tags", {}))

        # Parse geometry if provided (from 'out geom' query)
        geometry = []
        if "geometry" in elem:
            for pt in elem["geometry"]:
                geometry.append(OSMWayNode(lat=pt["lat"], lon=pt["lon"]))

        return OSMWay(
            id=elem["id"],
            type="way",
            tags=tags,
            nodes=elem.get("nodes", []),
            geometry=geometry,
            bounds=elem.get("bounds"),
        )

    def validate(self, model: OSMDocument) -> list[str]:
        """
        Validate parsed OSM data.

        Args:
            model: Parsed OSMDocument

        Returns:
            List of validation warnings
        """
        warnings = []

        if not model.nodes and not model.ways:
            warnings.append("No OSM elements found for this airport")

        if not model.gates:
            warnings.append("No gate nodes found")

        if not model.terminals:
            warnings.append("No terminal buildings found")

        # Check for gates without reference numbers
        gates_without_ref = [g for g in model.gates if not g.gate_ref]
        if gates_without_ref:
            warnings.append(f"{len(gates_without_ref)} gates missing ref numbers")

        return warnings

    def to_config(self, model: OSMDocument) -> dict:
        """
        Convert OSMDocument to internal configuration.

        Args:
            model: Parsed OSMDocument

        Returns:
            Configuration dictionary for airport config
        """
        from src.formats.osm.converter import OSMConverter

        converter = OSMConverter(self.converter)
        return converter.to_config(model)

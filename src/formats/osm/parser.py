"""
OpenStreetMap Overpass API Parser

Fetches and parses airport data from OpenStreetMap via Overpass API.
"""

import json
import logging
import time
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

# Built-in defaults (used when config file is absent)
_DEFAULT_OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
_DEFAULT_TIMEOUT = 60.0
_DEFAULT_QUERY_TIMEOUT = 55
_DEFAULT_RETRY_COUNT = 1
_DEFAULT_RETRY_DELAY = 2.0


def _load_overpass_config() -> dict:
    """Load Overpass API config from config/overpass_api.json, falling back to built-in defaults."""
    config_candidates = [
        Path(__file__).resolve().parents[3] / "config" / "overpass_api.json",
        Path.cwd() / "config" / "overpass_api.json",
    ]
    for path in config_candidates:
        if path.is_file():
            try:
                with open(path) as f:
                    cfg = json.load(f)
                logger.debug(f"Loaded Overpass config from {path}")
                return cfg
            except Exception as e:
                logger.warning(f"Failed to load Overpass config from {path}: {e}")
    return {}


_overpass_cfg = _load_overpass_config()

OVERPASS_ENDPOINTS: list[str] = _overpass_cfg.get("endpoints", _DEFAULT_OVERPASS_ENDPOINTS)
DEFAULT_TIMEOUT: float = _overpass_cfg.get("timeout_seconds", _DEFAULT_TIMEOUT)
QUERY_TIMEOUT: int = _overpass_cfg.get("query_timeout_seconds", _DEFAULT_QUERY_TIMEOUT)
RETRY_COUNT: int = _overpass_cfg.get("retry_count", _DEFAULT_RETRY_COUNT)
RETRY_DELAY: float = _overpass_cfg.get("retry_delay_seconds", _DEFAULT_RETRY_DELAY)


class OSMParser(AirportFormatParser[OSMDocument]):
    """
    Parser for OpenStreetMap airport data via Overpass API.

    Fetches gates, terminals, and other aeroway features for an airport.
    """

    def __init__(
        self,
        converter: CoordinateConverter | None = None,
        timeout: float | None = None,
    ):
        """
        Initialize OSM parser.

        Args:
            converter: Coordinate converter (auto-created from airport data)
            timeout: API request timeout in seconds (defaults to module-level DEFAULT_TIMEOUT)
        """
        super().__init__(converter)
        self.timeout = timeout if timeout is not None else DEFAULT_TIMEOUT

    def build_query(
        self,
        icao_code: str,
        include_gates: bool = True,
        include_terminals: bool = True,
        include_taxiways: bool = False,
        include_aprons: bool = False,
        include_runways: bool = False,
        include_hangars: bool = False,
        include_helipads: bool = False,
        include_parking_positions: bool = False,
    ) -> str:
        """
        Build Overpass QL query for airport features.

        Args:
            icao_code: ICAO airport code (e.g., "KSFO")
            include_gates: Fetch gate nodes
            include_terminals: Fetch terminal buildings
            include_taxiways: Fetch taxiway ways
            include_aprons: Fetch apron areas
            include_runways: Fetch runway ways
            include_hangars: Fetch hangar buildings
            include_helipads: Fetch helipad nodes/ways
            include_parking_positions: Fetch parking position nodes

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

        if include_runways:
            selectors.append('way["aeroway"="runway"](area.airport);')

        if include_hangars:
            selectors.append('way["aeroway"="hangar"](area.airport);')
            selectors.append('way["building"="hangar"](area.airport);')

        if include_helipads:
            selectors.append('node["aeroway"="helipad"](area.airport);')
            selectors.append('way["aeroway"="helipad"](area.airport);')

        if include_parking_positions:
            selectors.append('node["aeroway"="parking_position"](area.airport);')

        features = "\n  ".join(selectors)

        # Include airport area itself to get name/iata metadata
        query = f"""[out:json][timeout:{QUERY_TIMEOUT}];
area["icao"="{icao_code}"]->.airport;
(
  way["icao"="{icao_code}"]["aeroway"="aerodrome"];
  relation["icao"="{icao_code}"]["aeroway"="aerodrome"];
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
        include_runways: bool = False,
        include_hangars: bool = False,
        include_helipads: bool = False,
        include_parking_positions: bool = False,
    ) -> dict:
        """
        Fetch airport data from Overpass API.

        Args:
            icao_code: ICAO airport code
            include_gates: Fetch gate nodes
            include_terminals: Fetch terminal buildings
            include_taxiways: Fetch taxiway ways
            include_aprons: Fetch apron areas
            include_runways: Fetch runway ways
            include_hangars: Fetch hangar buildings
            include_helipads: Fetch helipad nodes/ways
            include_parking_positions: Fetch parking position nodes

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
            include_runways=include_runways,
            include_hangars=include_hangars,
            include_helipads=include_helipads,
            include_parking_positions=include_parking_positions,
        )

        logger.info(f"Fetching OSM data for {icao_code}")
        logger.debug(f"Overpass query:\n{query}")

        last_error = None
        max_retries = RETRY_COUNT
        retry_delay = RETRY_DELAY

        for endpoint in OVERPASS_ENDPOINTS:
            for attempt in range(max_retries + 1):
                try:
                    with httpx.Client(timeout=self.timeout) as client:
                        response = client.post(
                            endpoint,
                            data={"data": query},
                        )
                        response.raise_for_status()
                        return response.json()
                except httpx.TimeoutException:
                    last_error = f"Timeout fetching from {endpoint} (attempt {attempt + 1})"
                    logger.warning(last_error)
                except httpx.HTTPStatusError as e:
                    last_error = f"HTTP {e.response.status_code} from {endpoint} (attempt {attempt + 1}): {e.response.text}"
                    logger.warning(last_error)
                except Exception as e:
                    last_error = f"Error fetching from {endpoint} (attempt {attempt + 1}): {e}"
                    logger.warning(last_error)

                if attempt < max_retries:
                    logger.info(f"Retrying {endpoint} in {retry_delay}s...")
                    time.sleep(retry_delay)

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

        # Airport metadata from aerodrome element
        icao_code = None
        iata_code = None
        airport_name = None
        airport_operator = None

        for elem in elements:
            elem_type = elem.get("type")
            tags = elem.get("tags", {})

            # Check if this is the aerodrome (airport boundary/metadata)
            if tags.get("aeroway") == "aerodrome":
                icao_code = tags.get("icao")
                iata_code = tags.get("iata")
                airport_name = tags.get("name")
                airport_operator = tags.get("operator")

            if elem_type == "node":
                node = self._parse_node(elem)
                nodes.append(node)
            elif elem_type == "way":
                way = self._parse_way(elem)
                ways.append(way)

        version = data.get("version", "0.6")
        if not isinstance(version, str):
            version = str(version)

        return OSMDocument(
            version=version,
            generator=data.get("generator", "Overpass API"),
            icao_code=icao_code,
            iata_code=iata_code,
            airport_name=airport_name,
            airport_operator=airport_operator,
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

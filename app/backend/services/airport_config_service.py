"""
Airport Configuration Service

Manages airport configuration state and handles format imports.
Coordinates between format parsers and the configuration cache.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import logging

from src.formats.base import CoordinateConverter, ParseError, ValidationError

logger = logging.getLogger(__name__)


class AirportConfigService:
    """
    Service for managing airport configuration.

    Handles import from various formats (AIXM, IFC, AIDM) and maintains
    the current airport configuration state.
    """

    def __init__(self):
        """Initialize service with default configuration."""
        self._current_config: dict[str, Any] = {}
        self._last_updated: Optional[datetime] = None
        self._converter = CoordinateConverter(
            reference_lat=37.6213,  # SFO
            reference_lon=-122.379,
            reference_alt=4.0,
        )

    def get_config(self) -> dict[str, Any]:
        """
        Get current airport configuration.

        Returns:
            Current configuration or empty dict if not loaded
        """
        return self._current_config

    def get_last_updated(self) -> Optional[datetime]:
        """Get timestamp of last configuration update."""
        return self._last_updated

    def set_reference_point(self, lat: float, lon: float, alt: float = 0.0) -> None:
        """
        Update the coordinate reference point.

        Args:
            lat: Reference latitude
            lon: Reference longitude
            alt: Reference altitude in meters
        """
        self._converter = CoordinateConverter(
            reference_lat=lat,
            reference_lon=lon,
            reference_alt=alt,
        )

    def import_aixm(
        self,
        content: bytes,
        merge: bool = True,
    ) -> tuple[dict[str, Any], list[str]]:
        """
        Import AIXM data.

        Args:
            content: AIXM XML content
            merge: Whether to merge with existing config

        Returns:
            Tuple of (imported config, warnings)

        Raises:
            ParseError: If parsing fails
            ValidationError: If validation fails
        """
        from src.formats.aixm import AIXMParser

        parser = AIXMParser(self._converter)
        doc = parser.parse(content)
        warnings = parser.validate(doc)
        config = parser.to_config(doc)

        if merge and self._current_config:
            from src.formats.aixm.converter import merge_aixm_config
            config = merge_aixm_config(self._current_config, config)

        self._current_config = config
        self._last_updated = datetime.now(timezone.utc)

        return config, warnings

    def import_ifc(
        self,
        content: bytes,
        merge: bool = True,
        include_geometry: bool = False,
    ) -> tuple[dict[str, Any], list[str]]:
        """
        Import IFC data.

        Args:
            content: IFC file content
            merge: Whether to merge with existing config
            include_geometry: Whether to extract detailed geometry

        Returns:
            Tuple of (imported config, warnings)

        Raises:
            ParseError: If parsing fails (or ifcopenshell not installed)
        """
        from src.formats.ifc import IFCParser, IFCOPENSHELL_AVAILABLE

        if not IFCOPENSHELL_AVAILABLE:
            raise ParseError(
                "IFC import requires ifcopenshell. "
                "Install with: pip install ifcopenshell"
            )

        parser = IFCParser(
            self._converter,
            include_geometry=include_geometry,
        )
        doc = parser.parse(content)
        warnings = parser.validate(doc)
        config = parser.to_config(doc)

        if merge and self._current_config:
            from src.formats.ifc.converter import merge_ifc_config
            config = merge_ifc_config(self._current_config, config)

        # Update config with IFC buildings
        if "buildings" not in self._current_config:
            self._current_config["buildings"] = []
        self._current_config["buildings"].extend(config.get("buildings", []))
        self._current_config["ifc_elements"] = config.get("elements", [])

        self._last_updated = datetime.utcnow()

        return config, warnings

    def import_aidm(
        self,
        content: bytes | str,
        local_airport: str = "SFO",
    ) -> tuple[dict[str, Any], list[str]]:
        """
        Import AIDM operational data.

        Args:
            content: AIDM JSON or XML content
            local_airport: Local airport code for context

        Returns:
            Tuple of (imported config, warnings)

        Raises:
            ParseError: If parsing fails
        """
        from src.formats.aidm import AIDMParser

        parser = AIDMParser(self._converter, local_airport=local_airport)

        if isinstance(content, bytes):
            content = content.decode("utf-8")

        doc = parser.parse(content)
        warnings = parser.validate(doc)
        config = parser.to_config(doc)

        # AIDM provides flight data, not geometry
        # Store separately from airport config
        self._current_config["aidm_flights"] = config.get("flights", [])
        self._current_config["aidm_scheduled"] = config.get("scheduled_flights", [])
        self._current_config["aidm_resources"] = config.get("resources", [])
        self._current_config["aidm_events"] = config.get("events", [])

        self._last_updated = datetime.now(timezone.utc)

        return config, warnings

    def import_osm(
        self,
        icao_code: str,
        include_gates: bool = True,
        include_terminals: bool = True,
        include_taxiways: bool = False,
        include_aprons: bool = False,
        merge: bool = True,
    ) -> tuple[dict[str, Any], list[str]]:
        """
        Import airport data from OpenStreetMap via Overpass API.

        Fetches gates, terminals, and other aeroway features for the
        specified airport and converts them to internal format.

        Args:
            icao_code: ICAO airport code (e.g., "KSFO")
            include_gates: Fetch gate nodes
            include_terminals: Fetch terminal buildings
            include_taxiways: Fetch taxiway ways
            include_aprons: Fetch apron areas
            merge: Whether to merge with existing config

        Returns:
            Tuple of (imported config, warnings)

        Raises:
            ParseError: If API request or parsing fails
        """
        from src.formats.osm import OSMParser, merge_osm_config

        parser = OSMParser(self._converter)

        # Fetch and parse from Overpass API
        data = parser.fetch_from_api(
            icao_code,
            include_gates=include_gates,
            include_terminals=include_terminals,
            include_taxiways=include_taxiways,
            include_aprons=include_aprons,
        )
        doc = parser._parse_response(data)
        doc.icao_code = icao_code

        warnings = parser.validate(doc)
        config = parser.to_config(doc)
        config["icaoCode"] = icao_code

        if merge and self._current_config:
            config = merge_osm_config(self._current_config, config)

        self._current_config = config
        self._last_updated = datetime.now(timezone.utc)

        return config, warnings

    def import_faa(
        self,
        facility_id: str,
        merge: bool = True,
    ) -> tuple[dict[str, Any], list[str]]:
        """
        Import FAA runway data for a US airport.

        Args:
            facility_id: FAA facility ID (e.g., "SFO" or "KSFO")
            merge: Whether to merge with existing config

        Returns:
            Tuple of (imported config, warnings)
        """
        from src.formats.faa import FAADataFetcher, merge_faa_config

        fetcher = FAADataFetcher()
        runways = fetcher.fetch_airport_runways(facility_id)

        warnings = []
        if not runways:
            warnings.append(f"No runway data found for {facility_id}")

        config = fetcher.runways_to_aixm_config(runways, self._converter)

        if merge and self._current_config:
            config = merge_faa_config(self._current_config, config)

        if runways:
            self._current_config = config
            self._last_updated = datetime.now(timezone.utc)

        return config, warnings

    def clear_config(self) -> None:
        """Clear current configuration."""
        self._current_config = {}
        self._last_updated = None

    def get_element_counts(self) -> dict[str, int]:
        """
        Get counts of different element types in current config.

        Returns:
            Dictionary of element type to count
        """
        return {
            "runways": len(self._current_config.get("runways", [])),
            "taxiways": len(self._current_config.get("taxiways", [])),
            "buildings": len(self._current_config.get("buildings", [])),
            "aprons": len(self._current_config.get("aprons", [])),
            "navaids": len(self._current_config.get("navaids", [])),
            "ifc_elements": len(self._current_config.get("ifc_elements", [])),
            "aidm_flights": len(self._current_config.get("aidm_flights", [])),
            "gates": len(self._current_config.get("gates", [])),
            "terminals": len(self._current_config.get("terminals", [])),
        }


# Singleton instance
_service_instance: Optional[AirportConfigService] = None


def get_airport_config_service() -> AirportConfigService:
    """Get the airport configuration service singleton."""
    global _service_instance
    if _service_instance is None:
        _service_instance = AirportConfigService()
    return _service_instance

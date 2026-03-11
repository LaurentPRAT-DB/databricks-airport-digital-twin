"""
Airport Configuration Service

Manages airport configuration state and handles format imports.
Coordinates between format parsers and the configuration cache.
Supports persistence to Unity Catalog tables for fast loading.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import logging

from src.formats.base import CoordinateConverter, ParseError, ValidationError

logger = logging.getLogger(__name__)

# Default airport to load on startup
DEFAULT_AIRPORT = "KSFO"


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
        self._config_ready: bool = False
        self._taxiway_graph: Optional[Any] = None
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

    @property
    def config_ready(self) -> bool:
        """Whether airport config has been successfully loaded."""
        return self._config_ready

    @property
    def taxiway_graph(self):
        """TaxiwayGraph instance, or None if not built yet."""
        return self._taxiway_graph

    def _build_taxiway_graph(self) -> None:
        """Build taxiway routing graph from current config."""
        try:
            from src.routing.taxiway_graph import TaxiwayGraph
            graph = TaxiwayGraph()
            graph.build_from_config(self._current_config)
            if graph.nodes:
                self._taxiway_graph = graph
                logger.info("Taxiway graph built: %d nodes", len(graph.nodes))
            else:
                self._taxiway_graph = None
        except Exception as e:
            logger.warning("Failed to build taxiway graph: %s", e)
            self._taxiway_graph = None

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
        include_runways: bool = False,
        include_hangars: bool = False,
        include_helipads: bool = False,
        include_parking_positions: bool = False,
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
            include_runways: Fetch runway ways
            include_hangars: Fetch hangar buildings
            include_helipads: Fetch helipad nodes/ways
            include_parking_positions: Fetch parking position nodes
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
            include_runways=include_runways,
            include_hangars=include_hangars,
            include_helipads=include_helipads,
            include_parking_positions=include_parking_positions,
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
        self._config_ready = True
        self._build_taxiway_graph()

        # Auto-persist to lakehouse
        self.persist_config(icao_code)

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
            # Auto-persist to lakehouse
            self.persist_config()

        return config, warnings

    def clear_config(self) -> None:
        """Clear current configuration."""
        self._current_config = {}
        self._last_updated = None
        self._config_ready = False
        self._taxiway_graph = None

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
            "osmTaxiways": len(self._current_config.get("osmTaxiways", [])),
            "osmAprons": len(self._current_config.get("osmAprons", [])),
            "osmRunways": len(self._current_config.get("osmRunways", [])),
            "osmHangars": len(self._current_config.get("osmHangars", [])),
            "osmHelipads": len(self._current_config.get("osmHelipads", [])),
            "osmParkingPositions": len(self._current_config.get("osmParkingPositions", [])),
        }

    # =========================================================================
    # Persistence Operations
    # =========================================================================

    def persist_config(self, icao_code: Optional[str] = None) -> bool:
        """
        Persist current configuration to Unity Catalog tables.

        Args:
            icao_code: ICAO code to use (defaults to current config's code)

        Returns:
            True if successful, False if persistence unavailable
        """
        if not self._current_config:
            logger.warning("No configuration to persist")
            return False

        icao = icao_code or self._current_config.get("icaoCode")
        if not icao:
            logger.warning("No ICAO code available for persistence")
            return False

        try:
            from src.persistence import get_airport_repository
            repo = get_airport_repository()
            repo.save_airport_config(icao, self._current_config)
            logger.info(f"Persisted airport config for {icao} to lakehouse")
            return True
        except ImportError:
            logger.warning("Persistence module not available")
            return False
        except Exception as e:
            logger.error(f"Failed to persist airport config: {e}")
            return False

    def load_from_lakehouse(self, icao_code: str) -> bool:
        """
        Load airport configuration from Unity Catalog tables.

        Args:
            icao_code: ICAO airport code to load

        Returns:
            True if loaded successfully, False otherwise
        """
        try:
            from src.persistence import get_airport_repository
            repo = get_airport_repository()

            config = repo.load_airport_config(icao_code)
            if config:
                self._current_config = config
                self._last_updated = datetime.now(timezone.utc)
                self._config_ready = True
                self._build_taxiway_graph()
                logger.info(f"Loaded airport config for {icao_code} from lakehouse")
                return True
            else:
                logger.info(f"Airport {icao_code} not found in lakehouse")
                return False
        except ImportError:
            logger.warning("Persistence module not available")
            return False
        except Exception as e:
            logger.error(f"Failed to load from lakehouse: {e}")
            return False

    def list_persisted_airports(self) -> list[dict]:
        """
        List all airports persisted in the lakehouse.

        Returns:
            List of airport metadata dictionaries
        """
        try:
            from src.persistence import get_airport_repository
            repo = get_airport_repository()
            return repo.list_airports()
        except ImportError:
            return []
        except Exception as e:
            logger.error(f"Failed to list airports: {e}")
            return []

    def delete_persisted_airport(self, icao_code: str) -> bool:
        """
        Delete an airport from the lakehouse.

        Args:
            icao_code: ICAO code of airport to delete

        Returns:
            True if successful
        """
        try:
            from src.persistence import get_airport_repository
            repo = get_airport_repository()
            return repo.delete_airport(icao_code)
        except ImportError:
            return False
        except Exception as e:
            logger.error(f"Failed to delete airport: {e}")
            return False

    def save_to_lakebase_cache(self, icao_code: str) -> bool:
        """
        Write current config to Lakebase cache for fast startup.

        Args:
            icao_code: ICAO airport code

        Returns:
            True if successful
        """
        if not self._current_config:
            return False

        try:
            from app.backend.services.lakebase_service import get_lakebase_service
            lakebase = get_lakebase_service()
            return lakebase.upsert_airport_config(icao_code, self._current_config)
        except Exception as e:
            logger.warning(f"Failed to cache config in Lakebase: {e}")
            return False

    def load_from_lakebase_cache(self, icao_code: str) -> bool:
        """
        Load airport config from Lakebase cache.

        Args:
            icao_code: ICAO airport code

        Returns:
            True if loaded successfully
        """
        try:
            from app.backend.services.lakebase_service import get_lakebase_service
            lakebase = get_lakebase_service()
            config = lakebase.get_airport_config(icao_code)
            if config:
                self._current_config = config
                self._last_updated = datetime.now(timezone.utc)
                self._config_ready = True
                self._build_taxiway_graph()
                logger.info(f"Loaded airport config for {icao_code} from Lakebase cache")
                return True
            return False
        except Exception as e:
            logger.warning(f"Lakebase cache load failed: {e}")
            return False

    def initialize_from_lakehouse(
        self,
        icao_code: str = DEFAULT_AIRPORT,
        fallback_to_osm: bool = True,
    ) -> str | bool:
        """
        Initialize configuration with 3-tier loading:
        1. Lakebase cache (<10ms)
        2. Unity Catalog (30-60s)
        3. OSM fallback (external API)

        Args:
            icao_code: ICAO code to load
            fallback_to_osm: If True, fetch from OSM as last resort

        Returns:
            Source string ("lakebase_cache", "unity_catalog", "osm_api") on success,
            False on failure. Also truthy for backward compat.
        """
        # Tier 1: Lakebase cache (fastest)
        logger.info(f"Tier 1: Trying Lakebase cache for {icao_code}...")
        if self.load_from_lakebase_cache(icao_code):
            logger.info(f"Loaded {icao_code} from Lakebase cache (Tier 1)")
            return "lakebase_cache"

        # Tier 2: Unity Catalog (SQL Warehouse)
        logger.info(f"Tier 2: Trying Unity Catalog for {icao_code}...")
        if self.load_from_lakehouse(icao_code):
            # Write-through to Lakebase for next startup
            self.save_to_lakebase_cache(icao_code)
            logger.info(f"Loaded {icao_code} from Unity Catalog (Tier 2)")
            return "unity_catalog"

        # Tier 3: OSM fallback
        if fallback_to_osm:
            logger.info(f"Tier 3: Falling back to OSM Overpass API for {icao_code}...")
            try:
                self.import_osm(
                    icao_code,
                    include_gates=True,
                    include_terminals=True,
                    include_taxiways=True,
                    include_aprons=True,
                    include_runways=True,
                    include_hangars=True,
                    include_helipads=True,
                    include_parking_positions=True,
                    merge=False,
                )

                # For US airports, also import FAA runway data
                if icao_code.startswith("K"):
                    try:
                        self.import_faa(icao_code, merge=True)
                        logger.info(f"Imported FAA runway data for {icao_code}")
                    except Exception as e:
                        logger.warning(f"FAA import failed for {icao_code}: {e}")

                # Persist to both Unity Catalog and Lakebase cache
                self.persist_config(icao_code)
                self.save_to_lakebase_cache(icao_code)
                logger.info(f"Loaded {icao_code} from OSM Overpass API (Tier 3)")
                return "osm_api"
            except Exception as e:
                logger.error(f"OSM fallback failed: {e}")
                return False

        return False


# Singleton instance
_service_instance: Optional[AirportConfigService] = None


def get_airport_config_service() -> AirportConfigService:
    """Get the airport configuration service singleton."""
    global _service_instance
    if _service_instance is None:
        _service_instance = AirportConfigService()
    return _service_instance

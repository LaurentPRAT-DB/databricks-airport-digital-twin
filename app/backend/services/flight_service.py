"""Flight service with cascading data source strategy.

Data source priority:
1. Lakebase (PostgreSQL) - <10ms latency, best for real-time serving
2. Delta tables (Databricks SQL) - ~100ms latency, direct from Gold layer
3. Synthetic fallback - Always available for demos without backend
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional

from src.ingestion.fallback import generate_synthetic_flights
from app.backend.models.flight import FlightPosition, FlightListResponse
from app.backend.services.lakebase_service import get_lakebase_service
from app.backend.services.delta_service import get_delta_service

logger = logging.getLogger(__name__)


def _determine_flight_phase(
    altitude: float, vertical_rate: float, on_ground: bool
) -> str:
    """Determine the flight phase based on flight parameters."""
    if on_ground:
        return "ground"
    if altitude < 3000 and vertical_rate > 2:
        return "takeoff"
    if altitude < 3000 and vertical_rate < -2:
        return "landing"
    if vertical_rate > 2:
        return "climb"
    if vertical_rate < -2:
        return "descent"
    return "cruise"


def _dict_to_flight_position(data: dict, source: str) -> FlightPosition:
    """Convert a dictionary from Lakebase/Delta to FlightPosition model."""
    altitude = data.get("altitude") or 0.0
    vertical_rate = data.get("vertical_rate") or 0.0
    on_ground = data.get("on_ground", False)

    return FlightPosition(
        icao24=data["icao24"],
        callsign=data.get("callsign"),
        latitude=data.get("latitude"),
        longitude=data.get("longitude"),
        altitude=altitude,
        velocity=data.get("velocity"),
        heading=data.get("heading"),
        on_ground=on_ground,
        vertical_rate=vertical_rate,
        last_seen=data.get("last_seen"),
        data_source=source,
        flight_phase=data.get("flight_phase") or _determine_flight_phase(
            altitude, vertical_rate, on_ground
        ),
    )


class FlightService:
    """Service for managing flight data retrieval with cascading sources."""

    def __init__(self):
        """Initialize the flight service with data source services."""
        self._lakebase = get_lakebase_service()
        self._delta = get_delta_service()
        self._cache: Optional[FlightListResponse] = None
        self._use_mock = os.getenv("USE_MOCK_BACKEND", "true").lower() == "true"

    async def get_flights(self, count: int = 50) -> FlightListResponse:
        """
        Get current flight positions using cascading data sources.

        Priority:
        1. Lakebase (PostgreSQL) - fastest, <10ms
        2. Delta tables (Databricks SQL) - ~100ms
        3. Synthetic fallback - always available

        Args:
            count: Number of flights to retrieve.

        Returns:
            FlightListResponse with flight positions.
        """
        flights = []
        data_source = "synthetic"

        # Skip real backends if mock mode is enabled
        if not self._use_mock:
            # Try Lakebase first (lowest latency)
            lakebase_data = self._lakebase.get_flights(limit=count)
            if lakebase_data:
                logger.info("Serving flights from Lakebase")
                flights = [
                    _dict_to_flight_position(d, "lakebase") for d in lakebase_data
                ]
                data_source = "live"

            # Fall back to Delta tables
            if not flights:
                delta_data = self._delta.get_flights(limit=count)
                if delta_data:
                    logger.info("Serving flights from Delta tables")
                    flights = [
                        _dict_to_flight_position(d, "delta") for d in delta_data
                    ]
                    data_source = "live"

        # Fall back to synthetic data
        if not flights:
            logger.info("Serving synthetic flights (fallback)")
            flights = self._generate_synthetic_flights(count)
            data_source = "synthetic"

        response = FlightListResponse(
            flights=flights,
            count=len(flights),
            timestamp=datetime.now(timezone.utc),
            data_source=data_source,
        )

        self._cache = response
        return response

    def _generate_synthetic_flights(self, count: int) -> list[FlightPosition]:
        """Generate synthetic flight data using the fallback module."""
        raw_data = generate_synthetic_flights(count=count)

        flights = []
        for state in raw_data.get("states", []):
            altitude = state[7] if state[7] is not None else 0.0
            vertical_rate = state[11] if state[11] is not None else 0.0
            on_ground = state[8] if state[8] is not None else False

            flight = FlightPosition(
                icao24=state[0],
                callsign=state[1].strip() if state[1] else None,
                latitude=state[6],
                longitude=state[5],
                altitude=altitude,
                velocity=state[9],
                heading=state[10],
                on_ground=on_ground,
                vertical_rate=vertical_rate,
                last_seen=state[4],
                data_source="synthetic",
                flight_phase=_determine_flight_phase(altitude, vertical_rate, on_ground),
            )
            flights.append(flight)

        return flights

    async def get_flight_by_icao24(self, icao24: str) -> Optional[FlightPosition]:
        """
        Get a specific flight by ICAO24 address.

        Args:
            icao24: The ICAO24 address to search for.

        Returns:
            FlightPosition if found, None otherwise.
        """
        if not self._use_mock:
            # Try Lakebase first
            lakebase_data = self._lakebase.get_flight_by_icao24(icao24)
            if lakebase_data:
                return _dict_to_flight_position(lakebase_data, "lakebase")

            # Try Delta tables
            delta_data = self._delta.get_flight_by_icao24(icao24)
            if delta_data:
                return _dict_to_flight_position(delta_data, "delta")

        # Check cache for synthetic data
        if self._cache is None:
            await self.get_flights()

        if self._cache:
            for flight in self._cache.flights:
                if flight.icao24 == icao24:
                    return flight

        return None

    def get_data_sources_status(self) -> dict:
        """Get status of all data sources."""
        return {
            "lakebase": {
                "available": self._lakebase.is_available,
                "healthy": self._lakebase.health_check() if self._lakebase.is_available else False,
            },
            "delta": {
                "available": self._delta.is_available,
                "healthy": self._delta.health_check() if self._delta.is_available else False,
            },
            "synthetic": {
                "available": True,
                "healthy": True,
            },
            "mock_mode": self._use_mock,
        }


# Singleton instance
_flight_service: Optional[FlightService] = None


def get_flight_service() -> FlightService:
    """
    Dependency function for FastAPI injection.

    Returns:
        FlightService singleton instance.
    """
    global _flight_service
    if _flight_service is None:
        _flight_service = FlightService()
    return _flight_service

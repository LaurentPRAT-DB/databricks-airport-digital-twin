"""Schedule service for FIDS (Flight Information Display System).

Provides arrivals and departures schedule data.
Reads from Lakebase first for persistence, falls back to generator.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.ingestion.schedule_generator import (
    get_cached_schedule,
    get_arrivals,
    get_departures,
)
from app.backend.models.schedule import (
    ScheduledFlight,
    FlightStatus,
    FlightType,
    ScheduleResponse,
)
from app.backend.services.lakebase_service import get_lakebase_service

logger = logging.getLogger(__name__)


def _dict_to_scheduled_flight(data: dict) -> ScheduledFlight:
    """Convert schedule dictionary to ScheduledFlight model."""
    return ScheduledFlight(
        flight_number=data["flight_number"],
        airline=data["airline"],
        airline_code=data["airline_code"],
        origin=data["origin"],
        destination=data["destination"],
        scheduled_time=datetime.fromisoformat(data["scheduled_time"]),
        estimated_time=datetime.fromisoformat(data["estimated_time"]) if data.get("estimated_time") else None,
        actual_time=datetime.fromisoformat(data["actual_time"]) if data.get("actual_time") else None,
        gate=data.get("gate"),
        status=FlightStatus(data["status"]),
        delay_minutes=data.get("delay_minutes", 0),
        delay_reason=data.get("delay_reason"),
        aircraft_type=data.get("aircraft_type"),
        flight_type=FlightType(data["flight_type"]),
    )


class ScheduleService:
    """Service for flight schedule operations."""

    def __init__(self, airport: str = "SFO", airport_icao: str = "KSFO"):
        """Initialize schedule service."""
        self._airport = airport
        self._airport_icao = airport_icao

    def set_airport(self, airport: str, airport_icao: str) -> None:
        """Update the current airport for schedule queries."""
        self._airport = airport
        self._airport_icao = airport_icao

    def get_arrivals(
        self,
        hours_ahead: int = 2,
        hours_behind: int = 1,
        limit: int = 50,
    ) -> ScheduleResponse:
        """
        Get arrival flights for the specified time window.

        Reads from Lakebase first for persistence, falls back to generator.

        Args:
            hours_ahead: Hours into future to include
            hours_behind: Hours into past to include
            limit: Maximum flights to return

        Returns:
            ScheduleResponse with arrival flights
        """
        # Try Lakebase first (persisted data)
        lakebase = get_lakebase_service()
        raw_arrivals = None

        if lakebase.is_available:
            raw_arrivals = lakebase.get_schedule(
                flight_type="arrival",
                hours_behind=hours_behind,
                hours_ahead=hours_ahead,
                limit=limit,
                airport_icao=self._airport_icao,
            )
            if raw_arrivals:
                logger.debug(f"Schedule arrivals from Lakebase: {len(raw_arrivals)}")

        # Fallback to generator
        if not raw_arrivals:
            logger.debug("Schedule arrivals from generator")
            raw_arrivals = get_arrivals(
                airport=self._airport,
                hours_ahead=hours_ahead,
                hours_behind=hours_behind,
            )[:limit]

        flights = [_dict_to_scheduled_flight(f) for f in raw_arrivals]

        logger.info(f"Schedule service returning {len(flights)} arrivals")

        return ScheduleResponse(
            flights=flights,
            count=len(flights),
            airport=self._airport,
            flight_type=FlightType.ARRIVAL,
        )

    def get_departures(
        self,
        hours_ahead: int = 2,
        hours_behind: int = 1,
        limit: int = 50,
    ) -> ScheduleResponse:
        """
        Get departure flights for the specified time window.

        Reads from Lakebase first for persistence, falls back to generator.

        Args:
            hours_ahead: Hours into future to include
            hours_behind: Hours into past to include
            limit: Maximum flights to return

        Returns:
            ScheduleResponse with departure flights
        """
        # Try Lakebase first (persisted data)
        lakebase = get_lakebase_service()
        raw_departures = None

        if lakebase.is_available:
            raw_departures = lakebase.get_schedule(
                flight_type="departure",
                hours_behind=hours_behind,
                hours_ahead=hours_ahead,
                limit=limit,
                airport_icao=self._airport_icao,
            )
            if raw_departures:
                logger.debug(f"Schedule departures from Lakebase: {len(raw_departures)}")

        # Fallback to generator
        if not raw_departures:
            logger.debug("Schedule departures from generator")
            raw_departures = get_departures(
                airport=self._airport,
                hours_ahead=hours_ahead,
                hours_behind=hours_behind,
            )[:limit]

        flights = [_dict_to_scheduled_flight(f) for f in raw_departures]

        logger.info(f"Schedule service returning {len(flights)} departures")

        return ScheduleResponse(
            flights=flights,
            count=len(flights),
            airport=self._airport,
            flight_type=FlightType.DEPARTURE,
        )

    def get_flight_by_number(self, flight_number: str) -> Optional[ScheduledFlight]:
        """
        Get a specific flight by flight number.

        Args:
            flight_number: Flight number to search for

        Returns:
            ScheduledFlight if found, None otherwise
        """
        schedule = get_cached_schedule(airport=self._airport)
        for flight in schedule:
            if flight["flight_number"] == flight_number:
                return _dict_to_scheduled_flight(flight)
        return None


# Singleton instance
_schedule_service: Optional[ScheduleService] = None


def get_schedule_service() -> ScheduleService:
    """Get or create schedule service singleton."""
    global _schedule_service
    if _schedule_service is None:
        _schedule_service = ScheduleService()
    return _schedule_service

"""Schedule service for FIDS (Flight Information Display System).

Provides arrivals and departures schedule data.
Reads from Lakebase first, falls back to live synthetic flight states,
then to the independent schedule generator as a last resort.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.ingestion.schedule_generator import (
    get_cached_schedule,
    get_arrivals,
    get_departures,
    get_future_schedule,
    invalidate_schedule_cache,
)
from src.ingestion.fallback import get_flights_as_schedule
from app.backend.models.schedule import (
    ScheduledFlight,
    FlightStatus,
    FlightType,
    ScheduleResponse,
)
from app.backend.services.lakebase_service import get_lakebase_service

logger = logging.getLogger(__name__)


def _parse_datetime(val) -> datetime:
    """Parse a datetime value that may be a string or already a datetime object."""
    if isinstance(val, datetime):
        return val
    return datetime.fromisoformat(val)


def _dict_to_scheduled_flight(data: dict) -> ScheduledFlight:
    """Convert schedule dictionary to ScheduledFlight model."""
    return ScheduledFlight(
        flight_number=data["flight_number"],
        airline=data["airline"],
        airline_code=data["airline_code"],
        origin=data["origin"],
        destination=data["destination"],
        scheduled_time=_parse_datetime(data["scheduled_time"]),
        estimated_time=_parse_datetime(data["estimated_time"]) if data.get("estimated_time") else None,
        actual_time=_parse_datetime(data["actual_time"]) if data.get("actual_time") else None,
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
        invalidate_schedule_cache()

    def get_arrivals(
        self,
        hours_ahead: int = 2,
        hours_behind: int = 1,
        limit: int = 50,
    ) -> ScheduleResponse:
        """
        Get arrival flights for the specified time window.

        Always includes live sim flights (matching the map), supplemented
        by Lakebase persisted data or the schedule generator.

        Args:
            hours_ahead: Hours into future to include
            hours_behind: Hours into past to include
            limit: Maximum flights to return

        Returns:
            ScheduleResponse with arrival flights
        """
        raw_arrivals = self._get_merged_schedule("arrival", hours_ahead, hours_behind, limit)
        flights = [_dict_to_scheduled_flight(f) for f in raw_arrivals[:limit]]

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

        Always includes live sim flights (matching the map), supplemented
        by Lakebase persisted data or the schedule generator.

        Args:
            hours_ahead: Hours into future to include
            hours_behind: Hours into past to include
            limit: Maximum flights to return

        Returns:
            ScheduleResponse with departure flights
        """
        raw_departures = self._get_merged_schedule("departure", hours_ahead, hours_behind, limit)
        flights = [_dict_to_scheduled_flight(f) for f in raw_departures[:limit]]

        logger.info(f"Schedule service returning {len(flights)} departures")

        return ScheduleResponse(
            flights=flights,
            count=len(flights),
            airport=self._airport,
            flight_type=FlightType.DEPARTURE,
        )

    def _get_merged_schedule(
        self,
        flight_type: str,
        hours_ahead: int,
        hours_behind: int,
        limit: int,
    ) -> list[dict]:
        """Get schedule merging live sim flights with background schedule data.

        Live flights (from the simulation) always take priority since they
        match what the user sees on the map. Background data (Lakebase or
        schedule generator) fills out the rest of the FIDS.

        Args:
            flight_type: "arrival" or "departure"
            hours_ahead: Hours into future to include
            hours_behind: Hours into past to include
            limit: Maximum total flights to return

        Returns:
            Merged, deduplicated, sorted list of flight dicts
        """
        # 1. Always get live flights first (same data as map)
        live_schedule = get_flights_as_schedule()
        live_flights = [f for f in live_schedule if f["flight_type"] == flight_type]
        if live_flights:
            logger.debug(f"FIDS {flight_type}s: {len(live_flights)} live flights from map")

        # 2. Get background schedule data (Lakebase or generator)
        background_flights: list[dict] = []
        lakebase = get_lakebase_service()
        if lakebase.is_available:
            lb_data = lakebase.get_schedule(
                flight_type=flight_type,
                hours_behind=hours_behind,
                hours_ahead=hours_ahead,
                limit=limit,
                airport_icao=self._airport_icao,
            )
            if lb_data:
                background_flights = lb_data
                logger.debug(f"FIDS {flight_type}s: {len(lb_data)} from Lakebase")

        if not background_flights:
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(hours=hours_behind)
            background_flights = get_future_schedule(
                airport=self._airport,
                after=cutoff,
                flight_type=flight_type,
                limit=limit,
            )
            if background_flights:
                logger.debug(
                    f"FIDS {flight_type}s: {len(background_flights)} from generator"
                )

        # 3. Merge: live flights win over background by flight_number
        seen_numbers = {f["flight_number"] for f in live_flights}
        merged = list(live_flights)
        for f in background_flights:
            if f["flight_number"] not in seen_numbers:
                seen_numbers.add(f["flight_number"])
                merged.append(f)

        # 4. Sort by scheduled_time
        merged.sort(key=lambda x: x["scheduled_time"])
        return merged[:limit]

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

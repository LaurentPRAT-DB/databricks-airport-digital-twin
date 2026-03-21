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

        Reads from Lakebase first for persistence, otherwise merges live
        flights (matching the map) with future scheduled flights.

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

        # Merge live flights + future schedule
        if not raw_arrivals:
            raw_arrivals = self._merge_live_and_future("arrival", limit)

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

        Reads from Lakebase first for persistence, otherwise merges live
        flights (matching the map) with future scheduled flights.

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

        # Merge live flights + future schedule
        if not raw_departures:
            raw_departures = self._merge_live_and_future("departure", limit)

        flights = [_dict_to_scheduled_flight(f) for f in raw_departures[:limit]]

        logger.info(f"Schedule service returning {len(flights)} departures")

        return ScheduleResponse(
            flights=flights,
            count=len(flights),
            airport=self._airport,
            flight_type=FlightType.DEPARTURE,
        )

    def _merge_live_and_future(
        self, flight_type: str, limit: int,
    ) -> list[dict]:
        """Merge live map flights with future scheduled flights.

        Live flights (from the simulation) always take priority since they
        match what the user sees on the map. Future flights from the schedule
        generator fill out the rest of the FIDS.

        Args:
            flight_type: "arrival" or "departure"
            limit: Maximum total flights to return

        Returns:
            Merged, deduplicated, sorted list of flight dicts
        """
        # 1. Get live flights (same data as map)
        live_schedule = get_flights_as_schedule()
        live_flights = [f for f in live_schedule if f["flight_type"] == flight_type]
        if live_flights:
            logger.debug(f"FIDS {flight_type}s: {len(live_flights)} live flights from map")

        # 2. Determine cutoff: latest scheduled_time among live flights
        #    Future flights will supplement after this point
        now = datetime.now(timezone.utc)
        if live_flights:
            latest_live = max(
                datetime.fromisoformat(f["scheduled_time"]) for f in live_flights
            )
            cutoff = latest_live
        else:
            cutoff = now - timedelta(minutes=30)

        # 3. Get future flights from schedule generator
        future_flights = get_future_schedule(
            airport=self._airport,
            after=cutoff,
            flight_type=flight_type,
            limit=limit,
        )
        if future_flights:
            logger.debug(
                f"FIDS {flight_type}s: {len(future_flights)} future flights from generator"
            )

        # 4. Merge and deduplicate by flight_number (live wins)
        seen_numbers = {f["flight_number"] for f in live_flights}
        merged = list(live_flights)
        for f in future_flights:
            if f["flight_number"] not in seen_numbers:
                seen_numbers.add(f["flight_number"])
                merged.append(f)

        # 5. Sort by scheduled_time
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

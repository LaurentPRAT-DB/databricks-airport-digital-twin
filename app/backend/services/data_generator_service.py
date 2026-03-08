"""Data Generation Service for synthetic airport data.

This service generates and persists synthetic data to Lakebase on startup
and refreshes it periodically:
- Weather: every 10 minutes
- Schedule: every 1 minute
- Baggage: every 30 seconds
- GSE: every 30 seconds
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from src.ingestion.weather_generator import generate_metar, generate_taf
from src.ingestion.schedule_generator import generate_daily_schedule
from src.ingestion.baggage_generator import get_flight_baggage_stats
from src.ml.gse_model import get_fleet_status, generate_gse_positions

from app.backend.services.lakebase_service import get_lakebase_service

logger = logging.getLogger(__name__)


class DataGeneratorService:
    """Service for generating and persisting synthetic airport data."""

    def __init__(
        self,
        airport: str = "SFO",
        weather_station: str = "KSFO",
        weather_interval_seconds: int = 600,    # 10 minutes
        schedule_interval_seconds: int = 60,    # 1 minute
        baggage_interval_seconds: int = 30,     # 30 seconds
        gse_interval_seconds: int = 30,         # 30 seconds
    ):
        self._airport = airport
        self._weather_station = weather_station
        self._weather_interval = weather_interval_seconds
        self._schedule_interval = schedule_interval_seconds
        self._baggage_interval = baggage_interval_seconds
        self._gse_interval = gse_interval_seconds

        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._initialized = False

    async def initialize_all_data(self) -> bool:
        """
        Initialize all data sources on startup.

        Returns:
            True if initialization successful, False otherwise.
        """
        if self._initialized:
            logger.info("Data already initialized, skipping")
            return True

        lakebase = get_lakebase_service()
        if not lakebase.is_available:
            logger.warning("Lakebase not available, skipping data initialization")
            return False

        logger.info("=" * 60)
        logger.info("Initializing synthetic data to Lakebase")
        logger.info("=" * 60)

        try:
            # Initialize weather
            weather_count = await self._generate_weather()
            logger.info(f"  Weather: {weather_count} station(s)")

            # Initialize schedule
            schedule_count = await self._generate_schedule()
            logger.info(f"  Schedule: {schedule_count} flights")

            # Initialize baggage (for active flights)
            baggage_count = await self._generate_baggage()
            logger.info(f"  Baggage: {baggage_count} flight stats")

            # Initialize GSE fleet
            gse_count = await self._generate_gse_fleet()
            logger.info(f"  GSE Fleet: {gse_count} units")

            logger.info("=" * 60)
            logger.info("Data initialization complete")
            logger.info("=" * 60)

            self._initialized = True
            return True

        except Exception as e:
            logger.error(f"Data initialization failed: {e}", exc_info=True)
            return False

    async def start_periodic_refresh(self) -> None:
        """Start background tasks for periodic data refresh."""
        if self._running:
            logger.warning("Periodic refresh already running")
            return

        self._running = True
        logger.info("Starting periodic data refresh tasks")

        # Create background tasks
        self._tasks = [
            asyncio.create_task(self._weather_refresh_loop()),
            asyncio.create_task(self._schedule_refresh_loop()),
            asyncio.create_task(self._baggage_refresh_loop()),
            asyncio.create_task(self._gse_refresh_loop()),
        ]

    async def stop_periodic_refresh(self) -> None:
        """Stop all background refresh tasks."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks = []
        logger.info("Stopped periodic data refresh tasks")

    # =========================================================================
    # Weather Generation
    # =========================================================================

    async def _generate_weather(self) -> int:
        """Generate and persist weather data."""
        lakebase = get_lakebase_service()
        if not lakebase.is_available:
            return 0

        metar = generate_metar(station=self._weather_station)
        taf = generate_taf(station=self._weather_station)

        obs = {
            "station": metar["station"],
            "observation_time": metar["observation_time"],
            "wind_direction": metar.get("wind_direction"),
            "wind_speed_kts": metar.get("wind_speed_kts", 0),
            "wind_gust_kts": metar.get("wind_gust_kts"),
            "visibility_sm": metar["visibility_sm"],
            "clouds": metar.get("clouds", []),
            "temperature_c": metar["temperature_c"],
            "dewpoint_c": metar["dewpoint_c"],
            "altimeter_inhg": metar["altimeter_inhg"],
            "weather": metar.get("weather", []),
            "flight_category": metar["flight_category"],
            "raw_metar": metar.get("raw_metar"),
            "taf_text": taf.get("forecast_text"),
            "taf_valid_from": taf.get("valid_from"),
            "taf_valid_to": taf.get("valid_to"),
        }

        if lakebase.upsert_weather(obs):
            return 1
        return 0

    async def _weather_refresh_loop(self) -> None:
        """Background loop for weather refresh."""
        while self._running:
            try:
                await asyncio.sleep(self._weather_interval)
                count = await self._generate_weather()
                if count > 0:
                    logger.debug(f"Weather refresh: {count} station(s) updated")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Weather refresh error: {e}")

    # =========================================================================
    # Schedule Generation
    # =========================================================================

    async def _generate_schedule(self) -> int:
        """Generate and persist flight schedule."""
        lakebase = get_lakebase_service()
        if not lakebase.is_available:
            return 0

        schedule = generate_daily_schedule(airport=self._airport)

        # Clean old schedule first
        lakebase.clear_old_schedule(hours_old=24)

        # Upsert new schedule
        return lakebase.upsert_schedule(schedule)

    async def _schedule_refresh_loop(self) -> None:
        """Background loop for schedule refresh."""
        while self._running:
            try:
                await asyncio.sleep(self._schedule_interval)
                count = await self._generate_schedule()
                if count > 0:
                    logger.debug(f"Schedule refresh: {count} flights updated")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Schedule refresh error: {e}")

    # =========================================================================
    # Baggage Generation
    # =========================================================================

    async def _generate_baggage(self) -> int:
        """Generate and persist baggage stats for active flights."""
        lakebase = get_lakebase_service()
        if not lakebase.is_available:
            return 0

        # Get active flights from schedule
        schedule = lakebase.get_schedule(hours_behind=1, hours_ahead=2, limit=50)
        if not schedule:
            return 0

        count = 0
        for flight in schedule:
            flight_number = flight.get("flight_number")
            if not flight_number:
                continue

            # Generate baggage stats
            is_arrival = flight.get("flight_type") == "arrival"
            scheduled_time = flight.get("scheduled_time")

            stats = get_flight_baggage_stats(
                flight_number=flight_number,
                aircraft_type=flight.get("aircraft_type", "A320"),
                origin=flight.get("origin", self._airport),
                destination=flight.get("destination", "LAX"),
                scheduled_time=scheduled_time,
                is_arrival=is_arrival,
            )

            if lakebase.upsert_baggage_stats(stats):
                count += 1

        return count

    async def _baggage_refresh_loop(self) -> None:
        """Background loop for baggage refresh."""
        while self._running:
            try:
                await asyncio.sleep(self._baggage_interval)
                count = await self._generate_baggage()
                if count > 0:
                    logger.debug(f"Baggage refresh: {count} flights updated")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Baggage refresh error: {e}")

    # =========================================================================
    # GSE Fleet Generation
    # =========================================================================

    async def _generate_gse_fleet(self) -> int:
        """Generate and persist GSE fleet inventory."""
        lakebase = get_lakebase_service()
        if not lakebase.is_available:
            return 0

        fleet = get_fleet_status()
        units = []

        unit_counter = {}
        for gse_type, counts in fleet.get("by_type", {}).items():
            unit_counter[gse_type] = unit_counter.get(gse_type, 0)
            for i in range(counts.get("total", 0)):
                unit_counter[gse_type] += 1
                unit_id = f"{gse_type.upper()[:3]}-{unit_counter[gse_type]:03d}"

                if i < counts.get("in_service", 0):
                    status = "servicing"
                elif i < counts.get("in_service", 0) + counts.get("available", 0):
                    status = "available"
                else:
                    status = "maintenance"

                units.append({
                    "unit_id": unit_id,
                    "gse_type": gse_type,
                    "status": status,
                    "assigned_flight": None,
                    "assigned_gate": None,
                    "position_x": 0.0,
                    "position_y": 0.0,
                })

        return lakebase.upsert_gse_fleet(units)

    async def _gse_refresh_loop(self) -> None:
        """Background loop for GSE fleet refresh."""
        while self._running:
            try:
                await asyncio.sleep(self._gse_interval)
                count = await self._generate_gse_fleet()
                if count > 0:
                    logger.debug(f"GSE fleet refresh: {count} units updated")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"GSE fleet refresh error: {e}")


# Singleton instance
_data_generator_service: Optional[DataGeneratorService] = None


def get_data_generator_service() -> DataGeneratorService:
    """Get or create DataGeneratorService singleton."""
    global _data_generator_service
    if _data_generator_service is None:
        _data_generator_service = DataGeneratorService()
    return _data_generator_service

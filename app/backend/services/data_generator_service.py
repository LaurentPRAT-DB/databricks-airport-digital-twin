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
import os
import uuid
from datetime import datetime, timezone
from typing import Callable, Coroutine, Optional

ProgressCallback = Optional[Callable[[int, int, str, bool], Coroutine]]

from src.ingestion.weather_generator import generate_metar, generate_taf
from src.ingestion.schedule_generator import generate_daily_schedule
from src.ingestion.baggage_generator import get_flight_baggage_stats
from src.ml.gse_model import get_fleet_status, generate_gse_positions

from app.backend.demo_config import (
    DEFAULT_AIRPORT_ICAO, DEFAULT_AIRPORT_IATA, icao_to_iata,
)
from app.backend.services.lakebase_service import get_lakebase_service

logger = logging.getLogger(__name__)


class DataGeneratorService:
    """Service for generating and persisting synthetic airport data."""

    def __init__(
        self,
        airport: str = DEFAULT_AIRPORT_IATA,
        weather_station: str = DEFAULT_AIRPORT_ICAO,
        weather_interval_seconds: int = 600,    # 10 minutes
        schedule_interval_seconds: int = 60,    # 1 minute
        baggage_interval_seconds: int = 30,     # 30 seconds
        gse_interval_seconds: int = 30,         # 30 seconds
        snapshot_interval_seconds: int = 15,    # 15 seconds
    ):
        self._airport = airport
        self._weather_station = weather_station
        self._current_airport_icao = weather_station  # e.g. "KSFO"
        self._weather_interval = weather_interval_seconds
        self._schedule_interval = schedule_interval_seconds
        self._baggage_interval = baggage_interval_seconds
        self._gse_interval = gse_interval_seconds
        self._snapshot_interval = snapshot_interval_seconds

        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._initialized = False
        self._initialized_airports: set[str] = set()

        # Session tracking for ML data persistence
        self._session_id = str(uuid.uuid4())

    @property
    def session_id(self) -> str:
        """Unique ID for this app run, used to group ML training data."""
        return self._session_id

    async def initialize_all_data(
        self,
        airport_icao: str = "KSFO",
        progress_callback: ProgressCallback = None,
    ) -> bool:
        """
        Initialize all data sources on startup.

        Args:
            airport_icao: ICAO code for the airport to generate data for.
            progress_callback: Optional async callback(step, total, message, done).

        Returns:
            True if initialization successful, False otherwise.
        """
        if airport_icao in self._initialized_airports:
            logger.info(f"Data already initialized for {airport_icao}, skipping")
            return True

        # Update current airport context
        self._current_airport_icao = airport_icao
        self._airport = icao_to_iata(airport_icao)
        self._weather_station = airport_icao

        lakebase = get_lakebase_service()
        has_lakebase = lakebase.is_available

        logger.info("=" * 60)
        logger.info(f"Initializing synthetic data for {airport_icao} (Lakebase: {'available' if has_lakebase else 'unavailable'})")
        logger.info("=" * 60)

        total_steps = 7

        import time as _time

        try:
            _t_data_start = _time.monotonic()

            if progress_callback:
                await progress_callback(4, total_steps, "Generating flight schedule...", False)
            _t_sub = _time.monotonic()
            schedule_count = await self._generate_schedule() if has_lakebase else 0
            logger.info(f"[DIAG] Step 4 (schedule): {_time.monotonic() - _t_sub:.3f}s — {schedule_count} flights")

            if progress_callback:
                await progress_callback(5, total_steps, "Generating weather data...", False)
            _t_sub = _time.monotonic()
            weather_count = await self._generate_weather() if has_lakebase else 0
            logger.info(f"[DIAG] Step 5 (weather): {_time.monotonic() - _t_sub:.3f}s — {weather_count} station(s)")

            if progress_callback:
                await progress_callback(6, total_steps, "Generating baggage data...", False)
            _t_sub = _time.monotonic()
            baggage_count = await self._generate_baggage() if has_lakebase else 0
            logger.info(f"[DIAG] Step 6 (baggage): {_time.monotonic() - _t_sub:.3f}s — {baggage_count} flight stats")

            if progress_callback:
                await progress_callback(7, total_steps, "Generating GSE fleet data...", False)
            _t_sub = _time.monotonic()
            gse_count = await self._generate_gse_fleet() if has_lakebase else 0
            logger.info(f"[DIAG] Step 7 (GSE): {_time.monotonic() - _t_sub:.3f}s — {gse_count} units")

            total_data = _time.monotonic() - _t_data_start
            logger.info(f"[DIAG] Steps 4-7 (data gen) total: {total_data:.3f}s")
            logger.info("=" * 60)
            logger.info(f"Data initialization complete for {airport_icao}")
            logger.info("=" * 60)

            self._initialized = True
            self._initialized_airports.add(airport_icao)
            return True

        except Exception as e:
            logger.error(f"Data initialization failed: {e}", exc_info=True)
            return False

    async def switch_airport(
        self,
        icao_code: str,
        progress_callback: ProgressCallback = None,
    ) -> bool:
        """Switch synthetic data generation to a new airport.

        Checks if Lakebase already has data for this airport.
        If not, generates schedule, weather, baggage, and GSE data.
        In-memory synthetic data (flight positions) always works regardless
        of Lakebase availability.

        Args:
            icao_code: ICAO airport code (e.g., "KJFK").
            progress_callback: Optional async callback(step, total, message, done).

        Returns:
            True if airport context was switched (always True).
        """
        # Update current airport context
        self._current_airport_icao = icao_code
        self._airport = icao_to_iata(icao_code)
        self._weather_station = icao_code

        # Skip if already initialized in this session
        if icao_code in self._initialized_airports:
            logger.info(f"Airport {icao_code} already initialized in this session")
            return True

        # Try to populate Lakebase (non-blocking best-effort)
        try:
            lakebase = get_lakebase_service()
            if lakebase.is_available and lakebase.has_synthetic_data(icao_code):
                logger.info(f"Lakebase already has synthetic data for {icao_code}")
                self._initialized_airports.add(icao_code)
                return True

            # Generate fresh data to Lakebase
            logger.info(f"Generating synthetic data for new airport {icao_code}")
            await self.initialize_all_data(
                airport_icao=icao_code, progress_callback=progress_callback
            )
        except Exception as e:
            logger.warning(f"Lakebase data generation failed for {icao_code}: {e}")
            # Mark as initialized anyway — in-memory generators still work
            self._initialized_airports.add(icao_code)

        return True

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
            asyncio.create_task(self._flight_snapshot_refresh_loop()),
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
        lakebase.clear_old_schedule(hours_old=24, airport_icao=self._current_airport_icao)

        # Upsert new schedule
        return lakebase.upsert_schedule(schedule, airport_icao=self._current_airport_icao)

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
        schedule = lakebase.get_schedule(
            hours_behind=1, hours_ahead=2, limit=50,
            airport_icao=self._current_airport_icao,
        )
        if not schedule:
            return 0

        count = 0
        all_stats = []
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

            if lakebase.upsert_baggage_stats(stats, airport_icao=self._current_airport_icao):
                count += 1
            all_stats.append({"airport_icao": self._current_airport_icao, **stats})

        # Write events to landing zone for DLT pipeline pickup
        # (only works inside Databricks — /Volumes is not mounted in App containers)
        if all_stats and os.path.isdir("/Volumes"):
            try:
                from src.ingestion.baggage_writer import write_baggage_events
                write_baggage_events(
                    all_stats,
                    catalog="serverless_stable_3n0ihb_catalog",
                    schema="airport_digital_twin",
                )
            except Exception as e:
                logger.warning(f"Failed to write baggage events to landing zone: {e}")

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

        return lakebase.upsert_gse_fleet(units, airport_icao=self._current_airport_icao)

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

    # =========================================================================
    # Flight Data Snapshot & ML Event Persistence
    # =========================================================================

    async def _persist_flight_data(self) -> dict:
        """Persist flight snapshots, phase transitions, gate events, and predictions.

        Drains all event buffers and batch-inserts to Lakebase in one pass.
        Returns counts of persisted records.
        """
        from src.ingestion.fallback import (
            get_current_flight_states,
            drain_phase_transitions,
            drain_gate_events,
            drain_predictions,
            drain_turnaround_events,
        )

        lakebase = get_lakebase_service()
        if not lakebase.is_available:
            return {"snapshots": 0, "transitions": 0, "gate_events": 0, "predictions": 0}

        session_id = self._session_id
        airport_icao = self._current_airport_icao

        # Collect all data
        snapshots = get_current_flight_states()
        transitions = drain_phase_transitions()
        gate_events = drain_gate_events()
        predictions = drain_predictions()
        turnaround_events = drain_turnaround_events()

        # Batch insert
        snap_count = lakebase.insert_flight_snapshots(snapshots, session_id, airport_icao)
        trans_count = lakebase.insert_phase_transitions(transitions, session_id, airport_icao)
        gate_count = lakebase.insert_gate_events(gate_events, session_id, airport_icao)
        pred_count = lakebase.insert_ml_predictions(predictions, session_id, airport_icao)

        # Log turnaround events (Lakebase table pending)
        ta_count = len(turnaround_events)
        if ta_count > 0:
            logger.debug(f"Drained {ta_count} turnaround events for {airport_icao}")

        return {
            "snapshots": snap_count,
            "transitions": trans_count,
            "gate_events": gate_count,
            "predictions": pred_count,
            "turnaround_events": ta_count,
        }

    async def _flight_snapshot_refresh_loop(self) -> None:
        """Background loop for persisting flight data every 15s."""
        while self._running:
            try:
                await asyncio.sleep(self._snapshot_interval)
                counts = await self._persist_flight_data()
                total = sum(counts.values())
                if total > 0:
                    logger.debug(
                        f"Persisted {counts['snapshots']} snapshots, "
                        f"{counts['transitions']} transitions, "
                        f"{counts['gate_events']} gate events, "
                        f"{counts['predictions']} predictions"
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Flight snapshot refresh error: {e}")


# Singleton instance
_data_generator_service: Optional[DataGeneratorService] = None


def get_data_generator_service() -> DataGeneratorService:
    """Get or create DataGeneratorService singleton."""
    global _data_generator_service
    if _data_generator_service is None:
        _data_generator_service = DataGeneratorService()
    return _data_generator_service

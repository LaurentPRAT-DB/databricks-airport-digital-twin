"""Tests for DataGeneratorService.

Tests the unified data generation service that populates Lakebase
on startup and refreshes data periodically.
"""

import asyncio
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock

from app.backend.services.data_generator_service import (
    DataGeneratorService,
    get_data_generator_service,
)


class TestDataGeneratorServiceInit:
    """Tests for DataGeneratorService initialization."""

    def test_default_config(self):
        """Test default configuration values."""
        service = DataGeneratorService()

        assert service._airport == "SFO"
        assert service._weather_station == "KSFO"
        assert service._current_airport_icao == "KSFO"
        assert service._weather_interval == 600  # 10 minutes
        assert service._schedule_interval == 60  # 1 minute
        assert service._baggage_interval == 30  # 30 seconds
        assert service._gse_interval == 30  # 30 seconds
        assert service._running is False
        assert service._initialized is False
        assert service._initialized_airports == set()
        assert service._tasks == []

    def test_custom_config(self):
        """Test custom configuration values."""
        service = DataGeneratorService(
            airport="LAX",
            weather_station="KLAX",
            weather_interval_seconds=300,
            schedule_interval_seconds=120,
            baggage_interval_seconds=15,
            gse_interval_seconds=15,
        )

        assert service._airport == "LAX"
        assert service._weather_station == "KLAX"
        assert service._weather_interval == 300
        assert service._schedule_interval == 120
        assert service._baggage_interval == 15
        assert service._gse_interval == 15


class TestDataGeneratorServiceSingleton:
    """Tests for singleton pattern."""

    def test_get_data_generator_service_singleton(self):
        """Test singleton returns same instance."""
        # Reset singleton
        import app.backend.services.data_generator_service as module
        module._data_generator_service = None

        service1 = get_data_generator_service()
        service2 = get_data_generator_service()

        assert service1 is service2


class TestDataGeneratorServiceInitialization:
    """Tests for data initialization."""

    @pytest.mark.asyncio
    async def test_initialize_all_data_lakebase_unavailable(self):
        """Test initialization returns False when Lakebase unavailable."""
        service = DataGeneratorService()

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = False

        with patch(
            "app.backend.services.data_generator_service.get_lakebase_service",
            return_value=mock_lakebase,
        ):
            result = await service.initialize_all_data()

        assert result is False
        assert service._initialized is False

    @pytest.mark.asyncio
    async def test_initialize_all_data_success(self):
        """Test successful data initialization."""
        service = DataGeneratorService()

        # Mock Lakebase service
        mock_lakebase = MagicMock()
        mock_lakebase.is_available = True
        mock_lakebase.upsert_weather.return_value = True
        mock_lakebase.upsert_schedule.return_value = 50
        mock_lakebase.upsert_baggage_stats.return_value = True
        mock_lakebase.upsert_gse_fleet.return_value = 30
        mock_lakebase.clear_old_schedule.return_value = None
        mock_lakebase.get_schedule.return_value = [
            {"flight_number": "UA123", "flight_type": "arrival", "scheduled_time": datetime.now(timezone.utc)}
        ]

        # Mock generators
        mock_metar = {
            "station": "KSFO",
            "observation_time": datetime.now(timezone.utc),
            "visibility_sm": 10.0,
            "temperature_c": 20,
            "dewpoint_c": 15,
            "altimeter_inhg": 30.01,
            "flight_category": "VFR",
        }
        mock_taf = {
            "forecast_text": "TAF...",
            "valid_from": datetime.now(timezone.utc),
            "valid_to": datetime.now(timezone.utc),
        }
        mock_schedule = [{"flight_number": "UA123"}]
        mock_baggage_stats = {
            "flight_number": "UA123",
            "total_bags": 100,
        }
        mock_fleet = {
            "by_type": {
                "pushback_tug": {"total": 5, "in_service": 2, "available": 3},
            }
        }

        with patch(
            "app.backend.services.data_generator_service.get_lakebase_service",
            return_value=mock_lakebase,
        ), patch(
            "app.backend.services.data_generator_service.generate_metar",
            return_value=mock_metar,
        ), patch(
            "app.backend.services.data_generator_service.generate_taf",
            return_value=mock_taf,
        ), patch(
            "app.backend.services.data_generator_service.generate_daily_schedule",
            return_value=mock_schedule,
        ), patch(
            "app.backend.services.data_generator_service.get_flight_baggage_stats",
            return_value=mock_baggage_stats,
        ), patch(
            "app.backend.services.data_generator_service.get_fleet_status",
            return_value=mock_fleet,
        ):
            result = await service.initialize_all_data()

        assert result is True
        assert service._initialized is True
        assert "KSFO" in service._initialized_airports
        mock_lakebase.upsert_weather.assert_called_once()
        mock_lakebase.upsert_schedule.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_all_data_already_initialized(self):
        """Test that re-initialization is skipped."""
        service = DataGeneratorService()
        service._initialized_airports.add("KSFO")

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = True

        with patch(
            "app.backend.services.data_generator_service.get_lakebase_service",
            return_value=mock_lakebase,
        ):
            result = await service.initialize_all_data(airport_icao="KSFO")

        assert result is True
        # Should not call any Lakebase methods
        mock_lakebase.upsert_weather.assert_not_called()

    @pytest.mark.asyncio
    async def test_initialize_all_data_error_handling(self):
        """Test error handling during initialization."""
        service = DataGeneratorService()

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = True
        mock_lakebase.upsert_weather.side_effect = Exception("DB error")

        with patch(
            "app.backend.services.data_generator_service.get_lakebase_service",
            return_value=mock_lakebase,
        ), patch(
            "app.backend.services.data_generator_service.generate_metar",
            return_value={"station": "KSFO", "observation_time": datetime.now(timezone.utc)},
        ), patch(
            "app.backend.services.data_generator_service.generate_taf",
            return_value={},
        ):
            result = await service.initialize_all_data()

        assert result is False
        assert service._initialized is False


class TestDataGeneratorServicePeriodicRefresh:
    """Tests for periodic refresh functionality."""

    @pytest.mark.asyncio
    async def test_start_periodic_refresh(self):
        """Test starting periodic refresh creates tasks."""
        service = DataGeneratorService()
        service._running = False

        # Start refresh
        await service.start_periodic_refresh()

        assert service._running is True
        assert len(service._tasks) == 4

        # Clean up
        await service.stop_periodic_refresh()

    @pytest.mark.asyncio
    async def test_start_periodic_refresh_already_running(self):
        """Test that starting refresh when already running is ignored."""
        service = DataGeneratorService()
        service._running = True
        service._tasks = [MagicMock()]  # Fake existing task

        await service.start_periodic_refresh()

        # Should still have just 1 task (not create new ones)
        assert len(service._tasks) == 1

    @pytest.mark.asyncio
    async def test_stop_periodic_refresh(self):
        """Test stopping periodic refresh cancels tasks."""
        service = DataGeneratorService()

        # Create mock tasks
        mock_task1 = MagicMock()
        mock_task2 = MagicMock()
        service._tasks = [mock_task1, mock_task2]
        service._running = True

        await service.stop_periodic_refresh()

        assert service._running is False
        assert service._tasks == []
        mock_task1.cancel.assert_called_once()
        mock_task2.cancel.assert_called_once()


class TestWeatherGeneration:
    """Tests for weather data generation."""

    @pytest.mark.asyncio
    async def test_generate_weather_lakebase_unavailable(self):
        """Test weather generation returns 0 when Lakebase unavailable."""
        service = DataGeneratorService()

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = False

        with patch(
            "app.backend.services.data_generator_service.get_lakebase_service",
            return_value=mock_lakebase,
        ):
            result = await service._generate_weather()

        assert result == 0

    @pytest.mark.asyncio
    async def test_generate_weather_success(self):
        """Test successful weather generation."""
        service = DataGeneratorService()

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = True
        mock_lakebase.upsert_weather.return_value = True

        mock_metar = {
            "station": "KSFO",
            "observation_time": datetime.now(timezone.utc),
            "wind_direction": 270,
            "wind_speed_kts": 10,
            "visibility_sm": 10.0,
            "clouds": [{"cover": "FEW", "altitude": 5000}],
            "temperature_c": 18,
            "dewpoint_c": 12,
            "altimeter_inhg": 30.05,
            "weather": [],
            "flight_category": "VFR",
            "raw_metar": "KSFO...",
        }
        mock_taf = {
            "forecast_text": "TAF KSFO...",
            "valid_from": datetime.now(timezone.utc),
            "valid_to": datetime.now(timezone.utc),
        }

        with patch(
            "app.backend.services.data_generator_service.get_lakebase_service",
            return_value=mock_lakebase,
        ), patch(
            "app.backend.services.data_generator_service.generate_metar",
            return_value=mock_metar,
        ), patch(
            "app.backend.services.data_generator_service.generate_taf",
            return_value=mock_taf,
        ):
            result = await service._generate_weather()

        assert result == 1
        mock_lakebase.upsert_weather.assert_called_once()

        # Verify the observation dict passed
        call_args = mock_lakebase.upsert_weather.call_args[0][0]
        assert call_args["station"] == "KSFO"
        assert call_args["wind_direction"] == 270
        assert call_args["flight_category"] == "VFR"


class TestScheduleGeneration:
    """Tests for schedule data generation."""

    @pytest.mark.asyncio
    async def test_generate_schedule_success(self):
        """Test successful schedule generation."""
        service = DataGeneratorService()

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = True
        mock_lakebase.upsert_schedule.return_value = 50
        mock_lakebase.clear_old_schedule.return_value = None

        mock_schedule = [
            {"flight_number": f"UA{i}", "scheduled_time": datetime.now(timezone.utc)}
            for i in range(50)
        ]

        with patch(
            "app.backend.services.data_generator_service.get_lakebase_service",
            return_value=mock_lakebase,
        ), patch(
            "app.backend.services.data_generator_service.generate_daily_schedule",
            return_value=mock_schedule,
        ):
            result = await service._generate_schedule()

        assert result == 50
        mock_lakebase.clear_old_schedule.assert_called_once_with(hours_old=24, airport_icao="KSFO")
        mock_lakebase.upsert_schedule.assert_called_once_with(mock_schedule, airport_icao="KSFO")


class TestBaggageGeneration:
    """Tests for baggage data generation."""

    @pytest.mark.asyncio
    async def test_generate_baggage_no_active_flights(self):
        """Test baggage generation with no active flights."""
        service = DataGeneratorService()

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = True
        mock_lakebase.get_schedule.return_value = []

        with patch(
            "app.backend.services.data_generator_service.get_lakebase_service",
            return_value=mock_lakebase,
        ):
            result = await service._generate_baggage()

        assert result == 0

    @pytest.mark.asyncio
    async def test_generate_baggage_success(self):
        """Test successful baggage generation for active flights."""
        service = DataGeneratorService()

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = True
        mock_lakebase.get_schedule.return_value = [
            {
                "flight_number": "UA123",
                "flight_type": "arrival",
                "scheduled_time": datetime.now(timezone.utc),
                "aircraft_type": "B737",
                "origin": "LAX",
                "destination": "SFO",
            },
            {
                "flight_number": "DL456",
                "flight_type": "departure",
                "scheduled_time": datetime.now(timezone.utc),
            },
        ]
        mock_lakebase.upsert_baggage_stats.return_value = True

        mock_baggage_stats = {
            "flight_number": "UA123",
            "total_bags": 150,
            "loaded": 100,
        }

        with patch(
            "app.backend.services.data_generator_service.get_lakebase_service",
            return_value=mock_lakebase,
        ), patch(
            "app.backend.services.data_generator_service.get_flight_baggage_stats",
            return_value=mock_baggage_stats,
        ):
            result = await service._generate_baggage()

        assert result == 2
        assert mock_lakebase.upsert_baggage_stats.call_count == 2


class TestGSEFleetGeneration:
    """Tests for GSE fleet data generation."""

    @pytest.mark.asyncio
    async def test_generate_gse_fleet_success(self):
        """Test successful GSE fleet generation."""
        service = DataGeneratorService()

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = True
        mock_lakebase.upsert_gse_fleet.return_value = 15

        mock_fleet = {
            "by_type": {
                "pushback_tug": {"total": 5, "in_service": 2, "available": 2, "maintenance": 1},
                "fuel_truck": {"total": 4, "in_service": 1, "available": 3, "maintenance": 0},
                "belt_loader": {"total": 6, "in_service": 3, "available": 2, "maintenance": 1},
            }
        }

        with patch(
            "app.backend.services.data_generator_service.get_lakebase_service",
            return_value=mock_lakebase,
        ), patch(
            "app.backend.services.data_generator_service.get_fleet_status",
            return_value=mock_fleet,
        ):
            result = await service._generate_gse_fleet()

        assert result == 15
        mock_lakebase.upsert_gse_fleet.assert_called_once()

        # Verify units structure
        call_args = mock_lakebase.upsert_gse_fleet.call_args[0][0]
        assert len(call_args) == 15  # 5 + 4 + 6

        # Check unit ID format
        unit_ids = [u["unit_id"] for u in call_args]
        assert any(u.startswith("PUS") for u in unit_ids)  # pushback_tug
        assert any(u.startswith("FUE") for u in unit_ids)  # fuel_truck
        assert any(u.startswith("BEL") for u in unit_ids)  # belt_loader


class TestRefreshLoops:
    """Tests for background refresh loop behavior."""

    @pytest.mark.asyncio
    async def test_weather_refresh_loop_cancellation(self):
        """Test weather refresh loop handles cancellation gracefully."""
        service = DataGeneratorService(weather_interval_seconds=0.01)
        service._running = True

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = True
        mock_lakebase.upsert_weather.return_value = True

        call_count = 0

        async def mock_generate_weather():
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                service._running = False
            return 1

        with patch.object(service, "_generate_weather", side_effect=mock_generate_weather):
            await service._weather_refresh_loop()

        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_refresh_loop_error_handling(self):
        """Test refresh loop continues after errors."""
        service = DataGeneratorService(schedule_interval_seconds=0.01)
        service._running = True

        call_count = 0

        async def mock_generate_schedule():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Temporary error")
            if call_count >= 3:
                service._running = False
            return 10

        with patch.object(service, "_generate_schedule", side_effect=mock_generate_schedule):
            await service._schedule_refresh_loop()

        # Should continue after error
        assert call_count >= 3

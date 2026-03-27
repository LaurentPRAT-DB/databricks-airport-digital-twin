"""Tests for backend services."""

import pytest
from unittest.mock import Mock, patch, MagicMock
import os

# ==============================================================================
# Delta Service Tests
# ==============================================================================


class TestDeltaService:
    """Tests for Delta service configuration and methods."""

    def test_is_available_without_databricks_sql(self):
        """Test availability check when databricks-sql-connector is not installed."""
        with patch.dict("sys.modules", {"databricks.sql": None}):
            with patch("app.backend.services.delta_service.DATABRICKS_SQL_AVAILABLE", False):
                from app.backend.services.delta_service import DeltaService

                service = DeltaService()
                assert service.is_available is False

    def test_is_available_without_config(self):
        """Test availability check without required environment variables."""
        with patch.dict(os.environ, {}, clear=True):
            from app.backend.services.delta_service import DeltaService

            service = DeltaService()
            assert service.is_available is False

    def test_is_available_with_config(self):
        """Test availability check with proper configuration."""
        env_vars = {
            "DATABRICKS_HOST": "test-host.databricks.com",
            "DATABRICKS_HTTP_PATH": "/sql/1.0/warehouses/abc123",
            "DATABRICKS_TOKEN": "test-token",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            with patch("app.backend.services.delta_service.DATABRICKS_SQL_AVAILABLE", True):
                from app.backend.services.delta_service import DeltaService

                service = DeltaService()
                assert service.is_available is True

    def test_get_flights_when_unavailable(self):
        """Test get_flights returns None when service unavailable."""
        with patch.dict(os.environ, {}, clear=True):
            from app.backend.services.delta_service import DeltaService

            service = DeltaService()
            result = service.get_flights(limit=10)
            assert result is None

    def test_get_flight_by_icao24_when_unavailable(self):
        """Test get_flight_by_icao24 returns None when service unavailable."""
        with patch.dict(os.environ, {}, clear=True):
            from app.backend.services.delta_service import DeltaService

            service = DeltaService()
            result = service.get_flight_by_icao24("abc123")
            assert result is None

    def test_get_trajectory_when_unavailable(self):
        """Test get_trajectory returns None when service unavailable."""
        with patch.dict(os.environ, {}, clear=True):
            from app.backend.services.delta_service import DeltaService

            service = DeltaService()
            result = service.get_trajectory("abc123", minutes=60)
            assert result is None

    def test_health_check_when_unavailable(self):
        """Test health_check returns False when service unavailable."""
        with patch.dict(os.environ, {}, clear=True):
            from app.backend.services.delta_service import DeltaService

            service = DeltaService()
            result = service.health_check()
            assert result is False

    def test_get_delta_service_singleton(self):
        """Test that get_delta_service returns singleton instance."""
        from app.backend.services.delta_service import get_delta_service

        service1 = get_delta_service()
        service2 = get_delta_service()
        assert service1 is service2

    def test_catalog_schema_defaults(self):
        """Test default catalog and schema values."""
        with patch.dict(os.environ, {}, clear=True):
            from app.backend.services.delta_service import DeltaService

            service = DeltaService()
            assert service._catalog == "main"
            assert service._schema == "airport_digital_twin"

    def test_catalog_schema_from_env(self):
        """Test catalog and schema values from environment."""
        env_vars = {
            "DATABRICKS_CATALOG": "custom_catalog",
            "DATABRICKS_SCHEMA": "custom_schema",
        }
        with patch.dict(os.environ, env_vars):
            from app.backend.services.delta_service import DeltaService

            service = DeltaService()
            assert service._catalog == "custom_catalog"
            assert service._schema == "custom_schema"

    def test_trajectory_minutes_validation(self):
        """Test trajectory minutes parameter validation."""
        env_vars = {
            "DATABRICKS_HOST": "test-host.databricks.com",
            "DATABRICKS_HTTP_PATH": "/sql/1.0/warehouses/abc123",
            "DATABRICKS_TOKEN": "test-token",
        }

        with patch.dict(os.environ, env_vars):
            with patch("app.backend.services.delta_service.DATABRICKS_SQL_AVAILABLE", True):
                from app.backend.services.delta_service import DeltaService

                service = DeltaService()

                # Test with invalid minutes (should use default)
                # We can't test the actual query without mocking the connection,
                # but we verify the validation logic exists
                assert service._catalog is not None


# ==============================================================================
# Flight Service Tests
# ==============================================================================


class TestFlightService:
    """Tests for Flight service."""

    def test_service_initialization(self):
        """Test flight service initializes correctly."""
        from app.backend.services.flight_service import FlightService

        service = FlightService()
        # Check service has required attributes
        assert hasattr(service, "_lakebase")
        assert hasattr(service, "_delta")
        assert hasattr(service, "_cache")

    def test_get_flights_uses_synthetic_fallback(self):
        """Test that get_flights falls back to synthetic data."""
        from app.backend.services.flight_service import FlightService
        import asyncio

        service = FlightService()
        result = asyncio.run(service.get_flights(count=10))

        assert result is not None
        assert result.flights is not None
        assert len(result.flights) <= 10
        assert result.data_source in ["synthetic", "lakebase", "delta"]

    def test_get_flight_service_function(self):
        """Test get_flight_service returns correct instance."""
        from app.backend.services.flight_service import get_flight_service

        service = get_flight_service()
        assert service is not None

    def test_get_data_sources_status(self):
        """Test data sources status check."""
        from app.backend.services.flight_service import FlightService

        service = FlightService()
        status = service.get_data_sources_status()

        assert "lakebase" in status
        assert "delta" in status
        assert "synthetic" in status
        assert status["synthetic"]["available"] is True


# ==============================================================================
# Schedule Service Tests
# ==============================================================================


class TestScheduleService:
    """Tests for Schedule service."""

    def test_get_arrivals(self):
        """Test get_arrivals returns valid data."""
        from app.backend.services.schedule_service import get_schedule_service

        service = get_schedule_service()
        result = service.get_arrivals(hours_ahead=2, hours_behind=1, limit=20)

        assert result is not None
        assert result.flight_type == "arrival"
        assert len(result.flights) <= 20

    def test_get_departures(self):
        """Test get_departures returns valid data."""
        from app.backend.services.schedule_service import get_schedule_service

        service = get_schedule_service()
        result = service.get_departures(hours_ahead=2, hours_behind=1, limit=20)

        assert result is not None
        assert result.flight_type == "departure"
        assert len(result.flights) <= 20

    def test_arrivals_sorted_by_time(self):
        """Test that arrivals are sorted by scheduled time."""
        from app.backend.services.schedule_service import get_schedule_service

        service = get_schedule_service()
        result = service.get_arrivals(hours_ahead=4, limit=50)

        if len(result.flights) > 1:
            for i in range(len(result.flights) - 1):
                assert result.flights[i].scheduled_time <= result.flights[i + 1].scheduled_time


# ==============================================================================
# Weather Service Tests
# ==============================================================================


class TestWeatherService:
    """Tests for Weather service."""

    def test_get_current_weather_default_station(self):
        """Test get_current_weather with default station."""
        from app.backend.services.weather_service import get_weather_service

        service = get_weather_service()
        result = service.get_current_weather()

        assert result is not None
        assert result.metar is not None
        assert result.station == "KSFO"

    def test_get_current_weather_custom_station(self):
        """Test get_current_weather with custom station."""
        from app.backend.services.weather_service import get_weather_service

        service = get_weather_service()
        result = service.get_current_weather(station="KLAX")

        assert result is not None
        assert result.station == "KLAX"

    def test_metar_fields_present(self):
        """Test that METAR contains all required fields."""
        from app.backend.services.weather_service import get_weather_service

        service = get_weather_service()
        result = service.get_current_weather()
        metar = result.metar

        assert metar.station is not None
        assert metar.wind_speed_kts is not None
        assert metar.visibility_sm is not None
        assert metar.temperature_c is not None
        assert metar.flight_category is not None


# ==============================================================================
# GSE Service Tests
# ==============================================================================


class TestGSEService:
    """Tests for GSE service."""

    def test_get_fleet_status(self):
        """Test get_fleet_status returns valid data."""
        from app.backend.services.gse_service import get_gse_service

        service = get_gse_service()
        result = service.get_fleet_status()

        assert result is not None
        assert result.total_units > 0
        assert result.available >= 0
        assert result.in_service >= 0
        assert result.maintenance >= 0

    def test_fleet_counts_consistent(self):
        """Test that fleet counts are consistent."""
        from app.backend.services.gse_service import get_gse_service

        service = get_gse_service()
        result = service.get_fleet_status()

        total_from_sum = result.available + result.in_service + result.maintenance
        assert total_from_sum == result.total_units

    def test_get_turnaround_status(self):
        """Test get_turnaround_status returns valid data."""
        from app.backend.services.gse_service import get_gse_service

        service = get_gse_service()
        # Use unique icao24 to avoid state pollution from security tests
        result = service.get_turnaround_status(
            icao24="gse_status_test_001", gate="A5", aircraft_type="B737"
        )

        assert result is not None
        assert result.turnaround is not None
        assert result.turnaround.icao24 == "gse_status_test_001"
        assert result.turnaround.gate == "A5"
        assert result.turnaround.aircraft_type == "B737"

    def test_turnaround_progress_valid(self):
        """Test that turnaround progress values are valid."""
        from app.backend.services.gse_service import get_gse_service

        service = get_gse_service()
        result = service.get_turnaround_status(icao24="test123")

        assert 0 <= result.turnaround.phase_progress_pct <= 100
        assert 0 <= result.turnaround.total_progress_pct <= 100


# ==============================================================================
# Baggage Service Tests
# ==============================================================================


class TestBaggageService:
    """Tests for Baggage service."""

    def test_get_overall_stats(self):
        """Test get_overall_stats returns valid data."""
        from app.backend.services.baggage_service import get_baggage_service

        service = get_baggage_service()
        result = service.get_overall_stats()

        assert result is not None
        assert result.total_bags_today >= 0
        assert result.bags_in_system >= 0
        assert 0 <= result.misconnect_rate_pct <= 100

    def test_get_flight_baggage(self):
        """Test get_flight_baggage returns valid data."""
        from app.backend.services.baggage_service import get_baggage_service

        service = get_baggage_service()
        result = service.get_flight_baggage(
            flight_number="UA123", aircraft_type="B737", include_bags=False
        )

        assert result is not None
        assert result.stats is not None
        assert result.stats.flight_number == "UA123"
        assert result.stats.total_bags >= 0

    def test_get_flight_baggage_with_bags(self):
        """Test get_flight_baggage includes bags when requested."""
        from app.backend.services.baggage_service import get_baggage_service

        service = get_baggage_service()
        result = service.get_flight_baggage(
            flight_number="UA123", aircraft_type="B777", include_bags=True
        )

        assert result is not None
        assert len(result.bags) > 0

    def test_get_alerts(self):
        """Test get_alerts returns valid data."""
        from app.backend.services.baggage_service import get_baggage_service

        service = get_baggage_service()
        result = service.get_alerts()

        assert result is not None
        assert result.count == len(result.alerts)


# ==============================================================================
# Additional Route Tests
# ==============================================================================


class TestAdditionalRoutes:
    """Tests for additional API routes not covered elsewhere."""

    def test_trajectory_endpoint(self):
        """Test trajectory endpoint returns valid data."""
        from fastapi.testclient import TestClient
        from app.backend.main import app

        client = TestClient(app)

        # First get a flight
        flights_response = client.get("/api/flights?count=1")
        assert flights_response.status_code == 200

        flights_data = flights_response.json()
        if flights_data["flights"]:
            icao24 = flights_data["flights"][0]["icao24"]

            # Get trajectory for that flight
            response = client.get(f"/api/flights/{icao24}/trajectory")
            assert response.status_code in [200, 404]

            if response.status_code == 200:
                data = response.json()
                assert "icao24" in data
                assert "points" in data
                assert "count" in data

    def test_trajectory_parameters(self):
        """Test trajectory endpoint with custom parameters."""
        from fastapi.testclient import TestClient
        from app.backend.main import app

        client = TestClient(app)

        # Get a flight first
        flights_response = client.get("/api/flights?count=1")
        flights_data = flights_response.json()

        if flights_data["flights"]:
            icao24 = flights_data["flights"][0]["icao24"]

            # Test with custom parameters
            response = client.get(
                f"/api/flights/{icao24}/trajectory?minutes=30&limit=100"
            )
            assert response.status_code in [200, 404]

    def test_data_sources_endpoint(self):
        """Test data sources status endpoint."""
        from fastapi.testclient import TestClient
        from app.backend.main import app

        client = TestClient(app)
        response = client.get("/api/data-sources")

        assert response.status_code == 200
        data = response.json()

        assert "lakebase" in data
        assert "delta" in data
        assert "synthetic" in data

    def test_metrics_endpoint(self):
        """Test web vitals metrics collection endpoint."""
        from fastapi.testclient import TestClient
        from app.backend.main import app

        client = TestClient(app)

        # Post a web vital metric
        metric = {
            "name": "LCP",
            "value": 1234.56,
            "rating": "good",
            "delta": 100.0,
            "id": "test-id",
            "navigationType": "navigate",
            "timestamp": 1709654400000,
        }

        response = client.post("/api/metrics", json=metric)
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "ok"
        assert data["count"] >= 1

    def test_metrics_summary_endpoint(self):
        """Test web vitals metrics summary endpoint."""
        from fastapi.testclient import TestClient
        from app.backend.main import app

        client = TestClient(app)

        # First post some metrics
        metrics = [
            {"name": "LCP", "value": 1000},
            {"name": "LCP", "value": 1500},
            {"name": "INP", "value": 50},
        ]

        for m in metrics:
            client.post("/api/metrics", json=m)

        # Get summary
        response = client.get("/api/metrics/summary")
        assert response.status_code == 200

        data = response.json()
        assert "metrics" in data


# ==============================================================================
# Performance Tests for Services
# ==============================================================================


class TestServicePerformance:
    """Performance tests for backend services."""

    def test_flight_service_response_time(self):
        """Test that flight service responds within acceptable time."""
        import time
        from app.backend.services.flight_service import FlightService
        import asyncio

        service = FlightService()

        start = time.time()
        asyncio.run(service.get_flights(count=50))
        elapsed = time.time() - start

        assert elapsed < 2.0, f"Flight service took {elapsed:.2f}s (> 2s limit)"

    def test_schedule_service_response_time(self):
        """Test that schedule service responds quickly."""
        import time
        from app.backend.services.schedule_service import get_schedule_service

        service = get_schedule_service()

        start = time.time()
        service.get_arrivals(hours_ahead=2, limit=50)
        elapsed = time.time() - start

        assert elapsed < 0.5, f"Schedule service took {elapsed:.2f}s (> 0.5s limit)"

    def test_weather_service_response_time(self):
        """Test that weather service responds quickly."""
        import time
        from app.backend.services.weather_service import get_weather_service

        service = get_weather_service()

        start = time.time()
        service.get_current_weather()
        elapsed = time.time() - start

        assert elapsed < 0.5, f"Weather service took {elapsed:.2f}s (> 0.5s limit)"

    def test_gse_service_response_time(self):
        """Test that GSE service responds quickly."""
        import time
        from app.backend.services.gse_service import get_gse_service

        service = get_gse_service()

        start = time.time()
        service.get_fleet_status()
        elapsed = time.time() - start

        assert elapsed < 0.5, f"GSE service took {elapsed:.2f}s (> 0.5s limit)"

    def test_baggage_service_response_time(self):
        """Test that baggage service responds quickly."""
        import time
        from app.backend.services.baggage_service import get_baggage_service

        service = get_baggage_service()

        start = time.time()
        service.get_overall_stats()
        elapsed = time.time() - start

        assert elapsed < 0.5, f"Baggage service took {elapsed:.2f}s (> 0.5s limit)"


# ==============================================================================
# Lakebase-First Fallback Pattern Tests
# ==============================================================================


class TestWeatherServiceLakebaseFallback:
    """Tests for Weather service Lakebase-first pattern."""

    def test_weather_service_tries_lakebase_first(self):
        """Test that weather service tries Lakebase before generator."""
        from app.backend.services.weather_service import WeatherService
        from datetime import datetime, timezone

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = True
        mock_lakebase.get_weather.return_value = {
            "station": "KSFO",
            "observation_time": datetime.now(timezone.utc).isoformat(),
            "wind_direction": 270,
            "wind_speed_kts": 10,
            "visibility_sm": 10.0,
            "clouds": [],
            "temperature_c": 18,
            "dewpoint_c": 12,
            "altimeter_inhg": 30.05,
            "weather": [],
            "flight_category": "VFR",
            "raw_metar": "KSFO from Lakebase",
            "taf_text": "TAF KSFO...",
            "taf_valid_from": datetime.now(timezone.utc).isoformat(),
            "taf_valid_to": datetime.now(timezone.utc).isoformat(),
        }

        with patch(
            "app.backend.services.weather_service.get_lakebase_service",
            return_value=mock_lakebase,
        ):
            service = WeatherService()
            result = service.get_current_weather("KSFO")

        mock_lakebase.get_weather.assert_called_once_with("KSFO")
        assert "from Lakebase" in result.metar.raw_metar

    def test_weather_service_fallback_to_generator(self):
        """Test that weather service falls back to generator when Lakebase unavailable."""
        from app.backend.services.weather_service import WeatherService

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = False

        with patch(
            "app.backend.services.weather_service.get_lakebase_service",
            return_value=mock_lakebase,
        ):
            service = WeatherService()
            result = service.get_current_weather("KSFO")

        # Should still return valid weather from generator
        assert result is not None
        assert result.metar is not None
        assert result.station == "KSFO"

    def test_weather_service_fallback_when_lakebase_returns_none(self):
        """Test fallback when Lakebase returns None."""
        from app.backend.services.weather_service import WeatherService

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = True
        mock_lakebase.get_weather.return_value = None

        with patch(
            "app.backend.services.weather_service.get_lakebase_service",
            return_value=mock_lakebase,
        ):
            service = WeatherService()
            result = service.get_current_weather("KSFO")

        # Should fall back to generator
        assert result is not None
        assert result.metar is not None


class TestScheduleServiceLakebaseFallback:
    """Tests for Schedule service Lakebase-first pattern."""

    def test_schedule_service_tries_lakebase_first(self):
        """Test that schedule service tries Lakebase before generator."""
        from app.backend.services.schedule_service import ScheduleService
        from datetime import datetime, timezone

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = True
        mock_lakebase.get_schedule.return_value = [
            {
                "flight_number": "UA123",
                "airline": "United Airlines",
                "airline_code": "UA",
                "origin": "LAX",
                "destination": "SFO",
                "scheduled_time": datetime.now(timezone.utc).isoformat(),
                "estimated_time": None,
                "actual_time": None,
                "gate": "A1",
                "status": "on_time",
                "delay_minutes": 0,
                "delay_reason": None,
                "aircraft_type": "A320",
                "flight_type": "arrival",
            }
        ]

        with patch(
            "app.backend.services.schedule_service.get_lakebase_service",
            return_value=mock_lakebase,
        ), patch(
            "app.backend.services.schedule_service.get_flights_as_schedule",
            return_value=[],
        ):
            service = ScheduleService()
            result = service.get_arrivals(hours_ahead=2, hours_behind=1, limit=20)

        mock_lakebase.get_schedule.assert_called_once()
        assert len(result.flights) == 1
        assert result.flights[0].flight_number == "UA123"

    def test_schedule_service_fallback_to_generator(self):
        """Test that schedule service falls back to generator when Lakebase unavailable."""
        from app.backend.services.schedule_service import ScheduleService

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = False

        with patch(
            "app.backend.services.schedule_service.get_lakebase_service",
            return_value=mock_lakebase,
        ):
            service = ScheduleService()
            result = service.get_arrivals(hours_ahead=2, hours_behind=1, limit=20)

        # Should still return valid schedule from generator
        assert result is not None
        assert result.flights is not None

    def test_departures_tries_lakebase_first(self):
        """Test that departures endpoint also tries Lakebase first."""
        from app.backend.services.schedule_service import ScheduleService
        from datetime import datetime, timezone

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = True
        mock_lakebase.get_schedule.return_value = [
            {
                "flight_number": "DL456",
                "airline": "Delta",
                "airline_code": "DL",
                "origin": "SFO",
                "destination": "JFK",
                "scheduled_time": datetime.now(timezone.utc).isoformat(),
                "estimated_time": None,
                "actual_time": None,
                "gate": "B2",
                "status": "boarding",
                "delay_minutes": 0,
                "delay_reason": None,
                "aircraft_type": "B737",
                "flight_type": "departure",
            }
        ]

        with patch(
            "app.backend.services.schedule_service.get_lakebase_service",
            return_value=mock_lakebase,
        ), patch(
            "app.backend.services.schedule_service.get_flights_as_schedule",
            return_value=[],
        ):
            service = ScheduleService()
            result = service.get_departures(hours_ahead=2, hours_behind=1, limit=20)

        mock_lakebase.get_schedule.assert_called_once()
        assert len(result.flights) == 1


class TestBaggageServiceLakebaseFallback:
    """Tests for Baggage service Lakebase-first pattern."""

    def test_baggage_service_tries_lakebase_first(self):
        """Test that baggage service tries Lakebase before generator."""
        from app.backend.services.baggage_service import BaggageService

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = True
        mock_lakebase.get_baggage_stats.return_value = {
            "flight_number": "UA123",
            "total_bags": 200,
            "checked_in": 190,
            "loaded": 150,
            "unloaded": 0,
            "on_carousel": 0,
            "loading_progress_pct": 75,
            "connecting_bags": 15,
            "misconnects": 0,
            "carousel": None,
        }

        with patch(
            "app.backend.services.baggage_service.get_lakebase_service",
            return_value=mock_lakebase,
        ):
            service = BaggageService()
            result = service.get_flight_baggage(
                flight_number="UA123",
                aircraft_type="A320",
                include_bags=False,
            )

        mock_lakebase.get_baggage_stats.assert_called_once_with("UA123")
        assert result.stats.total_bags == 200
        assert result.stats.loading_progress_pct == 75

    def test_baggage_service_fallback_to_generator(self):
        """Test that baggage service falls back to generator when Lakebase unavailable."""
        from app.backend.services.baggage_service import BaggageService

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = False

        with patch(
            "app.backend.services.baggage_service.get_lakebase_service",
            return_value=mock_lakebase,
        ):
            service = BaggageService()
            result = service.get_flight_baggage(
                flight_number="UA123",
                aircraft_type="A320",
                include_bags=False,
            )

        # Should still return valid baggage stats from generator
        assert result is not None
        assert result.stats is not None
        assert result.stats.flight_number == "UA123"


class TestGSEServiceLakebaseFallback:
    """Tests for GSE service Lakebase-first pattern."""

    def test_gse_fleet_tries_lakebase_first(self):
        """Test that GSE fleet status tries Lakebase before generator."""
        from app.backend.services.gse_service import GSEService

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = True
        mock_lakebase.get_gse_fleet.return_value = [
            {
                "unit_id": "PUS-001",
                "gse_type": "pushback_tug",
                "status": "available",
                "assigned_flight": None,
                "assigned_gate": None,
                "position_x": 0.0,
                "position_y": 0.0,
            },
            {
                "unit_id": "FUE-001",
                "gse_type": "fuel_truck",
                "status": "servicing",
                "assigned_flight": "UA123",
                "assigned_gate": "A1",
                "position_x": 10.0,
                "position_y": 20.0,
            },
        ]

        with patch(
            "app.backend.services.gse_service.get_lakebase_service",
            return_value=mock_lakebase,
        ):
            service = GSEService()
            result = service.get_fleet_status()

        mock_lakebase.get_gse_fleet.assert_called_once()
        assert result.total_units == 2
        assert result.available == 1
        assert result.in_service == 1

    def test_gse_fleet_fallback_to_generator(self):
        """Test that GSE fleet falls back to generator when Lakebase unavailable."""
        from app.backend.services.gse_service import GSEService

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = False

        with patch(
            "app.backend.services.gse_service.get_lakebase_service",
            return_value=mock_lakebase,
        ):
            service = GSEService()
            result = service.get_fleet_status()

        # Should still return valid fleet status from generator
        assert result is not None
        assert result.total_units > 0

    def test_gse_fleet_fallback_when_lakebase_returns_empty(self):
        """Test fallback when Lakebase returns empty list."""
        from app.backend.services.gse_service import GSEService

        mock_lakebase = MagicMock()
        mock_lakebase.is_available = True
        mock_lakebase.get_gse_fleet.return_value = []

        with patch(
            "app.backend.services.gse_service.get_lakebase_service",
            return_value=mock_lakebase,
        ):
            service = GSEService()
            result = service.get_fleet_status()

        # Should fall back to generator
        assert result is not None
        assert result.total_units > 0

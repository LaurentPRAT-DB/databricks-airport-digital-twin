"""Tests for the extended LakebaseService with all data types.

Tests cover:
- Weather observation CRUD operations
- Flight schedule CRUD operations
- Baggage status CRUD operations
- GSE fleet CRUD operations
- GSE turnaround CRUD operations
- Connection handling and error cases
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone, timedelta
import os


class TestLakebaseServiceAvailability:
    """Tests for Lakebase service availability checks."""

    def test_unavailable_without_psycopg2(self):
        """Test service unavailable when psycopg2 not installed."""
        with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", False):
            from app.backend.services.lakebase_service import LakebaseService
            service = LakebaseService()
            assert service.is_available is False

    def test_unavailable_without_config(self):
        """Test service unavailable without configuration."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                service = LakebaseService()
                assert service.is_available is False

    def test_available_with_connection_string(self):
        """Test service available with connection string."""
        env_vars = {
            "LAKEBASE_CONNECTION_STRING": "postgresql://user:pass@host:5432/db",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                service = LakebaseService()
                assert service.is_available is True

    def test_available_with_direct_credentials(self):
        """Test service available with direct credentials."""
        env_vars = {
            "LAKEBASE_HOST": "localhost",
            "LAKEBASE_USER": "user",
            "LAKEBASE_PASSWORD": "password",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                service = LakebaseService()
                assert service.is_available is True

    def test_available_with_oauth(self):
        """Test service available with OAuth configuration."""
        env_vars = {
            "LAKEBASE_HOST": "endpoint.databricks.com",
            "LAKEBASE_ENDPOINT_NAME": "projects/test/branches/main/endpoints/primary",
            "LAKEBASE_USE_OAUTH": "true",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                service = LakebaseService()
                assert service.is_available is True


class TestLakebaseWeatherOperations:
    """Tests for weather operations in LakebaseService."""

    def test_upsert_weather_when_unavailable(self):
        """Test upsert_weather returns False when service unavailable."""
        with patch.dict(os.environ, {}, clear=True):
            from app.backend.services.lakebase_service import LakebaseService
            service = LakebaseService()
            result = service.upsert_weather({"station": "KSFO"})
            assert result is False

    def test_get_weather_when_unavailable(self):
        """Test get_weather returns None when service unavailable."""
        with patch.dict(os.environ, {}, clear=True):
            from app.backend.services.lakebase_service import LakebaseService
            service = LakebaseService()
            result = service.get_weather("KSFO")
            assert result is None

    @patch("app.backend.services.lakebase_service.psycopg2", create=True)
    def test_upsert_weather_success(self, mock_psycopg2):
        """Test successful weather upsert."""
        # Setup mock
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=False)
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        env_vars = {
            "LAKEBASE_CONNECTION_STRING": "postgresql://user:pass@host:5432/db",
        }
        with patch.dict(os.environ, env_vars):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                service = LakebaseService()

                obs = {
                    "station": "KSFO",
                    "observation_time": datetime.now(timezone.utc).isoformat(),
                    "wind_direction": 280,
                    "wind_speed_kts": 12,
                    "wind_gust_kts": None,
                    "visibility_sm": 10.0,
                    "clouds": [{"coverage": "SCT", "altitude_ft": 4500}],
                    "temperature_c": 18,
                    "dewpoint_c": 12,
                    "altimeter_inhg": 30.05,
                    "weather": [],
                    "flight_category": "VFR",
                    "raw_metar": "KSFO 121200Z 28012KT 10SM SCT045 18/12 A3005",
                    "taf_text": "28012KT P6SM SCT040",
                    "taf_valid_from": None,
                    "taf_valid_to": None,
                }

                result = service.upsert_weather(obs)
                assert result is True
                mock_cursor.execute.assert_called_once()
                mock_conn.commit.assert_called_once()

    @patch("app.backend.services.lakebase_service.RealDictCursor", create=True)
    @patch("app.backend.services.lakebase_service.psycopg2", create=True)
    def test_get_weather_success(self, mock_psycopg2, mock_rdc):
        """Test successful weather retrieval."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=False)
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=False)

        # Mock RealDictCursor return value
        mock_row = {
            "station": "KSFO",
            "observation_time": datetime.now(timezone.utc),
            "wind_direction": 280,
            "wind_speed_kts": 12,
            "wind_gust_kts": None,
            "visibility_sm": 10.0,
            "clouds": '[{"coverage": "SCT", "altitude_ft": 4500}]',
            "temperature_c": 18,
            "dewpoint_c": 12,
            "altimeter_inhg": 30.05,
            "weather": "[]",
            "flight_category": "VFR",
            "raw_metar": "KSFO...",
            "taf_text": None,
            "taf_valid_from": None,
            "taf_valid_to": None,
        }
        mock_cursor.fetchone.return_value = mock_row
        mock_conn.cursor.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        env_vars = {
            "LAKEBASE_CONNECTION_STRING": "postgresql://user:pass@host:5432/db",
        }
        with patch.dict(os.environ, env_vars):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                service = LakebaseService()

                result = service.get_weather("KSFO")
                assert result is not None
                assert result["station"] == "KSFO"
                assert result["wind_direction"] == 280


class TestLakebaseScheduleOperations:
    """Tests for schedule operations in LakebaseService."""

    def test_upsert_schedule_when_unavailable(self):
        """Test upsert_schedule returns 0 when service unavailable."""
        with patch.dict(os.environ, {}, clear=True):
            from app.backend.services.lakebase_service import LakebaseService
            service = LakebaseService()
            result = service.upsert_schedule([{"flight_number": "UA123"}])
            assert result == 0

    def test_upsert_schedule_empty_list(self):
        """Test upsert_schedule with empty list returns 0."""
        with patch.dict(os.environ, {}, clear=True):
            from app.backend.services.lakebase_service import LakebaseService
            service = LakebaseService()
            result = service.upsert_schedule([])
            assert result == 0

    def test_get_schedule_when_unavailable(self):
        """Test get_schedule returns None when service unavailable."""
        with patch.dict(os.environ, {}, clear=True):
            from app.backend.services.lakebase_service import LakebaseService
            service = LakebaseService()
            result = service.get_schedule(flight_type="arrival")
            assert result is None

    @patch("app.backend.services.lakebase_service.psycopg2", create=True)
    def test_upsert_schedule_success(self, mock_psycopg2):
        """Test successful schedule upsert."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=False)
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        env_vars = {
            "LAKEBASE_CONNECTION_STRING": "postgresql://user:pass@host:5432/db",
        }
        with patch.dict(os.environ, env_vars):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                service = LakebaseService()

                flights = [
                    {
                        "flight_number": "UA123",
                        "airline": "United Airlines",
                        "airline_code": "UAL",
                        "origin": "SFO",
                        "destination": "LAX",
                        "scheduled_time": datetime.now(timezone.utc).isoformat(),
                        "estimated_time": None,
                        "actual_time": None,
                        "gate": "B12",
                        "status": "on_time",
                        "delay_minutes": 0,
                        "delay_reason": None,
                        "aircraft_type": "A320",
                        "flight_type": "departure",
                    }
                ]

                result = service.upsert_schedule(flights)
                assert result == 1
                # execute is called multiple times: 4 ALTER TABLE migrations + 1 INSERT
                assert mock_cursor.execute.call_count >= 1
                mock_conn.commit.assert_called()

    def test_clear_old_schedule_when_unavailable(self):
        """Test clear_old_schedule returns 0 when unavailable."""
        with patch.dict(os.environ, {}, clear=True):
            from app.backend.services.lakebase_service import LakebaseService
            service = LakebaseService()
            result = service.clear_old_schedule(hours_old=24)
            assert result == 0


class TestLakebaseBaggageOperations:
    """Tests for baggage operations in LakebaseService."""

    def test_upsert_baggage_stats_when_unavailable(self):
        """Test upsert_baggage_stats returns False when unavailable."""
        with patch.dict(os.environ, {}, clear=True):
            from app.backend.services.lakebase_service import LakebaseService
            service = LakebaseService()
            result = service.upsert_baggage_stats({"flight_number": "UA123"})
            assert result is False

    def test_get_baggage_stats_when_unavailable(self):
        """Test get_baggage_stats returns None when unavailable."""
        with patch.dict(os.environ, {}, clear=True):
            from app.backend.services.lakebase_service import LakebaseService
            service = LakebaseService()
            result = service.get_baggage_stats("UA123")
            assert result is None

    @patch("app.backend.services.lakebase_service.psycopg2", create=True)
    def test_upsert_baggage_stats_success(self, mock_psycopg2):
        """Test successful baggage stats upsert."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=False)
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        env_vars = {
            "LAKEBASE_CONNECTION_STRING": "postgresql://user:pass@host:5432/db",
        }
        with patch.dict(os.environ, env_vars):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                service = LakebaseService()

                stats = {
                    "flight_number": "UA123",
                    "total_bags": 180,
                    "checked_in": 180,
                    "loaded": 150,
                    "unloaded": 0,
                    "on_carousel": 0,
                    "loading_progress_pct": 83,
                    "connecting_bags": 27,
                    "misconnects": 2,
                    "carousel": None,
                }

                result = service.upsert_baggage_stats(stats)
                assert result is True


class TestLakebaseGSEFleetOperations:
    """Tests for GSE fleet operations in LakebaseService."""

    def test_upsert_gse_fleet_when_unavailable(self):
        """Test upsert_gse_fleet returns 0 when unavailable."""
        with patch.dict(os.environ, {}, clear=True):
            from app.backend.services.lakebase_service import LakebaseService
            service = LakebaseService()
            result = service.upsert_gse_fleet([{"unit_id": "TUG-001"}])
            assert result == 0

    def test_upsert_gse_fleet_empty_list(self):
        """Test upsert_gse_fleet with empty list returns 0."""
        with patch.dict(os.environ, {}, clear=True):
            from app.backend.services.lakebase_service import LakebaseService
            service = LakebaseService()
            result = service.upsert_gse_fleet([])
            assert result == 0

    def test_get_gse_fleet_when_unavailable(self):
        """Test get_gse_fleet returns None when unavailable."""
        with patch.dict(os.environ, {}, clear=True):
            from app.backend.services.lakebase_service import LakebaseService
            service = LakebaseService()
            result = service.get_gse_fleet()
            assert result is None

    @patch("app.backend.services.lakebase_service.psycopg2", create=True)
    def test_upsert_gse_fleet_success(self, mock_psycopg2):
        """Test successful GSE fleet upsert."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=False)
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        env_vars = {
            "LAKEBASE_CONNECTION_STRING": "postgresql://user:pass@host:5432/db",
        }
        with patch.dict(os.environ, env_vars):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                service = LakebaseService()

                units = [
                    {
                        "unit_id": "TUG-001",
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
                        "assigned_gate": "B12",
                        "position_x": 15.5,
                        "position_y": -3.2,
                    },
                ]

                result = service.upsert_gse_fleet(units)
                assert result == 2
                # execute is called for 4 ALTER TABLE migrations + 2 INSERTs
                assert mock_cursor.execute.call_count >= 2


class TestLakebaseTurnaroundOperations:
    """Tests for turnaround operations in LakebaseService."""

    def test_upsert_turnaround_when_unavailable(self):
        """Test upsert_turnaround returns False when unavailable."""
        with patch.dict(os.environ, {}, clear=True):
            from app.backend.services.lakebase_service import LakebaseService
            service = LakebaseService()
            result = service.upsert_turnaround({"icao24": "abc123"})
            assert result is False

    def test_get_turnaround_when_unavailable(self):
        """Test get_turnaround returns None when unavailable."""
        with patch.dict(os.environ, {}, clear=True):
            from app.backend.services.lakebase_service import LakebaseService
            service = LakebaseService()
            result = service.get_turnaround("abc123")
            assert result is None

    def test_delete_turnaround_when_unavailable(self):
        """Test delete_turnaround returns False when unavailable."""
        with patch.dict(os.environ, {}, clear=True):
            from app.backend.services.lakebase_service import LakebaseService
            service = LakebaseService()
            result = service.delete_turnaround("abc123")
            assert result is False

    @patch("app.backend.services.lakebase_service.psycopg2", create=True)
    def test_upsert_turnaround_success(self, mock_psycopg2):
        """Test successful turnaround upsert."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=False)
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        env_vars = {
            "LAKEBASE_CONNECTION_STRING": "postgresql://user:pass@host:5432/db",
        }
        with patch.dict(os.environ, env_vars):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                service = LakebaseService()

                turnaround = {
                    "icao24": "abc123",
                    "flight_number": "UA123",
                    "gate": "B12",
                    "arrival_time": datetime.now(timezone.utc).isoformat(),
                    "current_phase": "refueling",
                    "phase_progress_pct": 45,
                    "total_progress_pct": 60,
                    "estimated_departure": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                    "aircraft_type": "A320",
                }

                result = service.upsert_turnaround(turnaround)
                assert result is True

    @patch("app.backend.services.lakebase_service.psycopg2", create=True)
    def test_delete_turnaround_success(self, mock_psycopg2):
        """Test successful turnaround deletion."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=False)
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        env_vars = {
            "LAKEBASE_CONNECTION_STRING": "postgresql://user:pass@host:5432/db",
        }
        with patch.dict(os.environ, env_vars):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                service = LakebaseService()

                result = service.delete_turnaround("abc123")
                assert result is True


class TestLakebaseServiceSingleton:
    """Tests for Lakebase service singleton pattern."""

    def test_get_lakebase_service_returns_singleton(self):
        """Test that get_lakebase_service returns same instance."""
        from app.backend.services.lakebase_service import get_lakebase_service

        service1 = get_lakebase_service()
        service2 = get_lakebase_service()
        assert service1 is service2

    def test_singleton_preserves_config(self):
        """Test that singleton preserves configuration."""
        from app.backend.services.lakebase_service import get_lakebase_service

        service = get_lakebase_service()
        # Access internal attributes to verify config is preserved
        assert hasattr(service, "_host")
        assert hasattr(service, "_port")
        assert hasattr(service, "_database")


class TestLakebaseConnectionErrorHandling:
    """Tests for connection error handling."""

    @patch("app.backend.services.lakebase_service.psycopg2", create=True)
    def test_auth_error_clears_cached_credentials(self, mock_psycopg2):
        """Test that authentication errors clear cached OAuth credentials."""
        mock_psycopg2.connect.side_effect = Exception(
            "password authentication failed for user 'sp-uuid'"
        )

        env_vars = {
            "LAKEBASE_CONNECTION_STRING": "postgresql://user:pass@host:5432/db",
        }
        with patch.dict(os.environ, env_vars):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                service = LakebaseService()

                # Set some cached credentials
                service._cached_credentials = ("token", "user@example.com")

                # Try an operation that will fail with auth error
                result = service.get_weather("KSFO")

                assert result is None
                assert service._cached_credentials is None  # Should be cleared

    @patch("app.backend.services.lakebase_service.psycopg2", create=True)
    def test_sql_error_preserves_cached_credentials(self, mock_psycopg2):
        """Test that SQL errors (missing table etc.) do NOT clear credentials."""
        conn = MagicMock()
        mock_psycopg2.connect.return_value = conn
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cursor.execute.side_effect = Exception('relation "weather" does not exist')

        env_vars = {
            "LAKEBASE_CONNECTION_STRING": "postgresql://user:pass@host:5432/db",
        }
        with patch.dict(os.environ, env_vars):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                service = LakebaseService()

                service._cached_credentials = ("token", "user@example.com")

                result = service.get_weather("KSFO")

                assert result is None
                assert service._cached_credentials is not None  # Should be preserved

    @patch("app.backend.services.lakebase_service.psycopg2", create=True)
    def test_health_check_handles_errors(self, mock_psycopg2):
        """Test health_check gracefully handles errors."""
        mock_psycopg2.connect.side_effect = Exception("Connection refused")

        env_vars = {
            "LAKEBASE_CONNECTION_STRING": "postgresql://user:pass@host:5432/db",
        }
        with patch.dict(os.environ, env_vars):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                service = LakebaseService()

                result = service.health_check()
                assert result is False


class TestLakebaseConnectionPool:
    """Tests for connection pool management."""

    @patch("app.backend.services.lakebase_service.ThreadedConnectionPool", create=True)
    @patch("app.backend.services.lakebase_service.psycopg2", create=True)
    def test_pool_created_on_first_connection(self, mock_psycopg2, mock_pool_cls):
        """Test that ThreadedConnectionPool is created on first use."""
        mock_pool = MagicMock()
        mock_pool.closed = False
        mock_conn = MagicMock()
        mock_pool.getconn.return_value = mock_conn
        mock_pool_cls.return_value = mock_pool

        env_vars = {
            "LAKEBASE_HOST": "host",
            "LAKEBASE_USER": "user",
            "LAKEBASE_PASSWORD": "pass",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                service = LakebaseService()

                with service._get_connection() as conn:
                    assert conn is mock_conn

                mock_pool_cls.assert_called_once()
                assert mock_pool_cls.call_args.kwargs["minconn"] == 2
                assert mock_pool_cls.call_args.kwargs["maxconn"] == 10

    @patch("app.backend.services.lakebase_service.ThreadedConnectionPool", create=True)
    @patch("app.backend.services.lakebase_service.psycopg2", create=True)
    def test_pool_reuses_connections(self, mock_psycopg2, mock_pool_cls):
        """Test that pool.getconn/putconn are used instead of psycopg2.connect."""
        mock_pool = MagicMock()
        mock_pool.closed = False
        mock_conn = MagicMock()
        mock_pool.getconn.return_value = mock_conn
        mock_pool_cls.return_value = mock_pool

        env_vars = {
            "LAKEBASE_HOST": "host",
            "LAKEBASE_USER": "user",
            "LAKEBASE_PASSWORD": "pass",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                service = LakebaseService()

                with service._get_connection():
                    pass
                with service._get_connection():
                    pass

                # Pool created once, getconn called twice
                mock_pool_cls.assert_called_once()
                assert mock_pool.getconn.call_count == 2
                assert mock_pool.putconn.call_count == 2
                # psycopg2.connect should NOT be called
                mock_psycopg2.connect.assert_not_called()

    @patch("app.backend.services.lakebase_service.ThreadedConnectionPool", create=True)
    @patch("app.backend.services.lakebase_service.psycopg2", create=True)
    def test_pool_invalidated_on_auth_error(self, mock_psycopg2, mock_pool_cls):
        """Test pool is torn down on auth failure."""
        mock_pool = MagicMock()
        mock_pool.closed = False
        mock_pool_cls.return_value = mock_pool

        env_vars = {
            "LAKEBASE_HOST": "host",
            "LAKEBASE_USER": "user",
            "LAKEBASE_PASSWORD": "pass",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                service = LakebaseService()
                # Manually set up a pool
                service._pool = mock_pool

                service._invalidate_credentials_if_auth_error(
                    Exception("password authentication failed")
                )

                mock_pool.closeall.assert_called_once()
                assert service._pool is None

    @patch("app.backend.services.lakebase_service.ThreadedConnectionPool", create=True)
    @patch("app.backend.services.lakebase_service.psycopg2", create=True)
    def test_connection_returned_on_error(self, mock_psycopg2, mock_pool_cls):
        """Test putconn(close=True) called on query error."""
        mock_pool = MagicMock()
        mock_pool.closed = False
        mock_conn = MagicMock()
        mock_pool.getconn.return_value = mock_conn
        mock_pool_cls.return_value = mock_pool

        env_vars = {
            "LAKEBASE_HOST": "host",
            "LAKEBASE_USER": "user",
            "LAKEBASE_PASSWORD": "pass",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                service = LakebaseService()

                with pytest.raises(RuntimeError):
                    with service._get_connection() as conn:
                        raise RuntimeError("query failed")

                # Should have called putconn with close=True for the bad conn
                mock_pool.putconn.assert_called_once_with(mock_conn, close=True)

    @patch("app.backend.services.lakebase_service.ThreadedConnectionPool", create=True)
    @patch("app.backend.services.lakebase_service.psycopg2", create=True)
    def test_close_pool(self, mock_psycopg2, mock_pool_cls):
        """Test close_pool calls closeall."""
        mock_pool = MagicMock()
        mock_pool.closed = False
        mock_pool_cls.return_value = mock_pool

        env_vars = {
            "LAKEBASE_HOST": "host",
            "LAKEBASE_USER": "user",
            "LAKEBASE_PASSWORD": "pass",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                service = LakebaseService()
                service._pool = mock_pool

                service.close_pool()

                mock_pool.closeall.assert_called_once()
                assert service._pool is None

    @patch("app.backend.services.lakebase_service.psycopg2", create=True)
    def test_connection_string_bypasses_pool(self, mock_psycopg2):
        """Test that connection string mode doesn't use pooling."""
        mock_conn = MagicMock()
        mock_psycopg2.connect.return_value = mock_conn

        env_vars = {
            "LAKEBASE_CONNECTION_STRING": "postgresql://user:pass@host:5432/db",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                service = LakebaseService()

                with service._get_connection() as conn:
                    assert conn is mock_conn

                mock_psycopg2.connect.assert_called_once()
                assert service._pool is None


class TestSchemaMigrationRetry:
    """Tests for schema migration retry logic."""

    @patch("app.backend.services.lakebase_service.psycopg2", create=True)
    def test_migration_retries_on_failure(self, mock_psycopg2):
        """Test flag NOT set after failure, allowing retry."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=False)
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=False)
        mock_cursor.execute.side_effect = Exception("connection lost")
        mock_conn.cursor.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        env_vars = {
            "LAKEBASE_CONNECTION_STRING": "postgresql://user:pass@host:5432/db",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                service = LakebaseService()

                service._ensure_airport_columns()

                # Flag should NOT be set after single failure
                assert service._airport_columns_ensured is False
                assert service._airport_columns_retries == 1

    @patch("app.backend.services.lakebase_service.psycopg2", create=True)
    def test_migration_succeeds_after_retry(self, mock_psycopg2):
        """Test migration succeeds on second attempt."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=False)
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        env_vars = {
            "LAKEBASE_CONNECTION_STRING": "postgresql://user:pass@host:5432/db",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                service = LakebaseService()

                # First call fails
                mock_cursor.execute.side_effect = Exception("connection lost")
                service._ensure_airport_columns()
                assert service._airport_columns_ensured is False

                # Second call succeeds
                mock_cursor.execute.side_effect = None
                service._ensure_airport_columns()
                assert service._airport_columns_ensured is True

    @patch("app.backend.services.lakebase_service.psycopg2", create=True)
    def test_migration_stops_after_max_retries(self, mock_psycopg2):
        """Test migration gives up after 3 failures."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=False)
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=False)
        mock_cursor.execute.side_effect = Exception("persistent failure")
        mock_conn.cursor.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        env_vars = {
            "LAKEBASE_CONNECTION_STRING": "postgresql://user:pass@host:5432/db",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                service = LakebaseService()

                for _ in range(3):
                    service._ensure_airport_columns()

                # After 3 retries, should give up and mark as ensured
                assert service._airport_columns_ensured is True
                assert service._airport_columns_retries == 3

    @patch("app.backend.services.lakebase_service.psycopg2", create=True)
    def test_migration_flag_set_on_success(self, mock_psycopg2):
        """Test flag set after successful commit."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=False)
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        env_vars = {
            "LAKEBASE_CONNECTION_STRING": "postgresql://user:pass@host:5432/db",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                service = LakebaseService()

                service._ensure_airport_columns()

                assert service._airport_columns_ensured is True
                mock_conn.commit.assert_called_once()

    @patch("app.backend.services.lakebase_service.psycopg2", create=True)
    def test_ml_tables_migration_retries(self, mock_psycopg2):
        """Test ML tables migration has same retry logic."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=False)
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=False)
        mock_cursor.execute.side_effect = Exception("connection lost")
        mock_conn.cursor.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        env_vars = {
            "LAKEBASE_CONNECTION_STRING": "postgresql://user:pass@host:5432/db",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                service = LakebaseService()

                service._ensure_ml_tables()
                assert service._ml_tables_ensured is False
                assert service._ml_tables_retries == 1

                # After 3 failures, gives up
                service._ensure_ml_tables()
                service._ensure_ml_tables()
                assert service._ml_tables_ensured is True
                assert service._ml_tables_retries == 3


class TestLakebaseReadReplica:
    """Tests for read replica auto-discovery and connection routing."""

    def _make_service(self, **extra_env):
        """Create a LakebaseService with OAuth config."""
        env_vars = {
            "LAKEBASE_HOST": "primary.databricks.com",
            "LAKEBASE_PORT": "5432",
            "LAKEBASE_DATABASE": "databricks_postgres",
            "LAKEBASE_SCHEMA": "public",
            "LAKEBASE_ENDPOINT_NAME": "projects/test/branches/prod/endpoints/primary",
            "LAKEBASE_USE_OAUTH": "true",
            **extra_env,
        }
        with patch.dict(os.environ, env_vars, clear=True):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                return LakebaseService()

    def test_discover_read_replica_success(self):
        """Test auto-discovery finds read_only_host from SDK endpoint."""
        service = self._make_service()

        mock_ep = MagicMock()
        mock_ep.status.hosts.read_only_host = "replica.databricks.com"

        with patch("app.backend.services.lakebase_service.LakebaseService._discover_read_replica") as mock_discover:
            mock_discover.return_value = "replica.databricks.com"
            # Simulate lazy discovery
            service._read_host_discovered = False
            service._read_host = None

        # Test the actual method
        with patch("databricks.sdk.WorkspaceClient") as MockWC:
            mock_wc = MockWC.return_value
            mock_wc.postgres.get_endpoint.return_value = mock_ep

            result = service._discover_read_replica()
            assert result == "replica.databricks.com"
            mock_wc.postgres.get_endpoint.assert_called_once_with(
                name="projects/test/branches/prod/endpoints/primary"
            )

    def test_discover_read_replica_none_when_not_configured(self):
        """Test discovery returns None when endpoint has no read replica."""
        service = self._make_service()

        mock_ep = MagicMock()
        mock_ep.status.hosts.read_only_host = None

        with patch("databricks.sdk.WorkspaceClient") as MockWC:
            mock_wc = MockWC.return_value
            mock_wc.postgres.get_endpoint.return_value = mock_ep

            result = service._discover_read_replica()
            assert result is None

    def test_discover_read_replica_none_without_oauth(self):
        """Test discovery returns None when OAuth not configured."""
        env_vars = {
            "LAKEBASE_HOST": "primary.databricks.com",
            "LAKEBASE_USER": "user",
            "LAKEBASE_PASSWORD": "pass",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                service = LakebaseService()
                result = service._discover_read_replica()
                assert result is None

    def test_discover_read_replica_graceful_on_sdk_error(self):
        """Test discovery returns None and doesn't raise on SDK errors."""
        service = self._make_service()

        with patch("databricks.sdk.WorkspaceClient") as MockWC:
            MockWC.side_effect = Exception("SDK unavailable")
            result = service._discover_read_replica()
            assert result is None

    def test_read_pool_uses_replica_host(self):
        """Test read pool is created with replica host, not primary."""
        service = self._make_service()
        service._read_host_discovered = True
        service._read_host = "replica.databricks.com"

        # Mock credentials and pool creation
        with patch.object(service, "_get_credentials", return_value=("token", "user@db.com")):
            with patch("app.backend.services.lakebase_service.ThreadedConnectionPool") as MockPool:
                mock_pool = MagicMock()
                mock_pool.closed = False
                MockPool.return_value = mock_pool

                pool = service._get_or_create_read_pool()
                assert pool is mock_pool
                # Verify pool was created with replica host
                call_kwargs = MockPool.call_args
                assert call_kwargs.kwargs["host"] == "replica.databricks.com"

    def test_read_pool_returns_none_without_replica(self):
        """Test read pool returns None when no replica discovered."""
        service = self._make_service()
        service._read_host_discovered = True
        service._read_host = None

        pool = service._get_or_create_read_pool()
        assert pool is None

    def test_get_read_connection_uses_replica_pool(self):
        """Test _get_read_connection uses the read pool when available."""
        service = self._make_service()

        mock_read_conn = MagicMock()
        mock_read_pool = MagicMock()
        mock_read_pool.closed = False
        mock_read_pool.getconn.return_value = mock_read_conn

        with patch.object(service, "_get_or_create_read_pool", return_value=mock_read_pool):
            with service._get_read_connection() as conn:
                assert conn is mock_read_conn
            mock_read_pool.getconn.assert_called_once()
            mock_read_pool.putconn.assert_called_once_with(mock_read_conn)

    def test_get_read_connection_falls_back_to_primary(self):
        """Test _get_read_connection falls back to primary when no replica."""
        service = self._make_service()

        mock_primary_conn = MagicMock()

        with patch.object(service, "_get_or_create_read_pool", return_value=None):
            with patch.object(service, "_get_connection") as mock_get_conn:
                mock_get_conn.return_value.__enter__ = Mock(return_value=mock_primary_conn)
                mock_get_conn.return_value.__exit__ = Mock(return_value=False)
                with service._get_read_connection() as conn:
                    assert conn is mock_primary_conn

    def test_invalidate_pool_clears_both_pools(self):
        """Test _invalidate_pool tears down both primary and read pools."""
        service = self._make_service()

        mock_primary_pool = MagicMock()
        mock_read_pool = MagicMock()
        service._pool = mock_primary_pool
        service._read_pool = mock_read_pool

        service._invalidate_pool()

        mock_primary_pool.closeall.assert_called_once()
        mock_read_pool.closeall.assert_called_once()
        assert service._pool is None
        assert service._read_pool is None

    def test_discovery_called_lazily_once(self):
        """Test replica discovery is only called on first read pool request."""
        service = self._make_service()
        assert service._read_host_discovered is False

        with patch.object(service, "_discover_read_replica", return_value=None) as mock_discover:
            service._get_or_create_read_pool()
            assert mock_discover.call_count == 1
            assert service._read_host_discovered is True

            # Second call should NOT re-discover
            service._get_or_create_read_pool()
            assert mock_discover.call_count == 1

    @patch("app.backend.services.lakebase_service.RealDictCursor", create=True)
    @patch("app.backend.services.lakebase_service.psycopg2", create=True)
    def test_get_flights_uses_read_connection(self, mock_psycopg2, mock_rdc):
        """Test that get_flights routes through _get_read_connection."""
        service = self._make_service()

        with patch.object(service, "_get_read_connection") as mock_read:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = []
            mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)
            mock_read.return_value.__enter__ = Mock(return_value=mock_conn)
            mock_read.return_value.__exit__ = Mock(return_value=False)

            service.get_flights(limit=10)
            mock_read.assert_called_once()

    @patch("app.backend.services.lakebase_service.psycopg2", create=True)
    def test_upsert_weather_uses_primary_connection(self, mock_psycopg2):
        """Test that write methods still use primary _get_connection."""
        service = self._make_service()

        with patch.object(service, "_get_connection") as mock_primary:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)
            mock_primary.return_value.__enter__ = Mock(return_value=mock_conn)
            mock_primary.return_value.__exit__ = Mock(return_value=False)

            service.upsert_weather({
                "station": "KSFO", "observation_time": "2026-01-01T00:00:00Z",
                "wind_direction": 0, "wind_speed_kts": 0, "wind_gust_kts": None,
                "visibility_sm": 10, "clouds": "[]", "temperature_c": 15,
                "dewpoint_c": 10, "altimeter_inhg": 30.0, "weather": "[]",
                "flight_category": "VFR", "raw_metar": "", "taf_text": None,
                "taf_valid_from": None, "taf_valid_to": None,
            })
            mock_primary.assert_called()

        # Verify _get_read_connection was NOT called for write
        with patch.object(service, "_get_read_connection") as mock_read:
            with patch.object(service, "_get_connection") as mock_primary2:
                mock_conn2 = MagicMock()
                mock_cursor2 = MagicMock()
                mock_conn2.cursor.return_value.__enter__ = Mock(return_value=mock_cursor2)
                mock_conn2.cursor.return_value.__exit__ = Mock(return_value=False)
                mock_primary2.return_value.__enter__ = Mock(return_value=mock_conn2)
                mock_primary2.return_value.__exit__ = Mock(return_value=False)

                service.upsert_weather({
                    "station": "KSFO", "observation_time": "2026-01-01T00:00:00Z",
                    "wind_direction": 0, "wind_speed_kts": 0, "wind_gust_kts": None,
                    "visibility_sm": 10, "clouds": "[]", "temperature_c": 15,
                    "dewpoint_c": 10, "altimeter_inhg": 30.0, "weather": "[]",
                    "flight_category": "VFR", "raw_metar": "", "taf_text": None,
                    "taf_valid_from": None, "taf_valid_to": None,
                })
                mock_read.assert_not_called()


class TestInsertFlightSnapshots:
    """Tests for insert_flight_snapshots including data_source column."""

    def _make_service(self):
        env_vars = {
            "LAKEBASE_CONNECTION_STRING": "postgresql://user:pass@host:5432/db",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                service = LakebaseService()
                service._ml_tables_ensured = True  # Skip migration
                return service

    def test_returns_zero_when_unavailable(self):
        with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", False):
            from app.backend.services.lakebase_service import LakebaseService
            service = LakebaseService()
            result = service.insert_flight_snapshots([{"icao24": "abc"}], "sess", "KSFO")
            assert result == 0

    def test_returns_zero_for_empty_snapshots(self):
        service = self._make_service()
        result = service.insert_flight_snapshots([], "sess", "KSFO")
        assert result == 0

    def test_includes_data_source_in_insert(self):
        service = self._make_service()

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)

        with patch.object(service, "_get_connection", return_value=mock_conn):
            with patch("app.backend.services.lakebase_service.execute_values") as mock_exec:
                result = service.insert_flight_snapshots(
                    [{"icao24": "abc123", "data_source": "opensky", "snapshot_time": "2026-04-02T10:00:00Z"}],
                    "sess-1",
                    "KSFO",
                )

        assert result == 1
        # Verify data_source is in the SQL and values
        sql_arg = mock_exec.call_args[0][1]
        assert "data_source" in sql_arg
        values_arg = mock_exec.call_args[0][2]
        # data_source should be in the tuple
        assert "opensky" in values_arg[0]

    def test_data_source_defaults_to_simulation(self):
        service = self._make_service()

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)

        with patch.object(service, "_get_connection", return_value=mock_conn):
            with patch("app.backend.services.lakebase_service.execute_values") as mock_exec:
                service.insert_flight_snapshots(
                    [{"icao24": "abc123"}],
                    "sess-1",
                    "KSFO",
                )

        values_arg = mock_exec.call_args[0][2]
        # Without data_source in dict, should default to 'simulation'
        assert "simulation" in values_arg[0]

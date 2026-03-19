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

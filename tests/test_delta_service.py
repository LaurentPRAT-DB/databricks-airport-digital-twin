"""Tests for DeltaService - querying flight data via Databricks SQL."""

import pytest
from unittest.mock import patch, MagicMock, PropertyMock
import os

from app.backend.services.delta_service import (
    DeltaService,
    get_delta_service,
    DATABRICKS_SQL_AVAILABLE,
)


class TestDeltaServiceInit:
    """Tests for DeltaService initialization."""

    def test_init_reads_environment_variables(self):
        """Test that init reads connection params from environment."""
        with patch.dict(os.environ, {
            "DATABRICKS_HOST": "test-host.databricks.com",
            "DATABRICKS_HTTP_PATH": "/sql/1.0/warehouses/abc123",
            "DATABRICKS_TOKEN": "test-token",
            "DATABRICKS_CATALOG": "test_catalog",
            "DATABRICKS_SCHEMA": "test_schema",
        }, clear=False):
            service = DeltaService()
            assert service._host == "test-host.databricks.com"
            assert service._http_path == "/sql/1.0/warehouses/abc123"
            assert service._token == "test-token"
            assert service._catalog == "test_catalog"
            assert service._schema == "test_schema"

    def test_init_with_alternate_env_vars(self):
        """Test that init reads alternate environment variable names."""
        with patch.dict(os.environ, {
            "DATABRICKS_SERVER_HOSTNAME": "alt-host.databricks.com",
            "DATABRICKS_WAREHOUSE_HTTP_PATH": "/sql/alt/path",
            "DATABRICKS_ACCESS_TOKEN": "alt-token",
        }, clear=True):
            service = DeltaService()
            assert service._host == "alt-host.databricks.com"
            assert service._http_path == "/sql/alt/path"
            assert service._token == "alt-token"

    def test_init_default_catalog_schema(self):
        """Test that init uses default catalog and schema."""
        with patch.dict(os.environ, {}, clear=True):
            service = DeltaService()
            assert service._catalog == "main"
            assert service._schema == "airport_digital_twin"

    def test_init_oauth_mode(self):
        """Test that OAuth mode is detected from environment."""
        with patch.dict(os.environ, {
            "DATABRICKS_USE_OAUTH": "true",
        }, clear=False):
            service = DeltaService()
            assert service._use_oauth is True

        with patch.dict(os.environ, {
            "DATABRICKS_USE_OAUTH": "false",
        }, clear=False):
            service = DeltaService()
            assert service._use_oauth is False


class TestDeltaServiceIsAvailable:
    """Tests for DeltaService.is_available property."""

    @patch('app.backend.services.delta_service.DATABRICKS_SQL_AVAILABLE', True)
    def test_available_when_configured(self):
        """Test is_available returns True when properly configured."""
        with patch.dict(os.environ, {
            "DATABRICKS_HOST": "test.databricks.com",
            "DATABRICKS_HTTP_PATH": "/sql/path",
        }, clear=False):
            service = DeltaService()
            assert service.is_available is True

    @patch('app.backend.services.delta_service.DATABRICKS_SQL_AVAILABLE', True)
    def test_unavailable_without_host(self):
        """Test is_available returns False without host."""
        with patch.dict(os.environ, {
            "DATABRICKS_HTTP_PATH": "/sql/path",
        }, clear=True):
            service = DeltaService()
            assert service.is_available is False

    @patch('app.backend.services.delta_service.DATABRICKS_SQL_AVAILABLE', True)
    def test_unavailable_without_http_path(self):
        """Test is_available returns False without http_path."""
        with patch.dict(os.environ, {
            "DATABRICKS_HOST": "test.databricks.com",
        }, clear=True):
            service = DeltaService()
            assert service.is_available is False

    @patch('app.backend.services.delta_service.DATABRICKS_SQL_AVAILABLE', False)
    def test_unavailable_without_connector(self):
        """Test is_available returns False when connector not installed."""
        with patch.dict(os.environ, {
            "DATABRICKS_HOST": "test.databricks.com",
            "DATABRICKS_HTTP_PATH": "/sql/path",
        }, clear=False):
            service = DeltaService()
            assert service.is_available is False


class TestDeltaServiceGetConnection:
    """Tests for DeltaService._get_connection method."""

    @patch('app.backend.services.delta_service.sql')
    def test_get_connection_with_token(self, mock_sql):
        """Test connection uses token authentication."""
        with patch.dict(os.environ, {
            "DATABRICKS_HOST": "test.databricks.com",
            "DATABRICKS_HTTP_PATH": "/sql/path",
            "DATABRICKS_TOKEN": "test-token",
            "DATABRICKS_USE_OAUTH": "false",
        }, clear=False):
            service = DeltaService()
            service._get_connection()

            mock_sql.connect.assert_called_once()
            call_kwargs = mock_sql.connect.call_args.kwargs
            assert call_kwargs["server_hostname"] == "test.databricks.com"
            assert call_kwargs["http_path"] == "/sql/path"
            assert call_kwargs["access_token"] == "test-token"

    @patch('app.backend.services.delta_service.sql')
    def test_get_connection_with_oauth(self, mock_sql):
        """Test connection uses OAuth when configured."""
        with patch.dict(os.environ, {
            "DATABRICKS_HOST": "test.databricks.com",
            "DATABRICKS_HTTP_PATH": "/sql/path",
            "DATABRICKS_USE_OAUTH": "true",
        }, clear=False):
            service = DeltaService()
            service._get_connection()

            mock_sql.connect.assert_called_once()
            call_kwargs = mock_sql.connect.call_args.kwargs
            assert call_kwargs.get("credentials_provider") is None
            assert "access_token" not in call_kwargs


class TestDeltaServiceGetFlights:
    """Tests for DeltaService.get_flights method."""

    def test_get_flights_unavailable(self):
        """Test get_flights returns None when service unavailable."""
        with patch.dict(os.environ, {}, clear=True):
            service = DeltaService()
            result = service.get_flights()
            assert result is None

    @patch('app.backend.services.delta_service.DATABRICKS_SQL_AVAILABLE', True)
    @patch('app.backend.services.delta_service.sql')
    def test_get_flights_success(self, mock_sql):
        """Test get_flights returns flight data on success."""
        # Mock cursor and connection
        mock_cursor = MagicMock()
        mock_cursor.description = [
            ("icao24",), ("callsign",), ("latitude",), ("longitude",),
            ("altitude",), ("velocity",), ("heading",), ("on_ground",),
            ("vertical_rate",), ("last_seen",), ("flight_phase",), ("data_source",),
        ]
        mock_cursor.fetchall.return_value = [
            ("abc123", "UAL123", 37.6, -122.4, 5000, 250, 90, False, 0, 1709900000, "CRUISING", "synthetic"),
            ("def456", "DAL456", 37.7, -122.5, 10000, 300, 180, False, -500, 1709900001, "DESCENDING", "synthetic"),
        ]

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        mock_sql.connect.return_value = mock_conn

        with patch.dict(os.environ, {
            "DATABRICKS_HOST": "test.databricks.com",
            "DATABRICKS_HTTP_PATH": "/sql/path",
        }, clear=False):
            service = DeltaService()
            result = service.get_flights(limit=50)

            assert result is not None
            assert len(result) == 2
            assert result[0]["icao24"] == "abc123"
            assert result[0]["callsign"] == "UAL123"
            assert result[1]["icao24"] == "def456"

    @patch('app.backend.services.delta_service.DATABRICKS_SQL_AVAILABLE', True)
    @patch('app.backend.services.delta_service.sql')
    def test_get_flights_query_exception(self, mock_sql):
        """Test get_flights returns None on query exception."""
        mock_sql.connect.side_effect = Exception("Connection failed")

        with patch.dict(os.environ, {
            "DATABRICKS_HOST": "test.databricks.com",
            "DATABRICKS_HTTP_PATH": "/sql/path",
        }, clear=False):
            service = DeltaService()
            result = service.get_flights()
            assert result is None


class TestDeltaServiceGetFlightByIcao24:
    """Tests for DeltaService.get_flight_by_icao24 method."""

    def test_get_flight_by_icao24_unavailable(self):
        """Test get_flight_by_icao24 returns None when service unavailable."""
        with patch.dict(os.environ, {}, clear=True):
            service = DeltaService()
            result = service.get_flight_by_icao24("abc123")
            assert result is None

    @patch('app.backend.services.delta_service.DATABRICKS_SQL_AVAILABLE', True)
    @patch('app.backend.services.delta_service.sql')
    def test_get_flight_by_icao24_found(self, mock_sql):
        """Test get_flight_by_icao24 returns flight when found."""
        mock_cursor = MagicMock()
        mock_cursor.description = [
            ("icao24",), ("callsign",), ("latitude",), ("longitude",),
            ("altitude",), ("velocity",), ("heading",), ("on_ground",),
            ("vertical_rate",), ("last_seen",), ("flight_phase",), ("data_source",),
        ]
        mock_cursor.fetchone.return_value = (
            "abc123", "UAL123", 37.6, -122.4, 5000, 250, 90, False, 0, 1709900000, "CRUISING", "synthetic"
        )

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        mock_sql.connect.return_value = mock_conn

        with patch.dict(os.environ, {
            "DATABRICKS_HOST": "test.databricks.com",
            "DATABRICKS_HTTP_PATH": "/sql/path",
        }, clear=False):
            service = DeltaService()
            result = service.get_flight_by_icao24("abc123")

            assert result is not None
            assert result["icao24"] == "abc123"
            assert result["callsign"] == "UAL123"

    @patch('app.backend.services.delta_service.DATABRICKS_SQL_AVAILABLE', True)
    @patch('app.backend.services.delta_service.sql')
    def test_get_flight_by_icao24_not_found(self, mock_sql):
        """Test get_flight_by_icao24 returns None when not found."""
        mock_cursor = MagicMock()
        mock_cursor.description = [("icao24",)]
        mock_cursor.fetchone.return_value = None

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        mock_sql.connect.return_value = mock_conn

        with patch.dict(os.environ, {
            "DATABRICKS_HOST": "test.databricks.com",
            "DATABRICKS_HTTP_PATH": "/sql/path",
        }, clear=False):
            service = DeltaService()
            result = service.get_flight_by_icao24("nonexistent")
            assert result is None

    @patch('app.backend.services.delta_service.DATABRICKS_SQL_AVAILABLE', True)
    @patch('app.backend.services.delta_service.sql')
    def test_get_flight_by_icao24_exception(self, mock_sql):
        """Test get_flight_by_icao24 handles exceptions."""
        mock_sql.connect.side_effect = Exception("Query failed")

        with patch.dict(os.environ, {
            "DATABRICKS_HOST": "test.databricks.com",
            "DATABRICKS_HTTP_PATH": "/sql/path",
        }, clear=False):
            service = DeltaService()
            result = service.get_flight_by_icao24("abc123")
            assert result is None


class TestDeltaServiceGetTrajectory:
    """Tests for DeltaService.get_trajectory method."""

    def test_get_trajectory_unavailable(self):
        """Test get_trajectory returns None when service unavailable."""
        with patch.dict(os.environ, {}, clear=True):
            service = DeltaService()
            result = service.get_trajectory("abc123")
            assert result is None

    @patch('app.backend.services.delta_service.DATABRICKS_SQL_AVAILABLE', True)
    @patch('app.backend.services.delta_service.sql')
    def test_get_trajectory_success(self, mock_sql):
        """Test get_trajectory returns position history."""
        mock_cursor = MagicMock()
        mock_cursor.description = [
            ("icao24",), ("callsign",), ("latitude",), ("longitude",),
            ("altitude",), ("velocity",), ("heading",), ("vertical_rate",),
            ("on_ground",), ("flight_phase",), ("timestamp",),
        ]
        mock_cursor.fetchall.return_value = [
            ("abc123", "UAL123", 37.60, -122.40, 5000, 250, 90, 0, False, "CRUISING", 1709900000),
            ("abc123", "UAL123", 37.61, -122.41, 5100, 250, 91, 100, False, "CRUISING", 1709900060),
            ("abc123", "UAL123", 37.62, -122.42, 5200, 250, 92, 100, False, "CRUISING", 1709900120),
        ]

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        mock_sql.connect.return_value = mock_conn

        with patch.dict(os.environ, {
            "DATABRICKS_HOST": "test.databricks.com",
            "DATABRICKS_HTTP_PATH": "/sql/path",
        }, clear=False):
            service = DeltaService()
            result = service.get_trajectory("abc123", minutes=30, limit=100)

            assert result is not None
            assert len(result) == 3
            assert result[0]["latitude"] == 37.60
            assert result[2]["latitude"] == 37.62

    @patch('app.backend.services.delta_service.DATABRICKS_SQL_AVAILABLE', True)
    @patch('app.backend.services.delta_service.sql')
    def test_get_trajectory_validates_minutes(self, mock_sql):
        """Test get_trajectory validates minutes parameter."""
        mock_cursor = MagicMock()
        mock_cursor.description = [("icao24",)]
        mock_cursor.fetchall.return_value = []

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        mock_sql.connect.return_value = mock_conn

        with patch.dict(os.environ, {
            "DATABRICKS_HOST": "test.databricks.com",
            "DATABRICKS_HTTP_PATH": "/sql/path",
        }, clear=False):
            service = DeltaService()

            # Test with invalid minutes - should default to 60
            result = service.get_trajectory("abc123", minutes=-1)
            assert result is not None  # Should not raise

            result = service.get_trajectory("abc123", minutes=10000)
            assert result is not None  # Should not raise

    @patch('app.backend.services.delta_service.DATABRICKS_SQL_AVAILABLE', True)
    @patch('app.backend.services.delta_service.sql')
    def test_get_trajectory_exception(self, mock_sql):
        """Test get_trajectory handles exceptions."""
        mock_sql.connect.side_effect = Exception("Query failed")

        with patch.dict(os.environ, {
            "DATABRICKS_HOST": "test.databricks.com",
            "DATABRICKS_HTTP_PATH": "/sql/path",
        }, clear=False):
            service = DeltaService()
            result = service.get_trajectory("abc123")
            assert result is None


class TestDeltaServiceHealthCheck:
    """Tests for DeltaService.health_check method."""

    def test_health_check_unavailable(self):
        """Test health_check returns False when service unavailable."""
        with patch.dict(os.environ, {}, clear=True):
            service = DeltaService()
            result = service.health_check()
            assert result is False

    @patch('app.backend.services.delta_service.DATABRICKS_SQL_AVAILABLE', True)
    @patch('app.backend.services.delta_service.sql')
    def test_health_check_success(self, mock_sql):
        """Test health_check returns True when connection healthy."""
        mock_cursor = MagicMock()
        mock_cursor.execute.return_value = None

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        mock_sql.connect.return_value = mock_conn

        with patch.dict(os.environ, {
            "DATABRICKS_HOST": "test.databricks.com",
            "DATABRICKS_HTTP_PATH": "/sql/path",
        }, clear=False):
            service = DeltaService()
            result = service.health_check()
            assert result is True
            mock_cursor.execute.assert_called_with("SELECT 1")

    @patch('app.backend.services.delta_service.DATABRICKS_SQL_AVAILABLE', True)
    @patch('app.backend.services.delta_service.sql')
    def test_health_check_failure(self, mock_sql):
        """Test health_check returns False on connection failure."""
        mock_sql.connect.side_effect = Exception("Connection refused")

        with patch.dict(os.environ, {
            "DATABRICKS_HOST": "test.databricks.com",
            "DATABRICKS_HTTP_PATH": "/sql/path",
        }, clear=False):
            service = DeltaService()
            result = service.health_check()
            assert result is False


class TestGetDeltaService:
    """Tests for get_delta_service singleton function."""

    def test_returns_singleton(self):
        """Test that get_delta_service returns same instance."""
        service1 = get_delta_service()
        service2 = get_delta_service()
        assert service1 is service2

    def test_service_is_delta_service(self):
        """Test that singleton is a DeltaService instance."""
        service = get_delta_service()
        assert isinstance(service, DeltaService)

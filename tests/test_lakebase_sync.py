"""Tests for Lakebase to Unity Catalog sync script.

Tests the sync_all_to_unity_catalog.py script that syncs operational data
from Lakebase PostgreSQL to Unity Catalog Delta tables.
"""

import os
import sys
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

# Ensure psycopg2 and databricks.sql are available as mocks when not installed
_mock_psycopg2 = None
_mock_databricks_sql = None

if "psycopg2" not in sys.modules:
    _mock_psycopg2 = MagicMock()
    _mock_psycopg2.extras = MagicMock()
    _mock_psycopg2.extras.RealDictCursor = MagicMock()
    sys.modules["psycopg2"] = _mock_psycopg2
    sys.modules["psycopg2.extras"] = _mock_psycopg2.extras

if "databricks" not in sys.modules or not hasattr(sys.modules.get("databricks", None), "sql"):
    _mock_databricks = sys.modules.get("databricks", MagicMock())
    _mock_databricks_sql = MagicMock()
    _mock_databricks.sql = _mock_databricks_sql
    sys.modules.setdefault("databricks", _mock_databricks)
    sys.modules["databricks.sql"] = _mock_databricks_sql


class TestQuoteValue:
    """Tests for _quote_value helper function."""

    def test_quote_value_none(self):
        """Test quoting None values."""
        from scripts.sync_all_to_unity_catalog import _quote_value

        assert _quote_value(None) == "NULL"

    def test_quote_value_boolean(self):
        """Test quoting boolean values."""
        from scripts.sync_all_to_unity_catalog import _quote_value

        assert _quote_value(True) == "true"
        assert _quote_value(False) == "false"

    def test_quote_value_integer(self):
        """Test quoting integer values."""
        from scripts.sync_all_to_unity_catalog import _quote_value

        assert _quote_value(42) == "42"
        assert _quote_value(0) == "0"
        assert _quote_value(-10) == "-10"

    def test_quote_value_float(self):
        """Test quoting float values."""
        from scripts.sync_all_to_unity_catalog import _quote_value

        assert _quote_value(3.14) == "3.14"
        assert _quote_value(0.0) == "0.0"

    def test_quote_value_datetime(self):
        """Test quoting datetime values."""
        from scripts.sync_all_to_unity_catalog import _quote_value

        dt = datetime(2026, 3, 8, 10, 30, 0, tzinfo=timezone.utc)
        result = _quote_value(dt)
        assert result.startswith("'")
        assert result.endswith("'")
        assert "2026-03-08" in result

    def test_quote_value_string(self):
        """Test quoting string values."""
        from scripts.sync_all_to_unity_catalog import _quote_value

        assert _quote_value("hello") == "'hello'"
        assert _quote_value("test value") == "'test value'"

    def test_quote_value_string_with_quotes(self):
        """Test quoting string values with embedded quotes."""
        from scripts.sync_all_to_unity_catalog import _quote_value

        result = _quote_value("it's a test")
        assert result == "'it''s a test'"


class TestLakebaseConnection:
    """Tests for Lakebase connection function."""

    def test_get_lakebase_connection_with_connection_string(self):
        """Test connection with connection string."""
        mock_connect = MagicMock()

        with patch.dict(os.environ, {"LAKEBASE_CONNECTION_STRING": "postgresql://test:test@localhost/db"}, clear=True):
            with patch("psycopg2.connect", mock_connect):
                from scripts.sync_all_to_unity_catalog import get_lakebase_connection
                get_lakebase_connection()

            mock_connect.assert_called_once_with("postgresql://test:test@localhost/db")

    def test_get_lakebase_connection_with_credentials(self):
        """Test connection with direct credentials."""
        mock_connect = MagicMock()

        env_vars = {
            "LAKEBASE_HOST": "localhost",
            "LAKEBASE_PORT": "5432",
            "LAKEBASE_DATABASE": "test_db",
            "LAKEBASE_USER": "testuser",
            "LAKEBASE_PASSWORD": "testpass",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            with patch("psycopg2.connect", mock_connect):
                from scripts.sync_all_to_unity_catalog import get_lakebase_connection
                get_lakebase_connection()

            mock_connect.assert_called_once_with(
                host="localhost",
                port="5432",
                database="test_db",
                user="testuser",
                password="testpass",
                sslmode="require",
            )


class TestDeltaConnection:
    """Tests for Delta connection function."""

    def test_get_delta_connection(self):
        """Test Delta SQL connection."""
        mock_connect = MagicMock()

        env_vars = {
            "DATABRICKS_HOST": "test.databricks.com",
            "DATABRICKS_HTTP_PATH": "/sql/1.0/warehouses/abc123",
            "DATABRICKS_TOKEN": "dapi12345",
        }
        with patch.dict(os.environ, env_vars):
            with patch("databricks.sql.connect", mock_connect):
                from scripts.sync_all_to_unity_catalog import get_delta_connection
                get_delta_connection()

            mock_connect.assert_called_once_with(
                server_hostname="test.databricks.com",
                http_path="/sql/1.0/warehouses/abc123",
                access_token="dapi12345",
            )


class TestFetchFromLakebase:
    """Tests for fetching data from Lakebase."""

    def test_fetch_weather_from_lakebase(self):
        """Test fetching weather observations."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
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
                "taf_text": None,
                "taf_valid_from": None,
                "taf_valid_to": None,
            }
        ]

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch("scripts.sync_all_to_unity_catalog.get_lakebase_connection", return_value=mock_conn):
            from scripts.sync_all_to_unity_catalog import fetch_weather_from_lakebase
            result = fetch_weather_from_lakebase()

        assert len(result) == 1
        assert result[0]["station"] == "KSFO"

    def test_fetch_schedule_from_lakebase(self):
        """Test fetching flight schedule."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                "flight_number": "UA123",
                "airline": "United Airlines",
                "airline_code": "UA",
                "origin": "SFO",
                "destination": "LAX",
                "scheduled_time": datetime.now(timezone.utc),
                "estimated_time": None,
                "actual_time": None,
                "gate": "A1",
                "status": "On Time",
                "delay_minutes": 0,
                "delay_reason": None,
                "aircraft_type": "A320",
                "flight_type": "departure",
            }
        ]

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch("scripts.sync_all_to_unity_catalog.get_lakebase_connection", return_value=mock_conn):
            from scripts.sync_all_to_unity_catalog import fetch_schedule_from_lakebase
            result = fetch_schedule_from_lakebase()

        assert len(result) == 1
        assert result[0]["flight_number"] == "UA123"

    def test_fetch_baggage_from_lakebase(self):
        """Test fetching baggage status."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                "flight_number": "UA123",
                "total_bags": 150,
                "checked_in": 140,
                "loaded": 100,
                "unloaded": 0,
                "on_carousel": 0,
                "loading_progress_pct": 67,
                "connecting_bags": 10,
                "misconnects": 0,
                "carousel": None,
            }
        ]

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch("scripts.sync_all_to_unity_catalog.get_lakebase_connection", return_value=mock_conn):
            from scripts.sync_all_to_unity_catalog import fetch_baggage_from_lakebase
            result = fetch_baggage_from_lakebase()

        assert len(result) == 1
        assert result[0]["total_bags"] == 150

    def test_fetch_gse_fleet_from_lakebase(self):
        """Test fetching GSE fleet."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                "unit_id": "PUS-001",
                "gse_type": "pushback_tug",
                "status": "available",
                "assigned_flight": None,
                "assigned_gate": None,
                "position_x": 0.0,
                "position_y": 0.0,
            }
        ]

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch("scripts.sync_all_to_unity_catalog.get_lakebase_connection", return_value=mock_conn):
            from scripts.sync_all_to_unity_catalog import fetch_gse_fleet_from_lakebase
            result = fetch_gse_fleet_from_lakebase()

        assert len(result) == 1
        assert result[0]["unit_id"] == "PUS-001"

    def test_fetch_turnaround_from_lakebase(self):
        """Test fetching turnaround status."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                "icao24": "abc123",
                "flight_number": "UA123",
                "gate": "A1",
                "arrival_time": datetime.now(timezone.utc),
                "current_phase": "deboarding",
                "phase_progress_pct": 50,
                "total_progress_pct": 25,
                "estimated_departure": datetime.now(timezone.utc),
                "aircraft_type": "A320",
            }
        ]

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch("scripts.sync_all_to_unity_catalog.get_lakebase_connection", return_value=mock_conn):
            from scripts.sync_all_to_unity_catalog import fetch_turnaround_from_lakebase
            result = fetch_turnaround_from_lakebase()

        assert len(result) == 1
        assert result[0]["icao24"] == "abc123"


class TestSyncToDelta:
    """Tests for syncing data to Delta tables."""

    def test_sync_weather_to_delta_empty(self):
        """Test syncing empty weather list."""
        from scripts.sync_all_to_unity_catalog import sync_weather_to_delta

        result = sync_weather_to_delta([], "catalog", "schema")
        assert result == 0

    def test_sync_weather_to_delta_success(self):
        """Test successful weather sync."""
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        observations = [
            {
                "station": "KSFO",
                "observation_time": datetime.now(timezone.utc),
                "wind_direction": 270,
                "wind_speed_kts": 10,
                "visibility_sm": 10.0,
                "clouds": "[]",
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
        ]

        with patch("scripts.sync_all_to_unity_catalog.get_delta_connection", return_value=mock_conn):
            from scripts.sync_all_to_unity_catalog import sync_weather_to_delta
            result = sync_weather_to_delta(observations, "main", "airport_digital_twin")

        assert result == 1
        mock_cursor.execute.assert_called_once()
        # Verify MERGE statement is used
        call_args = mock_cursor.execute.call_args[0][0]
        assert "MERGE INTO" in call_args
        assert "main.airport_digital_twin.weather_observations_gold" in call_args

    def test_sync_schedule_to_delta_success(self):
        """Test successful schedule sync."""
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        flights = [
            {
                "flight_number": "UA123",
                "airline": "United",
                "airline_code": "UA",
                "origin": "SFO",
                "destination": "LAX",
                "scheduled_time": datetime.now(timezone.utc),
                "estimated_time": None,
                "actual_time": None,
                "gate": "A1",
                "status": "On Time",
                "delay_minutes": 0,
                "delay_reason": None,
                "aircraft_type": "A320",
                "flight_type": "departure",
            }
        ]

        with patch("scripts.sync_all_to_unity_catalog.get_delta_connection", return_value=mock_conn):
            from scripts.sync_all_to_unity_catalog import sync_schedule_to_delta
            result = sync_schedule_to_delta(flights, "main", "airport_digital_twin")

        assert result == 1
        # Verify MERGE with composite key
        call_args = mock_cursor.execute.call_args[0][0]
        assert "MERGE INTO" in call_args
        assert "flight_number" in call_args
        assert "scheduled_time" in call_args


class TestAppendHistory:
    """Tests for appending to history tables."""

    def test_append_baggage_history_empty(self):
        """Test appending empty baggage list."""
        from scripts.sync_all_to_unity_catalog import append_baggage_history

        result = append_baggage_history([], "catalog", "schema")
        assert result == 0

    def test_append_baggage_history_success(self):
        """Test successful baggage history append."""
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        stats = [
            {
                "flight_number": "UA123",
                "total_bags": 150,
                "checked_in": 140,
                "loaded": 100,
                "unloaded": 0,
                "on_carousel": 0,
                "loading_progress_pct": 67,
                "connecting_bags": 10,
                "misconnects": 0,
                "carousel": None,
            }
        ]

        with patch("scripts.sync_all_to_unity_catalog.get_delta_connection", return_value=mock_conn):
            from scripts.sync_all_to_unity_catalog import append_baggage_history
            result = append_baggage_history(stats, "main", "airport_digital_twin")

        assert result == 1
        # Verify INSERT statement (not MERGE)
        call_args = mock_cursor.execute.call_args[0][0]
        assert "INSERT INTO" in call_args
        assert "baggage_events_history" in call_args

    def test_append_turnaround_history_success(self):
        """Test successful turnaround history append."""
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        turnarounds = [
            {
                "icao24": "abc123",
                "flight_number": "UA123",
                "gate": "A1",
                "arrival_time": datetime.now(timezone.utc),
                "current_phase": "deboarding",
                "phase_progress_pct": 50,
                "total_progress_pct": 25,
                "estimated_departure": datetime.now(timezone.utc),
                "aircraft_type": "A320",
            }
        ]

        with patch("scripts.sync_all_to_unity_catalog.get_delta_connection", return_value=mock_conn):
            from scripts.sync_all_to_unity_catalog import append_turnaround_history
            result = append_turnaround_history(turnarounds, "main", "airport_digital_twin")

        assert result == 1
        # Verify INSERT statement
        call_args = mock_cursor.execute.call_args[0][0]
        assert "INSERT INTO" in call_args
        assert "gse_turnaround_history" in call_args


class TestSyncGSEFleet:
    """Tests for GSE fleet sync."""

    def test_sync_gse_fleet_to_delta_success(self):
        """Test successful GSE fleet sync."""
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        units = [
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
                "position_x": 10.5,
                "position_y": 20.3,
            },
        ]

        with patch("scripts.sync_all_to_unity_catalog.get_delta_connection", return_value=mock_conn):
            from scripts.sync_all_to_unity_catalog import sync_gse_fleet_to_delta
            result = sync_gse_fleet_to_delta(units, "main", "airport_digital_twin")

        assert result == 2
        assert mock_cursor.execute.call_count == 2


class TestMainFunction:
    """Tests for main sync function."""

    @patch.dict(os.environ, {
        "DATABRICKS_CATALOG": "test_catalog",
        "DATABRICKS_SCHEMA": "test_schema",
    })
    def test_main_success(self):
        """Test successful main sync."""
        with patch("scripts.sync_all_to_unity_catalog.fetch_weather_from_lakebase", return_value=[{"station": "KSFO"}]), \
             patch("scripts.sync_all_to_unity_catalog.fetch_schedule_from_lakebase", return_value=[]), \
             patch("scripts.sync_all_to_unity_catalog.fetch_baggage_from_lakebase", return_value=[]), \
             patch("scripts.sync_all_to_unity_catalog.fetch_gse_fleet_from_lakebase", return_value=[]), \
             patch("scripts.sync_all_to_unity_catalog.fetch_turnaround_from_lakebase", return_value=[]), \
             patch("scripts.sync_all_to_unity_catalog.fetch_flight_snapshots_from_lakebase", return_value=[]), \
             patch("scripts.sync_all_to_unity_catalog.fetch_phase_transitions_from_lakebase", return_value=[]), \
             patch("scripts.sync_all_to_unity_catalog.fetch_gate_events_from_lakebase", return_value=[]), \
             patch("scripts.sync_all_to_unity_catalog.fetch_ml_predictions_from_lakebase", return_value=[]), \
             patch("scripts.sync_all_to_unity_catalog.sync_weather_to_delta", return_value=1), \
             patch("scripts.sync_all_to_unity_catalog.sync_schedule_to_delta", return_value=0), \
             patch("scripts.sync_all_to_unity_catalog.append_baggage_history", return_value=0), \
             patch("scripts.sync_all_to_unity_catalog.sync_gse_fleet_to_delta", return_value=0), \
             patch("scripts.sync_all_to_unity_catalog.append_turnaround_history", return_value=0), \
             patch("scripts.sync_all_to_unity_catalog.append_flight_snapshots_history", return_value=0), \
             patch("scripts.sync_all_to_unity_catalog.append_phase_transitions_history", return_value=0), \
             patch("scripts.sync_all_to_unity_catalog.append_gate_events_history", return_value=0), \
             patch("scripts.sync_all_to_unity_catalog.append_ml_predictions_history", return_value=0):

            from scripts.sync_all_to_unity_catalog import main
            result = main()

        assert result == 0

    @patch.dict(os.environ, {
        "DATABRICKS_CATALOG": "test_catalog",
        "DATABRICKS_SCHEMA": "test_schema",
    })
    def test_main_error(self):
        """Test main handles errors gracefully."""
        with patch("scripts.sync_all_to_unity_catalog.fetch_weather_from_lakebase", side_effect=Exception("Connection error")):
            from scripts.sync_all_to_unity_catalog import main
            result = main()

        assert result == 1


class TestJSONHandling:
    """Tests for JSON field handling."""

    def test_fetch_weather_json_conversion(self):
        """Test JSON fields are properly converted for Delta."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                "station": "KSFO",
                "observation_time": datetime.now(timezone.utc),
                "wind_direction": 270,
                "wind_speed_kts": 10,
                "visibility_sm": 10.0,
                "clouds": [{"cover": "FEW", "altitude": 5000}],  # List (JSONB)
                "temperature_c": 18,
                "dewpoint_c": 12,
                "altimeter_inhg": 30.05,
                "weather": ["RA"],  # List (JSONB)
                "flight_category": "VFR",
                "raw_metar": "KSFO...",
                "taf_text": None,
                "taf_valid_from": None,
                "taf_valid_to": None,
            }
        ]

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch("scripts.sync_all_to_unity_catalog.get_lakebase_connection", return_value=mock_conn):
            from scripts.sync_all_to_unity_catalog import fetch_weather_from_lakebase
            result = fetch_weather_from_lakebase()

        # JSONB fields should be converted to JSON strings
        assert isinstance(result[0]["clouds"], str)
        assert isinstance(result[0]["weather"], str)
        assert '"FEW"' in result[0]["clouds"]

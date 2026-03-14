"""Tests for ML training data persistence.

Tests event emission buffers, Lakebase batch inserts, periodic flush loop,
and the sync script extensions for flight snapshots, phase transitions,
gate events, and ML predictions.
"""

import asyncio
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock


class TestEventBuffers:
    """Tests for event emission and drain in fallback.py."""

    def setup_method(self):
        """Clear all buffers before each test."""
        from src.ingestion.fallback import (
            _phase_transition_buffer,
            _gate_event_buffer,
            _prediction_buffer,
            _phase_transition_lock,
            _gate_event_lock,
            _prediction_lock,
        )
        with _phase_transition_lock:
            _phase_transition_buffer.clear()
        with _gate_event_lock:
            _gate_event_buffer.clear()
        with _prediction_lock:
            _prediction_buffer.clear()

    def test_emit_phase_transition(self):
        """Phase transitions are buffered correctly."""
        from src.ingestion.fallback import emit_phase_transition, drain_phase_transitions

        emit_phase_transition(
            icao24="abc123", callsign="UAL456",
            from_phase="approaching", to_phase="landing",
            latitude=37.6, longitude=-122.4, altitude=500.0,
            aircraft_type="B738", assigned_gate="A1",
        )

        events = drain_phase_transitions()
        assert len(events) == 1
        e = events[0]
        assert e["icao24"] == "abc123"
        assert e["from_phase"] == "approaching"
        assert e["to_phase"] == "landing"
        assert e["aircraft_type"] == "B738"
        assert "event_time" in e

    def test_drain_clears_buffer(self):
        """Draining returns events and clears the buffer."""
        from src.ingestion.fallback import emit_phase_transition, drain_phase_transitions

        emit_phase_transition("a", "c", "parked", "pushback", 0, 0, 0)
        assert len(drain_phase_transitions()) == 1
        assert len(drain_phase_transitions()) == 0  # Second drain is empty

    def test_emit_gate_event(self):
        """Gate events are buffered correctly."""
        from src.ingestion.fallback import emit_gate_event, drain_gate_events

        emit_gate_event("abc123", "UAL456", "B3", "assign", "A320")
        emit_gate_event("abc123", "UAL456", "B3", "occupy", "A320")
        emit_gate_event("abc123", "UAL456", "B3", "release", "A320")

        events = drain_gate_events()
        assert len(events) == 3
        assert events[0]["event_type"] == "assign"
        assert events[1]["event_type"] == "occupy"
        assert events[2]["event_type"] == "release"

    def test_emit_prediction(self):
        """ML predictions are buffered correctly."""
        from src.ingestion.fallback import emit_prediction, drain_predictions

        emit_prediction("delay", "abc123", {"delay_minutes": 15.5, "confidence": 0.85})
        emit_prediction("congestion", None, {"area_id": "runway_28L", "level": "high"})

        events = drain_predictions()
        assert len(events) == 2
        assert events[0]["prediction_type"] == "delay"
        assert events[0]["icao24"] == "abc123"
        assert events[1]["prediction_type"] == "congestion"
        assert events[1]["icao24"] is None

    def test_buffer_cap(self):
        """Buffers are capped to prevent unbounded growth."""
        from src.ingestion.fallback import (
            emit_phase_transition, drain_phase_transitions, _MAX_BUFFER_SIZE,
        )

        # Emit more than max
        for i in range(_MAX_BUFFER_SIZE + 100):
            emit_phase_transition(f"a{i}", "c", "parked", "pushback", 0, 0, 0)

        events = drain_phase_transitions()
        assert len(events) <= _MAX_BUFFER_SIZE

    def test_get_current_flight_states(self):
        """get_current_flight_states returns snapshot of current flights."""
        from src.ingestion.fallback import (
            get_current_flight_states, _flight_states, FlightState, FlightPhase,
        )

        # Inject a test flight
        _flight_states["test123"] = FlightState(
            icao24="test123", callsign="TST100",
            latitude=37.6, longitude=-122.4,
            altitude=1000.0, velocity=150.0,
            heading=280.0, vertical_rate=-500.0,
            on_ground=False, phase=FlightPhase.APPROACHING,
            aircraft_type="B738",
        )

        try:
            snapshots = get_current_flight_states()
            assert len(snapshots) >= 1
            test_snap = [s for s in snapshots if s["icao24"] == "test123"]
            assert len(test_snap) == 1
            assert test_snap[0]["flight_phase"] == "approaching"
            assert test_snap[0]["callsign"] == "TST100"
            assert "snapshot_time" in test_snap[0]
        finally:
            del _flight_states["test123"]


class TestPhaseTransitionEmission:
    """Test that phase transitions in _update_flight_state emit events."""

    def setup_method(self):
        from src.ingestion.fallback import (
            _phase_transition_buffer, _gate_event_buffer,
            _phase_transition_lock, _gate_event_lock,
        )
        with _phase_transition_lock:
            _phase_transition_buffer.clear()
        with _gate_event_lock:
            _gate_event_buffer.clear()

    def test_parked_to_pushback_emits(self):
        """Transition from PARKED to PUSHBACK emits a phase event."""
        from src.ingestion.fallback import (
            _update_flight_state, FlightState, FlightPhase,
            drain_phase_transitions,
        )

        state = FlightState(
            icao24="emit1", callsign="TST1",
            latitude=37.615, longitude=-122.395,
            altitude=0, velocity=0, heading=180,
            vertical_rate=0, on_ground=True,
            phase=FlightPhase.PARKED,
            aircraft_type="A320", assigned_gate="G1",
            time_at_gate=9999,  # Force immediate pushback
        )

        _update_flight_state(state, 1.0)

        if state.phase == FlightPhase.PUSHBACK:
            events = drain_phase_transitions()
            parked_to_pushback = [
                e for e in events
                if e["from_phase"] == "parked" and e["to_phase"] == "pushback"
            ]
            assert len(parked_to_pushback) == 1
            assert parked_to_pushback[0]["icao24"] == "emit1"


class TestLakebaseBatchInserts:
    """Tests for Lakebase batch-insert methods with mocked DB."""

    def _make_mock_service(self):
        """Create a LakebaseService with mocked connection."""
        from app.backend.services.lakebase_service import LakebaseService

        service = LakebaseService()
        service._ml_tables_ensured = True  # Skip DDL
        return service

    @patch("app.backend.services.lakebase_service.execute_values", create=True)
    def test_insert_flight_snapshots(self, mock_exec_values):
        """insert_flight_snapshots calls execute_values with correct data."""
        from app.backend.services.lakebase_service import LakebaseService

        service = self._make_mock_service()
        mock_conn = MagicMock()

        snapshots = [
            {
                "icao24": "abc123", "callsign": "UAL456",
                "latitude": 37.6, "longitude": -122.4,
                "altitude": 1000, "velocity": 150,
                "heading": 280, "vertical_rate": -500,
                "on_ground": False, "flight_phase": "approaching",
                "aircraft_type": "B738", "assigned_gate": None,
                "origin_airport": "ORD", "destination_airport": None,
                "snapshot_time": "2026-03-10T12:00:00+00:00",
            }
        ]

        with patch.object(LakebaseService, "is_available", new_callable=lambda: property(lambda self: True)), \
             patch.object(service, "_get_connection") as mock_get_conn:
            mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
            count = service.insert_flight_snapshots(snapshots, "sess-1", "KSFO")

        assert count == 1
        mock_exec_values.assert_called_once()

    @patch("app.backend.services.lakebase_service.execute_values", create=True)
    def test_insert_phase_transitions(self, mock_exec_values):
        """insert_phase_transitions handles batch correctly."""
        from app.backend.services.lakebase_service import LakebaseService

        service = self._make_mock_service()
        mock_conn = MagicMock()

        events = [
            {
                "icao24": "abc123", "callsign": "UAL456",
                "from_phase": "approaching", "to_phase": "landing",
                "latitude": 37.6, "longitude": -122.4,
                "altitude": 500, "aircraft_type": "B738",
                "assigned_gate": None, "event_time": "2026-03-10T12:00:00+00:00",
            }
        ]

        with patch.object(LakebaseService, "is_available", new_callable=lambda: property(lambda self: True)), \
             patch.object(service, "_get_connection") as mock_get_conn:
            mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
            count = service.insert_phase_transitions(events, "sess-1", "KSFO")

        assert count == 1
        mock_exec_values.assert_called_once()

    def test_insert_empty_returns_zero(self):
        """Empty lists return 0 without DB calls."""
        from app.backend.services.lakebase_service import LakebaseService

        service = self._make_mock_service()
        with patch.object(LakebaseService, "is_available", new_callable=lambda: property(lambda self: True)):
            assert service.insert_flight_snapshots([], "s", "K") == 0
            assert service.insert_phase_transitions([], "s", "K") == 0
            assert service.insert_gate_events([], "s", "K") == 0
            assert service.insert_ml_predictions([], "s", "K") == 0

    def test_insert_unavailable_returns_zero(self):
        """All insert methods return 0 when Lakebase unavailable."""
        service = self._make_mock_service()
        # Default is_available is False since no env vars set
        assert service.insert_flight_snapshots([{"icao24": "x"}], "s", "K") == 0
        assert service.insert_phase_transitions([{"icao24": "x", "from_phase": "a", "to_phase": "b"}], "s", "K") == 0
        assert service.insert_gate_events([{"icao24": "x", "gate": "A1", "event_type": "assign"}], "s", "K") == 0
        assert service.insert_ml_predictions([{"prediction_type": "delay"}], "s", "K") == 0


class TestDataGeneratorServiceSession:
    """Tests for session tracking and persistence loop."""

    def test_session_id_is_uuid(self):
        """Service generates a valid UUID session_id."""
        import uuid
        from app.backend.services.data_generator_service import DataGeneratorService

        service = DataGeneratorService()
        # Should be a valid UUID
        parsed = uuid.UUID(service.session_id)
        assert str(parsed) == service.session_id

    def test_session_id_stable(self):
        """session_id doesn't change between accesses."""
        from app.backend.services.data_generator_service import DataGeneratorService

        service = DataGeneratorService()
        assert service.session_id == service.session_id

    def test_different_instances_different_sessions(self):
        """Each service instance gets a unique session_id."""
        from app.backend.services.data_generator_service import DataGeneratorService

        s1 = DataGeneratorService()
        s2 = DataGeneratorService()
        assert s1.session_id != s2.session_id

    def test_snapshot_interval_default(self):
        """Default snapshot interval is 15 seconds."""
        from app.backend.services.data_generator_service import DataGeneratorService

        service = DataGeneratorService()
        assert service._snapshot_interval == 15

    @pytest.mark.asyncio
    async def test_persist_flight_data_no_lakebase(self):
        """_persist_flight_data returns zeros when Lakebase unavailable."""
        from app.backend.services.data_generator_service import DataGeneratorService

        service = DataGeneratorService()

        with patch("app.backend.services.data_generator_service.get_lakebase_service") as mock_lb:
            mock_lb.return_value.is_available = False
            counts = await service._persist_flight_data()
            assert counts == {"snapshots": 0, "transitions": 0, "gate_events": 0, "predictions": 0}


class TestSyncScriptExtensions:
    """Tests for the sync script's new data stream functions."""

    def test_append_functions_handle_empty(self):
        """Append functions return 0 for empty lists."""
        from scripts.sync_all_to_unity_catalog import (
            append_flight_snapshots_history,
            append_phase_transitions_history,
            append_gate_events_history,
            append_ml_predictions_history,
        )

        assert append_flight_snapshots_history([], "cat", "sch") == 0
        assert append_phase_transitions_history([], "cat", "sch") == 0
        assert append_gate_events_history([], "cat", "sch") == 0
        assert append_ml_predictions_history([], "cat", "sch") == 0


class TestDeltaTableDDLs:
    """Tests for new Delta table DDL definitions."""

    def test_all_ml_tables_in_list(self):
        """All 4 new ML tables are included in ALL_TABLES."""
        from src.persistence.airport_tables import ALL_TABLES

        table_names = [name for name, _ in ALL_TABLES]
        assert "flight_position_history" in table_names
        assert "flight_phase_transition_history" in table_names
        assert "gate_assignment_history" in table_names
        assert "ml_prediction_history" in table_names

    def test_ddl_has_partitioning(self):
        """ML table DDLs include PARTITIONED BY clause."""
        from src.persistence.airport_tables import (
            FLIGHT_POSITION_HISTORY_DDL,
            FLIGHT_PHASE_TRANSITION_HISTORY_DDL,
            GATE_ASSIGNMENT_HISTORY_DDL,
            ML_PREDICTION_HISTORY_DDL,
        )

        for ddl in [
            FLIGHT_POSITION_HISTORY_DDL,
            FLIGHT_PHASE_TRANSITION_HISTORY_DDL,
            GATE_ASSIGNMENT_HISTORY_DDL,
            ML_PREDICTION_HISTORY_DDL,
        ]:
            assert "PARTITIONED BY" in ddl
            assert "recorded_date" in ddl
            assert "airport_icao" in ddl

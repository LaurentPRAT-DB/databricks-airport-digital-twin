"""Tests for WebSocket endpoints and FlightBroadcaster."""

import pytest
import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import WebSocket

from app.backend.api.websocket import (
    FlightBroadcaster,
    broadcaster,
    websocket_flights,
    _compute_deltas,
)


class TestFlightBroadcaster:
    """Tests for FlightBroadcaster class."""

    def test_init(self):
        """Test broadcaster initialization."""
        fb = FlightBroadcaster()
        assert fb._connections == set()
        assert fb._broadcast_task is None

    @pytest.mark.asyncio
    async def test_connect(self):
        """Test connecting a websocket."""
        fb = FlightBroadcaster()
        mock_ws = AsyncMock(spec=WebSocket)

        await fb.connect(mock_ws)

        mock_ws.accept.assert_called_once()
        assert mock_ws in fb._connections
        assert fb.connection_count == 1

    @pytest.mark.asyncio
    async def test_connect_multiple(self):
        """Test connecting multiple websockets."""
        fb = FlightBroadcaster()
        mock_ws1 = AsyncMock(spec=WebSocket)
        mock_ws2 = AsyncMock(spec=WebSocket)

        await fb.connect(mock_ws1)
        await fb.connect(mock_ws2)

        assert fb.connection_count == 2

    def test_disconnect(self):
        """Test disconnecting a websocket."""
        fb = FlightBroadcaster()
        mock_ws = MagicMock(spec=WebSocket)
        fb._connections.add(mock_ws)

        fb.disconnect(mock_ws)

        assert mock_ws not in fb._connections
        assert fb.connection_count == 0

    def test_disconnect_not_connected(self):
        """Test disconnecting a websocket that wasn't connected."""
        fb = FlightBroadcaster()
        mock_ws = MagicMock(spec=WebSocket)

        # Should not raise
        fb.disconnect(mock_ws)
        assert fb.connection_count == 0

    def test_connection_count(self):
        """Test connection_count property."""
        fb = FlightBroadcaster()
        assert fb.connection_count == 0

        mock_ws1 = MagicMock(spec=WebSocket)
        mock_ws2 = MagicMock(spec=WebSocket)
        fb._connections.add(mock_ws1)
        assert fb.connection_count == 1

        fb._connections.add(mock_ws2)
        assert fb.connection_count == 2

    @pytest.mark.asyncio
    async def test_broadcast_no_connections(self):
        """Test broadcast with no connections does nothing."""
        fb = FlightBroadcaster()

        # Should not raise
        await fb.broadcast({"type": "test", "data": "hello"})

    @pytest.mark.asyncio
    async def test_broadcast_to_single_connection(self):
        """Test broadcasting to a single connection."""
        fb = FlightBroadcaster()
        mock_ws = AsyncMock(spec=WebSocket)
        fb._connections.add(mock_ws)

        data = {"type": "flight_update", "count": 5}
        await fb.broadcast(data)

        mock_ws.send_text.assert_called_once()
        sent_data = json.loads(mock_ws.send_text.call_args[0][0])
        assert sent_data["type"] == "flight_update"
        assert sent_data["count"] == 5

    @pytest.mark.asyncio
    async def test_broadcast_to_multiple_connections(self):
        """Test broadcasting to multiple connections."""
        fb = FlightBroadcaster()
        mock_ws1 = AsyncMock(spec=WebSocket)
        mock_ws2 = AsyncMock(spec=WebSocket)
        fb._connections.add(mock_ws1)
        fb._connections.add(mock_ws2)

        data = {"type": "test"}
        await fb.broadcast(data)

        mock_ws1.send_text.assert_called_once()
        mock_ws2.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_removes_disconnected_clients(self):
        """Test that broadcast removes clients that fail to receive."""
        fb = FlightBroadcaster()
        mock_ws_good = AsyncMock(spec=WebSocket)
        mock_ws_bad = AsyncMock(spec=WebSocket)
        mock_ws_bad.send_text.side_effect = Exception("Connection closed")

        fb._connections.add(mock_ws_good)
        fb._connections.add(mock_ws_bad)

        await fb.broadcast({"type": "test"})

        # Bad connection should be removed
        assert mock_ws_bad not in fb._connections
        assert mock_ws_good in fb._connections
        assert fb.connection_count == 1

    @pytest.mark.asyncio
    async def test_broadcast_handles_datetime(self):
        """Test that broadcast serializes datetime objects."""
        fb = FlightBroadcaster()
        mock_ws = AsyncMock(spec=WebSocket)
        fb._connections.add(mock_ws)

        now = datetime.now(timezone.utc)
        data = {"timestamp": now, "type": "test"}
        await fb.broadcast(data)

        # Should not raise - datetime should be serialized
        mock_ws.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_loop_pushes_updates(self):
        """Test _broadcast_loop sends flight updates to connected clients."""
        fb = FlightBroadcaster()
        mock_ws = AsyncMock(spec=WebSocket)
        fb._connections.add(mock_ws)

        mock_flight = MagicMock()
        mock_flight.model_dump.return_value = {"icao24": "abc123"}

        mock_response = MagicMock()
        mock_response.flights = [mock_flight]
        mock_response.count = 1
        mock_response.timestamp = datetime.now(timezone.utc)

        mock_service = AsyncMock()
        mock_service.get_flights.return_value = mock_response

        with patch('app.backend.api.websocket.get_flight_service', return_value=mock_service):
            task = asyncio.create_task(fb._broadcast_loop(interval=0.1))
            await asyncio.sleep(0.15)
            # Remove connections so loop exits naturally
            fb._connections.clear()
            await task

        # Should have broadcast at least once
        assert mock_ws.send_text.call_count >= 1

    @pytest.mark.asyncio
    async def test_broadcast_loop_stops_when_no_clients(self):
        """Test _broadcast_loop exits when no clients are connected."""
        fb = FlightBroadcaster()
        # No connections → loop should return immediately

        mock_service = AsyncMock()
        with patch('app.backend.api.websocket.get_flight_service', return_value=mock_service):
            await fb._broadcast_loop(interval=0.1)

        # get_flights should never have been called
        mock_service.get_flights.assert_not_called()

    @pytest.mark.asyncio
    async def test_broadcast_loop_handles_exceptions(self):
        """Test that _broadcast_loop continues on exceptions."""
        fb = FlightBroadcaster()
        mock_ws = AsyncMock(spec=WebSocket)
        fb._connections.add(mock_ws)

        mock_service = AsyncMock()
        mock_service.get_flights.side_effect = Exception("Service error")

        with patch('app.backend.api.websocket.get_flight_service', return_value=mock_service):
            task = asyncio.create_task(fb._broadcast_loop(interval=0.1))
            await asyncio.sleep(0.15)
            fb._connections.clear()
            await task


class TestGlobalBroadcaster:
    """Tests for global broadcaster instance."""

    def test_broadcaster_exists(self):
        """Test that global broadcaster exists."""
        assert broadcaster is not None
        assert isinstance(broadcaster, FlightBroadcaster)


class TestWebsocketFlightsEndpoint:
    """Tests for websocket_flights endpoint."""

    @pytest.mark.asyncio
    async def test_websocket_connects_and_sends_initial_data(self):
        """Test websocket endpoint connects and sends initial data."""
        mock_ws = AsyncMock(spec=WebSocket)

        # Mock initial data response
        mock_flight = MagicMock()
        mock_flight.model_dump.return_value = {"icao24": "abc123", "callsign": "UAL123"}

        mock_response = MagicMock()
        mock_response.flights = [mock_flight]
        mock_response.count = 1
        mock_response.timestamp = datetime.now(timezone.utc)

        mock_service = AsyncMock()
        mock_service.get_flights.return_value = mock_response

        # Mock receive_text to simulate disconnect after initial send
        mock_ws.receive_text.side_effect = Exception("Disconnect")

        with patch('app.backend.api.websocket.broadcaster') as mock_broadcaster:
            mock_broadcaster.connect = AsyncMock()
            mock_broadcaster.disconnect = MagicMock()

            with patch('app.backend.api.websocket.get_flight_service', return_value=mock_service):
                # Run endpoint - should exit on exception
                await websocket_flights(mock_ws)

        # Should have connected
        mock_broadcaster.connect.assert_called_once_with(mock_ws)
        # Should have sent initial data
        mock_ws.send_json.assert_called_once()
        initial_data = mock_ws.send_json.call_args[0][0]
        assert initial_data["type"] == "initial"
        assert initial_data["data"]["count"] == 1

    @pytest.mark.asyncio
    async def test_websocket_handles_refresh_command(self):
        """Test websocket handles refresh command."""
        mock_ws = AsyncMock(spec=WebSocket)

        # Mock flight data
        mock_flight = MagicMock()
        mock_flight.model_dump.return_value = {"icao24": "abc123"}

        mock_response = MagicMock()
        mock_response.flights = [mock_flight]
        mock_response.count = 1
        mock_response.timestamp = datetime.now(timezone.utc)

        mock_service = AsyncMock()
        mock_service.get_flights.return_value = mock_response

        # Simulate receiving "refresh" then disconnect
        mock_ws.receive_text.side_effect = ["refresh", Exception("Disconnect")]

        with patch('app.backend.api.websocket.broadcaster') as mock_broadcaster:
            mock_broadcaster.connect = AsyncMock()
            mock_broadcaster.disconnect = MagicMock()

            with patch('app.backend.api.websocket.get_flight_service', return_value=mock_service):
                await websocket_flights(mock_ws)

        # Should have sent initial + refresh response
        assert mock_ws.send_json.call_count == 2
        refresh_data = mock_ws.send_json.call_args_list[1][0][0]
        assert refresh_data["type"] == "flight_update"

    @pytest.mark.asyncio
    async def test_websocket_handles_disconnect(self):
        """Test websocket handles WebSocketDisconnect."""
        from fastapi import WebSocketDisconnect

        mock_ws = AsyncMock(spec=WebSocket)

        mock_flight = MagicMock()
        mock_flight.model_dump.return_value = {"icao24": "abc123"}

        mock_response = MagicMock()
        mock_response.flights = [mock_flight]
        mock_response.count = 1
        mock_response.timestamp = datetime.now(timezone.utc)

        mock_service = AsyncMock()
        mock_service.get_flights.return_value = mock_response

        mock_ws.receive_text.side_effect = WebSocketDisconnect()

        with patch('app.backend.api.websocket.broadcaster') as mock_broadcaster:
            mock_broadcaster.connect = AsyncMock()
            mock_broadcaster.disconnect = MagicMock()

            with patch('app.backend.api.websocket.get_flight_service', return_value=mock_service):
                await websocket_flights(mock_ws)

        # Should have disconnected
        mock_broadcaster.disconnect.assert_called_once_with(mock_ws)

    @pytest.mark.asyncio
    async def test_websocket_handles_initial_data_exception(self):
        """Test websocket continues even if initial data fetch fails."""
        mock_ws = AsyncMock(spec=WebSocket)

        mock_service = AsyncMock()
        mock_service.get_flights.side_effect = [
            Exception("Initial fetch failed"),  # First call fails
        ]

        mock_ws.receive_text.side_effect = Exception("Disconnect")

        with patch('app.backend.api.websocket.broadcaster') as mock_broadcaster:
            mock_broadcaster.connect = AsyncMock()
            mock_broadcaster.disconnect = MagicMock()

            with patch('app.backend.api.websocket.get_flight_service', return_value=mock_service):
                # Should not raise
                await websocket_flights(mock_ws)

        # Should still have connected
        mock_broadcaster.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_websocket_ignores_non_refresh_messages(self):
        """Test websocket ignores messages that aren't 'refresh'."""
        mock_ws = AsyncMock(spec=WebSocket)

        mock_flight = MagicMock()
        mock_flight.model_dump.return_value = {"icao24": "abc123"}

        mock_response = MagicMock()
        mock_response.flights = [mock_flight]
        mock_response.count = 1
        mock_response.timestamp = datetime.now(timezone.utc)

        mock_service = AsyncMock()
        mock_service.get_flights.return_value = mock_response

        # Simulate receiving non-refresh messages
        mock_ws.receive_text.side_effect = ["ping", "hello", Exception("Disconnect")]

        with patch('app.backend.api.websocket.broadcaster') as mock_broadcaster:
            mock_broadcaster.connect = AsyncMock()
            mock_broadcaster.disconnect = MagicMock()

            with patch('app.backend.api.websocket.get_flight_service', return_value=mock_service):
                await websocket_flights(mock_ws)

        # Should only have sent initial data (1 call)
        assert mock_ws.send_json.call_count == 1


class TestComputeDeltas:
    """Tests for _compute_deltas function."""

    def test_new_flight_sent_in_full(self):
        """New flights (not in previous snapshot) should be sent in full."""
        prev = {}
        current = [{"icao24": "abc", "latitude": 37.0, "callsign": "UAL1"}]
        deltas, removed = _compute_deltas(prev, current)

        assert len(deltas) == 1
        assert deltas[0] == current[0]
        assert removed == []

    def test_no_changes_produces_empty_deltas(self):
        """Identical snapshots should produce no deltas."""
        flight = {"icao24": "abc", "latitude": 37.0, "longitude": -122.0, "heading": 90.0}
        prev = {"abc": flight.copy()}
        current = [flight.copy()]
        deltas, removed = _compute_deltas(prev, current)

        assert len(deltas) == 0
        assert removed == []

    def test_position_change_produces_delta(self):
        """Changed position fields should appear in delta."""
        prev = {"abc": {"icao24": "abc", "latitude": 37.0, "longitude": -122.0, "heading": 90.0, "callsign": "UAL1"}}
        current = [{"icao24": "abc", "latitude": 37.01, "longitude": -122.01, "heading": 91.0, "callsign": "UAL1"}]
        deltas, removed = _compute_deltas(prev, current)

        assert len(deltas) == 1
        assert deltas[0]["icao24"] == "abc"
        assert deltas[0]["latitude"] == 37.01
        assert deltas[0]["longitude"] == -122.01
        assert deltas[0]["heading"] == 91.0
        # Unchanged field should not appear
        assert "callsign" not in deltas[0]

    def test_removed_flight_detected(self):
        """Flights in prev but not in current should be in removed list."""
        prev = {
            "abc": {"icao24": "abc", "latitude": 37.0},
            "def": {"icao24": "def", "latitude": 38.0},
        }
        current = [{"icao24": "abc", "latitude": 37.0}]
        deltas, removed = _compute_deltas(prev, current)

        assert "def" in removed
        assert "abc" not in removed

    def test_non_delta_field_change_included(self):
        """Changes to non-position fields (e.g. assigned_gate) should also be sent."""
        prev = {"abc": {"icao24": "abc", "latitude": 37.0, "assigned_gate": "A1"}}
        current = [{"icao24": "abc", "latitude": 37.0, "assigned_gate": "B3"}]
        deltas, removed = _compute_deltas(prev, current)

        assert len(deltas) == 1
        assert deltas[0]["assigned_gate"] == "B3"
        assert "latitude" not in deltas[0]  # lat unchanged

    def test_multiple_flights_mixed_changes(self):
        """Mix of new, changed, unchanged, and removed flights."""
        prev = {
            "aaa": {"icao24": "aaa", "latitude": 37.0, "heading": 90},
            "bbb": {"icao24": "bbb", "latitude": 38.0, "heading": 180},
            "ccc": {"icao24": "ccc", "latitude": 39.0, "heading": 270},
        }
        current = [
            {"icao24": "aaa", "latitude": 37.0, "heading": 90},   # unchanged
            {"icao24": "bbb", "latitude": 38.5, "heading": 180},  # lat changed
            {"icao24": "ddd", "latitude": 40.0, "heading": 0},    # new
        ]
        deltas, removed = _compute_deltas(prev, current)

        # aaa unchanged → no delta; bbb changed → delta; ddd new → full
        icao_to_delta = {d["icao24"]: d for d in deltas}
        assert "aaa" not in icao_to_delta
        assert "bbb" in icao_to_delta
        assert icao_to_delta["bbb"]["latitude"] == 38.5
        assert "heading" not in icao_to_delta["bbb"]
        assert "ddd" in icao_to_delta
        assert icao_to_delta["ddd"]["latitude"] == 40.0
        assert "ccc" in removed

    def test_empty_prev_all_flights_are_new(self):
        """With empty previous snapshot, all flights are new."""
        current = [
            {"icao24": "a", "latitude": 1.0},
            {"icao24": "b", "latitude": 2.0},
        ]
        deltas, removed = _compute_deltas({}, current)

        assert len(deltas) == 2
        assert removed == []

    def test_empty_current_all_flights_removed(self):
        """With empty current list, all previous flights are removed."""
        prev = {"a": {"icao24": "a"}, "b": {"icao24": "b"}}
        deltas, removed = _compute_deltas(prev, [])

        assert len(deltas) == 0
        assert set(removed) == {"a", "b"}


class TestBroadcastLoopDeltaFormat:
    """Tests that _broadcast_loop sends flight_delta messages."""

    @pytest.mark.asyncio
    async def test_broadcast_loop_sends_delta_type(self):
        """Verify broadcast loop sends flight_delta messages, not flight_update."""
        fb = FlightBroadcaster()
        mock_ws = AsyncMock(spec=WebSocket)
        fb._connections.add(mock_ws)

        mock_flight = MagicMock()
        mock_flight.model_dump.return_value = {"icao24": "abc123", "latitude": 37.0}

        mock_response = MagicMock()
        mock_response.flights = [mock_flight]
        mock_response.count = 1
        mock_response.timestamp = datetime.now(timezone.utc)

        mock_service = AsyncMock()
        mock_service.get_flights.return_value = mock_response

        with patch('app.backend.api.websocket.get_flight_service', return_value=mock_service):
            task = asyncio.create_task(fb._broadcast_loop(interval=0.1))
            await asyncio.sleep(0.15)
            fb._connections.clear()
            await task

        # Check that the message sent was flight_delta
        assert mock_ws.send_text.call_count >= 1
        sent_data = json.loads(mock_ws.send_text.call_args_list[0][0][0])
        assert sent_data["type"] == "flight_delta"
        assert "deltas" in sent_data["data"]
        assert "removed" in sent_data["data"]
        assert "count" in sent_data["data"]
        assert "timestamp" in sent_data["data"]

    @pytest.mark.asyncio
    async def test_broadcast_loop_first_message_sends_all_as_new(self):
        """First broadcast should send all flights as new (full data in deltas)."""
        fb = FlightBroadcaster()
        mock_ws = AsyncMock(spec=WebSocket)
        fb._connections.add(mock_ws)

        mock_flight = MagicMock()
        mock_flight.model_dump.return_value = {
            "icao24": "abc123", "latitude": 37.0, "callsign": "UAL1"
        }

        mock_response = MagicMock()
        mock_response.flights = [mock_flight]
        mock_response.count = 1
        mock_response.timestamp = datetime.now(timezone.utc)

        mock_service = AsyncMock()
        mock_service.get_flights.return_value = mock_response

        with patch('app.backend.api.websocket.get_flight_service', return_value=mock_service):
            task = asyncio.create_task(fb._broadcast_loop(interval=0.1))
            await asyncio.sleep(0.15)
            fb._connections.clear()
            await task

        sent_data = json.loads(mock_ws.send_text.call_args_list[0][0][0])
        # First message: all flights are new → deltas contain full flight data
        assert len(sent_data["data"]["deltas"]) == 1
        assert sent_data["data"]["deltas"][0]["icao24"] == "abc123"
        assert sent_data["data"]["deltas"][0]["callsign"] == "UAL1"
        assert sent_data["data"]["removed"] == []

    @pytest.mark.asyncio
    async def test_broadcast_loop_tracks_prev_state(self):
        """Subsequent broadcasts should only send changed fields."""
        fb = FlightBroadcaster()
        mock_ws = AsyncMock(spec=WebSocket)
        fb._connections.add(mock_ws)

        # Same flight, two snapshots with different latitude
        flight_v1 = {"icao24": "abc", "latitude": 37.0, "callsign": "UAL1", "heading": 90}
        flight_v2 = {"icao24": "abc", "latitude": 37.01, "callsign": "UAL1", "heading": 90}

        mock_flight_1 = MagicMock()
        mock_flight_1.model_dump.return_value = flight_v1
        mock_flight_2 = MagicMock()
        mock_flight_2.model_dump.return_value = flight_v2

        resp_1 = MagicMock()
        resp_1.flights = [mock_flight_1]
        resp_1.count = 1
        resp_1.timestamp = datetime.now(timezone.utc)

        resp_2 = MagicMock()
        resp_2.flights = [mock_flight_2]
        resp_2.count = 1
        resp_2.timestamp = datetime.now(timezone.utc)

        mock_service = AsyncMock()
        mock_service.get_flights.side_effect = [resp_1, resp_2]

        with patch('app.backend.api.websocket.get_flight_service', return_value=mock_service):
            task = asyncio.create_task(fb._broadcast_loop(interval=0.05))
            await asyncio.sleep(0.12)
            fb._connections.clear()
            await task

        assert mock_ws.send_text.call_count >= 2
        # Second message should be a delta with only latitude changed
        second_msg = json.loads(mock_ws.send_text.call_args_list[1][0][0])
        assert second_msg["type"] == "flight_delta"
        delta = second_msg["data"]["deltas"]
        assert len(delta) == 1
        assert delta[0]["icao24"] == "abc"
        assert delta[0]["latitude"] == 37.01
        # Unchanged fields should not be present
        assert "callsign" not in delta[0]
        assert "heading" not in delta[0]

    @pytest.mark.asyncio
    async def test_prev_flights_initialized_empty(self):
        """Verify FlightBroadcaster starts with empty _prev_flights."""
        fb = FlightBroadcaster()
        assert fb._prev_flights == {}

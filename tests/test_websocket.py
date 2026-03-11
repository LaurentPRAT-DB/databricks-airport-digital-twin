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

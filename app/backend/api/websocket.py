"""WebSocket endpoints for real-time flight data streaming."""

import asyncio
import json
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.backend.services.flight_service import get_flight_service


websocket_router = APIRouter(tags=["websocket"])


class FlightBroadcaster:
    """Manager for WebSocket connections and broadcasting flight updates."""

    def __init__(self):
        """Initialize the broadcaster."""
        self._connections: Set[WebSocket] = set()
        self._running: bool = False

    async def connect(self, websocket: WebSocket) -> None:
        """
        Accept and register a new WebSocket connection.

        Args:
            websocket: The WebSocket connection to register.
        """
        await websocket.accept()
        self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        """
        Remove a WebSocket connection.

        Args:
            websocket: The WebSocket connection to remove.
        """
        self._connections.discard(websocket)

    @property
    def connection_count(self) -> int:
        """Return the number of active connections."""
        return len(self._connections)

    async def broadcast(self, data: dict) -> None:
        """
        Broadcast data to all connected WebSocket clients.

        Args:
            data: Dictionary to broadcast as JSON.
        """
        if not self._connections:
            return

        message = json.dumps(data, default=str)
        disconnected = set()

        for websocket in self._connections:
            try:
                await websocket.send_text(message)
            except Exception:
                disconnected.add(websocket)

        # Clean up disconnected clients
        self._connections -= disconnected

    async def start_broadcasting(self, interval: float = 2.0) -> None:
        """
        Start broadcasting flight updates at regular intervals.

        Args:
            interval: Time between broadcasts in seconds.
        """
        self._running = True
        service = get_flight_service()

        while self._running:
            try:
                flight_data = await service.get_flights()
                await self.broadcast({
                    "type": "flight_update",
                    "data": {
                        "flights": [f.model_dump() for f in flight_data.flights],
                        "count": flight_data.count,
                        "timestamp": flight_data.timestamp.isoformat(),
                    },
                })
            except Exception:
                # Log error but continue broadcasting
                pass

            await asyncio.sleep(interval)

    def stop_broadcasting(self) -> None:
        """Stop the broadcasting loop."""
        self._running = False


# Global broadcaster instance
broadcaster = FlightBroadcaster()


@websocket_router.websocket("/ws/flights")
async def websocket_flights(websocket: WebSocket):
    """
    WebSocket endpoint for real-time flight updates.

    Clients connect to receive streaming flight position updates.
    """
    await broadcaster.connect(websocket)

    # Send initial data
    service = get_flight_service()
    try:
        initial_data = await service.get_flights()
        await websocket.send_json({
            "type": "initial",
            "data": {
                "flights": [f.model_dump() for f in initial_data.flights],
                "count": initial_data.count,
                "timestamp": initial_data.timestamp.isoformat(),
            },
        })
    except Exception:
        pass

    try:
        # Keep connection alive and handle incoming messages
        while True:
            # Wait for any message from client (ping/pong, commands, etc.)
            data = await websocket.receive_text()

            # Handle refresh request
            if data == "refresh":
                flight_data = await service.get_flights()
                await websocket.send_json({
                    "type": "flight_update",
                    "data": {
                        "flights": [f.model_dump() for f in flight_data.flights],
                        "count": flight_data.count,
                        "timestamp": flight_data.timestamp.isoformat(),
                    },
                })
    except WebSocketDisconnect:
        broadcaster.disconnect(websocket)
    except Exception:
        broadcaster.disconnect(websocket)

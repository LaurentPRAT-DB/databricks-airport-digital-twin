"""WebSocket endpoints for real-time flight data streaming."""

import asyncio
import json
import logging
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.backend.services.flight_service import get_flight_service


logger = logging.getLogger(__name__)
websocket_router = APIRouter(tags=["websocket"])


class FlightBroadcaster:
    """Manager for WebSocket connections and broadcasting flight updates."""

    def __init__(self):
        """Initialize the broadcaster."""
        self._connections: Set[WebSocket] = set()
        self._broadcast_task: asyncio.Task | None = None

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)
        # Start broadcast loop on first client
        if self._broadcast_task is None or self._broadcast_task.done():
            self._broadcast_task = asyncio.create_task(self._broadcast_loop())

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    async def broadcast(self, data: dict) -> None:
        if not self._connections:
            return

        message = json.dumps(data, default=str)
        disconnected = set()

        for websocket in self._connections:
            try:
                await websocket.send_text(message)
            except Exception:
                disconnected.add(websocket)

        self._connections -= disconnected

    async def broadcast_progress(
        self, step: int, total: int, message: str, icao_code: str, done: bool = False
    ) -> None:
        """Broadcast airport switch progress to all connected clients."""
        await self.broadcast({
            "type": "airport_switch_progress",
            "data": {
                "step": step,
                "total": total,
                "message": message,
                "icaoCode": icao_code,
                "done": done,
            },
        })

    async def _broadcast_loop(self, interval: float = 2.0) -> None:
        """Push flight updates to all connected clients every `interval` seconds."""
        service = get_flight_service()
        while True:
            if not self._connections:
                # No clients — stop the loop; it restarts on next connect
                logger.debug("No WS clients, stopping broadcast loop")
                return

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
                pass

            await asyncio.sleep(interval)


# Global broadcaster instance
broadcaster = FlightBroadcaster()


@websocket_router.websocket("/ws/flights")
async def websocket_flights(websocket: WebSocket):
    """WebSocket endpoint for real-time flight updates.

    Sends initial data immediately, then the broadcast loop pushes
    updates every 2 seconds to all connected clients.
    """
    await broadcaster.connect(websocket)

    # Send initial data immediately so the client doesn't wait 2s
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
        # Keep connection alive — handle client messages (refresh, ping)
        while True:
            data = await websocket.receive_text()
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

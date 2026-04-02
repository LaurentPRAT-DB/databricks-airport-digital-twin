"""WebSocket endpoints for real-time flight data streaming."""

import asyncio
import json
import logging
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.backend.services.flight_service import get_flight_service


logger = logging.getLogger(__name__)
websocket_router = APIRouter(tags=["websocket"])

# Fields that change every update (position/movement) — sent as deltas
_DELTA_FIELDS = {
    "latitude", "longitude", "altitude", "velocity",
    "heading", "on_ground", "vertical_rate", "flight_phase",
}


def _compute_deltas(
    prev_flights: dict[str, dict],
    current_flights: list[dict],
) -> tuple[list[dict], list[str]]:
    """Compare current flights against previous snapshot.

    Returns (deltas, removed_icao24s).
    Each delta contains icao24 + only the fields that changed.
    New flights are sent in full.
    """
    deltas: list[dict] = []
    current_ids = {f["icao24"] for f in current_flights}
    removed = [k for k in prev_flights if k not in current_ids]

    for flight in current_flights:
        icao24 = flight["icao24"]
        prev = prev_flights.get(icao24)
        if prev is None:
            # New flight — send full data
            deltas.append(flight)
            continue

        diff: dict = {"icao24": icao24}
        for key in _DELTA_FIELDS:
            cur_val = flight.get(key)
            if cur_val != prev.get(key):
                diff[key] = cur_val

        # Also include non-delta fields that changed (gate reassignment, etc.)
        for key in flight:
            if key not in _DELTA_FIELDS and key != "icao24":
                if flight[key] != prev.get(key):
                    diff[key] = flight[key]

        if len(diff) > 1:  # More than just icao24
            deltas.append(diff)

    return deltas, removed


class FlightBroadcaster:
    """Manager for WebSocket connections and broadcasting flight updates."""

    def __init__(self):
        """Initialize the broadcaster."""
        self._connections: Set[WebSocket] = set()
        self._broadcast_task: asyncio.Task | None = None
        self._prev_flights: dict[str, dict] = {}
        self._mode: str = "simulation"  # "simulation" or "live"

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
        self, step: int, total: int, message: str, icao_code: str,
        done: bool = False, error: bool = False,
    ) -> None:
        """Broadcast airport switch progress to all connected clients."""
        data: dict = {
            "step": step,
            "total": total,
            "message": message,
            "icaoCode": icao_code,
            "done": done,
        }
        if error:
            data["error"] = True
        await self.broadcast({
            "type": "airport_switch_progress",
            "data": data,
        })

    async def set_mode(self, mode: str) -> None:
        """Switch between 'simulation' and 'live' data modes."""
        if mode not in ("simulation", "live"):
            return
        if mode == self._mode:
            return
        self._mode = mode
        self._prev_flights = {}  # Reset delta tracking on mode switch
        await self.broadcast({
            "type": "mode_change",
            "data": {"mode": mode},
        })
        logger.info("Broadcaster mode switched to: %s", mode)

    @property
    def mode(self) -> str:
        return self._mode

    async def _broadcast_loop(self, interval: float = 2.0) -> None:
        """Push flight updates to all connected clients every `interval` seconds."""
        service = get_flight_service()
        while True:
            if not self._connections:
                logger.debug("No WS clients, stopping broadcast loop")
                return

            try:
                if self._mode == "live":
                    flights_dicts, timestamp = await self._fetch_opensky_flights()
                else:
                    flight_data = await service.get_flights()
                    flights_dicts = [f.model_dump() for f in flight_data.flights]
                    timestamp = flight_data.timestamp.isoformat()

                # Compute deltas against previous broadcast
                deltas, removed = _compute_deltas(self._prev_flights, flights_dicts)

                # Update snapshot for next cycle
                self._prev_flights = {f["icao24"]: f for f in flights_dicts}

                # Send delta update (smaller payload)
                await self.broadcast({
                    "type": "flight_delta",
                    "data": {
                        "deltas": deltas,
                        "removed": removed,
                        "count": len(flights_dicts),
                        "timestamp": timestamp,
                        "mode": self._mode,
                    },
                })
            except Exception:
                pass

            # Live mode polls less frequently (OpenSky rate limits)
            sleep_time = 10.0 if self._mode == "live" else interval
            await asyncio.sleep(sleep_time)

    async def _fetch_opensky_flights(self) -> tuple[list[dict], str]:
        """Fetch flights from OpenSky for the current airport."""
        from datetime import datetime, timezone
        from app.backend.services.opensky_service import get_opensky_service
        from app.backend.services.airport_config_service import get_airport_config_service

        opensky = get_opensky_service()
        config_service = get_airport_config_service()
        config = config_service.get_config()

        # Get airport center
        ref = config.get("reference_point") or config.get("referencePoint") or {}
        lat = float(ref.get("latitude", 37.6213))
        lon = float(ref.get("longitude", -122.379))

        flights = await opensky.fetch_flights(lat, lon)
        timestamp = datetime.now(timezone.utc).isoformat()
        return flights, timestamp


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

    # Send current mode to newly connected client
    try:
        await websocket.send_json({
            "type": "mode_change",
            "data": {"mode": broadcaster.mode},
        })
    except Exception:
        pass

    try:
        # Keep connection alive — handle client messages (refresh, ping, mode switch)
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
            else:
                # Try to parse JSON commands
                try:
                    msg = json.loads(data)
                    if msg.get("command") == "set_mode":
                        await broadcaster.set_mode(msg.get("mode", "simulation"))
                except (json.JSONDecodeError, TypeError):
                    pass
    except WebSocketDisconnect:
        broadcaster.disconnect(websocket)
    except Exception:
        broadcaster.disconnect(websocket)

"""Schedule queue — feeds FLIFO data to the simulation spawner.

When FLIFO is active, upcoming flights are pre-loaded into a queue.
The spawner consumes from this queue instead of generating random callsigns,
so map and FIDS show the same flight numbers.
"""

import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Spawn windows (how far ahead of scheduled_time to spawn)
ARRIVAL_SPAWN_WINDOW_MIN = 45
DEPARTURE_SPAWN_WINDOW_MIN = 30

# How often to refresh from FLIFO (seconds)
REFRESH_INTERVAL_S = 60

# FLIFO status → simulation phase mapping
_ARRIVAL_PHASE_MAP = {
    "SC": "APPROACHING",
    "ON": "APPROACHING",
    "FE": "APPROACHING",
    "DL": "APPROACHING",
    "IA": "APPROACHING",
    "AB": "APPROACHING",
    "LN": "TAXI_TO_GATE",
    "TX": "TAXI_TO_GATE",
    "AR": "PARKED",
    "BG": "PARKED",
}

_DEPARTURE_PHASE_MAP = {
    "SC": "PARKED",
    "ON": "PARKED",
    "BD": "PARKED",
    "FC": "PARKED",
    "GC": "PARKED",
    "GO": "PARKED",
    "CO": "PARKED",
    "CD": "PARKED",
    "OB": "TAXI_TO_RUNWAY",
    "DP": "TAXI_TO_RUNWAY",
    "DL": "PARKED",
}


class ScheduleQueue:
    """Feeds FLIFO schedule data to the simulation spawner."""

    def __init__(self):
        self._arrivals: deque[dict] = deque()
        self._departures: deque[dict] = deque()
        self._spawned: set[str] = set()
        self._last_refresh: float = 0
        self._available = False

    @property
    def is_active(self) -> bool:
        return self._available and (len(self._arrivals) > 0 or len(self._departures) > 0)

    def refresh(self, airport_iata: str) -> None:
        """Fetch from FLIFO service, populate queues. Called periodically."""
        now = time.time()
        if now - self._last_refresh < REFRESH_INTERVAL_S:
            return

        self._last_refresh = now

        try:
            from app.backend.services.flifo_service import get_flifo_service
            flifo = get_flifo_service()
            if not flifo.is_available:
                self._available = False
                return

            schedule = flifo.get_schedule(
                airport_iata=airport_iata,
                hours_behind=1,
                hours_ahead=2,
                limit=100,
            )
            if not schedule:
                self._available = False
                return

            self._available = True
            self._rebuild_queues(schedule)
            logger.debug(
                f"ScheduleQueue refreshed: {len(self._arrivals)} arrivals, "
                f"{len(self._departures)} departures, {len(self._spawned)} already spawned"
            )

        except Exception as e:
            logger.warning(f"ScheduleQueue refresh failed: {e}")
            self._available = False

    def _rebuild_queues(self, schedule: list[dict]) -> None:
        """Rebuild arrival/departure queues from schedule data."""
        arrivals = []
        departures = []

        for flight in schedule:
            fn = flight.get("flight_number", "")
            if fn in self._spawned:
                continue

            if flight.get("flight_type") == "arrival":
                arrivals.append(flight)
            else:
                departures.append(flight)

        arrivals.sort(key=lambda f: f.get("scheduled_time", ""))
        departures.sort(key=lambda f: f.get("scheduled_time", ""))

        self._arrivals = deque(arrivals)
        self._departures = deque(departures)

    def next_arrival(self) -> Optional[dict]:
        """Pop next arrival within spawn window that hasn't been spawned."""
        return self._pop_ready(self._arrivals, ARRIVAL_SPAWN_WINDOW_MIN)

    def next_departure(self) -> Optional[dict]:
        """Pop next departure within spawn window that hasn't been spawned."""
        return self._pop_ready(self._departures, DEPARTURE_SPAWN_WINDOW_MIN)

    def _pop_ready(self, queue: deque, window_min: int) -> Optional[dict]:
        """Pop first flight within spawn window from queue."""
        now = datetime.now(timezone.utc)

        while queue:
            flight = queue[0]
            sched_str = flight.get("scheduled_time", "")
            fn = flight.get("flight_number", "")

            if fn in self._spawned:
                queue.popleft()
                continue

            try:
                if isinstance(sched_str, str):
                    sched = datetime.fromisoformat(sched_str.replace("Z", "+00:00"))
                else:
                    sched = sched_str
                if sched.tzinfo is None:
                    sched = sched.replace(tzinfo=timezone.utc)
            except (ValueError, AttributeError):
                queue.popleft()
                continue

            minutes_until = (sched - now).total_seconds() / 60

            # Already too far in the past (>60min) — skip
            if minutes_until < -60:
                queue.popleft()
                continue

            # Within spawn window (past or upcoming within window)
            if minutes_until <= window_min:
                queue.popleft()
                self._spawned.add(fn)
                return flight

            # Not ready yet — stop (queue is sorted)
            break

        return None

    def mark_spawned(self, flight_number: str) -> None:
        """Mark flight as spawned to prevent duplicates."""
        self._spawned.add(flight_number)

    def get_phase_for_flight(self, flight: dict) -> str:
        """Map FLIFO flight data to simulation spawn phase."""
        flight_type = flight.get("flight_type", "arrival")
        status = flight.get("status", "scheduled")

        # Map internal status back to approximate FLIFO code for phase selection
        _status_to_flifo = {
            "scheduled": "SC",
            "on_time": "ON",
            "delayed": "DL",
            "boarding": "BD",
            "final_call": "FC",
            "gate_closed": "GC",
            "departed": "DP",
            "arrived": "AR",
            "cancelled": "CX",
        }
        flifo_code = _status_to_flifo.get(status, "SC")

        if flight_type == "arrival":
            return _ARRIVAL_PHASE_MAP.get(flifo_code, "APPROACHING")
        else:
            return _DEPARTURE_PHASE_MAP.get(flifo_code, "PARKED")


# Module-level singleton
_schedule_queue: Optional[ScheduleQueue] = None


def get_schedule_queue() -> ScheduleQueue:
    global _schedule_queue
    if _schedule_queue is None:
        _schedule_queue = ScheduleQueue()
    return _schedule_queue

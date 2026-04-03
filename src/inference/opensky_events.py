"""Infer gate events and phase transitions from raw OpenSky ADS-B state vectors.

Processes time-ordered ADS-B frames and produces simulation-compatible events
(phase_transitions, gate_events) by:
1. Matching on-ground stationary aircraft to nearest OSM gate via haversine
2. Tracking per-aircraft state machines to detect parked/taxi/takeoff/landing

Output format matches src/simulation/recorder.py so enriched recordings can
feed directly into the ML training pipeline (src/ml/obt_features.py).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# ── Thresholds (in raw OpenSky units: m/s) ──────────────────────────────

STATIONARY_VELOCITY_MS = 2.0   # < 2 m/s ≈ 4 kts → considered stopped
TAXI_MAX_VELOCITY_MS = 30.0    # > 30 m/s ≈ 58 kts → likely takeoff roll
GATE_MATCH_RADIUS_M = 100.0    # Max distance to match aircraft to a gate

# Earth radius for haversine
_R_EARTH_M = 6_371_000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in meters between two WGS84 points."""
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = rlat2 - rlat1
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return _R_EARTH_M * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── Per-aircraft state ───────────────────────────────────────────────────

@dataclass
class AircraftState:
    """Snapshot of an aircraft's last known state."""
    on_ground: bool = False
    velocity_ms: float = 0.0
    latitude: float = 0.0
    longitude: float = 0.0
    altitude_ft: float = 0.0
    heading: float | None = None
    vertical_rate_ftmin: float = 0.0
    phase: str = "unknown"       # Current inferred sim-phase


@dataclass
class AircraftTracker:
    """Tracks one aircraft across frames, emitting events on state changes."""
    icao24: str
    callsign: str
    assigned_gate: str | None = None
    parked_since: str | None = None   # ISO timestamp when parking started
    prev: AircraftState | None = None
    was_airborne: bool = False        # True if we've seen this aircraft airborne


# ── Main inferrer ────────────────────────────────────────────────────────

class OpenSkyEventInferrer:
    """Processes time-ordered ADS-B frames and produces simulation-compatible events.

    Usage:
        inferrer = OpenSkyEventInferrer(gates_from_config)
        for ts in sorted_timestamps:
            inferrer.process_frame(ts, frame_snapshots)
        result = inferrer.get_results()
        # result["phase_transitions"], result["gate_events"]
    """

    def __init__(self, gates: list[dict[str, Any]]) -> None:
        """Initialize with gate positions from airport config.

        Args:
            gates: List of gate dicts from config["gates"], each with
                   "ref" (or "id") and "geo": {"latitude": ..., "longitude": ...}
        """
        self._gate_positions: list[tuple[str, float, float]] = []
        for g in gates:
            gate_id = g.get("ref") or g.get("id") or ""
            geo = g.get("geo", {})
            lat = geo.get("latitude")
            lon = geo.get("longitude")
            if gate_id and lat is not None and lon is not None:
                self._gate_positions.append((str(gate_id), float(lat), float(lon)))

        self._trackers: dict[str, AircraftTracker] = {}
        self._phase_transitions: list[dict[str, Any]] = []
        self._gate_events: list[dict[str, Any]] = []
        self._enriched_snapshots: list[dict[str, Any]] = []

        logger.info("OpenSkyEventInferrer initialized with %d gate positions", len(self._gate_positions))

    def find_nearest_gate(
        self, lat: float, lon: float, max_dist_m: float = GATE_MATCH_RADIUS_M
    ) -> tuple[str | None, float]:
        """Find the nearest gate within max_dist_m.

        Returns:
            (gate_id, distance_m) or (None, inf) if no gate within range.
        """
        best_id: str | None = None
        best_dist = float("inf")

        for gate_id, glat, glon in self._gate_positions:
            d = haversine_m(lat, lon, glat, glon)
            if d < best_dist:
                best_dist = d
                best_id = gate_id

        if best_dist <= max_dist_m:
            return best_id, best_dist
        return None, float("inf")

    def _emit_phase_transition(
        self,
        timestamp: str,
        tracker: AircraftTracker,
        from_phase: str,
        to_phase: str,
        state: AircraftState,
    ) -> None:
        self._phase_transitions.append({
            "time": timestamp,
            "icao24": tracker.icao24,
            "callsign": tracker.callsign,
            "from_phase": from_phase,
            "to_phase": to_phase,
            "latitude": state.latitude,
            "longitude": state.longitude,
            "altitude": state.altitude_ft,
            "aircraft_type": "",  # Unknown from ADS-B
            "assigned_gate": tracker.assigned_gate,
        })

    def _emit_gate_event(
        self,
        timestamp: str,
        tracker: AircraftTracker,
        gate: str,
        event_type: str,
        gate_distance_m: float = 0.0,
    ) -> None:
        self._gate_events.append({
            "time": timestamp,
            "icao24": tracker.icao24,
            "callsign": tracker.callsign,
            "gate": gate,
            "event_type": event_type,
            "aircraft_type": "",  # Unknown from ADS-B
            "gate_distance_m": round(gate_distance_m, 1),
        })

    def _infer_phase(
        self,
        on_ground: bool,
        velocity_ms: float,
        near_gate: str | None,
        was_parked: bool,
    ) -> str:
        """Infer simulation-compatible phase from raw state."""
        if on_ground:
            if velocity_ms < STATIONARY_VELOCITY_MS and near_gate:
                return "parked"
            if velocity_ms < STATIONARY_VELOCITY_MS:
                # Stationary but not near a gate — could be holding position
                return "parked" if was_parked else "taxi_to_gate"
            if velocity_ms > TAXI_MAX_VELOCITY_MS:
                return "takeoff"
            # Moving on ground — taxi direction inferred from context
            return "taxi_to_runway" if was_parked else "taxi_to_gate"
        # Airborne
        return "airborne"  # Caller can refine with altitude/vrate

    def process_frame(self, timestamp: str, states: list[dict[str, Any]]) -> None:
        """Process one time-slice of ADS-B snapshots.

        Args:
            timestamp: ISO timestamp for this frame.
            states: List of snapshot dicts with keys:
                icao24, callsign, latitude, longitude, on_ground,
                velocity (kts, already converted), altitude (ft),
                vertical_rate (ft/min), heading
        """
        seen_icao24s: set[str] = set()

        for snap in states:
            icao24 = snap.get("icao24", "")
            if not icao24:
                continue
            seen_icao24s.add(icao24)

            callsign = snap.get("callsign", icao24).strip() or icao24
            lat = snap.get("latitude")
            lon = snap.get("longitude")
            if lat is None or lon is None:
                continue

            on_ground = bool(snap.get("on_ground", False))
            # Velocity in the frame is already in kts — convert back to m/s for thresholds
            velocity_kts = float(snap.get("velocity", 0) or 0)
            velocity_ms = velocity_kts / 1.94384  # kts → m/s
            altitude_ft = float(snap.get("altitude", 0) or 0)
            heading = snap.get("heading")
            vrate_ftmin = float(snap.get("vertical_rate", 0) or 0)

            # Get or create tracker
            if icao24 not in self._trackers:
                self._trackers[icao24] = AircraftTracker(icao24=icao24, callsign=callsign)
            tracker = self._trackers[icao24]
            tracker.callsign = callsign  # Update in case it changes

            cur = AircraftState(
                on_ground=on_ground,
                velocity_ms=velocity_ms,
                latitude=lat,
                longitude=lon,
                altitude_ft=altitude_ft,
                heading=heading,
                vertical_rate_ftmin=vrate_ftmin,
            )

            prev = tracker.prev
            was_parked = prev is not None and prev.phase == "parked"

            # Gate proximity check
            near_gate, gate_dist = self.find_nearest_gate(lat, lon) if on_ground else (None, float("inf"))

            # Determine current phase
            phase = self._infer_phase(on_ground, velocity_ms, near_gate, was_parked)

            # Refine airborne phases
            if phase == "airborne":
                tracker.was_airborne = True
                if altitude_ft < 3000 and vrate_ftmin < -200:
                    phase = "landing"
                elif altitude_ft < 3000 and vrate_ftmin > 200:
                    phase = "takeoff"
                elif altitude_ft < 10000 and vrate_ftmin < -200:
                    phase = "approaching"
                elif altitude_ft < 10000 and vrate_ftmin > 200:
                    phase = "departing"
                else:
                    phase = "enroute"

            cur.phase = phase
            prev_phase = prev.phase if prev else "unknown"

            # ── Detect transitions ───────────────────────────────────

            if prev_phase != phase and prev_phase != "unknown":
                self._emit_phase_transition(timestamp, tracker, prev_phase, phase, cur)

                # Gate occupy: transitioned to parked near a gate
                if phase == "parked" and near_gate:
                    tracker.assigned_gate = near_gate
                    tracker.parked_since = timestamp
                    self._emit_gate_event(timestamp, tracker, near_gate, "assign", gate_dist)
                    self._emit_gate_event(timestamp, tracker, near_gate, "occupy", gate_dist)

                # Gate release: was parked, now moving
                if prev_phase == "parked" and tracker.assigned_gate:
                    self._emit_gate_event(timestamp, tracker, tracker.assigned_gate, "release", gate_dist)
                    tracker.assigned_gate = None
                    tracker.parked_since = None

            elif prev_phase == "unknown" and phase == "parked" and near_gate:
                # First observation is already parked at gate
                tracker.assigned_gate = near_gate
                tracker.parked_since = timestamp
                cur.phase = phase

            # Accumulate enriched snapshot
            self._enriched_snapshots.append({
                "time": timestamp,
                "icao24": icao24,
                "callsign": callsign,
                "latitude": lat,
                "longitude": lon,
                "altitude": altitude_ft,
                "velocity": velocity_kts,
                "heading": heading,
                "vertical_rate": vrate_ftmin,
                "phase": phase,
                "on_ground": on_ground,
                "aircraft_type": snap.get("aircraft_type", ""),
                "assigned_gate": tracker.assigned_gate,
            })

            tracker.prev = cur

    def get_enriched_snapshots(self) -> list[dict[str, Any]]:
        """Return all processed frames with inferred phase and gate assignment.

        Each snapshot has: time, icao24, callsign, latitude, longitude, altitude,
        velocity, heading, vertical_rate, phase, on_ground, aircraft_type, assigned_gate.
        """
        return self._enriched_snapshots

    def get_results(self) -> dict[str, Any]:
        """Return enriched events in simulation-compatible format.

        Returns:
            Dict with "phase_transitions", "gate_events", and "enriched_snapshots" lists.
        """
        logger.info(
            "Event inference complete: %d phase transitions, %d gate events, "
            "%d enriched snapshots, %d aircraft tracked",
            len(self._phase_transitions),
            len(self._gate_events),
            len(self._enriched_snapshots),
            len(self._trackers),
        )
        return {
            "phase_transitions": self._phase_transitions,
            "gate_events": self._gate_events,
            "enriched_snapshots": self._enriched_snapshots,
        }

"""Thread-safe event buffers for ML training data persistence.

Buffers collect events during state machine updates and are drained
periodically by DataGeneratorService for Lakebase persistence.
Extracted from fallback.py.
"""

import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.ingestion._constants import _MAX_BUFFER_SIZE
from src.simulation.diagnostics import diag_log

_phase_transition_buffer: List[Dict[str, Any]] = []
_phase_transition_lock = threading.Lock()

_gate_event_buffer: List[Dict[str, Any]] = []
_gate_event_lock = threading.Lock()

_prediction_buffer: List[Dict[str, Any]] = []
_prediction_lock = threading.Lock()

_turnaround_event_buffer: List[Dict[str, Any]] = []
_turnaround_event_lock = threading.Lock()


_suppress_phase_transition_emit: bool = False


def set_suppress_phase_transitions(suppress: bool) -> None:
    """Enable/disable phase transition buffering (used by simulation engine)."""
    global _suppress_phase_transition_emit
    _suppress_phase_transition_emit = suppress


def emit_phase_transition(
    icao24: str,
    callsign: str,
    from_phase: str,
    to_phase: str,
    latitude: float,
    longitude: float,
    altitude: float,
    aircraft_type: str = "A320",
    assigned_gate: Optional[str] = None,
) -> None:
    """Record a flight phase transition event."""
    if _suppress_phase_transition_emit:
        return

    event = {
        "icao24": icao24,
        "callsign": callsign,
        "from_phase": from_phase,
        "to_phase": to_phase,
        "latitude": latitude,
        "longitude": longitude,
        "altitude": altitude,
        "aircraft_type": aircraft_type,
        "assigned_gate": assigned_gate,
        "event_time": datetime.now(timezone.utc).isoformat(),
    }
    with _phase_transition_lock:
        _phase_transition_buffer.append(event)
        if len(_phase_transition_buffer) > _MAX_BUFFER_SIZE:
            del _phase_transition_buffer[: _MAX_BUFFER_SIZE // 2]

    diag_log(
        "PHASE_TRANSITION", datetime.now(timezone.utc),
        icao24=icao24, callsign=callsign,
        from_phase=from_phase, to_phase=to_phase,
        alt=altitude, vel=0,
    )


def emit_gate_event(
    icao24: str,
    callsign: str,
    gate: str,
    event_type: str,  # "assign", "occupy", "release"
    aircraft_type: str = "A320",
) -> None:
    """Record a gate assignment/release event."""
    event = {
        "icao24": icao24,
        "callsign": callsign,
        "gate": gate,
        "event_type": event_type,
        "aircraft_type": aircraft_type,
        "event_time": datetime.now(timezone.utc).isoformat(),
    }
    with _gate_event_lock:
        _gate_event_buffer.append(event)
        if len(_gate_event_buffer) > _MAX_BUFFER_SIZE:
            del _gate_event_buffer[: _MAX_BUFFER_SIZE // 2]


def emit_prediction(
    prediction_type: str,  # "delay", "congestion", "gate_recommendation"
    icao24: Optional[str],
    result: Dict[str, Any],
) -> None:
    """Record an ML prediction result for feedback/evaluation."""
    event = {
        "prediction_type": prediction_type,
        "icao24": icao24,
        "result_json": result,
        "event_time": datetime.now(timezone.utc).isoformat(),
    }
    with _prediction_lock:
        _prediction_buffer.append(event)
        if len(_prediction_buffer) > _MAX_BUFFER_SIZE:
            del _prediction_buffer[: _MAX_BUFFER_SIZE // 2]


def drain_phase_transitions() -> List[Dict[str, Any]]:
    """Drain and return all buffered phase transition events."""
    with _phase_transition_lock:
        events = list(_phase_transition_buffer)
        _phase_transition_buffer.clear()
    return events


def drain_gate_events() -> List[Dict[str, Any]]:
    """Drain and return all buffered gate events."""
    with _gate_event_lock:
        events = list(_gate_event_buffer)
        _gate_event_buffer.clear()
    return events


def drain_predictions() -> List[Dict[str, Any]]:
    """Drain and return all buffered prediction events."""
    with _prediction_lock:
        events = list(_prediction_buffer)
        _prediction_buffer.clear()
    return events


def emit_turnaround_event(
    icao24: str,
    callsign: str,
    gate: str,
    phase: str,
    event_type: str,  # "phase_start" or "phase_complete"
    aircraft_type: str = "A320",
) -> None:
    """Record a turnaround sub-phase event."""
    event = {
        "icao24": icao24,
        "callsign": callsign,
        "gate": gate,
        "turnaround_phase": phase,
        "event_type": event_type,
        "aircraft_type": aircraft_type,
        "event_time": datetime.now(timezone.utc).isoformat(),
    }
    with _turnaround_event_lock:
        _turnaround_event_buffer.append(event)
        if len(_turnaround_event_buffer) > _MAX_BUFFER_SIZE:
            del _turnaround_event_buffer[: _MAX_BUFFER_SIZE // 2]


def drain_turnaround_events() -> List[Dict[str, Any]]:
    """Drain and return all buffered turnaround events."""
    with _turnaround_event_lock:
        events = list(_turnaround_event_buffer)
        _turnaround_event_buffer.clear()
    return events

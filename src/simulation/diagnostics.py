"""Structured diagnostic event logger for simulation analysis.

Captures machine-readable events alongside the existing SimulationRecorder.
Not a replacement for Python logging — an additional data layer for automated
anomaly detection and root-cause mapping.
"""

import json
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Optional


# Module-level reference (same pattern as _flight_states, _gate_states)
_diagnostics: Optional["DiagnosticLogger"] = None


def get_diagnostics() -> Optional["DiagnosticLogger"]:
    """Return the active DiagnosticLogger, or None if disabled."""
    return _diagnostics


def set_diagnostics(logger: Optional["DiagnosticLogger"]) -> None:
    """Set the module-level diagnostic logger."""
    global _diagnostics
    _diagnostics = logger


def diag_log(event_type: str, sim_time: datetime, **fields: Any) -> None:
    """Convenience: emit a diagnostic event if diagnostics are enabled."""
    dl = _diagnostics
    if dl is not None:
        dl.log(event_type, sim_time, **fields)


class DiagnosticLogger:
    """Collects structured diagnostic events during a simulation run."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.events: list[dict[str, Any]] = []

    def log(self, event_type: str, sim_time: datetime, **fields: Any) -> None:
        """Record a diagnostic event."""
        if not self.enabled:
            return
        self.events.append({
            "type": event_type,
            "sim_time": sim_time.isoformat(),
            **fields,
        })

    def summary(self) -> dict[str, Any]:
        """Compute summary statistics: counts by type, top offenders, anomaly flags."""
        counts: Counter[str] = Counter()
        go_around_by_flight: Counter[str] = Counter()
        separation_losses: list[dict] = []
        gate_conflicts: list[dict] = []
        taxi_violations: list[dict] = []
        runway_conflicts: list[dict] = []
        tick_elapsed: list[float] = []

        for evt in self.events:
            etype = evt["type"]
            counts[etype] += 1

            if etype == "GO_AROUND":
                go_around_by_flight[evt.get("icao24", "unknown")] += 1
            elif etype == "SEPARATION_LOSS":
                separation_losses.append(evt)
            elif etype == "GATE_CONFLICT":
                gate_conflicts.append(evt)
            elif etype == "TAXI_SPEED_VIOLATION":
                taxi_violations.append(evt)
            elif etype == "RUNWAY_CONFLICT":
                runway_conflicts.append(evt)
            elif etype == "TICK_STATS":
                if "elapsed_ms" in evt:
                    tick_elapsed.append(evt["elapsed_ms"])

        total_flights = counts.get("PHASE_TRANSITION", 0)
        total_go_arounds = counts.get("GO_AROUND", 0)

        # Anomaly flags
        anomalies: dict[str, Any] = {}
        if total_flights > 0 and total_go_arounds / max(total_flights, 1) > 0.05:
            anomalies["excessive_go_arounds"] = {
                "count": total_go_arounds,
                "rate": round(total_go_arounds / max(total_flights, 1), 3),
                "top_offenders": go_around_by_flight.most_common(5),
            }
        if separation_losses:
            anomalies["separation_losses"] = {
                "count": len(separation_losses),
                "events": separation_losses[:10],
            }
        if gate_conflicts:
            anomalies["gate_conflicts"] = {
                "count": len(gate_conflicts),
                "events": gate_conflicts[:10],
            }
        if taxi_violations:
            anomalies["taxi_speed_violations"] = {
                "count": len(taxi_violations),
                "events": taxi_violations[:10],
            }
        if runway_conflicts:
            anomalies["runway_conflicts"] = {
                "count": len(runway_conflicts),
                "events": runway_conflicts[:10],
            }

        avg_tick_ms = (
            round(sum(tick_elapsed) / len(tick_elapsed), 2) if tick_elapsed else 0.0
        )

        return {
            "total_events": len(self.events),
            "counts_by_type": dict(counts.most_common()),
            "anomalies": anomalies,
            "avg_tick_ms": avg_tick_ms,
            "max_tick_ms": round(max(tick_elapsed), 2) if tick_elapsed else 0.0,
        }

    def write(self, path: str) -> None:
        """Write all events and summary to a JSON file."""
        output = {
            "summary": self.summary(),
            "events": self.events,
        }
        with open(path, "w") as f:
            json.dump(output, f, indent=2, default=str)

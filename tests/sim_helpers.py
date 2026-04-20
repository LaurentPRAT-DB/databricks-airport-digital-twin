"""Shared helpers for simulation-based tests.

Extracted from multiple test files that all run SimulationEngine, extract
flight traces, and validate aviation properties.
"""

import math
from collections import defaultdict
from datetime import datetime

from src.simulation.recorder import SimulationRecorder


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in nautical miles."""
    R_NM = 3440.065
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return 2 * R_NM * math.asin(math.sqrt(min(a, 1.0)))


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in meters."""
    return haversine_nm(lat1, lon1, lat2, lon2) * 1852.0


def extract_flight_traces(recorder: SimulationRecorder) -> dict[str, list[dict]]:
    """Group position_snapshots by icao24, sorted by time."""
    traces: dict[str, list[dict]] = defaultdict(list)
    for snap in recorder.position_snapshots:
        traces[snap["icao24"]].append(snap)
    for icao24 in traces:
        traces[icao24].sort(key=lambda p: p["time"])
    return dict(traces)


def phase_positions(trace: list[dict], phase: str) -> list[dict]:
    """Extract positions belonging to a specific phase."""
    return [p for p in trace if p["phase"] == phase]


def phase_sequence(trace: list[dict]) -> list[str]:
    """Extract ordered list of distinct phases (deduplicated consecutive)."""
    if not trace:
        return []
    phases = [trace[0]["phase"]]
    for p in trace[1:]:
        if p["phase"] != phases[-1]:
            phases.append(p["phase"])
    return phases


def dt_seconds(t1: str, t2: str) -> float:
    """Seconds between two ISO timestamps."""
    return (datetime.fromisoformat(t2) - datetime.fromisoformat(t1)).total_seconds()

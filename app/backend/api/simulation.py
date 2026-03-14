"""Simulation replay API — serves simulation JSON files to the frontend."""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

simulation_router = APIRouter(prefix="/api/simulation", tags=["simulation"])

# Look for simulation output files in the project root
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


def _find_simulation_files() -> list[dict]:
    """Scan for simulation JSON files in the project root and simulation_output/ dir."""
    files = []
    # Look in both project root (simulation_output_*.json) and simulation_output/ dir
    candidates = sorted(PROJECT_ROOT.glob("simulation_output_*.json"))
    sim_output_dir = PROJECT_ROOT / "simulation_output"
    if sim_output_dir.is_dir():
        candidates.extend(sorted(sim_output_dir.glob("simulation_*.json")))
    for p in candidates:
        try:
            with open(p) as f:
                data = json.load(f)
            summary = data.get("summary", {})
            config = data.get("config", {})
            files.append({
                "filename": p.name,
                "airport": config.get("airport", "?"),
                "total_flights": summary.get("total_flights", 0),
                "arrivals": summary.get("arrivals", 0),
                "departures": summary.get("departures", 0),
                "duration_hours": config.get("duration_hours", 0),
                "size_kb": round(p.stat().st_size / 1024, 1),
                "scenario_name": summary.get("scenario_name"),
            })
        except Exception as e:
            logger.warning(f"Skipping {p.name}: {e}")
    return files


@simulation_router.get("/files")
async def list_simulation_files() -> dict:
    """List available simulation output files."""
    files = _find_simulation_files()
    return {"files": files, "count": len(files)}


@simulation_router.get("/data/{filename}")
async def get_simulation_data(
    filename: str,
    start_hour: float = Query(default=0.0, ge=0, description="Start hour to slice from"),
    end_hour: float = Query(default=24.0, ge=0, description="End hour to slice to"),
) -> dict:
    """
    Load simulation data, optionally sliced to a time window.

    Returns position snapshots and metadata for the frontend replay engine.
    Position snapshots are grouped by timestamp for efficient frame-based playback.
    """
    # Validate filename to prevent path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    filepath = PROJECT_ROOT / filename
    # Also check simulation_output/ subdirectory
    if not filepath.exists():
        filepath = PROJECT_ROOT / "simulation_output" / filename
    if not filepath.exists() or not filepath.name.startswith("simulation"):
        raise HTTPException(status_code=404, detail=f"Simulation file not found: {filename}")

    try:
        with open(filepath) as f:
            data = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read simulation file: {e}")

    config = data.get("config", {})
    summary = data.get("summary", {})
    schedule = data.get("schedule", [])
    snapshots = data.get("position_snapshots", [])
    phase_transitions = data.get("phase_transitions", [])
    gate_events = data.get("gate_events", [])
    scenario_events = data.get("scenario_events", [])

    # Determine simulation start time from config or first snapshot
    start_time_iso = config.get("start_time")
    if not start_time_iso and snapshots:
        start_time_iso = snapshots[0].get("time")

    # Filter snapshots to the requested time window
    if start_time_iso:
        from datetime import datetime, timedelta, timezone
        if isinstance(start_time_iso, str):
            sim_start = datetime.fromisoformat(start_time_iso.replace("Z", "+00:00"))
        else:
            sim_start = start_time_iso

        window_start = sim_start + timedelta(hours=start_hour)
        window_end = sim_start + timedelta(hours=end_hour)

        window_start_iso = window_start.isoformat()
        window_end_iso = window_end.isoformat()

        snapshots = [
            s for s in snapshots
            if window_start_iso <= s.get("time", "") <= window_end_iso
        ]
        phase_transitions = [
            p for p in phase_transitions
            if window_start_iso <= p.get("time", "") <= window_end_iso
        ]
        gate_events = [
            g for g in gate_events
            if window_start_iso <= g.get("time", "") <= window_end_iso
        ]

    # Group snapshots by timestamp for frame-based playback
    frames: dict[str, list] = {}
    for snap in snapshots:
        t = snap.get("time", "")
        if t not in frames:
            frames[t] = []
        frames[t].append(snap)

    # Sort frame timestamps
    sorted_timestamps = sorted(frames.keys())

    return {
        "config": config,
        "summary": summary,
        "schedule": schedule,
        "frames": {t: frames[t] for t in sorted_timestamps},
        "frame_timestamps": sorted_timestamps,
        "frame_count": len(sorted_timestamps),
        "phase_transitions": phase_transitions,
        "gate_events": gate_events,
        "scenario_events": scenario_events,
        "time_window": {
            "start_hour": start_hour,
            "end_hour": end_hour,
        },
    }

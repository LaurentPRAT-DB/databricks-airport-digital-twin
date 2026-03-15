"""Simulation replay API — serves simulation JSON files to the frontend."""

import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

simulation_router = APIRouter(prefix="/api/simulation", tags=["simulation"])

# Look for simulation output files in the project root
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

# UC coordinates (read from env, same as DeltaService)
_UC_CATALOG = os.getenv("DATABRICKS_CATALOG", "serverless_stable_3n0ihb_catalog")
_UC_SCHEMA = os.getenv("DATABRICKS_SCHEMA", "airport_digital_twin")
_UC_VOLUME = "simulation_data"


def _find_simulation_files_local() -> list[dict]:
    """Scan for simulation JSON files on the local filesystem."""
    files = []
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


def _find_simulation_files_from_catalog() -> list[dict] | None:
    """Query simulation_runs table in Unity Catalog for file listing.

    Uses the Databricks SDK StatementExecution API with a threaded timeout
    to prevent WorkspaceClient() from hanging on U2M browser-based OAuth
    in headless environments (Databricks Apps).
    """
    try:
        from databricks.sdk import WorkspaceClient
        from databricks.sdk.service.sql import StatementState
    except ImportError:
        return None

    warehouse_id = os.getenv("DATABRICKS_WAREHOUSE_ID", "")
    if not warehouse_id:
        # Extract from HTTP_PATH: /sql/1.0/warehouses/<id>
        http_path = os.getenv("DATABRICKS_HTTP_PATH", "")
        if "/warehouses/" in http_path:
            warehouse_id = http_path.rsplit("/warehouses/", 1)[-1]
    if not warehouse_id:
        return None

    import threading

    result: list = []
    error: list = []

    def _try_query():
        try:
            w = WorkspaceClient()
            resp = w.statement_execution.execute_statement(
                warehouse_id=warehouse_id,
                statement=f"""
                    SELECT filename, airport, scenario_name, total_flights,
                           arrivals, departures, duration_hours, size_bytes,
                           volume_path
                    FROM {_UC_CATALOG}.{_UC_SCHEMA}.simulation_runs
                    ORDER BY created_at DESC
                """,
                wait_timeout="15s",
            )
            if not (resp.status and resp.status.state == StatementState.SUCCEEDED):
                error.append(f"Statement failed: {resp.status}")
                return

            files = []
            columns = [c.name for c in resp.manifest.schema.columns]
            for row in (resp.result.data_array or []):
                r = dict(zip(columns, row))
                files.append({
                    "filename": r["filename"],
                    "airport": r["airport"],
                    "total_flights": int(r["total_flights"] or 0),
                    "arrivals": int(r["arrivals"] or 0),
                    "departures": int(r["departures"] or 0),
                    "duration_hours": float(r["duration_hours"] or 0),
                    "size_kb": round(int(r["size_bytes"] or 0) / 1024, 1),
                    "scenario_name": r["scenario_name"],
                    "volume_path": r["volume_path"],
                })
            result.append(files)
        except Exception as e:
            error.append(e)

    thread = threading.Thread(target=_try_query, daemon=True)
    thread.start()
    thread.join(timeout=15)  # 15s max to prevent U2M hang

    if result:
        logger.info(f"Catalog returned {len(result[0])} simulation files")
        return result[0]
    if error:
        logger.warning(f"Failed to query simulation_runs table: {error[0]}")
    else:
        logger.warning("Timed out querying simulation_runs (possible U2M auth flow)")
    return None


def _load_simulation_from_volume(filename: str) -> dict | None:
    """Read simulation JSON from UC Volume via the Databricks SDK.

    Uses a threaded timeout to prevent WorkspaceClient() from hanging on
    U2M browser-based OAuth in headless environments (Databricks Apps).
    """
    try:
        from databricks.sdk import WorkspaceClient
    except ImportError:
        return None

    import threading

    volume_path = f"/Volumes/{_UC_CATALOG}/{_UC_SCHEMA}/{_UC_VOLUME}/{filename}"
    result: list = []
    error: list = []

    def _try_load():
        try:
            w = WorkspaceClient()
            resp = w.files.download(volume_path)
            result.append(json.loads(resp.contents.read()))
        except Exception as e:
            error.append(e)

    thread = threading.Thread(target=_try_load, daemon=True)
    thread.start()
    thread.join(timeout=15)  # 15s max to prevent U2M hang

    if result:
        logger.info(f"Loaded {filename} from UC Volume")
        return result[0]
    if error:
        logger.warning(f"Failed to read {filename} from UC Volume: {error[0]}")
    else:
        logger.warning(f"Timed out loading {filename} from UC Volume (possible U2M auth flow)")
    return None


def _load_simulation_local(filename: str) -> dict | None:
    """Read simulation JSON from local filesystem."""
    if "/" in filename or "\\" in filename or ".." in filename:
        return None

    filepath = PROJECT_ROOT / filename
    if not filepath.exists():
        filepath = PROJECT_ROOT / "simulation_output" / filename
    if not filepath.exists() or not filepath.name.startswith("simulation"):
        return None

    try:
        with open(filepath) as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to read local file {filename}: {e}")
        return None


@simulation_router.get("/files")
async def list_simulation_files() -> dict:
    """List available simulation output files."""
    # Try catalog first (works in deployed app), fall back to local filesystem
    files = _find_simulation_files_from_catalog()
    if files is None:
        files = _find_simulation_files_local()
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

    # Try UC Volume first, fall back to local
    data = _load_simulation_from_volume(filename)
    if data is None:
        data = _load_simulation_local(filename)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Simulation file not found: {filename}")

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

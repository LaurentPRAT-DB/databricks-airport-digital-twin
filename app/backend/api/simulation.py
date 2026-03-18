"""Simulation replay API — serves simulation JSON files to the frontend."""

import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request

logger = logging.getLogger(__name__)

simulation_router = APIRouter(prefix="/api/simulation", tags=["simulation"])

# Look for simulation output files in the project root
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

# UC coordinates (read from env, same as DeltaService)
_UC_CATALOG = os.getenv("DATABRICKS_CATALOG", "serverless_stable_3n0ihb_catalog")
_UC_SCHEMA = os.getenv("DATABRICKS_SCHEMA", "airport_digital_twin")
_UC_VOLUME = "simulation_data"

# Files larger than this cannot be loaded into browser memory
_MAX_LOADABLE_BYTES = 1 * 1024 * 1024 * 1024  # 1 GB


def _extract_user_token(request: Request | None) -> str | None:
    """Extract the user's Bearer token from the request for OBO auth."""
    if request is None:
        return None
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer "):]
    return None


def _make_workspace_client(user_token: str | None = None):
    """Create a WorkspaceClient, optionally using OBO with a user token."""
    from databricks.sdk import WorkspaceClient

    if user_token:
        host = os.getenv("DATABRICKS_HOST", "")
        if not host:
            # Try to infer from default client
            try:
                w = WorkspaceClient()
                host = w.config.host
            except Exception:
                return None
        return WorkspaceClient(host=host, token=user_token)
    return WorkspaceClient()


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
            size_bytes = p.stat().st_size
            files.append({
                "filename": p.name,
                "airport": config.get("airport", "?"),
                "total_flights": summary.get("total_flights", 0),
                "arrivals": summary.get("arrivals", 0),
                "departures": summary.get("departures", 0),
                "duration_hours": config.get("duration_hours", 0),
                "size_kb": round(size_bytes / 1024, 1),
                "size_bytes": size_bytes,
                "scenario_name": summary.get("scenario_name"),
            })
        except Exception as e:
            logger.warning(f"Skipping {p.name}: {e}")
    return files


def _find_simulation_files_from_catalog(user_token: str | None = None) -> list[dict] | None:
    """Query simulation_runs table in Unity Catalog for file listing.

    Uses the Databricks SDK StatementExecution API with a threaded timeout
    to prevent WorkspaceClient() from hanging on U2M browser-based OAuth
    in headless environments (Databricks Apps).

    Tries SP auth first; falls back to OBO if SP auth fails and a user token
    is available.
    """
    try:
        from databricks.sdk.service.sql import StatementState
    except ImportError:
        logger.warning("databricks-sdk not installed, cannot query simulation_runs")
        return None

    warehouse_id = os.getenv("DATABRICKS_WAREHOUSE_ID", "")
    if not warehouse_id:
        # Extract from HTTP_PATH: /sql/1.0/warehouses/<id>
        http_path = os.getenv("DATABRICKS_HTTP_PATH", "")
        if "/warehouses/" in http_path:
            warehouse_id = http_path.rsplit("/warehouses/", 1)[-1]
    if not warehouse_id:
        logger.warning("No warehouse ID available for simulation_runs query")
        return None

    logger.info(f"Querying simulation_runs with warehouse_id={warehouse_id}")

    import threading

    # Try SP auth first, then OBO fallback
    tokens_to_try = [None]  # None = default SP auth
    if user_token:
        tokens_to_try.append(user_token)

    for token in tokens_to_try:
        auth_label = "OBO" if token else "SP"
        result: list = []
        error: list = []

        def _try_query(tkn=token):
            try:
                w = _make_workspace_client(tkn)
                if w is None:
                    error.append("Could not create WorkspaceClient")
                    return
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
                    size_bytes = int(r["size_bytes"] or 0)
                    files.append({
                        "filename": r["filename"],
                        "airport": r["airport"],
                        "total_flights": int(r["total_flights"] or 0),
                        "arrivals": int(r["arrivals"] or 0),
                        "departures": int(r["departures"] or 0),
                        "duration_hours": float(r["duration_hours"] or 0),
                        "size_kb": round(size_bytes / 1024, 1),
                        "size_bytes": size_bytes,
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
            logger.info(f"Catalog returned {len(result[0])} simulation files via {auth_label} auth")
            return result[0]
        if error:
            logger.warning(f"Failed to query simulation_runs via {auth_label}: {error[0]}")
        else:
            logger.warning(f"Timed out querying simulation_runs via {auth_label}")

        # If SP failed and we have a user token, try OBO next iteration
        if token is None and user_token:
            logger.info("SP auth failed, trying OBO fallback...")

    return None


def _load_simulation_from_volume(
    filename: str,
    user_token: str | None = None,
    size_bytes: int | None = None,
) -> dict | None:
    """Read simulation JSON from UC Volume via the Databricks SDK.

    Uses a threaded timeout to prevent WorkspaceClient() from hanging on
    U2M browser-based OAuth in headless environments (Databricks Apps).

    Timeout scales with file size: 1 min per 100 MB, max 10 min.
    Tries SP auth first; falls back to OBO if a user token is available.
    """
    try:
        from databricks.sdk import WorkspaceClient  # noqa: F401
    except ImportError:
        return None

    # Check size cap
    if size_bytes and size_bytes > _MAX_LOADABLE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File is too large for browser playback ({size_bytes / (1024**3):.1f} GB). Max: 1 GB.",
        )

    # Scale timeout: 1 min per 100 MB, min 60s, max 600s
    if size_bytes and size_bytes > 0:
        timeout = min(600, max(60, int(size_bytes / (100 * 1024 * 1024) * 60)))
    else:
        timeout = 60

    import threading

    volume_path = f"/Volumes/{_UC_CATALOG}/{_UC_SCHEMA}/{_UC_VOLUME}/{filename}"
    logger.info(f"Loading simulation from UC Volume: {volume_path} (timeout={timeout}s)")

    # Try SP auth first, then OBO fallback
    tokens_to_try = [None]
    if user_token:
        tokens_to_try.append(user_token)

    for token in tokens_to_try:
        auth_label = "OBO" if token else "SP"
        result: list = []
        error: list = []

        def _try_load(tkn=token):
            try:
                w = _make_workspace_client(tkn)
                if w is None:
                    error.append("Could not create WorkspaceClient")
                    return
                resp = w.files.download(volume_path)
                result.append(json.loads(resp.contents.read()))
            except Exception as e:
                error.append(e)

        thread = threading.Thread(target=_try_load, daemon=True)
        thread.start()
        thread.join(timeout=timeout)

        if result:
            logger.info(f"Loaded {filename} from UC Volume via {auth_label} ({len(json.dumps(result[0])) // 1024} KB)")
            return result[0]
        if error:
            logger.warning(f"Failed to read {filename} via {auth_label}: {error[0]}")
        else:
            logger.warning(f"Timed out loading {filename} via {auth_label} ({timeout}s)")

        if token is None and user_token:
            logger.info("SP auth failed for file download, trying OBO fallback...")

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


def _get_file_size_bytes(filename: str, files_cache: list[dict] | None) -> int | None:
    """Look up size_bytes for a filename from the cached file listing."""
    if files_cache:
        for f in files_cache:
            if f.get("filename") == filename:
                return f.get("size_bytes")
    return None


@simulation_router.get("/files")
async def list_simulation_files(request: Request) -> dict:
    """List available simulation output files."""
    user_token = _extract_user_token(request)
    # Try catalog first (works in deployed app), fall back to local filesystem
    files = _find_simulation_files_from_catalog(user_token=user_token)
    if files is None:
        files = _find_simulation_files_local()
    return {"files": files, "count": len(files)}


@simulation_router.get("/data/{filename}")
async def get_simulation_data(
    request: Request,
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

    user_token = _extract_user_token(request)

    # Look up file size from catalog to enforce size cap and set timeout
    catalog_files = _find_simulation_files_from_catalog(user_token=user_token)
    size_bytes = _get_file_size_bytes(filename, catalog_files)

    # Try UC Volume first, fall back to local
    data = _load_simulation_from_volume(filename, user_token=user_token, size_bytes=size_bytes)
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

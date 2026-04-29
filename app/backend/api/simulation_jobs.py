"""REST API for creating and monitoring simulation jobs on Databricks."""

import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

simulation_jobs_router = APIRouter(prefix="/api/simulation", tags=["simulation-jobs"])

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

_UC_CATALOG = os.getenv("DATABRICKS_CATALOG", "serverless_stable_3n0ihb_catalog")
_UC_SCHEMA = os.getenv("DATABRICKS_SCHEMA", "airport_digital_twin")
_UC_VOLUME = "simulation_data"


def _extract_user_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer "):]
    return None


def _make_workspace_client(user_token: str | None = None):
    from databricks.sdk import WorkspaceClient

    if user_token:
        host = os.getenv("DATABRICKS_HOST", "")
        if not host:
            try:
                w = WorkspaceClient()
                host = w.config.host
            except Exception:
                return None
        return WorkspaceClient(host=host, token=user_token)
    return WorkspaceClient()


_BUNDLE_WS_ROOT = os.getenv(
    "BUNDLE_WORKSPACE_ROOT",
    "/Workspace/Users/laurent.prat@databricks.com/.bundle/airport-digital-twin/dev/files",
)


def _get_notebook_path() -> str:
    """Derive the workspace path for the simulation runner notebook."""
    ws_root = _BUNDLE_WS_ROOT
    if ws_root.startswith("/Workspace"):
        ws_root = ws_root[len("/Workspace"):]
    return f"{ws_root}/databricks/notebooks/run_simulation_airport"


# ── Request / Response Models ────────────────────────────────────────

class CustomScenario(BaseModel):
    name: str = "Custom Scenario"
    description: str = ""
    weather_events: list[dict] = Field(default_factory=list)
    runway_events: list[dict] = Field(default_factory=list)
    ground_events: list[dict] = Field(default_factory=list)
    traffic_modifiers: list[dict] = Field(default_factory=list)


class CreateSimulationRequest(BaseModel):
    airport: str
    arrivals: int = 500
    departures: int = 500
    duration_hours: int = 24
    time_step_seconds: float = 2.0
    seed: Optional[int] = None
    scenario_name: Optional[str] = None
    custom_scenario: Optional[CustomScenario] = None
    skip_positions: bool = False
    run_name: Optional[str] = None


class SimulationJobResponse(BaseModel):
    run_id: int
    status: str
    airport: str
    run_name: str
    start_time: Optional[int] = None
    end_time: Optional[int] = None
    elapsed_seconds: Optional[int] = None
    run_page_url: Optional[str] = None
    output_file: Optional[str] = None


# ── Helpers ──────────────────────────────────────────────────────────

def _write_custom_scenario_to_volume(
    scenario: CustomScenario,
    user_token: str | None,
) -> str | None:
    """Write a custom scenario YAML to the UC Volume and return its FUSE path."""
    scenario_dict = {
        "name": scenario.name,
        "description": scenario.description,
    }
    if scenario.weather_events:
        scenario_dict["weather_events"] = scenario.weather_events
    if scenario.runway_events:
        scenario_dict["runway_events"] = scenario.runway_events
    if scenario.ground_events:
        scenario_dict["ground_events"] = scenario.ground_events
    if scenario.traffic_modifiers:
        scenario_dict["traffic_modifiers"] = scenario.traffic_modifiers

    yaml_content = yaml.dump(scenario_dict, default_flow_style=False, sort_keys=False)
    filename = f"custom_scenario_{int(time.time())}.yaml"
    volume_path = f"/Volumes/{_UC_CATALOG}/{_UC_SCHEMA}/{_UC_VOLUME}/scenarios/{filename}"

    tokens_to_try = [None]
    if user_token:
        tokens_to_try.append(user_token)

    for token in tokens_to_try:
        result: list = []
        error: list = []

        def _try_write(tkn=token):
            try:
                w = _make_workspace_client(tkn)
                if w is None:
                    error.append("Could not create WorkspaceClient")
                    return
                w.files.upload(volume_path, yaml_content.encode("utf-8"), overwrite=True)
                result.append(True)
            except Exception as e:
                error.append(e)

        thread = threading.Thread(target=_try_write, daemon=True)
        thread.start()
        thread.join(timeout=15)

        if result:
            return volume_path
        if error:
            logger.warning(f"Failed to write scenario: {error[0]}")

    return None


def _format_run(run) -> SimulationJobResponse:
    """Convert a Databricks Run object to our response model."""
    state = run.state
    if state:
        life = state.life_cycle_state.value if state.life_cycle_state else "UNKNOWN"
        result = state.result_state.value if state.result_state else None
        if life in ("TERMINATED",) and result:
            status = result
        else:
            status = life
    else:
        status = "UNKNOWN"

    elapsed = None
    if run.start_time and run.end_time:
        elapsed = int((run.end_time - run.start_time) / 1000)
    elif run.start_time:
        elapsed = int((time.time() * 1000 - run.start_time) / 1000)

    # Try to extract output filename from notebook output
    output_file = None
    if status == "SUCCESS" and run.tasks:
        for task in run.tasks:
            if task.state and task.state.result_state and task.state.result_state.value == "SUCCESS":
                try:
                    import json
                    output = task.run_output if hasattr(task, "run_output") else None
                    if output and hasattr(output, "notebook_output") and output.notebook_output:
                        result_data = json.loads(output.notebook_output.result or "{}")
                        output_file = result_data.get("output_file")
                except Exception:
                    pass

    # Extract airport from run name or task parameters
    airport = ""
    if run.run_name and run.run_name.startswith("Simulation "):
        parts = run.run_name.split()
        if len(parts) >= 2:
            airport = parts[1]
    if not airport and run.tasks:
        for task in run.tasks:
            nb = task.notebook_task if hasattr(task, "notebook_task") else None
            if nb and hasattr(nb, "base_parameters") and nb.base_parameters:
                airport = nb.base_parameters.get("airport", "")
                break

    return SimulationJobResponse(
        run_id=run.run_id,
        status=status,
        airport=airport,
        run_name=run.run_name or "",
        start_time=run.start_time,
        end_time=run.end_time,
        elapsed_seconds=elapsed,
        run_page_url=getattr(run, "run_page_url", None),
        output_file=output_file,
    )


def _sdk_call(fn, user_token: str | None, timeout: int = 30):
    """Execute a Databricks SDK call with SP + OBO fallback and timeout."""
    tokens_to_try = [None]
    if user_token:
        tokens_to_try.append(user_token)

    for token in tokens_to_try:
        auth_label = "OBO" if token else "SP"
        result: list = []
        error: list = []

        def _try(tkn=token):
            try:
                w = _make_workspace_client(tkn)
                if w is None:
                    error.append("Could not create WorkspaceClient")
                    return
                result.append(fn(w))
            except Exception as e:
                error.append(e)

        thread = threading.Thread(target=_try, daemon=True)
        thread.start()
        thread.join(timeout=timeout)

        if result:
            return result[0]
        if error:
            logger.warning(f"SDK call failed via {auth_label}: {error[0]}")
        else:
            logger.warning(f"SDK call timed out via {auth_label}")

        if token is None and user_token:
            logger.info("SP auth failed, trying OBO...")

    return None


# ── Endpoints ────────────────────────────────────────────────────────

@simulation_jobs_router.post("/jobs")
async def create_simulation_job(request: Request, body: CreateSimulationRequest):
    """Submit a new simulation job to Databricks."""
    from databricks.sdk.service.jobs import SubmitTask, NotebookTask, Source

    user_token = _extract_user_token(request)
    notebook_path = _get_notebook_path()

    params = {
        "airport": body.airport,
        "arrivals": str(body.arrivals),
        "departures": str(body.departures),
        "duration_hours": str(body.duration_hours),
        "time_step_seconds": str(body.time_step_seconds),
        "output_file": f"simulation_output/sim_{body.airport.lower()}_{int(time.time())}.json",
    }
    if body.seed is not None:
        params["seed"] = str(body.seed)
    if body.skip_positions:
        params["skip_positions"] = "true"

    if body.scenario_name:
        ws_root = _BUNDLE_WS_ROOT
        if ws_root.startswith("/Workspace"):
            ws_root = ws_root[len("/Workspace"):]
        params["scenario_file"] = f"{ws_root}/scenarios/{body.scenario_name}"
    elif body.custom_scenario:
        vol_path = _write_custom_scenario_to_volume(body.custom_scenario, user_token)
        if not vol_path:
            raise HTTPException(status_code=500, detail="Failed to write custom scenario to Volume")
        params["scenario_file"] = vol_path

    total_flights = body.arrivals + body.departures
    run_name = body.run_name or f"Simulation {body.airport} {total_flights}f"

    task = SubmitTask(
        task_key="run_simulation",
        notebook_task=NotebookTask(
            notebook_path=notebook_path,
            base_parameters=params,
            source=Source.WORKSPACE,
        ),
    )

    def _submit(w):
        waiter = w.jobs.submit(
            run_name=run_name,
            tasks=[task],
            timeout_seconds=7200,
        )
        return waiter.run_id

    run_id = _sdk_call(_submit, user_token, timeout=30)
    if run_id is None:
        raise HTTPException(status_code=500, detail="Failed to submit simulation job")

    lakebase = _get_lakebase()
    lakebase.insert_simulation_run(run_id, run_name, body.airport)

    logger.info(f"Submitted simulation job run_id={run_id}: {run_name}")
    return {"run_id": run_id, "run_name": run_name}


@simulation_jobs_router.get("/jobs")
async def list_simulation_jobs(request: Request):
    """List simulation runs tracked in the runs registry."""
    user_token = _extract_user_token(request)
    lakebase = _get_lakebase()
    known_ids = set(lakebase.list_simulation_run_ids())

    if not known_ids:
        return {"jobs": []}

    def _list(w):
        results = []
        for rid in known_ids:
            try:
                run = w.jobs.get_run(rid)
                results.append(_format_run(run))
            except Exception:
                pass
        results.sort(key=lambda j: j.start_time or 0, reverse=True)
        return results

    jobs = _sdk_call(_list, user_token, timeout=30)
    if jobs is None:
        return {"jobs": [], "error": "Could not connect to Databricks"}

    return {"jobs": [j.model_dump() for j in jobs]}


@simulation_jobs_router.get("/jobs/{run_id}")
async def get_simulation_job(request: Request, run_id: int):
    """Get status of a specific simulation run."""
    user_token = _extract_user_token(request)

    def _get(w):
        run = w.jobs.get_run(run_id)
        return _format_run(run)

    job = _sdk_call(_get, user_token, timeout=15)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found or not accessible")

    return job.model_dump()


@simulation_jobs_router.get("/scenarios")
async def list_scenarios():
    """List available built-in scenario YAML files."""
    scenarios_dir = PROJECT_ROOT / "scenarios"
    logger.info(
        f"Scanning scenarios: PROJECT_ROOT={PROJECT_ROOT}, "
        f"scenarios_dir={scenarios_dir}, exists={scenarios_dir.is_dir()}"
    )

    if not scenarios_dir.is_dir():
        alt = Path.cwd() / "scenarios"
        logger.info(f"Trying fallback: {alt}, exists={alt.is_dir()}")
        if alt.is_dir():
            scenarios_dir = alt

    if not scenarios_dir.is_dir():
        logger.warning(f"Scenarios directory not found at {scenarios_dir}")
        return {"scenarios": []}

    results = []
    for f in sorted(scenarios_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text())
            results.append({
                "filename": f.name,
                "name": data.get("name", f.stem),
                "description": (data.get("description", "") or "").strip(),
            })
        except Exception as e:
            logger.warning(f"Skipping scenario {f.name}: {e}")

    logger.info(f"Found {len(results)} scenarios")
    return {"scenarios": results}


def _resolve_scenarios_dir() -> Path | None:
    """Find the scenarios directory, with fallback."""
    d = PROJECT_ROOT / "scenarios"
    if d.is_dir():
        return d
    alt = Path.cwd() / "scenarios"
    if alt.is_dir():
        return alt
    return None


@simulation_jobs_router.get("/scenarios/{filename}")
async def get_scenario_detail(filename: str):
    """Return full content of a built-in scenario YAML file."""
    scenarios_dir = _resolve_scenarios_dir()
    if not scenarios_dir:
        raise HTTPException(status_code=404, detail="Scenarios directory not found")

    path = scenarios_dir / filename
    if not path.is_file() or not path.suffix == ".yaml":
        raise HTTPException(status_code=404, detail=f"Scenario {filename} not found")

    try:
        data = yaml.safe_load(path.read_text())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse scenario: {e}")

    return {
        "filename": filename,
        "name": data.get("name", path.stem),
        "description": (data.get("description", "") or "").strip(),
        "weather_events": data.get("weather_events", []),
        "runway_events": data.get("runway_events", []),
        "ground_events": data.get("ground_events", []),
        "traffic_modifiers": data.get("traffic_modifiers", []),
    }


# ── Draft Management (Lakebase + Delta backup) ────────────────────────

_DRAFTS_DIR = f"/Volumes/{_UC_CATALOG}/{_UC_SCHEMA}/{_UC_VOLUME}/drafts"


class SimulationDraft(BaseModel):
    name: str
    display_name: str
    airport: str
    arrivals: int = 500
    departures: int = 500
    duration_hours: int = 24
    time_step_seconds: float = 2.0
    seed: Optional[int] = None
    scenario_name: Optional[str] = None
    custom_scenario: Optional[CustomScenario] = None
    skip_positions: bool = False
    run_id: Optional[int] = None
    created_at: str = ""
    updated_at: str = ""


class SaveDraftRequest(BaseModel):
    display_name: str
    airport: str
    arrivals: int = 500
    departures: int = 500
    duration_hours: int = 24
    time_step_seconds: float = 2.0
    seed: Optional[int] = None
    scenario_name: Optional[str] = None
    custom_scenario: Optional[CustomScenario] = None
    skip_positions: bool = False


def _slugify(name: str) -> str:
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:80] or "draft"


def _get_lakebase():
    from app.backend.services.lakebase_service import get_lakebase_service
    return get_lakebase_service()


def _sync_draft_to_delta(draft_dict: dict, user_token: str | None, delete: bool = False):
    """Background sync of draft to Delta table for backup."""
    import json as _json

    def _do_sync():
        name = draft_dict.get("name", "")
        if delete:
            def _del(w):
                w.statement_execution.execute_statement(
                    warehouse_id=os.getenv("DATABRICKS_SQL_WAREHOUSE_ID", ""),
                    statement=f"DELETE FROM {_UC_CATALOG}.{_UC_SCHEMA}.simulation_drafts WHERE name = '{name}'",
                    wait_timeout="30s",
                )
            _sdk_call(_del, user_token, timeout=15)
        else:
            custom = draft_dict.get("custom_scenario")
            custom_str = _json.dumps(custom) if custom else None

            def _upsert(w):
                cols = "name, display_name, airport, arrivals, departures, duration_hours, time_step_seconds, seed, scenario_name, custom_scenario, skip_positions, created_at, updated_at"
                vals = ", ".join([
                    f"'{draft_dict['name']}'",
                    f"'{draft_dict['display_name']}'",
                    f"'{draft_dict['airport']}'",
                    str(draft_dict.get('arrivals', 500)),
                    str(draft_dict.get('departures', 500)),
                    str(draft_dict.get('duration_hours', 24)),
                    str(draft_dict.get('time_step_seconds', 2.0)),
                    str(draft_dict.get('seed') or 'NULL'),
                    f"'{draft_dict.get('scenario_name') or ''}'",
                    f"'{(custom_str or '').replace(chr(39), chr(39)+chr(39))}'" if custom_str else "NULL",
                    str(draft_dict.get('skip_positions', False)).lower(),
                    f"'{draft_dict.get('created_at', '')}'",
                    f"'{draft_dict.get('updated_at', '')}'",
                ])
                sql = f"""
                    MERGE INTO {_UC_CATALOG}.{_UC_SCHEMA}.simulation_drafts AS t
                    USING (SELECT {vals}) AS s({cols})
                    ON t.name = s.name
                    WHEN MATCHED THEN UPDATE SET *
                    WHEN NOT MATCHED THEN INSERT *
                """
                w.statement_execution.execute_statement(
                    warehouse_id=os.getenv("DATABRICKS_SQL_WAREHOUSE_ID", ""),
                    statement=sql,
                    wait_timeout="30s",
                )
            _sdk_call(_upsert, user_token, timeout=15)

    threading.Thread(target=_do_sync, daemon=True).start()


def _migrate_volume_drafts_to_lakebase(user_token: str | None):
    """One-time migration: read YAML drafts from UC Volume into Lakebase."""
    lakebase = _get_lakebase()

    def _list_volume(w):
        try:
            entries = list(w.files.list_directory_contents(_DRAFTS_DIR))
        except Exception:
            return []
        drafts = []
        for entry in entries:
            if not entry.path.endswith(".yaml"):
                continue
            try:
                resp = w.files.download(entry.path)
                content = resp.contents.read().decode("utf-8")
                data = yaml.safe_load(content)
                drafts.append(data)
            except Exception as e:
                logger.warning("Skipping volume draft %s: %s", entry.path, e)
        return drafts

    volume_drafts = _sdk_call(_list_volume, user_token, timeout=20)
    if not volume_drafts:
        return 0

    migrated = 0
    for d in volume_drafts:
        if lakebase.upsert_simulation_draft(d):
            migrated += 1
    logger.info("Migrated %d drafts from UC Volume to Lakebase", migrated)
    return migrated


@simulation_jobs_router.get("/drafts")
async def list_drafts(request: Request):
    """List all saved simulation drafts from Lakebase."""
    lakebase = _get_lakebase()
    drafts = lakebase.list_simulation_drafts()

    if not drafts:
        user_token = _extract_user_token(request)
        migrated = _migrate_volume_drafts_to_lakebase(user_token)
        if migrated > 0:
            drafts = lakebase.list_simulation_drafts()

    return {"drafts": drafts}


@simulation_jobs_router.post("/drafts")
async def save_draft(request: Request, body: SaveDraftRequest):
    """Save a new simulation draft to Lakebase (+ async Delta backup)."""
    from datetime import datetime, timezone

    name = _slugify(body.display_name)
    now = datetime.now(timezone.utc).isoformat()

    draft = SimulationDraft(
        name=name,
        display_name=body.display_name,
        airport=body.airport,
        arrivals=body.arrivals,
        departures=body.departures,
        duration_hours=body.duration_hours,
        time_step_seconds=body.time_step_seconds,
        seed=body.seed,
        scenario_name=body.scenario_name,
        custom_scenario=body.custom_scenario,
        skip_positions=body.skip_positions,
        created_at=now,
        updated_at=now,
    )
    draft_dict = draft.model_dump(mode="json")

    lakebase = _get_lakebase()
    if not lakebase.upsert_simulation_draft(draft_dict):
        raise HTTPException(status_code=500, detail="Failed to save draft")

    _sync_draft_to_delta(draft_dict, _extract_user_token(request))
    return draft_dict


@simulation_jobs_router.put("/drafts/{name}")
async def update_draft(request: Request, name: str, body: SaveDraftRequest):
    """Update an existing simulation draft in Lakebase (+ async Delta backup)."""
    from datetime import datetime, timezone

    lakebase = _get_lakebase()
    now = datetime.now(timezone.utc).isoformat()

    existing = lakebase.get_simulation_draft(name)
    created_at = existing["created_at"] if existing else now

    draft = SimulationDraft(
        name=name,
        display_name=body.display_name,
        airport=body.airport,
        arrivals=body.arrivals,
        departures=body.departures,
        duration_hours=body.duration_hours,
        time_step_seconds=body.time_step_seconds,
        seed=body.seed,
        scenario_name=body.scenario_name,
        custom_scenario=body.custom_scenario,
        skip_positions=body.skip_positions,
        created_at=created_at,
        updated_at=now,
    )
    draft_dict = draft.model_dump(mode="json")

    if not lakebase.upsert_simulation_draft(draft_dict):
        raise HTTPException(status_code=500, detail="Failed to update draft")

    _sync_draft_to_delta(draft_dict, _extract_user_token(request))
    return draft_dict


@simulation_jobs_router.delete("/drafts/{name}")
async def delete_draft(request: Request, name: str):
    """Delete a simulation draft from Lakebase (+ async Delta cleanup)."""
    lakebase = _get_lakebase()
    if not lakebase.delete_simulation_draft(name):
        raise HTTPException(status_code=500, detail="Failed to delete draft")

    _sync_draft_to_delta({"name": name}, _extract_user_token(request), delete=True)
    return {"deleted": name}


@simulation_jobs_router.post("/drafts/{name}/run")
async def run_draft(request: Request, name: str):
    """Run a saved draft: create a Databricks job and store its run_id on the draft."""
    from databricks.sdk.service.jobs import SubmitTask, NotebookTask, Source
    from datetime import datetime, timezone

    lakebase = _get_lakebase()
    existing = lakebase.get_simulation_draft(name)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Draft '{name}' not found")

    user_token = _extract_user_token(request)
    notebook_path = _get_notebook_path()

    params = {
        "airport": existing["airport"],
        "arrivals": str(existing.get("arrivals", 500)),
        "departures": str(existing.get("departures", 500)),
        "duration_hours": str(existing.get("duration_hours", 24)),
        "time_step_seconds": str(existing.get("time_step_seconds", 2.0)),
        "output_file": f"simulation_output/sim_{existing['airport'].lower()}_{int(time.time())}.json",
    }
    seed = existing.get("seed")
    if seed is not None:
        params["seed"] = str(seed)
    if existing.get("skip_positions"):
        params["skip_positions"] = "true"

    scenario_name = existing.get("scenario_name")
    custom_scenario = existing.get("custom_scenario")
    if scenario_name:
        ws_root = _BUNDLE_WS_ROOT
        if ws_root.startswith("/Workspace"):
            ws_root = ws_root[len("/Workspace"):]
        params["scenario_file"] = f"{ws_root}/scenarios/{scenario_name}"
    elif custom_scenario:
        cs = CustomScenario(**custom_scenario) if isinstance(custom_scenario, dict) else custom_scenario
        vol_path = _write_custom_scenario_to_volume(cs, user_token)
        if not vol_path:
            raise HTTPException(status_code=500, detail="Failed to write custom scenario to Volume")
        params["scenario_file"] = vol_path

    total_flights = existing.get("arrivals", 500) + existing.get("departures", 500)
    run_name = existing.get("display_name") or f"Simulation {existing['airport']} {total_flights}f"

    task = SubmitTask(
        task_key="run_simulation",
        notebook_task=NotebookTask(
            notebook_path=notebook_path,
            base_parameters=params,
            source=Source.WORKSPACE,
        ),
    )

    def _submit(w):
        waiter = w.jobs.submit(run_name=run_name, tasks=[task], timeout_seconds=7200)
        return waiter.run_id

    run_id = _sdk_call(_submit, user_token, timeout=30)
    if run_id is None:
        raise HTTPException(status_code=500, detail="Failed to submit simulation job")

    lakebase.insert_simulation_run(run_id, run_name, existing["airport"])

    now = datetime.now(timezone.utc).isoformat()
    existing["run_id"] = run_id
    existing["updated_at"] = now
    lakebase.upsert_simulation_draft(existing)
    _sync_draft_to_delta(existing, user_token)

    logger.info(f"Submitted draft run run_id={run_id}: {run_name} (draft={name})")
    return existing

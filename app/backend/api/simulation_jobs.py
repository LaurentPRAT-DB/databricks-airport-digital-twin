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


def _get_notebook_path() -> str:
    """Derive the workspace path for the simulation runner notebook."""
    ws_path = str(PROJECT_ROOT / "databricks" / "notebooks" / "run_simulation_airport.py")
    if ws_path.startswith("/Workspace"):
        ws_path = ws_path[len("/Workspace"):]
    return ws_path


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

    # Extract airport from run name (format: "Simulation SFO 1000f")
    airport = ""
    if run.run_name and run.run_name.startswith("Simulation "):
        parts = run.run_name.split()
        if len(parts) >= 2:
            airport = parts[1]

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
        scenario_ws_path = str(PROJECT_ROOT / "scenarios" / body.scenario_name)
        if scenario_ws_path.startswith("/Workspace"):
            scenario_ws_path = scenario_ws_path[len("/Workspace"):]
        params["scenario_file"] = scenario_ws_path
    elif body.custom_scenario:
        vol_path = _write_custom_scenario_to_volume(body.custom_scenario, user_token)
        if not vol_path:
            raise HTTPException(status_code=500, detail="Failed to write custom scenario to Volume")
        params["scenario_file"] = vol_path

    total_flights = body.arrivals + body.departures
    run_name = f"Simulation {body.airport} {total_flights}f"

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

    logger.info(f"Submitted simulation job run_id={run_id}: {run_name}")
    return {"run_id": run_id, "run_name": run_name}


@simulation_jobs_router.get("/jobs")
async def list_simulation_jobs(request: Request):
    """List recent simulation runs (SUBMIT_RUN type, last 20)."""
    from databricks.sdk.service.jobs import RunType

    user_token = _extract_user_token(request)

    def _list(w):
        runs = list(w.jobs.list_runs(
            run_type=RunType.SUBMIT_RUN,
            expand_tasks=False,
            limit=20,
        ))
        return [
            _format_run(r)
            for r in runs
            if r.run_name and r.run_name.startswith("Simulation ")
        ]

    jobs = _sdk_call(_list, user_token, timeout=15)
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
    if not scenarios_dir.is_dir():
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

    return {"scenarios": results}

"""LLM-powered simulation report generator.

Produces a narrative markdown report from simulation output (KPIs, weather, events)
using a configurable prompt template and Databricks Foundation Model endpoint.
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_PROMPT_FILE = Path(__file__).parent.parent.parent / "prompts" / "simulation_report.md"
MODEL_ENDPOINT = os.getenv("ASSISTANT_MODEL_ENDPOINT", "databricks-claude-sonnet-4-5")
MAX_TOKENS = 4096
TEMPERATURE = 0.3


def _load_prompt_template(
    prompt_template: str | None = None,
    prompt_file: str | None = None,
) -> str:
    """Load prompt template with priority: explicit string > explicit file > default file."""
    if prompt_template:
        return prompt_template
    if prompt_file:
        path = Path(prompt_file)
        if not path.is_file():
            raise FileNotFoundError(f"Report prompt file not found: {prompt_file}")
        return path.read_text(encoding="utf-8")
    if DEFAULT_PROMPT_FILE.is_file():
        return DEFAULT_PROMPT_FILE.read_text(encoding="utf-8")
    raise FileNotFoundError(f"Default prompt template not found at {DEFAULT_PROMPT_FILE}")


def _format_kpis(summary: dict[str, Any]) -> str:
    """Format KPI summary as readable text."""
    lines = [
        f"- On-time performance: {summary.get('on_time_pct', '--')}%",
        f"- Average schedule delay: {summary.get('schedule_delay_min', '--')} min",
        f"- Average capacity hold: {summary.get('avg_capacity_hold_min', '--')} min",
        f"- Maximum capacity hold: {summary.get('max_capacity_hold_min', '--')} min",
        f"- Cancellation rate: {summary.get('cancellation_rate_pct', '--')}%",
        f"- Total flights: {summary.get('total_flights', '--')} ({summary.get('arrivals', '--')} arr / {summary.get('departures', '--')} dep)",
        f"- Spawned: {summary.get('spawned_count', '--')}/{summary.get('total_flights', '--')}",
        f"- Peak simultaneous flights: {summary.get('peak_simultaneous_flights', '--')}",
        f"- Gates used: {summary.get('gate_utilization_gates_used', '--')}",
        f"- Average turnaround: {summary.get('avg_turnaround_min', '--')} min",
        f"- Go-arounds: {summary.get('total_go_arounds', 0)}",
        f"- Diversions: {summary.get('total_diversions', 0)}",
        f"- Holdings: {summary.get('total_holdings', 0)}",
        f"- Cancellations (scenario): {summary.get('total_cancellations', 0)}",
    ]
    return "\n".join(lines)


def _format_weather_timeline(weather_snapshots: list[dict[str, Any]]) -> str:
    """Format weather snapshots as a chronological timeline."""
    if not weather_snapshots:
        return "No weather events recorded."
    lines = []
    for w in weather_snapshots:
        time_str = w.get("time", "")
        try:
            t = datetime.fromisoformat(time_str)
            time_fmt = t.strftime("%H:%M UTC")
        except (ValueError, TypeError):
            time_fmt = time_str
        weather_type = w.get("type", "unknown")
        severity = w.get("severity", "")
        vis = w.get("visibility_nm")
        ceil = w.get("ceiling_ft")
        wind = w.get("wind_speed_kt")
        gusts = w.get("wind_gusts_kt")
        parts = [f"{time_fmt}: {severity} {weather_type}"]
        if vis is not None:
            parts.append(f"vis {vis}nm")
        if ceil is not None:
            parts.append(f"ceiling {ceil}ft")
        if wind is not None:
            wind_str = f"wind {wind}kt"
            if gusts:
                wind_str += f" gusting {gusts}kt"
            parts.append(wind_str)
        duration = w.get("duration_hours")
        if duration:
            parts.append(f"duration {duration}h")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def _format_scenario_events(scenario_events: list[dict[str, Any]], limit: int = 50) -> str:
    """Format key scenario events as a timeline."""
    if not scenario_events:
        return "No scenario events recorded."
    lines = []
    for e in scenario_events[:limit]:
        time_str = e.get("time", "")
        try:
            t = datetime.fromisoformat(time_str)
            time_fmt = t.strftime("%H:%M UTC")
        except (ValueError, TypeError):
            time_fmt = time_str
        event_type = e.get("event_type", "")
        description = e.get("description", "")
        lines.append(f"- [{time_fmt}] ({event_type}) {description}")
    if len(scenario_events) > limit:
        lines.append(f"... and {len(scenario_events) - limit} more events")
    return "\n".join(lines)


def _format_schedule_summary(schedule: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    """Format flight schedule summary."""
    total = summary.get("total_flights", 0)
    arr = summary.get("arrivals", 0)
    dep = summary.get("departures", 0)
    lines = [
        f"- Total scheduled: {total} flights ({arr} arrivals, {dep} departures)",
        f"- Peak simultaneous: {summary.get('peak_simultaneous_flights', '--')} flights",
    ]
    if schedule:
        delayed = sum(1 for f in schedule if f.get("delay_minutes", 0) > 0)
        lines.append(f"- Flights with schedule delay: {delayed}/{total}")
        types = {}
        for f in schedule:
            ac = f.get("aircraft_type", "unknown")
            types[ac] = types.get(ac, 0) + 1
        if types:
            top_types = sorted(types.items(), key=lambda x: -x[1])[:5]
            lines.append(f"- Aircraft mix: {', '.join(f'{t}({c})' for t, c in top_types)}")
    return "\n".join(lines)


def _render_prompt(
    template: str,
    simulation_output: dict[str, Any],
) -> str:
    """Render the prompt template with simulation data."""
    config = simulation_output.get("config", {})
    summary = simulation_output.get("summary", {})
    weather = simulation_output.get("weather_snapshots", [])
    events = simulation_output.get("scenario_events", [])
    schedule = simulation_output.get("schedule", [])

    variables = {
        "airport": config.get("airport", "Unknown"),
        "scenario_name": summary.get("scenario_name") or "Standard Operations",
        "scenario_description": config.get("scenario_description", "No scenario description provided."),
        "duration_hours": config.get("duration_hours", "N/A"),
        "start_date": config.get("start_date") or config.get("start_time", "Not specified"),
        "kpis_json": _format_kpis(summary),
        "weather_timeline": _format_weather_timeline(weather),
        "scenario_events": _format_scenario_events(events),
        "flight_schedule_summary": _format_schedule_summary(schedule, summary),
    }

    try:
        return template.format(**variables)
    except KeyError as e:
        logger.warning(f"Prompt template has unknown variable: {e}")
        for key in variables:
            template = template.replace(f"{{{key}}}", variables[key] if isinstance(variables[key], str) else str(variables[key]))
        return template


async def _call_llm(host: str, token: str, messages: list[dict]) -> str:
    """Call the FM endpoint and return the response text."""
    url = f"{host}/serving-endpoints/{MODEL_ENDPOINT}/invocations"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "messages": messages,
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, headers=headers, json=payload)

    if resp.status_code >= 400:
        detail = resp.text[:500]
        logger.error(f"Report LLM call failed ({resp.status_code}): {detail}")
        raise RuntimeError(f"LLM endpoint error ({resp.status_code}): {detail}")

    data = resp.json()
    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError("LLM returned no choices")
    return choices[0].get("message", {}).get("content", "")


class ReportGenerator:
    """Generates narrative markdown reports from simulation output using an LLM."""

    def __init__(
        self,
        prompt_template: str | None = None,
        prompt_file: str | None = None,
    ):
        self._template = _load_prompt_template(prompt_template, prompt_file)

    async def generate(
        self,
        simulation_output: dict[str, Any],
        host: str,
        token: str,
    ) -> str:
        """Generate a markdown report from simulation output."""
        rendered_prompt = _render_prompt(self._template, simulation_output)
        messages = [
            {"role": "user", "content": rendered_prompt},
        ]
        logger.info(f"Generating report for {simulation_output.get('config', {}).get('airport', '?')}...")
        report = await _call_llm(host, token, messages)
        logger.info(f"Report generated: {len(report)} chars")
        return report

    def generate_sync(
        self,
        simulation_output: dict[str, Any],
        host: str,
        token: str,
    ) -> str:
        """Synchronous wrapper for CLI usage."""
        return asyncio.run(self.generate(simulation_output, host, token))


def get_databricks_auth() -> tuple[str, str]:
    """Get Databricks host and token for CLI usage (from SDK config or env vars)."""
    host = os.getenv("DATABRICKS_HOST", "")
    token = os.getenv("DATABRICKS_TOKEN", "")

    if host and token:
        if not host.startswith("http"):
            host = f"https://{host}"
        return host, token

    try:
        from databricks.sdk.core import Config
        cfg = Config()
        host = cfg.host or host
        if not host.startswith("http"):
            host = f"https://{host}"
        token = cfg.token
        if token:
            return host, token
        headers = cfg.authenticate()
        auth = headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return host, auth[len("Bearer "):]
    except Exception as e:
        logger.debug(f"SDK auth failed: {e}")

    raise RuntimeError(
        "No Databricks authentication available. "
        "Set DATABRICKS_HOST + DATABRICKS_TOKEN or configure databricks-cli."
    )


def derive_report_path(simulation_output_path: str) -> str:
    """Derive the REPORT_*.md path from a simulation output JSON path."""
    p = Path(simulation_output_path)
    base = p.stem
    if base.startswith("simulation_"):
        report_name = "REPORT_" + base[len("simulation_"):] + ".md"
    else:
        report_name = "REPORT_" + base + ".md"
    return str(p.parent / report_name)

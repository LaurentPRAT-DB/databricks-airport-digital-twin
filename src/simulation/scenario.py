"""Scenario models and YAML loader for composable disruption injection."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Union

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class WeatherEvent(BaseModel):
    """A weather disruption event."""

    time: str  # "HH:MM" within sim day
    type: str  # thunderstorm | fog | snow | wind_shift | clear | sandstorm | dust | smoke | haze | rain | freezing_rain | ice_pellets
    severity: str  # light | moderate | severe
    duration_hours: float
    visibility_nm: float | None = None
    ceiling_ft: int | None = None
    wind_speed_kt: int | None = None
    wind_gusts_kt: int | None = None
    wind_direction: int | None = None


class RunwayEvent(BaseModel):
    """A runway closure or configuration change."""

    time: str
    type: str  # closure | config_change | reopen
    runway: str | None = None
    runway_config: str | None = None
    duration_minutes: int | None = None
    reason: str | None = None


class GroundEvent(BaseModel):
    """A ground-side disruption (gate failure, taxiway closure, etc.)."""

    time: str
    type: str  # gate_failure | taxiway_closure | fuel_shortage | deicing_required
    target: str | None = None
    duration_hours: float = 1.0
    impact: dict | None = None


class CurfewEvent(BaseModel):
    """A noise curfew restricting operations during certain hours.

    Real-world examples: SYD 23:00-06:00, NRT 23:00-06:00, FRA 23:00-05:00.
    During curfew, no departures and severely limited arrivals (emergency only).
    """

    start: str  # "HH:MM" — curfew begins
    end: str    # "HH:MM" — curfew ends
    allow_emergency_arrivals: bool = True  # Allow a trickle of arrivals
    max_arrivals_per_hour: int = 2  # Emergency-only arrival rate during curfew


class TrafficModifier(BaseModel):
    """A traffic injection event (surge, diversion, cancellation, ground stop)."""

    time: str | None = None
    time_range: list[str] | None = None
    type: str  # surge | diversion | cancellation | ground_stop
    extra_arrivals: int = 0
    extra_departures: int = 0
    diversion_origin: str | None = None
    duration_hours: float | None = None  # For ground_stop: how long it lasts


class SimulationScenario(BaseModel):
    """Top-level scenario definition with composable disruption events."""

    name: str
    description: str = ""
    base_config: str | None = None
    weather_events: list[WeatherEvent] = Field(default_factory=list)
    runway_events: list[RunwayEvent] = Field(default_factory=list)
    ground_events: list[GroundEvent] = Field(default_factory=list)
    curfew_events: list[CurfewEvent] = Field(default_factory=list)
    traffic_modifiers: list[TrafficModifier] = Field(default_factory=list)


@dataclass
class ResolvedEvent:
    """A scenario event resolved to an absolute datetime."""

    time: datetime
    event_type: str  # "weather", "runway", "ground", "traffic"
    event: Union[WeatherEvent, RunwayEvent, GroundEvent, TrafficModifier]
    description: str


def load_scenario(path: str) -> SimulationScenario:
    """Load a scenario from a YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return SimulationScenario(**data)


def _parse_hhmm(time_str: str, base_date: datetime) -> datetime:
    """Convert 'HH:MM' to absolute datetime using base_date's date.

    Supports hours >= 24 for multi-day scenarios (e.g. '25:30' = 01:30 next day,
    '36:00' = 12:00 next day). This follows the aviation convention where
    schedules extending past midnight use 24+ hour notation.
    """
    h, m = map(int, time_str.split(":"))
    extra_days = h // 24
    h = h % 24
    result = base_date.replace(hour=h, minute=m, second=0, microsecond=0)
    if extra_days:
        result += timedelta(days=extra_days)
    return result


def _describe_weather(e: WeatherEvent) -> str:
    parts = [f"{e.severity} {e.type}"]
    if e.visibility_nm is not None:
        parts.append(f"vis {e.visibility_nm}nm")
    if e.ceiling_ft is not None:
        parts.append(f"ceil {e.ceiling_ft}ft")
    if e.wind_gusts_kt is not None:
        parts.append(f"gusts {e.wind_gusts_kt}kt")
    parts.append(f"for {e.duration_hours}h")
    return "Weather: " + ", ".join(parts)


def _describe_runway(e: RunwayEvent) -> str:
    if e.type == "closure":
        dur = f" for {e.duration_minutes}min" if e.duration_minutes else ""
        reason = f" ({e.reason})" if e.reason else ""
        return f"Runway {e.runway} closed{dur}{reason}"
    elif e.type == "reopen":
        return f"Runway {e.runway} reopened"
    else:
        return f"Runway config change: {e.runway_config}" + (f" ({e.reason})" if e.reason else "")


def _describe_ground(e: GroundEvent) -> str:
    target = f" {e.target}" if e.target else ""
    return f"Ground: {e.type}{target} for {e.duration_hours}h"


def _describe_traffic(e: TrafficModifier) -> str:
    parts = [f"Traffic: {e.type}"]
    if e.extra_arrivals:
        parts.append(f"+{e.extra_arrivals} arr")
    if e.extra_departures:
        parts.append(f"+{e.extra_departures} dep")
    if e.diversion_origin:
        parts.append(f"from {e.diversion_origin}")
    return ", ".join(parts)


def resolve_times(
    scenario: SimulationScenario, sim_start: datetime
) -> list[ResolvedEvent]:
    """Convert all scenario events to absolute datetimes, sorted chronologically."""
    resolved: list[ResolvedEvent] = []

    for e in scenario.weather_events:
        resolved.append(ResolvedEvent(
            time=_parse_hhmm(e.time, sim_start),
            event_type="weather",
            event=e,
            description=_describe_weather(e),
        ))

    for e in scenario.runway_events:
        resolved.append(ResolvedEvent(
            time=_parse_hhmm(e.time, sim_start),
            event_type="runway",
            event=e,
            description=_describe_runway(e),
        ))

    for e in scenario.ground_events:
        resolved.append(ResolvedEvent(
            time=_parse_hhmm(e.time, sim_start),
            event_type="ground",
            event=e,
            description=_describe_ground(e),
        ))

    for e in scenario.traffic_modifiers:
        if e.time:
            t = _parse_hhmm(e.time, sim_start)
        elif e.time_range and len(e.time_range) >= 1:
            t = _parse_hhmm(e.time_range[0], sim_start)
        else:
            continue  # global modifier, no specific trigger time
        resolved.append(ResolvedEvent(
            time=t,
            event_type="traffic",
            event=e,
            description=_describe_traffic(e),
        ))

    resolved.sort(key=lambda r: r.time)
    return resolved

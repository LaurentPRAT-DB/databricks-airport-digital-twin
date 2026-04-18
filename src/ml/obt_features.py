"""Feature extraction for Off-Block Time (OBT) prediction.

Predicts AOBT — the actual timestamp when an aircraft pushes back from
the gate.  The target is expressed as departure_offset_min = AOBT - SOBT,
i.e. how many minutes early (negative) or late (positive) the pushback
occurs relative to the scheduled off-block time.

This is distinct from the turnaround model which predicts the duration
of the gate stay (AOBT - AIBT).  The OBT model incorporates schedule
context, arrival delay propagation, and operational factors to predict
the absolute pushback time.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.ml.turnaround_features import (
    _load_sim_json_lightweight,
    classify_aircraft,
    is_hub_connection,
    _gate_prefix,
    _is_remote_stand,
    _cyclical_hour,
    _is_international_route,
    _find_nearest_weather,
    _has_ground_stop,
    _count_concurrent_gate_ops,
    _parse_iso,
)

logger = logging.getLogger(__name__)

DEPARTURE_OFFSET_MIN_BOUND = -30.0
DEPARTURE_OFFSET_MAX_BOUND = 120.0


@dataclass
class OBTFeatureSet:
    """Feature vector for OBT (Off-Block Time) prediction at T-park horizon.

    Available once the aircraft has parked and the turnaround has begun.
    The target is departure_offset_min = (AOBT - SOBT) in minutes.
    """

    scheduled_departure_hour: int
    scheduled_turnaround_min: float
    arrival_delay_min: float
    aircraft_category: str
    airline_code: str
    is_international: bool
    is_hub_connecting: bool
    gate_id_prefix: str
    is_remote_stand: bool
    concurrent_gate_ops: int
    airport_code: str
    hour_of_day: int
    day_of_week: int
    hour_sin: float
    hour_cos: float
    wind_speed_kt: float
    visibility_sm: float
    has_active_ground_stop: bool
    turnaround_predicted_min: float = 0.0


@dataclass
class OBTCoarseFeatureSet:
    """Feature vector for T-schedule OBT prediction (hours before departure).

    Only schedule + historical patterns available at this horizon.
    """

    scheduled_departure_hour: int
    aircraft_category: str
    airline_code: str
    is_international: bool
    is_hub_connecting: bool
    airport_code: str
    day_of_week: int
    hour_sin: float
    hour_cos: float
    wind_speed_kt: float
    visibility_sm: float
    has_active_ground_stop: bool


def extract_obt_training_data(sim_json_path: str | Path) -> List[Dict[str, Any]]:
    """Extract OBT training data from a simulation JSON file.

    Joins schedule (for SOBT) + phase_transitions (for AIBT and AOBT) +
    gate_events + weather to produce (features, departure_offset_min) pairs.

    The target is: departure_offset_min = (pushback_time - scheduled_time)
    in minutes.  Positive = late pushback, negative = early.

    Only departure flights with both a schedule entry and parked→pushback
    transition are included.
    """
    path = Path(sim_json_path)
    data = _load_sim_json_lightweight(path)

    schedule = data.get("schedule", [])
    phase_transitions = data.get("phase_transitions", [])
    gate_events = data.get("gate_events", [])
    weather_snapshots = data.get("weather_snapshots", [])
    scenario_events = data.get("scenario_events", [])
    config = data.get("config", {})
    airport_iata = config.get("airport", "")

    gate_events_sorted = sorted(gate_events, key=lambda e: e["time"])

    departure_schedule: Dict[str, Dict[str, Any]] = {}
    for s in schedule:
        if s.get("flight_type") == "departure":
            departure_schedule[s["flight_number"]] = s

    parked_transitions: Dict[str, Dict[str, Any]] = {}
    pushback_transitions: Dict[str, Dict[str, Any]] = {}
    for pt in phase_transitions:
        if pt["to_phase"] == "parked":
            parked_transitions[pt["icao24"]] = pt
        if pt["from_phase"] == "parked" and pt["to_phase"] == "pushback":
            pushback_transitions[pt["icao24"]] = pt

    gate_assignments: Dict[str, str] = {}
    for ge in gate_events:
        if ge["event_type"] in ("assign", "occupy"):
            gate_assignments[ge["icao24"]] = ge["gate"]

    usable = set(parked_transitions.keys()) & set(pushback_transitions.keys())

    results = []
    for icao24 in usable:
        parked_pt = parked_transitions[icao24]
        pushback_pt = pushback_transitions[icao24]

        callsign = parked_pt.get("callsign", "")
        sched = departure_schedule.get(callsign)
        if not sched:
            continue

        sched_time_str = sched.get("scheduled_time", "")
        if not sched_time_str:
            continue

        parked_time = _parse_iso(parked_pt["time"])
        pushback_time = _parse_iso(pushback_pt["time"])
        scheduled_time = _parse_iso(sched_time_str)

        departure_offset_min = (pushback_time - scheduled_time).total_seconds() / 60.0

        if departure_offset_min < DEPARTURE_OFFSET_MIN_BOUND or departure_offset_min > DEPARTURE_OFFSET_MAX_BOUND:
            continue

        scheduled_turnaround_min = (scheduled_time - parked_time).total_seconds() / 60.0
        arrival_delay = float(sched.get("delay_minutes", 0) or 0)

        aircraft_type = parked_pt.get("aircraft_type") or sched.get("aircraft_type", "A320")
        airline_code = sched.get("airline_code", callsign[:3] if len(callsign) >= 3 else "UNK")

        gate_id = gate_assignments.get(icao24, parked_pt.get("assigned_gate", ""))
        origin = sched.get("origin", "")
        destination = sched.get("destination", "")
        is_intl = _is_international_route(origin, destination, airport_iata)

        weather = _find_nearest_weather(weather_snapshots, parked_time)
        wind_speed = float(weather.get("wind_speed_kts", 0) or 0)
        visibility = float(weather.get("visibility_sm", 10.0) or 10.0)
        ground_stop = _has_ground_stop(scenario_events, parked_time, pushback_time)
        concurrent_ops = _count_concurrent_gate_ops(gate_events_sorted, parked_time, icao24)

        h_sin, h_cos = _cyclical_hour(parked_time.hour)

        features = OBTFeatureSet(
            scheduled_departure_hour=scheduled_time.hour,
            scheduled_turnaround_min=max(0.0, min(300.0, scheduled_turnaround_min)),
            arrival_delay_min=arrival_delay,
            aircraft_category=classify_aircraft(aircraft_type),
            airline_code=airline_code,
            is_international=is_intl,
            is_hub_connecting=is_hub_connection(airline_code, airport_iata),
            gate_id_prefix=_gate_prefix(gate_id),
            is_remote_stand=_is_remote_stand(gate_id),
            concurrent_gate_ops=concurrent_ops,
            airport_code=airport_iata,
            hour_of_day=parked_time.hour,
            day_of_week=parked_time.weekday(),
            hour_sin=h_sin,
            hour_cos=h_cos,
            wind_speed_kt=wind_speed,
            visibility_sm=visibility,
            has_active_ground_stop=ground_stop,
        )

        results.append({
            "features": asdict(features),
            "target": round(departure_offset_min, 2),
            "airport": airport_iata,
            "flight_id": icao24,
            "callsign": callsign,
            "sobt": sched_time_str,
            "aobt": pushback_pt["time"],
        })

    logger.info(
        "Extracted %d OBT training samples from %s (airport=%s)",
        len(results), path.name, airport_iata,
    )
    return results

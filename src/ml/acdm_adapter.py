"""A-CDM (Airport Collaborative Decision Making) data adapter.

Maps A-CDM milestones (AIBT, AOBT, SOBT, TOBT, EOBT, etc.) to the
OBT feature set used by the simulation-trained model.  This adapter
is the first step toward fine-tuning the synthetic model on real
operational data.

A-CDM reference milestones:
- SIBT: Scheduled In-Block Time
- AIBT: Actual In-Block Time (= parked_time)
- SOBT: Scheduled Off-Block Time (= scheduled departure)
- TOBT: Target Off-Block Time (airline's own estimate)
- EOBT: Estimated Off-Block Time (CDM system estimate)
- AOBT: Actual Off-Block Time (= pushback_time = target)
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.ml.obt_features import (
    OBTFeatureSet,
    classify_aircraft,
    _gate_prefix,
    _is_remote_stand,
    _cyclical_hour,
    _is_international_route,
)

logger = logging.getLogger(__name__)


def acdm_record_to_features(
    record: Dict[str, Any],
    airport_iata: str,
) -> Optional[tuple[OBTFeatureSet, float]]:
    """Convert a single A-CDM record to (OBTFeatureSet, target_turnaround_min).

    Expected record keys (all timestamps as ISO strings or datetime):
        - aibt: Actual In-Block Time (required)
        - aobt: Actual Off-Block Time (required — this is the target)
        - sobt: Scheduled Off-Block Time
        - aircraft_type: ICAO type designator (e.g. "A320")
        - airline_code: 3-letter ICAO airline code
        - gate: Gate identifier
        - origin: Origin IATA code
        - destination: Destination IATA code
        - arrival_delay_min: Inbound delay (optional, default 0)
        - wind_speed_kts: Weather at gate time (optional)
        - visibility_sm: Weather at gate time (optional)
        - concurrent_ops: Number of concurrent gate operations (optional)
        - has_ground_stop: Whether a GDP/GS was active (optional)

    Returns:
        Tuple of (OBTFeatureSet, turnaround_minutes) or None if invalid.
    """
    try:
        aibt = _to_datetime(record["aibt"])
        aobt = _to_datetime(record["aobt"])
    except (KeyError, ValueError, TypeError) as e:
        logger.debug("Skipping A-CDM record — missing/invalid timestamps: %s", e)
        return None

    turnaround_min = (aobt - aibt).total_seconds() / 60.0
    if turnaround_min < 10 or turnaround_min > 180:
        return None

    aircraft_type = record.get("aircraft_type", "A320")
    airline_code = record.get("airline_code", "UNK")
    gate_id = record.get("gate", "")
    origin = record.get("origin", "")
    destination = record.get("destination", "")

    sobt = _to_datetime(record.get("sobt")) if record.get("sobt") else None
    scheduled_dep_hour = sobt.hour if sobt else aobt.hour
    scheduled_buffer = 0.0
    if sobt:
        scheduled_buffer = max(-60.0, min(300.0, (sobt - aibt).total_seconds() / 60.0))

    h_sin, h_cos = _cyclical_hour(aibt.hour)

    features = OBTFeatureSet(
        aircraft_category=classify_aircraft(aircraft_type),
        airline_code=airline_code,
        hour_of_day=aibt.hour,
        is_international=_is_international_route(origin, destination, airport_iata),
        arrival_delay_min=float(record.get("arrival_delay_min", 0)),
        gate_id_prefix=_gate_prefix(gate_id),
        is_remote_stand=_is_remote_stand(gate_id),
        concurrent_gate_ops=int(record.get("concurrent_ops", 0)),
        wind_speed_kt=float(record.get("wind_speed_kts", 0)),
        visibility_sm=float(record.get("visibility_sm", 10.0)),
        has_active_ground_stop=bool(record.get("has_ground_stop", False)),
        scheduled_departure_hour=scheduled_dep_hour,
        airport_code=airport_iata,
        day_of_week=aibt.weekday(),
        hour_sin=h_sin,
        hour_cos=h_cos,
        is_weather_scenario=False,  # real data, not a sim scenario
        scheduled_buffer_min=scheduled_buffer,
    )
    return features, turnaround_min


def convert_acdm_dataset(
    records: List[Dict[str, Any]],
    airport_iata: str,
) -> tuple[List[OBTFeatureSet], List[float]]:
    """Convert a batch of A-CDM records to training-ready features + targets."""
    features: List[OBTFeatureSet] = []
    targets: List[float] = []
    skipped = 0

    for rec in records:
        result = acdm_record_to_features(rec, airport_iata)
        if result is None:
            skipped += 1
            continue
        feat, target = result
        features.append(feat)
        targets.append(target)

    logger.info(
        "Converted %d A-CDM records to OBT features (%d skipped)",
        len(features), skipped,
    )
    return features, targets


def _to_datetime(val: Any) -> datetime:
    """Coerce string or datetime to datetime."""
    if isinstance(val, datetime):
        return val
    return datetime.fromisoformat(str(val))

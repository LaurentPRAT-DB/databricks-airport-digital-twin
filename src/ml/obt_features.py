"""Feature extraction for Off-Block Time (OBT) prediction.

Extracts training features and targets from simulation JSON files.
Each simulation contains schedule, phase_transitions, gate_events,
weather_snapshots, and scenario_events that are joined to produce
feature vectors for turnaround duration prediction.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OurAirports-based IATA → country lookup (lazy-loaded singleton)
# ---------------------------------------------------------------------------
_OURAIRPORTS_CSV = Path(__file__).resolve().parent.parent.parent / "data" / "calibration" / "airports.csv"
_iata_country_cache: Optional[Dict[str, str]] = None


def _load_iata_country_lookup() -> Dict[str, str]:
    """Build IATA→country mapping from OurAirports CSV.

    Falls back to the hardcoded _AIRPORT_COUNTRY dict if the CSV is not
    available.  Result is cached at module level.
    """
    global _iata_country_cache
    if _iata_country_cache is not None:
        return _iata_country_cache

    if _OURAIRPORTS_CSV.exists():
        try:
            from src.calibration.ourairports_ingest import parse_airports_csv

            airports = parse_airports_csv(_OURAIRPORTS_CSV)
            lookup: Dict[str, str] = {}
            for info in airports.values():
                iata = info.get("iata", "").strip().upper()
                country = info.get("country", "").strip().upper()
                if iata and country:
                    lookup[iata] = country
            _iata_country_cache = lookup
            logger.info("Loaded %d IATA→country mappings from OurAirports CSV", len(lookup))
            return _iata_country_cache
        except Exception as exc:
            logger.warning("Failed to load OurAirports CSV, using fallback: %s", exc)

    # Fallback: use the small hardcoded dict (converted into the cache)
    _iata_country_cache = dict(_AIRPORT_COUNTRY)
    return _iata_country_cache


def _get_country(iata: str) -> str:
    """Look up the ISO country code for an IATA airport code.

    Tries the OurAirports-backed cache first, then falls back to the
    hardcoded _AIRPORT_COUNTRY dict.
    """
    lookup = _load_iata_country_lookup()
    return lookup.get(iata.upper(), "")


# Aircraft type -> category mapping
WIDE_BODY_TYPES = frozenset([
    "A330", "A340", "A350", "A380",
    "B747", "B767", "B777", "B787",
])
REGIONAL_TYPES = frozenset([
    "E170", "E175", "E190", "E195",
    "CRJ2", "CRJ7", "CRJ9", "CR2", "CR7", "CR9",
    "ATR", "AT72", "AT76", "DH8D", "DH8A",
])

# Turnaround duration bounds (minutes) for filtering outliers
MIN_TURNAROUND_MIN = 10.0
MAX_TURNAROUND_MIN = 180.0

# Country lookup for international detection (reused from fallback.py)
_AIRPORT_COUNTRY: Dict[str, str] = {
    "SFO": "US", "LAX": "US", "ORD": "US", "DFW": "US", "JFK": "US",
    "ATL": "US", "DEN": "US", "SEA": "US", "BOS": "US", "PHX": "US",
    "LAS": "US", "MCO": "US", "MIA": "US", "CLT": "US", "MSP": "US",
    "DTW": "US", "EWR": "US", "PHL": "US", "IAH": "US", "SAN": "US",
    "PDX": "US",
    "LHR": "GB", "CDG": "FR", "FRA": "DE", "AMS": "NL",
    "HKG": "HK", "NRT": "JP", "HND": "JP", "SIN": "SG", "SYD": "AU",
    "DXB": "AE", "ICN": "KR", "GRU": "BR", "JNB": "ZA",
}


@dataclass
class OBTCoarseFeatureSet:
    """Feature vector for T-90 (pre-arrival) OBT prediction.

    Contains only features knowable 90 minutes before scheduled departure:
    schedule data, inbound delay estimate, and current weather/ops status.
    Gate-side features (gate prefix, remote stand, concurrent ops, parking
    hour) are NOT available at this horizon.
    """

    aircraft_category: str        # "narrow", "wide", "regional"
    airline_code: str
    scheduled_departure_hour: int  # 0-23
    is_international: bool
    arrival_delay_min: float
    wind_speed_kt: float
    visibility_sm: float
    has_active_ground_stop: bool
    # New features
    airport_code: str             # 3-letter IATA
    day_of_week: int              # 0=Monday, 6=Sunday
    hour_sin: float               # sin(2*pi*hour/24) — cyclical encoding
    hour_cos: float               # cos(2*pi*hour/24)
    is_weather_scenario: bool     # True if simulation used a scenario file
    scheduled_buffer_min: float = 0.0  # SOBT - SIBT (schedule-only at T-90)
    is_hub_connecting: bool = False  # True when airline's hub matches airport


@dataclass
class OBTFeatureSet:
    """Feature vector for T-park (refined) OBT turnaround duration prediction.

    Full feature set available once the aircraft is parked at the gate.
    """

    aircraft_category: str        # "narrow", "wide", "regional"
    airline_code: str
    hour_of_day: int              # 0-23, hour the aircraft parked
    is_international: bool
    arrival_delay_min: float
    gate_id_prefix: str           # first letter(s) of gate ID (terminal area)
    is_remote_stand: bool
    concurrent_gate_ops: int
    wind_speed_kt: float
    visibility_sm: float
    has_active_ground_stop: bool
    scheduled_departure_hour: int  # 0-23
    # New features
    airport_code: str             # 3-letter IATA
    day_of_week: int              # 0=Monday, 6=Sunday
    hour_sin: float               # sin(2*pi*hour/24) — cyclical encoding
    hour_cos: float               # cos(2*pi*hour/24)
    is_weather_scenario: bool     # True if simulation used a scenario file
    scheduled_buffer_min: float = 0.0  # scheduled_departure - actual_arrival (T-park)
    is_hub_connecting: bool = False  # True when airline's hub matches airport

    def to_coarse(self) -> OBTCoarseFeatureSet:
        """Project full feature set down to T-90 coarse features."""
        return OBTCoarseFeatureSet(
            aircraft_category=self.aircraft_category,
            airline_code=self.airline_code,
            scheduled_departure_hour=self.scheduled_departure_hour,
            is_international=self.is_international,
            arrival_delay_min=self.arrival_delay_min,
            wind_speed_kt=self.wind_speed_kt,
            visibility_sm=self.visibility_sm,
            has_active_ground_stop=self.has_active_ground_stop,
            airport_code=self.airport_code,
            day_of_week=self.day_of_week,
            hour_sin=self.hour_sin,
            hour_cos=self.hour_cos,
            is_weather_scenario=self.is_weather_scenario,
            scheduled_buffer_min=self.scheduled_buffer_min,
            is_hub_connecting=self.is_hub_connecting,
        )

    def to_board(
        self,
        elapsed_gate_time_min: float,
        tpark_predicted_min: float,
    ) -> "OBTBoardFeatureSet":
        """Extend to T-board features once boarding has started."""
        total = max(tpark_predicted_min, 1.0)
        progress = min(1.0, elapsed_gate_time_min / total)
        remaining = max(0.0, tpark_predicted_min - elapsed_gate_time_min)
        return OBTBoardFeatureSet(
            **{k: getattr(self, k) for k in OBTFeatureSet.__dataclass_fields__},
            elapsed_gate_time_min=elapsed_gate_time_min,
            remaining_predicted_min=remaining,
            turnaround_progress_pct=progress,
        )


@dataclass
class OBTBoardFeatureSet(OBTFeatureSet):
    """Feature vector for T-board (boarding start) OBT prediction.

    Extends T-park features with elapsed time at the gate and progress
    information.  The T-board model is triggered when ~70% of the
    predicted turnaround has elapsed.
    """

    elapsed_gate_time_min: float = 0.0
    remaining_predicted_min: float = 0.0
    turnaround_progress_pct: float = 0.0


# Airline ICAO code → hub IATA codes lookup
_AIRLINE_HUBS: Dict[str, frozenset] = {
    "UAL": frozenset({"SFO", "ORD", "IAH", "EWR", "DEN", "IAD", "LAX"}),
    "AAL": frozenset({"DFW", "CLT", "MIA", "PHX", "PHL", "ORD", "LAX"}),
    "DAL": frozenset({"ATL", "MSP", "DTW", "SLC", "SEA", "JFK", "LAX", "BOS"}),
    "SWA": frozenset({"DAL", "MDW", "BWI", "DEN", "LAS", "OAK"}),
    "DLH": frozenset({"FRA", "MUC"}),
    "BAW": frozenset({"LHR", "LGW"}),
    "AFR": frozenset({"CDG", "ORY"}),
    "KLM": frozenset({"AMS"}),
    "SIA": frozenset({"SIN"}),
    "CPA": frozenset({"HKG"}),
    "ANA": frozenset({"NRT", "HND"}),
    "JAL": frozenset({"NRT", "HND"}),
    "KAL": frozenset({"ICN"}),
    "UAE": frozenset({"DXB"}),
    "QFA": frozenset({"SYD", "MEL"}),
    "THY": frozenset({"IST"}),
}


def is_hub_connection(airline_code: str, airport_iata: str) -> bool:
    """Check if the airline operates this airport as a hub."""
    hubs = _AIRLINE_HUBS.get(airline_code.upper(), frozenset())
    return airport_iata.upper() in hubs


def classify_aircraft(aircraft_type: str) -> str:
    """Map aircraft type code to category.

    >>> classify_aircraft("B738")
    'narrow'
    >>> classify_aircraft("B777")
    'wide'
    >>> classify_aircraft("E190")
    'regional'
    """
    # Normalize: strip trailing digits for family matching
    base = aircraft_type.upper().rstrip("0123456789") if aircraft_type else ""
    full = aircraft_type.upper() if aircraft_type else ""

    if full in WIDE_BODY_TYPES or base in {"A33", "A34", "A35", "A38", "B74", "B76", "B77", "B78"}:
        return "wide"
    if full in REGIONAL_TYPES or base in {"E17", "E19", "CRJ", "ATR", "AT7", "DH8"}:
        return "regional"
    return "narrow"


def _gate_prefix(gate_id: str) -> str:
    """Extract terminal prefix from gate ID (e.g. 'B2' -> 'B', 'T1-12' -> 'T1')."""
    if not gate_id:
        return "UNK"
    # Take leading alpha characters
    prefix = ""
    for ch in gate_id:
        if ch.isalpha():
            prefix += ch
        else:
            break
    return prefix if prefix else gate_id[0]


def _is_remote_stand(gate_id: str) -> bool:
    """Remote stands typically have 'R' prefix or high numeric IDs."""
    if not gate_id:
        return False
    return gate_id.upper().startswith("R") or gate_id.upper().startswith("REM")


def _parse_iso(ts: str) -> datetime:
    """Parse ISO timestamp string to datetime."""
    return datetime.fromisoformat(ts)


def _cyclical_hour(hour: int) -> tuple[float, float]:
    """Encode hour as cyclical sin/cos so 23 and 0 are adjacent."""
    rad = 2.0 * math.pi * hour / 24.0
    return round(math.sin(rad), 6), round(math.cos(rad), 6)


def _is_international_route(origin: str, destination: str, airport_iata: str) -> bool:
    """Determine if a flight is international using country lookup.

    Uses the OurAirports-backed IATA→country lookup (60K+ airports) when
    available, falling back to the hardcoded dict.  Returns False when
    either airport is unknown.
    """
    if not origin or not destination:
        return False
    airport_country = _get_country(airport_iata)
    other = destination if origin.upper() == airport_iata.upper() else origin
    other_country = _get_country(other)
    if not airport_country or not other_country:
        return False
    return airport_country != other_country


def _find_nearest_weather(
    weather_snapshots: List[Dict[str, Any]],
    target_time: datetime,
) -> Dict[str, Any]:
    """Find the weather snapshot closest to target_time."""
    if not weather_snapshots:
        return {"wind_speed_kts": 0.0, "visibility_sm": 10.0}

    best = weather_snapshots[0]
    best_diff = abs((_parse_iso(best["time"]) - target_time).total_seconds())

    for ws in weather_snapshots[1:]:
        diff = abs((_parse_iso(ws["time"]) - target_time).total_seconds())
        if diff < best_diff:
            best = ws
            best_diff = diff

    return best


def _has_ground_stop(
    scenario_events: List[Dict[str, Any]],
    start_time: datetime,
    end_time: datetime,
) -> bool:
    """Check if any ground stop event was active during [start_time, end_time]."""
    for event in scenario_events:
        if event.get("event_type") != "ground":
            continue
        event_time = _parse_iso(event["time"])
        if start_time <= event_time <= end_time:
            return True
    return False


def _count_concurrent_gate_ops(
    gate_events: List[Dict[str, Any]],
    target_time: datetime,
    exclude_icao24: str,
) -> int:
    """Count how many other aircraft are at gates at target_time.

    Tracks occupy/release events to determine who is at a gate.
    """
    # Build occupancy state at target_time
    occupied: Dict[str, str] = {}  # gate -> icao24

    for event in gate_events:
        event_time = _parse_iso(event["time"])
        if event_time > target_time:
            break

        gate = event["gate"]
        icao24 = event["icao24"]
        etype = event["event_type"]

        if etype == "occupy":
            occupied[gate] = icao24
        elif etype == "release":
            if gate in occupied and occupied[gate] == icao24:
                del occupied[gate]

    # Count others (exclude our flight)
    return sum(1 for v in occupied.values() if v != exclude_icao24)


def extract_training_data(sim_json_path: str | Path) -> List[Dict[str, Any]]:
    """Parse a simulation JSON file and return (features, target) pairs.

    Joins schedule + phase_transitions + gate_events + weather + scenario_events
    to produce training samples for turnaround duration prediction.

    Args:
        sim_json_path: Path to simulation JSON file.

    Returns:
        List of dicts, each with 'features' (OBTFeatureSet as dict) and
        'target' (turnaround_duration_min as float).
    """
    path = Path(sim_json_path)
    with open(path) as f:
        data = json.load(f)

    schedule = data.get("schedule", [])
    phase_transitions = data.get("phase_transitions", [])
    gate_events = data.get("gate_events", [])
    weather_snapshots = data.get("weather_snapshots", [])
    scenario_events = data.get("scenario_events", [])
    config = data.get("config", {})
    airport_iata = config.get("airport", "")
    is_weather_scenario = bool(config.get("scenario_file"))

    # Sort gate events by time for concurrent counting
    gate_events_sorted = sorted(gate_events, key=lambda e: e["time"])

    # Build lookup: icao24 -> schedule entry
    # Schedule uses flight_number as callsign linkage
    schedule_by_callsign: Dict[str, Dict[str, Any]] = {}
    for s in schedule:
        schedule_by_callsign[s["flight_number"]] = s

    # Build parked and pushback times from phase_transitions
    parked_transitions: Dict[str, Dict[str, Any]] = {}  # icao24 -> transition
    pushback_transitions: Dict[str, Dict[str, Any]] = {}

    for pt in phase_transitions:
        if pt["to_phase"] == "parked":
            parked_transitions[pt["icao24"]] = pt
        if pt["from_phase"] == "parked" and pt["to_phase"] == "pushback":
            pushback_transitions[pt["icao24"]] = pt

    # Build gate assignments: icao24 -> gate from gate_events
    gate_assignments: Dict[str, str] = {}
    for ge in gate_events:
        if ge["event_type"] in ("assign", "occupy"):
            gate_assignments[ge["icao24"]] = ge["gate"]

    # Find usable flights (have both parked and pushback transitions)
    usable_icao24s = set(parked_transitions.keys()) & set(pushback_transitions.keys())

    results = []
    for icao24 in usable_icao24s:
        parked_pt = parked_transitions[icao24]
        pushback_pt = pushback_transitions[icao24]

        parked_time = _parse_iso(parked_pt["time"])
        pushback_time = _parse_iso(pushback_pt["time"])

        # Calculate turnaround duration
        turnaround_min = (pushback_time - parked_time).total_seconds() / 60.0

        # Filter outliers
        if turnaround_min < MIN_TURNAROUND_MIN or turnaround_min > MAX_TURNAROUND_MIN:
            continue

        # Find schedule entry via callsign
        callsign = parked_pt.get("callsign", "")
        sched = schedule_by_callsign.get(callsign, {})

        # Aircraft category
        aircraft_type = parked_pt.get("aircraft_type") or sched.get("aircraft_type", "A320")
        aircraft_category = classify_aircraft(aircraft_type)

        # Airline code
        airline_code = sched.get("airline_code", callsign[:3] if len(callsign) >= 3 else "UNK")

        # Gate info
        gate_id = gate_assignments.get(icao24, parked_pt.get("assigned_gate", ""))
        gate_pfx = _gate_prefix(gate_id)
        is_remote = _is_remote_stand(gate_id)

        # International check — country-based
        origin = sched.get("origin", "")
        destination = sched.get("destination", "")
        is_intl = _is_international_route(origin, destination, airport_iata)

        # Arrival delay
        arrival_delay = float(sched.get("delay_minutes", 0) or 0)

        # Scheduled departure hour
        sched_time_str = sched.get("scheduled_time", "")
        if sched_time_str:
            sched_dt = _parse_iso(sched_time_str)
            scheduled_dep_hour = sched_dt.hour
        else:
            scheduled_dep_hour = parked_time.hour

        # Weather at parking time
        weather = _find_nearest_weather(weather_snapshots, parked_time)
        wind_speed = float(weather.get("wind_speed_kts", 0) or 0)
        visibility = float(weather.get("visibility_sm", 10.0) or 10.0)

        # Ground stop during turnaround
        ground_stop = _has_ground_stop(scenario_events, parked_time, pushback_time)

        # Concurrent gate operations
        concurrent_ops = _count_concurrent_gate_ops(
            gate_events_sorted, parked_time, icao24
        )

        # Cyclical hour encoding
        h_sin, h_cos = _cyclical_hour(parked_time.hour)

        # Scheduled buffer: time between scheduled departure and actual arrival
        scheduled_buffer = 0.0
        if sched_time_str:
            sched_dt = _parse_iso(sched_time_str)
            scheduled_buffer = (sched_dt - parked_time).total_seconds() / 60.0
            # Clamp to reasonable range (negative = already late)
            scheduled_buffer = max(-60.0, min(300.0, scheduled_buffer))

        # Hub connection check
        hub_connecting = is_hub_connection(airline_code, airport_iata)

        features = OBTFeatureSet(
            aircraft_category=aircraft_category,
            airline_code=airline_code,
            hour_of_day=parked_time.hour,
            is_international=is_intl,
            arrival_delay_min=arrival_delay,
            gate_id_prefix=gate_pfx,
            is_remote_stand=is_remote,
            concurrent_gate_ops=concurrent_ops,
            wind_speed_kt=wind_speed,
            visibility_sm=visibility,
            has_active_ground_stop=ground_stop,
            scheduled_departure_hour=scheduled_dep_hour,
            airport_code=airport_iata,
            day_of_week=parked_time.weekday(),
            hour_sin=h_sin,
            hour_cos=h_cos,
            is_weather_scenario=is_weather_scenario,
            scheduled_buffer_min=scheduled_buffer,
            is_hub_connecting=hub_connecting,
        )

        results.append({
            "features": asdict(features),
            "target": turnaround_min,
            "airport": airport_iata,
            "flight_id": icao24,
            "callsign": callsign,
        })

    logger.info(
        f"Extracted {len(results)} OBT training samples from {path.name} "
        f"(airport={airport_iata})"
    )
    return results

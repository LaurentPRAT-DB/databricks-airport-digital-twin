"""Synthetic flight data generator with realistic stateful movements.

Generates persistent flight states with realistic behaviors:
- Landing approach and touchdown with proper separation
- Taxi from runway to gate
- Parked at gate
- Pushback and taxi to runway
- Takeoff and departure climb

Aircraft Separation Standards (FAA/ICAO):
- Approach: 3-6 NM minimum depending on wake turbulence category
- Runway: Only one aircraft at a time
- Taxi: ~150-300 ft minimum visual separation
- Gate: Aircraft dimensions + safety buffer
"""

import logging
import math
import random
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

from src.simulation.diagnostics import diag_log

from src.simulation.openap_profiles import (
    get_descent_profile,
    get_climb_profile,
    interpolate_profile,
)
from faker import Faker

from src.ml.gse_model import get_turnaround_timing, get_aircraft_category, PHASE_DEPENDENCIES


fake = Faker()


def _sanitize_float(val: float, default: float = 0.0) -> float:
    """Replace NaN/Inf with a safe default."""
    if val is None or math.isnan(val) or math.isinf(val):
        return default
    return val


# ============================================================================
# AIRLINE TURNAROUND SPEED FACTORS
# ============================================================================
# 1.0 = standard, <1.0 = faster turnaround, >1.0 = slower turnaround.
# Based on industry data: LCCs target 25-30 min turns, full-service 45-90 min,
# Gulf/Asian premium carriers add 5-15% for extra catering/cleaning.

AIRLINE_TURNAROUND_FACTOR: Dict[str, float] = {
    # US low-cost carriers — fast turns
    "SWA": 0.72,   # Southwest: 25-min target, industry fastest
    "FFT": 0.78,   # Frontier: ULCC, minimal service
    "NKS": 0.78,   # Spirit: ULCC
    "JBU": 0.88,   # JetBlue: midway LCC/legacy
    # US legacy carriers — standard
    "UAL": 1.0, "DAL": 1.0, "AAL": 1.0,
    # US regional — slightly faster
    "ASA": 0.92, "SKW": 0.90, "RPA": 0.90, "ENY": 0.90,
    # European LCCs — very fast
    "RYR": 0.70,   # Ryanair: 25-min target
    "EZY": 0.75,   # easyJet: 30-min target
    # European legacy
    "BAW": 1.05, "DLH": 1.05, "AFR": 1.05, "KLM": 1.0,
    # Gulf carriers — premium service, longer turns
    "UAE": 1.15, "QTR": 1.12, "ETD": 1.10,
    # Asian carriers — premium service
    "SIA": 1.10, "CPA": 1.08, "ANA": 1.05, "JAL": 1.05, "KAL": 1.05,
    "CZ": 1.0,     # China Southern
    # Latin American
    "AMX": 1.0, "MXA": 1.0,
    # Hawaiian
    "HAL": 0.95,
}
_DEFAULT_AIRLINE_FACTOR = 1.0

# Calibration override: when set (> 0), the physics turnaround uses this
# median gate time (in minutes) from BTS OTP data instead of the GSE model's
# nominal timing.  The simulation engine populates this from the airport profile.
_calibration_gate_minutes: float = 0.0


def set_calibration_gate_minutes(minutes: float) -> None:
    """Set calibrated median gate turnaround time (minutes). 0 disables."""
    global _calibration_gate_minutes
    _calibration_gate_minutes = minutes


# Calibration: BTS taxi-out mean time in seconds.  When set (> 0), the
# taxi_to_runway phase adds a departure-queue hold so total taxi-out duration
# (waypoint travel + hold) matches the real-world BTS mean.
_calibration_taxi_out_target_s: float = 0.0
# Estimated seconds the waypoint path alone takes (set once per airport).
_calibration_taxi_out_waypoint_s: float = 0.0


def set_calibration_taxi_out(mean_minutes: float, waypoint_travel_s: float = 180.0) -> None:
    """Set calibrated taxi-out target from BTS OTP data.

    Args:
        mean_minutes: BTS mean taxi-out time in minutes (e.g. 20.1 for SFO).
        waypoint_travel_s: estimated seconds the sim's waypoint path takes
            without any hold (default 180s ~ 3 min at 25 kts over 5 waypoints).
    """
    global _calibration_taxi_out_target_s, _calibration_taxi_out_waypoint_s
    _calibration_taxi_out_target_s = mean_minutes * 60.0
    _calibration_taxi_out_waypoint_s = waypoint_travel_s


# ============================================================================
# WEATHER STATE — updated by simulation engine each weather tick
# ============================================================================

_current_weather: Dict[str, float] = {"wind_speed_kts": 0.0, "visibility_sm": 10.0}


def set_current_weather(wind_speed_kts: float, visibility_sm: float) -> None:
    """Called by simulation engine after each weather update."""
    _current_weather["wind_speed_kts"] = wind_speed_kts
    _current_weather["visibility_sm"] = visibility_sm


def _get_turnaround_weather_factor() -> float:
    """Weather impact on ground handling operations.

    High winds slow fueling/cargo; low visibility slows ramp movement.
    """
    factor = 1.0
    wind = _current_weather.get("wind_speed_kts", 0.0)
    vis = _current_weather.get("visibility_sm", 10.0)

    if wind > 50:
        factor += 0.25
    elif wind > 35:
        factor += 0.15
    elif wind > 25:
        factor += 0.05

    if vis < 0.5:
        factor += 0.15
    elif vis < 1.0:
        factor += 0.10
    elif vis < 3.0:
        factor += 0.05

    return factor


def _get_turnaround_congestion_factor() -> float:
    """More concurrent gate ops = longer turnaround due to crew contention."""
    _init_gate_states()
    occupied = sum(1 for gs in _gate_states.values() if gs.occupied_by is not None)
    return 1.0 + 0.01 * max(0, occupied - 10)


def _get_turnaround_day_of_week_factor() -> float:
    """Weekend turnarounds are ~5% slower (fewer ground crew on roster)."""
    dow = datetime.now(timezone.utc).weekday()
    if dow >= 5:  # Saturday or Sunday
        return 1.05
    return 1.0


def _get_turnaround_international_factor(state: "FlightState") -> float:
    """International flights have longer turnarounds (+25%)."""
    origin = state.origin_airport or ""
    dest = state.destination_airport or ""
    local = get_current_airport_iata()
    other = dest if origin == local else origin
    if _is_international_airport(other):
        return 1.25
    return 1.0

# ============================================================================
# GATE-KEYED INBOUND DELAY TRACKING (for reactionary delay prediction)
# ============================================================================

_gate_last_delay: Dict[str, float] = {}


def get_gate_last_delay(gate_id: str) -> float:
    """Return the delay of the last inbound flight at this gate (minutes)."""
    return _gate_last_delay.get(gate_id, 0.0)


def get_airport_load_ratio() -> float:
    """Return current airport load ratio: active flights / nominal capacity.

    Uses the target flight count as nominal capacity (the count parameter
    from generate_synthetic_flights, typically 50).
    """
    active = len(_flight_states)
    # Default capacity is the target flight count (50)
    capacity = max(1, 50)
    return active / capacity


# ============================================================================
# EVENT BUFFERS for ML training data persistence
# ============================================================================
# Thread-safe buffers that collect events during state machine updates.
# Drained periodically by DataGeneratorService for Lakebase persistence.

_MAX_BUFFER_SIZE = 10000  # Cap to prevent unbounded memory growth

_phase_transition_buffer: List[Dict[str, Any]] = []
_phase_transition_lock = threading.Lock()

_gate_event_buffer: List[Dict[str, Any]] = []
_gate_event_lock = threading.Lock()

_prediction_buffer: List[Dict[str, Any]] = []
_prediction_lock = threading.Lock()

_turnaround_event_buffer: List[Dict[str, Any]] = []
_turnaround_event_lock = threading.Lock()


# When True, emit_phase_transition() skips buffering because the
# simulation engine records transitions directly via the recorder.
# This prevents duplicate phase transition entries (defect D05).
_suppress_phase_transition_emit: bool = False


def set_suppress_phase_transitions(suppress: bool) -> None:
    """Enable/disable phase transition buffering (used by simulation engine)."""
    global _suppress_phase_transition_emit
    _suppress_phase_transition_emit = suppress


def emit_phase_transition(
    icao24: str,
    callsign: str,
    from_phase: str,
    to_phase: str,
    latitude: float,
    longitude: float,
    altitude: float,
    aircraft_type: str = "A320",
    assigned_gate: Optional[str] = None,
) -> None:
    """Record a flight phase transition event."""
    # Skip buffering when the simulation engine records transitions directly
    if _suppress_phase_transition_emit:
        return

    event = {
        "icao24": icao24,
        "callsign": callsign,
        "from_phase": from_phase,
        "to_phase": to_phase,
        "latitude": latitude,
        "longitude": longitude,
        "altitude": altitude,
        "aircraft_type": aircraft_type,
        "assigned_gate": assigned_gate,
        "event_time": datetime.now(timezone.utc).isoformat(),
    }
    with _phase_transition_lock:
        _phase_transition_buffer.append(event)
        if len(_phase_transition_buffer) > _MAX_BUFFER_SIZE:
            del _phase_transition_buffer[: _MAX_BUFFER_SIZE // 2]

    diag_log(
        "PHASE_TRANSITION", datetime.now(timezone.utc),
        icao24=icao24, callsign=callsign,
        from_phase=from_phase, to_phase=to_phase,
        alt=altitude, vel=0,
    )


def emit_gate_event(
    icao24: str,
    callsign: str,
    gate: str,
    event_type: str,  # "assign", "occupy", "release"
    aircraft_type: str = "A320",
) -> None:
    """Record a gate assignment/release event."""
    event = {
        "icao24": icao24,
        "callsign": callsign,
        "gate": gate,
        "event_type": event_type,
        "aircraft_type": aircraft_type,
        "event_time": datetime.now(timezone.utc).isoformat(),
    }
    with _gate_event_lock:
        _gate_event_buffer.append(event)
        if len(_gate_event_buffer) > _MAX_BUFFER_SIZE:
            del _gate_event_buffer[: _MAX_BUFFER_SIZE // 2]


def emit_prediction(
    prediction_type: str,  # "delay", "congestion", "gate_recommendation"
    icao24: Optional[str],
    result: Dict[str, Any],
) -> None:
    """Record an ML prediction result for feedback/evaluation."""
    event = {
        "prediction_type": prediction_type,
        "icao24": icao24,
        "result_json": result,
        "event_time": datetime.now(timezone.utc).isoformat(),
    }
    with _prediction_lock:
        _prediction_buffer.append(event)
        if len(_prediction_buffer) > _MAX_BUFFER_SIZE:
            del _prediction_buffer[: _MAX_BUFFER_SIZE // 2]


def drain_phase_transitions() -> List[Dict[str, Any]]:
    """Drain and return all buffered phase transition events."""
    with _phase_transition_lock:
        events = list(_phase_transition_buffer)
        _phase_transition_buffer.clear()
    return events


def drain_gate_events() -> List[Dict[str, Any]]:
    """Drain and return all buffered gate events."""
    with _gate_event_lock:
        events = list(_gate_event_buffer)
        _gate_event_buffer.clear()
    return events


def drain_predictions() -> List[Dict[str, Any]]:
    """Drain and return all buffered prediction events."""
    with _prediction_lock:
        events = list(_prediction_buffer)
        _prediction_buffer.clear()
    return events


def emit_turnaround_event(
    icao24: str,
    callsign: str,
    gate: str,
    phase: str,
    event_type: str,  # "phase_start" or "phase_complete"
    aircraft_type: str = "A320",
) -> None:
    """Record a turnaround sub-phase event."""
    event = {
        "icao24": icao24,
        "callsign": callsign,
        "gate": gate,
        "turnaround_phase": phase,
        "event_type": event_type,
        "aircraft_type": aircraft_type,
        "event_time": datetime.now(timezone.utc).isoformat(),
    }
    with _turnaround_event_lock:
        _turnaround_event_buffer.append(event)
        if len(_turnaround_event_buffer) > _MAX_BUFFER_SIZE:
            del _turnaround_event_buffer[: _MAX_BUFFER_SIZE // 2]


def drain_turnaround_events() -> List[Dict[str, Any]]:
    """Drain and return all buffered turnaround events."""
    with _turnaround_event_lock:
        events = list(_turnaround_event_buffer)
        _turnaround_event_buffer.clear()
    return events


def get_flight_turnaround_info(icao24: str) -> Optional[Dict[str, Any]]:
    """Get turnaround info for a flight from simulation state.

    Returns None if the flight is not found or not in PARKED phase.
    Turnaround data is only meaningful when an aircraft is docked at a gate.
    """
    state = _flight_states.get(icao24)
    if state is None:
        return None
    # Only return turnaround data for aircraft actually parked at a gate
    if state.phase != FlightPhase.PARKED:
        return {
            "parked_since": None,
            "time_at_gate_seconds": 0,
            "assigned_gate": state.assigned_gate,
            "aircraft_type": state.aircraft_type,
            "callsign": state.callsign,
            "phase": state.phase.value,
            "turnaround_phase": "",
            "turnaround_schedule": None,
        }
    return {
        "parked_since": datetime.fromtimestamp(state.parked_since, tz=timezone.utc) if state.parked_since > 0 else None,
        "time_at_gate_seconds": state.time_at_gate,
        "assigned_gate": state.assigned_gate,
        "aircraft_type": state.aircraft_type,
        "callsign": state.callsign,
        "phase": state.phase.value,
        "turnaround_phase": state.turnaround_phase,
        "turnaround_schedule": state.turnaround_schedule,
    }


def get_current_flight_states() -> List[Dict[str, Any]]:
    """Snapshot current flight states for persistence."""
    snapshots = []
    for icao24, state in _flight_states.items():
        snapshots.append({
            "icao24": icao24,
            "callsign": state.callsign,
            "latitude": state.latitude,
            "longitude": state.longitude,
            "altitude": state.altitude,
            "velocity": 0 if state.phase == FlightPhase.PARKED else state.velocity,
            "heading": state.heading,
            "vertical_rate": state.vertical_rate,
            "on_ground": state.on_ground,
            "flight_phase": state.phase.value,
            "aircraft_type": state.aircraft_type,
            "assigned_gate": state.assigned_gate,
            "origin_airport": state.origin_airport,
            "destination_airport": state.destination_airport,
            "snapshot_time": datetime.now(timezone.utc).isoformat(),
        })
    return snapshots


# Callsign prefix → airline name mapping (must match AIRLINE_FLEET keys)
_AIRLINE_NAMES = {
    # ICAO codes (3-letter)
    "UAL": "United Airlines",
    "DAL": "Delta Air Lines",
    "AAL": "American Airlines",
    "SWA": "Southwest Airlines",
    "JBU": "JetBlue Airways",
    "ASA": "Alaska Airlines",
    "UAE": "Emirates",
    "AFR": "Air France",
    "CPA": "Cathay Pacific",
    "CSN": "China Southern",
    "HAL": "Hawaiian Airlines",
    "ACA": "Air Canada",
    "MXA": "Mexicana",
    "QFA": "Qantas",
    "ANA": "All Nippon Airways",
    "BAW": "British Airways",
    "DLH": "Lufthansa",
    "KAL": "Korean Air",
    "JAL": "Japan Airlines",
    "SIA": "Singapore Airlines",
    "THY": "Turkish Airlines",
    "EVA": "EVA Air",
    "CCA": "Air China",
    "SAS": "SAS",
    "ICE": "Icelandair",
    "FIN": "Finnair",
    "TAP": "TAP Portugal",
    "KLM": "KLM Royal Dutch",
    "QTR": "Qatar Airways",
    "ETH": "Ethiopian Airlines",
    "VIR": "Virgin Atlantic",
    "NKS": "Spirit Airlines",
    "FFT": "Frontier Airlines",
    "SKW": "SkyWest Airlines",
    "RPA": "Republic Airways",
    "ENY": "Envoy Air",
    "PDT": "Piedmont Airlines",
    "CPZ": "Compass Airlines",
    "EDV": "Endeavor Air",
    "OTH": "Other",
    # Airlines in AIRLINES dict but previously missing here
    "AAY": "Allegiant Air",
    "AMX": "Aeromexico",
    "ETD": "Etihad Airways",
    "EZY": "easyJet",
    "FDB": "flydubai",
    "RYR": "Ryanair",
    "SAA": "South African Airways",
    "SCX": "Sun Country Airlines",
    "TAM": "LATAM Airlines",
    # Airlines from calibration profiles (known_profiles.py)
    "SKY": "Skymark Airlines",
    "ADO": "Air Do",
    "SFJ": "StarFlyer",
    "CES": "China Eastern Airlines",
    "SNJ": "Solaseed Air",
    "IBX": "IBEX Airlines",
    "AAR": "Asiana Airlines",
    "APJ": "Peach Aviation",
    "AVA": "Avianca",
    "AZU": "Azul Brazilian Airlines",
    "CAW": "Comair",
    "ELY": "El Al",
    "EWG": "Eurowings",
    "FAS": "FlySafair",
    "GAI": "Gol Airlines",
    "GLO": "Gol Linhas Aereas",
    "HDA": "Honda Jet",
    "JJP": "Jetstar Japan",
    "JNA": "JetSMART",
    "JST": "Jetstar Airways",
    "LAN": "LATAM Chile",
    "MAS": "Malaysia Airlines",
    "MNX": "Mango Airlines",
    "SLK": "Silk Air",
    "SPI": "SpiceJet",
    "SUN": "Sun Express",
    "THA": "Thai Airways",
    "TRA": "Transavia",
    "TWB": "T'way Air",
    "VOZ": "Virgin Australia",
    "WJA": "WestJet",
    # IATA codes (2-letter) — some callsigns use these
    "CZ": "China Southern",
    "MU": "China Eastern",
    "CA": "Air China",
    "NH": "All Nippon Airways",
    "JL": "Japan Airlines",
    "KE": "Korean Air",
    "SQ": "Singapore Airlines",
    "TK": "Turkish Airlines",
    "BR": "EVA Air",
    "EK": "Emirates",
    "QR": "Qatar Airways",
    "LH": "Lufthansa",
    "BA": "British Airways",
    "AF": "Air France",
    "AC": "Air Canada",
    "QF": "Qantas",
    "HA": "Hawaiian Airlines",
    "WS": "WestJet",
}


def get_flights_as_schedule() -> List[Dict[str, Any]]:
    """Convert current synthetic flight states into FIDS schedule entries.

    This ensures the FIDS display shows the same flights that are visible
    on the map, rather than independently generated schedule data.

    Returns:
        List of schedule-format dicts compatible with ScheduleService.
    """
    now = datetime.now(timezone.utc)
    schedule = []

    for icao24, state in _flight_states.items():
        callsign = state.callsign.strip() if state.callsign else ""
        airline_code = callsign[:3].upper() if len(callsign) >= 3 else "UAL"
        # Try ICAO 3-letter, then IATA 2-letter prefix
        airline_name = _AIRLINE_NAMES.get(airline_code) or _AIRLINE_NAMES.get(callsign[:2].upper(), airline_code)

        local_iata = get_current_airport_iata()
        origin = state.origin_airport or "???"
        destination = state.destination_airport or local_iata

        # Determine flight type: arrival if destination is local airport
        is_arrival = (destination == local_iata)

        # Guard against self-referencing: arrival origin must not be local airport
        if is_arrival and origin == local_iata:
            origin = _pick_random_origin()
        flight_type = "arrival" if is_arrival else "departure"

        # Map flight phase to FIDS status
        phase = state.phase
        if phase in (FlightPhase.PARKED,):
            if is_arrival:
                status = "arrived"
            elif state.turnaround_phase in ("boarding", "loading", "chocks_off"):
                status = "boarding"
            else:
                status = "scheduled"
        elif phase == FlightPhase.APPROACHING:
            status = "scheduled"  # approaching = not yet arrived, show as upcoming
        elif phase == FlightPhase.LANDING:
            status = "final_call"  # actively landing
        elif phase == FlightPhase.TAXI_TO_GATE:
            status = "arrived"  # on the ground, taxiing in
        elif phase in (FlightPhase.PUSHBACK, FlightPhase.TAXI_TO_RUNWAY):
            status = "gate_closed" if not is_arrival else "on_time"
        elif phase == FlightPhase.TAKEOFF:
            status = "departed"
        elif phase == FlightPhase.DEPARTING:
            status = "departed"
        elif phase == FlightPhase.ENROUTE:
            status = "scheduled" if is_arrival else "departed"
        else:
            status = "on_time"

        # Deterministic per-flight hash for stable FIDS ordering across refreshes.
        # Use a large prime multiplier to spread hash values evenly.
        _h = ((hash(icao24) * 2654435761) ^ hash(airline_code)) & 0xFFFFFFFF

        # Delay jitter: ~20% of flights have 5-45 min delay
        delay_minutes = 0
        if (_h >> 4) % 5 == 0:  # deterministic 20% chance
            delay_minutes = 5 + ((_h >> 8) % 41)  # 5-45 min

        # Compute scheduled times based on actual flight phase and state.
        # Wide modulo ranges prevent clustering on the FIDS display.
        if is_arrival:
            if phase in (FlightPhase.PARKED,):
                # Already arrived: scheduled in the past (5-120 min ago)
                past_offset = 5 + (_h % 115)
                scheduled_time = (now - timedelta(minutes=past_offset)).isoformat()
            elif phase == FlightPhase.TAXI_TO_GATE:
                # Just landed, taxiing in: arrived ~2-8 min ago
                scheduled_time = (now - timedelta(minutes=2 + _h % 6)).isoformat()
            elif phase == FlightPhase.LANDING:
                # Actively landing: ETA is now
                scheduled_time = (now + timedelta(minutes=1 + _h % 3)).isoformat()
            elif phase == FlightPhase.APPROACHING:
                # Use altitude to compute realistic ETA
                descent_rate = 800.0  # ft/min typical descent
                descent_min = state.altitude / descent_rate if state.altitude > 0 else 5.0
                eta_min = max(3, int(descent_min))
                scheduled_time = (now + timedelta(minutes=eta_min)).isoformat()
            elif phase == FlightPhase.ENROUTE:
                # Far out: spread 15-135 min into the future
                scheduled_time = (now + timedelta(minutes=15 + _h % 120)).isoformat()
            else:
                scheduled_time = (now + timedelta(minutes=_h % 90)).isoformat()
        else:
            if phase == FlightPhase.PARKED:
                # Departures waiting: spread 10-120 min into the future
                scheduled_time = (now + timedelta(minutes=10 + _h % 110)).isoformat()
            elif phase in (FlightPhase.PUSHBACK, FlightPhase.TAXI_TO_RUNWAY):
                # About to depart: scheduled 0-5 min ago
                scheduled_time = (now - timedelta(minutes=_h % 5)).isoformat()
            elif phase in (FlightPhase.TAKEOFF, FlightPhase.DEPARTING):
                # Departed: scheduled 5-25 min ago
                scheduled_time = (now - timedelta(minutes=5 + _h % 20)).isoformat()
            else:
                scheduled_time = (now + timedelta(minutes=_h % 90)).isoformat()

        # Compute estimated_time for delayed flights or approaching aircraft
        estimated_time = None
        if delay_minutes > 0:
            sched_dt = datetime.fromisoformat(scheduled_time)
            estimated_time = (sched_dt + timedelta(minutes=delay_minutes)).isoformat()

        schedule.append({
            "flight_number": callsign,
            "airline": airline_name,
            "airline_code": airline_code,
            "origin": origin,
            "destination": destination,
            "scheduled_time": scheduled_time,
            "estimated_time": estimated_time,
            "actual_time": now.isoformat() if status in ("arrived", "departed") else None,
            "gate": state.assigned_gate,
            "status": status,
            "delay_minutes": delay_minutes,
            "delay_reason": "Late arrival" if delay_minutes > 0 and is_arrival else ("Gate hold" if delay_minutes > 0 else None),
            "aircraft_type": state.aircraft_type,
            "flight_type": flight_type,
        })

    return schedule


# ============================================================================
# SEPARATION CONSTANTS (FAA/ICAO Standards)
# ============================================================================

# Wake turbulence categories
WAKE_CATEGORY = {
    "A380": "SUPER",
    "B747": "HEAVY", "B777": "HEAVY", "B787": "HEAVY", "A330": "HEAVY",
    "A340": "HEAVY", "A350": "HEAVY", "A345": "HEAVY",
    "A320": "LARGE", "A321": "LARGE", "A319": "LARGE", "A318": "LARGE",
    "B737": "LARGE", "B738": "LARGE", "B739": "LARGE",
    "CRJ9": "LARGE", "E175": "LARGE", "E190": "LARGE",
}

# Minimum separation in nautical miles (lead aircraft → following aircraft)
WAKE_SEPARATION_NM = {
    ("SUPER", "SUPER"): 4.0,
    ("SUPER", "HEAVY"): 6.0,
    ("SUPER", "LARGE"): 7.0,
    ("SUPER", "SMALL"): 8.0,
    ("HEAVY", "HEAVY"): 4.0,
    ("HEAVY", "LARGE"): 5.0,
    ("HEAVY", "SMALL"): 6.0,
    ("LARGE", "LARGE"): 3.0,
    ("LARGE", "SMALL"): 4.0,
    ("SMALL", "SMALL"): 3.0,
}
DEFAULT_SEPARATION_NM = 3.0

# Taxi speed standards (ICAO Doc 9157 / Annex 14 design speeds)
# 1 knot ≈ 0.5144 m/s; 1° latitude ≈ 111,000 m
_KTS_TO_DEG_PER_SEC = 0.5144 / 111_000  # ~4.63e-6 °/s per knot

TAXI_SPEED_STRAIGHT_KTS = 25    # ICAO standard taxiway design speed
TAXI_SPEED_TURN_KTS = 15        # Reduced speed through turns
TAXI_SPEED_RAMP_KTS = 8         # Near-gate / ramp area
TAXI_SPEED_PUSHBACK_KTS = 3     # Tug-assisted pushback

MAX_SPEED_BELOW_FL100_KTS = 250  # 14 CFR 91.117: 250 kts IAS below 10,000 ft MSL

# ILS Category I decision height (ft AGL) — primary approach→landing trigger
DECISION_HEIGHT_FT = 200
# Stabilized approach gate (ft AGL) — unstabilized above this → go-around
STABILIZED_APPROACH_GATE_FT = 500
STABILIZED_MAX_SPEED_OVER_VREF = 30  # kts above Vref (generous for sim)
STABILIZED_MAX_SINK_RATE = 1500       # fpm (generous — real airlines use 1000)

# Reference approach speeds (Vref) by aircraft type (kts, typical landing weight)
# Sources: manufacturer operating manuals, airline performance data
VREF_SPEEDS = {
    "A318": 125, "A319": 130, "A320": 133, "A321": 138,
    "B737": 130, "B738": 135, "B739": 137,
    "CRJ9": 128, "E175": 126, "E190": 130,
    "A330": 140, "A340": 145, "A345": 145,
    "A350": 142, "B777": 149, "B787": 143,
    "B747": 152, "A380": 145,
    # Fighter jets (Easter egg) — approach at ~150-160 kts
    "F14": 155, "F15": 150, "F16": 148, "F18": 150, "F22": 155, "F35": 152,
}
_DEFAULT_VREF = 135  # A320-class fallback

# Convert NM to degrees (approximate at this latitude)
# 1 NM ≈ 1/60 degree ≈ 0.0167 degrees
NM_TO_DEG = 1.0 / 60.0

# Minimum separation distances
MIN_APPROACH_SEPARATION_DEG = 3.0 * NM_TO_DEG  # 3 NM minimum on approach
MIN_TAXI_SEPARATION_DEG = 0.001  # ~100m for taxi operations (FAA visual separation ~60-90m)
MIN_TAXI_SEPARATION_ARRIVAL_DEG = 0.0006  # ~60m for arriving aircraft (ATC gives inbound priority)
MIN_GATE_SEPARATION_DEG = 0.010  # ~800m in 3D scale for gate area (prevents overlap)
# Aircraft fuselage half-lengths in meters (nose-to-center), by ICAO type designator.
# Used to compute how far to offset parked aircraft from the gate/jetbridge point
# so the fuselage sits on the apron instead of overlapping the terminal building.
# Sources: manufacturer specs (Airbus, Boeing, Bombardier, Embraer).
AIRCRAFT_HALF_LENGTH_M = {
    "A318": 15.6,  # 31.4m total
    "A319": 16.8,  # 33.8m
    "A320": 18.9,  # 37.6m
    "A321": 22.2,  # 44.5m
    "B737": 19.6,  # 39.5m (B737-800 representative)
    "B738": 19.8,  # 39.5m
    "B739": 21.0,  # 42.1m
    "CRJ9": 18.4,  # 36.4m
    "E175": 15.9,  # 31.7m
    "E190": 18.2,  # 36.2m
    "A330": 29.6,  # 58.8m (A330-300)
    "A340": 31.7,  # 63.7m (A340-300)
    "A345": 37.6,  # 75.3m (A340-600)
    "A350": 33.1,  # 66.8m (A350-900)
    "B777": 36.9,  # 73.9m (B777-300)
    "B787": 28.3,  # 56.7m (B787-8)
    "B747": 35.3,  # 70.7m (B747-400)
    "A380": 36.4,  # 72.7m
}
_DEFAULT_HALF_LENGTH_M = 18.9  # A320-class fallback

# ============================================================================
# TAKEOFF PERFORMANCE DATA (14 CFR 25.107 / manufacturer performance manuals)
# ============================================================================
# type: (V1_kts, VR_kts, V2_kts, accel_kts_per_s, initial_climb_fpm)
TAKEOFF_PERFORMANCE = {
    "A318": (125, 130, 135, 3.0, 2500),
    "A319": (128, 133, 138, 2.8, 2400),
    "A320": (130, 135, 140, 2.7, 2300),
    "A321": (135, 140, 145, 2.5, 2200),
    "B737": (128, 133, 138, 2.8, 2500),
    "B738": (132, 137, 142, 2.6, 2300),
    "B739": (134, 139, 144, 2.5, 2200),
    "CRJ9": (120, 125, 130, 3.2, 2800),
    "E175": (118, 123, 128, 3.3, 3000),
    "E190": (122, 127, 132, 3.1, 2700),
    "A330": (140, 145, 150, 2.0, 1800),
    "A340": (145, 150, 155, 1.8, 1600),
    "A345": (145, 150, 155, 1.8, 1600),
    "A350": (138, 143, 148, 2.2, 2000),
    "B777": (142, 147, 152, 2.0, 1900),
    "B787": (138, 143, 148, 2.3, 2100),
    "B747": (150, 155, 160, 1.6, 1500),
    "A380": (150, 155, 165, 1.5, 1400),
}
_DEFAULT_TAKEOFF_PERF = (130, 135, 140, 2.7, 2300)  # A320-class fallback

# Departure wake turbulence separation (FAA 7110.65 5-8-1 / ICAO Doc 4444 6.3.3)
# (leader_category, follower_category) -> minimum seconds
DEPARTURE_SEPARATION_S = {
    ("SUPER", "SUPER"): 180, ("SUPER", "HEAVY"): 180,
    ("SUPER", "LARGE"): 180, ("SUPER", "SMALL"): 180,
    ("HEAVY", "HEAVY"): 120, ("HEAVY", "LARGE"): 120,
    ("HEAVY", "SMALL"): 120, ("LARGE", "SMALL"): 120,
}
DEFAULT_DEPARTURE_SEPARATION_S = 60  # Default same-runway spacing

# Common US airline callsign prefixes with typical aircraft types
AIRLINE_FLEET = {
    "UAL": ["B738", "B739", "A320", "A319", "B777", "B787"],  # United Airlines
    "DAL": ["B738", "B739", "A320", "A321", "A330", "B777"],  # Delta Air Lines
    "AAL": ["B738", "A321", "A320", "B777", "B787"],          # American Airlines
    "SWA": ["B737", "B738"],                                  # Southwest Airlines
    "JBU": ["A320", "A321", "A319"],                          # JetBlue Airways
    "ASA": ["B738", "B739", "A320"],                          # Alaska Airlines
    "UAE": ["A380", "B777", "A345"],                          # Emirates
    "AFR": ["A320", "A318", "A319", "A330"],                  # Air France
    "CPA": ["A330", "B777", "A350"],                          # Cathay Pacific
    # US regional carriers (used as OTH replacements)
    "SKW": ["CRJ9", "E175"],                                   # SkyWest Airlines
    "RPA": ["E175", "A319"],                                    # Republic Airways
    "ENY": ["E175", "CRJ9"],                                    # Envoy Air
    "PDT": ["E175", "CRJ9"],                                    # Piedmont Airlines
    "EDV": ["CRJ9", "E175"],                                    # Endeavor Air
}

CALLSIGN_PREFIXES = list(AIRLINE_FLEET.keys())

# ============================================================================
# AIRPORT GEOMETRY - SFO Coordinates (aligned with frontend maps)
# ============================================================================
# These coordinates MUST match the frontend definitions in:
# - app/frontend/src/constants/airportLayout.ts (2D map)
# - app/frontend/src/constants/airport3D.ts (3D scene)
#
# Coordinate system reference:
# - 2D Map: Direct lat/lon (GeoJSON/Leaflet)
# - 3D Map: Converted via latLonTo3D() with center (37.6213, -122.379), scale 10000
# ============================================================================

# Airport center — dynamic, updated when airport switches
# Default is SFO (matches frontend DEFAULT_CENTER_LAT/LON)
_airport_center = (37.6213, -122.379)
_current_airport_iata = "SFO"

# Keep the constant for backward compatibility in tests
AIRPORT_CENTER = (37.6213, -122.379)


def get_airport_center() -> tuple:
    """Get the current airport center coordinates (lat, lon)."""
    return _airport_center


def get_current_airport_iata() -> str:
    """Get the IATA code of the current airport."""
    return _current_airport_iata


def set_airport_center(lat: float, lon: float, iata: str = "SFO") -> None:
    """Set the current airport center for synthetic flight generation.

    Called when the user switches airports. Updates the center used for
    spawning flights, generating trajectories, and computing bearings.
    """
    global _airport_center, _current_airport_iata
    _airport_center = (lat, lon)
    _current_airport_iata = iata

# Real SFO runway endpoints from FAA Airport/Facility Directory
# These match the frontend airportLayout.ts polygon coordinates
# 4 runways: 28L/10R, 28R/10L (parallel E-W), 01L/19R, 01R/19L (crosswind N-S)

# Runway 28L/10R - 11,381 ft (south parallel, extends into bay)
# Primary landing runway for arrivals from the east
RUNWAY_28L_THRESHOLD = (-122.358349, 37.611712)   # 28L threshold (west end, touchdown)
RUNWAY_10R_THRESHOLD = (-122.393105, 37.626291)   # 10R threshold (east end)

# Runway 28R/10L - 11,870 ft (north parallel, extends into bay)
# Primary departure runway
RUNWAY_28R_THRESHOLD = (-122.357141, 37.613534)   # 28R threshold (west end)
RUNWAY_10L_THRESHOLD = (-122.393392, 37.628739)   # 10L threshold (east end)

# Runway 01L/19R - 7,650 ft (west crosswind)
RUNWAY_01L_THRESHOLD = (-122.381929, 37.607898)   # 01L threshold (south end)
RUNWAY_19R_THRESHOLD = (-122.369609, 37.626481)   # 19R threshold (north end)

# Runway 01R/19L - 8,650 ft (east crosswind)
RUNWAY_01R_THRESHOLD = (-122.380041, 37.606330)   # 01R threshold (south end)
RUNWAY_19L_THRESHOLD = (-122.366111, 37.627342)   # 19L threshold (north end)

# Legacy aliases for backward compatibility
RUNWAY_28L_WEST = RUNWAY_28L_THRESHOLD
RUNWAY_28L_EAST = RUNWAY_10R_THRESHOLD
RUNWAY_28R_WEST = RUNWAY_28R_THRESHOLD
RUNWAY_28R_EAST = RUNWAY_10L_THRESHOLD

# Terminal area - International Terminal (southwest area of airport)
# Matches frontend airportLayout.ts terminal polygon
TERMINAL_CENTER = (37.615, -122.391)

# Gate positions - MUST match frontend airportLayout.ts GATE_POSITIONS
# These are the actual gate locations used in both 2D and 3D visualization
# NOTE: This is the fallback when no OSM data is imported
_DEFAULT_GATES = {
    # International Terminal - Boarding Area G
    "G1": (37.6145, -122.3955),  # Wide-body capable
    "G2": (37.6140, -122.3945),
    "G3": (37.6135, -122.3935),
    "G4": (37.6130, -122.3925),
    # International Terminal - Boarding Area A
    "A1": (37.6155, -122.3900),  # Wide-body capable
    "A2": (37.6150, -122.3890),
    "A3": (37.6145, -122.3880),
    # Domestic Terminal 1 - Boarding Area B
    "B1": (37.6165, -122.3850),
    "B2": (37.6160, -122.3840),
    "B3": (37.6155, -122.3830),
    "B4": (37.6150, -122.3820),
    # Domestic Terminal 2 - Boarding Area C
    "C1": (37.6175, -122.3800),
    "C2": (37.6170, -122.3790),
    "C3": (37.6165, -122.3780),
    # Domestic Terminal 3 - Boarding Area E
    "E1": (37.6180, -122.3760),
    "E2": (37.6175, -122.3750),
    "E3": (37.6170, -122.3740),
    # Domestic Terminal 3 - Boarding Area F
    "F1": (37.6185, -122.3720),
    "F2": (37.6180, -122.3710),
    "F3": (37.6175, -122.3700),
}

# Cache for dynamically loaded gates
_loaded_gates: Optional[Dict[str, tuple]] = None

# Minimum gates to avoid constant saturation with moderate flight counts
MIN_GATES_FOR_OPERATIONS = 15
MAX_OVERFLOW_STANDS = 10  # Maximum dynamically generated remote parking positions


def _generate_overflow_stands(existing_gates: Dict[str, tuple], count: int) -> Dict[str, tuple]:
    """Generate overflow remote parking positions near the airport apron.

    Places stands in a line south of the terminal area, spaced ~100m apart.
    These serve as remote parking when all terminal gates are occupied.
    """
    center = get_airport_center()
    stands = {}
    # Place overflow stands south of terminal area
    base_lat = center[0] - 0.005  # ~500m south of center
    base_lon = center[1]
    spacing = 0.001  # ~100m between stands

    for i in range(min(count, MAX_OVERFLOW_STANDS)):
        ref = f"R{i+1}"  # R for "Remote"
        if ref not in existing_gates:
            stands[ref] = (base_lat, base_lon + (i - count / 2) * spacing)

    return stands


def get_gates() -> Dict[str, tuple]:
    """
    Get gate positions, preferring imported OSM data over defaults.

    Only caches the result once the airport config service reports ready,
    preventing early calls from permanently locking in a partial gate set.
    Generates overflow remote stands if total gates are below the minimum.

    Returns:
        Dictionary mapping gate refs to (latitude, longitude) tuples
    """
    global _loaded_gates

    if _loaded_gates is not None:
        return _loaded_gates

    gates = None

    # Try to load from airport config service
    try:
        from app.backend.services.airport_config_service import get_airport_config_service
        service = get_airport_config_service()
        config = service.get_config()

        osm_gates = config.get("gates", [])
        if osm_gates:
            gates = {}
            for gate in osm_gates:
                ref = gate.get("ref") or gate.get("id")
                geo = gate.get("geo", {})
                lat = geo.get("latitude")
                lon = geo.get("longitude")
                if ref and lat and lon:
                    # Validate gate ID: reject malformed refs
                    ref_str = str(ref)
                    numeric_part = "".join(c for c in ref_str if c.isdigit())
                    if numeric_part and int(numeric_part) > 200:
                        logger.debug(f"Rejected malformed gate ref: {ref_str}")
                        continue
                    gates[ref_str] = (float(lat), float(lon))

            if not gates:
                gates = None
            elif service.config_ready:
                # Only cache when config is fully loaded
                pass  # Will cache below after overflow check
    except ImportError:
        pass
    except Exception:
        pass

    if gates is None:
        gates = dict(_DEFAULT_GATES)

    # Add overflow stands if total gates are below the minimum
    if len(gates) < MIN_GATES_FOR_OPERATIONS:
        overflow = _generate_overflow_stands(gates, MIN_GATES_FOR_OPERATIONS - len(gates))
        gates.update(overflow)

    # Cache only when service is ready
    try:
        from app.backend.services.airport_config_service import get_airport_config_service
        service = get_airport_config_service()
        if service.config_ready:
            _loaded_gates = gates
    except Exception:
        pass

    return gates


def reload_gates() -> Dict[str, tuple]:
    """
    Force reload of gates from airport config service.

    Call this after importing new OSM data to refresh the gate positions.
    Also invalidates the FIDS schedule cache so schedules regenerate with
    the new airport's gate names.

    Returns:
        Updated dictionary mapping gate refs to (latitude, longitude) tuples
    """
    global _loaded_gates, _flight_states
    _loaded_gates = None
    gates = get_gates()
    # Reset gate states and flight states to use new gates
    _reset_gate_states()
    _flight_states.clear()  # Clear flights so they regenerate with new gates
    # Invalidate FIDS schedule cache so it regenerates with the correct gates
    from src.ingestion.schedule_generator import invalidate_schedule_cache
    invalidate_schedule_cache()
    return gates


# Backward compatibility: GATES is now a function call result
# Code using GATES directly will get the default gates
GATES = _DEFAULT_GATES

# ============================================================================
# TAXIWAY WAYPOINTS
# ============================================================================
# Routes from runways to gates, aligned with frontend taxiway definitions
# Coordinates follow actual SFO ground movement paths

# Arrival route: Runway 28L → Terminal gates
# Aircraft land heading west (280°), exit via high-speed taxiway, turn north to terminal
TAXI_WAYPOINTS_ARRIVAL = [
    (-122.370, 37.615),    # High-speed exit from 28L (midpoint rollout)
    (-122.378, 37.616),    # Taxiway Alpha intersection
    (-122.385, 37.617),    # Turn toward terminal complex
    (-122.390, 37.616),    # Terminal apron entry
]

# Departure route: Terminal gates → Runway 28R
# Aircraft push back, taxi south then east to runway 28R for departure
TAXI_WAYPOINTS_DEPARTURE = [
    (-122.390, 37.616),    # Leave terminal apron
    (-122.385, 37.618),    # Taxiway Bravo
    (-122.378, 37.620),    # Join main taxiway
    (-122.370, 37.622),    # Hold short runway 28R
    (-122.360, 37.614),    # Runway 28R entry point
]

# ============================================================================
# ILS APPROACH PATH - Runway 28L
# ============================================================================
# Standard ILS approach from the east over San Francisco Bay
# Runway 28L heading: 284° magnetic (298° true)
# 28L threshold: 37.611712, -122.358349
#
# Approach path angles align aircraft with the extended runway centerline
# The approach course passes over the bay, descending from 6000ft to touchdown

# Calculate approach path aligned with runway centerline
# Runway centerline vector: from 28L threshold toward 10R threshold
_RWY_28L_LAT = 37.611712
_RWY_28L_LON = -122.358349
_RWY_10R_LAT = 37.626291
_RWY_10R_LON = -122.393105

# Approach path extends east from 28L threshold, following the extended centerline
# Each waypoint: (longitude, latitude, altitude_feet)
APPROACH_WAYPOINTS = [
    # Initial approach fix - 15 NM east of threshold (~4770 ft on 3° GS)
    (-122.10, 37.58, 4800),
    (-122.15, 37.588, 3800),
    # Intermediate fix - 10 NM from threshold (~3180 ft on 3° GS)
    (-122.20, 37.595, 3200),
    (-122.24, 37.600, 2500),
    # Final approach fix - 5 NM from threshold (~1590 ft on 3° GS)
    (-122.28, 37.605, 1600),
    (-122.30, 37.607, 1300),
    # Glideslope intercept - 3 NM from threshold (~950 ft on 3° GS)
    (-122.32, 37.608, 950),
    (-122.333, 37.609, 630),
    # Short final - 1 NM from threshold (~318 ft on 3° GS)
    (-122.345, 37.610, 320),
    (-122.352, 37.6109, 160),
    # Runway 28L threshold (50 ft TCH per 14 CFR 97.3)
    (_RWY_28L_LON, _RWY_28L_LAT, 50),
]

# ============================================================================
# DEPARTURE PATH - Runway 28R
# ============================================================================
# Standard departure from runway 28R (north parallel)
# Initial climb on runway heading, then turn per SID

_RWY_28R_LAT = 37.613534
_RWY_28R_LON = -122.357141

DEPARTURE_WAYPOINTS = [
    # Initial climb - runway 28R just after liftoff (~0.5 NM)
    (_RWY_28R_LON + 0.02, _RWY_28R_LAT, 200),
    # Climbing runway heading (~2 NM, 284° true)
    (-122.32, 37.608, 1000),
    # Continue climb over bay (~4 NM)
    (-122.28, 37.60, 2000),
    # Departure fix - climbing to cruise (~10 NM)
    (-122.20, 37.58, 5000),
    # Enroute - over the bay (~15 NM)
    (-122.10, 37.55, 8000),
]

# ============================================================================
# AIRPORT OFFSET — shift SFO coordinates to target airport
# ============================================================================
# In standalone CLI mode (no OSM data), all coordinates are SFO-based.
# apply_airport_offset() shifts them to center on any target airport.

_SFO_CENTER = (37.6213, -122.379)

# Save originals for reset
_ORIG_DEFAULT_GATES = dict(_DEFAULT_GATES)
_ORIG_RUNWAY_28L_THRESHOLD = RUNWAY_28L_THRESHOLD
_ORIG_RUNWAY_10R_THRESHOLD = RUNWAY_10R_THRESHOLD
_ORIG_RUNWAY_28R_THRESHOLD = RUNWAY_28R_THRESHOLD
_ORIG_RUNWAY_10L_THRESHOLD = RUNWAY_10L_THRESHOLD
_ORIG_RUNWAY_01L_THRESHOLD = RUNWAY_01L_THRESHOLD
_ORIG_RUNWAY_19R_THRESHOLD = RUNWAY_19R_THRESHOLD
_ORIG_RUNWAY_01R_THRESHOLD = RUNWAY_01R_THRESHOLD
_ORIG_RUNWAY_19L_THRESHOLD = RUNWAY_19L_THRESHOLD
_ORIG_TERMINAL_CENTER = TERMINAL_CENTER
_ORIG_TAXI_WAYPOINTS_ARRIVAL = list(TAXI_WAYPOINTS_ARRIVAL)
_ORIG_TAXI_WAYPOINTS_DEPARTURE = list(TAXI_WAYPOINTS_DEPARTURE)
_ORIG_APPROACH_WAYPOINTS = list(APPROACH_WAYPOINTS)
_ORIG_DEPARTURE_WAYPOINTS = list(DEPARTURE_WAYPOINTS)
_ORIG_RWY_28L_LAT = _RWY_28L_LAT
_ORIG_RWY_28L_LON = _RWY_28L_LON
_ORIG_RWY_28R_LAT = _RWY_28R_LAT
_ORIG_RWY_28R_LON = _RWY_28R_LON
_ORIG_RWY_10R_LAT = _RWY_10R_LAT
_ORIG_RWY_10R_LON = _RWY_10R_LON


def apply_airport_offset(target_lat: float, target_lon: float) -> None:
    """Offset all hardcoded SFO coordinates to center on the target airport.

    Called by the simulation engine for non-SFO airports in standalone mode
    (no OSM data available). Preserves the realistic relative layout (gate
    spacing, runway angles, taxi routing) while centering at the target airport.
    """
    global _DEFAULT_GATES, GATES
    global RUNWAY_28L_THRESHOLD, RUNWAY_10R_THRESHOLD
    global RUNWAY_28R_THRESHOLD, RUNWAY_10L_THRESHOLD
    global RUNWAY_01L_THRESHOLD, RUNWAY_19R_THRESHOLD
    global RUNWAY_01R_THRESHOLD, RUNWAY_19L_THRESHOLD
    global RUNWAY_28L_WEST, RUNWAY_28L_EAST, RUNWAY_28R_WEST, RUNWAY_28R_EAST
    global TERMINAL_CENTER
    global TAXI_WAYPOINTS_ARRIVAL, TAXI_WAYPOINTS_DEPARTURE
    global APPROACH_WAYPOINTS, DEPARTURE_WAYPOINTS
    global _RWY_28L_LAT, _RWY_28L_LON, _RWY_28R_LAT, _RWY_28R_LON
    global _RWY_10R_LAT, _RWY_10R_LON

    lat_off = target_lat - _SFO_CENTER[0]
    lon_off = target_lon - _SFO_CENTER[1]

    # Gates: {ref: (lat, lon)}
    _DEFAULT_GATES = {k: (v[0] + lat_off, v[1] + lon_off) for k, v in _ORIG_DEFAULT_GATES.items()}
    GATES = _DEFAULT_GATES

    # Runways: (lon, lat)
    RUNWAY_28L_THRESHOLD = (_ORIG_RUNWAY_28L_THRESHOLD[0] + lon_off, _ORIG_RUNWAY_28L_THRESHOLD[1] + lat_off)
    RUNWAY_10R_THRESHOLD = (_ORIG_RUNWAY_10R_THRESHOLD[0] + lon_off, _ORIG_RUNWAY_10R_THRESHOLD[1] + lat_off)
    RUNWAY_28R_THRESHOLD = (_ORIG_RUNWAY_28R_THRESHOLD[0] + lon_off, _ORIG_RUNWAY_28R_THRESHOLD[1] + lat_off)
    RUNWAY_10L_THRESHOLD = (_ORIG_RUNWAY_10L_THRESHOLD[0] + lon_off, _ORIG_RUNWAY_10L_THRESHOLD[1] + lat_off)
    RUNWAY_01L_THRESHOLD = (_ORIG_RUNWAY_01L_THRESHOLD[0] + lon_off, _ORIG_RUNWAY_01L_THRESHOLD[1] + lat_off)
    RUNWAY_19R_THRESHOLD = (_ORIG_RUNWAY_19R_THRESHOLD[0] + lon_off, _ORIG_RUNWAY_19R_THRESHOLD[1] + lat_off)
    RUNWAY_01R_THRESHOLD = (_ORIG_RUNWAY_01R_THRESHOLD[0] + lon_off, _ORIG_RUNWAY_01R_THRESHOLD[1] + lat_off)
    RUNWAY_19L_THRESHOLD = (_ORIG_RUNWAY_19L_THRESHOLD[0] + lon_off, _ORIG_RUNWAY_19L_THRESHOLD[1] + lat_off)

    # Legacy aliases
    RUNWAY_28L_WEST = RUNWAY_28L_THRESHOLD
    RUNWAY_28L_EAST = RUNWAY_10R_THRESHOLD
    RUNWAY_28R_WEST = RUNWAY_28R_THRESHOLD
    RUNWAY_28R_EAST = RUNWAY_10L_THRESHOLD

    # Terminal center: (lat, lon)
    TERMINAL_CENTER = (_ORIG_TERMINAL_CENTER[0] + lat_off, _ORIG_TERMINAL_CENTER[1] + lon_off)

    # Taxi waypoints: [(lon, lat), ...]
    TAXI_WAYPOINTS_ARRIVAL = [(wp[0] + lon_off, wp[1] + lat_off) for wp in _ORIG_TAXI_WAYPOINTS_ARRIVAL]
    TAXI_WAYPOINTS_DEPARTURE = [(wp[0] + lon_off, wp[1] + lat_off) for wp in _ORIG_TAXI_WAYPOINTS_DEPARTURE]

    # Approach/departure: [(lon, lat, alt), ...]
    APPROACH_WAYPOINTS = [(wp[0] + lon_off, wp[1] + lat_off, wp[2]) for wp in _ORIG_APPROACH_WAYPOINTS]
    DEPARTURE_WAYPOINTS = [(wp[0] + lon_off, wp[1] + lat_off, wp[2]) for wp in _ORIG_DEPARTURE_WAYPOINTS]

    # Individual runway coordinate floats
    _RWY_28L_LAT = _ORIG_RWY_28L_LAT + lat_off
    _RWY_28L_LON = _ORIG_RWY_28L_LON + lon_off
    _RWY_28R_LAT = _ORIG_RWY_28R_LAT + lat_off
    _RWY_28R_LON = _ORIG_RWY_28R_LON + lon_off
    _RWY_10R_LAT = _ORIG_RWY_10R_LAT + lat_off
    _RWY_10R_LON = _ORIG_RWY_10R_LON + lon_off


def reset_airport_offset() -> None:
    """Restore all coordinates to their original SFO values.

    Called for test isolation and when switching back to SFO.
    """
    global _DEFAULT_GATES, GATES
    global RUNWAY_28L_THRESHOLD, RUNWAY_10R_THRESHOLD
    global RUNWAY_28R_THRESHOLD, RUNWAY_10L_THRESHOLD
    global RUNWAY_01L_THRESHOLD, RUNWAY_19R_THRESHOLD
    global RUNWAY_01R_THRESHOLD, RUNWAY_19L_THRESHOLD
    global RUNWAY_28L_WEST, RUNWAY_28L_EAST, RUNWAY_28R_WEST, RUNWAY_28R_EAST
    global TERMINAL_CENTER
    global TAXI_WAYPOINTS_ARRIVAL, TAXI_WAYPOINTS_DEPARTURE
    global APPROACH_WAYPOINTS, DEPARTURE_WAYPOINTS
    global _RWY_28L_LAT, _RWY_28L_LON, _RWY_28R_LAT, _RWY_28R_LON
    global _RWY_10R_LAT, _RWY_10R_LON

    _DEFAULT_GATES = dict(_ORIG_DEFAULT_GATES)
    GATES = _DEFAULT_GATES
    RUNWAY_28L_THRESHOLD = _ORIG_RUNWAY_28L_THRESHOLD
    RUNWAY_10R_THRESHOLD = _ORIG_RUNWAY_10R_THRESHOLD
    RUNWAY_28R_THRESHOLD = _ORIG_RUNWAY_28R_THRESHOLD
    RUNWAY_10L_THRESHOLD = _ORIG_RUNWAY_10L_THRESHOLD
    RUNWAY_01L_THRESHOLD = _ORIG_RUNWAY_01L_THRESHOLD
    RUNWAY_19R_THRESHOLD = _ORIG_RUNWAY_19R_THRESHOLD
    RUNWAY_01R_THRESHOLD = _ORIG_RUNWAY_01R_THRESHOLD
    RUNWAY_19L_THRESHOLD = _ORIG_RUNWAY_19L_THRESHOLD
    RUNWAY_28L_WEST = RUNWAY_28L_THRESHOLD
    RUNWAY_28L_EAST = RUNWAY_10R_THRESHOLD
    RUNWAY_28R_WEST = RUNWAY_28R_THRESHOLD
    RUNWAY_28R_EAST = RUNWAY_10L_THRESHOLD
    TERMINAL_CENTER = _ORIG_TERMINAL_CENTER
    TAXI_WAYPOINTS_ARRIVAL = list(_ORIG_TAXI_WAYPOINTS_ARRIVAL)
    TAXI_WAYPOINTS_DEPARTURE = list(_ORIG_TAXI_WAYPOINTS_DEPARTURE)
    APPROACH_WAYPOINTS = list(_ORIG_APPROACH_WAYPOINTS)
    DEPARTURE_WAYPOINTS = list(_ORIG_DEPARTURE_WAYPOINTS)
    _RWY_28L_LAT = _ORIG_RWY_28L_LAT
    _RWY_28L_LON = _ORIG_RWY_28L_LON
    _RWY_28R_LAT = _ORIG_RWY_28R_LAT
    _RWY_28R_LON = _ORIG_RWY_28R_LON
    _RWY_10R_LAT = _ORIG_RWY_10R_LAT
    _RWY_10R_LON = _ORIG_RWY_10R_LON


def _entry_direction_quadrant(entry_dir: float) -> str:
    """Classify an entry bearing into a directional quadrant for STAR/SID naming."""
    normalized = entry_dir % 360
    if normalized >= 315 or normalized < 45:
        return "NORTH"
    elif normalized < 135:
        return "EAST"
    elif normalized < 225:
        return "SOUTH"
    else:
        return "WEST"


# Named STAR procedures by approach quadrant.  Each defines distinct initial
# waypoint geometry (distances, altitudes) that converge to the common
# final approach fix.  Named after real SFO STARs where applicable.
#
# Distinct distances and altitudes per corridor create visually different
# approach paths — longer corridors for oceanic arrivals (BDEGA from the
# north Pacific), shorter for nearby domestic (DYAMD from Central Valley).
_STAR_CORRIDORS = {
    "NORTH": {
        "name": "BDEGA",          # Real SFO STAR from Point Reyes (north Pacific)
        "base_distances": [0.20, 0.16, 0.12, 0.07],
        "base_altitudes": [6000, 4500, 3200, 2500],
    },
    "EAST": {
        "name": "DYAMD",          # Real SFO STAR from Central Valley
        "base_distances": [0.14, 0.11, 0.08, 0.05],
        "base_altitudes": [4800, 3800, 3000, 2500],
    },
    "SOUTH": {
        "name": "SERFR",          # Real SFO STAR from Monterey Bay (SE)
        "base_distances": [0.18, 0.14, 0.10, 0.06],
        "base_altitudes": [5500, 4200, 3200, 2500],
    },
    "WEST": {
        "name": "OCEANIC",        # Trans-Pacific arrivals over the ocean
        "base_distances": [0.22, 0.17, 0.12, 0.07],
        "base_altitudes": [7000, 5000, 3500, 2500],
    },
}


def _get_star_name(origin_iata: Optional[str] = None) -> str:
    """Return the STAR procedure name for the given origin airport.

    Uses the same bearing logic as _get_approach_waypoints but avoids
    consuming random state for unknown airports.
    """
    if origin_iata is None:
        return _STAR_CORRIDORS["WEST"]["name"]  # Default corridor
    coords = _get_airport_coordinates()
    if origin_iata not in coords:
        return _STAR_CORRIDORS["EAST"]["name"]  # Unknown origin default
    rwy_heading = _get_runway_heading() or 280.0
    approach_course = (rwy_heading + 180) % 360
    bearing_to_apt = _bearing_from_airport(origin_iata)
    entry_dir = (bearing_to_apt + 180) % 360
    quadrant = _entry_direction_quadrant(entry_dir)
    return _STAR_CORRIDORS[quadrant]["name"]


def _get_approach_waypoints(origin_iata: Optional[str] = None) -> list:
    """Get approach waypoints aligned with the actual runway.

    When *origin_iata* is provided the approach starts from the bearing of that
    airport, so a flight from SEA appears from the north, one from LAX from the
    south, etc.  When origin is ``None`` a default entry from the east is used.

    Uses directional STAR corridors: 4 distinct approach paths (North, East,
    South, West) based on origin bearing quadrant, all converging to the same
    final approach fix on the ILS.

    When no OSM runway data is available, generates fallback waypoints using the
    airport center with a default heading of 280 (westbound approach, typical for
    most US airports).
    """
    rwy_threshold = _get_runway_threshold()  # (lon, lat) or None
    rwy_heading = _get_runway_heading()       # float or None
    if rwy_threshold is None or rwy_heading is None:
        # Fallback: generate approach waypoints from airport center with default heading
        center = get_airport_center()
        rwy_lat, rwy_lon = center[0], center[1]
        rwy_heading = 280.0  # Default westbound approach
        rwy_threshold = (rwy_lon, rwy_lat)  # (lon, lat)

    rwy_lat, rwy_lon = rwy_threshold[1], rwy_threshold[0]
    approach_course = (rwy_heading + 180) % 360

    if origin_iata is None:
        entry_dir = (approach_course + 180) % 360  # Default: from behind the approach course
    else:
        bearing_to_apt = _bearing_from_airport(origin_iata)
        entry_dir = (bearing_to_apt + 180) % 360

    # Phase 2: Final approach — centered on RUNWAY THRESHOLD (shared by all STARs)
    # Altitudes follow standard 3° glideslope (~318 ft/NM)
    final_distances = [0.10, 0.075, 0.05, 0.035, 0.02, 0.01, 0.0]
    final_altitudes = [1600, 1300, 950, 630, 320, 160, 50]
    final_wps = []
    for dist, alt in zip(final_distances, final_altitudes):
        if dist == 0.0:
            final_wps.append((rwy_lon, rwy_lat, alt))
        else:
            pt = _point_on_circle(rwy_lat, rwy_lon, approach_course, dist)
            final_wps.append((pt[1], pt[0], alt))

    # Phase 1: STAR corridor — distinct per quadrant, converges to final approach fix
    quadrant = _entry_direction_quadrant(entry_dir)
    corridor = _STAR_CORRIDORS[quadrant]
    anchor_lat, anchor_lon = final_wps[0][1], final_wps[0][0]
    base_distances = corridor["base_distances"]
    base_altitudes = corridor["base_altitudes"]

    base_wps = []
    for i, (dist, alt) in enumerate(zip(base_distances, base_altitudes)):
        blend = i / len(base_distances)  # 0→0.75
        bearing = entry_dir + _shortest_angle_diff(entry_dir, approach_course) * blend
        pt = _point_on_circle(anchor_lat, anchor_lon, bearing, dist)
        base_wps.append((pt[1], pt[0], alt))

    return base_wps + final_wps


def _get_runway_heading() -> Optional[float]:
    """Compute the runway heading from OSM runway geometry.

    Returns the heading in degrees or None when no OSM runway data is available.
    """
    rwy = _get_osm_primary_runway()
    if rwy:
        _, _, heading = _osm_runway_endpoints(rwy)
        return heading
    return None


# Named SID procedures by departure quadrant.
_SID_CORRIDORS = {
    "NORTH": {
        "name": "NORTH DEPARTURE",
        "initial_turn_offset": 0,
        "turn_start_wp": 1,          # Early turn — heading north quickly
        "turn_end_wp": 4,
    },
    "EAST": {
        "name": "EAST DEPARTURE",
        "initial_turn_offset": 0,
        "turn_start_wp": 2,          # Standard turn timing
        "turn_end_wp": 5,
    },
    "SOUTH": {
        "name": "SOUTH DEPARTURE",
        "initial_turn_offset": 0,
        "turn_start_wp": 1,          # Early turn — heading south quickly
        "turn_end_wp": 4,
    },
    "WEST": {
        "name": "WEST DEPARTURE",
        "initial_turn_offset": 0,
        "turn_start_wp": 3,          # Late turn — noise abatement over water
        "turn_end_wp": 6,
    },
}


def _get_sid_name(destination_iata: Optional[str] = None) -> str:
    """Return the SID procedure name for the given destination airport."""
    if destination_iata is None:
        return _SID_CORRIDORS["WEST"]["name"]  # Default corridor
    coords = _get_airport_coordinates()
    if destination_iata not in coords:
        return _SID_CORRIDORS["EAST"]["name"]  # Unknown destination default
    rwy_heading = _get_runway_heading() or 280.0
    exit_dir = _bearing_to_airport(destination_iata)
    quadrant = _entry_direction_quadrant(exit_dir)
    return _SID_CORRIDORS[quadrant]["name"]


def _get_departure_waypoints(destination_iata: Optional[str] = None) -> list:
    """Get departure waypoints aligned with the actual runway.

    Same-direction ops: departure climb-out extends beyond the approach
    threshold (aircraft takes off toward the threshold, then keeps climbing
    past it).  Waypoints radiate from the threshold in the runway heading
    direction.

    Uses directional SID corridors: 4 distinct departure paths (North, East,
    South, West) based on destination bearing quadrant.

    When *destination_iata* is provided the departure curves toward that
    airport's bearing so the trajectory visually heads in the right direction.

    When no OSM runway data is available, generates fallback waypoints using
    the airport center with a default heading of 280.
    """
    rwy_threshold = _get_runway_threshold()  # (lon, lat) — approach end
    rwy_heading = _get_runway_heading()  # float or None
    if rwy_threshold is None or rwy_heading is None:
        # Fallback: use airport center with default heading
        center = get_airport_center()
        rwy_threshold = (center[1], center[0])  # (lon, lat)
        rwy_heading = 280.0

    # Departure climb-out starts at the threshold (liftoff point) and extends
    # in the same direction as the runway heading.
    dep_lat, dep_lon = rwy_threshold[1], rwy_threshold[0]

    if destination_iata is None:
        exit_dir = rwy_heading  # Default: continue along runway heading
    else:
        exit_dir = _bearing_to_airport(destination_iata)

    # Select SID corridor based on destination quadrant
    quadrant = _entry_direction_quadrant(exit_dir)
    corridor = _SID_CORRIDORS[quadrant]
    turn_start = corridor["turn_start_wp"]
    turn_end = corridor["turn_end_wp"]
    initial_offset = corridor["initial_turn_offset"]

    # Distances and altitudes for 9 departure waypoints
    # Realistic SID climb: ~250 ft/NM average (varies by SID and noise abatement)
    distances = [0.02, 0.035, 0.05, 0.075, 0.10, 0.135, 0.17, 0.21, 0.25]
    altitudes = [200, 600, 1000, 1800, 2500, 3500, 5000, 6500, 8000]

    initial_heading = (rwy_heading + initial_offset) % 360

    waypoints = []
    for i, (dist, alt) in enumerate(zip(distances, altitudes)):
        if i < turn_start:
            bearing = initial_heading
        elif i < turn_end:
            blend = (i - turn_start) / max(1, turn_end - turn_start)
            bearing = initial_heading + _shortest_angle_diff(initial_heading, exit_dir) * blend
        else:
            bearing = exit_dir
        pt = _point_on_circle(dep_lat, dep_lon, bearing, dist)
        waypoints.append((pt[1], pt[0], alt))  # (lon, lat, alt)
    return waypoints


def _get_osm_primary_runway() -> Optional[dict]:
    """Get the primary (longest) runway from OSM config data.

    Returns the runway dict with 'geoPoints' [{latitude, longitude}, ...] or None
    if no OSM runway data is available.
    """
    try:
        from app.backend.services.airport_config_service import get_airport_config_service
        service = get_airport_config_service()
        config = service.get_config()
        runways = config.get("osmRunways", [])
        if not runways:
            return None
        # Pick the longest runway by number of geoPoints (proxy for length)
        best = max(runways, key=lambda r: len(r.get("geoPoints", [])))
        if len(best.get("geoPoints", [])) < 2:
            return None
        return best
    except Exception:
        return None


def _osm_runway_endpoints(runway: dict) -> tuple:
    """Extract threshold and opposite-end positions from an OSM runway.

    Returns ((threshold_lon, threshold_lat), (far_lon, far_lat), heading_deg).

    The 'threshold' is the APPROACH end — aircraft land here, flying in the
    direction of *heading_deg*.  The 'far end' is opposite.

    OSM geoPoints don't guarantee which end comes first, so we use the runway
    ref tag (e.g. "10R/28L") to orient correctly.  The ref encodes two
    designators: the first matches the heading from geoPoint[0]→geoPoint[-1].
    We pick the designator with the HIGHER number as the active arrival
    direction (standard for prevailing-wind operations at most airports).
    If the higher designator corresponds to the reverse direction, we swap
    the endpoints.
    """
    pts = runway["geoPoints"]
    p0_lat, p0_lon = pts[0]["latitude"], pts[0]["longitude"]
    pN_lat, pN_lon = pts[-1]["latitude"], pts[-1]["longitude"]
    raw_heading = _calculate_heading((p0_lat, p0_lon), (pN_lat, pN_lon))

    # Parse ref to decide orientation: "10R/28L" → [10, 28]
    ref = runway.get("ref") or runway.get("name", "")
    import re as _re
    designators = [int(m) for m in _re.findall(r'\d+', ref)]

    need_swap = False
    if len(designators) >= 2:
        # The first designator matches raw_heading (first→last geoPoint)
        # The second designator matches the reciprocal
        first_des, second_des = designators[0], designators[1]
        # Use the higher-numbered designator as the active arrival direction
        # (prevailing westerly winds → higher number in US/Europe)
        if second_des > first_des:
            # The active arrival matches the SECOND designator = reciprocal
            # Swap so threshold = last geoPoint, heading = reciprocal
            need_swap = True

    if need_swap:
        heading = (raw_heading + 180) % 360
        return (pN_lon, pN_lat), (p0_lon, p0_lat), heading
    else:
        return (p0_lon, p0_lat), (pN_lon, pN_lat), raw_heading


def _get_runway_threshold() -> Optional[tuple]:
    """Get the approach runway threshold (lon, lat) from OSM data.

    Returns (lon, lat) tuple or None when no OSM runway data is available.
    """
    rwy = _get_osm_primary_runway()
    if rwy:
        threshold, _, _ = _osm_runway_endpoints(rwy)
        return threshold
    return None


def _get_arrival_runway_name() -> str:
    """Get the arrival runway name from OSM ref tag or fall back to '28R'.

    Derives the runway name dynamically from OSM data instead of hardcoding.
    Uses the same orientation logic as _osm_runway_endpoints: the active
    arrival is the HIGHER-numbered designator (prevailing wind direction).
    """
    rwy = _get_osm_primary_runway()
    if rwy:
        ref = rwy.get("ref") or rwy.get("name", "")
        if ref:
            import re as _re
            parts = [p.strip() for p in ref.split("/")]
            designators = [int(m) for m in _re.findall(r'\d+', ref)]
            if len(parts) >= 2 and len(designators) >= 2:
                # Pick the designator with the higher number
                if designators[1] > designators[0]:
                    return parts[1]
                return parts[0]
            return parts[0]
    return "28R"



def _get_departure_runway() -> Optional[tuple]:
    """Get the departure runway start (lon, lat) from OSM data.

    Departures use the SAME active runway direction as arrivals (real-world
    standard: both ops into the wind).  The departure start is the threshold
    end of the runway — aircraft taxi here, line up, and take off rolling
    toward the far end.  For KSFO 10L/28R with heading ~284°, the threshold
    (first geoPoint) is the east end where aircraft begin the takeoff roll.

    Returns (lon, lat) tuple or None when no OSM runway data is available.
    """
    rwy = _get_osm_primary_runway()
    if rwy:
        threshold, _, _ = _osm_runway_endpoints(rwy)
        return threshold
    return None


def _get_takeoff_runway_geometry() -> tuple:
    """Get departure runway geometry for takeoff: start position, end position, heading, length.

    Uses OSM data when available, falls back to SFO Runway 28R constants.
    Returns ((start_lat, start_lon), (end_lat, end_lon), heading_deg, length_ft).
    Start is where the aircraft begins the roll; end is the far end (lift-off area).
    """
    rwy = _get_osm_primary_runway()
    if rwy:
        threshold, far_end, hdg = _osm_runway_endpoints(rwy)
        # threshold = first geoPoint (east end for KSFO 10L/28R)
        # far_end = last geoPoint (west end for KSFO 10L/28R)
        # hdg = heading from threshold → far_end (~284° for KSFO)
        # Aircraft lines up at threshold, rolls toward far_end (same direction as hdg)
        start = (threshold[1], threshold[0])  # (lat, lon) — start of takeoff roll
        end = (far_end[1], far_end[0])        # (lat, lon) — lift-off end
        dep_heading = hdg  # heading along direction of travel
        # Estimate length from coordinates
        dlat = end[0] - start[0]
        dlon = end[1] - start[1]
        dist_m = math.sqrt((dlat * 111000)**2 + (dlon * 111000 * math.cos(math.radians(start[0])))**2)
        length_ft = dist_m / 0.3048
        return start, end, dep_heading, max(length_ft, 3000)

    # Fallback: SFO Runway 28L — same-direction ops, heading ~284 (west)
    # Start at east end (10R threshold), roll toward west end (28L threshold)
    start = (RUNWAY_10R_THRESHOLD[1], RUNWAY_10R_THRESHOLD[0])
    end = (RUNWAY_28L_THRESHOLD[1], RUNWAY_28L_THRESHOLD[0])
    return start, end, 284.0, 11381.0


def _get_apron_aware_fallback(gate_pos: tuple, center: tuple) -> List[tuple]:
    """Build an apron-aware taxi route that avoids cutting through terminals.

    Instead of a straight line center→gate, routes via the nearest apron
    centroid as an intermediate waypoint, creating an L-shaped path that
    stays on paved ramp areas.

    Args:
        gate_pos: (lat, lon) of the gate
        center: (lat, lon) of the airport center

    Returns:
        List of (lon, lat) waypoints, or empty list if no apron data.
    """
    try:
        from app.backend.services.airport_config_service import get_airport_config_service
        service = get_airport_config_service()
        config = service.get_config()
        aprons = config.get("osmAprons", [])
        if not aprons:
            return []

        gate_lat, gate_lon = gate_pos
        center_lat, center_lon = center

        # Find the nearest apron centroid to the gate
        best_apron_geo = None
        best_dist = float("inf")
        for apron in aprons:
            geo = apron.get("geo", {})
            a_lat = geo.get("latitude")
            a_lon = geo.get("longitude")
            if a_lat is None or a_lon is None:
                continue
            d = (float(a_lat) - gate_lat) ** 2 + (float(a_lon) - gate_lon) ** 2
            if d < best_dist:
                best_dist = d
                best_apron_geo = (float(a_lat), float(a_lon))

        if best_apron_geo is None:
            return []

        apron_lat, apron_lon = best_apron_geo

        # Route: runway area → apron centroid → gate
        # This creates an L-shaped path that goes around the terminal.
        # Only use the apron waypoint if it's not collinear with center→gate
        # (i.e., it actually helps avoid a building).
        waypoints = [
            (center_lon, center_lat),
            (apron_lon, apron_lat),
            (gate_lon, gate_lat),
        ]
        return waypoints

    except ImportError:
        return []
    except Exception:
        return []


def _get_taxi_waypoints_arrival(gate_ref: str) -> List[tuple]:
    """Get taxi route from landing runway exit to assigned gate.

    Uses OSM taxiway graph when available, falls back to hardcoded SFO
    waypoints or apron-aware routing for non-SFO airports.

    Returns list of (lon, lat) tuples matching existing waypoint format.
    """
    try:
        from app.backend.services.airport_config_service import get_airport_config_service
        service = get_airport_config_service()
        graph = service.taxiway_graph
        if graph:
            runway_exit = _get_runway_threshold()  # (lon, lat) or None
            gate_pos = get_gates().get(gate_ref)
            if runway_exit and gate_pos:
                route = graph.find_route(
                    (runway_exit[1], runway_exit[0]),  # (lat, lon) for graph
                    gate_pos,  # (lat, lon)
                )
                if route and len(route) >= 2:
                    return [(lon, lat) for lat, lon in route]
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Taxiway graph arrival route failed for gate %s: %s", gate_ref, e)

    # Fallback: existing behavior
    center = get_airport_center()
    if abs(center[0] - AIRPORT_CENTER[0]) < 0.01:
        return TAXI_WAYPOINTS_ARRIVAL

    # Apron-aware fallback: route via nearest apron centroid to avoid
    # cutting through terminal buildings
    gate_pos = get_gates().get(gate_ref, center)
    apron_route = _get_apron_aware_fallback(gate_pos, center)
    if apron_route:
        logger.debug("Using apron-aware fallback for arrival gate %s", gate_ref)
        return apron_route

    # Last resort: straight line from center to gate
    logger.debug("Using straight-line fallback for arrival gate %s", gate_ref)
    return [(center[1], center[0]), (gate_pos[1], gate_pos[0])]


def _get_taxi_waypoints_departure(gate_ref: str) -> List[tuple]:
    """Get taxi route from gate to departure runway.

    Uses OSM taxiway graph when available, falls back to hardcoded SFO
    waypoints or apron-aware routing for non-SFO airports.

    Returns list of (lon, lat) tuples matching existing waypoint format.
    """
    try:
        from app.backend.services.airport_config_service import get_airport_config_service
        service = get_airport_config_service()
        graph = service.taxiway_graph
        if graph:
            runway_threshold = _get_departure_runway()  # (lon, lat) or None
            gate_pos = get_gates().get(gate_ref)
            if runway_threshold and gate_pos:
                route = graph.find_route(
                    gate_pos,  # (lat, lon)
                    (runway_threshold[1], runway_threshold[0]),  # (lat, lon) for graph
                )
                if route and len(route) >= 2:
                    return [(lon, lat) for lat, lon in route]
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Taxiway graph departure route failed for gate %s: %s", gate_ref, e)

    # Fallback: existing behavior
    center = get_airport_center()
    if abs(center[0] - AIRPORT_CENTER[0]) < 0.01:
        return TAXI_WAYPOINTS_DEPARTURE

    # Apron-aware fallback: route via nearest apron centroid to avoid
    # cutting through terminal buildings (reversed: gate → apron → runway)
    gate_pos = get_gates().get(gate_ref, center)
    apron_route = _get_apron_aware_fallback(gate_pos, center)
    if apron_route:
        logger.debug("Using apron-aware fallback for departure gate %s", gate_ref)
        # Reverse the arrival route for departures: gate → apron → runway
        return list(reversed(apron_route))

    # Last resort: straight line from gate to center
    logger.debug("Using straight-line fallback for departure gate %s", gate_ref)
    return [(gate_pos[1], gate_pos[0]), (center[1], center[0])]


def _get_pushback_heading(gate_ref: str) -> float:
    """Determine pushback direction: move straight away from the terminal.

    The parked heading points the nose toward the terminal wall.
    Pushback simply reverses that direction so the aircraft backs away
    from the building.  This is more reliable than using the departure
    taxi route's first segment, which can point along or even into
    adjacent building walls for gates on concourse fingers.

    Falls back to 180° (south) if no gate or terminal data.
    """
    gate_pos = get_gates().get(gate_ref)
    if gate_pos:
        parked_hdg = _get_parked_heading(gate_pos[0], gate_pos[1])
        # Pushback direction = opposite of nose heading (back away from terminal)
        return (parked_hdg + 180) % 360
    return 180.0  # Default: south


class FlightPhase(Enum):
    """Flight operational phases."""
    APPROACHING = "approaching"    # Descending toward airport
    LANDING = "landing"           # Final approach and touchdown
    TAXI_TO_GATE = "taxi_to_gate" # Taxiing from runway to gate
    PARKED = "parked"             # At gate
    PUSHBACK = "pushback"         # Pushing back from gate
    TAXI_TO_RUNWAY = "taxi_to_runway"  # Taxiing to departure runway
    TAKEOFF = "takeoff"           # Takeoff roll and initial climb
    DEPARTING = "departing"       # Climbing out
    ENROUTE = "enroute"           # Cruising at altitude


@dataclass
class FlightState:
    """Persistent state for a synthetic flight."""
    icao24: str
    callsign: str
    latitude: float
    longitude: float
    altitude: float  # feet
    velocity: float  # knots
    heading: float   # degrees
    vertical_rate: float  # ft/min
    on_ground: bool
    phase: FlightPhase
    aircraft_type: str = "A320"  # ICAO aircraft type code
    assigned_gate: Optional[str] = None
    waypoint_index: int = 0
    phase_progress: float = 0.0  # 0-1 progress through current phase
    time_at_gate: float = 0.0    # seconds parked
    origin_airport: Optional[str] = None      # IATA code of origin
    destination_airport: Optional[str] = None  # IATA code of destination
    taxi_route: Optional[List] = None          # Cached taxi waypoints [(lon, lat), ...]
    takeoff_subphase: str = "lineup"           # lineup/roll/rotate/liftoff/initial_climb
    takeoff_roll_dist_ft: float = 0.0          # Accumulated ground roll distance in feet
    holding_phase_time: float = 0.0            # Elapsed time in current holding leg (seconds)
    holding_inbound: bool = True               # True = inbound leg, False = outbound leg
    go_around_count: int = 0                   # Number of go-arounds for this approach
    go_around_target_alt: float = 0.0           # Target altitude for current go-around climb
    gate_retry_at: float = 0.0                 # time.time() when to next retry gate assignment
    parked_since: float = 0.0                  # time.time() when aircraft entered PARKED phase
    turnaround_phase: str = ""                 # Current turnaround sub-phase (e.g. "deboarding")
    turnaround_schedule: Optional[Dict] = None # {phase: {"start_offset_s", "duration_s", "done", "started"}}
    departure_queue_hold_s: float = 0.0        # Remaining departure queue hold (seconds, calibrated)
    departure_queue_set: bool = False           # True once the hold has been computed
    cruise_altitude: float = 0.0               # Target cruise FL (hemispheric rule)
    star_name: str = ""                          # Assigned STAR procedure name
    sid_name: str = ""                           # Assigned SID procedure name


# Maximum simultaneous aircraft on approach (approach + landing)
MAX_APPROACH_AIRCRAFT = 8

# Phase index — maintained automatically by _FlightStateDict and _set_phase
_flights_by_phase: Dict[FlightPhase, Set[str]] = {phase: set() for phase in FlightPhase}


class _FlightStateDict(dict):
    """Dict subclass that auto-syncs _flights_by_phase on insert/delete/clear."""

    def __setitem__(self, key: str, value: FlightState):
        old = self.get(key)
        if old is not None and old is not value:
            # Different object replacing an existing entry — update the index.
            # When old IS value (same reference, modified in-place by _update_flight_state),
            # _set_phase already updated the index, so skip to avoid double-counting.
            _flights_by_phase[old.phase].discard(key)
        super().__setitem__(key, value)
        _flights_by_phase[value.phase].add(key)

    def __delitem__(self, key: str):
        old = self.get(key)
        if old is not None:
            _flights_by_phase[old.phase].discard(key)
        super().__delitem__(key)

    def clear(self):
        super().clear()
        for s in _flights_by_phase.values():
            s.clear()


# Global state storage
_flight_states: Dict[str, FlightState] = _FlightStateDict()
_last_update: float = 0.0


def _set_phase(state: FlightState, new_phase: FlightPhase):
    """Update a flight's phase and keep the _flights_by_phase index in sync."""
    old = state.phase
    if old != new_phase:
        _flights_by_phase[old].discard(state.icao24)
        _flights_by_phase[new_phase].add(state.icao24)
        state.phase = new_phase

# ============================================================================
# SEPARATION MANAGEMENT
# ============================================================================

@dataclass
class RunwayState:
    """Tracks runway occupancy for separation."""
    occupied_by: Optional[str] = None  # icao24 of aircraft on runway
    last_departure_time: float = 0.0   # Timestamp of last departure
    last_arrival_time: float = 0.0     # Timestamp of last arrival
    approach_queue: List[str] = field(default_factory=list)  # Ordered approach sequence
    departure_queue: List[str] = field(default_factory=list)  # Ordered departure sequence
    last_departure_type: str = "LARGE"  # Wake category of last departure (FAA 7110.65)

# Minimum gate buffer (seconds) between consecutive occupancies.
# Real airports require 15-30 min for jetbridge repositioning, FOD check,
# and pushback clearance before the next aircraft can dock.
GATE_BUFFER_SECONDS = 15 * 60  # 15 minutes

# Track gate conflicts for validation reporting
_gate_conflict_count: int = 0


@dataclass
class GateState:
    """Tracks gate occupancy."""
    occupied_by: Optional[str] = None  # icao24 of aircraft at gate
    available_at: float = 0.0          # When gate becomes available (epoch seconds)
    last_released: float = 0.0         # When gate was last vacated

# Global separation state — dynamic runway dict keyed by name (D1 fix: no more hardcoded "28R")
_runway_states: Dict[str, RunwayState] = {}
# Backward-compatible aliases for tests — these are pre-populated entries in _runway_states
_runway_28L: RunwayState = RunwayState()
_runway_28R: RunwayState = RunwayState()
_runway_states["28L"] = _runway_28L
_runway_states["28R"] = _runway_28R
_gate_states: Dict[str, GateState] = {}


def _get_runway_state(runway: str) -> RunwayState:
    """Get or create a RunwayState for the given runway name."""
    if runway not in _runway_states:
        _runway_states[runway] = RunwayState()
    return _runway_states[runway]


def _get_reciprocal_designator(runway: str) -> Optional[str]:
    """Get the reciprocal designator for a runway (e.g. '28L' ↔ '10R').

    Runway designators are heading/10 rounded. The reciprocal is +18 (mod 36).
    L↔R suffix swaps; C stays C.
    Returns None if the designator cannot be parsed.
    """
    import re as _re
    m = _re.match(r'^(\d{1,2})([LRC]?)$', runway.strip())
    if not m:
        return None
    num = int(m.group(1))
    suffix = m.group(2)
    recip_num = (num + 18) % 36
    if recip_num == 0:
        recip_num = 36
    suffix_map = {'L': 'R', 'R': 'L', 'C': 'C', '': ''}
    recip_suffix = suffix_map.get(suffix, '')
    return f"{recip_num:02d}{recip_suffix}" if recip_num >= 10 else f"{recip_num}{recip_suffix}"


def _get_departure_runway_name() -> str:
    """Select the departure runway dynamically from OSM data.

    Strategy: use a different runway than the arrival runway when multiple
    runways exist (mixed-mode ops). Falls back to the arrival runway for
    single-runway airports.
    """
    try:
        from app.backend.services.airport_config_service import get_airport_config_service
        service = get_airport_config_service()
        config = service.get_config()
        runways = config.get("osmRunways", [])
        if not runways:
            return _get_arrival_runway_name()

        # Get all runway refs
        runway_refs = []
        for rwy in runways:
            ref = rwy.get("ref") or rwy.get("name", "")
            if ref and len(rwy.get("geoPoints", [])) >= 2:
                runway_refs.append(ref)

        if not runway_refs:
            return _get_arrival_runway_name()

        arrival_rwy = _get_arrival_runway_name()

        # For multi-runway airports, prefer a different runway for departures
        if len(runway_refs) > 1:
            # Pick the second runway (not the primary/longest used for arrivals)
            for ref in runway_refs:
                # OSM ref format: "10R/28L" — split and pick the reciprocal
                names = [n.strip() for n in ref.split("/")]
                # If any name in this runway matches the arrival runway, skip it
                if arrival_rwy in names:
                    continue
                # Use the first designator of this alternate runway
                return names[0]

        # Single runway or all match arrival: use the reciprocal end
        # E.g., arrival is "28L" (from ref "10R/28L"), departure uses "10R"
        for ref in runway_refs:
            names = [n.strip() for n in ref.split("/")]
            if arrival_rwy in names:
                # Return the other end
                for n in names:
                    if n != arrival_rwy:
                        return n
                return names[0]

        return runway_refs[0].split("/")[0].strip()
    except Exception:
        return _get_arrival_runway_name()

def _init_gate_states():
    """Initialize gate states, re-syncing if OSM gates become available."""
    current_gates = get_gates()
    # Re-initialize if gate set has changed (e.g., OSM loaded after fallback)
    if not _gate_states or set(_gate_states.keys()) != set(current_gates.keys()):
        old_states = dict(_gate_states)
        _gate_states.clear()
        for gate in current_gates:
            if gate in old_states:
                _gate_states[gate] = old_states[gate]
            else:
                _gate_states[gate] = GateState()

def _reset_gate_states():
    """Reset gate states when gates are reloaded."""
    _gate_states.clear()
    _init_gate_states()

def _get_wake_category(aircraft_type: str) -> str:
    """Get wake turbulence category for aircraft type."""
    return WAKE_CATEGORY.get(aircraft_type, "LARGE")

def _get_required_separation(lead_type: str, follow_type: str) -> float:
    """Get required separation in degrees between two aircraft types."""
    lead_cat = _get_wake_category(lead_type)
    follow_cat = _get_wake_category(follow_type)
    separation_nm = WAKE_SEPARATION_NM.get(
        (lead_cat, follow_cat),
        DEFAULT_SEPARATION_NM
    )
    return separation_nm * NM_TO_DEG

def _distance_nm(pos1: tuple, pos2: tuple) -> float:
    """Calculate distance in nautical miles between two positions."""
    deg_dist = _distance_between(pos1, pos2)
    return deg_dist / NM_TO_DEG

def _find_aircraft_ahead_on_approach(state: FlightState) -> Optional[FlightState]:
    """Find the aircraft directly ahead on the approach path.

    "Ahead" means closer to the airport center (further along the approach).
    Uses distance-from-center so it works regardless of approach bearing.
    """
    if state.phase not in [FlightPhase.APPROACHING, FlightPhase.LANDING]:
        return None

    center = get_airport_center()
    state_dist_to_center = _distance_between(
        (state.latitude, state.longitude), center
    )

    closest_ahead = None
    closest_gap = float('inf')

    approach_ids = _flights_by_phase[FlightPhase.APPROACHING] | _flights_by_phase[FlightPhase.LANDING]
    for icao24 in approach_ids:
        if icao24 == state.icao24:
            continue
        other = _flight_states.get(icao24)
        if other is None:
            continue  # flight removed mid-iteration (diverted/completed)

        other_dist_to_center = _distance_between(
            (other.latitude, other.longitude), center
        )
        # Other is ahead if it is closer to the airport
        if other_dist_to_center < state_dist_to_center:
            gap = _distance_between(
                (state.latitude, state.longitude),
                (other.latitude, other.longitude)
            )
            if gap < closest_gap:
                closest_gap = gap
                closest_ahead = other

    return closest_ahead


def _find_last_aircraft_on_approach() -> Optional[FlightState]:
    """Find the aircraft furthest back in the approach queue.

    "Furthest back" means the greatest distance from the airport center.
    Uses distance-from-center so it works regardless of approach bearing.
    """
    center = get_airport_center()
    last_aircraft = None
    max_dist = -1.0

    approach_ids = _flights_by_phase[FlightPhase.APPROACHING] | _flights_by_phase[FlightPhase.LANDING]
    for icao24 in approach_ids:
        state = _flight_states.get(icao24)
        if state is None:
            continue
        dist = _distance_between((state.latitude, state.longitude), center)
        if dist > max_dist:
            max_dist = dist
            last_aircraft = state

    return last_aircraft

def _check_approach_separation(state: FlightState) -> bool:
    """Check if aircraft has sufficient separation from ALL approaching/landing aircraft.

    Uses both lateral wake separation AND ICAO vertical separation (1000ft)
    as alternative clearance criteria — if either is satisfied the pair is safe.
    """
    approach_ids = _flights_by_phase[FlightPhase.APPROACHING] | _flights_by_phase[FlightPhase.LANDING]
    for other_id in approach_ids:
        if other_id == state.icao24:
            continue
        other = _flight_states.get(other_id)
        if other is None:
            continue

        lateral_dist = _distance_between(
            (state.latitude, state.longitude),
            (other.latitude, other.longitude)
        )
        required_dist = _get_required_separation(other.aircraft_type, state.aircraft_type)

        if lateral_dist >= required_dist:
            continue  # Lateral separation satisfied

        # Lateral separation violated — check vertical separation (1000ft)
        vertical_sep = abs(state.altitude - other.altitude)
        if vertical_sep >= 1000:
            continue  # Vertical separation satisfied

        diag_log(
            "SEPARATION_LOSS", datetime.now(timezone.utc),
            icao24=state.icao24, leader=other_id,
            distance_nm=round(lateral_dist / NM_TO_DEG, 2),
            required_nm=round(required_dist / NM_TO_DEG, 2),
            vertical_ft=round(vertical_sep),
        )
        return False  # Both lateral and vertical separation violated

    return True

def _is_runway_clear(runway: str = "") -> bool:
    """Check if runway is clear for landing or takeoff.

    Checks BOTH the given designator AND its reciprocal (e.g. '28L' and '10R')
    because they are the same physical runway.
    """
    if not runway:
        runway = _get_arrival_runway_name()
    if _get_runway_state(runway).occupied_by is not None:
        return False
    recip = _get_reciprocal_designator(runway)
    if recip and recip in _runway_states and _runway_states[recip].occupied_by is not None:
        return False
    return True

def _occupy_runway(icao24: str, runway: str = ""):
    """Mark runway as occupied by aircraft (both designators for same physical runway)."""
    if not runway:
        runway = _get_arrival_runway_name()
    rs = _get_runway_state(runway)
    if rs.occupied_by is not None and rs.occupied_by != icao24:
        diag_log(
            "RUNWAY_CONFLICT", datetime.now(timezone.utc),
            runway=runway, occupant=rs.occupied_by, requester=icao24,
        )
    rs.occupied_by = icao24
    # Also mark reciprocal designator (same physical runway)
    recip = _get_reciprocal_designator(runway)
    if recip:
        _get_runway_state(recip).occupied_by = icao24

def _release_runway(icao24: str, runway: str = "", aircraft_type: str = ""):
    """Release runway when aircraft clears. Stores wake category for departure separation."""
    if not runway:
        runway = _get_arrival_runway_name()
    rs = _get_runway_state(runway)
    if rs.occupied_by == icao24:
        rs.occupied_by = None
        rs.last_arrival_time = time.time()
        if aircraft_type:
            rs.last_departure_type = _get_wake_category(aircraft_type)
            rs.last_departure_time = time.time()
    # Also release reciprocal designator (same physical runway)
    recip = _get_reciprocal_designator(runway)
    if recip and recip in _runway_states:
        rrs = _runway_states[recip]
        if rrs.occupied_by == icao24:
            rrs.occupied_by = None
            rrs.last_arrival_time = time.time()
            if aircraft_type:
                rrs.last_departure_type = _get_wake_category(aircraft_type)
                rrs.last_departure_time = time.time()

def _find_available_gate() -> Optional[str]:
    """Find a random available gate, preferring terminal gates over remote stands.

    Respects GATE_BUFFER_SECONDS — gates recently vacated are not eligible.
    Increments conflict counter when a gate is requested but all are in buffer.
    """
    global _gate_conflict_count
    _init_gate_states()
    current_time = time.time()

    available = [
        gate for gate, state in _gate_states.items()
        if state.occupied_by is None and current_time >= state.available_at
    ]
    if not available:
        # Check if gates are blocked by buffer (conflict) vs truly occupied
        in_buffer = [
            g for g, s in _gate_states.items()
            if s.occupied_by is None and current_time < s.available_at
        ]
        if in_buffer:
            _gate_conflict_count += 1
            diag_log(
                "GATE_CONFLICT", datetime.now(timezone.utc),
                gates_in_buffer=len(in_buffer),
            )
        return None

    # Prefer terminal gates (non-R-prefixed) over remote stands
    terminal_gates = [g for g in available if not g.startswith("R")]
    if terminal_gates:
        return random.choice(terminal_gates)
    return random.choice(available)

def _find_overflow_gate() -> Optional[str]:
    """Find a gate for overflow (all occupied). Distributes across gates.

    Prefers gates whose occupant is departing (PUSHBACK/TAXI_TO_RUNWAY)
    over gates with parked aircraft, to avoid true double-occupancy.
    Falls back to soonest-to-free if no departing gates found.
    """
    _init_gate_states()
    if not _gate_states:
        return None
    # Prefer gates where the occupant is actively departing
    departing_gates = []
    for gate, gs in _gate_states.items():
        if gs.occupied_by and gs.occupied_by in _flight_states:
            fs = _flight_states[gs.occupied_by]
            if fs.phase in (FlightPhase.PUSHBACK, FlightPhase.TAXI_TO_RUNWAY,
                            FlightPhase.TAKEOFF, FlightPhase.DEPARTING):
                departing_gates.append(gate)
    if departing_gates:
        return random.choice(departing_gates)
    # Sort gates by available_at, pick randomly from top 5 soonest
    sorted_gates = sorted(_gate_states.keys(), key=lambda g: _gate_states[g].available_at)
    top_n = min(5, len(sorted_gates))
    return random.choice(sorted_gates[:top_n])


def _occupy_gate(icao24: str, gate: str):
    """Mark gate as occupied."""
    _init_gate_states()
    if gate in _gate_states:
        _gate_states[gate].occupied_by = icao24

def _release_gate(icao24: str, gate: str):
    """Release gate when aircraft departs, enforcing minimum buffer."""
    _init_gate_states()
    if gate in _gate_states and _gate_states[gate].occupied_by == icao24:
        _gate_states[gate].occupied_by = None
        _gate_states[gate].last_released = time.time()
        _gate_states[gate].available_at = time.time() + GATE_BUFFER_SECONDS


def get_gate_conflict_count() -> int:
    """Return count of gate conflicts (attempted assignment before buffer expired)."""
    return _gate_conflict_count


def reset_gate_conflict_count() -> None:
    """Reset gate conflict counter (call at start of validation run)."""
    global _gate_conflict_count
    _gate_conflict_count = 0

def _check_taxi_separation(state: FlightState) -> bool:
    """Check if aircraft has sufficient separation from others on ground.

    Returns True (can move at full speed) or False (must stop).
    For graduated speed control, use _taxi_speed_factor() instead.
    """
    return _taxi_speed_factor(state) > 0.0


def _taxi_speed_factor(state: FlightState) -> float:
    """Compute taxi speed factor based on traffic ahead and head-on conflicts.

    Returns:
        1.0 = clear, full speed
        0.3-0.9 = traffic ahead, reduce speed proportionally
        0.0 = must stop (too close to traffic ahead)
       -1.0 = head-on hold (must yield to oncoming traffic, no creep)

    Checks both same-direction traffic (ahead) and head-on conflicts.
    Head-on priority: arrivals (TAXI_TO_GATE) have right of way over
    departures (TAXI_TO_RUNWAY). Same-phase ties broken by icao24.
    """
    if not state.on_ground:
        return 1.0

    import math
    hdg_rad = math.radians(state.heading)
    fwd_x = math.sin(hdg_rad)  # east component of heading
    fwd_y = math.cos(hdg_rad)  # north component of heading

    # Arriving aircraft get tighter separation (ATC inbound priority)
    sep_threshold = (
        MIN_TAXI_SEPARATION_ARRIVAL_DEG
        if state.phase == FlightPhase.TAXI_TO_GATE
        else MIN_TAXI_SEPARATION_DEG
    )
    # Graduated zone: 2x separation threshold — slow down before stopping
    slow_zone = sep_threshold * 2.0
    # Head-on detection zone: 3x separation (detect earlier for smooth stop)
    head_on_zone = sep_threshold * 3.0

    min_factor = 1.0
    head_on_hold = False

    for icao24, other in _flight_states.items():
        if icao24 == state.icao24:
            continue
        if not other.on_ground:
            continue
        if other.phase == FlightPhase.PARKED:
            continue  # Parked aircraft don't block taxi routes

        dist = _distance_between(
            (state.latitude, state.longitude),
            (other.latitude, other.longitude)
        )

        # Head-on conflict detection (wider zone)
        if dist < head_on_zone and other.phase in (
            FlightPhase.TAXI_TO_GATE, FlightPhase.TAXI_TO_RUNWAY,
            FlightPhase.PUSHBACK,
        ):
            # Check if headings are roughly opposite (>120° difference)
            heading_diff = abs(((state.heading - other.heading + 180) % 360) - 180)
            if heading_diff > 120:
                # Determine priority: arrival > departure; else lower icao24 wins
                state_priority = 1 if state.phase == FlightPhase.TAXI_TO_GATE else 0
                other_priority = 1 if other.phase == FlightPhase.TAXI_TO_GATE else 0
                if state_priority != other_priority:
                    must_yield = state_priority < other_priority
                else:
                    must_yield = state.icao24 > other.icao24
                if must_yield:
                    head_on_hold = True

        if dist < slow_zone:
            dlat = other.latitude - state.latitude
            dlon = other.longitude - state.longitude
            dot = dlon * fwd_x + dlat * fwd_y

            # Overlap prevention: if nearly on top of each other (<20m),
            # stop the aircraft with higher icao24 regardless of heading.
            if dist < 0.0002 and state.icao24 > other.icao24:
                return -1.0 if head_on_hold else 0.0

            # Consider aircraft AHEAD of us (same direction or approaching)
            if dot > 0:
                if dist < sep_threshold:
                    return -1.0 if head_on_hold else 0.0
                # Graduated: linearly reduce from 1.0 at slow_zone to 0.3 at sep_threshold
                ratio = (dist - sep_threshold) / (slow_zone - sep_threshold)
                factor = 0.3 + 0.7 * ratio
                min_factor = min(min_factor, factor)

    if head_on_hold:
        return -1.0

    return min_factor

def _count_aircraft_in_phase(phase: FlightPhase) -> int:
    """Count how many aircraft are currently in a specific phase.

    Counts from actual flight state rather than the phase index to avoid
    desync issues where the index retains stale entries.
    """
    return sum(1 for s in _flight_states.values() if s.phase == phase)

def _get_approach_queue_position(icao24: str) -> int:
    """Get position in approach queue (0 = first/next to land)."""
    queue = [s for s in _flight_states.values()
             if s.phase in [FlightPhase.APPROACHING, FlightPhase.LANDING]]
    # Sort by distance to airport center (closest first)
    center = get_airport_center()
    queue.sort(key=lambda s: _distance_between((s.latitude, s.longitude), center))

    for i, s in enumerate(queue):
        if s.icao24 == icao24:
            return i
    return len(queue)


def _shortest_angle_diff(from_deg: float, to_deg: float) -> float:
    """Signed shortest rotation from *from_deg* to *to_deg* (both 0-360)."""
    diff = (to_deg - from_deg + 180) % 360 - 180
    return diff


def _calculate_heading(from_pos: tuple, to_pos: tuple) -> float:
    """Calculate heading (bearing) from one position to another.

    Uses latitude-corrected longitude to account for Mercator distortion.
    Without this correction, headings are skewed at higher latitudes
    because 1° of longitude is shorter than 1° of latitude.
    """
    lat1, lon1 = from_pos
    lat2, lon2 = to_pos

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    # Scale longitude by cos(latitude) to convert to approximate meters
    avg_lat = math.radians((lat1 + lat2) / 2)
    dlon_corrected = dlon * math.cos(avg_lat)

    # Calculate bearing (clockwise from north)
    angle = math.atan2(dlon_corrected, dlat)
    heading = math.degrees(angle)

    # Normalize to 0-360
    return (heading + 360) % 360


def _smooth_heading(current: float, target: float, max_rate_per_sec: float, dt: float) -> float:
    """Limit heading change to a realistic turn rate.

    Standard rate turn = 3 deg/s.  Returns new heading in [0, 360).
    """
    diff = (target - current + 540) % 360 - 180  # shortest signed angle
    max_change = max_rate_per_sec * dt
    clamped = max(-max_change, min(max_change, diff))
    return (current + clamped) % 360


def _distance_between(pos1: tuple, pos2: tuple) -> float:
    """Calculate approximate distance in degrees (simplified)."""
    lat1, lon1 = pos1[:2]
    lat2, lon2 = pos2[:2]
    return math.sqrt((lat2 - lat1) ** 2 + (lon2 - lon1) ** 2)


def _move_toward(current: tuple, target: tuple, speed_factor: float) -> tuple:
    """Move current position toward target by speed factor."""
    lat, lon = current[:2]
    target_lat, target_lon = target[:2]

    dlat = target_lat - lat
    dlon = target_lon - lon
    distance = math.sqrt(dlat ** 2 + dlon ** 2)

    if distance < 0.0001:  # Close enough
        return target[:2]

    # Move by speed factor (degrees per update)
    move_dist = min(speed_factor, distance)
    ratio = move_dist / distance

    new_lat = lat + dlat * ratio
    new_lon = lon + dlon * ratio

    return (new_lat, new_lon)


def _interpolate_altitude(current_alt: float, target_alt: float, rate: float) -> float:
    """Smoothly change altitude toward target."""
    if abs(current_alt - target_alt) < 50:
        return target_alt

    if current_alt < target_alt:
        return current_alt + rate
    else:
        return current_alt - rate


def _get_aircraft_type_for_airline(callsign: str, is_international: bool = False) -> str:
    """Get a random aircraft type based on airline callsign and route type.

    Uses calibrated fleet mix from the airport profile when available.
    """
    airline_code = callsign[:3].upper() if callsign and len(callsign) >= 3 else None

    # Easter egg: Ukrainian Air Force gets fighter jets
    if airline_code == "UAF":
        return random.choice(["F16", "F15", "F22", "F35"])

    # Try calibrated fleet mix first
    if airline_code:
        profile = _get_current_airport_profile()
        if profile and airline_code in profile.fleet_mix:
            fleet = profile.fleet_mix[airline_code]
            if fleet:
                types = list(fleet.keys())
                weights = list(fleet.values())
                return random.choices(types, weights=weights, k=1)[0]

    # Fall back to hardcoded AIRLINE_FLEET
    if airline_code and airline_code in AIRLINE_FLEET:
        fleet = AIRLINE_FLEET[airline_code]
        if is_international:
            wide_body = [a for a in fleet if a in ("B777", "B787", "A330", "A350", "A380", "A345")]
            if wide_body:
                return random.choice(wide_body)
        return random.choice(fleet)
    if is_international:
        return random.choice(["B777", "B787", "A350", "A330"])
    return random.choice(["A320", "B738", "A321", "B737"])


def _get_airport_coordinates() -> dict:
    """Get the airport coordinates lookup table."""
    from src.ingestion.schedule_generator import AIRPORT_COORDINATES
    return AIRPORT_COORDINATES


def _bearing_from_airport(origin_iata: str) -> float:
    """Compute initial bearing FROM origin airport TO current airport center (degrees, 0=N, 90=E).

    This gives the direction from which an arriving flight should appear.
    """
    coords = _get_airport_coordinates()
    if origin_iata not in coords:
        return random.uniform(0, 360)

    center = get_airport_center()
    lat1, lon1 = math.radians(coords[origin_iata][0]), math.radians(coords[origin_iata][1])
    lat2, lon2 = math.radians(center[0]), math.radians(center[1])

    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360) % 360


def _bearing_to_airport(dest_iata: str) -> float:
    """Compute initial bearing FROM current airport center TO destination airport (degrees, 0=N, 90=E).

    This gives the direction a departing flight should head toward.
    """
    coords = _get_airport_coordinates()
    if dest_iata not in coords:
        return random.uniform(0, 360)

    center = get_airport_center()
    lat1, lon1 = math.radians(center[0]), math.radians(center[1])
    lat2, lon2 = math.radians(coords[dest_iata][0]), math.radians(coords[dest_iata][1])

    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360) % 360


def _point_on_circle(center_lat: float, center_lon: float, bearing_deg: float, radius_deg: float) -> tuple:
    """Calculate a point at a given bearing and distance from center.

    Args:
        center_lat, center_lon: Center point in degrees
        bearing_deg: Bearing in degrees (0=N, 90=E)
        radius_deg: Distance in degrees

    Returns:
        (latitude, longitude) tuple
    """
    bearing_rad = math.radians(bearing_deg)
    lat = center_lat + radius_deg * math.cos(bearing_rad)
    # Adjust longitude for latitude (1 degree longitude is shorter at higher latitudes)
    lon = center_lon + radius_deg * math.sin(bearing_rad) / math.cos(math.radians(center_lat))
    return (lat, lon)


def _offset_position_by_heading(lat: float, lon: float, heading_deg: float, distance_meters: float) -> tuple:
    """Move a point away from a heading direction (i.e., pull aircraft back from gate).

    The aircraft nose points at heading_deg (toward the terminal). This function
    moves the position in the *opposite* direction so the nose reaches the gate
    point while the fuselage sits on the apron.

    Args:
        lat, lon: Original position in degrees (gate/jetbridge point)
        heading_deg: Direction the nose is pointing (toward terminal)
        distance_meters: How far to pull the aircraft back

    Returns:
        (latitude, longitude) tuple offset away from the terminal
    """
    # Move in the opposite direction of the heading
    reverse_bearing_rad = math.radians((heading_deg + 180) % 360)
    # Convert meters to degrees (approximate)
    distance_deg = distance_meters / 111_000  # ~111 km per degree of latitude
    new_lat = lat + distance_deg * math.cos(reverse_bearing_rad)
    new_lon = lon + distance_deg * math.sin(reverse_bearing_rad) / math.cos(math.radians(lat))
    return (new_lat, new_lon)


def _distance_meters(pos1: tuple, pos2: tuple) -> float:
    """Approximate distance in meters between two (lat, lon) points."""
    lat1, lon1 = pos1[:2]
    lat2, lon2 = pos2[:2]
    dlat = (lat2 - lat1) * 111_000
    dlon = (lon2 - lon1) * 111_000 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.sqrt(dlat ** 2 + dlon ** 2)


def _point_to_segment_distance_m(px: float, py: float,
                                  ax: float, ay: float,
                                  bx: float, by: float) -> float:
    """Minimum distance in meters from point (px, py) to segment (ax,ay)-(bx,by).

    All coordinates in (lat, lon) degrees.
    """
    # Project point onto segment in local meter space
    cos_lat = math.cos(math.radians(px))
    # Convert to meters from an arbitrary origin (ax, ay)
    pxm = (px - ax) * 111_000
    pym = (py - ay) * 111_000 * cos_lat
    bxm = (bx - ax) * 111_000
    bym = (by - ay) * 111_000 * cos_lat

    seg_len_sq = bxm * bxm + bym * bym
    if seg_len_sq < 1e-10:
        return math.sqrt(pxm * pxm + pym * pym)

    t = max(0.0, min(1.0, (pxm * bxm + pym * bym) / seg_len_sq))
    proj_x = t * bxm
    proj_y = t * bym
    return math.sqrt((pxm - proj_x) ** 2 + (pym - proj_y) ** 2)


def _point_in_polygon(lat: float, lon: float, polygon: list[dict]) -> bool:
    """Ray-casting point-in-polygon test.

    Returns True if the point (lat, lon) is inside the polygon.
    Polygon vertices are dicts with 'latitude' and 'longitude' keys.
    """
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        # latitude = y-axis, longitude = x-axis
        yi = float(polygon[i].get("latitude", 0))
        xi = float(polygon[i].get("longitude", 0))
        yj = float(polygon[j].get("latitude", 0))
        xj = float(polygon[j].get("longitude", 0))
        if ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / (yj - yi) + xi
        ):
            inside = not inside
        j = i
    return inside


def _is_gate_inside_terminal(gate_lat: float, gate_lon: float) -> bool:
    """Check if a gate position is inside any terminal polygon.

    Uses OSM terminal geoPolygon data. Returns False if no terminal data.
    """
    try:
        from app.backend.services.airport_config_service import get_airport_config_service
        service = get_airport_config_service()
        config = service.get_config()
        terminals = config.get("terminals", [])
        for terminal in terminals:
            geo_polygon = terminal.get("geoPolygon", [])
            if len(geo_polygon) < 3:
                continue
            if _point_in_polygon(gate_lat, gate_lon, geo_polygon):
                return True
        return False
    except Exception:
        return False


def _gate_to_terminal_edge_distance_m(gate_lat: float, gate_lon: float) -> float | None:
    """Compute distance in meters from a gate to the nearest terminal polygon edge.

    Uses OSM terminal geoPolygon data. Returns None if no terminal data is available.
    """
    try:
        from app.backend.services.airport_config_service import get_airport_config_service
        service = get_airport_config_service()
        config = service.get_config()
        terminals = config.get("terminals", [])
        if not terminals:
            return None

        best_dist = float('inf')
        for terminal in terminals:
            geo_polygon = terminal.get("geoPolygon", [])
            if len(geo_polygon) < 3:
                continue
            # Check distance to each edge of the terminal polygon
            for i in range(len(geo_polygon)):
                j = (i + 1) % len(geo_polygon)
                a_lat = float(geo_polygon[i].get("latitude", 0))
                a_lon = float(geo_polygon[i].get("longitude", 0))
                b_lat = float(geo_polygon[j].get("latitude", 0))
                b_lon = float(geo_polygon[j].get("longitude", 0))
                d = _point_to_segment_distance_m(gate_lat, gate_lon,
                                                  a_lat, a_lon, b_lat, b_lon)
                if d < best_dist:
                    best_dist = d
        return best_dist if best_dist < float('inf') else None
    except Exception:
        return None


def _compute_gate_standoff(gate_lat: float, gate_lon: float,
                           heading_deg: float, aircraft_type: str) -> float:
    """Compute how far to offset a parked aircraft from the gate node.

    Uses the airport's OSM terminal polygon to determine the gate-to-terminal
    edge distance, combined with the aircraft's full length, so different
    airports and aircraft types produce different standoff distances.

    The Leaflet marker is anchored at the aircraft CENTER. To place the NOSE
    at the gate/jetbridge point while keeping the fuselage on the apron, we
    must offset the center back by at least half the fuselage length.

    When the gate node is on or inside the terminal wall (edge_dist ≈ 0,
    typical for OSM jetbridge nodes), we also add a jetbridge gap so the
    nose clears the building entirely.

    Args:
        gate_lat, gate_lon: Gate/jetbridge position from OSM
        heading_deg: Aircraft nose heading (toward terminal)
        aircraft_type: ICAO type designator (e.g. "A320", "B777")

    Returns:
        Standoff distance in meters (applied in the reverse heading direction)
    """
    half_length = AIRCRAFT_HALF_LENGTH_M.get(aircraft_type, _DEFAULT_HALF_LENGTH_M)
    # Jetbridge gap: distance from terminal wall to aircraft nose tip
    jetbridge_gap_m = 5.0

    edge_dist = _gate_to_terminal_edge_distance_m(gate_lat, gate_lon)
    if edge_dist is None:
        # No OSM terminal data — offset by half-length + jetbridge gap
        return half_length + jetbridge_gap_m

    required = half_length + jetbridge_gap_m
    inside = _is_gate_inside_terminal(gate_lat, gate_lon)

    if inside:
        # Gate is inside terminal building (common for jetbridge nodes) —
        # must push out past the wall first, then clear jetbridge + half-length.
        return required + edge_dist
    else:
        # Gate is outside the building — already has some clearance from wall.
        if edge_dist >= required:
            # Remote stand far from building — no offset needed.
            return 0.0
        return required - edge_dist


def _get_parked_heading(gate_lat: float, gate_lon: float) -> float:
    """Compute heading for a parked aircraft: nose perpendicular to nearest terminal edge.

    This ensures the aircraft wings are parallel to the terminal building face,
    matching real-world gate orientation. Falls back to airport center if no
    terminal data is available, or 180 deg as a last resort.

    Normal disambiguation uses a point-in-polygon probe instead of centroid
    direction, which is robust for irregular/L-shaped terminals and concourse
    fingers where the centroid can be far from the local gate area.

    If the gate is inside a terminal polygon, only edges from that terminal are
    considered (prevents picking an edge from an adjacent terminal building).
    """
    try:
        from app.backend.services.airport_config_service import get_airport_config_service
        service = get_airport_config_service()
        config = service.get_config()
        terminals = config.get("terminals", [])
        if not terminals:
            raise ValueError("no terminals")

        # Collect terminal polygons (parsed once)
        parsed_terminals: list[tuple[list[dict], list[tuple]]] = []
        containing_idx = -1
        for idx, terminal in enumerate(terminals):
            geo_polygon = terminal.get("geoPolygon", [])
            if not geo_polygon or len(geo_polygon) < 3:
                continue
            verts = [
                (float(p.get("latitude", 0)), float(p.get("longitude", 0)))
                for p in geo_polygon
            ]
            parsed_terminals.append((geo_polygon, verts))
            if _point_in_polygon(gate_lat, gate_lon, geo_polygon):
                containing_idx = len(parsed_terminals) - 1

        # If gate is inside a terminal, restrict search to that terminal's edges
        if containing_idx >= 0:
            search_set = [parsed_terminals[containing_idx]]
        else:
            search_set = parsed_terminals

        best_dist = float('inf')
        best_edge = None   # (a_lat, a_lon, b_lat, b_lon)
        best_poly = None   # geo_polygon list for the owning terminal

        for geo_polygon, verts in search_set:
            n = len(verts)
            for i in range(n):
                j = (i + 1) % n
                a_lat, a_lon = verts[i]
                b_lat, b_lon = verts[j]
                d = _point_to_segment_distance_m(
                    gate_lat, gate_lon, a_lat, a_lon, b_lat, b_lon
                )
                if d < best_dist:
                    best_dist = d
                    best_edge = (a_lat, a_lon, b_lat, b_lon)
                    best_poly = geo_polygon

        if best_edge and best_poly:
            a_lat, a_lon, b_lat, b_lon = best_edge
            cos_lat = math.cos(math.radians(gate_lat))
            dx = (b_lon - a_lon) * 111_000 * cos_lat
            dy = (b_lat - a_lat) * 111_000
            edge_len = math.sqrt(dx * dx + dy * dy)
            if edge_len > 0.01:
                # Two candidate normals perpendicular to the edge
                n1x, n1y = -dy / edge_len, dx / edge_len
                # Probe: move 1m from edge midpoint in n1 direction — if
                # that lands inside the polygon, n1 is the inward normal
                mid_lat = (a_lat + b_lat) / 2
                mid_lon = (a_lon + b_lon) / 2
                probe_m = 1.0  # 1 meter
                probe_deg = probe_m / 111_000
                probe_lat = mid_lat + n1y * probe_deg
                probe_lon = mid_lon + n1x * probe_deg / max(cos_lat, 0.01)
                if _point_in_polygon(probe_lat, probe_lon, best_poly):
                    # n1 points inward — use it (nose toward building)
                    nx, ny = n1x, n1y
                else:
                    # n1 points outward — flip to inward
                    nx, ny = -n1x, -n1y
                heading = round(math.degrees(math.atan2(nx, ny)) % 360, 1)
                return heading
    except Exception:
        pass
    # Fallback: face toward airport center
    center = get_airport_center()
    if _distance_between((gate_lat, gate_lon), center) > 0.0001:
        return _calculate_heading((gate_lat, gate_lon), center)
    return 180.0


def _is_international_airport(iata: str) -> bool:
    """Check if an airport code is in the international list."""
    from src.ingestion.schedule_generator import INTERNATIONAL_AIRPORTS
    return iata in INTERNATIONAL_AIRPORTS


# Country lookup for origin_country field
_AIRPORT_COUNTRY = {
    "SFO": "United States", "LAX": "United States", "ORD": "United States",
    "DFW": "United States", "JFK": "United States", "ATL": "United States",
    "DEN": "United States", "SEA": "United States", "BOS": "United States",
    "PHX": "United States", "LAS": "United States", "MCO": "United States",
    "MIA": "United States", "CLT": "United States", "MSP": "United States",
    "DTW": "United States", "EWR": "United States", "PHL": "United States",
    "IAH": "United States", "SAN": "United States", "PDX": "United States",
    "LHR": "United Kingdom", "CDG": "France", "FRA": "Germany",
    "AMS": "Netherlands", "HKG": "Hong Kong", "NRT": "Japan",
    "SIN": "Singapore", "SYD": "Australia", "DXB": "UAE", "ICN": "South Korea",
    "HND": "Japan",
    # European
    "GVA": "Switzerland", "MUC": "Germany", "DUS": "Germany",
    "HAM": "Germany", "BER": "Germany", "STR": "Germany", "CGN": "Germany",
    "ORY": "France", "NCE": "France", "LYS": "France", "MRS": "France",
    "TLS": "France", "BOD": "France",
    "LGW": "United Kingdom", "MAN": "United Kingdom", "EDI": "United Kingdom",
    "STN": "United Kingdom",
    "EIN": "Netherlands", "RTM": "Netherlands",
    "ATH": "Greece", "IST": "Turkey",
    # Asia-Pacific
    "KIX": "Japan", "FUK": "Japan", "CTS": "Japan",
    "GMP": "South Korea", "PUS": "South Korea", "CJU": "South Korea",
    "MEL": "Australia", "BNE": "Australia",
    # Americas
    "GIG": "Brazil", "CGH": "Brazil", "GRU": "Brazil",
    "YYZ": "Canada", "YVR": "Canada",
    "MEX": "Mexico", "CUN": "Mexico",
    "SCL": "Chile",
    # Middle East / Africa
    "AUH": "UAE", "DOH": "Qatar",
    "CMN": "Morocco", "CAI": "Egypt",
    "JNB": "South Africa", "CPT": "South Africa",
}


def _get_origin_country(origin_iata: Optional[str]) -> str:
    """Get the country for an airport IATA code."""
    if origin_iata:
        from src.ingestion.airport_table import get_country_name
        name = get_country_name(origin_iata)
        if name != "Unknown":
            return name
        # Fallback to legacy dict for any codes not in the global table
        if origin_iata in _AIRPORT_COUNTRY:
            return _AIRPORT_COUNTRY[origin_iata]
    return "United States"


def _get_current_airport_profile():
    """Get the calibrated profile for the current airport (cached, lazy-loaded)."""
    from src.ingestion.schedule_generator import _get_profile_loader
    return _get_profile_loader().get_profile(get_current_airport_iata())


def _pick_random_airport(exclude: Optional[str] = None) -> str:
    """Pick a random airport, excluding the specified one (typically the local airport).

    Uses calibrated route shares from the airport profile when available.
    """
    profile = _get_current_airport_profile()

    if profile and (profile.domestic_route_shares or profile.international_route_shares):
        is_domestic = random.random() < profile.domestic_ratio
        if is_domestic and profile.domestic_route_shares:
            routes = {k: v for k, v in profile.domestic_route_shares.items() if k != exclude}
            if routes:
                return random.choices(list(routes.keys()), weights=list(routes.values()), k=1)[0]
        if profile.international_route_shares:
            routes = {k: v for k, v in profile.international_route_shares.items() if k != exclude}
            if routes:
                return random.choices(list(routes.keys()), weights=list(routes.values()), k=1)[0]

    from src.ingestion.schedule_generator import get_nearby_airports, INTERNATIONAL_AIRPORTS
    local_iata = get_current_airport_iata()
    nearby, far = get_nearby_airports(local_iata)
    if random.random() < 0.7:
        pool = [a for a in nearby if a != exclude]
    else:
        pool = [a for a in far if a != exclude]
    if not pool:
        pool = [a for a in INTERNATIONAL_AIRPORTS if a != exclude] or INTERNATIONAL_AIRPORTS
    return random.choice(pool)


def _pick_random_origin() -> str:
    """Pick a random origin airport for arriving flights (never the local airport)."""
    return _pick_random_airport(exclude=get_current_airport_iata())


def _pick_random_destination() -> str:
    """Pick a random destination airport for departing flights (never the local airport)."""
    return _pick_random_airport(exclude=get_current_airport_iata())


# Gate-relevant turnaround phases in DAG order (excludes taxi/pushback sim phases)
_GATE_PHASES = [
    "chocks_on", "deboarding", "unloading", "cleaning",
    "catering", "refueling", "loading", "boarding", "chocks_off",
]


def _build_turnaround_schedule(
    aircraft_type: str,
    airline_code: str,
    combined_factor: float,
) -> Dict[str, Dict]:
    """Build a critical-path turnaround schedule for gate sub-phases.

    Returns dict: {phase_name: {"start_offset_s", "duration_s", "done", "started"}}
    All times are in seconds relative to PARKED entry (time_at_gate=0).
    """
    timing = get_turnaround_timing(aircraft_type)
    phases = timing["phases"]

    # Compute jittered durations (minutes) for gate phases only
    jittered: Dict[str, float] = {}
    for phase in _GATE_PHASES:
        nominal = phases.get(phase, 5)
        jittered[phase] = nominal * combined_factor * random.uniform(0.9, 1.1)

    # Critical-path scheduling: earliest start = max finish of dependencies
    finish: Dict[str, float] = {}
    start: Dict[str, float] = {}
    for phase in _GATE_PHASES:
        deps = PHASE_DEPENDENCIES.get(phase, [])
        # Only consider deps that are also gate phases
        earliest_start = max(
            (finish[d] for d in deps if d in finish),
            default=0.0,
        )
        start[phase] = earliest_start
        finish[phase] = earliest_start + jittered[phase]

    # Convert to seconds and build schedule dict
    schedule: Dict[str, Dict] = {}
    for phase in _GATE_PHASES:
        schedule[phase] = {
            "start_offset_s": start[phase] * 60,
            "duration_s": jittered[phase] * 60,
            "done": False,
            "started": False,
        }

    return schedule


def _create_new_flight(
    icao24: str, callsign: str, phase: FlightPhase,
    origin: Optional[str] = None, destination: Optional[str] = None,
) -> FlightState:
    """Create a new flight in the specified phase with proper separation."""
    is_intl = _is_international_airport(origin or "") or _is_international_airport(destination or "")
    aircraft_type = _get_aircraft_type_for_airline(callsign, is_international=is_intl)

    if phase == FlightPhase.APPROACHING:
        # Start on approach from the origin direction WITH PROPER WAKE TURBULENCE SEPARATION
        base_wp = _get_approach_waypoints(origin)[0]
        center = get_airport_center()

        # Find how many aircraft are already approaching
        approaching_count = _count_aircraft_in_phase(FlightPhase.APPROACHING)
        landing_count = _count_aircraft_in_phase(FlightPhase.LANDING)

        # Limit simultaneous approaches (realistic: max 4-5 in sequence)
        if approaching_count + landing_count >= MAX_APPROACH_AIRCRAFT:
            # Too many on approach - start as enroute instead
            return _create_new_flight(icao24, callsign, FlightPhase.ENROUTE, origin=origin, destination=destination)

        # Calculate position based on actual aircraft positions (not just count)
        last_aircraft = _find_last_aircraft_on_approach()

        if last_aircraft is None:
            # No aircraft on approach - start at base waypoint
            lat = base_wp[1] + random.uniform(-0.005, 0.005)
            lon = base_wp[0]
            alt = base_wp[2]
        else:
            # Calculate required separation based on wake turbulence categories
            required_sep_deg = _get_required_separation(
                last_aircraft.aircraft_type,
                aircraft_type
            )
            required_sep_deg *= 1.2

            # Position new aircraft behind the last one (further from airport center)
            dir_from_center = _calculate_heading(
                center, (last_aircraft.latitude, last_aircraft.longitude)
            )
            new_pos = _point_on_circle(
                last_aircraft.latitude, last_aircraft.longitude,
                dir_from_center, required_sep_deg
            )
            lat = new_pos[0] + random.uniform(-0.005, 0.005)
            lon = new_pos[1]
            alt = max(last_aircraft.altitude + 500, 600)

        # Pre-assign a gate so it shows as INBOUND on the gate status panel
        _init_gate_states()
        pre_gate = _find_available_gate()
        if pre_gate:
            _occupy_gate(icao24, pre_gate)

        # Snap waypoint_index to the closest approach waypoint to spawn position
        # so the aircraft doesn't chase a waypoint that's behind it
        approach_wps = _get_approach_waypoints(origin)
        best_wp_idx = 0
        if approach_wps:
            best_dist = float('inf')
            for wi, wp in enumerate(approach_wps):
                d = _distance_between((lat, lon), (wp[1], wp[0]))
                if d < best_dist:
                    best_dist = d
                    best_wp_idx = wi

        # Initialize speed from OpenAP descent profile at the spawn waypoint
        # to avoid the visible speed jump on the first tick when the profile
        # overrides the initial velocity.
        _total_wps = len(approach_wps) if approach_wps else 1
        _spawn_progress = best_wp_idx / max(1, _total_wps - 1)
        _prof_progress = 0.5 + 0.5 * _spawn_progress
        _dp = get_descent_profile(aircraft_type)
        _prof_alt, _prof_spd, _prof_vr = interpolate_profile(_dp, _prof_progress)
        vref = VREF_SPEEDS.get(aircraft_type, _DEFAULT_VREF)
        init_speed = max(vref, min(_prof_spd, MAX_SPEED_BELOW_FL100_KTS))

        return FlightState(
            icao24=icao24,
            callsign=callsign,
            latitude=lat,
            longitude=lon,
            altitude=alt + random.uniform(-30, 30),  # realistic ILS approach deviation (±30ft)
            velocity=init_speed + random.uniform(-5, 5),
            heading=_calculate_heading((lat, lon), center),
            vertical_rate=_prof_vr if _prof_vr else -800,
            on_ground=False,
            phase=phase,
            aircraft_type=aircraft_type,
            assigned_gate=pre_gate,
            waypoint_index=best_wp_idx,
            origin_airport=origin,
            destination_airport=destination,
        )

    elif phase == FlightPhase.PARKED:
        # Start at a gate, nose facing toward the nearest terminal center
        _init_gate_states()

        # Find an available gate
        gate = _find_available_gate()
        if gate is None:
            # All gates occupied - switch to approaching or enroute
            return _create_new_flight(icao24, callsign, FlightPhase.APPROACHING, origin=origin, destination=destination)

        lat, lon = get_gates()[gate]
        _occupy_gate(icao24, gate)
        emit_gate_event(icao24, callsign, gate, "occupy", aircraft_type)

        # Compute heading toward nearest terminal (or airport center as fallback)
        parked_heading = _get_parked_heading(lat, lon)

        # Offset aircraft away from terminal based on OSM geometry + aircraft dimensions
        standoff = _compute_gate_standoff(lat, lon, parked_heading, aircraft_type)
        lat, lon = _offset_position_by_heading(lat, lon, parked_heading, standoff)

        initial_time_at_gate = random.uniform(0, 300)  # 0-5 min pre-parked time

        # Build turnaround schedule and pre-advance to match elapsed time
        airline_code = callsign[:3] if callsign and len(callsign) >= 3 else ""
        combined_factor = AIRLINE_TURNAROUND_FACTOR.get(airline_code, _DEFAULT_AIRLINE_FACTOR)
        schedule = _build_turnaround_schedule(aircraft_type, airline_code, combined_factor)
        # Pre-advance phases that would already be started/done given initial_time_at_gate
        current_phase = ""
        for p_name in _GATE_PHASES:
            info = schedule[p_name]
            if initial_time_at_gate >= info["start_offset_s"] + info["duration_s"]:
                info["done"] = True
                info["started"] = True
            elif initial_time_at_gate >= info["start_offset_s"]:
                info["started"] = True
                current_phase = p_name
        if not current_phase:
            # Find first not-yet-started phase
            for p_name in _GATE_PHASES:
                if not schedule[p_name]["done"]:
                    current_phase = p_name
                    break

        return FlightState(
            icao24=icao24,
            callsign=callsign,
            latitude=lat,
            longitude=lon,
            altitude=0,
            velocity=0,
            heading=parked_heading,
            vertical_rate=0,
            on_ground=True,
            phase=phase,
            aircraft_type=aircraft_type,
            assigned_gate=gate,
            time_at_gate=initial_time_at_gate,
            origin_airport=origin,
            destination_airport=destination,
            parked_since=time.time() - initial_time_at_gate,
            turnaround_phase=current_phase,
            turnaround_schedule=schedule,
        )

    elif phase == FlightPhase.ENROUTE:
        # Spawn on edge of visibility circle at bearing from origin airport
        VISIBILITY_RADIUS_DEG = 0.4  # ~25 NM

        if origin:
            # Arriving flight: spawn at correct inbound bearing
            bearing_to_sfo = _bearing_from_airport(origin)
            # The aircraft appears FROM that bearing, so spawn on the circle at the reciprocal
            spawn_bearing = (bearing_to_sfo + 180) % 360
            center = get_airport_center()
            spawn_point = _point_on_circle(
                center[0], center[1],
                spawn_bearing,
                VISIBILITY_RADIUS_DEG + random.uniform(-0.05, 0.05),
            )
            lat, lon = spawn_point
            heading = _calculate_heading((lat, lon), center)
            # International = higher altitude
            alt = random.uniform(33000, 43000) if is_intl else random.uniform(28000, 39000)
        elif destination:
            # Departing flight that's already enroute: heading toward destination
            bearing = _bearing_to_airport(destination)
            # Spawn somewhere between airport and edge of circle
            dist = random.uniform(0.1, 0.3)
            center = get_airport_center()
            spawn_point = _point_on_circle(
                center[0], center[1], bearing, dist,
            )
            lat, lon = spawn_point
            heading = bearing + random.uniform(-5, 5)
            # Departing enroute: spawn at mid-climb altitude (visible as climbing)
            alt = random.uniform(10000, 25000)
        else:
            # No origin/destination — random position on the circle edge
            center = get_airport_center()
            bearing = random.uniform(0, 360)
            spawn_point = _point_on_circle(
                center[0], center[1],
                bearing,
                VISIBILITY_RADIUS_DEG + random.uniform(-0.1, 0.0),
            )
            lat, lon = spawn_point
            heading = _calculate_heading((lat, lon), center)
            # Hemispheric rule (ICAO): eastbound (0-179°) → odd FL, westbound (180-359°) → even FL
            if heading < 180:
                alt = random.choice([29000, 31000, 33000, 35000, 37000, 39000])  # odd FLs
            else:
                alt = random.choice([28000, 30000, 32000, 34000, 36000, 38000])  # even FLs

        # Departing enroute flights climb; arriving ones descend
        _is_departing_enroute = destination is not None and origin is None
        if _is_departing_enroute:
            vrate = random.uniform(800, 2000)  # Climbing
            vel = random.uniform(280, 400)
        else:
            vrate = random.uniform(-500, -100)  # Descending toward airport
            vel = random.uniform(400, 500)

        return FlightState(
            icao24=icao24,
            callsign=callsign,
            latitude=lat,
            longitude=lon,
            altitude=alt,
            velocity=vel,
            heading=heading,
            vertical_rate=vrate,
            on_ground=False,
            phase=phase,
            aircraft_type=aircraft_type,
            origin_airport=origin,
            destination_airport=destination,
        )

    elif phase == FlightPhase.TAXI_TO_GATE:
        # Just landed, taxiing from runway
        _init_gate_states()

        # Check if runway is occupied - if so, can't spawn here
        arrival_rwy = _get_arrival_runway_name()
        if not _is_runway_clear(arrival_rwy):
            return _create_new_flight(icao24, callsign, FlightPhase.APPROACHING, origin=origin, destination=destination)

        gate = _find_available_gate()
        if gate is None:
            # No gates available
            return _create_new_flight(icao24, callsign, FlightPhase.ENROUTE, origin=origin, destination=destination)

        # Compute taxi route from runway to gate (uses OSM graph when available)
        taxi_route = _get_taxi_waypoints_arrival(gate)
        wp = taxi_route[0]
        spawn_pos = (wp[1], wp[0])  # lat, lon

        # Check if taxiway start position is clear (no other taxiing aircraft)
        for other_icao24, other in _flight_states.items():
            if other.on_ground and other.phase in [FlightPhase.TAXI_TO_GATE, FlightPhase.TAXI_TO_RUNWAY]:
                dist = _distance_between(spawn_pos, (other.latitude, other.longitude))
                if dist < MIN_TAXI_SEPARATION_DEG * 2:  # Buffer for spawn position
                    # Taxiway congested - spawn as approaching instead
                    return _create_new_flight(icao24, callsign, FlightPhase.APPROACHING, origin=origin, destination=destination)

        _occupy_gate(icao24, gate)

        # Heading toward second waypoint (or gate if only one wp)
        if len(taxi_route) >= 2:
            heading = _calculate_heading(spawn_pos, (taxi_route[1][1], taxi_route[1][0]))
        else:
            heading = _calculate_heading(spawn_pos, get_gates()[gate])

        return FlightState(
            icao24=icao24,
            callsign=callsign,
            latitude=wp[1],
            longitude=wp[0],
            altitude=0,
            velocity=15,
            heading=heading,
            vertical_rate=0,
            on_ground=True,
            phase=phase,
            aircraft_type=aircraft_type,
            assigned_gate=gate,
            waypoint_index=0,
            origin_airport=origin,
            destination_airport=destination,
            taxi_route=taxi_route,
        )

    elif phase == FlightPhase.TAXI_TO_RUNWAY:
        # Departing, starting from a gate position
        _init_gate_states()

        # Find an available gate for the departing aircraft
        gate = _find_available_gate()
        if gate is None:
            # All gates occupied - can't spawn departing aircraft
            return _create_new_flight(icao24, callsign, FlightPhase.ENROUTE, origin=origin, destination=destination)

        lat, lon = get_gates()[gate]
        _occupy_gate(icao24, gate)

        # Compute departure taxi route from gate to runway (uses OSM graph when available)
        taxi_route = _get_taxi_waypoints_departure(gate)

        # Heading toward first departure waypoint
        if taxi_route:
            heading = _calculate_heading((lat, lon), (taxi_route[0][1], taxi_route[0][0]))
        else:
            heading = 180  # Fallback: south

        return FlightState(
            icao24=icao24,
            callsign=callsign,
            latitude=lat,
            longitude=lon,
            altitude=0,
            velocity=10,
            heading=heading,
            vertical_rate=0,
            on_ground=True,
            phase=phase,
            aircraft_type=aircraft_type,
            assigned_gate=gate,
            waypoint_index=0,
            origin_airport=origin,
            destination_airport=destination,
            taxi_route=taxi_route,
        )

    # Default: random enroute
    return _create_new_flight(icao24, callsign, FlightPhase.ENROUTE, origin=origin, destination=destination)


def _update_flight_state(state: FlightState, dt: float) -> FlightState:
    """Update a flight's state based on its current phase.

    Implements FAA/ICAO separation standards:
    - Approach: 3-6 NM based on wake turbulence category
    - Runway: Single occupancy (one aircraft at a time)
    - Taxi: Visual separation (~150-300 ft)
    """

    if state.phase == FlightPhase.APPROACHING:
        # Descend toward airport following approach waypoints WITH SEPARATION
        # Primary transition trigger: altitude <= DECISION_HEIGHT_FT (Cat I ILS DA)
        # Safety fallback: waypoint exhaustion
        approach_wps = _get_approach_waypoints(state.origin_airport)

        # Helper: execute go-around (missed approach procedure)
        # Transitions to ENROUTE so the aircraft flies FORWARD (on runway heading),
        # climbs to missed approach altitude, then re-sequences via the holding
        # pattern / approach capacity logic — instead of flying backward to wp 0.
        def _execute_go_around(reason: str = "runway_busy") -> None:
            state.go_around_count += 1
            state.holding_phase_time = 0.0
            state.holding_inbound = True

            # Missed approach: climb to 1500ft AGL minimum
            state.go_around_target_alt = max(1500.0, state.altitude + 300)
            state.vertical_rate = 1500

            # Missed approach speed: gradual acceleration to Vref + 20 kts
            vref_ga = VREF_SPEEDS.get(state.aircraft_type, _DEFAULT_VREF)
            target_ga_speed = vref_ga + 20
            if target_ga_speed > state.velocity:
                state.velocity = min(target_ga_speed, state.velocity + 10)

            # Keep current heading — the aircraft is already pointing in the
            # correct approach direction from _smooth_heading during APPROACHING.
            # Don't override with _get_runway_heading() which depends on OSM
            # geoPoint ordering and could be 180° off.

            # Transition to ENROUTE which has holding pattern + re-approach logic
            emit_phase_transition(
                state.icao24, state.callsign,
                FlightPhase.APPROACHING.value, FlightPhase.ENROUTE.value,
                state.latitude, state.longitude, state.altitude,
                state.aircraft_type, state.assigned_gate,
            )
            _set_phase(state, FlightPhase.ENROUTE)
            state.waypoint_index = 0

            logger.info(
                "GO-AROUND #%d %s (%s): %s at %.0fft → ENROUTE for re-sequence",
                state.go_around_count, state.callsign, state.aircraft_type,
                reason, state.altitude,
            )
            diag_log(
                "GO_AROUND", datetime.now(timezone.utc),
                icao24=state.icao24, callsign=state.callsign,
                reason=reason, alt=state.altitude,
                count=state.go_around_count,
            )

        if state.waypoint_index < len(approach_wps):
            wp = approach_wps[state.waypoint_index]
            target = (wp[1], wp[0])  # lat, lon
            target_alt = wp[2]

            # CHECK SEPARATION before moving
            has_separation = _check_approach_separation(state)
            queue_pos = _get_approach_queue_position(state.icao24)

            if has_separation:
                # --- OpenAP-based descent profile ---
                total_wps = len(approach_wps)
                progress = state.waypoint_index / max(1, total_wps - 1)
                # Map approach progress (0=far out, 1=threshold) to descent
                # profile progress (0=TOD, 1=touchdown).  Approach waypoints
                # only cover the last ~15 NM, which is roughly the final 50%
                # of a full descent.  We map [0,1] → [0.5, 1.0].
                profile_progress = 0.5 + 0.5 * progress
                desc_prof = get_descent_profile(state.aircraft_type)
                prof_alt, prof_spd, prof_vr = interpolate_profile(desc_prof, profile_progress)

                # Speed from profile (respect separation slow-down)
                speed_slow = 1.0
                ahead = _find_aircraft_ahead_on_approach(state)
                if ahead:
                    dist = _distance_nm((state.latitude, state.longitude),
                                       (ahead.latitude, ahead.longitude))
                    req_sep = _get_required_separation(ahead.aircraft_type, state.aircraft_type) / NM_TO_DEG
                    if dist < req_sep * 1.5:
                        speed_slow = 0.5

                # Clamp speed: altitude-aware Vref floor + 250kt ceiling
                # Smooth acceleration/deceleration (max 5 kts/s) to prevent
                # visible speed jumps in 30s snapshot intervals (A05 fix).
                vref = VREF_SPEEDS.get(state.aircraft_type, _DEFAULT_VREF)
                raw_speed = min(prof_spd * speed_slow, MAX_SPEED_BELOW_FL100_KTS)
                if state.altitude < 1000:
                    # Below 1000ft: hard ceiling at Vref + 30 (stabilized approach)
                    # This also handles post-go-around re-entry at low altitude
                    target_speed = min(vref + 30, max(vref, raw_speed))
                elif state.altitude < 2000 or progress > 0.85:
                    target_speed = max(vref, raw_speed)
                else:
                    target_speed = max(vref * 0.9, raw_speed)
                max_speed_change = 5.0 * dt  # 5 kts/s
                if target_speed > state.velocity:
                    state.velocity = min(target_speed, state.velocity + max_speed_change)
                elif target_speed < state.velocity:
                    state.velocity = max(target_speed, state.velocity - max_speed_change)

                # Move based on actual velocity
                speed_deg = state.velocity * _KTS_TO_DEG_PER_SEC * dt
                dist_to_wp = _distance_between((state.latitude, state.longitude), target)
                if dist_to_wp > 1e-8:
                    dlat = target[0] - state.latitude
                    dlon = target[1] - state.longitude
                    ratio = min(speed_deg / dist_to_wp, 1.0)
                    state.latitude += dlat * ratio
                    state.longitude += dlon * ratio

                # Go-around climb: if target alt is set, climb gradually (O05 fix)
                if state.go_around_target_alt > 0 and state.altitude < state.go_around_target_alt:
                    climb_fps = 25.0  # ~1500 ft/min
                    state.altitude = min(state.go_around_target_alt, state.altitude + climb_fps * dt)
                    state.vertical_rate = 1500
                    if state.altitude >= state.go_around_target_alt:
                        state.go_around_target_alt = 0.0  # Done climbing, resume descent
                else:
                    # Altitude from profile — use OpenAP vertical rate (ft/min→ft/s)
                    # instead of flat 500/tick for smooth, realistic descent.
                    # Floor at 25 ft/s (~1500 fpm) to maintain approach separation.
                    state.go_around_target_alt = 0.0
                    descent_fps = max(25.0, min(30.0, abs(prof_vr) / 60.0)) if prof_vr else 25.0
                    effective_target = min(prof_alt, target_alt)
                    prev_alt = state.altitude
                    state.altitude = max(float(DECISION_HEIGHT_FT), _interpolate_altitude(state.altitude, effective_target, descent_fps * dt))
                    # Set vertical_rate to match actual altitude direction (O05 fix):
                    # after go-around, waypoint target may be higher than current alt,
                    # causing a climb. Report positive vrate so snapshots are consistent.
                    if state.altitude > prev_alt:
                        state.vertical_rate = abs(prof_vr) if prof_vr else 1500
                    else:
                        state.vertical_rate = prof_vr

                # P1: Decision height-based approach→landing transition
                # Transition when altitude at or below Cat I ILS decision height
                # AND runway is clear. If busy, aircraft continues to waypoint
                # exhaustion where the holding pattern handles the wait.
                if state.altitude <= DECISION_HEIGHT_FT:
                    arrival_rwy = _get_arrival_runway_name()
                    if _is_runway_clear(arrival_rwy):
                        emit_phase_transition(
                            state.icao24, state.callsign,
                            FlightPhase.APPROACHING.value, FlightPhase.LANDING.value,
                            state.latitude, state.longitude, state.altitude,
                            state.aircraft_type, state.assigned_gate,
                        )
                        _set_phase(state, FlightPhase.LANDING)
                        state.waypoint_index = 0
                        _occupy_runway(state.icao24, arrival_rwy)
                    else:
                        # P2: Runway busy at decision height → go-around
                        _execute_go_around("runway_busy")
                        return state
            else:
                # Too close to aircraft ahead - slow down but keep creeping forward
                # so the map marker doesn't freeze in place (A03 stuck marker fix)
                vref = VREF_SPEEDS.get(state.aircraft_type, _DEFAULT_VREF)
                # Smooth deceleration: max 5 kts/s (matches accel rate in A05 fix)
                state.velocity = max(vref * 0.7, state.velocity - 5.0 * dt)
                state.vertical_rate = -200
                # Creep forward at reduced speed to avoid stuck markers
                creep_deg = state.velocity * 0.3 * _KTS_TO_DEG_PER_SEC * dt
                dist_to_wp = _distance_between((state.latitude, state.longitude), target)
                if dist_to_wp > 1e-8:
                    dlat = target[0] - state.latitude
                    dlon = target[1] - state.longitude
                    ratio = min(creep_deg / dist_to_wp, 0.3)
                    state.latitude += dlat * ratio
                    state.longitude += dlon * ratio

            # Smooth heading toward waypoint (max 3°/s standard rate turn)
            target_hdg = _calculate_heading((state.latitude, state.longitude), target)
            state.heading = _smooth_heading(state.heading, target_hdg, 3.0, dt)

            # Check if reached waypoint
            if _distance_between((state.latitude, state.longitude), target) < 0.003:
                state.waypoint_index += 1
        else:
            # Safety fallback: waypoint exhaustion
            if state.altitude > 1000:
                # Still too high — go around rather than starting landing from altitude
                _execute_go_around("high_altitude_at_threshold")
            else:
                arrival_rwy = _get_arrival_runway_name()
                if _is_runway_clear(arrival_rwy):
                    emit_phase_transition(
                        state.icao24, state.callsign,
                        FlightPhase.APPROACHING.value, FlightPhase.LANDING.value,
                        state.latitude, state.longitude, state.altitude,
                        state.aircraft_type, state.assigned_gate,
                    )
                    _set_phase(state, FlightPhase.LANDING)
                    state.waypoint_index = 0
                    _occupy_runway(state.icao24, arrival_rwy)
                else:
                    # Runway busy at waypoint exhaustion — execute missed approach
                    # per ICAO Doc 8168: climb to missed approach altitude, re-sequence
                    _execute_go_around("runway_busy_at_threshold")

    elif state.phase == FlightPhase.LANDING:
        # Final touchdown sequence - land on active arrival runway
        # Runway should already be marked as occupied
        thr = _get_runway_threshold()
        runway_touchdown = (thr[1], thr[0]) if thr else (RUNWAY_28L_EAST[1], RUNWAY_28L_EAST[0])  # lat, lon

        # Get runway far end for rollout direction (aircraft rolls past threshold)
        rwy_data = _get_osm_primary_runway()
        if rwy_data:
            _, far_end_lonlat, rwy_hdg = _osm_runway_endpoints(rwy_data)
            runway_far_end = (far_end_lonlat[1], far_end_lonlat[0])  # lat, lon
        else:
            runway_far_end = (RUNWAY_28L_WEST[1], RUNWAY_28L_WEST[0])
            rwy_hdg = 284.0

        # Aircraft moves along the runway heading during landing.
        # Use heading-based movement (not _move_toward) so the aircraft
        # continues rolling past the runway far-end marker instead of
        # clamping — real aircraft roll out well past the midpoint.
        speed_deg = state.velocity * _KTS_TO_DEG_PER_SEC * dt
        rwy_hdg_rad = math.radians(rwy_hdg)
        state.latitude += speed_deg * math.cos(rwy_hdg_rad)
        state.longitude += speed_deg * math.sin(rwy_hdg_rad) / math.cos(math.radians(state.latitude))
        state.heading = rwy_hdg

        if state.altitude > 0:
            # Airborne: descend to touchdown on the glideslope (~750 fpm)
            descent_fpm = 750
            state.altitude = max(0, state.altitude - (descent_fpm / 60.0) * dt)
            if state.altitude <= 0:
                state.altitude = 0
                state.on_ground = True
                state.vertical_rate = 0
        else:
            # On-ground rollout: decelerate from touchdown speed to taxi speed
            # Typical rollout: 1500-2500m, decel ~2 kts/s (reverse thrust + brakes)
            state.altitude = 0
            state.on_ground = True
            state.vertical_rate = 0
            state.velocity = max(25, state.velocity - 2.0 * dt)

        if state.on_ground and state.velocity <= 30:
            # Rollout complete — exit runway to taxiway
            emit_phase_transition(
                state.icao24, state.callsign,
                FlightPhase.LANDING.value, FlightPhase.TAXI_TO_GATE.value,
                state.latitude, state.longitude, state.altitude,
                state.aircraft_type, state.assigned_gate,
            )
            _set_phase(state, FlightPhase.TAXI_TO_GATE)
            # Release runway when exiting to taxiway
            arrival_rwy = _get_arrival_runway_name()
            _release_runway(state.icao24, arrival_rwy)
            # Reuse pre-assigned gate from approach if still held, else find new one
            _init_gate_states()
            pre_gate = state.assigned_gate
            if pre_gate and pre_gate in _gate_states and _gate_states[pre_gate].occupied_by == state.icao24:
                # Keep pre-assigned gate
                emit_gate_event(state.icao24, state.callsign, pre_gate, "assign", state.aircraft_type)
                state.taxi_route = _get_taxi_waypoints_arrival(pre_gate)
            else:
                available_gate = _find_available_gate()
                if available_gate:
                    # Release old pre-assigned gate if it was held
                    if pre_gate and pre_gate in _gate_states and _gate_states[pre_gate].occupied_by == state.icao24:
                        _release_gate(state.icao24, pre_gate)
                    state.assigned_gate = available_gate
                    _occupy_gate(state.icao24, available_gate)
                    emit_gate_event(state.icao24, state.callsign, available_gate, "assign", state.aircraft_type)
                    state.taxi_route = _get_taxi_waypoints_arrival(available_gate)
                else:
                    # All gates occupied — defer assignment to taxi phase.
                    # The TAXI_TO_GATE handler retries gate assignment every
                    # few seconds, so a gate freed by a pushback will be
                    # picked up before the aircraft reaches the ramp.
                    if pre_gate and pre_gate in _gate_states and _gate_states[pre_gate].occupied_by == state.icao24:
                        _release_gate(state.icao24, pre_gate)
                    state.assigned_gate = None
                    state.taxi_route = None  # Use default arrival waypoints

            # Prepend current position to taxi route so the aircraft taxis
            # smoothly from the runway rollout end to the first taxiway
            # waypoint, instead of teleporting to it.
            taxi_wps = state.taxi_route or TAXI_WAYPOINTS_ARRIVAL
            current_pos = (state.longitude, state.latitude)  # (lon, lat) format
            if taxi_wps:
                state.taxi_route = [current_pos] + list(taxi_wps)
            else:
                state.taxi_route = [current_pos]
            state.waypoint_index = 1  # Already at wp 0 (current pos)

    elif state.phase == FlightPhase.TAXI_TO_GATE:
        # Taxi along waypoints to assigned gate WITH SEPARATION

        # First, ensure we have an assigned gate before proceeding
        if state.assigned_gate is None:
            now = time.time()
            if now < state.gate_retry_at:
                # Still waiting for retry — micro-move to avoid stuck marker (A03)
                state.velocity = 1
                jitter = random.uniform(-0.00002, 0.00002)
                state.latitude += jitter
                state.longitude += jitter
                return state
            available_gate = _find_available_gate()
            if not available_gate:
                available_gate = _find_overflow_gate()
            if available_gate:
                state.assigned_gate = available_gate
                _occupy_gate(state.icao24, available_gate)
                state.taxi_route = _get_taxi_waypoints_arrival(available_gate)
                state.gate_retry_at = 0.0
            else:
                # No gates available — retry in 5 seconds (sim time)
                state.gate_retry_at = now + 5.0
                state.velocity = 1
                jitter = random.uniform(-0.00002, 0.00002)
                state.latitude += jitter
                state.longitude += jitter
                return state

        # Use cached taxi route (dynamic from OSM graph or fallback)
        taxi_wps = state.taxi_route or TAXI_WAYPOINTS_ARRIVAL
        if state.waypoint_index < len(taxi_wps):
            wp = taxi_wps[state.waypoint_index]
            target = (wp[1], wp[0])

            # Graduated taxi separation — slow down near traffic, stop if too close
            speed_factor = _taxi_speed_factor(state)
            if speed_factor > 0:
                # Arriving aircraft taxi faster on the initial straight
                # (ATC clears runway exits quickly to maintain arrival rate)
                base_speed = TAXI_SPEED_STRAIGHT_KTS + 5  # 30 kts for inbound
                taxi_speed = base_speed * speed_factor
                speed_deg = taxi_speed * _KTS_TO_DEG_PER_SEC * dt
                new_pos = _move_toward((state.latitude, state.longitude), target, speed_deg)
                state.latitude, state.longitude = new_pos
                state.velocity = taxi_speed
            elif speed_factor < 0:
                # Head-on hold: yielding to oncoming traffic — jitter in place,
                # do NOT creep toward waypoint (would pass through oncoming aircraft)
                state.velocity = 0
                speed_deg = 0
                jitter = random.uniform(-0.00002, 0.00002)
                state.latitude += jitter
                state.longitude += jitter
            else:
                # Factor 0 = traffic ahead within separation threshold.
                # Full stop — no creep — to maintain queue spacing.
                state.velocity = 0
                speed_deg = 0

            # Smooth heading toward waypoint (max 5°/s for taxi turns)
            target_hdg = _calculate_heading((state.latitude, state.longitude), target)
            state.heading = _smooth_heading(state.heading, target_hdg, 5.0, dt)

            if _distance_between((state.latitude, state.longitude), target) < max(speed_deg, 0.0005):
                state.waypoint_index += 1
        else:
            # Head to gate
            target = get_gates()[state.assigned_gate]

            # Check if our gate is still available
            _init_gate_states()
            gate_state = _gate_states.get(state.assigned_gate)
            if gate_state and gate_state.occupied_by and gate_state.occupied_by != state.icao24:
                # Gate was taken, find another
                new_gate = _find_available_gate()
                if new_gate:
                    state.assigned_gate = new_gate
                    _occupy_gate(state.icao24, new_gate)
                    target = get_gates()[new_gate]
                else:
                    # No gates — try overflow gate
                    new_gate = _find_overflow_gate()
                    if new_gate:
                        state.assigned_gate = new_gate
                        _occupy_gate(state.icao24, new_gate)
                        target = get_gates()[new_gate]
                    else:
                        state.velocity = 0
                        return state

            speed_factor = _taxi_speed_factor(state)
            if speed_factor > 0:
                ramp_speed = TAXI_SPEED_RAMP_KTS * speed_factor
                speed_deg = ramp_speed * _KTS_TO_DEG_PER_SEC * dt
                new_pos = _move_toward((state.latitude, state.longitude), target, speed_deg)
                state.latitude, state.longitude = new_pos
                state.velocity = ramp_speed
            else:
                state.velocity = 0
                speed_deg = 0

            target_hdg = _calculate_heading((state.latitude, state.longitude), target)
            state.heading = _smooth_heading(state.heading, target_hdg, 5.0, dt)

            if _distance_between((state.latitude, state.longitude), target) < max(speed_deg, 0.0003):
                emit_phase_transition(
                    state.icao24, state.callsign,
                    FlightPhase.TAXI_TO_GATE.value, FlightPhase.PARKED.value,
                    state.latitude, state.longitude, state.altitude,
                    state.aircraft_type, state.assigned_gate,
                )
                emit_gate_event(state.icao24, state.callsign, state.assigned_gate, "occupy", state.aircraft_type)
                _set_phase(state, FlightPhase.PARKED)
                state.velocity = 0
                state.time_at_gate = 0
                state.parked_since = time.time()
                _occupy_gate(state.icao24, state.assigned_gate)
                # Record inbound delay for reactionary delay prediction
                # (TAXI_TO_GATE → PARKED is always an arrival)
                if state.assigned_gate:
                    _h = (hash(state.icao24) ^ hash(state.callsign[:3] if state.callsign else "")) & 0xFFFF
                    inbound_delay = (5 + ((_h >> 8) % 41)) if ((_h >> 4) % 5 == 0) else 0
                    _gate_last_delay[state.assigned_gate] = float(inbound_delay)
                # Snap to gate position, then offset away from terminal
                gate_pos = get_gates().get(state.assigned_gate)
                if gate_pos:
                    state.latitude, state.longitude = gate_pos
                parked_heading = _get_parked_heading(state.latitude, state.longitude)
                state.heading = parked_heading
                standoff = _compute_gate_standoff(
                    state.latitude, state.longitude, parked_heading, state.aircraft_type
                )
                state.latitude, state.longitude = _offset_position_by_heading(
                    state.latitude, state.longitude, parked_heading, standoff
                )
                # Build turnaround schedule
                airline_code = state.callsign[:3] if state.callsign and len(state.callsign) >= 3 else ""
                airline_factor = AIRLINE_TURNAROUND_FACTOR.get(airline_code, _DEFAULT_AIRLINE_FACTOR)
                weather_factor = _get_turnaround_weather_factor()
                congestion_factor = _get_turnaround_congestion_factor()
                intl_factor = _get_turnaround_international_factor(state)
                dow_factor = _get_turnaround_day_of_week_factor()
                combined = airline_factor * weather_factor * congestion_factor * intl_factor * dow_factor
                state.turnaround_schedule = _build_turnaround_schedule(
                    state.aircraft_type, airline_code, combined,
                )
                state.turnaround_phase = "chocks_on"

    elif state.phase == FlightPhase.PARKED:
        # Stay at gate for some time, then pushback
        state.velocity = 0
        state.time_at_gate += dt

        # Progress turnaround sub-phases based on schedule
        if state.turnaround_schedule:
            active_phase = ""
            for p_name in _GATE_PHASES:
                info = state.turnaround_schedule.get(p_name)
                if info is None:
                    continue
                phase_end = info["start_offset_s"] + info["duration_s"]
                if not info["started"] and state.time_at_gate >= info["start_offset_s"]:
                    info["started"] = True
                    emit_turnaround_event(
                        state.icao24, state.callsign,
                        state.assigned_gate or "", p_name, "phase_start",
                        state.aircraft_type,
                    )
                if info["started"] and not info["done"] and state.time_at_gate >= phase_end:
                    info["done"] = True
                    emit_turnaround_event(
                        state.icao24, state.callsign,
                        state.assigned_gate or "", p_name, "phase_complete",
                        state.aircraft_type,
                    )
                if info["started"] and not info["done"]:
                    active_phase = p_name
            state.turnaround_phase = active_phase

        # Realistic turnaround: use calibrated BTS data if available,
        # otherwise fall back to GSE model timing
        if _calibration_gate_minutes > 0:
            # Calibrated: use BTS OTP median turnaround (already gate-only time)
            category = get_aircraft_category(state.aircraft_type)
            if category == "wide_body":
                gate_minutes = _calibration_gate_minutes * 1.4
            else:
                gate_minutes = _calibration_gate_minutes
        else:
            # Fallback: GSE model total minus taxi/pushback phases
            timing = get_turnaround_timing(state.aircraft_type)
            total_min = timing["total_minutes"]  # 45 min narrow-body, 90 min wide-body
            non_gate_min = (timing["phases"].get("arrival_taxi", 0)
                            + timing["phases"].get("pushback", 0)
                            + timing["phases"].get("departure_taxi", 0))
            gate_minutes = total_min - non_gate_min
        gate_seconds = gate_minutes * 60
        # Feature-dependent turnaround: airline + weather + congestion + international
        airline_code = state.callsign[:3] if state.callsign and len(state.callsign) >= 3 else ""
        airline_factor = AIRLINE_TURNAROUND_FACTOR.get(airline_code, _DEFAULT_AIRLINE_FACTOR)
        weather_factor = _get_turnaround_weather_factor()
        congestion_factor = _get_turnaround_congestion_factor()
        intl_factor = _get_turnaround_international_factor(state)
        dow_factor = _get_turnaround_day_of_week_factor()
        combined_factor = airline_factor * weather_factor * congestion_factor * intl_factor * dow_factor
        # +/-10% jitter (reduced from 20% since factors explain more variance)
        target = gate_seconds * combined_factor * random.uniform(0.9, 1.1)
        if state.time_at_gate > target:
            # Ensure correct origin/dest for departure: origin=local, dest=new airport
            local_iata = get_current_airport_iata()
            if state.origin_airport != local_iata:
                # Aircraft arrived here — swap to departing: origin=local, dest=new
                state.origin_airport = local_iata
                state.destination_airport = _pick_random_destination()
            elif not state.destination_airport or state.destination_airport == local_iata:
                # No valid destination set — pick one
                state.destination_airport = _pick_random_destination()
            emit_phase_transition(
                state.icao24, state.callsign,
                FlightPhase.PARKED.value, FlightPhase.PUSHBACK.value,
                state.latitude, state.longitude, state.altitude,
                state.aircraft_type, state.assigned_gate,
            )
            _set_phase(state, FlightPhase.PUSHBACK)
            state.phase_progress = 0

    elif state.phase == FlightPhase.PUSHBACK:
        # Slow pushback from gate WITH separation check
        # Real pushback: tug pushes aircraft ~50-80m back from the gate onto the apron/taxiway.
        # Total phase is ~60s of movement (at 3kts ≈ 90m).
        pb_heading = _get_pushback_heading(state.assigned_gate) if state.assigned_gate else 180.0
        state.phase_progress += dt / 60.0  # ~60s for pushback movement
        if _check_taxi_separation(state):
            state.velocity = TAXI_SPEED_PUSHBACK_KTS
            pb_rad = math.radians(pb_heading)
            pb_speed_deg = TAXI_SPEED_PUSHBACK_KTS * _KTS_TO_DEG_PER_SEC * dt
            state.latitude += pb_speed_deg * math.cos(pb_rad)
            state.longitude += pb_speed_deg * math.sin(pb_rad)
        else:
            state.velocity = 0  # Hold movement if blocked, but timer still advances

        # Smooth heading rotation: nose swings from parked heading toward
        # the pushback nose direction (opposite of movement) over the pushback duration.
        nose_target = (pb_heading + 180) % 360
        state.heading = _smooth_heading(state.heading, nose_target, 3.0, dt)

        if state.phase_progress >= 1.0:
            # Release gate when clear of it
            if state.assigned_gate:
                _release_gate(state.icao24, state.assigned_gate)
                emit_gate_event(state.icao24, state.callsign, state.assigned_gate, "release", state.aircraft_type)
            emit_phase_transition(
                state.icao24, state.callsign,
                FlightPhase.PUSHBACK.value, FlightPhase.TAXI_TO_RUNWAY.value,
                state.latitude, state.longitude, state.altitude,
                state.aircraft_type, state.assigned_gate,
            )
            _set_phase(state, FlightPhase.TAXI_TO_RUNWAY)
            state.waypoint_index = 0
            state.taxi_route = _get_taxi_waypoints_departure(state.assigned_gate) if state.assigned_gate else None

    elif state.phase == FlightPhase.TAXI_TO_RUNWAY:
        # Taxi to runway with graduated separation
        taxi_wps = state.taxi_route or TAXI_WAYPOINTS_DEPARTURE
        if state.waypoint_index < len(taxi_wps):
            wp = taxi_wps[state.waypoint_index]
            target = (wp[1], wp[0])

            speed_factor = _taxi_speed_factor(state)
            if speed_factor > 0:
                taxi_speed = TAXI_SPEED_STRAIGHT_KTS * speed_factor
                speed_deg = taxi_speed * _KTS_TO_DEG_PER_SEC * dt
                new_pos = _move_toward((state.latitude, state.longitude), target, speed_deg)
                state.latitude, state.longitude = new_pos
                state.velocity = taxi_speed
            elif speed_factor < 0:
                # Head-on hold: yielding to oncoming traffic — jitter in place
                state.velocity = 0
                jitter = random.uniform(-0.00002, 0.00002)
                state.latitude += jitter
                state.longitude += jitter
                speed_deg = 0
            else:
                # Factor 0 = traffic ahead within separation threshold.
                # Full stop — no creep — to maintain queue spacing.
                state.velocity = 0
                speed_deg = 0

            # Smooth heading toward waypoint (max 5°/s for taxi turns)
            target_hdg = _calculate_heading((state.latitude, state.longitude), target)
            state.heading = _smooth_heading(state.heading, target_hdg, 5.0, dt)

            if _distance_between((state.latitude, state.longitude), target) < max(speed_deg, 0.0005):
                state.waypoint_index += 1
        elif state.departure_queue_hold_s > 0:
            # Calibrated departure queue hold — simulates real-world queue time
            # at the runway hold line that the short waypoint path doesn't capture.
            state.departure_queue_hold_s -= dt
            # Creep forward slowly (1kt) so the marker doesn't freeze on screen
            _, _, dep_hdg, _ = _get_takeoff_runway_geometry()
            creep_speed = 1.0
            speed_deg = creep_speed * _KTS_TO_DEG_PER_SEC * dt
            # Move toward the runway threshold to form a visible queue
            thr_start, _, _, _ = _get_takeoff_runway_geometry()
            if thr_start:
                thr_pos = (thr_start[1], thr_start[0])
                new_pos = _move_toward((state.latitude, state.longitude), thr_pos, speed_deg)
                state.latitude, state.longitude = new_pos
            state.velocity = creep_speed
            state.heading = _smooth_heading(state.heading, dep_hdg, 5.0, dt)
        else:
            # Smoothly face the runway at the hold line
            _, _, dep_hdg, _ = _get_takeoff_runway_geometry()
            state.heading = _smooth_heading(state.heading, dep_hdg, 5.0, dt)
            # Compute departure queue hold once when aircraft first reaches hold line
            if not state.departure_queue_set and _calibration_taxi_out_target_s > 0:
                # Target total taxi-out = waypoint_travel + queue_hold
                # queue_hold = target - waypoint_estimate, with ±20% jitter
                queue_base = max(0.0, _calibration_taxi_out_target_s - _calibration_taxi_out_waypoint_s)
                state.departure_queue_hold_s = queue_base * random.uniform(0.80, 1.20)
                state.departure_queue_set = True
                if state.departure_queue_hold_s > 0:
                    state.velocity = 0
                    # Skip runway check this tick — start holding
                    return state

            # At runway hold line - check runway clear AND departure wake separation
            dep_rwy = _get_departure_runway_name()
            runway_clear = _is_runway_clear(dep_rwy)
            if runway_clear:
                # Check departure wake turbulence separation (FAA 7110.65 5-8-1)
                runway_st = _get_runway_state(dep_rwy)
                elapsed = time.time() - runway_st.last_departure_time
                lead_cat = runway_st.last_departure_type
                follow_cat = _get_wake_category(state.aircraft_type)
                required = DEPARTURE_SEPARATION_S.get(
                    (lead_cat, follow_cat), DEFAULT_DEPARTURE_SEPARATION_S
                )
                if elapsed >= required:
                    emit_phase_transition(
                        state.icao24, state.callsign,
                        FlightPhase.TAXI_TO_RUNWAY.value, FlightPhase.TAKEOFF.value,
                        state.latitude, state.longitude, state.altitude,
                        state.aircraft_type, state.assigned_gate,
                    )
                    _set_phase(state, FlightPhase.TAKEOFF)
                    _, _, dep_hdg, _ = _get_takeoff_runway_geometry()
                    state.heading = dep_hdg
                    state.takeoff_subphase = "lineup"
                    state.phase_progress = 0.0
                    state.takeoff_roll_dist_ft = 0.0
                    state.sid_name = _get_sid_name(state.destination_airport)
                    _occupy_runway(state.icao24, dep_rwy)
                else:
                    # Hold short: wake separation not yet met — creep/wiggle
                    state.velocity = 1
                    # Micro-movement to avoid stuck marker (A03 fix)
                    _, _, dep_hdg, _ = _get_takeoff_runway_geometry()
                    jitter = random.uniform(-0.00002, 0.00002)
                    state.latitude += jitter
                    state.longitude += jitter
            else:
                # Hold short of runway — creep to avoid frozen marker
                state.velocity = 1
                _, _, dep_hdg, _ = _get_takeoff_runway_geometry()
                jitter = random.uniform(-0.00002, 0.00002)
                state.latitude += jitter
                state.longitude += jitter

    elif state.phase == FlightPhase.TAKEOFF:
        # Realistic takeoff with sub-phases (14 CFR 25.107/111)
        perf = TAKEOFF_PERFORMANCE.get(state.aircraft_type, _DEFAULT_TAKEOFF_PERF)
        v1, vr, v2, accel_rate, climb_fpm = perf

        # Dynamic runway geometry (OSM-aware with SFO fallback)
        rwy_start, rwy_end, rwy_heading, rwy_len_ft = _get_takeoff_runway_geometry()
        rwy_dlat = rwy_end[0] - rwy_start[0]
        rwy_dlon = rwy_end[1] - rwy_start[1]
        rwy_len_deg = math.sqrt(rwy_dlat**2 + rwy_dlon**2)

        state.heading = rwy_heading

        if state.takeoff_subphase == "lineup":
            # Align on runway centerline, brief pause (~3s)
            state.velocity = 0
            state.on_ground = True
            state.phase_progress += dt
            # Snap to runway start position
            state.latitude = rwy_start[0]
            state.longitude = rwy_start[1]
            if state.phase_progress >= 3.0:
                state.takeoff_subphase = "roll"
                state.phase_progress = 0.0
                state.takeoff_roll_dist_ft = 0.0

        elif state.takeoff_subphase == "roll":
            # Ground roll: accelerate at aircraft-specific rate until VR
            state.velocity = min(state.velocity + accel_rate * dt, vr)
            state.on_ground = True
            # Accumulate ground roll distance
            velocity_ft_s = state.velocity * 1.6878  # knots to ft/s
            state.takeoff_roll_dist_ft += velocity_ft_s * dt
            # Interpolate position along runway centerline
            roll_frac = min(state.takeoff_roll_dist_ft / rwy_len_ft, 0.95)
            state.latitude = rwy_start[0] + rwy_dlat * roll_frac
            state.longitude = rwy_start[1] + rwy_dlon * roll_frac
            if state.velocity >= vr:
                state.takeoff_subphase = "rotate"
                state.phase_progress = 0.0

        elif state.takeoff_subphase == "rotate":
            # Rotation: nose pitches up, reduced acceleration (~3s)
            state.velocity = min(state.velocity + accel_rate * 0.8 * dt, v2 + 5)
            state.on_ground = True
            # Still rolling on ground during rotation
            velocity_ft_s = state.velocity * 1.6878
            state.takeoff_roll_dist_ft += velocity_ft_s * dt
            roll_frac = min(state.takeoff_roll_dist_ft / rwy_len_ft, 0.98)
            state.latitude = rwy_start[0] + rwy_dlat * roll_frac
            state.longitude = rwy_start[1] + rwy_dlon * roll_frac
            # Ramp vertical rate from 0 toward 500 fpm, start climbing
            state.phase_progress += dt
            state.vertical_rate = min(500 * (state.phase_progress / 3.0), 500)
            state.altitude += state.vertical_rate / 60.0 * dt
            if state.phase_progress >= 3.0 or state.velocity >= v2:
                state.takeoff_subphase = "liftoff"
                state.phase_progress = 0.0
                state.on_ground = False  # Wheels leave the ground

        elif state.takeoff_subphase == "liftoff":
            # Wheels off ground, climb to 35 ft screen height
            state.on_ground = False
            state.velocity = min(state.velocity + accel_rate * 0.5 * dt, v2 + 10)
            # Ramp vertical rate from 500 toward initial climb rate
            state.phase_progress += dt
            ramp = min(state.phase_progress / 5.0, 1.0)
            state.vertical_rate = 500 + (climb_fpm - 500) * ramp
            state.altitude += state.vertical_rate / 60.0 * dt
            # Continue along runway heading
            speed_deg = state.velocity * _KTS_TO_DEG_PER_SEC * dt
            state.latitude += (rwy_dlat / rwy_len_deg) * speed_deg
            state.longitude += (rwy_dlon / rwy_len_deg) * speed_deg
            if state.altitude >= 35:
                state.takeoff_subphase = "initial_climb"
                state.phase_progress = 0.0

        elif state.takeoff_subphase == "initial_climb":
            # Climb from 35 ft to 500 ft, then transition to DEPARTING
            # 14 CFR 25.111: min 2.4% net climb gradient, all-engine
            state.on_ground = False
            state.velocity = min(state.velocity + accel_rate * 0.3 * dt, v2 + 10)
            state.vertical_rate = climb_fpm
            state.altitude += climb_fpm / 60.0 * dt
            # Continue along runway heading (noise abatement: no turns below 400 ft)
            speed_deg = state.velocity * _KTS_TO_DEG_PER_SEC * dt
            state.latitude += (rwy_dlat / rwy_len_deg) * speed_deg
            state.longitude += (rwy_dlon / rwy_len_deg) * speed_deg

            if state.altitude >= 500:
                # Release runway and transition to DEPARTING
                _release_runway(state.icao24, _get_departure_runway_name(), state.aircraft_type)
                emit_phase_transition(
                    state.icao24, state.callsign,
                    FlightPhase.TAKEOFF.value, FlightPhase.DEPARTING.value,
                    state.latitude, state.longitude, state.altitude,
                    state.aircraft_type, state.assigned_gate,
                )
                _set_phase(state, FlightPhase.DEPARTING)
                state.waypoint_index = 0
                state.takeoff_subphase = "lineup"  # Reset for next use
                state.takeoff_roll_dist_ft = 0.0

    elif state.phase == FlightPhase.DEPARTING:
        # Climb out following departure path (destination-aware turn)
        departure_wps = _get_departure_waypoints(state.destination_airport)
        if state.waypoint_index < len(departure_wps):
            wp = departure_wps[state.waypoint_index]
            target = (wp[1], wp[0])
            target_alt = wp[2]

            # --- OpenAP-based climb profile ---
            total_wps = len(departure_wps)
            progress = state.waypoint_index / max(1, total_wps - 1)
            # Departure waypoints cover initial climb only (~first 40% of full climb)
            profile_progress = 0.4 * progress
            climb_prof = get_climb_profile(state.aircraft_type)
            prof_alt, prof_spd, prof_vr = interpolate_profile(climb_prof, profile_progress)

            # Speed from profile, respect 250kt below FL100
            target_spd = min(prof_spd, MAX_SPEED_BELOW_FL100_KTS) if state.altitude < 10000 else prof_spd
            # Limit acceleration to ~2 kts/s (realistic for commercial jets)
            max_accel = 2.0 * dt  # kts per tick
            if target_spd > state.velocity:
                state.velocity = min(target_spd, state.velocity + max_accel)
            else:
                state.velocity = max(target_spd, state.velocity - max_accel)

            # Move based on actual velocity
            speed_deg = state.velocity * _KTS_TO_DEG_PER_SEC * dt
            dist_to_wp = _distance_between((state.latitude, state.longitude), target)
            if dist_to_wp > 1e-8:
                dlat = target[0] - state.latitude
                dlon = target[1] - state.longitude
                ratio = min(speed_deg / dist_to_wp, 1.0)
                state.latitude += dlat * ratio
                state.longitude += dlon * ratio

            # Climb rate capped at realistic values (prof_vr is ft/min from OpenAP)
            max_climb_fpm = abs(prof_vr) if prof_vr and prof_vr > 0 else 2500
            max_climb_fpm = min(max_climb_fpm, 3500)  # hard cap for narrow-body
            alt_step = max_climb_fpm / 60.0 * dt
            # During departure, altitude must never decrease (monotonic climb).
            # Waypoints may have lower altitudes from SID constraints, but the
            # aircraft should continue climbing past them, not descend.
            new_alt = max(0.0, _interpolate_altitude(state.altitude, target_alt, alt_step))
            state.altitude = max(state.altitude, new_alt)
            # Use profile altitude ceiling (not waypoint) so VR stays positive
            # during climb even when current alt exceeds the low initial waypoint.
            state.vertical_rate = prof_vr if (state.altitude < target_alt or state.altitude < prof_alt) else 0

            # Smooth heading toward waypoint (max 3°/s standard rate turn)
            target_hdg = _calculate_heading((state.latitude, state.longitude), target)
            state.heading = _smooth_heading(state.heading, target_hdg, 3.0, dt)

            if _distance_between((state.latitude, state.longitude), target) < 0.005:
                state.waypoint_index += 1
        else:
            # Waypoints exhausted — continue climbing to FL180 before ENROUTE transition
            if state.altitude < 18000:
                # Use OpenAP climb profile for post-waypoint climb
                climb_prof = get_climb_profile(state.aircraft_type)
                # We're past waypoints, roughly 40-60% of climb
                frac = min(1.0, 0.4 + 0.2 * (state.altitude / 18000.0))
                _, prof_spd, prof_vr = interpolate_profile(climb_prof, frac)
                target_spd = min(prof_spd, MAX_SPEED_BELOW_FL100_KTS) if state.altitude < 10000 else prof_spd
                max_accel = 2.0 * dt
                if target_spd > state.velocity:
                    state.velocity = min(target_spd, state.velocity + max_accel)
                else:
                    state.velocity = max(target_spd, state.velocity - max_accel)
                climb_fpm = prof_vr if prof_vr > 0 else 1500
                climb_fpm = min(climb_fpm, 3500)  # hard cap for narrow-body
                state.vertical_rate = climb_fpm
                state.altitude += climb_fpm / 60.0 * dt
                # Continue on departure heading
                speed_deg = state.velocity * _KTS_TO_DEG_PER_SEC * dt
                state.latitude += math.cos(math.radians(state.heading)) * speed_deg
                state.longitude += math.sin(math.radians(state.heading)) * speed_deg / max(0.01, math.cos(math.radians(state.latitude)))
            else:
                # Now switch to enroute — heading toward destination
                emit_phase_transition(
                    state.icao24, state.callsign,
                    FlightPhase.DEPARTING.value, FlightPhase.ENROUTE.value,
                    state.latitude, state.longitude, state.altitude,
                    state.aircraft_type, state.assigned_gate,
                )
                _set_phase(state, FlightPhase.ENROUTE)
                if state.destination_airport:
                    state.heading = _bearing_to_airport(state.destination_airport)

    elif state.phase == FlightPhase.ENROUTE:
        EXIT_RADIUS_DEG = 0.5  # ~30 NM — remove when exiting this circle
        APPROACH_RADIUS_DEG = 0.25  # ~15 NM — transition to approach

        center = get_airport_center()
        dist_from_airport = _distance_between(
            (state.latitude, state.longitude),
            center,
        )

        if state.origin_airport and not state.destination_airport:
            # ARRIVING enroute: heading toward airport, transition to approach when close

            # Go-around climb: if aircraft just executed a missed approach,
            # climb to target altitude before resuming normal enroute behavior.
            if state.go_around_target_alt > 0 and state.altitude < state.go_around_target_alt:
                climb_fps = 25.0  # ~1500 ft/min
                state.altitude = min(state.go_around_target_alt, state.altitude + climb_fps * dt)
                state.vertical_rate = 1500
                # Continue flying forward on current heading during climb
                speed_deg = state.velocity * _KTS_TO_DEG_PER_SEC * dt
                state.latitude += math.cos(math.radians(state.heading)) * speed_deg
                state.longitude += math.sin(math.radians(state.heading)) * speed_deg / max(0.01, math.cos(math.radians(state.latitude)))
                if state.altitude >= state.go_around_target_alt:
                    state.go_around_target_alt = 0.0
                return state

            target_heading = _calculate_heading(
                (state.latitude, state.longitude), center
            )
            # Gently steer toward target (smooth turns)
            heading_diff = (target_heading - state.heading + 540) % 360 - 180
            state.heading += max(-3, min(3, heading_diff)) * dt
            state.heading = state.heading % 360

            # Progressive descent & speed envelope for arriving flights
            # dist_from_airport is in degrees; ~0.5° ≈ 30 NM, ~0.25° ≈ 15 NM
            # Start descent around 0.5° out (~30 NM), reach ~3000 ft at 0.17° (~10 NM)
            if dist_from_airport < EXIT_RADIUS_DEG and state.altitude > 3000:
                frac = max(0.0, (dist_from_airport - 0.17) / (EXIT_RADIUS_DEG - 0.17))
                target_alt = max(3000.0, 3000.0 + frac * (35000.0 - 3000.0))
                if state.altitude > target_alt:
                    descent_rate = min(2000.0, (state.altitude - target_alt) * 2.0)
                    state.altitude -= descent_rate * dt / 60.0
                    state.altitude = max(target_alt, state.altitude)
                    state.vertical_rate = -descent_rate

            # Speed envelope based on altitude (realistic deceleration)
            if state.altitude < 3000:
                state.velocity = min(state.velocity, 180)
            elif state.altitude < 5000:
                state.velocity = min(state.velocity, 210)
            elif state.altitude < 10000:
                state.velocity = min(state.velocity, MAX_SPEED_BELOW_FL100_KTS)

            # Enforce approach capacity at runtime (max 4 on approach)
            approach_count = (_count_aircraft_in_phase(FlightPhase.APPROACHING)
                              + _count_aircraft_in_phase(FlightPhase.LANDING))
            can_start_approach = approach_count < MAX_APPROACH_AIRCRAFT


            if can_start_approach and dist_from_airport < APPROACH_RADIUS_DEG:
                # Close enough — transition to approach
                emit_phase_transition(
                    state.icao24, state.callsign,
                    FlightPhase.ENROUTE.value, FlightPhase.APPROACHING.value,
                    state.latitude, state.longitude, state.altitude,
                    state.aircraft_type, state.assigned_gate,
                )
                _set_phase(state, FlightPhase.APPROACHING)
                state.waypoint_index = 0
                state.star_name = _get_star_name(state.origin_airport)
                # Smooth speed transition: set speed from OpenAP descent profile
                # to prevent a visible speed jump on the first approach tick
                _dp = get_descent_profile(state.aircraft_type)
                _, _ps, _pv = interpolate_profile(_dp, 0.5)
                _vref = VREF_SPEEDS.get(state.aircraft_type, _DEFAULT_VREF)
                state.velocity = max(_vref, min(_ps, MAX_SPEED_BELOW_FL100_KTS))
                state.vertical_rate = _pv if _pv else -800
            elif can_start_approach and random.random() < 0.01 * dt and dist_from_airport < 0.35:
                emit_phase_transition(
                    state.icao24, state.callsign,
                    FlightPhase.ENROUTE.value, FlightPhase.APPROACHING.value,
                    state.latitude, state.longitude, state.altitude,
                    state.aircraft_type, state.assigned_gate,
                )
                _set_phase(state, FlightPhase.APPROACHING)
                state.waypoint_index = 0
                state.star_name = _get_star_name(state.origin_airport)
                _dp = get_descent_profile(state.aircraft_type)
                _, _ps, _pv = interpolate_profile(_dp, 0.5)
                _vref = VREF_SPEEDS.get(state.aircraft_type, _DEFAULT_VREF)
                state.velocity = max(_vref, min(_ps, MAX_SPEED_BELOW_FL100_KTS))
                state.vertical_rate = _pv if _pv else -800
            elif not can_start_approach and dist_from_airport < APPROACH_RADIUS_DEG:
                # Approach full — FAA standard racetrack holding pattern
                # 1-minute inbound/outbound legs, standard rate turns (3°/s)
                HOLDING_LEG_SECONDS = 60.0  # 1-minute legs per FAA 7110.65
                STANDARD_RATE_DEG_S = 3.0   # Standard rate turn
                state.holding_phase_time += dt
                if state.holding_inbound:
                    # Inbound leg: fly toward the fix (airport center)
                    state.heading = _calculate_heading(
                        (state.latitude, state.longitude), center
                    )
                    if state.holding_phase_time >= HOLDING_LEG_SECONDS:
                        state.holding_phase_time = 0.0
                        state.holding_inbound = False  # Start turn + outbound
                else:
                    # Outbound leg: 180° turn then fly away from fix
                    if state.holding_phase_time < 30.0:
                        # Standard rate 180° turn (~60s for full 360°, 30s for 180°)
                        state.heading = (state.heading + STANDARD_RATE_DEG_S * dt) % 360
                    elif state.holding_phase_time < 30.0 + HOLDING_LEG_SECONDS:
                        # Straight outbound leg — maintain heading
                        pass
                    else:
                        # Turn back inbound
                        state.holding_phase_time = 0.0
                        state.holding_inbound = True

        elif state.destination_airport:
            # DEPARTING enroute: heading away from SFO toward destination
            target_heading = _bearing_to_airport(state.destination_airport)
            heading_diff = (target_heading - state.heading + 540) % 360 - 180
            state.heading += max(-3, min(3, heading_diff)) * dt
            state.heading = state.heading % 360

            # Climb toward cruise altitude (hemispheric rule: east=odd FL, west=even FL)
            if state.cruise_altitude == 0.0:
                if state.heading < 180:
                    state.cruise_altitude = random.choice([35000, 37000, 39000])
                else:
                    state.cruise_altitude = random.choice([34000, 36000, 38000])
            if state.altitude < state.cruise_altitude:
                # Climb rate capped at realistic values (ft/min → ft/tick)
                # A320-family: ~2500 fpm below FL200, ~1500 fpm above
                max_climb_fpm = 2500 if state.altitude < 20000 else 1500
                alt_step = min(max_climb_fpm / 60.0 * dt, state.cruise_altitude - state.altitude)
                state.altitude += alt_step
                state.vertical_rate = max_climb_fpm

            # Speed management: 250 kts below FL100, accelerate above
            if state.altitude < 10000:
                target_spd = min(state.velocity, MAX_SPEED_BELOW_FL100_KTS)
            else:
                # Cruise speed ~450 kts for jets, limit acceleration to 2 kts/s
                target_spd = 450 if state.altitude > 20000 else 300
            max_accel = 2.0 * dt
            if target_spd > state.velocity:
                state.velocity = min(target_spd, state.velocity + max_accel)
            elif target_spd < state.velocity:
                state.velocity = max(target_spd, state.velocity - max_accel)

            # Remove when exiting visibility circle
            if dist_from_airport > EXIT_RADIUS_DEG:
                # Mark for removal by returning None-like signal
                # We set a special flag — the main loop will handle cleanup
                state.phase_progress = -1.0  # Signal: remove this flight
                return state

        else:
            # No origin/destination — legacy random behavior, head toward airport
            if dist_from_airport > EXIT_RADIUS_DEG:
                state.heading = _calculate_heading(
                    (state.latitude, state.longitude), center
                )
            else:
                pass  # Maintain current heading — no jitter

            if random.random() < 0.005 * dt:
                _set_phase(state, FlightPhase.APPROACHING)
                state.waypoint_index = 0
                state.star_name = _get_star_name(state.origin_airport)

        # 14 CFR 91.117: 250 kts IAS below 10,000 ft MSL
        if state.altitude < 10000:
            state.velocity = min(state.velocity, MAX_SPEED_BELOW_FL100_KTS)

        # Move in current heading direction
        state.latitude += math.cos(math.radians(state.heading)) * 0.001 * dt
        state.longitude += math.sin(math.radians(state.heading)) * 0.001 * dt

    # Safety: clamp altitude floor and normalize heading
    state.altitude = max(0.0, state.altitude)
    state.heading = state.heading % 360

    # Safety: clamp velocity for ground phases
    if state.phase in (FlightPhase.TAXI_TO_GATE, FlightPhase.TAXI_TO_RUNWAY):
        state.velocity = min(state.velocity, TAXI_SPEED_STRAIGHT_KTS)
    elif state.phase == FlightPhase.PARKED:
        state.velocity = 0.0
        state.vertical_rate = 0.0

    return state


def _get_flight_phase_name(phase: FlightPhase) -> str:
    """Convert flight phase to API-compatible phase name (fine-grained 9-phase)."""
    phase_map = {
        FlightPhase.APPROACHING: "approaching",
        FlightPhase.LANDING: "landing",
        FlightPhase.TAXI_TO_GATE: "taxi_in",
        FlightPhase.PARKED: "parked",
        FlightPhase.PUSHBACK: "pushback",
        FlightPhase.TAXI_TO_RUNWAY: "taxi_out",
        FlightPhase.TAKEOFF: "takeoff",
        FlightPhase.DEPARTING: "departing",
        FlightPhase.ENROUTE: "enroute",
    }
    return phase_map.get(phase, "parked")


def generate_synthetic_flights(
    count: int = 50,
    bbox: Dict[str, float] | None = None,
) -> Dict[str, Any]:
    """
    Generate synthetic flight data with persistent realistic movements.

    Maintains flight state across calls for smooth, realistic movements.
    Aircraft follow proper taxi paths, landing/takeoff sequences, and
    cruise patterns. Implements FAA/ICAO separation standards.

    Args:
        count: Number of flights to generate (default 50).
        bbox: Bounding box (unused, kept for API compatibility).

    Returns:
        Dict with 'time' (int) and 'states' (list of lists) matching
        the OpenSky /states/all response format.
    """
    global _flight_states, _last_update

    current_time = datetime.now(timezone.utc).timestamp()
    dt = min(current_time - _last_update, 5.0) if _last_update > 0 else 1.0
    _last_update = current_time

    # Initialize gate states on first run
    _init_gate_states()

    # Remove flights that have exited the visibility circle (departures)
    for icao24 in list(_flight_states.keys()):
        state = _flight_states[icao24]
        if state.phase == FlightPhase.ENROUTE and state.phase_progress == -1.0:
            # Release any gate still held
            if state.assigned_gate:
                _release_gate(icao24, state.assigned_gate)
            del _flight_states[icao24]

    # Initialize flights if needed (fill up to target count)
    if len(_flight_states) < count:
        local_iata = get_current_airport_iata()

        # Generate random flights
        while len(_flight_states) < count:
            icao24 = fake.hexify(text="^^^^^^", upper=False)
            if icao24 in _flight_states:
                continue

            # Select airline from calibrated profile if available
            _profile = _get_current_airport_profile()
            _from_profile = False
            if _profile and _profile.airline_shares:
                _codes = list(_profile.airline_shares.keys())
                _weights = list(_profile.airline_shares.values())
                prefix = random.choices(_codes, weights=_weights, k=1)[0]
                _from_profile = True
            else:
                prefix = random.choice(CALLSIGN_PREFIXES)

            # Replace "OTH" catch-all with a real regional carrier
            _OTH_REPLACEMENTS = ["SKW", "RPA", "ENY", "PDT", "EDV"]
            if prefix == "OTH":
                prefix = random.choice(_OTH_REPLACEMENTS)

            # Easter egg: ~15% chance of Ukrainian Air Force at UA airports
            try:
                from src.ingestion.airport_table import AIRPORTS as _apt_table
                _apt_entry = _apt_table.get(local_iata)
                _icao_to_iata_map = {v[2]: k for k, v in _apt_table.items()}
                _resolved_iata = _icao_to_iata_map.get(local_iata, local_iata)
                _apt_entry2 = _apt_table.get(_resolved_iata)
                _check = _apt_entry or _apt_entry2
                if _check and _check[3] == "UA":
                    if random.random() < 0.15:
                        prefix = "UAF"
                        logger.info("Easter egg: UAF fighter jet spawning at %s (resolved: %s)", local_iata, _resolved_iata)
            except Exception:
                pass

            # Validate airline scope — only for non-profile airlines.
            # If the profile explicitly includes a carrier for this airport, trust it.
            if not _from_profile:
                _US_DOMESTIC_CARRIERS = {"SWA", "JBU", "ASA", "HAL"}
                _US_REGIONAL_CARRIERS = {"SKW", "RPA", "ENY", "PDT", "EDV"}
                _US_IATA_CODES = {
                    "SFO", "LAX", "ORD", "DFW", "JFK", "ATL", "DEN", "SEA", "BOS",
                    "PHX", "LAS", "MCO", "MIA", "CLT", "MSP", "DTW", "EWR", "PHL",
                    "IAH", "SAN", "PDX", "HNL", "AUS", "TPA", "SLC", "BNA", "DCA",
                    "IAD", "FLL", "STL", "BWI", "RDU", "SJC", "DAL", "MDW", "OAK",
                    "SMF", "IND", "CLE", "MCI", "CMH", "PIT", "SAT", "MKE", "CVG",
                }
                _is_us_airport = local_iata in _US_IATA_CODES

                # Filter domestic-only US carriers at non-US airports
                if prefix in _US_DOMESTIC_CARRIERS and not _is_us_airport:
                    prefix = random.choice(["UAL", "DAL", "AAL", "UAE", "AFR", "CPA"])

                # Filter US regional carriers at non-US airports
                if prefix in _US_REGIONAL_CARRIERS and not _is_us_airport:
                    prefix = random.choice(["UAL", "DAL", "AAL", "UAE", "AFR", "CPA"])

                try:
                    from src.ingestion.schedule_generator import AIRLINES as _SG_AIRLINES
                    _airline_info = _SG_AIRLINES.get(prefix)
                    if _airline_info:
                        _scope = _airline_info.get("scope", "full")
                        if _scope == "regional_eu" and not _is_international_airport(local_iata):
                            prefix = random.choice(["UAL", "DAL", "AAL", "UAE", "AFR", "CPA"])
                        elif _scope == "regional_me":
                            if not any(local_iata.startswith(p) for p in ("DXB", "DOH", "AUH", "BAH", "KWI", "MCT")):
                                prefix = random.choice(["UAL", "DAL", "AAL", "UAE", "AFR", "CPA"])
                except ImportError:
                    pass

            flight_num = random.randint(100, 9999)
            callsign = f"{prefix}{flight_num}"

            # Ensure callsign uniqueness — skip duplicates (loop will retry)
            if any(s.callsign == callsign for s in _flight_states.values()):
                continue

            # Count current phases to balance distribution
            parked_count = _count_aircraft_in_phase(FlightPhase.PARKED)
            approach_count = _count_aircraft_in_phase(FlightPhase.APPROACHING)
            taxi_count = (_count_aircraft_in_phase(FlightPhase.TAXI_TO_GATE) +
                         _count_aircraft_in_phase(FlightPhase.TAXI_TO_RUNWAY))

            max_parked = int(len(get_gates()) * 0.8)  # 80% cap — buffer for arrivals
            approach_weight = 0.10 if approach_count < MAX_APPROACH_AIRCRAFT else 0.0
            parked_weight = 0.12 if parked_count < max_parked else 0.0
            taxi_in_weight = 0.05 if taxi_count < 6 else 0.0
            taxi_out_weight = 0.08 if taxi_count < 6 else 0.0
            departing_weight = 0.15

            total_assigned = approach_weight + parked_weight + taxi_in_weight + taxi_out_weight + departing_weight
            enroute_weight = max(0.0, 1.0 - total_assigned)

            # Split ENROUTE 50/50 into arriving and departing.
            # "ENROUTE_DEPARTING" is a pseudo-phase: spawns as ENROUTE but positioned outbound.
            phase_weights = [
                (FlightPhase.ENROUTE, enroute_weight * 0.5),           # arriving enroute
                ("ENROUTE_DEPARTING", enroute_weight * 0.5),           # departing enroute (pseudo)
                (FlightPhase.APPROACHING, approach_weight),
                (FlightPhase.PARKED, parked_weight),
                (FlightPhase.TAXI_TO_GATE, taxi_in_weight),
                (FlightPhase.TAXI_TO_RUNWAY, taxi_out_weight),
                (FlightPhase.DEPARTING, departing_weight),
            ]

            r = random.random()
            cumulative = 0
            selected_phase = FlightPhase.ENROUTE
            _is_enroute_departing = False
            for phase, weight in phase_weights:
                cumulative += weight
                if r <= cumulative:
                    if phase == "ENROUTE_DEPARTING":
                        selected_phase = FlightPhase.ENROUTE
                        _is_enroute_departing = True
                    else:
                        selected_phase = phase
                    break

            # Assign origin/destination based on phase
            origin = None
            dest = None
            is_arriving = (
                selected_phase in (
                    FlightPhase.ENROUTE, FlightPhase.APPROACHING,
                    FlightPhase.LANDING, FlightPhase.TAXI_TO_GATE,
                )
                and not _is_enroute_departing
            )
            is_departing = (
                selected_phase in (
                    FlightPhase.PUSHBACK, FlightPhase.TAXI_TO_RUNWAY,
                    FlightPhase.TAKEOFF, FlightPhase.DEPARTING,
                )
                or _is_enroute_departing
            )

            local_iata = get_current_airport_iata()
            if is_arriving:
                # Convention: arriving flights have origin set, NO destination
                # (_update_flight_state checks `origin and not destination` for arrivals)
                origin = _pick_random_origin()
                dest = None
            elif is_departing:
                # Convention: departing flights have destination set, NO origin
                # (_update_flight_state checks `destination` for departures)
                origin = None
                dest = _pick_random_destination()
            elif selected_phase == FlightPhase.PARKED:
                # Parked: set both — parked flights don't use the enroute direction logic
                if random.random() < 0.5:
                    origin = _pick_random_origin()
                    dest = local_iata
                else:
                    origin = local_iata
                    dest = _pick_random_destination()

            _flight_states[icao24] = _create_new_flight(icao24, callsign, selected_phase, origin=origin, destination=dest)

    # Update all flight states
    for icao24, state in list(_flight_states.items()):
        _flight_states[icao24] = _update_flight_state(state, dt)

    # Build response in OpenSky format
    states: List[List[Any]] = []

    for icao24, state in list(_flight_states.items())[:count]:
        # Sanitize numeric fields to prevent NaN/Inf propagation to frontend
        _alt = _sanitize_float(state.altitude, 0.0)
        _vel = _sanitize_float(state.velocity, 0.0)
        _hdg = _sanitize_float(state.heading, 0.0)
        _vr = _sanitize_float(state.vertical_rate, 0.0)
        _lat = _sanitize_float(state.latitude, 0.0)
        _lon = _sanitize_float(state.longitude, 0.0)

        state_vector = [
            state.icao24,                              # 0: icao24
            state.callsign.ljust(8),                   # 1: callsign
            _get_origin_country(state.origin_airport), # 2: origin_country
            int(current_time) - random.randint(0, 2), # 3: time_position
            int(current_time),                         # 4: last_contact
            _lon,                                      # 5: longitude
            _lat,                                      # 6: latitude
            _alt * 0.3048,                             # 7: baro_altitude (convert ft to m)
            state.on_ground,                           # 8: on_ground
            _vel * 0.514444,                           # 9: velocity (convert kts to m/s)
            _hdg,                                      # 10: true_track
            _vr * 0.00508,                             # 11: vertical_rate (ft/min to m/s)
            None,                                      # 12: sensors
            _alt * 0.3048,                             # 13: geo_altitude
            f"{random.randint(1000, 7777):04d}",       # 14: squawk
            False,                                     # 15: spi
            0,                                         # 16: position_source
            random.randint(2, 6),                      # 17: category
            _get_flight_phase_name(state.phase),       # 18: flight_phase (custom)
            state.aircraft_type,                       # 19: aircraft_type (custom)
            state.origin_airport,                      # 20: origin_airport (custom)
            state.destination_airport,                 # 21: destination_airport (custom)
            state.assigned_gate if state.phase in (FlightPhase.PARKED, FlightPhase.TAXI_TO_GATE) else None,  # 22: assigned_gate (only at/approaching gate)
        ]
        states.append(state_vector)

    return {
        "time": int(current_time),
        "states": states,
    }




def generate_synthetic_trajectory(icao24: str, minutes: int = 60, limit: int = 1000) -> List[Dict[str, Any]]:
    """Generate synthetic trajectory data for a flight.

    Creates a realistic approach-to-landing trajectory pattern for demo purposes.
    The trajectory follows the ILS approach path to runway 28L at SFO:
    - Approach from the east over San Francisco Bay
    - Descend on the 3° glideslope
    - Land heading approximately 284° (true heading)
    - Taxi to gate via the terminal apron

    The generated trajectory aligns with both the 2D map (Leaflet) and
    3D visualization (Three.js) using the same coordinate reference.

    Args:
        icao24: The ICAO24 address of the aircraft.
        minutes: Minutes of history to simulate.
        limit: Maximum number of points to return.

    Returns:
        List of trajectory points as dictionaries.
    """
    from datetime import datetime, timedelta, timezone

    # Find the flight in the flight states manager
    flight_info = None
    if icao24 in _flight_states:
        state = _flight_states[icao24]
        flight_info = {"icao24": icao24, "callsign": state.callsign}

    if flight_info is None:
        return []

    callsign = flight_info.get("callsign", "UNKNOWN")

    # Get the current flight state if available
    current_state = _flight_states.get(icao24)

    # Determine aircraft's current situation
    if current_state:
        end_lat = current_state.latitude
        end_lon = current_state.longitude
        end_alt = current_state.altitude
        current_heading = current_state.heading
        current_phase = current_state.phase.value if current_state.phase else "descending"
    else:
        # Fallback to approach position
        _app_wps = _get_approach_waypoints()
        end_lat = _app_wps[-1][1]
        end_lon = _app_wps[-1][0]
        end_alt = _app_wps[-1][2]
        current_heading = 284  # Runway 28L heading
        current_phase = "descending"

    # Parked aircraft don't need a synthetic trajectory trail — they're
    # stationary at a gate.  Showing a fabricated arrival path is misleading.
    if current_phase == "parked":
        return []

    # Determine if aircraft is on ground
    ground_phases = ["ground", "taxi_to_gate", "taxi_to_runway", "pushback"]
    is_on_ground = current_phase in ground_phases or end_alt < 100

    # =========================================================================
    # Generate trajectory following the ILS approach path
    # =========================================================================
    # The ILS approach to runway 28L comes from the east (higher longitude)
    # Aircraft descend on a 3° glideslope (approximately 300 ft/NM)
    # Touchdown zone is at the runway 28L threshold

    points = []
    num_points = min(limit, 80)
    now = datetime.now(timezone.utc)
    interval_seconds = (minutes * 60) / num_points

    # Runway parameters from OSM data — no runway = no trajectory
    _rwy_threshold = _get_runway_threshold()
    _dep_threshold = _get_departure_runway()
    if _rwy_threshold is None or _dep_threshold is None:
        return []  # No runway data, disable trajectory
    runway_28l_lon, runway_28l_lat = _rwy_threshold[0], _rwy_threshold[1]
    dep_rwy_lon, dep_rwy_lat = _dep_threshold[0], _dep_threshold[1]

    if is_on_ground:
        # Aircraft is on ground - show approach + landing + taxi trajectory
        # Divide trajectory: 45% approach, 20% landing roll, 35% taxi
        # Realistic rollout: 1500-2500m from touchdown to taxi turnoff.

        # Landing roll direction along actual runway heading
        _rwy_heading = _get_runway_heading()
        if _rwy_heading is None:
            return []
        _rwy_heading_rad = math.radians(_rwy_heading)
        _roll_distance = 0.020  # ~2.2 km roll in degrees (typical landing rollout)
        roll_dlat = _roll_distance * math.cos(_rwy_heading_rad)
        roll_dlon = _roll_distance * math.sin(_rwy_heading_rad) / math.cos(math.radians(runway_28l_lat))

        _running_hdg = current_heading  # smooth heading across points
        for i in range(num_points):
            progress = i / (num_points - 1) if num_points > 1 else 0

            if progress < 0.45:
                # APPROACH PHASE: Following ILS glideslope
                approach_progress = progress / 0.45  # 0 to 1

                # Interpolate along the approach waypoints
                # Start from initial approach fix, end at threshold
                _origin_airport = current_state.origin_airport if current_state else None
                _traj_app_wps = _get_approach_waypoints(_origin_airport)
                wp_count = len(_traj_app_wps)
                wp_progress = approach_progress * (wp_count - 1)
                wp_idx = int(wp_progress)
                wp_frac = wp_progress - wp_idx

                if wp_idx >= wp_count - 1:
                    wp_idx = wp_count - 2
                    wp_frac = 1.0

                # Interpolate between waypoints
                wp1 = _traj_app_wps[wp_idx]
                wp2 = _traj_app_wps[min(wp_idx + 1, wp_count - 1)]

                lon = wp1[0] + (wp2[0] - wp1[0]) * wp_frac
                lat = wp1[1] + (wp2[1] - wp1[1]) * wp_frac

                # Altitude from descent profile — progress 0.5-1.0
                _gnd_actype = current_state.aircraft_type if current_state else "A320"
                _gnd_desc_prof = get_descent_profile(_gnd_actype)
                _gnd_prof_prog = 0.5 + 0.5 * approach_progress
                prof_alt, prof_spd, prof_vr = interpolate_profile(_gnd_desc_prof, _gnd_prof_prog)
                alt = prof_alt

                # Smooth heading toward next waypoint
                target_hdg = _calculate_heading((lat, lon), (wp2[1], wp2[0]))
                _running_hdg = _smooth_heading(_running_hdg, target_hdg, 3.0, interval_seconds)
                heading = _running_hdg

                phase = "approaching" if alt > 500 else "landing"
                velocity = prof_spd
                vertical_rate = prof_vr

            elif progress < 0.65:
                # LANDING ROLL: Decelerating on runway (20% of trajectory)
                roll_progress = (progress - 0.45) / 0.20

                # Move along runway heading
                lat = runway_28l_lat + roll_progress * roll_dlat
                lon = runway_28l_lon + roll_progress * roll_dlon
                alt = 0

                heading = _rwy_heading
                phase = "ground"
                velocity = 130 - roll_progress * 100  # Decelerate to 30 kts
                vertical_rate = 0

            else:
                # TAXI PHASE: Follow taxiway route from runway to current position
                taxi_progress = (progress - 0.65) / 0.35

                # Landing roll endpoint (must match the roll phase above)
                roll_end_lat = runway_28l_lat + roll_dlat
                roll_end_lon = runway_28l_lon + roll_dlon

                # Build taxi path: use the flight's taxi route if available,
                # otherwise fall back to the gate-based route or straight line.
                taxi_path = []
                if current_state and current_state.taxi_route:
                    # Use the actual route the aircraft is following
                    taxi_path = [(lon_wp, lat_wp) for lon_wp, lat_wp in current_state.taxi_route]
                elif current_state and current_state.assigned_gate:
                    taxi_path = _get_taxi_waypoints_arrival(current_state.assigned_gate)

                if len(taxi_path) >= 2:
                    taxi_path_latlons = [(lat_wp, lon_wp) for lon_wp, lat_wp in taxi_path]

                    # Connect roll endpoint to the taxi route smoothly:
                    # Find the closest point on the taxi route to roll_end,
                    # then splice from that point onward to avoid backtracking.
                    best_idx = 0
                    best_dist = _distance_between(
                        (roll_end_lat, roll_end_lon), taxi_path_latlons[0]
                    )
                    for _ti in range(1, len(taxi_path_latlons)):
                        d = _distance_between(
                            (roll_end_lat, roll_end_lon), taxi_path_latlons[_ti]
                        )
                        if d < best_dist:
                            best_dist = d
                            best_idx = _ti

                    # Trim the taxi path: start from the closest point onward
                    taxi_path_latlons = taxi_path_latlons[best_idx:]

                    # Prepend roll endpoint for smooth phase transition
                    taxi_path_latlons.insert(0, (roll_end_lat, roll_end_lon))
                    # Append current position only if close to last taxi waypoint
                    # to avoid a visible "jump" across the airport
                    last_taxi = taxi_path_latlons[-1]
                    gap = _distance_between(last_taxi, (end_lat, end_lon))
                    if gap < 0.005:  # ~500m — reasonable gate proximity
                        taxi_path_latlons.append((end_lat, end_lon))

                    # Compute cumulative distances along the path
                    cum_dist = [0.0]
                    for j in range(1, len(taxi_path_latlons)):
                        d = _distance_between(taxi_path_latlons[j - 1], taxi_path_latlons[j])
                        cum_dist.append(cum_dist[-1] + d)
                    total_dist = cum_dist[-1] if cum_dist[-1] > 0 else 1e-9

                    # Find the interpolated position along the path
                    target_dist = taxi_progress * total_dist
                    seg_idx = 0
                    for j in range(1, len(cum_dist)):
                        if cum_dist[j] >= target_dist:
                            seg_idx = j - 1
                            break
                    else:
                        seg_idx = len(cum_dist) - 2

                    seg_len = cum_dist[seg_idx + 1] - cum_dist[seg_idx]
                    seg_frac = (target_dist - cum_dist[seg_idx]) / seg_len if seg_len > 0 else 0.0
                    seg_frac = max(0.0, min(1.0, seg_frac))

                    p1 = taxi_path_latlons[seg_idx]
                    p2 = taxi_path_latlons[seg_idx + 1]
                    lat = p1[0] + seg_frac * (p2[0] - p1[0])
                    lon = p1[1] + seg_frac * (p2[1] - p1[1])
                    heading = _calculate_heading((lat, lon), p2)
                else:
                    # Fallback: straight line from runway exit to current position
                    lat = roll_end_lat + taxi_progress * (end_lat - roll_end_lat)
                    lon = roll_end_lon + taxi_progress * (end_lon - roll_end_lon)
                    heading = _calculate_heading((lat, lon), (end_lat, end_lon))

                alt = 0
                phase = "ground"
                velocity = TAXI_SPEED_STRAIGHT_KTS
                vertical_rate = 0

            # Append point for this iteration (inside the for loop)
            timestamp = now - timedelta(seconds=interval_seconds * (num_points - 1 - i))

            points.append({
                "timestamp": timestamp.isoformat(),
                "icao24": icao24,
                "callsign": callsign,
                "latitude": lat,
                "longitude": lon,
                "altitude": max(0, alt),
                "velocity": max(10, velocity),
                "heading": heading,
                "vertical_rate": vertical_rate,
                "on_ground": alt < 50,
                "flight_phase": phase,
                "data_source": "synthetic",
            })

    elif current_phase in ["climbing", "cruising", "departing", "takeoff", "enroute"]:
        # DEPARTURE trajectory - show takeoff, climb, then turn toward destination
        dest_airport = current_state.destination_airport if current_state else None
        _dep_rwy_heading = _get_runway_heading()
        if _dep_rwy_heading is None:
            return []  # No runway data, disable trajectory
        dest_bearing = _bearing_to_airport(dest_airport) if dest_airport else _dep_rwy_heading

        _traj_dep_wps = _get_departure_waypoints(dest_airport)
        if not _traj_dep_wps:
            return []  # No runway data, disable trajectory

        # OpenAP climb profile for realistic speeds/altitudes
        _dep_actype = current_state.aircraft_type if current_state else "A320"
        _dep_climb_prof = get_climb_profile(_dep_actype)

        _running_hdg = _dep_rwy_heading  # smooth heading across points
        for i in range(num_points):
            progress = i / (num_points - 1) if num_points > 1 else 0

            if progress < 0.15:
                # Takeoff roll and initial climb — profile progress 0.0-0.05
                takeoff_progress = progress / 0.15
                profile_prog = takeoff_progress * 0.05
                prof_alt, prof_spd, prof_vr = interpolate_profile(_dep_climb_prof, profile_prog)

                wp = _traj_dep_wps[0]
                lat = dep_rwy_lat + takeoff_progress * (wp[1] - dep_rwy_lat)
                lon = dep_rwy_lon + takeoff_progress * (wp[0] - dep_rwy_lon)
                alt = takeoff_progress * wp[2]
                heading = _dep_rwy_heading
                _running_hdg = heading
                velocity = prof_spd
                vertical_rate = prof_vr if takeoff_progress > 0.3 else 0
                phase = "takeoff" if takeoff_progress < 0.5 else "climbing"
            elif progress < 0.50:
                # Climb out following departure waypoints — profile progress 0.05-0.40
                climb_progress = (progress - 0.15) / 0.35
                profile_prog = 0.05 + climb_progress * 0.35
                prof_alt, prof_spd, prof_vr = interpolate_profile(_dep_climb_prof, profile_prog)

                wp_count = len(_traj_dep_wps)
                wp_progress = climb_progress * (wp_count - 1)
                wp_idx = int(wp_progress)
                wp_frac = wp_progress - wp_idx

                if wp_idx >= wp_count - 1:
                    wp_idx = wp_count - 2
                    wp_frac = 1.0

                wp1 = _traj_dep_wps[wp_idx]
                wp2 = _traj_dep_wps[min(wp_idx + 1, wp_count - 1)]

                lon = wp1[0] + (wp2[0] - wp1[0]) * wp_frac
                lat = wp1[1] + (wp2[1] - wp1[1]) * wp_frac
                alt = wp1[2] + (wp2[2] - wp1[2]) * wp_frac

                target_hdg = _calculate_heading((lat, lon), (wp2[1], wp2[0]))
                _running_hdg = _smooth_heading(_running_hdg, target_hdg, 3.0, interval_seconds)
                heading = _running_hdg
                # Enforce 250kt below FL100
                velocity = min(prof_spd, MAX_SPEED_BELOW_FL100_KTS) if alt < 10000 else prof_spd
                vertical_rate = prof_vr
                phase = "departing"
            else:
                # En-route extension — profile progress 0.40-0.80
                enroute_progress = (progress - 0.50) / 0.50
                profile_prog = 0.40 + enroute_progress * 0.40
                prof_alt, prof_spd, prof_vr = interpolate_profile(_dep_climb_prof, profile_prog)

                last_wp = _traj_dep_wps[-1]
                start_lat_dep = last_wp[1]
                start_lon_dep = last_wp[0]
                start_alt_dep = last_wp[2]

                # Project toward destination bearing
                dist = enroute_progress * 0.15  # ~10 NM extension
                lat = start_lat_dep + dist * math.cos(math.radians(dest_bearing))
                lon = start_lon_dep + dist * math.sin(math.radians(dest_bearing)) / math.cos(math.radians(start_lat_dep))
                alt = start_alt_dep + enroute_progress * (prof_alt - start_alt_dep)

                _running_hdg = _smooth_heading(_running_hdg, dest_bearing, 3.0, interval_seconds)
                heading = _running_hdg
                velocity = min(prof_spd, MAX_SPEED_BELOW_FL100_KTS) if alt < 10000 else prof_spd
                vertical_rate = prof_vr if enroute_progress < 0.7 else max(200, prof_vr * 0.3)
                phase = "departing"

            timestamp = now - timedelta(seconds=interval_seconds * (num_points - 1 - i))

            points.append({
                "timestamp": timestamp.isoformat(),
                "icao24": icao24,
                "callsign": callsign,
                "latitude": lat,
                "longitude": lon,
                "altitude": max(0, alt),
                "velocity": max(50, velocity),
                "heading": heading,
                "vertical_rate": vertical_rate,
                "on_ground": alt < 50,
                "flight_phase": phase,
                "data_source": "synthetic",
            })

    else:
        # APPROACH trajectory (aircraft still descending)
        # Use origin-aware approach waypoints so the trajectory starts from
        # the correct direction, then interpolate toward the aircraft's
        # current position.  Only show waypoints up to the aircraft's
        # current position along the approach (not past it).
        origin_airport = current_state.origin_airport if current_state else None
        center = get_airport_center()
        _traj_app_wps2 = _get_approach_waypoints(origin_airport)

        # Clamp end position to reasonable airport vicinity
        clamped_lat = max(center[0] - 0.5, min(center[0] + 0.5, end_lat))
        clamped_lon = max(center[1] - 0.5, min(center[1] + 0.5, end_lon))
        final_alt = end_alt if abs(end_lat - center[0]) < 0.5 else 3000

        # ── Guard: prevent trajectories that cross over the airfield ──
        # The approach waypoints go from far out (index 0) toward the
        # runway threshold (last index).  If the aircraft's current
        # position is on the *opposite* side of the threshold from the
        # approach direction, drawing the full waypoint path would cross
        # the airport center — producing unrealistic overflight.
        #
        # Detection: the last waypoint (threshold) should be *between*
        # the first waypoint (entry) and the aircraft.  If the aircraft
        # is closer to the first waypoint than the threshold is, the
        # aircraft is beyond the threshold on the approach side — fine.
        # If the aircraft is farther from the first waypoint than the
        # threshold AND on the opposite side of the threshold from the
        # approach entry, the path would cross the field.
        threshold_wp = _traj_app_wps2[-1]  # (lon, lat, alt)
        entry_wp = _traj_app_wps2[0]       # (lon, lat, alt)
        dist_entry_to_threshold = _distance_between(
            (entry_wp[1], entry_wp[0]), (threshold_wp[1], threshold_wp[0])
        )
        dist_entry_to_aircraft = _distance_between(
            (entry_wp[1], entry_wp[0]), (clamped_lat, clamped_lon)
        )
        dist_threshold_to_aircraft = _distance_between(
            (threshold_wp[1], threshold_wp[0]), (clamped_lat, clamped_lon)
        )

        # Aircraft is "past the threshold" if it's farther from entry
        # than the threshold AND farther from the threshold than the
        # approach corridor width (~0.02 deg ≈ 2 km).
        aircraft_past_threshold = (
            dist_entry_to_aircraft > dist_entry_to_threshold
            and dist_threshold_to_aircraft > 0.02
        )

        if aircraft_past_threshold:
            # Don't draw approach waypoints — just show a short
            # descent segment ending at the aircraft position to avoid
            # a trajectory line that crosses the airfield.
            # Use only the last 3 approach waypoints (near threshold)
            # offset toward the aircraft's side so the trail stays
            # on the approach side of the field.
            path_wps = [(clamped_lon, clamped_lat, final_alt)]
            path_count = 1
        else:
            # Normal case: find nearest waypoint and build path
            wp_count = len(_traj_app_wps2)
            best_wp_idx = 0
            best_wp_dist = float('inf')
            for _wi in range(wp_count):
                _wd = _distance_between(
                    (clamped_lat, clamped_lon),
                    (_traj_app_wps2[_wi][1], _traj_app_wps2[_wi][0])
                )
                if _wd < best_wp_dist:
                    best_wp_dist = _wd
                    best_wp_idx = _wi

            # Build path: approach waypoints from first up to nearest-to-aircraft,
            # then final segment to the aircraft's exact position.
            path_wps = _traj_app_wps2[:best_wp_idx + 1]
            # Append current position as the final target
            path_wps.append((clamped_lon, clamped_lat, final_alt))
            path_count = len(path_wps)

        if path_count < 2:
            # Single point — just emit the aircraft's current position
            timestamp = now
            points.append({
                "timestamp": timestamp.isoformat(),
                "icao24": icao24,
                "callsign": callsign,
                "latitude": clamped_lat,
                "longitude": clamped_lon,
                "altitude": max(0, final_alt),
                "velocity": 200,
                "heading": current_heading,
                "vertical_rate": -600,
                "on_ground": False,
                "flight_phase": "approaching",
                "data_source": "synthetic",
            })
        else:
            _running_hdg = current_heading  # smooth heading across points
            for i in range(num_points):
                progress = i / (num_points - 1) if num_points > 1 else 0

                wp_progress = progress * (path_count - 1)
                wp_idx = int(wp_progress)
                wp_frac = wp_progress - wp_idx
                if wp_idx >= path_count - 1:
                    wp_idx = path_count - 2
                    wp_frac = 1.0

                wp1 = path_wps[wp_idx]
                wp2 = path_wps[min(wp_idx + 1, path_count - 1)]

                lon = wp1[0] + (wp2[0] - wp1[0]) * wp_frac
                lat = wp1[1] + (wp2[1] - wp1[1]) * wp_frac

                # Altitude from descent profile — progress 0.3-1.0
                _air_actype = current_state.aircraft_type if current_state else "A320"
                _air_desc_prof = get_descent_profile(_air_actype)
                _air_prof_prog = 0.3 + 0.7 * progress
                prof_alt, prof_spd, prof_vr = interpolate_profile(_air_desc_prof, _air_prof_prog)
                alt = prof_alt

                target_hdg = _calculate_heading((lat, lon), (wp2[1], wp2[0]))
                _running_hdg = _smooth_heading(_running_hdg, target_hdg, 3.0, interval_seconds)
                heading = _running_hdg
                velocity = prof_spd
                vertical_rate = prof_vr
                phase = "approaching" if alt > 500 else "landing"

                timestamp = now - timedelta(seconds=interval_seconds * (num_points - 1 - i))

                points.append({
                    "timestamp": timestamp.isoformat(),
                    "icao24": icao24,
                    "callsign": callsign,
                    "latitude": lat,
                    "longitude": lon,
                    "altitude": max(0, alt),
                    "velocity": max(100, velocity),
                    "heading": heading,
                    "vertical_rate": vertical_rate,
                    "on_ground": alt < 50,
                    "flight_phase": phase,
                    "data_source": "synthetic",
                })

    return points


def reset_synthetic_state() -> dict:
    """Reset all synthetic flight state to start fresh.

    Clears all flight states, runway occupancy, and gate assignments
    to regenerate flights with proper separation from scratch.

    Returns:
        dict with count of cleared items.
    """
    global _flight_states, _last_update, _runway_states, _runway_28L, _runway_28R, _gate_states

    cleared_flights = len(_flight_states)
    cleared_gates = len(_gate_states)

    # Clear flight state only — airport center is managed by the activate endpoint
    _flight_states.clear()
    _last_update = 0.0
    _runway_states.clear()
    _runway_28L = RunwayState()
    _runway_28R = RunwayState()
    _runway_states["28L"] = _runway_28L
    _runway_states["28R"] = _runway_28R
    _gate_states.clear()

    # Clear event buffers
    with _phase_transition_lock:
        _phase_transition_buffer.clear()
    with _gate_event_lock:
        _gate_event_buffer.clear()
    with _prediction_lock:
        _prediction_buffer.clear()
    with _turnaround_event_lock:
        _turnaround_event_buffer.clear()

    return {
        "cleared_flights": cleared_flights,
        "cleared_gates": cleared_gates,
        "status": "reset_complete",
    }

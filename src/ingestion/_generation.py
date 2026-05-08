"""Public generation entry points: synthetic flights, trajectories, and reset."""

import logging
import math
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional

from faker import Faker

logger = logging.getLogger(__name__)

from src.simulation.openap_profiles import (
    get_descent_profile,
    get_climb_profile,
    interpolate_profile,
)
from src.ml.gse_model import get_turnaround_timing, get_aircraft_category

import src.ingestion._state as _st
from src.ingestion._state import (
    FlightPhase,
    FlightState,
    _flight_states,
    _last_update,
    RunwayState,
    _runway_states,
    _runway_28L,
    _runway_28R,
    _gate_states,
    MAX_APPROACH_AIRCRAFT,
    get_max_approach_aircraft,
)
from src.ingestion._constants import (
    _AIRLINE_NAMES,
    CALLSIGN_PREFIXES,
    MAX_VELOCITY_KTS,
    VREF_SPEEDS,
    _DEFAULT_VREF,
    TAXI_SPEED_STRAIGHT_KTS,
    DECISION_HEIGHT_FT,
    MAX_SPEED_BELOW_FL100_KTS,
    _KTS_TO_DEG_PER_SEC,
)
from src.ingestion._geo import (
    _sanitize_float,
    _calculate_heading,
    _smooth_heading,
    _distance_between,
)
from src.ingestion._event_buffers import (
    drain_phase_transitions,
    drain_gate_events,
    drain_predictions,
    drain_turnaround_events,
)
from src.ingestion._runway_ops import (
    _init_gate_states,
    _release_gate,
    _find_available_gate,
    _count_aircraft_in_phase,
    _get_reciprocal_designator,
)
from src.ingestion._approach_departure import (
    _bearing_cache,
    _get_approach_waypoints,
    _get_departure_waypoints,
    _get_runway_threshold,
    _get_runway_heading,
    _get_osm_primary_runway,
    _get_fallback_runway,
    _get_departure_runway,
    _get_arrival_runway_name,
    _bearing_to_airport,
)
from src.ingestion._taxi_routing import (
    _get_taxi_waypoints_arrival,
)
from src.ingestion._flight_lifecycle import (
    _create_new_flight,
    _update_flight_state,
    _get_flight_phase_name,
    _get_current_airport_profile,
    _is_international_airport,
    _get_origin_country,
    _pick_random_origin,
    _pick_random_destination,
    _get_turnaround_weather_factor,
    _get_turnaround_congestion_factor,
    _get_turnaround_international_factor,
    _get_turnaround_day_of_week_factor,
    _gate_last_delay,
    _GATE_PHASES,
    _build_turnaround_schedule,
    _get_aircraft_type_for_airline,
    get_gate_last_delay,
    get_airport_load_ratio,
    set_calibration_gate_minutes,
    set_calibration_taxi_out,
    set_calibration_taxi_in,
    set_current_weather,
)

fake = Faker()


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


def get_flights_as_schedule(
    sim_time: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Convert current synthetic flight states into FIDS schedule entries.

    This ensures the FIDS display shows the same flights that are visible
    on the map, rather than independently generated schedule data.

    Args:
        sim_time: Simulation clock time. If provided, all time calculations
                  use this instead of wall clock. This keeps FIDS aligned
                  with the simulation replay.

    Returns:
        List of schedule-format dicts compatible with ScheduleService.
    """
    from src.ingestion.fallback import get_current_airport_iata
    now = sim_time or datetime.now(timezone.utc)
    schedule = []

    for icao24, state in _flight_states.items():
        callsign = state.callsign.strip() if state.callsign else ""
        airline_code = callsign[:3].upper() if len(callsign) >= 3 else "UAL"
        # Try ICAO 3-letter, then IATA 2-letter prefix
        airline_name = _AIRLINE_NAMES.get(airline_code) or _AIRLINE_NAMES.get(callsign[:2].upper(), airline_code)

        local_iata = get_current_airport_iata()
        origin = state.origin_airport or "???"
        destination = state.destination_airport or local_iata

        # Determine flight type using phase as a strong signal for in-flight
        # aircraft, falling back to origin/destination convention for ambiguous phases.
        phase = state.phase
        arriving_phases = (FlightPhase.APPROACHING, FlightPhase.LANDING, FlightPhase.TAXI_TO_GATE)
        departing_phases = (FlightPhase.PUSHBACK, FlightPhase.TAXI_TO_RUNWAY, FlightPhase.TAKEOFF, FlightPhase.DEPARTING)

        if phase in arriving_phases:
            is_arrival = True
            destination = local_iata
        elif phase in departing_phases:
            is_arrival = False
            if origin != local_iata:
                origin = local_iata
        elif phase == FlightPhase.ENROUTE:
            is_arrival = bool(state.origin_airport and not state.destination_airport) or (destination == local_iata)
        else:
            is_arrival = (destination == local_iata)

        # Guard against self-referencing: arrival origin must not be local airport
        if is_arrival and origin == local_iata:
            origin = _pick_random_origin()
        flight_type = "arrival" if is_arrival else "departure"

        # Map flight phase to FIDS status
        if phase in (FlightPhase.PARKED,):
            if is_arrival:
                status = "arrived"
            elif state.turnaround_phase in ("boarding", "loading", "chocks_off"):
                status = "boarding"
            else:
                status = "scheduled"
        elif phase == FlightPhase.APPROACHING:
            status = "on_time"  # approaching = inbound, on its way
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

        # Compute delay from simulation state for arrivals, hash-based for departures
        delay_minutes = 0
        if is_arrival:
            if state.holding_phase_time > 0:
                delay_minutes = max(1, int(state.holding_phase_time / 60))
            elif state.go_around_target_alt > 0:
                delay_minutes = 5
            elif (_h >> 4) % 10 == 0:
                delay_minutes = 5 + ((_h >> 8) % 20)
        else:
            if (_h >> 4) % 5 == 0:
                delay_minutes = 5 + ((_h >> 8) % 41)

        # Mark as delayed if delay detected and status is not terminal
        if delay_minutes > 0 and status in ("scheduled", "on_time"):
            status = "delayed"

        # Compute scheduled times based on actual flight phase and state.
        # Wide modulo ranges prevent clustering on the FIDS display.
        if is_arrival:
            if phase in (FlightPhase.PARKED,):
                # Use actual parked_since timestamp so the FIDS entry
                # reflects when the aircraft really arrived (not a random
                # hash offset that could push it outside the time window).
                if state.parked_since > 0:
                    scheduled_time = datetime.fromtimestamp(
                        state.parked_since, tz=timezone.utc
                    ).isoformat()
                else:
                    scheduled_time = (now - timedelta(minutes=5 + _h % 55)).isoformat()
            elif phase == FlightPhase.TAXI_TO_GATE:
                # Use actual landing timestamp if available
                if state.landed_at > 0:
                    scheduled_time = datetime.fromtimestamp(
                        state.landed_at, tz=timezone.utc
                    ).isoformat()
                else:
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
                if state.parked_since > 0:
                    from src.ml.gse_model import get_turnaround_timing
                    timing = get_turnaround_timing(state.aircraft_type or "A320")
                    dep_time = datetime.fromtimestamp(state.parked_since, tz=timezone.utc) + timedelta(minutes=timing["total_minutes"])
                    scheduled_time = dep_time.isoformat()
                else:
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
    from src.ingestion.fallback import get_airport_center, get_current_airport_iata, get_gates

    # Don't create flights until the airport config (runways/gates) is loaded.
    # Generating flights with fallback 270° heading locks in wrong trajectories.
    osm_rwy = _get_osm_primary_runway()
    if osm_rwy is None:
        logger.info("[DIAG] generate_synthetic_flights: BLOCKED — no OSM runway yet")
        return {"time": int(datetime.now(timezone.utc).timestamp()), "states": []}
    if not _flight_states:
        logger.info("[DIAG] generate_synthetic_flights: FIRST RUN with runway ref=%s, %d geoPoints",
                     osm_rwy.get("ref"), len(osm_rwy.get("geoPoints", [])))

    current_time = datetime.now(timezone.utc).timestamp()
    dt = min(current_time - _st._last_update, 5.0) if _st._last_update > 0 else 1.0
    _st._last_update = current_time

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

    # Compute airport-appropriate target flight count:
    # 1) Scale to gate count (small airports get fewer flights)
    # 2) Modulate by hourly traffic profile (quiet hours = fewer flights)
    gate_count = len(get_gates())
    if gate_count > 0:
        target = max(15, min(count, int(gate_count * 1.5)))
    else:
        target = count  # No gates loaded yet — use default

    profile = _get_current_airport_profile()
    if profile and profile.hourly_profile and len(profile.hourly_profile) == 24:
        hour_utc = datetime.now(timezone.utc).hour
        hour_weight = profile.hourly_profile[hour_utc]
        peak_weight = max(profile.hourly_profile)
        if peak_weight > 0:
            hourly_factor = max(0.15, hour_weight / peak_weight)  # floor at 15%
            target = max(5, int(target * hourly_factor))

    # Soft-cull excess flights (max 2 per tick to avoid visual pop)
    if len(_flight_states) > target + 5:
        _cull_candidates = [
            k for k, s in _flight_states.items()
            if s.phase == FlightPhase.ENROUTE and s.phase_progress == -1.0
        ]
        if not _cull_candidates:
            # Fall back to any enroute flight (departing outbound)
            _cull_candidates = [
                k for k, s in _flight_states.items()
                if s.phase == FlightPhase.ENROUTE
            ]
        for _cull_id in _cull_candidates[:2]:
            _cs = _flight_states.get(_cull_id)
            if _cs and _cs.assigned_gate:
                _release_gate(_cull_id, _cs.assigned_gate)
            _flight_states.pop(_cull_id, None)

    # Initialize flights if needed (fill up to target count)
    if len(_flight_states) < target:
        local_iata = get_current_airport_iata()

        # Generate random flights
        while len(_flight_states) < target:
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
            if callsign in _flight_states._callsigns:
                continue

            # Count current phases to balance distribution
            parked_count = _count_aircraft_in_phase(FlightPhase.PARKED)
            approach_count = _count_aircraft_in_phase(FlightPhase.APPROACHING)
            taxi_count = (_count_aircraft_in_phase(FlightPhase.TAXI_TO_GATE) +
                         _count_aircraft_in_phase(FlightPhase.TAXI_TO_RUNWAY))

            max_parked = int(len(get_gates()) * 0.8)  # 80% cap — buffer for arrivals

            # Adjust phase bias based on hourly traffic intensity:
            # Quiet hours → more parked, fewer active movements
            # Busy hours  → more approach/departing activity
            _activity_boost = 1.0
            if profile and profile.hourly_profile and len(profile.hourly_profile) == 24:
                _avg_weight = sum(profile.hourly_profile) / 24
                _cur_weight = profile.hourly_profile[datetime.now(timezone.utc).hour]
                if _avg_weight > 0:
                    _activity_boost = max(0.3, min(1.5, _cur_weight / _avg_weight))

            approach_weight = (0.10 * _activity_boost) if approach_count < get_max_approach_aircraft() else 0.0
            parked_weight = (0.12 / max(0.5, _activity_boost)) if parked_count < max_parked else 0.0
            taxi_in_weight = (0.05 * _activity_boost) if taxi_count < 6 else 0.0
            taxi_out_weight = (0.08 * _activity_boost) if taxi_count < 6 else 0.0
            departing_weight = 0.15 * _activity_boost

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
                # Arriving flights: origin=remote airport, destination=local airport
                origin = _pick_random_origin()
                dest = local_iata
            elif is_departing:
                # Departing flights: origin=local airport, destination=remote
                origin = local_iata
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

    for icao24, state in list(_flight_states.items())[:target]:
        # Sanitize numeric fields to prevent NaN/Inf propagation to frontend
        _alt = _sanitize_float(state.altitude, 0.0)
        _vel = min(_sanitize_float(state.velocity, 0.0), MAX_VELOCITY_KTS)
        _hdg = _sanitize_float(state.heading, 0.0) % 360
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
            datetime.fromtimestamp(state.parked_since, tz=timezone.utc).isoformat() if state.parked_since > 0 and state.phase == FlightPhase.PARKED else None,  # 23: parked_since
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
    from src.ingestion.fallback import get_airport_center, get_current_airport_iata

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
        current_heading = _get_runway_heading() or _get_fallback_runway()[2]
        current_phase = "descending"

    # Parked aircraft don't need a synthetic trajectory trail — they're
    # stationary at a gate.  Showing a fabricated arrival path is misleading.
    if current_phase == "parked":
        return []

    # Determine if aircraft is on ground
    ground_phases = ["ground", "taxi_to_gate", "taxi_to_runway", "pushback"]
    is_on_ground = current_phase in ground_phases or end_alt < 100

    # Detect go-around: aircraft has executed a missed approach and is either
    # still in enroute/holding or has re-entered approaching for a second attempt.
    _local_iata = get_current_airport_iata()
    is_go_around = (
        current_state
        and current_state.go_around_count > 0
        and current_phase in ("enroute", "approaching")
        and (current_state.origin_airport and (
            not current_state.destination_airport
            or current_state.destination_airport == _local_iata
        ))
    )

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
    rwy_threshold_lon, rwy_threshold_lat = _rwy_threshold[0], _rwy_threshold[1]
    dep_rwy_lon, dep_rwy_lat = _dep_threshold[0], _dep_threshold[1]

    if is_go_around:
        # =================================================================
        # GO-AROUND TRAJECTORY: approach → climb-out → return → re-approach
        # =================================================================
        # Shows the initial approach, the climb-out on runway heading after
        # the missed approach, the curve back, and (when the aircraft has
        # re-entered approaching) the second approach to current position.
        origin_airport = current_state.origin_airport if current_state else None
        _traj_app_wps_ga = _get_approach_waypoints(origin_airport)
        _rwy_heading_ga = _get_runway_heading()
        if _rwy_heading_ga is None or len(_traj_app_wps_ga) < 2:
            return []

        _ga_is_reapproach = current_phase == "approaching"

        if _ga_is_reapproach:
            # 4-phase: initial approach + climb-out + return + re-approach
            _GA_APP_PTS = 30
            _GA_CLIMB_PTS = 12
            _GA_RETURN_PTS = 10
            _GA_REAPP_PTS = 28
            _ga_app_frac = 0.35
            _ga_climb_frac = 0.15
            _ga_return_frac = 0.15
            _ga_reapp_frac = 0.35
        else:
            # 3-phase: initial approach + climb-out + return to holding
            _GA_APP_PTS = 48
            _GA_CLIMB_PTS = 20
            _GA_RETURN_PTS = 12
            _GA_REAPP_PTS = 0
            _ga_app_frac = 0.60
            _ga_climb_frac = 0.25
            _ga_return_frac = 0.15
            _ga_reapp_frac = 0.0

        _ga_total = _GA_APP_PTS + _GA_CLIMB_PTS + _GA_RETURN_PTS + _GA_REAPP_PTS
        _ga_total_secs = minutes * 60
        _ga_app_dur = _ga_app_frac * _ga_total_secs
        _ga_climb_dur = _ga_climb_frac * _ga_total_secs
        _ga_return_dur = _ga_return_frac * _ga_total_secs
        _ga_reapp_dur = _ga_reapp_frac * _ga_total_secs

        # Climb-out endpoint: project forward on runway heading from threshold
        _rwy_rad_ga = math.radians(_rwy_heading_ga)
        _climb_dist_deg = 0.03  # ~3.3 km climb-out segment
        _climb_end_lat = rwy_threshold_lat + _climb_dist_deg * math.cos(_rwy_rad_ga)
        _climb_end_lon = rwy_threshold_lon + _climb_dist_deg * math.sin(_rwy_rad_ga) / math.cos(math.radians(rwy_threshold_lat))
        _climb_end_alt = 1500.0  # missed approach altitude

        # Re-approach entry point: find the approach waypoint nearest to
        # the downwind endpoint so the base-turn → re-approach transition is
        # seamless (no large gap that would split the polyline on the map).
        _perp_rad_pre = math.radians((_rwy_heading_ga - 90) % 360)
        _recip_rad_pre = math.radians((_rwy_heading_ga + 180) % 360)
        _lat_cos_pre = math.cos(math.radians(_climb_end_lat))
        _dw_lat_pre = (_climb_end_lat + 0.015 * math.cos(_perp_rad_pre)
                       + 0.025 * math.cos(_recip_rad_pre))
        _dw_lon_pre = (_climb_end_lon
                       + 0.015 * math.sin(_perp_rad_pre) / max(0.01, _lat_cos_pre)
                       + 0.025 * math.sin(_recip_rad_pre) / max(0.01, _lat_cos_pre))
        _reapp_entry_wp_idx = len(_traj_app_wps_ga) - 1
        _best_dist_sq = float('inf')
        for _wp_i in range(len(_traj_app_wps_ga)):
            _wp_lon, _wp_lat = _traj_app_wps_ga[_wp_i][0], _traj_app_wps_ga[_wp_i][1]
            _d_sq = (_wp_lat - _dw_lat_pre) ** 2 + (_wp_lon - _dw_lon_pre) ** 2
            if _d_sq < _best_dist_sq:
                _best_dist_sq = _d_sq
                _reapp_entry_wp_idx = _wp_i
        _reapp_entry_lon = _traj_app_wps_ga[_reapp_entry_wp_idx][0]
        _reapp_entry_lat = _traj_app_wps_ga[_reapp_entry_wp_idx][1]

        # How far along the approach waypoints the aircraft currently is
        _ga_wp_idx = current_state.waypoint_index if current_state else 0
        _ga_wp_count = len(_traj_app_wps_ga)
        # Clamp to valid range
        _ga_wp_idx = min(_ga_wp_idx, _ga_wp_count - 1)

        # Aircraft type for descent/climb profiles
        _ga_actype = current_state.aircraft_type if current_state else "A320"
        _ga_desc_prof = get_descent_profile(_ga_actype)

        _running_hdg = current_heading
        for i in range(_ga_total):
            if i < _GA_APP_PTS:
                # PHASE 1 — Initial approach: interpolate along local waypoints
                # to the runway threshold.  Use enough waypoints for smooth
                # movement but not so many that we include distant STAR points
                # with large gaps between them.
                app_progress = i / max(_GA_APP_PTS - 1, 1)
                # Start from halfway between entry and the beginning, ensuring
                # at least 3 waypoints of range for visible movement.
                _app_start_idx = max(0, _reapp_entry_wp_idx - 3)
                _app_wp_range = max(1, _ga_wp_count - 1 - _app_start_idx)
                wp_progress = app_progress * _app_wp_range + _app_start_idx
                wp_idx = int(wp_progress)
                wp_frac = wp_progress - wp_idx
                if wp_idx >= _ga_wp_count - 1:
                    wp_idx = _ga_wp_count - 2
                    wp_frac = 1.0

                wp1 = _traj_app_wps_ga[wp_idx]
                wp2 = _traj_app_wps_ga[min(wp_idx + 1, _ga_wp_count - 1)]
                lon = wp1[0] + (wp2[0] - wp1[0]) * wp_frac
                lat = wp1[1] + (wp2[1] - wp1[1]) * wp_frac

                _ga_prof_prog = 0.5 + 0.5 * app_progress
                prof_alt, prof_spd, prof_vr = interpolate_profile(_ga_desc_prof, _ga_prof_prog)
                alt = prof_alt

                target_hdg = _calculate_heading((lat, lon), (wp2[1], wp2[0]))
                _ga_interval = _ga_app_dur / max(_GA_APP_PTS, 1)
                _running_hdg = _smooth_heading(_running_hdg, target_hdg, 3.0, _ga_interval)
                heading = _running_hdg
                velocity = prof_spd
                vertical_rate = prof_vr
                phase = "approaching"
                t_offset = i * _ga_interval

            elif i < _GA_APP_PTS + _GA_CLIMB_PTS:
                # PHASE 2 — Climb-out: fly runway heading, climb to missed approach alt
                ci = i - _GA_APP_PTS
                climb_progress = ci / max(_GA_CLIMB_PTS - 1, 1)

                lat = rwy_threshold_lat + climb_progress * (_climb_end_lat - rwy_threshold_lat)
                lon = rwy_threshold_lon + climb_progress * (_climb_end_lon - rwy_threshold_lon)
                alt = float(DECISION_HEIGHT_FT) + climb_progress * (_climb_end_alt - DECISION_HEIGHT_FT)

                heading = _rwy_heading_ga
                _running_hdg = heading
                vref_ga = VREF_SPEEDS.get(_ga_actype, _DEFAULT_VREF)
                velocity = vref_ga + 20  # missed approach speed
                vertical_rate = 1500
                phase = "enroute"
                _ga_climb_interval = _ga_climb_dur / max(_GA_CLIMB_PTS, 1)
                t_offset = _ga_app_dur + ci * _ga_climb_interval

            elif i < _GA_APP_PTS + _GA_CLIMB_PTS + _GA_RETURN_PTS:
                # PHASE 3 — Return: missed approach pattern (crosswind → downwind → base)
                # Offsets laterally so the path doesn't cross back over the runway.
                ri = i - _GA_APP_PTS - _GA_CLIMB_PTS
                return_progress = ri / max(_GA_RETURN_PTS - 1, 1)

                if _ga_is_reapproach:
                    _ret_target_lat = _reapp_entry_lat
                    _ret_target_lon = _reapp_entry_lon
                    _ret_target_alt = 3500.0
                else:
                    _ret_target_lat = end_lat
                    _ret_target_lon = end_lon
                    _ret_target_alt = end_alt

                # Build rectangular missed approach pattern:
                # crosswind turn (left 90°) → downwind → base turn to re-approach entry
                _perp_rad = math.radians((_rwy_heading_ga - 90) % 360)
                _recip_rad = math.radians((_rwy_heading_ga + 180) % 360)
                _lat_cos = math.cos(math.radians(_climb_end_lat))
                _lateral_offset = 0.015  # ~1.7 km lateral offset
                _downwind_dist = 0.025   # ~2.8 km along downwind leg

                # Crosswind point: perpendicular left from climb-out end
                _cw_lat = _climb_end_lat + _lateral_offset * math.cos(_perp_rad)
                _cw_lon = _climb_end_lon + _lateral_offset * math.sin(_perp_rad) / max(0.01, _lat_cos)
                # Downwind point: fly reciprocal heading (back toward approach side)
                _dw_lat = _cw_lat + _downwind_dist * math.cos(_recip_rad)
                _dw_lon = _cw_lon + _downwind_dist * math.sin(_recip_rad) / max(0.01, _lat_cos)

                # 3-segment interpolation: crosswind (0-0.3), downwind (0.3-0.7), base (0.7-1.0)
                if return_progress < 0.3:
                    seg_frac = return_progress / 0.3
                    lat = _climb_end_lat + seg_frac * (_cw_lat - _climb_end_lat)
                    lon = _climb_end_lon + seg_frac * (_cw_lon - _climb_end_lon)
                elif return_progress < 0.7:
                    seg_frac = (return_progress - 0.3) / 0.4
                    lat = _cw_lat + seg_frac * (_dw_lat - _cw_lat)
                    lon = _cw_lon + seg_frac * (_dw_lon - _cw_lon)
                else:
                    seg_frac = (return_progress - 0.7) / 0.3
                    lat = _dw_lat + seg_frac * (_ret_target_lat - _dw_lat)
                    lon = _dw_lon + seg_frac * (_ret_target_lon - _dw_lon)

                alt = _climb_end_alt + return_progress * (_ret_target_alt - _climb_end_alt)

                target_hdg = _calculate_heading((lat, lon), (_ret_target_lat, _ret_target_lon))
                _ga_return_interval = _ga_return_dur / max(_GA_RETURN_PTS, 1)
                _running_hdg = _smooth_heading(_running_hdg, target_hdg, 3.0, _ga_return_interval)
                heading = _running_hdg
                vref_ga = VREF_SPEEDS.get(_ga_actype, _DEFAULT_VREF)
                velocity = vref_ga + 10
                vertical_rate = 500 if _ret_target_alt > _climb_end_alt else -500
                phase = "enroute"
                t_offset = _ga_app_dur + _ga_climb_dur + ri * _ga_return_interval

            else:
                # PHASE 4 — Re-approach: from re-approach entry to aircraft position.
                # Linear interpolation keeps gaps small and avoids jumping back to
                # distant STAR waypoints.
                rai = i - _GA_APP_PTS - _GA_CLIMB_PTS - _GA_RETURN_PTS
                reapp_progress = rai / max(_GA_REAPP_PTS - 1, 1)
                lon = _reapp_entry_lon + reapp_progress * (end_lon - _reapp_entry_lon)
                lat = _reapp_entry_lat + reapp_progress * (end_lat - _reapp_entry_lat)

                # Descent profile for re-approach
                _reapp_prof_prog = 0.5 + 0.5 * reapp_progress
                prof_alt, prof_spd, prof_vr = interpolate_profile(_ga_desc_prof, _reapp_prof_prog)
                alt = prof_alt

                if reapp_progress < 0.95:
                    target_hdg = _calculate_heading((lat, lon), (end_lat, end_lon))
                else:
                    target_hdg = current_heading
                _ga_reapp_interval = _ga_reapp_dur / max(_GA_REAPP_PTS, 1)
                _running_hdg = _smooth_heading(_running_hdg, target_hdg, 3.0, _ga_reapp_interval)
                heading = _running_hdg
                velocity = prof_spd
                vertical_rate = prof_vr
                phase = "approaching"
                t_offset = _ga_app_dur + _ga_climb_dur + _ga_return_dur + rai * _ga_reapp_interval

            _total_ga_dur = _ga_app_dur + _ga_climb_dur + _ga_return_dur + _ga_reapp_dur
            timestamp = now - timedelta(seconds=_total_ga_dur - t_offset)

            points.append({
                "timestamp": timestamp.isoformat(),
                "icao24": icao24,
                "callsign": callsign,
                "latitude": lat,
                "longitude": lon,
                "altitude": max(0, alt),
                "velocity": min(max(50, velocity), MAX_VELOCITY_KTS),
                "heading": heading % 360,
                "vertical_rate": vertical_rate,
                "on_ground": False,
                "flight_phase": phase,
                "data_source": "synthetic",
            })

        return points

    elif is_on_ground:
        # Aircraft is on ground - show approach + landing + taxi trajectory
        # Divide trajectory: 45% approach, 20% landing roll, 35% taxi
        # Realistic rollout: 1500-2500m from touchdown to taxi turnoff.

        # Landing roll direction along actual runway heading
        _rwy_heading = _get_runway_heading()
        if _rwy_heading is None:
            return []
        _rwy_heading_rad = math.radians(_rwy_heading)
        _roll_distance = 0.012  # ~1.3 km roll in degrees (touchdown to high-speed exit)
        roll_dlat = _roll_distance * math.cos(_rwy_heading_rad)
        roll_dlon = _roll_distance * math.sin(_rwy_heading_rad) / math.cos(math.radians(rwy_threshold_lat))

        # Adaptive point spacing: dense on ground, sparse in approach.
        # Real ADS-B has ~4-10s ground updates vs ~30-60s airborne.
        _APP_PTS = 28   # 35% of budget → approach (~58s intervals)
        _ROLL_PTS = 12  # 15% of budget → landing roll (~36s intervals)
        _TAXI_PTS = 40  # 50% of budget → taxi (~19s intervals → ~150m apart)

        _progress_schedule = []
        _time_offsets = []        # cumulative seconds from trajectory start
        _total_secs = minutes * 60

        # Phase durations (must sum to _total_secs)
        _app_dur = 0.45 * _total_secs   # 1620s
        _roll_dur = 0.20 * _total_secs  # 720s
        _taxi_dur = 0.35 * _total_secs  # 1260s

        _app_interval = _app_dur / max(_APP_PTS, 1)
        for k in range(_APP_PTS):
            _progress_schedule.append(0.45 * k / max(_APP_PTS - 1, 1))
            _time_offsets.append(k * _app_interval)

        _roll_interval = _roll_dur / max(_ROLL_PTS, 1)
        for k in range(_ROLL_PTS):
            _progress_schedule.append(0.45 + 0.20 * k / max(_ROLL_PTS - 1, 1))
            _time_offsets.append(_app_dur + k * _roll_interval)

        _taxi_interval = _taxi_dur / max(_TAXI_PTS, 1)
        for k in range(_TAXI_PTS):
            _progress_schedule.append(0.65 + 0.35 * k / max(_TAXI_PTS - 1, 1))
            _time_offsets.append(_app_dur + _roll_dur + k * _taxi_interval)

        num_points = len(_progress_schedule)

        _running_hdg = current_heading  # smooth heading across points
        for i, progress in enumerate(_progress_schedule):
            # Per-point time delta for heading smoothing
            _pt_interval = (_time_offsets[i] - _time_offsets[i - 1]) if i > 0 else _app_interval

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
                _running_hdg = _smooth_heading(_running_hdg, target_hdg, 3.0, _pt_interval)
                heading = _running_hdg

                phase = "approaching" if alt > 500 else "landing"
                velocity = prof_spd
                vertical_rate = prof_vr

            elif progress < 0.65:
                # LANDING ROLL: Decelerating on runway (20% of trajectory)
                roll_progress = (progress - 0.45) / 0.20

                # Move along runway heading
                lat = rwy_threshold_lat + roll_progress * roll_dlat
                lon = rwy_threshold_lon + roll_progress * roll_dlon
                alt = 0

                heading = _rwy_heading
                phase = "ground"
                velocity = 130 - roll_progress * 100  # Decelerate to 30 kts
                vertical_rate = 0

            else:
                # TAXI PHASE: Follow taxiway route from runway to current position
                taxi_progress = (progress - 0.65) / 0.35

                # Landing roll endpoint (must match the roll phase above)
                roll_end_lat = rwy_threshold_lat + roll_dlat
                roll_end_lon = rwy_threshold_lon + roll_dlon

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

            # Append point — timestamp from adaptive time offsets
            _total_duration = _time_offsets[-1]
            timestamp = now - timedelta(seconds=_total_duration - _time_offsets[i])

            points.append({
                "timestamp": timestamp.isoformat(),
                "icao24": icao24,
                "callsign": callsign,
                "latitude": lat,
                "longitude": lon,
                "altitude": max(0, alt),
                "velocity": min(max(10, velocity), MAX_VELOCITY_KTS),
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
                "velocity": min(max(50, velocity), MAX_VELOCITY_KTS),
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
            # Back-project a short trailing segment so the renderer
            # has >= 2 points (splitAtGaps drops single-point segments).
            back_dist = 0.02  # ~2.2 km behind aircraft
            back_bearing = (current_heading + 180) % 360
            back_lat = clamped_lat + back_dist * math.cos(math.radians(back_bearing))
            back_lon = clamped_lon + back_dist * math.sin(math.radians(back_bearing)) / math.cos(math.radians(clamped_lat))
            path_wps = [
                (back_lon, back_lat, final_alt + 300),
                (clamped_lon, clamped_lat, final_alt),
            ]
            path_count = 2
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
                    "velocity": min(max(100, velocity), MAX_VELOCITY_KTS),
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
    import src.ingestion.fallback as _fb

    cleared_flights = len(_flight_states)
    cleared_gates = len(_gate_states)

    # Clear flight state only — airport center is managed by the activate endpoint
    _flight_states.clear()
    _bearing_cache.clear()
    _st._last_update = 0.0
    _st.reset_max_approach_cache()
    _runway_states.clear()
    # Re-populate with current airport's runway names (dynamic, not hardcoded SFO)
    arr_rwy = _get_arrival_runway_name()
    _st._runway_28L = RunwayState()
    _st._runway_28R = RunwayState()
    _runway_states[arr_rwy] = _st._runway_28L
    recip = _get_reciprocal_designator(arr_rwy)
    if recip:
        _runway_states[recip] = _st._runway_28R
    _gate_states.clear()
    _fb._loaded_gates = None
    _st._occupied_gate_count = 0

    # Clear event buffers (drain functions clear under lock)
    drain_phase_transitions()
    drain_gate_events()
    drain_predictions()
    drain_turnaround_events()

    return {
        "cleared_flights": cleared_flights,
        "cleared_gates": cleared_gates,
        "status": "reset_complete",
    }

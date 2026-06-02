"""Runway and gate resource management.

RunwayState/GateState occupancy tracking, separation logic, gate
assignment, and taxi speed factors. Extracted from fallback.py.
"""

import math
import random
import re as _re
from datetime import datetime, timezone
from typing import Optional

from src.ingestion._clock import get_time

from src.ingestion._constants import (
    CROSSING_ZONE_DEG,
    DEFAULT_SEPARATION_NM,
    MIN_ARRIVAL_SEPARATION_S,
    MIN_TAXI_SEPARATION_ARRIVAL_DEG,
    MIN_TAXI_SEPARATION_DEG,
    NM_TO_DEG,
    WAKE_CATEGORY,
    WAKE_SEPARATION_NM,
)
from src.ingestion._geo import _calculate_heading, _distance_between
from src.ingestion._state import (
    FlightPhase,
    FlightState,
    GATE_BUFFER_SECONDS,
    GateState,
    MAX_APPROACH_AIRCRAFT,
    RunwayState,
    _flight_states,
    _flights_by_phase,
    _gate_conflict_count,
    _gate_states,
    _occupied_gate_count,
    _runway_states,
)
from src.simulation.diagnostics import diag_log


# ── Runway helpers ──────────────────────────────────────────────────────────

_scenario_closed_runways: set[str] = set()


def set_runway_closed(runway: str) -> None:
    _scenario_closed_runways.add(runway)


def set_runway_open(runway: str) -> None:
    _scenario_closed_runways.discard(runway)


def clear_runway_closures() -> None:
    _scenario_closed_runways.clear()


def _is_runway_scenario_open(runway: str) -> bool:
    """Check if runway is NOT scenario-closed (ignores occupancy)."""
    if runway in _scenario_closed_runways:
        return False
    recip = _get_reciprocal_designator(runway)
    if recip and recip in _scenario_closed_runways:
        return False
    return True


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
    from src.ingestion.fallback import _get_arrival_runway_name

    try:
        from app.backend.services.airport_config_service import get_airport_config_service
        service = get_airport_config_service()
        config = service.get_config()
        runways = config.get("osmRunways", [])
        if not runways:
            return _get_arrival_runway_name()

        runway_refs = []
        for rwy in runways:
            ref = rwy.get("ref") or rwy.get("name", "")
            if ref and len(rwy.get("geoPoints", [])) >= 2:
                runway_refs.append(ref)

        if not runway_refs:
            return _get_arrival_runway_name()

        arrival_rwy = _get_arrival_runway_name()

        if len(runway_refs) > 1:
            for ref in runway_refs:
                names = [n.strip() for n in ref.split("/")]
                if arrival_rwy in names:
                    continue
                return names[0]

        for ref in runway_refs:
            names = [n.strip() for n in ref.split("/")]
            if arrival_rwy in names:
                for n in names:
                    if n != arrival_rwy:
                        return n
                return names[0]

        return runway_refs[0].split("/")[0].strip()
    except Exception:
        return _get_arrival_runway_name()


# ── Gate state management ───────────────────────────────────────────────────


def _recount_occupied_gates() -> None:
    """Recompute _occupied_gate_count from gate states (called after init/reset)."""
    import src.ingestion._state as _st
    _st._occupied_gate_count = sum(1 for gs in _gate_states.values() if gs.occupied_by is not None)


def _init_gate_states():
    """Initialize gate states, re-syncing if OSM gates become available."""
    from src.ingestion.fallback import get_gates

    current_gates = get_gates()
    if not _gate_states or set(_gate_states.keys()) != set(current_gates.keys()):
        old_states = dict(_gate_states)
        _gate_states.clear()
        for gate in current_gates:
            if gate in old_states:
                _gate_states[gate] = old_states[gate]
            else:
                _gate_states[gate] = GateState()
        _recount_occupied_gates()


def _reset_gate_states():
    """Reset gate states when gates are reloaded."""
    import src.ingestion._state as _st
    _gate_states.clear()
    _st._occupied_gate_count = 0
    _init_gate_states()


# ── Wake turbulence separation ──────────────────────────────────────────────


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


# ── Approach separation ─────────────────────────────────────────────────────


def _find_aircraft_ahead_on_approach(state: FlightState) -> Optional[FlightState]:
    """Find the aircraft directly ahead on the approach path.

    "Ahead" means closer to the airport center (further along the approach).
    Uses distance-from-center so it works regardless of approach bearing.
    """
    from src.ingestion.fallback import get_airport_center

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
            continue

        other_dist_to_center = _distance_between(
            (other.latitude, other.longitude), center
        )
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
    from src.ingestion.fallback import get_airport_center

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
            continue

        vertical_sep = abs(state.altitude - other.altitude)
        if vertical_sep >= 1000:
            continue

        diag_log(
            "SEPARATION_LOSS", datetime.now(timezone.utc),
            icao24=state.icao24, leader=other_id,
            distance_nm=round(lateral_dist / NM_TO_DEG, 2),
            required_nm=round(required_dist / NM_TO_DEG, 2),
            vertical_ft=round(vertical_sep),
        )
        return False

    return True


# ── Runway occupancy ────────────────────────────────────────────────────────


def _is_runway_clear(runway: str = "") -> bool:
    """Check if runway is clear for landing or takeoff.

    Checks BOTH the given designator AND its reciprocal (e.g. '28L' and '10R')
    because they are the same physical runway. Also checks scenario closures.
    """
    if not runway:
        from src.ingestion.fallback import _get_arrival_runway_name
        runway = _get_arrival_runway_name()
    if runway in _scenario_closed_runways:
        return False
    if _get_runway_state(runway).occupied_by is not None:
        return False
    recip = _get_reciprocal_designator(runway)
    if recip:
        if recip in _scenario_closed_runways:
            return False
        if recip in _runway_states and _runway_states[recip].occupied_by is not None:
            return False
    return True


def _is_arrival_separation_met(runway: str = "") -> bool:
    """Check if minimum arrival separation time has elapsed since last landing."""
    if not runway:
        from src.ingestion.fallback import _get_arrival_runway_name
        runway = _get_arrival_runway_name()
    rs = _get_runway_state(runway)
    if rs.last_arrival_time == 0.0:
        return True
    return (get_time() - rs.last_arrival_time) >= MIN_ARRIVAL_SEPARATION_S


def _occupy_runway(icao24: str, runway: str = ""):
    """Mark runway as occupied by aircraft (both designators for same physical runway)."""
    if not runway:
        from src.ingestion.fallback import _get_arrival_runway_name
        runway = _get_arrival_runway_name()
    rs = _get_runway_state(runway)
    if rs.occupied_by is not None and rs.occupied_by != icao24:
        diag_log(
            "RUNWAY_CONFLICT", datetime.now(timezone.utc),
            runway=runway, occupant=rs.occupied_by, requester=icao24,
        )
    rs.occupied_by = icao24
    recip = _get_reciprocal_designator(runway)
    if recip:
        _get_runway_state(recip).occupied_by = icao24


def _release_runway(icao24: str, runway: str = "", aircraft_type: str = ""):
    """Release runway when aircraft clears. Stores wake category for departure separation."""
    if not runway:
        from src.ingestion.fallback import _get_arrival_runway_name
        runway = _get_arrival_runway_name()
    rs = _get_runway_state(runway)
    if rs.occupied_by == icao24:
        rs.occupied_by = None
        rs.last_arrival_time = get_time()
        if aircraft_type:
            rs.last_departure_type = _get_wake_category(aircraft_type)
            rs.last_departure_time = get_time()
    recip = _get_reciprocal_designator(runway)
    if recip and recip in _runway_states:
        rrs = _runway_states[recip]
        if rrs.occupied_by == icao24:
            rrs.occupied_by = None
            rrs.last_arrival_time = get_time()
            if aircraft_type:
                rrs.last_departure_type = _get_wake_category(aircraft_type)
                rrs.last_departure_time = get_time()


# ── Gate assignment ─────────────────────────────────────────────────────────


def _find_available_gate() -> Optional[str]:
    """Find a random available gate, preferring terminal gates over remote stands.

    Respects GATE_BUFFER_SECONDS — gates recently vacated are not eligible.
    Increments conflict counter when a gate is requested but all are in buffer.
    """
    import src.ingestion._state as _st

    _init_gate_states()
    current_time = get_time()

    available = [
        gate for gate, state in _gate_states.items()
        if state.occupied_by is None and current_time >= state.available_at
    ]
    if not available:
        in_buffer = [
            g for g, s in _gate_states.items()
            if s.occupied_by is None and current_time < s.available_at
        ]
        if in_buffer:
            _st._gate_conflict_count += 1
            diag_log(
                "GATE_CONFLICT", datetime.now(timezone.utc),
                gates_in_buffer=len(in_buffer),
            )
        return None

    terminal_gates = [g for g in available if not g.startswith("R")]
    if terminal_gates:
        return random.choice(terminal_gates)
    return random.choice(available)


def _resolve_preferred_gate(preferred: Optional[str]) -> Optional[str]:
    """Return preferred gate if it exists in OSM data and is currently available."""
    if not preferred:
        return None
    _init_gate_states()
    if preferred not in _gate_states:
        return None
    state = _gate_states[preferred]
    current_time = get_time()
    if state.occupied_by is None and current_time >= state.available_at:
        return preferred
    return None


def _find_overflow_gate() -> Optional[str]:
    """Find a gate for overflow (all occupied). Distributes across gates.

    Prefers gates whose occupant is departing (PUSHBACK/TAXI_TO_RUNWAY)
    over gates with parked aircraft, to avoid true double-occupancy.
    Falls back to soonest-to-free if no departing gates found.
    """
    _init_gate_states()
    if not _gate_states:
        return None
    departing_gates = []
    for gate, gs in _gate_states.items():
        if gs.occupied_by and gs.occupied_by in _flight_states:
            fs = _flight_states[gs.occupied_by]
            if fs.phase in (FlightPhase.PUSHBACK, FlightPhase.TAXI_TO_RUNWAY,
                            FlightPhase.TAKEOFF, FlightPhase.DEPARTING):
                departing_gates.append(gate)
    if departing_gates:
        return random.choice(departing_gates)
    sorted_gates = sorted(_gate_states.keys(), key=lambda g: _gate_states[g].available_at)
    top_n = min(5, len(sorted_gates))
    return random.choice(sorted_gates[:top_n])


def _occupy_gate(icao24: str, gate: str):
    """Mark gate as occupied, evicting previous occupant if needed."""
    import src.ingestion._state as _st

    _init_gate_states()
    if gate in _gate_states:
        prev = _gate_states[gate].occupied_by
        was_empty = prev is None
        if prev is not None and prev != icao24:
            from src.ingestion._event_buffers import emit_gate_event
            prev_state = _flight_states.get(prev)
            cs = prev_state.callsign if prev_state else prev
            atype = prev_state.aircraft_type if prev_state else "A320"
            emit_gate_event(prev, cs, gate, "release", atype)
        _gate_states[gate].occupied_by = icao24
        if was_empty:
            _st._occupied_gate_count += 1


def _release_gate(icao24: str, gate: str):
    """Release gate when aircraft departs, enforcing minimum buffer."""
    import src.ingestion._state as _st

    _init_gate_states()
    if gate in _gate_states and _gate_states[gate].occupied_by == icao24:
        _gate_states[gate].occupied_by = None
        _gate_states[gate].last_released = get_time()
        _gate_states[gate].available_at = get_time() + GATE_BUFFER_SECONDS
        _st._occupied_gate_count = max(0, _st._occupied_gate_count - 1)


def get_gate_conflict_count() -> int:
    """Return count of gate conflicts (attempted assignment before buffer expired)."""
    import src.ingestion._state as _st
    return _st._gate_conflict_count


def reset_gate_conflict_count() -> None:
    """Reset gate conflict counter (call at start of validation run)."""
    import src.ingestion._state as _st
    _st._gate_conflict_count = 0


# ── Taxi separation ─────────────────────────────────────────────────────────


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

    hdg_rad = math.radians(state.heading)
    fwd_x = math.sin(hdg_rad)
    fwd_y = math.cos(hdg_rad)

    sep_threshold = (
        MIN_TAXI_SEPARATION_ARRIVAL_DEG
        if state.phase == FlightPhase.TAXI_TO_GATE
        else MIN_TAXI_SEPARATION_DEG
    )
    slow_zone = sep_threshold * 2.0
    head_on_zone = sep_threshold * 3.0

    min_factor = 1.0
    head_on_hold = False

    _ground_move_ids = (
        _flights_by_phase[FlightPhase.TAXI_TO_GATE]
        | _flights_by_phase[FlightPhase.TAXI_TO_RUNWAY]
        | _flights_by_phase[FlightPhase.PUSHBACK]
        | _flights_by_phase[FlightPhase.LANDING]
        | _flights_by_phase[FlightPhase.TAKEOFF]
    )
    _ground_move_ids.discard(state.icao24)

    for icao24 in _ground_move_ids:
        other = _flight_states.get(icao24)
        if other is None or not other.on_ground:
            continue

        dist = _distance_between(
            (state.latitude, state.longitude),
            (other.latitude, other.longitude)
        )

        if dist < head_on_zone and other.phase in (
            FlightPhase.TAXI_TO_GATE, FlightPhase.TAXI_TO_RUNWAY,
            FlightPhase.PUSHBACK,
        ):
            heading_diff = abs(((state.heading - other.heading + 180) % 360) - 180)
            if heading_diff > 120:
                state_priority = 1 if state.phase == FlightPhase.TAXI_TO_GATE else 0
                other_priority = 1 if other.phase == FlightPhase.TAXI_TO_GATE else 0
                if state_priority != other_priority:
                    must_yield = state_priority < other_priority
                else:
                    must_yield = state.icao24 > other.icao24
                if must_yield:
                    head_on_hold = True

        if (dist < CROSSING_ZONE_DEG
            and state.velocity > 2 and other.velocity > 2
            and state.taxi_route and other.taxi_route
            and other.phase in (FlightPhase.TAXI_TO_GATE, FlightPhase.TAXI_TO_RUNWAY)
        ):
            crossing_hdg_diff = abs(((state.heading - other.heading + 180) % 360) - 180)
            if 60 < crossing_hdg_diff < 120:
                rel_lat = other.latitude - state.latitude
                rel_lon = other.longitude - state.longitude
                dot_me = rel_lon * fwd_x + rel_lat * fwd_y
                other_hdg_rad = math.radians(other.heading)
                dot_other = -rel_lon * math.sin(other_hdg_rad) + -rel_lat * math.cos(other_hdg_rad)
                if dot_me > 0 and dot_other > 0:
                    state_pri = 1 if state.phase == FlightPhase.TAXI_TO_GATE else 0
                    other_pri = 1 if other.phase == FlightPhase.TAXI_TO_GATE else 0
                    if state_pri != other_pri:
                        crossing_yield = state_pri < other_pri
                    else:
                        crossing_yield = state.icao24 > other.icao24
                    if crossing_yield:
                        if dist < sep_threshold:
                            return 0.0
                        ratio = (dist - sep_threshold) / (CROSSING_ZONE_DEG - sep_threshold)
                        min_factor = min(min_factor, 0.3 + 0.7 * ratio)

        if dist < slow_zone:
            dlat = other.latitude - state.latitude
            dlon = other.longitude - state.longitude
            dot = dlon * fwd_x + dlat * fwd_y

            if dist < 0.0002 and state.icao24 > other.icao24:
                return -1.0 if head_on_hold else 0.0

            if dot > 0:
                if dist < sep_threshold:
                    return -1.0 if head_on_hold else 0.0
                ratio = (dist - sep_threshold) / (slow_zone - sep_threshold)
                factor = 0.3 + 0.7 * ratio
                min_factor = min(min_factor, factor)

    if head_on_hold:
        return -1.0

    return min_factor


# ── Utility queries ─────────────────────────────────────────────────────────


def _count_aircraft_in_phase(phase: FlightPhase) -> int:
    """Count how many aircraft are currently in a specific phase.

    Uses the _flights_by_phase index for O(1) lookup instead of scanning
    all flight states. The index is kept in sync by _PhaseTrackedFlightStates.
    """
    return len(_flights_by_phase[phase])


def _get_approach_queue_position(icao24: str) -> int:
    """Get position in approach queue (0 = first/next to land)."""
    from src.ingestion.fallback import get_airport_center

    queue = [s for s in _flight_states.values()
             if s.phase in [FlightPhase.APPROACHING, FlightPhase.LANDING]]
    center = get_airport_center()
    queue.sort(key=lambda s: _distance_between((s.latitude, s.longitude), center))

    for i, s in enumerate(queue):
        if s.icao24 == icao24:
            return i
    return len(queue)

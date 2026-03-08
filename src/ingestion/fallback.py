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

import math
import random
import time
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass, field
from enum import Enum

from faker import Faker


fake = Faker()

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
    "CRJ9": "SMALL", "E175": "SMALL", "E190": "SMALL",
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

# Convert NM to degrees (approximate at this latitude)
# 1 NM ≈ 1/60 degree ≈ 0.0167 degrees
NM_TO_DEG = 1.0 / 60.0

# Minimum separation distances
MIN_APPROACH_SEPARATION_DEG = 3.0 * NM_TO_DEG  # 3 NM minimum on approach
MIN_TAXI_SEPARATION_DEG = 0.003  # ~300m for taxi operations (larger for 3D visibility)
MIN_GATE_SEPARATION_DEG = 0.010  # ~800m in 3D scale for gate area (prevents overlap)

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
}

CALLSIGN_PREFIXES = list(AIRLINE_FLEET.keys())

# Airport geometry (matching frontend airportLayout.ts)
AIRPORT_CENTER = (37.5, -122.0)

# Runway endpoints aligned with 3D scene
# 3D: Runway 28L at z=-100 (south), Runway 28R at z=100 (north)
# x from -500 to 500
RUNWAY_28L_WEST = (-122.05, 37.49)   # West end of runway 28L (x≈-400, z=100)
RUNWAY_28L_EAST = (-121.95, 37.49)   # East end of runway 28L (x≈400, z=100)
RUNWAY_28R_WEST = (-122.05, 37.51)   # West end of runway 28R (x≈-400, z=-100)
RUNWAY_28R_EAST = (-121.95, 37.51)   # East end of runway 28R (x≈400, z=-100)

# Terminal and gate positions (aligned with 3D jetbridge positions)
# 3D scene: terminal at z=0 (spans z=-40 to z=+40), gates SOUTH of terminal
# Aircraft at gates should be SOUTH of terminal (positive z = lower latitude)
# z = -(lat - 37.5) * 10000, so lat 37.492 → z = +80
TERMINAL_CENTER = (37.5, -122.0)

# Gate spacing calculation:
# - Aircraft wingspan: ~35m (A320/B737) to ~80m (A380)
# - Aircraft length: ~40m (A320/B737) to ~73m (A380)
# - 3D scale: 10000, so 0.015 deg lon ≈ 120 units spacing
# - Terminal edge at z=+40, need ~50m margin for aircraft nose + jetbridge
# - Gates at z=+90 gives 50 units margin from terminal edge
# - Wide spacing (0.015 deg = ~120 units) to prevent visual overlap in 3D
GATES = {
    # Gate positions SOUTH of terminal (lower lat = positive z)
    # Terminal edge at z=+40, gates at z≈+90 (50 units margin for aircraft)
    # Wide spacing (0.015 deg = ~120 units) for clean visual separation
    "A1": (37.491, -122.030),   # x≈-240, z≈+90 (wide-body capable)
    "A2": (37.491, -122.015),   # x≈-120, z≈+90
    "A3": (37.491, -122.000),   # x≈0, z≈+90 (center gate)
    "B1": (37.491, -121.985),   # x≈+120, z≈+90
    "B2": (37.491, -121.970),   # x≈+240, z≈+90 (wide-body capable)
}

# Taxiway waypoints aligned with 3D scene
# 3D: Runway 28R at z=+100 (south), terminal edge at z=+40, gates at z=+90
# Scale 10000: z=+100 → lat = 37.5 - 0.01 = 37.49
TAXI_WAYPOINTS_ARRIVAL = [
    (-122.000, 37.49),    # Exit runway 28R at z=+100
    (-122.000, 37.491),   # Approach gate area z=+90
]

TAXI_WAYPOINTS_DEPARTURE = [
    (-122.000, 37.491),   # Leave gate area z=+90
    (-122.000, 37.49),    # Join runway 28R at z=+100
    (-122.03, 37.49),     # Runway threshold west (x≈-240)
]

# ILS Approach to Runway 28L (heading 280°, from east to west)
# All waypoints at same latitude (37.49) for straight-in approach aligned with runway
# Standard 3° glideslope: ~318 ft per NM descent rate
# Runway 28L east threshold at (-121.95, 37.49)
APPROACH_WAYPOINTS = [
    (-121.75, 37.49, 6000),   # FAF - Final Approach Fix, ~12 NM out
    (-121.82, 37.49, 4000),   # Intermediate fix, ~8 NM out
    (-121.88, 37.49, 2000),   # 4 NM from threshold
    (-121.93, 37.49, 500),    # Short final, 1 NM from threshold
    (-121.95, 37.49, 50),     # Runway 28L threshold
]

# Departure path from Runway 28L (climb on runway heading, then turn)
# Standard departure: maintain runway heading to 3000ft before turn
# Runway 28L west end at (-122.05, 37.49)
DEPARTURE_WAYPOINTS = [
    (-122.08, 37.49, 1500),   # Initial climb, runway heading (280°)
    (-122.15, 37.49, 3000),   # Continue climb, runway heading
    (-122.22, 37.47, 5000),   # Turn south after 3000ft
    (-122.30, 37.44, 8000),   # Departure fix, climbing
]


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


# Global state storage
_flight_states: Dict[str, FlightState] = {}
_last_update: float = 0.0

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

@dataclass
class GateState:
    """Tracks gate occupancy."""
    occupied_by: Optional[str] = None  # icao24 of aircraft at gate
    available_at: float = 0.0          # When gate becomes available

# Global separation state
_runway_28L: RunwayState = RunwayState()
_runway_28R: RunwayState = RunwayState()
_gate_states: Dict[str, GateState] = {}

def _init_gate_states():
    """Initialize gate states if not done."""
    global _gate_states
    if not _gate_states:
        for gate in GATES:
            _gate_states[gate] = GateState()

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
    """Find the aircraft directly ahead on the approach path."""
    if state.phase not in [FlightPhase.APPROACHING, FlightPhase.LANDING]:
        return None

    closest_ahead = None
    closest_dist = float('inf')

    for icao24, other in _flight_states.items():
        if icao24 == state.icao24:
            continue
        if other.phase not in [FlightPhase.APPROACHING, FlightPhase.LANDING]:
            continue

        # Check if other aircraft is ahead (further along approach = lower longitude toward runway)
        if other.longitude < state.longitude:  # Closer to runway (west)
            dist = _distance_between(
                (state.latitude, state.longitude),
                (other.latitude, other.longitude)
            )
            if dist < closest_dist:
                closest_dist = dist
                closest_ahead = other

    return closest_ahead


def _find_last_aircraft_on_approach() -> Optional[FlightState]:
    """Find the aircraft furthest back in the approach queue (highest longitude).

    This is used when spawning new aircraft to ensure proper separation.
    """
    last_aircraft = None
    max_longitude = -float('inf')

    for icao24, state in _flight_states.items():
        if state.phase not in [FlightPhase.APPROACHING, FlightPhase.LANDING]:
            continue

        # Aircraft furthest from runway (highest longitude = furthest east)
        if state.longitude > max_longitude:
            max_longitude = state.longitude
            last_aircraft = state

    return last_aircraft

def _check_approach_separation(state: FlightState) -> bool:
    """Check if aircraft has sufficient separation from aircraft ahead."""
    ahead = _find_aircraft_ahead_on_approach(state)
    if ahead is None:
        return True  # No one ahead, clear to proceed

    current_dist = _distance_between(
        (state.latitude, state.longitude),
        (ahead.latitude, ahead.longitude)
    )
    required_dist = _get_required_separation(ahead.aircraft_type, state.aircraft_type)

    return current_dist >= required_dist

def _is_runway_clear(runway: str = "28R") -> bool:
    """Check if runway is clear for landing or takeoff."""
    runway_state = _runway_28R if runway == "28R" else _runway_28L
    return runway_state.occupied_by is None

def _occupy_runway(icao24: str, runway: str = "28R"):
    """Mark runway as occupied by aircraft."""
    runway_state = _runway_28R if runway == "28R" else _runway_28L
    runway_state.occupied_by = icao24

def _release_runway(icao24: str, runway: str = "28R"):
    """Release runway when aircraft clears."""
    runway_state = _runway_28R if runway == "28R" else _runway_28L
    if runway_state.occupied_by == icao24:
        runway_state.occupied_by = None
        runway_state.last_arrival_time = time.time()

def _find_available_gate() -> Optional[str]:
    """Find an available gate that isn't occupied."""
    _init_gate_states()
    current_time = time.time()

    for gate, state in _gate_states.items():
        if state.occupied_by is None and current_time >= state.available_at:
            return gate
    return None

def _occupy_gate(icao24: str, gate: str):
    """Mark gate as occupied."""
    _init_gate_states()
    if gate in _gate_states:
        _gate_states[gate].occupied_by = icao24

def _release_gate(icao24: str, gate: str):
    """Release gate when aircraft departs."""
    _init_gate_states()
    if gate in _gate_states and _gate_states[gate].occupied_by == icao24:
        _gate_states[gate].occupied_by = None
        _gate_states[gate].available_at = time.time() + 60  # 1 min cooldown

def _check_taxi_separation(state: FlightState) -> bool:
    """Check if aircraft has sufficient separation from others on ground."""
    if not state.on_ground:
        return True

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
        if dist < MIN_TAXI_SEPARATION_DEG:
            return False

    return True

def _count_aircraft_in_phase(phase: FlightPhase) -> int:
    """Count how many aircraft are currently in a specific phase."""
    return sum(1 for s in _flight_states.values() if s.phase == phase)

def _get_approach_queue_position(icao24: str) -> int:
    """Get position in approach queue (0 = first/next to land)."""
    queue = [s for s in _flight_states.values()
             if s.phase in [FlightPhase.APPROACHING, FlightPhase.LANDING]]
    # Sort by distance to runway (closest first)
    runway_pos = (RUNWAY_28L_EAST[1], RUNWAY_28L_EAST[0])
    queue.sort(key=lambda s: _distance_between((s.latitude, s.longitude), runway_pos))

    for i, s in enumerate(queue):
        if s.icao24 == icao24:
            return i
    return len(queue)


def _calculate_heading(from_pos: tuple, to_pos: tuple) -> float:
    """Calculate heading from one position to another."""
    lat1, lon1 = from_pos
    lat2, lon2 = to_pos

    dlon = lon2 - lon1
    dlat = lat2 - lat1

    # Calculate bearing
    angle = math.atan2(dlon, dlat)
    heading = math.degrees(angle)

    # Normalize to 0-360
    return (heading + 360) % 360


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


def _get_aircraft_type_for_airline(callsign: str) -> str:
    """Get a random aircraft type based on airline callsign."""
    if callsign and len(callsign) >= 3:
        airline_code = callsign[:3].upper()
        if airline_code in AIRLINE_FLEET:
            return random.choice(AIRLINE_FLEET[airline_code])
    # Default to common narrow-body types
    return random.choice(["A320", "B738", "A321", "B737"])


def _create_new_flight(icao24: str, callsign: str, phase: FlightPhase) -> FlightState:
    """Create a new flight in the specified phase with proper separation."""
    aircraft_type = _get_aircraft_type_for_airline(callsign)

    if phase == FlightPhase.APPROACHING:
        # Start on approach from the east WITH PROPER WAKE TURBULENCE SEPARATION
        base_wp = APPROACH_WAYPOINTS[0]

        # Find how many aircraft are already approaching
        approaching_count = _count_aircraft_in_phase(FlightPhase.APPROACHING)
        landing_count = _count_aircraft_in_phase(FlightPhase.LANDING)

        # Limit simultaneous approaches (realistic: max 4-5 in sequence)
        if approaching_count + landing_count >= 4:
            # Too many on approach - start as enroute instead
            return _create_new_flight(icao24, callsign, FlightPhase.ENROUTE)

        # Calculate position based on actual aircraft positions (not just count)
        last_aircraft = _find_last_aircraft_on_approach()

        if last_aircraft is None:
            # No aircraft on approach - start at base waypoint
            lat = base_wp[1] + random.uniform(-0.005, 0.005)
            lon = base_wp[0]
            alt = base_wp[2]
        else:
            # Calculate required separation based on wake turbulence categories
            # New aircraft is FOLLOWING the last aircraft, so we need separation
            # based on last_aircraft (lead) -> new_aircraft (follow)
            required_sep_deg = _get_required_separation(
                last_aircraft.aircraft_type,
                aircraft_type
            )
            # Add 20% buffer for safety margin
            required_sep_deg *= 1.2

            # Position new aircraft behind the last one (higher longitude = further east)
            lat = last_aircraft.latitude + random.uniform(-0.005, 0.005)
            lon = last_aircraft.longitude + required_sep_deg
            # Each aircraft further back is at higher altitude
            alt = last_aircraft.altitude + 500

        return FlightState(
            icao24=icao24,
            callsign=callsign,
            latitude=lat,
            longitude=lon,
            altitude=alt + random.uniform(-200, 200),
            velocity=180 + random.uniform(-10, 10),
            heading=_calculate_heading((lat, lon), (RUNWAY_28L_EAST[1], RUNWAY_28L_EAST[0])),
            vertical_rate=-800,
            on_ground=False,
            phase=phase,
            aircraft_type=aircraft_type,
            waypoint_index=0,
        )

    elif phase == FlightPhase.PARKED:
        # Start at a gate (facing the terminal, heading ~180)
        _init_gate_states()

        # Find an available gate
        gate = _find_available_gate()
        if gate is None:
            # All gates occupied - switch to approaching or enroute
            return _create_new_flight(icao24, callsign, FlightPhase.APPROACHING)

        lat, lon = GATES[gate]
        _occupy_gate(icao24, gate)

        return FlightState(
            icao24=icao24,
            callsign=callsign,
            latitude=lat,
            longitude=lon,
            altitude=0,
            velocity=0,
            heading=180,  # Facing terminal (south)
            vertical_rate=0,
            on_ground=True,
            phase=phase,
            aircraft_type=aircraft_type,
            assigned_gate=gate,
            time_at_gate=random.uniform(0, 300),  # Random time already parked
        )

    elif phase == FlightPhase.ENROUTE:
        # Cruising flight visible in 3D scene area
        lat = AIRPORT_CENTER[0] + random.uniform(-0.05, 0.05)
        lon = AIRPORT_CENTER[1] + random.uniform(-0.05, 0.05)
        heading = random.uniform(0, 360)
        return FlightState(
            icao24=icao24,
            callsign=callsign,
            latitude=lat,
            longitude=lon,
            altitude=random.uniform(8000, 15000),  # Lower for visibility
            velocity=random.uniform(400, 500),
            heading=heading,
            vertical_rate=random.uniform(-200, 200),
            on_ground=False,
            phase=phase,
            aircraft_type=aircraft_type,
        )

    elif phase == FlightPhase.TAXI_TO_GATE:
        # Just landed, taxiing from runway
        _init_gate_states()

        # Check if runway is occupied - if so, can't spawn here
        if not _is_runway_clear("28R"):
            return _create_new_flight(icao24, callsign, FlightPhase.APPROACHING)

        # Check if taxiway start position is clear (no other taxiing aircraft)
        wp = TAXI_WAYPOINTS_ARRIVAL[0]
        spawn_pos = (wp[1], wp[0])  # lat, lon

        for other_icao24, other in _flight_states.items():
            if other.on_ground and other.phase in [FlightPhase.TAXI_TO_GATE, FlightPhase.TAXI_TO_RUNWAY]:
                dist = _distance_between(spawn_pos, (other.latitude, other.longitude))
                if dist < MIN_TAXI_SEPARATION_DEG * 2:  # Buffer for spawn position
                    # Taxiway congested - spawn as approaching instead
                    return _create_new_flight(icao24, callsign, FlightPhase.APPROACHING)

        gate = _find_available_gate()
        if gate is None:
            # No gates available
            return _create_new_flight(icao24, callsign, FlightPhase.ENROUTE)

        _occupy_gate(icao24, gate)

        return FlightState(
            icao24=icao24,
            callsign=callsign,
            latitude=wp[1],
            longitude=wp[0],
            altitude=0,
            velocity=15,
            heading=0,  # Heading north toward terminal
            vertical_rate=0,
            on_ground=True,
            phase=phase,
            aircraft_type=aircraft_type,
            assigned_gate=gate,
            waypoint_index=0,
        )

    elif phase == FlightPhase.TAXI_TO_RUNWAY:
        # Departing, starting from a gate position
        _init_gate_states()

        # Find an available gate for the departing aircraft
        gate = _find_available_gate()
        if gate is None:
            # All gates occupied - can't spawn departing aircraft
            # Create as enroute instead to avoid gate collision
            return _create_new_flight(icao24, callsign, FlightPhase.ENROUTE)

        lat, lon = GATES[gate]
        _occupy_gate(icao24, gate)

        return FlightState(
            icao24=icao24,
            callsign=callsign,
            latitude=lat,
            longitude=lon,
            altitude=0,
            velocity=10,
            heading=180,  # Heading south toward runway
            vertical_rate=0,
            on_ground=True,
            phase=phase,
            aircraft_type=aircraft_type,
            assigned_gate=gate,
            waypoint_index=0,
        )

    # Default: random enroute
    return _create_new_flight(icao24, callsign, FlightPhase.ENROUTE)


def _update_flight_state(state: FlightState, dt: float) -> FlightState:
    """Update a flight's state based on its current phase.

    Implements FAA/ICAO separation standards:
    - Approach: 3-6 NM based on wake turbulence category
    - Runway: Single occupancy (one aircraft at a time)
    - Taxi: Visual separation (~150-300 ft)
    """

    if state.phase == FlightPhase.APPROACHING:
        # Descend toward airport following approach waypoints WITH SEPARATION
        if state.waypoint_index < len(APPROACH_WAYPOINTS):
            wp = APPROACH_WAYPOINTS[state.waypoint_index]
            target = (wp[1], wp[0])  # lat, lon
            target_alt = wp[2]

            # CHECK SEPARATION before moving
            has_separation = _check_approach_separation(state)
            queue_pos = _get_approach_queue_position(state.icao24)

            if has_separation:
                # Clear to proceed - move toward waypoint
                speed_factor = 0.002
                # Slow down if close to aircraft ahead
                ahead = _find_aircraft_ahead_on_approach(state)
                if ahead:
                    dist = _distance_nm((state.latitude, state.longitude),
                                       (ahead.latitude, ahead.longitude))
                    req_sep = _get_required_separation(ahead.aircraft_type, state.aircraft_type) / NM_TO_DEG
                    if dist < req_sep * 1.5:  # Within 1.5x required separation
                        speed_factor *= 0.5  # Slow down

                new_pos = _move_toward((state.latitude, state.longitude), target, speed_factor)
                state.latitude, state.longitude = new_pos

                # Descend
                state.altitude = _interpolate_altitude(state.altitude, target_alt, 300 * dt)
                state.velocity = 180 - (state.waypoint_index * 20)  # Slow down on approach
                state.vertical_rate = -800 if state.altitude > target_alt else 0
            else:
                # Too close to aircraft ahead - slow down / hold speed
                state.velocity = max(140, state.velocity - 10 * dt)  # Reduce speed
                state.vertical_rate = -200  # Reduce descent rate

            # Update heading regardless
            state.heading = _calculate_heading((state.latitude, state.longitude), target)

            # Check if reached waypoint
            if _distance_between((state.latitude, state.longitude), target) < 0.003:
                state.waypoint_index += 1
        else:
            # Transition to landing only if runway is clear
            if _is_runway_clear("28R"):
                state.phase = FlightPhase.LANDING
                state.waypoint_index = 0
                _occupy_runway(state.icao24, "28R")
            else:
                # Hold - orbit or slow down significantly
                state.velocity = max(130, state.velocity - 5 * dt)
                # Slight orbit pattern
                state.heading = (state.heading + 5 * dt) % 360

    elif state.phase == FlightPhase.LANDING:
        # Final touchdown sequence - land on runway 28R
        # Runway should already be marked as occupied
        runway_touchdown = (RUNWAY_28L_EAST[1], RUNWAY_28L_EAST[0])  # lat, lon
        new_pos = _move_toward((state.latitude, state.longitude), runway_touchdown, 0.002)
        state.latitude, state.longitude = new_pos
        state.altitude = max(0, state.altitude - 500 * dt)
        state.velocity = max(30, state.velocity - 20 * dt)
        state.heading = _calculate_heading(new_pos, runway_touchdown)

        if state.altitude <= 0:
            state.altitude = 0
            state.on_ground = True
            state.vertical_rate = 0
            state.phase = FlightPhase.TAXI_TO_GATE
            state.waypoint_index = 0
            # Release runway when exiting to taxiway
            _release_runway(state.icao24, "28R")
            # Find an available gate (don't just pick random)
            available_gate = _find_available_gate()
            if available_gate:
                state.assigned_gate = available_gate
                _occupy_gate(state.icao24, available_gate)
            else:
                # All gates occupied - assign random, will wait
                state.assigned_gate = random.choice(list(GATES.keys()))

    elif state.phase == FlightPhase.TAXI_TO_GATE:
        # Taxi along waypoints to assigned gate WITH SEPARATION
        if state.waypoint_index < len(TAXI_WAYPOINTS_ARRIVAL):
            wp = TAXI_WAYPOINTS_ARRIVAL[state.waypoint_index]
            target = (wp[1], wp[0])

            # Check taxi separation before moving
            if _check_taxi_separation(state):
                new_pos = _move_toward((state.latitude, state.longitude), target, 0.0003)
                state.latitude, state.longitude = new_pos
                state.velocity = 15  # Taxi speed ~15 knots
            else:
                # Hold position - too close to another aircraft
                state.velocity = 0

            state.heading = _calculate_heading((state.latitude, state.longitude), target)

            if _distance_between((state.latitude, state.longitude), target) < 0.0005:
                state.waypoint_index += 1
        else:
            # Head to gate
            gate_pos = GATES.get(state.assigned_gate, GATES["A1"])
            target = gate_pos

            # Check if our gate is still available
            _init_gate_states()
            gate_state = _gate_states.get(state.assigned_gate)
            if gate_state and gate_state.occupied_by and gate_state.occupied_by != state.icao24:
                # Gate was taken, find another
                new_gate = _find_available_gate()
                if new_gate:
                    state.assigned_gate = new_gate
                    _occupy_gate(state.icao24, new_gate)
                    target = GATES[new_gate]
                else:
                    # No gates available - hold position
                    state.velocity = 0
                    return state

            if _check_taxi_separation(state):
                new_pos = _move_toward((state.latitude, state.longitude), target, 0.0002)
                state.latitude, state.longitude = new_pos
                state.velocity = 8  # Slower near gate
            else:
                state.velocity = 0

            state.heading = _calculate_heading((state.latitude, state.longitude), target)

            if _distance_between((state.latitude, state.longitude), target) < 0.0003:
                state.phase = FlightPhase.PARKED
                state.velocity = 0
                state.time_at_gate = 0
                _occupy_gate(state.icao24, state.assigned_gate)

    elif state.phase == FlightPhase.PARKED:
        # Stay at gate for some time, then pushback
        state.velocity = 0
        state.time_at_gate += dt

        # After 5-10 minutes, start pushback
        if state.time_at_gate > random.uniform(300, 600):
            state.phase = FlightPhase.PUSHBACK
            state.phase_progress = 0

    elif state.phase == FlightPhase.PUSHBACK:
        # Slow pushback from gate WITH separation check
        if _check_taxi_separation(state):
            state.velocity = 3  # Very slow
            state.phase_progress += dt * 0.1
            # Move slightly south (away from terminal)
            state.latitude -= 0.00002 * dt
        else:
            state.velocity = 0  # Hold if blocked

        state.heading = 180  # Facing south during pushback

        if state.phase_progress >= 1.0:
            # Release gate when clear of it
            if state.assigned_gate:
                _release_gate(state.icao24, state.assigned_gate)
            state.phase = FlightPhase.TAXI_TO_RUNWAY
            state.waypoint_index = 0

    elif state.phase == FlightPhase.TAXI_TO_RUNWAY:
        # Taxi to runway WITH separation
        if state.waypoint_index < len(TAXI_WAYPOINTS_DEPARTURE):
            wp = TAXI_WAYPOINTS_DEPARTURE[state.waypoint_index]
            target = (wp[1], wp[0])

            if _check_taxi_separation(state):
                new_pos = _move_toward((state.latitude, state.longitude), target, 0.0003)
                state.latitude, state.longitude = new_pos
                state.velocity = 15
            else:
                state.velocity = 0  # Hold

            state.heading = _calculate_heading((state.latitude, state.longitude), target)

            if _distance_between((state.latitude, state.longitude), target) < 0.0005:
                state.waypoint_index += 1
        else:
            # At runway hold line - check if runway is clear before takeoff
            if _is_runway_clear("28R"):
                state.phase = FlightPhase.TAKEOFF
                state.heading = 280  # Runway heading
                _occupy_runway(state.icao24, "28R")
            else:
                # Hold short of runway
                state.velocity = 0

    elif state.phase == FlightPhase.TAKEOFF:
        # Accelerate down runway and lift off (runway heading ~280 = west)
        state.velocity = min(state.velocity + 30 * dt, 160)
        state.longitude -= 0.002 * dt  # Move west down runway
        state.heading = 280  # Runway heading

        if state.velocity >= 140:  # Rotation speed
            state.on_ground = False
            state.altitude += 1500 * dt
            state.vertical_rate = 2000

            if state.altitude > 500:
                # Release runway when airborne and clear
                _release_runway(state.icao24, "28R")
                state.phase = FlightPhase.DEPARTING
                state.waypoint_index = 0

    elif state.phase == FlightPhase.DEPARTING:
        # Climb out following departure path
        if state.waypoint_index < len(DEPARTURE_WAYPOINTS):
            wp = DEPARTURE_WAYPOINTS[state.waypoint_index]
            target = (wp[1], wp[0])
            target_alt = wp[2]

            new_pos = _move_toward((state.latitude, state.longitude), target, 0.002)
            state.latitude, state.longitude = new_pos
            state.altitude = _interpolate_altitude(state.altitude, target_alt, 500 * dt)
            state.velocity = 200 + state.waypoint_index * 50
            state.vertical_rate = 1500 if state.altitude < target_alt else 0
            state.heading = _calculate_heading(new_pos, target)

            if _distance_between(new_pos, target) < 0.005:
                state.waypoint_index += 1
        else:
            # Switch to enroute
            state.phase = FlightPhase.ENROUTE

    elif state.phase == FlightPhase.ENROUTE:
        # Cruise with minor variations
        state.latitude += math.cos(math.radians(state.heading)) * 0.001 * dt
        state.longitude += math.sin(math.radians(state.heading)) * 0.001 * dt

        # Slight random heading changes
        state.heading += random.uniform(-1, 1) * dt
        state.heading = state.heading % 360

        # Random chance to start approach
        if random.random() < 0.001 * dt:
            state.phase = FlightPhase.APPROACHING
            state.waypoint_index = 0

    return state


def _get_flight_phase_name(phase: FlightPhase) -> str:
    """Convert flight phase to API-compatible phase name."""
    phase_map = {
        FlightPhase.APPROACHING: "descending",
        FlightPhase.LANDING: "descending",
        FlightPhase.TAXI_TO_GATE: "ground",
        FlightPhase.PARKED: "ground",
        FlightPhase.PUSHBACK: "ground",
        FlightPhase.TAXI_TO_RUNWAY: "ground",
        FlightPhase.TAKEOFF: "climbing",
        FlightPhase.DEPARTING: "climbing",
        FlightPhase.ENROUTE: "cruising",
    }
    return phase_map.get(phase, "ground")


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

    # Initialize flights if needed
    if len(_flight_states) < count:
        # Predefined test flights - diversified phases to avoid conflicts
        # Only 5 gates available, so limit ground operations
        test_flights = [
            ("a12345", "UAL123", FlightPhase.APPROACHING),   # Arriving
            ("b67890", "DAL456", FlightPhase.ENROUTE),       # Cruising
            ("c11111", "SWA789", FlightPhase.ENROUTE),       # Cruising
            ("d22222", "AAL100", FlightPhase.PARKED),        # At gate
            ("e33333", "JBU555", FlightPhase.DEPARTING),     # Climbing out
        ]

        for icao24, callsign, phase in test_flights:
            if icao24 not in _flight_states:
                _flight_states[icao24] = _create_new_flight(icao24, callsign, phase)

        # Generate additional random flights
        while len(_flight_states) < count:
            icao24 = fake.hexify(text="^^^^^^", upper=False)
            if icao24 in _flight_states:
                continue

            prefix = random.choice(CALLSIGN_PREFIXES)
            flight_num = random.randint(100, 9999)
            callsign = f"{prefix}{flight_num}"

            # Count current phases to balance distribution
            parked_count = _count_aircraft_in_phase(FlightPhase.PARKED)
            approach_count = _count_aircraft_in_phase(FlightPhase.APPROACHING)
            taxi_count = (_count_aircraft_in_phase(FlightPhase.TAXI_TO_GATE) +
                         _count_aircraft_in_phase(FlightPhase.TAXI_TO_RUNWAY))

            # Distribute phases realistically WITH CAPACITY LIMITS
            # - Max 5 parked (gates)
            # - Max 4 on approach (separation)
            # - Max 2 taxiing at once
            # Adjust weights based on current counts to prevent overcrowding
            approach_weight = 0.15 if approach_count < 4 else 0.0
            parked_weight = 0.15 if parked_count < 5 else 0.0
            taxi_in_weight = 0.05 if taxi_count < 2 else 0.0
            taxi_out_weight = 0.05 if taxi_count < 2 else 0.0

            # Redistribute unused weight to enroute
            total_ground = approach_weight + parked_weight + taxi_in_weight + taxi_out_weight
            enroute_weight = 1.0 - total_ground - 0.05  # 0.05 for departing

            phase_weights = [
                (FlightPhase.ENROUTE, enroute_weight),
                (FlightPhase.APPROACHING, approach_weight),
                (FlightPhase.PARKED, parked_weight),
                (FlightPhase.TAXI_TO_GATE, taxi_in_weight),
                (FlightPhase.TAXI_TO_RUNWAY, taxi_out_weight),
                (FlightPhase.DEPARTING, 0.05),
            ]

            r = random.random()
            cumulative = 0
            selected_phase = FlightPhase.ENROUTE
            for phase, weight in phase_weights:
                cumulative += weight
                if r <= cumulative:
                    selected_phase = phase
                    break

            _flight_states[icao24] = _create_new_flight(icao24, callsign, selected_phase)

    # Update all flight states
    for icao24, state in list(_flight_states.items()):
        _flight_states[icao24] = _update_flight_state(state, dt)

    # Build response in OpenSky format
    states: List[List[Any]] = []

    for icao24, state in list(_flight_states.items())[:count]:
        state_vector = [
            state.icao24,                              # 0: icao24
            state.callsign.ljust(8),                   # 1: callsign
            "United States",                           # 2: origin_country
            int(current_time) - random.randint(0, 2), # 3: time_position
            int(current_time),                         # 4: last_contact
            state.longitude,                           # 5: longitude
            state.latitude,                            # 6: latitude
            state.altitude * 0.3048,                   # 7: baro_altitude (convert ft to m)
            state.on_ground,                           # 8: on_ground
            state.velocity * 0.514444,                 # 9: velocity (convert kts to m/s)
            state.heading,                             # 10: true_track
            state.vertical_rate * 0.00508,             # 11: vertical_rate (ft/min to m/s)
            None,                                      # 12: sensors
            state.altitude * 0.3048,                   # 13: geo_altitude
            f"{random.randint(1000, 7777):04d}",       # 14: squawk
            False,                                     # 15: spi
            0,                                         # 16: position_source
            random.randint(2, 6),                      # 17: category
            _get_flight_phase_name(state.phase),       # 18: flight_phase (custom)
            state.aircraft_type,                       # 19: aircraft_type (custom)
        ]
        states.append(state_vector)

    return {
        "time": int(current_time),
        "states": states,
    }


# Keep the test flights list for backward compatibility
TEST_FLIGHTS_WITH_TRAJECTORY = [
    {"icao24": "a12345", "callsign": "UAL123"},
    {"icao24": "b67890", "callsign": "DAL456"},
    {"icao24": "c11111", "callsign": "SWA789"},
    {"icao24": "d22222", "callsign": "AAL100"},
    {"icao24": "e33333", "callsign": "JBU555"},
]


def generate_synthetic_trajectory(icao24: str, minutes: int = 60, limit: int = 1000) -> List[Dict[str, Any]]:
    """Generate synthetic trajectory data for a flight.

    Creates a realistic approach-to-landing trajectory pattern for demo purposes.
    Works with mock mode when Delta tables are not available.

    Args:
        icao24: The ICAO24 address of the aircraft.
        minutes: Minutes of history to simulate.
        limit: Maximum number of points to return.

    Returns:
        List of trajectory points as dictionaries.
    """
    from datetime import datetime, timedelta, timezone

    # Find the flight in our test flights list
    flight_info = None
    for f in TEST_FLIGHTS_WITH_TRAJECTORY:
        if f["icao24"] == icao24:
            flight_info = f
            break

    # If not found, check in the flight states manager
    if flight_info is None and icao24 in _flight_states:
        state = _flight_states[icao24]
        flight_info = {"icao24": icao24, "callsign": state.callsign}

    if flight_info is None:
        return []

    callsign = flight_info.get("callsign", "UNKNOWN")

    # Generate trajectory points - simulate an approach pattern
    points = []
    num_points = min(limit, 30)  # Generate up to 30 points
    now = datetime.now(timezone.utc)
    interval_seconds = (minutes * 60) / num_points

    # Get the current flight state if available
    current_state = _flight_states.get(icao24)

    # Create trajectory based on flight's current phase
    # Use ILS approach path aligned with runway 28L (lat 37.49)
    for i in range(num_points):
        t = i / (num_points - 1) if num_points > 1 else 0  # Progress 0 to 1

        # Straight-in ILS approach aligned with runway 28L centerline (lat 37.49)
        if t < 0.2:
            # FAF - Initial approach at 12 NM, 6000 ft
            lat = 37.49  # On centerline
            lon = -121.75 + t * 0.35  # Moving west from -121.75 to -121.82
            alt = 6000 - t * 10000  # 6000 to 4000 ft
            phase = "approaching"
        elif t < 0.5:
            # Intermediate approach
            lat = 37.49  # On centerline
            lon = -121.82 + (t - 0.2) * 0.33  # -121.82 to -121.92
            alt = 4000 - (t - 0.2) * 6667  # 4000 to 2000 ft
            phase = "descending"
        elif t < 0.75:
            # Final approach - short final
            lat = 37.49  # On centerline
            lon = -121.92 + (t - 0.5) * 0.12  # -121.92 to -121.95
            alt = 2000 - (t - 0.5) * 8000  # 2000 to 0 ft
            phase = "landing"
        else:
            # On ground, taxiing to gate
            progress = (t - 0.75) / 0.25
            lat = 37.49 + progress * 0.001  # Move slightly north toward terminal
            lon = -121.95 - progress * 0.05  # Move west along taxiway
            alt = 0
            phase = "ground"

        # Calculate heading (280° for runway 28, roughly west)
        heading = 280 + random.uniform(-2, 2) if alt > 0 else 0
        velocity = 150 - t * 100 if alt > 0 else 15  # Slow down on approach
        vertical_rate = -500 if alt > 100 else 0

        timestamp = now - timedelta(seconds=interval_seconds * (num_points - 1 - i))

        points.append({
            "timestamp": timestamp.isoformat(),
            "icao24": icao24,
            "callsign": callsign,
            "latitude": lat + random.uniform(-0.0005, 0.0005),  # Small jitter
            "longitude": lon + random.uniform(-0.0005, 0.0005),
            "altitude": max(0, alt + random.uniform(-20, 20)),
            "velocity": max(10, velocity + random.uniform(-5, 5)),
            "heading": heading,
            "vertical_rate": vertical_rate,
            "on_ground": alt == 0,
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
    global _flight_states, _last_update, _runway_28L, _runway_28R, _gate_states

    cleared_flights = len(_flight_states)
    cleared_gates = len(_gate_states)

    # Clear all state
    _flight_states.clear()
    _last_update = 0.0
    _runway_28L = RunwayState()
    _runway_28R = RunwayState()
    _gate_states.clear()

    return {
        "cleared_flights": cleared_flights,
        "cleared_gates": cleared_gates,
        "status": "reset_complete",
    }

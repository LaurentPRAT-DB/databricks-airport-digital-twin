"""Synthetic flight data generator with realistic stateful movements.

Generates persistent flight states with realistic behaviors:
- Landing approach and touchdown
- Taxi from runway to gate
- Parked at gate
- Pushback and taxi to runway
- Takeoff and departure climb
"""

import math
import random
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

from faker import Faker


fake = Faker()

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
# 3D scene: terminal at z=0, jetbridges extend south toward z=+40
# Aircraft at gates should be SOUTH of terminal (positive z = lower latitude)
# z = -(lat - 37.5) * 10000, so lat 37.494 → z = +60
TERMINAL_CENTER = (37.5, -122.0)

# Gate spacing calculation:
# - Aircraft wingspan: ~35m (A320/B737) to ~80m (A380)
# - 3D scale: 10000, so 0.006 deg lon ≈ 48 units spacing
# - Need space for: aircraft (~25 units) + ground equipment (~15 units)
# - Minimum spacing: 0.006 deg longitude (~48 units) for narrow-body
GATES = {
    # Gate positions SOUTH of terminal (lower lat = positive z)
    # Terminal at z=0, runways at z=±100, gates at z≈+60
    # Wider spacing (0.008 deg = ~64 units) to avoid overlap and allow ground equipment
    "A1": (37.494, -122.016),   # x≈-128, z≈+60 (wide-body capable)
    "A2": (37.494, -122.008),   # x≈-64, z≈+60
    "A3": (37.494, -122.000),   # x≈0, z≈+60 (center gate)
    "B1": (37.494, -121.992),   # x≈+64, z≈+60
    "B2": (37.494, -121.984),   # x≈+128, z≈+60 (wide-body capable)
}

# Taxiway waypoints aligned with 3D scene
# 3D: Runway 28R at z=+100 (south), terminal at z=0, gates at z=+60
# Scale 10000: z=+100 → lat = 37.5 - 0.01 = 37.49
TAXI_WAYPOINTS_ARRIVAL = [
    (-122.000, 37.49),    # Exit runway 28R at z=+100
    (-122.000, 37.492),   # Taxiway heading north z=+80
    (-122.000, 37.494),   # Approach gate area z=+60
]

TAXI_WAYPOINTS_DEPARTURE = [
    (-122.000, 37.494),   # Leave gate area z=+60
    (-122.000, 37.492),   # Head to taxiway z=+80
    (-122.000, 37.49),    # Join runway 28R at z=+100
    (-122.03, 37.49),     # Runway threshold west (x≈-240)
]

# Approach path (from east, descending to runway 28R at z=+100)
# Approach from east/southeast, landing heading west
APPROACH_WAYPOINTS = [
    (-121.90, 37.48, 6000),   # Initial approach (x≈800, z≈200) - east of airport
    (-121.94, 37.49, 3000),   # Intermediate (x≈480, z≈100)
    (-121.97, 37.49, 1000),   # Final approach (x≈240, z≈100)
    (-122.00, 37.49, 50),     # Touchdown (x=0, z=100 - runway 28R)
]

# Departure path (climbing to west from runway 28R)
DEPARTURE_WAYPOINTS = [
    (-122.03, 37.49, 1500),   # Initial climb (x≈-240, z=100)
    (-122.06, 37.48, 4000),   # Continued climb (x≈-480, z=200)
    (-122.10, 37.46, 8000),   # Departure fix (x≈-800, z≈400)
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
    """Create a new flight in the specified phase."""
    aircraft_type = _get_aircraft_type_for_airline(callsign)

    if phase == FlightPhase.APPROACHING:
        # Start on approach from the east
        wp = APPROACH_WAYPOINTS[0]
        lat = wp[1] + random.uniform(-0.01, 0.01)
        lon = wp[0] + random.uniform(-0.01, 0.01)
        return FlightState(
            icao24=icao24,
            callsign=callsign,
            latitude=lat,
            longitude=lon,
            altitude=wp[2] + random.uniform(-500, 500),
            velocity=180 + random.uniform(-20, 20),
            heading=_calculate_heading((lat, lon), (RUNWAY_28L_EAST[1], RUNWAY_28L_EAST[0])),
            vertical_rate=-800,
            on_ground=False,
            phase=phase,
            aircraft_type=aircraft_type,
            waypoint_index=0,
        )

    elif phase == FlightPhase.PARKED:
        # Start at a gate (facing the terminal, heading ~180)
        gate = random.choice(list(GATES.keys()))
        lat, lon = GATES[gate]
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
        wp = TAXI_WAYPOINTS_ARRIVAL[0]
        gate = random.choice(list(GATES.keys()))
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
        gate = random.choice(list(GATES.keys()))
        lat, lon = GATES[gate]
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
    """Update a flight's state based on its current phase."""

    if state.phase == FlightPhase.APPROACHING:
        # Descend toward airport following approach waypoints
        if state.waypoint_index < len(APPROACH_WAYPOINTS):
            wp = APPROACH_WAYPOINTS[state.waypoint_index]
            target = (wp[1], wp[0])  # lat, lon
            target_alt = wp[2]

            # Move toward waypoint
            new_pos = _move_toward((state.latitude, state.longitude), target, 0.002)
            state.latitude, state.longitude = new_pos

            # Descend
            state.altitude = _interpolate_altitude(state.altitude, target_alt, 300 * dt)
            state.velocity = 180 - (state.waypoint_index * 20)  # Slow down on approach
            state.vertical_rate = -800 if state.altitude > target_alt else 0

            # Update heading
            state.heading = _calculate_heading(new_pos, target)

            # Check if reached waypoint
            if _distance_between(new_pos, target) < 0.003:
                state.waypoint_index += 1
        else:
            # Transition to landing
            state.phase = FlightPhase.LANDING
            state.waypoint_index = 0

    elif state.phase == FlightPhase.LANDING:
        # Final touchdown sequence - land on runway 28R (z=100, northern runway)
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
            state.assigned_gate = random.choice(list(GATES.keys()))

    elif state.phase == FlightPhase.TAXI_TO_GATE:
        # Taxi along waypoints to assigned gate
        if state.waypoint_index < len(TAXI_WAYPOINTS_ARRIVAL):
            wp = TAXI_WAYPOINTS_ARRIVAL[state.waypoint_index]
            target = (wp[1], wp[0])

            new_pos = _move_toward((state.latitude, state.longitude), target, 0.0003)
            state.latitude, state.longitude = new_pos
            state.velocity = 15  # Taxi speed ~15 knots
            state.heading = _calculate_heading((state.latitude, state.longitude), target)

            if _distance_between(new_pos, target) < 0.0005:
                state.waypoint_index += 1
        else:
            # Head to gate
            gate_pos = GATES.get(state.assigned_gate, GATES["A1"])
            target = gate_pos

            new_pos = _move_toward((state.latitude, state.longitude), target, 0.0002)
            state.latitude, state.longitude = new_pos
            state.velocity = 8  # Slower near gate
            state.heading = _calculate_heading((state.latitude, state.longitude), target)

            if _distance_between(new_pos, target) < 0.0003:
                state.phase = FlightPhase.PARKED
                state.velocity = 0
                state.time_at_gate = 0

    elif state.phase == FlightPhase.PARKED:
        # Stay at gate for some time, then pushback
        state.velocity = 0
        state.time_at_gate += dt

        # After 5-10 minutes, start pushback
        if state.time_at_gate > random.uniform(300, 600):
            state.phase = FlightPhase.PUSHBACK
            state.phase_progress = 0

    elif state.phase == FlightPhase.PUSHBACK:
        # Slow pushback from gate
        state.velocity = 3  # Very slow
        state.phase_progress += dt * 0.1

        # Move slightly south (away from terminal)
        state.latitude -= 0.00002 * dt
        state.heading = 180  # Facing south during pushback

        if state.phase_progress >= 1.0:
            state.phase = FlightPhase.TAXI_TO_RUNWAY
            state.waypoint_index = 0

    elif state.phase == FlightPhase.TAXI_TO_RUNWAY:
        # Taxi to runway
        if state.waypoint_index < len(TAXI_WAYPOINTS_DEPARTURE):
            wp = TAXI_WAYPOINTS_DEPARTURE[state.waypoint_index]
            target = (wp[1], wp[0])

            new_pos = _move_toward((state.latitude, state.longitude), target, 0.0003)
            state.latitude, state.longitude = new_pos
            state.velocity = 15
            state.heading = _calculate_heading((state.latitude, state.longitude), target)

            if _distance_between(new_pos, target) < 0.0005:
                state.waypoint_index += 1
        else:
            # At runway, begin takeoff
            state.phase = FlightPhase.TAKEOFF
            state.heading = 280  # Runway heading (10L = 280 degrees)

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
    cruise patterns.

    Args:
        count: Number of flights to generate (default 50).
        bbox: Bounding box (unused, kept for API compatibility).

    Returns:
        Dict with 'time' (int) and 'states' (list of lists) matching
        the OpenSky /states/all response format.
    """
    global _flight_states, _last_update

    current_time = datetime.utcnow().timestamp()
    dt = min(current_time - _last_update, 5.0) if _last_update > 0 else 1.0
    _last_update = current_time

    # Initialize flights if needed
    if len(_flight_states) < count:
        # Predefined test flights with trajectory history
        test_flights = [
            ("a12345", "UAL123", FlightPhase.TAXI_TO_GATE),
            ("b67890", "DAL456", FlightPhase.APPROACHING),
            ("c11111", "SWA789", FlightPhase.ENROUTE),
            ("d22222", "AAL100", FlightPhase.PARKED),
            ("e33333", "JBU555", FlightPhase.TAXI_TO_RUNWAY),
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

            # Distribute phases realistically
            phase_weights = [
                (FlightPhase.ENROUTE, 0.50),      # Most are enroute
                (FlightPhase.APPROACHING, 0.15),  # Some approaching
                (FlightPhase.PARKED, 0.15),       # Some at gates
                (FlightPhase.TAXI_TO_GATE, 0.08), # Few taxiing in
                (FlightPhase.TAXI_TO_RUNWAY, 0.07), # Few taxiing out
                (FlightPhase.DEPARTING, 0.05),    # Few departing
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

    # Create an approach trajectory (from far to runway)
    for i in range(num_points):
        t = i / (num_points - 1) if num_points > 1 else 0  # Progress 0 to 1

        # Interpolate along approach path
        if t < 0.3:
            # Initial approach - high altitude, far from airport
            lat = 37.52 - (t / 0.3) * 0.02
            lon = -121.92 - (t / 0.3) * 0.03
            alt = 6000 - (t / 0.3) * 3000
            phase = "approaching"
        elif t < 0.6:
            # Intermediate approach
            lat = 37.50 - ((t - 0.3) / 0.3) * 0.01
            lon = -121.95 - ((t - 0.3) / 0.3) * 0.03
            alt = 3000 - ((t - 0.3) / 0.3) * 2000
            phase = "descending"
        elif t < 0.8:
            # Final approach
            lat = 37.49
            lon = -121.98 - ((t - 0.6) / 0.2) * 0.02
            alt = 1000 - ((t - 0.6) / 0.2) * 900
            phase = "landing"
        else:
            # On ground, taxiing
            lat = 37.49 + ((t - 0.8) / 0.2) * 0.014
            lon = -122.0 - ((t - 0.8) / 0.2) * 0.004
            alt = 0
            phase = "ground"

        # Calculate heading (roughly west for approach)
        heading = 270 + random.uniform(-5, 5)
        velocity = 150 if alt > 0 else 15  # Ground speed
        vertical_rate = -500 if alt > 0 else 0

        timestamp = now - timedelta(seconds=interval_seconds * (num_points - 1 - i))

        points.append({
            "timestamp": timestamp.isoformat(),
            "icao24": icao24,
            "callsign": callsign,
            "latitude": lat + random.uniform(-0.001, 0.001),
            "longitude": lon + random.uniform(-0.001, 0.001),
            "altitude": max(0, alt + random.uniform(-50, 50)),
            "velocity": velocity + random.uniform(-5, 5),
            "heading": heading,
            "vertical_rate": vertical_rate,
            "on_ground": alt == 0,
            "flight_phase": phase,
            "data_source": "synthetic",
        })

    return points

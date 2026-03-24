"""Ground Support Equipment (GSE) allocation and turnaround model.

Defines GSE requirements per aircraft type, turnaround timing models,
and GSE dispatch with depot-based travel time estimation.
"""

import math
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional
import random

# GSE requirements by aircraft category
GSE_REQUIREMENTS = {
    # Narrow body aircraft
    "A319": {
        "pushback_tug": 1,
        "fuel_truck": 1,
        "belt_loader": 2,
        "passenger_stairs": 0,  # Jetbridge
        "catering_truck": 1,
        "lavatory_truck": 1,
        "ground_power": 1,
    },
    "A320": {
        "pushback_tug": 1,
        "fuel_truck": 1,
        "belt_loader": 2,
        "passenger_stairs": 0,
        "catering_truck": 1,
        "lavatory_truck": 1,
        "ground_power": 1,
    },
    "A321": {
        "pushback_tug": 1,
        "fuel_truck": 1,
        "belt_loader": 2,
        "passenger_stairs": 0,
        "catering_truck": 2,
        "lavatory_truck": 1,
        "ground_power": 1,
    },
    "B737": {
        "pushback_tug": 1,
        "fuel_truck": 1,
        "belt_loader": 2,
        "passenger_stairs": 0,
        "catering_truck": 1,
        "lavatory_truck": 1,
        "ground_power": 1,
    },
    "B738": {
        "pushback_tug": 1,
        "fuel_truck": 1,
        "belt_loader": 2,
        "passenger_stairs": 0,
        "catering_truck": 1,
        "lavatory_truck": 1,
        "ground_power": 1,
    },
    # Wide body aircraft
    "A330": {
        "pushback_tug": 1,
        "fuel_truck": 2,
        "belt_loader": 3,
        "passenger_stairs": 0,
        "catering_truck": 2,
        "lavatory_truck": 2,
        "ground_power": 1,
    },
    "A350": {
        "pushback_tug": 1,
        "fuel_truck": 2,
        "belt_loader": 3,
        "passenger_stairs": 0,
        "catering_truck": 2,
        "lavatory_truck": 2,
        "ground_power": 1,
    },
    "A380": {
        "pushback_tug": 1,
        "fuel_truck": 3,
        "belt_loader": 4,
        "passenger_stairs": 2,  # Upper deck remote stands
        "catering_truck": 4,
        "lavatory_truck": 3,
        "ground_power": 2,
    },
    "B777": {
        "pushback_tug": 1,
        "fuel_truck": 2,
        "belt_loader": 3,
        "passenger_stairs": 0,
        "catering_truck": 2,
        "lavatory_truck": 2,
        "ground_power": 1,
    },
    "B787": {
        "pushback_tug": 1,
        "fuel_truck": 2,
        "belt_loader": 3,
        "passenger_stairs": 0,
        "catering_truck": 2,
        "lavatory_truck": 2,
        "ground_power": 1,
    },
}

# Turnaround timing by aircraft category (in minutes)
TURNAROUND_TIMING = {
    "narrow_body": {
        "total_minutes": 45,
        "phases": {
            "arrival_taxi": 5,
            "chocks_on": 2,
            "deboarding": 8,
            "unloading": 10,
            "cleaning": 12,
            "catering": 15,
            "refueling": 18,
            "loading": 12,
            "boarding": 15,
            "chocks_off": 2,
            "pushback": 5,
            "departure_taxi": 8,
        }
    },
    "wide_body": {
        "total_minutes": 90,
        "phases": {
            "arrival_taxi": 8,
            "chocks_on": 2,
            "deboarding": 20,
            "unloading": 25,
            "cleaning": 20,
            "catering": 30,
            "refueling": 35,
            "loading": 25,
            "boarding": 30,
            "chocks_off": 2,
            "pushback": 8,
            "departure_taxi": 12,
        }
    },
}

# Phase dependencies and parallelism
PHASE_DEPENDENCIES = {
    "arrival_taxi": [],
    "chocks_on": ["arrival_taxi"],
    "deboarding": ["chocks_on"],
    "unloading": ["chocks_on"],  # Can happen in parallel with deboarding
    "cleaning": ["deboarding"],
    "catering": ["deboarding"],  # Can happen in parallel with cleaning
    "refueling": ["deboarding"],  # Can happen in parallel
    "loading": ["unloading"],
    "boarding": ["cleaning", "catering"],
    "chocks_off": ["boarding", "loading", "refueling"],
    "pushback": ["chocks_off"],
    "departure_taxi": ["pushback"],
}

# GSE colors for visualization
GSE_COLORS = {
    "pushback_tug": "#FFD700",      # Gold/Yellow
    "fuel_truck": "#FF4444",        # Red
    "belt_loader": "#4444FF",       # Blue
    "passenger_stairs": "#AAAAAA",  # Gray
    "catering_truck": "#FFFFFF",    # White
    "lavatory_truck": "#8B4513",    # Brown
    "ground_power": "#00FF00",      # Green
    "air_start": "#FFA500",         # Orange
}


def get_aircraft_category(aircraft_type: str) -> str:
    """Determine if aircraft is narrow or wide body."""
    wide_body_types = ["A330", "A340", "A350", "A380", "B747", "B767", "B777", "B787"]
    if aircraft_type in wide_body_types:
        return "wide_body"
    return "narrow_body"


def get_gse_requirements(aircraft_type: str) -> dict:
    """Get GSE requirements for an aircraft type."""
    if aircraft_type in GSE_REQUIREMENTS:
        return GSE_REQUIREMENTS[aircraft_type]
    # Default to A320 requirements for unknown types
    return GSE_REQUIREMENTS.get("A320", {
        "pushback_tug": 1,
        "fuel_truck": 1,
        "belt_loader": 2,
        "catering_truck": 1,
        "ground_power": 1,
    })


def get_turnaround_timing(aircraft_type: str) -> dict:
    """Get turnaround timing for an aircraft type."""
    category = get_aircraft_category(aircraft_type)
    return TURNAROUND_TIMING[category]


def calculate_turnaround_status(
    arrival_time: datetime,
    aircraft_type: str = "A320",
    current_time: Optional[datetime] = None,
) -> dict:
    """
    Calculate current turnaround status based on arrival time.

    Args:
        arrival_time: When aircraft arrived at gate
        aircraft_type: Aircraft type code
        current_time: Current time (defaults to now)

    Returns:
        Dictionary with current phase, progress, and timing
    """
    if current_time is None:
        current_time = datetime.now(timezone.utc)

    timing = get_turnaround_timing(aircraft_type)
    phases = timing["phases"]

    # Calculate elapsed time since arrival
    elapsed_minutes = (current_time - arrival_time).total_seconds() / 60

    # Find current phase
    cumulative = 0
    current_phase = "complete"
    phase_progress = 100
    total_progress = 100

    phase_order = [
        "arrival_taxi", "chocks_on", "deboarding", "unloading",
        "cleaning", "catering", "refueling", "loading",
        "boarding", "chocks_off", "pushback", "departure_taxi"
    ]

    for phase in phase_order:
        phase_duration = phases.get(phase, 5)
        if elapsed_minutes < cumulative + phase_duration:
            current_phase = phase
            phase_elapsed = elapsed_minutes - cumulative
            phase_progress = int((phase_elapsed / phase_duration) * 100)
            total_progress = int((elapsed_minutes / timing["total_minutes"]) * 100)
            break
        cumulative += phase_duration

    # Calculate estimated departure
    estimated_departure = arrival_time + timedelta(minutes=timing["total_minutes"])

    return {
        "current_phase": current_phase,
        "phase_progress_pct": min(phase_progress, 100),
        "total_progress_pct": min(total_progress, 100),
        "estimated_departure": estimated_departure,
        "elapsed_minutes": elapsed_minutes,
        "remaining_minutes": max(0, timing["total_minutes"] - elapsed_minutes),
    }


def generate_gse_positions(
    gate: str,
    aircraft_type: str = "A320",
    current_phase: str = "refueling",
    gate_lat: Optional[float] = None,
    gate_lon: Optional[float] = None,
) -> list[dict]:
    """
    Generate GSE unit positions around an aircraft at a gate.

    Args:
        gate: Gate identifier
        aircraft_type: Aircraft type code
        current_phase: Current turnaround phase
        gate_lat: Gate latitude (for travel time estimation)
        gate_lon: Gate longitude (for travel time estimation)

    Returns:
        List of GSE unit dictionaries with positions and travel info
    """
    requirements = get_gse_requirements(aircraft_type)
    gse_units = []
    unit_counter = {}

    # Position offsets for each GSE type (relative to aircraft center)
    position_templates = {
        "pushback_tug": [(0, -25)],  # Front of aircraft
        "fuel_truck": [(15, 0), (-15, 0)],  # Either side
        "belt_loader": [(10, -10), (-10, -10), (10, 10), (-10, 10)],  # Near cargo
        "passenger_stairs": [(8, 5), (-8, 5)],  # Door positions
        "catering_truck": [(12, 8), (-12, 8), (12, -8), (-12, -8)],
        "lavatory_truck": [(-15, -5)],  # Rear
        "ground_power": [(5, -15)],  # Forward
        "air_start": [(-5, -15)],
    }

    # Determine which GSE is active based on phase
    active_gse = {
        "arrival_taxi": [],
        "chocks_on": ["ground_power"],
        "deboarding": ["passenger_stairs", "ground_power"],
        "unloading": ["belt_loader", "ground_power"],
        "cleaning": ["ground_power"],
        "catering": ["catering_truck", "ground_power"],
        "refueling": ["fuel_truck", "ground_power"],
        "loading": ["belt_loader", "ground_power"],
        "boarding": ["passenger_stairs", "ground_power"],
        "chocks_off": [],
        "pushback": ["pushback_tug"],
        "departure_taxi": [],
        "complete": [],
    }

    active_types = active_gse.get(current_phase, [])

    for gse_type, count in requirements.items():
        if count == 0:
            continue

        positions = position_templates.get(gse_type, [(0, 0)])
        unit_counter[gse_type] = unit_counter.get(gse_type, 0)

        for i in range(count):
            unit_counter[gse_type] += 1
            unit_id = f"{gse_type.upper()[:3]}-{unit_counter[gse_type]:03d}"

            pos_idx = i % len(positions)
            base_x, base_y = positions[pos_idx]
            # Add small random offset
            x = base_x + random.uniform(-2, 2)
            y = base_y + random.uniform(-2, 2)

            # Determine status
            if gse_type in active_types:
                status = "servicing"
            elif current_phase in ["pushback", "departure_taxi", "complete"]:
                status = "available"
            else:
                status = "en_route" if random.random() < 0.3 else "available"

            # Estimate travel time from depot if gate coordinates available
            travel_info = None
            if gate_lat is not None and gate_lon is not None:
                travel_info = estimate_gse_travel_time(gate_lat, gate_lon, gse_type)

            gse_units.append({
                "unit_id": unit_id,
                "gse_type": gse_type,
                "status": status,
                "assigned_flight": None,  # Would be set by caller
                "assigned_gate": gate,
                "position_x": x,
                "position_y": y,
                "color": GSE_COLORS.get(gse_type, "#888888"),
                "depot": travel_info["depot_type"] if travel_info else None,
                "travel_time_min": travel_info["travel_time_min"] if travel_info else None,
            })

    return gse_units


def _get_gate_count(airport_code: str = "KSFO") -> int:
    """Get gate count for an airport from OSM config.

    Returns:
        Number of gates, defaulting to 120 (SFO baseline).
    """
    try:
        from app.backend.services.airport_config_service import (
            get_airport_config_service,
        )
        service = get_airport_config_service()
        config = service.get_config()
        gates = config.get("gates", [])
        if gates:
            return len(gates)
    except Exception:
        pass
    return 120  # SFO baseline


def get_fleet_status(airport_code: str = "KSFO") -> dict:
    """
    Get overall GSE fleet status scaled by airport size.

    Fleet sizes are proportional to gate count. SFO (120 gates) is the
    baseline. Larger airports get scaled-up fleets, smaller airports
    get scaled-down fleets.

    Args:
        airport_code: ICAO airport code to scale fleet for.

    Returns:
        Simulated fleet inventory and availability.
    """
    gate_count = _get_gate_count(airport_code)
    scale = gate_count / 120.0  # SFO = 120 gates baseline

    # SFO baseline fleet numbers
    base_fleet = {
        "pushback_tug": {"total": 15, "available": 8, "in_service": 5, "maintenance": 2},
        "fuel_truck": {"total": 12, "available": 6, "in_service": 5, "maintenance": 1},
        "belt_loader": {"total": 30, "available": 15, "in_service": 12, "maintenance": 3},
        "passenger_stairs": {"total": 8, "available": 5, "in_service": 2, "maintenance": 1},
        "catering_truck": {"total": 20, "available": 10, "in_service": 8, "maintenance": 2},
        "lavatory_truck": {"total": 10, "available": 5, "in_service": 4, "maintenance": 1},
        "ground_power": {"total": 25, "available": 12, "in_service": 10, "maintenance": 3},
    }

    fleet = {}
    for gse_type, counts in base_fleet.items():
        fleet[gse_type] = {
            k: max(1, round(v * scale)) for k, v in counts.items()
        }

    total_units = sum(v["total"] for v in fleet.values())
    available = sum(v["available"] for v in fleet.values())
    in_service = sum(v["in_service"] for v in fleet.values())
    maintenance = sum(v["maintenance"] for v in fleet.values())

    return {
        "total_units": total_units,
        "available": available,
        "in_service": in_service,
        "maintenance": maintenance,
        "by_type": fleet,
    }


# ---------------------------------------------------------------------------
# GSE depot model — tracks depot locations and computes dispatch travel time
# ---------------------------------------------------------------------------

# Depots are positioned relative to terminal areas.  Each depot type serves
# a specific equipment category and has a finite capacity.
GSE_DEPOT_TYPES = {
    "fuel_depot":       {"serves": ["fuel_truck"], "avg_speed_kph": 20},
    "tug_yard":         {"serves": ["pushback_tug"], "avg_speed_kph": 15},
    "cargo_depot":      {"serves": ["belt_loader"], "avg_speed_kph": 18},
    "catering_depot":   {"serves": ["catering_truck"], "avg_speed_kph": 25},
    "service_depot":    {"serves": ["lavatory_truck", "ground_power", "passenger_stairs"], "avg_speed_kph": 20},
}


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in metres between two coordinates."""
    R = 6_371_000
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = rlat2 - rlat1
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _get_airport_center() -> tuple[float, float]:
    """Get airport center coordinates from config service."""
    try:
        from app.backend.services.airport_config_service import get_airport_config_service
        service = get_airport_config_service()
        config = service.get_config()
        center = config.get("center", {})
        return (float(center.get("latitude", 37.6213)),
                float(center.get("longitude", -122.3790)))
    except Exception:
        return (37.6213, -122.3790)  # SFO fallback


def get_depot_locations(airport_code: str = "KSFO") -> list[dict]:
    """Generate depot locations around the airport perimeter.

    Depots are placed at cardinal offsets from the airport center,
    simulating real-world depot placement near terminal areas.
    """
    center_lat, center_lon = _get_airport_center()
    # Offset in degrees (~500-1000m from center)
    offsets = {
        "fuel_depot":     (0.005, -0.008),   # South-west (fuel farm)
        "tug_yard":       (-0.002, -0.003),  # Near terminal apron
        "cargo_depot":    (0.006, 0.002),     # East cargo area
        "catering_depot": (-0.004, 0.005),    # North service road
        "service_depot":  (0.001, -0.005),    # Central maintenance
    }

    depots = []
    for depot_type, (dlat, dlon) in offsets.items():
        info = GSE_DEPOT_TYPES[depot_type]
        depots.append({
            "depot_type": depot_type,
            "latitude": center_lat + dlat,
            "longitude": center_lon + dlon,
            "serves": info["serves"],
            "avg_speed_kph": info["avg_speed_kph"],
        })
    return depots


def estimate_gse_travel_time(
    gate_lat: float,
    gate_lon: float,
    gse_type: str,
    airport_code: str = "KSFO",
) -> dict:
    """Estimate GSE dispatch travel time from nearest depot to gate.

    Args:
        gate_lat: Gate latitude.
        gate_lon: Gate longitude.
        gse_type: Equipment type (e.g., "fuel_truck").
        airport_code: ICAO airport code.

    Returns:
        Dict with depot_type, distance_m, travel_time_min, and speed_kph.
    """
    depots = get_depot_locations(airport_code)

    # Find the depot that serves this GSE type
    best = None
    best_dist = float("inf")
    for depot in depots:
        if gse_type in depot["serves"]:
            dist = _haversine_m(gate_lat, gate_lon, depot["latitude"], depot["longitude"])
            # Routing factor: actual road path ~1.4x straight-line
            road_dist = dist * 1.4
            if road_dist < best_dist:
                best_dist = road_dist
                best = depot

    if best is None:
        # Fallback: generic depot at center
        center_lat, center_lon = _get_airport_center()
        best_dist = _haversine_m(gate_lat, gate_lon, center_lat, center_lon) * 1.4
        speed_kph = 18
    else:
        speed_kph = best["avg_speed_kph"]

    travel_time_min = (best_dist / 1000) / speed_kph * 60  # km / kph * 60 = min
    # Add dispatch overhead: 1-3 min for crew to board and start equipment
    dispatch_overhead = random.uniform(1.0, 3.0)

    return {
        "depot_type": best["depot_type"] if best else "generic",
        "distance_m": round(best_dist),
        "travel_time_min": round(travel_time_min + dispatch_overhead, 1),
        "speed_kph": speed_kph,
    }

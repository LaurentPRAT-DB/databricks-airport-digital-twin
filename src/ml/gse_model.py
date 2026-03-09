"""Ground Support Equipment (GSE) allocation and turnaround model.

Defines GSE requirements per aircraft type and turnaround timing models.
"""

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
) -> list[dict]:
    """
    Generate GSE unit positions around an aircraft at a gate.

    Args:
        gate: Gate identifier
        aircraft_type: Aircraft type code
        current_phase: Current turnaround phase

    Returns:
        List of GSE unit dictionaries with positions
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

            gse_units.append({
                "unit_id": unit_id,
                "gse_type": gse_type,
                "status": status,
                "assigned_flight": None,  # Would be set by caller
                "assigned_gate": gate,
                "position_x": x,
                "position_y": y,
                "color": GSE_COLORS.get(gse_type, "#888888"),
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

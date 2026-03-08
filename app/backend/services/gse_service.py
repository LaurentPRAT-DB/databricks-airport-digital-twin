"""Ground Support Equipment (GSE) service for turnaround operations.

Provides GSE status and turnaround tracking.
Reads from Lakebase first for persistence, falls back to generator.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
import random

from src.ml.gse_model import (
    calculate_turnaround_status,
    generate_gse_positions,
    get_fleet_status,
    get_gse_requirements,
    GSE_COLORS,
)
from app.backend.models.gse import (
    GSEUnit,
    GSEType,
    GSEStatus,
    TurnaroundPhase,
    TurnaroundStatus,
    TurnaroundResponse,
    GSEFleetStatus,
)
from app.backend.services.lakebase_service import get_lakebase_service

logger = logging.getLogger(__name__)


def _map_gse_type(gse_type_str: str) -> GSEType:
    """Map string GSE type to enum."""
    type_map = {
        "pushback_tug": GSEType.PUSHBACK_TUG,
        "fuel_truck": GSEType.FUEL_TRUCK,
        "belt_loader": GSEType.BELT_LOADER,
        "passenger_stairs": GSEType.PASSENGER_STAIRS,
        "catering_truck": GSEType.CATERING_TRUCK,
        "lavatory_truck": GSEType.LAVATORY_TRUCK,
        "ground_power": GSEType.GROUND_POWER,
        "air_start": GSEType.AIR_START,
    }
    return type_map.get(gse_type_str, GSEType.GROUND_POWER)


def _map_gse_status(status_str: str) -> GSEStatus:
    """Map string status to enum."""
    status_map = {
        "available": GSEStatus.AVAILABLE,
        "en_route": GSEStatus.EN_ROUTE,
        "servicing": GSEStatus.SERVICING,
        "returning": GSEStatus.RETURNING,
        "maintenance": GSEStatus.MAINTENANCE,
    }
    return status_map.get(status_str, GSEStatus.AVAILABLE)


def _map_turnaround_phase(phase_str: str) -> TurnaroundPhase:
    """Map string phase to enum."""
    phase_map = {
        "arrival_taxi": TurnaroundPhase.ARRIVAL_TAXI,
        "chocks_on": TurnaroundPhase.CHOCKS_ON,
        "deboarding": TurnaroundPhase.DEBOARDING,
        "unloading": TurnaroundPhase.UNLOADING,
        "cleaning": TurnaroundPhase.CLEANING,
        "catering": TurnaroundPhase.CATERING,
        "refueling": TurnaroundPhase.REFUELING,
        "loading": TurnaroundPhase.LOADING,
        "boarding": TurnaroundPhase.BOARDING,
        "chocks_off": TurnaroundPhase.CHOCKS_OFF,
        "pushback": TurnaroundPhase.PUSHBACK,
        "departure_taxi": TurnaroundPhase.DEPARTURE_TAXI,
        "complete": TurnaroundPhase.COMPLETE,
    }
    return phase_map.get(phase_str, TurnaroundPhase.COMPLETE)


def _dict_to_gse_unit(data: dict) -> GSEUnit:
    """Convert GSE dictionary to GSEUnit model."""
    return GSEUnit(
        unit_id=data["unit_id"],
        gse_type=_map_gse_type(data["gse_type"]),
        status=_map_gse_status(data["status"]),
        assigned_flight=data.get("assigned_flight"),
        assigned_gate=data.get("assigned_gate"),
        position_x=data.get("position_x", 0.0),
        position_y=data.get("position_y", 0.0),
    )


class GSEService:
    """Service for GSE and turnaround operations."""

    def __init__(self):
        """Initialize GSE service."""
        # Simulated active turnarounds cache
        self._active_turnarounds: dict[str, dict] = {}

    def get_turnaround_status(
        self,
        icao24: str,
        flight_number: Optional[str] = None,
        gate: Optional[str] = None,
        aircraft_type: str = "A320",
    ) -> TurnaroundResponse:
        """
        Get turnaround status for an aircraft.

        Args:
            icao24: Aircraft ICAO24 address
            flight_number: Flight number
            gate: Gate assignment
            aircraft_type: Aircraft type code

        Returns:
            TurnaroundResponse with current status
        """
        # Check if we have an existing turnaround
        if icao24 not in self._active_turnarounds:
            # Create a new turnaround starting 10-30 minutes ago
            arrival_offset = random.randint(10, 30)
            arrival_time = datetime.now(timezone.utc) - timedelta(minutes=arrival_offset)
            self._active_turnarounds[icao24] = {
                "arrival_time": arrival_time,
                "gate": gate or f"{random.choice(['A', 'B', 'C'])}{random.randint(1, 20)}",
                "aircraft_type": aircraft_type,
                "flight_number": flight_number,
            }

        turnaround_info = self._active_turnarounds[icao24]
        status = calculate_turnaround_status(
            arrival_time=turnaround_info["arrival_time"],
            aircraft_type=turnaround_info.get("aircraft_type", aircraft_type),
        )

        # Generate GSE positions
        gse_positions = generate_gse_positions(
            gate=turnaround_info["gate"],
            aircraft_type=turnaround_info.get("aircraft_type", aircraft_type),
            current_phase=status["current_phase"],
        )
        gse_units = [_dict_to_gse_unit(g) for g in gse_positions]

        turnaround = TurnaroundStatus(
            icao24=icao24,
            flight_number=turnaround_info.get("flight_number", flight_number),
            gate=turnaround_info["gate"],
            arrival_time=turnaround_info["arrival_time"],
            current_phase=_map_turnaround_phase(status["current_phase"]),
            phase_progress_pct=status["phase_progress_pct"],
            total_progress_pct=status["total_progress_pct"],
            estimated_departure=status["estimated_departure"],
            assigned_gse=gse_units,
            aircraft_type=turnaround_info.get("aircraft_type", aircraft_type),
        )

        logger.info(f"GSE service: {icao24} at {turnaround.gate}, phase: {turnaround.current_phase}")

        return TurnaroundResponse(turnaround=turnaround)

    def get_fleet_status(self) -> GSEFleetStatus:
        """
        Get overall GSE fleet status.

        Reads from Lakebase first for persistence, falls back to generator.

        Returns:
            GSEFleetStatus with fleet inventory
        """
        # Try Lakebase first (persisted data)
        lakebase = get_lakebase_service()
        lb_units = None

        if lakebase.is_available:
            lb_units = lakebase.get_gse_fleet()
            if lb_units:
                logger.debug(f"GSE fleet from Lakebase: {len(lb_units)} units")

        if lb_units:
            # Convert Lakebase data to model
            units = []
            available = 0
            in_service = 0
            maintenance = 0

            for u in lb_units:
                status = u.get("status", "available")
                if status == "available":
                    available += 1
                elif status in ("servicing", "en_route"):
                    in_service += 1
                elif status == "maintenance":
                    maintenance += 1

                units.append(GSEUnit(
                    unit_id=u["unit_id"],
                    gse_type=_map_gse_type(u["gse_type"]),
                    status=_map_gse_status(status),
                    assigned_flight=u.get("assigned_flight"),
                    assigned_gate=u.get("assigned_gate"),
                    position_x=float(u.get("position_x", 0) or 0),
                    position_y=float(u.get("position_y", 0) or 0),
                ))

            logger.info(f"GSE fleet status: {len(units)} total, {available} available (from Lakebase)")

            return GSEFleetStatus(
                total_units=len(units),
                available=available,
                in_service=in_service,
                maintenance=maintenance,
                units=units,
            )

        # Fallback to generator
        logger.debug("GSE fleet from generator")
        fleet = get_fleet_status()

        # Generate unit list
        units = []
        unit_id = 1
        for gse_type, counts in fleet["by_type"].items():
            for i in range(counts["total"]):
                if i < counts["in_service"]:
                    status = "servicing"
                    gate = f"{random.choice(['A', 'B', 'C'])}{random.randint(1, 20)}"
                elif i < counts["in_service"] + counts["available"]:
                    status = "available"
                    gate = None
                else:
                    status = "maintenance"
                    gate = None

                units.append(GSEUnit(
                    unit_id=f"{gse_type.upper()[:3]}-{unit_id:03d}",
                    gse_type=_map_gse_type(gse_type),
                    status=_map_gse_status(status),
                    assigned_gate=gate,
                    position_x=0.0,
                    position_y=0.0,
                ))
                unit_id += 1

        logger.info(f"GSE fleet status: {fleet['total_units']} total, {fleet['available']} available")

        return GSEFleetStatus(
            total_units=fleet["total_units"],
            available=fleet["available"],
            in_service=fleet["in_service"],
            maintenance=fleet["maintenance"],
            units=units,
        )

    def clear_turnaround(self, icao24: str) -> bool:
        """
        Clear a turnaround when aircraft departs.

        Args:
            icao24: Aircraft ICAO24 address

        Returns:
            True if cleared, False if not found
        """
        if icao24 in self._active_turnarounds:
            del self._active_turnarounds[icao24]
            return True
        return False


# Singleton instance
_gse_service: Optional[GSEService] = None


def get_gse_service() -> GSEService:
    """Get or create GSE service singleton."""
    global _gse_service
    if _gse_service is None:
        _gse_service = GSEService()
    return _gse_service

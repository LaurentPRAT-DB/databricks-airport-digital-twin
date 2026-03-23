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
from src.ingestion.fallback import get_flight_turnaround_info
from src.ingestion.schedule_generator import find_scheduled_departure

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

        Uses real simulation state when available (parked_since, assigned_gate,
        aircraft_type) and looks up scheduled departure from the FIDS schedule.
        Falls back to random fabrication only when the flight is not in the sim.

        Args:
            icao24: Aircraft ICAO24 address
            flight_number: Flight number
            gate: Gate assignment
            aircraft_type: Aircraft type code

        Returns:
            TurnaroundResponse with current status
        """
        # Try to get real data from simulation state
        sim_info = get_flight_turnaround_info(icao24)

        # If flight exists in sim but is NOT parked, return "not at gate" status
        # (G1 fix: turnaround phases must not start until aircraft is PARKED)
        if sim_info is not None and not sim_info.get("parked_since"):
            phase = sim_info.get("phase", "unknown")
            effective_callsign = sim_info.get("callsign") or flight_number
            effective_gate = sim_info.get("assigned_gate") or gate
            turnaround = TurnaroundStatus(
                icao24=icao24,
                flight_number=effective_callsign or "",
                gate=effective_gate or "",
                arrival_time=datetime.now(timezone.utc),
                current_phase=TurnaroundPhase.ARRIVAL,
                phase_progress_pct=0,
                total_progress_pct=0,
                estimated_departure=datetime.now(timezone.utc) + timedelta(hours=1),
                assigned_gse=[],
                aircraft_type=sim_info.get("aircraft_type") or aircraft_type,
            )
            return TurnaroundResponse(
                turnaround=turnaround,
                message=f"Aircraft not at gate (phase: {phase})",
            )

        if sim_info is not None and sim_info.get("parked_since"):
            # Use real simulation data
            arrival_time = sim_info["parked_since"]
            effective_gate = sim_info["assigned_gate"] or gate or "A1"
            effective_aircraft = sim_info["aircraft_type"] or aircraft_type
            effective_callsign = sim_info["callsign"] or flight_number

            # Look up scheduled departure from FIDS
            scheduled_dep = find_scheduled_departure(
                effective_callsign or "",
            )

            # Check if we have a real turnaround schedule from the simulation
            turnaround_schedule = sim_info.get("turnaround_schedule")
            turnaround_phase = sim_info.get("turnaround_phase", "")

            if turnaround_schedule and turnaround_phase:
                # Use real simulated turnaround phase
                phase_info = turnaround_schedule.get(turnaround_phase, {})
                phase_start = phase_info.get("start_offset_s", 0)
                phase_duration = phase_info.get("duration_s", 1)
                time_at_gate = sim_info.get("time_at_gate_seconds", 0)
                phase_elapsed = max(0, time_at_gate - phase_start)
                phase_progress = min(100, int((phase_elapsed / max(phase_duration, 1)) * 100))

                # Total progress: fraction of phases completed
                total_phases = len(turnaround_schedule)
                done_count = sum(1 for p in turnaround_schedule.values() if p.get("done"))
                # Add fractional progress of current phase
                total_progress = min(100, int(((done_count + phase_progress / 100) / max(total_phases, 1)) * 100))

                from src.ml.gse_model import get_turnaround_timing
                timing = get_turnaround_timing(effective_aircraft)
                estimated_departure = arrival_time + timedelta(minutes=timing["total_minutes"])

                status = {
                    "current_phase": turnaround_phase,
                    "phase_progress_pct": phase_progress,
                    "total_progress_pct": total_progress,
                    "estimated_departure": estimated_departure,
                    "elapsed_minutes": time_at_gate / 60,
                    "remaining_minutes": max(0, timing["total_minutes"] - time_at_gate / 60),
                }
            else:
                # Fallback: compute from elapsed time
                status = calculate_turnaround_status(
                    arrival_time=arrival_time,
                    aircraft_type=effective_aircraft,
                )

            # If we have a schedule, override estimated departure
            if scheduled_dep:
                sched_time_str = scheduled_dep.get("estimated_time") or scheduled_dep["scheduled_time"]
                status["estimated_departure"] = datetime.fromisoformat(sched_time_str)

            # Update cache so clear_turnaround works
            self._active_turnarounds[icao24] = {
                "arrival_time": arrival_time,
                "gate": effective_gate,
                "aircraft_type": effective_aircraft,
                "flight_number": effective_callsign,
            }
        else:
            # Fallback: fabricate turnaround data (flight not in sim)
            if icao24 not in self._active_turnarounds:
                arrival_offset = random.randint(10, 30)
                arrival_time = datetime.now(timezone.utc) - timedelta(minutes=arrival_offset)
                self._active_turnarounds[icao24] = {
                    "arrival_time": arrival_time,
                    "gate": gate or f"{random.choice(['A', 'B', 'C'])}{random.randint(1, 20)}",
                    "aircraft_type": aircraft_type,
                    "flight_number": flight_number,
                }

            effective_gate = self._active_turnarounds[icao24]["gate"]
            effective_aircraft = self._active_turnarounds[icao24].get("aircraft_type", aircraft_type)
            effective_callsign = self._active_turnarounds[icao24].get("flight_number", flight_number)
            arrival_time = self._active_turnarounds[icao24]["arrival_time"]

            status = calculate_turnaround_status(
                arrival_time=arrival_time,
                aircraft_type=effective_aircraft,
            )

        # Generate GSE positions
        gse_positions = generate_gse_positions(
            gate=effective_gate,
            aircraft_type=effective_aircraft,
            current_phase=status["current_phase"],
        )
        gse_units = [_dict_to_gse_unit(g) for g in gse_positions]

        turnaround = TurnaroundStatus(
            icao24=icao24,
            flight_number=effective_callsign or flight_number,
            gate=effective_gate,
            arrival_time=arrival_time,
            current_phase=_map_turnaround_phase(status["current_phase"]),
            phase_progress_pct=status["phase_progress_pct"],
            total_progress_pct=status["total_progress_pct"],
            estimated_departure=status["estimated_departure"],
            assigned_gse=gse_units,
            aircraft_type=effective_aircraft,
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

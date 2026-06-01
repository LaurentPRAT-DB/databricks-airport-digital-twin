"""Schedule endpoints — arrivals, departures, FIDS audit."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query

from app.backend.models.schedule import ScheduleResponse
from app.backend.services.schedule_service import get_schedule_service
from app.backend.services.flifo_service import get_flifo_service
from src.ingestion._schedule_queue import get_schedule_queue

router = APIRouter(prefix="/api", tags=["schedule"])


@router.get("/schedule/arrivals", response_model=ScheduleResponse)
async def get_arrivals(
    hours_ahead: int = Query(default=2, ge=1, le=12, description="Hours into future"),
    hours_behind: int = Query(default=1, ge=0, le=6, description="Hours into past"),
    limit: int = Query(default=100, ge=1, le=200, description="Max flights"),
    sim_time: Optional[str] = Query(default=None, description="Simulation clock ISO timestamp"),
) -> ScheduleResponse:
    """Get scheduled arrivals for FIDS display."""
    parsed_sim_time = None
    if sim_time:
        parsed_sim_time = datetime.fromisoformat(sim_time)
        if parsed_sim_time.tzinfo is None:
            parsed_sim_time = parsed_sim_time.replace(tzinfo=timezone.utc)

    service = get_schedule_service()
    return service.get_arrivals(
        hours_ahead=hours_ahead,
        hours_behind=hours_behind,
        limit=limit,
        sim_time=parsed_sim_time,
    )


@router.get("/schedule/departures", response_model=ScheduleResponse)
async def get_departures(
    hours_ahead: int = Query(default=2, ge=1, le=12, description="Hours into future"),
    hours_behind: int = Query(default=1, ge=0, le=6, description="Hours into past"),
    limit: int = Query(default=100, ge=1, le=200, description="Max flights"),
    sim_time: Optional[str] = Query(default=None, description="Simulation clock ISO timestamp"),
) -> ScheduleResponse:
    """Get scheduled departures for FIDS display."""
    parsed_sim_time = None
    if sim_time:
        parsed_sim_time = datetime.fromisoformat(sim_time)
        if parsed_sim_time.tzinfo is None:
            parsed_sim_time = parsed_sim_time.replace(tzinfo=timezone.utc)

    service = get_schedule_service()
    return service.get_departures(
        hours_ahead=hours_ahead,
        hours_behind=hours_behind,
        limit=limit,
        sim_time=parsed_sim_time,
    )


@router.get("/schedule/flifo/status")
async def get_flifo_status():
    """Get FLIFO data feed status."""
    flifo = get_flifo_service()
    queue = get_schedule_queue()
    return {
        "configured": flifo.is_available,
        "enabled": queue.enabled,
        "active": queue.is_active,
        "queued_arrivals": len(queue._arrivals),
        "queued_departures": len(queue._departures),
    }


@router.post("/schedule/flifo/toggle")
async def toggle_flifo(enabled: bool = Query(...)):
    """Enable or disable FLIFO data feed."""
    queue = get_schedule_queue()
    queue.enabled = enabled
    return {"enabled": queue.enabled}


@router.get("/schedule/audit")
async def audit_schedule():
    """Cross-reference live simulation flights with FIDS schedule data."""
    from src.ingestion.fallback import _flight_states

    service = get_schedule_service()
    arrivals = service.get_arrivals(hours_ahead=4, hours_behind=2, limit=200)
    departures = service.get_departures(hours_ahead=4, hours_behind=2, limit=200)

    fids_map: dict[str, dict] = {}
    for f in arrivals.flights:
        fids_map[f.flight_number.upper()] = {
            "flight_number": f.flight_number,
            "status": f.status.value,
            "scheduled_time": f.scheduled_time.isoformat(),
            "estimated_time": f.estimated_time.isoformat() if f.estimated_time else None,
            "gate": f.gate,
            "delay_minutes": f.delay_minutes,
            "flight_type": "arrival",
            "origin": f.origin,
            "destination": f.destination,
        }
    for f in departures.flights:
        fids_map[f.flight_number.upper()] = {
            "flight_number": f.flight_number,
            "status": f.status.value,
            "scheduled_time": f.scheduled_time.isoformat(),
            "estimated_time": f.estimated_time.isoformat() if f.estimated_time else None,
            "gate": f.gate,
            "delay_minutes": f.delay_minutes,
            "flight_type": "departure",
            "origin": f.origin,
            "destination": f.destination,
        }

    audit_entries = []
    matched = 0
    missing = 0

    for icao24, state in _flight_states.items():
        callsign = (state.callsign or "").strip().upper()
        if not callsign:
            continue

        fids_entry = fids_map.get(callsign)
        is_matched = fids_entry is not None

        if is_matched:
            matched += 1
        else:
            missing += 1

        entry = {
            "callsign": callsign,
            "icao24": icao24,
            "sim": {
                "phase": state.phase.value if hasattr(state.phase, 'value') else str(state.phase),
                "altitude": round(state.altitude, 0),
                "velocity": round(state.velocity, 0),
                "vertical_rate": round(state.vertical_rate, 0),
                "heading": round(state.heading % 360, 1),
                "latitude": round(state.latitude, 4),
                "longitude": round(state.longitude, 4),
                "on_ground": state.on_ground,
                "gate": state.assigned_gate,
                "origin": state.origin_airport,
                "destination": state.destination_airport,
                "aircraft_type": state.aircraft_type,
            },
            "fids": fids_entry,
            "matched": is_matched,
        }

        if is_matched:
            issues = []
            if fids_entry["gate"] and state.assigned_gate and fids_entry["gate"] != state.assigned_gate:
                issues.append(f"gate mismatch: sim={state.assigned_gate} fids={fids_entry['gate']}")
            entry["issues"] = issues

        audit_entries.append(entry)

    audit_entries.sort(key=lambda x: (x["matched"], x["callsign"]))

    return {
        "total_sim_flights": len(_flight_states),
        "total_fids_arrivals": len(arrivals.flights),
        "total_fids_departures": len(departures.flights),
        "matched": matched,
        "missing_from_fids": missing,
        "match_rate": f"{matched / max(1, matched + missing) * 100:.1f}%",
        "flights": audit_entries,
    }

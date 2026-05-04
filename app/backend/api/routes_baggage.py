"""Baggage handling endpoints — stats, per-flight info, alerts."""

from typing import Optional

from fastapi import APIRouter, Query

from app.backend.models.baggage import (
    FlightBaggageResponse,
    BaggageStatsResponse,
    BaggageAlertsResponse,
)
from app.backend.services.baggage_service import get_baggage_service

router = APIRouter(prefix="/api", tags=["baggage"])


@router.get("/baggage/stats", response_model=BaggageStatsResponse)
async def get_baggage_stats() -> BaggageStatsResponse:
    """Get overall baggage handling statistics."""
    service = get_baggage_service()
    return service.get_overall_stats()


@router.get("/baggage/flight/{flight_number}", response_model=FlightBaggageResponse)
async def get_flight_baggage(
    flight_number: str,
    aircraft_type: str = Query(default="A320", description="Aircraft type"),
    include_bags: bool = Query(default=False, description="Include bag list"),
) -> FlightBaggageResponse:
    """Get baggage information for a specific flight."""
    flight_phase = None
    try:
        from src.ingestion.fallback import _flight_states
        for state in _flight_states.values():
            if state.callsign and state.callsign.strip() == flight_number:
                flight_phase = state.phase.value if state.phase else None
                break
    except Exception:
        pass

    service = get_baggage_service()
    return service.get_flight_baggage(
        flight_number=flight_number,
        aircraft_type=aircraft_type,
        include_bags=include_bags,
        flight_phase=flight_phase,
    )


@router.get("/baggage/alerts", response_model=BaggageAlertsResponse)
async def get_baggage_alerts() -> BaggageAlertsResponse:
    """Get active baggage alerts."""
    service = get_baggage_service()
    return service.get_alerts()

"""REST API routes for ML predictions."""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from app.backend.services.prediction_service import (
    PredictionService,
    get_prediction_service,
)
from app.backend.services.flight_service import FlightService, get_flight_service
from src.ingestion.fallback import emit_prediction


# Response models
class DelayPredictionResponse(BaseModel):
    """Response model for delay prediction."""

    icao24: str = Field(description="Flight ICAO24 identifier")
    delay_minutes: float = Field(description="Predicted delay in minutes")
    confidence: float = Field(ge=0, le=1, description="Confidence score (0-1)")
    category: str = Field(description="Delay category: on_time, slight, moderate, severe")


class GateRecommendationResponse(BaseModel):
    """Response model for gate recommendation."""

    gate_id: str = Field(description="Recommended gate ID (e.g., A1, B3)")
    score: float = Field(ge=0, le=1, description="Recommendation score (0-1)")
    reasons: List[str] = Field(description="Reasons for recommendation")
    taxi_time: int = Field(description="Estimated taxi time in minutes")


class CongestionResponse(BaseModel):
    """Response model for area congestion."""

    area_id: str = Field(description="Area identifier (e.g., runway_28L)")
    area_type: str = Field(description="Area type: runway, taxiway, apron, terminal")
    level: str = Field(description="Congestion level: low, moderate, high, critical")
    flight_count: int = Field(ge=0, description="Number of flights in area")
    capacity: int = Field(ge=0, description="Area capacity (max concurrent flights)")
    wait_minutes: int = Field(ge=0, description="Estimated wait time in minutes")


class DelaysListResponse(BaseModel):
    """Response model for list of delay predictions."""

    delays: List[DelayPredictionResponse]
    count: int


class CongestionListResponse(BaseModel):
    """Response model for list of congestion areas."""

    areas: List[CongestionResponse]
    count: int


class CongestionSummaryResponse(BaseModel):
    """Response model for combined congestion + bottlenecks."""

    areas: List[CongestionResponse]
    bottlenecks: List[CongestionResponse]
    areas_count: int
    bottlenecks_count: int


# Router
prediction_router = APIRouter(prefix="/api/predictions", tags=["predictions"])


@prediction_router.get("/delays", response_model=DelaysListResponse)
async def get_delays(
    icao24: Optional[str] = Query(
        default=None, description="ICAO24 address for single flight"
    ),
    prediction_service: PredictionService = Depends(get_prediction_service),
    flight_service: FlightService = Depends(get_flight_service),
) -> DelaysListResponse:
    """
    Get delay predictions for flights.

    If icao24 is provided, returns prediction for that flight only.
    Otherwise, returns predictions for all current flights.
    """
    # Get current flights
    flight_response = await flight_service.get_flights()
    flights = [f.model_dump() for f in flight_response.flights]

    if icao24:
        # Filter to single flight
        flights = [f for f in flights if f.get("icao24") == icao24]

    if not flights:
        return DelaysListResponse(delays=[], count=0)

    # Get predictions
    try:
        predictions = await prediction_service.get_flight_predictions(flights)
    except Exception as e:
        logger.error(f"Delay prediction failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Prediction error: {str(e)}")
    delay_predictions = predictions.get("delays", {})

    delays = []
    for flight_icao24, pred in delay_predictions.items():
        delays.append(
            DelayPredictionResponse(
                icao24=flight_icao24,
                delay_minutes=pred.delay_minutes,
                confidence=pred.confidence,
                category=pred.delay_category,
            )
        )
        emit_prediction("delay", flight_icao24, {
            "delay_minutes": pred.delay_minutes,
            "confidence": pred.confidence,
            "category": pred.delay_category,
        })

    return DelaysListResponse(delays=delays, count=len(delays))


@prediction_router.get("/gates/{icao24}", response_model=List[GateRecommendationResponse])
async def get_gate_recommendations(
    icao24: str,
    top_k: int = Query(default=3, ge=1, le=10, description="Number of recommendations"),
    prediction_service: PredictionService = Depends(get_prediction_service),
    flight_service: FlightService = Depends(get_flight_service),
) -> List[GateRecommendationResponse]:
    """
    Get gate recommendations for a specific flight.

    Args:
        icao24: The ICAO24 address of the flight.
        top_k: Number of recommendations to return (default 3).

    Returns:
        List of gate recommendations sorted by score.
    """
    # Get flight data
    flight = await flight_service.get_flight_by_icao24(icao24)
    if flight is None:
        # Return default recommendation if flight not found
        flight_data = {"icao24": icao24, "callsign": ""}
    else:
        flight_data = flight.model_dump()

    recommendations = await prediction_service.get_gate_recommendations(
        flight_data, top_k=top_k
    )

    results = [
        GateRecommendationResponse(
            gate_id=rec.gate_id,
            score=rec.score,
            reasons=rec.reasons,
            taxi_time=rec.estimated_taxi_time,
        )
        for rec in recommendations
    ]
    for rec in recommendations:
        emit_prediction("gate_recommendation", icao24, {
            "gate_id": rec.gate_id,
            "score": rec.score,
            "reasons": rec.reasons,
            "taxi_time": rec.estimated_taxi_time,
        })
    return results


@prediction_router.get("/congestion", response_model=CongestionListResponse)
async def get_congestion(
    prediction_service: PredictionService = Depends(get_prediction_service),
    flight_service: FlightService = Depends(get_flight_service),
) -> CongestionListResponse:
    """
    Get congestion levels for all airport areas.

    Returns congestion data for runways, taxiways, and terminal aprons.
    """
    # Get current flights
    flight_response = await flight_service.get_flights()
    flights = [f.model_dump() for f in flight_response.flights]

    congestion = await prediction_service.get_congestion(flights)

    areas = [
        CongestionResponse(
            area_id=c.area_id,
            area_type=c.area_type,
            level=c.level.value,
            flight_count=c.flight_count,
            capacity=c.capacity,
            wait_minutes=c.predicted_wait_minutes,
        )
        for c in congestion
    ]
    for c in congestion:
        emit_prediction("congestion", None, {
            "area_id": c.area_id,
            "area_type": c.area_type,
            "level": c.level.value,
            "flight_count": c.flight_count,
            "capacity": c.capacity,
            "wait_minutes": c.predicted_wait_minutes,
        })

    return CongestionListResponse(areas=areas, count=len(areas))


@prediction_router.get("/bottlenecks", response_model=CongestionListResponse)
async def get_bottlenecks(
    prediction_service: PredictionService = Depends(get_prediction_service),
    flight_service: FlightService = Depends(get_flight_service),
) -> CongestionListResponse:
    """
    Get only HIGH and CRITICAL congestion areas (bottlenecks).

    Returns areas that may cause delays or require attention.
    """
    # Get current flights
    flight_response = await flight_service.get_flights()
    flights = [f.model_dump() for f in flight_response.flights]

    bottlenecks = await prediction_service.get_bottlenecks(flights)

    areas = [
        CongestionResponse(
            area_id=c.area_id,
            area_type=c.area_type,
            level=c.level.value,
            flight_count=c.flight_count,
            capacity=c.capacity,
            wait_minutes=c.predicted_wait_minutes,
        )
        for c in bottlenecks
    ]

    return CongestionListResponse(areas=areas, count=len(areas))


class KPICard(BaseModel):
    label: str
    value: str
    color: str = "slate"


class DelayRow(BaseModel):
    icao24: str
    callsign: str
    delay_minutes: float
    confidence: float
    category: str


class PredictionsDashboardResponse(BaseModel):
    kpi_cards: List[KPICard]
    congestion_areas: List[CongestionResponse]
    delay_table: List[DelayRow]
    total_flights: int


@prediction_router.get("/dashboard", response_model=PredictionsDashboardResponse)
async def get_predictions_dashboard(
    prediction_service: PredictionService = Depends(get_prediction_service),
    flight_service: FlightService = Depends(get_flight_service),
) -> PredictionsDashboardResponse:
    """Aggregate predictions dashboard: KPI summary + congestion + delays."""
    try:
        flight_response = await flight_service.get_flights()
        flight_dicts = [f.model_dump() for f in flight_response.flights]
    except Exception:
        flight_dicts = []
    total_flights = len(flight_dicts)

    if total_flights == 0:
        return PredictionsDashboardResponse(
            kpi_cards=[
                KPICard(label="On-Time", value="--", color="slate"),
                KPICard(label="Avg Delay", value="--", color="slate"),
                KPICard(label="Congestion", value="--", color="slate"),
                KPICard(label="Bottlenecks", value="--", color="slate"),
                KPICard(label="Avg Turnaround", value="--", color="slate"),
                KPICard(label="Active Flights", value="0", color="slate"),
            ],
            congestion_areas=[],
            delay_table=[],
            total_flights=0,
        )

    predictions = await prediction_service.get_flight_predictions(flight_dicts)
    congestion = await prediction_service.get_congestion(flight_dicts)

    # Delay aggregates
    delays = predictions.get("delays", {})
    delay_list = list(delays.values())
    on_time_count = sum(1 for d in delay_list if d.delay_minutes < 15)
    on_time_pct = round(on_time_count / max(total_flights, 1) * 100)
    avg_delay = round(sum(d.delay_minutes for d in delay_list) / max(len(delay_list), 1), 1)

    # Congestion aggregates
    level_rank = {"low": 0, "moderate": 1, "high": 2, "critical": 3}
    worst_level = "low"
    for c in congestion:
        if level_rank.get(c.level.value, 0) > level_rank.get(worst_level, 0):
            worst_level = c.level.value
    bottleneck_count = sum(1 for c in congestion if c.level.value in ("high", "critical"))

    # Turnaround average (from parked flights)
    parked = [f for f in flight_dicts if f.get("flight_phase") == "parked"]
    from src.ml.gse_model import get_turnaround_timing
    turnaround_minutes = []
    for f in parked:
        timing = get_turnaround_timing(f.get("aircraft_type", "A320"))
        turnaround_minutes.append(timing["total_minutes"])
    avg_turnaround = round(sum(turnaround_minutes) / max(len(turnaround_minutes), 1)) if turnaround_minutes else 55

    # KPI cards
    level_colors = {"low": "green", "moderate": "yellow", "high": "orange", "critical": "red"}
    kpi_cards = [
        KPICard(label="On-Time", value=f"{on_time_pct}%", color="green" if on_time_pct >= 80 else "orange" if on_time_pct >= 60 else "red"),
        KPICard(label="Avg Delay", value=f"{avg_delay}m", color="green" if avg_delay < 10 else "orange" if avg_delay < 30 else "red"),
        KPICard(label="Congestion", value=worst_level.capitalize(), color=level_colors.get(worst_level, "slate")),
        KPICard(label="Bottlenecks", value=str(bottleneck_count), color="green" if bottleneck_count == 0 else "red"),
        KPICard(label="Avg Turnaround", value=f"{avg_turnaround}m", color="blue"),
        KPICard(label="Active Flights", value=str(total_flights), color="blue"),
    ]

    # Congestion table sorted by severity
    congestion_areas = sorted(
        [
            CongestionResponse(
                area_id=c.area_id,
                area_type=c.area_type,
                level=c.level.value,
                flight_count=c.flight_count,
                capacity=c.capacity,
                wait_minutes=c.predicted_wait_minutes,
            )
            for c in congestion
        ],
        key=lambda a: -level_rank.get(a.level, 0),
    )

    # Delay table sorted by worst delay
    icao_to_callsign = {f.get("icao24", ""): f.get("callsign", "").strip() for f in flight_dicts}
    delay_table = sorted(
        [
            DelayRow(
                icao24=icao24,
                callsign=icao_to_callsign.get(icao24, icao24),
                delay_minutes=round(pred.delay_minutes, 1),
                confidence=round(pred.confidence, 2),
                category=pred.delay_category,
            )
            for icao24, pred in delays.items()
        ],
        key=lambda r: -r.delay_minutes,
    )

    return PredictionsDashboardResponse(
        kpi_cards=kpi_cards,
        congestion_areas=congestion_areas,
        delay_table=delay_table,
        total_flights=total_flights,
    )


@prediction_router.get("/congestion-summary", response_model=CongestionSummaryResponse)
async def get_congestion_summary(
    prediction_service: PredictionService = Depends(get_prediction_service),
    flight_service: FlightService = Depends(get_flight_service),
) -> CongestionSummaryResponse:
    """
    Get congestion levels and bottlenecks in a single response.

    Returns all congestion areas plus a filtered subset of high/critical bottlenecks,
    avoiding duplicate flight fetches.
    """
    flight_response = await flight_service.get_flights()
    flights = [f.model_dump() for f in flight_response.flights]

    congestion = await prediction_service.get_congestion(flights)

    all_areas = [
        CongestionResponse(
            area_id=c.area_id,
            area_type=c.area_type,
            level=c.level.value,
            flight_count=c.flight_count,
            capacity=c.capacity,
            wait_minutes=c.predicted_wait_minutes,
        )
        for c in congestion
    ]

    bottleneck_areas = [a for a in all_areas if a.level in ("high", "critical")]

    return CongestionSummaryResponse(
        areas=all_areas,
        bottlenecks=bottleneck_areas,
        areas_count=len(all_areas),
        bottlenecks_count=len(bottleneck_areas),
    )

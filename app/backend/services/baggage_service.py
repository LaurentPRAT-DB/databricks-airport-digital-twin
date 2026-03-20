"""Baggage handling service for bag tracking and statistics.

Provides baggage data.
Reads from Lakebase first for persistence, falls back to generator.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from src.ingestion.baggage_generator import (
    generate_bags_for_flight,
    get_flight_baggage_stats,
    generate_baggage_alerts,
    get_overall_baggage_stats,
)
from app.backend.models.baggage import (
    Bag,
    BagStatus,
    FlightBaggageStats,
    FlightBaggageResponse,
    BaggageStatsResponse,
    BaggageAlert,
    BaggageAlertsResponse,
)
from app.backend.services.lakebase_service import get_lakebase_service

logger = logging.getLogger(__name__)


def _map_bag_status(status_str: str) -> BagStatus:
    """Map string status to enum."""
    status_map = {
        "checked_in": BagStatus.CHECKED_IN,
        "security_screening": BagStatus.SECURITY_SCREENING,
        "sorted": BagStatus.SORTED,
        "loaded": BagStatus.LOADED,
        "in_transit": BagStatus.IN_TRANSIT,
        "unloaded": BagStatus.UNLOADED,
        "on_carousel": BagStatus.ON_CAROUSEL,
        "claimed": BagStatus.CLAIMED,
        "misconnect": BagStatus.MISCONNECT,
        "lost": BagStatus.LOST,
    }
    return status_map.get(status_str, BagStatus.CHECKED_IN)


def _dict_to_bag(data: dict) -> Bag:
    """Convert bag dictionary to Bag model."""
    return Bag(
        bag_id=data["bag_id"],
        flight_number=data["flight_number"],
        passenger_name=data.get("passenger_name"),
        status=_map_bag_status(data["status"]),
        is_connecting=data.get("is_connecting", False),
        connecting_flight=data.get("connecting_flight"),
        origin=data.get("origin"),
        destination=data.get("destination"),
        check_in_time=datetime.fromisoformat(data["check_in_time"]) if data.get("check_in_time") else None,
        carousel=data.get("carousel"),
    )


def _dict_to_stats(data: dict) -> FlightBaggageStats:
    """Convert stats dictionary to FlightBaggageStats model."""
    return FlightBaggageStats(
        flight_number=data["flight_number"],
        total_bags=data["total_bags"],
        checked_in=data.get("checked_in", 0),
        loaded=data.get("loaded", 0),
        unloaded=data.get("unloaded", 0),
        on_carousel=data.get("on_carousel", 0),
        loading_progress_pct=data.get("loading_progress_pct", 0),
        connecting_bags=data.get("connecting_bags", 0),
        misconnects=data.get("misconnects", 0),
        carousel=data.get("carousel"),
    )


def _dict_to_alert(data: dict) -> BaggageAlert:
    """Convert alert dictionary to BaggageAlert model."""
    return BaggageAlert(
        alert_id=data["alert_id"],
        alert_type=data["alert_type"],
        bag_id=data["bag_id"],
        flight_number=data["flight_number"],
        connecting_flight=data.get("connecting_flight"),
        message=data["message"],
        created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(timezone.utc),
        resolved=data.get("resolved", False),
    )


class BaggageService:
    """Service for baggage handling operations."""

    def __init__(self):
        """Initialize baggage service."""
        pass

    def get_flight_baggage(
        self,
        flight_number: str,
        aircraft_type: str = "A320",
        origin: str = "SFO",
        destination: str = "LAX",
        is_arrival: bool = True,
        include_bags: bool = False,
        bag_limit: int = 10,
        flight_phase: str | None = None,
    ) -> FlightBaggageResponse:
        """
        Get baggage information for a flight.

        Reads from Lakebase first for persistence, falls back to generator.

        Args:
            flight_number: Flight number
            aircraft_type: Aircraft type code
            origin: Origin airport
            destination: Destination airport
            is_arrival: Whether this is an arrival
            include_bags: Whether to include individual bag list
            bag_limit: Maximum bags to return in list

        Returns:
            FlightBaggageResponse with stats and optionally bags
        """
        # Try Lakebase first (persisted data)
        lakebase = get_lakebase_service()
        stats_dict = None

        if lakebase.is_available:
            stats_dict = lakebase.get_baggage_stats(flight_number)
            if stats_dict:
                logger.debug(f"Baggage stats from Lakebase for {flight_number}")

        # Fallback to generator
        if not stats_dict:
            logger.debug(f"Baggage stats from generator for {flight_number}")
            stats_dict = get_flight_baggage_stats(
                flight_number=flight_number,
                aircraft_type=aircraft_type,
                origin=origin,
                destination=destination,
                is_arrival=is_arrival,
                flight_phase=flight_phase,
            )

        stats = _dict_to_stats(stats_dict)

        bags = []
        if include_bags:
            raw_bags = generate_bags_for_flight(
                flight_number=flight_number,
                aircraft_type=aircraft_type,
                origin=origin,
                destination=destination,
                is_arrival=is_arrival,
            )
            bags = [_dict_to_bag(b) for b in raw_bags[:bag_limit]]

        logger.info(f"Baggage service: {flight_number} has {stats.total_bags} bags, {stats.loading_progress_pct}% loaded")

        return FlightBaggageResponse(
            stats=stats,
            bags=bags,
        )

    def get_overall_stats(self) -> BaggageStatsResponse:
        """
        Get overall baggage handling statistics.

        Returns:
            BaggageStatsResponse with airport-wide stats
        """
        stats = get_overall_baggage_stats()

        logger.info(f"Baggage stats: {stats['total_bags_today']} today, {stats['misconnect_rate_pct']}% misconnect")

        return BaggageStatsResponse(
            total_bags_today=stats["total_bags_today"],
            bags_in_system=stats["bags_in_system"],
            loaded_departures=stats["loaded_departures"],
            delivered_arrivals=stats["delivered_arrivals"],
            connecting_bags=stats["connecting_bags"],
            misconnects=stats["misconnects"],
            misconnect_rate_pct=stats["misconnect_rate_pct"],
            avg_processing_time_min=stats["avg_processing_time_min"],
        )

    def get_alerts(self, flight_numbers: Optional[list[str]] = None) -> BaggageAlertsResponse:
        """
        Get active baggage alerts.

        Args:
            flight_numbers: Optional list of flight numbers to check

        Returns:
            BaggageAlertsResponse with active alerts
        """
        if flight_numbers is None:
            # Generate some default flight numbers
            flight_numbers = [
                f"UA{i}" for i in range(100, 120)
            ] + [
                f"DL{i}" for i in range(200, 210)
            ]

        raw_alerts = generate_baggage_alerts(flight_numbers)
        alerts = [_dict_to_alert(a) for a in raw_alerts]

        logger.info(f"Baggage alerts: {len(alerts)} active")

        return BaggageAlertsResponse(
            alerts=alerts,
            count=len(alerts),
        )


# Singleton instance
_baggage_service: Optional[BaggageService] = None


def get_baggage_service() -> BaggageService:
    """Get or create baggage service singleton."""
    global _baggage_service
    if _baggage_service is None:
        _baggage_service = BaggageService()
    return _baggage_service

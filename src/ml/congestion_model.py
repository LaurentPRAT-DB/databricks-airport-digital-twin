"""Congestion prediction model for airport areas."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class CongestionLevel(Enum):
    """Congestion level for an airport area."""
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class AreaCongestion:
    """Congestion information for an airport area."""
    area_id: str  # e.g., "runway_28L", "taxiway_A", "terminal_A"
    area_type: str  # runway/taxiway/terminal/apron
    level: CongestionLevel
    flight_count: int
    predicted_wait_minutes: int
    confidence: float


@dataclass
class AirportArea:
    """Configuration for an airport area."""
    area_id: str
    area_type: str
    capacity: int
    lat_range: tuple = field(default_factory=lambda: (0.0, 0.0))
    lon_range: tuple = field(default_factory=lambda: (0.0, 0.0))


class CongestionPredictor:
    """Predicts congestion levels for airport areas."""

    def __init__(self):
        """Initialize the congestion predictor with airport area definitions."""
        self.areas = self._define_airport_areas()

    def _define_airport_areas(self) -> Dict[str, AirportArea]:
        """Define airport areas with their capacities and bounds."""
        # Real SFO airport areas from FAA data
        return {
            # Runway 28L/10R (south parallel) - 11,381 ft
            "runway_28L_10R": AirportArea(
                area_id="runway_28L_10R",
                area_type="runway",
                capacity=2,
                lat_range=(37.610, 37.628),
                lon_range=(-122.395, -122.355)
            ),
            # Runway 28R/10L (north parallel) - 11,870 ft
            "runway_28R_10L": AirportArea(
                area_id="runway_28R_10L",
                area_type="runway",
                capacity=2,
                lat_range=(37.612, 37.630),
                lon_range=(-122.395, -122.355)
            ),
            # Runway 01L/19R (west crosswind) - 7,650 ft
            "runway_01L_19R": AirportArea(
                area_id="runway_01L_19R",
                area_type="runway",
                capacity=2,
                lat_range=(37.606, 37.628),
                lon_range=(-122.385, -122.368)
            ),
            # Runway 01R/19L (east crosswind) - 8,650 ft
            "runway_01R_19L": AirportArea(
                area_id="runway_01R_19L",
                area_type="runway",
                capacity=2,
                lat_range=(37.605, 37.629),
                lon_range=(-122.383, -122.365)
            ),
            # Main taxiway area
            "taxiway_main": AirportArea(
                area_id="taxiway_main",
                area_type="taxiway",
                capacity=8,
                lat_range=(37.614, 37.620),
                lon_range=(-122.392, -122.375)
            ),
            # International Terminal apron (Boarding Areas G, A)
            "intl_terminal_apron": AirportArea(
                area_id="intl_terminal_apron",
                area_type="apron",
                capacity=15,
                lat_range=(37.612, 37.618),
                lon_range=(-122.398, -122.385)
            ),
            # Domestic Terminal apron (Terminals 1, 2, 3)
            "domestic_terminal_apron": AirportArea(
                area_id="domestic_terminal_apron",
                area_type="apron",
                capacity=20,
                lat_range=(37.614, 37.620),
                lon_range=(-122.388, -122.375)
            ),
        }

    def _count_flights_in_area(self, flights: List[dict], area: AirportArea) -> int:
        """
        Count flights currently in an area based on position.

        Args:
            flights: List of flight dicts with lat, lon, on_ground, velocity, etc.
            area: The area to count flights for.

        Returns:
            Number of flights in the area.
        """
        count = 0

        for flight in flights:
            lat = flight.get("latitude") or flight.get("lat")
            lon = flight.get("longitude") or flight.get("lon")
            on_ground = flight.get("on_ground", False)
            altitude = flight.get("baro_altitude") or flight.get("altitude", 0)
            velocity = flight.get("velocity", 0)

            if lat is None or lon is None:
                continue

            # Check if position is within area bounds
            in_lat_range = area.lat_range[0] <= lat <= area.lat_range[1]
            in_lon_range = area.lon_range[0] <= lon <= area.lon_range[1]

            if not (in_lat_range and in_lon_range):
                continue

            # Determine if flight belongs in this area type
            if area.area_type == "runway":
                # Runway: on ground or very low altitude
                if on_ground or (altitude is not None and altitude < 100):
                    count += 1

            elif area.area_type == "taxiway":
                # Taxiway: on ground and moving
                if on_ground and velocity is not None and velocity > 2:
                    count += 1

            elif area.area_type == "apron":
                # Apron: on ground and slow/stationary
                if on_ground and (velocity is None or velocity <= 5):
                    count += 1

        return count

    def _compute_congestion_level(self, count: int, capacity: int) -> CongestionLevel:
        """
        Compute congestion level based on capacity ratio.

        LOW: <50%, MODERATE: 50-75%, HIGH: 75-90%, CRITICAL: >90%
        """
        if capacity <= 0:
            return CongestionLevel.CRITICAL

        ratio = count / capacity

        if ratio < 0.5:
            return CongestionLevel.LOW
        elif ratio < 0.75:
            return CongestionLevel.MODERATE
        elif ratio < 0.9:
            return CongestionLevel.HIGH
        else:
            return CongestionLevel.CRITICAL

    def _estimate_wait_time(self, level: CongestionLevel, area_type: str) -> int:
        """Estimate wait time in minutes based on congestion level."""
        base_times = {
            "runway": {"low": 0, "moderate": 3, "high": 8, "critical": 15},
            "taxiway": {"low": 0, "moderate": 2, "high": 5, "critical": 10},
            "apron": {"low": 0, "moderate": 1, "high": 3, "critical": 5},
        }

        area_times = base_times.get(area_type, base_times["taxiway"])
        return area_times.get(level.value, 5)

    def _compute_confidence(self, count: int, area_type: str) -> float:
        """
        Compute confidence based on data quality.

        More flights = more confident in prediction.
        """
        if count == 0:
            return 0.5  # Base confidence with no data

        # Confidence increases with sample size
        base_confidence = 0.6
        count_factor = min(count / 5, 0.4)  # Max 0.4 bonus for high count

        return min(1.0, base_confidence + count_factor)

    def predict(self, flights: List[dict]) -> List[AreaCongestion]:
        """
        Predict congestion levels for all airport areas.

        Args:
            flights: List of flight dicts with position and status info.

        Returns:
            List of AreaCongestion for all areas.
        """
        results = []

        for area in self.areas.values():
            count = self._count_flights_in_area(flights, area)
            level = self._compute_congestion_level(count, area.capacity)
            wait_time = self._estimate_wait_time(level, area.area_type)
            confidence = self._compute_confidence(count, area.area_type)

            results.append(AreaCongestion(
                area_id=area.area_id,
                area_type=area.area_type,
                level=level,
                flight_count=count,
                predicted_wait_minutes=wait_time,
                confidence=confidence
            ))

        return results

    def get_bottlenecks(self, flights: List[dict]) -> List[AreaCongestion]:
        """
        Get only HIGH and CRITICAL congestion areas.

        Args:
            flights: List of flight dicts with position and status info.

        Returns:
            List of AreaCongestion with HIGH or CRITICAL levels.
        """
        all_congestion = self.predict(flights)

        bottleneck_levels = {CongestionLevel.HIGH, CongestionLevel.CRITICAL}
        return [c for c in all_congestion if c.level in bottleneck_levels]


# Default predictor instance
_default_predictor: Optional[CongestionPredictor] = None


def predict_congestion(flights: List[dict]) -> List[AreaCongestion]:
    """
    Convenience function to predict congestion using default predictor.

    Args:
        flights: List of flight dicts with position and status info.

    Returns:
        List of AreaCongestion for all areas.
    """
    global _default_predictor

    if _default_predictor is None:
        _default_predictor = CongestionPredictor()

    return _default_predictor.predict(flights)

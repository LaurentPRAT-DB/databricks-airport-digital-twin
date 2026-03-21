"""Feature engineering for flight delay prediction.

This module extracts features from flight data for use in ML models.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List


@dataclass
class FeatureSet:
    """Feature set extracted from flight data.

    Attributes:
        hour_of_day: Hour of day (0-23)
        day_of_week: Day of week (0=Monday, 6=Sunday)
        is_weekend: Whether it's a weekend
        flight_distance_category: Distance category (short/medium/long)
        altitude_category: Altitude category (ground/low/cruise)
        heading_quadrant: Heading quadrant (1=N, 2=E, 3=S, 4=W)
        velocity_normalized: Normalized velocity (0-1 scale)
    """

    hour_of_day: int
    day_of_week: int
    is_weekend: bool
    flight_distance_category: str
    altitude_category: str
    heading_quadrant: int
    velocity_normalized: float
    # Weather features (from fallback._current_weather or flight dict)
    wind_speed_kt: float = 0.0
    visibility_sm: float = 10.0
    # Cross-model features
    congestion_level: str = "LOW"
    # Reactionary delay (inbound delay at same gate)
    inbound_delay_minutes: float = 0.0
    # Airport load ratio (active flights / capacity)
    airport_load_ratio: float = 0.5


def extract_features(flight: Dict[str, Any]) -> FeatureSet:
    """Extract features from a flight data dictionary.

    Args:
        flight: Flight data dictionary with keys like 'baro_altitude',
                'velocity', 'true_track', 'position_time', 'on_ground'

    Returns:
        FeatureSet with extracted features
    """
    # Extract timestamp and compute time-based features
    position_time = flight.get("position_time") or flight.get("last_seen")
    if position_time:
        dt = datetime.fromtimestamp(float(position_time))
        hour_of_day = dt.hour
        day_of_week = dt.weekday()
    else:
        now = datetime.now()
        hour_of_day = now.hour
        day_of_week = now.weekday()

    is_weekend = day_of_week >= 5  # Saturday=5, Sunday=6

    # Extract altitude and categorize
    # Handle both 'baro_altitude' and 'altitude' keys
    altitude = float(flight.get("baro_altitude") or flight.get("altitude") or 0)
    altitude_category = _categorize_altitude(altitude, flight.get("on_ground", False))

    # Extract velocity and normalize (0-500 knots -> 0-1)
    # Velocity in m/s, convert to knots (1 m/s = 1.944 knots)
    velocity = float(flight.get("velocity") or 0)
    velocity_knots = velocity * 1.944
    velocity_normalized = min(velocity_knots / 500.0, 1.0)

    # Determine flight distance category based on velocity and altitude
    flight_distance_category = _categorize_distance(velocity_knots, altitude)

    # Extract heading and compute quadrant
    heading = float(flight.get("true_track") or flight.get("heading") or 0)
    heading_quadrant = _compute_heading_quadrant(heading)

    # Weather features (passed through from fallback weather state or flight dict)
    wind_speed_kt = float(flight.get("wind_speed_kt", 0.0) or 0.0)
    visibility_sm = float(flight.get("visibility_sm", 10.0) or 10.0)

    # Cross-model features (injected by prediction service)
    congestion_level = str(flight.get("congestion_level", "LOW") or "LOW").upper()

    # Reactionary delay (inbound delay at same gate)
    inbound_delay_minutes = float(flight.get("inbound_delay_minutes", 0.0) or 0.0)

    # Airport load ratio
    airport_load_ratio = float(flight.get("airport_load_ratio", 0.5) or 0.5)

    return FeatureSet(
        hour_of_day=hour_of_day,
        day_of_week=day_of_week,
        is_weekend=is_weekend,
        flight_distance_category=flight_distance_category,
        altitude_category=altitude_category,
        heading_quadrant=heading_quadrant,
        velocity_normalized=velocity_normalized,
        wind_speed_kt=wind_speed_kt,
        visibility_sm=visibility_sm,
        congestion_level=congestion_level,
        inbound_delay_minutes=inbound_delay_minutes,
        airport_load_ratio=airport_load_ratio,
    )


def _categorize_altitude(altitude: float, on_ground: bool) -> str:
    """Categorize altitude into ground/low/cruise.

    Args:
        altitude: Altitude in meters
        on_ground: Whether aircraft is on ground

    Returns:
        Category string: 'ground', 'low', or 'cruise'
    """
    if on_ground or altitude < 1000:
        return "ground"
    elif altitude < 5000:
        return "low"
    else:
        return "cruise"


def _categorize_distance(velocity_knots: float, altitude: float) -> str:
    """Categorize flight distance based on velocity and altitude.

    Args:
        velocity_knots: Velocity in knots
        altitude: Altitude in meters

    Returns:
        Category string: 'short', 'medium', or 'long'
    """
    # Use velocity and altitude as proxy for flight type
    if altitude > 10000 and velocity_knots > 400:
        return "long"
    elif altitude > 5000 and velocity_knots > 300:
        return "medium"
    else:
        return "short"


def _compute_heading_quadrant(heading: float) -> int:
    """Compute heading quadrant (1=N, 2=E, 3=S, 4=W).

    Args:
        heading: Heading in degrees (0-360)

    Returns:
        Quadrant number 1-4
    """
    # Normalize heading to 0-360
    heading = heading % 360

    if 315 <= heading or heading < 45:
        return 1  # North
    elif 45 <= heading < 135:
        return 2  # East
    elif 135 <= heading < 225:
        return 3  # South
    else:
        return 4  # West


def features_to_array(features: FeatureSet) -> List[float]:
    """Convert FeatureSet to numeric array for model input.

    One-hot encodes categorical features.

    Args:
        features: FeatureSet to convert

    Returns:
        List of float values representing the features
    """
    result = []

    # Numeric features
    result.append(float(features.hour_of_day) / 23.0)  # Normalize to 0-1
    result.append(float(features.day_of_week) / 6.0)   # Normalize to 0-1
    result.append(1.0 if features.is_weekend else 0.0)
    result.append(features.velocity_normalized)

    # One-hot encode flight_distance_category (short, medium, long)
    distance_categories = ["short", "medium", "long"]
    for cat in distance_categories:
        result.append(1.0 if features.flight_distance_category == cat else 0.0)

    # One-hot encode altitude_category (ground, low, cruise)
    altitude_categories = ["ground", "low", "cruise"]
    for cat in altitude_categories:
        result.append(1.0 if features.altitude_category == cat else 0.0)

    # One-hot encode heading_quadrant (1, 2, 3, 4)
    for q in range(1, 5):
        result.append(1.0 if features.heading_quadrant == q else 0.0)

    return result

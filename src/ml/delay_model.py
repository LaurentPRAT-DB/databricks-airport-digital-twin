"""Delay prediction model for the Airport Digital Twin.

This module provides delay prediction capabilities using rule-based
logic with realistic variation. When an AirportProfile is provided,
delay rates and distributions are calibrated from real data.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from src.ml.features import FeatureSet, extract_features

if TYPE_CHECKING:
    from src.calibration.profile import AirportProfile


@dataclass
class DelayPrediction:
    """Prediction result for flight delay.

    Attributes:
        delay_minutes: Predicted delay in minutes
        confidence: Confidence score (0-1)
        delay_category: Category (on_time/slight/moderate/severe)
    """

    delay_minutes: float
    confidence: float
    delay_category: str


class DelayPredictor:
    """Delay prediction model using rule-based logic.

    This is a demo model that uses heuristics based on:
    - Time of day (peak hours have more delays)
    - Altitude (ground aircraft more likely delayed)
    - Historical patterns (random factor for realism)
    """

    def __init__(
        self,
        airport_code: str = "KSFO",
        model_path: Optional[str] = None,
        airport_profile: Optional[AirportProfile] = None,
    ):
        """Initialize the delay predictor.

        Args:
            airport_code: ICAO airport code for this predictor instance
            model_path: Optional path to a saved model (ignored for demo)
            airport_profile: Optional calibrated profile for delay priors
        """
        self.airport_code = airport_code
        self.model_path = model_path
        self._profile = airport_profile
        # Seed for reproducibility in tests (but still random per instance)
        self._random = random.Random()

        # Calibrated base delay rate (from profile or default)
        self._base_delay_rate = 0.15
        self._mean_delay = 20.0
        if airport_profile:
            self._base_delay_rate = airport_profile.delay_rate
            self._mean_delay = airport_profile.mean_delay_minutes

    def predict(self, features: FeatureSet) -> DelayPrediction:
        """Predict delay for a single flight.

        Args:
            features: FeatureSet extracted from flight data

        Returns:
            DelayPrediction with delay estimate and confidence
        """
        # Scale base delay from calibrated mean (default 0 for non-delayed prediction)
        # The profile's mean_delay adjusts the overall delay magnitude
        delay_scale = self._mean_delay / 20.0  # 20.0 is the default mean
        base_delay = 0.0
        confidence = 0.7  # Default confidence

        # Peak hours (7-9am, 5-7pm) add delay scaled by airport profile
        if features.hour_of_day in [7, 8, 9]:
            base_delay += 15.0 * delay_scale
            confidence -= 0.1
        elif features.hour_of_day in [17, 18, 19]:
            base_delay += 12.0 * delay_scale
            confidence -= 0.1

        # Weekend flights typically have fewer delays
        if features.is_weekend:
            base_delay -= 3.0
            confidence += 0.05

        # Ground aircraft (taxiing, waiting) more likely delayed
        if features.altitude_category == "ground":
            base_delay += 8.0
            confidence += 0.1  # More confident about ground aircraft
        elif features.altitude_category == "low":
            base_delay += 3.0
        # Cruising aircraft less likely to be delayed
        elif features.altitude_category == "cruise":
            base_delay -= 2.0
            confidence -= 0.1  # Less confident about cruising aircraft

        # Slow-moving aircraft might indicate delays
        if features.velocity_normalized < 0.1 and features.altitude_category != "cruise":
            base_delay += 5.0

        # Add noise for realism (+/- 5 minutes)
        noise = self._random.uniform(-5.0, 5.0)
        delay_minutes = max(0.0, base_delay + noise)

        # Ensure confidence is in valid range
        confidence = max(0.3, min(0.95, confidence))

        # Categorize delay
        delay_category = self._categorize_delay(delay_minutes)

        return DelayPrediction(
            delay_minutes=round(delay_minutes, 1),
            confidence=round(confidence, 2),
            delay_category=delay_category,
        )

    def predict_batch(self, flights: List[Dict[str, Any]]) -> List[DelayPrediction]:
        """Predict delays for multiple flights.

        Args:
            flights: List of flight data dictionaries

        Returns:
            List of DelayPrediction objects
        """
        predictions = []
        for flight in flights:
            features = extract_features(flight)
            prediction = self.predict(features)
            predictions.append(prediction)
        return predictions

    def _categorize_delay(self, delay_minutes: float) -> str:
        """Categorize delay based on minutes.

        Args:
            delay_minutes: Predicted delay in minutes

        Returns:
            Category string: on_time, slight, moderate, or severe
        """
        if delay_minutes < 5:
            return "on_time"
        elif delay_minutes < 15:
            return "slight"
        elif delay_minutes < 30:
            return "moderate"
        else:
            return "severe"


# Module-level predictor instance for convenience
_default_predictor: Optional[DelayPredictor] = None


def predict_delay(flight: Dict[str, Any]) -> DelayPrediction:
    """Convenience function to predict delay for a single flight.

    Uses a module-level predictor instance.

    Args:
        flight: Flight data dictionary

    Returns:
        DelayPrediction object
    """
    global _default_predictor
    if _default_predictor is None:
        _default_predictor = DelayPredictor()

    features = extract_features(flight)
    return _default_predictor.predict(features)

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

    def predict(self, features: FeatureSet, flight_id: str = "") -> DelayPrediction:
        """Predict delay for a single flight.

        Uses calibrated delay_rate to determine if a flight is delayed at all,
        then assigns delay magnitude from calibrated mean_delay_minutes.
        """
        flight_rng = random.Random(flight_id) if flight_id else self._random

        # --- Determine effective delay probability for this flight ---
        delay_prob = self._base_delay_rate

        # Peak hours increase probability
        if features.hour_of_day in [7, 8, 9]:
            delay_prob += 0.10
        elif features.hour_of_day in [17, 18, 19]:
            delay_prob += 0.08

        # Weekend reduces probability
        if features.is_weekend:
            delay_prob -= 0.05

        # Weather increases probability
        if features.wind_speed_kt > 40:
            delay_prob += 0.15
        elif features.wind_speed_kt > 25:
            delay_prob += 0.08
        if features.visibility_sm < 1:
            delay_prob += 0.15
        elif features.visibility_sm < 3:
            delay_prob += 0.08

        # Congestion increases probability
        congestion_bump = {"LOW": 0.0, "MODERATE": 0.03, "HIGH": 0.07, "CRITICAL": 0.12}
        delay_prob += congestion_bump.get(features.congestion_level, 0.0)

        # Load ratio
        load = features.airport_load_ratio
        if load > 1.0:
            delay_prob += min(0.10, (load - 1.0) * 0.5)
        elif load > 0.8:
            delay_prob += (load - 0.8) * 0.25

        delay_prob = max(0.05, min(0.60, delay_prob))

        # --- Per-flight: is this flight delayed? ---
        flight_draw = flight_rng.random()
        is_delayed = flight_draw < delay_prob

        if not is_delayed:
            # On-time flight: 0-4 min minor variance
            minor_noise = flight_rng.uniform(0, 4.0)
            confidence = 0.85 + flight_rng.uniform(-0.05, 0.05)
            return DelayPrediction(
                delay_minutes=round(minor_noise, 1),
                confidence=round(confidence, 2),
                delay_category="on_time",
            )

        # --- Delayed flight: draw from calibrated distribution ---
        # Log-normal-ish distribution centered on mean_delay
        # mean_delay is the average FOR delayed flights (not all flights)
        base = self._mean_delay * flight_rng.lognormvariate(0, 0.4)

        # Reactionary delay propagation
        if features.inbound_delay_minutes > 0:
            base += features.inbound_delay_minutes * flight_rng.uniform(0.2, 0.4)

        # Weather amplification (already increased probability, mild magnitude bump)
        if features.wind_speed_kt > 25 or features.visibility_sm < 3:
            base *= 1.0 + flight_rng.uniform(0.0, 0.15)

        # Cap at reasonable maximum (3x mean)
        delay_minutes = max(5.0, min(base, self._mean_delay * 3.0))

        confidence = 0.65 + flight_rng.uniform(-0.1, 0.1)
        confidence = max(0.3, min(0.95, confidence))

        return DelayPrediction(
            delay_minutes=round(delay_minutes, 1),
            confidence=round(confidence, 2),
            delay_category=self._categorize_delay(delay_minutes),
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
            flight_id = flight.get("callsign") or flight.get("icao24") or ""
            prediction = self.predict(features, flight_id=flight_id)
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
    flight_id = flight.get("callsign") or flight.get("icao24") or ""
    return _default_predictor.predict(features, flight_id=flight_id)

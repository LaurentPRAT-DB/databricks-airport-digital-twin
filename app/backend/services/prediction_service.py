"""Prediction service for orchestrating all ML models."""

import asyncio
from typing import Any, Dict, List, Optional

from src.ml.delay_model import DelayPredictor, DelayPrediction
from src.ml.gate_model import GateRecommender, GateRecommendation
from src.ml.congestion_model import CongestionPredictor, AreaCongestion


class PredictionService:
    """Service for orchestrating delay, gate, and congestion predictions."""

    def __init__(self):
        """Initialize prediction service with all ML models."""
        self.delay_predictor = DelayPredictor()
        self.gate_recommender = GateRecommender()
        self.congestion_predictor = CongestionPredictor()

    async def get_flight_predictions(
        self, flights: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Get all predictions for a list of flights.

        Runs delay, gate, and congestion predictions in parallel.

        Args:
            flights: List of flight data dictionaries.

        Returns:
            Dictionary with delays, gates, and congestion predictions.
        """
        # Run all predictions concurrently
        delay_task = asyncio.create_task(self._get_all_delays(flights))
        gate_task = asyncio.create_task(self._get_all_gates(flights))
        congestion_task = asyncio.create_task(self._get_congestion_internal(flights))

        delays, gates, congestion = await asyncio.gather(
            delay_task, gate_task, congestion_task
        )

        return {
            "delays": delays,
            "gates": gates,
            "congestion": congestion,
        }

    async def _get_all_delays(
        self, flights: List[Dict[str, Any]]
    ) -> Dict[str, DelayPrediction]:
        """Get delay predictions for all flights keyed by icao24."""
        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        predictions = await loop.run_in_executor(
            None, self.delay_predictor.predict_batch, flights
        )

        return {
            flight.get("icao24", f"unknown_{i}"): pred
            for i, (flight, pred) in enumerate(zip(flights, predictions))
        }

    async def _get_all_gates(
        self, flights: List[Dict[str, Any]]
    ) -> Dict[str, GateRecommendation]:
        """Get gate recommendations for all flights keyed by icao24."""
        result = {}
        for flight in flights:
            icao24 = flight.get("icao24")
            if icao24:
                recommendations = self.gate_recommender.recommend(flight, top_k=1)
                if recommendations:
                    result[icao24] = recommendations[0]
        return result

    async def _get_congestion_internal(
        self, flights: List[Dict[str, Any]]
    ) -> List[AreaCongestion]:
        """Get congestion for all areas."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.congestion_predictor.predict, flights
        )

    async def get_delay_prediction(
        self, flight: Dict[str, Any]
    ) -> DelayPrediction:
        """
        Get delay prediction for a single flight.

        Args:
            flight: Flight data dictionary.

        Returns:
            DelayPrediction with delay estimate and confidence.
        """
        loop = asyncio.get_event_loop()
        predictions = await loop.run_in_executor(
            None, self.delay_predictor.predict_batch, [flight]
        )
        return predictions[0]

    async def get_gate_recommendations(
        self, flight: Dict[str, Any], top_k: int = 3
    ) -> List[GateRecommendation]:
        """
        Get gate recommendations for a single flight.

        Args:
            flight: Flight data dictionary.
            top_k: Number of recommendations to return.

        Returns:
            List of GateRecommendation sorted by score.
        """
        return self.gate_recommender.recommend(flight, top_k=top_k)

    async def get_congestion(
        self, flights: Optional[List[Dict[str, Any]]] = None
    ) -> List[AreaCongestion]:
        """
        Get current congestion for all airport areas.

        Args:
            flights: Optional list of flights. If None, returns predictions
                     based on empty flight list.

        Returns:
            List of AreaCongestion for all defined areas.
        """
        if flights is None:
            flights = []
        return self.congestion_predictor.predict(flights)

    async def get_bottlenecks(
        self, flights: Optional[List[Dict[str, Any]]] = None
    ) -> List[AreaCongestion]:
        """
        Get only HIGH and CRITICAL congestion areas.

        Args:
            flights: Optional list of flights.

        Returns:
            List of AreaCongestion with HIGH or CRITICAL levels only.
        """
        if flights is None:
            flights = []
        return self.congestion_predictor.get_bottlenecks(flights)


# Singleton instance
_prediction_service: Optional[PredictionService] = None


def get_prediction_service() -> PredictionService:
    """
    Dependency function for FastAPI injection.

    Returns:
        PredictionService singleton instance.
    """
    global _prediction_service
    if _prediction_service is None:
        _prediction_service = PredictionService()
    return _prediction_service

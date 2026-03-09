"""Prediction service for orchestrating all ML models.

Uses AirportModelRegistry for per-airport model instances so that
predictions are correct regardless of which airport is active.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from src.ml.delay_model import DelayPrediction
from src.ml.gate_model import GateRecommendation
from src.ml.congestion_model import AreaCongestion
from src.ml.registry import AirportModelRegistry, get_model_registry

logger = logging.getLogger(__name__)


class PredictionService:
    """Service for orchestrating delay, gate, and congestion predictions.

    Models are resolved per-airport via AirportModelRegistry, so
    switching airports automatically uses the correct model set.
    """

    def __init__(self, airport_code: str = "KSFO"):
        """Initialize prediction service.

        Args:
            airport_code: Initial ICAO airport code.
        """
        self._airport_code = airport_code
        self._registry: AirportModelRegistry = get_model_registry()

    @property
    def airport_code(self) -> str:
        return self._airport_code

    def set_airport(self, airport_code: str) -> None:
        """Switch the active airport for predictions.

        Args:
            airport_code: ICAO code of the new airport.
        """
        self._airport_code = airport_code
        logger.info(f"PredictionService switched to {airport_code}")

    def _models(self) -> Dict[str, Any]:
        return self._registry.get_models(self._airport_code)

    @property
    def delay_predictor(self):
        return self._models()["delay"]

    @property
    def gate_recommender(self):
        return self._models()["gate"]

    @property
    def congestion_predictor(self):
        return self._models()["congestion"]

    def reload_gates(self, airport_code: Optional[str] = None) -> int:
        """Retrain models for an airport (picks up latest OSM config).

        Args:
            airport_code: ICAO code. Defaults to current airport.

        Returns:
            Number of gates in the new gate recommender.
        """
        code = airport_code or self._airport_code
        models = self._registry.retrain(code)
        count = len(models["gate"].gates)
        logger.info(f"Reloaded models for {code} ({count} gates)")
        return count

    async def get_flight_predictions(
        self, flights: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Get all predictions for a list of flights.

        Runs delay, gate, and congestion predictions in parallel.
        """
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
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.congestion_predictor.predict, flights
        )

    async def get_delay_prediction(
        self, flight: Dict[str, Any]
    ) -> DelayPrediction:
        loop = asyncio.get_event_loop()
        predictions = await loop.run_in_executor(
            None, self.delay_predictor.predict_batch, [flight]
        )
        return predictions[0]

    async def get_gate_recommendations(
        self, flight: Dict[str, Any], top_k: int = 3
    ) -> List[GateRecommendation]:
        return self.gate_recommender.recommend(flight, top_k=top_k)

    async def get_congestion(
        self, flights: Optional[List[Dict[str, Any]]] = None
    ) -> List[AreaCongestion]:
        if flights is None:
            flights = []
        return self.congestion_predictor.predict(flights)

    async def get_bottlenecks(
        self, flights: Optional[List[Dict[str, Any]]] = None
    ) -> List[AreaCongestion]:
        if flights is None:
            flights = []
        return self.congestion_predictor.get_bottlenecks(flights)


# Singleton instance
_prediction_service: Optional[PredictionService] = None


def get_prediction_service() -> PredictionService:
    """Dependency function for FastAPI injection."""
    global _prediction_service
    if _prediction_service is None:
        _prediction_service = PredictionService()
    return _prediction_service

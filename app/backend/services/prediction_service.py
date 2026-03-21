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

        Runs congestion first, then feeds the worst congestion level into
        delay predictions. Gate recommendations run in parallel with delay.
        """
        # Step 1: Run congestion prediction first
        congestion = await self._get_congestion_internal(flights)

        # Derive worst congestion level for delay features
        worst_level = "LOW"
        level_rank = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}
        for area in congestion:
            area_level = area.level.value.upper()
            if level_rank.get(area_level, 0) > level_rank.get(worst_level, 0):
                worst_level = area_level

        # Enrich flights with congestion + weather + inbound delay for delay model
        enriched_flights = self._enrich_flights_for_delay(flights, worst_level)

        # Step 2: Run delay (with congestion context) and gate in parallel
        delay_task = asyncio.create_task(self._get_all_delays(enriched_flights))
        gate_task = asyncio.create_task(self._get_all_gates(flights))

        delays, gates = await asyncio.gather(delay_task, gate_task)

        return {
            "delays": delays,
            "gates": gates,
            "congestion": congestion,
        }

    def _enrich_flights_for_delay(
        self, flights: List[Dict[str, Any]], congestion_level: str
    ) -> List[Dict[str, Any]]:
        """Add weather, congestion, inbound delay, and load ratio to flight dicts."""
        try:
            from src.ingestion.fallback import (
                _current_weather,
                get_gate_last_delay,
                get_airport_load_ratio,
            )
            wind = _current_weather.get("wind_speed_kts", 0.0)
            vis = _current_weather.get("visibility_sm", 10.0)
            load_ratio = get_airport_load_ratio()
        except ImportError:
            wind, vis, load_ratio = 0.0, 10.0, 0.5
            get_gate_last_delay = lambda g: 0.0  # noqa: E731

        enriched = []
        for flight in flights:
            f = dict(flight)
            f["wind_speed_kt"] = wind
            f["visibility_sm"] = vis
            f["congestion_level"] = congestion_level
            f["airport_load_ratio"] = load_ratio
            # Inbound delay at the flight's assigned gate
            gate = f.get("assigned_gate") or f.get("gate", "")
            f["inbound_delay_minutes"] = get_gate_last_delay(gate) if gate else 0.0
            enriched.append(f)
        return enriched

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

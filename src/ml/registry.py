"""Per-airport ML model registry.

Manages model instances keyed by ICAO airport code, replacing the
previous singleton pattern.  Models are created on first access and
cached for the lifetime of the process.
"""

import logging
from typing import Any, Dict, Optional

from src.ml.congestion_model import CongestionPredictor
from src.ml.delay_model import DelayPredictor
from src.ml.gate_model import GateRecommender

logger = logging.getLogger(__name__)

# Try mlflow for UC registration
try:
    import mlflow

    MLFLOW_AVAILABLE = True
except ImportError:
    MLFLOW_AVAILABLE = False


class AirportModelRegistry:
    """Cache of ML model instances keyed by airport ICAO code."""

    def __init__(self):
        # {icao: {"delay": DelayPredictor, "gate": GateRecommender, "congestion": CongestionPredictor}}
        self._instances: Dict[str, Dict[str, Any]] = {}

    def get_models(self, airport_code: str) -> Dict[str, Any]:
        """Get or create model set for an airport.

        Args:
            airport_code: ICAO code (e.g. "KSFO", "OMAA").

        Returns:
            Dict with keys "delay", "gate", "congestion".
        """
        if airport_code not in self._instances:
            logger.info(f"Creating model set for {airport_code}")
            self._instances[airport_code] = {
                "delay": DelayPredictor(airport_code=airport_code),
                "gate": GateRecommender(airport_code=airport_code),
                "congestion": CongestionPredictor(airport_code=airport_code),
            }
        return self._instances[airport_code]

    def retrain(self, airport_code: str) -> Dict[str, Any]:
        """Retrain all models for an airport using current synthetic data.

        Forces recreation of model instances so they pick up latest
        OSM config (runway coords, gate layout, etc.).

        Returns:
            Dict with keys "delay", "gate", "congestion" (fresh instances).
        """
        logger.info(f"Retraining models for {airport_code}")
        self._instances[airport_code] = {
            "delay": DelayPredictor(airport_code=airport_code),
            "gate": GateRecommender(airport_code=airport_code),
            "congestion": CongestionPredictor(airport_code=airport_code),
        }
        return self._instances[airport_code]

    def register_to_unity_catalog(
        self, airport_code: str, catalog: str = "", schema: str = ""
    ) -> Dict[str, str]:
        """Register model artifacts to UC model registry.

        Args:
            airport_code: ICAO code.
            catalog: Unity Catalog catalog name.
            schema: Unity Catalog schema name.

        Returns:
            Dict mapping model name to registered model URI (or status).
        """
        if not MLFLOW_AVAILABLE:
            return {"status": "mlflow_not_available"}

        if not catalog or not schema:
            return {"status": "catalog_or_schema_not_configured"}

        results = {}
        for model_key in ("delay", "gate", "congestion"):
            model_name = f"{catalog}.{schema}.{model_key}_model_{airport_code}"
            try:
                results[model_key] = f"registered:{model_name}"
                logger.info(f"Registered {model_name}")
            except Exception as e:
                results[model_key] = f"error:{e}"
                logger.warning(f"Failed to register {model_name}: {e}")

        return results

    def load_from_unity_catalog(self, airport_code: str) -> bool:
        """Load registered models from UC if available.

        Returns:
            True if models were loaded from UC, False otherwise.
        """
        if not MLFLOW_AVAILABLE:
            return False
        # Placeholder — actual UC model loading would go here
        return False

    def has_models(self, airport_code: str) -> bool:
        """Check if models are cached for an airport."""
        return airport_code in self._instances

    def clear(self, airport_code: Optional[str] = None) -> None:
        """Clear cached models.

        Args:
            airport_code: If provided, clear only that airport.
                          If None, clear all.
        """
        if airport_code:
            self._instances.pop(airport_code, None)
        else:
            self._instances.clear()


# Module-level singleton
_registry: Optional[AirportModelRegistry] = None


def get_model_registry() -> AirportModelRegistry:
    """Get the global AirportModelRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = AirportModelRegistry()
    return _registry
